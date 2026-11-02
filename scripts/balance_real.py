# -*- coding: utf-8 -*-
"""
Balance de la tanda real: resultado por direccion, activo, tipo de mercado, fuerza de la
vela, zona y margen. Solo lectura. Uso: python scripts/balance_real.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from ciclo_fin import fin_binaria                                # noqa: E402
from iq_probe import connect                                     # noqa: E402

EXPS = (1, 2, 3, 4, 5)


def main() -> int:
    ops = [o for o in csv.DictReader(open(ROOT / "bot/data/gemma_real_live.csv", encoding="utf-8")) if o["status"] in ("win", "loose", "equal")]
    api = connect()
    filas = []
    for o in ops:
        f = json.loads(o["features"])
        t0 = pd.Timestamp(o["signal_candle_utc"]) + pd.Timedelta(seconds=15)
        c = pd.DataFrame(api.get_candles(o["asset"], 15, 80, t0.timestamp() + 400))
        px = pd.Series(c["close"].astype(float).to_numpy(), index=pd.to_datetime(c["from"] + 15, unit="s"))
        ant = c[c["from"] + 15 <= t0.timestamp()]
        atr = float((ant["max"] - ant["min"]).astype(float).iloc[-21:-1].mean())
        d = 1 if o["direction"] == "call" else -1
        a = px.get(t0)
        fila = {"hora": o["signal_candle_utc"][11:16], "activo": o["asset"].replace("-OTC", "*"), "dir": o["direction"], "res": o["status"],
                "pnl": float(o["broker_profit"]), "otc": "OTC" in o["asset"], "fuerte": f.get("confirma_fuerte"), "primera": f.get("primera"),
                "pos30": round(f["pos30"], 2), "avance": round(f["avance"], 2), "pos3h": round(f.get("pos_3h", 0), 2)}
        for e in EXPS:
            b = px.get(fin_binaria(t0 + pd.Timedelta(seconds=1), e))
            fila[f"m{e}"] = round(d * (b - a) / atr, 1) if a is not None and b is not None else np.nan
        filas.append(fila)
    t = pd.DataFrame(filas)
    pd.set_option("display.width", 220)
    print(t.drop(columns=["otc"]).to_string(index=False))
    print(f"\nTotal {len(t)}: {int((t.res == 'win').sum())}G {int((t.res == 'loose').sum())}P, {t.pnl.sum():+.2f}")
    for col in ("dir", "otc", "fuerte", "primera"):
        print(col, {str(k): f"{int((g.res == 'win').sum())}G {int((g.res == 'loose').sum())}P" for k, g in t.groupby(col)})
    print("avance", {k: f"{int((g.res == 'win').sum())}G {int((g.res == 'loose').sum())}P" for k, g in t.groupby(t.avance > .3)}, "(True = >0.30)")
    print("pos3h", {k: f"{int((g.res == 'win').sum())}G {int((g.res == 'loose').sum())}P" for k, g in t.groupby(t.pos3h > .8)}, "(True = >0.80)")
    print("ganarian por vencimiento:", {e: f"{int((t[f'm{e}'] > 0).sum())}/{int(t[f'm{e}'].notna().sum())}" for e in EXPS})
    print("casi empate (margen 3 min < 0.5):", int((t.m3.abs() < .5).sum()))
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
