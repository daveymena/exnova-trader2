"""BREAKOUT DIRECTO strategy.

Encuentra soportes y resistencias validos en M5.
Entra CUANDO el precio ROMPE el nivel (vela M1 rompiendo).
No espera retest. No compra en soporte ni vende en resistencia.
Expiración: 3-5 minutos.
"""
from typing import Optional
import statistics

from app.data.schemas import Candle, Direction, MarketRegime


class BreakoutDirectStrategy:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.atr_period = self.config.get("atr_period", 14)
        self.min_breakout_body_pct = self.config.get("min_breakout_body_pct", 0.4)
        self.min_confidence = self.config.get("min_confidence", 0.50)
        self.lookback_candles = self.config.get("lookback_candles", 20)

    def evaluate(self, candles_m15: list[Candle], candles_m5: list[Candle],
                 candles_m1: list[Candle], asset: str = "") -> dict:
        reasons = []
        features = {}

        m5_sorted = sorted(candles_m5, key=lambda c: c.open_time)
        m1_sorted = sorted(candles_m1, key=lambda c: c.open_time)

        if len(m5_sorted) < 20 or len(m1_sorted) < 5:
            reasons.append("Insufficient candle data")
            return self._reject(reasons, features)

        atr = self._compute_atr(m5_sorted)
        support, resistance = self._find_levels(m5_sorted)
        features["atr"] = round(atr, 4)

        if support is None or resistance is None:
            reasons.append("Cannot determine S/R levels")
            return self._reject(reasons, features)

        features["support"] = round(support, 4)
        features["resistance"] = round(resistance, 4)

        m1_last = m1_sorted[-1]
        m1_prev = m1_sorted[-2] if len(m1_sorted) >= 2 else None
        price = m1_last.close

        # Check UP breakout: price rompe resistencia AHORA
        if price >= resistance and m1_last.high > resistance:
            if self._check_breakout_candle(m1_last, resistance, True, atr, features):
                return self._approve(
                    Direction.CALL, f"Breakout UP sobre resistencia {resistance:.4f}",
                    m1_last, m1_prev, features, reasons
                )

        # Check DOWN breakout: precio rompe soporte AHORA
        if price <= support and m1_last.low < support:
            if self._check_breakout_candle(m1_last, support, False, atr, features):
                return self._approve(
                    Direction.PUT, f"Breakout DOWN bajo soporte {support:.4f}",
                    m1_last, m1_prev, features, reasons
                )

        reasons.append("No breakout detected")
        return self._reject(reasons, features)

    def _check_breakout_candle(self, candle: Candle, level: float,
                                breakout_up: bool, atr: float,
                                features: dict) -> bool:
        # La vela debe tener cuerpo significativo (no solo mecha)
        if candle.body_pct < self.min_breakout_body_pct:
            return False

        # Debe romper el nivel con conviccion
        if breakout_up:
            distance = candle.close - level
            if distance <= 0:
                return False
            features["breakout_distance"] = round(distance, 4)
            features["breakout_body_pct"] = round(candle.body_pct, 4)
        else:
            distance = level - candle.close
            if distance <= 0:
                return False
            features["breakout_distance"] = round(distance, 4)
            features["breakout_body_pct"] = round(candle.body_pct, 4)

        return True

    def _approve(self, direction: Direction, rationale: str,
                 m1_last: Candle, m1_prev: Candle,
                 features: dict, reasons: list) -> dict:
        confidence = self.min_confidence
        if m1_last and m1_last.body_pct > 0.6:
            confidence += 0.15
        if m1_last and m1_last.body > 0:
            confidence += 0.05
        if m1_prev and m1_prev.body_pct > 0.5:
            confidence += 0.05
        confidence = min(confidence, 0.90)

        features["confidence"] = round(confidence, 4)

        return {
            "direction": direction,
            "strategy": "breakout_direct",
            "market_regime": MarketRegime.UNKNOWN,
            "entry_rationale": rationale,
            "invalidation": "Breakout fails, price back inside range",
            "confidence": round(confidence, 4),
            "features": features,
            "expiry": self.config.get("default_expiry", 180),
            "reasons": ["breakout_direct_validated"],
        }

    def _find_levels(self, candles: list[Candle]) -> tuple:
        if len(candles) < 10:
            return None, None

        recent = candles[-self.lookback_candles:]
        highs = sorted([c.high for c in recent], reverse=True)
        lows = sorted([c.low for c in recent])

        # Resistencia = cluster de los highs mas altos
        resistance = statistics.median(highs[:5])

        # Soporte = cluster de los lows mas bajos
        support = statistics.median(lows[:5])

        if resistance <= support:
            return None, None

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
            "strategy": "breakout_direct",
            "market_regime": MarketRegime.UNKNOWN,
            "entry_rationale": "; ".join(reasons),
            "invalidation": "not_applicable",
            "confidence": 0.0,
            "features": features,
            "expiry": 0,
            "reasons": reasons,
        }
