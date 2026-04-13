#!/usr/bin/env python3
"""
MONITOREO DE FASE 3: Medir efectividad del sistema de confluencia en PRACTICE
"""
import sys
import os
import time
import threading
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from data.market_data import MarketDataHandler
from strategies.technical import FeatureEngineer
from core.agent import RLAgent
from core.risk import RiskManager
from core.asset_manager import AssetManager
from core.trader import LiveTrader

class MonitorPhase3:
    def __init__(self):
        self.metrics = {
            'start_time': datetime.now(),
            'initial_balance': 0,
            'final_balance': 0,
            'trades_executed': 0,
            'trades_won': 0,
            'trades_lost': 0,
            'confluence_rejections': 0,
            'cooldown_rejections': 0,
            'resistance_rejections': 0,
            'total_rejections': 0,
            'confluence_scores': [],
            'messages': []
        }
        self.trader = None
        self.running = True
    
    def log(self, msg):
        """Almacenar mensajes de log"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        full_msg = f"[{timestamp}] {msg}"
        self.metrics['messages'].append(full_msg)
        print(full_msg)
    
    def run(self):
        try:
            # Conectar a broker
            self.log("[INIT] Conectando a Exnova PRACTICE...")
            market_data = MarketDataHandler(broker_name="exnova", account_type="PRACTICE")
            
            if not market_data.connect(Config.EXNOVA_EMAIL, Config.EXNOVA_PASSWORD):
                self.log("[ERROR] No se pudo conectar a Exnova")
                return False
            
            self.log("[OK] Conectado a Exnova")
            
            # Obtener balance inicial
            try:
                initial_balance = market_data.get_balance()
                self.metrics['initial_balance'] = initial_balance
                self.log(f"[BALANCE] Saldo inicial: ${initial_balance:.2f}")
            except Exception as e:
                self.log(f"[WARNING] No se pudo obtener balance: {e}")
            
            # Inicializar componentes
            feature_engineer = FeatureEngineer()
            agent = RLAgent()
            risk_manager = RiskManager(
                capital_per_trade=Config.CAPITAL_PER_TRADE,
                stop_loss_pct=Config.STOP_LOSS_PERCENT,
                take_profit_pct=Config.TAKE_PROFIT_PERCENT,
                max_martingale_steps=Config.MAX_MARTINGALE
            )
            asset_manager = AssetManager(market_data)
            
            # Crear trader con todas las fases activadas
            self.trader = LiveTrader(
                market_data=market_data,
                feature_engineer=feature_engineer,
                agent=agent,
                risk_manager=risk_manager,
                asset_manager=asset_manager,
                llm_client=None
            )
            
            # Conectar signals para capturar eventos
            def on_trade_executed(asset, direction, price, time_opened):
                self.metrics['trades_executed'] += 1
                self.log(f"[TRADE] EJECUTADA: {asset} {direction} @ {price}")
            
            def on_trade_result(asset, direction, win_loss):
                if win_loss:
                    self.metrics['trades_won'] += 1
                    self.log(f"[WIN] {asset} - Victoria")
                else:
                    self.metrics['trades_lost'] += 1
                    self.log(f"[LOSS] {asset} - Pérdida")
            
            # Los signals están disponibles
            try:
                self.trader.signals.trade_executed.connect(on_trade_executed)
                self.trader.signals.trade_result.connect(on_trade_result)
            except:
                self.log("[INFO] Signals no disponibles (modo simplificado)")
            
            # Info de configuración
            self.log("[CONFIG] FASE 1: Cooldown 300s por activo")
            self.log("[CONFIG] FASE 2: Detección de resistencias (4 métodos)")
            self.log("[CONFIG] FASE 3: Validación de confluencia M30/M15/M5/M1")
            self.log(f"[CONFIG] Score mínimo confluencia: 0.70 (70%)")
            
            # Lanzar trader
            self.log("[START] Iniciando bot en hilo separado...")
            self.trader.start()
            
            # Monitorear durante N segundos
            monitor_duration = 300  # 5 minutos
            print(f"\n{'='*80}")
            print(f"MONITOREANDO FASE 3 POR {monitor_duration} SEGUNDOS")
            print(f"{'='*80}\n")
            
            start = time.time()
            sample_count = 0
            while time.time() - start < monitor_duration and self.running:
                time.sleep(5)
                elapsed = int(time.time() - start)
                
                if elapsed % 30 == 0:
                    self.log(f"[MONITOR] {elapsed}s / {monitor_duration}s - Trades: {self.metrics['trades_executed']}")
                
                sample_count += 1
            
            # Detener trader
            self.log("[STOP] Deteniendo bot...")
            self.trader.stop()
            time.sleep(2)
            
            # Obtener balance final
            try:
                final_balance = market_data.get_balance()
                self.metrics['final_balance'] = final_balance
                profit = final_balance - self.metrics['initial_balance']
                self.log(f"[BALANCE] Saldo final: ${final_balance:.2f}")
                self.log(f"[PROFIT] P&L: ${profit:+.2f}")
            except Exception as e:
                self.log(f"[WARNING] No se pudo obtener balance final: {e}")
            
            # Mostrar resumen
            self.print_summary()
            
            return True
            
        except Exception as e:
            self.log(f"[FATAL] Error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def print_summary(self):
        print("\n" + "="*80)
        print("RESULTADO DE MONITOREO FASE 3")
        print("="*80)
        print(f"Inicio: {self.metrics['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Duración: ~5 minutos")
        print(f"\nBALANCE:")
        print(f"  Inicial: ${self.metrics['initial_balance']:.2f}")
        print(f"  Final:   ${self.metrics['final_balance']:.2f}")
        if self.metrics['initial_balance'] > 0:
            pnl = self.metrics['final_balance'] - self.metrics['initial_balance']
            pnl_pct = (pnl / self.metrics['initial_balance']) * 100
            print(f"  P&L:     ${pnl:+.2f} ({pnl_pct:+.2f}%)")
        
        print(f"\nOPERACIONES:")
        print(f"  Ejecutadas: {self.metrics['trades_executed']}")
        print(f"  Ganadoras:  {self.metrics['trades_won']}")
        print(f"  Perdedoras: {self.metrics['trades_lost']}")
        
        if self.metrics['trades_executed'] > 0:
            win_rate = (self.metrics['trades_won'] / self.metrics['trades_executed']) * 100
            print(f"  Win Rate:   {win_rate:.1f}%")
        
        print("\nLOGS DETALLADOS:")
        for msg in self.metrics['messages'][-20:]:  # Últimos 20 mensajes
            print(f"  {msg}")
        
        print("\n" + "="*80)
        print("[OK] Monitoreo completado")
        print("="*80)

if __name__ == "__main__":
    monitor = MonitorPhase3()
    success = monitor.run()
    sys.exit(0 if success else 1)
