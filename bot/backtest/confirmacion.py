# -*- coding: utf-8 -*-
"""
Lugar y confirmacion de la entrada (guia + informe "Retroceso a favor" v1.2).

Mira la ultima vela de 15 s cerrada, como el usuario antes de entrar:
  confirma_fuerte: vela a favor que cierra mas alla del extremo de la anterior;
  confirma: vela a favor (la "primera vela roja/verde" de sus setups);
  primera: esa vela es la primera a favor tras una vela en contra (el giro);
  pos: posicion del cierre en el rango de 5 min;
  espacio_atr: distancia a la resistencia (CALL) o soporte (PUT) de 30 min, en
    rangos medios; negativa o cero = el precio ya esta en ese nivel o lo rompe;
  pos30: posicion en el rango de 30 min, 1 = pegado al nivel hacia el que se opera;
  avance: parte ya recorrida del camino entre el arranque del movimiento (10 min)
    y ese nivel; 0 = recien empieza, 1 = ya llego.
"""
from __future__ import annotations

import pandas as pd

RANGO_VELAS, NIVEL_VELAS, ATR_VELAS = 20, 120, 20
RETROCESO_VELAS, TOQUE_ATR = 7, 0.35   # informe: retroceso de 1-6 velas que toca la EMA 20 (<= 0.35 ATR)
SWING_VELAS = 40                       # 10 min: de donde arranca el movimiento actual


def cruces_e20(df: pd.DataFrame) -> int:
    """Veces que el cierre cruzo la EMA 20 en los ultimos 10 min: muchos cruces = lateral."""
    cl = df["close"]
    return int(((cl - cl.ewm(span=20, adjust=False).mean()) > 0).astype(int).diff().abs().iloc[-40:].sum())


def tendencia_1m(df: pd.DataFrame, direccion: str) -> dict | None:
    """Contexto de 1 min en el lado de la operacion: orden y pendiente de las EMAs y posicion en 3 h."""
    m = df.resample("1min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(m) < 60:
        return None
    e20, e50 = (m["close"].ewm(span=n, adjust=False).mean() for n in (20, 50))
    d = 1 if direccion == "CALL" else -1
    hi, lo, c = float(m["high"].max()), float(m["low"].min()), float(m["close"].iloc[-1])
    pos = (c - lo) / (hi - lo) if hi > lo else 0.5
    return {"orden": bool(d * (e20.iloc[-1] - e50.iloc[-1]) > 0),
            "pendiente": bool(d * (e20.iloc[-1] - e20.iloc[-6]) > 0),
            "sobre_e50": bool(d * (c - e50.iloc[-1]) > 0),
            "pos_3h": pos if d > 0 else 1 - pos}


def revisar(df: pd.DataFrame, direccion: str) -> dict | None:
    if len(df) < NIVEL_VELAS + 2:
        return None
    u, a = df.iloc[-1], df.iloc[-2]
    atr = float((df["high"] - df["low"]).iloc[-ATR_VELAS - 1:-1].mean())
    if atr <= 0:
        return None
    w = df.iloc[-RANGO_VELAS:]
    hi, lo = float(w["high"].max()), float(w["low"].min())
    pos = (u.close - lo) / (hi - lo) if hi > lo else 0.5
    previas = df.iloc[-NIVEL_VELAS - 1:-1]
    e20 = df["close"].ewm(span=20, adjust=False).mean().iloc[-RETROCESO_VELAS:]
    r = df.iloc[-RETROCESO_VELAS:]
    res, sop = float(previas["high"].max()), float(previas["low"].min())
    swing = df.iloc[-SWING_VELAS:]
    if direccion == "CALL":
        base = float(swing["low"].min())
        return {"confirma": bool(u.close > u.open), "confirma_fuerte": bool(u.close > u.open and u.close > a.high),
                "primera": bool(u.close > u.open and a.close <= a.open),
                "pos": pos, "pos_lado": pos, "espacio_atr": (res - u.close) / atr,
                "pos30": (u.close - sop) / (res - sop) if res > sop else 0.5,
                "avance": (u.close - base) / (res - base) if res > base else 1.0,
                "toco_e20": bool((r["low"] <= e20 + TOQUE_ATR * atr).any())}
    base = float(swing["high"].max())
    return {"confirma": bool(u.close < u.open), "confirma_fuerte": bool(u.close < u.open and u.close < a.low),
            "primera": bool(u.close < u.open and a.close >= a.open),
            "pos": pos, "pos_lado": 1 - pos, "espacio_atr": (u.close - sop) / atr,
            "pos30": (res - u.close) / (res - sop) if res > sop else 0.5,
            "avance": (base - u.close) / (base - sop) if base > sop else 1.0,
            "toco_e20": bool((r["high"] >= e20 - TOQUE_ATR * atr).any())}
