# -*- coding: utf-8 -*-
"""
¿Se reconoce el momento previo a la entrada del usuario? Revisa las reglas 30-60 s
antes de cada operacion suya y en los controles. Comparar con pos30/avance actuales.
No compra nada. Uso: python scripts/medir_previo.py
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from bot.backtest.confirmacion import revisar                    # noqa: E402
from bot.vision.ejemplos_usuario import _load, casos, ventana    # noqa: E402
from gemma_live import direccion_guia                            # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402


def fila(v: pd.DataFrame, dir_: str | None) -> dict | None:
    if len(v) < 300:
        return None
    g = direccion_guia(v, float(v["close"].iloc[-1]))
    d = dir_ or g
    r = revisar(v, d) if d else None
    if r:
        u = v.iloc[-1]
        r["filtro"] = g == d
        r["contra"] = bool(u.close < u.open) if d == "CALL" else bool(u.close > u.open)
    return r


def main() -> int:
    cs, cache = casos(MAP), {}
    for atras in (0, 15, 30, 45, 60):
        filas = []
        for c in cs:
            df = cache.setdefault(c["asset"], _load(c["asset"]))
            r = fila(ventana(df, c["ts"] - pd.Timedelta(seconds=atras)), c["dir"] or None)
            if r:
                filas.append({"tipo": c["tipo"], "res": c["res"], **r})
        t = pd.DataFrame(filas)
        s, k = t[t.tipo == "suya"], t[t.tipo == "control"]
        print(f"\n{atras} s antes: lado EMA20 correcto {s.filtro.mean():.2f} ctrl {k.filtro.mean():.2f} | "
              f"pos30 mediana {s.pos30.median():.2f} ctrl {k.pos30.median():.2f} | avance {s.avance.median():.2f} ctrl {k.avance.median():.2f} | "
              f"vela a favor {s.confirma.mean():.2f} ctrl {k.confirma.mean():.2f} | vela en contra {s.contra.mean():.2f} ctrl {k.contra.mean():.2f}")
        if atras in (0, 45):
            for p30, av, vela in itertools.product((.5, .6, .7, .8), (.35, .45), ("confirma", "contra", "")):
                def pasa(x):
                    m = x.filtro & (x.pos30 <= p30) & (x.avance <= av)
                    return m & x[vela] if vela else m
                ms = pasa(s)
                g, p = int((s.res[ms] == "GANADA").sum()), int((s.res[ms] == "PERDIDA").sum())
                print(f"  pos30<={p30} avance<={av} vela={vela or 'cualquiera':10s}: suyas {int(ms.sum())} ({g}G {p}P) ctrl {int(pasa(k).sum())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
