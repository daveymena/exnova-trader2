"""
🧠 REFINADOR DE ESTRATEGIA
Sistema que refina entradas ganadoras y mejora entradas perdedoras
Objetivo: Máxima consistencia y rentabilidad
"""
import json
import time
from typing import Dict, List, Optional
from collections import defaultdict
import statistics


class StrategyRefiner:
    """
    Refina la estrategia de trading analizando:
    1. Entradas ganadoras → Extraer características clave
    2. Entradas perdedoras → Identificar qué salió mal
    3. Generar reglas de entrada mejoradas
    4. Adaptar parámetros dinámicamente
    """

    def __init__(self):
        self.name = "Strategy Refiner v1.0"
        self.version = "1.0"
        
        # Reglas aprendidas
        self.winning_rules = []
        self.losing_patterns = []
        self.adaptive_rules = {}
        
        # Métricas
        self.refinements_count = 0
        self.rule_effectiveness = {}
        
        print(f"[OK] {self.name} inicializado")

    # ═══════════════════════════════════════════════════════════════════════════════
    # ANÁLISIS DE ENTRADAS GANADORAS
    # ═══════════════════════════════════════════════════════════════════════════════

    def extract_winning_characteristics(self, winning_trades: List[Dict]) -> Dict:
        """
        Extrae características de entradas ganadoras
        """
        print(f"\n🏆 ANALIZANDO {len(winning_trades)} ENTRADAS GANADORAS...")
        
        characteristics = {
            'total_wins': len(winning_trades),
            'avg_pnl': statistics.mean([t['pnl'] for t in winning_trades]),
            'max_pnl': max([t['pnl'] for t in winning_trades]),
            'min_pnl': min([t['pnl'] for t in winning_trades]),
            
            # Características de entrada
            'entry_characteristics': {
                'rsi_range': self._get_rsi_range(winning_trades),
                'preferred_patterns': self._get_preferred_patterns(winning_trades),
                'preferred_assets': self._get_preferred_assets(winning_trades),
                'preferred_sessions': self._get_preferred_sessions(winning_trades),
                'zone_strength_min': self._get_min_zone_strength(winning_trades),
                'first_visit_vs_revisit': self._analyze_visit_type(winning_trades),
                'trend_alignment': self._analyze_trend_alignment(winning_trades),
            },
            
            # Reglas de entrada
            'entry_rules': self._generate_entry_rules(winning_trades),
        }
        
        return characteristics

    def _get_rsi_range(self, trades: List[Dict]) -> Dict:
        """Rango de RSI en operaciones ganadoras"""
        rsi_values = [t.get('rsi_at_touch', 50) for t in trades]
        return {
            'min': min(rsi_values),
            'max': max(rsi_values),
            'mean': statistics.mean(rsi_values),
            'median': statistics.median(rsi_values),
            'stdev': statistics.stdev(rsi_values) if len(rsi_values) > 1 else 0,
        }

    def _get_preferred_patterns(self, trades: List[Dict]) -> Dict:
        """Patrones más efectivos"""
        patterns = defaultdict(list)
        for t in trades:
            pattern = t.get('pattern', 'none')
            patterns[pattern].append(t['pnl'])
        
        result = {}
        for pattern, pnls in patterns.items():
            result[pattern] = {
                'count': len(pnls),
                'avg_pnl': statistics.mean(pnls),
                'total_pnl': sum(pnls),
                'effectiveness': len(pnls) / len(trades) * 100,
            }
        
        return dict(sorted(result.items(), key=lambda x: x[1]['total_pnl'], reverse=True))

    def _get_preferred_assets(self, trades: List[Dict]) -> Dict:
        """Activos más rentables"""
        assets = defaultdict(list)
        for t in trades:
            asset = t['asset']
            assets[asset].append(t['pnl'])
        
        result = {}
        for asset, pnls in assets.items():
            result[asset] = {
                'count': len(pnls),
                'avg_pnl': statistics.mean(pnls),
                'total_pnl': sum(pnls),
                'effectiveness': len(pnls) / len(trades) * 100,
            }
        
        return dict(sorted(result.items(), key=lambda x: x[1]['total_pnl'], reverse=True))

    def _get_preferred_sessions(self, trades: List[Dict]) -> Dict:
        """Sesiones más rentables"""
        sessions = defaultdict(list)
        for t in trades:
            session = t.get('session', 'UNKNOWN')
            sessions[session].append(t['pnl'])
        
        result = {}
        for session, pnls in sessions.items():
            result[session] = {
                'count': len(pnls),
                'avg_pnl': statistics.mean(pnls),
                'total_pnl': sum(pnls),
            }
        
        return dict(sorted(result.items(), key=lambda x: x[1]['total_pnl'], reverse=True))

    def _get_min_zone_strength(self, trades: List[Dict]) -> float:
        """Fortaleza mínima de zona en ganancias"""
        strengths = [t.get('zone_strength', 0.5) for t in trades]
        return min(strengths) if strengths else 0.5

    def _analyze_visit_type(self, trades: List[Dict]) -> Dict:
        """Análisis de primeras visitas vs revisitas"""
        first_visits = [t for t in trades if t.get('was_first_visit', False)]
        revisits = [t for t in trades if not t.get('was_first_visit', False)]
        
        return {
            'first_visits': {
                'count': len(first_visits),
                'avg_pnl': statistics.mean([t['pnl'] for t in first_visits]) if first_visits else 0,
                'total_pnl': sum([t['pnl'] for t in first_visits]),
            },
            'revisits': {
                'count': len(revisits),
                'avg_pnl': statistics.mean([t['pnl'] for t in revisits]) if revisits else 0,
                'total_pnl': sum([t['pnl'] for t in revisits]),
            },
            'recommendation': 'REVISITS' if len(revisits) > 0 and statistics.mean([t['pnl'] for t in revisits]) > statistics.mean([t['pnl'] for t in first_visits]) else 'FIRST_VISITS'
        }

    def _analyze_trend_alignment(self, trades: List[Dict]) -> Dict:
        """Análisis de alineación con tendencia"""
        aligned = [t for t in trades if t.get('trend_aligned', False)]
        against = [t for t in trades if not t.get('trend_aligned', False)]
        
        return {
            'with_trend': {
                'count': len(aligned),
                'avg_pnl': statistics.mean([t['pnl'] for t in aligned]) if aligned else 0,
                'total_pnl': sum([t['pnl'] for t in aligned]),
            },
            'against_trend': {
                'count': len(against),
                'avg_pnl': statistics.mean([t['pnl'] for t in against]) if against else 0,
                'total_pnl': sum([t['pnl'] for t in against]),
            },
            'recommendation': 'AGAINST_TREND' if len(against) > 0 and statistics.mean([t['pnl'] for t in against]) > statistics.mean([t['pnl'] for t in aligned]) else 'WITH_TREND'
        }

    def _generate_entry_rules(self, trades: List[Dict]) -> List[Dict]:
        """Genera reglas de entrada basadas en ganancias"""
        rules = []
        
        # Regla 1: Preferir ciertos activos
        assets = self._get_preferred_assets(trades)
        top_assets = list(assets.keys())[:3]
        rules.append({
            'id': 'prefer_top_assets',
            'description': f'Preferir operaciones en {", ".join(top_assets)}',
            'priority': 'HIGH',
            'expected_impact': '+2-3% WR'
        })
        
        # Regla 2: Usar patrones efectivos
        patterns = self._get_preferred_patterns(trades)
        effective_patterns = [p for p, d in patterns.items() if d['effectiveness'] > 20]
        rules.append({
            'id': 'use_effective_patterns',
            'description': f'Priorizar patrones: {", ".join(effective_patterns)}',
            'priority': 'HIGH',
            'expected_impact': '+1-2% WR'
        })
        
        # Regla 3: Preferir sesiones rentables
        sessions = self._get_preferred_sessions(trades)
        top_sessions = list(sessions.keys())[:2]
        rules.append({
            'id': 'prefer_sessions',
            'description': f'Aumentar volumen en sesiones: {", ".join(top_sessions)}',
            'priority': 'MEDIUM',
            'expected_impact': '+1% PnL'
        })
        
        # Regla 4: RSI óptimo
        rsi_range = self._get_rsi_range(trades)
        rules.append({
            'id': 'rsi_optimization',
            'description': f'RSI óptimo: {rsi_range["min"]:.0f}-{rsi_range["max"]:.0f} (media: {rsi_range["mean"]:.0f})',
            'priority': 'MEDIUM',
            'expected_impact': '+0.5-1% WR'
        })
        
        return rules

    # ═══════════════════════════════════════════════════════════════════════════════
    # ANÁLISIS DE ENTRADAS PERDEDORAS
    # ═══════════════════════════════════════════════════════════════════════════════

    def analyze_losing_patterns(self, losing_trades: List[Dict]) -> Dict:
        """
        Analiza patrones de pérdida para evitarlos
        """
        print(f"\n❌ ANALIZANDO {len(losing_trades)} ENTRADAS PERDEDORAS...")
        
        analysis = {
            'total_losses': len(losing_trades),
            'avg_loss': statistics.mean([t['pnl'] for t in losing_trades]),
            'max_loss': min([t['pnl'] for t in losing_trades]),
            'min_loss': max([t['pnl'] for t in losing_trades]),
            
            # Características de pérdida
            'loss_characteristics': {
                'problematic_assets': self._get_problematic_assets(losing_trades),
                'unreliable_patterns': self._get_unreliable_patterns(losing_trades),
                'bad_sessions': self._get_bad_sessions(losing_trades),
                'rsi_in_losses': self._get_rsi_range(losing_trades),
            },
            
            # Reglas para evitar pérdidas
            'avoidance_rules': self._generate_avoidance_rules(losing_trades),
        }
        
        return analysis

    def _get_problematic_assets(self, trades: List[Dict]) -> Dict:
        """Activos problemáticos"""
        assets = defaultdict(list)
        for t in trades:
            asset = t['asset']
            assets[asset].append(t['pnl'])
        
        result = {}
        for asset, pnls in assets.items():
            result[asset] = {
                'count': len(pnls),
                'avg_loss': statistics.mean(pnls),
                'total_loss': sum(pnls),
                'severity': 'CRITICAL' if len(pnls) > 5 else 'HIGH'
            }
        
        return dict(sorted(result.items(), key=lambda x: x[1]['total_loss']))

    def _get_unreliable_patterns(self, trades: List[Dict]) -> Dict:
        """Patrones no confiables"""
        patterns = defaultdict(list)
        for t in trades:
            pattern = t.get('pattern', 'none')
            patterns[pattern].append(t['pnl'])
        
        result = {}
        for pattern, pnls in patterns.items():
            result[pattern] = {
                'count': len(pnls),
                'avg_loss': statistics.mean(pnls),
                'total_loss': sum(pnls),
            }
        
        return dict(sorted(result.items(), key=lambda x: x[1]['total_loss']))

    def _get_bad_sessions(self, trades: List[Dict]) -> Dict:
        """Sesiones problemáticas"""
        sessions = defaultdict(list)
        for t in trades:
            session = t.get('session', 'UNKNOWN')
            sessions[session].append(t['pnl'])
        
        result = {}
        for session, pnls in sessions.items():
            result[session] = {
                'count': len(pnls),
                'avg_loss': statistics.mean(pnls),
                'total_loss': sum(pnls),
            }
        
        return dict(sorted(result.items(), key=lambda x: x[1]['total_loss']))

    def _generate_avoidance_rules(self, trades: List[Dict]) -> List[Dict]:
        """Genera reglas para evitar pérdidas"""
        rules = []
        
        # Regla 1: Evitar activos problemáticos
        assets = self._get_problematic_assets(trades)
        worst_assets = [a for a, d in list(assets.items())[:2]]
        if worst_assets:
            rules.append({
                'id': 'avoid_bad_assets',
                'description': f'PAUSAR o reducir: {", ".join(worst_assets)}',
                'priority': 'CRITICAL',
                'expected_impact': f'+{abs(sum([d["total_loss"] for a, d in list(assets.items())[:2]]))*0.5:.0f} PnL'
            })
        
        # Regla 2: Evitar patrones no confiables
        patterns = self._get_unreliable_patterns(trades)
        bad_patterns = [p for p, d in list(patterns.items())[:2] if d['count'] > 2]
        if bad_patterns:
            rules.append({
                'id': 'avoid_bad_patterns',
                'description': f'Mejorar validación para: {", ".join(bad_patterns)}',
                'priority': 'HIGH',
                'expected_impact': '+1-2% WR'
            })
        
        # Regla 3: Evitar sesiones malas
        sessions = self._get_bad_sessions(trades)
        bad_sessions = [s for s, d in list(sessions.items())[:1]]
        if bad_sessions:
            rules.append({
                'id': 'avoid_bad_sessions',
                'description': f'Reducir operaciones en: {", ".join(bad_sessions)}',
                'priority': 'MEDIUM',
                'expected_impact': '+0.5-1% WR'
            })
        
        return rules

    # ═══════════════════════════════════════════════════════════════════════════════
    # REFINAMIENTO DE ESTRATEGIA
    # ═══════════════════════════════════════════════════════════════════════════════

    def refine_strategy(self, winning_trades: List[Dict], losing_trades: List[Dict]) -> Dict:
        """
        Refina la estrategia completa
        """
        print(f"\n🧠 REFINANDO ESTRATEGIA...")
        
        # Analizar ganancias
        winning_chars = self.extract_winning_characteristics(winning_trades)
        
        # Analizar pérdidas
        losing_chars = self.analyze_losing_patterns(losing_trades)
        
        # Generar estrategia refinada
        refined_strategy = {
            'timestamp': time.time(),
            'version': self.version,
            
            # Lo que funciona
            'do_this': {
                'assets': list(winning_chars['entry_characteristics']['preferred_assets'].keys())[:3],
                'patterns': list(winning_chars['entry_characteristics']['preferred_patterns'].keys())[:3],
                'sessions': list(winning_chars['entry_characteristics']['preferred_sessions'].keys()),
                'rsi_range': winning_chars['entry_characteristics']['rsi_range'],
                'rules': winning_chars['entry_rules'],
            },
            
            # Lo que evitar
            'avoid_this': {
                'assets': list(losing_chars['loss_characteristics']['problematic_assets'].keys())[:2],
                'patterns': list(losing_chars['loss_characteristics']['unreliable_patterns'].keys())[:2],
                'sessions': list(losing_chars['loss_characteristics']['bad_sessions'].keys())[:1],
                'rules': losing_chars['avoidance_rules'],
            },
            
            # Recomendaciones
            'recommendations': self._generate_recommendations(winning_chars, losing_chars),
        }
        
        self.refinements_count += 1
        return refined_strategy

    def _generate_recommendations(self, winning_chars: Dict, losing_chars: Dict) -> List[Dict]:
        """Genera recomendaciones finales"""
        recommendations = []
        
        # Recomendación 1: Aumentar volumen en activos ganadores
        top_asset = list(winning_chars['entry_characteristics']['preferred_assets'].keys())[0]
        recommendations.append({
            'priority': 'CRITICAL',
            'action': f'Aumentar volumen en {top_asset} (1.5x)',
            'reason': f'Mejor activo con {winning_chars["entry_characteristics"]["preferred_assets"][top_asset]["effectiveness"]:.0f}% efectividad',
            'expected_impact': '+50-100 PnL'
        })
        
        # Recomendación 2: Pausar activos malos
        worst_asset = list(losing_chars['loss_characteristics']['problematic_assets'].keys())[0]
        recommendations.append({
            'priority': 'CRITICAL',
            'action': f'PAUSAR {worst_asset}',
            'reason': f'Pérdida total: {losing_chars["loss_characteristics"]["problematic_assets"][worst_asset]["total_loss"]:.2f}',
            'expected_impact': f'+{abs(losing_chars["loss_characteristics"]["problematic_assets"][worst_asset]["total_loss"])*0.5:.0f} PnL'
        })
        
        # Recomendación 3: Usar patrones efectivos
        top_pattern = list(winning_chars['entry_characteristics']['preferred_patterns'].keys())[0]
        recommendations.append({
            'priority': 'HIGH',
            'action': f'Priorizar patrón: {top_pattern}',
            'reason': f'Efectividad: {winning_chars["entry_characteristics"]["preferred_patterns"][top_pattern]["effectiveness"]:.0f}%',
            'expected_impact': '+20-30 PnL'
        })
        
        return recommendations

    def get_summary(self) -> Dict:
        """Resumen del refinador"""
        return {
            'name': self.name,
            'version': self.version,
            'refinements_count': self.refinements_count,
            'status': 'ACTIVE'
        }


# Singleton
_refiner: Optional[StrategyRefiner] = None


def get_strategy_refiner() -> StrategyRefiner:
    global _refiner
    if _refiner is None:
        _refiner = StrategyRefiner()
    return _refiner
