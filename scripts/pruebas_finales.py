# -*- coding: utf-8 -*-
"""
Preguntas que quedaban abiertas, sin repetir lo ya probado. No compra nada.
  1. Habilidad del usuario: ¿sus aciertos superan a entrar en momentos al azar del mismo
     activo, misma direccion, misma duracion y cerca de la misma hora?
  2. Toma de ganancia: las senales de las reglas con objetivo y stop, como en forex/CFD,
     en mercado real y con un costo de spread supuesto.
Uso: python scripts/pruebas_finales.py
"""
from __future__ import annotations

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
from bot.vision.ejemplos_usuario import H, _load                 # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402
from medir_vencimiento import senales                            # noqa: E402

VENTANA_H, SIMS = 6, 200_000
SPREAD_ATR, LIMITE = 0.3, 40      # costo supuesto en rangos de vela; 10 min de velas de 15 s
rng = np.random.default_rng(7)


def habilidad() -> None:
    trades = json.load(open(ROOT / "reports" / "graficos_rs_data.json", encoding="utf-8"))["trades"]
    filas, cache = [], {}
    for x in trades:
        if x["res"] not in ("GANADA", "PERDIDA"):
            continue
        a = MAP[x["asset"]]
        df = cache.setdefault(a, _load(a))
        ent, dur = pd.Timestamp(x["entry_ts"], unit="s"), int(x["end_ts"] - x["entry_ts"])
        w = df[(df.index >= ent - pd.Timedelta(hours=VENTANA_H)) & (df.index <= ent + pd.Timedelta(hours=VENTANA_H))]["close"]
        pasos = max(1, dur // 15)
        fut = w.shift(-pasos)
        ok = (fut.index.to_series().shift(-pasos) - fut.index.to_series()).dt.total_seconds() == pasos * 15
        d = 1 if x["dir"] == "CALL" else -1
        mov = (d * (fut - w))[ok.to_numpy()].dropna()
        mov = mov[mov != 0]
        filas.append({"gano": x["res"] == "GANADA", "p": (mov > 0).mean() if len(mov) else np.nan, "n": len(mov),
                      "otc": "OTC" in a, "dia": ent.strftime("%m-%d")})
    t = pd.DataFrame(filas).dropna()
    for nombre, g in (("Todas", t), ("Mercado real", t[~t.otc]), ("OTC", t[t.otc])):
        if g.empty:
            continue
        sim = (rng.random((SIMS, len(g))) < g.p.to_numpy()).sum(axis=1)
        w = int(g.gano.sum())
        print(f"{nombre}: {w}/{len(g)} = {100 * w / len(g):.1f}% | al azar se esperaba {100 * g.p.mean():.1f}% | "
              f"p = {(sim >= w).mean():.4f}")
    print("Por sesion:", {k: f"{int(v.gano.sum())}/{len(v)}" for k, v in t.groupby("dia")})


def toma_ganancia() -> None:
    res = []
    for fp in sorted(H.glob("*_15.parquet")):
        a = fp.stem.rsplit("_", 1)[0]
        if "OTC" in a:
            continue
        df = _load(a)
        s = senales(df, "confirma", comienzo=True)
        if s.empty:
            continue
        atr = (df["high"] - df["low"]).rolling(20).mean().shift(1)
        hi, lo = df["high"].to_numpy(), df["low"].to_numpy()
        pos = df.index.get_indexer(s.index)
        for tp, sl in itertools.product((1.5, 3, 5), (1.5, 3)):
            for i, lado, p in zip(pos, s["lado"], s["p"]):
                ar = atr.iloc[i]
                if not ar > 0 or i + LIMITE >= len(df):
                    continue
                r, fin = None, df["close"].iloc[i + LIMITE]
                for j in range(i + 1, i + LIMITE + 1):
                    fav = (hi[j] - p) if lado > 0 else (p - lo[j])
                    con = (p - lo[j]) if lado > 0 else (hi[j] - p)
                    if con >= sl * ar:             # si toca ambos en la vela, cuenta el stop
                        r = -sl
                        break
                    if fav >= tp * ar:
                        r = tp
                        break
                if r is None:
                    r = lado * (fin - p) / ar
                res.append({"tp": tp, "sl": sl, "t": df.index[i], "r": r - SPREAD_ATR})
    t = pd.DataFrame(res)
    corte = t.t.sort_values().iloc[len(t) // 2]
    print(f"\nToma de ganancia, mercado real, costo supuesto {SPREAD_ATR} rangos por operacion (resultado medio en rangos):")
    for (tp, sl), g in t.groupby(["tp", "sl"]):
        d, v = g[g.t < corte].r, g[g.t >= corte].r
        print(f"  objetivo {tp} / stop {sl}: dev {d.mean():+.3f} n={len(d)} | val {v.mean():+.3f} n={len(v)} | "
              f"sin costo {g.r.mean() + SPREAD_ATR:+.3f}")


def main() -> int:
    habilidad()
    toma_ganancia()
    return 0


if __name__ == "__main__":
    sys.exit(main())
