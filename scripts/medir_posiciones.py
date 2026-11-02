# -*- coding: utf-8 -*-
"""
¿Se habria ganado entrando antes o despues? Mueve cada entrada del usuario y del bot
de -60 a +60 s con la misma duracion. Despues prueba limites de las reglas sobre las
64 operaciones (ajuste DENTRO de la muestra, a peticion del usuario) y mira las mejores
en el historial. No compra nada. Uso: python scripts/medir_posiciones.py
"""
from __future__ import annotations

import csv
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
import azura_live as al                                          # noqa: E402
import medir_vencimiento as mv                                   # noqa: E402
from bot.backtest.confirmacion import revisar                    # noqa: E402
from bot.vision.ejemplos_usuario import H, _load, casos          # noqa: E402
from gemma_live import direccion_guia                            # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402
from iq_probe import connect                                     # noqa: E402

OFFS = range(-60, 61, 15)
UN = pd.Timedelta(seconds=15)


def precio(df: pd.DataFrame, t: pd.Timestamp) -> float:
    u = df[df.index + UN <= t]
    return float(u["close"].iloc[-1]) if len(u) and (t - u.index[-1]).total_seconds() <= 60 else np.nan


def mover(df: pd.DataFrame, ini: pd.Timestamp, dur: int, d: int) -> dict:
    fila = {}
    for o in OFFS:
        t = ini + pd.Timedelta(seconds=o)
        a, b = precio(df, t), precio(df, t + pd.Timedelta(seconds=dur))
        fila[o] = np.sign(d * (b - a)) if a == a and b == b else np.nan
    return fila


def tabla(t: pd.DataFrame, nombre: str) -> None:
    print(nombre + ": " + " ".join(f"{o:+d}s {100 * (t[o].dropna()[t[o].dropna() != 0] > 0).mean():.0f}%" for o in OFFS))


def usuario() -> None:
    trades = json.load(open(ROOT / "reports" / "graficos_rs_data.json", encoding="utf-8"))["trades"]
    filas, cache = [], {}
    for x in trades:
        a = MAP[x["asset"]]
        cache.setdefault(a, _load(a))
        dur = int(x["end_ts"] - x["entry_ts"])
        f = mover(cache[a], pd.Timestamp(x["entry_ts"], unit="s"), dur, 1 if x["dir"] == "CALL" else -1)
        filas.append({"res": x["res"], **f})
    t = pd.DataFrame(filas)
    tabla(t, f"Tus {len(t)} operaciones, misma duracion, entrando en")
    p = t[t.res == "PERDIDA"]
    tabla(p, f"  solo tus {len(p)} perdidas")
    print("  perdidas que habrian ganado entrando antes (-15 a -60):", int((p[[-60, -45, -30, -15]] > 0).any(axis=1).sum()),
          "| despues (+15 a +60):", int((p[[15, 30, 45, 60]] > 0).any(axis=1).sum()))


def bot() -> None:
    api, filas = connect(), []
    for nombre in ("gemma_ejemplos_live.csv", "gemma_lugar_live.csv", "gemma_temprana_live.csv"):
        p = ROOT / "bot" / "data" / nombre
        if not p.exists():
            continue
        for o in csv.DictReader(open(p, encoding="utf-8")):
            if o["status"] not in ("win", "loose"):
                continue
            ini = pd.Timestamp(o["signal_candle_utc"]) + pd.Timedelta(seconds=16)
            ts = ini.timestamp() + 60 + int(o["expiry_min"]) * 60 + 60
            df = al.closed_candles(api, o["asset"], 15, ts, 60)
            f = mover(df, ini, int(o["expiry_min"]) * 60, 1 if o["direction"] == "call" else -1)
            filas.append({"res": o["status"], **f})
    t = pd.DataFrame(filas)
    tabla(t, f"Compras del bot ({len(t)}), misma duracion, entrando en")


def pasa(x: pd.DataFrame, pos30, avance, espacio, pos5, conf) -> pd.Series:
    m = (x.pos30 <= pos30) & (x.avance <= avance) & (x.espacio_atr >= espacio) & (x.pos_lado <= pos5) & x.filtro
    return m & x.confirma if conf else m


def historial(pos30, avance, espacio, pos5, conf) -> str:
    mv.POS30_MAX, mv.AVANCE_MAX, mv.ESPACIO_MIN_ATR, mv.POS_MAX = pos30, avance, espacio, pos5
    out = []
    for fp in sorted(H.glob("*_15.parquet")):
        df = _load(fp.stem.rsplit("_", 1)[0])
        s = mv.senales(df, "confirma" if conf else "", comienzo=True)
        if s.empty:
            continue
        sal = df["close"].reindex(mv.fin_binaria(s.index + pd.Timedelta(seconds=16), 3) - UN).to_numpy()
        s["r"] = np.sign(s["lado"].to_numpy() * (sal - s["p"].to_numpy()))
        out.append(s)
    r = pd.concat(out).sort_index()["r"].dropna()
    r = r[r != 0]
    return f"{100 * (r > 0).mean():.1f}% n={len(r)}"


def ajuste() -> None:
    filas = []
    for c in casos(MAP):
        g = direccion_guia(c["v"], float(c["v"]["close"].iloc[-1]))
        d = c["dir"] or g
        r = revisar(c["v"], d) if d else None
        if r:
            filas.append({"tipo": c["tipo"], "res": c["res"], "filtro": g == d, **r})
    t = pd.DataFrame(filas)
    s, k = t[t.tipo == "suya"], t[t.tipo == "control"]
    res = []
    for pos30, avance, espacio, pos5, conf in itertools.product((.5, .6, .7, .8, 1.01), (.35, .45, .6, .8, 1.01),
                                                                (0, 1, 2), (.85, 1.01), (True, False)):
        ms, mk = pasa(s, pos30, avance, espacio, pos5, conf), pasa(k, pos30, avance, espacio, pos5, conf)
        g, p = int((s.res[ms] == "GANADA").sum()), int((s.res[ms] == "PERDIDA").sum())
        res.append({"pos30": pos30, "avance": avance, "espacio": espacio, "pos5": pos5, "conf": conf,
                    "suyas": int(ms.sum()), "ctrl": int(mk.sum()), "gan": g, "per": p,
                    "acierto": g / max(g + p, 1)})
    r = pd.DataFrame(res)
    pd.set_option("display.width", 200)
    print(f"\nAjuste dentro de la muestra: {len(r)} combinaciones (suyas de {len(s)}, controles de 64)")
    print("Mas suyas sin subir controles (por diferencia):")
    a = r.assign(dif=r.suyas - r.ctrl).sort_values(["dif", "acierto"], ascending=False).head(5)
    print(a.round(2).to_string(index=False))
    print("Mejor acierto en sus operaciones con al menos 15:")
    b = r[r.gan + r.per >= 15].sort_values(["acierto", "suyas"], ascending=False).head(5)
    print(b.round(2).to_string(index=False))
    print("\nEsas mismas en el historial a 3 min:")
    for x in pd.concat([a.head(3), b.head(3)]).drop_duplicates().itertuples():
        print(f"  pos30<={x.pos30} avance<={x.avance} espacio>={x.espacio} pos5<={x.pos5} conf={x.conf}: "
              f"{historial(x.pos30, x.avance, x.espacio, x.pos5, x.conf)}")


def main() -> int:
    usuario()
    bot()
    ajuste()
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    import os
    os._exit(code)
