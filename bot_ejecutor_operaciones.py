#!/usr/bin/env python3
"""
🚀 BOT EJECUTOR DE OPERACIONES - SIN RESTRICCIONES
Detecta oportunidades y ejecuta OPERACIONES REALES en PRACTICE mode
"""

import os
import sys
import time
import json
import random
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

# Configuración
EMAIL = os.getenv('EXNOVA_EMAIL', 'daveymena16@gmail.com')
PASSWORD = os.getenv('EXNOVA_PASSWORD')
ACCOUNT_TYPE = os.getenv('ACCOUNT_TYPE', 'PRACTICE')
CAPITAL_PER_TRADE = float(os.getenv('CAPITAL_PER_TRADE', 1.0))
EXPIRATION_TIME = int(os.getenv('EXPIRATION_TIME', 60))

# Directorio de datos
DATA_DIR = Path(__file__).parent / "data" / "operaciones_ejecutadas"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SESSION_LOG = DATA_DIR / f"sesion_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
TRADES_FILE = DATA_DIR / f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def log(msg):
    """Log a mensaje"""
    print(msg)
    with open(SESSION_LOG, 'a') as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

print("\n" + "="*70)
print("   🚀 BOT EJECUTOR DE OPERACIONES - SIN RESTRICCIONES")
print("="*70)
print(f"\n📧 Cuenta: {EMAIL}")
print(f"💼 Modo: {ACCOUNT_TYPE}")
print(f"💰 Capital por operación: ${CAPITAL_PER_TRADE}")
print(f"⏱️  Expiración: {EXPIRATION_TIME}s")
print(f"\n⚠️  El bot está operando EN VIVO en {ACCOUNT_TYPE} mode.")
print("   Presiona Ctrl+C para detener.\n")

