"""
Context Analyzer — Analiza el contexto completo del mercado
Lee la estructura del precio: tendencia, momentum, qué pasó antes y qué suele pasar después.
No busca señales aleatorias — entiende el relato del mercado.
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, List


class ContextAnalyzer:

    def analyze(self, df_m1: pd.DataFrame, df_m5: pd.DataFrame,
                df_m15: pd.DataFrame, df_h1: Optional[pd.DataFrame],
                zone=None, current_price: float = 0.0) -> Dict:
        """
        Análisis completo del contexto del mercado.
        Devuelve un dict con toda la información de contexto.
        """
        if len(df_m1) < 20:
            return self._empty_context()

        price = current_price or float(df_m1["close"].iloc[-1])

        # Estructura del mercado en cada timeframe
        structure_m1 = self._market_structure(df_m1)
        structure_m5 = self._market_structure(df_m5) if len(df_m5) >= 10 else structure_m1
        structure_m15 = self._market_structure(df_m15) if len(df_m15) >= 10 else structure_m5
        structure_h1 = self._market_structure(df_h1) if df_h1 is not None and len(df_h1) >= 5 else structure_m15

        # Tendencia dominante (H1 > M15 > M5)
        dominant_trend = self._dominant_trend(structure_h1, structure_m15, structure_m5)

        # Momentum actual (M1 / M5)
        momentum = self._momentum_analysis(df_m1, df_m5)

        # Fase del mercado
        phase = self._market_phase(df_m15 if len(df_m15) >= 20 else df_m5, structure_m15)

        # Contexto de zona
        zone_context = self._zone_context(zone, price, dominant_trend) if zone else {}

        # Dirección esperada dado el contexto
        expected_dir, dir_confidence = self._expected_direction(
            dominant_trend, momentum, zone_context, structure_m1
        )

        # Calidad del setup
        setup_quality = self._setup_quality(
            dominant_trend, momentum, zone_context, phase, structure_m5
        )

        # Análisis de qué pasó antes (últimas 10 velas M5)
        before_context = self._what_happened_before(df_m5, price, zone)

        return {
            "dominant_trend": dominant_trend,
            "structure_m1": structure_m1,
            "structure_m5": structure_m5,
            "structure_m15": structure_m15,
            "structure_h1": structure_h1,
            "momentum": momentum,
            "market_phase": phase,
            "zone_context": zone_context,
            "expected_direction": expected_dir,
            "direction_confidence": dir_confidence,
            "setup_quality": setup_quality,
            "before_context": before_context,
            "current_price": price,
        }

    # ── Estructura de mercado ─────────────────────────────────────────────────

    def _market_structure(self, df: pd.DataFrame) -> Dict:
        """
        Detecta HH/HL (uptrend), LH/LL (downtrend) o estructura rota.
        Analiza los últimos pivots del dataframe.
        """
        if len(df) < 10:
            return {"trend": "neutral", "hh": False, "hl": False, "lh": False, "ll": False,
                    "swing_high": 0.0, "swing_low": 0.0, "structure": "unclear",
                    "last_peak_idx": None, "last_trough_idx": None}

        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        n = len(df)

        # Últimos 4 extremos locales
        peaks = []
        troughs = []
        for i in range(2, n - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                peaks.append((i, float(highs[i])))
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                troughs.append((i, float(lows[i])))

        peaks = peaks[-4:]
        troughs = troughs[-4:]

        hh = len(peaks) >= 2 and peaks[-1][1] > peaks[-2][1]
        ll = len(troughs) >= 2 and troughs[-1][1] < troughs[-2][1]
        lh = len(peaks) >= 2 and peaks[-1][1] < peaks[-2][1]
        hl = len(troughs) >= 2 and troughs[-1][1] > troughs[-2][1]

        if hh and hl:
            trend = "uptrend"
            structure = "bullish"
        elif ll and lh:
            trend = "downtrend"
            structure = "bearish"
        elif hh and ll:
            trend = "volatile"
            structure = "choppy"
        else:
            trend = "neutral"
            structure = "consolidating"

        swing_high = float(max([p[1] for p in peaks])) if peaks else float(highs.max())
        swing_low = float(min([t[1] for t in troughs])) if troughs else float(lows.min())

        # EMA slope
        if len(closes) >= 20:
            ema20 = self._ema(closes, 20)
            slope = (ema20[-1] - ema20[-5]) / ema20[-5] * 100 if ema20[-5] != 0 else 0
        else:
            slope = 0.0

        return {
            "trend": trend,
            "hh": hh, "hl": hl, "lh": lh, "ll": ll,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "structure": structure,
            "ema_slope": slope,
            "last_peak_idx": peaks[-1][0] if peaks else None,
            "last_trough_idx": troughs[-1][0] if troughs else None,
            "peaks": peaks,
            "troughs": troughs,
            "n_candles": n,
        }

    def _dominant_trend(self, h1: Dict, m15: Dict, m5: Dict) -> str:
        """La tendencia dominante considerando los 3 timeframes superiores."""
        scores = {"uptrend": 0, "downtrend": 0, "neutral": 0}
        weights = {"h1": 3, "m15": 2, "m5": 1}
        for name, struct, w in [("h1", h1, 3), ("m15", m15, 2), ("m5", m5, 1)]:
            t = struct.get("trend", "neutral")
            if t in scores:
                scores[t] += w
        if scores["uptrend"] > scores["downtrend"] + 1:
            return "uptrend"
        elif scores["downtrend"] > scores["uptrend"] + 1:
            return "downtrend"
        return "neutral"

    # ── Momentum ──────────────────────────────────────────────────────────────

    def _momentum_analysis(self, df_m1: pd.DataFrame, df_m5: pd.DataFrame) -> Dict:
        closes_m1 = df_m1["close"].values
        closes_m5 = df_m5["close"].values if len(df_m5) >= 5 else closes_m1

        rsi_m1 = self._rsi(closes_m1, 14)
        rsi_m5 = self._rsi(closes_m5, 14)
        macd_m1, signal_m1, hist_m1 = self._macd(closes_m1)

        rsi_val = float(rsi_m1[-1]) if len(rsi_m1) > 0 else 50.0
        rsi_m5_val = float(rsi_m5[-1]) if len(rsi_m5) > 0 else 50.0

        # Detectar divergencias simples
        price_rising = closes_m1[-1] > closes_m1[-5] if len(closes_m1) >= 5 else False
        rsi_rising = rsi_m1[-1] > rsi_m1[-5] if len(rsi_m1) >= 5 else False
        bearish_div = price_rising and not rsi_rising and rsi_val > 60
        bullish_div = not price_rising and rsi_rising and rsi_val < 40

        hist_last = float(hist_m1[-1]) if len(hist_m1) > 0 else 0.0
        hist_prev = float(hist_m1[-2]) if len(hist_m1) > 1 else 0.0

        return {
            "rsi_m1": rsi_val,
            "rsi_m5": rsi_m5_val,
            "rsi_oversold": rsi_val < 30,
            "rsi_overbought": rsi_val > 70,
            "rsi_extreme_oversold": rsi_val < 20,
            "rsi_extreme_overbought": rsi_val > 80,
            "macd_hist": hist_last,
            "macd_turning": (hist_last > 0) != (hist_prev > 0),
            "bullish_divergence": bullish_div,
            "bearish_divergence": bearish_div,
            "direction": "bullish" if rsi_val < 45 else "bearish" if rsi_val > 55 else "neutral",
        }

    # ── Fase del mercado ──────────────────────────────────────────────────────

    def _market_phase(self, df: pd.DataFrame, structure: Dict) -> str:
        if len(df) < 20:
            return "unknown"
        closes = df["close"].values
        atr = self._atr(df)
        avg_atr = float(np.mean(atr[-20:])) if len(atr) >= 20 else float(np.mean(atr))
        last_atr = float(atr[-1]) if len(atr) > 0 else 0.0

        trend = structure.get("trend", "neutral")
        is_volatile = last_atr > avg_atr * 1.4
        is_dead = last_atr < avg_atr * 0.5

        if is_dead:
            return "dead"
        if is_volatile and trend == "neutral":
            return "volatile_ranging"
        if trend == "uptrend":
            return "trending_up"
        if trend == "downtrend":
            return "trending_down"
        return "ranging"

    # ── Contexto de zona ──────────────────────────────────────────────────────

    def _zone_context(self, zone, price: float, dominant_trend: str) -> Dict:
        if zone is None:
            return {}

        # zone es un dict, no un objeto con atributos
        zone_level = zone.get("level", price) if isinstance(zone, dict) else zone.level
        zone_type = zone.get("zone_type", "support") if isinstance(zone, dict) else zone.zone_type
        zone_strength = zone.get("strength", 0.5) if isinstance(zone, dict) else zone.strength
        zone_touches = zone.get("touches", 1) if isinstance(zone, dict) else zone.touches
        zone_hold_rate = zone.get("hold_rate", 0.5) if isinstance(zone, dict) else zone.hold_rate

        is_at_zone = abs(zone_level - price) / price <= 0.001

        # Dirección esperada al estar en la zona
        if zone_type == "support":
            expected = "CALL"
            trend_aligned = dominant_trend == "uptrend" or dominant_trend == "neutral"
        elif zone_type == "resistance":
            expected = "PUT"
            trend_aligned = dominant_trend == "downtrend" or dominant_trend == "neutral"
        else:
            expected = "CALL" if dominant_trend == "uptrend" else "PUT"
            trend_aligned = True

        return {
            "at_zone": is_at_zone,
            "zone_type": zone_type,
            "zone_strength": zone_strength,
            "zone_touches": zone_touches,
            "zone_hold_rate": zone_hold_rate,
            "expected_direction": expected,
            "trend_aligned": trend_aligned,
            "level": zone_level,
        }

    def _expected_direction(self, dominant_trend: str, momentum: Dict,
                             zone_ctx: Dict, structure_m1: Dict) -> tuple:
        signals_call = 0
        signals_put = 0
        total = 0

        # Zona sugiere dirección
        if zone_ctx.get("expected_direction") == "CALL":
            signals_call += 3 * zone_ctx.get("zone_strength", 0.5)
            total += 3
        elif zone_ctx.get("expected_direction") == "PUT":
            signals_put += 3 * zone_ctx.get("zone_strength", 0.5)
            total += 3

        # Tendencia dominante
        if dominant_trend == "uptrend":
            signals_call += 2; total += 2
        elif dominant_trend == "downtrend":
            signals_put += 2; total += 2
        else:
            total += 2

        # RSI
        rsi = momentum.get("rsi_m1", 50)
        if rsi < 30:
            signals_call += 2; total += 2
        elif rsi > 70:
            signals_put += 2; total += 2
        else:
            total += 2

        # Divergencias
        if momentum.get("bullish_divergence"):
            signals_call += 2; total += 2
        elif momentum.get("bearish_divergence"):
            signals_put += 2; total += 2

        # M1 structure
        if structure_m1.get("hh") and structure_m1.get("hl"):
            signals_call += 1; total += 1
        elif structure_m1.get("lh") and structure_m1.get("ll"):
            signals_put += 1; total += 1
        else:
            total += 1

        if total == 0:
            return "NEUTRAL", 0.0

        call_score = signals_call / total
        put_score = signals_put / total

        if call_score > put_score and call_score >= 0.45:
            return "CALL", call_score
        elif put_score > call_score and put_score >= 0.45:
            return "PUT", put_score
        return "NEUTRAL", max(call_score, put_score)

    def _setup_quality(self, dominant_trend: str, momentum: Dict,
                        zone_ctx: Dict, phase: str, structure: Dict) -> float:
        """Score 0-1 de la calidad del setup actual."""
        score = 0.0
        checks = 0

        # Zona fuerte
        if zone_ctx.get("zone_strength", 0) >= 0.6:
            score += 1.0; checks += 1
        elif zone_ctx.get("zone_strength", 0) >= 0.4:
            score += 0.5; checks += 1
        else:
            checks += 1

        # Tendencia alineada con zona
        if zone_ctx.get("trend_aligned"):
            score += 1.0; checks += 1
        else:
            checks += 1

        # RSI en zona extrema
        rsi = momentum.get("rsi_m1", 50)
        if rsi < 25 or rsi > 75:
            score += 1.0; checks += 1
        elif rsi < 35 or rsi > 65:
            score += 0.6; checks += 1
        else:
            checks += 1

        # Fase de mercado favorable
        if phase in ("ranging", "trending_up", "trending_down"):
            score += 1.0; checks += 1
        elif phase == "dead":
            checks += 1
        else:
            score += 0.3; checks += 1

        # Divergencia confirmando
        if momentum.get("bullish_divergence") or momentum.get("bearish_divergence"):
            score += 1.0; checks += 1
        else:
            checks += 1

        return score / max(checks, 1)

    def _what_happened_before(self, df_m5: pd.DataFrame, price: float, zone) -> Dict:
        if len(df_m5) < 10:
            return {"approach": "unknown", "candles": []}

        last10 = df_m5.tail(10)
        closes = last10["close"].values
        direction = "up" if closes[-1] > closes[0] else "down"
        volatility = float(np.std(closes) / np.mean(closes) * 10000) if np.mean(closes) > 0 else 0

        # ¿El precio llega a la zona desde arriba o desde abajo?
        approach = "unknown"
        if zone:
            zone_level = zone.get("level", price) if isinstance(zone, dict) else zone.level
            zone_type = zone.get("zone_type", "support") if isinstance(zone, dict) else zone.zone_type
            above_zone = sum(1 for c in closes[:-3] if c > zone_level)
            below_zone = sum(1 for c in closes[:-3] if c <= zone_level)
            if zone_type == "support":
                approach = "falling_to_support" if direction == "down" else "already_at_support"
            elif zone_type == "resistance":
                approach = "rising_to_resistance" if direction == "up" else "already_at_resistance"

        return {
            "approach": approach,
            "direction_last_10": direction,
            "volatility_pips": volatility,
        }

    # ── Indicadores internos ──────────────────────────────────────────────────

    @staticmethod
    def _ema(data: np.ndarray, period: int) -> np.ndarray:
        if len(data) < period:
            return data
        alpha = 2.0 / (period + 1)
        ema = np.zeros(len(data))
        ema[period - 1] = np.mean(data[:period])
        for i in range(period, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        return ema

    @staticmethod
    def _rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
        if len(closes) < period + 1:
            return np.full(len(closes), 50.0)
        delta = np.diff(closes)
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)
        avg_gain = np.zeros(len(delta))
        avg_loss = np.zeros(len(delta))
        avg_gain[period - 1] = np.mean(gain[:period])
        avg_loss[period - 1] = np.mean(loss[:period])
        for i in range(period, len(delta)):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
        rs = np.where(avg_loss > 1e-10, avg_gain / np.where(avg_loss > 1e-10, avg_loss, 1e-10), 100.0)
        rsi = 100 - 100 / (1 + rs)
        return np.concatenate([[50.0], rsi])

    @staticmethod
    def _macd(closes: np.ndarray, fast=12, slow=26, signal=9):
        def ema(data, p):
            if len(data) < p:
                return data
            a = 2.0 / (p + 1)
            e = np.zeros(len(data))
            e[p - 1] = np.mean(data[:p])
            for i in range(p, len(data)):
                e[i] = a * data[i] + (1 - a) * e[i - 1]
            return e

        if len(closes) < slow + signal:
            z = np.zeros(len(closes))
            return z, z, z
        ema_fast = ema(closes, fast)
        ema_slow = ema(closes, slow)
        macd_line = ema_fast - ema_slow
        signal_line = ema(macd_line, signal)
        hist = macd_line - signal_line
        return macd_line, signal_line, hist

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> np.ndarray:
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        n = len(df)
        if n < 2:
            return np.zeros(n)
        tr = np.zeros(n)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(highs[i] - lows[i],
                        abs(highs[i] - closes[i - 1]),
                        abs(lows[i] - closes[i - 1]))
        atr = np.zeros(n)
        if n >= period:
            atr[period - 1] = np.mean(tr[:period])
            for i in range(period, n):
                atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        return atr

    @staticmethod
    def _empty_context() -> Dict:
        return {
            "dominant_trend": "neutral",
            "structure_m1": {"trend": "neutral"},
            "structure_m5": {"trend": "neutral"},
            "structure_m15": {"trend": "neutral"},
            "structure_h1": {"trend": "neutral"},
            "momentum": {"rsi_m1": 50, "rsi_m5": 50},
            "market_phase": "unknown",
            "zone_context": {},
            "expected_direction": "NEUTRAL",
            "direction_confidence": 0.0,
            "setup_quality": 0.0,
            "before_context": {},
            "current_price": 0.0,
        }
