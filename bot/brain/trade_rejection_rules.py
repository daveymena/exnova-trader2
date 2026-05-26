"""
TRADE REJECTION RULES v1.0
═══════════════════════════════════════════════════════════════════════════════

Sistema de REGLAS para rechazar trades que tienen alta probabilidad de perder.
Basado en análisis histórico de pérdidas y patrones fallidos.

Lógica:
- Cada regla analiza específicas condiciones del mercado
- Si cumple la condición, la operación es RECHAZADA
- Se registra la razón del rechazo para aprendizaje
"""

from typing import Dict, Tuple, Optional
import pandas as pd


class TradeRejectionRules:
    """
    Sistema de reglas de RECHAZO automático.
    Previene entradas que estadísticamente pierden.
    """
    
    def __init__(self):
        self.rejections_log = []
        self.rejection_reasons = {}
    
    def evaluate(self, 
                trade_proposal: Dict,
                market_context: Dict,
                zone_info: Dict,
                technical_data: Dict) -> Tuple[bool, Optional[str]]:
        """
        Evalúa si una propuesta de trade debe ser RECHAZADA.
        
        Args:
            trade_proposal: {direction, expiration_seconds, pattern}
            market_context: {macro_trend, h1_trend, m1_trend, consolidation_level}
            zone_info: {strength, hold_rate, touches, distance}
            technical_data: {rsi_m1, rsi_m5, atr_m5, rsi_extremes}
        
        Returns:
            (should_reject: bool, reason: str or None)
        """
        
        # Regla 1: Zona demasiado débil
        should_reject, reason = self._rule_zone_too_weak(zone_info)
        if should_reject:
            return True, reason
        
        # Regla 2: Contra-tendencia sin confirmación
        should_reject, reason = self._rule_counter_trend_risky(
            trade_proposal, market_context, zone_info
        )
        if should_reject:
            return True, reason
        
        # Regla 3: RSI extremo sin zona fuerte
        should_reject, reason = self._rule_rsi_extreme_weak_zone(
            technical_data, zone_info
        )
        if should_reject:
            return True, reason
        
        # Regla 4: Consolidación + movimiento extremo = trampa
        should_reject, reason = self._rule_consolidation_trap(
            market_context, zone_info, technical_data
        )
        if should_reject:
            return True, reason
        
        # Regla 5: Breakout contra consolidación = falso
        should_reject, reason = self._rule_false_breakout(
            trade_proposal, market_context, zone_info
        )
        if should_reject:
            return True, reason
        
        # Regla 6: Divergencia fuerte = riesgo alto
        should_reject, reason = self._rule_divergence_risk(
            market_context, technical_data
        )
        if should_reject:
            return True, reason
        
        # Regla 7: Expiración muy corta en contexto difícil
        should_reject, reason = self._rule_expiration_too_short(
            trade_proposal, market_context, zone_info
        )
        if should_reject:
            return True, reason
        
        # Regla 8: Zona de bajo hold rate (no respeta)
        should_reject, reason = self._rule_low_hold_rate_zone(zone_info)
        if should_reject:
            return True, reason
        
        # Regla 9: Zona fallback (toques <= 1 y strength <= 0.55)
        should_reject, reason = self._rule_fallback_zone(zone_info)
        if should_reject:
            return True, reason
        
        # Regla 10: Patrón de vela peligroso (engulfing_bearish, doji, hammer)
        should_reject, reason = self._rule_bad_pattern(trade_proposal, technical_data)
        if should_reject:
            return True, reason
        
        # Regla 11: Contra-tendencia sin score alto (trend_aligned check)
        should_reject, reason = self._rule_weak_trend_alignment(trade_proposal, market_context, technical_data)
        if should_reject:
            return True, reason
        
        # ✅ Pasó todas las reglas - Permitir
        return False, None
    
    # ─────────────────────────────────────────────────────────────────────────────
    # REGLAS DE RECHAZO
    # ─────────────────────────────────────────────────────────────────────────────
    
    def _rule_zone_too_weak(self, zone_info: Dict) -> Tuple[bool, Optional[str]]:
        """REGLA 1: Si la zona es demasiado débil, rechazar."""
        
        min_strength = 0.20
        strength = zone_info.get("strength", 0.0)
        
        if strength < min_strength:
            reason = f"🚫 RECHAZO: Zona demasiado débil (fuerza={strength:.2f}, necesita ≥{min_strength})"
            self._log_rejection("zone_too_weak", reason)
            return True, reason
        
        return False, None
    
    def _rule_counter_trend_risky(self, 
                                  trade_proposal: Dict,
                                  market_context: Dict,
                                  zone_info: Dict) -> Tuple[bool, Optional[str]]:
        """REGLA 2: Contra-tendencia sin confirmación suficiente."""
        
        direction = trade_proposal.get("direction", "").upper()  # "CALL" o "PUT"
        macro_trend = market_context.get("macro_trend", "neutral")
        m5_trend = market_context.get("m5_trend", "neutral")
        zone_strength = zone_info.get("strength", 0.0)
        expiration_sec = trade_proposal.get("expiration_seconds", 300)
        
        # Detectar si es contra-tendencia
        is_counter_macro = (
            (macro_trend in ["strong_up", "weak_up"] and direction == "PUT") or
            (macro_trend in ["strong_down", "weak_down"] and direction == "CALL")
        )
        
        is_counter_m5 = (
            (m5_trend in ["up", "strong_up"] and direction == "PUT") or
            (m5_trend in ["down", "strong_down"] and direction == "CALL")
        )
        
        # Si es contra-tendencia en AMBOS niveles (macro + M5)
        if is_counter_macro and is_counter_m5:
            # Necesita zona suficiente
            min_zone_strength = 0.50
            if zone_strength < min_zone_strength:
                reason = (
                    f"🚫 RECHAZO: Contra-tendencia (macro={macro_trend}, M5={m5_trend}) "
                    f"sin zona suficiente (fuerza={zone_strength:.2f}, necesita ≥{min_zone_strength})"
                )
                self._log_rejection("counter_trend_risky", reason)
                return True, reason
            
            # Necesita tiempo suficiente
            min_expiration_sec = 120  # 2 minutos
            if expiration_sec < min_expiration_sec:
                reason = (
                    f"🚫 RECHAZO: Contra-tendencia requiere mínimo {min_expiration_sec}s "
                    f"(propuesto: {expiration_sec}s)"
                )
                self._log_rejection("counter_trend_risky", reason)
                return True, reason
        
        return False, None
    
    def _rule_rsi_extreme_weak_zone(self,
                                    technical_data: Dict,
                                    zone_info: Dict) -> Tuple[bool, Optional[str]]:
        """REGLA 3: RSI extremo + zona débil = trampa probable."""
        
        rsi_m1 = technical_data.get("rsi_m1", 50)
        rsi_m5 = technical_data.get("rsi_m5", 50)
        zone_strength = zone_info.get("strength", 0.0)
        
        # Si M1 está extremadamente sobrecomprado/sobreventa
        is_rsi_m1_extreme = rsi_m1 < 10 or rsi_m1 > 90
        
        # Pero M5 no confirma (está neutral)
        is_rsi_m5_neutral = 30 < rsi_m5 < 70
        
        # Y la zona no es fuerte
        if is_rsi_m1_extreme and is_rsi_m5_neutral and zone_strength < 0.40:
            reason = (
                f"🚫 RECHAZO: Trampa detectable - RSI M1 extremo ({rsi_m1:.0f}) "
                f"sin confirmación M5 ({rsi_m5:.0f}) + zona débil ({zone_strength:.2f})"
            )
            self._log_rejection("rsi_extreme_weak_zone", reason)
            return True, reason
        
        return False, None
    
    def _rule_consolidation_trap(self,
                                market_context: Dict,
                                zone_info: Dict,
                                technical_data: Dict) -> Tuple[bool, Optional[str]]:
        """REGLA 4: Mercado consolidado + movimiento fuerte = trampa."""
        
        consolidation = market_context.get("consolidation_level") or 0.0
        atr = technical_data.get("atr_m5") or 0.0
        zone_strength = zone_info.get("strength", 0.0)
        
        # Si está MUY consolidado
        if consolidation > 0.95:
            # Y hay un breakout/zona fuerte local
            if zone_strength > 0.60 and atr > 0.5:
                reason = (
                    f"🚫 RECHAZO: Trampa de breakout - mercado consolidado ({consolidation:.2f}) "
                    f"intenta breakout ({atr:.2f} ATR)"
                )
                self._log_rejection("consolidation_trap", reason)
                return True, reason
        
        return False, None
    
    def _rule_false_breakout(self,
                            trade_proposal: Dict,
                            market_context: Dict,
                            zone_info: Dict) -> Tuple[bool, Optional[str]]:
        """REGLA 5: Breakout que contradice macro-tendencia."""
        
        pattern = trade_proposal.get("pattern", "").lower()
        direction = trade_proposal.get("direction", "").upper()
        macro_trend = market_context.get("macro_trend", "neutral")
        m15_trend = market_context.get("m15_trend", "neutral")
        zone_strength = zone_info.get("strength", 0.0)
        
        # Si es breakout
        if pattern == "breakout":
            # Pero la tendencia es contraria débil
            is_breakout_against_macro = (
                (macro_trend in ["strong_down", "weak_down"] and direction == "CALL") or
                (macro_trend in ["strong_up", "weak_up"] and direction == "PUT")
            )
            
            # Y M15 también va contra
            is_m15_against = (
                (m15_trend in ["down", "strong_down"] and direction == "CALL") or
                (m15_trend in ["up", "strong_up"] and direction == "PUT")
            )
            
            if is_breakout_against_macro and is_m15_against and zone_strength < 0.40:
                reason = (
                    f"🚫 RECHAZO: Falso breakout - macro={macro_trend}, M15={m15_trend}, "
                    f"breakout={direction} (zona={zone_strength:.2f})"
                )
                self._log_rejection("false_breakout", reason)
                return True, reason
        
        return False, None
    
    def _rule_divergence_risk(self,
                             market_context: Dict,
                             technical_data: Dict) -> Tuple[bool, Optional[str]]:
        """REGLA 6: Divergencia M1 vs Macro = riesgo alto."""
        
        divergence = market_context.get("divergence_detected", False)
        macro_trend = market_context.get("macro_trend", "neutral")
        
        # Si hay divergencia detectada Y la macro es neutral/débil
        if divergence and macro_trend in ["neutral", "weak_up", "weak_down"]:
            reason = (
                f"🚫 RECHAZO: Divergencia detectada con macro débil (macro={macro_trend})"
            )
            self._log_rejection("divergence_risk", reason)
            return True, reason
        
        return False, None
    
    def _rule_expiration_too_short(self,
                                  trade_proposal: Dict,
                                  market_context: Dict,
                                  zone_info: Dict) -> Tuple[bool, Optional[str]]:
        """REGLA 7: Expiración muy corta en contexto difícil."""
        
        expiration_sec = trade_proposal.get("expiration_seconds", 300)
        macro_trend = market_context.get("macro_trend", "neutral")
        consolidation = market_context.get("consolidation_level") or 0.0
        zone_strength = zone_info.get("strength", 0.0)
        
        # Contexto difícil: consolidado + zona débil
        is_difficult_context = consolidation > 0.85 and zone_strength < 0.40
        
        # Con expiración corta
        if is_difficult_context and expiration_sec < 60:  # < 1 minuto
            reason = (
                f"🚫 RECHAZO: Expiración muy corta ({expiration_sec}s) "
                f"en contexto difícil (consolidation={consolidation:.2f})"
            )
            self._log_rejection("expiration_too_short", reason)
            return True, reason
        
        return False, None
    
    def _rule_low_hold_rate_zone(self, zone_info: Dict) -> Tuple[bool, Optional[str]]:
        """REGLA 8: Zona con bajo hold rate (no respeta histórico)."""
        
        hold_rate = zone_info.get("hold_rate", 0.5)
        touches = zone_info.get("touches", 0)
        
        # Si la zona tiene muchos toques pero bajo hold rate
        if touches >= 10 and hold_rate < 0.10:
            reason = (
                f"🚫 RECHAZO: Zona no respeta (hold_rate={hold_rate:.2f} "
                f"después de {touches} toques) - es una trampa"
            )
            self._log_rejection("low_hold_rate_zone", reason)
            return True, reason
        
        return False, None
    
    # ─────────────────────────────────────────────────────────────────────────────
    # LOGGING
    # ─────────────────────────────────────────────────────────────────────────────
    
    def _rule_fallback_zone(self, zone_info: Dict) -> Tuple[bool, Optional[str]]:
        """REGLA 9: Zona sin toques reales ni análisis (fallback = zona artificial)."""
        touches = zone_info.get("touches", 0)
        strength = zone_info.get("strength", 0.0)
        hold_rate = zone_info.get("hold_rate", 0.5)
        
        # Si tiene <= 1 toque y strength baja, es zona generada artificialmente (fallback)
        if touches <= 1 and strength <= 0.30:
            reason = (f"RECHAZO: Zona artificial/fallback (toques={touches}, "
                      f"strength={strength:.2f}) - no hay soporte/resistencia real")
            self._log_rejection("fallback_zone", reason)
            return True, reason
        
        return False, None

    def _rule_bad_pattern(self,
                         trade_proposal: Dict,
                         technical_data: Dict) -> Tuple[bool, Optional[str]]:
        """REGLA 10: Patrón de vela estadísticamente peligroso."""
        
        pattern = trade_proposal.get("pattern", "").lower()
        
        # engulfing_bearish: 20% WR en 10 trades históricos
        if pattern == "engulfing_bearish":
            reason = "RECHAZO: Patrón engulfing_bearish (20% WR histórico) - evitar"
            self._log_rejection("bad_pattern", reason)
            return True, reason
        
        # doji: 0% WR en datos históricos
        if pattern == "doji":
            reason = "RECHAZO: Patrón doji (0% WR histórico) - muy riesgoso"
            self._log_rejection("bad_pattern", reason)
            return True, reason
        
        # hammer: 42.9% WR - solo permitir si RSI y zona son excepcionales
        if pattern == "hammer":
            rsi_m1 = technical_data.get("rsi_m1", 50)
            rsi_m5 = technical_data.get("rsi_m5", 50)
            zone_strength = trade_proposal.get("zone_strength", 0)
            
            # hammer solo es aceptable si RSI < 25 o RSI > 75 (extremo real)
            # y la zona es fuerte
            if not ((rsi_m1 < 25 or rsi_m1 > 75) and zone_strength >= 0.60):
                reason = (f"RECHAZO: Patrón hammer en condiciones no óptimas "
                          f"(RSI={rsi_m1:.0f}, zona={zone_strength:.2f})")
                self._log_rejection("bad_pattern", reason)
                return True, reason
        
        return False, None
    
    def _rule_weak_trend_alignment(self,
                                  trade_proposal: Dict,
                                  market_context: Dict,
                                  technical_data: Dict) -> Tuple[bool, Optional[str]]:
        """REGLA 11: Trade contra-tendencia sin suficiente respaldo."""
        
        direction = trade_proposal.get("direction", "").upper()
        macro_trend = market_context.get("macro_trend", "neutral")
        h1_trend = market_context.get("h1_trend", "neutral")
        
        # Detectar si va contra la tendencia macro
        trend_aligned = (
            (direction == "CALL" and macro_trend in ["CALL", "strong_up", "weak_up"]) or
            (direction == "PUT" and macro_trend in ["PUT", "strong_down", "weak_down"])
        )
        
        if not trend_aligned and macro_trend != "NEUTRAL":
            # Contra-tendencia: estadísticamente 23.1% WR
            # Solo permitir si H1 también confirma la contra-tendencia
            h1_aligned = (
                (direction == "CALL" and h1_trend in ["CALL", "strong_up", "weak_up"]) or
                (direction == "PUT" and h1_trend in ["PUT", "strong_down", "weak_down"])
            )
            
            if not h1_aligned:
                reason = (f"RECHAZO: Contra-tendencia sin confirmación H1 "
                          f"(dir={direction}, macro={macro_trend}, H1={h1_trend})")
                self._log_rejection("weak_trend_alignment", reason)
                return True, reason
        
        return False, None

    def _log_rejection(self, rule_name: str, reason: str):
        """Registra un rechazo."""
        self.rejections_log.append({
            "rule": rule_name,
            "reason": reason,
            "timestamp": pd.Timestamp.now(),
        })
        
        # Actualizar estadística
        if rule_name not in self.rejection_reasons:
            self.rejection_reasons[rule_name] = 0
        self.rejection_reasons[rule_name] += 1
    
    def get_rejection_stats(self) -> Dict:
        """Retorna estadísticas de rechazos."""
        total_rejections = len(self.rejections_log)
        return {
            "total_rejections": total_rejections,
            "by_rule": self.rejection_reasons,
            "most_common_rule": max(self.rejection_reasons.items(), 
                                   key=lambda x: x[1])[0] if self.rejection_reasons else None,
        }
