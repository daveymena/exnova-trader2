#!/usr/bin/env python3
"""
Diagnóstico de persistencia - Analiza el estado de todos los datos guardados
"""
import json
import os
from pathlib import Path


def diagnose():
    """Ejecuta diagnóstico completo"""
    print("\n" + "="*70)
    print("🔍 DIAGNÓSTICO DE PERSISTENCIA DE DATOS")
    print("="*70 + "\n")
    
    # 1. Revisar learning_state.json
    print("📁 1. LEARNING STATE (bot/brain/learning_state.json)")
    print("-" * 70)
    learning_state_path = Path("bot/brain/learning_state.json")
    if learning_state_path.exists():
        with open(learning_state_path, 'r') as f:
            data = json.load(f)
        
        zones_count = sum(len(zones) for zones in data.get('zones', {}).values())
        trade_history_count = len(data.get('trade_history', []))
        
        print(f"✅ Archivo existe")
        print(f"   - Zonas detectadas: {zones_count}")
        print(f"   - Trade history: {trade_history_count} (VACÍO)" if trade_history_count == 0 else f"   - Trade history: {trade_history_count}")
        print(f"   - Última actualización: {data.get('updated', 'N/A')}")
    else:
        print("❌ Archivo NO existe")
    
    # 2. Revisar zone_reactions.json
    print("\n📁 2. ZONE REACTIONS (bot/brain/zone_reactions.json)")
    print("-" * 70)
    zone_reactions_path = Path("bot/brain/zone_reactions.json")
    if zone_reactions_path.exists():
        with open(zone_reactions_path, 'r') as f:
            data = json.load(f)
        
        total_events = sum(len(zone.get('touch_events', [])) for zone in data.values())
        
        print(f"✅ Archivo existe")
        print(f"   - Zonas con historial: {len(data)}")
        print(f"   - Total eventos de toque: {total_events}")
        
        # Mostrar últimas zonas tocadas
        recent_zones = sorted(
            data.items(),
            key=lambda x: x[1].get('last_touch_ts', 0),
            reverse=True
        )[:3]
        
        print(f"   - Últimas zonas tocadas:")
        for zone_key, zone_data in recent_zones:
            asset = zone_data.get('asset', 'N/A')
            level = zone_data.get('level', 'N/A')
            touches = zone_data.get('total_touches', 0)
            holds = zone_data.get('successful_holds', 0)
            print(f"     • {asset} @ {level}: {touches} toques, {holds} holds")
    else:
        print("❌ Archivo NO existe")
    
    # 3. Revisar trade_history.json (nuevo)
    print("\n📁 3. TRADE HISTORY (bot/brain/trade_history.json)")
    print("-" * 70)
    trade_history_path = Path("bot/brain/trade_history.json")
    if trade_history_path.exists():
        with open(trade_history_path, 'r') as f:
            data = json.load(f)
        
        total_trades = data.get('total_trades', 0)
        total_wins = data.get('total_wins', 0)
        total_losses = data.get('total_losses', 0)
        total_pnl = data.get('total_pnl', 0.0)
        trades_count = len(data.get('trades', []))
        
        print(f"✅ Archivo existe")
        print(f"   - Total trades: {total_trades}")
        print(f"   - Wins: {total_wins}")
        print(f"   - Losses: {total_losses}")
        print(f"   - Win Rate: {(total_wins/total_trades*100):.1f}%" if total_trades > 0 else "   - Win Rate: N/A")
        print(f"   - Total PnL: {total_pnl:.2f}")
        print(f"   - Trades en archivo: {trades_count}")
        
        if trades_count > 0:
            recent_trades = data.get('trades', [])[-5:]
            print(f"   - Últimos 5 trades:")
            for trade in recent_trades:
                asset = trade.get('asset', 'N/A')
                direction = trade.get('direction', 'N/A')
                result = trade.get('result', 'N/A')
                pnl = trade.get('pnl', 0.0)
                print(f"     • {asset} {direction}: {result} ({pnl:+.2f})")
    else:
        print("❌ Archivo NO existe (será creado en la próxima operación)")
    
    # 4. Revisar learning_progress.json
    print("\n📁 4. LEARNING PROGRESS (data/learning_progress.json)")
    print("-" * 70)
    progress_path = Path("data/learning_progress.json")
    if progress_path.exists():
        with open(progress_path, 'r') as f:
            data = json.load(f)
        
        print(f"✅ Archivo existe")
        print(f"   - Total trades: {data.get('total_trades', 0)}")
        print(f"   - Phase: {data.get('phase', 'N/A')}")
        print(f"   - Learning progress: {data.get('learning_progress', 0):.1%}")
    else:
        print("❌ Archivo NO existe")
    
    # 5. Resumen y recomendaciones
    print("\n" + "="*70)
    print("📊 RESUMEN Y RECOMENDACIONES")
    print("="*70 + "\n")
    
    if trade_history_path.exists():
        with open(trade_history_path, 'r') as f:
            trade_data = json.load(f)
        total_trades = trade_data.get('total_trades', 0)
    else:
        total_trades = 0
    
    if zone_reactions_path.exists():
        with open(zone_reactions_path, 'r') as f:
            zone_data = json.load(f)
        total_events = sum(len(zone.get('touch_events', [])) for zone in zone_data.values())
    else:
        total_events = 0
    
    print(f"✅ DATOS DETECTADOS:")
    print(f"   - Zonas con reacciones: {len(zone_data) if zone_reactions_path.exists() else 0}")
    print(f"   - Eventos de zona: {total_events}")
    print(f"   - Trades registrados: {total_trades}")
    
    if total_trades == 0 and total_events > 0:
        print(f"\n⚠️  PROBLEMA IDENTIFICADO:")
        print(f"   El bot ha operado {total_events} veces (según zone_reactions.json)")
        print(f"   pero NO hay trades registrados en trade_history.json")
        print(f"\n💡 SOLUCIÓN:")
        print(f"   1. El nuevo sistema de persistencia está activo")
        print(f"   2. Los próximos trades se guardarán correctamente")
        print(f"   3. Ejecuta el bot para generar nuevos trades")
    elif total_trades > 0:
        print(f"\n✅ SISTEMA FUNCIONANDO:")
        print(f"   Los trades se están guardando correctamente")
        print(f"   El bot recuerda {total_trades} operaciones previas")
    else:
        print(f"\n⏳ SIN DATOS:")
        print(f"   El bot aún no ha realizado operaciones")
        print(f"   Los datos se guardarán cuando comience a operar")
    
    print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    diagnose()
