"""
Estrategia PCR Completa - Price Action basada en Estructuras y Fractalidad
Versión avanzada basada en curso JNLX Trading
Incluye: Estructuras de mercado, fractalidad, contextos de reversión/continuidad
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class PCRComplete:
    """
    PCR Completa: Estructuras + Fractalidad + Acción del Precio
    - Identifica swing highs/lows (máximos y mínimos de estructura)
    - Análisis de fractalidad entre timeframes
    - Zonas de compradores (demand) y vendedores (supply)
    - Contextos de reversión vs continuidad
    - Lectura de acción del precio (retests, rompimientos, trampas)
    """

    def __init__(self, ema_period=20, structure_lookback=100, fractal_tolerance=0.003):
        """
        Args:
            ema_period: Período para EMA (default 20)
            structure_lookback: Velas a analizar para estructuras (default 100)
            fractal_tolerance: Tolerancia para fractalidad (%): 0.3%
        """
        self.ema_period = ema_period
        self.structure_lookback = structure_lookback
        self.fractal_tolerance = fractal_tolerance

    def analyze(self, df, df_higher_tf=None, asset_name=None):
        """
        Análisis completo PCR Completa

        Args:
            df: DataFrame con OHLCV (timeframe actual)
            df_higher_tf: DataFrame de timeframe superior (opcional, para fractalidad)
            asset_name: Nombre del activo

        Returns:
            dict con análisis detallado y recomendación
        """
        if df is None or df.empty or len(df) < self.ema_period + 20:
            return {
                'signal': None,
                'confidence': 0,
                'reasons': ['Datos insuficientes'],
                'structure': None,
                'zones': None,
                'context': None,
                'price_action': None
            }

        result = {
            'timestamp': df.iloc[-1]['timestamp'] if 'timestamp' in df.columns else None,
            'close': float(df.iloc[-1]['close']),
            'signal': None,
            'confidence': 0,
            'reasons': [],
            'structure': None,
            'zones': None,
            'context': None,
            'price_action': None,
            'fractal_alignment': None
        }

        # 1. Analizar estructura de mercado
        structure = self._analyze_structure(df)
        result['structure'] = structure

        # 2. Detectar zonas S/D
        zones = self._detect_zones(df, structure)
        result['zones'] = zones

        # 3. Analizar contexto (reversión vs continuidad)
        context = self._analyze_context(df, structure)
        result['context'] = context

        # 4. Lectura de acción del precio
        price_action = self._analyze_price_action(df, structure, zones)
        result['price_action'] = price_action

        # 5. Fractalidad (si hay datos de timeframe superior)
        if df_higher_tf is not None and not df_higher_tf.empty:
            fractal = self._check_fractal_alignment(df, df_higher_tf, structure)
            result['fractal_alignment'] = fractal

        # 6. Generar señal final
        signal_data = self._generate_signal(
            df, structure, zones, context, price_action,
            result.get('fractal_alignment', None)
        )

        result['signal'] = signal_data['signal']
        result['confidence'] = signal_data['confidence']
        result['reasons'] = signal_data['reasons']

        return result

    def _analyze_structure(self, df):
        """
        Analiza la estructura de mercado
        Identifica swing highs (HH, LH) y swing lows (LL, HL)
        """
        if len(df) < 20:
            return None

        recent = df.tail(self.structure_lookback).copy()
        highs = recent['high'].values
        lows = recent['low'].values
        closes = recent['close'].values

        structure = {
            'swing_highs': [],
            'swing_lows': [],
            'current_trend': None,
            'hh': False,  # Higher High
            'll': False,  # Lower Low
            'lh': False,  # Lower High
            'hl': False,  # Higher Low
            'structure_break': None  # BOS o CHOCH
        }

        # Encontrar últimos 3 swing highs y lows
        swing_highs = []
        swing_lows = []

        # Buscar máximos y mínimos con movimiento significativo
        min_movement = 0.0005  # 0.05% movimiento mínimo para contar como estructura

        for i in range(5, len(highs) - 5):
            # Swing high: máximo local con confirmación
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                if highs[i] > max(highs[i-5:i]) * (1 - min_movement) or \
                   highs[i] > max(highs[i+1:i+6]) * (1 - min_movement):
                    swing_highs.append({'index': i, 'price': highs[i]})

            # Swing low: mínimo local con confirmación
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                if lows[i] < min(lows[i-5:i]) * (1 + min_movement) or \
                   lows[i] < min(lows[i+1:i+6]) * (1 + min_movement):
                    swing_lows.append({'index': i, 'price': lows[i]})

        # Ordenar por índice y tomar últimos
        if swing_highs:
            swing_highs = sorted(swing_highs, key=lambda x: x['index'])[-3:]
            structure['swing_highs'] = swing_highs

        if swing_lows:
            swing_lows = sorted(swing_lows, key=lambda x: x['index'])[-3:]
            structure['swing_lows'] = swing_lows

        # Determinar patrón HH/HL, LL/LH
        current_high = highs[-1]
        current_low = lows[-1]

        if len(swing_highs) >= 2:
            prev_high = swing_highs[-2]['price']
            if current_high > prev_high * 1.0002:  # HH
                structure['hh'] = True
                structure['current_trend'] = 'UP'
            else:  # LH
                structure['lh'] = True
                structure['current_trend'] = 'DOWN'

        if len(swing_lows) >= 2:
            prev_low = swing_lows[-2]['price']
            if current_low < prev_low * 0.9998:  # LL
                structure['ll'] = True
                structure['current_trend'] = 'DOWN'
            else:  # HL
                structure['hl'] = True
                structure['current_trend'] = 'UP'

        return structure

    def _detect_zones(self, df, structure):
        """
        Detecta zonas de Supply/Demand basadas en estructura
        """
        if not structure:
            return None

        current_price = df.iloc[-1]['close']

        zones = {
            'supply_zones': [],
            'demand_zones': [],
            'nearest_supply': None,
            'nearest_demand': None
        }

        # Supply zones: swing highs donde el precio intentó romper pero falló
        for sh in structure.get('swing_highs', []):
            # Si el precio rebotó desde aquí múltiples veces, es strong supply
            price_level = sh['price']
            zones['supply_zones'].append({
                'level': price_level,
                'type': 'supply_swing',
                'strength': 'strong',
                'distance_pct': ((price_level - current_price) / current_price) * 100 if current_price > 0 else 0
            })

        # Demand zones: swing lows donde el precio rebotó múltiples veces
        for sl in structure.get('swing_lows', []):
            price_level = sl['price']
            zones['demand_zones'].append({
                'level': price_level,
                'type': 'demand_swing',
                'strength': 'strong',
                'distance_pct': ((price_level - current_price) / current_price) * 100 if current_price > 0 else 0
            })

        # Encontrar zonas más cercanas
        if zones['supply_zones']:
            nearest_supply = min(zones['supply_zones'], key=lambda x: x['distance_pct'])
            if nearest_supply['distance_pct'] > 0:  # Supply debe estar ARRIBA del precio
                zones['nearest_supply'] = nearest_supply

        if zones['demand_zones']:
            nearest_demand = min(zones['demand_zones'],
                               key=lambda x: -x['distance_pct'])  # Demand debe estar ABAJO
            if nearest_demand['distance_pct'] < 0:
                zones['nearest_demand'] = nearest_demand

        return zones

    def _analyze_context(self, df, structure):
        """
        Analiza contexto: ¿Estamos en zona de REVERSIÓN o CONTINUIDAD?
        """
        if not structure:
            return None

        current_price = df.iloc[-1]['close']
        recent = df.tail(50).copy()

        context = {
            'type': None,  # 'reversal' o 'continuation'
            'strength': None,
            'reasons': [],
            'price_action_type': None  # 'retest', 'breakout', 'trap'
        }

        # Si HH + HL -> Tendencia UP, posible continuidad
        if structure.get('hh') and structure.get('hl'):
            context['type'] = 'continuation'
            context['price_action_type'] = 'breakout'  # Buscamos romper hacia arriba
            context['strength'] = 'strong'
            context['reasons'].append("Estructura alcista: HH + HL = continuidad UP")

        # Si LH + LL -> Tendencia DOWN, posible continuidad
        elif structure.get('lh') and structure.get('ll'):
            context['type'] = 'continuation'
            context['price_action_type'] = 'breakout'  # Buscamos romper hacia abajo
            context['strength'] = 'strong'
            context['reasons'].append("Estructura bajista: LH + LL = continuidad DOWN")

        # Si LH + HL -> Reversión (zigzag)
        elif structure.get('lh') and structure.get('hl'):
            context['type'] = 'reversal'
            context['price_action_type'] = 'retest'
            context['strength'] = 'medium'
            context['reasons'].append("Estructura lateral: LH + HL = posible reversión")

        # Si HH + LL -> Reversión (zigzag inverso)
        elif structure.get('hh') and structure.get('ll'):
            context['type'] = 'reversal'
            context['price_action_type'] = 'retest'
            context['strength'] = 'medium'
            context['reasons'].append("Estructura invertida: HH + LL = posible reversión")

        else:
            context['type'] = 'undefined'
            context['strength'] = 'weak'

        return context

    def _analyze_price_action(self, df, structure, zones):
        """
        Analiza la acción del precio en relación a las zonas
        Identifica: retests, rompimientos, trampas
        """
        if not zones:
            return None

        current_price = df.iloc[-1]['close']
        recent = df.tail(20).copy()

        pa = {
            'action_type': None,
            'location': None,
            'trend_confirmation': None,
            'quality': 'low'
        }

        # ¿Está cerca de una zona?
        if zones.get('nearest_supply'):
            supply = zones['nearest_supply']
            distance_pct = abs(supply['distance_pct'])

            # Si estamos dentro del 0.5% de la supply zone
            if distance_pct <= 0.5:
                pa['location'] = 'at_supply'
                pa['trend_confirmation'] = 'sell_pressure'  # Esperamos que rebote hacia abajo
                pa['quality'] = 'high'

        if zones.get('nearest_demand'):
            demand = zones['nearest_demand']
            distance_pct = abs(demand['distance_pct'])

            # Si estamos dentro del 0.5% de la demand zone
            if distance_pct <= 0.5:
                pa['location'] = 'at_demand'
                pa['trend_confirmation'] = 'buy_pressure'  # Esperamos que rebote hacia arriba
                pa['quality'] = 'high'

        return pa

    def _check_fractal_alignment(self, df, df_higher_tf, structure):
        """
        Verifica si la estructura del timeframe actual alinea con timeframe superior
        Fractalidad: mismo patrón a diferentes escalas = CONFIRMACIÓN
        """
        if df_higher_tf is None or df_higher_tf.empty or len(df_higher_tf) < 10:
            return None

        # Analizar estructura de timeframe superior
        higher_structure = self._analyze_structure(df_higher_tf)

        alignment = {
            'aligned': False,
            'higher_tf_trend': None,
            'current_tf_trend': None,
            'confidence_boost': 0
        }

        if higher_structure:
            alignment['higher_tf_trend'] = higher_structure.get('current_trend')
            alignment['current_tf_trend'] = structure.get('current_trend')

            # Si ambos timeframes están en la MISMA tendencia: FUERTE CONFIRMACIÓN
            if alignment['higher_tf_trend'] == alignment['current_tf_trend'] and alignment['higher_tf_trend']:
                alignment['aligned'] = True
                alignment['confidence_boost'] = 15  # +15% confianza si hay fractal alignment
            elif alignment['higher_tf_trend'] and alignment['current_tf_trend'] and \
                    alignment['higher_tf_trend'] != alignment['current_tf_trend']:
                # Tendencias opuestas: DEBILIDAD
                alignment['confidence_boost'] = -10

        return alignment

    def _generate_signal(self, df, structure, zones, context, price_action, fractal_alignment):
        """Genera señal final de trading (versión mejorada - más selectiva)"""
        signal = None
        confidence = 0
        reasons = []

        if not structure or not zones or not context:
            return {
                'signal': None,
                'confidence': 0,
                'reasons': ['No hay suficiente información de mercado']
            }

        # REGLA 1: CONTINUIDAD ALCISTA (Strong Setup)
        # Requiere: HH + HL + Precio en demand + Fractal alignment
        if context.get('type') == 'continuation' and structure.get('hh') and structure.get('hl'):
            if price_action.get('location') == 'at_demand' and zones.get('nearest_demand'):
                demand = zones['nearest_demand']
                distance_pct = abs(demand['distance_pct'])

                if distance_pct <= 0.3:  # Debe estar MUY cerca de demand
                    signal = 'CALL'
                    confidence = 75
                    reasons.append("Continuidad alcista: HH + HL confirmados")
                    reasons.append("Precio rebotando en demand zone")

                    # Boost if fractal aligned
                    if fractal_alignment and fractal_alignment.get('aligned'):
                        confidence = 90
                        reasons.append("✓ Confirmado en timeframe superior")

        # REGLA 2: CONTINUIDAD BAJISTA (Strong Setup)
        # Requiere: LL + LH + Precio en supply + Fractal alignment
        elif context.get('type') == 'continuation' and structure.get('ll') and structure.get('lh'):
            if price_action.get('location') == 'at_supply' and zones.get('nearest_supply'):
                supply = zones['nearest_supply']
                distance_pct = supply['distance_pct']

                if distance_pct <= 0.3:  # Debe estar MUY cerca de supply
                    signal = 'PUT'
                    confidence = 75
                    reasons.append("Continuidad bajista: LL + LH confirmados")
                    reasons.append("Precio rebotando en supply zone")

                    # Boost if fractal aligned
                    if fractal_alignment and fractal_alignment.get('aligned'):
                        confidence = 90
                        reasons.append("✓ Confirmado en timeframe superior")

        # REGLA 3: REVERSIÓN (Solo si NO hay continuidad clara)
        elif context.get('type') == 'reversal' or context.get('type') == 'undefined':
            # Reversión alcista solo si tocamos demand Y no hay LH reciente
            if not structure.get('lh') and zones.get('nearest_demand'):
                demand = zones['nearest_demand']
                distance_pct = abs(demand['distance_pct'])

                if distance_pct <= 0.25:  # Muy selectivo
                    signal = 'CALL'
                    confidence = 60
                    reasons.append("Reversión alcista desde demand zone")
                    reasons.append(f"Soporte en ${demand['level']:.2f}")

            # Reversión bajista solo si tocamos supply Y no hay HH reciente
            elif not structure.get('hh') and zones.get('nearest_supply'):
                supply = zones['nearest_supply']
                distance_pct = supply['distance_pct']

                if distance_pct <= 0.25:  # Muy selectivo
                    signal = 'PUT'
                    confidence = 60
                    reasons.append("Reversión bajista desde supply zone")
                    reasons.append(f"Resistencia en ${supply['level']:.2f}")

        # Penalizar si hay desalineación de timeframes
        if fractal_alignment and fractal_alignment.get('confidence_boost', 0) < 0:
            confidence = max(0, confidence - 20)  # -20% confianza
            reasons.append("⚠ Señal débil: timeframes desalineados")

        # Requisito mínimo: solo operar si confianza >= 60
        if signal and confidence < 60:
            signal = None
            confidence = 0
            reasons.append("Confianza insuficiente (< 60%)")

        if not signal:
            confidence = 0
            reasons.append("No se cumplen condiciones PCR completa")

        return {
            'signal': signal,
            'confidence': confidence,
            'reasons': reasons
        }

    def get_entry_time(self, timeframe='1m'):
        """Retorna tiempo recomendado de entrada"""
        # PCR completa: espera confirmación
        time_map = {
            '1m': 120,     # 2 minutos (espera retest confirmado)
            '5m': 300,     # 5 minutos
            '15m': 900,    # 15 minutos
        }
        return time_map.get(timeframe, 120)

    def get_expiry_time(self, timeframe='1m'):
        """Retorna tiempo recomendado de expiración"""
        # PCR completa: largo plazo (espera movimiento estructurado)
        time_map = {
            '1m': 300,     # 5 minutos
            '5m': 900,     # 15 minutos
            '15m': 1800,   # 30 minutos
        }
        return time_map.get(timeframe, 300)
