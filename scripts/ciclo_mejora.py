# -*- coding: utf-8 -*-
"""
Ciclo de mejora: cada analisis de Gemma, compre o no, se mide despues con las velas de IQ
para cada punto de entrada y cada vencimiento de 1 a 5 min (gemma_sombra.csv). Resume en
reports/ciclo_mejora.txt que gana y, si una combinacion ejecutable supera a Wilson con
Bonferroni y al menos 100 casos, escribe su vencimiento en gemma_config.json, que el bot lee.
No compra nada. Uso: python scripts/ciclo_mejora.py [--una-vez]
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from backtest_playbook import wilson                             # noqa: E402
from ciclo_fin import fin_binaria                                # noqa: E402
from iq_probe import connect                                     # noqa: E402
from repaso_real import actualizar as repaso_real                # noqa: E402

DATA = ROOT / "bot" / "data"
ANALISIS, SOMBRA, CONFIG = DATA / "gemma_real_analisis.csv", DATA / "gemma_sombra_real.csv", DATA / "gemma_config.json"
REPORTE = ROOT / "reports" / "ciclo_mejora.txt"
DESDE = "2026-11-02 04:20:00"     # version actual de las reglas en real
VERSION = "2026-11-02 04:20:00"   # el informe cuenta solo la version actual de las reglas
RETRASOS, EXPS = (-60, -30, -15, 0, 15, 30), (1, 2, 3, 4, 5)
EJECUTABLES = [(r, e) for r in (0, 15, 30) for e in EXPS]
BE, N_MIN, ESPERA = 1 / 1.85, 100, 480
UN = pd.Timedelta(seconds=15)


def medir(api, f: dict) -> dict | None:
    cierre = pd.Timestamp(f["hora_utc"]).floor("15s")
    c = api.get_candles(f["activo"], 15, 80, cierre.timestamp() + 420)
    if not c:
        return None
    px = pd.Series({pd.Timestamp(v["from"] + 15, unit="s"): float(v["close"]) for v in c}).sort_index()
    d = 1 if f["guia"] == "CALL" else -1
    fila = {"hora_utc": f["hora_utc"], "activo": f["activo"], "lado": f["guia"], "gemma": f["gemma"],
            "aprobada": f["gemma"] == f["guia"], "confirmo": f["confirmo_al_cierre"] == "True"}
    for r in RETRASOS:
        t = cierre + pd.Timedelta(seconds=r)
        a = px.get(t)
        for e in EXPS:
            b = px.get(fin_binaria(t + pd.Timedelta(seconds=1), e))
            fila[f"r{r}_e{e}"] = int(np.sign(d * (b - a))) if a is not None and b is not None else ""
    return fila


def actualizar(api) -> int:
    hechos = set()
    if SOMBRA.exists():
        hechos = {(r["hora_utc"], r["activo"]) for r in csv.DictReader(open(SOMBRA, encoding="utf-8"))}
    limite = datetime.now(timezone.utc).timestamp() - ESPERA
    nuevos = 0
    for f in csv.DictReader(open(ANALISIS, encoding="utf-8")):
        if f["hora_utc"] < DESDE or (f["hora_utc"], f["activo"]) in hechos or f["gemma"] == "ERROR":
            continue
        if pd.Timestamp(f["hora_utc"], tz="UTC").timestamp() > limite:
            continue
        fila = medir(api, f)
        if fila is None:
            continue
        existe = SOMBRA.exists()
        with SOMBRA.open("a", newline="", encoding="utf-8") as s:
            w = csv.DictWriter(s, fieldnames=list(fila))
            if not existe:
                w.writeheader()
            w.writerow(fila)
        nuevos += 1
    return nuevos


def separar(t: pd.DataFrame) -> pd.DataFrame:
    """Un caso por activo cada 4 min: analisis seguidos del mismo activo no son independientes."""
    t = t.sort_values("hora_utc")
    guardar, ultimo = [], {}
    for i, r in zip(t.index, t.itertuples()):
        h = pd.Timestamp(r.hora_utc)
        if r.activo not in ultimo or (h - ultimo[r.activo]).total_seconds() >= 240:
            guardar.append(i)
            ultimo[r.activo] = h
    return t.loc[guardar]


def celda(t: pd.DataFrame, r: int, e: int) -> tuple[int, int]:
    x = pd.to_numeric(t[f"r{r}_e{e}"], errors="coerce").dropna()
    x = x[x != 0]
    return int((x > 0).sum()), len(x)


def texto(g: int, n: int) -> str:
    if not n:
        return "sin datos"
    lo, hi = wilson(g, n)
    return f"{100 * g / n:.1f}% [{100 * lo:.0f}-{100 * hi:.0f}] n={n}"


def informe() -> None:
    t = pd.read_csv(SOMBRA, keep_default_na=False)
    t = t[t["hora_utc"] >= VERSION]
    if t.empty:
        return
    t["aprobada"], t["confirmo"] = t["aprobada"].astype(str) == "True", t["confirmo"].astype(str) == "True"
    grupos = (("Compraria (aprobada y confirmada)", separar(t[t.confirmo])),
              ("Gemma aprueba", separar(t[t.aprobada])),
              ("Gemma dice NO", separar(t[~t.aprobada])))
    L = [f"Actualizado {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Analisis medidos: {len(t)}. "
         f"Hace falta mas de {100 * BE:.1f}%, con al menos {N_MIN} casos."]
    for nombre, g in grupos:
        L.append(f"\n{nombre}: {len(g)} casos independientes")
        L.append("  Vencimiento, entrando al cierre:")
        L += [f"    {e} min: {texto(*celda(g, 0, e))}" for e in EXPS]
        L.append("  Punto de entrada, a 3 min:")
        L += [f"    {r:+d} s: {texto(*celda(g, r, 3))}" for r in RETRASOS]
    base = grupos[0][1]
    z = NormalDist().inv_cdf(1 - 0.05 / 2 / len(EJECUTABLES))
    pasan = []
    for r, e in EJECUTABLES:
        w, n = celda(base, r, e)
        if n >= N_MIN and wilson(w, n, z)[0] > BE:
            pasan.append((w / n, r, e, n))
    if pasan:
        p, r, e, n = max(pasan)
        L.append(f"\nPASA: entrar {r:+d} s con vencimiento {e} min, {100 * p:.1f}% n={n}")
        if CONFIG.exists() and json.loads(CONFIG.read_text()).get("origen") == "usuario":
            L.append("El usuario fijo el vencimiento: decision manual.")
        elif r == 0:
            CONFIG.write_text(json.dumps({"vencimiento_min": e, "acierto": p, "n": n}))
            L.append("El bot cambia a ese vencimiento.")
        else:
            L.append("Requiere retrasar la entrada: decision manual.")
    else:
        L.append("\nNinguna combinacion supera la prueba todavia: el bot sigue igual.")
    REPORTE.write_text("\n".join(L) + "\n", encoding="utf-8")


def main() -> int:
    api = connect()
    while True:
        try:
            if not api.check_connect():
                api = connect()
            nuevos = actualizar(api)
            if SOMBRA.exists():
                informe()
            repaso_real(api)
            print(f"{datetime.now(timezone.utc):%H:%M:%S} UTC nuevos {nuevos}", flush=True)
        except Exception as e:
            print(f"error {e!r}", flush=True)
        if "--una-vez" in sys.argv:
            return 0
        time.sleep(300)


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    import os
    os._exit(code)
