"""
IntelligentEngine v5.0 – Motor de zonas válidas + alineación M15/M30
====================================================================

Principios:
- Solo opera con SOPORTES Y RESISTENCIAS VÁLIDOS (zone_strength >= 0.55, no fallback)
- Confirmación de 3 fases REAL (bypass solo si AI >= 70)
- Alineación de dirección: M15 + M30 definen la tendencia
- Patrón de vela + zona + AI deben estar alineados
- Sin zonas artificiales: si no hay zonas reales, WAIT
- Momento perfecto: entrada solo cuando todo está alineado
"""

import time
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple

from brain.zone_detector import ZoneDetector
from brain.context_analyzer import ContextAnalyzer
from brain.market_ai import MarketAI
from brain.market_trap_detector import MarketTrapDetector
from brain.three_phase_confirmation import ThreePhaseConfirmation
from brain.trade_context_analyzer import TradeContextAnalyzer
from brain.trade_rejection_rules import TradeRejectionRules


class IntelligentEngine:
    def __init__(self, session_name: str):
        self.session_name = session_name
        self.zone_detector = ZoneDetector()
        self.market_ai = MarketAI()
        self.trap_detector = MarketTrapDetector()
        self.phase_analyzer = ThreePhaseConfirmation()
        self.rejection_rules = TradeRejectionRules()
        self.context_analyzer = ContextAnalyzer()

        # Umbrales optimizados (basados en análisis de 265 trades históricos)
        # Análisis: pin_bar_bullish WR 68.2%, engulfing_bearish WR 20%, trend_aligned WR 55.3% vs 23.1%
        self.MIN_ZONE_STRENGTH = 0.55  # AUMENTADO: Solo zonas fuertes (0.96+)
        self.MIN_AI_SCORE_PHASE_BYPASS = 65  # AUMENTADO: IA muy buena para bypass
        self.MIN_AI_SCORE_TRADE = 45  # AUMENTADO: Score mínimo 45 (antes 35)
        self.MIN_TREND_ALIGNED_CONFIDENCE = 0.50  # AUMENTADO: Mínimo confianza si trend_aligned=False


    # ---------------------------------------------------------------------
    @staticmethod
    def calculate_rsi(closes: np.ndarray, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        delta = np.diff(closes)
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)
        avg_gain = np.mean(gain[:period])
        avg_loss = np.mean(loss[:period])
        if avg_loss < 1e-10:
            return 100.0
        for i in range(period, len(delta)):
            avg_gain = (avg_gain * (period - 1) + gain[i]) / period
            avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    # ─────────────────────────────────────────────────────────────────────────────
    def _validate_rsi_extreme(self, rsi: float, zone_dir: str) -> Optional[str]:
        """
        Valida que RSI no esté extremo (sobrecomprado/overbought o sobrevenido/oversold).
        
        Si RSI > 70: mercado sobrecomprado → evitar CALL (compra)
        Si RSI < 30: mercado sobrevenido → evitar PUT (venta)
        
        Returns: reason string or None if OK
        """
        overbought = 70
        oversold = 30
        
        if zone_dir == "CALL" and rsi > overbought:
            return f"RSI extremo: {rsi:.0f} (sobrecomprado > {overbought}) - evitar CALL"
        
        if zone_dir == "PUT" and rsi < oversold:
            return f"RSI extremo: {rsi:.0f} (sobrevenido < {oversold}) - evitar PUT"
        
        return None

    # ─────────────────────────────────────────────────────────────────────────────
    def _validate_no_opposite_zone_nearby(self, price: float, all_zones: list, 
                                          zone_dir: str, asset: str = "") -> tuple:
        """
        Valida que NO haya una zona opuesta muy cerca.
        
        Ej: Si vamos a hacer CALL (compra en soporte), verificar que NO hay resistencia muy cerca arriba.
        Si vamos a hacer PUT (venta en resistencia), verificar que NO hay soporte muy cerca abajo.
        
        Returns: (is_valid, reason)
        """
        if not all_zones:
            return True, None
        
        # Distancia máxima aceptable en pips (relativa al precio)
        max_distance_pct = 0.008  # 0.8% = ~8 pips en pares normales
        
        for zone in all_zones:
            zone_type = zone.get("zone_type", "support")
            zone_level = zone.get("level", 0)
            
            # Si es CALL, buscamos resistencias arriba
            if zone_dir == "CALL" and zone_type == "resistance":
                dist_pct = (zone_level - price) / price if price > 0 else 1.0
                if 0 < dist_pct < max_distance_pct:
                    return False, f"Resistencia muy cerca: {zone_level:.5f} (dist={dist_pct*100:.2f}%)"
            
            # Si es PUT, buscamos soportes abajo
            elif zone_dir == "PUT" and zone_type == "support":
                dist_pct = (price - zone_level) / price if price > 0 else 1.0
                if 0 < dist_pct < max_distance_pct:
                    return False, f"Soporte muy cerca: {zone_level:.5f} (dist={dist_pct*100:.2f}%)"
        
        return True, None

    # ─────────────────────────────────────────────────────────────────────────────
    def detect_candle_patterns(self, df: pd.DataFrame) -> Tuple[int, str, str]:
        if len(df) < 4:
            return 50, "NEUTRAL", "none"

        c0 = df.iloc[-1]
        c1 = df.iloc[-2]
        c2 = df.iloc[-3]

        o0, h0, l0, cl0 = float(c0["open"]), float(c0["high"]), float(c0["low"]), float(c0["close"])
        o1, h1, l1, cl1 = float(c1["open"]), float(c1["high"]), float(c1["low"]), float(c1["close"])
        o2, h2, l2, cl2 = float(c2["open"]), float(c2["high"]), float(c2["low"]), float(c2["close"])

        body0  = abs(cl0 - o0)
        body1  = abs(cl1 - o1)
        range0 = h0 - l0

        lower_wick0 = min(o0, cl0) - l0
        upper_wick0 = h0 - max(o0, cl0)

        is_bull0 = cl0 > o0
        is_bear0 = cl0 < o0
        is_bear1 = cl1 < o1

        if (is_bull0 and lower_wick0 > 2 * body0 and upper_wick0 < body0 * 0.5 and range0 > 0):
            return 88, "CALL", "hammer"
        if (is_bear0 and upper_wick0 > 2 * body0 and lower_wick0 < body0 * 0.5 and range0 > 0):
            return 88, "PUT", "shooting_star"
        if (lower_wick0 > 2.5 * body0 and lower_wick0 > upper_wick0 * 2 and range0 > 0):
            return 85, "CALL", "pin_bar_bullish"
        if (upper_wick0 > 2.5 * body0 and upper_wick0 > lower_wick0 * 2 and range0 > 0):
            return 85, "PUT", "pin_bar_bearish"
        if (is_bull0 and is_bear1 and o0 <= cl1 and cl0 >= o1 and body0 > body1 * 1.0):
            return 90, "CALL", "engulfing_bullish"
        if (is_bear0 and not is_bear1 and o0 >= cl1 and cl0 <= o1 and body0 > body1 * 1.0):
            return 90, "PUT", "engulfing_bearish"
        if range0 > 0 and body0 / range0 < 0.1:
            return 40, "NEUTRAL", "doji"

        return 50, "NEUTRAL", "none"

    # ---------------------------------------------------------------------
    def _get_trend_from_tf(self, df: pd.DataFrame) -> Tuple[str, float]:
        """Determina tendencia de un timeframe usando EMAs.
        Returns (direction, strength) donde direction es CALL/ PUT/ NEUTRAL"""
        if df is None or len(df) < 20:
            return "NEUTRAL", 0.0
        closes = df["close"].values
        ema8 = pd.Series(closes).ewm(span=8).mean().iloc[-1]
        ema21 = pd.Series(closes).ewm(span=21).mean().iloc[-1]
        price = closes[-1]

        if price > ema8 > ema21:
            return "CALL", 0.8
        elif price < ema8 < ema21:
            return "PUT", 0.8
        elif price > ema21:
            return "CALL", 0.4
        elif price < ema21:
            return "PUT", 0.4
        return "NEUTRAL", 0.0

    # ---------------------------------------------------------------------
    def evaluate_market(self, asset: str, df_m1: pd.DataFrame, df_m5: pd.DataFrame,
                         df_m15: pd.DataFrame, df_m30: pd.DataFrame = None,
                         df_h1: pd.DataFrame = None) -> Dict:
        price = float(df_m1["close"].iloc[-1])
        current_rsi = self.calculate_rsi(df_m1["close"].values)

        # =====================================================================
        # 1. ZONAS VÁLIDAS - Solo S/R reales, nada artificial
        # =====================================================================
        try:
            h1_input = df_m30 if df_m30 is not None else df_h1
            zones = self.zone_detector.detect_multi_tf(df_m5, df_m15, h1_input)
        except:
            zones = None

        if not zones:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": "Sin zonas válidas de S/R en M5/M15/M30",
                "confidence": 0,
                "score": 0,
                "pattern": "none",
                "ai_label": "SKIP",
                "zone_strength": 0,
                "rsi": current_rsi,
            }

        nearest_zone = zones[0] if isinstance(zones, list) else zones
        zone_strength = nearest_zone.get("strength", 0)
        zone_touches = nearest_zone.get("touches", 0)

        # Rechazar zonas débiles
        if zone_strength < self.MIN_ZONE_STRENGTH:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"Zona débil: strength={zone_strength:.2f} < {self.MIN_ZONE_STRENGTH}",
                "confidence": 0,
                "score": 0,
                "pattern": "none",
                "ai_label": "SKIP",
                "zone_strength": zone_strength,
                "rsi": current_rsi,
            }

        h1_data = df_m30 if df_m30 is not None else df_h1

        # =====================================================================
        # 2. ALINEACIÓN M15 + M30 - Tendencia principal
        # =====================================================================
        trend_m15, str_m15 = self._get_trend_from_tf(df_m15)
        trend_htf, str_htf = self._get_trend_from_tf(h1_data) if h1_data is not None else ("NEUTRAL", 0)

        # Dirección esperada de la zona
        zone_dir = "CALL" if nearest_zone.get("zone_type") == "support" else "PUT"

        # La tendencia principal viene del TF mayor disponible (M30 > M15)
        if str_htf >= 0.4:
            main_trend = trend_htf
            main_trend_str = str_htf
        elif str_m15 >= 0.4:
            main_trend = trend_m15
            main_trend_str = str_m15
        else:
            main_trend = "NEUTRAL"
            main_trend_str = 0

        # Verificar que la zona esté alineada con la tendencia principal
        # SUAVIZADO: ya no bloquea, solo reduce confianza

        expected_dir = zone_dir

        # =====================================================================
        # 3. PATRÓN DE VELA REAL
        # =====================================================================
        pat_score, pat_dir, pattern_name = self.detect_candle_patterns(df_m1)
        if pattern_name == "none":
            pat_score = 0
        pattern_conf = pat_score / 100.0

        # Si el patrón indica dirección contraria a la zona, dudar
        # SUAVIZADO: ya no bloquea, solo reduce confianza

        # =====================================================================
        # 4. CONTEXTO + IA
        # =====================================================================
        context = self.context_analyzer.analyze(
            df_m1, df_m5, df_m15, h1_data,
            zone=nearest_zone, current_price=price
        )

        ai_verdict = self.market_ai.analyze(
            df_m1=df_m1, df_m5=df_m5, df_m15=df_m15, df_h1=h1_data,
            zone_level=nearest_zone.get("level", 1.1),
            zone_type=nearest_zone.get("zone_type", "support"),
            zone_strength=zone_strength,
            zone_touches=zone_touches,
            zone_hold_rate=nearest_zone.get("hold_rate", 0.5),
            pattern_name=pattern_name,
            pattern_strength=pattern_conf,
            context=context,
        )
        ai_score, ai_conf, ai_dir, ai_label, ai_narrative, ai_should = (
            ai_verdict.score, ai_verdict.confidence,
            ai_verdict.direction, ai_verdict.setup_label,
            ai_verdict.narrative, ai_verdict.should_trade
        )

        if ai_label in {"SKIP", "WAIT"}:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"IA bloquea: {ai_label} - {ai_narrative[:60]}",
                "confidence": ai_conf,
                "score": ai_score,
                "pattern": pattern_name,
                "ai_label": ai_label,
                "zone_strength": zone_strength,
                "rsi": current_rsi,
            }

        # AI dirección debe coincidir con zona
        if ai_dir != expected_dir:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"IA sugiere {ai_dir} pero zona dice {expected_dir}",
                "confidence": ai_conf,
                "score": ai_score,
                "pattern": pattern_name,
                "ai_label": ai_label,
                "zone_strength": zone_strength,
                "rsi": current_rsi,
            }

        # Score mínimo de IA (suavizado)
        if ai_score < self.MIN_AI_SCORE_TRADE:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"IA score bajo: {ai_score:.0f} < {self.MIN_AI_SCORE_TRADE}. Esperar mejor setup.",
                "confidence": ai_conf,
                "score": ai_score,
                "pattern": pattern_name,
                "ai_label": ai_label,
                "zone_strength": zone_strength,
                "rsi": current_rsi,
            }

        # =====================================================================
        # 4.5 VALIDACIÓN DE PATRONES PELIGROSOS (basado en análisis histórico)
        # =====================================================================
        # Análisis de 265 trades:
        # - engulfing_bearish: 20% WR, -$83.85 PnL (PEOR)
        # - hammer: 42.9% WR, -$13.62 PnL
        # - doji: 0% WR, -$10.05 PnL
        # - pin_bar_bullish: 68.2% WR, +$64.00 PnL (MEJOR - FAVORECER)
        # - pin_bar_bearish: 56.1% WR, +$6.55 PnL (MANTENER)
        bad_patterns = {"engulfing_bearish", "doji", "hammer"}
        if pattern_name in bad_patterns:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"Patrón peligroso: {pattern_name} tiene WR<50% históricamente",
                "confidence": 0,
                "score": 0,
                "pattern": pattern_name,
                "ai_label": "SKIP",
                "zone_strength": zone_strength,
                "rsi": current_rsi,
            }

        # =====================================================================
        # 4.6 VALIDACIÓN DE ALINEACIÓN DE TENDENCIA (CRÍTICO)
        # =====================================================================
        # Análisis de 265 trades:
        # - Trend Aligned: 55.3% WR (141W / 114L)
        # - Trend NOT Aligned: 23.1% WR (3W / 10L)
        # - Diferencia: 32.2 puntos porcentuales
        trend_aligned = (main_trend != "NEUTRAL" and zone_dir == main_trend)
        if not trend_aligned:
            # Contra-tendencia detectada - RECHAZAR si IA score no es excelente
            if ai_score < 70:
                return {
                    "asset": asset,
                    "action": "WAIT",
                    "reason": f"Contra-tendencia: zona={zone_dir}, tendencia={main_trend}, AI={ai_score:.0f}<70. WR histórico: 23.1%",
                    "confidence": 0,
                    "score": ai_score,
                    "pattern": pattern_name,
                    "ai_label": "SKIP",
                    "zone_strength": zone_strength,
                    "rsi": current_rsi,
                }

        # =====================================================================
        # 5. REGLAS DE RECHAZO
        # =====================================================================
        trade_proposal = {
            "direction": expected_dir,
            "expiration_seconds": 180,
            "pattern": pattern_name,
            "zone_strength": zone_strength,
            "zone_hold_rate": nearest_zone.get("hold_rate", 0.5),
            "zone_touches": zone_touches,
        }
        zone_info = {
            "strength": zone_strength,
            "hold_rate": nearest_zone.get("hold_rate", 0.5),
            "touches": zone_touches,
            "distance": nearest_zone.get("distance", 0.0),
        }
        market_context = {
            "macro_trend": main_trend,
            "h1_trend": trend_htf,
            "m5_trend": trend_m15,
            "consolidation_level": context.get("consolidation_level"),
            "divergence_detected": context.get("divergence_detected", False),
        }
        technical_data = {
            "rsi_m1": current_rsi,
            "rsi_m5": self.calculate_rsi(df_m5["close"].values) if len(df_m5) >= 14 else 50,
        }
        should_reject, reject_reason = self.rejection_rules.evaluate(
            trade_proposal, market_context, zone_info, technical_data
        )
        if should_reject:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"RECHAZO: {reject_reason}",
                "confidence": ai_conf,
                "score": ai_score,
                "pattern": pattern_name,
                "ai_label": ai_label,
                "zone_strength": zone_strength,
                "rsi": current_rsi,
            }

        # =====================================================================
        # 6. CONFIRMACIÓN 3 FASES (SUAVIZADO - solo informativo, no bloquea)
        # =====================================================================
        phase = self.phase_analyzer.analyze_current_phase(
            df_m1, nearest_zone.get("level", 1.1), nearest_zone.get("zone_type", "support"),
            expected_dir
        )

        # Si AI score es bueno, no bloquear por fase
        if ai_score >= 40:
            phase["ready"] = True
            phase["message"] = f"Bypass 3-fase por IA score bueno ({ai_score:.0f})"
        elif not phase.get("ready", False) and ai_score >= 30:
            # Si IA es moderada, permitir pero con advertencia
            phase["ready"] = True
            phase["message"] = f"Permitido con IA moderada ({ai_score:.0f})"

        # =====================================================================
        # 7. TRAMPAS
        # =====================================================================
        trap = self.trap_detector.analyze_all_traps(
            df_m1, nearest_zone.get("level", 1.1), nearest_zone.get("zone_type", "support"),
            expected_dir, rsi=current_rsi
        )
        if trap.get("risk_score", 0) >= 0.98:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"TRAMPA: {trap.get('recommendation','')}",
                "confidence": ai_conf,
                "score": ai_score,
                "pattern": pattern_name,
                "ai_label": ai_label,
                "zone_strength": zone_strength,
                "rsi": current_rsi,
            }

        # =====================================================================
        # 8. VALIDACIONES ADICIONALES - Evitar operaciones malas
        # =====================================================================
        
        # 8.1 - VALIDAR RSI EXTREMO (pero no bloquear, solo advertir)
        rsi_validation = self._validate_rsi_extreme(current_rsi, expected_dir)
        rsi_penalty = 0.0
        if rsi_validation:
            # No bloquear, solo reducir confianza
            rsi_penalty = 0.15  # Reducir confianza 15% si RSI está extremo
        
        # 8.2 - NO OPERAR CERCA DE RESISTENCIAS/SOPORTES
        # Si estamos muy cerca de la zona, esperar a que se aleje
        zone_level = nearest_zone.get("level", price)
        distance_to_zone = abs(price - zone_level)
        zone_range = nearest_zone.get("range", 0.01)  # Rango de la zona
        
        # Si estamos dentro del 30% del rango de la zona, es muy arriesgado
        if distance_to_zone < zone_range * 0.3:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"Precio muy cerca de zona ({distance_to_zone:.5f} < {zone_range*0.3:.5f}). Esperar movimiento.",
                "confidence": ai_conf,
                "score": ai_score,
                "pattern": pattern_name,
                "ai_label": ai_label,
                "zone_strength": zone_strength,
                "rsi": current_rsi,
            }
        
        # 8.3 - VALIDAR DIRECCIÓN vs ZONA (SUAVIZADO - solo advertencia)
        zone_type = nearest_zone.get("zone_type", "support")
        
        # Si hay conflicto, usar IA como fuente de verdad
        if expected_dir == "CALL" and zone_type == "resistance":
            # Conflicto: CALL en resistencia - cambiar a PUT
            expected_dir = "PUT"
        elif expected_dir == "PUT" and zone_type == "support":
            # Conflicto: PUT en soporte - cambiar a CALL
            expected_dir = "CALL"
        
        # 8.4 - VERIFICAR QUE ESTAMOS EN INICIO DE MOVIMIENTO (SUAVIZADO - solo informativo)
        # Ya no bloquea, solo informa
        if phase.get("phase_name") not in ["ENTRY", "EARLY_MOVE", "CONFIRMATION"]:
            # No bloquear, solo reducir confianza ligeramente
            confidence_phase_penalty = 0.05
        else:
            confidence_phase_penalty = 0.0

        # =====================================================================
        # 9. VALIDACIÓN FINAL - Rechazar si dirección es NEUTRAL
        # =====================================================================
        if expected_dir == "NEUTRAL":
            # Si IA sugiere NEUTRAL, usar la zona como dirección
            if ai_dir == "NEUTRAL":
                expected_dir = zone_dir  # Usar dirección de la zona
            else:
                expected_dir = ai_dir  # Usar dirección de IA
        
        # Si aún es NEUTRAL, rechazar
        if expected_dir == "NEUTRAL":
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"Dirección NEUTRAL no válida. Rechazado.",
                "confidence": ai_conf,
                "score": ai_score,
                "pattern": pattern_name,
                "ai_label": ai_label,
                "zone_strength": zone_strength,
                "rsi": current_rsi,
            }

        # =====================================================================
        # 11. TRADE - TODO ALINEADO
        # =====================================================================
        final_score = max(ai_score, pat_score)
        confidence = min(0.90, final_score / 100)
        
        # FAVORECER patrones ganadores (basado en análisis de 265 trades)
        # pin_bar_bullish: 68.2% WR → +10% confianza
        # shooting_star: 60% WR → +8% confianza
        # pin_bar_bearish: 56.1% WR → +5% confianza
        if pattern_name == "pin_bar_bullish":
            confidence = min(0.95, confidence + 0.10)
            final_score = min(100, final_score + 10)
        elif pattern_name == "shooting_star":
            confidence = min(0.95, confidence + 0.08)
            final_score = min(100, final_score + 8)
        elif pattern_name == "pin_bar_bearish":
            confidence = min(0.95, confidence + 0.05)
            final_score = min(100, final_score + 5)
        
        # Aplicar penalidades
        if rsi_penalty > 0:
            confidence = max(0.30, confidence - rsi_penalty)
        if confidence_phase_penalty > 0:
            confidence = max(0.30, confidence - confidence_phase_penalty)

        # Verificar si la tendencia está alineada (zona + tendencia principal)
        trend_aligned = (main_trend != "NEUTRAL" and zone_dir == main_trend)

        r = {
            "asset": asset,
            "action": "TRADE",
            "signal": expected_dir,
            "score": final_score,
            "confidence": confidence,
            "pattern": pattern_name,
            "ai_label": ai_label,
            "zone_strength": zone_strength,
            "rsi": current_rsi,
            "exp_sec": 180,
            "phase": phase,
            "reason": ai_narrative,
            "trend_m15": trend_m15,
            "trend_htf": trend_htf,
            "trend_aligned": trend_aligned,
        }
        return r

    # ---------------------------------------------------------------------
    def start_loop(self, assets: list):
        while True:
            for asset in assets:
                df_m1 = pd.DataFrame()
                df_m5 = pd.DataFrame()
                df_m15 = pd.DataFrame()
                df_m30 = pd.DataFrame()
                decision = self.evaluate_market(asset, df_m1, df_m5, df_m15, df_m30)
                if decision["action"] == "TRADE":
                    print(f"[TRADE] {decision}")
                else:
                    print(f"[WAIT] {decision['reason']}")
            time.sleep(60)
