# -*- coding: utf-8 -*-
"""
¿Aporta la lectura de Gemma? Compara, a 3 min, lo que aprobo y lo que rechazo en la tanda
real y en la ultima version de practica, midiendo con velas de IQ. Solo lectura.
Uso: python scripts/medir_gemma.py [--bucle]   (con --bucle actualiza reports/valor_gemma.txt cada 10 min)
"""
from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from backtest_playbook import wilson                             # noqa: E402
from ciclo_mejora import ESPERA, medir, separar                  # noqa: E402
from iq_probe import connect                                     # noqa: E402

FUENTES = (("Toda la operativa real", "gemma_real_analisis.csv", ""),
           ("Real, reglas actuales", "gemma_real_analisis.csv", "2026-11-02 04:20:00"))


def linea(x: pd.DataFrame) -> str:
    r = pd.to_numeric(x["r0_e3"], errors="coerce").dropna()
    r = r[r != 0]
    g, n = int((r > 0).sum()), len(r)
    lo, hi = wilson(g, n) if n else (0, 0)
    return f"{g}/{n} = {100 * g / max(n, 1):.0f}% [{100 * lo:.0f}-{100 * hi:.0f}]"


def medir_todo(api) -> None:
    salida = [f"Actualizado {pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M} UTC. A 3 min, un caso por activo cada 4 min."]
    limite = pd.Timestamp.now(tz="UTC").timestamp() - ESPERA
    for nombre, archivo, desde in FUENTES:
        filas = []
        for f in csv.DictReader(open(ROOT / "bot" / "data" / archivo, encoding="utf-8")):
            if f["hora_utc"] < desde or f["gemma"] == "ERROR":
                continue
            if pd.Timestamp(f["hora_utc"], tz="UTC").timestamp() > limite:
                continue
            m = medir(api, f)
            if m:
                filas.append(m)
        if not filas:
            salida.append(f"{nombre}: sin datos")
            continue
        t = pd.DataFrame(filas)
        t["aprobada"] = t["aprobada"].astype(str) == "True"
        a, b = separar(t[t.aprobada]), separar(t[~t.aprobada])
        salida.append(f"{nombre}: {len(t)} lecturas | Gemma aprueba {linea(a)} | Gemma rechaza {linea(b)}")
    (ROOT / "reports" / "valor_gemma.txt").write_text("\n".join(salida) + "\n", encoding="utf-8")
    print("\n".join(salida), flush=True)


def main() -> int:
    api = connect()
    while True:
        try:
            if not api.check_connect():
                api = connect()
            medir_todo(api)
        except Exception as e:
            print(f"error {e!r}", flush=True)
        if "--bucle" not in sys.argv:
            return 0
        time.sleep(600)


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
