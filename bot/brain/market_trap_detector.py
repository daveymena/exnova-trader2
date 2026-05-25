"""
Market Trap Detector v1.0
Detecta "trampas de mercado":
- Fake breakouts (rompen zona pero luego reversan)
- Pump & dump (impulso falso seguido de caída fuerte)
- Dump & recovery (caída falsa seguida de recuperación)
- Consolidación engañosa (lateral antes de movimiento fuerte en opuesto)
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple


class MarketTrapDetector:
    """
    Analiza contexto de la operación para evitar trampas.
    """
    
    def __init__(self):
        self.trap_types = [
            "FAKE_BREAKOUT",      # Rompe pero revierte
            "PUMP_AND_DUMP",      # Sube fuerte + cae fuerte
            "DUMP_AND_RECOVERY",  # Cae + sube (fake venta)
            "CONSOLIDATION_BEFORE_REVERSAL",  # Lateral → movimiento opuesto
            "DIVERGENCE_RSI",     # Precio sube pero RSI baja (debilidad)
        ]
    
    # ════════════════════════════════════════════════════════════════════════════
    # 1. FAKE BREAKOUT - Rompe zona pero luego revierte
    # ════════════════════════════════════════════════════════════════════════════
    
    def detect_fake_breakout(self, 
                            df: pd.DataFrame,
                            zone_level: float,
                            zone_type: str,
                            direction: str,
                            lookback: int = 5) -> Dict:
        """
        Detecta si el breakout es falso:
        - CALL en resistencia: precio sube 0.1% pero luego cae 0.3% (fake)
        - PUT en soporte: precio baja 0.1% pero luego sube 0.3% (fake)
        """
        
        if len(df) < lookback + 2:
            return {"is_trap": False, "reason": "datos insuficientes"}
        
        # Últimas velas después del breakout
        recent = df.iloc[-lookback:].copy()
        signal_candle = df.iloc[-2]  # vela que detectó breakout
        current = df.iloc[-1]
        
        signal_close = float(signal_candle["close"])
        signal_high = float(signal_candle["high"])
        signal_low = float(signal_candle["low"])
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # CALL en resistencia: precio debe subir Y mantener arriba
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if direction == "CALL" and zone_type == "resistance":
            # Signal rompió hacia arriba
            if signal_high > zone_level * 1.001:  # Rompió >0.1%
                # Pero ahora está retrocediendo
                max_high_after = recent["high"].max()
                min_low_after = recent["low"].min()
                current_price = float(current["close"])
                
                # Si cae más de 0.3% desde el máximo, es fake
                pullback = (max_high_after - min_low_after) / zone_level
                if pullback > 0.003:  # >0.3% de pullback
                    return {
                        "is_trap": True,
                        "trap_type": "FAKE_BREAKOUT",
                        "reason": f"CALL en resistencia: rompe {signal_high:.5f} pero retrocede {pullback*100:.2f}%",
                        "breakout_level": signal_high,
                        "current_level": current_price,
                        "pullback_pct": pullback * 100
                    }
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # PUT en soporte: precio debe bajar Y mantener abajo
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if direction == "PUT" and zone_type == "support":
            # Signal rompió hacia abajo
            if signal_low < zone_level * 0.999:  # Rompió >0.1%
                # Pero ahora está rebotando
                max_high_after = recent["high"].max()
                min_low_after = recent["low"].min()
                current_price = float(current["close"])
                
                # Si sube más de 0.3% desde el mínimo, es fake
                bounce = (max_high_after - min_low_after) / zone_level
                if bounce > 0.003:  # >0.3% de bounce
                    return {
                        "is_trap": True,
                        "trap_type": "FAKE_BREAKOUT",
                        "reason": f"PUT en soporte: rompe {signal_low:.5f} pero rebota {bounce*100:.2f}%",
                        "breakout_level": signal_low,
                        "current_level": current_price,
                        "bounce_pct": bounce * 100
                    }
        
        return {"is_trap": False, "reason": "Breakout parece auténtico"}
    
    # ════════════════════════════════════════════════════════════════════════════
    # 2. PUMP & DUMP - Impulso fuerte seguido de caída fuerte
    # ════════════════════════════════════════════════════════════════════════════
    
    def detect_pump_and_dump(self,
                            df: pd.DataFrame,
                            direction: str,
                            lookback: int = 8) -> Dict:
        """
        Si CALL: precio sube 0.5% rápido, pero luego cae 0.8%+ (pump & dump)
        Si PUT: precio baja 0.5% rápido, pero luego sube 0.8%+ (dump & recovery)
        """
        
        if len(df) < lookback + 2:
            return {"is_trap": False, "reason": "datos insuficientes"}
        
        recent = df.iloc[-lookback:].copy()
        first_candle = df.iloc[-(lookback+1)]
        current = df.iloc[-1]
        
        first_price = float(first_candle["close"])
        max_price = float(recent["high"].max())
        min_price = float(recent["low"].min())
        current_price = float(current["close"])
        
        if direction == "CALL":
            # Movimiento alcista inicial
            up_move = (max_price - first_price) / first_price
            
            # Pero luego cae fuerte
            down_from_peak = (max_price - current_price) / max_price
            
            # Trap si: sube 0.5% pero cae >0.6% desde el pico
            if up_move > 0.005 and down_from_peak > 0.006:
                return {
                    "is_trap": True,
                    "trap_type": "PUMP_AND_DUMP",
                    "reason": f"CALL: sube {up_move*100:.2f}% pero cae {down_from_peak*100:.2f}% desde pico",
                    "up_move_pct": up_move * 100,
                    "down_move_pct": down_from_peak * 100,
                    "peak_price": max_price,
                    "current_price": current_price
                }
        
        elif direction == "PUT":
            # Movimiento bajista inicial
            down_move = (first_price - min_price) / first_price
            
            # Pero luego sube fuerte
            up_from_bottom = (current_price - min_price) / min_price
            
            # Trap si: baja 0.5% pero sube >0.6% desde el mínimo
            if down_move > 0.005 and up_from_bottom > 0.006:
                return {
                    "is_trap": True,
                    "trap_type": "DUMP_AND_RECOVERY",
                    "reason": f"PUT: baja {down_move*100:.2f}% pero sube {up_from_bottom*100:.2f}% desde mínimo",
                    "down_move_pct": down_move * 100,
                    "up_move_pct": up_from_bottom * 100,
                    "bottom_price": min_price,
                    "current_price": current_price
                }
        
        return {"is_trap": False, "reason": "Sin pump & dump detectado"}
    
    # ════════════════════════════════════════════════════════════════════════════
    # 3. CONSOLIDATION BEFORE REVERSAL
    # ════════════════════════════════════════════════════════════════════════════
    
    def detect_consolidation_reversal(self,
                                     df: pd.DataFrame,
                                     direction: str,
                                     lookback: int = 10) -> Dict:
        """
        Detecta si hay consolidación (lateral) seguida de movimiento OPUESTO:
        - CALL + consolidación → luego cae fuerte (reversal bajista)
        - PUT + consolidación → luego sube fuerte (reversal alcista)
        """
        
        if len(df) < lookback + 3:
            return {"is_trap": False, "reason": "datos insuficientes"}
        
        recent = df.iloc[-lookback:].copy()
        
        # Medir volatilidad de consolidación
        range_size = (recent["high"].max() - recent["low"].min()) / df.iloc[-2]["close"]
        
        # Consolidación es cuando rango < 0.3%
        is_consolidating = range_size < 0.003
        
        if not is_consolidating:
            return {"is_trap": False, "reason": "No hay consolidación"}
        
        # Ahora verifica si la vela actual (formándose) mueve en DIRECCIÓN OPUESTA
        current = df.iloc[-1]
        current_open = float(current["open"])
        current_low = float(current["low"])
        current_high = float(current["high"])
        
        if direction == "CALL":
            # Esperamos que siga subiendo, pero si baja es reversal
            if current_low < current_open * 0.998:  # Bajó >0.2%
                return {
                    "is_trap": True,
                    "trap_type": "CONSOLIDATION_BEFORE_REVERSAL",
                    "reason": f"CALL: consolidación lateral pero vela actual cae {(current_open - current_low)/current_open*100:.2f}%",
                    "consolidation_size_pct": range_size * 100,
                    "reversal_direction": "DOWN"
                }
        
        elif direction == "PUT":
            # Esperamos que siga bajando, pero si sube es reversal
            if current_high > current_open * 1.002:  # Subió >0.2%
                return {
                    "is_trap": True,
                    "trap_type": "CONSOLIDATION_BEFORE_REVERSAL",
                    "reason": f"PUT: consolidación lateral pero vela actual sube {(current_high - current_open)/current_open*100:.2f}%",
                    "consolidation_size_pct": range_size * 100,
                    "reversal_direction": "UP"
                }
        
        return {"is_trap": False, "reason": "Consolidación sin reversal visible"}
    
    # ════════════════════════════════════════════════════════════════════════════
    # 4. ANÁLISIS INTEGRAL - Ejecutar todos los checks
    # ════════════════════════════════════════════════════════════════════════════
    
    def analyze_all_traps(self,
                         df: pd.DataFrame,
                         zone_level: float,
                         zone_type: str,
                         direction: str,
                         rsi: Optional[float] = None) -> Dict:
        """
        Ejecuta todos los checks de trampa y retorna el resultado consolidado.
        """
        
        traps_detected = []
        risk_score = 0.0  # 0 = seguro, 1.0 = muy peligroso
        
        # Check 1: Fake Breakout
        fake_breakout = self.detect_fake_breakout(df, zone_level, zone_type, direction)
        if fake_breakout.get("is_trap"):
            traps_detected.append(fake_breakout)
            risk_score += 0.4
        
        # Check 2: Pump & Dump
        pump_dump = self.detect_pump_and_dump(df, direction)
        if pump_dump.get("is_trap"):
            traps_detected.append(pump_dump)
            risk_score += 0.3
        
        # Check 3: Consolidation Reversal
        consol_reversal = self.detect_consolidation_reversal(df, direction)
        if consol_reversal.get("is_trap"):
            traps_detected.append(consol_reversal)
            risk_score += 0.3
        
        # Check 4: RSI Divergence (opcional)
        if rsi is not None:
            rsi_div = self.detect_rsi_divergence(df, direction, rsi)
            if rsi_div.get("is_trap"):
                traps_detected.append(rsi_div)
                risk_score += 0.2
        
        risk_score = min(1.0, risk_score)  # Cap at 1.0
        
        return {
            "is_trap": len(traps_detected) > 0,
            "trap_count": len(traps_detected),
            "risk_score": risk_score,
            "traps": traps_detected,
            "recommendation": self._get_recommendation(len(traps_detected), risk_score)
        }
    
    # ════════════════════════════════════════════════════════════════════════════
    # 5. RSI DIVERGENCE - Debilidad en el movimiento
    # ════════════════════════════════════════════════════════════════════════════
    
    def detect_rsi_divergence(self,
                             df: pd.DataFrame,
                             direction: str,
                             current_rsi: float,
                             lookback: int = 5) -> Dict:
        """
        Divergencia: precio sube pero RSI baja (debilidad alcista)
        o precio baja pero RSI sube (debilidad bajista)
        """
        
        if len(df) < lookback + 1:
            return {"is_trap": False, "reason": "datos insuficientes"}
        
        # En contexto real, necesitarías calcular RSI histórico
        # Aquí es simplificado para demostración
        
        recent = df.iloc[-lookback:].copy()
        first_close = float(recent.iloc[0]["close"])
        last_close = float(recent.iloc[-1]["close"])
        
        price_up = last_close > first_close
        
        # Si dirección es CALL y RSI está bajo pero precio subió = divergencia débil
        if direction == "CALL" and current_rsi < 40 and price_up:
            return {
                "is_trap": True,
                "trap_type": "DIVERGENCE_RSI",
                "reason": f"CALL: precio sube pero RSI bajo ({current_rsi:.0f}) = debilidad",
                "rsi": current_rsi,
                "price_direction": "UP"
            }
        
        # Si dirección es PUT y RSI está alto pero precio bajó = divergencia débil
        if direction == "PUT" and current_rsi > 60 and not price_up:
            return {
                "is_trap": True,
                "trap_type": "DIVERGENCE_RSI",
                "reason": f"PUT: precio baja pero RSI alto ({current_rsi:.0f}) = debilidad",
                "rsi": current_rsi,
                "price_direction": "DOWN"
            }
        
        return {"is_trap": False, "reason": "RSI alineado con precio"}
    
    def _get_recommendation(self, trap_count: int, risk_score: float) -> str:
        """Retorna recomendación basada en riesgo."""
        if trap_count == 0:
            return "ENTER_SAFE - Sin trampas detectadas"
        elif trap_count == 1 and risk_score < 0.5:
            return "ENTER_CAUTION - 1 trampa menor detectada"
        elif trap_count >= 2 or risk_score >= 0.7:
            return "SKIP_TRADE - Múltiples trampas o riesgo alto"
        else:
            return "ENTER_CAREFUL - Riesgo moderado"


# ════════════════════════════════════════════════════════════════════════════
# Factory function
# ════════════════════════════════════════════════════════════════════════════

def get_trap_detector():
    """Retorna instancia del detector de trampas."""
    return MarketTrapDetector()
