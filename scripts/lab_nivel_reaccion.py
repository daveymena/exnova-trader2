# -*- coding: utf-8 -*-
"""
Reaccion en niveles mayores: nivel = maximo/minimo de las ultimas L velas de
1 min tocado 2+ veces (zona +-10% del rango). Senal cuando una vela de 15 s
perfora o toca el nivel y cierra de vuelta dentro con mecha >= 1.5 cuerpos
(rechazo); variante 'conf': ademas la vela siguiente cierra a favor.
Se opera en contra del toque (rebote). Dev = 2/3 iniciales, val = ultimo 1/3.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from backtest_playbook import wilson                 # noqa: E402
from lab_rs import load15, RULES_DAY                 # noqa: E402
BE = 1 / 1.855


def signals(df, L, conf):
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    W = L * 4
    hi = pd.Series(h).rolling(W).max().shift(1).to_numpy()
    lo = pd.Series(l).rolling(W).min().shift(1).to_numpy()
    rng = hi - lo
    body = np.maximum(np.abs(c - o), 1e-12)
    out = []
    for t in range(W + 1, len(c) - 1):
        r = rng[t]
        if not r > 0:
            continue
        tol = 0.10 * r
        seg_h, seg_l = h[t - W:t], l[t - W:t]
        d = None
        if h[t] >= hi[t] - tol and c[t] < hi[t] and h[t] - max(o[t], c[t]) >= 1.5 * body[t]:
            th = seg_h >= hi[t] - tol
            if int(th[0]) + int(np.sum(th[1:] & ~th[:-1])) >= 2:
                d = "put"
        elif l[t] <= lo[t] + tol and c[t] > lo[t] and min(o[t], c[t]) - l[t] >= 1.5 * body[t]:
            tl = seg_l <= lo[t] + tol
            if int(tl[0]) + int(np.sum(tl[1:] & ~tl[:-1])) >= 2:
                d = "call"
        if d is None:
            continue
        e = t
        if conf:
            s = 1 if d == "call" else -1
            if s * (c[t + 1] - o[t + 1]) <= 0:
                continue
            e = t + 1
        out.append((e, d))
    return out


def run(df, ents, exp):
    idx, c = df.index, df["close"].to_numpy(float)
    rows, free = [], idx[0]
    for e, d in ents:
        t = idx[e]
        if t < free:
            continue
        j = e + exp * 4
        if j >= len(c) or idx[j] - t != pd.Timedelta(minutes=exp):
            continue
        rows.append((t, "TIE" if c[j] == c[e] else ("WIN" if (c[j] > c[e]) == (d == "call") else "LOSS")))
        free = (t + pd.Timedelta(seconds=15 + 60 * exp)).ceil("1min") + pd.Timedelta(seconds=45)
    return rows


def line(lbl, g):
    g = g[g.res != "TIE"]; n = len(g); w = int((g.res == "WIN").sum())
    if not n:
        return f"{lbl:<26} n=0"
    lo, hi = wilson(w, n)
    return f"{lbl:<26} n={n:>5} {100*w/n:5.1f}% [{100*lo:4.1f},{100*hi:4.1f}]" + (" *" if lo > BE else "")


data = load15()
allt = pd.concat([df.index.to_series() for df in data.values()])
cut = allt.min() + (allt.max() - allt.min()) * 2 / 3
for L in (15, 30, 60):
    for conf in (False, True):
        for exp in (1, 2, 3, 5):
            rows = []
            for a, df in data.items():
                rows += [(a,) + r for r in run(df, signals(df, L, conf), exp)]
            t = pd.DataFrame(rows, columns=["asset", "time", "res"])
            t = t[~((t.time >= RULES_DAY[0]) & (t.time < RULES_DAY[1]))]
            lbl = f"L={L}m {'conf' if conf else 'mecha'} exp={exp}"
            print(line(lbl + " dev", t[t.time < cut]), " | ", line("val", t[t.time >= cut]))
