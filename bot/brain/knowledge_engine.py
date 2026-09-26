"""
🧠 KNOWLEDGE ENGINE — Estrategias reales de trading + parámetros refinados
═══════════════════════════════════════════════════════════════════════════════

Integra:
  - Estrategias reales de opciones binarias (Price Action, SMC, ICT)
  - Parámetros específicos por activo/temporalidad
  - Análisis profundo: estructura de mercado, liquidez, orden blocks
  - Pattern recognition: rally/drop, FVG, inducement
  - Gestión de riesgo profesional

Este módulo alimenta el Cerebro Autónomo con conocimiento real.
═══════════════════════════════════════════════════════════════════════════════
"""

import json
from typing import Dict, List, Tuple, Optional
from enum import Enum
from dataclasses import dataclass
import logging

log = logging.getLogger("KnowledgeEngine")


# ═══════════════════════════════════════════════════════════════════════════════
# ESTRATEGIAS REALES DE OPCIONES BINARIAS
# ═══════════════════════════════════════════════════════════════════════════════

class TradingStrategy(Enum):
    """Estrategias de trading implementadas"""
    BREAKOUT_FVG = "Breakout después de Fair Value Gap"
    LIQUIDITY_SWEEP = "Barrido de liquidez (EH/EL)"
    IMPULSE_RETRACE = "Impulso + retroceso (61.8% Fibo)"
    ORDER_BLOCK = "Orden block con confirmación"
    BOS_CHOCH = "Break of Structure + Change of Character"
    REJECTION_CANDLE = "Vela de rechazo en soporte/resistencia"
    MOVING_AVERAGE_CROSS = "Cruce de medias (21/55)"
    VOLATILITY_BREAKOUT = "Breakout de volatilidad (Bollinger)"
    RSI_DIVERGENCE = "Divergencia alcista/bajista en RSI"
    PRICE_ACTION_PIN = "Pin bar en nivel clave"


class MarketRegime(Enum):
    """Regímenes de mercado"""
    STRONG_UPTREND = "Tendencia alcista fuerte (mínimos crecientes)"
    STRONG_DOWNTREND = "Tendencia bajista fuerte (máximos decrecientes)"
    CONSOLIDATION = "Consolidación (lateralidad)"
    RECOVERY = "Recuperación después de caída"
    DISTRIBUTION = "Distribución antes de caída"
    ACCUMULATION = "Acumulación antes de subida"


@dataclass
class StrategyRule:
    """Regla de estrategia con parámetros específicos"""
    strategy: TradingStrategy
    entry_condition: str
    exit_tp_pct: float  # Take Profit en %
    exit_sl_pct: float  # Stop Loss en %
    min_confidence: float  # Confianza mínima para tradear
    timeframe: str  # 30s, 1m, 5m, etc
    max_spread: float  # Spread máximo permitido
    optimal_hour_start: Optional[int] = None  # Hora óptima inicio (UTC)
    optimal_hour_end: Optional[int] = None    # Hora óptima fin (UTC)

    def to_dict(self) -> Dict:
        return {
            'strategy': self.strategy.value,
            'entry_condition': self.entry_condition,
            'tp_pct': self.exit_tp_pct,
            'sl_pct': self.exit_sl_pct,
            'min_confidence': self.min_confidence,
            'timeframe': self.timeframe,
            'max_spread': self.max_spread
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PARÁMETROS REFINADOS POR ACTIVO/TEMPORALIDAD
# ═══════════════════════════════════════════════════════════════════════════════

class AssetParameters:
    """Parámetros optimizados para cada activo"""

    # EUR/USD - Activo más predecible
    EURUSD = {
        'volatility_typical': 0.001,
        'spread_typical': 0.0002,
        'best_session': 'LONDON',  # 08:00-11:00 UTC
        'best_hours': [8, 9, 10],
        'avoid_hours': [22, 23, 0, 1],  # Bajo volumen
        'optimal_timeframe': '1m',
        'price_step': 0.0001,
        'grid_distance': 0.005,  # Distancia mínima entre órdenes
        'momentum_threshold_strong': 0.65,
        'momentum_threshold_weak': 0.35,
        'rsi_overbought': 70,
        'rsi_oversold': 30,
        'atr_period': 14
    },

    # Gold - Alto riesgo/recompensa
    GOLD = {
        'volatility_typical': 0.005,
        'spread_typical': 0.01,
        'best_session': 'NEWYORK',  # 13:30-16:30 UTC
        'best_hours': [14, 15, 16],
        'avoid_hours': [22, 23, 0, 1, 2, 3],
        'optimal_timeframe': '5m',
        'price_step': 0.01,
        'grid_distance': 0.50,
        'momentum_threshold_strong': 0.70,
        'momentum_threshold_weak': 0.40,
        'rsi_overbought': 75,
        'rsi_oversold': 25,
        'atr_period': 14
    },

    # BTCUSD - Crypto volatilidad
    BTCUSD = {
        'volatility_typical': 0.02,
        'spread_typical': 1.0,
        'best_session': 'ASIAN',  # Cualquier hora
        'best_hours': list(range(24)),
        'avoid_hours': [],
        'optimal_timeframe': '5m',
        'price_step': 1.0,
        'grid_distance': 500,
        'momentum_threshold_strong': 0.60,
        'momentum_threshold_weak': 0.30,
        'rsi_overbought': 65,
        'rsi_oversold': 35,
        'atr_period': 14
    }
}


