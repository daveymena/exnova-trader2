# -*- coding: utf-8 -*-
"""Agente de senales: evalua TODAS las estrategias y las ordena.

EL PROBLEMA QUE RESUELVE
------------------------
La version anterior hacia esto:

    for name, strategy in self.strategies.items():
        signal = strategy.evaluate(...)
        if signal["direction"] == Direction.NO_TRADE:
            continue
        ...
        return {...}          # <- la PRIMERA que dispara

Dos consecuencias malas, medidas sobre 1500 ciclos de mercado simulado:

  1. `sr_bounce` disparaba en el 48.7% de los minutos y `breakout_direct` en
     el 29.9%. Como el bucle devolvia la primera, las cinco estrategias
     restantes casi nunca llegaban a evaluarse en el motor. No se puede medir
     lo que nunca se selecciona: el sistema era incapaz de comparar A vs B vs C,
     que es literalmente lo que pide `AGENTS.md` ("El sistema actua como un
     laboratorio: compara Estrategia A vs B vs C continuamente").

  2. `self.strategies` se construia con un `if practice else` que cambiaba los
     parametros segun el modo (`min_confidence` 0.40 en practice, 0.65 en real;
     `level_distance_atr` 2.5 vs 2.0). Es decir: el sistema que acumulaba
     estadisticas en practice NO ERA el sistema que operaria en real. Todo lo
     aprendido era intransferible.

AHORA
-----
`scan_all()` evalua todas las estrategias del registro y devuelve una lista de
candidatos ordenados por valor esperado, cada uno con su timing, su expiracion,
su validacion de edge y su aprobacion de riesgo ya calculadas. El motor recorre
la lista en orden y opera el primero que pase todos los vetos.

Ademas el motor registra la SENAL SOMBRA de cada candidato (ver
`TradingEngine._record_shadows`): su resultado se mide contra precios reales
aunque no se llegue a operar. Eso resuelve la circularidad del arranque en frio
-- todas las estrategias acumulan muestra en paralelo desde el primer minuto,
sin necesidad de operarlas todas.

ORDEN DE LOS CANDIDATOS
-----------------------
Primero los setups en PRODUCCION (edge demostrado), luego por confianza. El
orden es deliberadamente conservador: si hay una oportunidad con edge probado,
se prefiere sobre una con confianza alta pero sin muestra. `confidence` es la
opinion de la estrategia; el estado del setup es evidencia.

CAUSALIDAD
----------
Las velas que llegan aqui ya vienen filtradas por `MarketFeed.candles()`: solo
velas cerradas respecto a `feed.now()`. El agente no consulta el reloj ni pide
datos por su cuenta, asi que no puede introducir look-ahead aunque se use en un
backtest.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional, Sequence

from app.agents.edge_validator_agent import EdgeValidatorAgent
from app.agents.entry_timing_agent import EntryTimingAgent
from app.agents.expiry_selector import ExpirySelector
from app.agents.market_regime_agent import MarketRegimeAgent
from app.agents.multi_timeframe_agent import MultiTimeframeAgent
from app.config import config
from app.data.schemas import (
    Candle, Direction, EntryTiming, MarketRegime, SetupKey, SetupState, Timeframe,
)
from app.research.setup_evaluator import SetupEvaluator
from app.strategies.registry import StrategyRegistry

logger = logging.getLogger(__name__)


class SignalAgent:
    """Orquesta regimen, multi-temporalidad, estrategias y gates."""

    def __init__(self, registry: Optional[StrategyRegistry] = None,
                 setup_evaluator: Optional[SetupEvaluator] = None,
                 edge_validator: Optional[EdgeValidatorAgent] = None,
                 entry_timing: Optional[EntryTimingAgent] = None,
                 expiry_selector: Optional[ExpirySelector] = None,
                 regime_agent: Optional[MarketRegimeAgent] = None,
                 mtf_agent: Optional[MultiTimeframeAgent] = None,
                 persist: bool = True):
        """`persist=False` para backtest: ni el clasificador de regimen ni el
        multi-temporalidad deben escribir miles de filas por corrida de
        backtest en las tablas de vivo. Contaminarian el historial real con
        datos sinteticos y harian el backtest orders-of-magnitude mas lento."""
        self.registry = registry or StrategyRegistry()
        self.setups = setup_evaluator
        self.edge_validator = edge_validator or EdgeValidatorAgent()
        self.entry_timing = entry_timing or EntryTimingAgent()
        self.expiry_selector = expiry_selector or ExpirySelector(persist=persist)
        self.regime_agent = regime_agent or MarketRegimeAgent(persist=persist)
        self.mtf_agent = mtf_agent or MultiTimeframeAgent(persist=persist)
        self.persist = persist

    # ── escaneo completo ──────────────────────────────────────────────────

    def scan_all(self, candles_m15: Sequence[Candle], candles_m5: Sequence[Candle],
                 candles_m1: Sequence[Candle], asset: str = "",
                 account_equity: float = 10_000.0,
                 timestamp: Optional[datetime] = None,
                 payout: Optional[float] = None,
                 risk_manager=None,
                 forming_m1: Optional[Candle] = None) -> list[dict]:
        """Evalua todas las estrategias y devuelve candidatos ordenados.

        Cada candidato lleva su propia validacion: no se filtra aqui. Quien
        decide es el motor, que puede recorrer la lista y quedarse con el
        primero que pase los vetos -- y registrar los demas como senales
        sombra para que acumulen muestra.
        """
        timestamp = timestamp or datetime.utcnow()
        m15, m5, m1 = list(candles_m15), list(candles_m5), list(candles_m1)
        if len(m15) < 20 or len(m5) < 15 or len(m1) < 8:
            return []

        # Contexto comun a todas las estrategias. Se calcula UNA vez: antes cada
        # estrategia recalculaba su propio regimen, y dos lecturas distintas del
        # mismo mercado en el mismo instante son una fuente de inconsistencia.
        try:
            mtf = self.mtf_agent.analyze(m15, m5, m1, asset, timestamp)
        except Exception as exc:                              # noqa: BLE001
            logger.warning("multi-temporalidad fallo en %s: %s", asset, exc)
            mtf = None

        candidates: list[dict] = []
        for name, strategy in self.registry.strategies().items():
            try:
                signal = strategy.evaluate(m15, m5, m1, asset)
            except Exception as exc:                          # noqa: BLE001
                # Una estrategia que lanza no debe tumbar el ciclo entero: se
                # registra y se sigue con las demas. Pero se cuenta, porque una
                # estrategia que falla siempre deja de producir senales en
                # silencio y nadie se entera si no se mira.
                logger.warning("estrategia %s fallo: %s: %s", name,
                               type(exc).__name__, exc)
                candidates.append(self._failure_candidate(name, asset, timestamp, exc))
                continue

            if not isinstance(signal, dict):
                continue
            signal["strategy_name"] = name
            direction = signal.get("direction", Direction.NO_TRADE)
            if direction == Direction.NO_TRADE:
                continue

            regime = signal.get("market_regime") or MarketRegime.UNKNOWN
            if not isinstance(regime, MarketRegime):
                regime = MarketRegime.UNKNOWN
            confidence = float(signal.get("confidence", 0.0) or 0.0)

            expiries = self.registry.expiries(name)
            expiry_result = self.expiry_selector.select(
                asset, name, direction, regime, confidence,
                payout or config.backtest_min_payout, candidates_expiries=expiries)
            expiry = int(expiry_result["selected_expiry"])
            effective_payout = float(expiry_result.get("payout") or payout or 0.85)

            key = SetupKey(asset, name, direction, regime, expiry)
            setup = self.setups.current(key) if self.setups else None

            edge = self.edge_validator.validate(
                asset, name, direction, regime, expiry, effective_payout,
                confidence=confidence, setup=setup,
                summary=(setup and self._summary_for(setup)) or None)

            if signal.get("skip_entry_timing"):
                timing = {"timing": EntryTiming.ENTER_NOW, "enter_now": True,
                          "rationale": "la estrategia confirmo el timing",
                          "features": {}}
            else:
                try:
                    # La firma real es
                    #   evaluate(m1, m5, direction, entry_zone: float|None, signal_timestamp)
                    # `entry_zone` es un NIVEL DE PRECIO, no un regimen. La
                    # version anterior de esta linea le pasaba `regime` ahi, con
                    # lo que el agente comparaba un enum contra un float.
                    # La vela en formacion se usa SOLO para el timing. Las
                    # estrategias siguen viendo unicamente velas cerradas: la
                    # senal no puede depender de una forma que aun no cerro.
                    # Se pasa la vela en formacion SOLO si ya lleva recorrido.
                    #
                    # Con un ciclo de 60s alineado al minuto -- el caso normal de
                    # un backtest y tambien el de un bot que escanea cada minuto
                    # -- la vela en formacion acaba de abrir y su edad es 0. Si se
                    # entrega asi, el agente dice "esperando confirmacion" SIEMPRE
                    # y no se opera nunca. Pero en el limite de minuto no hay nada
                    # que confirmar: la vela anterior ACABA DE CERRAR y la senal se
                    # genero con velas cerradas. Es el mejor momento para entrar,
                    # no el peor.
                    #
                    # Asi que: si la vela en formacion tiene menos de
                    # `MIN_FORMING_AGE_SEC`, se omite y el agente evalua la ultima
                    # CERRADA, cuya edad es ~100% y cae en el caso
                    # `at_candle_boundary` -> entrada valida.
                    MIN_FORMING_AGE_SEC = 5.0
                    timing_candles = list(m1)
                    if forming_m1 is not None and \
                            (timestamp - forming_m1.open_time).total_seconds() >= MIN_FORMING_AGE_SEC:
                        timing_candles = timing_candles + [forming_m1]
                    zone = None
                    feats = signal.get("features") or {}
                    for key in ("level", "pool_level", "sweep_level", "sr_level"):
                        if isinstance(feats.get(key), (int, float)):
                            zone = float(feats[key])
                            break
                    timing = self.entry_timing.evaluate(timing_candles, m5, direction,
                                                        zone, timestamp)
                except Exception as exc:                      # noqa: BLE001
                    logger.warning("entry_timing fallo en %s: %s", name, exc)
                    timing = {"timing": EntryTiming.NO_TRADE, "enter_now": False,
                              "rationale": f"error de timing: {exc}", "features": {}}

            risk = None
            if risk_manager is not None:
                try:
                    risk = risk_manager.approve(
                        asset, direction, name, regime, confidence, account_equity,
                        payout=effective_payout, edge=edge,
                        setup_state=setup.state if setup else SetupState.EXPLORACION,
                        stake_multiplier=setup.stake_multiplier if setup else 1.0,
                        now=timestamp)
                except Exception as exc:                      # noqa: BLE001
                    logger.warning("risk approve fallo en %s: %s", name, exc)

            candidates.append({
                "asset": asset,
                "timestamp": timestamp.isoformat(),
                "signal": signal,
                "multi_timeframe": self._mtf_dict(mtf),
                "entry_timing": timing,
                "expiry": expiry_result,
                "edge_validation": edge,
                "risk_approval": risk,
                "setup_state": setup.state.value if setup else SetupState.EXPLORACION.value,
                "setup_verdict": setup.verdict.value if setup else "insuficiente",
                "setup_n": setup.n if setup else 0,
                "rank_score": self._rank(edge, confidence, setup),
                "shadow": True,
            })

        # PRODUCCION primero (evidencia), luego valor esperado, luego confianza.
        candidates.sort(key=lambda c: -c["rank_score"])
        return candidates

    # ── compatibilidad con el API anterior ────────────────────────────────

    def scan(self, candles_m15: Sequence[Candle], candles_m5: Sequence[Candle],
             candles_m1: Sequence[Candle], asset: str = "",
             account_equity: float = 10_000.0,
             timestamp: Optional[datetime] = None,
             payout: Optional[float] = None,
             risk_manager=None,
             forming_m1: Optional[Candle] = None) -> dict:
        """Devuelve el MEJOR candidato, o un dict de no-operacion.

        Se conserva porque `app/main.py` heredado y varios scripts lo llaman.
        El motor nuevo usa `scan_all()`.
        """
        candidates = self.scan_all(candles_m15, candles_m5, candles_m1, asset,
                                   account_equity, timestamp, payout, risk_manager,
                                   forming_m1=forming_m1)
        if not candidates:
            return self._no_trade("ninguna estrategia encontro un setup valido",
                                  asset, timestamp)
        return candidates[0]

    # ── internos ──────────────────────────────────────────────────────────

    @staticmethod
    def _rank(edge: dict, confidence: float, setup) -> float:
        """Puntuacion de orden. Documentada porque decide que se opera primero.

        1.000 + expectancy_lower  si el setup tiene edge DEMOSTRADO
        0.500 + confidence*0.4    si esta en exploracion con algo de muestra
        0.100 + confidence*0.3    arranque en frio

        El escalon entre tiers es mayor que cualquier diferencia dentro de un
        tier: la evidencia manda sobre la opinion. Un setup con edge probado y
        expectancy marginal va antes que uno con confianza 0.99 y cero muestra.
        """
        state = setup.state if setup else SetupState.EXPLORACION
        if state == SetupState.PRODUCCION:
            lower = edge.get("expectancy_lower")
            return 1.0 + (lower if isinstance(lower, (int, float)) else 0.0)
        if state == SetupState.EXPLORACION:
            n = setup.n if setup else 0
            if n >= 30:
                return 0.5 + confidence * 0.4
            return 0.1 + confidence * 0.3
        # RETIRADO: no deberia llegar aqui (el validador de edge ya lo veta).
        # Se puntua por debajo de todo para que, si llegara, no se opere.
        return -1.0

    @staticmethod
    def _summary_for(setup) -> Optional[dict]:
        """Resumen compatible con `EdgeValidatorAgent` a partir del SetupRecord.

        Evita una segunda consulta a la base de datos por candidato: el
        evaluador ya tiene n, wins e intervalo calculados.
        """
        if setup is None or not setup.n:
            return None
        return {
            "n": setup.n,
            "wins": setup.wins,
            "losses": setup.n - setup.wins,
            "win_rate": setup.win_rate,
            "win_rate_lower": setup.win_rate_lower,
            "win_rate_upper": setup.win_rate_upper,
            "avg_payout": setup.avg_payout,
            "break_even": setup.break_even,
            "expectancy": setup.expectancy,
            "expectancy_lower": setup.expectancy_lower,
            "profit_factor": None,
        }

    @staticmethod
    def _mtf_dict(mtf) -> dict:
        if mtf is None:
            return {"alignment": "unknown"}
        return {
            "alignment": mtf.alignment,
            "m15_trend": mtf.m15_trend, "m5_trend": mtf.m5_trend,
            "m1_trend": mtf.m1_trend,
            "m15_regime": mtf.m15_regime.value,
            "m5_regime": mtf.m5_regime.value,
            "m1_regime": mtf.m1_regime.value,
        }

    def _failure_candidate(self, name: str, asset: str, timestamp: datetime,
                           exc: Exception) -> dict:
        return {
            "asset": asset, "timestamp": timestamp.isoformat(),
            "signal": {"direction": Direction.NO_TRADE, "strategy_name": name,
                       "confidence": 0.0,
                       "entry_rationale": f"error: {type(exc).__name__}: {exc}"},
            "multi_timeframe": {"alignment": "unknown"},
            "entry_timing": {"enter_now": False, "rationale": "error"},
            "expiry": {"selected_expiry": 0, "reason": "error"},
            "edge_validation": {"approved": False, "reasons": ["estrategia fallo"]},
            "risk_approval": None,
            "setup_state": SetupState.EXPLORACION.value,
            "setup_verdict": "insuficiente", "setup_n": 0,
            "rank_score": -1.0, "shadow": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    def _no_trade(self, reason: str, asset: str = "",
                  timestamp: Optional[datetime] = None) -> dict:
        return {
            "signal": {"direction": Direction.NO_TRADE, "strategy": "no_trade",
                       "strategy_name": "no_trade", "entry_rationale": reason,
                       "confidence": 0.0},
            "multi_timeframe": {"alignment": "unknown"},
            "entry_timing": {"enter_now": False, "rationale": "no_signal",
                             "timing": EntryTiming.NO_TRADE},
            "expiry": {"selected_expiry": 0, "reason": "no_signal"},
            "edge_validation": {"approved": False, "reasons": [reason]},
            "risk_approval": {"decision": "rejected", "reasons": [reason]},
            "asset": asset,
            "timestamp": (timestamp or datetime.utcnow()).isoformat(),
            "rank_score": -1.0,
        }
