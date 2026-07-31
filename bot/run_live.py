# -*- coding: utf-8 -*-
"""
Ejecuta el bot Exnova en modo texto (stdout) para monitoreo desde consola.

Este archivo es la fusion de los dos run_live.py que coexistian en el repo
(bot/run_live.py y el run_live.py de la raiz, este ultimo eliminado) mas el
diario/guard construidos en 2026-07-31. Motivo de la fusion, documentado para
que no se repita: el Dockerfile ejecutaba el run_live.py de la raiz, que NO
conocia trade_journal.py ni position_guard.py -- todo el trabajo de logging
real de esa fecha era efectivamente codigo muerto en produccion. Ahora solo
existe UN archivo, y es este.

Decisiones de reconciliacion tomadas al fusionar (documentadas, no ocultas):
  - RSI: se usa signal["rsi"] directamente (viene real de intelligent_engine.py
    en TODAS sus ramas de retorno). La version anterior de este archivo leia
    context.get("momentum",{}).get("rsi_m1",50) con context SIEMPRE {} (el
    diccionario que devuelve evaluate_market no tiene clave "context"), lo que
    contaminaba rsi_at_touch con 50 constante en el pipeline legado hacia
    agent_engine. Corregido tomando el campo real de signal.
  - zone_learner.record_trade_result: se usa la firma real del metodo
    (asset, direction, entry, exit, result, level) -- la version anterior de
    bot/run_live.py llamaba con entry_price=/exit_price=, kwargs que no
    existen, lanzando TypeError silencioso en cada trade real.
  - Parametros de riesgo para cuenta REAL: se toma el mas conservador de cada
    dimension entre las dos versiones que divergian (root vs bot/), porque a
    fecha de hoy NINGUN setup tiene edge demostrado con significancia
    estadistica (ver bot/core/self_evaluator.py) -- no hay base para asumir
    mas riesgo por operacion o mas frecuencia de la necesaria.
  - Monto fijo en REAL en vez de Kelly: Kelly asume una probabilidad de
    ganar conocida y precisa; sin edge demostrado esa entrada es una
    suposicion, no un dato, así que el sizing por Kelly en REAL amplificaria
    una apuesta sobre ruido. Monto fijo minimo mientras tanto.
  - Skip anti-deteccion tambien activo en REAL: cada operacion evitada es un
    dolar real no arriesgado sobre un sistema sin edge probado. La version
    anterior lo desactivaba en REAL bajo la logica de "cada trade cuenta",
    pero eso solo tiene sentido si el sistema tuviera edge positivo conocido.
  - Whitelist estatica de activos en REAL: se mantiene RETIRADA (decision ya
    tomada en 2026-07, ver comentario mas abajo) -- verificado que ningun
    activo del historial tenia muestra suficiente para que "buen WR" fuera
    señal y no ruido.
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
    get_current_time_colombia, es_horario_manana, ASSETS_OTC_24_7, ASSETS_PTC_MORNING,
    BAD_PATTERNS, ASSETS_BLACKLIST,
    REAL_PATTERNS_ALLOWED,
    REAL_ZONE_STRENGTH_MIN, REAL_ZONE_STRENGTH_MAX,
)
from data.market_data import MarketDataHandler
from core.advanced_risk_manager import initialize_risk_manager, RiskConfig
from brain.adaptive_learner import get_adaptive_learner
from brain.market_memory import get_market_memory
from brain.supervised_zone_learner import get_supervised_zone_learner
from brain.practice_trader import PracticeTrader
from brain.trade_evaluator import TradeEvaluator
from brain.adaptive_learning_mode import get_learning_mode
from brain.trade_persistence import get_trade_persistence
from engine.intelligent_engine import IntelligentEngine
from brain.agent_trading_engine import get_agent_trading_engine
from core.smart_money_analyzer import SmartMoneyAnalyzer
# Diario con features REALES y control de concurrencia por activo.
# El diario anterior guardaba rsi_at_touch=50 en 495 de 500 operaciones porque
# se rellenaba con defaults; sin features reales no hay nada que analizar despues.
from core.trade_journal import get_journal, features_from_candles
from core.position_guard import get_guard, GuardConfig

# ─── Constantes (sobreescribibles via env vars para EasyPanel) ──────────────
INITIAL_BALANCE    = float(os.getenv("INITIAL_BALANCE", "10000.0"))
MIN_CONFIDENCE     = float(os.getenv("MIN_CONFIDENCE", "0.60"))
COOLDOWN_AFTER_LOSS = int(os.getenv("COOLDOWN_AFTER_LOSS", "300"))
MIN_BETWEEN_TRADES  = int(os.getenv("MIN_BETWEEN_TRADES", "180"))
MIN_BETWEEN_SAME_ASSET = int(os.getenv("MIN_BETWEEN_SAME_ASSET", "300"))
MAX_CONSEC_LOSSES   = int(os.getenv("MAX_CONSEC_LOSSES", "5"))
PAUSE_AFTER_WIN_STREAK = int(os.getenv("PAUSE_AFTER_WIN_STREAK", "10"))
PAUSE_DURATION = int(os.getenv("PAUSE_DURATION", "120"))

# Cuenta: PRACTICE (default) o REAL (solo si se fuerza explícitamente)
ACCOUNT_TYPE = os.getenv("ACCOUNT_TYPE", "PRACTICE").upper()
if ACCOUNT_TYPE not in ("PRACTICE", "REAL"):
    print(f"[WARNING] ACCOUNT_TYPE inválido '{ACCOUNT_TYPE}', usando PRACTICE")
    ACCOUNT_TYPE = "PRACTICE"
elif ACCOUNT_TYPE == "REAL":
    confirm = os.getenv("REAL_ACCOUNT_CONFIRMED", "false").lower()
    if confirm != "true":
        print("[CRITICAL] ⚠️  CUENTA REAL DETECTADA pero REAL_ACCOUNT_CONFIRMED no es 'true'. Forzando PRACTICE por seguridad.")
        ACCOUNT_TYPE = "PRACTICE"
    else:
        print("[CRITICAL] ⚠️  CUENTA REAL ACTIVADA - Operando con dinero real")

# Demo trading: envia ordenes demo reales al broker (PRACTICE), basadas en el
# escaner de zonas de PracticeTrader. Desactivado por defecto.
DEMO_TRADING = os.getenv("DEMO_TRADING", "false").lower() == "true"
DEMO_AMOUNT = float(os.getenv("DEMO_AMOUNT", "2.0"))
if DEMO_TRADING:
    print(f"[DEMO] Modo demo activado - enviando ordenes reales a Exnova PRACTICE (${DEMO_AMOUNT}/trade)")

# ─── Anti-detección / Humanización ──────────────────────────────────────────
HUMAN_SKIP_PROBABILITY = 0.18  # 18% de trades válidos se saltan (parecer humano)
HUMAN_JITTER_FACTOR = 0.25  # ±25% de variación aleatoria en tiempos
HUMAN_DELAY_AFTER_TRADE_MIN = 5  # Delay post-trade mínimo (seg)
HUMAN_DELAY_AFTER_TRADE_MAX = 20  # Delay post-trade máximo (seg)
HUMAN_MICRO_PAUSE = 15  # Pausa aleatoria cada ~N ciclos

# ─── Estado global ──────────────────────────────────────────────────────────
from collections import deque

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
    "last_wait_duration": 6,
    # Demo trading state
    "demo_order": None,
    "demo_wins": 0, "demo_losses": 0, "demo_pnl": 0.0, "demo_balance": 0.0,
    "demo_trades": [],
}

# Lock para evitar operaciones simultáneas
trade_lock = threading.Lock()
trade_in_progress = False

def log(msg, level="INFO"):
    now = time.strftime("%H:%M:%S")
    print(f"[{now}] [{level}] {msg}", flush=True)

# ─── Trade execution ────────────────────────────────────────────────────────

sm_analyzer = SmartMoneyAnalyzer()

def execute_trade(market_data, rm, signal, amount, learner, memory, evaluator, agent_engine, zone_learner, df_m15=None, df_m5=None, df_m1=None):
    global trade_in_progress

    asset = signal["asset"]
    direction = signal["signal"]
    confidence = signal["confidence"]
    expiration = signal.get("expiration", 60)
    pattern = signal.get("pattern", "")
    zone_str = signal.get("zone_strength", 0.0)
    zone_obj = signal.get("zone_object")
    rsi_val = signal.get("rsi", 50)
    pattern_name = pattern
    trend_align = signal.get("trend_aligned", False)

    # `context` legado ({} siempre: evaluate_market no emite esa clave) se
    # sustituye por un diccionario de condiciones construido directamente con
    # los campos reales de `signal`, para que TradeEvaluator/AdaptiveLearner
    # reciban datos de verdad y no un dict vacio en cada operacion.
    context = {}
    conditions = {
        "zone_strength_high": zone_str > 0.7,
        "zone_strength_medium": 0.5 <= zone_str <= 0.7,
        "zone_multi_tf": signal.get("multi_tf", False),
        "trend_aligned": trend_align,
        "trend_strong": signal.get("trend_strong", False),
        "counter_trend": signal.get("counter_trend", False),
        "rsi_extreme": rsi_val < 25 or rsi_val > 75,
        "rsi_oversold": rsi_val < 35,
        "rsi_overbought": rsi_val > 65,
        "rsi_divergence": signal.get("rsi_divergence", False),
        "pattern_pin_bar": "pin_bar" in pattern_name,
        "pattern_engulfing": "engulfing" in pattern_name,
        "pattern_hammer": "hammer" in pattern_name,
        "pattern_doji_reversal": "doji" in pattern_name,
        "pattern_strong": bool(pattern_name) and "none" not in pattern_name,
        "setup_quality_high": signal.get("score", 0) >= 70,
        "market_phase_ranging": signal.get("market_phase", "") == "ranging",
        "market_phase_trending": signal.get("market_phase", "") == "trending",
    }

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

    # ── UNA SOLA OPERACIÓN POR ACTIVO ───────────────────────────────────────
    # Hasta conocer el resultado no se vuelve a entrar en la misma divisa.
    # Apilar entradas sobre la misma señal añade filas al dataset pero menos de
    # una observación independiente por fila, y eso corrompe la medición del
    # winrate que luego se usa para refinar.
    guard = get_guard()
    permitido, motivo = guard.can_trade(asset)
    if not permitido:
        log(f"[GUARD] {asset} bloqueado: {motivo}", "WAIT")
        return False

    try:
        zone_level = signal.get("zone", 0.0) or signal.get("entry_price", 0.0) or 0.0
        allowed, supervised_reason, supervised_details = zone_learner.get_opportunity(asset, direction, float(zone_level))
        if not allowed:
            log(f"[SUPERVISADO] {supervised_reason} | toques={supervised_details.get('touches', 0)} holds={supervised_details.get('holds', 0)}", "WARNING")
            state["status"] = "OBSERVANDO_ZONA"
            return False
        log(f"[SUPERVISADO] {supervised_reason} | strength={supervised_details.get('strength', 0):.2f} hold_rate={supervised_details.get('hold_rate', 0)*100:.0f}%")
    except Exception as e:
        log(f"[SUPERVISADO] Error validando zona: {e}", "WARNING")
        return False

    with trade_lock:
        # Marcar que hay una operación en progreso
        trade_in_progress = True
        state["active_order"] = f"pending_{time.time()}"

    # ── ORDER BLOCK M15: potenciador de confianza, NO bloqueante ────────────
    ob_validation = {'valid': False, 'reason': 'No M15 data', 'trend_aligned': False, 'trend': 'neutral'}
    if df_m15 is not None and len(df_m15) >= 20:
        ob_validation = sm_analyzer.validate_trade_with_ob(df_m15, direction)

        if ob_validation.get('ob') is not None:
            ob = ob_validation['ob']
            ob_type = "alcista" if ob['type'] == 'bullish' else "bajista"
            log(f"[OB M15] Order Block {ob_type} detectado: {ob['low']:.5f}-{ob['high']:.5f} (fuerza: {ob['strength']:.0f}%)")

        if not ob_validation['valid']:
            log(f"[OB M15] ⚠️ Sin OB M15, operando solo con señales técnicas", "WARNING")
        elif not ob_validation['trend_aligned']:
            log(f"[OB M15] ⚠️ Tendencia ({ob_validation['trend']}) no alineada, pero se procede con precaución", "WARNING")
        else:
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
        # RSI real: viene directo de signal["rsi"], que intelligent_engine.py
        # rellena con el RSI de Wilder calculado sobre velas M1 en TODAS sus
        # ramas de retorno. Antes se leia via context.get(...) con context
        # siempre {}, lo que fijaba este valor en 50 constante.
        'rsi': rsi_val,
        'trend': signal.get("trend_m15", "NEUTRAL"),
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
        trade_in_progress = False
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

            # ── DIARIO: registrar el estado REAL del mercado en la entrada ───
            # features_from_candles calcula sobre velas cerradas y devuelve None
            # en lo que no pueda calcular. Nunca un default: un hueco es honesto,
            # un 50 inventado contamina el dataset para siempre.
            journal = get_journal()
            journal_rec = None
            try:
                feats = features_from_candles(df_m1, df_m5, df_m15) if df_m1 is not None else {}
                feats.setdefault("pattern", pattern or None)
                feats.setdefault("zone_type", zone_obj.zone_type if zone_obj else None)
                feats.setdefault("zone_strength", zone_str if zone_str else None)
                journal_rec = journal.open_trade(
                    asset=asset, direction=direction,
                    strategy=signal.get("strategy", "intelligent_engine"),
                    setup=signal.get("setup", pattern or "sin_patron"),
                    amount=amount, expiration_seconds=expiration,
                    confidence=confidence, features=feats,
                    account_type=ACCOUNT_TYPE,
                )
                guard.register_open(asset)
            except Exception as e:
                log(f"[DIARIO] No se pudo registrar la entrada: {e}", "WARNING")

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

            # ── DIARIO: cerrar la operación con su resultado ─────────────────
            try:
                if journal_rec is not None:
                    journal.close_trade(journal_rec.trade_id, result, pnl)
                guard.register_close(asset, result, pnl)
            except Exception as e:
                log(f"[DIARIO] No se pudo registrar el cierre: {e}", "WARNING")

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
                    'confidence': confidence,
                    'score': signal.get("score", 0),
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
                "entry_price": current_price,
                "expiration_minutes": signal.get("expiration_minutes", duration),
            }
            diagnosis = evaluator.evaluate(trade_record, context, conditions, df_m1_after=df_after)
            learner.learn_from_trade(conditions, result, diagnosis)
            state["last_diagnosis"] = evaluator.format_for_display(diagnosis)

            try:
                exit_price = 0.0
                if df_after is not None and not df_after.empty:
                    exit_price = float(df_after.iloc[-1].get("close", 0.0))
                # Firma real: record_trade_result(asset, direction, entry, exit,
                # result, level=0.0). Antes se llamaba con entry_price=/exit_price=,
                # kwargs inexistentes -> TypeError tragado en silencio en cada trade.
                zone_learner.record_trade_result(
                    asset=trade_record["asset"],
                    direction=trade_record["direction"],
                    entry=float(trade_record.get("entry_price", 0.0)),
                    exit=float(exit_price),
                    result=result,
                    level=float(signal.get("zone", 0.0) or trade_record.get("entry_price", 0.0))
                )
                log("[SUPERVISADO] Resultado guardado en memoria de zonas")
            except Exception as e:
                log(f"[SUPERVISADO] Error guardando aprendizaje: {e}", "WARNING")

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

            # Anti-detección: delay post-trade variable (parecer humano analizando)
            post_trade_delay = np.random.uniform(HUMAN_DELAY_AFTER_TRADE_MIN, HUMAN_DELAY_AFTER_TRADE_MAX)
            log(f"[ANTI-DETECCIÓN] Analizando resultado... ({post_trade_delay:.0f}s)")
            time.sleep(post_trade_delay)

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
    persistence = get_trade_persistence()
    learner = get_adaptive_learner()
    memory = get_market_memory()
    zone_learner = get_supervised_zone_learner()
    practice = PracticeTrader(zone_learner)
    evaluator = TradeEvaluator()

    log(f"Conectando a Exnova {ACCOUNT_TYPE}...")
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

            # ── Demo trading: verificar orden pendiente ──────────────────────
            if DEMO_TRADING and state.get("demo_order"):
                demo = state["demo_order"]
                if time.time() - demo["entry_time"] >= demo["expiration_sec"] + 10:
                    try:
                        result_data = market_data.api.check_win_v4(demo["id"])
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
                            elif profit < 0:
                                pnl, result = -demo["amount"], "LOSS"
                            else:
                                pnl, result = 0.0, "DRAW"

                            state["demo_wins"] += 1 if result == "WIN" else 0
                            state["demo_losses"] += 1 if result == "LOSS" else 0
                            state["demo_pnl"] += pnl
                            state["demo_balance"] += pnl
                            state["demo_trades"].append({
                                "time": time.strftime("%H:%M:%S"),
                                "asset": demo["asset"], "direction": demo["direction"],
                                "amount": demo["amount"], "result": result, "pnl": pnl,
                                "zone_level": demo.get("zone_level", 0),
                            })

                            # Feedback al zone_learner (firma real: entry=/exit=)
                            zone_learner.record_trade_result(
                                asset=demo["asset"], direction=demo["direction"],
                                entry=demo["entry_price"], exit=0.0,
                                result=result, level=demo.get("zone_level", 0),
                            )

                            agent_engine.record_trade_result({
                                'asset': demo['asset'],
                                'direction': demo['direction'],
                                'amount': demo['amount'],
                                'result': result,
                                'pnl': pnl,
                                'pattern': demo.get('zone_type', 'demo'),
                                'zone_strength': demo.get('zone_win_rate', 0),
                                'confidence': demo.get('zone_win_rate', 0.5),
                                'score': int(demo.get('zone_win_rate', 0.5) * 100),
                                'rsi_at_touch': 50,
                                'trend_aligned': False,
                            })

                            icon = "🟢" if result == "WIN" else "🔴"
                            log(f"[DEMO] {icon} {result} {demo['direction']} {demo['asset']} "
                                f"${pnl:+.2f} | balance demo: ${state['demo_balance']:.2f}", "INFO")
                        else:
                            log(f"[DEMO] Sin confirmacion de orden {demo['id']}, asumiendo LOSS", "WARNING")
                            state["demo_losses"] += 1
                            state["demo_pnl"] -= demo["amount"]
                            state["demo_balance"] -= demo["amount"]
                    except Exception as e:
                        log(f"[DEMO] Error verificando orden: {e}", "WARNING")
                    state["demo_order"] = None

            # Rotar activos dinámicamente
            if not activos_disponibles:
                log("Sin activos disponibles para este horario")
                time.sleep(60)
                continue

            # Filtrar activos blacklisteados (bajo rendimiento histórico)
            activos_disponibles = [a for a in activos_disponibles if a not in ASSETS_BLACKLIST]
            if persistence is not None and persistence.total_trades >= 50:
                bad = set()
                for a in activos_disponibles:
                    ta = persistence.get_trades_by_asset(a)
                    if len(ta) >= 3:
                        w = sum(1 for t in ta if t.get('result') == 'WIN')
                        if w / len(ta) < 0.30:
                            bad.add(a)
                activos_disponibles = [a for a in activos_disponibles if a not in bad]
            if not activos_disponibles:
                log("Todos los activos están en blacklist - esperando...")
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

            # Observar mercado para aprendizaje supervisado
            try:
                zonas_actualizadas = zone_learner.observe(asset, df_m1, df_m15)
                if zonas_actualizadas > 0 and state["cycle"] % 10 == 0:
                    sumario = zone_learner.summary(asset)
                    if sumario.get("total_zonas", 0) > 0:
                        log(f"[SUPERVISADO] {asset}: {sumario['total_zonas']} zonas, "
                            f"{sumario.get('analisis_pendientes', 0)} pendientes, "
                            f"{sumario.get('analisis_completados', 0)} completados, "
                            f"WR={sumario.get('win_rate_real', 0):.0f}%", "INFO")
            except Exception as e:
                log(f"[SUPERVISADO] Error observando {asset}: {e}", "WARNING")

            # PracticeTrader: escanear zonas listas y resolver trades virtuales
            try:
                current_price = float(df_m1["close"].iloc[-1]) if df_m1 is not None and not df_m1.empty else None
                if current_price:
                    pt_trade = practice.scan_and_trade(asset, current_price, df_m1)
                    if pt_trade:
                        zs = pt_trade.zone_win_rate
                        log(f"[PRACTICE] 🎯 Trade virtual {pt_trade.direction} {asset} @ {pt_trade.entry_price:.5f} | "
                            f"zona WR={zs*100:.0f}% exp={pt_trade.expiration_sec}s", "SUCCESS")

                        # Demo trading real: enviar orden al broker en modo PRACTICE
                        if DEMO_TRADING and state["demo_order"] is None:
                            try:
                                action = "call" if pt_trade.direction == "CALL" else "put"
                                exp_min = max(1, pt_trade.expiration_sec // 60)
                                check, order_id = market_data.buy(asset, DEMO_AMOUNT, action, exp_min)
                                if check:
                                    state["demo_order"] = {
                                        "id": order_id,
                                        "asset": asset,
                                        "direction": pt_trade.direction,
                                        "amount": DEMO_AMOUNT,
                                        "entry_price": pt_trade.entry_price,
                                        "entry_time": time.time(),
                                        "expiration_sec": pt_trade.expiration_sec,
                                        "zone_level": pt_trade.zone_level,
                                        "zone_win_rate": pt_trade.zone_win_rate,
                                        "zone_strength": pt_trade.zone_strength,
                                    }
                                    log(f"[DEMO] 📈 Orden {pt_trade.direction} {asset} ${DEMO_AMOUNT:.2f} exp={exp_min}min | "
                                        f"zona WR={zs*100:.0f}%", "SUCCESS")
                            except Exception as e:
                                log(f"[DEMO] Error enviando orden: {e}", "WARNING")

                    res = practice.resolve_pending(asset, current_price)
                    if res > 0:
                        ps = practice.get_stats()
                        log(f"[PRACTICE] {res} trade(s) resueltos. Balance: ${ps['balance']:.2f} (PnL: ${ps['pnl']:.2f})", "INFO")
            except Exception as e:
                log(f"[PRACTICE] Error: {e}", "WARNING")

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

                # Validación extra de patrón (doble filtro)
                pattern = signal.get("pattern", "")
                if pattern in BAD_PATTERNS:
                    log(f"[FILTRO] Patrón peligroso saltado: {pattern}", "WARNING")
                    continue

                # Validación de alineación de tendencia
                trend_aligned = signal.get("trend_aligned", False)
                if not trend_aligned and signal.get("score", 0) < 45:
                    log(f"[FILTRO] Contra-tendencia sin score suficiente: score={signal.get('score',0):.0f}", "WARNING")
                    continue

                direccion = signal.get("signal", "")
                if direccion == "PUT" and confidence < MIN_CONFIDENCE + 0.15:
                    log(f"[FILTRO] PUT confianza baja ({confidence:.2f} < {MIN_CONFIDENCE+0.15:.2f})", "WARNING")
                    continue

                if action == "TRADE" and confidence >= MIN_CONFIDENCE:
                    # ═══════════════════════════════════════════════════════════
                    # FILTRO ULTRASEGURO para CUENTA REAL
                    # ═══════════════════════════════════════════════════════════
                    if ACCOUNT_TYPE == "REAL":
                        pattern = signal.get("pattern", "")
                        zone_str = signal.get("zone_strength", 0)
                        signal_dir = signal.get("signal", "CALL")

                        # NOTA: el gate por REAL_ASSETS_WHITELIST se retiró (2026-07).
                        # Se verificó contra bot/brain/trade_history.json: ningún activo
                        # tiene 30+ operaciones (mediana 4, 107 activos distintos), por lo
                        # que "100% WR" en un activo del whitelist a menudo es 1 sola
                        # operación. No es evidencia, es ruido. La seguridad real viene de
                        # los gates universales y sí probados (alineación de tendencia,
                        # calidad de patrón) que ya aplica IntelligentEngine antes de esto,
                        # mas el candado de asset_discovery.py (activos reales vs OTC
                        # verificados contra el broker) y self_evaluator.py (edge por
                        # setup con intervalo de Wilson) segun se vayan cableando.
                        if asset in ASSETS_BLACKLIST:
                            log(f"[REAL] {asset} está en blacklist histórica - saltando", "WARNING")
                            continue

                        if pattern not in REAL_PATTERNS_ALLOWED:
                            log(f"[REAL] Patrón '{pattern}' no está en whitelist - saltando", "WARNING")
                            continue

                        if zone_str < REAL_ZONE_STRENGTH_MIN or zone_str > REAL_ZONE_STRENGTH_MAX:
                            log(f"[REAL] Zona strength {zone_str:.2f} fuera del rango óptimo ({REAL_ZONE_STRENGTH_MIN}-{REAL_ZONE_STRENGTH_MAX}) - saltando", "WARNING")
                            continue

                        if confidence < 0.75:
                            log(f"[REAL] Confianza {confidence:.2f} < 0.75 para cuenta REAL - saltando", "WARNING")
                            continue

                        log(f"[REAL] ✅ Señal SUPER APROBADA: {asset} {signal_dir} | patrón={pattern} zona={zone_str:.2f}")

                    time_since = now - state["last_trade_time"]
                    learning_mode = get_learning_mode()
                    cooldown_mult = learning_mode.get_cooldown_multiplier()

                    # Jitter humano en cooldowns
                    base_cooldown = COOLDOWN_AFTER_LOSS if state["consecutive_losses"] > 0 else MIN_BETWEEN_TRADES
                    jitter = np.random.uniform(-HUMAN_JITTER_FACTOR, HUMAN_JITTER_FACTOR) * base_cooldown
                    cooldown_needed = int((base_cooldown + jitter) * cooldown_mult)
                    cooldown_needed = max(30, cooldown_needed)

                    signal_dir = signal.get("signal", "CALL")
                    asset_dir_key = f"{asset}_{signal_dir}"
                    last_asset_dir = state["last_trade_by_asset"].get(asset_dir_key, 0)
                    last_asset_any = state["last_trade_by_asset"].get(f"{asset}_*", 0)

                    same_asset_jitter = int(MIN_BETWEEN_SAME_ASSET + np.random.uniform(-30, 90))
                    same_asset_jitter = max(60, same_asset_jitter)

                    # Anti-detección: skip aleatorio, TAMBIEN en REAL. Sin edge
                    # demostrado, cada operacion evitada es un dolar real no
                    # arriesgado sobre un sistema sin ventaja probada.
                    if np.random.random() < HUMAN_SKIP_PROBABILITY and state["consecutive_losses"] == 0:
                        log(f"[ANTI-DETECCIÓN] Saltando trade válido para perfil humano")
                        continue

                    if state["active_order"] is not None:
                        log(f"⏳ Trade saltado - ya hay orden activa (ID: {state['active_order']})", "WARNING")
                    elif time_since < cooldown_needed:
                        log(f"⏳ Cooldown global: faltan {int(cooldown_needed - time_since)}s", "WAIT")
                    elif (now - last_asset_dir) < same_asset_jitter:
                        restante = int(same_asset_jitter - (now - last_asset_dir))
                        log(f"⏳ Cooldown {asset} {signal_dir}: faltan {restante}s", "WAIT")
                    elif rm.is_stopped:
                        log(f"RM activo: {rm.stop_reason}")
                    else:
                        if ACCOUNT_TYPE == "REAL":
                            # Monto fijo, no Kelly: Kelly asume una probabilidad
                            # de ganar conocida, y hoy no hay edge demostrado
                            # (ver bot/core/self_evaluator.py). Sizear por Kelly
                            # sobre una suposicion amplificaria una apuesta
                            # sobre ruido.
                            amount = 1.0
                        else:
                            base_amount = rm.calculate_position_size(confidence=confidence)
                            amount = max(1.0, round(base_amount * np.random.uniform(0.80, 1.20), 2))
                        if amount > 0:
                            executed = execute_trade(market_data, rm, signal, amount, learner, memory, evaluator, agent_engine, zone_learner, df_m15, df_m5, df_m1)
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
                sz = zone_learner.summary()
                print(f"[{elapsed}s] #{state['cycle']} {asset} | "
                      f"Trades:{total} W/L:{state['wins']}/{state['losses']} WR:{wr:.1f}% "
                      f"PnL:${state['total_pnl']:.2f} Bal:${state['balance']:.2f} | "
                      f"{state['status']}", flush=True)
                if sz.get("total_zonas", 0) > 0:
                    print(f"  [SUPER] {sz['total_zonas']} zonas | "
                          f"Pend:{sz.get('analisis_pendientes', 0)} Completos:{sz.get('analisis_completados', 0)} "
                          f"WR_real:{sz.get('win_rate_real', 0):.0f}% "
                          f"Listas:{sz.get('listas_para_practice', 0)}", flush=True)
                ps = practice.get_stats()
                if ps["trades"] > 0:
                    print(f"  [PRACTICE] Balance:${ps['balance']:.2f} "
                          f"Trades:{ps['trades']} W/L:{ps['wins']}/{ps['losses']} "
                          f"WR:{ps['win_rate']:.1f}% PnL:${ps['pnl']:.2f} "
                          f"Pend:{ps['pending']}", flush=True)
                if DEMO_TRADING and state["demo_trades"]:
                    d = state
                    dt = len(d["demo_trades"])
                    dwr = d["demo_wins"] / max(d["demo_wins"] + d["demo_losses"], 1) * 100
                    print(f"  [DEMO] Balance:${d['demo_balance']:.2f} "
                          f"Trades:{dt} W/L:{d['demo_wins']}/{d['demo_losses']} "
                          f"WR:{dwr:.1f}% PnL:${d['demo_pnl']:.2f} "
                          f"{'⏳' if d.get('demo_order') else ''}", flush=True)
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

            # Anti-detección: pausa variable con jitter humano
            cycle_sleep = max(3, int(6 + np.random.normal(0, 2)))
            state["last_wait_duration"] = cycle_sleep
            time.sleep(cycle_sleep)

            # Micro-pausas aleatorias para parecer humano
            if state["cycle"] % HUMAN_MICRO_PAUSE == 0:
                extra = int(np.random.uniform(5, 30))
                log(f"[ANTI-DETECCIÓN] Pausa corta de {extra}s (perfil humano)", "WAIT")
                time.sleep(extra)

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
    # Configuración de riesgo según tipo de cuenta.
    # Para REAL: se toma el mas conservador de cada dimension entre las dos
    # versiones que divergian (2/4/2/0.75 vs 5/15/3/0.70) porque no hay edge
    # demostrado con significancia estadistica todavia.
    if ACCOUNT_TYPE == "REAL":
        log("⚠️  CONFIGURACIÓN ULTRASEGURA PARA CUENTA REAL", "CRITICAL")
        risk_config = RiskConfig(
            max_drawdown_daily=0.50,
            max_trades_per_hour=2,
            max_trades_per_day=4,
            cooldown_after_loss_seconds=600,
            stop_after_consecutive_losses=2,
            min_confidence_threshold=0.75,
            kelly_ceiling=0.50,
            kelly_floor=0.25,
            anti_detection_jitter=False,
            anti_detection_skip_rate=0.0,
        )
    else:
        risk_config = RiskConfig(
            max_drawdown_daily=0.25, max_trades_per_hour=12,
            cooldown_after_loss_seconds=COOLDOWN_AFTER_LOSS,
            min_confidence_threshold=MIN_CONFIDENCE,
            stop_after_consecutive_losses=MAX_CONSEC_LOSSES,
        )
    rm = initialize_risk_manager(INITIAL_BALANCE, risk_config)
    market_data = MarketDataHandler(broker_name="exnova", account_type=ACCOUNT_TYPE)
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