class TimeframeParameters:
    """Parámetros por temporalidad"""

    # 30 segundos - Alta frecuencia, muy dinámico
    PARAM_30S = {
        'lookback_candles': 8,
        'min_candles_for_trend': 3,
        'rsi_period': 5,
        'ema_fast': 3,
        'ema_slow': 8,
        'atr_multiplier_tp': 1.5,
        'atr_multiplier_sl': 1.0,
        'min_hl_distance': 0.002,  # Min high-low para vela válida
        'max_trades_per_hour': 30,
        'confidence_multiplier': 0.8  # Reduce confianza por volatilidad
    },

    # 1 minuto - Intraday estándar
    PARAM_1M = {
        'lookback_candles': 20,
        'min_candles_for_trend': 5,
        'rsi_period': 14,
        'ema_fast': 5,
        'ema_slow': 13,
        'atr_multiplier_tp': 2.0,
        'atr_multiplier_sl': 1.5,
        'min_hl_distance': 0.0005,
        'max_trades_per_hour': 15,
        'confidence_multiplier': 1.0
    },

    # 5 minutos - Estable, confiable
    PARAM_5M = {
        'lookback_candles': 50,
        'min_candles_for_trend': 8,
        'rsi_period': 14,
        'ema_fast': 8,
        'ema_slow': 21,
        'atr_multiplier_tp': 2.5,
        'atr_multiplier_sl': 1.5,
        'min_hl_distance': 0.0003,
        'max_trades_per_hour': 8,
        'confidence_multiplier': 1.2  # Aumenta confianza por estabilidad
    }
}


# ═══════════════════════════════════════════════════════════════════════════════
# PATRONES Y SEÑALES REALES
# ═══════════════════════════════════════════════════════════════════════════════

class MarketStructureAnalyzer:
    """Analiza estructura real del mercado (Price Action)"""

    @staticmethod
    def detect_fvg(highs: List[float], lows: List[float]) -> Dict:
        """
        Detecta Fair Value Gap (brecha sin llenar)
        - Importante para entradas en breakout
        """
        if len(highs) < 3:
            return {'found': False}

        # FVG bajista: close_candle2 < low_candle1 (brecha entre candle 3 y 1)
        if len(lows) >= 3 and lows[-2] < highs[-3]:
            return {
                'found': True,
                'type': 'BEARISH',
                'top': highs[-3],
                'bottom': lows[-2],
                'size_pips': abs(highs[-3] - lows[-2]),
                'signal': 'BREAKOUT_DOWN_POSIBLE'
            }

        # FVG alcista: open_candle2 > high_candle1
        if len(highs) >= 3 and highs[-2] > lows[-3]:
            return {
                'found': True,
                'type': 'BULLISH',
                'bottom': lows[-3],
                'top': highs[-2],
                'size_pips': abs(highs[-2] - lows[-3]),
                'signal': 'BREAKOUT_UP_POSIBLE'
            }

        return {'found': False}

    @staticmethod
    def detect_order_block(highs: List[float], lows: List[float], closes: List[float]) -> Dict:
        """
        Detecta Order Block (zona donde institucionistas entraron)
        - Rechazo de precio en esta zona = buena entrada
        """
        if len(highs) < 4:
            return {'found': False}

        # Order block: candle fuerte, luego reversal
        last_high_range = highs[-2] - lows[-2]
        curr_range = highs[-1] - lows[-1]

        # Si último rango grande y actuales baja: posible OB
        if last_high_range > curr_range * 2:
            return {
                'found': True,
                'level_high': highs[-2],
                'level_low': lows[-2],
                'type': 'POTENTIAL_REVERSAL',
                'strength': 0.7
            }

        return {'found': False}

    @staticmethod
    def detect_bos_choch(highs: List[float], lows: List[float]) -> Dict:
        """
        Detecta Break of Structure + Change of Character
        - Cambio en tendencia principal
        """
        if len(highs) < 5:
            return {'found': False}

        # Buscar secuencia: HH,HL,LL (downtrend → uptrend)
        hh_detected = highs[-2] > highs[-4]
        hl_detected = lows[-3] > lows[-5]

        if hh_detected and hl_detected:
            return {
                'found': True,
                'type': 'BULLISH_CHOCH',
                'signal': 'ESTRUCTURA_CAMBIO_A_ALCISTA'
            }

        # LL, LH, HH (uptrend → downtrend)
        ll_detected = lows[-2] < lows[-4]
        lh_detected = highs[-3] < highs[-5]

        if ll_detected and lh_detected:
            return {
                'found': True,
                'type': 'BEARISH_CHOCH',
                'signal': 'ESTRUCTURA_CAMBIO_A_BAJISTA'
            }

        return {'found': False}


