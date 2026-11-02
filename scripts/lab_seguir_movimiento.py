# -*- coding: utf-8 -*-
"""
"Veo el movimiento de subida o bajada ya avanzado y entro a favor":
senal cuando el precio ya se movio >= X ATR en las ultimas N velas, con las
EMAs 20/50 ordenadas a favor y la ultima vela cerrando a favor. Entrada al
cierre de esa vela, vencimiento fijo. Una operacion a la vez por activo.
Dev = 2/3 iniciales de cada serie, val = ultimo tercio.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from backtest_playbook import wilson   # noqa: E402
BE = 1 / 1.85
H = ROOT / "bot" / "data" / "history"


def series(tf):
    src = 15 if tf < 60 else 60
    for f in sorted(H.glob(f"*_{src}.parquet")):
        df = pd.read_parquet(f)[["open", "high", "low", "close"]].astype(float)
        df = df[~df.index.duplicated()].sort_index()
        if tf != src:
            g = df.groupby(df.index.floor(f"{tf}s")); n = g.size()
            df = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                               "close": g.close.last()})[n == tf // src]
        yield f.stem.rsplit("_", 1)[0], df


def run(df, tf, N, X, exp_min):
    c, o, h, l = (df[k].to_numpy() for k in ("close", "open", "high", "low"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = pd.Series(tr).ewm(alpha=1 / 14).mean().to_numpy()
    e20 = pd.Series(c).ewm(span=20, adjust=False).mean().to_numpy()
    e50 = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()
    mv = (c - np.r_[np.full(N, np.nan), c[:-N]]) / atr
    up = (mv >= X) & (e20 > e50) & (c > o)
    dn = (mv <= -X) & (e20 < e50) & (c < o)
    ts = df.index.as_unit("s").asi8
    k = exp_min * 60 // tf
    pos = {t: i for i, t in enumerate(ts)}
    out, free = [], 0
    for i in np.flatnonzero(up | dn):
        if i < 200 or ts[i] < free:
            continue
        j = pos.get(ts[i] + exp_min * 60)
        if j is None:
            continue
        d = 1 if up[i] else -1
        r = 0 if c[j] == c[i] else (1 if d * (c[j] - c[i]) > 0 else -1)
        out.append((ts[i], r))
        free = ts[i] + exp_min * 60 + tf
    return out


def line(lbl, r):
    r = r[r != 0]; n = len(r); w = int((r > 0).sum())
    if not n:
        return f"{lbl:<6} n=0"
    lo, hi = wilson(w, n)
    return f"{lbl:<4} n={n:>5} {100*w/n:5.1f}% [{100*lo:4.1f},{100*hi:4.1f}]" + (" *" if lo > BE else "  ")


combos = 0
for tf in (15, 60, 300):
    data = list(series(tf))
    for N in (5, 10, 20):
        for X in (1.0, 2.0, 3.0):
            for exp in ((5, 10, 15) if tf == 300 else (2, 3, 5)):
                dev, val = [], []
                for a, df in data:
                    cut = df.index[0] + (df.index[-1] - df.index[0]) * 2 / 3
                    for t, r in run(df, tf, N, X, exp):
                        (val if pd.Timestamp(t, unit="s") >= cut else dev).append(r)
                combos += 1
                print(f"velas {tf:>3}s N={N:>2} mov>={X} ATR exp={exp}m | "
                      f"{line('dev', np.array(dev))} | {line('val', np.array(val))}", flush=True)
print(f"{combos} combinaciones probadas")
