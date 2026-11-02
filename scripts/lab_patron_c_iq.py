# -*- coding: utf-8 -*-
"""
Setup C del detector EMA (C_CALL_piso_rango / A_PUT_techo_rango) en velas de
5 min con el vencimiento que de verdad pone IQ Option a una binaria de 15 min:
el cuarto de hora (:00/:15/:30/:45) mas cercano a 15 min y a mas de 5 min
(entrada :00 -> 15 min, :05 -> 10 min, :10 -> 20 min). Una operacion a la vez
por activo. Dev = 2/3 iniciales, val = ultimo tercio.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from backtest_playbook import wilson                  # noqa: E402
import lab_patron_ema as lab                          # noqa: E402  (acelera swings)
det = lab.det
BE = 1 / 1.85


def iq_expiry_min(entry: pd.Timestamp) -> int:
    best = None
    for m in range(6, 60):
        t = entry + pd.Timedelta(minutes=m)
        if t.minute % 15 == 0 and (best is None or abs(m - 15) < abs(best - 15)):
            best = m
    return best


rows = []
p = det.Params(rango_velas=20)
for f in sorted((ROOT / "bot" / "data" / "history").glob("*_60.parquet")):
    asset = f.stem.rsplit("_", 1)[0]
    df = pd.read_parquet(f)[["open", "high", "low", "close"]].astype(float)
    df = df[~df.index.duplicated()].sort_index()
    cut = df.index[0] + (df.index[-1] - df.index[0]) * 2 / 3
    close1 = df["close"]
    g = df.groupby(df.index.floor("300s"))
    n = g.size()
    d5 = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                       "close": g.close.last()})[n == 5]
    for seg in lab.segmentos(d5, 300):
        v = [dict(t=t, o=r.open, h=r.high, l=r.low, c=r.close) for t, r in zip(seg.index, seg.itertuples())]
        D = det.Detector(v, p)
        free = seg.index[0]
        for i in range(len(v)):
            s = D.senal(i)
            if not s or not s["setup"].startswith(("C_", "A_PUT_techo")):
                continue
            entry = seg.index[i] + pd.Timedelta(minutes=5)
            if entry < free:
                continue
            m = iq_expiry_min(entry)
            end = entry + pd.Timedelta(minutes=m)
            e0, e1 = entry - pd.Timedelta(minutes=1), end - pd.Timedelta(minutes=1)
            if e0 not in close1.index or e1 not in close1.index:
                continue
            a, b = close1[e0], close1[e1]
            res = "EMPATE" if a == b else ("GANADA" if (b > a) == (s["direccion"] == "CALL") else "PERDIDA")
            rows.append(dict(asset=asset, t=entry, setup=s["setup"], exp=m, res=res, val=entry >= cut))
            free = end + pd.Timedelta(minutes=5)
t = pd.DataFrame(rows)


def line(lbl, g):
    g = g[g.res != "EMPATE"]; k = len(g); w = int((g.res == "GANADA").sum())
    if not k:
        return f"{lbl:<26} n=0"
    lo, hi = wilson(w, k)
    return f"{lbl:<26} n={k:>4} {100*w/k:5.1f}% [{100*lo:4.1f},{100*hi:4.1f}]" + (" *" if lo > BE else "")


print(f"Setup C en velas 5m, vencimiento real IQ | {t.t.min():%m-%d} -> {t.t.max():%m-%d} | BE {100*BE:.1f}%")
for k, gg in t.groupby("setup"):
    print(line(f"{k} dev", gg[~gg.val]), "|", line("val", gg[gg.val]))
    for m, g2 in gg.groupby("exp"):
        print("   ", line(f"exp {m} min", g2))
otc = t.asset.str.contains("OTC")
c = t[t.setup.str.startswith("C_")]
print(line("C OTC", c[otc]), "|", line("C real", c[~otc]))
print(f"senales C por dia: {len(c) / max(1, (t.t.max() - t.t.min()).days):.1f}")
