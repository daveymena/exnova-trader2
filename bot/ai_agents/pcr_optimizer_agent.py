"""
PCR Optimizer Agent - Agente IA que toma decisiones automáticas
- Monitorea desempeño
- Cambia estrategias cuando no funciona
- Refina parámetros automáticamente
- Genera recomendaciones de optimización
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class StrategyPerformance:
    """Métricas de desempeño de una estrategia"""
    name: str
    trades: int
    wr: float
    pnl: float
    sharpe: float
    max_dd: float
    consecutive_losses: int
    viable: bool
    timestamp: datetime


class PCROptimizerAgent:
    """
    Agente IA que:
    1. Monitorea desempeño de estrategias en tiempo real
    2. Detecta cuándo una estrategia no funciona
    3. Cambia automáticamente a mejor alternativa
    4. Refina parámetros para optimizar
    5. Genera alertas y recomendaciones
    """

    def __init__(self, evaluation_window: int = 50, min_trades_for_decision: int = 20):
        """
        Args:
            evaluation_window: Últimos N trades para evaluar
            min_trades_for_decision: Mínimo trades antes de decidir cambio
        """
        self.evaluation_window = evaluation_window
        self.min_trades_for_decision = min_trades_for_decision

        # Historial de desempeño
        self.performance_history: Dict[str, List[StrategyPerformance]] = {
            'pcr_simple': [],
            'pcr_complete': [],
            'pcr_hybrid': [],
            'pcr_hybrid_strict': []
        }

        # Estrategia actual
        self.current_strategy = 'pcr_simple'
        self.strategy_switches = []
        self.optimizations = []

    def evaluate_strategy(self, strategy_name: str, trades: List[Dict]) -> StrategyPerformance:
        """
        Evalúa una estrategia basada en trades recientes

        Args:
            strategy_name: Nombre de estrategia
            trades: Lista de trades

        Returns:
            StrategyPerformance con métricas
        """
        if not trades:
            return StrategyPerformance(
                name=strategy_name,
                trades=0,
                wr=0,
                pnl=0,
                sharpe=0,
                max_dd=0,
                consecutive_losses=0,
                viable=False,
                timestamp=datetime.now()
            )

        # Usar últimas N trades
        window_trades = trades[-self.evaluation_window:]
        df = pd.DataFrame(window_trades)

        total = len(df)
        wins = len(df[df['result'] == 'WIN'])
        wr = (wins / total * 100) if total > 0 else 0

        pnl = df['pnl'].sum()

        # Sharpe Ratio
        pnls = df['pnl'].values
        if len(pnls) > 1 and pnls.std() > 0:
            sharpe = (pnls.mean() / pnls.std()) * np.sqrt(252)
        else:
            sharpe = 0

        # Drawdown
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = running_max - cumulative
        max_dd = np.max(drawdown) if len(drawdown) > 0 else 0

        # Consecutivos
        results = df['result'].values
        max_losses = 0
        current_losses = 0
        for r in results:
            if r == 'LOSS':
                current_losses += 1
                max_losses = max(max_losses, current_losses)
            else:
                current_losses = 0

        viable = wr >= 54.4

        perf = StrategyPerformance(
            name=strategy_name,
            trades=total,
            wr=round(wr, 1),
            pnl=round(pnl, 2),
            sharpe=round(sharpe, 2),
            max_dd=round(max_dd, 2),
            consecutive_losses=max_losses,
            viable=viable,
            timestamp=datetime.now()
        )

        # Guardar en historial
        self.performance_history[strategy_name].append(perf)

        return perf

    def should_switch_strategy(self, current_perf: StrategyPerformance,
                              alternative_perfs: Dict[str, StrategyPerformance]) -> Tuple[bool, Optional[str], str]:
        """
        Decide si cambiar de estrategia

        Args:
            current_perf: Desempeño de estrategia actual
            alternative_perfs: Desempeño de alternativas

        Returns:
            (should_switch, new_strategy, reason)
        """
        # Criterio 1: WR crítica
        if current_perf.wr < 50 and current_perf.trades >= self.min_trades_for_decision:
            best_alt = max(alternative_perfs.items(), key=lambda x: x[1].wr if x[1].trades >= 10 else 0)
            if best_alt[1].wr > current_perf.wr:
                return True, best_alt[0], f"WR crítica {current_perf.wr}% → {best_alt[1].name} ({best_alt[1].wr}%)"

        # Criterio 2: Demasiadas pérdidas consecutivas
        if current_perf.consecutive_losses >= 5:
            best_alt = max(alternative_perfs.items(), key=lambda x: x[1].wr if x[1].trades >= 10 else 0)
            return True, best_alt[0], f"{current_perf.consecutive_losses} pérdidas consecutivas → cambiar a {best_alt[0]}"

        # Criterio 3: PnL muy negativo
        if current_perf.pnl < -100 and current_perf.trades >= 20:
            best_alt = max(alternative_perfs.items(), key=lambda x: x[1].pnl)
            return True, best_alt[0], f"PnL crítico (${current_perf.pnl}) → cambiar a {best_alt[0]}"

        # Criterio 4: Alterna mejora clara existe
        if current_perf.trades >= self.min_trades_for_decision:
            viable_alts = {k: v for k, v in alternative_perfs.items() if v.trades >= 10 and v.wr > 60}

            if viable_alts:
                best_alt = max(viable_alts.items(), key=lambda x: x[1].wr)
                if best_alt[1].wr > current_perf.wr + 5:  # +5% es mejora significativa
                    return True, best_alt[0], f"Mejora alternativa detectada: {best_alt[0]} ({best_alt[1].wr}%)"

        return False, None, "Estrategia actual funcionando"

    def get_optimization_recommendations(self, perf: StrategyPerformance) -> List[Dict]:
        """
        Genera recomendaciones de optimización

        Args:
            perf: Performance actual

        Returns:
            Lista de recomendaciones
        """
        recommendations = []

        # Recomendación 1: Ajustar confianza mínima
        if perf.wr < 55 and perf.trades >= 30:
            recommendations.append({
                'type': 'CONFIDENCE_THRESHOLD',
                'current': 60,
                'recommended': 70,
                'reason': f"WR baja ({perf.wr}%) - requerir más confianza",
                'impact': 'Menos trades pero más precisos'
            })

        # Recomendación 2: Aumentar volatilidad mínima
        if perf.wr < 54.4 and perf.trades >= 50:
            recommendations.append({
                'type': 'VOLATILITY_FILTER',
                'action': 'Increase minimum volatility',
                'reason': 'Evitar mercados muy tranquilos donde hay menos patrones',
                'impact': 'Mejor calidad de señales'
            })

        # Recomendación 3: Usar validación estricta
        if perf.consecutive_losses >= 3:
            recommendations.append({
                'type': 'STRICT_VALIDATION',
                'current': False,
                'recommended': True,
                'reason': 'Demasiadas pérdidas consecutivas',
                'impact': 'Menos falsos positivos'
            })

        # Recomendación 4: Cambiar timeframe
        if perf.wr > 60 and perf.trades < 10:
            recommendations.append({
                'type': 'EXPAND_TIMEFRAME',
                'reason': 'Buena WR pero pocos trades - expandir búsqueda',
                'impact': 'Más oportunidades de trade'
            })

        return recommendations

    def make_decision(self, strategies_performance: Dict[str, List[Dict]]) -> Dict:
        """
        Toma decisión automática sobre estrategia

        Args:
            strategies_performance: {strategy_name: [trades]}

        Returns:
            Decisión con recomendaciones
        """
        decision = {
            'timestamp': datetime.now().isoformat(),
            'current_strategy': self.current_strategy,
            'should_switch': False,
            'new_strategy': None,
            'reason': None,
            'recommendations': [],
            'performance_summary': {}
        }

        # Evaluar todas las estrategias
        current_perf = self.evaluate_strategy(
            self.current_strategy,
            strategies_performance.get(self.current_strategy, [])
        )

        alternative_perfs = {}
        for strat_name, trades in strategies_performance.items():
            if strat_name != self.current_strategy:
                alternative_perfs[strat_name] = self.evaluate_strategy(strat_name, trades)

        # Decidir si cambiar
        should_switch, new_strategy, reason = self.should_switch_strategy(current_perf, alternative_perfs)

        if should_switch and new_strategy:
            decision['should_switch'] = True
            decision['new_strategy'] = new_strategy
            decision['reason'] = reason
            self.current_strategy = new_strategy
            self.strategy_switches.append({
                'from': decision['current_strategy'],
                'to': new_strategy,
                'timestamp': datetime.now().isoformat(),
                'reason': reason
            })

        # Recomendaciones de optimización
        recommendations = self.get_optimization_recommendations(current_perf)
        decision['recommendations'] = recommendations

        # Resumen de desempeño
        decision['performance_summary'] = {
            'current': {
                'strategy': current_perf.name,
                'trades': current_perf.trades,
                'wr': current_perf.wr,
                'pnl': current_perf.pnl,
                'viable': current_perf.viable
            },
            'alternatives': {
                name: {
                    'trades': perf.trades,
                    'wr': perf.wr,
                    'pnl': perf.pnl,
                    'viable': perf.viable
                }
                for name, perf in alternative_perfs.items()
            }
        }

        return decision

    def print_decision(self, decision: Dict):
        """Imprime decisión de forma legible"""
        print(f"\n{'='*80}")
        print(f"🤖 DECISIÓN DEL AGENTE IA PCR")
        print(f"{'='*80}")

        if decision['should_switch']:
            print(f"\n⚠️  CAMBIO DE ESTRATEGIA RECOMENDADO")
            print(f"{'-'*80}")
            print(f"  De:     {decision['current_strategy']}")
            print(f"  A:      {decision['new_strategy']}")
            print(f"  Razón:  {decision['reason']}")
        else:
            print(f"\n✅ ESTRATEGIA ACTUAL FUNCIONANDO")
            print(f"{'-'*80}")
            print(f"  Estrategia: {decision['current_strategy']}")
            print(f"  Razón:      {decision['reason']}")

        # Desempeño
        perf = decision['performance_summary']['current']
        print(f"\n📊 DESEMPEÑO ACTUAL")
        print(f"{'-'*80}")
        print(f"  Trades:      {perf['trades']}")
        print(f"  WR:          {perf['wr']}%")
        print(f"  PnL:         ${perf['pnl']}")
        print(f"  Viable:      {'✅' if perf['viable'] else '❌'}")

        # Recomendaciones
        if decision['recommendations']:
            print(f"\n💡 RECOMENDACIONES DE OPTIMIZACIÓN")
            print(f"{'-'*80}")
            for rec in decision['recommendations']:
                print(f"  • {rec.get('type', 'UNKNOWN')}")
                print(f"    Razón: {rec.get('reason', 'N/A')}")
                print(f"    Impacto: {rec.get('impact', 'N/A')}")

        print(f"\n{'='*80}")

    def get_stats(self) -> Dict:
        """Retorna estadísticas del agente"""
        return {
            'current_strategy': self.current_strategy,
            'total_switches': len(self.strategy_switches),
            'total_optimizations': len(self.optimizations),
            'switches_history': self.strategy_switches,
            'strategies_tested': list(self.performance_history.keys())
        }
