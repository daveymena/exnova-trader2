"""
PCR Self-Learning Engine - Motor de Aprendizaje Automático
El bot se corrige a sí mismo, aprende de errores y mejora continuamente
SIN intervención humana
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import json
from dataclasses import dataclass, asdict


@dataclass
class TradeAnalysis:
    """Análisis detallado de un trade para aprendizaje"""
    trade_id: str
    asset: str
    signal: str
    confidence: float
    entry_price: float
    exit_price: float
    result: str  # WIN/LOSS
    pnl: float
    timestamp: datetime
    strategy_used: str
    parameters: Dict
    reason_for_loss: Optional[str] = None  # Si fue loss, por qué?
    improvement: Optional[str] = None  # Cómo mejorar?


class PCRSelfLearningEngine:
    """
    Motor de aprendizaje automático que:
    1. Analiza cada trade para aprender
    2. Detecta patrones de pérdidas
    3. Ajusta parámetros automáticamente
    4. Prueba mejoras en tiempo real
    5. Mantiene historial de optimizaciones
    """

    def __init__(self, learning_window: int = 100, min_trades_for_pattern: int = 20):
        """
        Args:
            learning_window: Últimos N trades para análisis
            min_trades_for_pattern: Mínimo trades para detectar patrón
        """
        self.learning_window = learning_window
        self.min_trades_for_pattern = min_trades_for_pattern

        # Historial de aprendizaje
        self.trade_history: List[TradeAnalysis] = []
        self.pattern_detections: List[Dict] = []
        self.parameter_adjustments: List[Dict] = []
        self.performance_improvements: List[Dict] = []

        # Parámetros dinámicos que se ajustan automáticamente
        self.dynamic_params = {
            'confidence_threshold': 60,  # Aumenta si hay muchos falsos positivos
            'zone_tolerance': 0.002,     # Se ajusta según precisión
            'ema_period': 20,            # Se prueba con diferentes valores
            'volatility_filter_min': 0.0005,
            'volatility_filter_max': 0.02,
            'strict_mode': False         # Se activa si WR cae
        }

        # Versiones de parámetros siendo testeadas
        self.ab_test_versions: Dict[str, Dict] = {
            'version_a': self.dynamic_params.copy(),  # Original
            'version_b': self.dynamic_params.copy(),  # Test 1
            'version_c': self.dynamic_params.copy(),  # Test 2
        }

    def analyze_trade_for_learning(self, trade: Dict) -> TradeAnalysis:
        """
        Analiza un trade completo para extraer lecciones

        Args:
            trade: Trade ejecutado con todos sus datos

        Returns:
            TradeAnalysis con insights de aprendizaje
        """
        analysis = TradeAnalysis(
            trade_id=trade.get('id'),
            asset=trade.get('asset'),
            signal=trade.get('signal'),
            confidence=trade.get('confidence', 0),
            entry_price=trade.get('entry_price'),
            exit_price=trade.get('exit_price'),
            result=trade.get('result'),
            pnl=trade.get('pnl'),
            timestamp=trade.get('timestamp', datetime.now()),
            strategy_used=trade.get('strategy'),
            parameters=trade.get('parameters', {})
        )

        # Si fue pérdida, diagnosticar por qué
        if trade['result'] == 'LOSS':
            analysis.reason_for_loss = self._diagnose_loss(trade)
            analysis.improvement = self._suggest_improvement(trade, analysis.reason_for_loss)

        # Guardar en historial
        self.trade_history.append(analysis)

        return analysis

    def _diagnose_loss(self, trade: Dict) -> str:
        """
        Diagnostica por qué falló un trade

        Causas posibles:
        1. Confianza muy baja (falso positivo)
        2. Zona débil (poco validada)
        3. Volatilidad extrema
        4. Movimiento muy pequeño (no alcanzó target)
        5. Cambio de tendencia repentino
        """
        confidence = trade.get('confidence', 0)
        entry = trade.get('entry_price', 0)
        exit_p = trade.get('exit_price', 0)
        signal = trade.get('signal')

        movement = abs(exit_p - entry) / entry * 100

        # Diagnóstico basado en características
        if confidence < 55:
            return "LOW_CONFIDENCE_SIGNAL"
        elif movement < 0.05:
            return "INSUFFICIENT_MOVEMENT"
        elif confidence > 75:
            return "UNEXPECTED_REVERSAL"
        elif trade.get('zone_touches', 0) < 2:
            return "WEAK_ZONE_VALIDATION"
        elif trade.get('volatility', 0) > 0.02:
            return "EXTREME_VOLATILITY"
        elif trade.get('time_to_close', 0) > 240:
            return "TOO_LONG_EXPIRY"
        else:
            return "RANDOM_MARKET_NOISE"

    def _suggest_improvement(self, trade: Dict, diagnosis: str) -> str:
        """
        Sugiere mejora basada en diagnóstico
        """
        improvements = {
            'LOW_CONFIDENCE_SIGNAL': 'Aumentar confidence_threshold de 60 a 65',
            'INSUFFICIENT_MOVEMENT': 'Reducir expiry time de 180s a 120s',
            'UNEXPECTED_REVERSAL': 'Usar validación estricta (strict_mode=True)',
            'WEAK_ZONE_VALIDATION': 'Aumentar min_touches de 2 a 3',
            'EXTREME_VOLATILITY': 'Reducir volatility_filter_max de 0.02 a 0.015',
            'TOO_LONG_EXPIRY': 'Cambiar expiry a 120-180s máximo',
            'RANDOM_MARKET_NOISE': 'Usar PCRHybrid en lugar de PCRSimple'
        }
        return improvements.get(diagnosis, 'Revisar contexto de mercado')

    def detect_loss_patterns(self) -> List[Dict]:
        """
        Detecta patrones en las pérdidas para identificar problemas sistemáticos

        Retorna: Lista de patrones detectados
        """
        patterns = []

        if len(self.trade_history) < self.min_trades_for_pattern:
            return patterns

        # Analizar últimas N pérdidas
        recent_trades = self.trade_history[-self.learning_window:]
        losses = [t for t in recent_trades if t.result == 'LOSS']

        if len(losses) < 3:
            return patterns

        # Patrón 1: Pérdidas consecutivas
        loss_streak = 0
        max_streak = 0
        for trade in recent_trades:
            if trade.result == 'LOSS':
                loss_streak += 1
                max_streak = max(max_streak, loss_streak)
            else:
                loss_streak = 0

        if max_streak >= 4:
            patterns.append({
                'type': 'CONSECUTIVE_LOSSES',
                'severity': 'HIGH' if max_streak >= 6 else 'MEDIUM',
                'count': max_streak,
                'action': 'Activar strict_mode o cambiar estrategia'
            })

        # Patrón 2: Pérdidas en activo específico
        losses_by_asset = {}
        for trade in losses:
            asset = trade.asset
            losses_by_asset[asset] = losses_by_asset.get(asset, 0) + 1

        for asset, count in losses_by_asset.items():
            if count >= 3:
                patterns.append({
                    'type': 'ASSET_SPECIFIC_LOSSES',
                    'asset': asset,
                    'count': count,
                    'action': f'Excluir {asset} temporalmente o revisar'
                })

        # Patrón 3: Pérdidas por rango de confianza
        losses_by_confidence = {
            'very_low': len([t for t in losses if t.confidence < 50]),
            'low': len([t for t in losses if 50 <= t.confidence < 60]),
            'medium': len([t for t in losses if 60 <= t.confidence < 70]),
            'high': len([t for t in losses if t.confidence >= 70])
        }

        if losses_by_confidence['very_low'] >= 2:
            patterns.append({
                'type': 'LOW_CONFIDENCE_LOSSES',
                'severity': 'HIGH',
                'count': losses_by_confidence['very_low'],
                'action': 'Aumentar confidence_threshold a 65+'
            })

        # Patrón 4: Pérdidas en horario específico
        losses_by_hour = {}
        for trade in losses:
            hour = trade.timestamp.hour
            losses_by_hour[hour] = losses_by_hour.get(hour, 0) + 1

        for hour, count in losses_by_hour.items():
            if count >= 3:
                patterns.append({
                    'type': 'HOURLY_PATTERN',
                    'hour': hour,
                    'count': count,
                    'action': f'Evitar trading en hora {hour} (riesgo alto)'
                })

        return patterns

    def auto_adjust_parameters(self) -> Dict:
        """
        Ajusta parámetros automáticamente basado en patrones detectados

        Retorna: Nuevos parámetros aplicados
        """
        patterns = self.detect_loss_patterns()

        if not patterns:
            return {'adjusted': False, 'reason': 'Sin patrones detectados'}

        adjustments = {
            'adjusted': True,
            'changes': [],
            'patterns': patterns,
            'timestamp': datetime.now().isoformat()
        }

        for pattern in patterns:
            ptype = pattern['type']

            # Ajuste 1: Pérdidas consecutivas
            if ptype == 'CONSECUTIVE_LOSSES':
                old_threshold = self.dynamic_params['confidence_threshold']
                self.dynamic_params['confidence_threshold'] = min(100, old_threshold + 5)
                adjustments['changes'].append({
                    'parameter': 'confidence_threshold',
                    'from': old_threshold,
                    'to': self.dynamic_params['confidence_threshold'],
                    'reason': f"{pattern['count']} pérdidas consecutivas detectadas"
                })

                # Activar modo estricto
                if pattern['severity'] == 'HIGH':
                    self.dynamic_params['strict_mode'] = True
                    adjustments['changes'].append({
                        'parameter': 'strict_mode',
                        'from': False,
                        'to': True,
                        'reason': 'Rachas largas de pérdidas - activar validación estricta'
                    })

            # Ajuste 2: Pérdidas por asset
            elif ptype == 'ASSET_SPECIFIC_LOSSES':
                adjustments['changes'].append({
                    'parameter': 'blacklist',
                    'asset': pattern['asset'],
                    'action': 'temporal_exclude',
                    'reason': f"{pattern['count']} pérdidas en {pattern['asset']}"
                })

            # Ajuste 3: Confianza muy baja
            elif ptype == 'LOW_CONFIDENCE_LOSSES':
                old_threshold = self.dynamic_params['confidence_threshold']
                self.dynamic_params['confidence_threshold'] = 65
                adjustments['changes'].append({
                    'parameter': 'confidence_threshold',
                    'from': old_threshold,
                    'to': 65,
                    'reason': 'Señales con baja confianza generan pérdidas'
                })

            # Ajuste 4: Patrón por hora
            elif ptype == 'HOURLY_PATTERN':
                adjustments['changes'].append({
                    'parameter': 'time_filter',
                    'exclude_hour': pattern['hour'],
                    'reason': f"Alto riesgo en hora {pattern['hour']}"
                })

        # Guardar ajuste
        self.parameter_adjustments.append(adjustments)

        return adjustments

    def ab_test_parameters(self) -> Dict:
        """
        Ejecuta A/B testing de parámetros automáticamente

        Versión A: Parámetros actuales (control)
        Versión B: Parámetros ligeramente más agresivos
        Versión C: Parámetros más conservadores

        Retorna: Versión ganadora después de N trades
        """
        recent_trades = self.trade_history[-50:]

        if len(recent_trades) < 50:
            return {'status': 'NOT_ENOUGH_DATA', 'trades': len(recent_trades)}

        # Simular desempeño de cada versión
        results = {}
        for version_name, params in self.ab_test_versions.items():
            wins = sum(1 for t in recent_trades if t.result == 'WIN')
            wr = (wins / len(recent_trades) * 100) if recent_trades else 0

            results[version_name] = {
                'parameters': params,
                'wr': wr,
                'trades': len(recent_trades),
                'confidence': 'HIGH' if len(recent_trades) >= 50 else 'LOW'
            }

        # Elegir ganador
        winner = max(results.items(), key=lambda x: x[1]['wr'])

        ab_test_result = {
            'timestamp': datetime.now().isoformat(),
            'results': results,
            'winner': winner[0],
            'winner_wr': winner[1]['wr'],
            'action': f"Aplicar parámetros de {winner[0]}"
        }

        # Aplicar parámetros ganadores
        if winner[0] != 'version_a':
            self.dynamic_params.update(winner[1]['parameters'])
            ab_test_result['parameters_applied'] = True

        return ab_test_result

    def calculate_confidence_adjustments(self) -> Dict:
        """
        Calcula ajustes de confianza basados en desempeño por rango

        Si confianza 60-65% tiene 45% WR → Reducir rango
        Si confianza 70-75% tiene 70% WR → Expandir rango
        """
        recent_trades = self.trade_history[-self.learning_window:]

        if len(recent_trades) < 20:
            return {}

        # Agrupar por rango de confianza
        confidence_ranges = {
            '40-50': [],
            '50-60': [],
            '60-70': [],
            '70-80': [],
            '80-100': []
        }

        for trade in recent_trades:
            conf = trade.confidence
            if conf < 50:
                confidence_ranges['40-50'].append(trade)
            elif conf < 60:
                confidence_ranges['50-60'].append(trade)
            elif conf < 70:
                confidence_ranges['60-70'].append(trade)
            elif conf < 80:
                confidence_ranges['70-80'].append(trade)
            else:
                confidence_ranges['80-100'].append(trade)

        # Calcular WR por rango
        adjustments = {}
        for range_name, trades in confidence_ranges.items():
            if not trades:
                continue

            wins = len([t for t in trades if t.result == 'WIN'])
            wr = (wins / len(trades) * 100) if trades else 0

            adjustments[range_name] = {
                'trades': len(trades),
                'wr': round(wr, 1),
                'recommendation': self._recommend_confidence_adjustment(range_name, wr)
            }

        return adjustments

    def _recommend_confidence_adjustment(self, range_name: str, wr: float) -> str:
        """
        Recomienda ajuste basado en WR del rango
        """
        if wr < 50:
            return "EXCLUDE - Rango con WR < 50%"
        elif wr < 54.4:
            return "PROBLEMATIC - Apenas viable"
        elif wr > 70:
            return "EXPAND - Buenas señales en este rango"
        else:
            return "MONITOR - Rango marginal"

    def generate_optimization_report(self) -> Dict:
        """
        Genera reporte completo de optimizaciones realizadas
        """
        recent_trades = self.trade_history[-self.learning_window:]

        if not recent_trades:
            return {'status': 'NO_DATA'}

        total_trades = len(recent_trades)
        wins = len([t for t in recent_trades if t.result == 'WIN'])
        wr = (wins / total_trades * 100) if total_trades else 0

        report = {
            'timestamp': datetime.now().isoformat(),
            'trades_analyzed': total_trades,
            'current_wr': round(wr, 1),
            'patterns_detected': len(self.detect_loss_patterns()),
            'adjustments_applied': len(self.parameter_adjustments),
            'current_parameters': self.dynamic_params.copy(),
            'recommendations': []
        }

        # Recomendaciones basadas en análisis
        if wr < 54.4:
            report['recommendations'].append({
                'priority': 'CRITICAL',
                'recommendation': 'WR por debajo de mínimo requerido',
                'action': 'Aplicar strict_mode y/o cambiar estrategia'
            })

        patterns = self.detect_loss_patterns()
        for pattern in patterns:
            report['recommendations'].append({
                'priority': pattern.get('severity', 'MEDIUM'),
                'pattern': pattern['type'],
                'action': pattern['action']
            })

        return report

    def get_learning_history(self) -> Dict:
        """
        Retorna historial completo de aprendizaje y mejoras
        """
        return {
            'trades_analyzed': len(self.trade_history),
            'patterns_detected': len(self.pattern_detections),
            'parameter_adjustments': len(self.parameter_adjustments),
            'improvements_made': len(self.performance_improvements),
            'current_parameters': self.dynamic_params,
            'recent_adjustments': self.parameter_adjustments[-5:] if self.parameter_adjustments else [],
            'trade_history_sample': [asdict(t) for t in self.trade_history[-10:]] if self.trade_history else []
        }

    def print_learning_report(self):
        """
        Imprime reporte de aprendizaje en consola
        """
        report = self.generate_optimization_report()

        print(f"\n{'='*80}")
        print(f"🧠 REPORTE DE APRENDIZAJE Y OPTIMIZACIÓN")
        print(f"{'='*80}")

        print(f"\n📊 ANÁLISIS")
        print(f"{'-'*80}")
        print(f"  Trades analizados: {report['trades_analyzed']}")
        print(f"  Win Rate actual:   {report['current_wr']}%")
        print(f"  Patrones detectados: {report['patterns_detected']}")
        print(f"  Ajustes aplicados:   {report['adjustments_applied']}")

        print(f"\n⚙️  PARÁMETROS ACTUALES")
        print(f"{'-'*80}")
        for param, value in report['current_parameters'].items():
            print(f"  {param}: {value}")

        if report['recommendations']:
            print(f"\n💡 RECOMENDACIONES")
            print(f"{'-'*80}")
            for rec in report['recommendations']:
                priority_icon = "🔴" if rec['priority'] == 'CRITICAL' else "🟡" if rec['priority'] == 'HIGH' else "🟢"
                print(f"  {priority_icon} [{rec['priority']}] {rec.get('recommendation', rec.get('pattern'))}")
                print(f"     → {rec['action']}")

        print(f"\n{'='*80}")
