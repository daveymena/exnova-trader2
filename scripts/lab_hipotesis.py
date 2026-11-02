# -*- coding: utf-8 -*-
"""
Laboratorio de hipotesis PRE-REGISTRADAS sobre mercado real (IQ Option).

Cada hipotesis se fijo ANTES de mirar resultados, con su fundamento. No se
barren parametros: cada una tiene una sola configuracion. Se mide en dos
tramos cronologicos:
  desarrollo  60% mas antiguo
  holdout     40% mas reciente  <- la unica cifra que decide
Intervalo de Wilson con Bonferroni sobre el numero de hipotesis.

H1 momentum_intradia   Gao, Han, Li y Zhou (2018) "Market intraday momentum",
                       JFE: el retorno desde el cierre anterior hasta las 10:00
                       ET predice el de la ultima media hora (15:30-16:00 ET)
                       en el S&P 500. Indices, 1 operacion/dia, 30 min.
H2 ruptura_apertura    Opening range breakout: rango de 9:30-9:45 ET; la primera
                       vela M1 que cierra fuera antes de las 11:00 ET marca la
                       direccion. Expiracion 15 min. Indices y forex.
H3 lead_lag_indices    El Nasdaq lidera: si USNDAQ100 se mueve >= 1 ATR en un
                       minuto y el otro indice < 0.25 ATR en la misma direccion,
                       operar el rezagado en la direccion del lider, 2 min.
H4 reversion_choque    Rebote de microestructura: vela M1 con cuerpo >= 2 ATR
                       (ATR de la vela anterior); operar en contra, 1 min.
                       Motivo: Azura al reves dio 51.6% a 1 min en mercado real.
H5 reversion_choque_3m Igual que H4 pero 3 min.

Uso:
    python scripts/lab_hipotesis.py --payout 0.86
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backtest_playbook import wilson, load        # noqa: E402
from bot.backtest.indicators import atr           # noqa: E402

DEV_FRACTION = 0.60
INDICES = ("USSPX500_N", "USNDAQ100_N", "US30_N")
NY = "America/New_York"


def ny(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = out.index.tz_localize("UTC").tz_convert(NY)
    return out


def trade(asset, t_entry, direction, df, exp_min):
    """Entrada a la apertura de t_entry, salida al cierre de la vela exp_min-1 despues."""
    t_exit = t_entry + pd.Timedelta(minutes=exp_min - 1)
    if t_entry not in df.index or t_exit not in df.index:
        return None
    e, x = df.at[t_entry, "open"], df.at[t_exit, "close"]
    if e == x:
        return None
    return {"asset": asset, "time": t_entry, "dir": direction,
            "win": (x > e) == (direction == "call")}


def h1_momentum_intradia(data):
    out = []
    for a in INDICES:
        if a not in data:
            continue
        df = ny(data[a])
        closes = df["close"]
        for day, g in df.groupby(df.index.date):
            if pd.Timestamp(day).weekday() >= 5:
                continue
            t10 = g.index[(g.index.hour == 9) & (g.index.minute == 59)]
            prev = df.index[(df.index < g.index[0].normalize()) &
                            (df.index.hour == 15) & (df.index.minute == 59)]
            if not len(t10) or not len(prev):
                continue
            r = closes[t10[0]] / closes[prev[-1]] - 1
            if r == 0:
                continue
            t_entry = g.index[0].normalize() + pd.Timedelta(hours=15, minutes=30)
            tr = trade(a, t_entry, "call" if r > 0 else "put", df, 30)
            if tr:
                out.append(tr)
    return out


def h2_ruptura_apertura(data):
    out = []
    for a, raw in data.items():
        if "-OTC" in a:
            continue
        df = ny(raw)
        for day, g in df.groupby(df.index.date):
            if pd.Timestamp(day).weekday() >= 5:
                continue
            base = g.index[0].normalize()
            rng = g[(g.index >= base + pd.Timedelta(hours=9, minutes=30)) &
                    (g.index < base + pd.Timedelta(hours=9, minutes=45))]
            if len(rng) < 15:
                continue
            hi, lo = rng["high"].max(), rng["low"].min()
            after = g[(g.index >= base + pd.Timedelta(hours=9, minutes=45)) &
                      (g.index < base + pd.Timedelta(hours=11))]
            brk = after[(after["close"] > hi) | (after["close"] < lo)]
            if brk.empty:
                continue
            t = brk.index[0]
            d = "call" if brk.iloc[0]["close"] > hi else "put"
            tr = trade(a, t + pd.Timedelta(minutes=1), d, df, 15)
            if tr:
                out.append(tr)
    return out


def h3_lead_lag(data):
    out = []
    lead = "USNDAQ100_N"
    if lead not in data:
        return out
    L = data[lead]
    la = atr(L, 14).shift(1)
    lret = (L["close"] - L["open"]) / la
    for f in ("USSPX500_N", "US30_N"):
        if f not in data:
            continue
        F = data[f]
        fret = (F["close"] - F["open"]) / atr(F, 14).shift(1)
        j = pd.concat({"l": lret, "f": fret}, axis=1).dropna()
        up = (j.l >= 1.0) & (j.f < 0.25)
        dn = (j.l <= -1.0) & (j.f > -0.25)
        last = None
        for t in j.index[up | dn]:
            if last is not None and t - last < pd.Timedelta(minutes=3):
                continue
            tr = trade(f, t + pd.Timedelta(minutes=1), "call" if up[t] else "put", F, 2)
            if tr:
                out.append(tr)
                last = t
    return out


def _shock(data, exp_min):
    out = []
    for a, df in data.items():
        if "-OTC" in a:
            continue
        a14 = atr(df, 14).shift(1)
        body = (df["close"] - df["open"]) / a14
        last = None
        for t in df.index[(body.abs() >= 2.0).fillna(False)]:
            if last is not None and t - last < pd.Timedelta(minutes=exp_min + 1):
                continue
            d = "put" if body[t] > 0 else "call"
            tr = trade(a, t + pd.Timedelta(minutes=1), d, df, exp_min)
            if tr:
                out.append(tr)
                last = t
    return out


HYPOTHESES = {
    "H1 momentum_intradia": h1_momentum_intradia,
    "H2 ruptura_apertura": h2_ruptura_apertura,
    "H3 lead_lag_indices": h3_lead_lag,
    "H4 reversion_choque_1m": lambda d: _shock(d, 1),
    "H5 reversion_choque_3m": lambda d: _shock(d, 3),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payout", type=float, default=0.86)
    args = ap.parse_args()
    be = 1 / (1 + args.payout)
    data = {a: d for a, d in load().items() if "-OTC" not in a}
    start = min(d.index[0] for d in data.values())
    end = max(d.index[-1] for d in data.values())
    split = (start + (end - start) * DEV_FRACTION).tz_localize("UTC").tz_convert(NY)
    z = NormalDist().inv_cdf(1 - 0.05 / (2 * len(HYPOTHESES)))

    print("=" * 100)
    print(f"HIPOTESIS PRE-REGISTRADAS | {len(data)} activos reales | {start} -> {end}")
    print(f"desarrollo < {split:%Y-%m-%d %H:%M} ET <= holdout | break-even {100 * be:.2f}% "
          f"| Bonferroni x{len(HYPOTHESES)}")
    print("=" * 100)
    print(f"{'hipotesis':<26}{'n_dev':>7}{'wr_dev':>8}{'n_hold':>8}{'wr_hold':>9}"
          f"   IC holdout corregido   veredicto")
    print("-" * 100)
    for name, fn in HYPOTHESES.items():
        t = pd.DataFrame(fn(data))
        if t.empty:
            print(f"{name:<26} sin operaciones")
            continue
        t["time"] = pd.to_datetime(t["time"], utc=True).dt.tz_convert(NY)
        dev, hold = t[t.time < split], t[t.time >= split]
        nd, wd = len(dev), int(dev.win.sum())
        nh, wh = len(hold), int(hold.win.sum())
        lo, hi = wilson(wh, nh, z)
        if nh < 100:
            v = "muestra insuficiente"
        elif lo > be:
            v = "EDGE"
        elif wd / max(nd, 1) > be and wh / nh > be:
            v = "prometedor (sobre BE en ambos tramos)"
        else:
            v = "sin ventaja"
        print(f"{name:<26}{nd:>7}{100 * wd / max(nd, 1):>7.1f}%{nh:>8}{100 * wh / max(nh, 1):>8.1f}%"
              f"   [{100 * lo:5.1f}%,{100 * hi:5.1f}%]   {v}")
        if name.startswith(("H1", "H2")) and nh:
            by = hold.groupby("asset").win.agg(["count", "mean"])
            print("      holdout por activo: " + ", ".join(
                f"{a} {100 * r['mean']:.0f}% (n={int(r['count'])})" for a, r in by.iterrows()))
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
