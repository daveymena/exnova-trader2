"""
MACRO TREND ANALYZER v2.0
═══════════════════════════════════════════════════════════════════════════════

Analiza el CONTEXTO MACRO para detectar:
✅ Patrones ganadores (momentos en que SIEMPRE gana)
❌ Trampas del mercado (momentos en que NUNCA debería entrar)
🎯 Tendencia dominante vs. contra-tendencia

Lógica:
- Si H1/D1 sube, prioriza CALL sobre PUT
- Si H1/D1 baja, prioriza PUT sobre CALL  
- Si está en consolidación, rechaza movimientos extremos
- Si ve divergencia macro (H1 vs M1), aumenta threshold de confianza
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
from datetime import datetime

class MacroTrendAnalyzer:
    
    def __init__(self):
        self.last_h1_close = None
        self.last_d1_close = None
        self.h1_trend_cache = None
        self.d1_trend_cache = None
        self.cache_time = None
        
    def analyze_macro_context(self, 
                              df_m1: pd.DataFrame,
                              df_m5: pd.DataFrame,
                              df_m15: pd.DataFrame,
                              df_h1: Optional[pd.DataFrame] = None,
                              df_d1: Optional[pd.DataFrame] = None) -> Dict:
        """
        Análisis macro completo: determina CONTEXTO GLOBAL del mercado.
        Devuelve recomendación de operación + riesgo de trampa.
        
        Returns:
            {
                "macro_trend": "strong_up" | "weak_up" | "neutral" | "weak_down" | "strong_down",
                "allows_call": bool,  # ¿Permite CALL?
                "allows_put": bool,   # ¿Permite PUT?
                "operation_allowed": bool,  # ¿Permite ALGUNA operación?
                "confidence_boost": float,  # +0.0 a +0.3 (agregue a confianza)
                "confidence_penalty": float,  # -0.0 a -0.3 (reste de confianza)
                "trap_risk": float,  # 0.0 a 1.0 (probabilidad de trampa macro)
                "reason": str,  # Explicación en español
                "macro_signal": "strong" | "weak" | "divergence" | "consolidation",
                "h1_trend": str,  # Tendencia H1
                "d1_trend": str,  # Tendencia D1
                "is_against_macro": bool,  # ¿Operar contra macro?
                "consolidation_level": float,  # 0-1 (cuán consolidado está)
            }
        """
        
        # Step 1: Analizar estructuras en cada timeframe
        m1_structure = self._analyze_structure(df_m1, "M1")
        m5_structure = self._analyze_structure(df_m5, "M5")
        m15_structure = self._analyze_structure(df_m15, "M15")
        h1_structure = self._analyze_structure(df_h1, "H1") if df_h1 is not None and len(df_h1) >= 10 else None
        d1_structure = self._analyze_structure(df_d1, "D1") if df_d1 is not None and len(df_d1) >= 5 else None
        
        # Step 2: Determinar tendencias por timeframe
        h1_trend = self._get_trend(h1_structure) if h1_structure else "neutral"
        d1_trend = self._get_trend(d1_structure) if d1_structure else "neutral"
        m15_trend = self._get_trend(m15_structure)
        m5_trend = self._get_trend(m5_structure)
        m1_trend = self._get_trend(m1_structure)
        
        # Step 3: Determinar MACRO TREND (jerarquía: D1 > H1 > M15)
        macro_trend = self._determine_macro_trend(d1_trend, h1_trend, m15_trend)
        
        # Step 4: Detectar DIVERGENCIAS (si M1 va contra macro)
        divergence_detected = self._detect_divergence(m1_trend, macro_trend, m5_trend)
        
        # Step 5: Detectar CONSOLIDACIÓN (precio está atrapado)
        consolidation_level = self._detect_consolidation(df_m15 or df_m5)
        
        # Step 6: Calcular penalizaciones y bonificaciones
        confidence_boost, confidence_penalty = self._calculate_confidence_adjustments(
            m1_trend, macro_trend, divergence_detected, consolidation_level, m5_structure
        )
        
        # Step 7: Determinar qué operaciones PERMITIR
        allows_call, allows_put, operation_allowed = self._determine_allowed_operations(
            macro_trend, consolidation_level, divergence_detected
        )
        
        # Step 8: Calcular riesgo de trampa
        trap_risk = self._calculate_trap_risk(
            m1_structure, m5_structure, m15_structure, macro_trend, 
            consolidation_level, divergence_detected
        )
        
        # Step 9: Generar explicación
        reason = self._generate_reason(
            macro_trend, h1_trend, d1_trend, consolidation_level, 
            divergence_detected, trap_risk
        )
        
        # Step 10: Generar macro_signal (calidad del contexto)
        macro_signal = self._generate_macro_signal(
            macro_trend, divergence_detected, consolidation_level, trap_risk
        )
        
        # Step 11: Determinar si es contra-tendencia
        is_against_macro = (macro_trend in ["strong_up", "weak_up"] and m1_trend in ["down", "strong_down"]) or \
                          (macro_trend in ["strong_down", "weak_down"] and m1_trend in ["up", "strong_up"])
        
        return {
            "macro_trend": macro_trend,
            "allows_call": allows_call,
            "allows_put": allows_put,
            "operation_allowed": operation_allowed,
            "confidence_boost": confidence_boost,
            "confidence_penalty": confidence_penalty,
            "trap_risk": trap_risk,
            "reason": reason,
            "macro_signal": macro_signal,
            "h1_trend": h1_trend,
            "d1_trend": d1_trend,
            "is_against_macro": is_against_macro,
            "consolidation_level": consolidation_level,
            "m1_trend": m1_trend,
            "m5_trend": m5_trend,
            "m15_trend": m15_trend,
            "divergence_detected": divergence_detected,
        }
    
    # ─────────────────────────────────────────────────────────────────────────────
    # STEP 1: Analizar estructura (detectar HH/HL, LH/LL, cuántas velas confirman)
    # ─────────────────────────────────────────────────────────────────────────────
    
    def _analyze_structure(self, df: Optional[pd.DataFrame], timeframe: str) -> Dict:
        """Analiza estructura: HH/HL/LH/LL, trend strength, etc."""
        
        if df is None or len(df) < 5:
            return {"trend": "neutral", "structure": "unclear", "strength": 0.0}
        
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        n = len(df)
        
        # Últimas 3 velas (lo más reciente)
        recent_high_1 = highs[-1]
        recent_high_2 = highs[-2] if n > 1 else recent_high_1
        recent_high_3 = highs[-3] if n > 2 else recent_high_2
        
        recent_low_1 = lows[-1]
        recent_low_2 = lows[-2] if n > 1 else recent_low_1
        recent_low_3 = lows[-3] if n > 2 else recent_low_2
        
        # Detectar estructura
        hh = recent_high_1 > recent_high_2 > recent_high_3  # Higher High
        ll = recent_low_1 < recent_low_2 < recent_low_3    # Lower Low
        hl = recent_high_1 > recent_high_2 and recent_low_1 < recent_low_2  # Breaking
        lh = recent_high_1 < recent_high_2 and recent_low_1 > recent_low_2  # Reversal signal
        
        # Calcular fuerza de la tendencia (cuántas velas confirman el patrón)
        if hh:
            structure = "HH (Higher High)"
            # Contar cuántas más velas confirman HH
            hh_count = 1
            for i in range(2, min(10, n)):
                if highs[-(i)] > highs[-(i+1)]:
                    hh_count += 1
                else:
                    break
            strength = min(hh_count / 5, 1.0)  # Max 1.0 si 5+ velas confirman
        elif ll:
            structure = "LL (Lower Low)"
            ll_count = 1
            for i in range(2, min(10, n)):
                if lows[-(i)] < lows[-(i+1)]:
                    ll_count += 1
                else:
                    break
            strength = min(ll_count / 5, 1.0)
        elif hl or lh:
            structure = "Breaking/Reversal"
            strength = 0.5
        else:
            structure = "Consolidation"
            strength = 0.2
        
        # RSI para confirmar momentum
        rsi = self._calculate_rsi(closes)
        
        # ATR para volatilidad
        atr = self._calculate_atr(df)
        
        return {
            "trend": "up" if (hh or hl) else "down" if (ll or lh) else "neutral",
            "structure": structure,
            "strength": strength,
            "hh": hh,
            "ll": ll,
            "hl": hl,
            "lh": lh,
            "rsi": rsi,
            "atr": atr,
            "recent_high": recent_high_1,
            "recent_low": recent_low_1,
            "recent_close": closes[-1],
        }
    
    # ─────────────────────────────────────────────────────────────────────────────
    # STEP 2-3: Convertir estructura a tendencia + determinar MACRO TREND
    # ─────────────────────────────────────────────────────────────────────────────
    
    def _get_trend(self, structure: Dict) -> str:
        """Convierte estructura a nombre de tendencia."""
        if structure is None:
            return "neutral"
        
        if structure["hh"]:
            if structure["strength"] > 0.7:
                return "strong_up"
            else:
                return "up"
        elif structure["ll"]:
            if structure["strength"] > 0.7:
                return "strong_down"
            else:
                return "down"
        else:
            return "neutral"
    
    def _determine_macro_trend(self, d1_trend: str, h1_trend: str, m15_trend: str) -> str:
        """
        Jerarquía: D1 (60%) > H1 (30%) > M15 (10%)
        Devuelve: strong_up, weak_up, neutral, weak_down, strong_down
        """
        trend_score = 0.0
        
        # D1 (60% del peso)
        if d1_trend == "strong_up":
            trend_score += 0.6
        elif d1_trend == "up":
            trend_score += 0.35
        elif d1_trend == "down":
            trend_score -= 0.35
        elif d1_trend == "strong_down":
            trend_score -= 0.6
        
        # H1 (30% del peso)
        if h1_trend == "strong_up":
            trend_score += 0.3
        elif h1_trend == "up":
            trend_score += 0.15
        elif h1_trend == "down":
            trend_score -= 0.15
        elif h1_trend == "strong_down":
            trend_score -= 0.3
        
        # M15 (10% del peso)
        if m15_trend == "strong_up":
            trend_score += 0.1
        elif m15_trend == "up":
            trend_score += 0.05
        elif m15_trend == "down":
            trend_score -= 0.05
        elif m15_trend == "strong_down":
            trend_score -= 0.1
        
        # Convertir score a categoría
        if trend_score > 0.4:
            return "strong_up"
        elif trend_score > 0.1:
            return "weak_up"
        elif trend_score < -0.4:
            return "strong_down"
        elif trend_score < -0.1:
            return "weak_down"
        else:
            return "neutral"
    
    # ─────────────────────────────────────────────────────────────────────────────
    # STEP 4: Detectar DIVERGENCIAS (M1 contra macro)
    # ─────────────────────────────────────────────────────────────────────────────
    
    def _detect_divergence(self, m1_trend: str, macro_trend: str, m5_trend: str) -> bool:
        """
        Detecta si M1 está yendo CONTRA la tendencia macro.
        Divergencia = M1 contrario a MACRO, pero M5 sigue a MACRO.
        """
        m1_is_up = m1_trend in ["up", "strong_up"]
        m1_is_down = m1_trend in ["down", "strong_down"]
        macro_is_up = macro_trend in ["strong_up", "weak_up"]
        macro_is_down = macro_trend in ["strong_down", "weak_down"]
        m5_is_up = m5_trend in ["up", "strong_up"]
        m5_is_down = m5_trend in ["down", "strong_down"]
        
        # Divergencia: M1 contra macro pero M5 sigue macro
        if macro_is_up and m1_is_down and m5_is_up:
            return True
        if macro_is_down and m1_is_up and m5_is_down:
            return True
        
        return False
    
    # ─────────────────────────────────────────────────────────────────────────────
    # STEP 5: Detectar CONSOLIDACIÓN
    # ─────────────────────────────────────────────────────────────────────────────
    
    def _detect_consolidation(self, df: pd.DataFrame) -> float:
        """
        Detecta qué tan consolidado está el precio.
        Retorna 0.0 (tendencia clara) a 1.0 (muy consolidado).
        """
        if len(df) < 10:
            return 0.5
        
        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        
        # Rango de las últimas 20 velas
        recent_range = highs[-20:].max() - lows[-20:].min()
        
        # Promedio de movimiento por vela
        avg_move = np.mean([abs(closes[i] - closes[i-1]) for i in range(1, min(20, len(closes)))])
        
        # Si el rango es pequeño vs movimiento promedio, está consolidado
        consolidation_level = 1.0 - min(avg_move / (recent_range + 1e-10), 1.0)
        
        return consolidation_level
    
    # ─────────────────────────────────────────────────────────────────────────────
    # STEP 6: Calcular ajustes de confianza
    # ─────────────────────────────────────────────────────────────────────────────
    
    def _calculate_confidence_adjustments(self, 
                                         m1_trend: str, 
                                         macro_trend: str, 
                                         divergence: bool,
                                         consolidation: float,
                                         m5_structure: Dict) -> Tuple[float, float]:
        """
        Retorna: (confidence_boost, confidence_penalty)
        """
        boost = 0.0
        penalty = 0.0
        
        # BONUS: Si M1 sigue al MACRO (trade con macro)
        m1_up = m1_trend in ["up", "strong_up"]
        m1_down = m1_trend in ["down", "strong_down"]
        macro_up = macro_trend in ["strong_up", "weak_up"]
        macro_down = macro_trend in ["strong_down", "weak_down"]
        
        if (m1_up and macro_up) or (m1_down and macro_down):
            boost += 0.15
        
        # BONUS: Si es strong_up o strong_down (tendencia clara)
        if macro_trend in ["strong_up", "strong_down"]:
            boost += 0.1
        
        # PENALTY: Si hay divergencia (M1 contra macro)
        if divergence:
            penalty += 0.20
        
        # PENALTY: Si está muy consolidado (sin movimiento)
        if consolidation > 0.8:
            penalty += 0.25
        
        # BONUS: Si M5 tiene RSI extremo (sobreventa/sobrecompra)
        if m5_structure.get("rsi", 50) < 20:
            boost += 0.1  # Sobreventa = posible rebote
        elif m5_structure.get("rsi", 50) > 80:
            boost += 0.1  # Sobrecompra = continuación posible
        
        return boost, penalty
    
    # ─────────────────────────────────────────────────────────────────────────────
    # STEP 7: Determinar operaciones permitidas
    # ─────────────────────────────────────────────────────────────────────────────
    
    def _determine_allowed_operations(self, 
                                     macro_trend: str, 
                                     consolidation: float, 
                                     divergence: bool) -> Tuple[bool, bool, bool]:
        """
        Retorna: (allows_call, allows_put, operation_allowed)
        """
        allows_call = False
        allows_put = False
        operation_allowed = False
        
        # Si está muy consolidado, rechazar TODO
        if consolidation > 0.9:
            return False, False, False
        
        # Si hay divergencia fuerte, aumentar threshold (ambas permitidas pero arriesgado)
        if divergence:
            # Ambas permitidas pero con riesgo
            allows_call = True
            allows_put = True
            operation_allowed = True
        else:
            # Sin divergencia: seguir al macro
            if macro_trend == "strong_up":
                allows_call = True  # Prioriza CALL
                allows_put = False   # PUT arriesgado
            elif macro_trend == "weak_up":
                allows_call = True
                allows_put = True   # PUT todavía posible si confirma
            elif macro_trend == "neutral":
                allows_call = True
                allows_put = True
            elif macro_trend == "weak_down":
                allows_call = True
                allows_put = True
            elif macro_trend == "strong_down":
                allows_put = True   # Prioriza PUT
                allows_call = False # CALL arriesgado
            
            operation_allowed = allows_call or allows_put
        
        return allows_call, allows_put, operation_allowed
    
    # ─────────────────────────────────────────────────────────────────────────────
    # STEP 8: Calcular riesgo de trampa MACRO
    # ─────────────────────────────────────────────────────────────────────────────
    
    def _calculate_trap_risk(self, 
                            m1_struct: Dict, 
                            m5_struct: Dict, 
                            m15_struct: Dict,
                            macro_trend: str,
                            consolidation: float,
                            divergence: bool) -> float:
        """
        Calcula probabilidad de trampa MACRO (0.0 a 1.0).
        """
        trap_risk = 0.0
        
        # Riesgo base: si está muy consolidado
        trap_risk += consolidation * 0.3  # Hasta 0.3
        
        # Riesgo: si hay divergencia
        if divergence:
            trap_risk += 0.25
        
        # Riesgo: si M1 es extremadamente sobrecomprado/sobreventa sin confirmación M5
        m1_rsi = m1_struct.get("rsi", 50)
        m5_rsi = m5_struct.get("rsi", 50)
        
        if (m1_rsi > 90 or m1_rsi < 10) and abs(m5_rsi - 50) < 20:
            trap_risk += 0.15  # M1 extremo pero M5 neutral = trampa
        
        # Riesgo: si macro es neutral y M1 hace movimiento violento
        if macro_trend == "neutral" and m1_struct.get("strength", 0) > 0.8:
            trap_risk += 0.2  # Movimiento sin contexto = trampa probable
        
        # Riesgo: si M1 y M15 están en direcciones opuestas
        m1_up = m1_struct.get("trend") in ["up", "strong_up"]
        m15_up = m15_struct.get("trend") in ["up", "strong_up"]
        if m1_up != m15_up:
            trap_risk += 0.1
        
        # Capear en 0-1
        trap_risk = min(max(trap_risk, 0.0), 1.0)
        
        return trap_risk
    
    # ─────────────────────────────────────────────────────────────────────────────
    # STEP 9-11: Generar explicaciones y señal
    # ─────────────────────────────────────────────────────────────────────────────
    
    def _generate_reason(self, 
                        macro_trend: str, 
                        h1_trend: str, 
                        d1_trend: str,
                        consolidation: float,
                        divergence: bool,
                        trap_risk: float) -> str:
        """Genera explicación en español del contexto macro."""
        
        reason_parts = []
        
        # Contexto macro
        trend_text = {
            "strong_up": "TENDENCIA ALCISTA FUERTE",
            "weak_up": "Tendencia alcista débil",
            "neutral": "Mercado neutral/consolidado",
            "weak_down": "Tendencia bajista débil",
            "strong_down": "TENDENCIA BAJISTA FUERTE",
        }
        reason_parts.append(f"📊 {trend_text.get(macro_trend, macro_trend)}")
        
        # Contextos por timeframe
        if d1_trend != "neutral":
            reason_parts.append(f"📅 D1: {d1_trend}")
        if h1_trend != "neutral":
            reason_parts.append(f"⏰ H1: {h1_trend}")
        
        # Consolidación
        if consolidation > 0.7:
            reason_parts.append("⚠️ Mercado muy consolidado (riesgo de falsos movimientos)")
        
        # Divergencia
        if divergence:
            reason_parts.append("🔄 DIVERGENCIA: M1 va contra macro (mayor riesgo)")
        
        # Riesgo de trampa
        if trap_risk > 0.6:
            reason_parts.append("🚨 ALTO RIESGO DE TRAMPA MACRO")
        elif trap_risk > 0.3:
            reason_parts.append("⚠️ Riesgo moderado de trampa")
        
        return " | ".join(reason_parts)
    
    def _generate_macro_signal(self, 
                              macro_trend: str, 
                              divergence: bool,
                              consolidation: float,
                              trap_risk: float) -> str:
        """Calidad general del contexto macro."""
        
        if trap_risk > 0.7:
            return "divergence"  # Contexto poco confiable
        elif consolidation > 0.8:
            return "consolidation"  # Mercado atrapado
        elif macro_trend in ["strong_up", "strong_down"]:
            return "strong"  # Contexto excelente
        elif divergence:
            return "divergence"  # Conflicto de timeframes
        else:
            return "weak"  # Contexto débil o neutral
    
    # ─────────────────────────────────────────────────────────────────────────────
    # Utilidades: RSI, ATR, etc.
    # ─────────────────────────────────────────────────────────────────────────────
    
    def _calculate_rsi(self, closes: np.ndarray, period: int = 14) -> float:
        """Calcula RSI de un array de closes."""
        if len(closes) < period + 1:
            return 50.0
        
        deltas = np.diff(closes[-period-1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calcula ATR (Average True Range)."""
        if len(df) < period:
            return 0.0
        
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        
        tr_values = []
        for i in range(1, len(df)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            tr_values.append(tr)
        
        atr = np.mean(tr_values[-period:])
        return atr
