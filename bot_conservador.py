#!/usr/bin/env python3
"""
BOT CONSERVADOR v3 - Alta selectividad, menor riesgo
Estrategias combinadas: Trend Following + Smart Reversal + Volatility Filter
"""
import sys
import os
import time
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from data.market_data import MarketDataHandler
from strategies.technical import FeatureEngineer
from strategies.trend_following import TrendFollowingStrategy
from strategies.smart_reversal import SmartReversalStrategy
from strategies.volatility_sniper import VolatilitySniperStrategy
from core.asset_manager import AssetManager
from core.risk import RiskManager


class ConservativeBot:
    def __init__(self):
        self.market_data = None
        self.feature_engineer = FeatureEngineer()
        self.trend_strategy = TrendFollowingStrategy(min_streak=3)
        self.reversal_strategy = SmartReversalStrategy()
        self.volatility_strategy = VolatilitySniperStrategy()
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.consecutive_losses = 0
        self.last_trade_time = None
        self.cooldown_seconds = 300  # 5 minutos entre operaciones
        
    def connect(self):
        print("\n" + "="*60)
        print("BOT CONSERVADOR v3 - Alta Selectividad")
        print("="*60)
        
        self.market_data = MarketDataHandler(
            broker_name="exnova",
            account_type="PRACTICE"
        )
        
        if not self.market_data.connect(Config.EXNOVA_EMAIL, Config.EXNOVA_PASSWORD):
            print("[ERROR] No se pudo conectar")
            return False
        
        balance = self.market_data.get_balance()
        print(f"[OK] Balance: ${balance:.2f}")
        print("[OK] Estrategias: Trend+Reversal+Volatility")
        print(f"[OK] Cooldown: {self.cooldown_seconds}s entre operaciones")
        return True
    
    def check_cooldown(self):
        """Verifica si hay que esperar antes de operar"""
        if self.last_trade_time is None:
            return True
        
        elapsed = time.time() - self.last_trade_time
        if elapsed < self.cooldown_seconds:
            wait_time = int(self.cooldown_seconds - elapsed)
            print(f"   [COOLDOWN] Esperando {wait_time}s...")
            time.sleep(wait_time)
            return True
        return True
    
    def check_consecutive_losses(self):
        """Si hay 3+ pérdidas consecutivas, aumentar cooldown"""
        if self.consecutive_losses >= 3:
            self.cooldown_seconds = 600  # 10 minutos
            print(f"   [ALERTA] 3+ pérdidas consecutivas - Cooldown extendido a 10 min")
        else:
            self.cooldown_seconds = 300  # Volver a 5 minutos
    
    def get_multiple_timeframe_context(self, asset):
        """Analiza múltiples timeframes para confirmar tendencia"""
        try:
            # M1 (principal)
            df_m1 = self.market_data.get_candles(asset, 60, 50)
            if df_m1.empty:
                return None
            
            # M5 (confirmación)
            df_m5 = self.market_data.get_candles(asset, 300, 20)
            
            if df_m5.empty:
                return {'m1': df_m1, 'm5': df_m1, 'm15': df_m1}
            
            # M15
            df_m15 = self.market_data.get_candles(asset, 900, 20)
            if df_m15.empty:
                df_m15 = df_m5
            
            return {'m1': df_m1, 'm5': df_m5, 'm15': df_m15}
        except:
            return None
    
    def analyze_with_strategies(self, dfs):
        """Ejecuta las 3 estrategias y retorna la mejor señal"""
        results = []
        
        # 1. Trend Following
        try:
            trend_result = self.trend_strategy.analyze(dfs['m1'])
            if trend_result['action'] != 'WAIT':
                trend_result['strategy'] = 'TrendFollowing'
                results.append(trend_result)
        except:
            pass
        
        # 2. Smart Reversal
        try:
            reversal_result = self.reversal_strategy.analyze(dfs['m1'])
            if reversal_result['action'] != 'WAIT':
                reversal_result['strategy'] = 'SmartReversal'
                results.append(reversal_result)
        except:
            pass
        
        # 3. Volatility Filter - no da señales, solo filtra
        try:
            vol_result = self.volatility_strategy.analyze(dfs['m1'])
            if vol_result.get('action') == 'WAIT':
                print("   [FILTRO] Volatility Snipe detecto mercado incierto")
                return None
        except:
            pass
        
        if not results:
            return None
        
        # Retornar la señal con mayor confianza
        best = max(results, key=lambda x: x['confidence'])
        
        # Verificar consenso entre estrategias
        actions = [r['action'] for r in results]
        if len(set(actions)) == 1:
            # Todas coinciden - mayor confianza
            best['consensus'] = True
        else:
            best['consensus'] = False
        
        return best
    
    def confirm_with_mtf(self, signal, dfs):
        """Confirma la señal con análisis multi-timeframe"""
        if not signal or not dfs:
            return signal
        
        m1 = dfs['m1']
        m5 = dfs['m5']
        
        # Solo confirmar si tenemos datos de M5
        if m5.empty or len(m5) < 10:
            return signal
        
        # Calcular EMAs en M5
        m5_ema9 = m5['close'].ewm(span=9).mean().iloc[-1]
        m5_ema21 = m5['close'].ewm(span=21).mean().iloc[-1]
        m5_trend = 'up' if m5_ema9 > m5_ema21 else 'down'
        
        # Ajustar confianza según consenso MTF
        if signal['action'] == 'CALL' and m5_trend == 'up':
            signal['confidence'] = min(signal['confidence'] * 1.2, 95)
            signal['mtf_confirmed'] = True
        elif signal['action'] == 'PUT' and m5_trend == 'down':
            signal['confidence'] = min(signal['confidence'] * 1.2, 95)
            signal['mtf_confirmed'] = True
        else:
            signal['mtf_confirmed'] = False
        
        return signal
    
    def scan_and_trade(self):
        """Escanea activos y opera si hay señal clara"""
        # Verificar cooldown
        self.check_cooldown()
        
        # Lista de activos a probar
        assets = [
            "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC",
            "AUDUSD-OTC", "EURJPY-OTC", "EURGBP-OTC"
        ]
        
        best_signal = None
        best_confidence = 0
        best_asset = None
        
        for asset in assets:
            print(f"\n   Analizando {asset}...")
            
            # Obtener datos multi-timeframe
            dfs = self.get_multiple_timeframe_context(asset)
            if not dfs:
                continue
            
            # Analizar con estrategias
            signal = self.analyze_with_strategies(dfs)
            if not signal:
                continue
            
            # Confirmar con MTF
            signal = self.confirm_with_mtf(signal, dfs)
            
            print(f"      {signal['action']} | {signal['strategy']} | Conf: {signal['confidence']:.0f}%")
            
            if signal['confidence'] > best_confidence:
                best_signal = signal
                best_confidence = signal['confidence']
                best_asset = asset
        
        # Solo operar si confianza >= 65%
        if best_signal and best_confidence >= 65:
            return self.execute_trade(best_asset, best_signal)
        
        print(f"   [WAIT] Sin señal clara (mejor confianza: {best_confidence:.0f}%)")
        return False
    
    def execute_trade(self, asset, signal):
        """Ejecuta una operación"""
        action = signal['action']
        expiration = signal.get('expiration', 5)
        amount = Config.CAPITAL_PER_TRADE
        
        print(f"\n   >>> EJECUTANDO {action} en {asset}")
        print(f"      Confianza: {signal['confidence']:.0f}% | Exp: {expiration}min")
        
        try:
            trade_id = self.market_data.buy(
                asset=asset,
                amount=amount,
                action=action.lower(),
                duration=expiration
            )
            
            print(f"      [OK] Trade ID: {trade_id}")
            self.last_trade_time = time.time()
            
            # Esperar resultado
            print(f"      Esperando {expiration} minutos...")
            wait_seconds = expiration * 60
            
            for i in range(0, wait_seconds, 10):
                remaining = wait_seconds - i
                if remaining <= 0:
                    break
                print(f"      [{min(i+10, wait_seconds)}s] {max(0, remaining)}s restantes", end='\r')
                time.sleep(min(10, remaining))
            
            print()
            
            # Verificar resultado (simplificado)
            return self.check_result(asset, action, signal)
            
        except Exception as e:
            print(f"      [ERROR] {e}")
            return False
    
    def check_result(self, asset, action, signal):
        """Verifica el resultado de la operación"""
        try:
            df = self.market_data.get_candles(asset, 60, 5)
            if df.empty:
                return False
            
            close = df.iloc[-1]['close']
            open_price = df.iloc[-2]['close'] if len(df) > 1 else df.iloc[0]['close']
            
            # Determinar win
            if action == 'CALL':
                is_win = close > open_price
            else:
                is_win = close < open_price
            
            self.trade_count += 1
            
            if is_win:
                self.win_count += 1
                self.consecutive_losses = 0
                print(f"      [WIN] +${Config.CAPITAL_PER_TRADE:.2f}")
            else:
                self.loss_count += 1
                self.consecutive_losses += 1
                print(f"      [LOSS] -${Config.CAPITAL_PER_TRADE:.2f}")
            
            self.check_consecutive_losses()
            self.print_stats()
            return True
            
        except Exception as e:
            print(f"      [ERROR] Verificando resultado: {e}")
            return False
    
    def print_stats(self):
        """Imprime estadísticas"""
        total = self.win_count + self.loss_count
        if total > 0:
            win_rate = (self.win_count / total) * 100
            print(f"\n   [STATS] Total: {total} | Wins: {self.win_count} ({win_rate:.0f}%) | Losses: {self.loss_count}")
    
    def run(self):
        """Bucle principal"""
        if not self.connect():
            return
        
        print("\n" + "="*60)
        print("Iniciando ciclo de operaciones...")
        print("="*60)
        
        while True:
            try:
                # Escanear y operar
                self.scan_and_trade()
                
                # Esperar entre ciclos
                print("\n   [PAUSE] Esperando siguiente ciclo...")
                time.sleep(60)
                
            except KeyboardInterrupt:
                print("\n\n[STOP] Bot detenido")
                break
            except Exception as e:
                print(f"\n[ERROR] {e}")
                time.sleep(30)
        
        self.print_stats()


def main():
    bot = ConservativeBot()
    bot.run()


if __name__ == "__main__":
    main()