"""
🔗 INTEGRATION WRAPPER — Conecta AutonomousCerebro con el motor existente
═══════════════════════════════════════════════════════════════════════════════

Este archivo envuelve el Cerebro Autónomo e integra sus decisiones
con el motor de trading existente sin romper nada.

Flujo:
  1. LiveTrader llama a should_trade()
  2. should_trade() delegá al Cerebro Autónomo
  3. Cerebro analiza con 5 fases
  4. Retorna decisión de alto nivel
  5. Motor ejecuta trade
  6. Resultado se registra en el Cerebro para aprendizaje
═══════════════════════════════════════════════════════════════════════════════
"""

import logging
from typing import Dict, Tuple, Optional
from datetime import datetime
import json

from .autonomous_cerebro import AutonomousCerebro

log = logging.getLogger("IntegrationWrapper")


class CerebroTradingAdapter:
    """
    Adaptador que convierte entre el formato del Cerebro Autónomo
    y el formato esperado por el motor de trading existente.
    """

    def __init__(self, db_path: str = "trading_bot.db"):
        self.cerebro = AutonomousCerebro(db_path=db_path)
        self.last_decision = None
        log.info("[CerebroTradingAdapter] ✅ Adaptador inicializado")

    def convert_market_context(self, legacy_market_data: Dict) -> Dict:
        """
        Convierte formato legacy del motor al formato esperado por Cerebro

        Legacy format (from market_data/analyzer):
          - price: float
          - high: float
          - low: float
          - close: float
          - volume: float
          - indicators: dict
          - ...

        Cerebro format:
          - price: float
          - trend: str (UP/DOWN/RANGE)
          - momentum: float (-1 to 1)
          - volatility: float (0-1)
          - volume: float
          - ...
        """

        try:
            indicators = legacy_market_data.get('indicators', {})

            # Extraer precio
            price = legacy_market_data.get('price') or legacy_market_data.get('close', 0)

            # Determinar trend
            rsi = indicators.get('rsi', 50)
            trend = 'UP' if rsi > 60 else 'DOWN' if rsi < 40 else 'RANGE'

            # Momentum (RSI normalizado)
            momentum = (rsi - 50) / 50  # -1 a 1

            # Volatility (ATR normalizado)
            atr = indicators.get('atr', 0)
            volatility = min(1.0, atr / price) if price > 0 else 0.5

            # Volumen
            volume = legacy_market_data.get('volume', 0)

            # Estructura
            structure = {
                'support': legacy_market_data.get('support', price * 0.99),
                'resistance': legacy_market_data.get('resistance', price * 1.01)
            }

            cerebro_context = {
                'price': price,
                'trend': trend,
                'momentum': momentum,
                'volatility': volatility,
                'volume': volume,
                'structure': structure,
                'indicators': indicators,
                'timestamp': datetime.now().isoformat()
            }

            return cerebro_context

        except Exception as e:
            log.error(f"[CerebroTradingAdapter] Error en conversión: {e}")
            return {
                'price': 0,
                'trend': 'RANGE',
                'momentum': 0,
                'volatility': 0.5,
                'volume': 0
            }

    def should_trade(self, legacy_market_data: Dict) -> Tuple[bool, Dict]:
        """
        Reemplaza la lógica de decision del motor existente

        Retorna: (should_trade: bool, analysis: dict)

        Compatible con:
          - AgentTradingEngine.should_trade()
          - LiveTrader.should_trade()
          - Cualquier motor que espere (bool, dict)
        """

        try:
            # Convertir contexto
            market_context = self.convert_market_context(legacy_market_data)

            # Cerebro analiza
            decision = self.cerebro.analyze_and_decide(market_context)

            # Guardar para logging posterior
            self.last_decision = {
                'decision': decision,
                'market_context': market_context,
                'timestamp': datetime.now().isoformat()
            }

            # Convertir a formato esperado por motor
            should_trade = decision['action'] == 'ENTER'

            analysis = {
                'decision': 'ENTER' if should_trade else 'SKIP',
                'direction': decision.get('direction', 'CALL'),
                'confidence': decision.get('confidence', 0),
                'reasoning': decision.get('reasoning', 'Cerebro autónomo'),
                'score': decision.get('option_score', 0),
                'next_move': decision.get('next_move_prediction', {}).get('direction'),
                'hedge': decision.get('hedge_suggestion'),
                'performance': decision.get('performance_metrics', {}),
                'incoherences_detected': []  # Legacy compatibility
            }

            log.debug(f"[CerebroTradingAdapter] Decision: {analysis['decision']} "
                     f"({analysis['confidence']:.2f})")

            return should_trade, analysis

        except Exception as e:
            log.error(f"[CerebroTradingAdapter] Error en should_trade: {e}")
            return False, {
                'decision': 'SKIP',
                'confidence': 0,
                'reasoning': f'Error en Cerebro: {str(e)}',
                'incoherences_detected': [f'Error: {str(e)}']
            }

    def get_trade_direction(self, legacy_market_data: Dict) -> Tuple[str, float, Dict]:
        """
        Reemplaza AgentTradingEngine.get_trade_direction()

        Retorna: (direction: str, confidence: float, analysis: dict)
        """

        _, analysis = self.should_trade(legacy_market_data)

        direction = analysis.get('direction', 'CALL')
        confidence = analysis.get('confidence', 0.5)

        return direction, confidence, analysis

    def log_trade_result(self, outcome: str, pnl: float, market_context: Optional[Dict] = None):
        """
        Registra resultado del trade en el Cerebro para aprendizaje

        outcome: 'WIN', 'LOSS', 'BREAKEVEN'
        pnl: ganancia/pérdida en dinero
        """

        try:
            if not self.last_decision:
                log.warning("[CerebroTradingAdapter] No hay decisión previa, ignorando resultado")
                return

            decision = self.last_decision['decision']
            ctx = self.last_decision['market_context']

            self.cerebro.log_trade_result(
                decision_id=f"{datetime.now().timestamp()}",
                outcome=outcome,
                pnl=pnl,
                direction=decision.get('direction', 'UNKNOWN'),
                confidence=decision.get('confidence', 0),
                market_context=ctx
            )

            log.info(f"[CerebroTradingAdapter] Trade resultado: {outcome} (PNL=${pnl:.2f})")

        except Exception as e:
            log.error(f"[CerebroTradingAdapter] Error al registrar resultado: {e}")

    def get_cerebro_status(self) -> Dict:
        """Obtiene estado actual del Cerebro"""
        return self.cerebro.get_status()


