# -*- coding: utf-8 -*-
"""
📊 DATA ANALYZER - Análisis de datos guardados
Analiza trades, patrones, activos y rendimiento
"""
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

class DataAnalyzer:
    """Analiza datos de trades guardados"""
    
    def __init__(self, data_dir='data'):
        self.data_dir = Path(data_dir)
        self.trades_file = self.data_dir / 'trades_all.json'
    
    def load_trades(self):
        """Carga todos los trades"""
        try:
            if self.trades_file.exists():
                return json.loads(self.trades_file.read_text())
            return []
        except Exception as e:
            print(f"[ERROR] Error cargando trades: {e}")
            return []
    
    def analyze_by_asset(self):
        """Analiza rendimiento por activo"""
        trades = self.load_trades()
        analysis = defaultdict(lambda: {
            'total': 0, 'wins': 0, 'losses': 0, 'draws': 0,
            'pnl': 0.0, 'win_rate': 0.0
        })
        
        for trade in trades:
            asset = trade.get('asset', 'UNKNOWN')
            result = trade.get('result', 'DRAW')
            pnl = trade.get('pnl', 0)
            
            analysis[asset]['total'] += 1
            analysis[asset]['pnl'] += pnl
            
            if result == 'WIN':
                analysis[asset]['wins'] += 1
            elif result == 'LOSS':
                analysis[asset]['losses'] += 1
            else:
                analysis[asset]['draws'] += 1
        
        # Calcular win rate
        for asset in analysis:
            total = analysis[asset]['total']
            if total > 0:
                analysis[asset]['win_rate'] = analysis[asset]['wins'] / total
        
        return dict(analysis)
    
    def analyze_by_pattern(self):
        """Analiza rendimiento por patrón"""
        trades = self.load_trades()
        analysis = defaultdict(lambda: {
            'total': 0, 'wins': 0, 'losses': 0, 'draws': 0,
            'pnl': 0.0, 'win_rate': 0.0
        })
        
        for trade in trades:
            pattern = trade.get('pattern', 'none')
            result = trade.get('result', 'DRAW')
            pnl = trade.get('pnl', 0)
            
            analysis[pattern]['total'] += 1
            analysis[pattern]['pnl'] += pnl
            
            if result == 'WIN':
                analysis[pattern]['wins'] += 1
            elif result == 'LOSS':
                analysis[pattern]['losses'] += 1
            else:
                analysis[pattern]['draws'] += 1
        
        # Calcular win rate
        for pattern in analysis:
            total = analysis[pattern]['total']
            if total > 0:
                analysis[pattern]['win_rate'] = analysis[pattern]['wins'] / total
        
        return dict(analysis)
    
    def analyze_by_hour(self):
        """Analiza rendimiento por hora"""
        trades = self.load_trades()
        analysis = defaultdict(lambda: {
            'total': 0, 'wins': 0, 'losses': 0, 'draws': 0,
            'pnl': 0.0, 'win_rate': 0.0
        })
        
        for trade in trades:
            try:
                timestamp = trade.get('timestamp', '')
                if timestamp:
                    hour = timestamp.split('T')[1].split(':')[0]
                    result = trade.get('result', 'DRAW')
                    pnl = trade.get('pnl', 0)
                    
                    analysis[hour]['total'] += 1
                    analysis[hour]['pnl'] += pnl
                    
                    if result == 'WIN':
                        analysis[hour]['wins'] += 1
                    elif result == 'LOSS':
                        analysis[hour]['losses'] += 1
                    else:
                        analysis[hour]['draws'] += 1
            except:
                pass
        
        # Calcular win rate
        for hour in analysis:
            total = analysis[hour]['total']
            if total > 0:
                analysis[hour]['win_rate'] = analysis[hour]['wins'] / total
        
        return dict(sorted(analysis.items()))
    
    def get_summary(self):
        """Obtiene resumen general"""
        trades = self.load_trades()
        
        if not trades:
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'draws': 0,
                'win_rate': 0.0,
                'pnl': 0.0,
                'best_trade': None,
                'worst_trade': None,
                'avg_pnl': 0.0,
                'consecutive_losses': 0,
                'best_streak': 0,
            }
        
        wins = len([t for t in trades if t.get('result') == 'WIN'])
        losses = len([t for t in trades if t.get('result') == 'LOSS'])
        draws = len([t for t in trades if t.get('result') == 'DRAW'])
        pnl = sum([t.get('pnl', 0) for t in trades])
        
        best_trade = max(trades, key=lambda x: x.get('pnl', 0))
        worst_trade = min(trades, key=lambda x: x.get('pnl', 0))
        
        return {
            'total_trades': len(trades),
            'wins': wins,
            'losses': losses,
            'draws': draws,
            'win_rate': wins / len(trades) if trades else 0,
            'pnl': pnl,
            'best_trade': best_trade,
            'worst_trade': worst_trade,
            'avg_pnl': pnl / len(trades) if trades else 0,
            'profit_factor': sum([t.get('pnl', 0) for t in trades if t.get('pnl', 0) > 0]) / 
                           abs(sum([t.get('pnl', 0) for t in trades if t.get('pnl', 0) < 0])) 
                           if sum([t.get('pnl', 0) for t in trades if t.get('pnl', 0) < 0]) != 0 else 0,
        }
    
    def get_top_assets(self, limit=10):
        """Obtiene activos con mejor rendimiento"""
        analysis = self.analyze_by_asset()
        sorted_assets = sorted(
            analysis.items(),
            key=lambda x: x[1]['pnl'],
            reverse=True
        )
        return sorted_assets[:limit]
    
    def get_worst_assets(self, limit=10):
        """Obtiene activos con peor rendimiento"""
        analysis = self.analyze_by_asset()
        sorted_assets = sorted(
            analysis.items(),
            key=lambda x: x[1]['pnl']
        )
        return sorted_assets[:limit]
    
    def get_top_patterns(self, limit=10):
        """Obtiene patrones con mejor rendimiento"""
        analysis = self.analyze_by_pattern()
        sorted_patterns = sorted(
            analysis.items(),
            key=lambda x: x[1]['win_rate'],
            reverse=True
        )
        return sorted_patterns[:limit]
    
    def generate_analysis_report(self):
        """Genera reporte de análisis completo"""
        report = {
            'generated_at': datetime.now().isoformat(),
            'summary': self.get_summary(),
            'by_asset': self.analyze_by_asset(),
            'by_pattern': self.analyze_by_pattern(),
            'by_hour': self.analyze_by_hour(),
            'top_assets': dict(self.get_top_assets()),
            'worst_assets': dict(self.get_worst_assets()),
            'top_patterns': dict(self.get_top_patterns()),
        }
        
        # Guardar reporte
        report_file = self.data_dir / f'analysis_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        report_file.write_text(json.dumps(report, indent=2))
        
        return report

# Singleton
_analyzer = None

def get_data_analyzer():
    """Obtiene instancia singleton de DataAnalyzer"""
    global _analyzer
    if _analyzer is None:
        _analyzer = DataAnalyzer()
    return _analyzer
