# -*- coding: utf-8 -*-
"""
Backtest vectorizado del playbook completo: sintetico OTC frente a mercado real.

Uso:
    python scripts/backtest_playbook.py
    python scripts/backtest_playbook.py --payout 0.85 --expiries 1,3,5
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.backtest.vectorized import PLAYBOOK, evaluate_signals   # noqa: E402

HISTORY_DIR = ROOT / "bot" / "data" / "history"
OOS_FRACTION = 0.30
MIN_OOS = 60


def wilson(w: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m), min(1.0, c + m))


def load() -> dict[str, pd.DataFrame]:
    out = {}
    for p in sorted(HISTORY_DIR.glob("*_60.parquet")):
        df = pd.read_parquet(p).sort_index()
        if len(df) >= 1000:
            out[p.stem[:-3]] = df
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payout", type=float, default=0.86)
    ap.add_argument("--expiries", default="1,3,5")
    args = ap.parse_args()

    breakeven = 1 / (1 + args.payout)
    expiries = [int(x) for x in args.expiries.split(",")]
    data = load()
    if not data:
        print(f"No hay historico en {HISTORY_DIR}")
        return 1

    print("=" * 96)
    print("BACKTEST DEL PLAYBOOK INVESTIGADO — SINTETICO OTC vs MERCADO REAL")
    print("=" * 96)
    print(f"Payout {args.payout:.3f} -> break-even {100 * breakeven:.2f}%")
    print(f"Activos: {len(data)}  |  Estrategias: {len(PLAYBOOK)}  |  "
          f"Expiraciones: {expiries} min")
    print("Solo cuenta el 30% mas reciente (fuera de muestra).\n")

    # Bonferroni sobre el numero real de combinaciones evaluadas.
    n_tests = len(PLAYBOOK) * len(expiries) * 2
    z_corr = 1.96 + 0.5 * math.log(max(n_tests, 1))

    rows = []
    for strat_name, fn in PLAYBOOK.items():
        for exp in expiries:
            for market in ("SINTETICO", "REAL"):
                assets = [(a, d) for a, d in data.items()
                          if (("-OTC" in a) == (market == "SINTETICO"))]
                if not assets:
                    continue
                n_in = w_in = n_out = w_out = 0
                for _, df in assets:
                    sig = fn(df)
                    res = evaluate_signals(df, sig, exp)
                    if res.empty:
                        continue
                    split = df.index[int(len(df) * (1 - OOS_FRACTION))]
                    ins, oos = res[res.index < split], res[res.index >= split]
                    n_in += len(ins); w_in += int(ins["win"].sum())
                    n_out += len(oos); w_out += int(oos["win"].sum())

                if n_out < MIN_OOS:
                    continue
                lo, hi = wilson(w_out, n_out, z_corr)
                rows.append({
                    "strat": strat_name, "exp": exp, "market": market,
                    "n_in": n_in, "wr_in": w_in / n_in if n_in else 0,
                    "n_out": n_out, "wr_out": w_out / n_out,
                    "lo": lo, "hi": hi,
                    "edge": lo > breakeven,
                })

    rows.sort(key=lambda r: -r["wr_out"])

    print(f"{'estrategia':<28}{'mkt':<11}{'exp':>4}{'n_in':>7}{'wr_in':>8}"
          f"{'n_oos':>7}{'wr_oos':>8}   IC corregido")
    print("-" * 96)
    for r in rows:
        star = "  <== EDGE" if r["edge"] else ""
        print(f"{r['strat'][:26]:<28}{r['market']:<11}{r['exp']:>3}m{r['n_in']:>7}"
              f"{100 * r['wr_in']:>7.1f}%{r['n_out']:>7}{100 * r['wr_out']:>7.1f}%"
              f"   [{100 * r['lo']:5.1f}%,{100 * r['hi']:5.1f}%]{star}")

    print("=" * 96)
    winners = [r for r in rows if r["edge"]]
    if winners:
        print(f"CON EDGE DEMOSTRADO FUERA DE MUESTRA ({len(winners)}):")
        for r in winners:
            print(f"  {r['strat']} | {r['market']} | {r['exp']}min | "
                  f"{100 * r['wr_out']:.1f}% (n={r['n_out']})")
    else:
        print("NINGUNA estrategia del playbook demuestra edge, en ningun mercado.")
        if rows:
            b = rows[0]
            print(f"\nLa mejor: {b['strat']} en {b['market']} a {b['exp']}min -> "
                  f"{100 * b['wr_out']:.1f}% fuera de muestra (n={b['n_out']}),")
            print(f"pero su intervalo baja a {100 * b['lo']:.1f}%, "
                  f"por debajo del {100 * breakeven:.1f}% necesario.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
