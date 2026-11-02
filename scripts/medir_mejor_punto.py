# -*- coding: utf-8 -*-
"""
Mejor punto de entrada de las ultimas operaciones del historial de IQ: prueba cada vela
de 15 s de -5 min a +1 min con la misma duracion y muestra que se veia en ese punto,
para saber si el bot podia reconocerlo. Solo lectura.
Uso: python scripts/medir_mejor_punto.py [n]
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
from bot.backtest.confirmacion import revisar                    # noqa: E402
from gemma_live import direccion_guia, lugar_ok                  # noqa: E402
from iq_probe import connect                                     # noqa: E402

OFFS = range(-300, 61, 15)


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    api = connect()
    nombres = {v: k for k, v in OP.ACTIVES.items()}
    _, h = api.get_position_history_v2("turbo-option", n, 0, 0, 0)
    filas = []
    for p in reversed(h.get("positions", [])):
        ev = p.get("raw_event", {})
        ini, fin = p["open_time"] / 1000, p["close_time"] / 1000
        asset = nombres.get(ev.get("active_id") or p.get("active_id"))
        lado = str(ev.get("direction")).upper()
        d = 1 if lado == "CALL" else -1
        c = api.get_candles(asset, 15, 1000, ini + 400)
        df = pd.DataFrame(c).rename(columns={"max": "high", "min": "low"})
        df.index = pd.to_datetime(df["from"], unit="s")
        df = df[["open", "high", "low", "close"]].astype(float)
        fin_v = df.index + pd.Timedelta(seconds=15)
        atr = float((df["high"] - df["low"]).iloc[-200:].mean())
        t0 = pd.Timestamp(ini, unit="s")
        dur = pd.Timedelta(seconds=fin - ini)

        def precio(t):
            u = df[fin_v <= t]
            return float(u["close"].iloc[-1]) if len(u) else None

        mov = {}
        for o in OFFS:
            t = t0 + pd.Timedelta(seconds=o)
            a, b = precio(t), precio(t + dur)
            if a is not None and b is not None and df.index[-1] + pd.Timedelta(seconds=15) >= t + dur:
                mov[o] = d * (b - a) / atr
        if not mov:
            continue
        real = mov.get(0, float("nan"))
        ganan = sorted(o for o, m in mov.items() if m > 0)
        mejor = max(mov, key=mov.get)
        w = df[fin_v <= t0 + pd.Timedelta(seconds=mejor)].iloc[-800:]
        g = direccion_guia(w, float(w["close"].iloc[-1]))
        r = revisar(w, lado) or {}
        print(f"{t0:%H:%M:%S} {asset} {lado} {p.get('close_reason')} dura {dur.total_seconds() / 60:.1f}m | "
              f"real {real:+.1f} rangos | ganan {len(ganan)}/{len(mov)} puntos | mejor {mejor:+d}s {mov[mejor]:+.1f} rangos")
        print(f"    en ese punto: lado EMA20 {g} | vela a favor {r.get('confirma')} primera {r.get('primera')} | "
              f"pos30 {r.get('pos30', 0):.2f} avance {r.get('avance', 0):.2f} toco EMA20 {r.get('toco_e20')} | "
              f"regla completa {'SI' if g == lado and lugar_ok(w, lado) else 'NO'}")
        i = sorted(mov)
        print("    recorrido: " + " ".join(f"{o:+d}:{'+' if mov[o] > 0 else '-'}" for o in i if o % 60 == 0 or o in (-30, -15, 15, 30)))
        filas.append({"mejor": mejor, "real": real, "m": mov[mejor], "antes": mejor < 0,
                      "confirma": r.get("confirma"), "primera": r.get("primera"), "pos30": r.get("pos30"),
                      "avance": r.get("avance"), "regla": bool(g == lado and lugar_ok(w, lado))})
    t = pd.DataFrame(filas)
    if len(t):
        print(f"\nResumen {len(t)}: mejor punto antes de la entrada en {int(t.antes.sum())} | mediana {t.mejor.median():.0f} s | "
              f"vela a favor {t.confirma.mean():.2f} primera {t.primera.mean():.2f} | pos30 {t.pos30.median():.2f} "
              f"avance {t.avance.median():.2f} | la regla lo veria en {int(t.regla.sum())}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