class CandlePatternRecognizer:
    """Reconoce patrones de velas reales"""

    @staticmethod
    def detect_pin_bar(open_: float, high: float, low: float, close: float) -> Dict:
        """
        Pin bar: rechazo de precio (mecha larga, cuerpo pequeño)
        - Reversal signal en niveles clave
        """
        range_ = high - low
        body = abs(close - open_)
        lower_wick = min(open_, close) - low
        upper_wick = high - max(open_, close)

        # Pin bar alcista: más mecha abajo
        if lower_wick > range_ * 0.6 and body < range_ * 0.3:
            return {
                'found': True,
                'type': 'BULLISH_PIN',
                'strength': min(1.0, lower_wick / range_),
                'interpretation': 'Rechazo alcista, comprador puede entrar'
            }

        # Pin bar bajista: más mecha arriba
        if upper_wick > range_ * 0.6 and body < range_ * 0.3:
            return {
                'found': True,
                'type': 'BEARISH_PIN',
                'strength': min(1.0, upper_wick / range_),
                'interpretation': 'Rechazo bajista, vendedor puede entrar'
            }

        return {'found': False}

    @staticmethod
    def detect_engulfing(prev_open: float, prev_high: float, prev_low: float, prev_close: float,
                        curr_open: float, curr_high: float, curr_low: float, curr_close: float) -> Dict:
        """
        Engulfing: vela actual envuelve la anterior
        - Reversal signal potente
        """
        # Alcista: close > prev_high Y open < prev_low
        if curr_close > prev_high and curr_open < prev_low:
            return {
                'found': True,
                'type': 'BULLISH_ENGULFING',
                'strength': min(1.0, (curr_close - prev_high) / (prev_high - prev_low)),
                'interpretation': 'Reversión alcista confirmada'
            }

        # Bajista
        if curr_close < prev_low and curr_open > prev_high:
            return {
                'found': True,
                'type': 'BEARISH_ENGULFING',
                'strength': min(1.0, (prev_low - curr_close) / (prev_high - prev_low)),
                'interpretation': 'Reversión bajista confirmada'
            }

        return {'found': False}


# ═══════════════════════════════════════════════════════════════════════════════
# MOTOR DE REGLAS DE ENTRADA
# ═══════════════════════════════════════════════════════════════════════════════

class EntryRuleEngine:
    """Genera reglas de entrada basadas en patrón actual + historial"""

    def __init__(self):
        self.strategies: Dict[str, StrategyRule] = {
            'breakout_fvg': StrategyRule(
                strategy=TradingStrategy.BREAKOUT_FVG,
                entry_condition="Price break above/below FVG + confirmación de vela",
                exit_tp_pct=2.0,
                exit_sl_pct=-1.0,
                min_confidence=0.65,
                timeframe='1m',
                max_spread=0.0005
            ),
            'liquidity_sweep': StrategyRule(
                strategy=TradingStrategy.LIQUIDITY_SWEEP,
                entry_condition="Barrido EH/EL + retorno rápido",
                exit_tp_pct=1.5,
                exit_sl_pct=-0.8,
                min_confidence=0.70,
                timeframe='5m',
                max_spread=0.0003
            ),
            'order_block': StrategyRule(
                strategy=TradingStrategy.ORDER_BLOCK,
                entry_condition="Rechazo en OB confirmado + vela pin bar",
                exit_tp_pct=2.5,
                exit_sl_pct=-1.2,
                min_confidence=0.75,
                timeframe='5m',
                max_spread=0.0003
            ),
            'rsi_divergence': StrategyRule(
                strategy=TradingStrategy.RSI_DIVERGENCE,
                entry_condition="Divergencia RSI + confirmación de estructura",
                exit_tp_pct=2.0,
                exit_sl_pct=-1.0,
                min_confidence=0.60,
                timeframe='5m',
                max_spread=0.0005
            )
        }

    def get_applicable_strategies(self, market_analysis: Dict) -> List[StrategyRule]:
        """
        Retorna estrategias aplicables basadas en análisis actual
        """
        applicable = []

        # Si detectó FVG
        if market_analysis.get('fvg', {}).get('found'):
            applicable.append(self.strategies['breakout_fvg'])

        # Si detectó Order Block
        if market_analysis.get('order_block', {}).get('found'):
            applicable.append(self.strategies['order_block'])

        # Si hay divergencia
        if market_analysis.get('rsi_divergence', {}).get('found'):
            applicable.append(self.strategies['rsi_divergence'])

        # Ordenar por confianza
        applicable.sort(key=lambda x: x.min_confidence, reverse=True)

        return applicable


