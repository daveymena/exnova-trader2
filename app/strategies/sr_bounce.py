"""S/R BOUNCE strategy.

1. Identifica soportes y resistencias en M15 (swing highs/lows)
2. Monitorea M1: precio acercandose a un nivel
3. Espera vela de RECHAZO en el nivel (mecha larga + cuerpo pequeno)
4. Entra en la SIGUIENTE vela cuando el impulso de rebote arranca
5. CALL desde soporte, PUT desde resistencia
6. Nunca entra en el nivel, siempre espera confirmacion del rebote
"""
from typing import Optional
import statistics

from app.data.schemas import Candle, Direction, MarketRegime


class SRBounceStrategy:
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.atr_period = self.config.get("atr_period", 14)
        self.min_confidence = self.config.get("min_confidence", 0.50)
        self.level_distance_atr = self.config.get("level_distance_atr", 1.5)
        self.min_rejection_wick_ratio = self.config.get("min_rejection_wick_ratio", 2.0)
        self.lookback_m5 = self.config.get("lookback_m5", 30)
        self.lookback_m15 = self.config.get("lookback_m15", 20)

    def evaluate(self, candles_m15: list[Candle], candles_m5: list[Candle],
                 candles_m1: list[Candle], asset: str = "") -> dict:
        reasons = []
        features = {}

        m15_sorted = sorted(candles_m15, key=lambda c: c.open_time)
        m5_sorted = sorted(candles_m5, key=lambda c: c.open_time)
        m1_sorted = sorted(candles_m1, key=lambda c: c.open_time)

        if len(m15_sorted) < 10 or len(m1_sorted) < 5:
            reasons.append("Insufficient candle data")
            return self._reject(reasons, features)

        # 1. Find S/R levels on M15
        atr_m5 = self._compute_atr(m5_sorted)
        support, resistance = self._find_sr_levels(m15_sorted)
        features["atr_m5"] = round(atr_m5, 4)

        if support is None or resistance is None:
            reasons.append("Cannot determine S/R levels")
            return self._reject(reasons, features)

        features["support"] = round(support, 4)
        features["resistance"] = round(resistance, 4)

        m1_last = m1_sorted[-1]
        m1_prev = m1_sorted[-2] if len(m1_sorted) >= 2 else None
        price = m1_last.close
        features["price"] = round(price, 4)

        # 2. Check if price is near a level
        dist_to_support = price - support if price > support else 0
        dist_to_resistance = resistance - price if price < resistance else 0

        features["dist_to_support"] = round(dist_to_support, 4)
        features["dist_to_resistance"] = round(dist_to_resistance, 4)

        # 3. Check CALL setup (rebote desde soporte)
        if dist_to_support <= atr_m5 * self.level_distance_atr:
            features["near_level"] = "support"
            if self._check_rejection(m1_last, m1_sorted, support, True):
                return self._approve_bounce(
                    Direction.CALL, support, m1_last, m1_prev,
                    atr_m5, features, reasons
                )

        # 4. Check PUT setup (rechazo en resistencia)
        if dist_to_resistance <= atr_m5 * self.level_distance_atr:
            features["near_level"] = "resistance"
            if self._check_rejection(m1_last, m1_sorted, resistance, False):
                return self._approve_bounce(
                    Direction.PUT, resistance, m1_last, m1_prev,
                    atr_m5, features, reasons
                )

        reasons.append("No S/R bounce setup detected")
        return self._reject(reasons, features)

    def _check_rejection(self, last_candle: Candle, all_m1: list[Candle],
                          level: float, is_support: bool) -> bool:
        """Verifica si alguna vela reciente toco el nivel y ahora se aleja.
        Busca en las ultimas 3 velas M1.
        """
        if len(all_m1) < 3:
            return False

        recent = all_m1[-3:]

        if is_support:
            # Busca al menos 1 vela que haya tocado soporte (low <= level)
            touched = [c for c in recent if c.low <= level]
            if not touched:
                return False
            # La vela MAS RECIENTE debe estar alejandose del soporte (alcista o cuerpo arriba)
            if last_candle.close <= last_candle.open:
                if last_candle.low > level:
                    return False  # Sigue bajando y no toco el nivel
            return True
        else:
            # Busca al menos 1 vela que haya tocado resistencia (high >= level)
            touched = [c for c in recent if c.high >= level]
            if not touched:
                return False
            # La vela MAS RECIENTE debe estar alejandose de la resistencia (bajista o cuerpo abajo)
            if last_candle.close >= last_candle.open:
                if last_candle.high < level:
                    return False  # Sigue subiendo y no toco el nivel
            return True

    def _approve_bounce(self, direction: Direction, level: float,
                        m1_last: Candle, m1_prev: Candle,
                        atr: float, features: dict, reasons: list) -> dict:
        confidence = self.min_confidence

        # Mayor confianza si el rechazo es fuerte
        if direction == Direction.CALL:
            rejection_strength = m1_last.lower_wick / max(m1_last.body, 0.0001)
            features["rejection_ratio"] = round(rejection_strength, 2)
            if rejection_strength > 3:
                confidence += 0.15
            elif rejection_strength > 2:
                confidence += 0.10
            # Vela previa tambien bajista = mas confirmacion
            if m1_prev and not m1_prev.is_bullish:
                confidence += 0.05
        else:
            rejection_strength = m1_last.upper_wick / max(m1_last.body, 0.0001)
            features["rejection_ratio"] = round(rejection_strength, 2)
            if rejection_strength > 3:
                confidence += 0.15
            elif rejection_strength > 2:
                confidence += 0.10
            if m1_prev and m1_prev.is_bullish:
                confidence += 0.05

        features["bounce_from_level"] = round(level, 4)
        features["entry_candle_body"] = round(m1_last.body, 4)
        features["entry_candle_close"] = round(m1_last.close, 4)
        confidence = min(confidence, 0.90)

        level_type = "soporte" if direction == Direction.CALL else "resistencia"
        return {
            "direction": direction,
            "strategy": "sr_bounce",
            "market_regime": MarketRegime.UNKNOWN,
            "entry_rationale": f"Rebote desde {level_type} {level:.4f} con vela de rechazo",
            "invalidation": f"Precio pierde {level:.4f}",
            "confidence": round(confidence, 4),
            "features": features,
            "expiry": self.config.get("default_expiry", 300),
            "reasons": ["sr_bounce_validated"],
            "skip_entry_timing": True,
        }

    def _find_sr_levels(self, candles: list[Candle]) -> tuple:
        """Encuentra S/R en M15 usando swing highs/lows."""
        if len(candles) < 10:
            return None, None

        recent = candles[-self.lookback_m15:]

        # Find swing highs (resistance)
        swing_highs = []
        for i in range(2, len(recent) - 2):
            if (recent[i].high > recent[i-1].high and
                recent[i].high > recent[i-2].high and
                recent[i].high > recent[i+1].high and
                recent[i].high > recent[i+2].high):
                swing_highs.append(recent[i].high)

        # Find swing lows (support)
        swing_lows = []
        for i in range(2, len(recent) - 2):
            if (recent[i].low < recent[i-1].low and
                recent[i].low < recent[i-2].low and
                recent[i].low < recent[i+1].low and
                recent[i].low < recent[i+2].low):
                swing_lows.append(recent[i].low)

        if not swing_highs or not swing_lows:
            # Fallback: use median of highs and lows
            highs = sorted([c.high for c in recent], reverse=True)
            lows = sorted([c.low for c in recent])
            resistance = statistics.median(highs[:5])
            support = statistics.median(lows[:5])
        else:
            # Cluster the nearest levels
            resistance = statistics.median(sorted(swing_highs, reverse=True)[:3])
            support = statistics.median(sorted(swing_lows)[:3])

        if resistance <= support or (resistance - support) < (statistics.mean([c.body for c in recent]) * 2):
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
            "strategy": "sr_bounce",
            "market_regime": MarketRegime.UNKNOWN,
            "entry_rationale": "; ".join(reasons),
            "invalidation": "not_applicable",
            "confidence": 0.0,
            "features": features,
            "expiry": 0,
            "reasons": reasons,
        }
