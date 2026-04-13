"""
Trading Bot Pro - Telegram Signal Integrator
Escucha señales de Telegram y las ejecuta automáticamente en el broker
"""

import sys
import asyncio
import time
import signal
import os
import re
from datetime import datetime, timedelta
from config import Config
from data.market_data import MarketDataHandler
from core.telegram_listener import TelegramListener
from core.risk import RiskManager

# Variable global para manejo de cierre
running = True

def signal_handler(sig, frame):
    """Maneja Ctrl+C para cerrar limpiamente"""
    global running
    print("\n\n🛑 Deteniendo bot de señales...")
    running = False

async def main():
    """Función principal asíncrona"""
    global running
    
    print("\n" + "="*60)
    print("🚀 TRADING BOT PRO - TELEGRAM AUTO-TRADE")
    print("="*60)
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Broker: {Config.BROKER_NAME.upper()}")
    print(f"Modo: {Config.ACCOUNT_TYPE}")
    print("="*60 + "\n")

    # 1. Inicializar componentes de Trading
    print("📦 Inicializando componentes de trading...")
    market_data = MarketDataHandler(
        broker_name=Config.BROKER_NAME,
        account_type=Config.ACCOUNT_TYPE
    )
    
    risk_manager = RiskManager(
        Config.CAPITAL_PER_TRADE, 
        Config.STOP_LOSS_PERCENT, 
        Config.TAKE_PROFIT_PERCENT, 
        max_martingale_steps=Config.MAX_MARTINGALE
    )

    # 2. Conectar al broker
    print(f"🔌 Conectando a {Config.BROKER_NAME.upper()}...")
    email = Config.EXNOVA_EMAIL if Config.BROKER_NAME == "exnova" else Config.IQ_OPTION_EMAIL
    password = Config.EXNOVA_PASSWORD if Config.BROKER_NAME == "exnova" else Config.IQ_OPTION_PASSWORD
    
    if not market_data.connect(email, password):
        print("❌ Error fatal: No se pudo conectar al broker. Verifica tu .env")
        return

    balance = market_data.get_balance()
    print(f"✅ Conectado | Balance actual: ${balance:.2f}\n")

    # --- SISTEMA DE IA (OLLAMA + MEMORIA) ---
    from ai_learning import create_learner
    try:
        learner = create_learner()
        print("🧠 Sistema de IA ACTIVADO (Ollama + Memoria de operaciones)")
    except Exception as e:
        print(f"⚠️ No se pudo cargar IA: {e}")
        learner = None
    # ----------------------------------------

    # Variables de estado para evitar duplicados y vaciado
    last_signal_signature = None
    last_trade_time = datetime.min
    TRADE_COOLDOWN_SECONDS = 300  # 5 minutos entre operaciones mínimo (por señal)

    import pandas as pd # Importación diferida o asegurar arriba

    async def monitor_trade_outcome(order_id, asset, direction, duration_min, indicators):
        """
        Monitorea el resultado y realiza un ANÁLISIS PROFUNDO (Deep Learning) post-mortem.
        """
        entry_time = time.time()
        
        # 0. Estrategia de Espera Inteligente 🧠⚡
        total_wait_time = duration_min * 60
        initial_sleep = max(0, total_wait_time - 15)
        
        if initial_sleep > 0:
            print(f"👀 Monitoreando {order_id} ({asset})... Durmiendo {initial_sleep:.1f}s...")
            await asyncio.sleep(initial_sleep)
        
        print(f"🕵️ Escaneando cierre de operación {order_id}...")
        
        loop = asyncio.get_event_loop()
        profit = None
        
        # Polling durante los últimos segundos + margen
        for i in range(60): # 60 intentos = 1 min de polling intenso
            try:
                is_connected = await loop.run_in_executor(None, market_data.api.check_connect)
                if not is_connected:
                    await loop.run_in_executor(None, lambda: market_data.connect(Config.EXNOVA_EMAIL, Config.EXNOVA_PASSWORD))
                
                profit = await loop.run_in_executor(None, lambda: market_data.api.check_win_v3(order_id))
                if profit is not None:
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
            
        if profit is None: profit = 0
        
        result = "WIN" if profit > 0 else "LOSS" if profit < 0 else "DRAW"
        print(f"🏁 Operación {order_id} finalizada. Resultado: {result} (${profit:.2f})")

        # 2. 🧪 DEEP LEARNING (Análisis Post-Mortem)
        try:
            # Obtener velas para análisis
            df_analysis = await loop.run_in_executor(None, lambda: market_data.get_candles(asset, 60, duration_min + 5, time.time()))
            
            deep_analysis = {}
            if not df_analysis.empty:
                entry_price_ref = indicators.get('close', df_analysis.iloc[0]['close'])
                min_price = df_analysis['low'].min()
                max_price = df_analysis['high'].max()
                
                if direction == 'CALL':
                    max_drawdown = entry_price_ref - min_price
                    max_profit = max_price - entry_price_ref
                else:
                    max_drawdown = max_price - entry_price_ref
                    max_profit = entry_price_ref - min_price
                
                deep_analysis['max_drawdown'] = max_drawdown
                deep_analysis['max_profit_potential'] = max_profit
                
                # Simulación de otros tiempos
                sims = {}
                for t in range(1, 6):
                    if t < len(df_analysis):
                        close_t = df_analysis.iloc[t]['close']
                        sim_win = close_t > entry_price_ref if direction == 'CALL' else close_t < entry_price_ref
                        sims[f'exp_{t}min'] = 'WIN' if sim_win else 'LOSS'
                deep_analysis['time_simulation'] = sims

            # Registrar experiencia en sistema de IA
            if learner:
                operation_data = {
                    'asset': asset,
                    'direction': direction,
                    'result': result,
                    'profit': profit,
                    'indicators': indicators,
                    'deep_analysis': deep_analysis
                }
                learner.record_operation(operation_data)
                print(f"🧠 Experiencia registrada para {asset}")
        except Exception as e:
            print(f"⚠️ Error guardando experiencia: {e}")

    async def process_telegram_signal(signal_data):
        nonlocal last_signal_signature, last_trade_time
        
        try:
            # 1. DEFINIR DATOS CLAVE
            asset = signal_data.get('asset')
            direction = signal_data.get('direction')
            expiration = signal_data.get('expiration', 5)
            
            if not asset or not direction:
                print("⚠️ Señal incompleta, ignorando.")
                return

            # 3. 🛡️ FILTROS DE SEGURIDAD 🛡️
            
            # A) Firma Anti-Duplicados
            current_sig = f"{asset}-{direction}-{datetime.now().strftime('%Y%m%d%H%M')}"
            if current_sig == last_signal_signature:
                print(f"🛑 DUPLICADO: Ya operamos {asset} hace un momento.")
                return
            
            # B) Cooldown Global
            seconds_since_last = (datetime.now() - last_trade_time).total_seconds()
            if seconds_since_last < 60: 
                 print(f"🛑 COOLDOWN: Espera {60 - seconds_since_last:.0f}s.")
                 return

            # C) Stop Loss Diario
            # Obtenemos balance actual con reintento simple si es 0
            current_balance = market_data.get_balance()
            if current_balance == 0:
                 await asyncio.sleep(1)
                 current_balance = market_data.get_balance()

            if not risk_manager.can_trade(current_balance):
                print(f"🛑 STOP LOSS DIARIO ALCANZADO (Balance: {current_balance}). Pausando operaciones...")
                return

            # D) Memoria IA - Verificar si patrón ha fallado antes
            if learner:
                current_context = {
                    'asset': asset,
                    'direction': direction,
                    'rsi': indicators.get('rsi', 50),
                    'price': indicators.get('close', 0),
                    'timestamp': datetime.now().isoformat()
                }
                should_enter, reason = learner.should_enter_trade(current_context)
                if not should_enter:
                    print(f"🛑 IA BLOQUEÓ OPERACIÓN: {reason}")
                    return

            # CAPTURAR INSTANTÁNEA DE MERCADO (RSI, MACD)
            indicators = {}
            try:
                # Intentamos obtener velas y calcular indicadores rápidos para guardar el contexto
                # Esto es crucial para que el bot "aprenda" el patrón
                # Solicitamos 50 velas para cálculo básico
                df = market_data.get_candles(asset, 60, 50, time.time())
                if not df.empty:
                     # Cálculo rápido manual de RSI (LocalAI lo hace internamente pero aquí necesitamos extraerlo)
                     # Por simplicidad, guardamos OHLC de la última vela o usamos LocalAI si expusiera método
                     delta = df['close'].diff()
                     gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                     loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                     rs = gain / loss
                     df['rsi'] = 100 - (100 / (1 + rs))
                     
                     indicators['rsi'] = df['rsi'].iloc[-1]
                     indicators['close'] = df['close'].iloc[-1]
                     # Podríamos calcular MACD aquí también
            except Exception as ind_e:
                print(f"⚠️ No se pudo capturar snapshot de mercado: {ind_e}")

            # 4. EJECUTAR OPERACIÓN
            print(f"\n⚡ EJECUTANDO: {asset} | {direction.upper()} | {expiration} min")
            amount = risk_manager.get_trade_amount()
            
            # USAR WRAPPER INTELIGENTE
            success, order_id = market_data.buy(asset, amount, direction, expiration)
            
            if success:
                print(f"✅ OPERACIÓN ÉXITOSA - ID: {order_id}")
                last_signal_signature = current_sig
                last_trade_time = datetime.now()
                
                # INICIAR APRENDIZAJE ASÍNCRONO
                asyncio.create_task(monitor_trade_outcome(order_id, asset, direction, expiration, indicators))
                
            else:
                print(f"❌ Falló ejecución en broker: {order_id}")

        except Exception as e:
            print(f"❌ Error procesando señal: {e}")

    # 4. Inicializar Telegram Listener (PRIORIDAD ALTA)
    telegram_task = None
    if Config.TELEGRAM_API_ID and Config.TELEGRAM_API_HASH:
        print("📱 Iniciando cliente de Telegram...")
        listener = TelegramListener(
            api_id=Config.TELEGRAM_API_ID,
            api_hash=Config.TELEGRAM_API_HASH,
            phone=Config.TELEGRAM_PHONE,
            session_name=Config.TELEGRAM_SESSION_NAME,
            signal_callback=process_telegram_signal
        )
        # Conexión Sincronizada (Bloqueante hasta login)
        try:
            print("⏳ Conectando a Telegram (Esperando login)...")
            await listener.start() # Esto pedirá el código si es necesario
            print("✅ Telegram conectado exitosamente.")
            
            # Una vez logueado, lanzamos la escucha en background
            telegram_task = asyncio.create_task(listener.listen(Config.TELEGRAM_CHATS))
        except Exception as e:
            print(f"❌ Error conectando a Telegram: {e}")
            return # Si falla Telegram crítico, mejor salir o revisar
    else:
        print("⚠️ Telegram NO configurado (API_ID/HASH faltantes)")

    # 5. Inicializar Web Scraper (AlgoritmoDeTrading)
    # Ejecutamos el scraper en un hilo separado o loop asíncrono
    web_scraper = None
    
    web_enable_str = os.getenv("WEB_ENABLE", "False").strip().lower()
    print(f"DEBUG: WEB_ENABLE='{web_enable_str}'") # Para ver qué lee realmente

    if web_enable_str in ["true", "1", "yes", "on"]:
        from core.web_signal_scraper import WebSignalScraper
        print("🌐 Iniciando Web Scraper (AlgoritmoDeTrading)...")
        
        web_user = os.getenv("WEB_USER", "Duvier mena")
        web_id = os.getenv("WEB_ID", "167326711")
        
        web_scraper = WebSignalScraper(web_user, web_id)
        
        # Función para monitorear la web en bucle
        async def monitor_web_signals():
            try:
                # Iniciar navegador (bloqueante)
                # Ejecutamos en executor para no bloquear el loop principal
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, web_scraper.start)
                
                last_signal_text = ""
                
                print("🌐 Web Scraper activo y monitoreando...")
                
                while running:
                    # Obtener señal actual
                    signal_data_web = await loop.run_in_executor(None, web_scraper.get_latest_signal)
                    
                    if signal_data_web and signal_data_web.get('raw_text'):
                        current_text = signal_data_web['raw_text']
                        
                        # Limpieza básica para comparar contenido real
                        clean_text = re.sub(r'Hora Actual:.*', '', current_text)
                        clean_text = re.sub(r'Tiempo restante.*', '', clean_text)
                        
                        # Solo procesamos si hay cambio real en la señal
                        if clean_text != last_signal_text:
                            print(f"\n🌐 NUEVA INFORMACIÓN WEB DETECTADA")
                            last_signal_text = clean_text
                            
                            # Enviamos al mismo procesador que Telegram
                            await process_telegram_signal({
                                'raw_message': f"WEB_SIGNAL_CONTEXT: {current_text}",
                                'asset': None, 'direction': None, 'expiration': None
                            })
                            
                    await asyncio.sleep(5) # Revisar cada 5 segundos
                    
            except Exception as e:
                print(f"❌ Error en monitor web: {e}")

        # Lanzar monitor web como tarea
        asyncio.create_task(monitor_web_signals())

    try:
        # Mantener el loop corriendo
        if telegram_task:
            await telegram_task
        else:
             # Si no hay telegram, mantener vivo por el web scraper
             while running:
                 await asyncio.sleep(1)
        
    except Exception as e:
        print(f"❌ Error en el loop principal: {e}")
    finally:
        if telegram_task:
            await listener.stop()
        if web_scraper:
            web_scraper.stop()
        print("👋 Bot finalizado.")

if __name__ == "__main__":
    # Configurar cierre limpio
    import signal
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\n👋 Cerrando por usuario...")
    except Exception as e:
        print(f"\n❌ Error inesperado: {e}")
