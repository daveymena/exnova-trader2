# -*- coding: utf-8 -*-
"""
Escenarios para el simulador de repeticion (reports/simulador_rs.html).

Toma momentos al azar de las velas de 15 s guardadas (fetch_history.py
--timeframes 15): 30 min de pasado visibles + 3 min de futuro tapado. Descarta
mercado cerrado (velas planas) y huecos. Excluye el 29 oct 21-24 h UTC-5, el
dia del que salieron las reglas RS.

Uso:
    python scripts/replay_data.py --n 240 --out reports/replay_data.json
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "bot" / "data" / "history"
PAST, FUT = 120, 12                     # velas de 15 s: 30 min / 3 min
NAMES = {"US30_N": "US 30", "USSPX500_N": "US 500", "USNDAQ100_N": "US 100",
         "GBPUSD-op": "GBP/USD", "EURUSD-op": "EUR/USD", "XAUUSD-op": "Oro",
         "OpenAI-OTC": "OpenAI (OTC)", "PENUSD-OTC": "PEN/USD (OTC)"}
EXCLUDE = (pd.Timestamp("2026-10-30 01:00"), pd.Timestamp("2026-10-30 05:00"))


def decimals(s: pd.Series) -> int:
    txt = s.head(500).map(lambda v: f"{v:.6f}".rstrip("0").split(".")[-1])
    return int(txt.str.len().max())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=240)
    ap.add_argument("--seed", type=int, default=29)
    ap.add_argument("--out", default=str(ROOT / "reports" / "replay_data.json"))
    args = ap.parse_args()
    rnd = random.Random(args.seed)

    pools = {}
    for f in sorted(HIST.glob("*_15.parquet")):
        key = f.stem[:-3]
        if key not in NAMES:
            continue
        df = pd.read_parquet(f)[["open", "high", "low", "close"]].astype(float)
        df = df[~df.index.duplicated()].sort_index()
        ts = df.index.to_series()
        contiguous = (ts.diff() == pd.Timedelta(seconds=15)).astype(int)
        # ventana valida: PAST+FUT velas seguidas sin huecos
        run = contiguous.groupby((contiguous == 0).cumsum()).cumsum()
        live = (df["high"] > df["low"]).astype(int).rolling(PAST + FUT).mean()
        ok = (run >= PAST + FUT - 1) & (live >= 0.8)
        ends = [i for i, flag in enumerate(ok.to_numpy()) if flag]
        pools[key] = (df, ends, decimals(df["close"]))

    per_asset = args.n // len(pools)
    scen = []
    for key, (df, ends, dec) in pools.items():
        picks, tries = [], 0
        while len(picks) < per_asset and tries < 20000:
            tries += 1
            end = rnd.choice(ends)                   # ultima vela del futuro
            t0 = df.index[end - FUT]                 # entrada al cierre de esta vela
            if EXCLUDE[0] <= t0 < EXCLUDE[1]:
                continue
            if any(abs(end - p) < PAST + FUT for p in picks):
                continue
            picks.append(end)
        for end in picks:
            w = df.iloc[end - PAST - FUT + 1: end + 1]
            entry_time = w.index[PAST - 1] + pd.Timedelta(seconds=15)
            scen.append({"asset": NAMES[key], "otc": "OTC" in key, "dec": dec,
                         "t": (entry_time - pd.Timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"),
                         "c": [[round(v, dec) for v in row] for row in w.to_numpy().tolist()]})
    rnd.shuffle(scen)
    for i, s in enumerate(scen):
        s["id"] = f"e{i:03d}"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(scen, separators=(",", ":")), encoding="utf-8")
    print(f"{len(scen)} escenarios -> {args.out} "
          f"({Path(args.out).stat().st_size / 1e6:.2f} MB) | {', '.join(NAMES[k] for k in pools)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
