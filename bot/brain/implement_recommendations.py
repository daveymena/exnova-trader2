#!/usr/bin/env python3
"""
Implementar recomendaciones automáticamente basadas en análisis de trades
"""
import json
from pathlib import Path


def implement_recommendations():
    """Implementa las recomendaciones en la configuración del bot"""
    
    print('\n' + '='*100)
    print('🔧 IMPLEMENTANDO RECOMENDACIONES AUTOMÁTICAMENTE')
    print('='*100 + '\n')
    
    # Cargar configuración actual
    config_path = Path('bot/config.py')
    
    recommendations = {
        'AUDUSD-OTC': {
            'action': 'PAUSAR',
            'reason': '10% WR, -0.51 PnL',
            'implementation': 'Agregar a lista negra de activos'
        },
        'EURJPY-OTC': {
            'action': 'PRIORIZAR',
            'reason': '55.6% WR, +146.71 PnL',
            'implementation': 'Aumentar volumen y reducir requisitos'
        },
        'GBPUSD-OTC': {
            'action': 'PRIORIZAR',
            'reason': '80% WR, +0.74 PnL',
            'implementation': 'Aumentar volumen'
        },
        'EURUSD-OTC': {
            'action': 'PRIORIZAR',
            'reason': '75% WR, +0.50 PnL',
            'implementation': 'Aumentar volumen'
        },
    }
    
    print('📋 RECOMENDACIONES A IMPLEMENTAR:\n')
    
    for asset, rec in recommendations.items():
        print(f'  {asset}:')
        print(f'    • Acción: {rec["action"]}')
        print(f'    • Razón: {rec["reason"]}')
        print(f'    • Implementación: {rec["implementation"]}\n')
    
    # Crear archivo de configuración de recomendaciones
    recommendations_config = {
        'version': '1.0',
        'generated': '2026-05-17',
        'based_on_trades': 42,
        'win_rate': 0.524,
        'pnl_total': 160.15,
        
        # Activos a pausar
        'paused_assets': ['AUDUSD-OTC'],
        
        # Activos prioritarios
        'priority_assets': {
            'EURJPY-OTC': {
                'priority': 1,
                'reason': 'Mejor PnL absoluto',
                'volume_multiplier': 1.5,
                'min_validation': 0.6,
            },
            'GBPUSD-OTC': {
                'priority': 2,
                'reason': 'Mejor win rate',
                'volume_multiplier': 1.3,
                'min_validation': 0.65,
            },
            'EURUSD-OTC': {
                'priority': 3,
                'reason': 'Confiable',
                'volume_multiplier': 1.2,
                'min_validation': 0.65,
            },
        },
        
        # Mejoras de validación
        'validation_improvements': {
            'require_pattern': True,
            'pattern_confidence_min': 0.65,
            'rsi_extremes_only': True,
            'rsi_min': 30,
            'rsi_max': 70,
            'zone_hold_rate_min': 0.70,
            'zone_touches_min': 5,
            'prefer_revisits': True,
            'revisit_confidence_boost': 0.05,
        },
        
        # Tendencia
        'trend_settings': {
            'review_needed': True,
            'current_issue': 'Ganancias ocurren 86.4% contra tendencia',
            'recommendation': 'Revisar lógica o invertir',
        },
        
        # Métricas objetivo
        'target_metrics': {
            'win_rate': 0.55,
            'pnl_per_trade': 5.0,
            'eurjpy_wr': 0.60,
            'audusd_status': 'PAUSED',
        }
    }
    
    # Guardar configuración
    config_file = Path('bot/brain/recommendations_config.json')
    with open(config_file, 'w') as f:
        json.dump(recommendations_config, f, indent=2)
    
    print(f'✅ Configuración guardada en: {config_file}\n')
    
    # Mostrar resumen de cambios
    print('📊 RESUMEN DE CAMBIOS:\n')
    print('  1. ❌ PAUSAR AUDUSD-OTC')
    print('     └─ Razón: 10% WR, -0.51 PnL')
    print('     └─ Impacto: Elimina 10 operaciones de alto riesgo\n')
    
    print('  2. ✅ PRIORIZAR EURJPY-OTC')
    print('     └─ Razón: 55.6% WR, +146.71 PnL')
    print('     └─ Acción: Aumentar volumen 1.5x\n')
    
    print('  3. ✅ PRIORIZAR GBPUSD-OTC')
    print('     └─ Razón: 80% WR, +0.74 PnL')
    print('     └─ Acción: Aumentar volumen 1.3x\n')
    
    print('  4. ✅ PRIORIZAR EURUSD-OTC')
    print('     └─ Razón: 75% WR, +0.50 PnL')
    print('     └─ Acción: Aumentar volumen 1.2x\n')
    
    print('  5. 🔧 MEJORAR VALIDACIÓN')
    print('     └─ Requerir patrón específico')
    print('     └─ RSI solo en extremos (< 30 o > 70)')
    print('     └─ Zona con hold rate > 70%')
    print('     └─ Zona con 5+ toques\n')
    
    print('  6. 🔍 REVISAR TENDENCIA')
    print('     └─ Problema: 86.4% ganancias contra tendencia')
    print('     └─ Acción: Revisar lógica o invertir\n')
    
    print('='*100)
    print('✅ RECOMENDACIONES IMPLEMENTADAS')
    print('='*100 + '\n')
    
    return recommendations_config


if __name__ == "__main__":
    config = implement_recommendations()
