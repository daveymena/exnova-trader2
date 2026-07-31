"""SUPPORT/RESISTANCE REVERSAL strategy.

Use only at validated multi-timeframe support or resistance with exhaustion evidence.
Countertrend entries require stronger evidence than trend-following.
"""
from datetime import datetime
from typing import Optional
import statistics

from app.data.schemas import (
    Candle, Direction, MarketRegime, EntryTiming
)
from app.agents.market_regime_agent import MarketRegimeAgent


class MeanReversionStrategy:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.regime_agent = MarketRegimeAgent(
            trend_adx_threshold=self.config.get("trend_adx_threshold", 25.0)
        )
        self.atr_period = self.config.get("atr_period", 14)
        self.zone_distance_atr = self.config.get("zone_distance_atr", 0.5)
        self.min_confidence = self.config.get("min_confidence", 0.70)

    def evaluate(self, candles_m15: list[Candle], candles_m5: list[Candle],
                 candles_m1: list[Candle], asset: str = "",
                 support_levels: Optional[list[float]] = None,
                 resistance_levels: Optional[list[float]] = None) -> dict:
        m15_snapshot = self.regime_agent.classify(candles_m15, asset)
        m5_snapshot = self.regime_agent.classify(candles_m5, asset)
        m1_snapshot = self.regime_agent.classify(candles_m1, asset)

        reasons = []
        features = {}

        # Reversal strategies only in RANGE or controlled exhaustion
        if m15_snapshot.regime not in (MarketRegime.RANGE,):
            reasons.append(f"Regime {m15_snapshot.regime.value} not suitable for reversal")
            return self._reject(reasons, features)

        m1_sorted = sorted(candles_m1, key=lambda c: c.open_time)
        m5_sorted = sorted(candles_m5, key=lambda c: c.open_time)
        m1_last = m1_sorted[-1] if m1_sorted else None

        if not m1_last:
            reasons.append("No M1 candles")
            return self._reject(reasons, features)

        support_levels = support_levels or self._detect_levels(candles_m15, "support")
        resistance_levels = resistance_levels or self._detect_levels(candles_m15, "resistance")
        atr = self._compute_atr(m5_sorted)

        price = m1_last.close
        features["price"] = price
        features["atr"] = round(atr, 4)

        # Check support bounce
        for level in sorted(support_levels, reverse=True):
            distance = abs(price - level)
            if distance <= atr * self.zone_distance_atr:
                features["nearest_support"] = round(level, 4)
                features["distance_to_support"] = round(distance, 4)
                return self._evaluate_reversal(
                    price, level, Direction.CALL, m1_last, m1_sorted,
                    reasons, features, "support"
                )

        # Check resistance rejection
        for level in sorted(resistance_levels):
            distance = abs(price - level)
            if distance <= atr * self.zone_distance_atr:
                features["nearest_resistance"] = round(level, 4)
                features["distance_to_resistance"] = round(distance, 4)
                return self._evaluate_reversal(
                    price, level, Direction.PUT, m1_last, m1_sorted,
                    reasons, features, "resistance"
                )

        reasons.append("Price not near any validated level")
        return self._reject(reasons, features)

    def _evaluate_reversal(self, price: float, level: float,
                           direction: Direction, m1_last: Candle,
                           m1_candles: list[Candle],
                           reasons: list, features: dict,
                           level_type: str) -> dict:
        if not m1_last:
            reasons.append("No M1 candle for confirmation")
            return self._reject(reasons, features)

        # Check for exhaustion evidence
        exhaustion = self._detect_exhaustion(m1_candles, direction)
        features["exhaustion_detected"] = exhaustion

        if not exhaustion:
            reasons.append(f"No exhaustion evidence near {level_type}")
            return self._reject(reasons, features)

        # M1 confirmation
        if direction == Direction.CALL:
            if not m1_last.is_bullish and m1_last.body > 0:
                reasons.append("M1 not showing bullish rejection")
                return self._reject(reasons, features)
        else:
            if m1_last.is_bullish and m1_last.body > 0:
                reasons.append("M1 not showing bearish rejection")
                return self._reject(reasons, features)

        confidence = self._compute_confidence(exhaustion, m1_last, m1_candles)

        return {
            "direction": direction,
            "strategy": "mean_reversion",
            "market_regime": MarketRegime.RANGE,
            "entry_rationale": f"Reversal at validated {level_type} with exhaustion",
            "invalidation": f"Break below {level:.4f} with expansion" if direction == Direction.CALL
                           else f"Break above {level:.4f} with expansion",
            "confidence": round(confidence, 4),
            "features": features,
            "expiry": self.config.get("default_expiry", 180),
            "reasons": ["reversal_validated"],
        }

    def _detect_exhaustion(self, candles: list[Candle], direction: Direction) -> bool:
        if len(candles) < 3:
            return False
        recent = candles[-3:]

        if direction == Direction.CALL:
            # Look for lower wick rejection (hammer-like)
            for c in recent:
                if c.lower_wick > c.body * 2 and c.lower_wick > 0:
                    return True
                if not c.is_bullish and c.lower_wick > c.range * 0.6:
                    return True
        else:
            # Look for upper wick rejection (shooting star-like)
            for c in recent:
                if c.upper_wick > c.body * 2 and c.upper_wick > 0:
                    return True
                if c.is_bullish and c.upper_wick > c.range * 0.6:
                    return True
        return False

    def _compute_confidence(self, exhaustion: bool, m1_last: Candle,
                            m1_candles: list[Candle]) -> float:
        conf = self.min_confidence
        if exhaustion:
            conf += 0.10
        if m1_last.body > 0:
            conf += 0.05
        if len(m1_candles) >= 5:
            # Check if we had prior rejection candles
            rejections = sum(1 for c in m1_candles[-5:]
                           if c.lower_wick > c.body * 2 or c.upper_wick > c.body * 2)
            if rejections >= 2:
                conf += 0.05
        return min(conf, 0.95)

    def _detect_levels(self, candles: list[Candle], level_type: str) -> list[float]:
        if len(candles) < 10:
            return []
        levels = []
        for i in range(2, len(candles) - 2):
            if level_type == "support":
                if candles[i].low < candles[i - 1].low and \
                   candles[i].low < candles[i + 1].low and \
                   candles[i].low < candles[i - 2].low and \
                   candles[i].low < candles[i + 2].low:
                    levels.append(candles[i].low)
            else:
                if candles[i].high > candles[i - 1].high and \
                   candles[i].high > candles[i + 1].high and \
                   candles[i].high > candles[i - 2].high and \
                   candles[i].high > candles[i + 2].high:
                    levels.append(candles[i].high)
        return levels

    def _compute_atr(self, candles: list[Candle]) -> float:
        if len(candles) < 2:
            return 0.0
        tr_values = []
        for i in range(1, len(candles)):
            hl = candles[i].high - candles[i].low
            hc = abs(candles[i].high - candles[i - 1].close)
            lc = abs(candles[i].low - candles[i - 1].close)
            tr_values.append(max(hl, hc, lc))
        period = min(self.atr_period, len(tr_values))
        return statistics.mean(tr_values[-period:]) if period > 0 else 0

    def _reject(self, reasons: list, features: dict) -> dict:
        return {
            "direction": Direction.NO_TRADE,
            "strategy": "mean_reversion",
            "market_regime": MarketRegime.UNKNOWN,
            "entry_rationale": "; ".join(reasons),
            "invalidation": "not_applicable",
            "confidence": 0.0,
            "features": features,
            "expiry": 0,
            "reasons": reasons,
        }
