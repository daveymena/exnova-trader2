# -*- coding: utf-8 -*-
"""
Examen de replica: ¿el bot entra donde entro el usuario y solo ahi?

Pasa por la logica de gemma_live.py (filtros de la guia + Gemma) sus operaciones
reales, en el instante de cada entrada, y un numero igual de momentos de control
de los mismos activos en los que no opero. No compra nada.

Uso: python scripts/replica_gemma.py [--out reports/replica_gemma.csv]
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from gemma_live import direccion_guia                            # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402
from bot.vision.ejemplos_usuario import casos                    # noqa: E402
from bot.vision.lector_gemma import leer                         # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "reports" / "replica_gemma.csv"))
    args = ap.parse_args()
    filas = []
    for c in casos(MAP):
        v = c["v"]
        fila = {k: c[k] for k in ("tipo", "id", "asset", "ts", "dir", "res")}
        fila.update(guia="", gemma="", conf="", setup="", razon="", paso="sin_historia")
        if len(v) >= 300:
            guia = direccion_guia(v, float(v["close"].iloc[-1]))
            fila.update(guia=guia or "", paso="filtro_rechaza")
            if guia:
                try:
                    r = leer(v, c["asset"])
                except Exception as e:
                    fila.update(paso="error", razon=repr(e)[:120])
                else:
                    fila.update(gemma=r["decision"], conf=r["confianza"], setup=r["setup"], razon=r["razon"])
                    fila["paso"] = "entra" if r["decision"] == guia and r["confianza"] >= 70 else "gemma_rechaza"
        filas.append(fila)
        print(fila["tipo"], fila["id"], fila["asset"], fila["dir"], "->", fila["paso"], fila["gemma"], flush=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
    t = pd.DataFrame(filas)
    print(t.groupby(["tipo", "paso"]).size().to_string())
    s = t[t.tipo == "suya"]
    print("Replica en la misma direccion:", int(((s.paso == "entra") & (s.gemma == s["dir"])).sum()), "de", len(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
