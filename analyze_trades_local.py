#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Análisis de trades locales para identificar patrones ganadores y perdedores
"""
import json
import sys

# Leer el archivo de trades
with open('bot/brain/trade_history.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

trades = data['trades']

# Análisis por patrón
patterns = {}
for trade in trades:
    pattern = trade.get('pattern', 'none')
    if pattern not in patterns:
        patterns[pattern] = {'wins': 0, 'losses': 0, 'total_pnl': 0, 'trades': []}
    
    result = trade['result']
    pnl = trade['pnl']
    
    if result == 'WIN':
        patterns[pattern]['wins'] += 1
    else:
        patterns[pattern]['losses'] += 1
    
    patterns[pattern]['total_pnl'] += pnl
    patterns[pattern]['trades'].append(trade)

# Análisis por dirección
directions = {}
for trade in trades:
    direction = trade.get('direction', 'UNKNOWN')
    if direction not in directions:
        directions[direction] = {'wins': 0, 'losses': 0, 'total_pnl': 0}
    
    result = trade['result']
    pnl = trade['pnl']
    
    if result == 'WIN':
        directions[direction]['wins'] += 1
    else:
        directions[direction]['losses'] += 1
    
    directions[direction]['total_pnl'] += pnl

# Análisis por trend_aligned
trend_aligned_stats = {'aligned': {'wins': 0, 'losses': 0, 'pnl': 0}, 'not_aligned': {'wins': 0, 'losses': 0, 'pnl': 0}}
for trade in trades:
    aligned = trade.get('trend_aligned', False)
    result = trade['result']
    pnl = trade['pnl']
    
    key = 'aligned' if aligned else 'not_aligned'
    if result == 'WIN':
        trend_aligned_stats[key]['wins'] += 1
    else:
        trend_aligned_stats[key]['losses'] += 1
    trend_aligned_stats[key]['pnl'] += pnl

# Mostrar análisis
print('=' * 100)
print('ANÁLISIS DE PATRONES - 265 TRADES')
print('=' * 100)
print()

for pattern in sorted(patterns.keys(), key=lambda x: patterns[x]['wins'] / (patterns[x]['wins'] + patterns[x]['losses']) if (patterns[x]['wins'] + patterns[x]['losses']) > 0 else 0, reverse=True):
    p = patterns[pattern]
    total = p['wins'] + p['losses']
    wr = (p['wins'] / total * 100) if total > 0 else 0
    avg_pnl = p['total_pnl'] / total if total > 0 else 0
    
    status = '✅' if wr >= 50 else '❌'
    print(f'{status} {pattern:25} | Trades: {total:3} | W: {p["wins"]:3} L: {p["losses"]:3} | WR: {wr:5.1f}% | PnL: ${p["total_pnl"]:8.2f} | Avg: ${avg_pnl:6.2f}')

print()
print('=' * 100)
print('ANÁLISIS POR DIRECCIÓN')
print('=' * 100)
print()

for direction in sorted(directions.keys()):
    d = directions[direction]
    total = d['wins'] + d['losses']
    wr = (d['wins'] / total * 100) if total > 0 else 0
    avg_pnl = d['total_pnl'] / total if total > 0 else 0
    
    status = '✅' if wr >= 50 else '❌'
    print(f'{status} {direction:10} | Trades: {total:3} | W: {d["wins"]:3} L: {d["losses"]:3} | WR: {wr:5.1f}% | PnL: ${d["total_pnl"]:8.2f} | Avg: ${avg_pnl:6.2f}')

print()
print('=' * 100)
print('ANÁLISIS POR TREND ALIGNED')
print('=' * 100)
print()

for key in ['aligned', 'not_aligned']:
    t = trend_aligned_stats[key]
    total = t['wins'] + t['losses']
    wr = (t['wins'] / total * 100) if total > 0 else 0
    avg_pnl = t['pnl'] / total if total > 0 else 0
    
    status = '✅' if wr >= 50 else '❌'
    label = 'Trend Aligned' if key == 'aligned' else 'Trend NOT Aligned'
    print(f'{status} {label:20} | Trades: {total:3} | W: {t["wins"]:3} L: {t["losses"]:3} | WR: {wr:5.1f}% | PnL: ${t["pnl"]:8.2f} | Avg: ${avg_pnl:6.2f}')

print()
print('=' * 100)
print('RESUMEN GENERAL')
print('=' * 100)
print(f'Total Trades: {data["total_trades"]}')
print(f'Wins: {data["total_wins"]}')
print(f'Losses: {data["total_losses"]}')
print(f'Win Rate: {(data["total_wins"] / data["total_trades"] * 100):.1f}%')
print(f'Total PnL: ${data["total_pnl"]:.2f}')
print()

# Identificar patrones peligrosos
print('=' * 100)
print('PATRONES PELIGROSOS (WR < 50%)')
print('=' * 100)
print()

bad_patterns = []
for pattern in patterns.keys():
    p = patterns[pattern]
    total = p['wins'] + p['losses']
    wr = (p['wins'] / total * 100) if total > 0 else 0
    if wr < 50 and total >= 5:  # Al menos 5 trades
        bad_patterns.append((pattern, wr, p['total_pnl'], total))

for pattern, wr, pnl, total in sorted(bad_patterns, key=lambda x: x[1]):
    print(f'❌ {pattern:25} | WR: {wr:5.1f}% | PnL: ${pnl:8.2f} | Trades: {total}')

print()
print('=' * 100)
print('RECOMENDACIONES')
print('=' * 100)
print()
print('1. RECHAZAR COMPLETAMENTE estos patrones:')
for pattern, wr, pnl, total in sorted(bad_patterns, key=lambda x: x[1])[:5]:
    print(f'   - {pattern} (WR: {wr:.1f}%, PnL: ${pnl:.2f})')

print()
print('2. FAVORECER estos patrones:')
good_patterns = []
for pattern in patterns.keys():
    p = patterns[pattern]
    total = p['wins'] + p['losses']
    wr = (p['wins'] / total * 100) if total > 0 else 0
    if wr >= 55 and total >= 5:
        good_patterns.append((pattern, wr, p['total_pnl'], total))

for pattern, wr, pnl, total in sorted(good_patterns, key=lambda x: x[1], reverse=True)[:5]:
    print(f'   - {pattern} (WR: {wr:.1f}%, PnL: ${pnl:.2f})')
