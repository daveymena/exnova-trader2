# -*- coding: utf-8 -*-
"""
Observacion del usuario en vivo: Choque pierde cuando la flecha de Azura
apunta al contrario de la entrada (es decir, Azura confirma el choque).

Hipotesis unica, sin barrer parametros: separar las senales de Choque
(>= 3 ATR, 5 min, mercado real) segun Azura (hl2) haya marcado flecha en la
direccion DEL CHOQUE en la vela de choque o en las 2 anteriores. Mismo corte
desarrollo 60% / holdout 40% que scripts/lab_choque.py.

Uso:
    python scripts/lab_choque_azura.py --payout 0.86
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backtest_playbook import wilson, load        # noqa: E402
from bot.backtest.azura import azura_signals      # noqa: E402
from lab_choque import DEV_FRACTION, shock_trades  # noqa: E402

LOOKBACK = 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payout", type=float, default=0.86)
    args = ap.parse_args()
    be = 1 / (1 + args.payout)
    data = {a: d for a, d in load().items() if "-OTC" not in a}
    start = min(d.index[0] for d in data.values())
    end = max(d.index[-1] for d in data.values())
    split = start + (end - start) * DEV_FRACTION

    parts = []
    for a, df in data.items():
        t = shock_trades(df, 3.0, 5, False)
        if t.empty:
            continue
        az = azura_signals(df)
        # flecha de Azura a favor del choque en la vela de choque o las anteriores
        az_up = az["call"].astype(int).rolling(LOOKBACK).max().astype(bool)
        az_dn = az["put"].astype(int).rolling(LOOKBACK).max().astype(bool)
        body_up = (df["close"] > df["open"])[t.time].to_numpy()
        t["azura_confirma"] = (body_up & az_up[t.time].to_numpy()) | \
                              (~body_up & az_dn[t.time].to_numpy())
        parts.append(t)
    t = pd.concat(parts)
    # Segunda observacion en vivo: varios activos con choque a la vez (noticia)
    # perdieron juntos. Choque "en grupo" = otro activo con choque a <= 2 min.
    times = t.time.sort_values()
    t["en_grupo"] = [((times - x).abs() <= pd.Timedelta(minutes=2)).sum() > 1 for x in t.time]

    print("=" * 80)
    print(f"CHOQUE x AZURA | break-even {100 * be:.2f}%")
    print("=" * 80)
    for label, g in (("todas", t), ("Azura confirma el choque", t[t.azura_confirma]),
                     ("Azura NO confirma", t[~t.azura_confirma]),
                     ("choque en grupo", t[t.en_grupo]), ("choque aislado", t[~t.en_grupo])):
        for tramo, s in (("desarrollo", g[g.time < split]), ("holdout", g[g.time >= split])):
            n, w = len(s), int(s.win.sum())
            lo, hi = wilson(w, max(n, 1))
            print(f"{label:<26}{tramo:>11}  n={n:>5}  {100 * w / max(n, 1):5.1f}%  "
                  f"[{100 * lo:5.1f}%,{100 * hi:5.1f}%]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
