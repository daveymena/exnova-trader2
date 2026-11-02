# -*- coding: utf-8 -*-
"""
Prueba del detector "Retroceso a favor" (bot/backtest/detector_rs_patron.py,
paquete bot_rs_patron_paquete del 1 nov) con velas reales de IQ Option.

El detector se usa tal cual; solo se acelera `swings` (precalculado una vez
por serie, mismo resultado). Vencimiento 3 min, entrada en la apertura de la
vela siguiente, enfriamiento y bloqueo de giro del propio backtest.
Desarrollo = primeros 2/3 de cada serie, validacion = ultimo tercio.

Uso: python scripts/lab_patron_ema.py [--tf 60|15] [--rango N]
"""
from __future__ import annotations
import argparse, bisect, sys
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from backtest_playbook import wilson                  # noqa: E402
import bot.backtest.detector_rs_patron as det         # noqa: E402

_orig, _cache = det.swings, {}


def fast_swings(velas, k, hasta):
    key = (id(velas), k)
    if key not in _cache:
        _cache.clear()
        _cache[key] = _orig(velas, k, len(velas))       # todos los swings
    a, b = _cache[key]
    lim = hasta - k                                     # el original usa i < hasta - k
    return a[:bisect.bisect_left(a, lim)], b[:bisect.bisect_left(b, lim)]


det.swings = fast_swings


def segmentos(df, tf):
    """Cortes en huecos de datos para no mezclar sesiones."""
    gap = df.index.to_series().diff() > pd.Timedelta(seconds=tf * 5)
    for _, g in df.groupby(gap.cumsum()):
        if len(g) > 400:
            yield g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", type=int, default=60)
    ap.add_argument("--rango", type=int, default=None)
    ap.add_argument("--src", type=int, default=None, help="tf del archivo base a reagrupar (p. ej. 60 para velas de 5/15/30 min)")
    ap.add_argument("--venc", type=int, default=None, help="vencimiento en velas (defecto: 3 min)")
    ap.add_argument("--payout", type=float, default=0.85)
    ap.add_argument("--assets", default="", help="lista separada por comas (vacio = todos)")
    a = ap.parse_args()
    src = a.src or a.tf
    venc = a.venc or max(1, 180 // a.tf)
    rango = a.rango or (5 if a.tf == 60 else 20)
    p = det.Params(vencimiento_velas=venc, rango_velas=rango, payout=a.payout,
                   enfriamiento_velas=max(1, 60 // a.tf), bloqueo_giro_velas=max(2, 120 // a.tf))
    be = 1 / (1 + a.payout)
    rows = []
    for f in sorted((ROOT / "bot" / "data" / "history").glob(f"*_{src}.parquet")):
        asset = f.stem.rsplit("_", 1)[0]
        if a.assets and asset not in a.assets.split(","):
            continue
        df = pd.read_parquet(f)[["open", "high", "low", "close"]].astype(float)
        df = df[~df.index.duplicated()].sort_index()
        if src != a.tf:
            g = df.groupby(df.index.floor(f"{a.tf}s"))
            n = g.size()
            df = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                               "close": g.close.last()})[n == a.tf // src]
        cut = df.index[0] + (df.index[-1] - df.index[0]) * 2 / 3
        for g in segmentos(df, a.tf):
            velas = [dict(t=t, o=r.open, h=r.high, l=r.low, c=r.close) for t, r in zip(g.index, g.itertuples())]
            r = det.backtest(velas, p)
            for o in r["operaciones"]:
                rows.append(dict(asset=asset, t=o["t_entrada"], setup=o["setup"], dir=o["direccion"],
                                 res=o["resultado"], val=o["t_entrada"] >= cut))
        print(f"  {asset}: {sum(x['asset'] == asset for x in rows)} ops", flush=True)
    t = pd.DataFrame(rows)
    out = ROOT / "reports" / f"lab_patron_ema_{a.tf}_v{venc}.csv"
    t.to_csv(out, index=False)

    def line(lbl, g):
        g = g[g.res != "EMPATE"]; n = len(g); w = int((g.res == "GANADA").sum())
        if not n:
            return f"{lbl:<30} n=0"
        lo, hi = wilson(w, n)
        return f"{lbl:<30} n={n:>5} {100*w/n:5.1f}% [{100*lo:4.1f},{100*hi:4.1f}]" + (" *" if lo > be else "")
    print(f"\nPATRON EMA 20/50/200 | velas {a.tf}s | venc {venc} velas ({venc * a.tf // 60} min) | rango {rango} velas | BE {100*be:.1f}%")
    print(line("desarrollo", t[~t.val]), "|", line("validacion", t[t.val]))
    for k, g in t.groupby("setup"):
        print(line(f"  {k} dev", g[~g.val]), "|", line("val", g[g.val]))
    otc = t.asset.str.contains("OTC")
    print(line("  OTC", t[otc]), "|", line("real", t[~otc]))
    for k, g in t.groupby("asset"):
        print(line(f"  {k}", g))


if __name__ == "__main__":
    main()
