"""
📊 DASHBOARD DE MONITOREO EN TIEMPO REAL
Monitorea el sistema de trading con IA
"""
import json
import time
from typing import Dict, List
from datetime import datetime
from collections import deque


class AITradingDashboard:
    """
    Dashboard que monitorea:
    1. Desempeño en tiempo real
    2. Análisis de IA
    3. Predicciones
    4. Optimizaciones
    """

    def __init__(self):
        self.name = "AI Trading Dashboard v1.0"
        self.version = "1.0"
        
        # Historial (últimos 100 eventos)
        self.events = deque(maxlen=100)
        self.trades = deque(maxlen=100)
        self.predictions = deque(maxlen=50)
        self.optimizations = deque(maxlen=20)
        
        # Métricas actuales
        self.current_metrics = {
            'win_rate': 0.524,
            'pnl_total': 160.15,
            'pnl_avg': 3.81,
            'total_trades': 42,
            'ai_predictions': 0,
            'ai_analyses': 0,
            'optimizations_applied': 0,
        }
        
        print(f"[OK] {self.name} inicializado")

    # ═══════════════════════════════════════════════════════════════════════════════
    # ACTUALIZACIÓN DE MÉTRICAS
    # ═══════════════════════════════════════════════════════════════════════════════

    def update_trade(self, trade: Dict) -> None:
        """Registra un nuevo trade"""
        trade_event = {
            'timestamp': time.time(),
            'type': 'trade',
            'asset': trade.get('asset'),
            'direction': trade.get('direction'),
            'result': trade.get('result'),
            'pnl': trade.get('pnl'),
        }
        
        self.trades.append(trade_event)
        self.events.append(trade_event)
        
        # Actualizar métricas
        self._update_metrics()

    def update_prediction(self, prediction: Dict) -> None:
        """Registra una predicción de IA"""
        pred_event = {
            'timestamp': time.time(),
            'type': 'prediction',
            'asset': prediction.get('asset'),
            'direction': prediction.get('direction'),
            'confidence': prediction.get('confidence'),
        }
        
        self.predictions.append(pred_event)
        self.events.append(pred_event)
        self.current_metrics['ai_predictions'] += 1

    def update_optimization(self, optimization: Dict) -> None:
        """Registra una optimización"""
        opt_event = {
            'timestamp': time.time(),
            'type': 'optimization',
            'changes': optimization.get('changes', []),
            'expected_improvement': optimization.get('expected_improvement'),
        }
        
        self.optimizations.append(opt_event)
        self.events.append(opt_event)
        self.current_metrics['optimizations_applied'] += 1

    def _update_metrics(self) -> None:
        """Actualiza métricas basadas en trades"""
        if not self.trades:
            return
        
        wins = sum(1 for t in self.trades if t['result'] == 'HOLD')
        total = len(self.trades)
        
        self.current_metrics['total_trades'] = total
        self.current_metrics['win_rate'] = wins / total if total > 0 else 0
        self.current_metrics['pnl_total'] = sum(t['pnl'] for t in self.trades)
        self.current_metrics['pnl_avg'] = self.current_metrics['pnl_total'] / total if total > 0 else 0

    # ═══════════════════════════════════════════════════════════════════════════════
    # VISUALIZACIÓN DEL DASHBOARD
    # ═══════════════════════════════════════════════════════════════════════════════

    def display_dashboard(self) -> str:
        """Genera visualización del dashboard"""
        
        dashboard = f"""
╔════════════════════════════════════════════════════════════════════════════════╗
║                    📊 DASHBOARD DE TRADING CON IA                             ║
║                         {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                                    ║
╚════════════════════════════════════════════════════════════════════════════════╝

┌─ MÉTRICAS PRINCIPALES ─────────────────────────────────────────────────────────┐
│                                                                                 │
│  Win Rate:              {self.current_metrics['win_rate']:>6.1%}  {'█' * int(self.current_metrics['win_rate'] * 20)}{'░' * (20 - int(self.current_metrics['win_rate'] * 20))}  │
│  PnL Total:             {self.current_metrics['pnl_total']:>8.2f}                                    │
│  PnL Promedio:          {self.current_metrics['pnl_avg']:>8.2f}                                    │
│  Total Trades:          {self.current_metrics['total_trades']:>6}                                      │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─ ACTIVIDAD DE IA ──────────────────────────────────────────────────────────────┐
│                                                                                 │
│  Predicciones:          {self.current_metrics['ai_predictions']:>6}                                      │
│  Análisis:              {self.current_metrics['ai_analyses']:>6}                                      │
│  Optimizaciones:        {self.current_metrics['optimizations_applied']:>6}                                      │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─ ÚLTIMOS EVENTOS ──────────────────────────────────────────────────────────────┐
│                                                                                 │
"""
        
        # Mostrar últimos 5 eventos
        for event in list(self.events)[-5:]:
            event_type = event.get('type', 'unknown').upper()
            timestamp = datetime.fromtimestamp(event['timestamp']).strftime('%H:%M:%S')
            
            if event_type == 'TRADE':
                result = event.get('result', 'N/A')
                pnl = event.get('pnl', 0)
                dashboard += f"│  [{timestamp}] TRADE: {event.get('asset')} {event.get('direction')} → {result} ({pnl:+.2f})  │\n"
            elif event_type == 'PREDICTION':
                confidence = event.get('confidence', 0)
                dashboard += f"│  [{timestamp}] PRED:  {event.get('asset')} {event.get('direction')} (conf: {confidence}%)  │\n"
            elif event_type == 'OPTIMIZATION':
                dashboard += f"│  [{timestamp}] OPT:   {event.get('expected_improvement', 'N/A')}  │\n"
        
        dashboard += f"""│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─ OBJETIVOS ────────────────────────────────────────────────────────────────────┐
│                                                                                 │
│  Win Rate Objetivo:     60.0%  {'█' * 12}░░░░░░░░  (Actual: {self.current_metrics['win_rate']:.1%})  │
│  PnL Objetivo:          +250   {'█' * int(min(self.current_metrics['pnl_total']/250*20, 20))}{'░' * (20 - int(min(self.current_metrics['pnl_total']/250*20, 20)))}  (Actual: {self.current_metrics['pnl_total']:+.0f})  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

╔════════════════════════════════════════════════════════════════════════════════╗
"""
        
        return dashboard

    def display_summary(self) -> str:
        """Resumen compacto"""
        
        summary = f"""
[DASHBOARD] WR: {self.current_metrics['win_rate']:.1%} | PnL: {self.current_metrics['pnl_total']:+.0f} | Trades: {self.current_metrics['total_trades']} | Pred: {self.current_metrics['ai_predictions']} | Opt: {self.current_metrics['optimizations_applied']}
"""
        return summary

    # ═══════════════════════════════════════════════════════════════════════════════
    # ANÁLISIS Y REPORTES
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_performance_analysis(self) -> Dict:
        """Análisis de desempeño"""
        
        if not self.trades:
            return {'status': 'no_data'}
        
        wins = [t for t in self.trades if t['result'] == 'HOLD']
        losses = [t for t in self.trades if t['result'] == 'BREAK']
        
        analysis = {
            'total_trades': len(self.trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(self.trades) if self.trades else 0,
            'avg_win': sum(t['pnl'] for t in wins) / len(wins) if wins else 0,
            'avg_loss': sum(t['pnl'] for t in losses) / len(losses) if losses else 0,
            'profit_factor': (sum(t['pnl'] for t in wins) / abs(sum(t['pnl'] for t in losses))) if losses and sum(t['pnl'] for t in losses) != 0 else 0,
        }
        
        return analysis

    def get_ai_effectiveness(self) -> Dict:
        """Efectividad de las predicciones de IA"""
        
        if not self.predictions:
            return {'status': 'no_predictions_yet'}
        
        correct = sum(1 for p in self.predictions if p.get('result') == 'correct')
        total = len(self.predictions)
        
        return {
            'total_predictions': total,
            'correct': correct,
            'accuracy': correct / total if total > 0 else 0,
            'avg_confidence': sum(p.get('confidence', 0) for p in self.predictions) / total if total > 0 else 0,
        }

    def get_summary(self) -> Dict:
        """Resumen del dashboard"""
        return {
            'name': self.name,
            'version': self.version,
            'current_metrics': self.current_metrics,
            'events_count': len(self.events),
            'trades_count': len(self.trades),
            'predictions_count': len(self.predictions),
            'optimizations_count': len(self.optimizations),
            'status': 'ACTIVE'
        }


# Singleton
_dashboard = None


def get_ai_dashboard() -> AITradingDashboard:
    global _dashboard
    if _dashboard is None:
        _dashboard = AITradingDashboard()
    return _dashboard


if __name__ == "__main__":
    # Demo del dashboard
    dashboard = get_ai_dashboard()
    
    # Simular algunos eventos
    dashboard.update_trade({
        'asset': 'EURJPY-OTC',
        'direction': 'PUT',
        'result': 'HOLD',
        'pnl': 43.09
    })
    
    dashboard.update_prediction({
        'asset': 'GBPUSD-OTC',
        'direction': 'CALL',
        'confidence': 75
    })
    
    # Mostrar dashboard
    print(dashboard.display_dashboard())
    print(json.dumps(dashboard.get_summary(), indent=2))
