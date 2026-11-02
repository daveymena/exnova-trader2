# -*- coding: utf-8 -*-
"""
Azura Conteo v10 + filtros de contexto, medidos uno a uno y combinados.

Filtros (todos causales, calculados solo con velas ya cerradas):
  tendencia_m15  CALL solo si el cierre esta sobre la EMA50 de M15 (PUT bajo ella)
  vela_fuerte    cuerpo >= 60% del rango de la vela de la senal
  volatilidad    ATR14 entre 0.8x y 2x su mediana de las ultimas 500 velas
  sesion         13:00-17:00 UTC (solape Londres / Nueva York)
  espacio_sr     al menos 1 ATR libre hasta la resistencia (CALL) o soporte (PUT)
  contraria      operar en sentido OPUESTO a la flecha (prueba de reversion)
  todos          tendencia_m15 + vela_fuerte + volatilidad + espacio_sr

Se elige con el 70% antiguo y se juzga solo con el 30% reciente, con
intervalo de Wilson corregido por Bonferroni sobre todas las pruebas.

Uso:
    python scripts/azura_filters.py --payout 0.86
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from statistics import NormalDist

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backtest_playbook import wilson, load, OOS_FRACTION          # noqa: E402
from backtest_azura import resample                               # noqa: E402
from bot.backtest.azura import azura_signals, evaluate_bars       # noqa: E402
from bot.backtest.indicators import atr, ema                      # noqa: E402

MIN_OOS = 40


def context(df: pd.DataFrame, wing: int = 5) -> pd.DataFrame:
    """Variables de contexto en cada vela, sin informacion futura."""
    c, o, h, l = df["close"], df["open"], df["high"], df["low"]
    a = atr(df, 14)

    # EMA50 de M15 usando solo bloques de 15 min ya cerrados.
    m15 = c.resample("15min", label="right", closed="left").last().dropna()
    htf = ema(m15, 50).reindex(df.index, method="ffill").shift(1)

    # Pivotes confirmados `wing` velas despues de formarse.
    win = 2 * wing + 1
    res = h.where((h == h.rolling(win, center=True).max()).shift(wing, fill_value=False)).ffill()
    sup = l.where((l == l.rolling(win, center=True).min()).shift(wing, fill_value=False)).ffill()

    rng = (h - l).replace(0, float("nan"))
    vol = a / a.rolling(500, min_periods=100).median()
    return pd.DataFrame({
        "above_htf": c > htf, "below_htf": c < htf,
        "strong": ((c - o).abs() / rng) >= 0.6,
        "vol_ok": vol.between(0.8, 2.0),
        "session": df.index.hour.isin([13, 14, 15, 16]),
        "room_up": (res - c) >= a, "room_dn": (c - sup) >= a,
    }, index=df.index).fillna(False)


def filtered(sig: pd.DataFrame, ctx: pd.DataFrame, name: str) -> pd.DataFrame:
    call, put = sig["call"], sig["put"]
    if name == "sin_filtro":
        pass
    elif name == "tendencia_m15":
        call, put = call & ctx.above_htf, put & ctx.below_htf
    elif name == "vela_fuerte":
        call, put = call & ctx.strong, put & ctx.strong
    elif name == "volatilidad":
        call, put = call & ctx.vol_ok, put & ctx.vol_ok
    elif name == "sesion":
        call, put = call & ctx.session, put & ctx.session
    elif name == "espacio_sr":
        call, put = call & ctx.room_up, put & ctx.room_dn
    elif name == "contraria":
        call, put = sig["put"], sig["call"]
    elif name == "todos":
        base = ctx.strong & ctx.vol_ok
        call = call & ctx.above_htf & ctx.room_up & base
        put = put & ctx.below_htf & ctx.room_dn & base
    return pd.DataFrame({"call": call, "put": put}, index=sig.index)


FILTERS = ["sin_filtro", "tendencia_m15", "vela_fuerte", "volatilidad",
           "sesion", "espacio_sr", "contraria", "todos"]
SETUPS = [(60, 1), (60, 3), (300, 1), (300, 3)]      # (timeframe s, expiracion en velas)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payout", type=float, default=0.86)
    args = ap.parse_args()
    be = 1 / (1 + args.payout)
    data = load()

    markets = ("REAL", "SINTETICO")
    n_tests = len(FILTERS) * len(SETUPS) * len(markets)
    z = NormalDist().inv_cdf(1 - 0.05 / (2 * n_tests))

    acc: dict[tuple, list[int]] = {}
    for asset, raw in data.items():
        market = "SINTETICO" if "-OTC" in asset else "REAL"
        for tf in sorted({s[0] for s in SETUPS}):
            df = resample(raw, tf)
            sig, ctx = azura_signals(df), context(df)
            split = df.index[int(len(df) * (1 - OOS_FRACTION))]
            for name in FILTERS:
                fs = filtered(sig, ctx, name)
                for tf_, exp in SETUPS:
                    if tf_ != tf:
                        continue
                    res = evaluate_bars(df, fs, exp, tf)
                    ins, oos = res[res.entry_time < split], res[res.entry_time >= split]
                    k = (name, tf, exp, market)
                    a = acc.setdefault(k, [0, 0, 0, 0])
                    a[0] += len(ins); a[1] += int(ins.win.sum())
                    a[2] += len(oos); a[3] += int(oos.win.sum())

    print("=" * 104)
    print(f"AZURA + FILTROS | payout {args.payout} -> break-even {100 * be:.2f}% | "
          f"{n_tests} pruebas, IC Bonferroni")
    print("=" * 104)
    print(f"{'filtro':<15}{'tf':>4}{'exp':>6}{'mercado':>11}{'n_in':>7}{'wr_in':>8}"
          f"{'n_oos':>7}{'wr_oos':>8}   IC corregido")
    print("-" * 104)
    rows = []
    for (name, tf, exp, market), (ni, wi, no, wo) in acc.items():
        if no < MIN_OOS:
            continue
        lo, hi = wilson(wo, no, z)
        rows.append((name, tf, exp, market, ni, wi / max(ni, 1), no, wo / no, lo, hi))
    for r in sorted(rows, key=lambda r: -r[7]):
        name, tf, exp, market, ni, wri, no, wro, lo, hi = r
        mins = exp * tf // 60
        flag = "  <== EDGE" if lo > be else ("  (prometedor)" if wri > be and wro > be else "")
        print(f"{name:<15}{'M' + str(tf // 60):>4}{str(mins) + 'min':>6}{market:>11}{ni:>7}"
              f"{100 * wri:>7.1f}%{no:>7}{100 * wro:>7.1f}%   [{100 * lo:5.1f}%,{100 * hi:5.1f}%]{flag}")
    print("=" * 104)
    print("EDGE = la cota inferior corregida supera el break-even.")
    print("prometedor = por encima del break-even en ambos tramos, pero sin muestra suficiente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
