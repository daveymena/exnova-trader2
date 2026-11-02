# -*- coding: utf-8 -*-
"""
Busqueda con disciplina: forma de entrar x vencimiento x segmento (activo, bloque
horario, entre semana / fin de semana). Se elige SOLO con la primera mitad y se
confirma en la segunda; pasa si el limite inferior de Wilson con Bonferroni supera
el punto de equilibrio. No compra nada. Uso: python scripts/buscar_borde.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from statistics import NormalDist                                # noqa: E402

from backtest_playbook import wilson                             # noqa: E402
from medir_antes import VARIANTES, medir                         # noqa: E402

BE = 1 / 1.85
N_MIN = 100
BLOQUES = ((0, 7), (7, 13), (13, 17), (17, 22), (22, 24))


def segmentos(t: pd.DataFrame):
    yield "todo", pd.Series(True, index=t.index)
    for a in sorted(t.activo.unique()):
        yield a, t.activo == a
    h = t.index.hour
    for i, j in BLOQUES:
        yield f"{i:02d}-{j:02d} UTC", pd.Series((h >= i) & (h < j), index=t.index)
    fin = pd.Series(t.index.dayofweek >= 5, index=t.index)
    yield "fin de semana", fin
    yield "entre semana", ~fin
    yield "CALL", t.lado > 0
    yield "PUT", t.lado < 0


def main() -> int:
    filas = []
    for nombre, vela in VARIANTES:
        t = medir(vela)
        corte = t.index[len(t) // 2]
        for seg, m in segmentos(t):
            x = t[m.to_numpy()]
            for e in (1, 2, 3, 4, 5):
                r = x[f"m{e}"].dropna()
                r = r[r != 0]
                d, v = r[r.index < corte], r[r.index >= corte]
                filas.append({"variante": nombre, "seg": seg, "exp": e, "nd": len(d), "ad": (d > 0).mean() if len(d) else 0,
                              "nv": len(v), "gv": int((v > 0).sum()), "av": (v > 0).mean() if len(v) else 0})
    f = pd.DataFrame(filas)
    print(f"Combinaciones probadas: {len(f)}")
    c = f[(f.nd >= N_MIN) & (f.nv >= N_MIN)].sort_values("ad", ascending=False)
    z = NormalDist().inv_cdf(1 - 0.05 / 2 / len(f))
    pd.set_option("display.width", 200)
    print("\nMejores por primera mitad y como les fue en la segunda:")
    print(c.head(15)[["variante", "seg", "exp", "nd", "ad", "nv", "av"]].round(3).to_string(index=False))
    print("\nPasan en segunda mitad con Bonferroni:")
    ok = [r for r in c.itertuples() if wilson(r.gv, r.nv, z)[0] > BE and r.ad > BE]
    for r in ok:
        print(" ", r.variante, r.seg, f"{r.exp}m", f"dev {r.ad:.3f} val {r.av:.3f} n {r.nv}")
    if not ok:
        print("  ninguna")
    return 0


if __name__ == "__main__":
    sys.exit(main())
