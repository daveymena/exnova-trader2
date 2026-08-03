"""
Estrategia PCR Simple - Price Action basada en Zonas S/D + EMA 20
Versión simplificada para validar concepto rápidamente
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class PCRSimple:
    """
    PCR Simple: Zonas Supply/Demand + EMA 20
    - Identifica zonas donde precio ha rebotado múltiples veces
    - EMA 20 como contexto de tendencia
    - Entradas simples en reversiones desde zonas
    """

    def __init__(self, ema_period=20, zone_lookback=50, zone_tolerance=0.002, min_touches=2):
        """
        Args:
            ema_period: Período para EMA (default 20)
            zone_lookback: Velas a analizar para zonas (default 50)
            zone_tolerance: Tolerancia para agrupar zonas (%): 0.2%
            min_touches: Mínimo de toques para considerar una zona válida (default 2)
        """
        self.ema_period = ema_period
        self.zone_lookback = zone_lookback
        self.zone_tolerance = zone_tolerance
        self.min_touches = min_touches

    def analyze(self, df, asset_name=None):
        """
        Análisis completo PCR Simple

        Args:
            df: DataFrame con OHLCV
            asset_name: Nombre del activo (para debugging)

        Returns:
            dict con análisis y recomendación
        """
        if df is None or df.empty or len(df) < self.ema_period + 10:
            return {
                'signal': None,
                'confidence': 0,
                'reasons': ['Datos insuficientes'],
                'supply_zones': [],
                'demand_zones': [],
                'ema20': None,
                'trend': None
            }

        result = {
            'timestamp': df.iloc[-1]['timestamp'] if 'timestamp' in df.columns else None,
            'close': float(df.iloc[-1]['close']),
            'signal': None,
            'confidence': 0,
            'reasons': [],
            'supply_zones': [],
            'demand_zones': [],
            'ema20': None,
            'trend': None,
            'zone_analysis': None
        }

        # Calcular EMA 20
        ema20 = self._calculate_ema(df, self.ema_period)
        if ema20 is None or len(ema20) == 0:
            return result

        result['ema20'] = float(ema20.iloc[-1])
        current_price = float(df.iloc[-1]['close'])

        # Determinar tendencia respecto a EMA 20
        result['trend'] = 'UP' if current_price > result['ema20'] else 'DOWN'

        # Detectar zonas Supply/Demand
        supply_zones = self._detect_supply_zones(df)
        demand_zones = self._detect_demand_zones(df)

        result['supply_zones'] = supply_zones
        result['demand_zones'] = demand_zones

        # Generar señal
        signal_data = self._generate_signal(
            df, current_price, result['ema20'], result['trend'],
            supply_zones, demand_zones
        )

        result['signal'] = signal_data['signal']
        result['confidence'] = signal_data['confidence']
        result['reasons'] = signal_data['reasons']
        result['zone_analysis'] = signal_data.get('zone_analysis', None)

        return result

    def _calculate_ema(self, df, period):
        """Calcula EMA"""
        if len(df) < period:
            return None
        try:
            return df['close'].ewm(span=period, adjust=False).mean()
        except:
            return None

    def _detect_supply_zones(self, df, lookback=None):
        """
        Detecta zonas de SUPPLY (resistencia)
        Máximos donde el precio ha rebotado múltiples veces hacia abajo
        """
        if lookback is None:
            lookback = self.zone_lookback

        if len(df) < lookback:
            lookback = len(df)

        recent = df.tail(lookback).copy()
        zones = []

        if len(recent) < 5:
            return zones

        # Encontrar máximos locales
        highs = recent['high'].values

        # Identificar picos (máximos locales)
        for i in range(1, len(highs) - 1):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                # Es un pico, revisar si hay múltiples toques
                price_level = highs[i]

                # Contar toques (velas que tocaron esta zona +/- tolerancia)
                touches = 0
                for j, h in enumerate(highs):
                    if abs(h - price_level) / price_level <= self.zone_tolerance:
                        touches += 1

                if touches >= self.min_touches:
                    # Verificar que no sea duplicado
                    is_duplicate = False
                    for zone in zones:
                        if abs(zone['level'] - price_level) / price_level <= self.zone_tolerance:
                            is_duplicate = True
                            zone['touches'] += 1
                            break

                    if not is_duplicate:
                        zones.append({
                            'level': price_level,
                            'touches': touches,
                            'type': 'supply',
                            'strength': 'strong' if touches >= 3 else 'medium'
                        })

        # Ordenar por fortaleza (toques)
        zones = sorted(zones, key=lambda x: x['touches'], reverse=True)
        return zones[:3]  # Top 3 zonas

    def _detect_demand_zones(self, df, lookback=None):
        """
        Detecta zonas de DEMAND (soporte)
        Mínimos donde el precio ha rebotado múltiples veces hacia arriba
        """
        if lookback is None:
            lookback = self.zone_lookback

        if len(df) < lookback:
            lookback = len(df)

        recent = df.tail(lookback).copy()
        zones = []

        if len(recent) < 5:
            return zones

        # Encontrar mínimos locales
        lows = recent['low'].values

        # Identificar valles (mínimos locales)
        for i in range(1, len(lows) - 1):
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                # Es un valle, revisar si hay múltiples toques
                price_level = lows[i]

                # Contar toques
                touches = 0
                for j, l in enumerate(lows):
                    if abs(l - price_level) / price_level <= self.zone_tolerance:
                        touches += 1

                if touches >= self.min_touches:
                    # Verificar que no sea duplicado
                    is_duplicate = False
                    for zone in zones:
                        if abs(zone['level'] - price_level) / price_level <= self.zone_tolerance:
                            is_duplicate = True
                            zone['touches'] += 1
                            break

                    if not is_duplicate:
                        zones.append({
                            'level': price_level,
                            'touches': touches,
                            'type': 'demand',
                            'strength': 'strong' if touches >= 3 else 'medium'
                        })

        # Ordenar por fortaleza (toques)
        zones = sorted(zones, key=lambda x: x['touches'], reverse=True)
        return zones[:3]  # Top 3 zonas

    def _generate_signal(self, df, current_price, ema20, trend, supply_zones, demand_zones):
        """Genera señal de trading basada en acción del precio y zonas"""
        signal = None
        confidence = 0
        reasons = []
        zone_analysis = None

        # Si estamos en tendencia UP y tocamos demand zone -> CALL
        if trend == 'UP' and demand_zones:
            closest_demand = demand_zones[0]
            distance_to_demand = abs(current_price - closest_demand['level']) / current_price

            # Si estamos cerca de la demand zone (dentro del 0.3%)
            if distance_to_demand <= 0.003:
                signal = 'CALL'
                confidence = 65 if closest_demand['strength'] == 'strong' else 55
                reasons.append(f"Precio toca zona demand fuerte en ${closest_demand['level']:.2f}")
                reasons.append(f"Tendencia alcista (precio > EMA20)")
                zone_analysis = {
                    'zone_type': 'demand',
                    'zone_level': closest_demand['level'],
                    'distance_pct': distance_to_demand * 100,
                    'zone_strength': closest_demand['strength'],
                    'touches': closest_demand['touches']
                }

        # Si estamos en tendencia DOWN y tocamos supply zone -> PUT
        if trend == 'DOWN' and supply_zones:
            closest_supply = supply_zones[0]
            distance_to_supply = abs(current_price - closest_supply['level']) / current_price

            # Si estamos cerca de la supply zone (dentro del 0.3%)
            if distance_to_supply <= 0.003:
                signal = 'PUT'
                confidence = 65 if closest_supply['strength'] == 'strong' else 55
                reasons.append(f"Precio toca zona supply fuerte en ${closest_supply['level']:.2f}")
                reasons.append(f"Tendencia bajista (precio < EMA20)")
                zone_analysis = {
                    'zone_type': 'supply',
                    'zone_level': closest_supply['level'],
                    'distance_pct': distance_to_supply * 100,
                    'zone_strength': closest_supply['strength'],
                    'touches': closest_supply['touches']
                }

        # Si hay ambigüedad o no tocamos zonas, NO hacer trade
        if not signal:
            reasons.append("No se cumplen condiciones PCR: precio lejos de zonas o sin contexto claro")
            confidence = 0

        return {
            'signal': signal,
            'confidence': confidence,
            'reasons': reasons,
            'zone_analysis': zone_analysis
        }

    def get_entry_time(self, timeframe='1m'):
        """Retorna tiempo recomendado de entrada"""
        # PCR simple entra rápidamente tras detectar toque de zona
        time_map = {
            '1m': 60,      # 1 minuto
            '5m': 300,     # 5 minutos
            '15m': 900,    # 15 minutos
        }
        return time_map.get(timeframe, 60)

    def get_expiry_time(self, timeframe='1m'):
        """Retorna tiempo recomendado de expiración"""
        # PCR simple: medio plazo (busca retest rápido de la zona)
        time_map = {
            '1m': 180,     # 3 minutos
            '5m': 600,     # 10 minutos
            '15m': 1800,   # 30 minutos
        }
        return time_map.get(timeframe, 180)
