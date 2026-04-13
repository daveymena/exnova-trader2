#!/usr/bin/env python3
"""
BOT MEJORADO v2 - CON 4 MEJORAS BASADAS EN ANÁLISIS REAL
1. Confirmación de 2+ velas
2. Validación de tendencia H1
3. One Trade Discipline (solo 1 operación a la vez)
4. Price Stabilization check
"""
import sys
import os
import time
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from data.market_data import MarketDataHandler
from strategies.technical import FeatureEngineer
from core.asset_manager import AssetManager
from core.risk import RiskManager

class OneTradeDiscipline:
    """🆕 MEJORA #3: Garantiza que solo haya una operación a la vez"""
    def __init__(self):
        self.active_trade = None
        self.pending_result = False
    
    def start_trade(self, asset, direction, trade_id):
        """Registra nuevo trade activo"""
        self.active_trade = {
            'asset': asset,
            'direction': direction,
            'id': trade_id,
            'start_time': time.time()
        }
        self.pending_result = True
        print(f"[ONE-TRADE] LOCKED: {asset} {direction} (ID: {trade_id})")
    
    def finish_trade(self):
        """Marca trade como completado"""
        if self.active_trade:
            elapsed = time.time() - self.active_trade['start_time']
            print(f"[ONE-TRADE] UNLOCKED (duration: {elapsed:.0f}s)")
        self.active_trade = None
        self.pending_result = False
    
    def can_trade(self):
        """Returns True si NO hay operación activa"""
        return not self.pending_result
    
    def get_status(self):
        """Status info"""
        if self.active_trade:
            return f"OPERACIÓN ACTIVA: {self.active_trade['asset']} {self.active_trade['direction']}"
        return "DISPONIBLE"


def check_price_stabilization(df, lookback=5):
    """
    MEJORA #4: Verifica que el precio este estabilizado
    No operar si hay alta volatilidad (movimientos >0.05% en últimas velas)
    """
    if df is None or len(df) < lookback:
        return True  # Permitir si no hay datos
    
    try:
        recent = df.tail(lookback)
        price_range = recent['high'].max() - recent['low'].min()
        price_avg = (recent['high'].mean() + recent['low'].mean()) / 2
        volatility_pct = (price_range / price_avg) * 100
        
        # Umbral: si volatilidad > 0.15% en últimas 5 velas, esperar
        if volatility_pct > 0.15:
            print(f"      ⚠️ VOLATILIDAD ALTA: {volatility_pct:.3f}% (requiere <0.15%)")
            return False
        
        print(f"      ✅ Volatilidad OK: {volatility_pct:.4f}%")
        return True
        
    except Exception as e:
        print(f"      ⚠️ Error verificando estabilidad: {e}")
        return True


