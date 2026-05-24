"""
🔄 ESTRATEGIA SMART REVERSAL
Ideal para mercados laterales o canales de tendencia.
Identifica agotamiento en niveles de soporte/resistencia y opera la reversión.
"""
import pandas as pd
import numpy as np

class SmartReversalStrategy:
    def __init__(self):
        pass

    def calculate_indicators(self, df):
        """Asegura que los indicadores necesarios estén presentes"""
        # RSI ya viene del FeatureEngineer, pero por si acaso:
        if 'rsi' not in df.columns:
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
        
        # Bandas de Bollinger para volatilidad y límites
        if 'bb_high' not in df.columns:
            sma = df['close'].rolling(window=20).mean()
            std = df['close'].rolling(window=20).std()
            df['bb_high'] = sma + (std * 2)
            df['bb_low'] = sma - (std * 2)
        
        return df

    def find_levels(self, df, window=20):
        """Identifica niveles locales de soporte y resistencia"""
        recent = df.tail(window)
        resistance = recent['high'].max()
        support = recent['low'].min()
        return support, resistance

    def analyze(self, df):
        """Analiza el mercado para buscar reversiones con confirmación multi-vela"""
        if len(df) < 50:
            return {'action': 'WAIT', 'confidence': 0, 'reason': 'Datos insuficientes'}

        df = self.calculate_indicators(df)
        last_candle = df.iloc[-1]
        prev_candle = df.iloc[-2]
        prev2_candle = df.iloc[-3] if len(df) >= 3 else prev_candle
        
        current_price = last_candle['close']
        rsi = last_candle['rsi']
        support, resistance = self.find_levels(df)
        
        # Verificar tendencia de las últimas 5 velas
        last_5 = df.tail(5)
        bodies_5 = [abs(r['close'] - r['open']) for _, r in last_5.iterrows()]
        avg_body_5 = sum(bodies_5) / len(bodies_5) if bodies_5 else 0
        
        # --- LÓGICA PARA CALL (Reversión al Alza) ---
        # REGLA: Solo comprar si el precio YA REBOTÓ del soporte
        # NO comprar mientras está cayendo hacia el soporte
        
        # 1. Precio cerca del soporte o banda inferior
        at_bottom = current_price <= support * 1.0005 or current_price <= last_candle['bb_low'] * 1.0005
        
        # 2. RSI en sobreventa
        oversold = rsi < 35
        
        # 3. CONFIRMACIÓN DE REBOTE (Crítico)
        candle_is_bullish = last_candle['close'] > last_candle['open']
        
        # 4. Verificar que las últimas 2 velas eran BAJISTAS (tendencia bajista confirmada)
        prev_was_bearish = prev_candle['close'] < prev_candle['open']
        prev2_was_bearish = prev2_candle['close'] < prev2_candle['open']
        bearish_streak = prev2_was_bearish and prev_was_bearish
        
        # 5. Mecha inferior larga = rechazo del soporte
        lower_wick = min(last_candle['open'], last_candle['close']) - last_candle['low']
        candle_range = last_candle['high'] - last_candle['low']
        strong_rejection = candle_range > 0 and lower_wick / candle_range > 0.3
        
        # 6. Vela de reversión debe tener cuerpo significativo (> 60% del promedio)
        body_ratio = abs(last_candle['close'] - last_candle['open']) / avg_body_5 if avg_body_5 > 0 else 1
        significant_body = body_ratio > 0.6 or strong_rejection
        
        if at_bottom and oversold and candle_is_bullish and significant_body and (bearish_streak or strong_rejection):
            confidence = 50
            if strong_rejection: confidence += 20
            if rsi < 30: confidence += 10
            if bearish_streak: confidence += 10
            if significant_body and not strong_rejection: confidence += 10
            
            return {
                'action': 'CALL',
                'confidence': min(confidence, 90),
                'strategy': 'Smart Reversal (Alcista)',
                'reason': f'Rebote confirmado en soporte {support:.5f} con RSI {rsi:.1f}',
                'details': {
                    'price': current_price,
                    'support': support,
                    'rsi': rsi,
                    'bb_low': last_candle['bb_low'],
                    'rejection_confirmed': strong_rejection
                },
                'expiration': 180
            }

        # --- LÓGICA PARA PUT (Reversión a la Baja) ---
        # REGLA: Solo vender si el precio YA RECHAZÓ la resistencia
        # NO vender mientras está subiendo hacia la resistencia
        
        at_top = current_price >= resistance * 0.9995 or current_price >= last_candle['bb_high'] * 0.9995
        overbought = rsi > 65
        candle_is_bearish = last_candle['close'] < last_candle['open']
        
        prev_was_bullish = prev_candle['close'] > prev_candle['open']
        prev2_was_bullish = prev2_candle['close'] > prev2_candle['open']
        bullish_streak = prev2_was_bullish and prev_was_bullish
        
        upper_wick = last_candle['high'] - max(last_candle['open'], last_candle['close'])
        candle_range = last_candle['high'] - last_candle['low']
        strong_rejection = candle_range > 0 and upper_wick / candle_range > 0.3
        
        body_ratio = abs(last_candle['close'] - last_candle['open']) / avg_body_5 if avg_body_5 > 0 else 1
        significant_body = body_ratio > 0.6 or strong_rejection
        
        if at_top and overbought and candle_is_bearish and significant_body and (bullish_streak or strong_rejection):
            confidence = 50
            if strong_rejection: confidence += 20
            if rsi > 70: confidence += 10
            if bullish_streak: confidence += 10
            if significant_body and not strong_rejection: confidence += 10
            
            return {
                'action': 'PUT',
                'confidence': min(confidence, 90),
                'strategy': 'Smart Reversal (Bajista)',
                'reason': f'Rechazo confirmado en resistencia {resistance:.5f} con RSI {rsi:.1f}',
                'details': {
                    'price': current_price,
                    'resistance': resistance,
                    'rsi': rsi,
                    'bb_high': last_candle['bb_high'],
                    'rejection_confirmed': strong_rejection
                },
                'expiration': 180
            }

        return {'action': 'WAIT', 'confidence': 0, 'reason': 'No hay condiciones de reversión'}
