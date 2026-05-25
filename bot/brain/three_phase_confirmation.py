"""
Confirmación de Entrada en 3 Fases v1.0
Phase 1: Liquidación - El precio prueba la zona, se rechaza
Phase 2: Retest - El precio vuelve a probar la zona
Phase 3: Confirmación - El precio CIERRA fuera con volumen → ENTER

Esto evita falsas micro-tendencias y asegura que el movimiento está real.
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, List, Tuple


class ThreePhaseConfirmation:
    """
    Sistema de confirmación multi-fase para evitar micro-tendencias falsas.
    
    Flujo:
    1. LIQUIDATION PHASE: Precio toca zona, rechaza violentamente
    2. RETEST PHASE: Precio vuelve a probar zona (más débil que antes)
    3. CONFIRMATION PHASE: Precio cierra fuera de zona con momentum sostenido
    """
    
    def __init__(self):
        self.phases = {
            "LIQUIDATION": 1,
            "RETEST": 2,
            "CONFIRMATION": 3,
        }
    
    # ════════════════════════════════════════════════════════════════════════════
    # PHASE 1: LIQUIDACIÓN - El precio rechaza en la zona
    # ════════════════════════════════════════════════════════════════════════════
    
    def detect_liquidation(self,
                          df: pd.DataFrame,
                          zone_level: float,
                          zone_type: str,
                          lookback: int = 3) -> Dict:
        """
        LIQUIDACIÓN: El precio toca la zona y RECHAZA inmediatamente.
        
        Para SUPPORT (CALL):
        - Precio baja toca soporte
        - Luego sube rápido (rechazo)
        - Se forma mecha larga hacia abajo
        
        Para RESISTANCE (PUT):
        - Precio sube toca resistencia
        - Luego baja rápido (rechazo)
        - Se forma mecha larga hacia arriba
        """
        
        if len(df) < lookback:
            return {"phase": "PENDING", "reason": "Datos insuficientes"}
        
        recent = df.iloc[-lookback:].copy()
        
        for i in range(len(recent) - 1):
            candle = recent.iloc[i]
            next_candle = recent.iloc[i + 1]
            
            candle_open = float(candle["open"])
            candle_close = float(candle["close"])
            candle_high = float(candle["high"])
            candle_low = float(candle["low"])
            
            next_open = float(next_candle["open"])
            next_close = float(next_candle["close"])
            
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # SUPPORT LIQUIDATION (CALL): Mecha larga hacia abajo, rechazo rápido
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            if zone_type == "support":
                # Detectar toque en soporte
                touched_support = candle_low <= zone_level * 1.001  # Toca soporte
                
                if touched_support:
                    # Mecha hacia abajo
                    wick_down = (candle_open - candle_low) / zone_level
                    
                    # Rechazo: cierre cerca del máximo (cuerpo de rechazo)
                    body_up = (candle_close - candle_open) / zone_level
                    
                    # Siguiente vela confirma el rechazo
                    next_candle_up = next_close > next_open
                    
                    if wick_down > 0.003 and body_up > 0.002 and next_candle_up:
                        return {
                            "phase": "LIQUIDATION",
                            "zone_type": "support",
                            "reason": f"Liquidación en soporte: mecha {wick_down*100:.2f}%, rechazo {body_up*100:.2f}%",
                            "touch_level": candle_low,
                            "wick_pct": wick_down * 100,
                            "rejection_body_pct": body_up * 100,
                            "candle_index": i,
                            "strength": min(1.0, (wick_down + body_up) / 0.01)  # Normalized 0-1
                        }
            
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # RESISTANCE LIQUIDATION (PUT): Mecha larga hacia arriba, rechazo rápido
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            if zone_type == "resistance":
                # Detectar toque en resistencia
                touched_resistance = candle_high >= zone_level * 0.999  # Toca resistencia
                
                if touched_resistance:
                    # Mecha hacia arriba
                    wick_up = (candle_high - candle_open) / zone_level
                    
                    # Rechazo: cierre cerca del mínimo (cuerpo de rechazo)
                    body_down = (candle_open - candle_close) / zone_level
                    
                    # Siguiente vela confirma el rechazo
                    next_candle_down = next_close < next_open
                    
                    if wick_up > 0.003 and body_down > 0.002 and next_candle_down:
                        return {
                            "phase": "LIQUIDATION",
                            "zone_type": "resistance",
                            "reason": f"Liquidación en resistencia: mecha {wick_up*100:.2f}%, rechazo {body_down*100:.2f}%",
                            "touch_level": candle_high,
                            "wick_pct": wick_up * 100,
                            "rejection_body_pct": body_down * 100,
                            "candle_index": i,
                            "strength": min(1.0, (wick_up + body_down) / 0.01)
                        }
        
        return {"phase": "PENDING", "reason": "Sin liquidación detectada"}
    
    # ════════════════════════════════════════════════════════════════════════════
    # PHASE 2: RETEST - El precio vuelve a probar la zona (más débil)
    # ════════════════════════════════════════════════════════════════════════════
    
    def detect_retest(self,
                     df: pd.DataFrame,
                     zone_level: float,
                     zone_type: str,
                     lookback: int = 5) -> Dict:
        """
        RETEST: Después de la liquidación, el precio vuelve a probar la zona.
        Pero esta vez es más débil (no llega tan profundo, mecha más corta).
        
        Esto indica que los "liquidadores" compraron/vendieron bastante y
        el precio rebota más débil.
        """
        
        if len(df) < lookback:
            return {"phase": "PENDING", "reason": "Datos insuficientes"}
        
        recent = df.iloc[-lookback:].copy()
        max_low = float(recent["low"].min())  # Mínimo más bajo
        max_high = float(recent["high"].max())  # Máximo más alto
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SUPPORT RETEST: Precio toca soporte pero NO BAJA tanto como antes
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if zone_type == "support":
            touches_support = max_low <= zone_level * 1.001
            
            if touches_support:
                # Primera pasada fue más profunda
                wick_retest = (zone_level - max_low) / zone_level
                
                # Si mecha es pequeña (< 0.2%) significa que fue débil = RETEST bueno
                if 0.0005 < wick_retest < 0.002:  # Toca pero débilmente
                    return {
                        "phase": "RETEST",
                        "zone_type": "support",
                        "reason": f"RETEST en soporte: mecha débil {wick_retest*100:.2f}% = rechazo débil",
                        "touch_level": max_low,
                        "wick_pct": wick_retest * 100,
                        "strength": 1.0 - (wick_retest * 100 / 0.3)  # Cuanto más débil, mayor confianza
                    }
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # RESISTANCE RETEST: Precio toca resistencia pero NO SUBE tanto como antes
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if zone_type == "resistance":
            touches_resistance = max_high >= zone_level * 0.999
            
            if touches_resistance:
                # Primera pasada fue más profunda
                wick_retest = (max_high - zone_level) / zone_level
                
                # Si mecha es pequeña (< 0.2%) significa que fue débil = RETEST bueno
                if 0.0005 < wick_retest < 0.002:  # Toca pero débilmente
                    return {
                        "phase": "RETEST",
                        "zone_type": "resistance",
                        "reason": f"RETEST en resistencia: mecha débil {wick_retest*100:.2f}% = rechazo débil",
                        "touch_level": max_high,
                        "wick_pct": wick_retest * 100,
                        "strength": 1.0 - (wick_retest * 100 / 0.3)
                    }
        
        return {"phase": "PENDING", "reason": "Sin RETEST detectado"}
    
    # ════════════════════════════════════════════════════════════════════════════
    # PHASE 3: CONFIRMACIÓN - El precio cierra FUERA de la zona con momentum
    # ════════════════════════════════════════════════════════════════════════════
    
    def detect_confirmation(self,
                           df: pd.DataFrame,
                           zone_level: float,
                           zone_type: str,
                           direction: str) -> Dict:
        """
        CONFIRMACIÓN: Después de liquidación + retest, el precio FINALMENTE
        cierra fuera de la zona con momentum sostenido.
        
        Para SUPPORT + CALL:
        - Precio cierra ENCIMA del soporte
        - La vela actual está formando arriba del soporte
        - Hay momentum (ATR aumentando, volumen)
        
        Para RESISTANCE + PUT:
        - Precio cierra DEBAJO de la resistencia
        - La vela actual está formando abajo de la resistencia
        - Hay momentum
        """
        
        if len(df) < 3:
            return {"phase": "PENDING", "reason": "Datos insuficientes"}
        
        signal_candle = df.iloc[-2]  # Vela cerrada
        current_candle = df.iloc[-1]  # Vela actual (formándose)
        
        signal_close = float(signal_candle["close"])
        signal_high = float(signal_candle["high"])
        signal_low = float(signal_candle["low"])
        
        current_open = float(current_candle["open"])
        current_close = float(current_candle["close"])
        current_high = float(current_candle["high"])
        current_low = float(current_candle["low"])
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SUPPORT + CALL: Precio cierra ENCIMA, vela actual en alza
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if zone_type == "support" and direction == "CALL":
            # Vela cerrada cerró arriba del soporte
            above_support = signal_close > zone_level * 1.001
            
            # Vela actual también está arriba
            current_above = current_close > zone_level * 1.0005
            
            # Vela actual tiene momentum (está subiendo)
            current_momentum = current_close > current_open
            
            # Distancia desde soporte crece (no vuelve a tocar)
            min_low = float(df.iloc[-3:]["low"].min())
            is_pulling_away = min_low > zone_level * 0.999  # No retoca
            
            if above_support and current_above and current_momentum and is_pulling_away:
                move_pct = (current_close - zone_level) / zone_level
                return {
                    "phase": "CONFIRMATION",
                    "zone_type": "support",
                    "direction": "CALL",
                    "reason": f"CONFIRMACIÓN CALL: precio cierra {move_pct*100:.2f}% arriba del soporte con momentum",
                    "move_pct": move_pct * 100,
                    "strength": min(1.0, move_pct * 200)  # Mayor movimiento = mayor confianza
                }
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # RESISTANCE + PUT: Precio cierra DEBAJO, vela actual en baja
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if zone_type == "resistance" and direction == "PUT":
            # Vela cerrada cerró debajo de la resistencia
            below_resistance = signal_close < zone_level * 0.999
            
            # Vela actual también está debajo
            current_below = current_close < zone_level * 0.9995
            
            # Vela actual tiene momentum (está bajando)
            current_momentum = current_close < current_open
            
            # Distancia desde resistencia crece (no vuelve a tocar)
            max_high = float(df.iloc[-3:]["high"].max())
            is_pulling_away = max_high < zone_level * 1.001  # No retoca
            
            if below_resistance and current_below and current_momentum and is_pulling_away:
                move_pct = (zone_level - current_close) / zone_level
                return {
                    "phase": "CONFIRMATION",
                    "zone_type": "resistance",
                    "direction": "PUT",
                    "reason": f"CONFIRMACIÓN PUT: precio cierra {move_pct*100:.2f}% abajo de la resistencia con momentum",
                    "move_pct": move_pct * 100,
                    "strength": min(1.0, move_pct * 200)
                }
        
        return {"phase": "PENDING", "reason": "Sin confirmación aún"}
    
    # ════════════════════════════════════════════════════════════════════════════
    # ANÁLISIS INTEGRAL: Detectar fase actual del precio
    # ════════════════════════════════════════════════════════════════════════════
    
    def analyze_current_phase(self,
                             df: pd.DataFrame,
                             zone_level: float,
                             zone_type: str,
                             direction: str) -> Dict:
        """
        Detecta en qué fase está el mercado:
        1. Liquidación
        2. Retest
        3. Confirmación → ENTER
        O: Ninguna (esperar)
        """
        
        phases_detected = []
        
        # Intentar detectar cada fase
        liquidation = self.detect_liquidation(df, zone_level, zone_type)
        if liquidation.get("phase") == "LIQUIDATION":
            phases_detected.append(liquidation)
        
        retest = self.detect_retest(df, zone_level, zone_type)
        if retest.get("phase") == "RETEST":
            phases_detected.append(retest)
        
        confirmation = self.detect_confirmation(df, zone_level, zone_type, direction)
        if confirmation.get("phase") == "CONFIRMATION":
            phases_detected.append(confirmation)
        
        # Determinar recomendación
        recommendation = self._get_recommendation(phases_detected)
        
        return {
            "phases_detected": phases_detected,
            "phase_count": len(phases_detected),
            "recommendation": recommendation,
            "can_enter": recommendation == "ENTER_NOW",
            "wait_message": self._get_wait_message(phases_detected)
        }
    
    def _get_recommendation(self, phases: List[Dict]) -> str:
        """Retorna recomendación basada en fases detectadas."""
        phase_names = [p.get("phase") for p in phases]
        
        # Caso ideal: Liquidación + Retest + Confirmación → ENTER
        if ("LIQUIDATION" in phase_names and 
            "RETEST" in phase_names and 
            "CONFIRMATION" in phase_names):
            return "ENTER_NOW"
        
        # Caso 2: Liquidación + Confirmación (sin retest claro) → ENTER con caution
        if ("LIQUIDATION" in phase_names and 
            "CONFIRMATION" in phase_names):
            return "ENTER_CAUTION"
        
        # Caso 3: Solo Liquidación + Retest (falta confirmación) → WAIT
        if ("LIQUIDATION" in phase_names and 
            "RETEST" in phase_names):
            return "WAIT_CONFIRMATION"
        
        # Caso 4: Solo Liquidación → WAIT para retest
        if "LIQUIDATION" in phase_names:
            return "WAIT_RETEST"
        
        # Caso 5: Solo Confirmación (sin liquidación previa) → CAUTION
        if "CONFIRMATION" in phase_names:
            return "ENTER_CAUTION"
        
        return "WAIT_LIQUIDATION"
    
    def _get_wait_message(self, phases: List[Dict]) -> str:
        """Retorna mensaje de espera explicando qué falta."""
        if not phases:
            return "Esperando liquidación en la zona..."
        
        phase_names = [p.get("phase") for p in phases]
        
        if "LIQUIDATION" not in phase_names:
            return "Fase 1/3: Esperando LIQUIDACIÓN (rechazo violento en zona)..."
        elif "RETEST" not in phase_names:
            return "Fase 2/3: Esperando RETEST (precio vuelve a zona más débilmente)..."
        elif "CONFIRMATION" not in phase_names:
            return "Fase 3/3: Esperando CONFIRMACIÓN (precio cierre fuera con momentum)..."
        
        return "Esperando próxima fase..."


# ════════════════════════════════════════════════════════════════════════════
# Factory function
# ════════════════════════════════════════════════════════════════════════════

def get_three_phase_confirmation():
    """Retorna instancia del sistema de confirmación en 3 fases."""
    return ThreePhaseConfirmation()
