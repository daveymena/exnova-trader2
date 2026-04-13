#!/usr/bin/env python3
"""
 LANZADOR BOT EXNOVA - MODO PRACTICE REAL
Ejecuta el bot en modo PRACTICE (dinero virtual) con monitoreo en vivo
"""

import sys
import os
import time
from datetime import datetime

# Agregar el directorio raíz al path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Importar config
from config import Config

def print_banner():
    print("\n" + "="*80)
    print("[LANZADOR] BOT DE TRADING EXNOVA - MODO PRACTICE".center(80))
    print("="*80)
    print(f"\n[CONFIG] Configuracion:")
    print(f"   Broker: {Config.BROKER_NAME.upper()}")
    print(f"   Modo: PRACTICE (dinero virtual - SIN RIESGO REAL)")
    print(f"   Activo Predeterminado: {Config.DEFAULT_ASSET}")
    print(f"   Capital por Operacion: ${Config.CAPITAL_PER_TRADE}")
    print(f"   Expiracion: {Config.EXPIRATION_TIME} segundos")
    print(f"\n[MEJORA] Cooldown por Activo = 5 minutos")
    print(f"   -> Evita multiples trades en el mismo par")
    print(f"   -> Impacto esperado: -70% perdidas por sobreoperacion")
    print("\n" + "="*80 + "\n")

def check_credentials():
    """Verifica que las credenciales esten configuradas"""
    print("[AUTH] Verificando credenciales de Exnova...")
    
    if not Config.EXNOVA_EMAIL or not Config.EXNOVA_PASSWORD:
        print("[ERROR] CREDENCIALES NO CONFIGURADAS")
        print("\n[INSTRUCCION] Por favor, configura:")
        print("   1. Crea archivo .env en la raiz del proyecto")
        print("   2. Anade:")
        print("      EXNOVA_EMAIL=tu_email@example.com")
        print("      EXNOVA_PASSWORD=tu_contrasena")
        print("      ACCOUNT_TYPE=PRACTICE")
        return False
    
    print("[OK] Credenciales encontradas")
    print(f"   Email: {Config.EXNOVA_EMAIL[:20]}***")
    return True

def start_bot():
    """Inicia el bot con manejo de errores"""
    print("\n[CONEXION] Conectando a Exnova en PRACTICE...")
    
    try:
        # Importar componentes principales
        from data.market_data import MarketDataHandler
        from strategies.technical import FeatureEngineer
        from core.agent import RLAgent
        from core.risk import RiskManager
        from core.asset_manager import AssetManager
        from ai.llm_client import LLMClient
        from core.trader import LiveTrader
        
        print("[OK] Modulos cargados correctamente")
        
        # Crear instancias
        print("\n[CONFIG] Inicializando sistema...")
        market_data = MarketDataHandler(
            broker_name=Config.BROKER_NAME,
            account_type="PRACTICE"  # FORZAR PRACTICE
        )
        
        print("[BROKER] Conectando al broker...")
        if not market_data.connect(Config.EXNOVA_EMAIL, Config.EXNOVA_PASSWORD):
            print("[ERROR] No se pudo conectar a Exnova")
            print("   Verifica internet, credenciales y que Exnova este operativo")
            return False
        
        print(f"[OK] Conectado a {market_data.broker_name.upper()}")
        print(f"   Modo: {market_data.account_type}")
        try:
            balance = market_data.get_balance()
            print(f"   Balance: ${balance:.2f}")
        except:
            print(f"   Balance: [No disponible]")
        
        # Crear components de trading
        feature_engineer = FeatureEngineer()
        agent = RLAgent()
        risk_manager = RiskManager(
            capital_per_trade=Config.CAPITAL_PER_TRADE,
            stop_loss_pct=Config.STOP_LOSS_PERCENT,
            take_profit_pct=Config.TAKE_PROFIT_PERCENT
        )
        asset_manager = AssetManager(market_data)
        
        # LLM opcional
        llm_client = None
        if Config.USE_LLM:
            try:
                llm_client = LLMClient()
                print("[IA] Sistema de IA (Groq/Ollama): Cargado")
            except Exception as e:
                print(f"[WARN] IA no disponible (continuando sin IA): {e}")
        
        # Crear trader
        print("\n[TRADER] Iniciando Live Trader...")
        trader = LiveTrader(
            market_data=market_data,
            feature_engineer=feature_engineer,
            agent=agent,
            risk_manager=risk_manager,
            asset_manager=asset_manager,
            llm_client=llm_client
        )
        
        # Mostrar mejoras activas
        print("\n" + "="*80)
        print("[MEJORAS] MEJORAS ACTIVAS")
        print("="*80)
        print(f"""
[OK] MEJORA 1: Cooldown por Activo
   . Tiempo: 5 minutos por cada par
   . Efecto: Bloquea operaciones repetidas en mismo par
   . Beneficio: Reduce perdidas en cascada

[OK] CONFIGURACION ACTUAL:
   . cooldown_per_asset = {trader.cooldown_per_asset}s (5 minutos)
   . max_consecutive_losses = {trader.max_consecutive_losses}
   . min_time_between_trades = {trader.min_time_between_trades}s
        """)
        print("="*80 + "\n")
        
        # Mostrar hotkeys
        print("[CONTROLES] CONTROLES:")
        print("   CTRL+C: Detener bot")
        print("   [Auto] El bot se pausa despues de 3 perdidas consecutivas")
        print("\n")
        
        # Conectar senales para logs
        def on_log(msg):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        
        def on_error(msg):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] {msg}")
        
        trader.signals.log_message.connect(on_log)
        trader.signals.error_message.connect(on_error)
        
        # Iniciar
        print("[START] Bot iniciando en modo 24/7...")
        print("="*80 + "\n")
        
        trader.start()
        
        # Keep running
        try:
            while trader.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\n[STOP] Deteniendo bot...")
            trader.stop()
            time.sleep(2)
            print("[OK] Bot detenido")
            return True
        
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Error al iniciar bot: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print_banner()
    
    # Verificar credenciales
    if not check_credentials():
        sys.exit(1)
    
    # Iniciar bot
    success = start_bot()
    sys.exit(0 if success else 1)
