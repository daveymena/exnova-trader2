# -*- coding: utf-8 -*-
"""
Prueba historica de la estrategia "Rechazo y Soporte" (bot/backtest/rs.py)
con velas de 15 s de IQ Option (scripts/fetch_history.py --timeframes 15).

1. Concordancia: para cada opcion real del 29 oct (CSV del paquete) dice si
   el detector daba senal en ese activo y direccion a +-30 s de la compra.
2. Backtest: una operacion a la vez por activo, entrada al cierre de la vela
   de senal, salida al cierre de la vela de vencimiento; F5 (enfriamiento:
   esperar a que cierre una vela de 1 min nueva tras el vencimiento).
   El dia 29-30 oct UTC (de donde salieron las reglas) se reporta aparte.

Uso:
    python scripts/lab_rs.py --trades ruta/operaciones_29oct_detalle.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backtest_playbook import wilson                # noqa: E402
from bot.backtest.rs import rs_signals              # noqa: E402

HIST = ROOT / "bot" / "data" / "history"
CSV_ASSET = {"US 30": "US30_N", "OpenAI (OTC)": "OpenAI-OTC", "GBP/USD": "GBPUSD-op",
             "US 500": "USSPX500_N", "PEN/USD (OTC)": "PENUSD-OTC"}
RULES_DAY = (pd.Timestamp("2026-10-30 01:00"), pd.Timestamp("2026-10-30 05:00"))


def load15() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted(HIST.glob("*_15.parquet")):
        df = pd.read_parquet(f)[["open", "high", "low", "close"]].astype(float)
        out[f.stem[:-3]] = df[~df.index.duplicated()].sort_index()
    return out


def trades(df: pd.DataFrame, sig: pd.DataFrame) -> pd.DataFrame:
    idx = df.index
    close = df["close"].to_numpy()
    pos_of = {t: i for i, t in enumerate(idx)}
    rows, free_from = [], idx[0]
    for t in sig.index[sig["dir"] != ""]:
        if t < free_from:
            continue
        i = pos_of[t]
        exp = int(sig.at[t, "exp_min"])
        j = i + exp * 4
        if j >= len(idx) or idx[j] - t != pd.Timedelta(minutes=exp):
            continue
        entry, exit_ = close[i], close[j]
        d = sig.at[t, "dir"]
        res = "TIE" if exit_ == entry else ("WIN" if (exit_ > entry) == (d == "call") else "LOSS")
        rows.append((t, d, sig.at[t, "setup"], exp, round(sig.at[t, "pos"], 2), res))
        expiry_end = t + pd.Timedelta(seconds=15) + pd.Timedelta(minutes=exp)
        free_from = expiry_end.ceil("1min") + pd.Timedelta(seconds=45)   # F5
    return pd.DataFrame(rows, columns=["time", "dir", "setup", "exp", "pos", "res"])


def summary(t: pd.DataFrame, label: str, be: float) -> None:
    d = t[t.res != "TIE"]
    n, w = len(d), int((d.res == "WIN").sum())
    if n == 0:
        print(f"  {label:<34} n=0")
        return
    lo, hi = wilson(w, n)
    flag = "  <-- IC sobre break-even" if lo > be else ""
    print(f"  {label:<34} n={n:>5}  {100 * w / n:5.1f}%  IC95 [{100 * lo:4.1f}, {100 * hi:4.1f}]"
          f"  empates={int((t.res == 'TIE').sum())}{flag}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", help="operaciones_29oct_detalle.csv del paquete")
    ap.add_argument("--payout", type=float, default=0.855)
    ap.add_argument("--out", default=str(ROOT / "reports" / "lab_rs_trades.csv"))
    args = ap.parse_args()
    be = 1 / (1 + args.payout)

    data = load15()
    sigs = {a: rs_signals(df) for a, df in data.items()}

    if args.trades:
        real = pd.read_csv(args.trades)
        print("=" * 90)
        print("CONCORDANCIA con las opciones reales del 29 oct (senal del detector a +-30 s)")
        print("=" * 90)
        hits = {}
        for _, r in real.iterrows():
            a = CSV_ASSET.get(r["activo"])
            if a not in sigs:
                continue
            t = pd.Timestamp(f"{r['fecha']} {str(r['hora_compra'])[:8]}") + pd.Timedelta(hours=5)
            s = sigs[a]
            win = s.loc[t - pd.Timedelta(seconds=30): t + pd.Timedelta(seconds=30)]
            match = win[win["dir"] == r["direccion"].lower()]
            got = ",".join(sorted(set(match["setup"]))) or "-"
            key = r["familia_setup"]
            hits.setdefault(key, [0, 0])
            hits[key][0] += got != "-"
            hits[key][1] += 1
            print(f"  {r['grupo_historial']:<4} {r['activo']:<14} {r['direccion']:<4} {r['resultado']:<8}"
                  f" {r['setup_entrada']:<28} detector={got}")
        for k, (h, n) in hits.items():
            print(f"  {k:<20} el detector senala {h}/{n}")

    allt = []
    for a, df in data.items():
        t = trades(df, sigs[a])
        t["asset"] = a
        allt.append(t)
    t = pd.concat(allt, ignore_index=True)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    t.to_csv(args.out, index=False)
    t["otc"] = t.asset.str.contains("OTC")
    t["hour"] = t.time.dt.hour
    in_rules = (t.time >= RULES_DAY[0]) & (t.time < RULES_DAY[1])
    oos = t[~in_rules]
    sess = oos[oos.hour.isin([2, 3, 4])]

    print("\n" + "=" * 90)
    print(f"BACKTEST RS v1.0 | {t.time.min():%Y-%m-%d} -> {t.time.max():%Y-%m-%d} | "
          f"break-even {100 * be:.1f}% (payout {100 * args.payout:.1f}%)")
    print("=" * 90)
    summary(t[in_rules], "dia de las reglas (29 oct 21-24h)", be)
    summary(oos, "resto, todas las horas", be)
    summary(sess, "resto, horario 21-24h UTC-5", be)
    for name, g in (("mercado real", oos[~oos.otc]), ("OTC", oos[oos.otc])):
        summary(g, f"resto, {name}", be)
    print("  por setup (resto):")
    for k, g in oos.groupby("setup"):
        summary(g, f"    setup {k}", be)
    print("  por activo (resto):")
    for k, g in oos.groupby("asset"):
        summary(g, f"    {k}", be)
    print("  por vencimiento (resto):")
    for k, g in oos.groupby("exp"):
        summary(g, f"    {k} min", be)
    days = max((oos.time.max() - oos.time.min()).days, 1)
    print(f"\n  senales/dia (resto, 1 a la vez por activo): {len(oos) / days:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