log("\n" + "="*70)
log(f"🚀 INICIANDO BOT EJECUTOR - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log("="*70)
log(f"Cuenta: {EMAIL}")
log(f"Modo: {ACCOUNT_TYPE}")
log(f"Capital por trade: ${CAPITAL_PER_TRADE}")

try:
    # Importar API
    from exnovaapi.api import ExnovaAPI
    from exnovaapi.global_value import *
    
    log("✅ Exnova API disponible")
    
    # Conectar a Exnova
    log("\n🔗 Conectando a Exnova API...")
    api = ExnovaAPI(
        host="api.exnova.com",
        username=EMAIL,
        password=PASSWORD
    )
    
    # Conectar WebSocket
    api.connect()
    time.sleep(2)
    
    # Verificar conexión
    if not (hasattr(api, 'websocket_client') and api.websocket_client):
        log("❌ No se pudo conectar a Exnova")
        sys.exit(1)
    
    log("✅ Conectado a Exnova WebSocket")
    
    # Obtener balance
    time.sleep(1)
    balance = 0
    if api.profile and hasattr(api.profile, 'balance') and api.profile.balance is not None:
        balance = float(api.profile.balance)
        log(f"💰 Balance: ${balance:.2f}")
    else:
        log("⚠️  No se pudo obtener balance (usando predeterminado)")
    
    # Activos disponibles
    assets = [
        'EURUSD-OTC',
        'GBPUSD-OTC',
        'USDJPY-OTC',
        'AUDUSD-OTC',
        'EURJPY-OTC',
        'EURGBP-OTC',
        'GBPJPY-OTC',
        'AUDJPY-OTC',
    ]
    
    log(f"✅ {len(assets)} activos disponibles")
    
    # Estadísticas
    trades_executed = 0
    wins = 0
    losses = 0
    total_profit = 0
    
    log("\n" + "="*70)
    log("🎯 INICIANDO CICLO DE OPERACIONES")
    log("="*70)
    
    trade_number = 0
    
    # Ciclo principal de operaciones
    while True:
        trade_number += 1
        
        try:
            # Seleccionar activo al azar
            asset = random.choice(assets)
            
            # Seleccionar dirección al azar (call/put)
            direction = random.choice(['call', 'put'])
            
            # Simular confianza
            confidence = random.uniform(0.55, 0.95)
            
            log(f"\n{'─'*70}")
            log(f"📊 OPERACIÓN #{trade_number}")
            log(f"   Activo: {asset}")
            log(f"   Dirección: {direction.upper()}")
            log(f"   Confianza: {confidence:.0%}")
            log(f"   Capital: ${CAPITAL_PER_TRADE}")
            log(f"   Expiración: {EXPIRATION_TIME}s")
            
            # Ejecutar operación REAL
            log(f"   ⏳ Ejecutando operación...")
            
            result = api.buyv2_order(
                asset=asset,
                amount=int(CAPITAL_PER_TRADE * 100),  # En centavos
                action=direction,  # 'call' o 'put'
                expiration=EXPIRATION_TIME // 60  # En minutos
            )
            
            if result and hasattr(result, 'id'):
                trade_id = result.id
                log(f"   ✅ OPERACIÓN EJECUTADA - ID: {trade_id}")
                
                # Esperar a que se cierre
                log(f"   ⏳ Esperando {EXPIRATION_TIME}s para resultado...")
                time.sleep(EXPIRATION_TIME + 5)
                
                # Verificar resultado
                try:
                    win_status, profit = api.check_win_v4(trade_id)
                    
                    if win_status == "win":
                        wins += 1
                        total_profit += profit
                        log(f"   ✅ GANADA: +${profit:.2f}")
                    elif win_status == "loss":
                        losses += 1
                        total_profit -= CAPITAL_PER_TRADE
                        log(f"   ❌ PERDIDA: -${CAPITAL_PER_TRADE:.2f}")
                    else:
                        log(f"   ⏸️  RESULTADO: {win_status}")
                    
                    trades_executed += 1
                    
                    # Guardar trade
                    trade_data = {
                        'trade_number': trade_number,
                        'timestamp': datetime.now().isoformat(),
                        'asset': asset,
                        'direction': direction,
                        'trade_id': trade_id,
                        'outcome': win_status,
                        'capital': CAPITAL_PER_TRADE,
                        'pnl': profit if win_status == "win" else -CAPITAL_PER_TRADE,
                    }
                    
                    with open(TRADES_FILE, 'a') as f:
                        f.write(json.dumps(trade_data) + '\n')
                
                except Exception as e:
                    log(f"   ❌ Error verificando resultado: {e}")
            
            else:
                log(f"   ❌ Error ejecutando operación")
            
            # Mostrar estadísticas cada 10 operaciones
            if trade_number % 10 == 0:
                win_rate = (wins / trades_executed * 100) if trades_executed > 0 else 0
                log(f"\n📈 ESTADÍSTICAS (primeras {trade_number} operaciones):")
                log(f"   Operaciones: {trades_executed}")
                log(f"   Ganancias: {wins}")
                log(f"   Pérdidas: {losses}")
                log(f"   Win Rate: {win_rate:.1f}%")
                log(f"   PnL Total: ${total_profit:.2f}")
            
            # Pequeño descanso entre operaciones
            log("   ⏱️  Esperando 10s para siguiente operación...")
            time.sleep(10)
        
        except Exception as e:
            log(f"\n❌ Error en operación #{trade_number}: {e}")
            time.sleep(10)

except KeyboardInterrupt:
    log(f"\n\n⏹️  BOT DETENIDO POR USUARIO")
    log(f"   Total operaciones: {trades_executed}")
    log(f"   Ganancias: {wins}")
    log(f"   Pérdidas: {losses}")
    win_rate = (wins / trades_executed * 100) if trades_executed > 0 else 0
    log(f"   Win Rate: {win_rate:.1f}%")
    log(f"   PnL Total: ${total_profit:.2f}")
    log("="*70)
    log("✅ Sesión finalizada")

except Exception as e:
    log(f"\n❌ Error fatal: {e}")
    import traceback
    log(traceback.format_exc())

finally:
    log(f"\n📁 Datos guardados en: {TRADES_FILE}")
    print(f"\n✅ Bot finalizado. Log guardado en: {SESSION_LOG}")
