# -*- coding: utf-8 -*-
"""
Version vectorizada del playbook.

El motor de replay barra a barra es correcto pero es O(n x lookback): sobre
14.000 velas y 8 estrategias tarda horas. Aqui cada estrategia produce de una
sola vez la serie de entradas para todo el activo.

El resultado es identico porque todos los indicadores empleados son causales
(EMA, SMA, MACD, RSI, estocastico, SAR: cada valor depende solo del pasado),
asi que calcularlos sobre la serie completa no filtra informacion futura.

Las dos excepciones se tratan explicitamente:
  - fractales    -> se desplazan `wing` barras, que es cuando se confirman
  - niveles S/R  -> se construyen con pivotes ya confirmados y se desplazan

Cada estrategia devuelve un DataFrame con columnas 'call' y 'put' (booleanas),
alineado al indice del precio.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import (
    alligator, atr, ema, macd, parabolic_sar, rsi, sma, stochastic,
)

EXPIRY_MINUTES = 3


def _empty(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"call": False, "put": False}, index=df.index)


def triple_ema(df: pd.DataFrame) -> pd.DataFrame:
    """EMA 15/30/60: cruce 15x30 confirmado por la posicion respecto a la 60."""
    c = df["close"]
    e15, e30, e60 = ema(c, 15), ema(c, 30), ema(c, 60)
    up = (e15.shift(1) <= e30.shift(1)) & (e15 > e30) & (e15 > e60) & (e30 > e60)
    dn = (e15.shift(1) >= e30.shift(1)) & (e15 < e30) & (e15 < e60) & (e30 < e60)
    return pd.DataFrame({"call": up.fillna(False), "put": dn.fillna(False)})


def macd_sma200(df: pd.DataFrame) -> pd.DataFrame:
    """MACD 12/26/9 filtrado por la SMA 200."""
    c = df["close"]
    line, sig, _ = macd(c, 12, 26, 9)
    trend = sma(c, 200)
    up = (line.shift(1) <= sig.shift(1)) & (line > sig) & (c > trend)
    dn = (line.shift(1) >= sig.shift(1)) & (line < sig) & (c < trend)
    return pd.DataFrame({"call": up.fillna(False), "put": dn.fillna(False)})


def sar_stochastic(df: pd.DataFrame) -> pd.DataFrame:
    """Parabolic SAR 0.02/0.2 + estocastico 14,3,3 cruzando 30 / 70."""
    sar = parabolic_sar(df, 0.02, 0.2)
    k, _ = stochastic(df, 14, 3, 3)
    c = df["close"]
    up = (sar < c) & (k.shift(1) <= 30) & (k > 30)
    dn = (sar > c) & (k.shift(1) >= 70) & (k < 70)
    return pd.DataFrame({"call": up.fillna(False), "put": dn.fillna(False)})


def ma_crossover(df: pd.DataFrame) -> pd.DataFrame:
    """Cruce simple 5/20, la referencia basica del conjunto."""
    c = df["close"]
    f, s = sma(c, 5), sma(c, 20)
    up = (f.shift(1) <= s.shift(1)) & (f > s)
    dn = (f.shift(1) >= s.shift(1)) & (f < s)
    return pd.DataFrame({"call": up.fillna(False), "put": dn.fillna(False)})


def bollinger_rsi(df: pd.DataFrame) -> pd.DataFrame:
    """Cierre fuera de la banda 20/2 confirmado por RSI 14 en extremo."""
    c = df["close"]
    mid, sd = sma(c, 20), c.rolling(20).std()
    r = rsi(c, 14)
    up = (c < mid - 2 * sd) & (r < 30)
    dn = (c > mid + 2 * sd) & (r > 70)
    return pd.DataFrame({"call": up.fillna(False), "put": dn.fillna(False)})


def pullback_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Retroceso a la EMA21 a favor de la pendiente de la EMA50."""
    c, o = df["close"], df["open"]
    e21, e50 = ema(c, 21), ema(c, 50)
    a = atr(df, 14)
    rising, falling = e50 > e50.shift(5), e50 < e50.shift(5)
    up = rising & (c > e50) & (df["low"] <= e21 + 0.25 * a) & (c > o)
    dn = falling & (c < e50) & (df["high"] >= e21 - 0.25 * a) & (c < o)
    return pd.DataFrame({"call": up.fillna(False), "put": dn.fillna(False)})


