# -*- coding: utf-8 -*-
"""
RS con confirmacion de reaccion: en vez de entrar al cierre de la vela de
senal, esperar a que el precio reaccione a favor y entrar ahi.

Variantes (M = velas de 15 s que se espera como maximo):
  base   entra al cierre de la vela de senal (RS v1.0)
  rompe  1a vela que cierra mas alla del extremo de la vela de senal
         (CALL: cierre > maximo de la senal; PUT: cierre < minimo)
  dos    dos cierres seguidos a favor (verde-verde / roja-roja)
  aleja  el precio ya se alejo >= 35% del rango desde el extremo tocado
         y la vela cierra a favor
  m1     la vela de 1 min que cierra despues de la senal es a favor
Desarrollo = primeros 2/3 de los dias, validacion = ultimo tercio.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from backtest_playbook import wilson                 # noqa: E402
from bot.backtest.rs import rs_signals               # noqa: E402
from lab_rs import load15, RULES_DAY                 # noqa: E402

M = 4
BE = 1 / 1.855


def confirm(df, sig, variant):
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    idx = df.index
    out = []
    for t in sig.index[sig["dir"] != ""]:
        i = idx.get_loc(t)
        d = sig.at[t, "dir"]; up = d == "call"
        s = 1 if up else -1
        e = None
        if variant == "base":
            e = i
        for k in range(i + 1, min(i + 1 + M, len(c))):
            if e is not None:
                break
            if idx[k] - idx[k - 1] != pd.Timedelta(seconds=15):
                break
            if variant == "rompe" and s * (c[k] - (h[i] if up else l[i])) > 0:
                e = k
            elif variant == "dos" and s * (c[k] - o[k]) > 0 and s * (c[k - 1] - o[k - 1]) > 0:
                e = k
            elif variant == "aleja":
                rng = sig.at[t, "rmax"] - sig.at[t, "rmin"]
                ext = l[i:k + 1].min() if up else h[i:k + 1].max()
                if rng > 0 and s * (c[k] - ext) >= 0.35 * rng and s * (c[k] - o[k]) > 0:
                    e = k
            elif variant == "m1" and (idx[k] + pd.Timedelta(seconds=15)).second == 0:
                st = k - 3
                if st >= 0 and s * (c[k] - o[st]) > 0:
                    e = k
                break_m1 = True
            # invalidacion: rompe el extremo de la senal en contra
            if e is None and s * ((l[k] if up else h[k]) - (l[i] if up else h[i])) < 0 and variant != "base":
                break
        if e is not None:
            out.append((idx[e], e, d, sig.at[t, "setup"], int(sig.at[t, "exp_min"])))
    return out


def run(df, ents, exp_override=None):
    idx, c = df.index, df["close"].to_numpy(float)
    rows, free = [], idx[0]
    for t, e, d, st, exp in ents:
        if t < free:
            continue
        exp = exp_override or exp
        j = e + exp * 4
        if j >= len(c) or idx[j] - t != pd.Timedelta(minutes=exp):
            continue
        r = "TIE" if c[j] == c[e] else ("WIN" if (c[j] > c[e]) == (d == "call") else "LOSS")
        rows.append((t, d, st, exp, r))
        free = (t + pd.Timedelta(seconds=15 + 60 * exp)).ceil("1min") + pd.Timedelta(seconds=45)
    return rows


def line(lbl, g):
    g = g[g.res != "TIE"]; n = len(g); w = int((g.res == "WIN").sum())
    if not n:
        return f"{lbl:<24} n=0"
    lo, hi = wilson(w, n)
    return f"{lbl:<24} n={n:>5} {100*w/n:5.1f}% [{100*lo:4.1f},{100*hi:4.1f}]" + (" *" if lo > BE else "")


data = load15()
sigs = {a: rs_signals(df) for a, df in data.items()}
allt = pd.concat([df.index.to_series() for df in data.values()])
cut = allt.min() + (allt.max() - allt.min()) * 2 / 3
print(f"datos {allt.min():%m-%d} -> {allt.max():%m-%d} | corte dev/val {cut:%m-%d %H:%M} | BE {100*BE:.1f}%")
for v in ("base", "rompe", "dos", "aleja", "m1"):
    for ex in (None, 1, 2, 3, 5):
        rows = []
        for a, df in data.items():
            rows += [(a,) + r for r in run(df, confirm(df, sigs[a], v), ex)]
        t = pd.DataFrame(rows, columns=["asset", "time", "dir", "setup", "exp", "res"])
        t = t[~((t.time >= RULES_DAY[0]) & (t.time < RULES_DAY[1]))]
        lbl = f"{v} exp={'RS' if ex is None else ex}"
        print(line(lbl + " dev", t[t.time < cut]), " | ", line("val", t[t.time >= cut]))
        if ex is None:
            for s, g in t.groupby("setup"):
                print("   ", line(f"setup {s} dev", g[g.time < cut]), " | ", line("val", g[g.time >= cut]))
