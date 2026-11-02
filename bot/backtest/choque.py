# -*- coding: utf-8 -*-
"""
Estrategia "Choque": reversion tras una vela M1 desproporcionada.

Regla (scripts/lab_choque.py, elegida en desarrollo y confirmada en holdout):
  una vela cerrada cuyo cuerpo mide >= `thr` veces el ATR14 de las velas
  ANTERIORES es una sobrerreaccion; se opera en contra en la apertura de la
  vela siguiente (vela alcista -> PUT, bajista -> CALL).

Medido con 60 dias M1 de 10 activos reales de IQ Option:
  >= 3 ATR, 5 min: 57.9% desarrollo (n=900), 55.4% holdout (n=572).
Solo mercado real: los OTC son paseo aleatorio.
"""
from __future__ import annotations

import pandas as pd

from .indicators import atr


def choque_signals(df: pd.DataFrame, thr: float = 3.0) -> pd.DataFrame:
    """Columnas booleanas 'call' / 'put' en la vela de choque."""
    body = (df["close"] - df["open"]) / atr(df, 14).shift(1)
    return pd.DataFrame({"call": (body <= -thr).fillna(False),
                         "put": (body >= thr).fillna(False)}, index=df.index)


def choque_features(df: pd.DataFrame) -> dict:
    """Contexto de la ultima vela, para filtrar despues con datos en vivo.

    body_atr   tamano del choque (con signo) en ATRs previos
    rechazo    mecha en contra del cuerpo / rango: el giro ya empezo dentro de la vela
    vol_regimen ATR14 previo / su media de 60 velas: mercado tranquilo (<1) o agitado (>1)
    previas_atr movimiento de las 5 velas anteriores en ATRs: choque aislado o en tendencia
    """
    a14 = atr(df, 14).shift(1)
    o, h, l, c = (df[k].iloc[-1] for k in ("open", "high", "low", "close"))
    a = a14.iloc[-1]
    rng = h - l
    wick = (h - max(o, c)) if c > o else (min(o, c) - l)
    prev = df["close"].iloc[-2] - df["open"].iloc[-6]
    return {"body_atr": round(float((c - o) / a), 2),
            "rechazo": round(float(wick / rng), 2) if rng else 0.0,
            "vol_regimen": round(float(a / a14.iloc[-60:].mean()), 2),
            "previas_atr": round(float(prev / a), 2)}
