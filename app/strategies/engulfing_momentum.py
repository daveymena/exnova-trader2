# -*- coding: utf-8 -*-
"""MOMENTUM POR VELA ENVOLVENTE en el sentido de la tendencia superior.

QUE BUSCA
---------
Continuacion, no reversion. En M15 hay tendencia confirmada (ADX por encima del
umbral y EMA con pendiente); el precio retrocede a la EMA rapida de M5; y una
vela M1 envolvente rechaza ese retroceso en el sentido de la tendencia. Se entra
a favor.

POR QUE ESTA FAMILIA Y NO OTRA
------------------------------
`trend_continuation` ya existe y usa cruce de EMAs con retroceso. Esta se
diferencia en el DISPARADOR: exige un patron de velas concreto (envolvente) con
cuerpo dominante, no solo "el precio volvio a subir". Son hipotesis distintas y
deben medirse por separado: el `SetupEvaluator` las tratara como setups
distintos y la estadistica dira cual sobrevive. Fusionarlas en una sola
estrategia ocultaria cual de las dos aporta el edge.

FILTROS QUE IMPORTAN EN BINARIAS
--------------------------------
* ADX minimo: sin fuerza de tendencia, una envolvente es ruido. En un mercado
  lateral las envolventes aparecen constantemente y no significan nada.
* Retroceso contenido: si el precio se alejo demasiado de la EMA, ya no es un
  retroceso sino un cambio de estructura.
* Volumen/cuerpo: el cuerpo de la envolvente debe dominar el rango. Una
  envolvente con mechas enormes es indecision, no momentum.
* Volatilidad acotada: en el percentil alto de ATR la expiracion corta se
  convierte en una moneda al aire, porque el recorrido hasta la liquidacion es
  puro ruido.

HONESTIDAD
----------
`confidence` es una composicion acotada de factores observables, no una
probabilidad calibrada. Ninguna envolvente "funciona el 80% de las veces": ese
numero, que aparece en la descripcion de varios bots publicos de senales para
Quotex y Pocket Option, no sobrevive a un test out-of-sample. Lo unico que
sostiene una afirmacion asi es la muestra real del setup, con su intervalo de
Wilson.
"""
from __future__ import annotations

from typing import Sequence

from app.data.schemas import Candle, Direction, MarketRegime
from app.strategies.base import (
    Strategy, adx, atr, atr_percentile, closes, directional_movement, ema,
    ema_series, ema_slope, is_stale, rsi,
)


