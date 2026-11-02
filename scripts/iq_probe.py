# -*- coding: utf-8 -*-
"""
Conecta a IQ Option en PRACTICE (solo lectura) y lista activos binarios abiertos.

Se lee get_all_init_v2() directamente: get_all_open_time() lanza hilos para
digital/cfd/forex que se cuelgan cuando el broker no contesta.
"""
import os
import sys
import time

from pathlib import Path

from dotenv import load_dotenv
from iqoptionapi.stable_api import IQ_Option

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))
from data.market_data import register_iq_actives   # noqa: E402


def open_binaries(api) -> dict[str, list[tuple[str, float]]]:
    """{'turbo': [(nombre, payout)], 'binary': [...]} de lo abierto ahora."""
    init = api.get_all_init_v2()
    out = {}
    for kind in ("turbo", "binary"):
        rows = []
        for a in init[kind]["actives"].values():
            if not a.get("enabled") or a.get("is_suspended"):
                continue
            name = str(a["name"]).split(".")[-1]
            payout = (100 - a["option"]["profit"]["commission"]) / 100
            rows.append((name, payout))
        out[kind] = sorted(rows, key=lambda r: ("-OTC" in r[0], -r[1]))
    return out


def connect() -> IQ_Option:
    load_dotenv()
    api = IQ_Option(os.getenv("EXNOVA_EMAIL"), os.getenv("EXNOVA_PASSWORD"))
    ok, reason = api.connect()
    if not ok:
        print("ERROR de conexion:", reason)
        sys.exit(1)
    api.change_balance("PRACTICE")
    register_iq_actives(api)
    return api


if __name__ == "__main__":
    api = connect()
    print(f"Conectado a IQ Option PRACTICE. Balance demo: {api.get_balance()}", flush=True)
    for kind, rows in open_binaries(api).items():
        real = [r for r in rows if "-OTC" not in r[0]]
        print(f"\n{kind.upper()}: {len(rows)} abiertos ({len(real)} reales)")
        for name, p in real + [r for r in rows if "-OTC" in r[0]][:12]:
            print(f"  {name:<22} payout={p:.2f}")
    c = api.get_candles("EURUSD-OTC", 60, 3, time.time())
    print("\nMuestra velas EURUSD-OTC:", [(x["from"], x["open"], x["close"]) for x in c])
    # os._exit: los hilos del websocket no son daemon y bloquean la salida.
    sys.stdout.flush()
    os._exit(0)
