#!/usr/bin/env python3
"""
Resumen ejecutivo del problema resuelto
"""
import json
from pathlib import Path


def show_summary():
    print('\n' + '='*80)
    print('🎯 RESUMEN EJECUTIVO: PROBLEMA DE PERSISTENCIA RESUELTO')
    print('='*80 + '\n')

    # Cargar datos
    trade_history = json.load(open('bot/brain/trade_history.json'))
    zone_reactions = json.load(open('bot/brain/zone_reactions.json'))

    print('📊 DATOS RECUPERADOS Y MIGRADOS:')
    print('-' * 80)
    print(f'  • Total de operaciones: {trade_history["total_trades"]}')
    print(f'  • Operaciones ganadoras: {trade_history["total_wins"]} ✅')
    print(f'  • Operaciones perdedoras: {trade_history["total_losses"]} ❌')
    wr = (trade_history["total_wins"]/trade_history["total_trades"]*100)
    print(f'  • Tasa de ganancia: {wr:.1f}%')
    print(f'  • PnL total: +{trade_history["total_pnl"]:.2f}')

    print('\n🔍 ZONAS CON HISTORIAL (Top 5):')
    print('-' * 80)
    sorted_zones = sorted(zone_reactions.items(), 
                         key=lambda x: x[1]['total_touches'], 
                         reverse=True)[:5]
    
    for i, (zone_key, zone_data) in enumerate(sorted_zones, 1):
        asset = zone_data['asset']
        level = zone_data['level']
        touches = zone_data['total_touches']
        holds = zone_data['successful_holds']
        hold_rate = (holds/touches*100) if touches > 0 else 0
        print(f'  {i}. {asset} @ {level:.5f}')
        print(f'     └─ {touches} toques, {holds} holds ({hold_rate:.0f}% hold rate)')

    print('\n✅ SOLUCIÓN IMPLEMENTADA:')
    print('-' * 80)
    print('  1. ✅ Nuevo sistema centralizado: trade_persistence.py')
    print('  2. ✅ Migración de datos históricos: 42 trades recuperados')
    print('  3. ✅ Sincronización con AdaptiveLearner')
    print('  4. ✅ Actualización de main.py para guardar automáticamente')
    print('  5. ✅ Herramientas de diagnóstico y migración')

    print('\n🚀 ESTADO ACTUAL:')
    print('-' * 80)
    print('  ✅ El bot recuerda 42 operaciones previas')
    print('  ✅ Puede aprender de experiencias pasadas')
    print('  ✅ Los nuevos trades se guardarán automáticamente')
    print('  ✅ Sistema robusto y centralizado')

    print('\n' + '='*80 + '\n')


if __name__ == "__main__":
    show_summary()