class EngulfingMomentum(Strategy):
    name = "engulfing_momentum"
    family = "trend_continuation"
    expiries = (180, 300)

    param_space = {
        "adx_min": (18.0, 40.0),
        "ema_fast": (8, 34),
        "ema_slow": (34, 100),
        "pullback_max_atr": (0.5, 3.0),
        "min_body_pct": (0.50, 0.90),
        "min_engulf_ratio": (1.0, 2.5),
        "max_atr_percentile": (0.55, 0.98),
        "rsi_band_low": (35.0, 55.0),
        "rsi_band_high": (45.0, 65.0),
        "min_confidence": (0.30, 0.80),
    }

    @classmethod
    def default_params(cls) -> dict:
        return {
            "adx_min": 22.0,
            "ema_fast": 9,
            "ema_slow": 21,
            "pullback_max_atr": 1.8,
            "min_body_pct": 0.60,
            "min_engulf_ratio": 1.1,
            "max_atr_percentile": 0.90,
            "rsi_band_low": 45.0,
            "rsi_band_high": 55.0,
            "min_confidence": 0.55,
            "lookback_m15": 60,
            "lookback_m5": 40,
        }

    def evaluate(self, candles_m15: Sequence[Candle], candles_m5: Sequence[Candle],
                 candles_m1: Sequence[Candle], asset: str = "") -> dict:
        p = self.params
        m15 = self._clean(self._sorted(candles_m15))
        m5 = self._clean(self._sorted(candles_m5))
        m1 = self._clean(self._sorted(candles_m1))

        if len(m15) < 30 or len(m5) < 25 or len(m1) < 10:
            return self._no_trade(
                [f"velas insuficientes (M15={len(m15)} M5={len(m5)} M1={len(m1)})"])
        if p["ema_fast"] >= p["ema_slow"]:
            # Parametros inconsistentes: la EMA rapida debe ser mas corta que la
            # lenta. Mejor rechazar explicitamente que producir senales sin
            # sentido con una config que el motor de mejora pudo generar mal.
            return self._no_trade(
                [f"config invalida: ema_fast={p['ema_fast']} >= ema_slow={p['ema_slow']}"])

        atr_m1 = atr(m1, 14)
        atr_m5 = atr(m5, 14)
        if not atr_m1 or not atr_m5 or atr_m1 <= 0:
            return self._no_trade(["ATR no calculable"])

        strength = adx(m15[-p["lookback_m15"]:], 14)
        pdi, mdi = directional_movement(m15[-p["lookback_m15"]:], 14)
        slope15 = ema_slope(closes(m15), 20, 5)
        vol_pct = atr_percentile(m5, 14) or 0.0

        features = {
            "adx_m15": round(strength, 2) if strength is not None else None,
            "pdi_m15": round(pdi, 2) if pdi is not None else None,
            "mdi_m15": round(mdi, 2) if mdi is not None else None,
            "ema_slope_m15": round(slope15, 6) if slope15 is not None else None,
            "atr_m1": round(atr_m1, 6),
            "atr_percentile_m5": round(vol_pct, 4),
        }

        if strength is None or pdi is None or mdi is None or slope15 is None:
            return self._no_trade(["indicadores de tendencia no calculables"], features)

        # ── 1. fuerza de tendencia en M15 ─────────────────────────────────
        if strength < p["adx_min"]:
            features["rejected_by"] = "adx"
            return self._no_trade(
                [f"ADX M15 {strength:.1f} < {p['adx_min']:.1f}: sin fuerza de tendencia"],
                features)

        # ── 2. direccion ──────────────────────────────────────────────────
        if pdi > mdi and slope15 > 0:
            direction, regime = Direction.CALL, MarketRegime.TREND_UP
        elif mdi > pdi and slope15 < 0:
            direction, regime = Direction.PUT, MarketRegime.TREND_DOWN
        else:
            # DI y pendiente de EMA en desacuerdo: la tendencia no esta clara.
            # Entrar aqui es apostar a cual de los dos indicadores tiene razon.
            features["rejected_by"] = "direccion_ambigua"
            return self._no_trade(
                [f"+DI/-DI y pendiente de EMA en desacuerdo "
                 f"(+DI={pdi:.1f} -DI={mdi:.1f} slope={slope15:.5f})"],
                features, MarketRegime.RANGE)

        features["direction_htf"] = direction.value

        # ── 3. volatilidad acotada ────────────────────────────────────────
        if vol_pct > p["max_atr_percentile"]:
            features["rejected_by"] = "volatilidad"
            return self._no_trade(
                [f"ATR percentile {vol_pct:.2f} > {p['max_atr_percentile']:.2f}"],
                features, regime)

        # ── 4. retroceso contenido hacia la EMA rapida de M5 ──────────────
        ema_fast = ema_series(closes(m5), p["ema_fast"])
        ema_slow = ema_series(closes(m5), p["ema_slow"])
        if len(ema_fast) < 3 or len(ema_slow) < 3:
            return self._no_trade(["EMA de M5 no calculable"], features, regime)
        pullback = abs(m5[-1].close - ema_fast[-1]) / atr_m5 if atr_m5 else None
        features["pullback_atr"] = round(pullback, 4) if pullback is not None else None
        features["ema_fast_m5"] = round(ema_fast[-1], 6)
        features["ema_slow_m5"] = round(ema_slow[-1], 6)
        if pullback is not None and pullback > p["pullback_max_atr"]:
            features["rejected_by"] = "retroceso_excesivo"
            return self._no_trade(
                [f"retroceso de {pullback:.2f} ATR > {p['pullback_max_atr']:.2f}: "
                 f"ya no es un pullback, es cambio de estructura"], features, regime)

        # Orden de EMAs: rapida por encima de lenta en alcista, al reves en bajista.
        if (direction == Direction.CALL and ema_fast[-1] < ema_slow[-1]) or \
           (direction == Direction.PUT and ema_fast[-1] > ema_slow[-1]):
            features["rejected_by"] = "cruce_de_emas"
            return self._no_trade(
                ["las EMAs de M5 no confirman la direccion de M15"], features, regime)

        # ── 5. disparador: envolvente en M1 ───────────────────────────────
        if len(m1) < 2:
            return self._no_trade(["sin velas M1 para el disparador"], features, regime)
        prev, last = m1[-2], m1[-1]
        if is_stale(prev) or is_stale(last):
            features["rejected_by"] = "vela_stale"
            return self._no_trade(
                ["vela M1 sin informacion (stale/plana): no se puede leer el patron"],
                features, regime)

        prev_body = prev.body
        engulfing = (
            last.is_bullish and not prev.is_bullish
            and last.close >= prev.open and last.open <= prev.close
        ) if direction == Direction.CALL else (
            not last.is_bullish and prev.is_bullish
            and last.open >= prev.close and last.close <= prev.open
        )
        ratio = (last.body / prev_body) if prev_body > 0 else float("inf")
        features["engulfing"] = engulfing
        features["engulf_ratio"] = round(ratio, 3) if ratio != float("inf") else None
        features["last_body_pct"] = round(last.body_pct, 4)

        if not engulfing:
            features["rejected_by"] = "sin_envolvente"
            return self._no_trade(
                ["la ultima vela M1 no es envolvente en el sentido de la tendencia"],
                features, regime)
        if ratio != float("inf") and ratio < p["min_engulf_ratio"]:
            features["rejected_by"] = "envolvente_debil"
            return self._no_trade(
                [f"cuerpo envolvente {ratio:.2f}x el anterior < {p['min_engulf_ratio']:.2f}x"],
                features, regime)
        if last.body_pct < p["min_body_pct"]:
            features["rejected_by"] = "cuerpo_pequeno"
            return self._no_trade(
                [f"cuerpo {last.body_pct:.2f} del rango < {p['min_body_pct']:.2f}: "
                 f"hay indecision, no momentum"], features, regime)

        # ── 6. RSI no agotado ─────────────────────────────────────────────
        r = rsi(closes(m1), 14)
        features["rsi_m1"] = round(r, 2) if r is not None else None
        rsi_penalty = 0.0
        if r is not None:
            if direction == Direction.CALL and r >= 100 - p["rsi_band_low"]:
                # RSI alto en un CALL de continuacion: el movimiento ya recorrio
                # demasiado y la expiracion corta puede pillar la correccion.
                rsi_penalty = 0.15
                features["rsi_warning"] = f"RSI {r:.1f} agotado al alza"
            elif direction == Direction.PUT and r <= p["rsi_band_high"] - 30:
                rsi_penalty = 0.15
                features["rsi_warning"] = f"RSI {r:.1f} agotado a la baja"

        confidence, why = self._score(strength, p["adx_min"], ratio,
                                      p["min_engulf_ratio"], last.body_pct,
                                      p["min_body_pct"], pullback,
                                      p["pullback_max_atr"], rsi_penalty)
        features["confidence_breakdown"] = why
        if confidence < p["min_confidence"]:
            features["rejected_by"] = "confianza"
            return self._no_trade(
                [f"confianza {confidence:.2f} < {p['min_confidence']:.2f} ({why})"],
                features, regime)

        return self._signal(
            direction, confidence, regime,
            rationale=(
                f"Tendencia M15 confirmada (ADX {strength:.1f}, "
                f"{'+' if direction == Direction.CALL else '-'}DI dominante, "
                f"pendiente EMA {slope15:+.5f}); retroceso de "
                f"{(pullback or 0):.2f} ATR a la EMA{p['ema_fast']} de M5 y vela "
                f"M1 envolvente de {ratio:.2f}x con cuerpo {last.body_pct:.2f} del "
                f"rango. Puntuacion: {why}"
            ),
            invalidation=(
                f"Invalido si el ADX M15 cae por debajo de {p['adx_min']:.0f}, si el "
                f"precio pierde la EMA{p['ema_slow']} de M5 "
                f"({ema_slow[-1]:.6f}), o si aparece una envolvente contraria."
            ),
            features=features,
        )

    @staticmethod
    def _score(strength: float, adx_min: float, ratio: float, min_ratio: float,
               body_pct: float, min_body_pct: float, pullback, pullback_max: float,
               rsi_penalty: float) -> tuple[float, str]:
        """Confianza compuesta. Cada componente es acotado y se reporta."""
        parts: list[str] = []
        score = 0.35
        parts.append("base 0.35")

        # Fuerza de tendencia: cuanto mas por encima del minimo, mejor, con tope.
        excess = min(1.0, max(0.0, (strength - adx_min) / 20.0))
        score += 0.20 * excess
        parts.append(f"ADX +{0.20 * excess:.2f}")

        # Fuerza de la envolvente.
        if ratio == float("inf") or ratio >= min_ratio * 2:
            score += 0.15; parts.append("envolvente dominante +0.15")
        else:
            gain = 0.15 * min(1.0, max(0.0, (ratio - min_ratio) / min_ratio))
            score += gain; parts.append(f"envolvente +{gain:.2f}")

        # Cuerpo dominante en el rango.
        body_gain = 0.15 * min(1.0, max(0.0, (body_pct - min_body_pct) / (1.0 - min_body_pct))) \
            if body_pct > min_body_pct else 0.0
        score += body_gain; parts.append(f"cuerpo +{body_gain:.2f}")

        # Retroceso poco profundo es mejor senal que uno justo en el limite.
        if pullback is not None:
            shallow = max(0.0, 1.0 - (pullback / pullback_max)) if pullback_max else 0.0
            score += 0.10 * shallow
            parts.append(f"retroceso +{0.10 * shallow:.2f}")

        if rsi_penalty:
            score -= rsi_penalty; parts.append(f"RSI agotado -{rsi_penalty:.2f}")

        return max(0.0, min(1.0, score)), ", ".join(parts)
