#!/usr/bin/env python3
"""
EXNOVA BOT v5.1 — 72 ACTIVOS OTC 24/7
Ejecuta con motor inteligente + detección de trampas + aprendizaje
"""

import os
import sys
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Setup paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "brain"))

load_dotenv()

# Importaciones
from engine.intelligent_engine import IntelligentEngine
from config_assets import ASSETS_OTC_24_7, get_current_time_colombia, es_horario_manana

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN OPERATIVA v4
# ─────────────────────────────────────────────────────────────────────────────

ASSETS = ASSETS_OTC_24_7  # 68 activos OTC
MIN_CONFIDENCE = 0.55  # Umbral mínimo de confianza (necesitamos >54% WR)
MIN_ZONE_STRENGTH = 0.55  # Fuerza mínima de zona (subido de 0.50)
MIN_HOLD_RATE = 0.35  # Tasa mínima de retención (subido de 0.25)
IA_MIN_SCORE = 50  # Score mínimo IA para operar (subido de 45)

# ─────────────────────────────────────────────────────────────────────────────
# GENERADOR DE CANDLES (MOCK)
# ─────────────────────────────────────────────────────────────────────────────

def get_price_range(asset: str):
    """Retorna rango de precio por tipo de activo."""
    if "JPY" in asset:
        return np.random.uniform(130, 160)  # USDJPY 130-160
    elif "EUR" in asset or "GBP" in asset:
        return np.random.uniform(1.08, 1.40)  # EUR/GBP
    elif "AUD" in asset or "NZD" in asset or "CAD" in asset:
        return np.random.uniform(0.60, 1.10)  # Antipodas/CAD
    elif "BTC" in asset:
        return np.random.uniform(40000, 50000)  # Bitcoin
    elif "ETH" in asset:
        return np.random.uniform(2000, 3000)  # Ethereum
    elif "GOLD" in asset:
        return np.random.uniform(1800, 2100)  # Oro
    elif "OIL" in asset:
        return np.random.uniform(70, 90)  # Petróleo
    elif "COPPER" in asset:
        return np.random.uniform(3.5, 4.5)  # Cobre
    elif "-OTC" in asset:  # Índices
        return np.random.uniform(15000, 50000)  # Índices
    else:
        return np.random.uniform(1.0, 2.0)  # Default

def generate_mock_candles(asset: str, interval: str, limit: int = 100) -> pd.DataFrame:
    """Genera candles ficticios con volatilidad realista por activo."""
    now = datetime.utcnow()
    data = []
    price = get_price_range(asset)
    volatility = np.random.uniform(0.001, 0.01)  # Volatilidad variable
    
    for i in range(limit):
        time_offset = now - timedelta(minutes=limit-i)
        
        # Movimiento más realista
        open_p = price
        change = np.random.normal(0, volatility)  # Distribución normal
        close_p = price * (1 + change)
        high_p = max(open_p, close_p) * (1 + np.random.uniform(0, 0.005))
        low_p = min(open_p, close_p) * (1 - np.random.uniform(0, 0.005))
        
        data.append({
            "time": time_offset,
            "open": open_p,
            "high": high_p,
            "low": low_p,
            "close": close_p,
            "volume": np.random.randint(1000, 10000),
        })
        price = close_p
    
    df = pd.DataFrame(data)
    df.set_index("time", inplace=True)
    return df

# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """Bucle principal del bot - 72 activos OTC 24/7."""
    print("\n" + "="*90)
    print("  EXNOVA BOT v5.1 - 72 ACTIVOS OTC 24/7")
    print("  Motor: IntelligentEngine v4.2 + Trap Detection + Aprendizaje")
    print(f"  Activos: {len(ASSETS)} OTC (Forex, Indices, Criptos, Materias Primas)")
    print(f"  Config: MIN_CONF={MIN_CONFIDENCE} | ZONE={MIN_ZONE_STRENGTH} | HOLD={MIN_HOLD_RATE}")
    print("="*90 + "\n")
    
    # Inicializar motor
    try:
        engine = IntelligentEngine(session_name="main_24h")
    except TypeError:
        engine = IntelligentEngine(session_name="main_24h")
    
    cycle = 0
    total_trades = 0
    total_wins = 0
    total_losses = 0
    total_pnl = 0.0
    cycle_start_time = time.time()
    
    # Bucle infinito
    while True:
        cycle += 1
        timestamp = datetime.now().strftime("%H:%M:%S")
        hora_colombia = get_current_time_colombia()
        es_manana = es_horario_manana()
        
        print(f"\n[{timestamp}] === CICLO #{cycle} === (Colombia: {hora_colombia} | Manana: {es_manana})")
        print(f"  Total hasta ahora: {total_trades} trades | W/L: {total_wins}/{total_losses} ({100*total_wins/(total_trades+1):.1f}%) | PnL: +${total_pnl:.2f}\n")
        
        cycle_trades = 0
        cycle_wins = 0
        
        for idx, asset in enumerate(ASSETS, 1):
            try:
                # Generar candles ficticios
                df_m1 = generate_mock_candles(asset, "1m", 100)
                df_m5 = generate_mock_candles(asset, "5m", 100)
                df_m15 = generate_mock_candles(asset, "15m", 100)
                df_h1 = generate_mock_candles(asset, "1h", 10)
                
                # Evaluar mercado
                decision = engine.evaluate_market(asset, df_m1, df_m5, df_m15, df_h1)
                
                action = decision.get("action", "WAIT")
                reason = decision.get("reason", "---")
                confidence = decision.get("confidence", 0)
                signal = decision.get("signal", "---")
                pattern = decision.get("pattern", "")
                zone_strength = decision.get("zone_strength", 0)
                
                # Simular resultado de trade
                if action == "TRADE":
                    is_win = np.random.choice([True, False], p=[0.56, 0.44])  # 56% win rate
                    pnl = 8.50 if is_win else -5.20
                    
                    total_trades += 1
                    cycle_trades += 1
                    if is_win:
                        total_wins += 1
                        cycle_wins += 1
                    else:
                        total_losses += 1
                    
                    total_pnl += pnl
                    
                    print(f"  [TRADE] #{total_trades:3d} | {asset:15s} | CONF:{confidence:.2f} | {signal:4s} | PnL:${pnl:+6.2f} | TOTAL:${total_pnl:+7.2f}")
                else:
                    print(f"  [WAIT] {asset:15s} | {reason[:45]}")
                
                # Pequeña pausa entre análisis
                time.sleep(0.1)
                
            except Exception as e:
                print(f"  [ERROR] {asset:15s} | {str(e)[:45]}")
        
        # Resumen del ciclo
        elapsed = time.time() - cycle_start_time
        print(f"\n[RESUMEN CICLO #{cycle}]")
        print(f"  Trades: {cycle_trades} | Wins: {cycle_wins} | Win Rate: {100*cycle_wins/(cycle_trades+0.1):.1f}%")
        print(f"  Total acumulado: {total_trades} trades | PnL: +${total_pnl:.2f} | Tiempo: {elapsed:.0f}s")
        print(f"  > Esperando 6 segundos antes del proximo ciclo...\n")
        
        time.sleep(6)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[INFO] Bot detenido por usuario (Ctrl+C).")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
