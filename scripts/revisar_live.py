# -*- coding: utf-8 -*-
"""
Revision periodica del forward test: donde gana y donde pierde la estrategia.

Lee bot/data/<estrategia>_live.csv (resultado del BROKER, que es el que paga)
y lo parte por activo, hora y por el contexto guardado en la columna
`features`. Un segmento solo se marca para filtrar si su intervalo de Wilson,
corregido por Bonferroni sobre todos los segmentos probados, queda entero por
debajo del break-even: asi no se apagan activos por una mala racha.

Uso:
    python scripts/revisar_live.py --strategy choque --payout 0.86
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import NormalDist

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from backtest_playbook import wilson              # noqa: E402

MIN_N = 30


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="choque")
    ap.add_argument("--payout", type=float, default=0.86)
    args = ap.parse_args()
    be = 1 / (1 + args.payout)

    name = "azura_live.csv" if args.strategy == "azura" else f"{args.strategy}_live.csv"
    df = pd.read_csv(ROOT / "bot" / "data" / name)
    df = df[df["status"].isin(["win", "loose"])].copy()
    if df.empty:
        print("Todavia no hay operaciones resueltas por el broker.")
        return 0
    df["win"] = df["status"] == "win"
    df["hora_utc"] = pd.to_datetime(df["signal_candle_utc"]).dt.hour
    if "features" in df:
        feats = df["features"].map(lambda s: json.loads(s) if isinstance(s, str) and s else {})
        df = df.join(pd.DataFrame(feats.tolist(), index=df.index))

    n, w = len(df), int(df.win.sum())
    lo, hi = wilson(w, n)
    print("=" * 78)
    print(f"{args.strategy.upper()} en vivo | {n} operaciones | acierto {100 * w / n:.1f}% "
          f"IC95 [{100 * lo:.1f}%, {100 * hi:.1f}%] | break-even {100 * be:.1f}%")
    print(f"beneficio demo: {df['broker_profit'].sum():+.2f} USD")
    print("=" * 78)

    segments = {"activo": df["asset"],
                "hora_utc": pd.cut(df["hora_utc"], [-1, 6, 12, 17, 23],
                                   labels=["00-06", "07-12", "13-17", "18-23"])}
    for col in ("body_atr", "rechazo", "vol_regimen", "previas_atr"):
        if col in df and df[col].notna().sum() >= 3 * MIN_N:
            vals = df[col].abs() if col == "body_atr" else df[col]
            segments[col] = pd.qcut(vals, 3, labels=["bajo", "medio", "alto"], duplicates="drop")

    groups = [(seg, k, g) for seg, key in segments.items() for k, g in df.groupby(key, observed=True)]
    z = NormalDist().inv_cdf(1 - 0.05 / (2 * max(len(groups), 1)))
    for seg, k, g in groups:
        gn, gw = len(g), int(g.win.sum())
        glo, ghi = wilson(gw, gn, z)
        flag = ("muestra corta" if gn < MIN_N else "FILTRAR" if ghi < be
                else "CONFIRMADO" if glo > be else "")
        print(f"{seg:>12} {str(k):<14} n={gn:>4}  {100 * gw / gn:5.1f}%  "
              f"[{100 * glo:5.1f}%,{100 * ghi:5.1f}%]  {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
