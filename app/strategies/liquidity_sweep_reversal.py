# -*- coding: utf-8 -*-
"""REVERSION POR BARRIDO DE LIQUIDEZ (Smart Money Concepts / Wyckoff).

QUE BUSCA
---------
El patron mas caracteristico de los feeds OTC y el que mas estrategias ingenuas
de ruptura destruye: el precio perfora un maximo/minimo relevante -- donde se
acumulan los stops y las entradas por breakout -- y cierra de vuelta dentro del
rango. Wyckoff lo llama `spring` (abajo) y `upthrust` (arriba); en SMC es un
`liquidity sweep` o `stop hunt`.

La logica operativa: quien barre liquidez por debajo de un minimo igualado esta
comprando las ventas forzadas de los que tenian stop ahi. Si el precio no
consigue continuar abajo y cierra por encima del nivel, la barra fue absorcion,
no ruptura. Se entra EN CONTRA del barrido.

POR QUE ESTA AQUI Y NO SOLO EN `sr_bounce`
------------------------------------------
`sr_bounce` busca rechazo en un nivel estatico (soporte/resistencia por swing).
Esta busca barrido de un POOL DE LIQUIDEZ: varios swing highs/lows alineados al
mismo precio ("equal highs"/"equal lows"). Son cosas distintas y tienen distinta
estadistica; mezclarlas en un solo setup impide medirlas por separado, que es
justo lo que el `SetupEvaluator` necesita.

REGLAS CAUSALES
---------------
Solo se usan velas cerradas. Un fractal sin confirmar (que necesita `right`
velas posteriores) no cuenta: `swing_points()` ya excluye las ultimas. El
barrido se confirma con la vela M1 YA CERRADA que perforo y volvio, y la
entrada seria en la vela siguiente -- que es la que el motor abrira.

HONESTIDAD SOBRE `confidence`
-----------------------------
No es una probabilidad calibrada. Es una composicion acotada de factores
observables (fuerza del rechazo, cuantas veces se toco el pool, alineacion de
temporalidades superiores). Sirve para ordenar oportunidades entre si, NO para
afirmar nada sobre el resultado. Lo que decide si se opera es la muestra real
del setup en `SetupEvaluator`.
"""
from __future__ import annotations

from typing import Optional, Sequence

from app.data.schemas import Candle, Direction, MarketRegime
from app.strategies.base import (
    Strategy, atr, atr_percentile, candle_patterns, closes, ema, rsi,
    swing_points,
)


