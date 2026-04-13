#!/usr/bin/env python3
"""
BOT v3 - MEJORADO Y REFINADO
- Mas flexible con RSI (umbrales mas bajos)
- Incluye analisis de momentum
- Tiempo reducido entre analisis
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

DATA_DIR = Path(__file__).parent / "data" / "operaciones_v3"
DATA_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = DATA_DIR / f"v3_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
TRADES_FILE = DATA_DIR / f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

def log(msg):
    print(msg)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

def get_candles(api, asset, interval=60, count=25):
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

def calculate_rsi(closes, period=7):
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

def calculate_ema(closes, period=5):
    if len(closes) < period:
        return sum(closes) / len(closes) if closes else 0
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for close in closes[period:]:
        ema = (close - ema) * multiplier + ema
    return ema

def get_momentum(candles):
    if len(candles) < 5:
        return 0
    closes = [c['close'] for c in candles]
    return closes[-1] - closes[-5]

def analyze_market(candles):
    if len(candles) < 15:
        return None, 0, "Insufficient data"
    
    closes = [c['close'] for c in candles]
    current_price = closes[-1]
    
    rsi = calculate_rsi(closes)
    ema_5 = calculate_ema(closes, 5)
    ema_10 = calculate_ema(closes, 10) if len(closes) >= 10 else ema_5
    
    momentum = get_momentum(candles)
    
    trend = 'UP' if ema_5 > ema_10 else 'DOWN'
    
    signal = None
    confidence = 0
    reason = ""
    
    # Mas flexible: RSI < 35 (bajo de 40)
    if rsi < 25:
        signal = 'call'
        confidence = 75
        reason = f"RSI oversold: {rsi:.1f}"
    elif rsi > 75:
        signal = 'put'
        confidence = 75
        reason = f"RSI overbought: {rsi:.1f}"
    # RSI entre 25-35 con momentum a favor
    elif rsi < 35 and momentum < 0:
        signal = 'call'
        confidence = 65
        reason = f"RSI {rsi:.1f} + negative momentum"
    # RSI entre 65-75 con momentum a favor
    elif rsi > 65 and momentum > 0:
        signal = 'put'
        confidence = 65
        reason = f"RSI {rsi:.1f} + positive momentum"
    # Extremo simple
    elif rsi < 38:
        signal = 'call'
        confidence = 55
        reason = f"RSI low: {rsi:.1f}"
    elif rsi > 62:
        signal = 'put'
        confidence = 55
        reason = f"RSI high: {rsi:.1f}"
    
    if signal:
        log(f"   [ANALYSIS] Price: {current_price:.5f} | RSI: {rsi:.1f} | EMA5: {ema_5:.5f} | EMA10: {ema_10:.5f} | Trend: {trend} | Momentum: {momentum:.6f}")
        log(f"   [SIGNAL] {signal.upper()} | Conf: {confidence}% | Reason: {reason}")
    
    return signal, confidence, reason

print("\n" + "="*70)
print("   [BOT v3] - IMPROVED FLEXIBILITY")
print("="*70 + "\n")

log("\n" + "="*70)
log(f"[BOT v3] - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
log("Strategy: RSI + EMA + Momentum + Flexible thresholds")
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
    
    assets = ['EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC', 'AUDUSD-OTC', 'EURJPY-OTC', 'USDCAD-OTC']
    log(f"[OK] {len(assets)} assets ready")
    
    trades = 0
    wins = 0
    losses = 0
    pnl = 0
    
    trade_num = 0
    
    log("\n" + "="*70)
    log("[TRADING] FLEXIBLE ANALYSIS")
    log("="*70)
    
    consecutive_losses = 0
    
    while True:
        trade_num += 1
        
        try:
            # Rotar activos
            asset = assets[(trade_num - 1) % len(assets)]
            
            log(f"\n[ANALYZING] {asset}...")
            candles = get_candles(api, asset, interval=60, count=25)
            
            if not candles:
                log(f"   [ERROR] No candles")
                time.sleep(5)
                continue
            
            signal, confidence, reason = analyze_market(candles)
            
            if not signal:
                log(f"   [NO SIGNAL] {reason}")
                time.sleep(8)
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
                            consecutive_losses = 0
                            log(f"   [WIN] +${profit:.2f}")
                        else:
                            losses += 1
                            pnl -= CAPITAL
                            consecutive_losses += 1
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
            
            # Stats cada 3 trades
            if trades > 0 and trades % 3 == 0:
                wr = (wins / trades * 100)
                log(f"\n[STATS] {trades} trades | {wins}W-{losses}L | {wr:.1f}% WR | ${pnl:.2f} PnL\n")
            
            # Si 3 perdidas seguidas, pausar
            if consecutive_losses >= 3:
                log(f"[PAUSE] 3 losses in a row, waiting 30s...")
                time.sleep(30)
                consecutive_losses = 0
            else:
                log("   [WAIT] 8s next analysis...")
                time.sleep(8)
        
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
