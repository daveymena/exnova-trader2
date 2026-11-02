# -*- coding: utf-8 -*-
"""
Repaso de cada operacion real: mueve la entrada de -60 a +60 s con la misma duracion y mide
por cuanto habria ganado o perdido, en rangos de vela de 15 s. Resume en
reports/repaso_real.txt si la entrada fue ajustada y que punto suele dar mas margen.
Solo lectura. Uso: python scripts/repaso_real.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from ciclo_fin import fin_binaria                                # noqa: E402
from iq_probe import connect                                     # noqa: E402

OPS = ROOT / "bot" / "data" / "gemma_real_live.csv"
REPORTE = ROOT / "reports" / "repaso_real.txt"
OFFSETS = range(-60, 61, 15)
AJUSTADA = 0.5       # menos de medio rango de vela de margen: casi empate


def repasar(api, o: dict) -> dict | None:
    t0 = pd.Timestamp(o["signal_candle_utc"]) + pd.Timedelta(seconds=15)
    c = api.get_candles(o["asset"], 15, 100, t0.timestamp() + 330)
    if not c:
        return None
    v = pd.DataFrame(c)
    v.index = pd.to_datetime(v["from"] + 15, unit="s")
    px = v["close"].astype(float)
    atr = float((v["max"] - v["min"]).astype(float).iloc[:40].mean())
    d = 1 if o["direction"] == "call" else -1
    dur = fin_binaria(t0 + pd.Timedelta(seconds=1), int(o["expiry_min"])) - t0
    m = {}
    for s in OFFSETS:
        ini = t0 + pd.Timedelta(seconds=s)
        a, b = px.get(ini), px.get(ini + dur)
        if a is not None and b is not None:
            m[s] = d * (b - a) / atr
    return {"op": o, "margen": m} if 0 in m else None


def actualizar(api=None) -> int:
    if not OPS.exists():
        return 0
    api = api or connect()
    ops = [o for o in csv.DictReader(open(OPS, encoding="utf-8")) if o["status"] in ("win", "loose", "equal")]
    filas = [r for r in (repasar(api, o) for o in ops) if r]
    L = [f"Operaciones reales repasadas: {len(filas)}. Margen en rangos de vela de 15 s; menos de {AJUSTADA} es casi empate."]
    for r in filas:
        o, m = r["op"], r["margen"]
        mejor = max(m, key=m.get)
        tipo = "AJUSTADA" if abs(m[0]) < AJUSTADA else "holgada"
        L.append(f"\n{o['signal_candle_utc']} {o['asset']} {o['direction'].upper()} {o['status']} {o['broker_profit']} | "
                 f"margen {m[0]:+.1f} ({tipo}) | mejor punto {mejor:+d} s con {m[mejor]:+.1f}")
        L.append("  " + " ".join(f"{s:+d}s:{x:+.1f}" for s, x in sorted(m.items())))
    if filas:
        t = pd.DataFrame([r["margen"] for r in filas])
        L.append("\nPromedio por punto de entrada:")
        L += [f"  {s:+d} s: margen {t[s].mean():+.2f}, ganarian {int((t[s] > 0).sum())}/{t[s].notna().sum()}" for s in sorted(t.columns)]
    REPORTE.write_text("\n".join(L) + "\n", encoding="utf-8")
    return len(filas)


if __name__ == "__main__":
    import os
    n = actualizar()
    print("repasadas", n, flush=True)
    os._exit(0)
