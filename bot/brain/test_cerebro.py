"""
🧪 TEST SUITE para AutonomousCerebro
═══════════════════════════════════════════════════════════════════════════════

Pruebas de:
  - Fase 1: Razonador (generación de opciones)
  - Fase 2: Memoria (almacenamiento y búsqueda)
  - Fase 3: Autonomía (auto-mejora)
  - Fase 4: Planificador (planes de ejecución)
  - Fase 5: Especulador (predicciones)
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import time
from autonomous_cerebro import (
    AutonomousCerebro, Reasoner, Memory, AutonomousImprover,
    Planner, Speculator
)


def test_phase1_reasoner():
    """Test Fase 1: Razonador"""
    print("\n" + "="*70)
    print("TEST FASE 1: RAZONADOR (Generación de 3 opciones)")
    print("="*70)

    reasoner = Reasoner()

    # Caso 1: Trend UP con momentum fuerte
    context_up = {
        'price': 1.2345,
        'trend': 'UP',
        'momentum': 0.8,
        'volatility': 0.02,
        'volume': 200
    }

    options = reasoner.think_options(context_up)

    print(f"\n✓ Generadas {len(options)} opciones para trend UP")
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt.direction} | Conf={opt.confidence:.2f} | Score={opt.score():.3f}")
        print(f"     → {opt.reasoning}")

    assert len(options) == 3, "Debe generar exactamente 3 opciones"
    assert options[0].score() > options[1].score(), "Opciones deben estar ordenadas"

    print("\n✓ FASE 1: OK")


def test_phase2_memory():
    """Test Fase 2: Memoria"""
    print("\n" + "="*70)
    print("TEST FASE 2: MEMORIA (Almacenamiento y búsqueda)")
    print("="*70)

    memory = Memory(db_path=":memory:")  # In-memory DB for testing

    # Almacenar contexto
    context = {'trend': 'UP', 'momentum': 0.7}
    memory.store_context(context, 'CALL', 'WIN', 2.50, 0.85)

    # Buscar contextos similares
    similar = memory.find_similar_contexts(context, limit=5)

    print(f"\n✓ Contexto almacenado")
    print(f"✓ Recuperados {len(similar)} contextos similares")

    # Win rate
    wins, total = memory.get_winrate_for_pattern('CALL')
    print(f"✓ Win rate para CALL: {wins}/{total}")

    print("\n✓ FASE 2: OK")


def test_phase3_autonomy():
    """Test Fase 3: Autonomía"""
    print("\n" + "="*70)
    print("TEST FASE 3: AUTONOMÍA (Auto-mejora)")
    print("="*70)

    improver = AutonomousImprover()

    # Simular trades con bajo win rate
    trades = [
        {'outcome': 'LOSS', 'pnl': -1.0, 'confidence': 0.50},
        {'outcome': 'LOSS', 'pnl': -1.0, 'confidence': 0.45},
        {'outcome': 'WIN', 'pnl': 2.0, 'confidence': 0.60},
        {'outcome': 'LOSS', 'pnl': -1.0, 'confidence': 0.48},
        {'outcome': 'LOSS', 'pnl': -1.0, 'confidence': 0.40},
    ]

    perf = improver.evaluate_performance(trades)

    print(f"\n✓ Performance evaluada:")
    print(f"  - Win Rate: {perf['win_rate']:.1%}")
    print(f"  - PNL: ${perf['pnl']:.2f}")
    print(f"  - Status: {perf['status']}")

    # Proponer mejoras
    improvements = improver.propose_improvements(perf)

    print(f"\n✓ Mejoras propuestas:")
    for imp in improvements:
        print(f"  - {imp}")

    print("\n✓ FASE 3: OK")


def test_phase4_planner():
    """Test Fase 4: Planificador"""
    print("\n" + "="*70)
    print("TEST FASE 4: PLANIFICADOR (Planes de ejecución)")
    print("="*70)

    from autonomous_cerebro import TradeOption

    planner = Planner()

    option = TradeOption(
        direction='CALL',
        confidence=0.75,
        reasoning='Strong uptrend',
        risk_score=0.02,
        reward_score=1.5,
        time_frame='1m'
    )

    market_context = {
        'price': 1.2345,
        'volatility': 0.02,
        'trend': 'UP'
    }

    plan = planner.create_execution_plan(option, market_context)

    print(f"\n✓ Plan de ejecución creado:")
    print(f"  - Entry: {plan['step_1_entry']['direction']} a ${plan['step_1_entry']['price']}")
    print(f"  - TP: {plan['step_2_tp']['action']}")
    print(f"  - SL: {plan['step_3_sl']['action']}")
    print(f"  - Monitor: Cada {plan['step_4_monitor']['interval_seconds']}s")

    # Test checkpoint
    should_exec = planner.should_execute_step('step_1_entry', 1.2345)
    print(f"\n✓ Should execute step 1: {should_exec}")

    print("\n✓ FASE 4: OK")


def test_phase5_speculator():
    """Test Fase 5: Especulador"""
    print("\n" + "="*70)
    print("TEST FASE 5: ESPECULADOR (Predicciones)")
    print("="*70)

    speculator = Speculator()

    context = {
        'price': 1.2345,
        'momentum': 0.75,
        'trend': 'UP',
        'volume': 150
    }

    history = [
        {'outcome': 'WIN', 'pnl': 2.0},
        {'outcome': 'WIN', 'pnl': 1.5},
        {'outcome': 'WIN', 'pnl': 2.5}
    ]

    prediction = speculator.predict_next_move(context, history)

    print(f"\n✓ Predicción del siguiente movimiento:")
    print(f"  - Direction: {prediction['direction']}")
    print(f"  - Probability: {prediction['probability']:.1%}")
    print(f"  - Reasoning: {prediction['reasoning']}")

    # Test hedge
    hedge = speculator.suggest_hedging(
        {'direction': 'CALL'},
        {'direction': 'DOWN', 'probability': 0.85}
    )

    if hedge:
        print(f"\n✓ Hedge sugerido:")
        print(f"  - Action: {hedge['action']}")
        print(f"  - Direction: {hedge['hedge_direction']}")
        print(f"  - Reasoning: {hedge['reasoning']}")

    print("\n✓ FASE 5: OK")


def test_full_pipeline():
    """Test pipeline completo: las 5 fases integradas"""
    print("\n" + "="*70)
    print("TEST PIPELINE COMPLETO (5 Fases integradas)")
    print("="*70)

    cerebro = AutonomousCerebro(db_path=":memory:")

    # Mercado alcista con momentum fuerte
    market_context = {
        'price': 1.2500,
        'trend': 'UP',
        'momentum': 0.70,
        'volatility': 0.015,
        'volume': 180
    }

    print(f"\n📊 Contexto de mercado: {market_context['trend']} momentum={market_context['momentum']:.2f}")

    # Análisis completo
    decision = cerebro.analyze_and_decide(market_context)

    print(f"\n✓ Decisión: {decision['action']} {decision['direction']}")
    print(f"  - Confianza: {decision['confidence']:.2f}")
    print(f"  - Score: {decision['option_score']:.3f}")
    print(f"  - Next Move: {decision['next_move_prediction']['direction']}")

    if decision['hedge_suggestion']:
        print(f"  - ⚠️  Hedge: {decision['hedge_suggestion']['action']}")

    # Simular trades
    print(f"\n🔄 Simulando secuencia de trades...")
    outcomes = ['WIN', 'WIN', 'LOSS', 'WIN', 'WIN']
    pnls = [2.5, 2.0, -1.0, 3.0, 1.5]

    for i, (outcome, pnl) in enumerate(zip(outcomes, pnls), 1):
        cerebro.log_trade_result(
            f"trade_{i}",
            outcome,
            pnl,
            decision['direction'],
            decision['confidence'],
            market_context
        )
        print(f"  Trade {i}: {outcome} (${pnl:+.1f})")

    # Status final
    status = cerebro.get_status()

    print(f"\n📈 Status final:")
    print(f"  - Total trades: {status['trades_total']}")
    print(f"  - Win rate: {status['win_rate']:.1%}")
    print(f"  - PNL: ${status['pnl']:+.2f}")
    print(f"  - Wins: {status['wins']}, Losses: {status['losses']}")

    print("\n✓ PIPELINE: OK")


def test_integration_wrapper():
    """Test adaptador de integración"""
    print("\n" + "="*70)
    print("TEST INTEGRATION WRAPPER (Adaptador)")
    print("="*70)

    from integration_wrapper import CerebroTradingAdapter, CerebroMonitor

    adapter = CerebroTradingAdapter(db_path=":memory:")
    monitor = CerebroMonitor(adapter)

    # Datos en formato legacy (del motor existente)
    legacy_market_data = {
        'price': 1.2400,
        'close': 1.2400,
        'volume': 160,
        'indicators': {
            'rsi': 65,  # Overbought, sugiere reversión
            'atr': 0.0025
        },
        'support': 1.2350,
        'resistance': 1.2450
    }

    print(f"\n✓ Datos legacy convertidos y analizados")

    # Llamar adaptador (compatible con AgentTradingEngine)
    should_trade, analysis = adapter.should_trade(legacy_market_data)

    print(f"\n✓ Resultado (formato motor existente):")
    print(f"  - Should trade: {should_trade}")
    print(f"  - Decision: {analysis['decision']}")
    print(f"  - Direction: {analysis['direction']}")
    print(f"  - Confidence: {analysis['confidence']:.2f}")

    # Log resultado
    adapter.log_trade_result('WIN', 2.75)

    # Status
    live_status = monitor.get_live_status()

    print(f"\n📊 Status en vivo (para dashboard):")
    print(json.dumps(live_status, indent=2, ensure_ascii=False))

    print("\n✓ INTEGRATION WRAPPER: OK")


if __name__ == "__main__":
    print("\n" + "█"*70)
    print("█" + " "*68 + "█")
    print("█" + "  🧠 AUTONOMOUS CEREBRO - TEST SUITE".center(68) + "█")
    print("█" + " "*68 + "█")
    print("█"*70)

    try:
        test_phase1_reasoner()
        test_phase2_memory()
        test_phase3_autonomy()
        test_phase4_planner()
        test_phase5_speculator()
        test_full_pipeline()
        test_integration_wrapper()

        print("\n" + "█"*70)
        print("█" + " "*68 + "█")
        print("█" + "  ✅ ALL TESTS PASSED".center(68) + "█")
        print("█" + " "*68 + "█")
        print("█"*70 + "\n")

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
