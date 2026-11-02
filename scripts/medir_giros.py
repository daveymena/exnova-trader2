# -*- coding: utf-8 -*-
"""
¿Que tienen en comun las operaciones que giraron? Lateral (cruces de la EMA 20 en 10 min y
ancho del rango) y lectura de Gemma en las operaciones reales, y el mismo patron en las
senales del historial de 15 s de IQ. Solo lectura. Uso: python scripts/medir_giros.py
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
from backtest_playbook import wilson                             # noqa: E402
from bot.vision.ejemplos_usuario import H, _load                 # noqa: E402
from iq_probe import connect                                     # noqa: E402
from medir_vencimiento import fin_binaria, senales               # noqa: E402

CORTES = ((3, "pocos cruces, 0-3"), (6, "algunos, 4-6"), (99, "lateral, 7 o mas"))


def contexto(d: pd.DataFrame) -> dict:
    c, hi, lo = d["close"].astype(float), d["max"].astype(float), d["min"].astype(float)
    e20 = c.ewm(span=20, adjust=False).mean()
    atr = (hi - lo).iloc[-21:-1].mean()
    return {"cruces": int(((c - e20) > 0).astype(int).diff().abs().iloc[-40:].sum()),
            "rango10": round(float((hi.iloc[-40:].max() - lo.iloc[-40:].min()) / atr), 1)}


def grupo(t: pd.DataFrame, m: pd.Series) -> str:
    x = t[m]
    return f"{int((x.res == 'win').sum())}G {int((x.res == 'loose').sum())}P"


def reales() -> None:
    api, filas = connect(), []
    for o in csv.DictReader(open(ROOT / "bot/data/gemma_real_live.csv", encoding="utf-8")):
        if o["status"] not in ("win", "loose"):
            continue
        f = json.loads(o["features"])
        t = pd.Timestamp(o["signal_candle_utc"]) + pd.Timedelta(seconds=15)
        d = pd.DataFrame(api.get_candles(o["asset"], 15, 200, t.timestamp()))
        d = d[d["from"] + 15 <= t.timestamp()]
        filas.append({"hora": o["signal_candle_utc"][11:16], "activo": o["asset"], "dir": o["direction"], "res": o["status"],
                      "ema200": "EMA200" in f.get("razon", ""), "pos3h": round(f.get("pos_3h", 0), 2), **contexto(d)})
    t = pd.DataFrame(filas)
    pd.set_option("display.width", 200)
    print(t.tail(6).to_string(index=False))
    print("Gemma cita EMA200:", grupo(t, t.ema200), "| no la cita:", grupo(t, ~t.ema200))
    previo = 0
    for corte, nombre in CORTES:
        print(f"  {nombre}: {grupo(t, (t.cruces > previo - 1 if previo else t.cruces >= 0) & (t.cruces <= corte))}")
        previo = corte + 1


def historial() -> None:
    out = []
    for fp in sorted(H.glob("*_15.parquet")):
        df = _load(fp.stem.rsplit("_", 1)[0])
        s = senales(df, "confirma", comienzo=True, tendencia=True)
        if s.empty:
            continue
        cl = df["close"]
        arriba = (cl - cl.ewm(span=20, adjust=False).mean()) > 0
        cruces = arriba.astype(int).diff().abs().rolling(40).sum()
        fin = fin_binaria(s.index + pd.Timedelta(seconds=16), 3) - pd.Timedelta(seconds=15)
        s["r"] = np.sign(s["lado"].to_numpy() * (cl.reindex(fin).to_numpy() - s["p"].to_numpy()))
        s["cruces"] = cruces.reindex(s.index)
        out.append(s)
    t = pd.concat(out).sort_index().dropna(subset=["r", "cruces"])
    t = t[t.r != 0]
    corte = t.index[len(t) // 2]
    print(f"\nHistorial, {len(t)} senales, a 3 min:")
    previo = 0
    for hasta, nombre in CORTES:
        x = t[(t.cruces >= previo) & (t.cruces <= hasta)]
        d, v = x[x.index < corte], x[x.index >= corte]
        g, n = int((x.r > 0).sum()), len(x)
        lo, hi = wilson(g, n) if n else (0, 0)
        print(f"  {nombre}: {100 * g / max(n, 1):.1f}% [{100 * lo:.1f}-{100 * hi:.1f}] n={n} | dev {100 * (d.r > 0).mean():.1f}% val {100 * (v.r > 0).mean():.1f}%")
        previo = hasta + 1


def main() -> int:
    reales()
    historial()
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
