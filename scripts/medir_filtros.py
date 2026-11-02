# -*- coding: utf-8 -*-
"""
Efecto de los filtros candidatos (zona alta de la panoramica y lateral) en las senales del
historial de IQ y en las entradas del usuario. Solo lectura. Uso: python scripts/medir_filtros.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from backtest_playbook import wilson                             # noqa: E402
from bot.backtest.confirmacion import tendencia_1m               # noqa: E402
from bot.vision.ejemplos_usuario import H, _load, casos          # noqa: E402
from gemma_live import direccion_guia, lugar_ok                  # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402
from medir_vencimiento import fin_binaria, senales               # noqa: E402

EXP = 2


def cruces(df: pd.DataFrame) -> pd.Series:
    cl = df["close"]
    return ((cl - cl.ewm(span=20, adjust=False).mean()) > 0).astype(int).diff().abs().rolling(40).sum()


def texto(x: pd.Series) -> str:
    x = x[x != 0].dropna()
    g, n = int((x > 0).sum()), len(x)
    lo, hi = wilson(g, n) if n else (0, 0)
    return f"{100 * g / max(n, 1):.1f}% [{100 * lo:.1f}-{100 * hi:.1f}] n={n}"


def main() -> int:
    out = []
    for fp in sorted(H.glob("*_15.parquet")):
        df = _load(fp.stem.rsplit("_", 1)[0])
        s = senales(df, "confirma", comienzo=True, tendencia=True)
        if s.empty:
            continue
        m1 = df["close"].resample("1min").last().dropna()
        hi, lo = m1.rolling(200).max().shift(1).reindex(df.index, method="ffill"), m1.rolling(200).min().shift(1).reindex(df.index, method="ffill")
        p = (df["close"] - lo) / (hi - lo)
        s["pos3h"] = p.reindex(s.index).where(s["lado"] > 0, 1 - p.reindex(s.index))
        s["cruces"] = cruces(df).reindex(s.index)
        fin = fin_binaria(s.index + pd.Timedelta(seconds=16), EXP) - pd.Timedelta(seconds=15)
        s["r"] = np.sign(s["lado"].to_numpy() * (df["close"].reindex(fin).to_numpy() - s["p"].to_numpy()))
        out.append(s)
    t = pd.concat(out).sort_index().dropna(subset=["pos3h", "cruces", "r"])
    corte = t.index[len(t) // 2]
    d, v = t[t.index < corte], t[t.index >= corte]
    print(f"Historial, {len(t)} senales, a {EXP} min (primera mitad | segunda mitad)")
    for nombre, f in (("Sin filtros", lambda x: x.lado != 0), ("Fuera de zona alta 3 h", lambda x: x.pos3h <= .8),
                      ("En zona alta 3 h", lambda x: x.pos3h > .8), ("Sin lateral", lambda x: x.cruces < 7),
                      ("En lateral", lambda x: x.cruces >= 7), ("Los dos filtros", lambda x: (x.pos3h <= .8) & (x.cruces < 7))):
        print(f"  {nombre}: {texto(d.r[f(d)])} | {texto(v.r[f(v)])}")
    n = {"suya": [0, 0, 0, 0], "control": [0, 0, 0, 0]}
    for c in casos(MAP):
        g = direccion_guia(c["v"], float(c["v"]["close"].iloc[-1]))
        di = c["dir"] if c["tipo"] == "suya" and g == c["dir"] else (g if c["tipo"] == "control" else None)
        if di and lugar_ok(c["v"], di):
            x = n[c["tipo"]]
            x[0] += 1
            alto = tendencia_1m(c["v"], di)["pos_3h"] > .8
            lat = cruces(c["v"]).iloc[-1] >= 7
            x[1] += not alto
            x[2] += not lat
            x[3] += not alto and not lat
    print("Pasan reglas actuales / sin zona alta / sin lateral / ambos:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
