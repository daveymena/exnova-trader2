# -*- coding: utf-8 -*-
"""
Examen de Gemma con panoramica: mitad cronologica posterior de las operaciones del
usuario (no vista en los ejemplos) y controles del mismo periodo. No compra nada.
Uso: python scripts/replica_panoramica.py
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from bot.vision.ejemplos_usuario import casos, leer_como_usuario, seleccionar  # noqa: E402
from gemma_live import direccion_guia, lugar_ok                  # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402


def main() -> int:
    ej = seleccionar(MAP)
    cs = casos(MAP)
    s = sorted((c for c in cs if c["tipo"] == "suya"), key=lambda c: c["ts"])
    corte = s[len(s) // 2]["ts"]
    examen = []
    for c in cs:
        g = direccion_guia(c["v"], float(c["v"]["close"].iloc[-1]))
        if c["ts"] >= corte and g and (not c["dir"] or c["dir"] == g) and lugar_ok(c["v"], g):
            c["g"] = g
            examen.append(c)

    def pregunta(c):
        t = time.time()
        try:
            r = leer_como_usuario(c["v"], c["asset"], ej, timeout=60, propuesta=c["g"])
        except Exception as e:
            r = {"decision": "ERROR", "confianza": 0, "razon": repr(e)[:80]}
        return r, time.time() - t

    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(pregunta, examen))
    filas = []
    for c, (r, seg) in zip(examen, res):
        g = direccion_guia(c["v"], float(c["v"]["close"].iloc[-1]))
        regla = g is not None and lugar_ok(c["v"], g) is not None
        filas.append({"tipo": c["tipo"], "id": c["id"], "asset": c["asset"], "dir": c["dir"], "res": c["res"], "guia": g or "",
                      "regla": regla, "gemma": r["decision"], "conf": r["confianza"], "seg": round(seg, 1), "razon": r["razon"]})
    t = pd.DataFrame(filas)
    t.to_csv(ROOT / "reports" / "replica_panoramica.csv", index=False)
    u, k = t[t.tipo == "suya"], t[t.tipo == "control"]
    print("Tiempo por consulta: mediana", t.seg.median(), "max", t.seg.max())
    print(t.groupby(["tipo", "gemma"]).size().to_string())
    m, n = u.gemma == u["guia"], k.gemma == k["guia"]
    print(f"Pasan las reglas: {len(u)} tuyas ({(u.res == 'GANADA').sum()}G {(u.res == 'PERDIDA').sum()}P) y {len(k)} controles")
    print(f"Gemma aprueba: tuyas {m.sum()}/{len(u)} ({(u.res[m] == 'GANADA').sum()}G {(u.res[m] == 'PERDIDA').sum()}P) | controles {n.sum()}/{len(k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
