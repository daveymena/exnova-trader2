"""
Retracement Timing Analyzer — mide cuánto ha durado y qué tan profundo va
un retroceso en curso frente a lo típico para ese mismo tramo de precio,
para distinguir un pullback que ya maduró (probable continuación de
tendencia) de uno que se extendió demasiado (probable invalidación).

Reutiliza los pivots (peaks/troughs) que ya calcula
ContextAnalyzer._market_structure — no vuelve a detectar swings.
"""
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Retroceso "típico" por defecto cuando aún no hay suficientes tramos
# previos en la ventana de velas para construir una línea base propia.
DEFAULT_TYPICAL_CANDLES = 5.0
DEFAULT_TYPICAL_DEPTH_PCT = 0.5


class RetracementTimingAnalyzer:

    def analyze(self, df: pd.DataFrame, structure: Dict, timeframe_minutes: int) -> Dict:
        if df is None or len(df) < 20 or not structure:
            return self._empty("datos insuficientes")

        trend = structure.get("trend", "neutral")
        peaks = structure.get("peaks") or []
        troughs = structure.get("troughs") or []
        n = structure.get("n_candles", len(df))

        if trend == "uptrend":
            direction = "up"
            retrace_from = self._find_last(peaks)
            leg_start = self._find_last(troughs, before_idx=retrace_from[0]) if retrace_from else None
        elif trend == "downtrend":
            direction = "down"
            retrace_from = self._find_last(troughs)
            leg_start = self._find_last(peaks, before_idx=retrace_from[0]) if retrace_from else None
        else:
            return self._empty("sin tendencia clara, no aplica timing de retroceso")

        if retrace_from is None or leg_start is None:
            return self._empty("pivots insuficientes para medir el impulso previo")

        retrace_from_idx, retrace_from_price = retrace_from
        # Un pivot recién formado tarda `right` velas en confirmarse (necesita
        # velas posteriores más bajas/altas). Si el precio ya hizo un extremo
        # más reciente y más extremo que el último pivot confirmado, ese es el
        # verdadero inicio del retroceso en curso — usar el pivot confirmado a
        # secas subestimaría cuánto ha durado/avanzado un retroceso que acaba
        # de empezar.
        retrace_from_idx, retrace_from_price = self._extend_to_raw_extreme(
            df, direction, retrace_from_idx, retrace_from_price
        )
        impulse_start_price = leg_start[1]
        impulse_range = abs(retrace_from_price - impulse_start_price)
        if impulse_range <= 0:
            return self._empty("impulso previo sin rango")

        current_price = float(df["close"].iloc[-1])
        candles_elapsed = max(n - 1 - retrace_from_idx, 0)
        minutes_elapsed = candles_elapsed * timeframe_minutes

        if direction == "up":
            retraced = retrace_from_price - current_price
            broke_prior_extreme = current_price < impulse_start_price
        else:
            retraced = current_price - retrace_from_price
            broke_prior_extreme = current_price > impulse_start_price
        retracement_depth_pct = max(retraced, 0.0) / impulse_range

        typical_candles, typical_depth = self._historical_baseline(peaks, troughs, direction)

        if broke_prior_extreme or retracement_depth_pct > 1.05:
            stage, bias = "invalidated", "reversal_watch"
        elif candles_elapsed < typical_candles * 0.6 and retracement_depth_pct < typical_depth * 0.6:
            stage, bias = "developing", "wait"
        elif candles_elapsed <= typical_candles * 1.4 and retracement_depth_pct <= max(typical_depth * 1.4, 0.786):
            stage, bias = "mature", "continuation"
        else:
            stage, bias = "extended", "reversal_watch"

        expected_direction = "NEUTRAL"
        if bias == "continuation":
            expected_direction = "CALL" if direction == "up" else "PUT"

        return {
            "direction": direction,
            "retracement_depth_pct": round(retracement_depth_pct, 3),
            "candles_elapsed": candles_elapsed,
            "minutes_elapsed": minutes_elapsed,
            "typical_candles": round(typical_candles, 1),
            "typical_depth_pct": round(typical_depth, 3),
            "stage": stage,
            "bias": bias,
            "expected_direction": expected_direction,
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extend_to_raw_extreme(df: pd.DataFrame, direction: str, idx: int, price: float) -> Tuple[int, float]:
        """Busca, después del último pivot confirmado, si el precio crudo
        (sin confirmar todavía como pivot) llegó más lejos — y si es así,
        usa ese punto como el verdadero inicio del retroceso en curso."""
        tail = df.iloc[idx + 1:]
        if tail.empty:
            return idx, price
        if direction == "up":
            pos = int(tail["high"].values.argmax())
            candidate_price = float(tail["high"].iloc[pos])
            if candidate_price > price:
                return idx + 1 + pos, candidate_price
        else:
            pos = int(tail["low"].values.argmin())
            candidate_price = float(tail["low"].iloc[pos])
            if candidate_price < price:
                return idx + 1 + pos, candidate_price
        return idx, price

    @staticmethod
    def _find_last(points: List[Tuple[int, float]], before_idx: Optional[int] = None) -> Optional[Tuple[int, float]]:
        if not points:
            return None
        if before_idx is None:
            return points[-1]
        candidates = [p for p in points if p[0] < before_idx]
        return candidates[-1] if candidates else None

    @staticmethod
    def _historical_baseline(peaks: List[Tuple[int, float]], troughs: List[Tuple[int, float]],
                              direction: str) -> Tuple[float, float]:
        """
        Mide, dentro de los mismos pivots ya detectados, cuánto duraron y qué
        tan profundos fueron retrocesos anteriores del mismo tipo, para usarlos
        como línea base en vivo (sin depender de almacenamiento externo).
        """
        tagged = sorted(
            [(idx, price, "peak") for idx, price in peaks] +
            [(idx, price, "trough") for idx, price in troughs],
            key=lambda t: t[0],
        )
        want_retrace_type = "trough" if direction == "up" else "peak"
        durations, depths = [], []
        for i in range(len(tagged) - 2):
            a, b, c = tagged[i], tagged[i + 1], tagged[i + 2]
            if a[2] == b[2] or b[2] == c[2] or c[2] != want_retrace_type:
                continue
            impulse = abs(b[1] - a[1])
            if impulse <= 0:
                continue
            durations.append(c[0] - b[0])
            depths.append(abs(c[1] - b[1]) / impulse)

        if not durations:
            return DEFAULT_TYPICAL_CANDLES, DEFAULT_TYPICAL_DEPTH_PCT
        durations.sort()
        depths.sort()
        return durations[len(durations) // 2], depths[len(depths) // 2]

    @staticmethod
    def _empty(note: str) -> Dict:
        return {
            "direction": "neutral",
            "retracement_depth_pct": 0.0,
            "candles_elapsed": 0,
            "minutes_elapsed": 0,
            "typical_candles": 0.0,
            "typical_depth_pct": 0.0,
            "stage": "unclear",
            "bias": "wait",
            "expected_direction": "NEUTRAL",
            "note": note,
        }
