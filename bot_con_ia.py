#!/usr/bin/env python3
"""
BOT CON IA - APRENDIZAJE PROGRESIVO
Combina:
1. Detector de contexto de precio
2. Sistema de IA con fallbacks
3. Aprendizaje de operaciones pasadas
4. Control de operaciones simultáneas
"""
import sys
import os
import time
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from data.market_data import MarketDataHandler
from strategies.technical import FeatureEngineer
from core.asset_manager import AssetManager
from core.risk import RiskManager
from ai_learning import TradingLearner, create_learner

# Importar detector de contexto
try:
    from bot_con_contexto import (
        detectar_contexto_precio,
        calcular_rsi,
        detectar_divergencia_rsi,
        validar_entrada_con_contexto
    )
except ImportError:
    print("⚠️ bot_con_contexto.py no encontrado, usando validación básica")
    def validar_entrada_con_contexto(df, direction):
        return True, "Validación básica (sin contexto)"
    def calcular_rsi(df):
        return 50.0

# ============================================================================
# BOT PRINCIPAL CON IA - CONTROLADO
# ============================================================================

def main():
    print("\n" + "="*80)
    print("BOT CON IA - APRENDIZAJE PROGRESIVO (CONTROLADO)")
    print("="*80)
    print("Sistema de IA:")
    print("  - Ollama Local (llama3.2) o Easypanel")
    print("  - Control de operaciones simultáneas")
    print("  - Aprendizaje de pérdidas")
    print("="*80)

    # 1. INICIALIZAR IA
    print("\n[1] Inicializando sistema de IA...")
    learner = create_learner()
    print(learner.get_status())

    # 2. CONECTAR
    print("\n[2] Conectando a Exnova...")
    account_type = os.getenv("ACCOUNT_TYPE", "PRACTICE")
    print(f"   Modo: {account_type}")

    market_data = MarketDataHandler(broker_name="exnova", account_type=account_type)
    if not market_data.connect(Config.EXNOVA_EMAIL, Config.EXNOVA_PASSWORD):
        print("[ERROR] No se pudo conectar")
        return False

    balance = market_data.get_balance()
    print(f"[OK] Balance: ${balance:.2f}")

    # 3. INICIALIZAR SISTEMAS
    print("\n[3] Inicializando sistemas de trading...")
    asset_manager = AssetManager(market_data)
    feature_engineer = FeatureEngineer()
    risk_manager = RiskManager(
        capital_per_trade=Config.CAPITAL_PER_TRADE,
        stop_loss_pct=Config.STOP_LOSS_PERCENT,
        take_profit_pct=Config.TAKE_PROFIT_PERCENT,
        max_martingale_steps=Config.MAX_MARTINGALE
    )

    # Variables de control
    trade_count = 0
    win_count = 0
    loss_count = 0
    rechazadas_contexto = 0
    rechazadas_ia = 0
    rechazadas_operacion_activa = 0

    print("[OK] Listo - Esperando oportunidades...")
    print("="*80)

    # 4. BUCLE DE OPERACIONES CON CONTROL
    while True:
        try:
            print(f"\n{'='*80}")
            print(f"[CICLO #{trade_count + 1}] - {datetime.now().strftime('%H:%M:%S')}")
            print("="*80)

            # 🚨 VERIFICAR SI HAY OPERACIÓN EN CURSO (PREVENCIÓN)
            if learner.is_operation_in_progress():
                print("⛔ OPERACIÓN EN CURSO - Esperando a que termine...")
                rechazadas_operacion_activa += 1
                time.sleep(10)
                continue

            # A. ESCANEAR MERCADO
            print("\nA) Escaneando mercado...")
            best_op = asset_manager.scan_best_opportunity(feature_engineer)

            if not best_op:
                print("   ⏳ Sin oportunidad clara, esperando 30s...")
                time.sleep(30)
                continue

            asset = best_op['asset']
            direction = best_op['action']
            score = best_op['score']

            print(f"   📊 Oportunidad: {asset} {direction} (Score: {score})")

            # B. OBTENER DATOS
            df = market_data.get_candles(asset, Config.TIMEFRAME, 50)
            if df.empty or len(df) < 20:
                print(f"   ❌ Datos insuficientes")
                time.sleep(5)
                continue

            price = df.iloc[-1]['close']
            rsi = calcular_rsi(df)

            print(f"   Precio: {price:.5f} | RSI: {rsi:.1f}")

            # C. VALIDAR CONTEXTO DE PRECIO
            print(f"\nB) Validando contexto de precio...")
            entrada_valida, razon_contexto = validar_entrada_con_contexto(df, direction)

            if not entrada_valida:
                print(f"   🚫 RECHAZADO (Contexto): {razon_contexto}")
                rechazadas_contexto += 1
                time.sleep(10)
                continue

            print(f"   {razon_contexto}")

            # D. VALIDAR CON IA (APRENDIZAJE + CONTROL)
            print(f"\nC) Consultando IA (incluye control de operaciones)...")

            current_context = {
                'asset': asset,
                'direction': direction,
                'rsi': rsi,
                'price': price,
                'score': score,
                'timestamp': datetime.now().isoformat()
            }

            should_enter, razon_ia = learner.should_enter_trade(current_context)

            if not should_enter:
                print(f"   🚫 RECHAZADO (IA): {razon_ia}")
                rechazadas_ia += 1
                time.sleep(10)
                continue

            print(f"   ✅ {razon_ia}")

            # 🚨 DOBLE VERIFICACIÓN ANTES DE OPERAR
            if learner.is_operation_in_progress():
                print("   ⚠️ ALERTA: Operación empezó mientras validábamos - Saltando")
                continue

            # E. EJECUTAR OPERACIÓN
            print(f"\nD) Ejecutando {direction} en {asset}...")

            amount = Config.CAPITAL_PER_TRADE
            expiration = 5  # 5 minutos

            try:
                # Registrar ANTES de ejecutar (lock)
                operation_data = {
                    'asset': asset,
                    'direction': direction,
                    'rsi': rsi,
                    'price': price,
                    'score': score,
                    'expiration': expiration,
                    'amount': amount,
                    'status': 'OPENING'
                }
                learner.record_operation(operation_data)

                # Ejecutar
                trade_id = market_data.buy(
                    asset=asset,
                    amount=amount,
                    action=direction.lower(),
                    duration=expiration
                )

                trade_count += 1

                print(f"   ✅ OPERACIÓN #{trade_count} EJECUTADA")
                print(f"      ID: {trade_id}")
                print(f"      Monto: ${amount:.2f}")
                print(f"      Expiración: {expiration} min")

            except Exception as e:
                print(f"   ⚠️ Error ejecutando: {e}")
                learner._release_lock()  # Liberar lock si falla
                time.sleep(5)
                continue

            # F. ESPERAR RESULTADO
            print(f"\nE) Esperando resultado ({expiration} minutos)...")
            print(f"   ⏱️  NO se buscarán nuevas operaciones hasta que termine esta")

            wait_time = expiration * 60
            check_interval = 5  # Verificar cada 5 segundos
            elapsed = 0

            while elapsed < wait_time:
                remaining = wait_time - elapsed
                mins = remaining // 60
                secs = remaining % 60
                print(f"   [{mins:02d}:{secs:02d}] Esperando...", end='\r')
                time.sleep(check_interval)
                elapsed += check_interval

                # Verificar si la operación sigue activa (opcional)
                # Aquí podríamos verificar el estado real si la API lo permite

            print("\n   ✅ Tiempo completado!")

            # G. VERIFICAR RESULTADO
            print("F) Verificando resultado...")

            df_new = market_data.get_candles(asset, Config.TIMEFRAME, 10)
            if df_new.empty:
                close_price = price
            else:
                close_price = df_new.iloc[-1]['close']

            movement = ((close_price - price) / price) * 100

            if direction == "CALL":
                is_win = close_price > price
            else:
                is_win = close_price < price

            result = "WIN" if is_win else "LOSS"

            if is_win:
                win_count += 1
                profit = amount * 0.85  # Asumiendo 85% retorno
                print(f"   ✅ WIN: +${profit:.2f}")
            else:
                loss_count += 1
                profit = -amount
                print(f"   ❌ LOSS: ${profit:.2f}")

            print(f"   Movimiento: {movement:+.4f}%")
            print(f"   Entrada: {price:.5f} → Salida: {close_price:.5f}")

            # H. REGISTRAR RESULTADO Y APRENDER
            print(f"\nG) Analizando resultado y aprendiendo...")

            result_data = {
                'asset': asset,
                'direction': direction,
                'rsi': rsi,
                'price': price,
                'close_price': close_price,
                'movement': movement,
                'result': result,
                'profit': profit,
                'context': razon_contexto,
                'score': score,
                'expiration': expiration
            }

            # Analizar con IA
            analysis = learner.analyze_operation(result_data)
            print(f"   📊 Análisis:")
            print(f"      Resultado: {analysis.get('why_won_or_lost', 'N/A')}")
            print(f"      Sugerencia: {analysis.get('suggestion', 'N/A')}")
            if analysis.get('adjustments_made'):
                for adj in analysis['adjustments_made']:
                    print(f"      → {adj}")

            # I. ESTADÍSTICAS
            print(f"\nH) Estadísticas:")
            total_trades = win_count + loss_count
            if total_trades > 0:
                win_rate = (win_count / total_trades) * 100
                print(f"   Operaciones: {total_trades} | Ganadas: {win_count} | Perdidas: {loss_count}")
                print(f"   Win Rate: {win_rate:.1f}%")
                print(f"   Rechazadas (Contexto): {rechazadas_contexto}")
                print(f"   Rechazadas (IA/Lock): {rechazadas_ia + rechazadas_operacion_activa}")

            # J. SUGERENCIAS CADA 10 OPERACIONES
            if trade_count % 10 == 0 and trade_count > 0:
                print(f"\nI) Sugerencias de mejora:")
                suggestions = learner.get_improvement_suggestions()
                for i, sug in enumerate(suggestions, 1):
                    print(f"   {i}. {sug}")

            # K. PAUSA OBLIGATORIA ENTRE OPERACIONES
            print(f"\n⏳ Pausa obligatoria de 30s antes de buscar nueva operación...")
            for i in range(30):
                print(f"   [{i+1:02d}s]", end='\r')
                time.sleep(1)

            print("\n   ✅ Listo para siguiente ciclo")

        except KeyboardInterrupt:
            print("\n\n[STOP] Usuario interrumpió")
            learner._release_lock()  # Asegurar liberar lock
            break
        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            learner._release_lock()  # Asegurar liberar lock en error
            time.sleep(5)

    # RESUMEN FINAL
    print("\n" + "="*80)
    print("RESUMEN FINAL")
    print("="*80)
    print(f"Total operaciones ejecutadas: {trade_count}")
    print(f"Ganadas: {win_count} | Perdidas: {loss_count}")
    if trade_count > 0:
        print(f"Win Rate: {(win_count/trade_count)*100:.1f}%")
    print(f"Rechazadas (Contexto): {rechazadas_contexto}")
    print(f"Rechazadas (IA/Lock): {rechazadas_ia + rechazadas_operacion_activa}")

    print("\n" + learner.get_status())
    print("="*80)

    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
