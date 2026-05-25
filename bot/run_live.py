# -*- coding: utf-8 -*-
"""
Ejecuta el bot Exnova en modo texto (stdout) para monitoreo desde consola.
"""
import sys, os, time, threading
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Agregar rutas de búsqueda para módulos (estamos en bot/)
app_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, app_dir)  # bot/ (donde estamos)
sys.path.insert(0, os.path.join(app_dir, 'brain'))  # bot/brain/
sys.path.insert(0, os.path.join(app_dir, 'core'))  # bot/core/
sys.path.insert(0, os.path.join(app_dir, 'data'))  # bot/data/
sys.path.insert(0, os.path.join(app_dir, 'engine'))  # bot/engine/
sys.path.insert(0, os.path.join(app_dir, 'strategies'))  # bot/strategies/

# ─── Lock de instancia única ──────────────────────────────────────────────
LOCK_FILE = os.path.join(os.path.dirname(__file__), 'run_live.lock')

def check_single_instance():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            if old_pid == os.getpid():
                return  # Somos nosotros mismos (reinicio)
            if os.name == 'nt':
                import ctypes
                h = ctypes.windll.kernel32.OpenProcess(0x0400, 0, old_pid)
                if h:
                    ctypes.windll.kernel32.CloseHandle(h)
                    print(f"[LOCK] PID {old_pid} ya ejecutando run_live.py. Abortando.")
                    sys.exit(0)
        except:
            pass
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))

def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(LOCK_FILE)
    except:
        pass

check_single_instance()
import atexit
atexit.register(release_lock)

from dotenv import load_dotenv
load_dotenv()

# Importar directamente (estamos en bot/ así que config_assets.py está aquí)
from config import Config
from config_assets import (
    get_activos_activos, get_config_sensibilidad,
    get_current_time_colombia, es_horario_manana, ASSETS_OTC_24_7, ASSETS_PTC_MORNING
)
from data.market_data import MarketDataHandler
from core.advanced_risk_manager import initialize_risk_manager, RiskConfig
from brain.adaptive_learner import get_adaptive_learner
from brain.market_memory import get_market_memory
from brain.trade_evaluator import TradeEvaluator
from brain.adaptive_learning_mode import get_learning_mode
from engine.intelligent_engine import IntelligentEngine
from brain.agent_trading_engine import get_agent_trading_engine
from core.smart_money_analyzer import SmartMoneyAnalyzer

# ─── Constantes ─────────────────────────────────────────────────────────────
INITIAL_BALANCE    = 10_000.0
MIN_CONFIDENCE     = 0.75  # AUMENTADO: Solo operar con confianza alta (75%+)
COOLDOWN_AFTER_LOSS = 180  # Esperar 3min después de pérdida
MIN_BETWEEN_TRADES  = 90   # Esperar 90s entre trades
MIN_BETWEEN_SAME_ASSET = 240  # Esperar 4min para mismo activo
MAX_CONSEC_LOSSES   = 3  # REDUCIDO: Parar después de 3 pérdidas seguidas
PAUSE_AFTER_WIN_STREAK = 5  # Pausa después de 5 wins
PAUSE_DURATION = 60  # Pausa de 1 minuto

# ─── Estado global ──────────────────────────────────────────────────────────
from collections import deque
import threading

state = {
    "running": True,
    "balance": 0.0, "initial_balance": 0.0,
    "wins": 0, "losses": 0, "total_pnl": 0.0,
    "trades": [],
    "cycle": 0, "start_time": time.time(),
    "last_trade_time": 0, "current_asset": "",
    "status": "INICIANDO", "active_order": None,
    "consecutive_losses": 0, "best_streak": 0, "current_streak": 0,
    "last_signal": {}, "last_diagnosis": [],
    "last_trade_by_asset": {}, "rejection_stats": {},
}

# Lock para evitar operaciones simultáneas
trade_lock = threading.Lock()
trade_in_progress = False

def log(msg, level="INFO"):
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] [{level}] {msg}", flush=True)

# ─── Trade execution ────────────────────────────────────────────────────────

sm_analyzer = SmartMoneyAnalyzer()

