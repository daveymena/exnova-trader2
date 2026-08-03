"""
PCR Backtest - Prueba de estrategias PCR simple y completa
Genera reportes comparativos de rendimiento en activos reales
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import sys
import os
from pathlib import Path

# Agregar ruta del bot
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.pcr_simple import PCRSimple
from strategies.pcr_complete import PCRComplete


class PCRBacktester:
    """Backtester para estrategias PCR"""

    def __init__(self, initial_balance=1000, payout_ratio=0.838, position_size=10):
        """
        Args:
            initial_balance: Saldo inicial
            payout_ratio: Ratio de payout (0.838 = 83.8%)
            position_size: Tamaño de cada posición en $
        """
        self.initial_balance = initial_balance
        self.payout_ratio = payout_ratio
        self.position_size = position_size
        self.current_balance = initial_balance

        self.pcr_simple = PCRSimple()
        self.pcr_complete = PCRComplete()

        self.trades_simple = []
        self.trades_complete = []

    def load_data(self, filepath, asset_name=None):
        """Carga datos OHLCV desde CSV"""
        try:
            df = pd.read_csv(filepath)

            # Normalizar nombres de columnas
            df.columns = [col.lower().strip() for col in df.columns]

            # Verificar que tenga las columnas necesarias
            required = ['open', 'high', 'low', 'close']
            if not all(col in df.columns for col in required):
                print(f"❌ {filepath}: columnas faltantes. Tiene: {list(df.columns)}")
                return None

            # Convertir a numérico
            for col in required:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            # Eliminar NaN
            df = df.dropna(subset=required)

            if df.empty:
                print(f"❌ {filepath}: sin datos válidos")
                return None

            print(f"✓ Cargado: {asset_name or filepath} ({len(df)} velas)")
            return df

        except Exception as e:
            print(f"❌ Error cargando {filepath}: {e}")
            return None

    def backtest_strategy(self, df, strategy_class, strategy_name, asset_name):
        """
        Realiza backtesting de una estrategia

        Args:
            df: DataFrame OHLCV
            strategy_class: Clase de estrategia (PCRSimple o PCRComplete)
            strategy_name: Nombre de estrategia
            asset_name: Nombre del activo

        Returns:
            dict con resultados
        """
        strategy = strategy_class()
        trades = []
        signals_count = {'CALL': 0, 'PUT': 0, 'NONE': 0}

        # Backtesting secuencial
        for i in range(max(50, len(df) // 3), len(df)):
            # Usar datos hasta index i
            df_slice = df.iloc[:i+1].copy()

            # Analizar con estrategia
            analysis = strategy.analyze(df_slice)

            if analysis is None:
                continue

            signal = analysis.get('signal')
            confidence = analysis.get('confidence', 0)
            price = analysis.get('close', 0)

            if not signal:
                signals_count['NONE'] += 1
                continue

            # Registrar señal
            signals_count[signal] += 1

            # Simular trade
            # En binarias: si signal es correcto (precio sube en CALL, baja en PUT) = WIN
            # Miramos la próxima vela
            if i + 1 < len(df):
                next_close = df.iloc[i + 1]['close']

                # Determinar resultado
                if signal == 'CALL':
                    win = next_close > price
                elif signal == 'PUT':
                    win = next_close < price
                else:
                    win = False

                # Calcular PnL
                if win:
                    pnl = self.position_size * self.payout_ratio
                else:
                    pnl = -self.position_size

                trade = {
                    'index': i,
                    'timestamp': df.iloc[i].get('timestamp', i),
                    'asset': asset_name,
                    'signal': signal,
                    'confidence': confidence,
                    'entry_price': price,
                    'exit_price': next_close,
                    'direction': 'UP' if signal == 'CALL' else 'DOWN',
                    'result': 'WIN' if win else 'LOSS',
                    'pnl': pnl,
                    'reasons': analysis.get('reasons', [])
                }

                trades.append(trade)

        # Calcular estadísticas
        stats = self._calculate_stats(trades, asset_name)

        return {
            'strategy_name': strategy_name,
            'asset': asset_name,
            'trades': trades,
            'signals_count': signals_count,
            'stats': stats
        }

    def _calculate_stats(self, trades, asset_name):
        """Calcula estadísticas de trades"""
        if not trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'pnl': 0,
                'avg_pnl': 0,
                'sharpe': 0,
                'max_loss': 0,
                'message': 'Sin operaciones'
            }

        df_trades = pd.DataFrame(trades)

        total_trades = len(trades)
        wins = len(df_trades[df_trades['result'] == 'WIN'])
        losses = len(df_trades[df_trades['result'] == 'LOSS'])
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        total_pnl = df_trades['pnl'].sum()
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

        # Sharpe Ratio
        pnls = df_trades['pnl'].values
        if len(pnls) > 1 and pnls.std() > 0:
            sharpe = pnls.mean() / pnls.std() * np.sqrt(252)
        else:
            sharpe = 0

        # Drawdown
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = running_max - cumulative
        max_drawdown = np.max(drawdown) if len(drawdown) > 0 else 0

        return {
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 2),
            'total_pnl': round(total_pnl, 2),
            'avg_pnl': round(avg_pnl, 2),
            'sharpe': round(sharpe, 2),
            'max_drawdown': round(max_drawdown, 2),
            'required_wr': 54.4,  # Para 0.838 payout
            'meets_requirement': win_rate >= 54.4
        }

    def generate_report(self, results_simple, results_complete):
        """Genera reporte comparativo"""
        print("\n" + "="*80)
        print("📊 REPORTE COMPARATIVO PCR - SIMPLE vs COMPLETO")
        print("="*80)

        for asset in set([r['asset'] for r in results_simple + results_complete]):
            print(f"\n🎯 ACTIVO: {asset}")
            print("-" * 80)

            # Buscar resultados de este activo
            simple = next((r for r in results_simple if r['asset'] == asset), None)
            complete = next((r for r in results_complete if r['asset'] == asset), None)

            if simple:
                self._print_strategy_result(simple, "PCR SIMPLE")

            if complete:
                self._print_strategy_result(complete, "PCR COMPLETO")

            # Comparación
            if simple and complete:
                print(f"\n{'Comparación':^40}")
                print("-" * 40)

                s_wr = simple['stats'].get('win_rate', 0)
                c_wr = complete['stats'].get('win_rate', 0)
                winner = "SIMPLE" if s_wr > c_wr else "COMPLETO" if c_wr > s_wr else "EMPATE"

                print(f"WR Ganador: {winner}")
                print(f"  Simple:   {s_wr}%")
                print(f"  Completo: {c_wr}%")

                s_pnl = simple['stats'].get('total_pnl', 0)
                c_pnl = complete['stats'].get('total_pnl', 0)
                print(f"\nPnL:")
                print(f"  Simple:   ${s_pnl}")
                print(f"  Completo: ${c_pnl}")

    def _print_strategy_result(self, result, strategy_name):
        """Imprime resultado de estrategia"""
        stats = result['stats']

        print(f"\n{strategy_name}:")
        print(f"  Trades: {stats['total_trades']} ({result['signals_count']['CALL']} CALL, {result['signals_count']['PUT']} PUT)")
        print(f"  WR:     {stats['win_rate']}% (requerido: {stats['required_wr']}%)")

        status = "✓" if stats['meets_requirement'] else "✗"
        print(f"  {status} Viable: {stats['meets_requirement']}")

        print(f"  PnL:    ${stats['total_pnl']} (promedio ${stats['avg_pnl']}/trade)")
        print(f"  Sharpe: {stats['sharpe']}")
        print(f"  MaxDD:  ${stats['max_drawdown']}")

    def run_backtest_real_assets(self, data_dir='bot/data/real_assets'):
        """Ejecuta backtest en todos los activos reales disponibles"""
        if not os.path.exists(data_dir):
            print(f"❌ Directorio no encontrado: {data_dir}")
            print(f"📁 Buscando datos en el proyecto...")
            return

        print(f"\n🔍 Buscando datos en: {data_dir}")

        results_simple = []
        results_complete = []

        # Buscar archivos CSV
        csv_files = list(Path(data_dir).glob('*.csv'))
        if not csv_files:
            print(f"⚠️  No hay archivos CSV en {data_dir}")
            return

        for csv_file in sorted(csv_files):
            asset_name = csv_file.stem.upper()
            df = self.load_data(str(csv_file), asset_name)

            if df is None or len(df) < 100:
                continue

            print(f"\n📊 Backtesting {asset_name}...")

            # PCR Simple
            result_simple = self.backtest_strategy(
                df, PCRSimple, "PCR Simple", asset_name
            )
            results_simple.append(result_simple)

            # PCR Complete
            result_complete = self.backtest_strategy(
                df, PCRComplete, "PCR Complete", asset_name
            )
            results_complete.append(result_complete)

        # Generar reporte
        if results_simple or results_complete:
            self.generate_report(results_simple, results_complete)

            # Guardar resultados en JSON
            output_file = 'pcr_backtest_results.json'
            with open(output_file, 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'simple': results_simple,
                    'complete': results_complete
                }, f, indent=2, default=str)
            print(f"\n✓ Resultados guardados en {output_file}")
        else:
            print("\n⚠️  No se generaron resultados")


def main():
    """Punto de entrada"""
    print("🚀 PCR Backtest - Pruebas de estrategia")
    print("="*80)

    backtester = PCRBacktester(
        initial_balance=1000,
        payout_ratio=0.838,
        position_size=10
    )

    # Intenta encontrar datos locales
    data_paths = [
        'bot/data/real_assets',
        'bot/data',
        'data',
        './data'
    ]

    for data_path in data_paths:
        if os.path.exists(data_path):
            print(f"📁 Usando datos de: {data_path}")
            backtester.run_backtest_real_assets(data_path)
            break
    else:
        print(f"⚠️  No se encontró directorio de datos")
        print(f"\nPara probar, coloca archivos CSV en uno de estos directorios:")
        for p in data_paths:
            print(f"  - {p}")
        print(f"\nFormato esperado: open, high, low, close (mínimo)")


if __name__ == '__main__':
    main()
