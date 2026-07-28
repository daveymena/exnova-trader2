# -*- coding: utf-8 -*-
"""
💾 DATA SAVER - Guardado de datos para análisis
Registra todos los trades, señales y métricas para análisis posterior
"""
import os
import json
import csv
from datetime import datetime
from pathlib import Path

class DataSaver:
    """Guarda datos de trades para análisis"""
    
    def __init__(self, data_dir='data'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        # Crear subdirectorios
        self.trades_dir = self.data_dir / 'trades'
        self.signals_dir = self.data_dir / 'signals'
        self.metrics_dir = self.data_dir / 'metrics'
        self.analysis_dir = self.data_dir / 'analysis'
        
        for d in [self.trades_dir, self.signals_dir, self.metrics_dir, self.analysis_dir]:
            d.mkdir(exist_ok=True)
        
        # Archivos principales
        self.trades_json = self.data_dir / 'trades_all.json'
        self.trades_csv = self.data_dir / 'trades_all.csv'
        self.signals_json = self.data_dir / 'signals_all.json'
        self.metrics_json = self.data_dir / 'metrics_current.json'
        
        # Inicializar archivos si no existen
        self._init_files()
    
    def _init_files(self):
        """Inicializa archivos si no existen"""
        if not self.trades_json.exists():
            self.trades_json.write_text(json.dumps([], indent=2))
        
        if not self.signals_json.exists():
            self.signals_json.write_text(json.dumps([], indent=2))
        
        if not self.metrics_json.exists():
            self.metrics_json.write_text(json.dumps({
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'draws': 0,
                'win_rate': 0.0,
                'pnl': 0.0,
                'balance': 0.0,
                'last_updated': datetime.now().isoformat(),
            }, indent=2))
    
    def save_trade(self, trade_data):
        """Guarda un trade individual"""
        try:
            # Agregar timestamp si no existe
            if 'timestamp' not in trade_data:
                trade_data['timestamp'] = datetime.now().isoformat()
            
            # Guardar en JSON
            trades = json.loads(self.trades_json.read_text())
            trades.append(trade_data)
            self.trades_json.write_text(json.dumps(trades, indent=2))
            
            # Guardar en CSV
            self._append_to_csv(trade_data)
            
            # Guardar en archivo diario
            self._save_daily_trade(trade_data)
            
            return True
        except Exception as e:
            print(f"[ERROR] Error guardando trade: {e}")
            return False
    
    def _append_to_csv(self, trade_data):
        """Agrega trade a CSV"""
        try:
            file_exists = self.trades_csv.exists()
            
            with open(self.trades_csv, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=[
                    'timestamp', 'asset', 'direction', 'amount', 'confidence',
                    'result', 'pnl', 'pattern', 'zone_strength', 'order_id',
                    'entry_price', 'expiration_minutes', 'rsi_at_entry',
                    'trend_m15', 'trend_aligned', 'ai_approved', 'ai_confidence'
                ])
                
                if not file_exists:
                    writer.writeheader()
                
                writer.writerow(trade_data)
        except Exception as e:
            print(f"[ERROR] Error guardando en CSV: {e}")
    
    def _save_daily_trade(self, trade_data):
        """Guarda trade en archivo diario"""
        try:
            date_str = datetime.now().strftime('%Y-%m-%d')
            daily_file = self.trades_dir / f'trades_{date_str}.json'
            
            if daily_file.exists():
                trades = json.loads(daily_file.read_text())
            else:
                trades = []
            
            trades.append(trade_data)
            daily_file.write_text(json.dumps(trades, indent=2))
        except Exception as e:
            print(f"[ERROR] Error guardando trade diario: {e}")
    
    def save_signal(self, signal_data):
        """Guarda una señal"""
        try:
            if 'timestamp' not in signal_data:
                signal_data['timestamp'] = datetime.now().isoformat()
            
            signals = json.loads(self.signals_json.read_text())
            signals.append(signal_data)
            self.signals_json.write_text(json.dumps(signals, indent=2))
            
            return True
        except Exception as e:
            print(f"[ERROR] Error guardando señal: {e}")
            return False
    
    def update_metrics(self, metrics):
        """Actualiza métricas actuales"""
        try:
            metrics['last_updated'] = datetime.now().isoformat()
            self.metrics_json.write_text(json.dumps(metrics, indent=2))
            
            # Guardar snapshot diario
            self._save_daily_metrics(metrics)
            
            return True
        except Exception as e:
            print(f"[ERROR] Error actualizando métricas: {e}")
            return False
    
    def _save_daily_metrics(self, metrics):
        """Guarda snapshot de métricas diarias"""
        try:
            date_str = datetime.now().strftime('%Y-%m-%d')
            daily_file = self.metrics_dir / f'metrics_{date_str}.json'
            
            if daily_file.exists():
                daily_metrics = json.loads(daily_file.read_text())
            else:
                daily_metrics = []
            
            daily_metrics.append(metrics)
            daily_file.write_text(json.dumps(daily_metrics, indent=2))
        except Exception as e:
            print(f"[ERROR] Error guardando métricas diarias: {e}")
    
    def get_trades(self, limit=None):
        """Obtiene todos los trades"""
        try:
            trades = json.loads(self.trades_json.read_text())
            if limit:
                return trades[-limit:]
            return trades
        except Exception as e:
            print(f"[ERROR] Error leyendo trades: {e}")
            return []
    
    def get_signals(self, limit=None):
        """Obtiene todas las señales"""
        try:
            signals = json.loads(self.signals_json.read_text())
            if limit:
                return signals[-limit:]
            return signals
        except Exception as e:
            print(f"[ERROR] Error leyendo señales: {e}")
            return []
    
    def get_metrics(self):
        """Obtiene métricas actuales"""
        try:
            return json.loads(self.metrics_json.read_text())
        except Exception as e:
            print(f"[ERROR] Error leyendo métricas: {e}")
            return {}
    
    def generate_daily_report(self):
        """Genera reporte diario"""
        try:
            date_str = datetime.now().strftime('%Y-%m-%d')
            report_file = self.analysis_dir / f'report_{date_str}.json'
            
            trades = self.get_trades()
            today_trades = [t for t in trades if t.get('timestamp', '').startswith(date_str)]
            
            if not today_trades:
                return None
            
            wins = len([t for t in today_trades if t.get('result') == 'WIN'])
            losses = len([t for t in today_trades if t.get('result') == 'LOSS'])
            draws = len([t for t in today_trades if t.get('result') == 'DRAW'])
            pnl = sum([t.get('pnl', 0) for t in today_trades])
            
            report = {
                'date': date_str,
                'total_trades': len(today_trades),
                'wins': wins,
                'losses': losses,
                'draws': draws,
                'win_rate': wins / len(today_trades) if today_trades else 0,
                'pnl': pnl,
                'best_trade': max(today_trades, key=lambda x: x.get('pnl', 0)) if today_trades else None,
                'worst_trade': min(today_trades, key=lambda x: x.get('pnl', 0)) if today_trades else None,
                'generated_at': datetime.now().isoformat(),
            }
            
            report_file.write_text(json.dumps(report, indent=2))
            return report
        except Exception as e:
            print(f"[ERROR] Error generando reporte: {e}")
            return None

# Singleton
_data_saver = None

def get_data_saver():
    """Obtiene instancia singleton de DataSaver"""
    global _data_saver
    if _data_saver is None:
        _data_saver = DataSaver()
    return _data_saver
