#!/usr/bin/env python3
"""
BOT CON IA - APRENDIZAJE PROGRESIVO
Combina:
1. Detector de contexto de precio
2. Sistema de IA con fallbacks
3. Aprendizaje de operaciones pasadas
"""
import sys
import os
import time
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from data.market_data import MarketDataHandler
from strategies.technical import FeatureEngineer
from core.asset_manager import AssetManager
from core.risk import RiskManager
from ai_learning import TradingLearner, create_learner

# Importar detector de contexto
from bot_con_contexto import (
    detectar_contexto_precio,
    calcular_rsi,
    detectar_divergencia_rsi,
    validar_entrada_con_contexto
)

# ============================================================================
# BOT PRINCIPAL CON IA
# ============================================================================

def main():
    print("\n" + "="*80)
    print("BOT CON IA - APRENDIZAJE PROGRESIVO")
    print("="*80)
    print("Sistema de IA:")
    print("  1. GitHub Models (gpt-4o-mini)")
    print("  2. Ollama Easypanel (minimax-m2.7)")
    print("  3. Ollama Local (llama3.2)")
    print("="*80)
    
    # 1. INICIALIZAR IA
    print("\n[1] Inicializando sistema de IA...")
    learner = create_learner()
    print(learner.get_status())
    
    # 2. CONECTAR
    print("\n[2] Conectando a Exnova PRACTICE...")
    market_data = MarketDataHandler(broker_name="exnova", account_type="PRACTICE")
    if not market_data.connect(Config.EXNOVA_EMAIL, Config.EXNOVA_PASSWORD):
        print("[ERROR] No se pudo conectar")
        return False
    
    balance = market_data.get_balance()
    print(f"[OK] Balance: ${balance:.2f}")
    
    # 3. INICIALIZAR SISTEMAS
    print("\n[3] Inicializando sistemas de trading...")
    asset_manager = AssetManager(market_data)
    feature_engineer = FeatureEngineer()
    risk_manager = RiskManager(
        capital_per_trade=Config.CAPITAL_PER_TRADE,
        stop_loss_pct=Config.STOP_LOSS_PERCENT,
        take_profit_pct=Config.TAKE_PROFIT_PERCENT,
        max_martingale_steps=Config.MAX_MARTINGALE
    )
    print("[OK] Listo")
    
    # 4. BUCLE DE OPERACIONES
    print("\n[4] Iniciando ciclo de operaciones...")
    print("="*80)
    
    trade_count = 0
    win_count = 0
    loss_count = 0
    rechazadas_contexto = 0
    rechazadas_ia = 0
    
    while True:
        try:
            print(f"\n{'='*80}")
            print(f"[CICLO #{trade_count + 1}] - {datetime.now().strftime('%H:%M:%S')}")
            print("="*80)
            
            # A. ESCANEAR MERCADO
            print("\nA) Escaneando mercado...")
            best_op = asset_manager.scan_best_opportunity(feature_engineer)
            
            if not best_op:
                print("   ⏳ Sin oportunidad clara, esperando 30s...")
                time.sleep(30)
                continue
            
            asset = best_op['asset']
            direction = best_op['action']
            score = best_op['score']
            
            print(f"   📊 Oportunidad: {asset} {direction} (Score: {score})")
            
            # B. OBTENER DATOS
            df = market_data.get_candles(asset, Config.TIMEFRAME, 50)
            if df.empty or len(df) < 20:
                print(f"   ❌ Datos insuficientes")
                time.sleep(5)
                continue
            
            price = df.iloc[-1]['close']
            rsi = calcular_rsi(df)
            
            print(f"   Precio: {price:.5f} | RSI: {rsi:.1f}")
            
            # C. VALIDAR CONTEXTO DE PRECIO
            print(f"\nB) Validando contexto de precio...")
            entrada_valida, razon_contexto = validar_entrada_con_contexto(df, direction)
            
            if not entrada_valida:
                print(f"   🚫 RECHAZADO (Contexto): {razon_contexto}")
                rechazadas_contexto += 1
                time.sleep(10)
                continue
            
            print(f"   {razon_contexto}")
            
            # D. VALIDAR CON IA (APRENDIZAJE)
            print(f"\nC) Consultando IA...")
            
            current_context = {
                'asset': asset,
                'direction': direction,
                'rsi': rsi,
                'price': price,
                'score': score,
                'timestamp': datetime.now().isoformat()
            }
            
            should_enter, razon_ia = learner.should_enter_trade(current_context)
            
            if not should_enter:
                print(f"   🚫 RECHAZADO (IA): {razon_ia}")
                rechazadas_ia += 1
                time.sleep(10)
                continue
            
            print(f"   ✅ {razon_ia}")
            
            # E. EJECUTAR OPERACIÓN
            print(f"\nD) Ejecutando {direction} en {asset}...")
            
            amount = Config.CAPITAL_PER_TRADE
            expiration = 5  # 5 minutos (puedes hacerlo dinámico después)
            
            try:
                trade_id = market_data.buy(
                    asset=asset,
                    amount=amount,
                    action=direction.lower(),
                    duration=expiration
                )
                
                trade_count += 1
                
                print(f"   ✅ OPERACIÓN #{trade_count} EJECUTADA")
                print(f"      ID: {trade_id}")
                print(f"      Monto: ${amount:.2f}")
                print(f"      Expiración: {expiration} min")
                
            except Exception as e:
                print(f"   ⚠️ Error ejecutando: {e}")
                time.sleep(5)
                continue
            
            # F. ESPERAR RESULTADO
            print(f"\nE) Esperando resultado ({expiration} minutos)...")
            
            wait_time = expiration * 60
            for i in range(wait_time):
                remaining = wait_time - i - 1
                mins = remaining // 60
                secs = remaining % 60
                print(f"   [{i+1:03d}s] {mins:02d}:{secs:02d} restantes", end='\r')
                time.sleep(1)
            
            print()
            
            # G. VERIFICAR RESULTADO
            print("F) Verificando resultado...")
            
            df_new = market_data.get_candles(asset, Config.TIMEFRAME, 10)
            if df_new.empty:
                close_price = price
            else:
                close_price = df_new.iloc[-1]['close']
            
            movement = ((close_price - price) / price) * 100
            
            if direction == "CALL":
                is_win = close_price > price
            else:
                is_win = close_price < price
            
            result = "WIN" if is_win else "LOSS"
            
            if is_win:
                win_count += 1
                profit = amount
                print(f"   ✅ WIN: +${profit:.2f}")
            else:
                loss_count += 1
                profit = -amount
                print(f"   ❌ LOSS: ${profit:.2f}")
            
            print(f"   Movimiento: {movement:+.4f}%")
            print(f"   Entrada: {price:.5f} → Salida: {close_price:.5f}")
            
            # H. REGISTRAR EN IA PARA APRENDIZAJE
            print(f"\nG) Enseñando a la IA...")
            
            operation_data = {
                'asset': asset,
                'direction': direction,
                'rsi': rsi,
                'price': price,
                'close_price': close_price,
                'movement': movement,
                'result': result,
                'profit': profit,
                'context': razon_contexto,
                'score': score,
                'expiration': expiration
            }
            
            # Registrar operación
            learner.record_operation(operation_data)
            
            # Analizar con IA
            analysis = learner.analyze_operation(operation_data)
            print(f"   📊 Análisis IA:")
            print(f"      Patrón: {analysis.get('pattern_detected', 'N/A')}")
            print(f"      Razón: {analysis.get('why_won_or_lost', 'N/A')}")
            print(f"      Sugerencia: {analysis.get('suggestion', 'N/A')}")
            
            # I. ESTADÍSTICAS
            print(f"\nH) Estadísticas:")
            total_trades = win_count + loss_count
            if total_trades > 0:
                win_rate = (win_count / total_trades) * 100
                print(f"   Operaciones ejecutadas: {total_trades}")
                print(f"   Ganancias: {win_count} ({win_rate:.1f}%)")
                print(f"   Pérdidas: {loss_count} ({100-win_rate:.1f}%)")
                print(f"   Rechazadas (Contexto): {rechazadas_contexto}")
                print(f"   Rechazadas (IA): {rechazadas_ia}")
            
            # J. SUGERENCIAS DE MEJORA (cada 10 operaciones)
            if trade_count % 10 == 0 and trade_count > 0:
                print(f"\nI) Sugerencias de mejora (cada 10 ops):")
                suggestions = learner.get_improvement_suggestions()
                for i, sug in enumerate(suggestions, 1):
                    print(f"   {i}. {sug}")
            
            # Pausa entre operaciones
            print(f"\n⏳ Esperando 30s antes de siguiente operación...")
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
            time.sleep(5)
    
    # RESUMEN FINAL
    print("\n" + "="*80)
    print("RESUMEN FINAL")
    print("="*80)
    print(f"Total operaciones ejecutadas: {trade_count}")
    print(f"Operaciones rechazadas (Contexto): {rechazadas_contexto}")
    print(f"Operaciones rechazadas (IA): {rechazadas_ia}")
    print(f"Ganancias: {win_count}")
    print(f"Pérdidas: {loss_count}")
    if trade_count > 0:
        print(f"Win Rate: {(win_count/trade_count)*100:.1f}%")
    
    print("\n" + learner.get_status())
    print("="*80)
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)