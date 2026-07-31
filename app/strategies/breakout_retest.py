"""BREAKOUT AND RETEST CONTINUATION strategy.

Price breaks meaningful support/resistance/range boundary.
Retest of broken level holds, then confirmation candle resumes breakout direction.
"""
from datetime import datetime
from typing import Optional
import statistics

from app.data.schemas import Candle, Direction, MarketRegime, EntryTiming
from app.agents.market_regime_agent import MarketRegimeAgent


class BreakoutRetestStrategy:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.regime_agent = MarketRegimeAgent(
            trend_adx_threshold=self.config.get("trend_adx_threshold", 25.0)
        )
        self.atr_period = self.config.get("atr_period", 14)
        self.min_breakout_body_pct = self.config.get("min_breakout_body_pct", 0.6)
        self.min_confidence = self.config.get("min_confidence", 0.65)

    def evaluate(self, candles_m15: list[Candle], candles_m5: list[Candle],
                 candles_m1: list[Candle], asset: str = "") -> dict:
        m15_snapshot = self.regime_agent.classify(candles_m15, asset)
        m5_snapshot = self.regime_agent.classify(candles_m5, asset)
        m1_snapshot = self.regime_agent.classify(candles_m1, asset)

        reasons = []
        features = {}

        if m15_snapshot.regime not in (
            MarketRegime.TREND_UP, MarketRegime.TREND_DOWN, MarketRegime.RANGE
        ):
            reasons.append(f"Regime {m15_snapshot.regime.value} not suitable")
            return self._reject(reasons, features)

        m5_sorted = sorted(candles_m5, key=lambda c: c.open_time)
        m1_sorted = sorted(candles_m1, key=lambda c: c.open_time)

        if len(m5_sorted) < 20 or len(m1_sorted) < 5:
            reasons.append("Insufficient candle data")
            return self._reject(reasons, features)

        atr = self._compute_atr(m5_sorted)
        support, resistance = self._find_range_boundaries(m5_sorted)

        if support is None or resistance is None:
            reasons.append("Cannot determine range boundaries")
            return self._reject(reasons, features)

        features["support"] = round(support, 4)
        features["resistance"] = round(resistance, 4)
        features["atr"] = round(atr, 4)

        m5_last = m5_sorted[-1]
        m1_last = m1_sorted[-1]
        price = m5_last.close

        # Check breakout above resistance
        breakout_up, retest_up = self._check_breakout_retest(
            m5_sorted, resistance, True, atr, features
        )
        if breakout_up and retest_up:
            return self._approve_signal(
                Direction.CALL, "Breakout above resistance with retest hold",
                m1_last, m1_sorted, features, reasons
            )

        # Check breakout below support
        breakout_down, retest_down = self._check_breakout_retest(
            m5_sorted, support, False, atr, features
        )
        if breakout_down and retest_down:
            return self._approve_signal(
                Direction.PUT, "Breakout below support with retest hold",
                m1_last, m1_sorted, features, reasons
            )

        reasons.append("No confirmed breakout with retest")
        return self._reject(reasons, features)

    def _check_breakout_retest(self, candles: list[Candle], level: float,
                               breakout_up: bool, atr: float,
                               features: dict) -> tuple[bool, bool]:
        if len(candles) < 5:
            return False, False

        recent = candles[-5:]
        breakout_detected = False
        retest_detected = False

        for i, c in enumerate(recent):
            if breakout_up:
                if c.high > level and c.close > level and c.body_pct >= self.min_breakout_body_pct:
                    breakout_detected = True
                    features["breakout_candle_idx"] = i
                    features["breakout_level"] = round(level, 4)
                    # Check subsequent candles for retest
                    for j in range(i + 1, len(recent)):
                        if abs(recent[j].close - level) <= atr * 0.3:
                            if recent[j].close > level:
                                retest_detected = True
                                features["retest_candle_idx"] = j
                            break
                    break
            else:
                if c.low < level and c.close < level and c.body_pct >= self.min_breakout_body_pct:
                    breakout_detected = True
                    features["breakout_candle_idx"] = i
                    features["breakout_level"] = round(level, 4)
                    for j in range(i + 1, len(recent)):
                        if abs(recent[j].close - level) <= atr * 0.3:
                            if recent[j].close < level:
                                retest_detected = True
                                features["retest_candle_idx"] = j
                            break
                    break

        return breakout_detected, retest_detected

    def _approve_signal(self, direction: Direction, rationale: str,
                        m1_last: Candle, m1_candles: list[Candle],
                        features: dict, reasons: list) -> dict:
        # M1 confirmation
        if m1_last:
            if direction == Direction.CALL and not m1_last.is_bullish and m1_last.body > 0:
                reasons.append("M1 not confirming bullish continuation")
                return self._reject(reasons, features)
            if direction == Direction.PUT and m1_last.is_bullish and m1_last.body > 0:
                reasons.append("M1 not confirming bearish continuation")
                return self._reject(reasons, features)

        confidence = self._compute_confidence(m1_last, m1_candles)
        features["m1_confirmation"] = m1_last.is_bullish if m1_last else "unknown"

        return {
            "direction": direction,
            "strategy": "breakout_retest",
            "market_regime": MarketRegime.RANGE,
            "entry_rationale": rationale,
            "invalidation": f"Retest fails, price re-enters range",
            "confidence": round(confidence, 4),
            "features": features,
            "expiry": self.config.get("default_expiry", 180),
            "reasons": ["breakout_retest_validated"],
        }

    def _compute_confidence(self, m1_last: Candle,
                            m1_candles: list[Candle]) -> float:
        conf = self.min_confidence
        if m1_last and m1_last.body > 0:
            conf += 0.10
        if m1_last and m1_last.body_pct > 0.7:
            conf += 0.05
        return min(conf, 0.95)

    def _find_range_boundaries(self, candles: list[Candle]) -> tuple:
        if len(candles) < 10:
            return None, None
        recent = candles[-20:]
        highs = [c.high for c in recent]
        lows = [c.low for c in recent]
        support = statistics.median(sorted(lows)[:5])
        resistance = statistics.median(sorted(highs, reverse=True)[:5])
        return support, resistance

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
            "strategy": "breakout_retest",
            "market_regime": MarketRegime.UNKNOWN,
            "entry_rationale": "; ".join(reasons),
            "invalidation": "not_applicable",
            "confidence": 0.0,
            "features": features,
            "expiry": 0,
            "reasons": reasons,
        }
