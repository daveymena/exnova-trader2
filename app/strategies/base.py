# -*- coding: utf-8 -*-
"""Contrato de estrategia + indicadores compartidos.

POR QUE UNA BASE COMUN
----------------------
Cada estrategia calculaba su propio ATR y su propia EMA con implementaciones
ligeramente distintas (`sr_bounce._compute_atr`, `breakout_direct`, etc.). Eso
tiene dos costes: codigo duplicado que diverge, y algo peor -- dos estrategias
que dicen "ATR" pero miden cosas distintas no se pueden comparar entre si, y el
motor de mejora continua vive de compararlas.

Aqui hay UNA implementacion de cada indicador, probada, y todas las estrategias
la usan.

CONTRATO DE CAUSALIDAD
----------------------
`evaluate()` recibe listas de velas que el `MarketFeed` YA filtro: solo velas
CERRADAS respecto a `feed.now()`. Una estrategia no puede hacer look-ahead
aunque quiera, porque la informacion futura no le llega. Es la diferencia con
el backtester anterior, que decidia el resultado del trade con la misma vela
que generaba la senal (punto 10 de la auditoria).

Por eso la regla es: `evaluate()` NUNCA mira el reloj ni pide datos por su
cuenta. Solo analiza lo que recibe. Eso la hace testeable en aislamiento y
reutilizable en backtest y en vivo sin cambios.

CONTRATO DE SALIDA
------------------
Siempre el mismo dict, siempre con estas claves:
    direction         Direction (CALL/PUT/NO_TRADE)
    confidence        float 0..1 -- probabilidad subjetiva, NO una promesa
    strategy          str
    market_regime     MarketRegime
    entry_rationale   str  -- por que entra, legible
    invalidation      str  -- que harian que la senal fuera falsa
    features          dict -- numeros crudos, para el motor de aprendizaje
    opportunity_score float
    skip_entry_timing bool -- solo si la estrategia YA confirma el timing

`confidence` merece una advertencia: es la opinion de la estrategia, no una
probabilidad calibrada. Lo que decide si se opera es el `SetupEvaluator` con su
muestra real. Un `confidence` de 0.95 no vale nada si el setup lleva 200
operaciones al 51%.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Optional, Sequence

from app.data.schemas import Candle, Direction, MarketRegime


# ===========================================================================
# Indicadores (una sola implementacion para todo el proyecto)
# ===========================================================================

def sma(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> list[float]:
    """EMA completa. Se devuelve la serie porque varias estrategias necesitan
    la pendiente, no solo el ultimo valor."""
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def ema(values: Sequence[float], period: int) -> Optional[float]:
    series = ema_series(values, period)
    return series[-1] if series else None


def ema_slope(values: Sequence[float], period: int,
              lookback: int = 3) -> Optional[float]:
    """Pendiente normalizada de la EMA: (ema_now - ema_prev) / ema_prev."""
    series = ema_series(values, period)
    if len(series) <= lookback:
        return None
    prev = series[-1 - lookback]
    if not prev:
        return None
    return (series[-1] - prev) / prev


def rsi(values: Sequence[float], period: int = 14) -> Optional[float]:
    """RSI de Wilder (suavizado RMA, no SMA simple).

    La diferencia importa: el RSI "de SMA" que implementan muchos bots da
    lecturas mas nerviosas y cruza 70/30 constantemente, generando senales
    donde Wilder no las ve.
    """
    if len(values) < period + 1 or period <= 0:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def true_range(candles: Sequence[Candle]) -> list[float]:
    if not candles:
        return []
    out = [candles[0].high - candles[0].low]
    for i in range(1, len(candles)):
        c, prev = candles[i], candles[i - 1]
        out.append(max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close)))
    return out


def atr(candles: Sequence[Candle], period: int = 14) -> Optional[float]:
    """ATR de Wilder sobre la serie de velas."""
    tr = true_range(candles)
    if len(tr) < period or period <= 0:
        return None
    value = sum(tr[:period]) / period
    for t in tr[period:]:
        value = (value * (period - 1) + t) / period
    return value


def atr_percentile(candles: Sequence[Candle], period: int = 14) -> Optional[float]:
    """Percentil del ATR actual dentro de su propio historico (0..1)."""
    tr = true_range(candles)
    if len(tr) < period * 2:
        return None
    series = []
    value = sum(tr[:period]) / period
    series.append(value)
    for t in tr[period:]:
        value = (value * (period - 1) + t) / period
        series.append(value)
    if not series:
        return None
    current = series[-1]
    below = sum(1 for v in series[:-1] if v < current)
    return below / max(1, len(series) - 1)


def adx(candles: Sequence[Candle], period: int = 14) -> Optional[float]:
    """ADX de Wilder. Mide FUERZA de tendencia, no direccion."""
    if len(candles) < period * 2 + 1:
        return None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        up = c.high - p.high
        down = p.low - c.low
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))

    def wilder(series: Sequence[float]) -> list[float]:
        out = [sum(series[:period]) / period]
        for v in series[period:]:
            out.append((out[-1] * (period - 1) + v) / period)
        return out

    atr_s = wilder(trs)
    plus_s = wilder(plus_dm)
    minus_s = wilder(minus_dm)
    n = min(len(atr_s), len(plus_s), len(minus_s))
    dxs = []
    for i in range(n):
        if atr_s[i] == 0:
            continue
        pdi = 100 * plus_s[i] / atr_s[i]
        mdi = 100 * minus_s[i] / atr_s[i]
        denom = pdi + mdi
        if denom > 0:
            dxs.append(100 * abs(pdi - mdi) / denom)
    if len(dxs) < period:
        return None
    value = sum(dxs[:period]) / period
    for d in dxs[period:]:
        value = (value * (period - 1) + d) / period
    return value


def directional_movement(candles: Sequence[Candle], period: int = 14
                         ) -> tuple[Optional[float], Optional[float]]:
    """(+DI, -DI) de Wilder. Da la DIRECCION que el ADX solo mide en fuerza."""
    if len(candles) < period * 2 + 1:
        return None, None
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        up = c.high - p.high
        down = p.low - c.low
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        trs.append(max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)))

    def wilder(series):
        out = [sum(series[:period]) / period]
        for v in series[period:]:
            out.append((out[-1] * (period - 1) + v) / period)
        return out

    atr_s, plus_s, minus_s = wilder(trs), wilder(plus_dm), wilder(minus_dm)
    if not atr_s or atr_s[-1] == 0:
        return None, None
    return 100 * plus_s[-1] / atr_s[-1], 100 * minus_s[-1] / atr_s[-1]


def bollinger(values: Sequence[float], period: int = 20,
              num_std: float = 2.0) -> Optional[tuple[float, float, float]]:
    """(banda superior, media, banda inferior). None sin muestra suficiente."""
    if len(values) < period:
        return None
    window = values[-period:]
    mid = sum(window) / period
    var = sum((v - mid) ** 2 for v in window) / max(1, period - 1)
    sd = math.sqrt(var)
    return mid + num_std * sd, mid, mid - num_std * sd


def stochastic(candles: Sequence[Candle], k_period: int = 14,
               d_period: int = 3) -> tuple[Optional[float], Optional[float]]:
    """(%K, %D). None sin muestra."""
    if len(candles) < k_period + d_period:
        return None, None
    ks = []
    for i in range(k_period - 1, len(candles)):
        window = candles[i - k_period + 1:i + 1]
        hi = max(c.high for c in window)
        lo = min(c.low for c in window)
        ks.append(50.0 if hi == lo else 100 * (candles[i].close - lo) / (hi - lo))
    if len(ks) < d_period:
        return None, None
    return ks[-1], sum(ks[-d_period:]) / d_period


def swing_points(candles: Sequence[Candle], left: int = 2,
                 right: int = 2) -> tuple[list[float], list[float]]:
    """(swing highs, swing lows) fractales.

    Un swing high es una vela con `left` velas mas bajas antes y `right` despues.
    Se excluyen las ultimas `right` velas porque su condicion aun no esta
    confirmada: contar un fractal sin cerrar es una forma sutil de look-ahead.
    """
    highs, lows = [], []
    if len(candles) < left + right + 1:
        return highs, lows
    for i in range(left, len(candles) - right):
        window = candles[i - left:i + right + 1]
        c = candles[i]
        if all(o.high <= c.high for o in window if o is not c):
            highs.append(c.high)
        if all(o.low >= c.low for o in window if o is not c):
            lows.append(c.low)
    return highs, lows


def candle_patterns(candles: Sequence[Candle]) -> dict:
    """Patrones de velas sobre las 3 ultimas. Devuelve flags, no opiniones."""
    if len(candles) < 3:
        return {}
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    body3 = c3.body
    rng3 = c3.range or 1e-12

    bullish_engulfing = (c2.close < c2.open and c3.close > c3.open
                         and c3.close >= c2.open and c3.open <= c2.close)
    bearish_engulfing = (c2.close > c2.open and c3.close < c3.open
                         and c3.open >= c2.close and c3.close <= c2.open)
    hammer = (c3.lower_wick >= 2.0 * body3 and c3.upper_wick <= body3
              and body3 / rng3 < 0.4)
    shooting_star = (c3.upper_wick >= 2.0 * body3 and c3.lower_wick <= body3
                     and body3 / rng3 < 0.4)
    doji = body3 / rng3 < 0.12
    morning_star = (c1.close < c1.open and c2.body < c1.body * 0.5
                    and c3.close > c3.open and c3.close > (c1.open + c1.close) / 2)
    evening_star = (c1.close > c1.open and c2.body < c1.body * 0.5
                    and c3.close < c3.open and c3.close < (c1.open + c1.close) / 2)
    return {
        "bullish_engulfing": bullish_engulfing,
        "bearish_engulfing": bearish_engulfing,
        "hammer": hammer,
        "shooting_star": shooting_star,
        "doji": doji,
        "morning_star": morning_star,
        "evening_star": evening_star,
        "last_body_pct": round(c3.body_pct, 4),
        "last_range": c3.range,
        "last_upper_wick": c3.upper_wick,
        "last_lower_wick": c3.lower_wick,
    }


def closes(candles: Sequence[Candle]) -> list[float]:
    return [c.close for c in candles]


def is_stale(candle: Candle) -> bool:
    """Vela sin informacion: plana o marcada como stale/duplicada."""
    from app.data.schemas import DataQuality
    return (candle.quality in (DataQuality.STALE, DataQuality.MISSING, DataQuality.DUPLICATE)
            or (candle.high == candle.low == candle.open == candle.close))


# ===========================================================================
# Contrato de estrategia
# ===========================================================================

class Strategy(ABC):
    """Interfaz comun. Todas las estrategias del registro la cumplen."""

    #: Nombre unico. Es parte del `SetupKey`, asi que cambiarlo invalida el
    #: historial estadistico del setup. No renombrar a la ligera.
    name: str = "strategy"

    #: Familia para el tope de variantes (ver `SetupEvaluator.register_variant`).
    family: str = "generic"

    #: Rango de parametros que el motor de mejora continua puede explorar.
    #: Nada fuera de aqui es ajustable automaticamente: es el sandbox del LLM.
    param_space: dict = {}

    #: Expiraciones candidatas en segundos.
    expiries: tuple = (60, 180, 300)

    def __init__(self, params: Optional[dict] = None):
        self.params = {**self.default_params(), **(params or {})}

    @classmethod
    def default_params(cls) -> dict:
        """Parametros por defecto. Las subclases lo sobreescriben."""
        return {}

    @abstractmethod
    def evaluate(self, candles_m15: Sequence[Candle], candles_m5: Sequence[Candle],
                 candles_m1: Sequence[Candle], asset: str = "") -> dict:
        """Analiza velas CERRADAS y devuelve el contrato de salida."""

    # ── utilidades comunes ────────────────────────────────────────────────

    def _no_trade(self, reasons: Sequence[str], features: Optional[dict] = None,
                  regime: MarketRegime = MarketRegime.UNKNOWN) -> dict:
        return {
            "direction": Direction.NO_TRADE,
            "confidence": 0.0,
            "strategy": self.name,
            "market_regime": regime,
            "entry_rationale": "; ".join(reasons) if reasons else "sin setup",
            "invalidation": "",
            "features": dict(features or {}),
            "opportunity_score": 0.0,
            "skip_entry_timing": False,
            "reasons": list(reasons),
        }

    def _signal(self, direction: Direction, confidence: float,
                regime: MarketRegime, rationale: str, invalidation: str,
                features: Optional[dict] = None,
                skip_entry_timing: bool = False) -> dict:
        confidence = max(0.0, min(1.0, float(confidence)))
        return {
            "direction": direction,
            "confidence": round(confidence, 4),
            "strategy": self.name,
            "market_regime": regime,
            "entry_rationale": rationale,
            "invalidation": invalidation,
            "features": dict(features or {}),
            "opportunity_score": round(confidence, 4),
            "skip_entry_timing": skip_entry_timing,
            "reasons": [],
        }

    @staticmethod
    def _sorted(candles: Sequence[Candle]) -> list[Candle]:
        return sorted(candles, key=lambda c: c.open_time)

    @staticmethod
    def _clean(candles: Sequence[Candle]) -> list[Candle]:
        """Descarta velas sin informacion al final de la serie.

        Una vela stale (close==high==low==open) al final de la serie hace que
        cualquier comparacion de cuerpos o mechas sea falsa: no hubo mercado,
        no hubo rechazo, no hubo nada. Mejor no opinar.
        """
        out = list(candles)
        while out and is_stale(out[-1]):
            out.pop()
        return out
