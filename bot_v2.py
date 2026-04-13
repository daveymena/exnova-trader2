#!/usr/bin/env python3
"""
BOT MEJORADO v2 - ANALISIS REAL DE MERCADO
- Análisis técnico real (RSI, tendencia, momentum)
- No más aleatorio puro
- Entradas basadas en condiciones de mercado
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

DATA_DIR = Path(__file__).parent / "data" / "operaciones_v2"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = DATA_DIR / f"v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
TRADES_FILE = DATA_DIR / f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def log(msg):
    print(msg)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

def get_candles(api, asset, interval=60, count=30):
    try:
        end_time = int(api.get_server_timestamp())
        data = api.get_candles(asset, interval, count, end_time)
        if data and len(data) > 0:
            return [{
                'open': c.get('open', 0),
                'close': c.get('close', 0),
                'high': c.get('max', 0),
                'low': c.get('min', 0),
            } for c in data]
        return []
    except:
        return []

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
    if len(gains) < period:
        return 50
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 70
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_ema(closes, period=10):
    if len(closes) < period:
        return sum(closes) / len(closes) if closes else 0
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for close in closes[period:]:
        ema = (close - ema) * multiplier + ema
    return ema

def analyze_market(candles):
    if len(candles) < 20:
        return None, 0, "Insufficient data"
    
    closes = [c['close'] for c in candles]
    current_price = closes[-1]
    
    rsi = calculate_rsi(closes)
    ema_10 = calculate_ema(closes, 10)
    ema_20 = calculate_ema(closes, 20) if len(closes) >= 20 else ema_10
    
    trend = 'UP' if ema_10 > ema_20 else 'DOWN'
    
    signal = None
    confidence = 0
    reason = ""
    
    if rsi < 30:
        signal = 'call'
        confidence = 70 + (30 - rsi)
        reason = f"RSI oversold: {rsi:.1f}"
    elif rsi > 70:
        signal = 'put'
        confidence = 70 + (rsi - 70)
        reason = f"RSI overbought: {rsi:.1f}"
    elif rsi < 40 and trend == 'DOWN':
        signal = 'call'
        confidence = 60
        reason = f"RSI {rsi:.1f} + trend DOWN"
    elif rsi > 60 and trend == 'UP':
        signal = 'put'
        confidence = 60
        reason = f"RSI {rsi:.1f} + trend UP"
    
    if signal:
        log(f"   [ANALYSIS] Price: {current_price:.5f} | RSI: {rsi:.1f} | EMA10: {ema_10:.5f} | EMA20: {ema_20:.5f} | Trend: {trend}")
        log(f"   [SIGNAL] {signal.upper()} | Conf: {confidence:.0f}% | Reason: {reason}")
    
    return signal, confidence, reason

print("\n" + "="*70)
print("   [BOT v2] - REAL MARKET ANALYSIS")
print("="*70 + "\n")

log("\n" + "="*70)
log(f"[BOT v2] - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log("Strategy: RSI + EMA + Real Analysis")
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
    log("[TRADING] REAL MARKET ANALYSIS")
    log("="*70)
    
    while True:
        trade_num += 1
        
        try:
            asset = random.choice(assets)
            
            log(f"\n[ANALYZING] {asset}...")
            candles = get_candles(api, asset, interval=60, count=30)
            
            if not candles:
                log(f"   [ERROR] No candles received")
                time.sleep(10)
                continue
            
            signal, confidence, reason = analyze_market(candles)
            
            if not signal:
                log(f"   [NO SIGNAL] {reason}")
                time.sleep(15)
                continue
            
            direction = signal
            price = CAPITAL
            
            log(f"\n[TRADE #{trade_num}] {asset} {direction.upper()} (${price})")
            
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
                                'confidence': confidence,
                                'reason': reason,
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
            
            log("   [WAIT] 15s next analysis...")
            time.sleep(15)
        
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
