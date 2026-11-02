# -*- coding: utf-8 -*-
"""
Refinamiento de H5 (reversion tras vela de choque) sin tocar el holdout.

Rejilla pequena elegida por fundamento de microestructura:
  umbral   cuerpo >= 1.5 / 2.0 / 2.5 / 3.0 ATR (choques mayores = mas sobrerreaccion)
  exp      2 / 3 / 5 min
  mercado  forex / indices / oro
  mecha    exigir o no que la vela ya muestre rechazo (mecha >= 25% del rango
           en contra del cuerpo): el giro ya empezo dentro de la vela

Se ELIGE la mejor celda por el limite inferior de Wilson en DESARROLLO y solo
esa se mira en HOLDOUT. El resto de celdas del holdout se imprime para
transparencia, pero no se usa para decidir.

Uso:
    python scripts/lab_choque.py --payout 0.86
"""
from __future__ import annotations

import argparse
import sys
from itertools import product
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backtest_playbook import wilson, load        # noqa: E402
from bot.backtest.indicators import atr           # noqa: E402

DEV_FRACTION = 0.60


def market(asset: str) -> str:
    if asset.endswith("_N"):
        return "indices"
    if asset.startswith("XAU"):
        return "oro"
    return "forex"


def shock_trades(df: pd.DataFrame, thr: float, exp: int, wick: bool) -> pd.DataFrame:
    """Cada choque se opera en contra; entrada en la apertura siguiente."""
    a14 = atr(df, 14).shift(1)
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o) / a14
    rng = (h - l).replace(0, float("nan"))
    upper_wick = (h - c.where(c > o, o)) / rng
    lower_wick = (c.where(c < o, o) - l) / rng
    mask = body.abs() >= thr
    if wick:
        mask &= ((body > 0) & (upper_wick >= 0.25)) | ((body < 0) & (lower_wick >= 0.25))

    entry = o.shift(-1)
    exit_ = c.shift(-exp)
    times = df.index.to_series()
    contiguous = (times.shift(-exp) - times) == pd.Timedelta(minutes=exp)
    ok = mask & entry.notna() & exit_.notna() & contiguous & (entry != exit_)

    idx, last, keep = df.index[ok.fillna(False)], None, []
    for t in idx:                                  # sin solapes dentro del activo
        if last is None or t - last > pd.Timedelta(minutes=exp):
            keep.append(t)
            last = t
    win = ((exit_ < entry) & (body > 0)) | ((exit_ > entry) & (body < 0))
    return pd.DataFrame({"time": keep, "win": win[keep].to_numpy(),
                         "hour": [t.hour for t in keep]})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payout", type=float, default=0.86)
    args = ap.parse_args()
    be = 1 / (1 + args.payout)
    data = {a: d for a, d in load().items() if "-OTC" not in a}
    start = min(d.index[0] for d in data.values())
    end = max(d.index[-1] for d in data.values())
    split = start + (end - start) * DEV_FRACTION

    cells = {}
    for (thr, exp, wick), (a, df) in product(product((1.5, 2.0, 2.5, 3.0), (2, 3, 5), (False, True)),
                                             data.items()):
        t = shock_trades(df, thr, exp, wick)
        for mk in (market(a), "todos"):
            cells.setdefault((thr, exp, wick, mk), []).append(t)

    rows = []
    for k, parts in cells.items():
        t = pd.concat(parts)
        dev, hold = t[t.time < split], t[t.time >= split]
        if len(dev) < 300:
            continue
        rows.append((k, len(dev), dev.win.mean(), wilson(int(dev.win.sum()), len(dev))[0],
                     len(hold), hold.win.mean(), wilson(int(hold.win.sum()), max(len(hold), 1))))

    rows.sort(key=lambda r: -r[3])
    print("=" * 104)
    print(f"REVERSION TRAS CHOQUE | break-even {100 * be:.2f}% | elegido por cota inferior en DESARROLLO")
    print("=" * 104)
    print(f"{'umbral':>7}{'exp':>5}{'mecha':>7}{'mercado':>9}{'n_dev':>7}{'wr_dev':>8}{'lo_dev':>8}"
          f"{'n_hold':>8}{'wr_hold':>9}   IC95 holdout")
    for (thr, exp, wick, mk), nd, wd, lod, nh, wh, (loh, hih) in rows[:15]:
        print(f"{thr:>7}{exp:>4}m{'si' if wick else 'no':>7}{mk:>9}{nd:>7}{100 * wd:>7.1f}%"
              f"{100 * lod:>7.1f}%{nh:>8}{100 * wh:>8.1f}%   [{100 * loh:5.1f}%,{100 * hih:5.1f}%]")
    best = rows[0]
    (thr, exp, wick, mk), nd, wd, lod, nh, wh, (loh, hih) = best
    print("-" * 104)
    print(f"ELEGIDA EN DESARROLLO: choque >= {thr} ATR, {exp} min, mecha={'si' if wick else 'no'}, {mk}")
    print(f"  holdout: {100 * wh:.1f}% (n={nh}), IC95 [{100 * loh:.1f}%, {100 * hih:.1f}%] "
          f"-> {'SUPERA' if loh > be else 'no supera'} el break-even con seguridad")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
