"""Deterministic, explainable market regime classifier.

Classifies each market state into:
- TREND_UP / TREND_DOWN
- RANGE
- HIGH_VOLATILITY
- LOW_LIQUIDITY_OR_BAD_DATA
- NEWS_RISK
- UNKNOWN
"""
import math
import statistics
from datetime import datetime
from typing import Optional

from app.data.schemas import Candle, MarketRegime, MarketRegimeSnapshot, Timeframe
from app.data.repository import repository


class MarketRegimeAgent:
    def __init__(self, adx_period: int = 14, atr_period: int = 14,
                 ema_period: int = 20, trend_adx_threshold: float = 25.0,
                 high_vol_atr_percentile: float = 0.80):
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.ema_period = ema_period
        self.trend_adx_threshold = trend_adx_threshold
        self.high_vol_atr_percentile = high_vol_atr_percentile

    def classify(self, candles: list[Candle], asset: str = "",
                 timestamp: Optional[datetime] = None) -> MarketRegimeSnapshot:
        if timestamp is None:
            timestamp = datetime.utcnow()
        if len(candles) < self.adx_period + 5:
            return MarketRegimeSnapshot(
                timestamp=timestamp, asset=asset,
                regime=MarketRegime.UNKNOWN,
                adx=0, atr_percentile=0, ema_slope=0,
                price_distance_ema=0, features={"reason": "insufficient_data"}
            )

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        sorted_candles = sorted(candles, key=lambda c: c.open_time)

        adx = self._compute_adx(sorted_candles)
        atr = self._compute_atr(sorted_candles)
        atr_percentile = self._compute_atr_percentile(sorted_candles)
        ema = self._compute_ema(closes)
        ema_slope = self._compute_ema_slope(ema)
        price_distance_ema = (closes[-1] - ema) / ema if ema != 0 else 0
        ema_trend = "up" if ema_slope > 0 else "down"

        regime = self._determine_regime(
            adx, atr_percentile, ema_slope, price_distance_ema,
            candles, sorted_candles
        )

        snapshot = MarketRegimeSnapshot(
            timestamp=timestamp,
            asset=asset,
            regime=regime,
            adx=round(adx, 2),
            atr_percentile=round(atr_percentile, 4),
            ema_slope=round(ema_slope, 6),
            price_distance_ema=round(price_distance_ema, 4),
            features={
                "adx": round(adx, 2),
                "atr": round(atr, 4),
                "atr_percentile": round(atr_percentile, 4),
                "ema": round(ema, 4),
                "ema_slope": round(ema_slope, 6),
                "price_distance_ema": round(price_distance_ema, 4),
                "ema_trend": ema_trend,
                "candle_count": len(candles),
                "trend_adx_threshold": self.trend_adx_threshold,
            }
        )

        repository.save_market_regime_snapshot(snapshot)
        return snapshot

    def _determine_regime(self, adx: float, atr_percentile: float,
                          ema_slope: float, price_distance_ema: float,
                          candles: list[Candle],
                          sorted_candles: list[Candle]) -> MarketRegime:
        reasons = []

        if atr_percentile > self.high_vol_atr_percentile:
            reasons.append("high_atr_percentile")

        candle_expansion = self._detect_candle_expansion(sorted_candles)
        if candle_expansion:
            reasons.append("candle_expansion")

        if adx >= self.trend_adx_threshold:
            if ema_slope > 0 and price_distance_ema > 0:
                return MarketRegime.TREND_UP
            elif ema_slope < 0 and price_distance_ema < 0:
                return MarketRegime.TREND_DOWN
        elif adx < 20:
            return MarketRegime.RANGE

        if atr_percentile > self.high_vol_atr_percentile:
            return MarketRegime.HIGH_VOLATILITY

        return MarketRegime.UNKNOWN

    def _compute_adx(self, candles: list[Candle]) -> float:
        if len(candles) < self.adx_period + 1:
            return 0.0
        tr_values = []
        for i in range(1, len(candles)):
            hl = candles[i].high - candles[i].low
            hc = abs(candles[i].high - candles[i - 1].close)
            lc = abs(candles[i].low - candles[i - 1].close)
            tr_values.append(max(hl, hc, lc))
        atr = statistics.mean(tr_values[-self.atr_period:]) if len(tr_values) >= self.atr_period else statistics.mean(tr_values)

        plus_dm = []
        minus_dm = []
        for i in range(1, len(candles)):
            up_move = candles[i].high - candles[i - 1].high
            down_move = candles[i - 1].low - candles[i].low
            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
            else:
                plus_dm.append(0)
            if down_move > up_move and down_move > 0:
                minus_dm.append(down_move)
            else:
                minus_dm.append(0)

        avg_plus = statistics.mean(plus_dm[-self.atr_period:]) if len(plus_dm) >= self.atr_period else statistics.mean(plus_dm) if plus_dm else 0
        avg_minus = statistics.mean(minus_dm[-self.atr_period:]) if len(minus_dm) >= self.atr_period else statistics.mean(minus_dm) if minus_dm else 0

        if atr == 0:
            return 0.0
        di_plus = 100 * avg_plus / atr if atr > 0 else 0
        di_minus = 100 * avg_minus / atr if atr > 0 else 0
        dx = abs(di_plus - di_minus) / (di_plus + di_minus) if (di_plus + di_minus) > 0 else 0
        adx = 100 * dx
        return adx

    def _compute_atr(self, candles: list[Candle]) -> float:
        if len(candles) < 2:
            return 0.0
        tr_values = []
        for i in range(1, len(candles)):
            hl = candles[i].high - candles[i].low
            hc = abs(candles[i].high - candles[i - 1].close)
            lc = abs(candles[i].low - candles[i - 1].close)
            tr_values.append(max(hl, hc, lc))
        return statistics.mean(tr_values[-self.atr_period:]) if len(tr_values) >= self.atr_period else statistics.mean(tr_values)

    def _compute_atr_percentile(self, candles: list[Candle]) -> float:
        if len(candles) < self.atr_period * 2:
            return 0.5
        atr_values = []
        for i in range(len(candles) - self.atr_period):
            chunk = candles[i:i + self.atr_period]
            atr_values.append(self._compute_atr(chunk))
        if not atr_values:
            return 0.5
        current_atr = self._compute_atr(candles)
        count_below = sum(1 for v in atr_values if v < current_atr)
        return count_below / len(atr_values)

    def _compute_ema(self, values: list[float]) -> float:
        if len(values) < self.ema_period:
            return statistics.mean(values) if values else 0.0
        k = 2 / (self.ema_period + 1)
        ema = statistics.mean(values[:self.ema_period])
        for v in values[self.ema_period:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _compute_ema_slope(self, ema: float) -> float:
        return ema - self._compute_ema([0]) if ema != 0 else 0

    def _detect_candle_expansion(self, candles: list[Candle]) -> bool:
        if len(candles) < 10:
            return False
        recent_ranges = [c.range for c in candles[-5:]]
        older_ranges = [c.range for c in candles[-10:-5]]
        if not older_ranges:
            return False
        avg_older = statistics.mean(older_ranges)
        if avg_older == 0:
            return False
        recent_avg = statistics.mean(recent_ranges)
        return (recent_avg / avg_older) > 2.0
