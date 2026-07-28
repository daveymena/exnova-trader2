#!/usr/bin/env python3
"""
Análisis detallado de operaciones - Identifica patrones de ganancia y pérdida
"""
import json
from pathlib import Path
from collections import defaultdict
import statistics


def analyze_trades():
    """Análisis completo de trades"""
    
    # Cargar datos
    with open('bot/brain/trade_history.json', 'r') as f:
        trade_data = json.load(f)
    
    trades = trade_data['trades']
    
    print('\n' + '='*100)
    print('📊 ANÁLISIS DETALLADO DE OPERACIONES')
    print('='*100 + '\n')
    
    # Separar ganancias y pérdidas
    wins = [t for t in trades if t['result'] == 'HOLD']
    losses = [t for t in trades if t['result'] == 'BREAK']
    
    print(f'📈 RESUMEN GENERAL:')
    print('-' * 100)
    print(f'  Total operaciones: {len(trades)}')
    print(f'  ✅ Ganancias (HOLD): {len(wins)} ({len(wins)/len(trades)*100:.1f}%)')
    print(f'  ❌ Pérdidas (BREAK): {len(losses)} ({len(losses)/len(trades)*100:.1f}%)')
    print(f'  💰 PnL total: +{sum(t["pnl"] for t in trades):.2f}')
    print(f'  📊 PnL promedio por trade: {sum(t["pnl"] for t in trades)/len(trades):.2f}')
    
    # Análisis de ganancias
    print(f'\n✅ ANÁLISIS DE OPERACIONES GANADORAS ({len(wins)} trades):')
    print('-' * 100)
    
    wins_pnl = [t['pnl'] for t in wins]
    print(f'  PnL total: +{sum(wins_pnl):.2f}')
    print(f'  PnL promedio: +{statistics.mean(wins_pnl):.2f}')
    print(f'  PnL máximo: +{max(wins_pnl):.2f}')
    print(f'  PnL mínimo: +{min(wins_pnl):.2f}')
    
    # Patrones en ganancias
    print(f'\n  📌 Patrones en ganancias:')
    pattern_wins = defaultdict(list)
    for t in wins:
        pattern = t.get('pattern', 'none')
        pattern_wins[pattern].append(t['pnl'])
    
    for pattern, pnls in sorted(pattern_wins.items(), key=lambda x: sum(x[1]), reverse=True):
        print(f'    • {pattern}: {len(pnls)} trades, +{sum(pnls):.2f} PnL, promedio +{statistics.mean(pnls):.2f}')
    
    # Sesiones en ganancias
    print(f'\n  🌍 Sesiones en ganancias:')
    session_wins = defaultdict(list)
    for t in wins:
        session = t.get('session', 'UNKNOWN')
        session_wins[session].append(t['pnl'])
    
    for session, pnls in sorted(session_wins.items(), key=lambda x: sum(x[1]), reverse=True):
        print(f'    • {session}: {len(pnls)} trades, +{sum(pnls):.2f} PnL, promedio +{statistics.mean(pnls):.2f}')
    
    # Activos en ganancias
    print(f'\n  💱 Activos en ganancias:')
    asset_wins = defaultdict(list)
    for t in wins:
        asset = t.get('asset', 'UNKNOWN')
        asset_wins[asset].append(t['pnl'])
    
    for asset, pnls in sorted(asset_wins.items(), key=lambda x: sum(x[1]), reverse=True):
        print(f'    • {asset}: {len(pnls)} trades, +{sum(pnls):.2f} PnL, promedio +{statistics.mean(pnls):.2f}')
    
    # RSI en ganancias
    print(f'\n  📈 RSI en ganancias:')
    rsi_values = [t.get('rsi_at_touch', 50) for t in wins]
    print(f'    • RSI promedio: {statistics.mean(rsi_values):.1f}')
    print(f'    • RSI mínimo: {min(rsi_values):.1f}')
    print(f'    • RSI máximo: {max(rsi_values):.1f}')
    
    # Trend aligned en ganancias
    trend_aligned_wins = len([t for t in wins if t.get('trend_aligned', False)])
    print(f'\n  🎯 Alineación con tendencia:')
    print(f'    • Con tendencia: {trend_aligned_wins}/{len(wins)} ({trend_aligned_wins/len(wins)*100:.1f}%)')
    print(f'    • Contra tendencia: {len(wins)-trend_aligned_wins}/{len(wins)} ({(len(wins)-trend_aligned_wins)/len(wins)*100:.1f}%)')
    
    # Análisis de pérdidas
    print(f'\n\n❌ ANÁLISIS DE OPERACIONES PERDEDORAS ({len(losses)} trades):')
    print('-' * 100)
    
    losses_pnl = [t['pnl'] for t in losses]
    print(f'  PnL total: {sum(losses_pnl):.2f}')
    print(f'  PnL promedio: {statistics.mean(losses_pnl):.2f}')
    print(f'  PnL máximo (menos pérdida): {max(losses_pnl):.2f}')
    print(f'  PnL mínimo (mayor pérdida): {min(losses_pnl):.2f}')
    
    # Patrones en pérdidas
    print(f'\n  📌 Patrones en pérdidas:')
    pattern_losses = defaultdict(list)
    for t in losses:
        pattern = t.get('pattern', 'none')
        pattern_losses[pattern].append(t['pnl'])
    
    for pattern, pnls in sorted(pattern_losses.items(), key=lambda x: sum(x[1])):
        print(f'    • {pattern}: {len(pnls)} trades, {sum(pnls):.2f} PnL, promedio {statistics.mean(pnls):.2f}')
    
    # Sesiones en pérdidas
    print(f'\n  🌍 Sesiones en pérdidas:')
    session_losses = defaultdict(list)
    for t in losses:
        session = t.get('session', 'UNKNOWN')
        session_losses[session].append(t['pnl'])
    
    for session, pnls in sorted(session_losses.items(), key=lambda x: sum(x[1])):
        print(f'    • {session}: {len(pnls)} trades, {sum(pnls):.2f} PnL, promedio {statistics.mean(pnls):.2f}')
    
    # Activos en pérdidas
    print(f'\n  💱 Activos en pérdidas:')
    asset_losses = defaultdict(list)
    for t in losses:
        asset = t.get('asset', 'UNKNOWN')
        asset_losses[asset].append(t['pnl'])
    
    for asset, pnls in sorted(asset_losses.items(), key=lambda x: sum(x[1])):
        print(f'    • {asset}: {len(pnls)} trades, {sum(pnls):.2f} PnL, promedio {statistics.mean(pnls):.2f}')
    
    # RSI en pérdidas
    print(f'\n  📈 RSI en pérdidas:')
    rsi_losses = [t.get('rsi_at_touch', 50) for t in losses]
    print(f'    • RSI promedio: {statistics.mean(rsi_losses):.1f}')
    print(f'    • RSI mínimo: {min(rsi_losses):.1f}')
    print(f'    • RSI máximo: {max(rsi_losses):.1f}')
    
    # Trend aligned en pérdidas
    trend_aligned_losses = len([t for t in losses if t.get('trend_aligned', False)])
    print(f'\n  🎯 Alineación con tendencia:')
    print(f'    • Con tendencia: {trend_aligned_losses}/{len(losses)} ({trend_aligned_losses/len(losses)*100:.1f}%)')
    print(f'    • Contra tendencia: {len(losses)-trend_aligned_losses}/{len(losses)} ({(len(losses)-trend_aligned_losses)/len(losses)*100:.1f}%)')
    
    # Análisis por activo
    print(f'\n\n📊 ANÁLISIS POR ACTIVO:')
    print('-' * 100)
    
    all_assets = set(t['asset'] for t in trades)
    for asset in sorted(all_assets):
        asset_trades = [t for t in trades if t['asset'] == asset]
        asset_wins = [t for t in asset_trades if t['result'] == 'HOLD']
        asset_losses = [t for t in asset_trades if t['result'] == 'BREAK']
        
        wr = len(asset_wins) / len(asset_trades) * 100 if asset_trades else 0
        pnl = sum(t['pnl'] for t in asset_trades)
        
        print(f'\n  {asset}:')
        print(f'    • Total: {len(asset_trades)} trades')
        print(f'    • Ganancias: {len(asset_wins)} ({wr:.1f}%)')
        print(f'    • Pérdidas: {len(asset_losses)} ({100-wr:.1f}%)')
        print(f'    • PnL: {pnl:+.2f}')
        
        if asset_wins:
            print(f'    • PnL promedio ganador: +{statistics.mean([t["pnl"] for t in asset_wins]):.2f}')
        if asset_losses:
            print(f'    • PnL promedio perdedor: {statistics.mean([t["pnl"] for t in asset_losses]):.2f}')
    
    # Problemas identificados
    print(f'\n\n🚨 PROBLEMAS IDENTIFICADOS:')
    print('-' * 100)
    
    # Activo con peor desempeño
    worst_asset = min(all_assets, key=lambda a: sum(t['pnl'] for t in trades if t['asset'] == a))
    worst_pnl = sum(t['pnl'] for t in trades if t['asset'] == worst_asset)
    worst_wr = len([t for t in trades if t['asset'] == worst_asset and t['result'] == 'HOLD']) / len([t for t in trades if t['asset'] == worst_asset]) * 100
    
    print(f'\n  1. ⚠️  ACTIVO CON PEOR DESEMPEÑO: {worst_asset}')
    print(f'     • PnL: {worst_pnl:.2f}')
    print(f'     • Win Rate: {worst_wr:.1f}%')
    print(f'     • Recomendación: REDUCIR OPERACIONES O PAUSAR EN ESTE ACTIVO')
    
    # Patrón con peor desempeño
    all_patterns = set(t.get('pattern', 'none') for t in trades)
    worst_pattern = min(all_patterns, key=lambda p: sum(t['pnl'] for t in trades if t.get('pattern', 'none') == p))
    worst_pattern_pnl = sum(t['pnl'] for t in trades if t.get('pattern', 'none') == worst_pattern)
    worst_pattern_wr = len([t for t in trades if t.get('pattern', 'none') == worst_pattern and t['result'] == 'HOLD']) / len([t for t in trades if t.get('pattern', 'none') == worst_pattern]) * 100 if [t for t in trades if t.get('pattern', 'none') == worst_pattern] else 0
    
    print(f'\n  2. ⚠️  PATRÓN CON PEOR DESEMPEÑO: {worst_pattern}')
    print(f'     • PnL: {worst_pattern_pnl:.2f}')
    print(f'     • Win Rate: {worst_pattern_wr:.1f}%')
    print(f'     • Recomendación: EVITAR O VALIDAR MEJOR ESTE PATRÓN')
    
    # Sesión con peor desempeño
    all_sessions = set(t.get('session', 'UNKNOWN') for t in trades)
    worst_session = min(all_sessions, key=lambda s: sum(t['pnl'] for t in trades if t.get('session', 'UNKNOWN') == s))
    worst_session_pnl = sum(t['pnl'] for t in trades if t.get('session', 'UNKNOWN') == worst_session)
    worst_session_wr = len([t for t in trades if t.get('session', 'UNKNOWN') == worst_session and t['result'] == 'HOLD']) / len([t for t in trades if t.get('session', 'UNKNOWN') == worst_session]) * 100 if [t for t in trades if t.get('session', 'UNKNOWN') == worst_session] else 0
    
    print(f'\n  3. ⚠️  SESIÓN CON PEOR DESEMPEÑO: {worst_session}')
    print(f'     • PnL: {worst_session_pnl:.2f}')
    print(f'     • Win Rate: {worst_session_wr:.1f}%')
    print(f'     • Recomendación: AJUSTAR PARÁMETROS PARA ESTA SESIÓN')
    
    # Recomendaciones
    print(f'\n\n💡 RECOMENDACIONES PARA EVITAR PÉRDIDAS:')
    print('-' * 100)
    
    print(f'\n  1. 🎯 ENFOCARSE EN LO QUE FUNCIONA:')
    best_asset = max(all_assets, key=lambda a: sum(t['pnl'] for t in trades if t['asset'] == a))
    best_asset_pnl = sum(t['pnl'] for t in trades if t['asset'] == best_asset)
    print(f'     • {best_asset} es el mejor activo (+{best_asset_pnl:.2f})')
    print(f'     • Aumentar volumen en este activo')
    
    best_pattern = max(all_patterns, key=lambda p: sum(t['pnl'] for t in trades if t.get('pattern', 'none') == p))
    best_pattern_pnl = sum(t['pnl'] for t in trades if t.get('pattern', 'none') == best_pattern)
    print(f'     • {best_pattern} es el mejor patrón (+{best_pattern_pnl:.2f})')
    print(f'     • Priorizar este patrón en las entradas')
    
    print(f'\n  2. ❌ EVITAR LO QUE NO FUNCIONA:')
    print(f'     • Reducir operaciones en {worst_asset} (PnL: {worst_pnl:.2f})')
    print(f'     • Validar mejor el patrón {worst_pattern} (PnL: {worst_pattern_pnl:.2f})')
    print(f'     • Ajustar parámetros en sesión {worst_session} (PnL: {worst_session_pnl:.2f})')
    
    print(f'\n  3. 📊 OPTIMIZAR RSI:')
    print(f'     • En ganancias: RSI promedio {statistics.mean(rsi_values):.1f}')
    print(f'     • En pérdidas: RSI promedio {statistics.mean(rsi_losses):.1f}')
    if statistics.mean(rsi_values) < statistics.mean(rsi_losses):
        print(f'     • Recomendación: Preferir RSI más bajo (menos extremo)')
    else:
        print(f'     • Recomendación: Preferir RSI más alto (más extremo)')
    
    print(f'\n  4. 🎯 TENDENCIA:')
    print(f'     • Ganancias con tendencia: {trend_aligned_wins/len(wins)*100:.1f}%')
    print(f'     • Pérdidas con tendencia: {trend_aligned_losses/len(losses)*100:.1f}%')
    if trend_aligned_wins/len(wins) > trend_aligned_losses/len(losses):
        print(f'     • Recomendación: PRIORIZAR OPERACIONES ALINEADAS CON TENDENCIA')
    else:
        print(f'     • Recomendación: REVISAR DETECCIÓN DE TENDENCIA')
    
    print(f'\n  5. 🔄 PRIMERAS VISITAS vs REVISITAS:')
    first_visit_wins = len([t for t in wins if t.get('was_first_visit', False)])
    first_visit_losses = len([t for t in losses if t.get('was_first_visit', False)])
    revisit_wins = len(wins) - first_visit_wins
    revisit_losses = len(losses) - first_visit_losses
    
    print(f'     • Primeras visitas: {first_visit_wins} wins, {first_visit_losses} losses ({first_visit_wins/(first_visit_wins+first_visit_losses)*100:.1f}% WR)')
    print(f'     • Revisitas: {revisit_wins} wins, {revisit_losses} losses ({revisit_wins/(revisit_wins+revisit_losses)*100:.1f}% WR)')
    
    if first_visit_wins/(first_visit_wins+first_visit_losses) > revisit_wins/(revisit_wins+revisit_losses):
        print(f'     • Recomendación: PREFERIR PRIMERAS VISITAS A ZONAS')
    else:
        print(f'     • Recomendación: REVISITAS SON MÁS CONFIABLES')
    
    print(f'\n' + '='*100 + '\n')


if __name__ == "__main__":
    analyze_trades()
