#!/usr/bin/env python3
"""
BOT CON IA V2 - CONTROL DE OPERACIONES ROBUSTO
Sistema mejorado para prevenir operaciones simultáneas
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
from operation_lock import get_lock, emergency_release

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


def main():
    print("\n" + "="*80)
    print("BOT CON IA V2 - CONTROL ROBUSTO DE OPERACIONES")
    print("="*80)
    print("✅ Lock atómico para prevenir operaciones simultáneas")
    print("✅ Verificación de proceso vivo")
    print("✅ Limpieza automática de locks huérfanos")
    print("="*80)

    # Inicializar sistema de lock
    lock = get_lock()

    # Verificar si hay lock previo y liberarlo
    if lock.is_locked():
        print("\n⚠️  Detectado lock anterior, liberando...")
        emergency_release()

    # Inicializar IA
    print("\n[1] Inicializando sistema de IA...")
    learner = create_learner()
    print(learner.get_status())

    # Conectar
    print("\n[2] Conectando a Exnova...")
    account_type = os.getenv("ACCOUNT_TYPE", "PRACTICE")
    print(f"   Modo: {account_type}")

    market_data = MarketDataHandler(broker_name="exnova", account_type=account_type)
    if not market_data.connect(Config.EXNOVA_EMAIL, Config.EXNOVA_PASSWORD):
        print("[ERROR] No se pudo conectar")
        return False

    balance = market_data.get_balance()
    print(f"[OK] Balance: ${balance:.2f}")

    # Inicializar sistemas
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
    rechazadas_lock = 0

    print("[OK] Listo - Esperando oportunidades...")
    print("="*80)

    # BUCLE PRINCIPAL
    while True:
        try:
            print(f"\n{'='*80}")
            print(f"[CICLO #{trade_count + 1}] - {datetime.now().strftime('%H:%M:%S')}")
            print("="*80)

            # 🚨 VERIFICAR LOCK GLOBAL (PRIORIDAD #1)
            if lock.is_locked():
                lock_info = lock.get_lock_info()
                if lock_info:
                    print(f"⛔ LOCK ACTIVO: Operación en curso desde {lock_info.get('created_at', 'desconocido')}")
                    print(f"   PID: {lock_info.get('pid', 'N/A')}")
                    rechazadas_lock += 1
                else:
                    print(f"⛔ LOCK ACTIVO: Otra operación en curso")
                print("   Esperando 10 segundos...")
                time.sleep(10)
                continue

            # Escaneo de mercado
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

            # Obtener datos
            df = market_data.get_candles(asset, Config.TIMEFRAME, 50)
            if df.empty or len(df) < 20:
                print(f"   ❌ Datos insuficientes")
                time.sleep(5)
                continue

            price = df.iloc[-1]['close']
            rsi = calcular_rsi(df)

            print(f"   Precio: {price:.5f} | RSI: {rsi:.1f}")

            # Validar contexto
            print(f"\nB) Validando contexto de precio...")
            entrada_valida, razon_contexto = validar_entrada_con_contexto(df, direction)

            if not entrada_valida:
                print(f"   🚫 RECHAZADO (Contexto): {razon_contexto}")
                rechazadas_contexto += 1
                time.sleep(10)
                continue

            print(f"   ✅ {razon_contexto}")

            # Validar con IA
            print(f"\nC) Consultando IA...")

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

            # 🚨 DOBLE VERIFICACIÓN DE LOCK
            if lock.is_locked():
                print("   ⚠️ ALERTA: Lock apareció mientras validábamos - Saltando")
                rechazadas_lock += 1
                continue

            # ADQUIRIR LOCK ATÓMICAMENTE
            operation_data = {
                'asset': asset,
                'direction': direction,
                'price': price,
                'rsi': rsi,
                'score': score
            }

            if not lock.acquire(operation_data):
                print("   ❌ No se pudo adquirir lock - Otra instancia tomó el lock")
                rechazadas_lock += 1
                continue

            # EJECUTAR OPERACIÓN
            print(f"\nD) Ejecutando {direction} en {asset}...")

            amount = Config.CAPITAL_PER_TRADE
            expiration = 5

            try:
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

                # Registrar en IA
                learner.record_operation({
                    'asset': asset,
                    'direction': direction,
                    'rsi': rsi,
                    'price': price,
                    'close_price': price,
                    'movement': 0,
                    'result': 'PENDING',
                    'profit': 0,
                    'context': razon_contexto,
                    'score': score,
                    'expiration': expiration
                })

            except Exception as e:
                print(f"   ⚠️ Error ejecutando: {e}")
                lock.release()
                time.sleep(5)
                continue

            # ESPERAR RESULTADO
            print(f"\nE) Esperando resultado ({expiration} min)...")
            print(f"   🔒 LOCK mantiene bloqueadas nuevas operaciones")

            wait_time = expiration * 60
            elapsed = 0

            while elapsed < wait_time:
                remaining = wait_time - elapsed
                mins = remaining // 60
                secs = remaining % 60
                print(f"   [{mins:02d}:{secs:02d}] Esperando...", end='\r')
                time.sleep(5)
                elapsed += 5

            print("\n   ✅ Tiempo completado!")

            # VERIFICAR RESULTADO
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
                profit = amount * 0.85
                print(f"   ✅ WIN: +${profit:.2f}")
            else:
                loss_count += 1
                profit = -amount
                print(f"   ❌ LOSS: ${profit:.2f}")

            print(f"   Movimiento: {movement:+.4f}%")

            # REGISTRAR Y APRENDER
            print(f"\nG) Analizando y aprendiendo...")

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

            analysis = learner.analyze_operation(result_data)
            print(f"   {analysis.get('suggestion', 'N/A')}")

            # LIBERAR LOCK
            lock.release()

            # ESTADÍSTICAS
            print(f"\nH) Estadísticas:")
            total_trades = win_count + loss_count
            if total_trades > 0:
                win_rate = (win_count / total_trades) * 100
                print(f"   Operaciones: {total_trades} | Ganadas: {win_count} | Perdidas: {loss_count}")
                print(f"   Win Rate: {win_rate:.1f}%")
                print(f"   Rechazadas (Contexto): {rechazadas_contexto}")
                print(f"   Rechazadas (IA): {rechazadas_ia}")
                print(f"   Rechazadas (Lock): {rechazadas_lock}")

            # PAUSA ENTRE OPERACIONES
            print(f"\n⏳ Pausa de 30s antes de buscar nueva operación...")
            for i in range(30):
                print(f"   [{i+1:02d}s]", end='\r')
                time.sleep(1)

            print("\n   ✅ Listo para siguiente ciclo")

        except KeyboardInterrupt:
            print("\n\n[STOP] Usuario interrumpió")
            lock.release()
            break
        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            lock.release()
            time.sleep(5)

    # RESUMEN FINAL
    print("\n" + "="*80)
    print("RESUMEN FINAL")
    print("="*80)
    print(f"Total operaciones: {trade_count}")
    print(f"Ganadas: {win_count} | Perdidas: {loss_count}")
    if trade_count > 0:
        print(f"Win Rate: {(win_count/trade_count)*100:.1f}%")
    print(f"Rechazadas (Lock): {rechazadas_lock}")
    print("="*80)

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
