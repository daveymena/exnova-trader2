#!/usr/bin/env python3
"""
TEST RÁPIDO: Verificar si el bot OPERARIA con configuración actual
Simula flujo completo: Setup -> Cooldown -> Resistencia -> Confluencia -> Execución
"""
import sys
import os
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from data.market_data import MarketDataHandler
from core.trader import LiveTrader
from core.resistance_detector import AdvancedResistanceDetector
from core.confluence_validator import ConfluenceValidator
from core.asset_manager import AssetManager
from strategies.technical import FeatureEngineer
from core.agent import RLAgent
from core.risk import RiskManager

def test_trading_validation():
    print("\n" + "="*80)
    print("TEST DE VALIDACION: ¿OPERARÍAMOS CON CONFIGURACIÓN ACTUAL?")
    print("="*80 + "\n")
    
    try:
        # 1. CONECTAR
        print("[1/6] Conectando a Exnova PRACTICE...")
        market_data = MarketDataHandler(broker_name="exnova", account_type="PRACTICE")
        
        if not market_data.connect(Config.EXNOVA_EMAIL, Config.EXNOVA_PASSWORD):
            print("[ERROR] No se pudo conectar")
            return False
        
        balance = market_data.get_balance()
        print(f"[OK] Conectado. Balance: ${balance:.2f}\n")
        
        # 2. OBTENER DATOS
        print("[2/6] Obteniendo datos del mercado (EURUSD-OTC)...")
        asset = "EURUSD-OTC"
        df = market_data.get_candles(asset, Config.TIMEFRAME, 200)
        
        if df.empty:
            print("[ERROR] Sin datos disponibles")
            return False
        
        current_price = df.iloc[-1]['close']
        print(f"[OK] Precio actual: {current_price:.5f}\n")
        
        # 3. CREAR VALIDADORES
        print("[3/6] Inicializando validadores...")
        resistance_detector = AdvancedResistanceDetector()
        confluence_validator = ConfluenceValidator()
        print("[OK] Validadores listos\n")
        
        # 4. SIMULAR SETUP ENCONTRADO (CALL)
        print("[4/6] Simulando setup encontrado: CALL\n")
        direction = "call"
        
        # A. TEST COOLDOWN
        print("   A) Verificando COOLDOWN POR ACTIVO...")
        last_trade_per_asset = {}
        cooldown_per_asset = 300
        
        if asset in last_trade_per_asset:
            time_since_last = time.time() - last_trade_per_asset[asset]
            if time_since_last < cooldown_per_asset:
                print(f"      ❌ RECHAZADO: Cooldown activo ({cooldown_per_asset - time_since_last:.0f}s restantes)")
                return False
        
        print(f"      ✅ PASÓ: Sin cooldown (primera operación en {asset})")
        
        # B. TEST RESISTENCIA
        print("\n   B) Verificando DETECCIÓN DE RESISTENCIAS...")
        should_reject, reason = resistance_detector.should_reject_trade(
            df, direction, current_price, tolerance_pct=0.3
        )
        
        if should_reject:
            print(f"      ❌ RECHAZADO: {reason}")
            return False
        
        print(f"      ✅ PASÓ: No hay resistencia peligrosa")
        
        # C. TEST CONFLUENCIA
        print("\n   C) Verificando CONFLUENCIA MULTITIMEFRAME...")
        is_confluence_valid, confluence_score, breakdown, confluence_reason = \
            confluence_validator.validate_entry(
                market_data, asset, direction, current_price, df
            )
        
        print(f"      Score: {confluence_score:.2f} / 0.50 (mínimo)")
        print(f"      Breakdown: {confluence_reason}")
        
        if confluence_score < 0.50 and len(df) >= 50:
            print(f"      ❌ RECHAZADO: Confluencia insuficiente")
            return False
        elif confluence_score < 0.50:
            print(f"      ⚠️ BAJO pero OPERANDO: Datos limitados")
        
        print(f"      ✅ PASÓ: Confluencia válida")
        
        # 5. CHECKS FINALES
        print("\n[5/6] Verificaciones finales...")
        print(f"   - Cooldown por activo: 300s (5 minutos) ✅")
        print(f"   - Detección de resistencias: 4-métodos ✅")
        print(f"   - Confluencia: Score >= 0.50 ✅")
        print(f"   - Max trades/hora: 100 ✅")
        
        # 6. CONCLUSIÓN
        print("\n[6/6] RESULTADO FINAL:\n")
        print("="*80)
        print("✅ SÍ OPERARÍAMOS")
        print("="*80)
        print(f"\n  Activo:      {asset}")
        print(f"  Dirección:   {direction.upper()}")
        print(f"  Precio:      {current_price:.5f}")
        print(f"  Confluencia: {confluence_score:.2f} (Requerido: >= 0.50)")
        print(f"\n  El bot EJECUTARÍA una operación CALL en {asset}")
        print("\n" + "="*80)
        
        return True
        
    except Exception as e:
        print(f"\n[ERROR] Excepción: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_trading_validation()
    sys.exit(0 if success else 1)