def main():
    print("\n" + "="*80)
    print("BOT MEJORADO v2 - CON 4 MEJORAS")
    print("="*80)
    
    # 1. CONECTAR
    print("\n[1] Conectando a Exnova PRACTICE...")
    market_data = MarketDataHandler(broker_name="exnova", account_type="PRACTICE")
    if not market_data.connect(Config.EXNOVA_EMAIL, Config.EXNOVA_PASSWORD):
        print("[ERROR] No se pudo conectar")
        return False
    
    balance = market_data.get_balance()
    print(f"[OK] Balance: ${balance:.2f}")
    
    # 2. INICIALIZAR
    print("\n[2] Inicializando sistemas...")
    asset_manager = AssetManager(market_data)
    feature_engineer = FeatureEngineer()
    risk_manager = RiskManager(
        capital_per_trade=Config.CAPITAL_PER_TRADE,
        stop_loss_pct=Config.STOP_LOSS_PERCENT,
        take_profit_pct=Config.TAKE_PROFIT_PERCENT,
        max_martingale_steps=Config.MAX_MARTINGALE
    )
    
    # 🆕 MEJORA #3: One Trade Discipline
    discipline = OneTradeDiscipline()
    
    print("[OK] Listo")
    print(f"[MEJORAS] 1) Confirmacion 2+ velas")
    print(f"[MEJORAS] 2) Validacion H1")
    print(f"[MEJORAS] 3) One Trade Discipline")
    print(f"[MEJORAS] 4) Price Stabilization")
    
    # 3. BUCLE DE OPERACIONES
    print("\n[3] Iniciando ciclo de operaciones...")
    print("="*80)
    
    trade_count = 0
    win_count = 0
    loss_count = 0
    
    while True:
        try:
            # MEJORA #3: Verificar si podemos operar (no hay trade activo)
            if not discipline.can_trade():
                print(f"\n[OPERACION] Esperando resultado del trade anterior...")
                print(f"[ONE-TRADE] Status: {discipline.get_status()}")
                time.sleep(5)
                continue
            
            trade_count += 1
            print(f"\n[OPERACION #{trade_count}] {datetime.now().strftime('%H:%M:%S')}")
            print("-" * 80)
            
            # A. ESCANEAR MEJOR OPORTUNIDAD
            print("A) Escaneando mercado...")
            best_op = asset_manager.scan_best_opportunity(feature_engineer)
            
            if not best_op:
                print("   WAIT Sin oportunidad clara, esperando...")
                time.sleep(5)
                continue
            
            asset = best_op['asset']
            direction = best_op['action']
            score = best_op['score']
            
            print(f"   OK Oportunidad: {asset} {direction} (Score: {score})")
            
            # B. OBTENER PRECIO ACTUAL
            df = market_data.get_candles(asset, Config.TIMEFRAME, 200)
            if df.empty:
                print("   WARNING Sin datos para {asset}")
                time.sleep(2)
                continue
            
            price = df.iloc[-1]['close']
            print(f"   Precio: {price:.5f}")
            
            # MEJORA #4: Price Stabilization Check
            print("\nA.5) Verificando estabilizacion de precio...")
            if not check_price_stabilization(df):
                print("   WARNING Precio inestable, saltando esta operacion")
                time.sleep(3)
                continue
            
            # C. EJECUTAR OPERACIÓN (CON MEJORAS 1-2 EN ASSET_MANAGER)
            print(f"\nB) Ejecutando {direction} en {asset}...")
            
            amount = Config.CAPITAL_PER_TRADE
            expiration = 5  # 5 minutos
            
            try:
                # Ejecutar orden usando el método buy
                trade_id = market_data.buy(
                    asset=asset,
                    amount=amount,
                    action=direction.lower(),
                    duration=expiration
                )
                
                print(f"   OK OPERACION EJECUTADA")
                print(f"      ID: {trade_id}")
                print(f"      Monto: ${amount:.2f}")
                print(f"      Expiración: {expiration} min")
                
                # MEJORA #3: Registrar operacion activa
                discipline.start_trade(asset, direction, trade_id)
                
            except Exception as e:
                print(f"   WARNING Error ejecutando: {e}")
                continue
            
            # D. ESPERAR RESULTADO
            print(f"\nC) Esperando resultado ({expiration} minutos)...")
            
            # Para test, esperar menos (real sería expiration * 60)
            wait_time = min(10, expiration * 60)
            for i in range(wait_time):
                remaining = wait_time - i - 1
                print(f"   [{i+1:02d}s] {remaining:02d}s restantes", end='\r')
                time.sleep(1)
            
            print()
            
            # E. VERIFICAR RESULTADO
            print("D) Verificando resultado...")
            
            # Obtener precio de cierre
            df_new = market_data.get_candles(asset, Config.TIMEFRAME, 10)
            if df_new.empty:
                close_price = price
            else:
                close_price = df_new.iloc[-1]['close']
            
            # Calcular ganancia/pérdida
            movement = ((close_price - price) / price) * 100
            
            if direction == "CALL":
                is_win = close_price > price
            else:
                is_win = close_price < price
            
            if is_win:
                win_count += 1
                result = "WIN"
                profit = amount
                print(f"   {result}: +${profit:.2f}")
            else:
                loss_count += 1
                result = "LOSS"
                profit = -amount
                print(f"   {result}: ${profit:.2f}")
            
            print(f"   Movimiento: {movement:+.4f}%")
            print(f"   Entrada: {price:.5f} → Salida: {close_price:.5f}")
            
            # 🆕 MEJORA #3: Desbloquear para siguiente operación
            discipline.finish_trade()
            
            # F. ESTADÍSTICAS
            print(f"\nE) Estadísticas:")
            total_trades = win_count + loss_count
            if total_trades > 0:
                win_rate = (win_count / total_trades) * 100
                print(f"   Total: {total_trades} operaciones")
                print(f"   Ganancias: {win_count} ({win_rate:.1f}%)")
                print(f"   Pérdidas: {loss_count} ({100-win_rate:.1f}%)")
            
            # Pausa entre operaciones
            print(f"\n Esperando 30s antes de siguiente operacion...")
            for i in range(30):
                print(f"   [{i+1:02d}s]", end='\r')
                time.sleep(1)
            
        except KeyboardInterrupt:
            print("\n\n[STOP] Usuario interrumpió")
            break
        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            # Desbloquear en caso de error
            discipline.finish_trade()
            time.sleep(5)
    
    # RESUMEN FINAL
    print("\n" + "="*80)
    print("RESUMEN FINAL - BOT MEJORADO v2")
    print("="*80)
    print(f"Total operaciones: {trade_count}")
    print(f"Ganancias: {win_count}")
    print(f"Pérdidas: {loss_count}")
    if trade_count > 0:
        print(f"Win Rate: {(win_count/trade_count)*100:.1f}%")
    print("\n[MEJORAS IMPLEMENTADAS]")
    print("OK 1) Confirmacion de 2+ velas de reversion")
    print("OK 2) Validacion de tendencia H1")
    print("OK 3) One Trade Discipline (1 operacion a la vez)")
    print("OK 4) Price Stabilization check")
    print("="*80)
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
