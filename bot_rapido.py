#!/usr/bin/env python3
"""
🚀 BOT OPERADOR ULTRA RÁPIDO - Versión simplificada
Ejecuta operaciones directamente sin validaciones innecesarias
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
print("   🚀 BOT OPERADOR ULTRA RÁPIDO")
print("="*70)
print(f"\n📧 Cuenta: {EMAIL}")
print(f"💼 Modo: {ACCOUNT_TYPE}")
print(f"💰 Capital: ${CAPITAL_PER_TRADE}")
print(f"\nPresiona Ctrl+C para detener.\n")

log("\n" + "="*70)
log(f"🚀 BOT OPERADOR ULTRA - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log("="*70)

try:
    from exnovaapi.api import ExnovaAPI
    
    # Conectar
    log("🔗 Conectando a Exnova...")
    api = ExnovaAPI(host="api.exnova.com", username=EMAIL, password=PASSWORD)
    
    log("⏳ Estableciendo conexión...")
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
            
            log(f"\n📊 #{trade_num}: {asset} {direction.upper()} ({confidence:.0%})")
            
            # Ejecutar operación - FIRMA CORRECTA: api.buy(amount, asset, action, duration)
            try:
                log(f"   ⏳ Ejecutando...")
                status, order_id = api.buy(
                    amount=CAPITAL_PER_TRADE,  # Cantidad en dinero
                    asset=asset,
                    action=direction,
                    duration=1  # 1 minuto
                )
                
                if status and order_id:
                    log(f"   ✅ Operación ejecutada - ID: {order_id}")
                    
                    # Esperar a que expire (65 segundos)
                    log(f"   ⏳ Esperando 65s para resultado...")
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
                        else:
                            log(f"   ⏸️  RESULTADO: {result_status}")
                        
                        trades += 1
                        
                        # Guardar
                        trade_data = {
                            'id': trade_num,
                            'timestamp': datetime.now().isoformat(),
                            'asset': asset,
                            'direction': direction,
                            'order_id': str(order_id),
                            'outcome': result_status,
                            'pnl': profit if result_status == "win" else -CAPITAL_PER_TRADE,
                        }
                        
                        with open(TRADES_FILE, 'a') as f:
                            f.write(json.dumps(trade_data) + '\n')
                    
                    except Exception as e:
                        log(f"   ⚠️  Error verificando resultado: {str(e)[:60]}")
                
                else:
                    log(f"   ❌ No se pudo ejecutar")
                    time.sleep(5)
            
            except Exception as e:
                log(f"   ❌ Error: {str(e)[:80]}")
                time.sleep(5)
            
            # Stats cada 5
            if trade_num % 5 == 0 and trades > 0:
                wr = (wins / trades * 100)
                log(f"\n📈 STATS: Trades={trades} | Wins={wins} | Loss={losses} | WR={wr:.1f}% | PnL=${pnl:.2f}\n")
            
            # Esperar entre operaciones (5 segundos es la expiracion mínima)
            log("   ⏱️  Esperando 5s para siguiente...")
            time.sleep(5)
        
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"❌ Error en operación: {e}")
            time.sleep(5)

except KeyboardInterrupt:
    log(f"\n⏹️  DETENIDO")
    if trades > 0:
        log(f"📊 Trades={trades} | Wins={wins} | Loss={losses} | WR={((wins/trades)*100):.1f}% | PnL=${pnl:.2f}")

except Exception as e:
    log(f"❌ Error fatal: {e}")
    import traceback
    log(traceback.format_exc())

finally:
    log(f"✅ Datos guardados en {TRADES_FILE}")
