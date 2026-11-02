# -*- coding: utf-8 -*-
"""
Mide vela de confirmacion y distancia a resistencia/soporte en las operaciones
del usuario, en momentos de control y en las compras del bot. No compra nada.

Uso: python scripts/medir_lugar.py
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


def resumen(t: pd.DataFrame, nombre: str) -> None:
    if t.empty:
        print(f"{nombre}: sin datos")
        return
    print(f"{nombre}: n={len(t)} | vela a favor {100 * t.confirma.mean():.0f}% | "
          f"fuerte {100 * t.confirma_fuerte.mean():.0f}% | pos_lado mediana {t.pos_lado.median():.2f}, "
          f"p90 {t.pos_lado.quantile(.9):.2f} | espacio mediana {t.espacio_atr.median():.2f}, "
          f"<1 ATR {100 * (t.espacio_atr < 1).mean():.0f}%")


def main() -> int:
    filas = []
    for c in casos(MAP):
        d = c["dir"] or direccion_guia(c["v"], float(c["v"]["close"].iloc[-1]))
        r = revisar(c["v"], d) if d else None
        if r:
            filas.append({"tipo": c["tipo"], "id": c["id"], "res": c["res"], **r})
    t = pd.DataFrame(filas)
    resumen(t[t.tipo == "suya"], "Tus operaciones")
    resumen(t[t.res == "GANADA"], "  ganadas")
    resumen(t[t.res == "PERDIDA"], "  perdidas")
    resumen(t[t.tipo == "control"], "Controles (sin entrada tuya)")
    t.to_csv(ROOT / "reports" / "medir_lugar.csv", index=False)

    api, filas = connect(), []
    with open(ROOT / "bot" / "data" / "gemma_ejemplos_live.csv", encoding="utf-8") as f:
        ops = [o for o in csv.DictReader(f) if o["status"] in ("win", "loose")]
    for o in ops:
        ts = pd.Timestamp(o["signal_candle_utc"], tz="UTC").timestamp() + 16
        v = al.closed_candles(api, o["asset"], 15, ts, 400)
        r = revisar(v, o["direction"].upper())
        if r:
            filas.append(r)
            print(o["signal_candle_utc"], o["asset"], o["direction"], o["status"], {k: round(x, 2) for k, x in r.items()})
    resumen(pd.DataFrame(filas), "Compras del bot")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    import os
    os._exit(code)
