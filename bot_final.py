#!/usr/bin/env python3
"""
🚀 BOT OPERADOR FINAL - SIN RESTRICCIONES
Ejecuta operaciones reales usando buyv3
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
print("   🚀 BOT OPERADOR FINAL")
print("="*70)
print(f"\n📧 Cuenta: {EMAIL}")
print(f"💼 Modo: {ACCOUNT_TYPE}\n")

log("\n" + "="*70)
log(f"🚀 BOT OPERADOR - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log("="*70)

try:
    from exnovaapi.api import ExnovaAPI
    from exnovaapi.global_value import OP_code
    
    # Conectar
    log("🔗 Conectando a Exnova...")
    api = ExnovaAPI(host="api.exnova.com", username=EMAIL, password=PASSWORD)
    
    log("⏳ Estableciendo conexión...")
    api.connect()
    
    # ESPERAR SINCRONIZACIÓN DE TIEMPO
    log("⏳ Sincronizando tiempo del servidor...")
    time.sleep(5)
    
    # Verificar que timesync está listo
    max_retries = 10
    retry = 0
    while retry < max_retries:
        if api.timesync and api.timesync.server_timestamp:
            log(f"✅ Tiempo sincronizado: {api.timesync.server_timestamp}")
            break
        time.sleep(1)
        retry += 1
    
    if not (api.timesync and api.timesync.server_timestamp):
        log("❌ No se pudo sincronizar el tiempo")
        sys.exit(1)
    
    if not (hasattr(api, 'websocket_client') and api.websocket_client):
        log("❌ No se pudo conectar WebSocket")
        sys.exit(1)
    
    log("✅ Conectado a Exnova")
    
    # Activos
    assets = ['EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC']
    log(f"✅ {len(assets)} activos para operar")
    
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
            
            log(f"\n📊 #{trade_num}: {asset} {direction.upper()}")
            
            # Usar buyv3 directamente
            try:
                log(f"   ⏳ Ejecutando...")
                
                # Obtener código del activo
                active_code = OP_code.ACTIVES.get(asset)
                if not active_code:
                    log(f"   ❌ Activo no encontrado")
                    continue
                
                # Ejecutar operación con buyv3
                req_id = f"trade_{trade_num}"
                api.buy_multi_option = {}
                
                result = api.buyv3(
                    price=CAPITAL_PER_TRADE,
                    active=active_code,
                    direction=direction.lower(),
                    duration=1,  # 1 minuto
                    request_id=req_id
                )
                
                # Esperar resultado
                time.sleep(2)
                
                if req_id in api.buy_multi_option:
                    trade_data = api.buy_multi_option[req_id]
                    if "id" in trade_data:
                        order_id = trade_data["id"]
                        log(f"   ✅ Operación ejecutada - ID: {order_id}")
                        
                        # Esperar a que expire
                        log(f"   ⏳ Esperando 65s...")
                        time.sleep(65)
                        
                        # Verificar resultado
                        try:
                            result_status, profit = api.check_win_v4(order_id)
                            
                            if result_status == "win":
                                wins += 1
                                pnl += profit
                                log(f"   ✅ GANADA: +${profit:.2f}")
                            elif result_status == "loss":
                                losses += 1
                                pnl -= CAPITAL_PER_TRADE
                                log(f"   ❌ PERDIDA: -${CAPITAL_PER_TRADE:.2f}")
                            
                            trades += 1
                            
                            # Guardar
                            t_data = {
                                'id': trade_num,
                                'timestamp': datetime.now().isoformat(),
                                'asset': asset,
                                'direction': direction,
                                'outcome': result_status,
                                'pnl': profit if result_status == "win" else -CAPITAL_PER_TRADE,
                            }
                            
                            with open(TRADES_FILE, 'a') as f:
                                f.write(json.dumps(t_data) + '\n')
                        
                        except Exception as e:
                            log(f"   ⚠️  Error verificando: {str(e)[:60]}")
                    else:
                        log(f"   ❌ No se obtuvo ID de orden")
                else:
                    log(f"   ❌ Sin respuesta del servidor")
            
            except Exception as e:
                log(f"   ❌ Error: {str(e)[:80]}")
            
            # Stats cada 5
            if trade_num % 5 == 0 and trades > 0:
                wr = (wins / trades * 100)
                log(f"\n📈 STATS: Trades={trades} | W={wins} | L={losses} | WR={wr:.1f}% | PnL=${pnl:.2f}\n")
            
            # Esperar
            log("   ⏱️  Esperando 5s...")
            time.sleep(5)
        
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"❌ Error: {e}")
            time.sleep(5)

except KeyboardInterrupt:
    log(f"\n⏹️  DETENIDO")
    if trades > 0:
        log(f"📊 Trades={trades} | W={wins} | L={losses} | WR={((wins/trades)*100):.1f}% | PnL=${pnl:.2f}")

except Exception as e:
    log(f"❌ Error fatal: {e}")

finally:
    log(f"✅ Datos guardados en {TRADES_FILE}")
