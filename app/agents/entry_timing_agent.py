"""Entry timing agent.

Calculates timing validation based on candle age, confirmation status,
distance from entry zone, and latency.
"""
from datetime import datetime
from typing import Optional

from app.data.schemas import Candle, EntryTiming, Direction


class EntryTimingAgent:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.max_candle_age_ratio = self.config.get("max_candle_age_ratio", 0.8)
        self.min_wick_to_body_ratio = self.config.get("min_wick_to_body_ratio", 1.5)
        self.min_age_ratio = self.config.get("min_age_ratio", 0.5)
        self.min_body_pct = self.config.get("min_body_pct", 0.0)

    def evaluate(self, m1_candles: list[Candle], m5_candles: list[Candle],
                 direction: Direction, entry_zone: Optional[float] = None,
                 signal_timestamp: Optional[datetime] = None) -> dict:
        if signal_timestamp is None:
            signal_timestamp = datetime.utcnow()

        reasons = []
        features = {}
        m1_sorted = sorted(m1_candles, key=lambda c: c.open_time)
        m1_last = m1_sorted[-1] if m1_sorted else None

        if not m1_last:
            return self._result(EntryTiming.NO_TRADE, "No M1 candles available", features)

        # Check candle confirmation
        candle_age = (datetime.utcnow() - m1_last.open_time).total_seconds()
        candle_duration = m1_last.timeframe.value if hasattr(m1_last.timeframe, 'value') else 60
        age_ratio = candle_age / candle_duration if candle_duration > 0 else 1

        features["candle_age_sec"] = candle_age
        features["candle_duration_sec"] = candle_duration
        features["age_ratio"] = round(age_ratio, 4)

        # TOO_LATE: candle is almost closed
        if age_ratio > self.max_candle_age_ratio:
            reasons.append(f"Candle {age_ratio*100:.0f}% complete - too late")
            return self._result(EntryTiming.TOO_LATE, "; ".join(reasons), features)

        # WAIT_CONFIRMATION: candle not yet closed
        if age_ratio < self.min_age_ratio:
            reasons.append(f"Candle only {age_ratio*100:.0f}% complete, waiting for close")
            return self._result(EntryTiming.WAIT_CONFIRMATION, "; ".join(reasons), features)

        # Check minimum body movement (evitar entradas en velas sin movimiento)
        if self.min_body_pct > 0 and m1_last.body > 0:
            body_pct = m1_last.body / max(m1_last.close, m1_last.open, 0.0001)
            features["body_pct"] = round(body_pct, 6)
            if body_pct < self.min_body_pct:
                reasons.append(f"Body too small: {body_pct:.4%}")
                return self._result(EntryTiming.NO_TRADE, "; ".join(reasons), features)

        # Check wick-to-body ratio for rejection quality
        if direction == Direction.CALL:
            if m1_last.lower_wick > 0:
                wick_ratio = m1_last.lower_wick / max(m1_last.body, 0.0001)
                features["wick_to_body_ratio"] = round(wick_ratio, 4)
                if wick_ratio < self.min_wick_to_body_ratio and m1_last.body > 0:
                    reasons.append(f"Lower wick too small: ratio {wick_ratio:.2f}")
                    return self._result(EntryTiming.NO_TRADE, "; ".join(reasons), features)
            if not m1_last.is_bullish:
                reasons.append("Last candle not bullish for CALL")
                return self._result(EntryTiming.NO_TRADE, "; ".join(reasons), features)
        else:
            if m1_last.upper_wick > 0:
                wick_ratio = m1_last.upper_wick / max(m1_last.body, 0.0001)
                features["wick_to_body_ratio"] = round(wick_ratio, 4)
                if wick_ratio < self.min_wick_to_body_ratio and m1_last.body > 0:
                    reasons.append(f"Upper wick too small: ratio {wick_ratio:.2f}")
                    return self._result(EntryTiming.NO_TRADE, "; ".join(reasons), features)
            if m1_last.is_bullish:
                reasons.append("Last candle not bearish for PUT")
                return self._result(EntryTiming.NO_TRADE, "; ".join(reasons), features)

        # Distance from entry zone check
        if entry_zone is not None:
            distance = abs(m1_last.close - entry_zone)
            features["distance_from_zone"] = round(distance, 4)
            atr_value = self._estimate_atr(m1_candles)
            if atr_value > 0 and distance > atr_value * 0.5:
                reasons.append(f"Price moved {distance:.4f} from entry zone")
                return self._result(EntryTiming.TOO_LATE, "; ".join(reasons), features)

        return self._result(EntryTiming.ENTER_NOW, "Entry timing confirmed", features)

    def _result(self, timing: EntryTiming, rationale: str, features: dict) -> dict:
        return {
            "timing": timing,
            "rationale": rationale,
            "features": features,
            "enter_now": timing == EntryTiming.ENTER_NOW,
        }

    def _estimate_atr(self, candles: list[Candle]) -> float:
        if len(candles) < 2:
            return 0.0
        tr_values = []
        for i in range(1, min(15, len(candles))):
            hl = candles[i].high - candles[i].low
            hc = abs(candles[i].high - candles[i - 1].close)
            lc = abs(candles[i].low - candles[i - 1].close)
            tr_values.append(max(hl, hc, lc))
        return sum(tr_values) / len(tr_values) if tr_values else 0
