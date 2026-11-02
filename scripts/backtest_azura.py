# -*- coding: utf-8 -*-
"""
Backtest del indicador "Azura Conteo v10" sobre historico real de Exnova.

Responde tres preguntas:
  1. Los contadores G/P que pinta el script, son reales? (ACT vs SIG)
  2. Hay alguna combinacion timeframe / expiracion / fuente / mercado cuyo
     winrate fuera de muestra supere el break-even con intervalo corregido?
  3. Varia por hora del dia? (solo informativo, no se usa para elegir)

Uso:
    python scripts/fetch_history.py --assets USSPX500:N,US30:N,EURUSD-OTC --days 30 --timeframes 60
    python scripts/backtest_azura.py
    python scripts/backtest_azura.py --synthetic     # control: datos aleatorios
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

from backtest_playbook import wilson, load, HISTORY_DIR, OOS_FRACTION   # noqa: E402
from bot.backtest.azura import azura_signals, evaluate_bars, script_counters   # noqa: E402

MIN_OOS = 60
TIMEFRAMES = (60, 300)
SOURCES = ("hl2", "close")


def resample(df: pd.DataFrame, tf: int) -> pd.DataFrame:
    if tf == 60:
        return df
    rule = f"{tf // 60}min"
    out = df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"})
    # Solo velas completas: 5 minutos M1 presentes.
    full = df["close"].resample(rule, label="left", closed="left").count() == tf // 60
    return out[full].dropna()


def synthetic(n: int = 60_000, seed: int = 7) -> dict[str, pd.DataFrame]:
    """Paseo aleatorio puro: cualquier estrategia debe dar ~50%."""
    rng = np.random.default_rng(seed)
    out = {}
    for name in ("RANDOM_A-OTC", "RANDOM_B:N"):
        close = 100 * np.exp(np.cumsum(rng.normal(0, 3e-4, n)))
        open_ = np.r_[100, close[:-1]]
        spread = np.abs(rng.normal(0, 2e-4, n)) * close
        idx = pd.date_range("2026-01-01", periods=n, freq="min")
        out[name] = pd.DataFrame({
            "open": open_, "close": close,
            "high": np.maximum(open_, close) + spread,
            "low": np.minimum(open_, close) - spread}, index=idx)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payout", type=float, default=0.85)
    ap.add_argument("--expiries", default="1,2,3", help="en velas del timeframe")
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()

    breakeven = 1 / (1 + args.payout)
    expiries = [int(x) for x in args.expiries.split(",")]
    data = synthetic() if args.synthetic else load()
    if not data:
        print(f"No hay historico en {HISTORY_DIR}. Ejecuta primero scripts/fetch_history.py")
        return 1

    print("=" * 100)
    print("AZURA CONTEO v10 — BACKTEST SIN LOOK-AHEAD" + ("  [CONTROL SINTETICO]" if args.synthetic else ""))
    print("=" * 100)
    print(f"Payout {args.payout:.2f} -> break-even {100 * breakeven:.2f}%  |  activos: {len(data)}")
    for a, d in data.items():
        print(f"  {a:<22} {len(d):>7} velas M1  {d.index[0]} -> {d.index[-1]}")

    # 1. Contadores del script tal como los dibuja (M1, fuente por defecto).
    print("\n1) CONTADORES DEL SCRIPT (M1, HL2)")
    print(f"{'activo':<22}{'ACT G/P':>14}{'ACT %':>8}{'SIG G/P':>14}{'SIG %':>8}")
    for a, d in data.items():
        c = script_counters(d, azura_signals(d))
        na, ns = c["act_win"] + c["act_loss"], c["sig_win"] + c["sig_loss"]
        print(f"{a:<22}{c['act_win']:>7}/{c['act_loss']:<6}{100 * c['act_win'] / max(na, 1):>7.1f}%"
              f"{c['sig_win']:>7}/{c['sig_loss']:<6}{100 * c['sig_win'] / max(ns, 1):>7.1f}%")
    print("ACT usa la vela que genero la senal: no se puede operar. SIG es la cifra real.")

    # 2. Rejilla completa con correccion de Bonferroni.
    markets = ("SINTETICO", "REAL")
    n_tests = len(TIMEFRAMES) * len(SOURCES) * len(expiries) * len(markets)
    z_corr = NormalDist().inv_cdf(1 - 0.05 / (2 * n_tests))
    rows, hourly = [], []
    for tf in TIMEFRAMES:
        frames = {a: resample(d, tf) for a, d in data.items()}
        for src in SOURCES:
            sigs = {a: azura_signals(f, source=src) for a, f in frames.items()}
            for exp in expiries:
                for market in markets:
                    n_in = w_in = n_out = w_out = 0
                    for a, f in frames.items():
                        if ("-OTC" in a) != (market == "SINTETICO"):
                            continue
                        res = evaluate_bars(f, sigs[a], exp, tf)
                        if res.empty:
                            continue
                        split = f.index[int(len(f) * (1 - OOS_FRACTION))]
                        ins, oos = res[res.entry_time < split], res[res.entry_time >= split]
                        n_in += len(ins); w_in += int(ins["win"].sum())
                        n_out += len(oos); w_out += int(oos["win"].sum())
                        if tf == 60 and src == "hl2" and exp == 1:
                            hourly.append(res.assign(market=market))
                    if n_out < MIN_OOS:
                        continue
                    lo, hi = wilson(w_out, n_out, z_corr)
                    rows.append(dict(tf=tf, src=src, exp=exp, market=market,
                                     n_in=n_in, wr_in=w_in / max(n_in, 1),
                                     n_out=n_out, wr_out=w_out / n_out, lo=lo, hi=hi,
                                     edge=lo > breakeven))

    print(f"\n2) REJILLA ({n_tests} combinaciones, IC Bonferroni) — fuera de muestra = 30% mas reciente")
    print(f"{'tf':>4}{'fuente':>7}{'exp':>5}{'mercado':>11}{'n_in':>7}{'wr_in':>8}"
          f"{'n_oos':>7}{'wr_oos':>8}   IC corregido")
    print("-" * 100)
    for r in sorted(rows, key=lambda r: -r["wr_out"]):
        star = "  <== EDGE" if r["edge"] else ""
        print(f"{'M' + str(r['tf'] // 60):>4}{r['src']:>7}{r['exp']:>4}v{r['market']:>11}"
              f"{r['n_in']:>7}{100 * r['wr_in']:>7.1f}%{r['n_out']:>7}{100 * r['wr_out']:>7.1f}%"
              f"   [{100 * r['lo']:5.1f}%,{100 * r['hi']:5.1f}%]{star}")

    if hourly:
        h = pd.concat(hourly)
        print("\n3) POR HORA UTC (M1, HL2, 1 vela, todo el historico) — solo informativo")
        t = h.groupby(["market", "hour"])["win"].agg(["count", "mean"])
        t = t[t["count"] >= 30]
        for (m, hr), r in t.iterrows():
            print(f"  {m:<10} {hr:02d}h  n={int(r['count']):>5}  wr={100 * r['mean']:5.1f}%")

    print("=" * 100)
    winners = [r for r in rows if r["edge"]]
    if winners:
        print("CANDIDATOS PARA VALIDAR EN DEMO:")
        for r in winners:
            print(f"  M{r['tf'] // 60} {r['src']} exp={r['exp']} {r['market']}: "
                  f"{100 * r['wr_out']:.1f}% (n={r['n_out']})")
    else:
        print(f"NINGUNA combinacion supera el {100 * breakeven:.1f}% con intervalo corregido.")
    print("Sin latencia ni slippage del broker. Un resultado historico no garantiza el futuro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
