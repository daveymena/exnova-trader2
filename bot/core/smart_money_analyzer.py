"""
Smart Money Analyzer - Sistema avanzado con Order Blocks M15/M30
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from strategies.fvg_analyzer import FVGAnalyzer

class SmartMoneyAnalyzer:
    """Analizador avanzado de conceptos Smart Money con Order Blocks M15/M30 y FVG"""
    
    def __init__(self):
        self.min_candles = 50
        self.fvg_analyzer = FVGAnalyzer(min_gap_pct=0.005, min_body_ratio=1.3)
        self.ob_lookback = 60
    
    def analyze(self, df: pd.DataFrame) -> Dict:
        """Método principal de análisis compatible con el bot"""
        return self.analyze_smart_money_structure(df)
    
    def find_order_blocks(self, candles: pd.DataFrame) -> Dict:
        """
        Detecta Order Blocks (OB) en M15/M30.
        Un OB es la última vela antes de un movimiento impulsivo fuerte.
        
        Bullish OB: Vela roja (bajista) antes de 3+ velas verdes consecutivas fuertes
        Bearish OB: Vela verde (alcista) antes de 3+ velas rojas consecutivas fuertes
        """
        if len(candles) < 20:
            return {'bullish': [], 'bearish': []}
        
        bullish_obs = []
        bearish_obs = []
        
        avg_body = abs(candles['close'] - candles['open']).rolling(14).mean()
        
        for i in range(2, len(candles) - 3):
            v_base = candles.iloc[i]
            v1 = candles.iloc[i+1]
            v2 = candles.iloc[i+2]
            v3 = candles.iloc[i+3]
            
            body_base = abs(v_base['close'] - v_base['open'])
            avg = avg_body.iloc[i] if not pd.isna(avg_body.iloc[i]) else body_base
            
            # Bullish OB: Vela roja (base) + 3 velas verdes fuertes consecutivas
            if (v_base['close'] < v_base['open'] and
                v1['close'] > v1['open'] and 
                v2['close'] > v2['open'] and 
                v3['close'] > v3['open']):
                
                # El movimiento impulsivo debe ser significativo
                move_strength = (v3['close'] - v1['close']) / v1['close'] * 100
                if move_strength > 0.15 and body_base > avg * 0.5:
                    strength = min(100, 50 + move_strength * 50)
                    bullish_obs.append({
                        'type': 'bullish',
                        'high': v_base['high'],
                        'low': v_base['low'],
                        'close': v_base['close'],
                        'index': i,
                        'strength': strength,
                        'mitigated': False
                    })
            
            # Bearish OB: Vela verde (base) + 3 velas rojas fuertes consecutivas
            if (v_base['close'] > v_base['open'] and
                v1['close'] < v1['open'] and 
                v2['close'] < v2['open'] and 
                v3['close'] < v3['open']):
                
                move_strength = abs((v3['close'] - v1['close']) / v1['close'] * 100)
                if move_strength > 0.15 and body_base > avg * 0.5:
                    strength = min(100, 50 + move_strength * 50)
                    bearish_obs.append({
                        'type': 'bearish',
                        'high': v_base['high'],
                        'low': v_base['low'],
                        'close': v_base['close'],
                        'index': i,
                        'strength': strength,
                        'mitigated': False
                    })
        
        return {'bullish': bullish_obs, 'bearish': bearish_obs}
    
    def check_ob_respect(self, candles: pd.DataFrame, ob: Dict) -> Tuple[bool, str]:
        """
        Verifica si un Order Block está siendo respetado.
        Respetado = precio llega al OB y rebota (no lo rompe)
        No respetado = precio rompe el OB con fuerza
        """
        recent = candles.tail(10)
        ob_high = ob['high']
        ob_low = ob['low']
        
        if ob['type'] == 'bullish':
            # Para CALL: precio debe estar DENTRO o CERCA del OB y NO romperlo abajo
            touches = recent['low'].min() <= ob_low * 1.002
            broken = (recent['close'] < ob_low * 0.998).any()
            if broken:
                return False, "OB roto por abajo - no respetado"
            if touches:
                return True, "OB respetado - precio tocó y no rompió"
            return False, "Precio aún no llega al OB"
        
        else:  # bearish
            # Para PUT: precio debe estar DENTRO o CERCA del OB y NO romperlo arriba
            touches = recent['high'].max() >= ob_high * 0.998
            broken = (recent['close'] > ob_high * 1.002).any()
            if broken:
                return False, "OB roto por arriba - no respetado"
            if touches:
                return True, "OB respetado - precio tocó y no rompió"
            return False, "Precio aún no llega al OB"
    
    def get_trend_from_htf(self, candles_m15: pd.DataFrame, candles_m30: pd.DataFrame = None) -> str:
        """Determina tendencia de M15/M30 usando EMAs"""
        df = candles_m30 if candles_m30 is not None and len(candles_m30) >= 20 else candles_m15
        if len(df) < 20:
            return 'neutral'
        
        ema20 = df['close'].ewm(span=20).mean()
        ema50 = df['close'].ewm(span=50).mean() if len(df) >= 50 else ema20
        
        last_ema20 = ema20.iloc[-1]
        last_ema50 = ema50.iloc[-1]
        last_price = df.iloc[-1]['close']
        
        # EMA20 > EMA50 = alcista, EMA20 < EMA50 = bajista
        if last_ema20 > last_ema50 and last_price > last_ema20:
            return 'bullish'
        elif last_ema20 < last_ema50 and last_price < last_ema20:
            return 'bearish'
        else:
            return 'neutral'
    
    def validate_trade_with_ob(self, candles_m15: pd.DataFrame, direction: str) -> Dict:
        """
        Valida si hay un Order Block de M15 que respalde la operación.
        
        Para CALL: Buscar OB alcista (bullish), precio cerca del OB, OB respetado
        Para PUT: Buscar OB bajista (bearish), precio cerca del OB, OB respetado
        """
        if len(candles_m15) < 20:
            return {'valid': False, 'reason': 'Datos M15 insuficientes'}
        
        obs = self.find_order_blocks(candles_m15)
        current_price = candles_m15.iloc[-1]['close']
        trend = self.get_trend_from_htf(candles_m15)
        
        if direction == 'CALL':
            # Buscar el OB alcista más cercano por debajo del precio
            valid_obs = [ob for ob in obs['bullish'] if ob['low'] <= current_price * 1.005]
            if not valid_obs:
                valid_obs = [ob for ob in obs['bullish']]
            
            for ob in reversed(valid_obs):
                if ob['low'] <= current_price <= ob['high'] * 1.003:
                    respected, msg = self.check_ob_respect(candles_m15, ob)
                    if respected:
                        aligned = trend in ('bullish', 'neutral')
                        return {
                            'valid': True,
                            'reason': f"OB alcista respetado: {ob['low']:.5f}-{ob['high']:.5f}",
                            'ob': ob,
                            'trend_aligned': aligned,
                            'trend': trend
                        }
            
            # Si no hay OB exacto, verificar tendencia al menos
            return {
                'valid': trend == 'bullish',
                'reason': f"No hay OB alcista cercano. Tendencia: {trend}",
                'ob': None,
                'trend_aligned': trend == 'bullish',
                'trend': trend
            }
        
        else:  # PUT
            valid_obs = [ob for ob in obs['bearish'] if ob['high'] >= current_price * 0.995]
            if not valid_obs:
                valid_obs = [ob for ob in obs['bearish']]
            
            for ob in reversed(valid_obs):
                if ob['high'] >= current_price >= ob['low'] * 0.997:
                    respected, msg = self.check_ob_respect(candles_m15, ob)
                    if respected:
                        aligned = trend in ('bearish', 'neutral')
                        return {
                            'valid': True,
                            'reason': f"OB bajista respetado: {ob['low']:.5f}-{ob['high']:.5f}",
                            'ob': ob,
                            'trend_aligned': aligned,
                            'trend': trend
                        }
            
            return {
                'valid': trend == 'bearish',
                'reason': f"No hay OB bajista cercano. Tendencia: {trend}",
                'ob': None,
                'trend_aligned': trend == 'bearish',
                'trend': trend
            }
    
    def analyze_smart_money_structure(self, candles: pd.DataFrame) -> Dict:
        """Análisis completo de estructura Smart Money e Imbalances"""
        if len(candles) < self.min_candles:
            return self._no_analysis("Insuficientes velas")
        
        try:
            fvgs = self.fvg_analyzer.find_fvgs(candles)
            latest_fvg = self.fvg_analyzer.get_latest_fvg(candles)
            obs = self.find_order_blocks(candles)
            recent_trend = self._get_simple_trend(candles)
            current_price = candles.iloc[-1]['close']
            
            fvg_hit = False
            fvg_type = None
            if latest_fvg:
                if latest_fvg['bottom'] <= current_price <= latest_fvg['top']:
                    fvg_hit = True
                    fvg_type = latest_fvg['type']
            
            # Detectar si hay un OB cerca y respetado
            ob_hit = False
            ob_strength = 0.0
            ob_near = None
            
            for ob_list in [obs['bullish'], obs['bearish']]:
                for ob in ob_list:
                    if ob['low'] <= current_price <= ob['high'] * 1.003:
                        respected, _ = self.check_ob_respect(candles, ob)
                        ob_hit = respected
                        ob_strength = ob['strength'] / 100
                        ob_near = ob
                        break
            
            entry_signal = {
                'should_enter': False,
                'direction': None,
                'confidence': 50,
                'entry_reasons': [],
                'risk_factors': [],
                'is_valid': False
            }
            
            if ob_hit and ob_near:
                dir_from_ob = 'CALL' if ob_near['type'] == 'bullish' else 'PUT'
                entry_signal.update({
                    'should_enter': True,
                    'direction': dir_from_ob,
                    'confidence': 75 + (ob_strength * 15),
                    'entry_reasons': [f"Order Block {ob_near['type']} respetado"],
                    'is_valid': True
                })
            elif fvg_hit and fvg_type == 'bullish' and recent_trend != 'bearish':
                entry_signal.update({
                    'should_enter': True,
                    'direction': 'CALL',
                    'confidence': 70,
                    'entry_reasons': ['Precio mitigando Bullish FVG'],
                    'is_valid': True
                })
            elif fvg_hit and fvg_type == 'bearish' and recent_trend != 'bullish':
                entry_signal.update({
                    'should_enter': True,
                    'direction': 'PUT',
                    'confidence': 70,
                    'entry_reasons': ['Precio mitigando Bearish FVG'],
                    'is_valid': True
                })
            
            return {
                'timestamp': datetime.now().isoformat(),
                'order_blocks': obs,
                'fair_value_gaps': fvgs,
                'latest_fvg': latest_fvg,
                'fvg_detected': latest_fvg is not None,
                'fvg_hit': fvg_hit,
                'liquidity_zones': [],
                'market_structure': {'trend': recent_trend, 'bos': None, 'choch': None, 'strength': 60},
                'inducement_signals': [],
                'mitigation_analysis': {
                    'mitigated_fvgs': [f for f in fvgs['bullish'] + fvgs['bearish'] if f['is_mitigated']],
                    'pending_fvg': latest_fvg if not latest_fvg or not latest_fvg['is_mitigated'] else None
                },
                'directional_bias': {'bias': recent_trend, 'confidence': 65, 'confidence_factors': [f'Tendencia {recent_trend}']},
                'entry_signal': entry_signal,
                'confidence': entry_signal['confidence'] if entry_signal['should_enter'] else 50,
                'is_valid': entry_signal['is_valid'],
                'order_block_hit': ob_hit,
                'order_block_strength': ob_strength,
                'liquidity_grab': False,
                'premium_discount': 0.5
            }
            
        except Exception as e:
            import traceback
            print(f"Error en SmartMoneyAnalyzer: {e}")
            traceback.print_exc()
            return self._no_analysis(f"Error: {str(e)}")
    
    def _get_simple_trend(self, candles: pd.DataFrame) -> str:
        """Determina tendencia simple"""
        if len(candles) < 20:
            return 'neutral'
        
        recent = candles.tail(20)
        first_price = recent.iloc[0]['close']
        last_price = recent.iloc[-1]['close']
        
        change_pct = ((last_price - first_price) / first_price) * 100
        
        if change_pct > 0.1:
            return 'bullish'
        elif change_pct < -0.1:
            return 'bearish'
        else:
            return 'neutral'
    
    def _no_analysis(self, reason: str) -> Dict:
        """Retorna análisis vacío"""
        return {
            'timestamp': datetime.now().isoformat(),
            'order_blocks': [],
            'fair_value_gaps': [],
            'liquidity_zones': [],
            'market_structure': {'trend': 'neutral', 'bos': None, 'choch': None, 'strength': 0},
            'inducement_signals': [],
            'mitigation_analysis': {'mitigated_blocks': [], 'pending_mitigation': [], 'fresh_blocks': []},
            'directional_bias': {'bias': 'neutral', 'confidence': 0, 'confidence_factors': []},
            'entry_signal': {
                'should_enter': False,
                'direction': None,
                'confidence': 0,
                'entry_reasons': [],
                'risk_factors': [reason],
                'is_valid': False
            },
            'confidence': 0,
            'is_valid': False,
            'error': reason
        }