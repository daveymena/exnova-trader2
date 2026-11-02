# -*- coding: utf-8 -*-
"""
¿Las entradas iban a favor de la tendencia de 1 min? Operaciones del usuario, controles
y ultimas compras en IQ. Solo lectura. Uso: python scripts/medir_tendencia.py [n]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from iqoptionapi import constants as OP                          # noqa: E402
from bot.backtest.confirmacion import tendencia_1m               # noqa: E402
from bot.vision.ejemplos_usuario import casos                    # noqa: E402
from gemma_live import direccion_guia, lugar_ok                  # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402
from iq_probe import connect                                     # noqa: E402

CAMPOS = ("orden", "pendiente", "sobre_e50", "pos_3h")


def resumen(t: pd.DataFrame, nombre: str) -> None:
    if t.empty:
        return
    g, p = t[t.res.isin(("GANADA", "win"))], t[t.res.isin(("PERDIDA", "loose"))]
    print(f"{nombre}: n={len(t)} | EMA20 sobre EMA50 a favor {100 * t.orden.mean():.0f}% | pendiente a favor {100 * t.pendiente.mean():.0f}% | "
          f"precio del lado bueno de EMA50 {100 * t.sobre_e50.mean():.0f}% | pos 3h mediana {t.pos_3h.median():.2f}")
    if len(g) and len(p):
        for c in CAMPOS[:3]:
            print(f"    con {c}: {int(g[c].sum())}G {int(p[c].sum())}P | sin {c}: {int((~g[c]).sum())}G {int((~p[c]).sum())}P")


def main() -> int:
    filas = []
    for c in casos(MAP):
        g = direccion_guia(c["v"], float(c["v"]["close"].iloc[-1]))
        d = c["dir"] or g
        r = tendencia_1m(c["v"], d) if d else None
        if r:
            filas.append({"tipo": c["tipo"], "res": c["res"], "regla": g == d and lugar_ok(c["v"], d) is not None, **r})
    t = pd.DataFrame(filas)
    s, k = t[t.tipo == "suya"], t[t.tipo == "control"]
    resumen(s, "Tus operaciones")
    resumen(s[s.regla], "  las que pasan las reglas")
    resumen(k, "Controles")
    resumen(k[k.regla], "  controles que pasan las reglas")

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    api = connect()
    nombres = {v: k for k, v in OP.ACTIVES.items()}
    _, h = api.get_position_history_v2("turbo-option", n, 0, 0, 0)
    filas = []
    for p in reversed(h.get("positions", [])):
        ev = p.get("raw_event", {})
        ini = p["open_time"] / 1000
        asset = nombres.get(ev.get("active_id") or p.get("active_id"))
        lado = str(ev.get("direction")).upper()
        df = pd.DataFrame(api.get_candles(asset, 15, 800, ini)).rename(columns={"max": "high", "min": "low"})
        df.index = pd.to_datetime(df["from"], unit="s")
        r = tendencia_1m(df[["open", "high", "low", "close"]].astype(float), lado)
        if r:
            filas.append({"res": p.get("close_reason"), **r})
            print(f"  {pd.Timestamp(ini, unit='s'):%H:%M:%S} {asset} {lado} {p.get('close_reason')} | orden {r['orden']} pendiente {r['pendiente']} "
                  f"lado EMA50 {r['sobre_e50']} pos3h {r['pos_3h']:.2f}")
    resumen(pd.DataFrame(filas), "Compras del bot")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
