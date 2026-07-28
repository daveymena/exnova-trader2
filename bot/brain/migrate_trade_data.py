#!/usr/bin/env python3
"""
Migración de datos - Convierte zone_reactions.json a trade_history.json
Recupera los 42 trades que ya se han realizado
"""
import json
import os
from pathlib import Path
from datetime import datetime


def migrate_zone_reactions_to_trades():
    """
    Lee zone_reactions.json y crea trade_history.json con los datos históricos
    """
    print("\n" + "="*70)
    print("🔄 MIGRACIÓN DE DATOS: zone_reactions.json → trade_history.json")
    print("="*70 + "\n")
    
    zone_reactions_path = Path("bot/brain/zone_reactions.json")
    trade_history_path = Path("bot/brain/trade_history.json")
    
    if not zone_reactions_path.exists():
        print("❌ No se encontró zone_reactions.json")
        return False
    
    # Cargar zone_reactions
    with open(zone_reactions_path, 'r') as f:
        zone_reactions = json.load(f)
    
    # Convertir eventos de zonas a trades
    trades = []
    total_wins = 0
    total_losses = 0
    total_pnl = 0.0
    
    print(f"📊 Procesando {len(zone_reactions)} zonas con historial...\n")
    
    for zone_key, zone_data in zone_reactions.items():
        asset = zone_data.get('asset', 'UNKNOWN')
        level = zone_data.get('level', 0.0)
        zone_type = zone_data.get('zone_type', 'unknown')
        
        # Cada evento de toque es un trade
        touch_events = zone_data.get('touch_events', [])
        
        for event in touch_events:
            timestamp = event.get('timestamp', 0)
            direction = event.get('direction_expected', 'CALL')
            result = event.get('result', 'DRAW').upper()
            pips_moved = event.get('pips_moved', 0.0)
            
            # Convertir pips a PnL (aproximado)
            # Asumiendo 1 pip = 0.01 en valor relativo
            pnl = pips_moved * 0.01 if result == 'HOLD' else -pips_moved * 0.01
            
            # Crear registro de trade
            trade = {
                'timestamp': timestamp,
                'asset': asset,
                'direction': direction,
                'entry_price': level,
                'exit_price': level + (pips_moved / 10000),  # Aproximado
                'amount': 1.0,  # Cantidad estándar
                'result': result,
                'pnl': pnl,
                'confidence': 0.65,  # Valor por defecto
                'pattern': event.get('pattern_name', 'none'),
                'zone_strength': 0.7,  # Valor por defecto
                'session': event.get('session', 'UNKNOWN'),
                'rsi_at_touch': event.get('rsi_at_touch', 50.0),
                'trend_aligned': event.get('trend_aligned', False),
                'was_first_visit': event.get('was_first_visit', False),
            }
            
            trades.append(trade)
            
            # Actualizar estadísticas
            if result == 'HOLD':
                total_wins += 1
            elif result == 'BREAK':
                total_losses += 1
            
            total_pnl += pnl
    
    # Ordenar por timestamp
    trades.sort(key=lambda x: x['timestamp'])
    
    # Crear archivo de trade_history
    trade_history_data = {
        'version': '1.0',
        'updated': datetime.now().timestamp(),
        'total_trades': len(trades),
        'total_wins': total_wins,
        'total_losses': len(trades) - total_wins,
        'total_pnl': total_pnl,
        'trades': trades[-500:],  # Últimos 500
    }
    
    # Guardar
    os.makedirs(trade_history_path.parent, exist_ok=True)
    with open(trade_history_path, 'w') as f:
        json.dump(trade_history_data, f, indent=2)
    
    print(f"✅ MIGRACIÓN COMPLETADA:")
    print(f"   - Trades convertidos: {len(trades)}")
    print(f"   - Wins (HOLD): {total_wins}")
    print(f"   - Losses (BREAK): {len(trades) - total_wins}")
    print(f"   - Win Rate: {(total_wins/len(trades)*100):.1f}%" if len(trades) > 0 else "   - Win Rate: N/A")
    print(f"   - Total PnL: {total_pnl:.2f}")
    print(f"\n📁 Archivo guardado: {trade_history_path}")
    print(f"   Tamaño: {trade_history_path.stat().st_size / 1024:.1f} KB")
    
    return True


if __name__ == "__main__":
    migrate_zone_reactions_to_trades()
    print("\n" + "="*70 + "\n")
