#!/usr/bin/env python3
"""Diagnostico: mide donde la cascada de filtros bloquea trades (modo practice).

Corre N ciclos sobre los mismos assets/mock candles que bot/main.py y cuenta
cuantas decisiones caen en cada razon de WAIT, y cuantas llegan a TRADE.
"""
import os
import sys
import re
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from collections import Counter

BOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot")
sys.path.insert(0, BOT_DIR)
sys.path.insert(0, os.path.join(BOT_DIR, "brain"))
sys.path.insert(0, os.path.join(BOT_DIR, "engine"))

os.environ.setdefault("AI_AUDIT_ENABLED", "false")
os.environ.setdefault("SMC_EDGE_FILTER", "0")

from engine.intelligent_engine import IntelligentEngine
from config_assets import ASSETS_OTC_24_7


def get_price_range(asset):
    if "JPY" in asset:
        return np.random.uniform(130, 160)
    elif "EUR" in asset or "GBP" in asset:
        return np.random.uniform(1.08, 1.40)
    elif "AUD" in asset or "NZD" in asset or "CAD" in asset:
        return np.random.uniform(0.60, 1.10)
    elif "BTC" in asset:
        return np.random.uniform(40000, 50000)
    elif "ETH" in asset:
        return np.random.uniform(2000, 3000)
    elif "GOLD" in asset:
        return np.random.uniform(1800, 2100)
    elif "OIL" in asset:
        return np.random.uniform(70, 90)
    elif "COPPER" in asset:
        return np.random.uniform(3.5, 4.5)
    elif "-OTC" in asset:
        return np.random.uniform(15000, 50000)
    else:
        return np.random.uniform(1.0, 2.0)


def generate_mock_candles(asset, limit=100):
    now = datetime.utcnow()
    data = []
    price = get_price_range(asset)
    volatility = np.random.uniform(0.001, 0.01)
    for i in range(limit):
        t = now - timedelta(minutes=limit - i)
        o = price
        c = price * (1 + np.random.normal(0, volatility))
        h = max(o, c) * (1 + np.random.uniform(0, 0.005))
        l = min(o, c) * (1 - np.random.uniform(0, 0.005))
        data.append({"time": t, "open": o, "high": h, "low": l, "close": c,
                     "volume": np.random.randint(1000, 10000)})
        price = c
    df = pd.DataFrame(data)
    df.set_index("time", inplace=True)
    return df


def bucket(reason):
    r = reason or ""
    rules = [
        ("sin_zonas", r"Sin zonas"),
        ("zona_debil", r"Zona d.bil"),
        ("ia_bloquea", r"IA bloquea"),
        ("ia_dir_mismatch", r"IA sugiere \w+ pero zona"),
        ("ia_score_bajo", r"IA score bajo"),
        ("mal_patron", r"Patr.n rechazado"),
        ("contra_tendencia", r"Contra-tendencia"),
        ("estructura", r"Estructura/timing"),
        ("timing_retro", r"Timing de retroceso"),
        ("rechazo_reglas", r"RECHAZO"),
        ("rebote", r"REBOTE"),
        ("trampa", r"TRAMPA"),
        ("smc", r"SMC:"),
        ("edge", r"EDGE:"),
        ("cerca_de_zona", r"Precio muy cerca"),
        ("neutral", r"NEUTRAL no v.lida"),
    ]
    for name, pat in rules:
        if re.search(pat, r):
            extra = ""
            m = re.search(r"RECHAZO:\s*([a-z_]+)", r)
            if m:
                extra = f" ({m.group(1)})"
            m2 = re.search(r"REBOTE\s+(\w+)", r)
            if m2:
                extra = f" ({m2.group(1)})"
            return name + extra
    return "OTRO: " + r[:50]


def main():
    cycles = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    assets = ASSETS_OTC_24_7
    engine = IntelligentEngine(session_name="diag", mode="practice")
    counts = Counter()
    trades = 0
    total = 0
    errors = Counter()
    for cyc in range(cycles):
        for asset in assets:
            try:
                df_m1 = generate_mock_candles(asset, 100)
                df_m5 = generate_mock_candles(asset, 100)
                df_m15 = generate_mock_candles(asset, 100)
                df_h1 = generate_mock_candles(asset, 10)
                d = engine.evaluate_market(asset, df_m1, df_m5, df_m15, None, df_h1)
                total += 1
                if d.get("action") == "TRADE":
                    trades += 1
                else:
                    counts[bucket(d.get("reason", ""))] += 1
            except Exception as e:
                errors[type(e).__name__ + ": " + str(e)[:60]] += 1
                total += 1
    print(f"\n=== DIAGNOSTICO: {total} evaluaciones, {trades} TRADEs "
          f"({100*trades/max(total,1):.2f}%) ===\n")
    for k, v in counts.most_common():
        print(f"  {v:5d}  {100*v/total:5.1f}%  {k}")
    if errors:
        print("\nERRORES:")
        for k, v in errors.most_common():
            print(f"  {v:5d}  {k}")


if __name__ == "__main__":
    main()
