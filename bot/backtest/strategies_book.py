# -*- coding: utf-8 -*-
"""
Playbook de estrategias investigadas, listas para backtestear.

Cada estrategia reproduce literalmente las reglas de su fuente, con los
periodos exactos que esta publica. Donde la fuente es vaga ("el precio se
acerca al nivel", "las lineas divergen") se elige un criterio numerico
explicito y se documenta como decision propia, para que quede claro que ESA
parte no viene de la fuente y es la primera candidata a revisarse si la
estrategia falla.

Fuentes: opciones-binarias.mx/estrategias/ (10 articulos) y el material de
SlideShare aportado por el usuario.

Todas operan sobre M1 con expiracion de 3 minutos, que es lo que recomiendan
las fuentes de forma unanime.
"""
from __future__ import annotations

import pandas as pd

from .indicators import (
    alligator, atr, ema, fractals, macd, parabolic_sar, rsi, sma,
    stochastic, swing_levels,
)
from .replay import Signal

# Solo se recalculan indicadores sobre la cola de la serie: recomputar 14.000
# barras en cada paso convertiria el backtest en O(n^2).
LOOKBACK = 600

# Expiracion recomendada por las fuentes, en segundos.
EXPIRY = 180


def _tail(frames: dict[int, pd.DataFrame]) -> pd.DataFrame | None:
    df = frames.get(60)
    if df is None or len(df) < 250:
        return None
    return df.iloc[-LOOKBACK:]


class TripleEMA:
    """
    Triple EMA 15 / 30 / 60.

    CALL: EMA15 cruza AL ALZA la EMA30 y ambas estan por encima de la EMA60.
    PUT : EMA15 cruza A LA BAJA la EMA30 y ambas estan por debajo de la EMA60.

    El filtro de la EMA60 es obligatorio en la fuente: un cruce sin el es
    senal contra-tendencia y se descarta.
    """
    name = "triple_ema_15_30_60"

    def evaluate(self, frames, now):
        df = _tail(frames)
        if df is None:
            return None
        c = df["close"]
        e15, e30, e60 = ema(c, 15), ema(c, 30), ema(c, 60)

        cross_up = e15.iloc[-2] <= e30.iloc[-2] and e15.iloc[-1] > e30.iloc[-1]
        cross_dn = e15.iloc[-2] >= e30.iloc[-2] and e15.iloc[-1] < e30.iloc[-1]

        if cross_up and e15.iloc[-1] > e60.iloc[-1] and e30.iloc[-1] > e60.iloc[-1]:
            return Signal("CALL", EXPIRY, "triple_ema_call")
        if cross_dn and e15.iloc[-1] < e60.iloc[-1] and e30.iloc[-1] < e60.iloc[-1]:
            return Signal("PUT", EXPIRY, "triple_ema_put")
        return None


class MacdSma200:
    """
    MACD (12,26,9) filtrado por SMA 200.

    CALL: precio por encima de la SMA200 y la linea MACD cruza al alza su senal.
    PUT : precio por debajo de la SMA200 y la linea MACD cruza a la baja.
    """
    name = "macd_12_26_9_sma200"

    def evaluate(self, frames, now):
        df = _tail(frames)
        if df is None:
            return None
        c = df["close"]
        line, sig, _ = macd(c, 12, 26, 9)
        trend = sma(c, 200)
        if pd.isna(trend.iloc[-1]):
            return None

        cross_up = line.iloc[-2] <= sig.iloc[-2] and line.iloc[-1] > sig.iloc[-1]
        cross_dn = line.iloc[-2] >= sig.iloc[-2] and line.iloc[-1] < sig.iloc[-1]

        if cross_up and c.iloc[-1] > trend.iloc[-1]:
            return Signal("CALL", EXPIRY, "macd_sma200_call")
        if cross_dn and c.iloc[-1] < trend.iloc[-1]:
            return Signal("PUT", EXPIRY, "macd_sma200_put")
        return None