# ═══════════════════════════════════════════════════════════════════════════════
# CONOCIMIENTO INTEGRADO EN EL CEREBRO
# ═══════════════════════════════════════════════════════════════════════════════

class KnowledgeBase:
    """Integra todo el conocimiento en una base centralizada"""

    def __init__(self):
        self.market_structure = MarketStructureAnalyzer()
        self.candle_patterns = CandlePatternRecognizer()
        self.entry_rules = EntryRuleEngine()
        log.info("[KnowledgeBase] ✅ Base de conocimiento inicializada")

    def analyze_market_deeply(self, price_data: Dict) -> Dict:
        """
        Análisis profundo del mercado con TODAS las herramientas

        Entrada:
          - opens, highs, lows, closes: list[float]
          - rsi, atr, ema_fast, ema_slow: float
          - volume: float
        """

        analysis = {
            'timestamp': price_data.get('timestamp'),
            'price': price_data.get('price', 0),
            'structures': {},
            'patterns': {},
            'strategies': [],
            'confidence_boost': 0
        }

        try:
            # Estructura del mercado
            fvg = self.market_structure.detect_fvg(
                price_data.get('highs', []),
                price_data.get('lows', [])
            )
            analysis['structures']['fvg'] = fvg
            if fvg.get('found'):
                analysis['confidence_boost'] += 0.10

            ob = self.market_structure.detect_order_block(
                price_data.get('highs', []),
                price_data.get('lows', []),
                price_data.get('closes', [])
            )
            analysis['structures']['order_block'] = ob
            if ob.get('found'):
                analysis['confidence_boost'] += 0.15

            choch = self.market_structure.detect_bos_choch(
                price_data.get('highs', []),
                price_data.get('lows', [])
            )
            analysis['structures']['choch'] = choch
            if choch.get('found'):
                analysis['confidence_boost'] += 0.20

            # Patrones de velas
            if len(price_data.get('opens', [])) > 0:
                pin = self.candle_patterns.detect_pin_bar(
                    price_data['opens'][-1],
                    price_data['highs'][-1],
                    price_data['lows'][-1],
                    price_data['closes'][-1]
                )
                analysis['patterns']['pin_bar'] = pin
                if pin.get('found'):
                    analysis['confidence_boost'] += 0.12

            # Estrategias aplicables
            strategies = self.entry_rules.get_applicable_strategies(analysis)
            analysis['strategies'] = [s.to_dict() for s in strategies]

            log.info(f"[KnowledgeBase] Análisis: {len(strategies)} estrategias aplicables, "
                    f"boost={analysis['confidence_boost']:.2f}")

        except Exception as e:
            log.error(f"[KnowledgeBase] Error en análisis: {e}")

        return analysis


if __name__ == "__main__":
    # Test
    kb = KnowledgeBase()

    # Datos simulados
    test_data = {
        'timestamp': '2026-09-26T10:30:00Z',
        'price': 1.2350,
        'opens': [1.2300, 1.2320, 1.2340],
        'highs': [1.2340, 1.2350, 1.2360],
        'lows': [1.2290, 1.2310, 1.2330],
        'closes': [1.2330, 1.2345, 1.2355],
        'rsi': 65,
        'atr': 0.0025,
        'volume': 150
    }

    analysis = kb.analyze_market_deeply(test_data)

    print("\n" + "="*70)
    print("ANÁLISIS PROFUNDO DEL MERCADO")
    print("="*70)
    print(json.dumps(analysis, indent=2, ensure_ascii=False))
