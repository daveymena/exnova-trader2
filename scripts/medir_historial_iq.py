# -*- coding: utf-8 -*-
"""
Ultimas operaciones de la cuenta de practica segun el historial de IQ: ¿cuales habrian
ganado con otra duracion? Solo lectura. Uso: python scripts/medir_historial_iq.py [n]
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
from iq_probe import connect                                     # noqa: E402

MIN = (1, 2, 3, 4, 5, 6, 8, 10)


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    api = connect()
    nombres = {v: k for k, v in OP.ACTIVES.items()}
    ok, h = api.get_position_history_v2("turbo-option", n, 0, 0, 0)
    posiciones = h.get("positions", []) if isinstance(h, dict) else []
    if posiciones:
        print("campos:", sorted(posiciones[0].keys()))
        print("raw:", {k: v for k, v in posiciones[0].get("raw_event", {}).items()
                       if k in ("direction", "instrument_dir", "open_time_millisecond", "expiration_time", "value")})
    filas = []
    for p in reversed(posiciones):
        ev = p.get("raw_event", {})
        ini = p.get("open_time", 0) / 1000
        fin = p.get("close_time", 0) / 1000
        asset = nombres.get(ev.get("active_id") or p.get("active_id") or int(p.get("instrument_id", 0) or 0))
        d = 1 if str(ev.get("direction") or p.get("instrument_dir")).lower() == "call" else -1
        entrada = p.get("open_underlying_price") or ev.get("value")
        if not asset or not entrada or not ini:
            print("sin datos:", p.get("external_id"), asset, entrada, ini)
            continue
        c = api.get_candles(asset, 15, 80, ini + 700)
        v = pd.DataFrame(c)
        v["fin"] = v["from"] + 15
        estado = {}
        for m in MIN:
            u = v[v["fin"] <= ini + m * 60]
            estado[m] = "+" if len(u) and d * (u["close"].iloc[-1] - entrada) > 0 else "-"
        dur = (fin - ini) / 60
        hora = pd.Timestamp(ini, unit="s").strftime("%H:%M:%S")
        filas.append({"res": p.get("close_reason"), **estado})
        print(f"{hora} UTC {asset:12s} {'CALL' if d > 0 else 'PUT ':4s} dura {dur:.1f}m {str(p.get('close_reason')):6s} | "
              + " ".join(f"{m}m{e}" for m, e in estado.items()))
    t = pd.DataFrame(filas)
    if len(t):
        print("\nGanarian a esa duracion:", " ".join(f"{m}m {int((t[m] == '+').sum())}/{len(t)}" for m in MIN))
        p = t[t.res != "win"]
        print(f"De {len(p)} perdidas ganarian:", " ".join(f"{m}m {int((p[m] == '+').sum())}" for m in MIN))
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