# ═══════════════════════════════════════════════════════════════════════════════
# PATCHING HELPER — Parcha el motor existente sin modificar archivos originales
# ═══════════════════════════════════════════════════════════════════════════════

_global_adapter = None


def get_or_create_adapter(db_path: str = "trading_bot.db") -> CerebroTradingAdapter:
    """Obtiene o crea el adaptador global"""
    global _global_adapter
    if _global_adapter is None:
        _global_adapter = CerebroTradingAdapter(db_path)
    return _global_adapter


def patch_agent_trading_engine():
    """
    Parcha AgentTradingEngine para usar Cerebro Autónomo
    Esto permite integración SIN modificar el código original
    """
    try:
        from brain.agent_trading_engine import AgentTradingEngine

        # Guardar métodos originales
        original_should_trade = AgentTradingEngine.should_trade
        original_get_direction = AgentTradingEngine.get_trade_direction

        adapter = get_or_create_adapter()

        # Reemplazar métodos
        def patched_should_trade(self, market_context: Dict):
            """Versión parchada que usa Cerebro"""
            try:
                should_trade, analysis = adapter.should_trade(market_context)
                return should_trade, analysis
            except:
                # Fallback al original
                return original_should_trade(self, market_context)

        def patched_get_direction(self, market_context: Dict):
            """Versión parchada que usa Cerebro"""
            try:
                direction, confidence, analysis = adapter.get_trade_direction(market_context)
                return direction, confidence, analysis
            except:
                # Fallback al original
                return original_get_direction(self, market_context)

        # Aplicar patches
        AgentTradingEngine.should_trade = patched_should_trade
        AgentTradingEngine.get_trade_direction = patched_get_direction

        log.info("[Patcher] ✅ AgentTradingEngine parchado con AutonomousCerebro")

        return True

    except Exception as e:
        log.error(f"[Patcher] No se pudo parchear AgentTradingEngine: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# MONITOREO EN TIEMPO REAL — API para dashboard
# ═══════════════════════════════════════════════════════════════════════════════

class CerebroMonitor:
    """Interfaz para monitoreo en tiempo real del Cerebro"""

    def __init__(self, adapter: Optional[CerebroTradingAdapter] = None):
        self.adapter = adapter or get_or_create_adapter()

    def get_live_status(self) -> Dict:
        """Estado en vivo para dashboard"""
        status = self.adapter.get_cerebro_status()

        return {
            'status': status.get('status', 'UNKNOWN'),
            'trades': status.get('trades_total', 0),
            'win_rate': f"{status.get('win_rate', 0):.1%}",
            'pnl': f"${status.get('pnl', 0):.2f}",
            'wins': status.get('wins', 0),
            'losses': status.get('losses', 0),
            'timestamp': datetime.now().isoformat()
        }

    def get_last_decision(self) -> Optional[Dict]:
        """Última decisión tomada"""
        if self.adapter.last_decision:
            return {
                'decision': self.adapter.last_decision['decision'].get('action'),
                'direction': self.adapter.last_decision['decision'].get('direction'),
                'confidence': self.adapter.last_decision['decision'].get('confidence'),
                'timestamp': self.adapter.last_decision['timestamp']
            }
        return None

    def get_5phases_status(self) -> Dict:
        """Estado de cada fase del Cerebro"""
        cerebro = self.adapter.cerebro

        return {
            'fase_1_razonador': {
                'name': cerebro.reasoner.name,
                'status': 'READY'
            },
            'fase_2_memoria': {
                'name': cerebro.memory.name,
                'status': 'READY'
            },
            'fase_3_autonomia': {
                'name': cerebro.improver.name,
                'status': 'READY'
            },
            'fase_4_planificador': {
                'name': cerebro.planner.name,
                'status': 'READY'
            },
            'fase_5_especulador': {
                'name': cerebro.speculator.name,
                'status': 'READY'
            }
        }


if __name__ == "__main__":
    # Test
    adapter = CerebroTradingAdapter()
    monitor = CerebroMonitor(adapter)

    # Simular datos
    market_data = {
        'price': 1.2345,
        'close': 1.2345,
        'volume': 150,
        'indicators': {
            'rsi': 65,
            'atr': 0.0025
        },
        'support': 1.23,
        'resistance': 1.24
    }

    # Test
    should_trade, analysis = adapter.should_trade(market_data)
    print(f"\nShouldTrade: {should_trade}")
    print(f"Analysis: {json.dumps(analysis, indent=2, ensure_ascii=False)}")

    # Simular resultado
    adapter.log_trade_result('WIN', 2.50)

    # Status
    print(f"\nStatus: {json.dumps(monitor.get_live_status(), indent=2, ensure_ascii=False)}")
    print(f"5 Phases: {json.dumps(monitor.get_5phases_status(), indent=2, ensure_ascii=False)}")