class ParabolicStochastic:
    """
    Parabolic SAR (0.02/0.2) + Estocastico (14,3,3).

    CALL: puntos del SAR por DEBAJO del precio y el %K cruza el nivel 30 al alza.
    PUT : puntos del SAR por ENCIMA del precio y el %K cruza el nivel 70 a la baja.

    Decision propia: la fuente no aclara si el cruce de 30/70 lo hace %K o %D.
    Se usa %K por ser la linea rapida y la que dispara antes.
    """
    name = "parabolic_sar_stochastic"

    def evaluate(self, frames, now):
        df = _tail(frames)
        if df is None:
            return None
        sar = parabolic_sar(df, 0.02, 0.2)
        k, _ = stochastic(df, 14, 3, 3)
        if pd.isna(sar.iloc[-1]) or pd.isna(k.iloc[-2]):
            return None

        price = df["close"].iloc[-1]
        up_through_30 = k.iloc[-2] <= 30 < k.iloc[-1]
        dn_through_70 = k.iloc[-2] >= 70 > k.iloc[-1]

        if sar.iloc[-1] < price and up_through_30:
            return Signal("CALL", EXPIRY, "sar_stoch_call")
        if sar.iloc[-1] > price and dn_through_70:
            return Signal("PUT", EXPIRY, "sar_stoch_put")
        return None


class SupportResistanceStochastic:
    """
    Soporte y resistencia confirmados + Estocastico.

    CALL: precio en zona de soporte y estocastico por debajo de 30.
    PUT : precio en zona de resistencia y estocastico por encima de 70.

    La fuente insiste en dos cosas que se respetan aqui: se opera una ZONA, no
    una linea, y el nivel debe haber sido rechazado varias veces.

    Decisiones propias: la zona es +-0.5 ATR alrededor del nivel, y se exige un
    minimo de 2 toques previos. La fuente dice "2-3 rechazos" sin fijar la
    tolerancia.
    """
    name = "soporte_resistencia_stoch"

    TOUCH_TOLERANCE_ATR = 0.5
    MIN_TOUCHES = 2

    def evaluate(self, frames, now):
        df = _tail(frames)
        if df is None:
            return None
        a = atr(df, 14).iloc[-1]
        if pd.isna(a) or a <= 0:
            return None

        supports, resistances = swing_levels(df, wing=5)
        if not supports and not resistances:
            return None

        price = df["close"].iloc[-1]
        k, _ = stochastic(df, 14, 3, 3)
        if pd.isna(k.iloc[-1]):
            return None
        tol = self.TOUCH_TOLERANCE_ATR * a

        def touches(levels: list[float], level: float) -> int:
            return sum(1 for x in levels if abs(x - level) <= tol)

        near_sup = [s for s in supports if abs(price - s) <= tol]
        if near_sup and k.iloc[-1] < 30:
            level = max(near_sup)
            if touches(supports, level) >= self.MIN_TOUCHES:
                return Signal("CALL", EXPIRY, "sr_soporte_call")

        near_res = [r for r in resistances if abs(price - r) <= tol]
        if near_res and k.iloc[-1] > 70:
            level = min(near_res)
            if touches(resistances, level) >= self.MIN_TOUCHES:
                return Signal("PUT", EXPIRY, "sr_resistencia_put")
        return None


class AlligatorFractal:
    """
    Alligator (13/8/5) + Fractal.

    CALL: labios por encima de dientes y estos por encima de mandibulas, con
          las lineas separadas; el precio retrocede hasta labios/dientes y
          rebota; hay un fractal bajo reciente.
    PUT : la imagen simetrica.

    La fuente marca esta estrategia como parcialmente subjetiva ("las lineas
    divergen", "el precio empieza a subir"). Aqui se traduce asi:
      - divergencia: separacion labios-mandibulas >= 0.3 ATR
      - retroceso  : el minimo de la vela toco la zona de labios/dientes
      - rebote     : la ultima vela cierra al alza
      - fractal    : hay un fractal bajo en las ultimas 10 barras confirmadas
    Todo eso es decision propia y es lo primero que habria que revisar.
    """
    name = "alligator_fractal"

    MIN_DIVERGENCE_ATR = 0.3
    FRACTAL_WINDOW = 10

    def evaluate(self, frames, now):
        df = _tail(frames)
        if df is None:
            return None
        jaw, teeth, lips = alligator(df, 13, 8, 5)
        if pd.isna(jaw.iloc[-1]) or pd.isna(lips.iloc[-1]):
            return None
        a = atr(df, 14).iloc[-1]
        if pd.isna(a) or a <= 0:
            return None

        spread = abs(lips.iloc[-1] - jaw.iloc[-1])
        if spread < self.MIN_DIVERGENCE_ATR * a:
            return None                       # alligator "dormido": no se opera

        up_frac, dn_frac = fractals(df, wing=2)
        # Un fractal solo esta confirmado 2 barras despues de su centro.
        confirmed = slice(-(self.FRACTAL_WINDOW + 2), -2)
        last = df.iloc[-1]
        bullish_candle = last["close"] > last["open"]

        aligned_up = lips.iloc[-1] > teeth.iloc[-1] > jaw.iloc[-1]
        aligned_dn = lips.iloc[-1] < teeth.iloc[-1] < jaw.iloc[-1]

        if aligned_up and bullish_candle and last["low"] <= teeth.iloc[-1]:
            if dn_frac.iloc[confirmed].any():
                return Signal("CALL", EXPIRY, "alligator_call")
        if aligned_dn and not bullish_candle and last["high"] >= teeth.iloc[-1]:
            if up_frac.iloc[confirmed].any():
                return Signal("PUT", EXPIRY, "alligator_put")
        return None


