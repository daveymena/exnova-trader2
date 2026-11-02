# -*- coding: utf-8 -*-
"""
Reglas de entrada de la guia del usuario (Downloads/Guia-agente-trading.pdf,
"Como entro: guia para el agente de trading", 1 nov 2026), en codigo.

Se evalua en velas de 15 s. `c` son las velas de 15 s CERRADAS hasta la ultima
(c[-1]) y `precio` el precio actual (vela en formacion). Pasos:
  1. Direccion: el lado de la EMA 20 de 15 s (el orden de las EMAs no decide).
  2. F1 no entrar en el extremo: distancia a la EMA 20 de 15 s (en ATR) y a la
     EMA 20 de 1 min (en %).
  3. F2 no perseguir la vela de impulso a favor.
  4. Setup: retroceso que toco la EMA 20 sin cerrar al otro lado de la EMA 50, y
     gatillo = el precio rompe el maximo (CALL) / minimo (PUT) de la ultima vela.
  5. Vencimiento 2 min.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class P:
    max_dist_atr: float = 1.5     # F1 en 15 s
    max_dist_1m: float = 0.03     # F1 en 1 min (fraccion)
    k_impulso: float = 1.5        # F2: cuerpo de la ultima vela en ATR
    toque: float = 0.3            # cuanto cerca de la EMA 20 cuenta como tocarla (ATR)
    vencimiento: int = 2


def features(c: pd.DataFrame, precio: float) -> dict | None:
    """c: velas de 15 s cerradas con historia (>= 200). Devuelve medidas para las reglas."""
    if len(c) < 60:
        return None
    cl = c["close"]
    e20 = cl.ewm(span=20, adjust=False).mean()
    e50 = cl.ewm(span=50, adjust=False).mean()
    atr = float((c["high"] - c["low"]).iloc[-20:].mean()) or 1e-12
    m = c.resample("1min").agg({"close": "last"}).dropna()
    e20_1m = float(m["close"].ewm(span=20, adjust=False).mean().iloc[-1])
    u = c.iloc[-1]
    ult3 = c.iloc[-3:]
    return {
        "lado": 1 if precio > e20.iloc[-1] else -1 if precio < e20.iloc[-1] else 0,
        "dist_atr": abs(precio - e20.iloc[-1]) / atr,
        "dist_1m": abs(precio / e20_1m - 1),
        "cuerpo_atr": abs(u.close - u.open) / atr,
        "ult_dir": 1 if u.close > u.open else -1 if u.close < u.open else 0,
        "low3_e20_atr": (float(ult3["low"].min()) - e20.iloc[-1]) / atr,
        "high3_e20_atr": (float(ult3["high"].max()) - e20.iloc[-1]) / atr,
        "sobre_e50": 1 if u.close > e50.iloc[-1] else -1,
        "rompe_max": precio > u.high,
        "rompe_min": precio < u.low,
        "orden": 1 if e20.iloc[-1] > e50.iloc[-1] else -1,
    }


def decidir(f: dict | None, p: P = P()) -> str | None:
    """Devuelve 'CALL', 'PUT' o None segun la guia."""
    if f is None or f["lado"] == 0:
        return None
    d = "CALL" if f["lado"] > 0 else "PUT"
    if f["dist_atr"] > p.max_dist_atr or f["dist_1m"] > p.max_dist_1m:          # F1
        return None
    if f["ult_dir"] == f["lado"] and f["cuerpo_atr"] > p.k_impulso:             # F2
        return None
    if d == "CALL":
        ok = f["low3_e20_atr"] <= p.toque and f["sobre_e50"] > 0 and f["rompe_max"]
    else:
        ok = f["high3_e20_atr"] >= -p.toque and f["sobre_e50"] < 0 and f["rompe_min"]
    return d if ok else None


def features_series(df: pd.DataFrame) -> pd.DataFrame:
    """Version vectorizada para el historial: entrada al cierre de la vela i
    (precio = close[i], 'ultima cerrada' = vela i-1)."""
    cl, hi, lo, op = df["close"], df["high"], df["low"], df["open"]
    e20 = cl.ewm(span=20, adjust=False).mean()
    e50 = cl.ewm(span=50, adjust=False).mean()
    atr = (hi - lo).rolling(20).mean().shift(1).replace(0, np.nan)
    m = cl.resample("1min").last().dropna()
    e1 = m.ewm(span=20, adjust=False).mean()
    e1 = e1.shift(1).reindex(df.index, method="ffill")                         # solo minutos cerrados
    pe20, pe50 = e20.shift(1), e50.shift(1)
    f = pd.DataFrame(index=df.index)
    f["lado"] = np.sign(cl - pe20)
    f["dist_atr"] = (cl - pe20).abs() / atr
    f["dist_1m"] = (cl / e1 - 1).abs()
    f["cuerpo_atr"] = (cl - op).abs().shift(1) / atr
    f["ult_dir"] = np.sign(cl - op).shift(1)
    f["low3_e20_atr"] = (lo.rolling(3).min().shift(1) - pe20) / atr
    f["high3_e20_atr"] = (hi.rolling(3).max().shift(1) - pe20) / atr
    f["sobre_e50"] = np.sign(cl.shift(1) - pe50)
    f["rompe_max"] = cl > hi.shift(1)
    f["rompe_min"] = cl < lo.shift(1)
    f["orden"] = np.sign(pe20 - pe50)
    return f


def senales(f: pd.DataFrame, p: P = P()) -> pd.Series:
    """+1 CALL, -1 PUT, 0 nada (vectorizado, mismas reglas que decidir)."""
    base = (f["dist_atr"] <= p.max_dist_atr) & (f["dist_1m"] <= p.max_dist_1m)
    base &= ~((f["ult_dir"] == f["lado"]) & (f["cuerpo_atr"] > p.k_impulso))
    call = base & (f["lado"] > 0) & (f["low3_e20_atr"] <= p.toque) & (f["sobre_e50"] > 0) & f["rompe_max"]
    put = base & (f["lado"] < 0) & (f["high3_e20_atr"] >= -p.toque) & (f["sobre_e50"] < 0) & f["rompe_min"]
    return call.astype(int) - put.astype(int)