def alligator_fractal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Alligator 13/8/5 + fractal de confirmacion.

    Los fractales se desplazan 2 barras: un fractal solo se conoce dos velas
    despues de su centro, y usarlo antes seria mirar al futuro.
    """
    jaw, teeth, lips = alligator(df, 13, 8, 5)
    a = atr(df, 14)
    c, o, hi, lo = df["close"], df["open"], df["high"], df["low"]

    diverged = (lips - jaw).abs() >= 0.3 * a
    aligned_up = (lips > teeth) & (teeth > jaw)
    aligned_dn = (lips < teeth) & (teeth < jaw)

    high_frac = ((hi > hi.shift(1)) & (hi > hi.shift(2)) &
                 (hi > hi.shift(-1)) & (hi > hi.shift(-2))).shift(2)
    low_frac = ((lo < lo.shift(1)) & (lo < lo.shift(2)) &
                (lo < lo.shift(-1)) & (lo < lo.shift(-2))).shift(2)
    recent_low = low_frac.fillna(False).infer_objects(copy=False).rolling(10).max().astype(bool)
    recent_high = high_frac.fillna(False).infer_objects(copy=False).rolling(10).max().astype(bool)

    up = diverged & aligned_up & (c > o) & (lo <= teeth) & recent_low
    dn = diverged & aligned_dn & (c < o) & (hi >= teeth) & recent_high
    return pd.DataFrame({"call": up.fillna(False), "put": dn.fillna(False)})


def support_resistance_stoch(df: pd.DataFrame, wing: int = 5) -> pd.DataFrame:
    """
    Soporte / resistencia por pivotes + estocastico en extremo.

    Los pivotes se desplazan `wing` barras: un pivote necesita `wing` velas
    posteriores para confirmarse, asi que antes de eso no existe.
    """
    hi, lo, c = df["high"], df["low"], df["close"]
    a = atr(df, 14)
    k, _ = stochastic(df, 14, 3, 3)

    win = 2 * wing + 1
    is_high = (hi == hi.rolling(win, center=True).max()).shift(wing)
    is_low = (lo == lo.rolling(win, center=True).min()).shift(wing)

    # Ultimo nivel confirmado disponible en cada instante.
    last_res = hi.where(is_high.fillna(False)).ffill()
    last_sup = lo.where(is_low.fillna(False)).ffill()

    near_sup = (c - last_sup).abs() <= 0.5 * a
    near_res = (c - last_res).abs() <= 0.5 * a

    up = near_sup & (k < 30)
    dn = near_res & (k > 70)
    return pd.DataFrame({"call": up.fillna(False), "put": dn.fillna(False)})


def support_resistance_refined(df: pd.DataFrame, wing: int = 5,
                               min_touches: int = 3) -> pd.DataFrame:
    """
    Version corregida de soporte/resistencia, segun lo que muestran los
    graficos de la fuente (no lo que dice su texto).

    Los graficos anotados revelan tres cosas que el texto no explicita y que
    cambian la regla por completo:

    1. La entrada NO es en el primer contacto con la zona. En ambos ejemplos
       hay tres circulos de rechazo previos y se entra en el siguiente toque.
    2. El estocastico no basta con que este en zona extrema: el circulo marca
       el instante en que %K CRUZA a %D. Es un giro confirmado, no un nivel.
    3. La vela de entrada perfora la zona con la mecha y cierra dentro. Es un
       rechazo, no un cierre al otro lado.

    La version basada solo en el texto usaba `k < 30` y 2 toques, que dispara
    mucho antes y en sitios donde el precio aun no ha girado.
    """
    hi, lo, c, o = df["high"], df["low"], df["close"], df["open"]
    a = atr(df, 14)
    k, d = stochastic(df, 14, 3, 3)

    win = 2 * wing + 1
    is_high = (hi == hi.rolling(win, center=True).max()).shift(wing).fillna(False)
    is_low = (lo == lo.rolling(win, center=True).min()).shift(wing).fillna(False)

    last_res = hi.where(is_high).ffill()
    last_sup = lo.where(is_low).ffill()
    tol = 0.5 * a

    # Cuantas veces se ha respetado ya esta zona: se cuentan pivotes previos
    # dentro de la tolerancia, en una ventana amplia.
    sup_touch = (lo - last_sup).abs() <= tol
    res_touch = (hi - last_res).abs() <= tol
    sup_count = sup_touch.rolling(120, min_periods=1).sum()
    res_count = res_touch.rolling(120, min_periods=1).sum()

    # Giro confirmado del estocastico desde el extremo.
    turn_up = (k.shift(1) <= d.shift(1)) & (k > d) & (k.shift(1) < 30)
    turn_dn = (k.shift(1) >= d.shift(1)) & (k < d) & (k.shift(1) > 70)

    # Rechazo: la mecha perfora la zona y el cuerpo cierra del lado correcto.
    reject_up = (lo <= last_sup + tol) & (c > last_sup) & (c > o)
    reject_dn = (hi >= last_res - tol) & (c < last_res) & (c < o)

    up = reject_up & turn_up & (sup_count >= min_touches)
    dn = reject_dn & turn_dn & (res_count >= min_touches)
    return pd.DataFrame({"call": up.fillna(False), "put": dn.fillna(False)})


PLAYBOOK = {
    "triple_ema_15_30_60": triple_ema,
    "macd_12_26_9_sma200": macd_sma200,
    "parabolic_sar_stochastic": sar_stochastic,
    "soporte_resistencia_stoch": support_resistance_stoch,
    "sr_refinada_graficos": support_resistance_refined,
    "alligator_fractal": alligator_fractal,
    "ma_crossover_5_20": ma_crossover,
    "bollinger_rsi": bollinger_rsi,
    "pullback_tendencia": pullback_trend,
}


def evaluate_signals(df: pd.DataFrame, sig: pd.DataFrame, expiry_min: int,
                     min_gap: int = 3) -> pd.DataFrame:
    """
    Resuelve cada senal: se entra en la apertura de la vela siguiente y se
    cierra `expiry_min` velas despues. Se descartan entradas demasiado juntas
    para no contar la misma senal varias veces.
    """
    entry = df["open"].shift(-1)
    exit_ = df["close"].shift(-(1 + expiry_min))

    direction = pd.Series(np.where(sig["call"], "CALL",
                          np.where(sig["put"], "PUT", "")), index=df.index)
    active = direction != ""

    # Espaciado minimo entre entradas.
    idx = np.flatnonzero(active.to_numpy())
    keep = []
    last = -10 ** 9
    for i in idx:
        if i - last >= min_gap:
            keep.append(i)
            last = i
    mask = np.zeros(len(df), dtype=bool)
    mask[keep] = True

    valid = mask & entry.notna().to_numpy() & exit_.notna().to_numpy()
    win = np.where(direction == "CALL", exit_ > entry, exit_ < entry)
    tie = (exit_ == entry).to_numpy()
    valid &= ~tie

    return pd.DataFrame({
        "direction": direction[valid],
        "win": pd.Series(win, index=df.index)[valid],
    })
