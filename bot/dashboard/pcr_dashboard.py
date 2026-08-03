"""
PCR Dashboard - Panel de Control para monitoreo en tiempo real
Compatible con Easy Panel, OpenCore y sistemas de monitoreo
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List
import json


class PCRDashboard:
    """
    Dashboard profesional para monitoreo de estrategia PCR
    Proporciona métricas, alertas y visualizaciones
    """

    def __init__(self, asset_name: str = None):
        self.asset_name = asset_name
        self.trades = []
        self.signals = []
        self.performance_history = []

    def add_trade(self, trade_data: Dict):
        """Registra un trade ejecutado"""
        self.trades.append({
            'timestamp': datetime.now().isoformat(),
            **trade_data
        })
        self._update_performance()

    def add_signal(self, signal_data: Dict):
        """Registra una señal generada"""
        self.signals.append({
            'timestamp': datetime.now().isoformat(),
            **signal_data
        })

    def get_live_metrics(self) -> Dict:
        """Retorna métricas en tiempo real"""
        if not self.trades:
            return {
                'trades': 0,
                'wins': 0,
                'losses': 0,
                'wr': 0,
                'pnl': 0,
                'status': 'SIN_DATOS'
            }

        df = pd.DataFrame(self.trades)
        total = len(df)
        wins = len(df[df['result'] == 'WIN'])
        losses = len(df[df['result'] == 'LOSS'])
        wr = (wins / total * 100) if total > 0 else 0
        pnl = df['pnl'].sum()

        status = 'OK' if wr >= 54.4 else 'ALERTA' if wr >= 50 else 'CRITICO'

        return {
            'timestamp': datetime.now().isoformat(),
            'asset': self.asset_name,
            'trades': total,
            'wins': wins,
            'losses': losses,
            'wr': round(wr, 1),
            'pnl': round(pnl, 2),
            'status': status,
            'viable': wr >= 54.4
        }

    def get_trade_history(self, limit: int = 50) -> List[Dict]:
        """Retorna últimos trades"""
        return self.trades[-limit:]

    def get_signal_history(self, limit: int = 100) -> List[Dict]:
        """Retorna últimas señales"""
        return self.signals[-limit:]

    def get_performance_summary(self) -> Dict:
        """Resumen de desempeño"""
        if not self.trades:
            return {}

        df = pd.DataFrame(self.trades)

        # Métricas por tipo de señal
        calls = df[df['signal'] == 'CALL']
        puts = df[df['signal'] == 'PUT']

        metrics = {
            'general': {
                'total_trades': len(df),
                'total_pnl': round(df['pnl'].sum(), 2),
                'wr': round((len(df[df['result'] == 'WIN']) / len(df) * 100), 1) if len(df) > 0 else 0,
            },
            'calls': {
                'count': len(calls),
                'wr': round((len(calls[calls['result'] == 'WIN']) / len(calls) * 100), 1) if len(calls) > 0 else 0,
                'pnl': round(calls['pnl'].sum(), 2) if len(calls) > 0 else 0,
            },
            'puts': {
                'count': len(puts),
                'wr': round((len(puts[puts['result'] == 'WIN']) / len(puts) * 100), 1) if len(puts) > 0 else 0,
                'pnl': round(puts['pnl'].sum(), 2) if len(puts) > 0 else 0,
            }
        }

        return metrics

    def get_alerts(self) -> List[Dict]:
        """Genera alertas basadas en desempeño"""
        alerts = []
        metrics = self.get_live_metrics()

        if metrics['status'] == 'CRITICO':
            alerts.append({
                'level': 'CRITICO',
                'message': f"WR muy baja: {metrics['wr']}% < 54.4%",
                'action': 'REVISAR_CONFIGURACION'
            })

        if metrics['wr'] < 50 and metrics['trades'] >= 30:
            alerts.append({
                'level': 'ALERTA',
                'message': f"Consistencia cuestionable con {metrics['trades']} trades",
                'action': 'MONITOREO'
            })

        if metrics['pnl'] < -100:
            alerts.append({
                'level': 'CRITICO',
                'message': f"PnL negativo: ${metrics['pnl']}",
                'action': 'PAUSE_TRADING'
            })

        # Verificar consecutivos
        if len(self.trades) >= 5:
            last_5 = self.trades[-5:]
            losses_count = len([t for t in last_5 if t['result'] == 'LOSS'])

            if losses_count == 5:
                alerts.append({
                    'level': 'CRITICO',
                    'message': "5 pérdidas consecutivas",
                    'action': 'PAUSE_TRADING'
                })

        return alerts

    def get_dashboard_json(self) -> str:
        """Retorna dashboard completo como JSON (para Easy Panel)"""
        return json.dumps({
            'timestamp': datetime.now().isoformat(),
            'asset': self.asset_name,
            'live_metrics': self.get_live_metrics(),
            'performance': self.get_performance_summary(),
            'alerts': self.get_alerts(),
            'recent_trades': self.get_trade_history(10),
            'recent_signals': self.get_signal_history(20)
        }, indent=2, default=str)

    def print_dashboard(self):
        """Imprime dashboard en consola"""
        metrics = self.get_live_metrics()
        performance = self.get_performance_summary()
        alerts = self.get_alerts()

        print(f"\n{'='*80}")
        print(f"📊 PCR DASHBOARD - {self.asset_name or 'GENERAL'}")
        print(f"{'='*80}")

        # Status
        status_icon = "🟢" if metrics['status'] == 'OK' else "🟡" if metrics['status'] == 'ALERTA' else "🔴"
        print(f"\n{status_icon} STATUS: {metrics['status']}")
        print(f"   Viable: {'✅' if metrics['viable'] else '❌'}")

        # Métricas principales
        print(f"\n📈 MÉTRICAS")
        print(f"{'-'*80}")
        print(f"  Trades:      {metrics['trades']}")
        print(f"  Wins:        {metrics['wins']} ({metrics['wr']}%)")
        print(f"  Losses:      {metrics['losses']}")
        print(f"  PnL:         ${metrics['pnl']}")

        # Por tipo de señal
        if performance:
            print(f"\n📊 DESEMPEÑO POR SEÑAL")
            print(f"{'-'*80}")

            calls = performance.get('calls', {})
            puts = performance.get('puts', {})

            print(f"  CALL:  {calls.get('count', 0)} trades, {calls.get('wr', 0)}% WR, ${calls.get('pnl', 0)} PnL")
            print(f"  PUT:   {puts.get('count', 0)} trades, {puts.get('wr', 0)}% WR, ${puts.get('pnl', 0)} PnL")

        # Alertas
        if alerts:
            print(f"\n⚠️  ALERTAS")
            print(f"{'-'*80}")
            for alert in alerts:
                icon = "🔴" if alert['level'] == 'CRITICO' else "🟡"
                print(f"  {icon} [{alert['level']}] {alert['message']}")
                print(f"     → Acción: {alert['action']}")
        else:
            print(f"\n✅ Sin alertas")

        print(f"\n{'='*80}")

    def export_for_easy_panel(self, filepath: str = 'pcr_dashboard.json'):
        """Exporta dashboard para Easy Panel"""
        with open(filepath, 'w') as f:
            f.write(self.get_dashboard_json())
        print(f"✓ Dashboard exportado a {filepath}")

    def get_html_dashboard(self) -> str:
        """Genera HTML para visualizar en navegador"""
        metrics = self.get_live_metrics()
        performance = self.get_performance_summary()

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>PCR Dashboard - {self.asset_name}</title>
            <style>
                body {{ font-family: Arial, sans-serif; background: #1a1a1a; color: #fff; margin: 0; padding: 20px; }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                .header {{ text-align: center; margin-bottom: 30px; }}
                .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 30px; }}
                .metric {{ background: #2a2a2a; padding: 20px; border-radius: 5px; text-align: center; }}
                .metric-value {{ font-size: 28px; font-weight: bold; margin: 10px 0; }}
                .metric-label {{ font-size: 12px; color: #aaa; }}
                .metric.good {{ border-left: 4px solid #4CAF50; }}
                .metric.warning {{ border-left: 4px solid #FFC107; }}
                .metric.danger {{ border-left: 4px solid #F44336; }}
                .status {{ text-align: center; font-size: 24px; margin: 20px 0; }}
                .status.good {{ color: #4CAF50; }}
                .status.warning {{ color: #FFC107; }}
                .status.danger {{ color: #F44336; }}
                .chart {{ background: #2a2a2a; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
                h1 {{ margin: 0; }}
                .timestamp {{ font-size: 12px; color: #666; text-align: right; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>PCR Strategy Dashboard</h1>
                    <p>{self.asset_name or 'All Assets'}</p>
                    <div class="timestamp">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
                </div>

                <div class="status {'good' if metrics['viable'] else 'danger'}">
                    {'✅ VIABLE' if metrics['viable'] else '❌ NO VIABLE'}
                </div>

                <div class="metrics">
                    <div class="metric {'good' if metrics['wr'] >= 54.4 else 'danger'}">
                        <div class="metric-label">Win Rate</div>
                        <div class="metric-value">{metrics['wr']}%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Trades</div>
                        <div class="metric-value">{metrics['trades']}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">PnL</div>
                        <div class="metric-value">${metrics['pnl']}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Wins/Losses</div>
                        <div class="metric-value">{metrics['wins']}/{metrics['losses']}</div>
                    </div>
                </div>

                <div class="chart">
                    <h3>Performance by Signal Type</h3>
                    <p>CALL: {performance.get('calls', {}).get('count', 0)} trades @ {performance.get('calls', {}).get('wr', 0)}% WR</p>
                    <p>PUT: {performance.get('puts', {}).get('count', 0)} trades @ {performance.get('puts', {}).get('wr', 0)}% WR</p>
                </div>
            </div>
        </body>
        </html>
        """

        return html

    def export_html(self, filepath: str = 'pcr_dashboard.html'):
        """Exporta dashboard como HTML"""
        with open(filepath, 'w') as f:
            f.write(self.get_html_dashboard())
        print(f"✓ Dashboard HTML exportado a {filepath}")
