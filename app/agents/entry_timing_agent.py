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
        #
        # BUG CORREGIDO: esto usaba `datetime.utcnow()` y NO el
        # `signal_timestamp` que la funcion recibe y ya habia normalizado dos
        # lineas mas arriba. En vivo la diferencia era pequena y pasaba
        # desapercibida; en un backtest con reloj virtual la vela tenia meses de
        # "antiguedad" y `age_ratio` salia de 41.000.000%, asi que el agente
        # devolvia TOO_LATE siempre. El backtest entero quedaba sin timing
        # valido y no se operaba nada -- un fallo silencioso que se parecia a
        # "el sistema es muy selectivo".
        #
        # Regla general: ningun componente de decision puede consultar el reloj
        # de pared. El unico reloj es el del feed.
        candle_age = (signal_timestamp - m1_last.open_time).total_seconds()
        candle_duration = m1_last.timeframe.value if hasattr(m1_last.timeframe, 'value') else 60
        age_ratio = candle_age / candle_duration if candle_duration > 0 else 1

        features["candle_age_sec"] = candle_age
        features["candle_duration_sec"] = candle_duration
        features["age_ratio"] = round(age_ratio, 4)

        # SEMANTICA CORREGIDA. "Demasiado tarde" significa: la vela que leo esta
        # EN FORMACION y ya casi cerro, asi que entrar ahora es entrar sobre una
        # forma que puede deshacerse en los ultimos segundos.
        #
        # La version anterior marcaba TOO_LATE para cualquier age_ratio por
        # encima del maximo, INCLUIDO age_ratio >= 1.0. Con un feed causal -- que
        # solo entrega velas CERRADAS -- y un ciclo alineado al minuto, la ultima
        # vela tiene SIEMPRE exactamente el 100% de edad. Resultado: TOO_LATE en
        # cada ciclo y cero operaciones, lo que se parecia a "el sistema es muy
        # selectivo" pero era un fallo de semantica.
        #
        # Una vela que ACABA de cerrar no es "tarde": es el mejor momento. La
        # senal se genero con velas cerradas y el precio de entrada es el actual.
        if 1.0 > age_ratio > self.max_candle_age_ratio:
            reasons.append(f"Vela en formacion al {age_ratio*100:.0f}% - demasiado tarde")
            return self._result(EntryTiming.TOO_LATE, "; ".join(reasons), features)

        # WAIT_CONFIRMATION: la vela en formacion aun no tiene recorrido suficiente
        if age_ratio < self.min_age_ratio:
            reasons.append(f"Vela solo al {age_ratio*100:.0f}%, esperando confirmacion")
            return self._result(EntryTiming.WAIT_CONFIRMATION, "; ".join(reasons), features)

        if age_ratio >= 1.0:
            features["at_candle_boundary"] = True

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
