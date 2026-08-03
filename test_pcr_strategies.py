#!/usr/bin/env python3
"""
Script de prueba rápida de estrategias PCR
Genera datos de prueba sintéticos y ejecuta backtest
"""
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

# Agregar rutas
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

from strategies.pcr_simple import PCRSimple
from strategies.pcr_complete import PCRComplete


def generate_synthetic_data(n_candles=500, trend='UP', volatility=0.005):
    """
    Genera datos OHLCV sintéticos para pruebas

    Args:
        n_candles: Número de velas
        trend: 'UP', 'DOWN', o 'SIDEWAYS'
        volatility: Volatilidad (0.005 = 0.5%)
    """
    base_price = 100.0
    prices = [base_price]

    # Generar movimiento de precios
    for i in range(n_candles):
        # Drift según tendencia
        if trend == 'UP':
            drift = 0.002
        elif trend == 'DOWN':
            drift = -0.002
        else:  # SIDEWAYS
            drift = 0

        # Random walk con drift
        change = np.random.normal(drift, volatility)
        new_price = prices[-1] * (1 + change)
        prices.append(new_price)

    # Convertir a OHLCV
    data = []
    start_time = datetime.now() - timedelta(hours=n_candles)

    for i in range(n_candles):
        # Dentro de cada vela: open, high, low, close
        open_price = prices[i]
        close_price = prices[i + 1]

        intra_high = max(open_price, close_price) * (1 + abs(np.random.normal(0, 0.001)))
        intra_low = min(open_price, close_price) * (1 - abs(np.random.normal(0, 0.001)))

        data.append({
            'timestamp': start_time + timedelta(hours=i),
            'open': open_price,
            'high': intra_high,
            'low': intra_low,
            'close': close_price,
            'volume': np.random.randint(1000, 10000)
        })

    return pd.DataFrame(data)


def test_strategy_on_data(strategy_class, strategy_name, df, asset_name):
    """
    Prueba una estrategia en datos
    """
    print(f"\n{'='*70}")
    print(f"🎯 {strategy_name.upper()} - {asset_name}")
    print(f"{'='*70}")

    strategy = strategy_class()
    signals_count = {'CALL': 0, 'PUT': 0, 'NONE': 0}
    winning_trades = 0
    total_trades = 0

    # Prueba en cada vela
    test_start = max(50, len(df) // 3)  # Espera datos suficientes

    for i in range(test_start, len(df)):
        df_slice = df.iloc[:i+1].copy()

        # Analizar
        analysis = strategy.analyze(df_slice)

        if analysis is None:
            continue

        signal = analysis.get('signal')
        confidence = analysis.get('confidence', 0)
        price = analysis.get('close', 0)

        if not signal:
            signals_count['NONE'] += 1
            continue

        signals_count[signal] += 1

        # Verificar resultado en próxima vela
        if i + 1 < len(df):
            next_close = df.iloc[i + 1]['close']

            if signal == 'CALL':
                result = next_close > price
            elif signal == 'PUT':
                result = next_close < price
            else:
                result = False

            if result:
                winning_trades += 1

            total_trades += 1

            # Mostrar señal de muestra
            if i == test_start or (i % (len(df) // 10) == 0):
                status = "✓ WIN" if result else "✗ LOSS"
                print(f"  [{i:3d}] {signal:4s} @ {price:7.2f} -> {next_close:7.2f} | {status}")

    # Resultados
    print(f"\n📊 RESULTADOS:")
    print(f"  Señales: {signals_count['CALL']} CALL + {signals_count['PUT']} PUT = {total_trades} trades")

    if total_trades > 0:
        wr = (winning_trades / total_trades) * 100
        print(f"  Win Rate: {wr:.1f}% ({winning_trades}/{total_trades})")
        print(f"  Requerido: 54.4%")

        status = "✓ VIABLE" if wr >= 54.4 else "✗ No viable"
        print(f"  {status}")
    else:
        print(f"  ⚠️  Sin trades generados")

    return {
        'strategy': strategy_name,
        'asset': asset_name,
        'signals': signals_count,
        'total_trades': total_trades,
        'wins': winning_trades,
        'wr': (winning_trades / total_trades * 100) if total_trades > 0 else 0
    }


def main():
    """Prueba ambas estrategias en datos sintéticos"""
    print("\n🚀 PRUEBA DE ESTRATEGIAS PCR")
    print("="*70)
    print("Generando datos de prueba sintéticos...")

    # Generar 3 escenarios
    scenarios = [
        ('UPTREND_ASSET', generate_synthetic_data(500, trend='UP'), 'Tendencia Alcista'),
        ('DOWNTREND_ASSET', generate_synthetic_data(500, trend='DOWN'), 'Tendencia Bajista'),
        ('SIDEWAYS_ASSET', generate_synthetic_data(500, trend='SIDEWAYS'), 'Mercado Lateral'),
    ]

    results = []

    for asset_name, df, description in scenarios:
        print(f"\n📈 Escenario: {description} ({asset_name})")
        print(f"   Datos: {len(df)} velas")

        # Prueba PCR Simple
        result_simple = test_strategy_on_data(
            PCRSimple, "PCR Simple", df, asset_name
        )
        results.append(result_simple)

        # Prueba PCR Complete
        result_complete = test_strategy_on_data(
            PCRComplete, "PCR Complete", df, asset_name
        )
        results.append(result_complete)

    # Resumen final
    print(f"\n\n{'='*70}")
    print(f"📊 RESUMEN COMPARATIVO")
    print(f"{'='*70}")

    simple_results = [r for r in results if 'Simple' in r['strategy']]
    complete_results = [r for r in results if 'Complete' in r['strategy']]

    avg_wr_simple = np.mean([r['wr'] for r in simple_results]) if simple_results else 0
    avg_wr_complete = np.mean([r['wr'] for r in complete_results]) if complete_results else 0

    print(f"\nWin Rate Promedio:")
    print(f"  PCR Simple:   {avg_wr_simple:.1f}%")
    print(f"  PCR Complete: {avg_wr_complete:.1f}%")
    print(f"  Requerido:    54.4%")

    print(f"\n{'Strategy':<20} {'Asset':<20} {'WR':>8} {'Trades':>8} {'Status':>10}")
    print(f"{'-'*70}")

    for r in results:
        status = "✓ OK" if r['wr'] >= 54.4 else "✗ NO"
        print(f"{r['strategy']:<20} {r['asset']:<20} {r['wr']:>7.1f}% {r['total_trades']:>8} {status:>10}")

    print(f"\n✅ Pruebas completadas")
    print(f"   Estrategias implementadas: PCR Simple + PCR Complete")
    print(f"   Próximo paso: Descargar datos reales y backtesting completo")
    print(f"\n💡 Para descarga de datos reales:")
    print(f"   python scripts/fetch_history.py --assets USSPX500:N,US30:N --days 30")


if __name__ == '__main__':
    main()
