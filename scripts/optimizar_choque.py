# -*- coding: utf-8 -*-
"""
Afinado de "Choque" sin enganarse: busqueda en rejilla sobre ENTRENAMIENTO
(60 % mas antiguo de cada serie), se eligen las 10 mejores por limite
inferior de Wilson, se comparan en VALIDACION (20 % siguiente) y solo la
ganadora de validacion se mide UNA vez en PRUEBA (20 % mas reciente).

Parametros: umbral de cuerpo (ATR), vencimiento, mecha de rechazo minima,
regimen de volatilidad, movimiento previo, mercado real/OTC.
Entrada en la apertura de la vela siguiente; una operacion a la vez por activo.
"""
from __future__ import annotations
import itertools, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from backtest_playbook import wilson   # noqa: E402
BE = 1 / 1.86


def prep(df):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    a = pd.Series(tr).rolling(14).mean().shift(1).to_numpy()
    body = (c - o) / a
    rng = h - l
    wick = np.where(c > o, h - np.maximum(o, c), np.minimum(o, c) - l)
    rech = np.divide(wick, rng, out=np.zeros_like(rng), where=rng > 0)
    vol = a / pd.Series(a).rolling(60).mean().to_numpy()
    prev = (np.r_[np.nan, c[:-1]] - np.r_[np.full(6, np.nan), o[:-6]]) / a
    ts = df.index.as_unit("s").asi8
    return dict(o=o, c=c, body=body, rech=rech, vol=vol, prev=prev, ts=ts, hour=df.index.hour.to_numpy())


def trades(P, thr, exp, rmin, volf, prevf):
    s = np.abs(P["body"]) >= thr
    s &= P["rech"] >= rmin
    if volf == "tranquilo":
        s &= P["vol"] < 1
    elif volf == "agitado":
        s &= P["vol"] >= 1
    sign = np.sign(P["body"])
    if prevf == "misma":        # choque al final de un movimiento en la misma direccion
        s &= np.sign(P["prev"]) == sign
    elif prevf == "contra":
        s &= np.sign(P["prev"]) == -sign
    ts, o, c = P["ts"], P["o"], P["c"]
    out, free = [], 0
    n = len(c)
    for i in np.flatnonzero(s):
        if ts[i] < free or i + exp >= n or ts[i + exp] - ts[i] != exp * 60:
            continue
        e, x = o[i + 1], c[i + exp]
        d = -sign[i]                     # en contra del choque
        r = 0 if x == e else (1 if d * (x - e) > 0 else -1)
        out.append((ts[i], r))
        free = ts[i] + (exp + 1) * 60
    return out


def stats(r):
    r = np.asarray([x for x in r if x != 0]); n = len(r)
    if n == 0:
        return 0, 0.0, 0.0
    w = int((r > 0).sum()); lo, _ = wilson(w, n)
    return n, w / n, lo


data = {}
for f in sorted((ROOT / "bot" / "data" / "history").glob("*_60.parquet")):
    df = pd.read_parquet(f)[["open", "high", "low", "close"]].astype(float)
    df = df[~df.index.duplicated()].sort_index()
    t0, t1 = df.index[0], df.index[-1]
    data[f.stem.rsplit("_", 1)[0]] = (prep(df), (t0 + (t1 - t0) * 0.6).timestamp(), (t0 + (t1 - t0) * 0.8).timestamp())

grid = list(itertools.product((2.0, 2.5, 3.0, 3.5, 4.0, 5.0), (2, 3, 5), (0.0, 0.15, 0.3),
                              ("todos", "tranquilo", "agitado"), ("todos", "misma", "contra"), ("real", "todos")))
res = []
for thr, exp, rmin, volf, prevf, mk in grid:
    parts = {"ent": [], "val": [], "pru": []}
    for a, (P, c1, c2) in data.items():
        if mk == "real" and "OTC" in a:
            continue
        for t, r in trades(P, thr, exp, rmin, volf, prevf):
            parts["ent" if t < c1 else "val" if t < c2 else "pru"].append(r)
    res.append(((thr, exp, rmin, volf, prevf, mk), {k: stats(v) for k, v in parts.items()}))

ok = [x for x in res if x[1]["ent"][0] >= 150]
ok.sort(key=lambda x: -x[1]["ent"][2])
print(f"{len(grid)} combinaciones | break-even {100*BE:.1f}% | top 10 por entrenamiento (limite inferior):")
fmt = lambda s: f"n={s[0]:>4} {100*s[1]:5.1f}% (min {100*s[2]:4.1f})"
for p, s in ok[:10]:
    print(f"  thr={p[0]} exp={p[1]} mecha>={p[2]} vol={p[3]:<9} previo={p[4]:<6} {p[5]:<5} | "
          f"ent {fmt(s['ent'])} | val {fmt(s['val'])}")
best = max(ok[:10], key=lambda x: x[1]["val"][1])
p, s = best
print(f"\nGANADORA en validacion: thr={p[0]} exp={p[1]} mecha>={p[2]} vol={p[3]} previo={p[4]} {p[5]}")
print(f"  PRUEBA final (datos nunca usados): {fmt(s['pru'])}  ->",
      "SUPERA break-even" if s["pru"][1] > BE else "no supera break-even")
base = next(x for x in res if x[0] == (3.0, 5, 0.0, "todos", "todos", "real"))[1]
print(f"  referencia Choque actual (3 ATR, 5 min, real): ent {fmt(base['ent'])} | val {fmt(base['val'])} | prueba {fmt(base['pru'])}")
