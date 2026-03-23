#!/usr/bin/env python3
"""
🚀 BOT EJECUTOR - FUNCIONANDO AHORA MISMO
Ejecuta operaciones reales SIN ERRORES
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
EMAIL = os.getenv('EXNOVA_EMAIL')
PASSWORD = os.getenv('EXNOVA_PASSWORD')
CAPITAL = float(os.getenv('CAPITAL_PER_TRADE', 1.0))

DATA_DIR = Path(__file__).parent / "data" / "operaciones_ejecutadas"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = DATA_DIR / f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
TRADES_FILE = DATA_DIR / f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def log(msg):
    print(msg)
    with open(LOG_FILE, 'a') as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

print("\n" + "="*70)
print("   🚀 BOT EJECUTOR - FUNCIONANDO AHORA")
print("="*70 + "\n")

log("\n" + "="*70)
log(f"🚀 BOT INICIADO - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log("="*70)

try:
    from exnovaapi.stable_api import Exnova
    
    # Conectar
    log("🔗 Conectando a Exnova...")
    api = Exnova(EMAIL, PASSWORD)
    api.connect()
    
    # Sincronizar tiempo - esperar más
    log("⏳ Sincronizando tiempo (esperando 15 segundos)...")
    time.sleep(15)
    
    # Verificar sincronización
    timestamp = api.get_server_timestamp()
    if timestamp and timestamp > 0:
        log(f"✅ Tiempo sincronizado: {timestamp}")
    else:
        log("⚠️  Continuando de todas formas...")
    
    # Obtener balance
    balance = api.get_balance()
    log(f"💰 Balance: ${balance:.2f}")
    
    # Activos
    assets = ['EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC']
    log(f"✅ {len(assets)} activos listos")
    
    # Stats
    trades = 0
    wins = 0
    losses = 0
    pnl = 0
    
    log("\n" + "="*70)
    log("🎯 EJECUTANDO OPERACIONES")
    log("="*70)
    
    trade_num = 0
    
    while True:
        trade_num += 1
        
        try:
            asset = random.choice(assets)
            direction = random.choice(['call', 'put'])
            price = CAPITAL
            
            log(f"\n📊 #{trade_num}: {asset} {direction.upper()} (${price})")
            
            # FIRMA CORRECTA: api.buy(price, active, direction, duration)
            # NO keywords, solo posicionales
            try:
                log(f"   ⏳ Ejecutando...")
                
                # Llamada correcta SIN keywords
                status, order_id = api.buy(price, asset, direction, 1)
                
                if status and order_id:
                    log(f"   ✅ Ejecutada - ID: {order_id}")
                    
                    # Esperar a que expire
                    log(f"   ⏳ Esperando 65s...")
                    time.sleep(65)
                    
                    # Resultado
                    try:
                        result_status, profit = api.check_win_v4(order_id)
                        
                        if result_status == "win":
                            wins += 1
                            pnl += profit
                            log(f"   ✅ GANADA: +${profit:.2f}")
                        else:
                            losses += 1
                            pnl -= CAPITAL
                            log(f"   ❌ PERDIDA: -${CAPITAL:.2f}")
                        
                        trades += 1
                        
                        # Guardar
                        with open(TRADES_FILE, 'a') as f:
                            f.write(json.dumps({
                                'id': trade_num,
                                'timestamp': datetime.now().isoformat(),
                                'asset': asset,
                                'direction': direction,
                                'outcome': result_status,
                                'pnl': profit if result_status == "win" else -CAPITAL,
                            }) + '\n')
                    
                    except Exception as e:
                        log(f"   ⚠️  Error verificando: {str(e)[:50]}")
                
                else:
                    log(f"   ❌ No se ejecutó")
            
            except Exception as e:
                log(f"   ❌ Error: {str(e)[:80]}")
            
            # Stats cada 5
            if trade_num % 5 == 0 and trades > 0:
                wr = (wins / trades * 100)
                log(f"\n📈 STATS: {trades} ops | {wins}W-{losses}L | {wr:.1f}% WR | ${pnl:.2f} PnL\n")
            
            log("   ⏱️  5s para siguiente...")
            time.sleep(5)
        
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"❌ Error: {e}")
            time.sleep(5)

except KeyboardInterrupt:
    log(f"\n⏹️  DETENIDO")
    if trades > 0:
        wr = (wins/trades*100)
        log(f"📊 {trades} operaciones | {wins}W-{losses}L | {wr:.1f}% WR | ${pnl:.2f}")

except Exception as e:
    log(f"❌ FATAL: {e}")
    import traceback
    log(traceback.format_exc())

finally:
    log(f"✅ Log: {LOG_FILE}")
    log(f"✅ Datos: {TRADES_FILE}")
