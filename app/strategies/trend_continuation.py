"""TREND CONTINUATION PULLBACK strategy.

Higher timeframes show a clear trend. Price makes a controlled pullback
toward EMA or structure. Entry after candle confirmation.
"""
from datetime import datetime
from typing import Optional

from app.data.schemas import (
    Candle, Direction, MarketRegime, Timeframe, EntryTiming
)
from app.agents.market_regime_agent import MarketRegimeAgent


class TrendContinuationStrategy:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.regime_agent = MarketRegimeAgent(
            trend_adx_threshold=self.config.get("trend_adx_threshold", 25.0)
        )
        self.ema_period = self.config.get("ema_period", 20)
        self.max_pullback_pct = self.config.get("max_pullback_pct", 0.5)
        self.min_confidence = self.config.get("min_confidence", 0.65)

    def evaluate(self, candles_m15: list[Candle], candles_m5: list[Candle],
                 candles_m1: list[Candle], asset: str = "") -> dict:
        m15_snapshot = self.regime_agent.classify(candles_m15, asset)
        m5_snapshot = self.regime_agent.classify(candles_m5, asset)
        m1_snapshot = self.regime_agent.classify(candles_m1, asset)

        reasons = []
        features = {}

        if m15_snapshot.regime not in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN):
            reasons.append("M15 not trending")
            return self._reject(reasons, features)

        if m5_snapshot.regime not in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN):
            reasons.append("M5 not trending")
            return self._reject(reasons, features)

        trend_up = m15_snapshot.regime == MarketRegime.TREND_UP
        trend_down = m15_snapshot.regime == MarketRegime.TREND_DOWN

        if (trend_up and m5_snapshot.regime != MarketRegime.TREND_UP) or \
           (trend_down and m5_snapshot.regime != MarketRegime.TREND_DOWN):
            reasons.append("M15 and M5 trend disagree")
            return self._reject(reasons, features)

        if m15_snapshot.adx < self.config.get("trend_adx_threshold", 25.0):
            reasons.append(f"Trend too weak: ADX {m15_snapshot.adx:.1f}")
            return self._reject(reasons, features)

        m5_sorted = sorted(candles_m5, key=lambda c: c.open_time)
        m1_sorted = sorted(candles_m1, key=lambda c: c.open_time)
        m5_last = m5_sorted[-1] if m5_sorted else None
        m1_last = m1_sorted[-1] if m1_sorted else None

        if not m5_last or not m1_last:
            reasons.append("No recent candles")
            return self._reject(reasons, features)

        m5_ema = self._compute_ema([c.close for c in m5_sorted])
        price = m5_last.close

        if trend_up:
            if price < m5_ema * 0.98:
                reasons.append("Price too far below EMA in uptrend")
                return self._reject(reasons, features)
            pullback_distance = (price - m5_ema) / m5_ema
            features["pullback_distance"] = round(pullback_distance, 4)
            # Pullback toward EMA from above: price should be at or near EMA
            if price > m5_ema * 1.01:
                reasons.append("Price too far above EMA, not in pullback zone")
                return self._reject(reasons, features)
        elif trend_down:
            if price > m5_ema * 1.02:
                reasons.append("Price too far above EMA in downtrend")
                return self._reject(reasons, features)
            pullback_distance = (m5_ema - price) / m5_ema
            features["pullback_distance"] = round(pullback_distance, 4)
            if price < m5_ema * 0.99:
                reasons.append("Price too far below EMA, not in pullback zone")
                return self._reject(reasons, features)

        # Recent price action alignment: last 3 M1 velas deben ir en la direccion del trade
        if len(m1_sorted) >= 3:
            recent_m1 = m1_sorted[-3:]
            if trend_up:
                # Al menos 2 de 3 ultimas velas deben ser alcistas
                bullish_count = sum(1 for c in recent_m1 if c.is_bullish)
                if bullish_count < 2:
                    reasons.append(f"M1 recent action no alineada: {bullish_count}/3 alcistas")
                    return self._reject(reasons, features)
            else:
                bearish_count = sum(1 for c in recent_m1 if not c.is_bullish)
                if bearish_count < 2:
                    reasons.append(f"M1 recent action no alineada: {bearish_count}/3 bajistas")
                    return self._reject(reasons, features)

        confidence = self._compute_confidence(m15_snapshot, m5_snapshot, m1_snapshot,
                                               m1_last, trend_up, trend_down)
        features.update({
            "m15_adx": m15_snapshot.adx,
            "m5_adx": m5_snapshot.adx,
            "m15_atr_percentile": m15_snapshot.atr_percentile,
            "m15_ema_slope": m15_snapshot.ema_slope,
            "price": price,
            "m5_ema": round(m5_ema, 4),
            "trend_direction": "up" if trend_up else "down",
        })

        return {
            "direction": Direction.CALL if trend_up else Direction.PUT,
            "strategy": "trend_continuation",
            "market_regime": m15_snapshot.regime,
            "entry_rationale": "Pullback to EMA with M15/M5 alignment and M1 confirmation",
            "invalidation": f"Break below {self._invalidation_level(m5_sorted, trend_up):.4f}",
            "confidence": round(confidence, 4),
            "features": features,
            "expiry": self.config.get("default_expiry", 180),
            "reasons": reasons if not reasons else ["trend_aligned"],
        }

    def _compute_confidence(self, m15, m5, m1, m1_last,
                            trend_up: bool, trend_down: bool) -> float:
        conf = self.min_confidence
        if m15.adx > 30:
            conf += 0.10
        if m15.adx > 40:
            conf += 0.05
        if m5.adx > 25:
            conf += 0.05
        if m1_last and m1_last.body > 0:
            conf += 0.05
        return min(conf, 0.95)

    def _invalidation_level(self, candles: list[Candle], trend_up: bool) -> float:
        if len(candles) < 5:
            return candles[-1].close if candles else 0
        recent = candles[-5:]
        if trend_up:
            return min(c.low for c in recent)
        else:
            return max(c.high for c in recent)

    def _reject(self, reasons: list, features: dict) -> dict:
        return {
            "direction": Direction.NO_TRADE,
            "strategy": "trend_continuation",
            "market_regime": MarketRegime.UNKNOWN,
            "entry_rationale": "; ".join(reasons),
            "invalidation": "not_applicable",
            "confidence": 0.0,
            "features": features,
            "expiry": 0,
            "reasons": reasons,
        }

    def _compute_ema(self, values: list[float]) -> float:
        if len(values) < 20:
            import statistics
            return statistics.mean(values) if values else 0.0
        k = 2 / (self.ema_period + 1)
        ema = sum(values[:self.ema_period]) / self.ema_period
        for v in values[self.ema_period:]:
            ema = v * k + ema * (1 - k)
        return ema
