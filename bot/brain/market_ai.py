"""
MarketAI — Analizador inteligente de mercado
No usa reglas rígidas. Razona como un trader experto:
- Construye un relato del mercado desde múltiples perspectivas
- Pondera evidencias con probabilidades
- Llega a una conclusión con reasoning explicable
- Se adapta al contexto — no es ciega ante señales contradictorias
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class Evidence:
    """Una pieza de evidencia a favor o en contra de un trade."""
    name: str
    weight: float        # 0–1 importancia relativa
    favor: bool          # True = a favor del trade, False = en contra
    value: float         # 0–1 intensidad de la evidencia
    description: str


@dataclass
class AIVerdict:
    """Veredicto final del análisis de la IA."""
    direction: str            # "CALL", "PUT", "NEUTRAL"
    confidence: float         # 0–1
    score: float              # 0–100
    narrative: str            # Razonamiento en lenguaje natural
    evidence_for: List[str]   # Argumentos a favor
    evidence_against: List[str]  # Argumentos en contra
    setup_label: str          # "EXCELENTE", "BUENO", "MODERADO", "DÉBIL", "SKIP"
    should_trade: bool
    reasoning_chain: List[str]  # Cadena de razonamiento paso a paso


class MarketAI:
    """
    Cerebro analítico del bot.
    Razona sobre el mercado como lo haría un trader experto:
    - No aplica reglas mecánicas
    - Pondera el contexto completo
    - Reconoce cuándo el mercado tiene trampa
    - Explica su razonamiento
    """

    def analyze(self, df_m1: pd.DataFrame, df_m5: pd.DataFrame,
                 df_m15: Optional[pd.DataFrame], df_h1: Optional[pd.DataFrame],
                 zone_level: float, zone_type: str, zone_strength: float,
                 zone_touches: int, zone_hold_rate: float,
                 pattern_name: str, pattern_strength: float,
                 context: Dict) -> AIVerdict:
        """
        Análisis completo tipo experto.
        Reúne toda la evidencia disponible y razona hacia una conclusión.
        """
        reasoning = []
        all_evidence: List[Evidence] = []

        # ── PASO 1: Leer la estructura del mercado ────────────────────────────
        reasoning.append("1. Leyendo estructura del mercado...")
        market_story = self._read_market_story(df_m1, df_m5, df_m15, df_h1, context)
        reasoning.extend(market_story["reasoning"])

        # ── PASO 2: Evaluar la zona ───────────────────────────────────────────
        reasoning.append("2. Evaluando zona de precio...")
        zone_evidence = self._evaluate_zone(
            zone_level, zone_type, zone_strength, zone_touches, zone_hold_rate,
            context, df_m5
        )
        all_evidence.extend(zone_evidence["evidence"])
        reasoning.extend(zone_evidence["reasoning"])

        # ── PASO 3: Analizar el patrón de vela ───────────────────────────────
        reasoning.append("3. Interpretando patrón de vela...")
        pattern_evidence = self._evaluate_pattern(
            pattern_name, pattern_strength, context, df_m1
        )
        all_evidence.extend(pattern_evidence["evidence"])
        reasoning.extend(pattern_evidence["reasoning"])

        # ── PASO 4: Momentum y RSI ────────────────────────────────────────────
        reasoning.append("4. Analizando momentum...")
        momentum_evidence = self._evaluate_momentum(df_m1, df_m5, context)
        all_evidence.extend(momentum_evidence["evidence"])
        reasoning.extend(momentum_evidence["reasoning"])

        # ── PASO 5: Alineación multi-timeframe ───────────────────────────────
        reasoning.append("5. Verificando alineación de timeframes...")
        mtf_evidence = self._evaluate_mtf(context, market_story["direction"])
        all_evidence.extend(mtf_evidence["evidence"])
        reasoning.extend(mtf_evidence["reasoning"])

        # ── PASO 6: Detectar trampas y señales de advertencia ────────────────
        reasoning.append("6. Buscando trampas del mercado...")
        trap_evidence = self._detect_traps(df_m1, df_m5, context, zone_level, zone_type)
        all_evidence.extend(trap_evidence["evidence"])
        reasoning.extend(trap_evidence["reasoning"])

        # ── PASO 7: Calcular veredicto con ponderación bayesiana ─────────────
        reasoning.append("7. Sintetizando evidencias...")
        verdict = self._synthesize(all_evidence, market_story["direction"], context, reasoning)

        # ── PASO 8: Construir narrativa humana ────────────────────────────────
        verdict.narrative = self._build_narrative(verdict, context, zone_type, zone_level, pattern_name)
        verdict.reasoning_chain = reasoning

        return verdict

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 1 — Estructura del mercado
    # ─────────────────────────────────────────────────────────────────────────

    def _read_market_story(self, df_m1, df_m5, df_m15, df_h1, context) -> Dict:
        reasoning = []
        dominant_trend = context.get("dominant_trend", "neutral")
        phase = context.get("market_phase", "ranging")

        if dominant_trend == "uptrend":
            reasoning.append(f"  → Tendencia dominante: ALCISTA. El mercado quiere subir.")
            direction = "CALL"
        elif dominant_trend == "downtrend":
            reasoning.append(f"  → Tendencia dominante: BAJISTA. El mercado quiere bajar.")
            direction = "PUT"
        else:
            reasoning.append(f"  → Tendencia: LATERAL. El mercado está consolidando.")
            direction = "NEUTRAL"

        if phase in ("trending_up", "trending_down"):
            reasoning.append(f"  → Fase: TENDENCIA activa. Las reversiones son de menor calidad aquí.")
        elif phase == "ranging":
            reasoning.append(f"  → Fase: RANGING. Las reversiones en zonas extremas son más confiables.")
        elif phase == "dead":
            reasoning.append(f"  → ADVERTENCIA: Mercado muerto. Poca volatilidad, spreads peligrosos.")

        # Leer los últimos 5 cuerpos de vela M5 para entender el impulso reciente
        if df_m5 is not None and len(df_m5) >= 8:
            recent = df_m5.tail(8)
            bull_count = sum(1 for _, r in recent.iterrows() if float(r["close"]) > float(r["open"]))
            bear_count = 8 - bull_count
            if bull_count >= 6:
                reasoning.append(f"  → Impulso reciente: MUY ALCISTA ({bull_count}/8 velas verdes)")
            elif bear_count >= 6:
                reasoning.append(f"  → Impulso reciente: MUY BAJISTA ({bear_count}/8 velas rojas)")
            else:
                reasoning.append(f"  → Impulso reciente: MIXTO ({bull_count} alcistas / {bear_count} bajistas)")

        return {"direction": direction, "reasoning": reasoning}

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 2 — Evaluación de zona
    # ─────────────────────────────────────────────────────────────────────────

    def _evaluate_zone(self, zone_level, zone_type, zone_strength,
                        zone_touches, zone_hold_rate, context, df_m5) -> Dict:
        evidence = []
        reasoning = []

        # Fuerza de la zona
        zone_ev = Evidence(
            name="zone_strength",
            weight=0.22,
            favor=zone_strength >= 0.55,
            value=zone_strength,
            description=f"Zona {zone_type} nivel {zone_level:.5f} — fuerza {zone_strength:.2f}"
        )
        evidence.append(zone_ev)
        reasoning.append(f"  → Zona {zone_type}: strength={zone_strength:.2f}, {zone_touches} toques, hold_rate={zone_hold_rate:.0%}")

        if zone_strength >= 0.80:
            reasoning.append(f"  → ZONA MUY FUERTE. Históricamente el precio ha rebotado aquí con alta consistencia.")
        elif zone_strength >= 0.60:
            reasoning.append(f"  → Zona sólida. Tiene historial de reacciones válidas.")
        elif zone_strength >= 0.40:
            reasoning.append(f"  → Zona moderada. Puede funcionar si hay buen patrón de confirmación.")
        else:
            reasoning.append(f"  → ADVERTENCIA: Zona débil. Baja probabilidad de reacción significativa.")

        # Hold rate
        hold_ev = Evidence(
            name="zone_hold_rate",
            weight=0.12,
            favor=zone_hold_rate >= 0.60,
            value=zone_hold_rate,
            description=f"Hold rate {zone_hold_rate:.0%}"
        )
        evidence.append(hold_ev)

        # Toques históricos
        touch_ev = Evidence(
            name="zone_touches",
            weight=0.10,
            favor=zone_touches >= 3,
            value=min(zone_touches / 8, 1.0),
            description=f"{zone_touches} toques confirmados"
        )
        evidence.append(touch_ev)
        if zone_touches >= 5:
            reasoning.append(f"  → {zone_touches} toques = zona muy probada y respetada por el mercado.")

        return {"evidence": evidence, "reasoning": reasoning}

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 3 — Evaluación de patrón
    # ─────────────────────────────────────────────────────────────────────────

    def _evaluate_pattern(self, pattern_name, pattern_strength, context, df_m1) -> Dict:
        evidence = []
        reasoning = []

        has_pattern = pattern_name not in ("none", "", None)

        # Puntaje base por tipo de patrón
        pattern_scores = {
            "morning_star":      0.95,
            "evening_star":      0.95,
            "bullish_engulfing": 0.88,
            "bearish_engulfing": 0.88,
            "pin_bar_bullish":   0.85,
            "pin_bar_bearish":   0.85,
            "hammer":            0.80,
            "shooting_star":     0.80,
            "doji_reversal_bull":0.62,
            "doji_reversal_bear":0.62,
        }
        base_score = pattern_scores.get(pattern_name, 0.50) if has_pattern else 0.30

        # En ausencia de patrón claro, mirar si las últimas 2 velas M1 forman estructura
        if not has_pattern and df_m1 is not None and len(df_m1) >= 5:
            micro_structure = self._micro_pattern_analysis(df_m1)
            if micro_structure["found"]:
                reasoning.append(f"  → Sin patrón clásico pero hay micro-estructura: {micro_structure['name']}")
                base_score = 0.55
                has_pattern = True
                pattern_name = micro_structure["name"]

        pattern_ev = Evidence(
            name="candle_pattern",
            weight=0.20,
            favor=has_pattern and base_score >= 0.65,
            value=base_score,
            description=f"Patrón: {pattern_name} (str={pattern_strength:.2f})"
        )
        evidence.append(pattern_ev)

        if has_pattern:
            if base_score >= 0.85:
                reasoning.append(f"  → PATRÓN FUERTE '{pattern_name}' en vela cerrada. Alta fiabilidad de reversión.")
            elif base_score >= 0.70:
                reasoning.append(f"  → Patrón '{pattern_name}' sólido. Buena señal de reversión.")
            else:
                reasoning.append(f"  → Patrón '{pattern_name}' débil. Necesita apoyo de otros factores.")
        else:
            reasoning.append(f"  → Sin patrón de vela definido. Confiamos más en el contexto general.")

        return {"evidence": evidence, "reasoning": reasoning}

    def _micro_pattern_analysis(self, df_m1: pd.DataFrame) -> Dict:
        """Detecta micro-estructuras de 2-3 velas que no son patrones clásicos."""
        if len(df_m1) < 4:
            return {"found": False}

        c_2 = df_m1.iloc[-3]
        c_1 = df_m1.iloc[-2]

        o2, c2 = float(c_2["open"]), float(c_2["close"])
        o1, c1 = float(c_1["open"]), float(c_1["close"])

        # Dos velas consecutivas del mismo color (momentum)
        if c2 > o2 and c1 > o1:
            return {"found": True, "name": "consecutive_bulls", "direction": "CALL"}
        if c2 < o2 and c1 < o1:
            return {"found": True, "name": "consecutive_bears", "direction": "PUT"}

        # Vela de reversión simple (gran cuerpo contrario)
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        if body1 >= body2 * 1.5:
            if c1 > o1 and c2 < o2:
                return {"found": True, "name": "strong_reversal_bull", "direction": "CALL"}
            if c1 < o1 and c2 > o2:
                return {"found": True, "name": "strong_reversal_bear", "direction": "PUT"}

        return {"found": False}

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 4 — Momentum y RSI
    # ─────────────────────────────────────────────────────────────────────────

    def _evaluate_momentum(self, df_m1, df_m5, context) -> Dict:
        evidence = []
        reasoning = []
        momentum = context.get("momentum", {})

        rsi = momentum.get("rsi_m1", 50)
        rsi_dist = abs(rsi - 50)
        macd_hist = momentum.get("macd_hist", 0)
        macd_turning = momentum.get("macd_turning", False)

        # RSI
        rsi_ev = Evidence(
            name="rsi_extreme",
            weight=0.18,
            favor=rsi_dist >= 15,
            value=min(rsi_dist / 40, 1.0),
            description=f"RSI M1 = {rsi:.1f} (distancia del centro: {rsi_dist:.1f})"
        )
        evidence.append(rsi_ev)

        if rsi < 20:
            reasoning.append(f"  → RSI {rsi:.0f}: EXTREMADAMENTE SOBREVENDIDO. Alta probabilidad de rebote.")
        elif rsi < 30:
            reasoning.append(f"  → RSI {rsi:.0f}: Sobrevendido. Condición favorable para CALL.")
        elif rsi > 80:
            reasoning.append(f"  → RSI {rsi:.0f}: EXTREMADAMENTE SOBRECOMPRADO. Alta probabilidad de caída.")
        elif rsi > 70:
            reasoning.append(f"  → RSI {rsi:.0f}: Sobrecomprado. Condición favorable para PUT.")
        elif rsi_dist >= 15:
            reasoning.append(f"  → RSI {rsi:.0f}: Moderadamente alejado del centro. Señal débil.")
        else:
            reasoning.append(f"  → RSI {rsi:.0f}: Neutral. No aporta señal direccional.")

        # MACD
        if macd_turning:
            macd_ev = Evidence(
                name="macd_turning",
                weight=0.10,
                favor=True,
                value=0.80,
                description="MACD girando — momentum cambiando de dirección"
            )
            evidence.append(macd_ev)
            reasoning.append(f"  → MACD girando: confirma cambio de momentum.")
        elif abs(macd_hist) > 1e-5:
            macd_ev = Evidence(
                name="macd_momentum",
                weight=0.07,
                favor=True,
                value=0.55,
                description=f"MACD hist={macd_hist:.6f}"
            )
            evidence.append(macd_ev)

        # Divergencia RSI
        if momentum.get("bullish_divergence"):
            evidence.append(Evidence("rsi_divergence", 0.15, True, 0.88,
                                      "Divergencia alcista RSI — precio bajó pero RSI subió"))
            reasoning.append(f"  → DIVERGENCIA ALCISTA detectada. Señal de reversión de alta calidad.")
        elif momentum.get("bearish_divergence"):
            evidence.append(Evidence("rsi_divergence", 0.15, True, 0.88,
                                      "Divergencia bajista RSI — precio subió pero RSI bajó"))
            reasoning.append(f"  → DIVERGENCIA BAJISTA detectada. Señal de reversión de alta calidad.")

        return {"evidence": evidence, "reasoning": reasoning}

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 5 — Alineación multi-timeframe
    # ─────────────────────────────────────────────────────────────────────────

    def _evaluate_mtf(self, context, story_direction) -> Dict:
        evidence = []
        reasoning = []

        s1  = context.get("structure_m1",  {}).get("trend", "neutral")
        s5  = context.get("structure_m5",  {}).get("trend", "neutral")
        s15 = context.get("structure_m15", {}).get("trend", "neutral")

        trends = [s1, s5, s15]
        up_count   = trends.count("uptrend")
        down_count = trends.count("downtrend")
        neutral_ct = trends.count("neutral")

        if up_count >= 2:
            aligned = story_direction == "CALL"
            reasoning.append(f"  → MTF: {up_count}/3 timeframes en UPTREND. Estructura alcista dominante.")
        elif down_count >= 2:
            aligned = story_direction == "PUT"
            reasoning.append(f"  → MTF: {down_count}/3 timeframes en DOWNTREND. Estructura bajista dominante.")
        else:
            aligned = False
            reasoning.append(f"  → MTF: Timeframes mezclados (M1={s1}, M5={s5}, M15={s15}). Señal débil.")

        mtf_ev = Evidence(
            name="mtf_alignment",
            weight=0.16,
            favor=aligned,
            value=0.85 if aligned else 0.35,
            description=f"M1={s1} M5={s5} M15={s15}"
        )
        evidence.append(mtf_ev)

        # Si la zona va contra la tendencia MTF pero el RSI está en extremo,
        # puede ser una corrección temporal — la IA lo toma en cuenta
        if not aligned:
            reasoning.append(f"  → NOTA: Trade contra la estructura MTF. Requiere patrón muy fuerte para compensar.")

        return {"evidence": evidence, "reasoning": reasoning}

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 6 — Detección de trampas
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_traps(self, df_m1, df_m5, context, zone_level, zone_type) -> Dict:
        evidence = []
        reasoning = []

        # ── Trampa 1: Rotura falsa (fake breakout) ────────────────────────────
        # Si el precio rompió la zona en la vela anterior y ahora volvió,
        # puede ser una trampa bajista/alcista clásica
        if df_m5 is not None and len(df_m5) >= 6:
            recent5 = df_m5.tail(6)
            prices_crossed = 0
            for _, row in recent5.iterrows():
                if zone_type == "resistance":
                    if float(row["high"]) > zone_level * 1.0008:
                        prices_crossed += 1
                else:
                    if float(row["low"]) < zone_level * 0.9992:
                        prices_crossed += 1
            if prices_crossed >= 2:
                evidence.append(Evidence(
                    "fake_breakout_risk", 0.12, False, 0.70,
                    f"Zona cruzada {prices_crossed}x recientemente — posible trampa"
                ))
                reasoning.append(f"  → ALERTA: La zona fue cruzada {prices_crossed} veces recientemente. Riesgo de falsa ruptura.")

        # ── Trampa 2: Mercado en noticias / spike ─────────────────────────────
        if df_m1 is not None and len(df_m1) >= 5:
            ranges = [float(r["high"]) - float(r["low"])
                      for _, r in df_m1.tail(5).iterrows()]
            avg_range = np.mean(ranges[:-1])  # promedio sin la última
            last_range = ranges[-1]
            if last_range > avg_range * 2.5:
                evidence.append(Evidence(
                    "spike_detected", 0.10, False, 0.80,
                    f"Vela spike detectada ({last_range:.5f} vs avg {avg_range:.5f})"
                ))
                reasoning.append(f"  → ALERTA: Vela spike detectada (rango {last_range/avg_range:.1f}x normal). Posibles noticias.")

        # ── Trampa 3: Mercado muerto (spread peligroso) ───────────────────────
        if context.get("market_phase") == "dead":
            evidence.append(Evidence(
                "dead_market", 0.14, False, 0.90,
                "Mercado sin volatilidad — spreads peligrosos"
            ))
            reasoning.append(f"  → MERCADO MUERTO: operar aquí aumenta el riesgo por spreads y falta de momentum.")
        else:
            reasoning.append(f"  → Sin trampas evidentes detectadas.")

        return {"evidence": evidence, "reasoning": reasoning}

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 7 — Síntesis bayesiana
    # ─────────────────────────────────────────────────────────────────────────

    def _synthesize(self, evidence: List[Evidence], story_direction: str,
                     context: Dict, reasoning: List[str]) -> AIVerdict:
        """
        Combina todas las evidencias usando ponderación bayesiana.
        La clave: una sola evidencia muy fuerte en contra puede bloquear el trade,
        pero múltiples evidencias débiles a favor pueden compensar.
        """
        if not evidence:
            return AIVerdict("NEUTRAL", 0.3, 30, "", [], [], "DÉBIL", False, reasoning)

        # Separar evidencias a favor y en contra
        ev_for     = [e for e in evidence if e.favor]
        ev_against = [e for e in evidence if not e.favor]

        # Score ponderado
        total_weight = sum(e.weight for e in evidence)
        score_for    = sum(e.weight * e.value for e in ev_for)
        score_against = sum(e.weight * e.value for e in ev_against)

        # Ratio favor/contra (0-1)
        net_score = (score_for - score_against * 0.8) / (total_weight + 1e-8)
        net_score = max(0.0, min(1.0, net_score))

        # Confianza ajustada por número de evidencias convergentes
        convergence_bonus = min(len(ev_for) / 8, 0.15)
        confidence = min(0.94, net_score * 0.75 + convergence_bonus + 0.10)

        # Si hay advertencia crítica de trampa, reducir confianza
        critical_against = [e for e in ev_against if e.value >= 0.80 and e.weight >= 0.10]
        if critical_against:
            confidence *= 0.75
            net_score  *= 0.80

        # Score 0-100
        score_100 = round(net_score * 100, 1)

        # Dirección
        direction = story_direction if story_direction != "NEUTRAL" else (
            context.get("expected_direction", "NEUTRAL")
        )

        # Threshold dinámico para operar (suavizado)
        trade_threshold = 0.20 if len(ev_for) >= 2 else 0.28

        should_trade = net_score >= trade_threshold and direction != "NEUTRAL"

        # Label de setup (umbrales suavizados)
        if score_100 >= 50:
            label = "EXCELENTE"
        elif score_100 >= 35:
            label = "BUENO"
        elif score_100 >= 20:
            label = "MODERADO"
        elif score_100 >= 10:
            label = "DEBIL"
        else:
            label = "SKIP"

        if label == "SKIP":
            should_trade = False
        # DEBIL no bloquea automaticamente
        if label == "DEBIL" and net_score >= 0.15 and direction != "NEUTRAL":
            should_trade = True

        evidence_for_text  = [e.description for e in ev_for]
        evidence_against_text = [e.description for e in ev_against]

        return AIVerdict(
            direction=direction,
            confidence=round(confidence, 3),
            score=score_100,
            narrative="",
            evidence_for=evidence_for_text,
            evidence_against=evidence_against_text,
            setup_label=label,
            should_trade=should_trade,
            reasoning_chain=reasoning,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # PASO 8 — Narrativa humana
    # ─────────────────────────────────────────────────────────────────────────

    def _build_narrative(self, verdict: AIVerdict, context: Dict,
                          zone_type: str, zone_level: float,
                          pattern_name: str) -> str:
        """Construye un resumen en lenguaje natural del análisis."""
        dominant = context.get("dominant_trend", "neutral")
        phase    = context.get("market_phase", "ranging")
        rsi      = context.get("momentum", {}).get("rsi_m1", 50)
        dir_word = "CALL (sube)" if verdict.direction == "CALL" else "PUT (baja)" if verdict.direction == "PUT" else "NEUTRAL"

        # Descripción de la zona
        zone_desc = f"zona de {'soporte' if zone_type == 'support' else 'resistencia'} {zone_level:.5f}"

        # Construcción de narrativa
        parts = []

        # Contexto de tendencia
        if dominant == "uptrend":
            parts.append(f"El mercado está en tendencia alcista dominante")
        elif dominant == "downtrend":
            parts.append(f"El mercado está en tendencia bajista dominante")
        else:
            parts.append(f"El mercado está en consolidación lateral")

        # Zona
        parts.append(f"el precio llegó a la {zone_desc}")

        # Patrón
        pattern_desc = {
            "pin_bar_bullish":   "formando un pin bar alcista (rechazo claro)",
            "pin_bar_bearish":   "formando un pin bar bajista (rechazo claro)",
            "bullish_engulfing": "con una vela engulfing alcista",
            "bearish_engulfing": "con una vela engulfing bajista",
            "morning_star":      "con patrón morning star (3 velas de reversión)",
            "evening_star":      "con patrón evening star (3 velas de reversión)",
            "hammer":            "formando un hammer (rechazo del soporte)",
            "shooting_star":     "formando un shooting star (rechazo de resistencia)",
        }.get(pattern_name, f"con señal de reversión")

        if pattern_name and pattern_name != "none":
            parts.append(pattern_desc)

        # RSI
        if rsi < 25:
            parts.append(f"RSI en sobreventa extrema ({rsi:.0f})")
        elif rsi < 35:
            parts.append(f"RSI sobrevendido ({rsi:.0f})")
        elif rsi > 75:
            parts.append(f"RSI en sobrecompra extrema ({rsi:.0f})")
        elif rsi > 65:
            parts.append(f"RSI sobrecomprado ({rsi:.0f})")

        # Conclusión
        conclusion = f"→ La IA recomienda {dir_word} con confianza {verdict.confidence*100:.0f}% [{verdict.setup_label}]"

        return ". ".join(parts) + ". " + conclusion