def execute_trade(market_data, rm, signal, amount, learner, memory, evaluator, agent_engine, df_m15=None, df_m5=None):
    global trade_in_progress
    
    asset = signal["asset"]
    direction = signal["signal"]
    confidence = signal["confidence"]
    expiration = signal.get("expiration", 60)
    pattern = signal.get("pattern", "")
    zone_str = signal.get("zone_strength", 0.0)
    context = signal.get("context", {})
    conditions = signal.get("conditions", {})
    zone_obj = signal.get("zone_object")

    action_str = "call" if direction == "CALL" else "put"
    duration = max(1, min(5, expiration // 60))
    exp_min = signal.get("expiration_minutes", duration)

    log(f"[ANALISIS LOCAL] Propuesta técnica: {asset} {direction} ${amount:.2f} | {pattern} | zona={zone_str:.2f} | conf={confidence*100:.0f}% | {exp_min}min")

    # ── LOCK: Evitar operaciones simultáneas ────────────────────────────────
    with trade_lock:
        if trade_in_progress:
            log(f"⏳ Trade saltado - ya hay una operación en progreso", "WARNING")
            return False
        
        if state["active_order"] is not None:
            log(f"⏳ Operación activa detectada (ID: {state['active_order']}). Esperando resultado.", "WAIT")
            return False
        
        # Marcar que hay una operación en progreso
        trade_in_progress = True
        state["active_order"] = f"pending_{time.time()}"

    # ── VALIDACIÓN CON ORDER BLOCK M15 ──────────────────────────────────────
    ob_validation = {'valid': False, 'reason': 'No M15 data', 'trend_aligned': False, 'trend': 'neutral'}
    if df_m15 is not None and len(df_m15) >= 20:
        ob_validation = sm_analyzer.validate_trade_with_ob(df_m15, direction)
        
        if ob_validation.get('ob') is not None:
            ob = ob_validation['ob']
            ob_type = "alcista" if ob['type'] == 'bullish' else "bajista"
            log(f"[OB M15] Order Block {ob_type} detectado: {ob['low']:.5f}-{ob['high']:.5f} (fuerza: {ob['strength']:.0f}%)")
        
        log(f"[OB M15] {ob_validation['reason']}")
        
        if not ob_validation['valid']:
            log(f"[OB M15] ⛔ SIN ORDER BLOCK VÁLIDO. Operación CANCELADA.", "WARNING")
            state["status"] = "ANALIZANDO"
            return False
        
        if not ob_validation['trend_aligned']:
            log(f"[TREND] ⚠️ Tendencia M15 ({ob_validation['trend']}) NO alineada con dirección {direction}. Operación CANCELADA.", "WARNING")
            state["status"] = "ANALIZANDO"
            return False
        
        log(f"[OB M15] ✅ Order Block respetado. Tendencia alineada: {ob_validation['trend']}")
    else:
        log(f"[OB M15] ⚠️ Sin datos M15, operando con validación técnica solamente", "WARNING")

    # ── VALIDACIÓN CON AGENTE IA ──────────────────────────────────────────────
    try:
        current_price = 0.0
        if not market_data.get_candles(asset, "1m", 1).empty:
            current_price = float(market_data.get_candles(asset, "1m", 1).iloc[-1]["close"])
    except Exception:
        current_price = signal.get("zone", 0.0) or amount

    trade_params = {
        'asset': asset,
        'direction': direction,
        'amount': amount,
        'price': current_price,
        'rsi': context.get("momentum", {}).get("rsi_m1", 50) if context else 50,
        'trend': context.get("dominant_trend", "NEUTRAL") if context else "NEUTRAL",
        'pattern': pattern or "none",
        'zone_type': zone_obj.zone_type if zone_obj else "support",
        'zone': zone_obj.level if zone_obj else current_price,
    }

    log(f"[AI] Evaluando propuesta de trade con Agente IA...")
    agent_result = agent_engine.execute_trade(trade_params)

    if not agent_result.get('executed', False):
        log(f"[AI] Trade RECHAZADO por Agente IA. Razón: {agent_result.get('reason')}", "WARNING")
        state["status"] = "ANALIZANDO"
        state["active_order"] = None
        return False

    direction = agent_result.get('direction', direction)
    action_str = "call" if direction == "CALL" else "put"
    log(f"[AI] Trade APROBADO por Agente IA. Dirección final: {direction} (Confianza IA: {agent_result.get('agent_analysis', {}).get('confidence', 0):.0f}%)")

    log(f"ENTRANDO A EXNOVA: {asset} {direction} ${amount:.2f} | {pattern} | {exp_min}min")
    state["status"] = "OPERANDO"
    state["last_trade_time"] = time.time()

    try:
        check, order_id = market_data.buy(asset, amount, action_str, duration)
        if check:
            log(f"Orden abierta: {direction} ${amount:.2f} exp={duration}min")
            state["active_order"] = order_id
            time.sleep(expiration + 8)

            result, pnl = "DRAW", 0.0
            try:
                result_data = market_data.api.check_win_v4(order_id)
                if result_data is not None:
                    if isinstance(result_data, tuple):
                        _, profit = result_data
                        profit = float(profit) if profit is not None else 0.0
                    elif isinstance(result_data, (int, float)):
                        profit = float(result_data)
                    else:
                        profit = 0.0

                    if profit > 0:
                        pnl, result = profit, "WIN"
                        log(f"WIN +${profit:.2f} | {asset} {direction} | patron={pattern} zona={zone_str:.2f}")
                    elif profit < 0:
                        pnl, result = -amount, "LOSS"
                        log(f"LOSS -${amount:.2f} | {asset} {direction} | patron={pattern} zona={zone_str:.2f}")
                    else:
                        log(f"DRAW | {asset} {direction}")
                else:
                    pnl, result = -amount * 0.5, "LOSS"
                    log("Sin confirmacion, asumiendo LOSS")
            except Exception as e:
                log(f"Error verificando resultado: {e}")
                pnl, result = 0.0, "DRAW"

            # Record trade
            state["trades"].append({
                "time": time.strftime("%H:%M:%S"), "asset": asset,
                "direction": direction, "amount": amount,
                "confidence": confidence, "result": result, "pnl": pnl,
                "pattern": pattern, "zone_strength": zone_str,
            })
            if result == "WIN":
                state["wins"] += 1
                state["consecutive_losses"] = 0
                state["current_streak"] = max(0, state["current_streak"]) + 1
                state["best_streak"] = max(state["best_streak"], state["current_streak"])
            elif result == "LOSS":
                state["losses"] += 1
                state["consecutive_losses"] += 1
                state["current_streak"] = min(0, state["current_streak"]) - 1
            state["total_pnl"] += pnl
            state["balance"] = max(0, state["balance"] + pnl)
            rm.update_balance(state["balance"], {"profit": pnl})

            learning_mode = get_learning_mode()
            learning_mode.record_trade()

            # Registrar resultado en AgentTradingEngine para aprendizaje continuo
            try:
                trade_to_learn = {
                    'asset': asset,
                    'direction': direction,
                    'amount': amount,
                    'result': result,  # 'WIN', 'LOSS', 'DRAW'
                    'pnl': pnl,
                    'pattern': pattern or "none",
                    'zone_strength': zone_str,
                    'rsi_at_touch': trade_params['rsi'],
                    'trend_aligned': signal.get("trend_aligned", False),
                }
                log(f"[AI] Registrando resultado en Agente IA para autocrítica y aprendizaje...")
                agent_engine.record_trade_result(trade_to_learn)
            except Exception as e:
                log(f"Error registrando resultado en Agente IA: {e}", "ERROR")

            # Post-trade analysis
            df_after = None
            try:
                df_after = market_data.get_candles(asset, 60, 20)
            except:
                pass

            trade_record = {
                "asset": asset, "direction": direction, "amount": amount,
                "confidence": confidence, "result": result, "pnl": pnl,
                "pattern": pattern, "order_id": str(order_id),
                "entry_price": signal.get("zone", 0.0) or amount,
                "expiration_minutes": signal.get("expiration_minutes", duration),
            }
            diagnosis = evaluator.evaluate(trade_record, context, conditions, df_m1_after=df_after)
            learner.learn_from_trade(conditions, result, diagnosis)
            state["last_diagnosis"] = evaluator.format_for_display(diagnosis)

            if result == "LOSS":
                cause = diagnosis.get("primary_cause", "unknown")
                log(f"[ANALISIS] Perdida por: {cause} | {diagnosis.get('lessons', ['-'])[0]}")
            elif result == "WIN":
                good = diagnosis.get("what_worked", ["-"])[0]
                log(f"[ANALISIS] Ganancia por: {good}")

            if zone_obj:
                reacted = (result == "WIN" and direction == "CALL" and zone_obj.zone_type == "support") or \
                          (result == "WIN" and direction == "PUT" and zone_obj.zone_type == "resistance")
                memory.add_or_update_zone(asset, zone_obj.level, zone_obj.zone_type, reacted)
                memory.save()

            state["status"] = "ANALIZANDO"
            state["active_order"] = None
            trade_in_progress = False
            return True
        else:
            log(f"Orden rechazada: {order_id}")
            state["status"] = "ANALIZANDO"
            state["active_order"] = None
            trade_in_progress = False
            return False
    except Exception as e:
        log(f"Error ejecutando trade: {e}")
        state["status"] = "ANALIZANDO"
        state["active_order"] = None
        trade_in_progress = False
        return False

# ─── Bucle principal ────────────────────────────────────────────────────────

def bot_loop(market_data, rm, engine, agent_engine):
    email = os.getenv("EXNOVA_EMAIL", "")
    password = os.getenv("EXNOVA_PASSWORD", "")
    learner = get_adaptive_learner()
    memory = get_market_memory()
    evaluator = TradeEvaluator()

    log("Conectando a Exnova PRACTICE...")
    state["status"] = "CONECTANDO"
    if not market_data.connect(email, password):
        log("ERROR: No se pudo conectar.")
        state["status"] = "ERROR"
        return

    try:
        balance = market_data.get_balance()
        balance = float(balance) if balance and float(balance) > 0 else INITIAL_BALANCE
    except:
        balance = INITIAL_BALANCE

    state["balance"] = balance
    state["initial_balance"] = balance
    rm.initialize(balance)
    log(f"Conectado. Balance: ${balance:,.2f}")
    log(f"Aprendizaje: {learner.summary()}")
    state["status"] = "ANALIZANDO"

    asset_idx = 0
    last_reconnect = time.time()
    day_trades = 0

    # Obtener activos activos basados en horario
    activos_config = get_activos_activos()
    activos_disponibles = activos_config["otc_24_7"] + activos_config["ptc_morning"] + activos_config["bo_otc"]
    
    print(f"\n{'='*60}")
    print(f"BOT OPERATIVO - Colombia (UTC-5)")
    print(f"Hora actual: {get_current_time_colombia().strftime('%H:%M:%S')}")
    print(f"Horario mañana (PTC): {es_horario_manana()}")
    print(f"OTC 24/7: {len(activos_config['otc_24_7'])} activos")
    print(f"PTC Mañana: {len(activos_config['ptc_morning'])} activos")
    print(f"BO OTC: {len(activos_config['bo_otc'])} activos")
    print(f"Total a monitorear: {len(activos_disponibles)} activos")
    print(f"{'='*60}\n")

    while state["running"]:
        try:
            state["cycle"] += 1
            now = time.time()

            # Actualizar activos disponibles cada ciclo (por cambio de horario)
            activos_config = get_activos_activos()
            activos_disponibles = activos_config["otc_24_7"] + activos_config["ptc_morning"] + activos_config["bo_otc"]

            # Reconexion
            if now - last_reconnect > 240:
                if not market_data.is_really_connected():
                    log("Reconectando...")
                    market_data.reconnect(email, password)
                last_reconnect = now

            # Cooldown por perdidas
            if state["consecutive_losses"] >= MAX_CONSEC_LOSSES:
                state["status"] = "PAUSA_RIESGO"
                log(f"PAUSA: {state['consecutive_losses']} perdidas seguidas. 5min.")
                time.sleep(300)
                state["consecutive_losses"] = 0
                continue

            # Pausa post-racha
            if state["current_streak"] >= PAUSE_AFTER_WIN_STREAK:
                state["status"] = "PAUSA_WIN_STREAK"
                log(f"Pausa post-racha: {state['current_streak']} wins. {PAUSE_DURATION}s.")
                time.sleep(PAUSE_DURATION)
                state["current_streak"] = 0
                continue

            # Rotar activos dinámicamente
            if not activos_disponibles:
                log("Sin activos disponibles para este horario")
                time.sleep(60)
                continue
                
            asset = activos_disponibles[asset_idx % len(activos_disponibles)]
            asset_idx += 1
            state["current_asset"] = asset
            
            # Determinar tipo de activo para configuración
            if "-OTC" in asset:
                if "-BO" in asset:
                    tipo_activo = "bo_otc"
                else:
                    tipo_activo = "otc_24_7"
            else:
                tipo_activo = "ptc_morning"
            
            # Obtener configuración de sensibilidad para este activo
            config_sens = get_config_sensibilidad(tipo_activo)

            # Obtener candles de diferentes timeframes
            try:
                df_m1 = market_data.get_candles(asset, "1m", 100)
                if df_m1.empty or len(df_m1) < 20:
                    if df_m1.empty:
                        log(f"Sin velas M1 para {asset} (API vacía)", "WARN")
                    continue
                df_m5 = market_data.get_candles(asset, "5m", 100)
                if df_m5.empty or len(df_m5) < 20:
                    if df_m5.empty:
                        log(f"Sin velas M5 para {asset} (API vacía)", "WARN")
                    continue
                df_m15 = market_data.get_candles(asset, "15m", 100)
                if df_m15.empty or len(df_m15) < 20:
                    if df_m15.empty:
                        log(f"Sin velas M15 para {asset} (API vacía)", "WARN")
                    continue
                df_m30 = market_data.get_candles(asset, "30m", 100)
                if df_m30.empty or len(df_m30) < 10:
                    df_m30 = None
                df_h1 = market_data.get_candles(asset, "1h", 100)
                if df_h1.empty or len(df_h1) < 10:
                    df_h1 = None
            except Exception as e:
                log(f"Error obteniendo candles de {asset}: {str(e)[:50]}")
                continue

            # Analizar
            try:
                signal = engine.evaluate_market(asset, df_m1, df_m5, df_m15, df_m30, df_h1)
            except Exception as e:
                log(f"Error analizando {asset}: {str(e)[:50]}")
                continue

            if signal:
                state["last_signal"] = signal
                action = signal.get("action", "WAIT")
                confidence = signal.get("confidence", 0)
                score = signal.get("score", 0)

                if action == "TRADE" and confidence >= MIN_CONFIDENCE:
                    time_since = now - state["last_trade_time"]
                    learning_mode = get_learning_mode()
                    cooldown_mult = learning_mode.get_cooldown_multiplier()
                    cooldown_needed = int((COOLDOWN_AFTER_LOSS if state["consecutive_losses"] > 0 else MIN_BETWEEN_TRADES) * cooldown_mult)
                    signal_dir = signal.get("signal", "CALL")
                    asset_dir_key = f"{asset}_{signal_dir}"
                    last_asset_dir = state["last_trade_by_asset"].get(asset_dir_key, 0)
                    last_asset_any = state["last_trade_by_asset"].get(f"{asset}_*", 0)
                    
                    if state["active_order"] is not None:
                        log(f"⏳ Trade saltado - ya hay orden activa (ID: {state['active_order']})", "WARNING")
                    elif time_since < cooldown_needed:
                        log(f"⏳ Cooldown global: faltan {int(cooldown_needed - time_since)}s", "WAIT")
                    elif (now - last_asset_dir) < MIN_BETWEEN_SAME_ASSET * 2:
                        restante = int(MIN_BETWEEN_SAME_ASSET * 2 - (now - last_asset_dir))
                        log(f"⏳ Cooldown {asset} {signal_dir}: faltan {restante}s", "WAIT")
                    elif rm.is_stopped:
                        log(f"RM activo: {rm.stop_reason}")
                    else:
                        amount = rm.calculate_position_size(confidence=confidence)
                        if amount > 0:
                            executed = execute_trade(market_data, rm, signal, amount, learner, memory, evaluator, agent_engine, df_m15, df_m5)
                            if executed:
                                day_trades += 1
                                state["last_trade_by_asset"][asset_dir_key] = time.time()
                                state["last_trade_by_asset"][f"{asset}_*"] = time.time()
                        else:
                            log(f"RM: amount=0 (conf={confidence:.2f})")
                elif action == "WAIT":
                    reason = signal.get("reason", "")
                    if reason:
                        if any(kw in reason.lower() for kw in ["trap", "rechazo", "zone", "fase", "phase", "esperando"]):
                            log(f"{asset} | {reason[:80]}")

            # Status periodico
            if state["cycle"] % 10 == 0:
                total = state["wins"] + state["losses"]
                wr = (state["wins"] / total * 100) if total > 0 else 0
                elapsed = int(time.time() - state["start_time"])
                sig = state.get("last_signal", {})
                print(f"[{elapsed}s] #{state['cycle']} {asset} | "
                      f"Trades:{total} W/L:{state['wins']}/{state['losses']} WR:{wr:.1f}% "
                      f"PnL:${state['total_pnl']:.2f} Bal:${state['balance']:.2f} | "
                      f"{state['status']}", flush=True)
                if sig:
                    patron = sig.get('pattern', '?')
                    ai = sig.get('ai_label', '?')
                    rsi = sig.get('rsi', 50)
                    zs = sig.get('zone_strength', 0)
                    t15 = sig.get('trend_m15', '?')
                    thf = sig.get('trend_htf', '?')
                    if sig.get('action') == 'TRADE':
                        print(f"  -> {sig.get('signal', '?')} "
                              f"Score={sig.get('score',0):.0f} Conf={sig.get('confidence',0):.2f} "
                              f"Patron={patron} IA={ai} RSI={rsi:.0f} ZS={zs:.2f} "
                              f"T15={t15} T30={thf}", flush=True)
                    else:
                        print(f"  -> WAIT: {sig.get('reason', '')[:60]} "
                              f"Patron={patron} IA={ai} RSI={rsi:.0f} ZS={zs:.2f}", flush=True)

            time.sleep(6)

        except KeyboardInterrupt:
            state["running"] = False
            break
        except Exception as e:
            log(f"Error en loop: {e}")
            time.sleep(5)

    log("Bot detenido.")
    state["status"] = "DETENIDO"
    memory.save()

# ─── Mock data fallback ──────────────────────────────────────────────────────

def get_price_range(asset: str):
    if "JPY" in asset:
        return np.random.uniform(130, 160)
    elif "EUR" in asset or "GBP" in asset:
        return np.random.uniform(1.08, 1.40)
    elif "AUD" in asset or "NZD" in asset or "CAD" in asset:
        return np.random.uniform(0.60, 1.10)
    elif "BTC" in asset:
        return np.random.uniform(40000, 50000)
    elif "ETH" in asset:
        return np.random.uniform(2000, 3000)
    elif "GOLD" in asset:
        return np.random.uniform(1800, 2100)
    elif "OIL" in asset:
        return np.random.uniform(70, 90)
    elif "COPPER" in asset:
        return np.random.uniform(3.5, 4.5)
    elif "-OTC" in asset:
        return np.random.uniform(15000, 50000)
    else:
        return np.random.uniform(1.0, 2.0)

def generate_mock_candles(asset: str, interval: str, limit: int = 100) -> pd.DataFrame:
    now = datetime.utcnow()
    data = []
    price = get_price_range(asset)
    volatility = np.random.uniform(0.001, 0.01)
    for i in range(limit):
        time_offset = now - timedelta(minutes=limit-i)
        open_p = price
        change = np.random.normal(0, volatility)
        close_p = price * (1 + change)
        high_p = max(open_p, close_p) * (1 + np.random.uniform(0, 0.005))
        low_p = min(open_p, close_p) * (1 - np.random.uniform(0, 0.005))
        data.append({
            "time": time_offset,
            "open": open_p, "high": high_p,
            "low": low_p, "close": close_p,
            "volume": np.random.randint(1000, 10000),
        })
        price = close_p
    df = pd.DataFrame(data)
    df.set_index("time", inplace=True)
    return df

# ─── Entry point ────────────────────────────────────────────────────────────

def main():
    risk_config = RiskConfig(
        max_drawdown_daily=0.25, max_trades_per_hour=12,
        cooldown_after_loss_seconds=COOLDOWN_AFTER_LOSS,
        min_confidence_threshold=MIN_CONFIDENCE,
        stop_after_consecutive_losses=MAX_CONSEC_LOSSES,
    )
    rm = initialize_risk_manager(INITIAL_BALANCE, risk_config)
    market_data = MarketDataHandler(broker_name="exnova", account_type="PRACTICE")
    engine = IntelligentEngine(session_name="bot_live")
    state["start_time"] = time.time()

    # Inicializar el motor del agente IA para filtrado y aprendizaje continuo
    github_token = os.getenv("GITHUB_TOKEN", "")
    if not github_token:
        log("ADVERTENCIA: GITHUB_TOKEN no configurado. Algunas funciones de IA pueden no funcionar.", "WARNING")
    log("Inicializando AgentTradingEngine...")
    agent_engine = get_agent_trading_engine(github_token)

    bot_loop(market_data, rm, engine, agent_engine)

    # Resumen final
    total = state["wins"] + state["losses"]
    wr = (state["wins"] / total * 100) if total > 0 else 0
    print(f"\n{'='*60}")
    print(f"RESUMEN FINAL")
    print(f"{'='*60}")
    print(f"Duracion: {int(time.time() - state['start_time'])}s")
    print(f"Trades: {total} | W: {state['wins']} L: {state['losses']}")
    print(f"Win Rate: {wr:.1f}%")
    print(f"PnL: ${state['total_pnl']:.2f}")
    print(f"Balance: ${state['balance']:.2f}")
    print(f"Mejor racha: +{state['best_streak']}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
