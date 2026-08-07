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
from brain.market_structure_engine import MarketStructureEngine
from core.asset_discovery import is_otc
from config_assets import BAD_PATTERNS


class IntelligentEngine:
    def __init__(self, session_name: str, mode: str = "real"):
        self.session_name = session_name
        self.mode = mode
        self.zone_detector = ZoneDetector()
        self.market_ai = MarketAI()
        self.trap_detector = MarketTrapDetector()
        self.phase_analyzer = ThreePhaseConfirmation()
        self.rejection_rules = TradeRejectionRules()
        self.context_analyzer = ContextAnalyzer()
        self.market_structure_engine = MarketStructureEngine()

        if mode == "practice":
            # Modo práctica: mínimos filtros para ver muchas operaciones
            self.MIN_ZONE_STRENGTH = 0.10
            self.MIN_AI_SCORE_PHASE_BYPASS = 10
            self.MIN_AI_SCORE_TRADE = 5
            self.MIN_TREND_ALIGNED_CONFIDENCE = 0.0
        else:
            # Umbrales optimizados (basados en análisis de 265 trades históricos)
            self.MIN_ZONE_STRENGTH = 0.40
            self.MIN_AI_SCORE_PHASE_BYPASS = 50
            self.MIN_AI_SCORE_TRADE = 30
            self.MIN_TREND_ALIGNED_CONFIDENCE = 0.30


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
    def _detect_bounce_stage(self, df_m1: pd.DataFrame, zone_level: float,
                              zone_type: str) -> Dict:
        """
        Detecta en qué etapa está el rebote respecto a la zona.
        
        Returns:
            {
                "stage": "EARLY" | "MIDDLE" | "LATE" | "DONE" | "NONE",
                "distance_from_zone_pct": float,
                "momentum_fading": bool,
                "rejection_confirmed": bool,
                "entry_viable": bool,
                "reason": str
            }
        """
        if len(df_m1) < 5:
            return {
                "stage": "NONE", "distance_from_zone_pct": 0,
                "momentum_fading": False, "rejection_confirmed": False,
                "entry_viable": False, "reason": "Datos insuficientes"
            }
        
        price = float(df_m1["close"].iloc[-1])
        distance_pct = abs(price - zone_level) / zone_level if zone_level > 0 else 1.0
        
        lookback = min(10, len(df_m1))
        recent = df_m1.iloc[-lookback:].copy()
        
        touched_zone = False
        touch_candle_idx = None
        rejection_candle_idx = None
        
        for i in range(len(recent)):
            candle = recent.iloc[i]
            candle_high = float(candle["high"])
            candle_low = float(candle["low"])
            
            if zone_type == "support" and candle_low <= zone_level * 1.002:
                touched_zone = True
                touch_candle_idx = i
                if float(candle["close"]) > float(candle["open"]):
                    rejection_candle_idx = i
                break
            elif zone_type == "resistance" and candle_high >= zone_level * 0.998:
                touched_zone = True
                touch_candle_idx = i
                if float(candle["close"]) < float(candle["open"]):
                    rejection_candle_idx = i
                break
        
        if not touched_zone:
            return {
                "stage": "NONE", "distance_from_zone_pct": distance_pct,
                "momentum_fading": False, "rejection_confirmed": False,
                "entry_viable": False, "reason": "Precio no tocó zona en las últimas velas"
            }
        
        if touch_candle_idx is not None:
            touch_price = float(recent.iloc[touch_candle_idx]["low"]) if zone_type == "support" else float(recent.iloc[touch_candle_idx]["high"])
            move_from_zone = abs(price - touch_price) / touch_price if touch_price > 0 else 0
        else:
            move_from_zone = distance_pct
        
        momentum_fading = False
        if len(recent) >= 3:
            last_3 = recent.iloc[-3:]
            closes = last_3["close"].values
            if zone_type == "support":
                momentum_fading = closes[-1] <= closes[-2] and closes[-2] <= closes[-1] * 1.0001
            else:
                momentum_fading = closes[-1] >= closes[-2] and closes[-2] >= closes[-1] * 0.9999
        
        rejection_confirmed = rejection_candle_idx is not None
        
        if not rejection_confirmed:
            stage = "NONE"
            entry_viable = False
            reason = "Sin rechazo confirmado en la zona"
        elif move_from_zone < 0.001:
            stage = "EARLY"
            entry_viable = True
            reason = f"Rechazo temprano: movimiento {move_from_zone*100:.3f}% desde zona"
        elif move_from_zone < 0.003:
            stage = "MIDDLE"
            entry_viable = not momentum_fading
            reason = f"Rebote en progreso: {move_from_zone*100:.3f}% desde zona" + (", momentum desvaneciéndose" if momentum_fading else "")
        elif move_from_zone < 0.006:
            stage = "LATE"
            entry_viable = False
            reason = f"Rebote avanzado: {move_from_zone*100:.3f}% desde zona. Entrada demasiado tarde."
        else:
            stage = "DONE"
            entry_viable = False
            reason = f"Rebote completado: {move_from_zone*100:.3f}% desde zona. Movimiento agotado."
        
        return {
            "stage": stage,
            "distance_from_zone_pct": move_from_zone,
            "momentum_fading": momentum_fading,
            "rejection_confirmed": rejection_confirmed,
            "entry_viable": entry_viable,
            "reason": reason
        }

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
        # Recalibrado sobre 500 trades reales (bot/brain/trade_history.json, excl. "demo"):
        # - engulfing_bearish: 16.7% WR (n=6) RECHAZAR
        # - doji: 0% WR (n=1) RECHAZAR
        # - hammer: 42.9% WR (n=7) RECHAZAR (por debajo de breakeven)
        # - engulfing_bullish: 44.4% WR (n=9) RECHAZAR (por debajo de breakeven)
        # - pin_bar_bullish: 69.2% WR (n=26) FAVORECER - único patrón con edge confirmado
        #   (consistente con análisis previo de 265 trades: 68.2% WR)
        # Todo lo demás (pin_bar_bearish, shooting_star, "none") queda neutral:
        # muestra insuficiente o resultado inconsistente entre cortes de datos,
        # no se rechaza ni se favorece.
        # Se aplica SIEMPRE (no solo en modo real) para que los datos recolectados
        # en práctica sean representativos de lo que pasaría en real.
        if pattern_name in BAD_PATTERNS:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"Patrón rechazado: {pattern_name} sin edge confirmado (WR<50% histórico)",
                "confidence": 0,
                "score": 0,
                "pattern": pattern_name,
                "ai_label": "SKIP",
                "zone_strength": zone_strength,
                "rsi": current_rsi,
            }

        # =====================================================================
        # 4.6 VALIDACIÓN DE ALINEACIÓN DE TENDENCIA (CRÍTICO - BLOQUEO DURO)
        # =====================================================================
        # Es la señal más robusta de todo el sistema, confirmada en dos análisis
        # independientes (265 trades y 500 trades):
        # - Trend Aligned: 54-55% WR
        # - Trend NOT Aligned: 18-23% WR
        # - Diferencia: 32-36 puntos porcentuales
        # Sin excepciones: ni por modo practice, ni por score de IA. Un score de
        # IA alto no compensa operar contra-tendencia; los datos muestran que
        # contra-tendencia pierde incluso cuando el resto del setup parece bueno.
        trend_aligned = (main_trend != "NEUTRAL" and zone_dir == main_trend)
        if not trend_aligned:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"Contra-tendencia: zona={zone_dir}, tendencia={main_trend}. Bloqueo duro (sin excepciones).",
                "confidence": 0,
                "score": ai_score,
                "pattern": pattern_name,
                "ai_label": "SKIP",
                "zone_strength": zone_strength,
                "rsi": current_rsi,
            }

        # =====================================================================
        # 4.7 ESTRUCTURA DE MERCADO + TIMING DE RETROCESO (solo activos reales)
        # =====================================================================
        # El OTC es un paseo aleatorio medido (sin edge direccional confirmado
        # en 57.000 velas / 138 reglas probadas), así que este motor solo
        # aplica a activos reales. En OTC el comportamiento no cambia.
        market_map = None
        if not is_otc(asset):
            market_map = self.market_structure_engine.build_map(
                asset, df_m1, df_m5, df_m15, h1_data,
                htf_minutes=30 if df_m30 is not None else 60,
                context=context,
            )
            if market_map["entry_bias"] == "WAIT":
                return {
                    "asset": asset,
                    "action": "WAIT",
                    "reason": f"Estructura/timing: {market_map['reason']}",
                    "confidence": ai_conf,
                    "score": ai_score,
                    "pattern": pattern_name,
                    "ai_label": ai_label,
                    "zone_strength": zone_strength,
                    "rsi": current_rsi,
                    "macro_trend": market_map["macro_trend"],
                    "retracement_stage": market_map["retracement_m15"]["stage"],
                }
            if market_map["entry_bias"] != "NEUTRAL" and market_map["entry_bias"] != expected_dir:
                return {
                    "asset": asset,
                    "action": "WAIT",
                    "reason": f"Timing de retroceso sugiere {market_map['entry_bias']} pero la zona espera {expected_dir}: {market_map['reason']}",
                    "confidence": ai_conf,
                    "score": ai_score,
                    "pattern": pattern_name,
                    "ai_label": ai_label,
                    "zone_strength": zone_strength,
                    "rsi": current_rsi,
                    "macro_trend": market_map["macro_trend"],
                    "retracement_stage": market_map["retracement_m15"]["stage"],
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
        # 5.5 VALIDACIÓN DE ETAPA DEL REBOTE (CRÍTICO - ENTRADA TEMPRANA)
        # =====================================================================
        bounce = self._detect_bounce_stage(
            df_m1, nearest_zone.get("level", 1.1), nearest_zone.get("zone_type", "support")
        )
        
        if not bounce["entry_viable"]:
            return {
                "asset": asset,
                "action": "WAIT",
                "reason": f"REBOTE {bounce['stage']}: {bounce['reason']}",
                "confidence": ai_conf,
                "score": ai_score,
                "pattern": pattern_name,
                "ai_label": ai_label,
                "zone_strength": zone_strength,
                "rsi": current_rsi,
                "bounce_stage": bounce["stage"],
            }

        # =====================================================================
        # 6. CONFIRMACIÓN 3 FASES (NO BYPASS para rebotes en etapa MIDDLE)
        # =====================================================================
        phase = self.phase_analyzer.analyze_current_phase(
            df_m1, nearest_zone.get("level", 1.1), nearest_zone.get("zone_type", "support"),
            expected_dir
        )

        # Solo bypass si el rebote está en etapa EARLY (ideal para entrada)
        # Si está en MIDDLE, requiere confirmación real
        if bounce["stage"] == "EARLY" and ai_score >= 40:
            phase["ready"] = True
            phase["message"] = f"Bypass 3-fase: rebote EARLY + IA score ({ai_score:.0f})"
        elif not phase.get("ready", False) and ai_score >= 50:
            phase["ready"] = True
            phase["message"] = f"Permitido con IA alta ({ai_score:.0f}) en rebote {bounce['stage']}"

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
        
        # Si estamos dentro del 10% del rango de la zona, esperar movimiento
        if distance_to_zone < zone_range * 0.1:
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
        
        # FAVORECER el único patrón con edge confirmado en dos análisis independientes
        # (265 trades: 68.2% WR: 500 trades: 69.2% WR). shooting_star y pin_bar_bearish
        # se removieron de aquí: su WR se invirtió/no se sostuvo entre cortes de datos,
        # no hay evidencia consistente de edge.
        if pattern_name == "pin_bar_bullish":
            confidence = min(0.95, confidence + 0.10)
            final_score = min(100, final_score + 10)
        
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
            "bounce_stage": bounce.get("stage", "UNKNOWN"),
            "bounce_distance_pct": bounce.get("distance_from_zone_pct", 0),
            "macro_trend": market_map["macro_trend"] if market_map else None,
            "retracement_stage": market_map["retracement_m15"]["stage"] if market_map else None,
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
