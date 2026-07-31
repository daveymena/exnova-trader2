# -*- coding: utf-8 -*-
"""
Indicadores tecnicos, implementados una sola vez y compartidos por todas las
estrategias del playbook.

Se calculan sobre numpy/pandas sin dependencias externas para que el backtest
no arrastre `ta` ni `talib`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window).mean()


def smma(s: pd.Series, window: int) -> pd.Series:
    """Media suavizada de Wilder, la que usa el Alligator."""
    return s.ewm(alpha=1 / window, adjust=False).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Devuelve (linea_macd, linea_senal, histograma) con los periodos 12/26/9."""
    line = ema(s, fast) - ema(s, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def stochastic(df: pd.DataFrame, k_period: int = 14, smooth_k: int = 3,
               smooth_d: int = 3):
    """Estocastico (14,3,3): devuelve (%K, %D)."""
    low = df["low"].rolling(k_period).min()
    high = df["high"].rolling(k_period).max()
    raw_k = 100 * (df["close"] - low) / (high - low).replace(0, np.nan)
    k = raw_k.rolling(smooth_k).mean()
    d = k.rolling(smooth_d).mean()
    return k, d


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def parabolic_sar(df: pd.DataFrame, step: float = 0.02,
                  max_step: float = 0.2) -> pd.Series:
    """
    Parabolic SAR (0.02 / 0.2).

    Es inherentemente iterativo: cada punto depende del anterior y del extremo
    alcanzado, asi que no admite una forma vectorizada limpia.
    """
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(df)
    out = np.full(n, np.nan)
    if n < 2:
        return pd.Series(out, index=df.index)

    bullish = high[1] >= high[0]
    af = step
    ep = high[1] if bullish else low[1]
    sar = low[0] if bullish else high[0]
    out[1] = sar

    for i in range(2, n):
        sar = sar + af * (ep - sar)

        if bullish:
            # El SAR nunca puede entrar en el rango de las dos velas previas.
            sar = min(sar, low[i - 1], low[i - 2])
            if low[i] < sar:                     # giro a bajista
                bullish, sar, ep, af = False, ep, low[i], step
            elif high[i] > ep:
                ep, af = high[i], min(af + step, max_step)
        else:
            sar = max(sar, high[i - 1], high[i - 2])
            if high[i] > sar:                    # giro a alcista
                bullish, sar, ep, af = True, ep, high[i], step
            elif low[i] < ep:
                ep, af = low[i], min(af + step, max_step)

        out[i] = sar

    return pd.Series(out, index=df.index)


def alligator(df: pd.DataFrame, jaw: int = 13, teeth: int = 8, lips: int = 5):
    """
    Alligator 13/8/5 sobre el precio medio (high+low)/2.

    Los desplazamientos canonicos son 8/5/3 barras hacia adelante. Se aplican
    con shift() porque sin ellos el indicador no es el que describe la fuente.
    """
    median = (df["high"] + df["low"]) / 2
    return (
        smma(median, jaw).shift(8),
        smma(median, teeth).shift(5),
        smma(median, lips).shift(3),
    )


def fractals(df: pd.DataFrame, wing: int = 2):
    """
    Fractales de Bill Williams: un maximo (o minimo) rodeado de `wing` barras
    menores a cada lado.

    Devuelve (fractal_alto, fractal_bajo) como series booleanas. Solo se marcan
    en la barra central, que se confirma `wing` barras despues; el consumidor
    debe tener eso en cuenta para no mirar al futuro.
    """
    high, low = df["high"], df["low"]
    up = pd.Series(True, index=df.index)
    down = pd.Series(True, index=df.index)
    for k in range(1, wing + 1):
        up &= (high > high.shift(k)) & (high > high.shift(-k))
        down &= (low < low.shift(k)) & (low < low.shift(-k))
    return up.fillna(False), down.fillna(False)


def swing_levels(df: pd.DataFrame, wing: int = 5) -> tuple[list[float], list[float]]:
    """
    Niveles de soporte y resistencia por pivotes confirmados.

    Solo se devuelven pivotes cuyas `wing` barras posteriores ya existen: un
    pivote sin confirmar seria mirar al futuro.
    """
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    resistances, supports = [], []
    for i in range(wing, n - wing):
        window_h = high[i - wing:i + wing + 1]
        window_l = low[i - wing:i + wing + 1]
        if high[i] == window_h.max():
            resistances.append(float(high[i]))
        if low[i] == window_l.min():
            supports.append(float(low[i]))
    return supports, resistances
