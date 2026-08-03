"""
PCR Validator Gates - Sistema de "Porteros" para validación exhaustiva
Múltiples filtros que actúan como guardianes antes de ejecutar trades
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple


class PCRValidatorGates:
    """
    Sistema de validación con múltiples "porteros" (gatekeepers)
    Cada portero valida un aspecto diferente de la señal
    """

    def __init__(self):
        """Inicializar porteros"""
        self.gates = {
            'confidence': self._gate_confidence,
            'volatility': self._gate_volatility,
            'trend_strength': self._gate_trend_strength,
            'zone_quality': self._gate_zone_quality,
            'price_action': self._gate_price_action,
            'time_filter': self._gate_time_filter,
            'correlation': self._gate_correlation,
            'volume': self._gate_volume
        }
        self.open_gates = []
        self.closed_gates = []

    def validate_signal(self, analysis: Dict, df: pd.DataFrame, strict=False) -> Tuple[bool, Dict]:
        """
        Valida señal a través de todos los porteros

        Args:
            analysis: Análisis de estrategia (output de PCR)
            df: DataFrame histórico
            strict: Si True, requiere 100% de porteros abiertos

        Returns:
            (bool: señal_válida, dict: detalles_validación)
        """
        self.open_gates = []
        self.closed_gates = []

        if not analysis or not analysis.get('signal'):
            return False, {
                'valid': False,
                'reason': 'Sin señal',
                'gates': {}
            }

        validation = {}
        gates_passed = 0
        total_gates = len(self.gates)

        for gate_name, gate_func in self.gates.items():
            passed, reason = gate_func(analysis, df)
            validation[gate_name] = {
                'passed': passed,
                'reason': reason
            }

            if passed:
                self.open_gates.append(gate_name)
                gates_passed += 1
            else:
                self.closed_gates.append(gate_name)

        # Determinar si es válida
        if strict:
            # Modo estricto: TODOS los porteros deben abrir
            valid = gates_passed == total_gates
        else:
            # Modo normal: 70%+ de porteros abiertos
            valid = (gates_passed / total_gates) >= 0.70

        return valid, {
            'valid': valid,
            'gates_passed': gates_passed,
            'total_gates': total_gates,
            'percentage': round((gates_passed / total_gates) * 100, 1),
            'details': validation,
            'open': self.open_gates,
            'closed': self.closed_gates
        }

    def _gate_confidence(self, analysis: Dict, df: pd.DataFrame) -> Tuple[bool, str]:
        """Portero 1: Confianza mínima"""
        confidence = analysis.get('confidence', 0)
        min_confidence = 60

        if confidence >= min_confidence:
            return True, f"Confianza {confidence}% >= {min_confidence}%"
        return False, f"Confianza insuficiente: {confidence}% < {min_confidence}%"

    def _gate_volatility(self, analysis: Dict, df: pd.DataFrame) -> Tuple[bool, str]:
        """Portero 2: Volatilidad dentro de rango (no muy tranquilo, no muy volátil)"""
        if df.empty or len(df) < 20:
            return False, "Datos insuficientes"

        recent = df.tail(20).copy()
        returns = recent['close'].pct_change().dropna()

        if len(returns) == 0:
            return False, "No hay datos de retornos"

        volatility = returns.std()
        min_vol = 0.0005  # 0.05%
        max_vol = 0.02    # 2%

        if min_vol <= volatility <= max_vol:
            return True, f"Volatilidad óptima: {volatility:.4f}"
        elif volatility > max_vol:
            return False, f"Volatilidad muy alta: {volatility:.4f} > {max_vol}"
        else:
            return False, f"Volatilidad muy baja: {volatility:.4f} < {min_vol}"

    def _gate_trend_strength(self, analysis: Dict, df: pd.DataFrame) -> Tuple[bool, str]:
        """Portero 3: Fortaleza de tendencia (debe haber tendencia clara)"""
        if 'ema20' not in analysis or 'close' not in analysis:
            return False, "Falta data de EMA20"

        current_price = analysis['close']
        ema20 = analysis['ema20']

        # Distancia del precio respecto a EMA
        distance_pct = abs(current_price - ema20) / ema20

        signal = analysis.get('signal')

        # CALL: precio debe estar ARRIBA de EMA (tendencia alcista fuerte)
        if signal == 'CALL':
            if current_price > ema20 and distance_pct >= 0.003:  # 0.3%
                return True, f"Tendencia alcista fuerte: {distance_pct:.3%} > EMA"
            return False, f"Tendencia alcista débil o inexistente"

        # PUT: precio debe estar ABAJO de EMA (tendencia bajista fuerte)
        elif signal == 'PUT':
            if current_price < ema20 and distance_pct >= 0.003:
                return True, f"Tendencia bajista fuerte: {distance_pct:.3%} < EMA"
            return False, f"Tendencia bajista débil o inexistente"

        return False, "Señal sin definir"

    def _gate_zone_quality(self, analysis: Dict, df: pd.DataFrame) -> Tuple[bool, str]:
        """Portero 4: Calidad de zonas (deben tener mínimo 2+ toques)"""
        signal = analysis.get('signal')
        supply_zones = analysis.get('supply_zones', [])
        demand_zones = analysis.get('demand_zones', [])

        if signal == 'CALL':
            # Para CALL necesitamos demand zones fuertes
            if not demand_zones:
                return False, "Sin zonas demand detectadas"

            best_demand = demand_zones[0]
            touches = best_demand.get('touches', 0)
            strength = best_demand.get('strength', 'weak')

            if touches >= 2 and strength == 'strong':
                return True, f"Demand zone fuerte: {touches} toques"
            elif touches >= 2:
                return True, f"Demand zone válida: {touches} toques"
            return False, f"Demand zone débil: {touches} toques"

        elif signal == 'PUT':
            # Para PUT necesitamos supply zones fuertes
            if not supply_zones:
                return False, "Sin zonas supply detectadas"

            best_supply = supply_zones[0]
            touches = best_supply.get('touches', 0)
            strength = best_supply.get('strength', 'weak')

            if touches >= 2 and strength == 'strong':
                return True, f"Supply zone fuerte: {touches} toques"
            elif touches >= 2:
                return True, f"Supply zone válida: {touches} toques"
            return False, f"Supply zone débil: {touches} toques"

        return False, "Señal sin definir"

    def _gate_price_action(self, analysis: Dict, df: pd.DataFrame) -> Tuple[bool, str]:
        """Portero 5: Acción del precio (validar patrón de velas recientes)"""
        if df.empty or len(df) < 5:
            return False, "Datos insuficientes"

        recent = df.tail(5).copy()
        signal = analysis.get('signal')

        # Para CALL: últimas velas deben mostrar fuerza alcista (closes ascendentes)
        if signal == 'CALL':
            closes = recent['close'].values
            higher_closes = sum(1 for i in range(len(closes)-1) if closes[i+1] > closes[i])

            if higher_closes >= 2:  # Al menos 2 closes en ascenso
                return True, f"Acción bullish confirmada: {higher_closes}/4 closes arriba"
            return False, f"Acción bullish débil: {higher_closes}/4 closes arriba"

        # Para PUT: últimas velas deben mostrar fuerza bajista (closes descendentes)
        elif signal == 'PUT':
            closes = recent['close'].values
            lower_closes = sum(1 for i in range(len(closes)-1) if closes[i+1] < closes[i])

            if lower_closes >= 2:  # Al menos 2 closes en descenso
                return True, f"Acción bearish confirmada: {lower_closes}/4 closes abajo"
            return False, f"Acción bearish débil: {lower_closes}/4 closes abajo"

        return False, "Señal sin definir"

    def _gate_time_filter(self, analysis: Dict, df: pd.DataFrame) -> Tuple[bool, str]:
        """Portero 6: Filtro temporal (no tradear durante mercados cerrados)"""
        if 'timestamp' not in df.columns:
            return True, "Sin datos de timestamp (asumiendo válido)"

        try:
            last_time = pd.to_datetime(df.iloc[-1]['timestamp'])
            current_hour = last_time.hour

            # Evitar últimas 2 horas de sesión (riesgo de gaps)
            if 15 <= current_hour < 23:  # Después de 3 PM
                return False, f"Hora peligrosa: {current_hour}h (cerca de cierre)"

            # Evitar madrugada (12 AM - 6 AM)
            if 0 <= current_hour < 6:
                return False, f"Madrugada: {current_hour}h (sin liquidez)"

            return True, f"Hora válida: {current_hour}h"
        except:
            return True, "No se pudo verificar hora (asumiendo válido)"

    def _gate_correlation(self, analysis: Dict, df: pd.DataFrame) -> Tuple[bool, str]:
        """Portero 7: Correlación con tendencia (validar consistencia)"""
        if df.empty or len(df) < 30:
            return True, "Datos insuficientes para correlación"

        # Calcular cambios de precio en últimas 30 velas
        recent = df.tail(30).copy()
        returns = recent['close'].pct_change().dropna()

        if len(returns) == 0:
            return True, "Sin datos de retornos"

        # Calcular tendencia: si el precio sube más que baja
        ups = (returns > 0).sum()
        downs = (returns < 0).sum()

        signal = analysis.get('signal')

        if signal == 'CALL':
            if ups > downs:
                ratio = ups / (ups + downs)
                return True, f"Correlación alcista: {ratio:.1%} ups"
            return False, f"Correlación bajista: solo {ups}/{ups+downs} ups"

        elif signal == 'PUT':
            if downs > ups:
                ratio = downs / (ups + downs)
                return True, f"Correlación bajista: {ratio:.1%} downs"
            return False, f"Correlación alcista: solo {downs}/{ups+downs} downs"

        return False, "Señal sin definir"

    def _gate_volume(self, analysis: Dict, df: pd.DataFrame) -> Tuple[bool, str]:
        """Portero 8: Volumen (debe haber actividad)"""
        if 'volume' not in df.columns:
            return True, "Sin datos de volumen"

        if df.empty or len(df) < 10:
            return True, "Datos insuficientes"

        recent_volume = df.tail(10)['volume'].mean()
        current_volume = df.iloc[-1]['volume']

        if current_volume > 0:
            ratio = current_volume / recent_volume if recent_volume > 0 else 1

            if ratio >= 0.7:  # Al menos 70% del volumen promedio
                return True, f"Volumen adecuado: {ratio:.1%} del promedio"
            return False, f"Volumen bajo: {ratio:.1%} del promedio"

        return False, "Volumen cero"

    def get_gates_summary(self) -> Dict:
        """Retorna resumen de porteros abiertos/cerrados"""
        return {
            'open': self.open_gates,
            'closed': self.closed_gates,
            'open_count': len(self.open_gates),
            'closed_count': len(self.closed_gates),
            'total': len(self.gates),
            'percentage_open': round((len(self.open_gates) / len(self.gates)) * 100, 1)
        }

    def print_gates_report(self, validation: Dict):
        """Imprime reporte visual de porteros"""
        print(f"\n{'VALIDACIÓN DE PORTEROS':^60}")
        print(f"{'='*60}")

        if not validation.get('valid'):
            print(f"❌ RECHAZADA: {validation.get('reason', 'Señal rechazada')}")
            return

        gates_passed = validation['gates_passed']
        total = validation['total_gates']
        percentage = validation['percentage']

        print(f"✅ APROBADA: {gates_passed}/{total} porteros ({percentage}%)")
        print(f"\n{'Porteros Abiertos':<30} {'Porteros Cerrados':<30}")
        print(f"{'-'*60}")

        for i in range(max(len(validation['open']), len(validation['closed']))):
            open_gate = validation['open'][i] if i < len(validation['open']) else ''
            closed_gate = validation['closed'][i] if i < len(validation['closed']) else ''

            open_str = f"✓ {open_gate}" if open_gate else ''
            closed_str = f"✗ {closed_gate}" if closed_gate else ''

            print(f"{open_str:<30} {closed_str:<30}")

        print(f"\n{'DETALLES':<60}")
        print(f"{'-'*60}")

        for gate, detail in validation['details'].items():
            status = "✓" if detail['passed'] else "✗"
            reason = detail['reason']
            print(f"{status} {gate:<25} {reason}")
