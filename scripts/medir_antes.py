# -*- coding: utf-8 -*-
"""
¿Entrar antes de la vela de confirmacion da margen? Compara, con velas de 15 s de IQ,
la entrada tras la confirmacion, sin esperarla y al final del retroceso. No compra nada.
Uso: python scripts/medir_antes.py
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
from bot.vision.ejemplos_usuario import H, _load                 # noqa: E402
from medir_vencimiento import EXPS, fin_binaria, senales         # noqa: E402

VARIANTES = (("Tras confirmacion (actual)", "confirma"), ("Sin esperar la vela", ""),
             ("Al final del retroceso", "contra"))


def medir(vela: str) -> pd.DataFrame:
    out = []
    for fp in sorted(H.glob("*_15.parquet")):
        a = fp.stem.rsplit("_", 1)[0]
        df = _load(a)
        s = senales(df, vela)
        if s.empty:
            continue
        s["activo"] = a
        ent = s.index + pd.Timedelta(seconds=16)
        for e in EXPS:
            sal = df["close"].reindex(fin_binaria(ent, e) - pd.Timedelta(seconds=15)).to_numpy()
            s[f"m{e}"] = np.sign(s["lado"].to_numpy() * (sal - s["p"].to_numpy()))
        out.append(s)
    return pd.concat(out).sort_index()


def acierto(x: pd.Series) -> str:
    x = x.dropna()
    x = x[x != 0]
    g, n = int((x > 0).sum()), len(x)
    lo, hi = wilson(g, n) if n else (0, 0)
    return f"{100 * g / max(n, 1):.1f}% [{100 * lo:.1f}-{100 * hi:.1f}] n={n}"


def main() -> int:
    for nombre, vela in VARIANTES:
        t = medir(vela)
        corte = t.index[len(t) // 2]
        print(nombre)
        for e in (2, 3, 5):
            print(f"  {e} min: dev {acierto(t[t.index < corte][f'm{e}'])} | val {acierto(t[t.index >= corte][f'm{e}'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
