#!/usr/bin/env python3
"""
BOT SIMPLIFICADO - VERSIÓN QUE REALMENTE OPERA
Elimina validadores bloqueantes, focúsa en OPERACIONES REALES
"""
import sys
import os
import time
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from data.market_data import MarketDataHandler
from strategies.technical import FeatureEngineer
from core.asset_manager import AssetManager
from core.risk import RiskManager

def main():
    print("\n" + "="*80)
    print("BOT SIMPLIFICADO - EJECUTAR OPERACIONES REALES")
    print("="*80)
    
    # 1. CONECTAR
    print("\n[1] Conectando a Exnova PRACTICE...")
    market_data = MarketDataHandler(broker_name="exnova", account_type="PRACTICE")
    if not market_data.connect(Config.EXNOVA_EMAIL, Config.EXNOVA_PASSWORD):
        print("[ERROR] No se pudo conectar")
        return False
    
    balance = market_data.get_balance()
    print(f"[OK] Balance: ${balance:.2f}")
    
    # 2. INICIALIZAR
    print("\n[2] Inicializando sistemas...")
    asset_manager = AssetManager(market_data)
    feature_engineer = FeatureEngineer()
    risk_manager = RiskManager(
        capital_per_trade=Config.CAPITAL_PER_TRADE,
        stop_loss_pct=Config.STOP_LOSS_PERCENT,
        take_profit_pct=Config.TAKE_PROFIT_PERCENT,
        max_martingale_steps=Config.MAX_MARTINGALE
    )
    print("[OK] Listo")
    
    # 3. BUCLE DE OPERACIONES
    print("\n[3] Iniciando ciclo de operaciones...")
    print("="*80)
    
    trade_count = 0
    win_count = 0
    loss_count = 0
    
    while True:
        try:
            trade_count += 1
            print(f"\n[OPERACION #{trade_count}]")
            print("-" * 80)
            
            # A. ESCANEAR MEJOR OPORTUNIDAD
            print("A) Escaneando mercado...")
            best_op = asset_manager.scan_best_opportunity(feature_engineer)
            
            if not best_op:
                print("   ⏳ Sin oportunidad clara, esperando...")
                time.sleep(5)
                continue
            
            asset = best_op['asset']
            direction = best_op['action']
            score = best_op['score']
            
            print(f"   ✅ Oportunidad: {asset} {direction} (Score: {score})")
            
            # B. OBTENER PRECIO ACTUAL
            df = market_data.get_candles(asset, Config.TIMEFRAME, 200)
            if df.empty:
                print(f"   ❌ Sin datos para {asset}")
                time.sleep(2)
                continue
            
            price = df.iloc[-1]['close']
            print(f"   Precio: {price:.5f}")
            
            # C. EJECUTAR OPERACIÓN (SIN VALIDACIÓN BLOQUEANTE)
            print(f"\nB) Ejecutando {direction} en {asset}...")
            
            amount = Config.CAPITAL_PER_TRADE
            expiration = 5  # 5 minutos
            
            try:
                # Ejecutar orden usando el método buy
                trade_id = market_data.buy(
                    asset=asset,
                    amount=amount,
                    action=direction.lower(),
                    duration=expiration
                )
                
                print(f"   ✅ OPERACION EJECUTADA")
                print(f"      ID: {trade_id}")
                print(f"      Monto: ${amount:.2f}")
                print(f"      Expiración: {expiration} min")
                
            except Exception as e:
                print(f"   ⚠️ Error ejecutando: {e}")
                continue
            
            # D. ESPERAR RESULTADO - TIEMPO REAL (5 MINUTOS)
            print(f"\nC) Esperando resultado ({expiration} minutos)...")
            
            # Esperar el tiempo COMPLETO de la operación (5 minutos = 300 segundos)
            wait_time = expiration * 60  # Sin limitar - esperar tiempo real
            for i in range(wait_time):
                remaining = wait_time - i - 1
                print(f"   [{i+1:03d}s] {remaining:03d}s restantes", end='\r')
                time.sleep(1)
            
            print()
            
            # E. VERIFICAR RESULTADO
            print("D) Verificando resultado...")
            
            # Obtener precio de cierre
            df_new = market_data.get_candles(asset, Config.TIMEFRAME, 10)
            if df_new.empty:
                close_price = price
            else:
                close_price = df_new.iloc[-1]['close']
            
            # Calcular ganancia/pérdida
            movement = ((close_price - price) / price) * 100
            
            if direction == "CALL":
                is_win = close_price > price
            else:
                is_win = close_price < price
            
            if is_win:
                win_count += 1
                result = "✅ WIN"
                profit = amount
                print(f"   {result}: +${profit:.2f}")
            else:
                loss_count += 1
                result = "❌ LOSS"
                profit = -amount
                print(f"   {result}: ${profit:.2f}")
            
            print(f"   Movimiento: {movement:+.4f}%")
            print(f"   Entrada: {price:.5f} → Salida: {close_price:.5f}")
            
            # F. ESTADÍSTICAS
            print(f"\nE) Estadísticas:")
            total_trades = win_count + loss_count
            if total_trades > 0:
                win_rate = (win_count / total_trades) * 100
                print(f"   Total: {total_trades} operaciones")
                print(f"   Ganancias: {win_count} ({win_rate:.1f}%)")
                print(f"   Pérdidas: {loss_count} ({100-win_rate:.1f}%)")
            
            # Pausa entre operaciones
            print(f"\n⏳ Esperando 30s antes de siguiente operación...")
            for i in range(30):
                print(f"   [{i+1:02d}s]", end='\r')
                time.sleep(1)
            
        except KeyboardInterrupt:
            print("\n\n[STOP] Usuario interrumpió")
            break
        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)
    
    # RESUMEN FINAL
    print("\n" + "="*80)
    print("RESUMEN FINAL")
    print("="*80)
    print(f"Total operaciones: {trade_count}")
    print(f"Ganancias: {win_count}")
    print(f"Pérdidas: {loss_count}")
    if trade_count > 0:
        print(f"Win Rate: {(win_count/trade_count)*100:.1f}%")
    print("="*80)
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
