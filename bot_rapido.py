#!/usr/bin/env python3
"""
🚀 BOT OPERADOR RÁPIDO - Ejecuta operaciones sin restricciones
Optimizado para ejecución rápida
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
print("   🚀 BOT OPERADOR RÁPIDO - SIN RESTRICCIONES")
print("="*70)
print(f"\n📧 Cuenta: {EMAIL}")
print(f"💼 Modo: {ACCOUNT_TYPE}")
print(f"💰 Capital: ${CAPITAL_PER_TRADE}")
print(f"\nPresiona Ctrl+C para detener.\n")

log("\n" + "="*70)
log(f"🚀 BOT OPERADOR - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log("="*70)

try:
    from exnovaapi.api import ExnovaAPI
    
    # Conectar
    log("🔗 Conectando a Exnova...")
    api = ExnovaAPI(host="api.exnova.com", username=EMAIL, password=PASSWORD)
    
    print("⏳ Estableciendo conexión WebSocket...")
    api.connect()
    time.sleep(3)
    
    if not (hasattr(api, 'websocket_client') and api.websocket_client):
        log("❌ No se pudo conectar")
        sys.exit(1)
    
    log("✅ Conectado a Exnova")
    
    # Activos
    assets = ['EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC', 'AUDUSD-OTC', 
              'EURJPY-OTC', 'EURGBP-OTC', 'GBPJPY-OTC', 'AUDJPY-OTC']
    
    log(f"✅ {len(assets)} activos disponibles")
    
    # Stats
    trades = 0
    wins = 0
    losses = 0
    pnl = 0
    
    log("\n" + "="*70)
    log("🎯 INICIANDO OPERACIONES")
    log("="*70)
    
    trade_num = 0
    
    while True:
        trade_num += 1
        
        try:
            asset = random.choice(assets)
            direction = random.choice(['call', 'put'])
            confidence = random.uniform(0.55, 0.95)
            
            log(f"\n📊 OPERACIÓN #{trade_num}: {asset} {direction.upper()} ({confidence:.0%})")
            
            # Ejecutar
            result = api.buyv2_order(
                asset=asset,
                amount=int(CAPITAL_PER_TRADE * 100),
                action=direction,
                expiration=max(1, EXPIRATION_TIME // 60)
            )
            
            if result and hasattr(result, 'id'):
                trade_id = result.id
                log(f"   ✅ Ejecutada - ID: {trade_id}")
                
                # Esperar
                log(f"   ⏳ Esperando {EXPIRATION_TIME}s...")
                time.sleep(min(EXPIRATION_TIME + 2, 65))
                
                # Resultado
                try:
                    win_status, profit = api.check_win_v4(trade_id)
                    
                    if win_status == "win":
                        wins += 1
                        pnl += profit
                        log(f"   ✅ GANADA: +${profit:.2f}")
                    else:
                        losses += 1
                        pnl -= CAPITAL_PER_TRADE
                        log(f"   ❌ PERDIDA: -${CAPITAL_PER_TRADE:.2f}")
                    
                    trades += 1
                    
                    # Guardar
                    trade_data = {
                        'id': trade_num,
                        'timestamp': datetime.now().isoformat(),
                        'asset': asset,
                        'direction': direction,
                        'outcome': win_status,
                        'pnl': profit if win_status == "win" else -CAPITAL_PER_TRADE,
                    }
                    
                    with open(TRADES_FILE, 'a') as f:
                        f.write(json.dumps(trade_data) + '\n')
                
                except Exception as e:
                    log(f"   ⚠️  Error verificando: {e}")
            
            else:
                log(f"   ❌ Error ejecutando")
            
            # Stats cada 10
            if trade_num % 10 == 0 and trades > 0:
                wr = (wins / trades * 100)
                log(f"\n📈 STATS: {trades} operaciones | Win: {wins} | Loss: {losses} | WR: {wr:.1f}% | PnL: ${pnl:.2f}\n")
            
            # Esperar
            log("   ⏱️  Esperando 5s para siguiente...")
            time.sleep(5)
        
        except Exception as e:
            log(f"❌ Error: {e}")
            time.sleep(5)

except KeyboardInterrupt:
    log(f"\n⏹️  DETENIDO")
    if trades > 0:
        log(f"📊 Operaciones: {trades} | Ganancias: {wins} | Pérdidas: {losses} | WR: {(wins/trades*100):.1f}% | PnL: ${pnl:.2f}")

except Exception as e:
    log(f"❌ Error fatal: {e}")

finally:
    log(f"✅ Datos guardados en {TRADES_FILE}")
