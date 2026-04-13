#!/usr/bin/env python3
"""
BOT DE TRADING EXNOVA - MODO PRACTICE SIMPLE
Version simplificada sin emojis - Replica del main_headless.py funcional
"""
import sys
import os
import time
import signal
from datetime import datetime

# Asegurar path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import modules
from config import Config
from data.market_data import MarketDataHandler
from strategies.technical import FeatureEngineer
from core.agent import RLAgent
from core.risk import RiskManager
from core.asset_manager import AssetManager
from core.trader import LiveTrader

running = True
trader = None

def signal_handler(sig, frame):
    """Shutdown graceful"""
    global running
    print("\n[SIGNAL] Shutdown recibido. Cerrando bot...")
    running = False
    if trader:
        trader.stop()
    sys.exit(0)

def main():
    global running, trader
    
    signal.signal(signal.SIGINT, signal_handler)
    
    print("=" * 80)
    print("[BOT] EXNOVA TRADING - MODO PRACTICE (SIN EMOJIS)")
    print("=" * 80)
    print(f"[TIME] Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[CONFIG] Capital: ${Config.CAPITAL_PER_TRADE}")
    print(f"[CONFIG] Estrategia: Tendencia + Reversión + Detección de Resistencias")
    print(f"[CONFIG] MEJORA ACTIVA: Cooldown 5min por activo (evita sobreoperación)")
    print("=" * 80)
    
    try:
        # 1. MARKET DATA (Conexión al broker)
        print("[INIT] Inicializando MarketDataHandler...")
        email = Config.EXNOVA_EMAIL
        password = Config.EXNOVA_PASSWORD
        
        if not email or not password:
            print("[ERROR] Faltan credenciales en .env")
            return 1
        
        market_data = MarketDataHandler(broker_name="exnova", account_type="PRACTICE")
        
        print("[CONNECT] Conectando a Exnova...")
        if not market_data.connect(email, password):
            print("[ERROR] No se pudo conectar a Exnova")
            return 1
        
        print("[OK] Conectado a Exnova PRACTICE")
        try:
            balance = market_data.get_balance()
            print(f"[BALANCE] Saldo disponible: ${balance:.2f}")
        except:
            print("[BALANCE] No disponible al conectar")
        
        # 2. TECHNICAL ANALYSIS
        print("[INIT] Cargando FeatureEngineer...")
        feature_engineer = FeatureEngineer()
        
        # 3. AGENT (Sin LLM para evitar errores)
        print("[INIT] Cargando RLAgent...")
        agent = RLAgent()
        
        # 4. RISK MANAGER
        print("[INIT] Configurando RiskManager...")
        risk_manager = RiskManager(
            capital_per_trade=Config.CAPITAL_PER_TRADE,
            stop_loss_pct=Config.STOP_LOSS_PERCENT,
            take_profit_pct=Config.TAKE_PROFIT_PERCENT,
            max_martingale_steps=Config.MAX_MARTINGALE
        )
        
        # 5. ASSET MANAGER
        print("[INIT] Cargando AssetManager...")
        asset_manager = AssetManager(market_data)
        
        # 6. LIVE TRADER (El core del bot)
        print("[INIT] Inicializando LiveTrader...")
        trader = LiveTrader(
            market_data=market_data,
            feature_engineer=feature_engineer,
            agent=agent,
            risk_manager=risk_manager,
            asset_manager=asset_manager,
            llm_client=None  # SIN LLM para evitar errores de emojis
        )
        
        # Conectar signals a funciones simples
        def log_message(msg):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        
        def error_message(msg):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERROR] {msg}")
        
        trader.signals.log_message.connect(log_message)
        trader.signals.error_message.connect(error_message)
        
        print("\n" + "=" * 80)
        print("[MEJORAS] Validando configuración de Cooldown por Activo")
        print("=" * 80)
        print(f"[CONFIG] cooldown_per_asset = {trader.cooldown_per_asset}s (5 minutos)")
        print(f"[CONFIG] max_consecutive_losses = {trader.max_consecutive_losses}")
        print(f"[CONFIG] min_time_between_trades = {trader.min_time_between_trades}s")
        print("\n[MENSAJE] Espera a que el bot inicie operaciones...")
        print("[MENSAJE] Presiona CTRL+C para detener")
        print("=" * 80 + "\n")
        
        # 7. LANZAR BOT
        print("[START] Iniciando LiveTrader en hilo separado...")
        trader.start()
        
        # Mantener el programa corriendo
        try:
            while trader.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[STOP] Interrupción detectada...")
            trader.stop()
            time.sleep(2)
            print("[OK] Bot detenido correctamente")
        
        return 0
        
    except Exception as e:
        print(f"\n[FATAL] Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
