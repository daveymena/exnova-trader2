"""
🚨 DETECTOR DE TRAMPAS DEL MERCADO
Identifica patrones engañosos que parecen oportunidades pero son trampas para perder dinero.
"""
import pandas as pd
import numpy as np

class TrapDetector:
    """
    Detecta trampas comunes del mercado:
    1. Bull Trap: Falsa ruptura al alza que luego cae
    2. Bear Trap: Falsa ruptura a la baja que luego sube
    3. Fakeout: Movimiento rápido que invierte inmediatamente
    4. Whipsaw: Volatilidad extrema sin dirección clara
    5. Manipulación de volumen: Movimientos artificiales
    """
    
    def __init__(self):
        self.trap_history = []
    
    def detect_bull_trap(self, df):
        """
        Bull Trap: Precio rompe resistencia pero NO hay fuerza real
        Señales:
        - Ruptura de resistencia con vela pequeña (sin convicción)
        - RSI ya en sobrecompra antes de la ruptura
        - Volumen bajo en la ruptura
        - Mechas superiores largas (rechazo)
        """
        if len(df) < 30:
            return False, 0
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        recent = df.tail(20)
        
        # Encontrar resistencia reciente
        resistance = recent['high'].iloc[:-1].max()
        
        # ¿Rompió la resistencia?
        broke_resistance = last['close'] > resistance
        
        if not broke_resistance:
            return False, 0
        
        trap_score = 0
        reasons = []
        
        # 1. Vela de ruptura débil (cuerpo pequeño)
        candle_body = abs(last['close'] - last['open'])
        candle_range = last['high'] - last['low']
        if candle_range > 0 and candle_body / candle_range < 0.4:
            trap_score += 30
            reasons.append("Vela de ruptura débil")
        
        # 2. RSI ya en sobrecompra (>70)
        if last.get('rsi', 50) > 70:
            trap_score += 25
            reasons.append("RSI sobrecomprado antes de ruptura")
        
        # 3. Mecha superior larga (rechazo inmediato)
        upper_wick = last['high'] - max(last['open'], last['close'])
        if candle_range > 0 and upper_wick / candle_range > 0.5:
            trap_score += 30
            reasons.append("Rechazo con mecha superior larga")
        
        # 4. Divergencia: Precio sube pero momentum baja
        if 'macd' in df.columns:
            macd_trend = df['macd'].tail(5).diff().mean()
            if macd_trend < 0:  # MACD bajando mientras precio sube
                trap_score += 15
                reasons.append("Divergencia bajista en MACD")
        
        is_trap = trap_score >= 50
        
        if is_trap:
            print(f"   🚨 BULL TRAP DETECTADO (Score: {trap_score})")
            for r in reasons:
                print(f"      - {r}")
        
        return is_trap, trap_score
    
    def detect_bear_trap(self, df):
        """
        Bear Trap: Precio rompe soporte pero NO hay fuerza real
        Señales:
        - Ruptura de soporte con vela pequeña
        - RSI ya en sobreventa antes de la ruptura
        - Volumen bajo
        - Mechas inferiores largas (rechazo)
        """
        if len(df) < 30:
            return False, 0
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        recent = df.tail(20)
        
        # Encontrar soporte reciente
        support = recent['low'].iloc[:-1].min()
        
        # ¿Rompió el soporte?
        broke_support = last['close'] < support
        
        if not broke_support:
            return False, 0
        
        trap_score = 0
        reasons = []
        
        # 1. Vela de ruptura débil
        candle_body = abs(last['close'] - last['open'])
        candle_range = last['high'] - last['low']
        if candle_range > 0 and candle_body / candle_range < 0.4:
            trap_score += 30
            reasons.append("Vela de ruptura débil")
        
        # 2. RSI ya en sobreventa (<30)
        if last.get('rsi', 50) < 30:
            trap_score += 25
            reasons.append("RSI sobrevendido antes de ruptura")
        
        # 3. Mecha inferior larga (rechazo inmediato)
        lower_wick = min(last['open'], last['close']) - last['low']
        if candle_range > 0 and lower_wick / candle_range > 0.5:
            trap_score += 30
            reasons.append("Rechazo con mecha inferior larga")
        
        # 4. Divergencia: Precio baja pero momentum sube
        if 'macd' in df.columns:
            macd_trend = df['macd'].tail(5).diff().mean()
            if macd_trend > 0:  # MACD subiendo mientras precio baja
                trap_score += 15
                reasons.append("Divergencia alcista en MACD")
        
        is_trap = trap_score >= 50
        
        if is_trap:
            print(f"   🚨 BEAR TRAP DETECTADO (Score: {trap_score})")
            for r in reasons:
                print(f"      - {r}")
        
        return is_trap, trap_score
    
    def detect_fakeout(self, df):
        """
        Fakeout: Movimiento rápido que invierte inmediatamente
        Señales:
        - Vela con mechas muy largas en ambos lados
        - Cierre cerca del precio de apertura (indecisión)
        - Volatilidad extrema sin seguimiento
        """
        if len(df) < 10:
            return False, 0
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        trap_score = 0
        reasons = []
        
        candle_body = abs(last['close'] - last['open'])
        candle_range = last['high'] - last['low']
        upper_wick = last['high'] - max(last['open'], last['close'])
        lower_wick = min(last['open'], last['close']) - last['low']
        
        # 1. Mechas largas en ambos lados (indecisión)
        if candle_range > 0:
            upper_ratio = upper_wick / candle_range
            lower_ratio = lower_wick / candle_range
            
            if upper_ratio > 0.3 and lower_ratio > 0.3:
                trap_score += 40
                reasons.append("Mechas largas en ambos lados (indecisión)")
        
        # 2. Cuerpo muy pequeño (doji o spinning top)
        if candle_range > 0 and candle_body / candle_range < 0.2:
            trap_score += 30
            reasons.append("Cuerpo muy pequeño (indecisión)")
        
        # 3. Volatilidad extrema sin seguimiento
        recent_volatility = df['close'].tail(10).std()
        avg_volatility = df['close'].tail(50).std()
        
        if recent_volatility > avg_volatility * 2:
            trap_score += 20
            reasons.append("Volatilidad extrema sin tendencia clara")
        
        is_trap = trap_score >= 50
        
        if is_trap:
            print(f"   🚨 FAKEOUT DETECTADO (Score: {trap_score})")
            for r in reasons:
                print(f"      - {r}")
        
        return is_trap, trap_score
    
    def detect_whipsaw(self, df):
        """
        Whipsaw: Cambios rápidos de dirección (mercado errático)
        Señales:
        - Múltiples reversiones en corto tiempo
        - Sin tendencia clara
        - Velas alternando colores constantemente
        """
        if len(df) < 15:
            return False, 0
        
        recent = df.tail(10)
        
        trap_score = 0
        reasons = []
        
        # Contar cambios de dirección
        reversals = 0
        for i in range(1, len(recent)):
            curr_bullish = recent.iloc[i]['close'] > recent.iloc[i]['open']
            prev_bullish = recent.iloc[i-1]['close'] > recent.iloc[i-1]['open']
            if curr_bullish != prev_bullish:
                reversals += 1
        
        # Si hay muchas reversiones, es whipsaw
        if reversals >= 6:  # 6+ cambios en 10 velas
            trap_score += 60
            reasons.append(f"Demasiadas reversiones ({reversals} en 10 velas)")
        
        # Rango de precios muy estrecho (lateral)
        price_range = recent['high'].max() - recent['low'].min()
        avg_price = recent['close'].mean()
        
        if avg_price > 0 and (price_range / avg_price) < 0.002:  # <0.2%
            trap_score += 30
            reasons.append("Mercado lateral sin dirección")
        
        is_trap = trap_score >= 50
        
        if is_trap:
            print(f"   🚨 WHIPSAW DETECTADO (Score: {trap_score})")
            for r in reasons:
                print(f"      - {r}")
        
        return is_trap, trap_score

        return is_trap, trap_score

    def detect_liquidity_sweep(self, df, action, levels):
        """
        Detecta tomas de liquidez (Liquidity Sweep).
        El precio perfora un nivel clave (limpia stops) y regresa rápidamente con fuerza.
        """
        if len(df) < 5: return False, 0
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Para un CALL (buscando reversión alcista)
        if action == 'CALL':
            for support in levels.get('support', []):
                # Si la vela anterior o actual perforó el soporte pero cerró por encima
                was_below = prev['low'] < support and prev['close'] > support
                is_below = last['low'] < support and last['close'] > support
                
                # Y la vela actual es alcista con fuerza (volumen o tamaño)
                if (was_below or is_below) and last['close'] > last['open']:
                    print(f"   🌊 LIQUIDITY SWEEP (Soporte {support:.5f}): Stops limpiados. Potencial entrada fuerte.")
                    return True, 85
                    
        # Para un PUT (buscando reversión bajista)
        if action == 'PUT':
            for resistance in levels.get('resistance', []):
                was_above = prev['high'] > resistance and prev['close'] < resistance
                is_above = last['high'] > resistance and last['close'] < resistance
                
                if (was_above or is_above) and last['close'] < last['open']:
                    print(f"   🌊 LIQUIDITY SWEEP (Resistencia {resistance:.5f}): Liquidez tomada. Potencial entrada fuerte.")
                    return True, 85
                    
        return False, 0

    def detect_level_exhaustion(self, df, levels):
        """
        Detecta si un nivel está exhausto (demasiados toques).
        Regla: Un nivel tocado más de 3 veces en 100 velas es probable que rompa.
        """
        last_price = df.iloc[-1]['close']
        recent_df = df.tail(100)
        
        exhausted_levels = {'support': [], 'resistance': []}
        
        # Analizar soportes
        for s in levels.get('support', []):
            touches = ((recent_df['low'] - s).abs() / s < 0.0005).sum()
            if touches >= 3:
                exhausted_levels['support'].append(s)
                
        # Analizar resistencias
        for r in levels.get('resistance', []):
            touches = ((recent_df['high'] - r).abs() / r < 0.0005).sum()
            if touches >= 3:
                exhausted_levels['resistance'].append(r)
                
        return exhausted_levels

    def detect_price_discovery(self, df):
        """
        Detecta si el precio está en 'Descubrimiento de Precio' (buscando nuevos máximos/mínimos).
        Si el precio rompe el máximo/mínimo de las últimas 200 velas con fuerza, NO intentar reversión.
        """
        if len(df) < 200: return False
        
        historical = df.iloc[:-10]
        recent = df.tail(10)
        
        h_max = historical['high'].max()
        h_min = historical['low'].min()
        
        curr_max = recent['high'].max()
        curr_min = recent['low'].min()
        
        if curr_max > h_max:
            print("   🚀 PRICE DISCOVERY (ALCISTA): El precio busca nuevos máximos. Peligro vender.")
            return 'BULL_DISCOVERY'
        if curr_min < h_min:
            print("   🚀 PRICE DISCOVERY (BAJISTA): El precio busca nuevos mínimos. Peligro comprar.")
            return 'BEAR_DISCOVERY'
            
        return None

    def detect_falling_knife(self, df, action):
        """
        Detecta si el precio está en caída libre (Falling Knife) o subida parabólica.
        Si está en caída libre, NO comprar (CALL).
        Si está en subida parabólica, NO vender (PUT).
        """
        if len(df) < 15:
            return False, 0
            
        recent = df.tail(10)
        
        # 1. Fuerza del movimiento bajista
        price_drop = recent['close'].diff().sum()
        avg_candle_size = abs(recent['high'] - recent['low']).mean()
        
        # Caída libre: Múltiples velas grandes seguidas sin mechas de rebote
        if action == 'CALL' and price_drop < 0:
            # Si el precio ha caído más de 3 veces el tamaño promedio de vela en 10 min
            if abs(price_drop) > avg_candle_size * 4:
                print(f"   🚨 FALLING KNIFE: Caída demasiado fuerte ({price_drop:.5f}). No intentar comprar.")
                return True, 85
        
        # Subida parabólica
        if action == 'PUT' and price_drop > 0:
            if price_drop > avg_candle_size * 4:
                print(f"   🚨 PARABOLIC ROCKET: Subida demasiado fuerte. No intentar vender.")
                return True, 85
                
        return False, 0

    def detect_exhaustion_failure(self, df, action):
        """
        Detecta si un rebote en nivel clave ha fallado (Debilidad).
        Si el rebote es muy débil, es probable que el nivel se rompa.
        """
        if len(df) < 5:
            return False, 0
            
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Si intentamos un CALL, y la vela actual es alcista pero MUY pequeña
        # comparada con la bajista anterior, hay debilidad.
        if action == 'CALL':
            if last['close'] > last['open'] and prev['close'] < prev['open']:
                bull_body = last['close'] - last['open']
                bear_body = prev['open'] - prev['close']
                if bull_body < bear_body * 0.3: # Rebote < 30% de la caída
                    print("   🚨 REBOTE DÉBIL: Compradores sin fuerza. Probable ruptura de soporte.")
                    return True, 70
        
        if action == 'PUT':
            if last['close'] < last['open'] and prev['close'] > prev['open']:
                bear_body = last['open'] - last['close']
                bull_body = prev['close'] - prev['open']
                if bear_body < bull_body * 0.3:
                    print("   🚨 RECHAZO DÉBIL: Vendedores sin fuerza. Probable ruptura de resistencia.")
                    return True, 70
                    
        return False, 0

    def detect_volatility_explosion(self, df):
        """
        Detecta si la volatilidad está explotando (Bandas de Bollinger se ensanchan).
        Si la volatilidad sube un 40% en 5 velas, es una explosión: NO reversiones.
        """
        if len(df) < 20: return False, 0
        
        recent_std = df['close'].tail(5).std()
        prev_std = df['close'].shift(5).tail(20).std()
        
        if prev_std > 0 and recent_std > prev_std * 1.4:
            print(f"   ⚡ EXPLOSIÓN DE VOLATILIDAD: Mercado inestable ({recent_std/prev_std:.2f}x). Peligro reversión.")
            return True, 90
        return False, 0

    def detect_momentum_acceleration(self, df, action):
        """
        Detecta si el precio está ACELERANDO hacia el nivel (Peligro)
        o DECELERANDO (Oportunidad de reversión).
        Analiza el tamaño de los cuerpos de las últimas 3 velas.
        """
        if len(df) < 5: return False, 0
        
        recent = df.tail(3)
        bodies = [abs(c['close'] - c['open']) for _, c in recent.iterrows()]
        
        # Si cada vela es más grande que la anterior -> ACELERACIÓN
        if bodies[2] > bodies[1] > bodies[0]:
            print(f"   🏎️ ACELERACIÓN DE MOMENTUM: Velas creciendo ({bodies[2]/bodies[0]:.2f}x). El muro no aguantará.")
            return True, 85 # Muy peligroso
        
        return False, 0

    def detect_consolidation_on_level(self, df, levels):
        """
        Detecta si el precio está 'grinding' o consolidando sobre un nivel.
        Si el precio pasa más de 5 velas muy cerca del nivel sin rebotar,
        es una señal de que va a romper.
        """
        if len(df) < 10: return False, 0
        
        last_price = df.iloc[-1]['close']
        recent = df.tail(8)
        
        # Buscar el nivel más cercano
        all_levels = levels.get('support', []) + levels.get('resistance', [])
        if not all_levels: return False, 0
        
        nearest = min(all_levels, key=lambda x: abs(x - last_price))
        
        # ¿Las últimas 6 velas están todas dentro del 0.03% del nivel?
        consolidating_candles = 0
        for _, row in recent.iterrows():
            if abs(row['close'] - nearest) / nearest < 0.0003:
                consolidating_candles += 1
        
        if consolidating_candles >= 5:
            print(f"   🧱 CONSOLIDACIÓN EN NIVEL: El precio está acumulando sobre {nearest:.5f}. Probable ruptura.")
            return True, 80
            
        return False, 0

    def detect_all_traps(self, df, proposed_action):
        """
        Ejecuta todos los detectores y retorna si hay alguna trampa
        
        Returns:
            tuple: (is_trap, trap_type, trap_score, should_inverse)
        """
        # Detectar niveles de soporte y resistencia (usar 100 velas para mayor precisión)
        lookback = min(100, len(df))
        recent_medium = df.tail(lookback)
        resistance = recent_medium['high'].max()
        support = recent_medium['low'].min()
        current_price = df.iloc[-1]['close']
        
        # También calcular niveles de 20 velas para contexto corto
        recent_short = df.tail(20)
        short_resistance = recent_short['high'].max()
        short_support = recent_short['low'].min()
        
        # 🚨 TRAMPA: Operación en dirección equivocada
        # Usar niveles de 100 velas (más fiables) para la verificación
        at_resistance = current_price >= resistance * 0.998
        at_support = current_price <= support * 1.002
        
        # Verificar si el precio está en el MEDIO del rango (no cerca de extremos)
        range_short = short_resistance - short_support
        mid_range = (short_resistance + short_support) / 2
        dist_from_mid = abs(current_price - mid_range) / range_short if range_short > 0 else 1
        
        # Solo considerar WRONG_DIRECTION si el precio está claramente en un extremo del rango
        if proposed_action == 'CALL' and at_resistance and dist_from_mid > 0.35:
            print(f"   ⚠️ PRECAUCIÓN: Intentando COMPRAR cerca de resistencia ({resistance:.5f})")
            print(f"      - Precio actual: {current_price:.5f}")
            print(f"      - Se permite solo si hay confirmación fuerte de ruptura")
            # No invertir automáticamente, solo marcar como riesgo
            return True, 'WRONG_DIRECTION_CALL', 60, False
        
        if proposed_action == 'PUT' and at_support and dist_from_mid > 0.35:
            print(f"   ⚠️ PRECAUCIÓN: Intentando VENDER cerca de soporte ({support:.5f})")
            print(f"      - Precio actual: {current_price:.5f}")
            print(f"      - Se permite solo si hay confirmación fuerte de ruptura")
            return True, 'WRONG_DIRECTION_PUT', 60, False
        
        # 🚨 NUEVA TRAMPA: Falling Knife (Caída libre)
        falling_knife, knife_score = self.detect_falling_knife(df, proposed_action)
        if falling_knife:
            return True, 'FALLING_KNIFE', knife_score, False
            
        # 🚨 NUEVA TRAMPA: Exhaustion Failure (Debilidad de rebote)
        weak_rebound, weak_score = self.detect_exhaustion_failure(df, proposed_action)
        if weak_rebound:
            return True, 'WEAK_REBOUND_FAILURE', weak_score, False

        if weak_rebound:
            return True, 'WEAK_REBOUND_FAILURE', weak_score, False

        # 🚨 NUEVA TRAMPA: Explosión de Volatilidad (Fase de ruptura violenta)
        vol_explosion, vol_score = self.detect_volatility_explosion(df)
        if vol_explosion:
            return True, 'VOLATILITY_EXPLOSION', vol_score, False

        # 🚨 NUEVA TRAMPA: Aceleración (Velas cada vez más grandes)
        acceleration, acc_score = self.detect_momentum_acceleration(df, proposed_action)
        if acceleration:
            return True, 'MOMENTUM_ACCELERATION_TRAP', acc_score, False

        # 🚨 NUEVA TRAMPA: Consolidación (Acumulación sobre nivel)
        # Necesitamos los niveles para este detector
        # Note: Esta función detect_all_traps no recibe levels, por lo que usaremos
        # el soporte/resistencia calculado localmente (recent high/low)
        local_levels = {'support': [support], 'resistance': [resistance]}
        consolidating, cons_score = self.detect_consolidation_on_level(df, local_levels)
        if consolidating:
            return True, 'CONSOLIDATION_BREAKOUT_TRAP', cons_score, False

        # 🚨 NUEVA TRAMPA: Price Discovery (Cazar el techo/suelo)
        discovery = self.detect_price_discovery(df)
        if (discovery == 'BULL_DISCOVERY' and proposed_action == 'PUT') or \
           (discovery == 'BEAR_DISCOVERY' and proposed_action == 'CALL'):
            return True, 'PRICE_DISCOVERY_TRAP', 90, False

        # Detectores originales
        bull_trap, bull_score = self.detect_bull_trap(df)
        bear_trap, bear_score = self.detect_bear_trap(df)
        fakeout, fakeout_score = self.detect_fakeout(df)
        whipsaw, whipsaw_score = self.detect_whipsaw(df)
        
        # 🚨 TOMA DE LIQUIDEZ (Esto NO es trampa, es OPORTUNIDAD, pero la marcamos para invertir lógica si es necesario)
        # Por ahora, si es sweep, reducimos probabilidad de que sea trampa de ruptura
        
        # Si detectamos una trampa relevante a la acción propuesta
        # NOTA: Ya no invertimos la dirección, solo bloqueamos la operación
        # La inversión causaba entradas en dirección equivocada
        if proposed_action == 'CALL' and bull_trap and bull_score >= 60:
            return True, 'BULL_TRAP', bull_score, False  # Solo bloquear, NO invertir
        
        if proposed_action == 'PUT' and bear_trap and bear_score >= 60:
            return True, 'BEAR_TRAP', bear_score, False  # Solo bloquear, NO invertir
        
        # Fakeout o Whipsaw: NO operar
        if fakeout:
            return True, 'FAKEOUT', fakeout_score, False
        
        if whipsaw:
            return True, 'WHIPSAW', whipsaw_score, False
        
        return False, None, 0, False
    
    def get_trap_advice(self, df, proposed_action):
        """
        Analiza si la acción propuesta cae en una trampa
        
        Returns:
            dict con recomendación
        """
        is_trap, trap_type, score, should_inverse = self.detect_all_traps(df, proposed_action)
        
        if not is_trap:
            return {
                'is_safe': True,
                'advice': 'No se detectaron trampas',
                'action': proposed_action
            }
        
        if should_inverse:
            new_action = 'PUT' if proposed_action == 'CALL' else 'CALL'
            return {
                'is_safe': False,
                'trap_detected': trap_type,
                'trap_score': score,
                'advice': f'TRAMPA DETECTADA: {trap_type}. Considera invertir la operación.',
                'action': new_action,
                'inverted': True
            }
        else:
            return {
                'is_safe': False,
                'trap_detected': trap_type,
                'trap_score': score,
                'advice': f'TRAMPA DETECTADA: {trap_type}. NO OPERAR.',
                'action': 'WAIT',
                'inverted': False
            }
