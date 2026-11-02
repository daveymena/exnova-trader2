# -*- coding: utf-8 -*-
"""
Autopsia de una operacion del historial de IQ: valores de las reglas al entrar, con las
velas que el bot tenia entonces. Solo lectura. Uso: python scripts/autopsia.py ACTIVO [n]
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
from bot.backtest.confirmacion import revisar, tendencia_1m      # noqa: E402
from gemma_live import direccion_guia, lugar_ok                  # noqa: E402
from iq_probe import connect                                     # noqa: E402


def main() -> int:
    activo = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    api = connect()
    nombres = {v: k for k, v in OP.ACTIVES.items()}
    _, h = api.get_position_history_v2("turbo-option", n, 0, 0, 0)
    for p in h.get("positions", []):
        ev = p.get("raw_event", {})
        asset = nombres.get(ev.get("active_id") or p.get("active_id"))
        if asset != activo:
            continue
        ini, fin = p["open_time"] / 1000, p["close_time"] / 1000
        lado = str(ev.get("direction")).upper()
        df = pd.DataFrame(api.get_candles(asset, 15, 800, ini)).rename(columns={"max": "high", "min": "low"})
        df.index = pd.to_datetime(df["from"], unit="s")
        df = df[df["from"] + 15 <= ini][["open", "high", "low", "close"]].astype(float)
        r, t = revisar(df, lado), tendencia_1m(df, lado)
        ult = df.iloc[-1]
        print(f"{pd.Timestamp(ini, unit='s'):%H:%M:%S} a {pd.Timestamp(fin, unit='s'):%H:%M:%S} UTC {asset} {lado} {p.get('close_reason')} "
              f"apertura {ev.get('value')} cierre {p.get('close_quote')}")
        print(f"   velas {len(df)} ultima {df.index[-1]:%H:%M:%S} o={ult.open} c={ult.close} | lado EMA20 {direccion_guia(df, float(ult.close))} | "
              f"regla actual {'PASA' if lugar_ok(df, lado) else 'NO PASA'}")
        print("   lugar:", {k: round(v, 2) if isinstance(v, float) else v for k, v in (r or {}).items()})
        print("   1 min:", {k: round(v, 2) if isinstance(v, float) else v for k, v in (t or {}).items()})
        w = df.iloc[-120:]
        print(f"   rango 30 min {w['low'].min()} a {w['high'].max()}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
