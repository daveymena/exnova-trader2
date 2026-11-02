# -*- coding: utf-8 -*-
"""
Examen de la lectura de Gemma por si sola, sin reglas de lugar: mitad posterior de las
operaciones del usuario (no vista) y controles. La direccion la pone el usuario o la
EMA 20; Gemma solo aprueba o rechaza. Compara dos formas de leer. No compra nada.
Uso: python scripts/examen_lectura.py
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from bot.vision import ejemplos_usuario as eu                    # noqa: E402
from gemma_live import direccion_guia                            # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402

ANTERIOR = ("La direccion ya esta decidida: {d}. Decide solo el lugar. Responde {d} si en la panoramica es el comienzo "
            "del movimiento y hay camino libre; responde NO si el precio ya viene subido, llega a un soporte o resistencia, "
            "o el impulso esta terminando.")
GUIADA = eu.VETO


def main() -> int:
    ej = eu.seleccionar(MAP)
    cs = eu.casos(MAP)
    s = sorted((c for c in cs if c["tipo"] == "suya"), key=lambda c: c["ts"])
    corte = s[len(s) // 2]["ts"]
    examen = []
    for c in cs:
        g = direccion_guia(c["v"], float(c["v"]["close"].iloc[-1]))
        d = c["dir"] or g
        if c["ts"] >= corte and d:
            examen.append(dict(c, d=d))
    filas = []
    for nombre, plantilla in (("anterior", ANTERIOR), ("guiada", GUIADA)):
        eu.VETO = plantilla

        def pregunta(c):
            try:
                return eu.leer_como_usuario(c["v"], c["asset"], ej, timeout=60, propuesta=c["d"])
            except Exception as e:
                return {"decision": "ERROR", "confianza": 0, "razon": repr(e)[:80]}

        with ThreadPoolExecutor(3) as ex:
            res = list(ex.map(pregunta, examen))
        for c, r in zip(examen, res):
            filas.append({"forma": nombre, "tipo": c["tipo"], "id": c["id"], "res": c["res"], "dir": c["d"],
                          "aprueba": r["decision"] == c["d"], "error": r["decision"] == "ERROR", "razon": r["razon"]})
    t = pd.DataFrame(filas)
    t.to_csv(ROOT / "reports" / "examen_lectura.csv", index=False)
    for nombre, g in t.groupby("forma"):
        u, k = g[g.tipo == "suya"], g[g.tipo == "control"]
        print(f"{nombre}: errores {int(g.error.sum())} | aprueba tuyas {int(u.aprueba.sum())}/{len(u)} "
              f"(ganadas {int((u.res[u.aprueba] == 'GANADA').sum())}/{int((u.res == 'GANADA').sum())}, "
              f"perdidas {int((u.res[u.aprueba] == 'PERDIDA').sum())}/{int((u.res == 'PERDIDA').sum())}) | "
              f"controles {int(k.aprueba.sum())}/{len(k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
