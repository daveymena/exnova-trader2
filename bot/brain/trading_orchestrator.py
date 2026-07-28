"""
ðŸŽ¼ ORQUESTADOR DE TRADING
Coordina el Agente de Trading y el Refinador de Estrategia
Objetivo: Sistema autoadaptativo que gana consistentemente
"""
import json
import time
from typing import Dict, List, Optional
from pathlib import Path

from trading_agent import get_trading_agent
from strategy_refiner import get_strategy_refiner
from .trade_persistence import get_trade_persistence


class TradingOrchestrator:
    """
    Orquestador que:
    1. Carga trades histÃ³ricos
    2. Ejecuta anÃ¡lisis del agente
    3. Refina la estrategia
    4. Genera recomendaciones
    5. Monitorea progreso
    """

    def __init__(self):
        self.name = "Trading Orchestrator v1.0"
        self.version = "1.0"
        
        # Componentes
        self.agent = get_trading_agent()
        self.refiner = get_strategy_refiner()
        self.persistence = get_trade_persistence()
        
        # Historial de ejecuciones
        self.execution_history = []
        self.recommendations_history = []
        
        print(f"\n[OK] {self.name} inicializado")
        print(f"   Agente: {self.agent.name}")
        print(f"   Refinador: {self.refiner.name}")

    def execute_full_analysis(self) -> Dict:
        """
        Ejecuta anÃ¡lisis completo del sistema
        """
        print(f"\n{'='*100}")
        print(f"ðŸŽ¼ EJECUTANDO ANÃLISIS COMPLETO DEL SISTEMA")
        print(f"{'='*100}")
        
        execution = {
            'timestamp': time.time(),
            'version': self.version,
            'stages': {}
        }
        
        # Etapa 1: Cargar trades
        print(f"\nðŸ“¥ ETAPA 1: CARGANDO TRADES...")
        trades = self.persistence.trades
        if not trades:
            print(f"âŒ No hay trades para analizar")
            return {'status': 'error', 'message': 'No trades found'}
        
        print(f"âœ… {len(trades)} trades cargados")
        execution['stages']['load_trades'] = {
            'status': 'completed',
            'trades_loaded': len(trades)
        }
        
        # Etapa 2: AnÃ¡lisis del agente
        print(f"\nðŸ¤– ETAPA 2: ANÃLISIS DEL AGENTE...")
        analysis = self.agent.analyze_trades(trades)
        execution['stages']['agent_analysis'] = {
            'status': 'completed',
            'analysis': analysis
        }
        
        # Etapa 3: Generar mejoras
        print(f"\nðŸ’¡ ETAPA 3: GENERANDO MEJORAS...")
        improvements = self.agent.generate_improvements(analysis)
        execution['stages']['generate_improvements'] = {
            'status': 'completed',
            'improvements_count': len(improvements)
        }
        
        # Etapa 4: Aplicar mejoras
        print(f"\nâœ… ETAPA 4: APLICANDO MEJORAS...")
        applied = self.agent.apply_improvements(improvements)
        execution['stages']['apply_improvements'] = {
            'status': 'completed',
            'applied_count': applied['total']
        }
        
        # Etapa 5: Refinar estrategia
        print(f"\nðŸ§  ETAPA 5: REFINANDO ESTRATEGIA...")
        wins = [t for t in trades if t['result'] == 'HOLD']
        losses = [t for t in trades if t['result'] == 'BREAK']
        refined_strategy = self.refiner.refine_strategy(wins, losses)
        execution['stages']['refine_strategy'] = {
            'status': 'completed',
            'strategy': refined_strategy
        }
        
        # Etapa 6: Adaptar parÃ¡metros
        print(f"\nðŸ”§ ETAPA 6: ADAPTANDO PARÃMETROS...")
        current_wr = analysis['win_rate']
        adaptations = self.agent.adapt_parameters(current_wr)
        execution['stages']['adapt_parameters'] = {
            'status': 'completed',
            'adaptations': adaptations
        }
        
        # Etapa 7: Generar reporte
        print(f"\nðŸ“Š ETAPA 7: GENERANDO REPORTE...")
        report = self.agent.generate_report(analysis, improvements)
        execution['stages']['generate_report'] = {
            'status': 'completed',
            'report': report
        }
        
        # Guardar ejecuciÃ³n
        self.execution_history.append(execution)
        self._save_execution(execution)
        
        # Mostrar reporte
        print(report)
        
        return execution

    def get_recommendations(self) -> Dict:
        """
        Obtiene recomendaciones actuales
        """
        if not self.execution_history:
            return {'status': 'no_analysis_yet'}
        
        latest = self.execution_history[-1]
        analysis = latest['stages']['agent_analysis']['analysis']
        refined = latest['stages']['refine_strategy']['strategy']
        
        recommendations = {
            'timestamp': time.time(),
            'current_wr': analysis['win_rate'],
            'target_wr': 0.60,
            
            'immediate_actions': [
                {
                    'priority': 'CRITICAL',
                    'action': f'PAUSAR {list(refined["avoid_this"]["assets"])[0] if refined["avoid_this"]["assets"] else "N/A"}',
                    'reason': 'Activo con bajo win rate',
                    'expected_impact': '+0.5-1% WR'
                },
                {
                    'priority': 'CRITICAL',
                    'action': f'Aumentar volumen en {list(refined["do_this"]["assets"])[0] if refined["do_this"]["assets"] else "N/A"} (1.5x)',
                    'reason': 'Activo con alto win rate',
                    'expected_impact': '+50-100 PnL'
                },
            ],
            
            'strategy_recommendations': refined['recommendations'],
            'do_this': refined['do_this'],
            'avoid_this': refined['avoid_this'],
        }
        
        self.recommendations_history.append(recommendations)
        return recommendations

    def monitor_progress(self) -> Dict:
        """
        Monitorea progreso del sistema
        """
        if not self.execution_history:
            return {'status': 'no_data'}
        
        latest = self.execution_history[-1]
        analysis = latest['stages']['agent_analysis']['analysis']
        
        progress = {
            'timestamp': time.time(),
            'current_metrics': {
                'win_rate': analysis['win_rate'],
                'pnl_total': analysis['pnl_total'],
                'pnl_avg': analysis['pnl_avg'],
                'total_trades': analysis['total_trades'],
            },
            'target_metrics': {
                'win_rate': 0.60,
                'pnl_total': 250,
                'pnl_avg': 6.0,
            },
            'progress': {
                'wr_progress': f"{analysis['win_rate']:.1%} / 60%",
                'pnl_progress': f"{analysis['pnl_total']:.0f} / 250",
                'status': 'ON_TRACK' if analysis['win_rate'] > 0.50 else 'NEEDS_IMPROVEMENT'
            },
            'agent_performance': self.agent.get_summary(),
            'refiner_performance': self.refiner.get_summary(),
        }
        
        return progress

    def _save_execution(self, execution: Dict):
        """Guarda ejecuciÃ³n en archivo"""
        try:
            path = Path('bot/brain/orchestrator_executions.json')
            
            # Cargar ejecuciones previas
            if path.exists():
                with open(path, 'r') as f:
                    data = json.load(f)
            else:
                data = {'executions': []}
            
            # Agregar nueva ejecuciÃ³n (sin anÃ¡lisis completo para ahorrar espacio)
            execution_summary = {
                'timestamp': execution['timestamp'],
                'version': execution['version'],
                'stages_completed': list(execution['stages'].keys()),
                'status': 'completed'
            }
            data['executions'].append(execution_summary)
            
            # Guardar
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            
            print(f"[OK] Ejecucion guardada en {path}")
        except Exception as e:
            print(f"âš ï¸ Error guardando ejecuciÃ³n: {e}")

    def generate_full_report(self) -> str:
        """
        Genera reporte completo del sistema
        """
        if not self.execution_history:
            return "No hay anÃ¡lisis disponible"
        
        latest = self.execution_history[-1]
        analysis = latest['stages']['agent_analysis']['analysis']
        refined = latest['stages']['refine_strategy']['strategy']
        
        report = f"""
â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—
â•‘                  ðŸŽ¼ REPORTE COMPLETO DEL ORQUESTADOR                          â•‘
â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

ðŸ“Š ESTADO ACTUAL:
  â€¢ Win Rate: {analysis['win_rate']:.1%}
  â€¢ PnL Total: {analysis['pnl_total']:+.2f}
  â€¢ PnL Promedio: {analysis['pnl_avg']:+.2f}
  â€¢ Total Operaciones: {analysis['total_trades']}

ðŸŽ¯ OBJETIVOS:
  â€¢ Win Rate Objetivo: 60%
  â€¢ PnL Objetivo: +250
  â€¢ PnL Promedio Objetivo: +6.0

âœ… LO QUE FUNCIONA:
  â€¢ Activos: {', '.join(refined['do_this']['assets'])}
  â€¢ Patrones: {', '.join(refined['do_this']['patterns'])}
  â€¢ Sesiones: {', '.join(refined['do_this']['sessions'])}

âŒ LO QUE EVITAR:
  â€¢ Activos: {', '.join(refined['avoid_this']['assets'])}
  â€¢ Patrones: {', '.join(refined['avoid_this']['patterns'])}
  â€¢ Sesiones: {', '.join(refined['avoid_this']['sessions'])}

ðŸ’¡ RECOMENDACIONES PRINCIPALES:
"""
        for i, rec in enumerate(refined['recommendations'][:5], 1):
            report += f"\n  {i}. [{rec['priority']}] {rec['action']}\n"
            report += f"     RazÃ³n: {rec['reason']}\n"
            report += f"     Impacto: {rec['expected_impact']}\n"
        
        report += f"\n{'='*80}\n"
        
        return report


# Singleton
_orchestrator: Optional[TradingOrchestrator] = None


def get_trading_orchestrator() -> TradingOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = TradingOrchestrator()
    return _orchestrator


if __name__ == "__main__":
    # Ejecutar anÃ¡lisis completo
    orchestrator = get_trading_orchestrator()
    execution = orchestrator.execute_full_analysis()
    
    # Mostrar recomendaciones
    print("\n" + "="*100)
    print("ðŸ“‹ RECOMENDACIONES")
    print("="*100)
    recommendations = orchestrator.get_recommendations()
    print(json.dumps(recommendations, indent=2, default=str))
    
    # Mostrar progreso
    print("\n" + "="*100)
    print("ðŸ“ˆ PROGRESO")
    print("="*100)
    progress = orchestrator.monitor_progress()
    print(json.dumps(progress, indent=2, default=str))
    
    # Mostrar reporte completo
    print("\n" + orchestrator.generate_full_report())

