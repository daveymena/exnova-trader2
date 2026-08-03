"""
PCR Exhaustive Backtest - Backtesting exhaustivo y riguroso
Prueba múltiples configuraciones, combinaciones y validadores
Genera reportes de consistencia y resistencia
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import json
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.pcr_simple import PCRSimple
from strategies.pcr_complete import PCRComplete
from strategies.pcr_hybrid import PCRHybrid
from strategies.pcr_validator_gates import PCRValidatorGates


class PCRExhaustiveBacktest:
    """
    Backtester exhaustivo que realiza:
    - Pruebas de múltiples configuraciones
    - Stress testing (volatilidad extrema)
    - Análisis de consistencia
    - Validación de resistencia
    - Generación de métricas profesionales
    """

    def __init__(self, payout_ratio=0.838, position_size=10):
        self.payout_ratio = payout_ratio
        self.position_size = position_size
        self.results = {}

    def generate_synthetic_data(self, n_candles=1000, scenario='normal',
                               volatility_multiplier=1.0) -> pd.DataFrame:
        """
        Genera datos sintéticos para diferentes escenarios

        Args:
            n_candles: Número de velas
            scenario: 'normal', 'uptrend', 'downtrend', 'extreme_volatility', 'consolidation'
            volatility_multiplier: Multiplicador de volatilidad
        """
        base_price = 100.0
        prices = [base_price]

        for i in range(n_candles):
            # Drift según escenario
            if scenario == 'uptrend':
                drift = 0.003
            elif scenario == 'downtrend':
                drift = -0.003
            elif scenario == 'extreme_volatility':
                drift = 0.001
            elif scenario == 'consolidation':
                drift = 0.0001  # Muy lateral
            else:  # normal
                drift = 0.001

            # Volatilidad
            base_vol = 0.005 * volatility_multiplier
            change = np.random.normal(drift, base_vol)
            new_price = prices[-1] * (1 + change)
            prices.append(new_price)

        # Convertir a OHLCV
        data = []
        for i in range(n_candles):
            open_p = prices[i]
            close_p = prices[i + 1]
            high_p = max(open_p, close_p) * (1 + abs(np.random.normal(0, 0.001)))
            low_p = min(open_p, close_p) * (1 - abs(np.random.normal(0, 0.001)))

            data.append({
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': close_p,
                'volume': np.random.randint(1000, 10000)
            })

        return pd.DataFrame(data)

    def backtest_strategy(self, df: pd.DataFrame, strategy_class,
                         strategy_name: str, strict_validation=False) -> Dict:
        """
        Backtea una estrategia

        Args:
            df: DataFrame OHLCV
            strategy_class: Clase de estrategia (PCRSimple, PCRComplete, PCRHybrid)
            strategy_name: Nombre
            strict_validation: Si True, usa validación estricta

        Returns:
            dict con resultados detallados
        """
        strategy = strategy_class()
        trades = []
        signals = {'CALL': 0, 'PUT': 0, 'REJECTED': 0}

        test_start = max(50, len(df) // 4)

        for i in range(test_start, len(df)):
            df_slice = df.iloc[:i+1].copy()

            # Analizar
            if isinstance(strategy, PCRHybrid):
                analysis = strategy.analyze(df_slice, strict=strict_validation)
                signal = analysis['hybrid'].get('signal')
                confidence = analysis['hybrid'].get('confidence', 0)
            else:
                analysis = strategy.analyze(df_slice)
                signal = analysis.get('signal')
                confidence = analysis.get('confidence', 0)

            if not signal:
                signals['REJECTED'] += 1
                continue

            signals[signal] += 1

            # Simular trade
            if i + 1 < len(df):
                current_price = df.iloc[i]['close']
                next_price = df.iloc[i + 1]['close']

                # Resultado
                if signal == 'CALL':
                    win = next_price > current_price
                else:  # PUT
                    win = next_price < current_price

                pnl = self.position_size * self.payout_ratio if win else -self.position_size

                trades.append({
                    'index': i,
                    'signal': signal,
                    'confidence': confidence,
                    'entry': current_price,
                    'exit': next_price,
                    'result': 'WIN' if win else 'LOSS',
                    'pnl': pnl
                })

        # Calcular estadísticas
        stats = self._calculate_stats(trades)

        return {
            'strategy': strategy_name,
            'trades': trades,
            'signals': signals,
            'stats': stats
        }

    def _calculate_stats(self, trades: List[Dict]) -> Dict:
        """Calcula métricas profesionales"""
        if not trades:
            return {
                'total': 0,
                'wins': 0,
                'losses': 0,
                'wr': 0,
                'pnl': 0,
                'sharpe': 0,
                'dd': 0,
                'consecutive_wins': 0,
                'consecutive_losses': 0
            }

        df_trades = pd.DataFrame(trades)
        total = len(trades)
        wins = len(df_trades[df_trades['result'] == 'WIN'])
        losses = len(df_trades[df_trades['result'] == 'LOSS'])
        wr = (wins / total * 100) if total > 0 else 0

        pnls = df_trades['pnl'].values
        total_pnl = pnls.sum()

        # Sharpe Ratio
        if len(pnls) > 1 and pnls.std() > 0:
            sharpe = (pnls.mean() / pnls.std()) * np.sqrt(252)
        else:
            sharpe = 0

        # Drawdown
        cumulative = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = running_max - cumulative
        max_dd = np.max(drawdown) if len(drawdown) > 0 else 0

        # Rachas
        results = df_trades['result'].values
        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0

        for r in results:
            if r == 'WIN':
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)

        return {
            'total': total,
            'wins': wins,
            'losses': losses,
            'wr': round(wr, 1),
            'pnl': round(total_pnl, 2),
            'sharpe': round(sharpe, 2),
            'dd': round(max_dd, 2),
            'consecutive_wins': max_wins,
            'consecutive_losses': max_losses,
            'viable': wr >= 54.4
        }

    def run_exhaustive_testing(self) -> Dict:
        """
        Ejecuta suite completa de pruebas exhaustivas
        """
        print("\n" + "="*80)
        print("🔬 PRUEBAS EXHAUSTIVAS PCR - SISTEMA COMPLETO")
        print("="*80)

        scenarios = {
            'normal': ('Mercado Normal', 1.0),
            'uptrend': ('Tendencia Alcista', 1.0),
            'downtrend': ('Tendencia Bajista', 1.0),
            'extreme_volatility': ('Volatilidad Extrema', 2.5),
            'consolidation': ('Consolidación', 0.5)
        }

        all_results = {}

        for scenario_key, (scenario_name, vol_mult) in scenarios.items():
            print(f"\n📊 ESCENARIO: {scenario_name}")
            print(f"{'-'*80}")

            df = self.generate_synthetic_data(n_candles=1000, scenario=scenario_key,
                                            volatility_multiplier=vol_mult)

            scenario_results = {}

            # Probar Simple
            simple_result = self.backtest_strategy(df, PCRSimple, 'PCR Simple')
            scenario_results['simple'] = simple_result
            self._print_result(simple_result)

            # Probar Complete
            complete_result = self.backtest_strategy(df, PCRComplete, 'PCR Complete')
            scenario_results['complete'] = complete_result
            self._print_result(complete_result)

            # Probar Hybrid
            hybrid_result = self.backtest_strategy(df, PCRHybrid, 'PCR Hybrid')
            scenario_results['hybrid'] = hybrid_result
            self._print_result(hybrid_result)

            # Probar Hybrid Estricto
            hybrid_strict_result = self.backtest_strategy(df, PCRHybrid, 'PCR Hybrid (Strict)',
                                                         strict_validation=True)
            scenario_results['hybrid_strict'] = hybrid_strict_result
            self._print_result(hybrid_strict_result)

            all_results[scenario_key] = scenario_results

        # Resumen comparativo
        self._print_comparative_summary(all_results)

        return all_results

    def _print_result(self, result: Dict):
        """Imprime resultado de backtesting"""
        stats = result['stats']
        strategy = result['strategy']
        signals = result['signals']

        total_sigs = signals['CALL'] + signals['PUT']
        status = "✅" if stats['viable'] else "❌"

        print(f"\n  {strategy:<25}")
        print(f"    Trades:    {stats['total']} ({signals['CALL']} CALL, {signals['PUT']} PUT)")
        print(f"    WR:        {stats['wr']}% {status} (req: 54.4%)")
        print(f"    PnL:       ${stats['pnl']}")
        print(f"    Sharpe:    {stats['sharpe']}")
        print(f"    MaxDD:     ${stats['dd']}")
        print(f"    Max Rachas: {stats['consecutive_wins']}W / {stats['consecutive_losses']}L")

    def _print_comparative_summary(self, all_results: Dict):
        """Imprime resumen comparativo de todos los escenarios"""
        print(f"\n\n{'='*80}")
        print(f"📈 RESUMEN COMPARATIVO - TODOS LOS ESCENARIOS")
        print(f"{'='*80}")

        strategies = ['simple', 'complete', 'hybrid', 'hybrid_strict']
        scenarios = list(all_results.keys())

        # Tabla WR
        print(f"\n📊 WIN RATE % (Requerido: 54.4%)")
        print(f"{'-'*80}")
        print(f"{'Escenario':<20}", end='')
        for strat in strategies:
            print(f"{strat:<15}", end='')
        print()

        for scenario in scenarios:
            print(f"{scenario:<20}", end='')
            for strat in strategies:
                wr = all_results[scenario][strat]['stats']['wr']
                status = "✓" if wr >= 54.4 else "✗"
                print(f"{wr:>5.1f}% {status:<8}", end='')
            print()

        # Tabla PnL
        print(f"\n💰 PnL TOTAL")
        print(f"{'-'*80}")
        print(f"{'Escenario':<20}", end='')
        for strat in strategies:
            print(f"{strat:<15}", end='')
        print()

        for scenario in scenarios:
            print(f"{scenario:<20}", end='')
            for strat in strategies:
                pnl = all_results[scenario][strat]['stats']['pnl']
                print(f"${pnl:>8.2f}    ", end='')
            print()

        # Ranking
        print(f"\n🏆 RANKING DE VIABILIDAD")
        print(f"{'-'*80}")

        viable_count = {}
        for strat in strategies:
            count = sum(1 for scenario in scenarios
                       if all_results[scenario][strat]['stats']['viable'])
            viable_count[strat] = count

        sorted_strats = sorted(viable_count.items(), key=lambda x: x[1], reverse=True)

        for i, (strat, count) in enumerate(sorted_strats, 1):
            percentage = (count / len(scenarios)) * 100
            print(f"{i}. {strat:<20} {count}/{len(scenarios)} escenarios ({percentage:.0f}%)")

        # Conclusiones
        print(f"\n{'='*80}")
        print(f"📋 CONCLUSIONES")
        print(f"{'='*80}")

        best_strat = sorted_strats[0][0]
        best_count = sorted_strats[0][1]

        print(f"\n✅ ESTRATEGIA RECOMENDADA: {best_strat.upper()}")
        print(f"   Viable en {best_count}/{len(scenarios)} escenarios")
        print(f"   Resistencia: {'ALTA' if best_count == len(scenarios) else 'MEDIA' if best_count >= 3 else 'BAJA'}")

        # Guardar resultados
        output_file = 'pcr_exhaustive_results.json'
        with open(output_file, 'w') as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"\n✓ Resultados guardados en {output_file}")


def main():
    """Punto de entrada"""
    backtester = PCRExhaustiveBacktest()
    results = backtester.run_exhaustive_testing()

    print(f"\n{'='*80}")
    print("🚀 PRUEBAS COMPLETADAS")
    print(f"{'='*80}")
    print(f"\nPróximo paso: Descargar datos REALES de Exnova")
    print(f"  python scripts/fetch_history.py --assets USSPX500:N,US30:N --days 180")
    print(f"  python bot/backtest/pcr_backtest.py")


if __name__ == '__main__':
    main()
