# -*- coding: utf-8 -*-
"""
¿Tiene ventaja entrar en el giro, antes de cruzar la EMA 20? Vela a favor en la zona
baja del rango (alta para PUT), sin pedir el lado de la EMA 20, con velas de 15 s de IQ.
Tambien muestra cuando llego cada operacion reciente a su mejor momento.
Solo lectura. Uso: python scripts/medir_giro.py
"""
from __future__ import annotations

import itertools
import os
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from iqoptionapi import constants as OP                          # noqa: E402
from backtest_playbook import wilson                             # noqa: E402
from bot.vision.ejemplos_usuario import H, _load                 # noqa: E402
from iq_probe import connect                                     # noqa: E402
from medir_vencimiento import fin_binaria                        # noqa: E402

BE = 1 / 1.85
UN = pd.Timedelta(seconds=15)


def base(df: pd.DataFrame) -> dict:
    cl, op, hi, lo = df["close"], df["open"], df["high"], df["low"]
    res, sop = hi.rolling(120).max().shift(1), lo.rolling(120).min().shift(1)
    rp, sp = hi.rolling(800).max().shift(1), lo.rolling(800).min().shift(1)
    b_c, b_p = lo.rolling(40).min(), hi.rolling(40).max()
    return {1: {"favor": cl > op, "prev": cl.shift() <= op.shift(), "pos": (cl - sop) / (res - sop),
                "av": (cl - b_c) / (res - b_c), "pano": (cl - sp) / (rp - sp)},
            -1: {"favor": cl < op, "prev": cl.shift() >= op.shift(), "pos": (res - cl) / (res - sop),
                 "av": (b_p - cl) / (b_p - sop), "pano": (rp - cl) / (rp - sp)}}


def medir(pos, av, pano) -> pd.DataFrame:
    out = []
    for fp in sorted(H.glob("*_15.parquet")):
        df = _load(fp.stem.rsplit("_", 1)[0])
        b = base(df)
        partes = []
        for d, x in b.items():
            m = x["favor"] & x["prev"] & (x["pos"] <= pos) & (x["av"] <= av) & (x["pano"] <= pano)
            partes.append(pd.DataFrame({"lado": d, "p": df["close"][m]}))
        s = pd.concat(partes).sort_index()
        keep, last = [], None
        for t in s.index:
            if last is None or (t - last).total_seconds() >= 240:
                keep.append(t)
                last = t
        s = s.loc[keep]
        s = s[~s.index.duplicated()]
        if s.empty:
            continue
        ent = s.index + pd.Timedelta(seconds=16)
        for e in (2, 3, 5):
            sal = df["close"].reindex(fin_binaria(ent, e) - UN).to_numpy()
            s[f"m{e}"] = np.sign(s["lado"].to_numpy() * (sal - s["p"].to_numpy()))
        out.append(s)
    return pd.concat(out).sort_index()


def busqueda() -> None:
    filas = []
    for pos, av, pano in itertools.product((.15, .25, .35), (.1, .2), (.3, 1.01)):
        t = medir(pos, av, pano)
        corte = t.index[len(t) // 2]
        for e in (2, 3, 5):
            r = t[f"m{e}"].dropna()
            r = r[r != 0]
            d, v = r[r.index < corte], r[r.index >= corte]
            filas.append({"pos30": pos, "avance": av, "pano": pano, "exp": e, "nd": len(d), "ad": (d > 0).mean(),
                          "nv": len(v), "gv": int((v > 0).sum()), "av": (v > 0).mean()})
    f = pd.DataFrame(filas)
    z = NormalDist().inv_cdf(1 - 0.05 / 2 / len(f))
    pd.set_option("display.width", 200)
    print(f"Giro: {len(f)} combinaciones. Mejores por la primera mitad:")
    print(f.sort_values("ad", ascending=False).head(6)[["pos30", "avance", "pano", "exp", "nd", "ad", "nv", "av"]].round(3).to_string(index=False))
    ok = [x for x in f[f.ad > BE].itertuples() if wilson(x.gv, x.nv, z)[0] > BE]
    print("Pasan con Bonferroni:", len(ok))


def recorridos(n: int) -> None:
    api = connect()
    nombres = {v: k for k, v in OP.ACTIVES.items()}
    _, h = api.get_position_history_v2("turbo-option", n, 0, 0, 0)
    filas = []
    for p in reversed(h.get("positions", [])):
        ev = p.get("raw_event", {})
        ini, fin = p["open_time"] / 1000, p["close_time"] / 1000
        asset = nombres.get(ev.get("active_id") or p.get("active_id"))
        d = 1 if str(ev.get("direction")).lower() == "call" else -1
        v = pd.DataFrame(api.get_candles(asset, 15, 60, fin + 30))
        v = v[(v["from"] + 15 > ini) & (v["from"] + 15 <= fin)]
        ent = ev.get("value") or p.get("open_underlying_price")
        if v.empty or not ent:
            continue
        ext = (v["max"] - ent) if d > 0 else (ent - v["min"])
        i = ext.idxmax()
        pico = int(v.loc[i, "from"] + 15 - ini)
        filas.append({"gano": p.get("close_reason") == "win", "fue_positiva": ext.max() > 0, "pico_s": pico, "dur": int(fin - ini)})
        print(f"  {pd.Timestamp(ini, unit='s'):%H:%M:%S} {asset} {p.get('close_reason')}: "
              f"mejor momento a los {pico} s de {int(fin - ini)} s, {100 * ext.max() / ent:+.3f} %")
    t = pd.DataFrame(filas)
    p = t[~t.gano]
    print(f"De {len(p)} perdidas, estuvieron a favor en algun momento: {int(p.fue_positiva.sum())}; "
          f"pico mediano a los {p.pico_s.median():.0f} s")


def main() -> int:
    recorridos(12)
    busqueda()
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
