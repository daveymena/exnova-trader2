# -*- coding: utf-8 -*-
"""
Cuanto del camino hacia la resistencia/soporte ya estaba hecho al entrar:
operaciones del usuario, controles y compras del bot. No compra nada.
Uso: python scripts/medir_recorrido.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
import azura_live as al                                          # noqa: E402
from bot.backtest.confirmacion import revisar                    # noqa: E402
from bot.vision.ejemplos_usuario import casos                    # noqa: E402
from gemma_live import direccion_guia                            # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402
from iq_probe import connect                                     # noqa: E402


def linea(t: pd.DataFrame, nombre: str) -> None:
    if t.empty:
        return
    q = lambda c, p: round(float(t[c].quantile(p)), 2)
    print(f"{nombre}: n={len(t)} | pos30 p25/50/75 {q('pos30', .25)}/{q('pos30', .5)}/{q('pos30', .75)} | "
          f"avance p25/50/75 {q('avance', .25)}/{q('avance', .5)}/{q('avance', .75)} | "
          f"avance>0.6 {100 * (t.avance > .6).mean():.0f}% | pos30>0.7 {100 * (t.pos30 > .7).mean():.0f}%")


def main() -> int:
    filas = []
    for c in casos(MAP):
        d = c["dir"] or direccion_guia(c["v"], float(c["v"]["close"].iloc[-1]))
        r = revisar(c["v"], d) if d else None
        if r:
            filas.append({"tipo": c["tipo"], "res": c["res"], **r})
    t = pd.DataFrame(filas)
    linea(t[t.tipo == "suya"], "Tus operaciones")
    linea(t[t.res == "GANADA"], "  ganadas")
    linea(t[t.res == "PERDIDA"], "  perdidas")
    linea(t[t.tipo == "control"], "Controles")
    api, filas = connect(), []
    for nombre in ("gemma_lugar_live.csv", "gemma_temprana_live.csv"):
        p = ROOT / "bot" / "data" / nombre
        if not p.exists():
            continue
        for o in csv.DictReader(open(p, encoding="utf-8")):
            if o["status"] not in ("win", "loose"):
                continue
            ts = pd.Timestamp(o["signal_candle_utc"], tz="UTC").timestamp() + 16
            r = revisar(al.closed_candles(api, o["asset"], 15, ts, 400), o["direction"].upper())
            if r:
                filas.append(r)
                print(f"  {o['signal_candle_utc']} {o['asset']} {o['direction']} {o['status']} "
                      f"pos30 {r['pos30']:.2f} avance {r['avance']:.2f} espacio {r['espacio_atr']:.1f}")
    linea(pd.DataFrame(filas), "Compras del bot")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    import os
    os._exit(code)
