# -*- coding: utf-8 -*-
"""
Gemma con los ejemplos MAS PARECIDOS de la primera mitad de las operaciones del usuario,
marcados como ganados o perdidos, examinada con la segunda mitad y controles. Compara con
los 14 ejemplos fijos. No compra nada. Uso: python scripts/examen_similares.py
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from bot.backtest.confirmacion import revisar                    # noqa: E402
from bot.vision import ejemplos_usuario as eu                    # noqa: E402
from gemma_live import direccion_guia                            # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402

RASGOS = ("pos30", "avance", "pos_lado")
GANADAS, PERDIDAS, SIN_ENTRADA = 6, 4, 4


def rasgos(c: dict) -> np.ndarray | None:
    r = revisar(c["v"], c["d"])
    return np.array([min(r[k], 1.5) for k in RASGOS]) if r else None


def cercanos(pool: list[dict], x: np.ndarray, n: int) -> list[dict]:
    return sorted(pool, key=lambda p: float(np.abs(p["x"] - x).sum()))[:n]


def main() -> int:
    fijos = eu.seleccionar(MAP)
    cs = eu.casos(MAP)
    s = sorted((c for c in cs if c["tipo"] == "suya"), key=lambda c: c["ts"])
    corte = s[len(s) // 2]["ts"]
    for c in cs:
        c["d"] = c["dir"] or direccion_guia(c["v"], float(c["v"]["close"].iloc[-1]))
    cs = [c for c in cs if c["d"]]
    for c in cs:
        c["x"] = rasgos(c)
    cs = [c for c in cs if c["x"] is not None]
    previas, examen = [c for c in cs if c["ts"] < corte], [c for c in cs if c["ts"] >= corte]
    for c in previas:
        c["png"] = eu.imagen(c["v"], c["asset"])

    def similares(c: dict) -> list[tuple[str, str]]:
        mismo = [p for p in previas if p["d"] == c["d"]]
        gan = cercanos([p for p in mismo if p["res"] == "GANADA"], c["x"], GANADAS)
        per = cercanos([p for p in mismo if p["res"] == "PERDIDA"], c["x"], PERDIDAS)
        sin = cercanos([p for p in mismo if p["tipo"] == "control"], c["x"], SIN_ENTRADA)
        return ([(p["png"], f"Duvier entro {p['d']} aqui y gano") for p in gan]
                + [(p["png"], f"Duvier entro {p['d']} aqui y perdio: no copiar") for p in per]
                + [(p["png"], "Duvier NO entro aqui") for p in sin])

    filas = []
    for nombre, ejemplos in (("fijos", lambda c: fijos), ("parecidos", similares)):
        def pregunta(c):
            try:
                return eu.leer_como_usuario(c["v"], c["asset"], ejemplos(c), timeout=60, propuesta=c["d"])
            except Exception as e:
                return {"decision": "ERROR", "confianza": 0, "razon": repr(e)[:80]}

        with ThreadPoolExecutor(3) as ex:
            res = list(ex.map(pregunta, examen))
        for c, r in zip(examen, res):
            filas.append({"forma": nombre, "tipo": c["tipo"], "id": c["id"], "res": c["res"], "aprueba": r["decision"] == c["d"],
                          "error": r["decision"] == "ERROR", "razon": r["razon"]})
    t = pd.DataFrame(filas)
    t.to_csv(ROOT / "reports" / "examen_similares.csv", index=False)
    for nombre, g in t.groupby("forma"):
        u, k = g[g.tipo == "suya"], g[g.tipo == "control"]
        print(f"{nombre}: errores {int(g.error.sum())} | tuyas {int(u.aprueba.sum())}/{len(u)} "
              f"(ganadas {int((u.res[u.aprueba] == 'GANADA').sum())}/{int((u.res == 'GANADA').sum())}, "
              f"perdidas {int((u.res[u.aprueba] == 'PERDIDA').sum())}/{int((u.res == 'PERDIDA').sum())}) | "
              f"controles {int(k.aprueba.sum())}/{len(k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
