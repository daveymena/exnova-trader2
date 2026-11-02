# -*- coding: utf-8 -*-
"""
Traduccion fiel del indicador "Azura Conteo v10" (script Lua de Exnova / IQ
Option, ver Downloads/newscript.txt) para poder medirlo sin look-ahead.

Reglas del script original:
  buffer1 = SMA(fuente, 1) - SMA(fuente, 34)      # "MACD artesanal"
  buffer2 = WMA(buffer1, 5)                       # linea de senal
  CALL: buffer1 cruza por encima de buffer2  y  EMA4(close) > EMA8(close)
  PUT : buffer1 cruza por debajo de buffer2  y  EMA4(close) < EMA8(close)

Con MA Fast = 1 la SMA rapida es la propia fuente, asi que buffer1 es la
distancia del precio a su media de 34 velas.

El script cuenta dos marcadores en el grafico:
  ACT -> color de la MISMA vela que genero la senal. No es operable: la senal
         solo existe cuando esa vela ya cerro, y el cruce alcista casi exige
         una vela verde. Es un contador inflado por construccion.
  SIG -> color de la vela SIGUIENTE. Es lo que se puede operar de verdad
         (entrar a la apertura de la siguiente vela con expiracion 1 vela).

Todos los indicadores son causales, asi que vectorizar no filtra futuro.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import ema, sma

# input.string_selection(inputs.titles): el indice 5 del script. En el lenguaje
# de scripts de IQ/Exnova la lista es open, high, low, close, hl2, hlc3, ohlc4,
# por lo que el valor por defecto corresponde a HL2. Se deja configurable.
SOURCES = {
    "open": lambda d: d["open"],
    "high": lambda d: d["high"],
    "low": lambda d: d["low"],
    "close": lambda d: d["close"],
    "hl2": lambda d: (d["high"] + d["low"]) / 2,
    "hlc3": lambda d: (d["high"] + d["low"] + d["close"]) / 3,
    "ohlc4": lambda d: (d["open"] + d["high"] + d["low"] + d["close"]) / 4,
}


def wma(s: pd.Series, window: int) -> pd.Series:
    """Media ponderada lineal: pesos 1..n, el mas reciente pesa mas."""
    w = np.arange(1, window + 1, dtype=float)
    return s.rolling(window).apply(lambda x: np.dot(x, w) / w.sum(), raw=True)


def azura_signals(df: pd.DataFrame, source: str = "hl2", fast: int = 1,
                  slow: int = 34, signal: int = 5, ema_fast: int = 4,
                  ema_slow: int = 8) -> pd.DataFrame:
    """Columnas booleanas 'call' / 'put' en la vela donde el script pinta la flecha."""
    src = SOURCES[source](df)
    b1 = sma(src, fast) - sma(src, slow)
    b2 = wma(b1, signal)
    bull = (b1 > b2) & (b1.shift(1) < b2.shift(1))
    bear = (b1 < b2) & (b1.shift(1) > b2.shift(1))

    ef, es = ema(df["close"], ema_fast), ema(df["close"], ema_slow)
    call = (bull & (ef > es)).fillna(False)
    put = (bear & (ef < es)).fillna(False)
    return pd.DataFrame({"call": call, "put": put}, index=df.index)


def script_counters(df: pd.DataFrame, sig: pd.DataFrame) -> dict[str, int]:
    """Reproduce los contadores G/P que el script dibuja (ACT y SIG)."""
    green, red = df["close"] > df["open"], df["close"] < df["open"]
    call, put = sig["call"], sig["put"]
    pc, pp = call.shift(1, fill_value=False), put.shift(1, fill_value=False)
    return {
        "act_win": int(((call & green) | (put & red)).sum()),
        "act_loss": int(((call & red) | (put & green)).sum()),
        "sig_win": int(((pc & green) | (pp & red)).sum()),
        "sig_loss": int(((pc & red) | (pp & green)).sum()),
    }


def evaluate_bars(df: pd.DataFrame, sig: pd.DataFrame, expiry_bars: int,
                  tf_seconds: int, min_gap: int = 1) -> pd.DataFrame:
    """
    Resuelve cada senal como una binaria real: entrada a la apertura de la
    vela siguiente, salida al cierre de la vela `expiry_bars` despues.
    Generaliza `vectorized.evaluate_signals` a cualquier timeframe.
    """
    if expiry_bars <= 0 or min_gap < 1:
        raise ValueError("expiry_bars y min_gap deben ser positivos")
    if not sig.index.equals(df.index):
        raise ValueError("Las senales deben alinearse con las velas")

    entry = df["open"].shift(-1)
    exit_ = df["close"].shift(-expiry_bars)
    direction = pd.Series(np.where(sig["call"], "CALL",
                          np.where(sig["put"], "PUT", "")), index=df.index)

    idx = np.flatnonzero((direction != "").to_numpy())
    keep, last = [], -10 ** 9
    for i in idx:
        if i - last >= min_gap:
            keep.append(i)
            last = i
    mask = np.zeros(len(df), dtype=bool)
    mask[keep] = True

    times = df.index.to_series()
    contiguous = (times.shift(-expiry_bars) - times ==
                  pd.Timedelta(seconds=expiry_bars * tf_seconds)).to_numpy()
    valid = mask & entry.notna().to_numpy() & exit_.notna().to_numpy() & contiguous
    valid &= ~(exit_ == entry).to_numpy()
    win = np.where(direction == "CALL", exit_ > entry, exit_ < entry)

    return pd.DataFrame({
        "direction": direction[valid],
        "win": pd.Series(win, index=df.index)[valid],
        "entry_time": times.shift(-1)[valid],
        "hour": times.shift(-1)[valid].dt.hour,
    })
