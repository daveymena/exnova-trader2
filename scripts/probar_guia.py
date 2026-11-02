# -*- coding: utf-8 -*-
"""
Prueba la guia del usuario (bot/backtest/regla_guia.py):
  1. contra sus 64 operaciones reales: que mide cada regla en ganadas y perdidas,
     y cuantas de sus entradas dispararia la regla;
  2. contra el historial de 15 s de IQ: acierto a 2 min de todas las senales,
     con mitad dev / mitad val para no engañarnos.

Uso: python scripts/probar_guia.py
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from backtest_playbook import wilson                       # noqa: E402
from bot.backtest import regla_guia as rg                  # noqa: E402
from graficos_operaciones import MAP                       # noqa: E402

H = ROOT / "bot" / "data" / "history"
BE = 1 / 1.85


def load(a):
    df = pd.read_parquet(H / f"{a}_15.parquet")[["open", "high", "low", "close"]].astype(float)
    return df[~df.index.duplicated()].sort_index()


def sus_operaciones():
    data = json.load(open(ROOT / "reports" / "graficos_rs_data.json", encoding="utf-8"))["trades"]
    filas, cache = [], {}
    for t in data:
        a = MAP[t["asset"]]
        if a not in cache:
            cache[a] = load(a)
        df = cache[a]
        ent = pd.Timestamp(t["entry_ts"], unit="s")
        c = df[df.index + pd.Timedelta(seconds=15) <= ent].iloc[-400:]
        f = rg.features(c, t["p_in"])
        if f is None:
            continue
        d = 1 if t["dir"] == "CALL" else -1
        filas.append({"id": t["id"], "res": t["res"], "a_favor_e20": f["lado"] == d,
                      "dist_atr": f["dist_atr"], "dist_1m": f["dist_1m"],
                      "impulso_a_favor": f["cuerpo_atr"] if f["ult_dir"] == d else 0.0,
                      "retroceso_atr": f["low3_e20_atr"] if d > 0 else -f["high3_e20_atr"],
                      "lado_e50_ok": f["sobre_e50"] == d,
                      "gatillo": f["rompe_max"] if d > 0 else f["rompe_min"],
                      "regla": rg.decidir(f) == t["dir"], "_f": f, "_d": t["dir"]})
    return pd.DataFrame(filas)


def historial(p, datos):
    out = []
    for a, (df, f) in datos.items():
        s = rg.senales(f, p)
        fut = df["close"].shift(-8)                              # 2 min = 8 velas de 15 s
        ok = (fut.index.to_series().shift(-8) - fut.index.to_series()).dt.total_seconds() == 120
        r = pd.DataFrame({"s": s, "g": (s * (fut - df["close"])) > 0,
                          "e": fut == df["close"]})[(s != 0) & ok]
        r = r[~r["e"]]
        # una sola entrada por activo cada 2 min (como un humano, sin apilar)
        keep, last = [], None
        for t in r.index:
            if last is None or (t - last).total_seconds() >= 120:
                keep.append(t)
                last = t
        r = r.loc[keep]
        r["mitad"] = (r.index > df.index[len(df) // 2])
        r["activo"] = a
        out.append(r)
    return pd.concat(out)


def main():
    t = sus_operaciones()
    t = t[t.res.isin(["GANADA", "PERDIDA"])]
    pd.set_option("display.width", 200)
    print(f"Tus operaciones con resultado: {len(t)}")
    print("\nMedias por resultado (que separa ganadas de perdidas):")
    print(t.groupby("res")[["dist_atr", "dist_1m", "impulso_a_favor", "retroceso_atr"]].median().round(3))
    for col in ("a_favor_e20", "lado_e50_ok", "gatillo"):
        g = t.groupby(col)["res"].apply(lambda s: f"{(s == 'GANADA').sum()}/{len(s)}")
        print(f"  {col}: {dict(g)}")
    print(f"\nLa regla (valores por defecto) dispara en {int(t.regla.sum())} de {len(t)} de tus entradas, "
          f"ganadas {int(((t.regla) & (t.res == 'GANADA')).sum())}")

    datos = {}
    for fp in sorted(H.glob("*_15.parquet")):
        a = fp.stem.rsplit("_", 1)[0]
        df = load(a)
        datos[a] = (df, rg.features_series(df))
    print(f"\nHistorial 15 s: {len(datos)} activos, "
          f"{sum(len(d) for d, _ in datos.values())} velas")
    res = []
    for md, m1, k, to in itertools.product((1.0, 1.5, 2.5), (0.01, 0.03, 1.0), (1.0, 1.5, 99), (0.0, 0.3, 0.6)):
        p = rg.P(max_dist_atr=md, max_dist_1m=m1, k_impulso=k, toque=to)
        r = historial(p, datos)
        dev, val = r[~r.mitad], r[r.mitad]
        res.append((md, m1, k, to, len(dev), dev.g.mean(), len(val), val.g.mean(), p))
    tab = pd.DataFrame(res, columns=["dist_atr", "dist_1m", "k_imp", "toque", "n_dev", "acc_dev", "n_val", "acc_val", "p"])
    print(tab.drop(columns="p").sort_values("acc_dev", ascending=False).head(12).round(3).to_string(index=False))
    base = historial(rg.P(), datos)
    g, n = int(base.g.sum()), len(base)
    lo, hi = wilson(g, n)
    print(f"\nRegla con valores por defecto: {g}/{n} = {100 * g / n:.1f} %  IC95 [{100 * lo:.1f}, {100 * hi:.1f}] "
          f"(hace falta > {100 * BE:.1f} %)")
    print(base.groupby("activo").g.agg(["mean", "count"]).round(3).to_string())
    mejor = tab.sort_values("acc_dev", ascending=False).iloc[0]
    print(f"\nMejor en dev: {mejor.acc_dev:.3f} (n {mejor.n_dev}) -> en val {mejor.acc_val:.3f} (n {mejor.n_val})")


if __name__ == "__main__":
    main()