class LiquiditySweepReversal(Strategy):
    name = "liquidity_sweep_reversal"
    family = "sweep_reversal"
    expiries = (180, 300)

    param_space = {
        # Tolerancia para considerar dos swings "al mismo precio", en ATR.
        "level_tolerance_atr": (0.10, 0.60),
        # Minimo de toques del pool para que sea liquidez de verdad. Con 2 ya
        # hay equal highs/lows; exigir mas reduce muestra y retrasa la senal.
        "min_pool_touches": (2, 5),
        # La mecha debe superar el nivel al menos esto (en ATR) para ser barrido
        # y no un simple roce. Un roce no activa stops.
        "min_pierce_atr": (0.05, 0.80),
        # Cuerpo/maximo de la vela de rechazo: cuanto mas pequeno el cuerpo
        # relativo al rango, mas absorcion y menos conviccion direccional.
        "max_rejection_body_pct": (0.25, 0.65),
        "min_wick_to_body": (1.0, 4.0),
        "max_atr_percentile": (0.55, 0.98),
        "rsi_extreme": (5.0, 35.0),
        "require_htf_agreement": (0, 1),
        "min_confidence": (0.30, 0.80),
    }

    @classmethod
    def default_params(cls) -> dict:
        return {
            "level_tolerance_atr": 0.25,
            "min_pool_touches": 2,
            "min_pierce_atr": 0.15,
            "max_rejection_body_pct": 0.50,
            "min_wick_to_body": 1.6,
            "max_atr_percentile": 0.90,
            "rsi_extreme": 25.0,
            "require_htf_agreement": 0,
            "min_confidence": 0.50,
            "lookback_m5": 60,
            "lookback_m15": 40,
            "m1_rejection_window": 3,
        }

    # ── evaluacion ────────────────────────────────────────────────────────

    def evaluate(self, candles_m15: Sequence[Candle], candles_m5: Sequence[Candle],
                 candles_m1: Sequence[Candle], asset: str = "") -> dict:
        p = self.params
        m15 = self._clean(self._sorted(candles_m15))
        m5 = self._clean(self._sorted(candles_m5))
        m1 = self._clean(self._sorted(candles_m1))

        if len(m15) < 15 or len(m5) < 20 or len(m1) < 8:
            return self._no_trade(
                [f"velas insuficientes (M15={len(m15)} M5={len(m5)} M1={len(m1)})"])

        atr_m1 = atr(m1, 14)
        atr_m5 = atr(m5, 14)
        if not atr_m1 or not atr_m5 or atr_m1 <= 0:
            return self._no_trade(["ATR no calculable"])

        features = {
            "atr_m1": round(atr_m1, 6),
            "atr_m5": round(atr_m5, 6),
            "atr_percentile_m5": round(atr_percentile(m5, 14) or 0.0, 4),
        }

        # ── filtro de volatilidad ─────────────────────────────────────────
        pct = features["atr_percentile_m5"]
        if pct > p["max_atr_percentile"]:
            # En volatilidad extrema los barridos no revierten: el precio
            # simplemente sigue. Entrar adivinando el final del movimiento es
            # la forma mas rapida de perder en OTC.
            features["rejected_by"] = "volatilidad"
            return self._no_trade(
                [f"ATR percentile {pct:.2f} > {p['max_atr_percentile']:.2f}"], features)

        regime = self._classify_regime(m15, m5)
        features["regime"] = regime.value

        # ── pools de liquidez en M5 ───────────────────────────────────────
        highs, lows = swing_points(m5[-p["lookback_m5"]:], left=2, right=2)
        tolerance = atr_m5 * p["level_tolerance_atr"]
        buy_pool = self._find_pool(lows, tolerance, p["min_pool_touches"])
        sell_pool = self._find_pool(highs, tolerance, p["min_pool_touches"])
        features["buy_pool"] = round(buy_pool["level"], 6) if buy_pool else None
        features["sell_pool"] = round(sell_pool["level"], 6) if sell_pool else None
        features["buy_pool_touches"] = buy_pool["touches"] if buy_pool else 0
        features["sell_pool_touches"] = sell_pool["touches"] if sell_pool else 0

        last = m1[-1]
        price = last.close
        features["price"] = round(price, 6)

        # ── CALL: barrido del pool de lows (spring) ───────────────────────
        if buy_pool:
            hit = self._detect_sweep(m1, buy_pool["level"], atr_m1, side="low")
            if hit:
                candle, pierce = hit
                features.update({
                    "sweep_side": "low", "pierce_atr": round(pierce / atr_m1, 4),
                    "sweep_wick": round(candle.lower_wick, 6),
                    "sweep_body_pct": round(candle.body_pct, 4),
                })
                confidence, why = self._score(
                    candle, pierce, atr_m1, buy_pool, side="low",
                    m1=m1, m5=m5, m15=m15, regime=regime)
                if confidence >= p["min_confidence"] and self._htf_ok(regime, Direction.CALL):
                    return self._signal(
                        Direction.CALL, confidence, regime,
                        rationale=(
                            f"Barrido de liquidez bajo {buy_pool['level']:.6f} "
                            f"({buy_pool['touches']} toques iguales), mecha de "
                            f"{pierce / atr_m1:.2f} ATR y cierre de vuelta dentro "
                            f"del rango. Absorcion vendedora: {why}"
                        ),
                        invalidation=(
                            f"Invalido si el precio cierra otra vela M1 por debajo de "
                            f"{buy_pool['level']:.6f} sin mecha de rechazo, o si el "
                            f"M15 pasa a tendencia bajista con ADX>25."
                        ),
                        features=features,
                    )
                features["sweep_rejected"] = why

        # ── PUT: barrido del pool de highs (upthrust) ─────────────────────
        if sell_pool:
            hit = self._detect_sweep(m1, sell_pool["level"], atr_m1, side="high")
            if hit:
                candle, pierce = hit
                features.update({
                    "sweep_side": "high", "pierce_atr": round(pierce / atr_m1, 4),
                    "sweep_wick": round(candle.upper_wick, 6),
                    "sweep_body_pct": round(candle.body_pct, 4),
                })
                confidence, why = self._score(
                    candle, pierce, atr_m1, sell_pool, side="high",
                    m1=m1, m5=m5, m15=m15, regime=regime)
                if confidence >= p["min_confidence"] and self._htf_ok(regime, Direction.PUT):
                    return self._signal(
                        Direction.PUT, confidence, regime,
                        rationale=(
                            f"Barrido de liquidez sobre {sell_pool['level']:.6f} "
                            f"({sell_pool['touches']} toques iguales), mecha de "
                            f"{pierce / atr_m1:.2f} ATR y cierre de vuelta dentro "
                            f"del rango. Absorcion compradora: {why}"
                        ),
                        invalidation=(
                            f"Invalido si el precio cierra otra vela M1 por encima de "
                            f"{sell_pool['level']:.6f} sin mecha de rechazo, o si el "
                            f"M15 pasa a tendencia alcista con ADX>25."
                        ),
                        features=features,
                    )
                features["sweep_rejected"] = why

        features["rejected_by"] = features.get("rejected_by", "sin barrido confirmado")
        return self._no_trade(["no hay barrido de liquidez confirmado"], features, regime)

    # ── piezas ────────────────────────────────────────────────────────────

    @staticmethod
    def _find_pool(levels: Sequence[float], tolerance: float,
                   min_touches: int) -> Optional[dict]:
        """Agrupa swings al mismo precio y devuelve el pool mas poblado.

        Un pool de 4 toques es liquidez de verdad; 2 toques casuales no. Se
        elige el mas poblado y, a igualdad de poblacion, el de nivel mas
        extremo (que es donde mas stops se acumulan).

        NOTA: la version anterior de este metodo hacia
        `sum(cluster)/len(cluster)` dentro del `else` sin comprobar que el
        cluster estuviera poblado, y en la primera iteracion -- cuando el
        cluster aun esta vacio -- lanzaba ZeroDivisionError. La estrategia
        entera quedaba inutilizada en silencio: el motor captura la excepcion
        y sigue, asi que el bot simplemente dejaba de ver barridos para
        siempre sin que nadie lo notara.
        """
        if not levels or tolerance <= 0 or min_touches < 1:
            return None
        ordered = sorted(levels)
        clusters: list[list[float]] = [[ordered[0]]]
        for value in ordered[1:]:
            if value - clusters[-1][0] <= tolerance:
                clusters[-1].append(value)
            else:
                clusters.append([value])

        best: Optional[dict] = None
        for cluster in clusters:
            if len(cluster) < min_touches:
                continue
            candidate = {
                "level": sum(cluster) / len(cluster),
                "touches": len(cluster),
            }
            if best is None or candidate["touches"] > best["touches"]:
                best = candidate
        return best

    def _detect_sweep(self, m1: Sequence[Candle], level: float, atr_m1: float,
                      side: str) -> Optional[tuple[Candle, float]]:
        """Busca en las ultimas velas M1 una que perforo el nivel y volvio.

        `side='low'`  -> la mecha inferior atraveso `level` y el cierre quedo por
                         encima (spring: se barre liquidez vendedora).
        `side='high'` -> la mecha superior atraveso `level` y el cierre quedo por
                         debajo (upthrust).
        """
        p = self.params
        min_pierce = atr_m1 * p["min_pierce_atr"]
        window = m1[-p["m1_rejection_window"]:]
        # Se recorre de mas reciente a mas antigua: interesa el ULTIMO barrido,
        # no uno de hace 3 velas que ya se jugo.
        for candle in reversed(window):
            if candle.range <= 0:
                continue
            if side == "low":
                pierce = level - candle.low
                if pierce >= min_pierce and candle.close > level:
                    return candle, pierce
            else:
                pierce = candle.high - level
                if pierce >= min_pierce and candle.close < level:
                    return candle, pierce
        return None

    def _score(self, candle: Candle, pierce: float, atr_m1: float, pool: dict,
               side: str, m1: Sequence[Candle], m5: Sequence[Candle],
               m15: Sequence[Candle], regime: MarketRegime) -> tuple[float, str]:
        """Compone la confianza a partir de factores observables.

        Cada componente suma una fraccion acotada y se reporta en `why`, de
        modo que la senal es auditable: se puede ver exactamente que aporto
        cada cosa. Una confianza que no se puede descomponer no se puede
        mejorar, y este proyecto vive de mejorar cosas.
        """
        p = self.params
        parts: list[str] = []
        score = 0.30
        parts.append("base 0.30")

        # 1. Tamano del pool: mas toques iguales = mas liquidez acumulada.
        touches = pool["touches"]
        if touches >= 4:
            score += 0.15; parts.append(f"pool de {touches} toques +0.15")
        elif touches >= 3:
            score += 0.10; parts.append(f"pool de {touches} toques +0.10")
        else:
            score += 0.05; parts.append(f"pool de {touches} toques +0.05")

        # 2. Profundidad del barrido: una mecha que solo roza el nivel no
        #    activa stops. Pero una mecha desmesurada es panico, no absorcion.
        pierce_atr = pierce / atr_m1 if atr_m1 else 0.0
        if p["min_pierce_atr"] <= pierce_atr <= 1.5:
            score += 0.15; parts.append(f"barrido {pierce_atr:.2f} ATR +0.15")
        elif pierce_atr <= 3.0:
            score += 0.05; parts.append(f"barrido profundo {pierce_atr:.2f} ATR +0.05")

        # 3. Forma de la vela de rechazo: mecha larga y cuerpo pequeno es
        #    absorcion. Un cuerpo grande en la direccion del barrido es
        #    continuacion, no reversion.
        body = candle.body
        wick = candle.lower_wick if side == "low" else candle.upper_wick
        if body > 0 and wick / body >= p["min_wick_to_body"]:
            score += 0.15; parts.append(f"mecha/cuerpo {wick / body:.2f} +0.15")
        if candle.body_pct <= p["max_rejection_body_pct"]:
            score += 0.05; parts.append(f"cuerpo {candle.body_pct:.2f} del rango +0.05")

        # 4. Agotamiento en M1: RSI extremo apoya la reversion.
        r = rsi(closes(m1), 14)
        if r is not None:
            if side == "low" and r <= p["rsi_extreme"]:
                score += 0.10; parts.append(f"RSI M1 {r:.1f} sobresold +0.10")
            elif side == "high" and r >= 100 - p["rsi_extreme"]:
                score += 0.10; parts.append(f"RSI M1 {r:.1f} sobrecomprado +0.10")
            elif r is not None and (side == "low" and r > 60 or side == "high" and r < 40):
                score -= 0.15; parts.append(f"RSI M1 {r:.1f} en contra -0.15")

        # 5. Contexto de temporalidad superior. Un barrido contra una tendencia
        #    M15 fuerte es coger un cuchillo cayendo: penaliza.
        if regime == MarketRegime.TREND_DOWN and side == "low":
            score -= 0.20; parts.append("M15 en tendencia bajista -0.20")
        elif regime == MarketRegime.TREND_UP and side == "high":
            score -= 0.20; parts.append("M15 en tendencia alcista -0.20")
        elif regime == MarketRegime.RANGE:
            score += 0.10; parts.append("M15 en rango (contexto ideal) +0.10")

        return max(0.0, min(1.0, score)), ", ".join(parts)

    def _htf_ok(self, regime: MarketRegime, direction: Direction) -> bool:
        """Veto de temporalidad superior si el parametro lo exige."""
        if not self.params.get("require_htf_agreement"):
            return True
        if direction == Direction.CALL:
            return regime != MarketRegime.TREND_DOWN
        return regime != MarketRegime.TREND_UP

    def _classify_regime(self, m15: Sequence[Candle], m5: Sequence[Candle]) -> MarketRegime:
        """Regimen simplificado, solo para anotar la senal.

        El regimen autoritativo lo calcula `MarketRegimeAgent` (ADX + ATR
        percentile + pendiente de EMA) y lo usa el motor. Aqui solo hace falta
        una lectura de contexto para puntuar; duplicar el clasificador completo
        crearia dos fuentes de verdad sobre el mismo concepto.
        """
        from app.strategies.base import adx, atr_percentile, ema_slope
        slope = ema_slope(closes(m15), 20, 5)
        strength = adx(m15, 14)
        vol = atr_percentile(m5, 14)
        if vol is not None and vol > 0.90:
            return MarketRegime.HIGH_VOLATILITY
        if slope is None or strength is None:
            return MarketRegime.UNKNOWN
        if strength >= 25 and slope > 0.0004:
            return MarketRegime.TREND_UP
        if strength >= 25 and slope < -0.0004:
            return MarketRegime.TREND_DOWN
        return MarketRegime.RANGE
