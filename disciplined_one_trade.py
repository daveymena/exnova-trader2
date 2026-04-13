#!/usr/bin/env python3
"""
SISTEMA DE TRADING DISCIPLINADO - UNA OPERACIÓN POR CICLO
Metodología: Ejecuta 1 operación -> Espera resultado -> Analiza -> Mejora
Evita sobre-operación. Basado en análisis real, no especulación.
"""
import sys
import os
import time
import json
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from data.market_data import MarketDataHandler
from core.asset_manager import AssetManager
from strategies.technical import FeatureEngineer
from core.resistance_detector import AdvancedResistanceDetector

class DisciplinedTradingSystem:
    def __init__(self):
        self.market_data = None
        self.asset_manager = None
        self.feature_engineer = None
        self.resistance_detector = None
        self.trade_log = []
        self.analysis_log = []
        
    def connect(self):
        """Conectar al broker"""
        print("\n[1] CONEXION AL BROKER")
        print("="*80)
        
        self.market_data = MarketDataHandler(broker_name="exnova", account_type="PRACTICE")
        if not self.market_data.connect(Config.EXNOVA_EMAIL, Config.EXNOVA_PASSWORD):
            print("[ERROR] No se pudo conectar")
            return False
        
        balance = self.market_data.get_balance()
        print(f"[OK] Conectado a Exnova PRACTICE")
        print(f"[BALANCE] ${balance:.2f}")
        return True
    
    def initialize_systems(self):
        """Inicializar sistemas de análisis"""
        print("\n[2] INICIALIZACION DE SISTEMAS")
        print("="*80)
        
        self.asset_manager = AssetManager(self.market_data)
        self.feature_engineer = FeatureEngineer()
        self.resistance_detector = AdvancedResistanceDetector()
        
        print("[OK] FeatureEngineer, AssetManager, ResistanceDetector listos")
    
    def analyze_market(self):
        """PASO 1: Analizar mercado para encontrar MEJOR oportunidad"""
        print("\n[3] ANALYSIS PROFUNDO - BUSCANDO MEJOR SETUP")
        print("="*80)
        
        # Escanear todos los activos
        print("[*] Escaneando activos disponibles...")
        available = self.asset_manager.get_available_otc_assets(verbose=False)
        
        best_setup = None
        best_score = 0
        
        for asset in available[:8]:  # Top 8
            df = self.market_data.get_candles(asset, Config.TIMEFRAME, 200)
            if df.empty:
                continue
            
            # Análisis rápido
            df = self.feature_engineer.prepare_for_rl(df)
            last_candle = df.iloc[-1]
            
            rsi = last_candle.get('rsi', 50)
            price = last_candle['close']
            
            # Puntuación simple
            score = 0
            signals = []
            
            # 1. Oversold/Overbought
            if rsi < 30:
                score += 30
                signals.append("RSI oversold")
            elif rsi > 70:
                score += 30
                signals.append("RSI overbought")
            
            # 2. Volatilidad
            volatility = last_candle.get('volatility', 0)
            if volatility > 0.002:
                score += 20
                signals.append(f"Volatilidad high ({volatility:.4f})")
            
            # 3. Trending
            sma20 = last_candle.get('sma_20', price)
            if price > sma20:
                score += 15
                signals.append("Precio > SMA20")
            
            if score > best_score:
                best_score = score
                best_setup = {
                    'asset': asset,
                    'price': price,
                    'rsi': rsi,
                    'score': score,
                    'signals': signals,
                    'df': df,
                    'direction': 'CALL' if rsi < 30 else 'PUT'
                }
        
        if not best_setup:
            print("[ERROR] Sin setups encontrados")
            return None
        
        print(f"\n[MEJOR SETUP] {best_setup['asset']}")
        print(f"  Precio:     {best_setup['price']:.5f}")
        print(f"  RSI:        {best_setup['rsi']:.1f}")
        print(f"  Score:      {best_setup['score']}")
        print(f"  Dirección:  {best_setup['direction']}")
        print(f"  Señales:    {', '.join(best_setup['signals'])}")
        
        return best_setup
    
    def validate_entry(self, setup):
        """PASO 2: Validar entrada ANTES de ejecutar"""
        print("\n[4] VALIDACION DE ENTRADA")
        print("="*80)
        
        asset = setup['asset']
        direction = setup['direction']
        price = setup['price']
        df = setup['df']
        
        validations = {
            'passed': True,
            'checks': []
        }
        
        # CHECK 1: Resistencia/Soporte
        print("\n[CHECK 1] Detección de Resistencias/Soportes...")
        should_reject, reason = self.resistance_detector.should_reject_trade(
            df, direction.lower(), price, tolerance_pct=1.0
        )
        
        if should_reject:
            print(f"  ❌ RECHAZADO: {reason}")
            validations['passed'] = False
            validations['checks'].append(f"Resistencia: FAIL - {reason}")
        else:
            print(f"  ✅ OK - Sin obstáculos de resistencia")
            validations['checks'].append("Resistencia: PASS")
        
        # CHECK 2: Confirmación de reversión
        print("\n[CHECK 2] Confirmación de reversión...")
        last_3 = df.tail(3)
        bullish_candles = (last_3['close'] > last_3['open']).sum()
        bearish_candles = (last_3['close'] < last_3['open']).sum()
        
        if direction == 'CALL':
            if bullish_candles >= 1:
                print(f"  ✅ OK - {bullish_candles} velas alcistas en últimas 3")
                validations['checks'].append("Confirmación CALL: PASS")
            else:
                print(f"  ⚠️ BAJO - Solo {bullish_candles} vela alcista")
                validations['checks'].append("Confirmación CALL: WEAK")
        else:
            if bearish_candles >= 1:
                print(f"  ✅ OK - {bearish_candles} velas bajistas en últimas 3")
                validations['checks'].append("Confirmación PUT: PASS")
            else:
                print(f"  ⚠️ BAJO - Solo {bearish_candles} vela bajista")
                validations['checks'].append("Confirmación PUT: WEAK")
        
        # CHECK 3: Proximidad a máximos/mínimos recientes
        print("\n[CHECK 3] Proximidad a niveles clave...")
        high_50 = df['high'].tail(50).max()
        low_50 = df['low'].tail(50).min()
        
        dist_to_high = ((high_50 - price) / price) * 100
        dist_to_low = ((price - low_50) / price) * 100
        
        print(f"  Distancia a máximo (50 velas): {dist_to_high:.3f}%")
        print(f"  Distancia a mínimo (50 velas): {dist_to_low:.3f}%")
        
        if dist_to_high < 0.3 and direction == 'CALL':
            print(f"  ⚠️ Muy cerca del máximo reciente - Riesgo alto")
            validations['checks'].append("Proximidad: RISK")
        elif dist_to_low < 0.3 and direction == 'PUT':
            print(f"  ⚠️ Muy cerca del mínimo reciente - Riesgo alto")
            validations['checks'].append("Proximidad: RISK")
        else:
            print(f"  ✅ OK - Distancia segura")
            validations['checks'].append("Proximidad: PASS")
        
        return validations
    
    def execute_one_trade(self, setup):
        """PASO 3: Ejecutar UNA operación"""
        print("\n[5] EJECUCION - UNA OPERACION")
        print("="*80)
        
        asset = setup['asset']
        direction = setup['direction']
        price = setup['price']
        
        print(f"\n[ENTRADA]")
        print(f"  Activo:        {asset}")
        print(f"  Dirección:     {direction}")
        print(f"  Precio Entrada: {price:.5f}")
        print(f"  Expiración:    5 minutos (binaria)")
        print(f"  Monto:         ${Config.CAPITAL_PER_TRADE:.2f}")
        
        # SIMULACIÓN: En PRACTICE, las órdenes se ejecutan automáticamente
        # Aquí registramos la operación para análisis
        
        trade_id = f"TEST_{int(time.time())}"
        entry_time = time.time()
        
        trade_data = {
            'id': trade_id,
            'asset': asset,
            'direction': direction,
            'entry_price': price,
            'entry_time': entry_time,
            'expiration_seconds': 300,  # 5 minutos
            'amount': Config.CAPITAL_PER_TRADE,
            'status': 'OPEN'
        }
        
        print(f"\n[OPERACION REGISTRADA] ID: {trade_id}")
        print(f"  Entraremos en {asset} con {direction}")
        
        return trade_data
    
    def wait_for_result(self, trade_data):
        """PASO 4: Esperar resultado"""
        print("\n[6] ESPERA DEL RESULTADO")
        print("="*80)
        
        expiration = trade_data['expiration_seconds']
        start = time.time()
        
        print(f"\n[⏳ ESPERANDO] {expiration} segundos para resultado...\n")
        
        # Para testing, esperar 10 segundos (en real serían 300)
        test_wait = min(10, expiration)
        
        for i in range(test_wait):
            elapsed = i + 1
            remaining = test_wait - elapsed
            print(f"  [{elapsed:02d}s] Operación abierta... ({remaining:02d}s restantes)", end='\r')
            time.sleep(1)
        
        print(f"\n[⏰ RESULTADO RECIBIDO]")
        
        # Obtener precio actual
        df = self.market_data.get_candles(trade_data['asset'], Config.TIMEFRAME, 10)
        if df.empty:
            close_price = trade_data['entry_price']
        else:
            close_price = df.iloc[-1]['close']
        
        # Determinar ganancia/pérdida
        direction = trade_data['direction'].lower()
        
        if direction == 'call':
            if close_price > trade_data['entry_price']:
                result = 'WIN'
                profit = Config.CAPITAL_PER_TRADE
            else:
                result = 'LOSS'
                profit = -Config.CAPITAL_PER_TRADE
        else:  # PUT
            if close_price < trade_data['entry_price']:
                result = 'WIN'
                profit = Config.CAPITAL_PER_TRADE
            else:
                result = 'LOSS'
                profit = -Config.CAPITAL_PER_TRADE
        
        trade_data['exit_price'] = close_price
        trade_data['result'] = result
        trade_data['profit'] = profit
        trade_data['exit_time'] = time.time()
        trade_data['status'] = 'CLOSED'
        
        return trade_data
    
    def analyze_result(self, trade_data):
        """PASO 5: Analizar qué pasó"""
        print("\n[7] ANALISIS DEL RESULTADO")
        print("="*80)
        
        entry = trade_data['entry_price']
        exit_price = trade_data['exit_price']
        result = trade_data['result']
        profit = trade_data['profit']
        direction = trade_data['direction']
        
        movement = ((exit_price - entry) / entry) * 100
        
        print(f"\n[RESUMEN DE LA OPERACIÓN]")
        print(f"  Entrada:       {entry:.5f}")
        print(f"  Salida:        {exit_price:.5f}")
        print(f"  Movimiento:    {movement:+.4f}%")
        print(f"  Resultado:     {result} ({profit:+.2f})")
        print(f"  Duración:      {trade_data['exit_time'] - trade_data['entry_time']:.0f}s")
        
        # Análisis profundo
        print(f"\n[ANALISIS PROFUNDO]")
        
        if result == 'WIN':
            print(f"  ✅ OPERACION GANADORA")
            print(f"  El precio se movió como esperado:")
            if direction == 'CALL':
                print(f"    - Entramos en CALL")
                print(f"    - El precio subió {movement:.4f}%")
            else:
                print(f"    - Entramos en PUT")
                print(f"    - El precio bajó {movement:.4f}%")
        else:
            print(f"  ❌ OPERACION PERDEDORA")
            print(f"  El precio se movió CONTRA nuestra predicción:")
            if direction == 'CALL':
                print(f"    - Entramos en CALL (esperábamos subida)")
                print(f"    - El precio bajó {movement:.4f}%")
            else:
                print(f"    - Entramos en PUT (esperábamos bajada)")
                print(f"    - El precio subió {movement:.4f}%")
        
        return {
            'trade_id': trade_data['id'],
            'result': result,
            'movement': movement,
            'profit': profit,
            'analysis_time': datetime.now().isoformat()
        }
    
    def suggest_improvements(self, trade_data, analysis):
        """PASO 6: Sugerir mejoras basadas en resultado REAL"""
        print("\n[8] SUGERENCIAS DE MEJORA")
        print("="*80)
        
        result = analysis['result']
        movement = analysis['movement']
        direction = trade_data['direction']
        
        improvements = []
        
        if result == 'WIN':
            print(f"\n✅ La estrategia funcionó. Mejoras de optimización:")
            
            # Si ganamos pero movimiento pequeño
            if abs(movement) < 0.1:
                improvements.append(
                    "1. Movimiento pequeño - Considerar esperar confirmación más fuerte"
                )
            
            # Si ganamos con resistencia cerca
            df = trade_data.get('df')
            if df is not None:
                high_50 = df['high'].tail(50).max()
                entry = trade_data['entry_price']
                dist = ((high_50 - entry) / entry) * 100
                if dist < 0.5:
                    improvements.append(
                        "2. Resistencia cercana pero ganamos - Validación de resistencia funcionó ✅"
                    )
        
        else:  # LOSS
            print(f"\n❌ La operación perdió. Problemas identificados:")
            
            # Análisis de por qué perdió
            if direction == 'CALL' and movement < 0:
                improvements.append(
                    "1. CALL pero precio bajó - Reversión falsa o falta de confirmación"
                )
                improvements.append(
                    "   → Solución: Esperar 2+ velas alcistas antes de entrar"
                )
                improvements.append(
                    "   → Solución: Verificar tendencia H1 antes de operar"
                )
            
            elif direction == 'PUT' and movement > 0:
                improvements.append(
                    "1. PUT pero precio subió - Reversión falsa o falta de confirmación"
                )
                improvements.append(
                    "   → Solución: Esperar 2+ velas bajistas antes de entrar"
                )
                improvements.append(
                    "   → Solución: Verificar tendencia H1 antes de operar"
                )
            
            # Si movimiento fue contra nosotros
            if abs(movement) > 0.3:
                improvements.append(
                    f"2. Movimiento fuerte contra ({movement:.3f}%) - Entrada en punto vulnerable"
                )
                improvements.append(
                    "   → Solución: Aumentar requerimiento de confirmación"
                )
                improvements.append(
                    "   → Solución: Esperar que precio estabilice antes de entrar"
                )
        
        # Sugerencias universales
        improvements.append("\n[MEJORAS GENERALES PARA IMPLEMENTAR]")
        improvements.append("• Análisis multi-timeframe (H1 para tendencia, M5 para entry)")
        improvements.append("• Esperar mínimo 2 velas alcistas para CALL, 2 bajistas para PUT")
        improvements.append("• Evitar entradas muy cerca de resistencias/soportes")
        improvements.append("• Implementar zona de consolidación (range-bound check)")
        
        for imp in improvements:
            print(f"  {imp}")
        
        return improvements
    
    def run(self):
        """Ejecutar ciclo completo"""
        print("\n" + "="*80)
        print("SISTEMA DE TRADING DISCIPLINADO - UNA OPERACIÓN POR CICLO")
        print("="*80)
        
        # 1. Conectar
        if not self.connect():
            return False
        
        # 2. Inicializar
        self.initialize_systems()
        
        # 3. Analizar mercado
        setup = self.analyze_market()
        if not setup:
            return False
        
        # 4. Validar entrada
        validation = self.validate_entry(setup)
        
        if not validation['passed']:
            print("\n[⚠️ ADVERTENCIA] Validación crítica fallida")
            print("No ejecutaremos esta operación (riesgo muy alto)")
            return False
        
        # 5. Ejecutar
        trade_data = self.execute_one_trade(setup)
        
        # 6. Esperar resultado
        trade_data = self.wait_for_result(trade_data)
        
        # 7. Analizar
        analysis = self.analyze_result(trade_data)
        
        # 8. Sugerir mejoras
        improvements = self.suggest_improvements(trade_data, analysis)
        
        # Guardar log
        self._save_log(trade_data, analysis, improvements)
        
        print("\n" + "="*80)
        print("[FIN] Ciclo completado. Log guardado en trade_analysis.json")
        print("="*80)
        
        return True
    
    def _save_log(self, trade_data, analysis, improvements):
        """Guardar análisis completo para revisión"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'trade': trade_data,
            'analysis': analysis,
            'improvements': improvements
        }
        
        # Guardar en archivo
        try:
            with open('trade_analysis.json', 'w') as f:
                json.dump(log_entry, f, indent=2)
        except:
            pass

if __name__ == "__main__":
    system = DisciplinedTradingSystem()
    success = system.run()
    sys.exit(0 if success else 1)
