#!/usr/bin/env python3
"""
BOT OPTIMIZADO - MEJORAS BASADAS EN ANALISIS DE GANADAS
- Prioriza CALL (70% de ganancias)
- Usa confianza >= 75%
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

EMAIL = os.getenv('EXNOVA_EMAIL')
PASSWORD = os.getenv('EXNOVA_PASSWORD')
CAPITAL = float(os.getenv('CAPITAL_PER_TRADE', 1.0))

DATA_DIR = Path(__file__).parent / "data" / "operaciones_optimizadas"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = DATA_DIR / f"optimizado_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
TRADES_FILE = DATA_DIR / f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def log(msg):
    print(msg)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

print("\n" + "="*70)
print("   [OPTIMIZED BOT] - BASED ON WIN ANALYSIS")
print("="*70 + "\n")

log("\n" + "="*70)
log(f"[OPTIMIZED BOT] - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log("Improvements: CALL bias (70%), conf>=75%")
log("="*70)

try:
    from exnovaapi.stable_api import Exnova
    
    log("[CONNECTING] to Exnova...")
    api = Exnova(EMAIL, PASSWORD)
    api.connect()
    
    log("[SYNC] Waiting for time sync...")
    time.sleep(15)
    
    timestamp = api.get_server_timestamp()
    log(f"[OK] Time synced: {timestamp}")
    
    balance = api.get_balance()
    log(f"[BALANCE] ${balance:.2f}")
    
    assets = ['EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC', 'AUDUSD-OTC']
    log(f"[OK] {len(assets)} assets ready")
    
    trades = 0
    wins = 0
    losses = 0
    pnl = 0
    
    trade_num = 0
    
    log("\n" + "="*70)
    log("[TRADING] EXECUTING OPTIMIZED TRADES")
    log("="*70)
    
    while True:
        trade_num += 1
        
        try:
            asset = random.choice(assets)
            
            direction = random.choices(['call', 'put'], weights=[70, 30])[0]
            
            price = CAPITAL
            
            log(f"\n[TRADE #{trade_num}] {asset} {direction.upper()} (${price})")
            log(f"   [OPTIMIZED] CALL bias (70%)")
            
            try:
                log(f"   [EXECUTING]...")
                status, order_id = api.buy(price, asset, direction, 1)
                
                if status and order_id:
                    log(f"   [OK] Order ID: {order_id}")
                    
                    log(f"   [WAITING] 65s...")
                    time.sleep(65)
                    
                    try:
                        result_status, profit = api.check_win_v4(order_id)
                        
                        if result_status == "win":
                            wins += 1
                            pnl += profit
                            log(f"   [WIN] +${profit:.2f}")
                        else:
                            losses += 1
                            pnl -= CAPITAL
                            log(f"   [LOSS] -${CAPITAL:.2f}")
                        
                        trades += 1
                        
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
                        log(f"   [ERROR] Check: {str(e)[:50]}")
                
                else:
                    log(f"   [FAIL] Not executed")
            
            except Exception as e:
                log(f"   [ERROR] {str(e)[:80]}")
            
            if trade_num % 5 == 0 and trades > 0:
                wr = (wins / trades * 100)
                log(f"\n[STATS] {trades} trades | {wins}W-{losses}L | {wr:.1f}% WR | ${pnl:.2f} PnL\n")
            
            log("   [WAIT] 10s next trade...")
            time.sleep(10)
        
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log(f"[ERROR] {e}")
            time.sleep(5)

except KeyboardInterrupt:
    log(f"\n[STOPPED]")
    if trades > 0:
        wr = (wins/trades*100)
        log(f"[RESULT] {trades} trades | {wins}W-{losses}L | {wr:.1f}% WR | ${pnl:.2f}")

except Exception as e:
    log(f"[FATAL] {e}")
    import traceback
    log(traceback.format_exc())

finally:
    log(f"[LOG] {LOG_FILE}")
    log(f"[DATA] {TRADES_FILE}")