class MaCrossover:
    """
    Cruce simple de medias moviles (rapida 5 / lenta 20).

    Es la estrategia mas basica del conjunto y sirve de referencia: si algo mas
    elaborado no la supera, esa elaboracion no esta aportando nada.
    """
    name = "ma_crossover_5_20"

    def evaluate(self, frames, now):
        df = _tail(frames)
        if df is None:
            return None
        c = df["close"]
        fast, slow = sma(c, 5), sma(c, 20)
        if pd.isna(slow.iloc[-2]):
            return None
        if fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]:
            return Signal("CALL", EXPIRY, "ma_cross_call")
        if fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]:
            return Signal("PUT", EXPIRY, "ma_cross_put")
        return None


class BollingerRsi:
    """
    Rebote en banda de Bollinger (20, 2) confirmado por RSI(14).

    CALL: cierre por debajo de la banda inferior y RSI < 30.
    PUT : cierre por encima de la banda superior y RSI > 70.

    Viene del material de SlideShare y del modulo bollinger_rsi_real.py que ya
    existia en el repo.
    """
    name = "bollinger_rsi"

    def evaluate(self, frames, now):
        df = _tail(frames)
        if df is None:
            return None
        c = df["close"]
        mid = sma(c, 20)
        sd = c.rolling(20).std()
        if pd.isna(sd.iloc[-1]) or sd.iloc[-1] == 0:
            return None
        upper, lower = mid + 2 * sd, mid - 2 * sd
        r = rsi(c, 14)
        if pd.isna(r.iloc[-1]):
            return None

        if c.iloc[-1] < lower.iloc[-1] and r.iloc[-1] < 30:
            return Signal("CALL", EXPIRY, "bollinger_rsi_call")
        if c.iloc[-1] > upper.iloc[-1] and r.iloc[-1] > 70:
            return Signal("PUT", EXPIRY, "bollinger_rsi_put")
        return None


class PullbackTrend:
    """
    Pullback a favor de la tendencia.

    CALL: EMA50 al alza, el precio retrocede hasta la EMA21 y rebota.
    PUT : simetrico.

    La fuente describe el concepto sin dar periodos; 21/50 es decision propia.
    """
    name = "pullback_tendencia"

    def evaluate(self, frames, now):
        df = _tail(frames)
        if df is None:
            return None
        c = df["close"]
        e21, e50 = ema(c, 21), ema(c, 50)
        if pd.isna(e50.iloc[-6]):
            return None
        a = atr(df, 14).iloc[-1]
        if pd.isna(a) or a <= 0:
            return None

        last = df.iloc[-1]
        rising = e50.iloc[-1] > e50.iloc[-6]
        falling = e50.iloc[-1] < e50.iloc[-6]
        touched_up = last["low"] <= e21.iloc[-1] + 0.25 * a
        touched_dn = last["high"] >= e21.iloc[-1] - 0.25 * a

        if rising and c.iloc[-1] > e50.iloc[-1] and touched_up and last["close"] > last["open"]:
            return Signal("CALL", EXPIRY, "pullback_call")
        if falling and c.iloc[-1] < e50.iloc[-1] and touched_dn and last["close"] < last["open"]:
            return Signal("PUT", EXPIRY, "pullback_put")
        return None


def all_strategies() -> list:
    """El playbook completo, en el orden en que se investigo."""
    return [
        TripleEMA(),
        MacdSma200(),
        ParabolicStochastic(),
        SupportResistanceStochastic(),
        AlligatorFractal(),
        MaCrossover(),
        BollingerRsi(),
        PullbackTrend(),
    ]
