# -*- coding: utf-8 -*-
"""Motor de trading. UN solo camino de codigo para vivo, paper y backtest.

POR QUE UN SOLO MOTOR
---------------------
El proyecto tenia dos implementaciones: `app/main.py` para vivo y
`app/research/backtester.py` para historico. Divergian, y en la copia se colo
el look-ahead del punto 10 de la auditoria (el backtester generaba la senal con
la vela `i` y decidia el resultado con ESA MISMA vela).

Aqui hay una sola clase. La diferencia entre "backtest" y "vivo" no es el
codigo: es el `MarketFeed` que se le enchufa.

    engine = TradingEngine(feed=ReplayFeed(csv), broker=PaperBroker(...))   # backtest
    engine = TradingEngine(feed=SimulatedFeed(...), broker=PaperBroker(...)) # paper
    engine = TradingEngine(feed=BrokerFeed(exnova), broker=ExnovaBroker(...))# practice

Como el motor solo puede ver el mercado a traves de `feed.candles()`, que
unicamente devuelve velas CERRADAS respecto a `feed.now()`, el look-ahead se
vuelve estructuralmente imposible: no hay forma de escribirlo por descuido,
porque la informacion futura no esta al alcance del codigo.

CICLO
-----
  1. Resolver las operaciones vencidas contra EVIDENCIA (precio observado en el
     instante exacto de expiracion, o PnL reportado por el broker).
  2. Actualizar el gestor de riesgo con esos resultados REALES.
  3. Escanear activos: regimen -> multi-temporalidad -> estrategias -> timing
     -> expiracion -> edge -> riesgo.
  4. Si todo aprueba, operar. Si no, registrar el motivo del rechazo (que es
     dato para el motor de mejora: saber por que NO se opera importa tanto
     como saber por que si).

RESOLUCION
----------
Una binaria se liquida comparando el precio de entrada con el precio en un
INSTANTE concreto. Por eso se usa `feed.price_at(asset, expiry_time)` y no "el
cierre de la vela siguiente": con expiraciones de 60/180/300s la vela siguiente
puede no existir o cubrir otro intervalo.

Empate (delta == 0) se trata como REEMBOLSO, no como perdida. Es lo que hace un
broker, y contabilizarlo como derrota sesgaria el win rate a la baja de forma
sistematica.

Si no hay evidencia (el broker no reporta y el feed no tiene precio en ese
instante) la operacion NO se resuelve: se reintenta, y pasado un timeout queda
en `ExecutionState.UNKNOWN` + `resolution_source=UNRESOLVED`, fuera de toda
estadistica. Inventar un resultado para salir del paso es exactamente el bug
que se corrigio aqui.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Sequence

from app.agents.risk_manager_agent import RiskManagerAgent
from app.agents.signal_agent import SignalAgent
from app.config import config
from app.data.feed import MarketFeed, VirtualClock
from app.data.repository import Repository, repository as default_repository
from app.data.schemas import (
    DataSource, Direction, ExecutionState, MarketRegime, ResolutionSource,
    RiskDecision, SetupKey, Timeframe, TradeDecision, TradeResult,
)
from app.research.setup_evaluator import SetupEvaluator
from app.services.broker_base import BrokerBase

logger = logging.getLogger(__name__)


@dataclass
class StepReport:
    """Resultado de un ciclo. Se persiste y se muestra en el dashboard."""
    timestamp: datetime
    asset: str = ""
    scanned: bool = False
    traded: bool = False
    trade: Optional[TradeResult] = None
    resolved: list = field(default_factory=list)
    rejection_stage: str = ""      # no_signal|timing|edge|risk|broker|halted
    rejection_reason: str = ""
    direction: str = "no_trade"
    strategy: str = ""
    confidence: float = 0.0
    regime: str = ""
    setup_state: str = ""
    stake: float = 0.0
    payout: float = 0.0
    candidates: int = 0
    shadows_resolved: int = 0


@dataclass
class EngineStats:
    """Contadores acumulados. El dashboard y los informes leen de aqui."""
    cycles: int = 0
    scans: int = 0
    signals: int = 0
    trades: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    unresolved: int = 0
    rejections: dict = field(default_factory=dict)
    evidence_trades: int = 0
    simulated_trades: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    halted: bool = False

    def reject(self, stage: str, reason: str = ""):
        self.rejections[stage] = self.rejections.get(stage, 0) + 1

    @property
    def resolved_trades(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> Optional[float]:
        n = self.resolved_trades
        return (self.wins / n) if n else None

    @property
    def net_pnl(self) -> float:
        return self.gross_profit - self.gross_loss

    def as_dict(self) -> dict:
        wr = self.win_rate
        return {
            "cycles": self.cycles, "scans": self.scans, "signals": self.signals,
            "trades": self.trades, "wins": self.wins, "losses": self.losses,
            "ties": self.ties, "unresolved": self.unresolved,
            "resolved_trades": self.resolved_trades,
            "win_rate": round(wr, 4) if wr is not None else None,
            "evidence_trades": self.evidence_trades,
            "simulated_trades": self.simulated_trades,
            "gross_profit": round(self.gross_profit, 2),
            "gross_loss": round(self.gross_loss, 2),
            "net_pnl": round(self.net_pnl, 2),
            "rejections": dict(self.rejections),
            "halted": self.halted,
        }


class TradingEngine:
    """Motor unico. Ver el docstring del modulo."""

    #: Cuanto se espera evidencia antes de dar una orden por no resoluble.
    RESOLVE_TIMEOUT_SEC = 900

    def __init__(self, feed: MarketFeed, broker: BrokerBase,
                 signal_agent: Optional[SignalAgent] = None,
                 risk_manager: Optional[RiskManagerAgent] = None,
                 setup_evaluator: Optional[SetupEvaluator] = None,
                 repo: Optional[Repository] = None,
                 assets: Optional[Sequence[str]] = None,
                 persist: bool = True,
                 equity_start: Optional[float] = None,
                 forensics=None,
                 failure_memory=None,
                 learn_every_cycles: int = 500):
        self.feed = feed
        self.broker = broker
        self.repo = repo or default_repository
        self.persist = persist
        self.signal_agent = signal_agent or SignalAgent()
        self.risk_manager = risk_manager or RiskManagerAgent()
        self.setup_evaluator = setup_evaluator or SetupEvaluator(repository=self.repo)
        # APRENDER DE LAS PERDIDAS. `forensics` diagnostica POR QUE se perdio
        # (MAE/MFE + recorrido posterior) y `failure_memory` convierte ese
        # diagnostico en un veto comprobable ANTES de volver a entrar. Sin ellos
        # el motor sabe que un setup pierde, pero no que entrada lo causa, y
        # repite la misma entrada indefinidamente.
        #
        # Se crean perezosamente para que un motor sin ellos (tests, scripts) no
        # cargue nada: son opcionales, no obligatorios.
        self.forensics = forensics
        self.failure_memory = failure_memory
        if self.forensics is None:
            from app.research.loss_forensics import LossForensics
            self.forensics = LossForensics()
        if self.failure_memory is None:
            from app.research.failure_memory import FailureMemory
            self.failure_memory = FailureMemory()
        self.learn_every_cycles = max(50, int(learn_every_cycles))
        self._last_learn_cycle = 0
        self.forensic_reports = 0
        self.vetoes_applied = 0
        self.assets = list(assets) if assets else feed.assets()
        self.stats = EngineStats()
        self.running = False
        self._asset_cursor = 0
        self._daily_key: Optional[tuple] = None
        self._start_equity = equity_start if equity_start is not None else broker.get_equity()
        self._peak_equity = self._start_equity
        self._max_drawdown_pct = 0.0
        self._equity_curve: list[tuple[datetime, float]] = []
        # Observaciones SOMBRA: senales que se miden contra precios reales pero
        # NO se operan. Ver `_record_shadows`.
        self._shadow_open: list[TradeResult] = []
        self.shadow_observations = 0

        if persist:
            self.repo.migrate()

        # El broker hereda la procedencia del feed. Es lo que decide si los
        # trades de este motor cuentan como evidencia: paper sobre CSV real ->
        # evidencia; paper sobre simulador -> no.
        if isinstance(self.broker.data_source, DataSource) and \
                self.broker.data_source != feed.data_source:
            self.broker.data_source = feed.data_source

    # ── propiedades de cuenta ─────────────────────────────────────────────

    @property
    def equity(self) -> float:
        return self.broker.get_equity()

    @property
    def max_drawdown_pct(self) -> float:
        return self._max_drawdown_pct

    @property
    def equity_curve(self) -> list[float]:
        return [v for _, v in self._equity_curve]

    # ── bucle principal ───────────────────────────────────────────────────

    def run(self, cycles: Optional[int] = None,
            seconds_per_cycle: int = 60,
            until: Optional[datetime] = None,
            on_cycle=None) -> EngineStats:
        """Ejecuta el motor.

        `cycles`/`until` acotan la ejecucion (backtest). Sin ellos corre hasta
        `stop()`. `seconds_per_cycle` solo avanza el reloj en feeds virtuales;
        en vivo el reloj es de pared y el ciclo duerme.
        """
        self.running = True
        done = 0
        while self.running:
            if cycles is not None and done >= cycles:
                break
            if until is not None and self.feed.now() >= until:
                break

            report = self.step()
            done += 1
            if on_cycle:
                on_cycle(report)

            if isinstance(self.feed.clock, VirtualClock):
                # Reloj virtual (backtest/replay): el ciclo no duerme, avanza el
                # reloj. Es lo que hace que un backtest de meses corra en segundos.
                self.feed.advance(seconds_per_cycle)
            else:
                # Reloj de pared (vivo): se espera al siguiente minuto de vela.
                # Dormir aqui y no "lo antes posible" es deliberado: escanear
                # mas rapido no produce mas informacion (las velas M1 solo
                # cambian una vez por minuto) y si produce mas decisiones
                # redundantes sobre la misma vela.
                import time as _time
                _time.sleep(max(0.0, float(seconds_per_cycle)))
        self.running = False
        return self.stats

    def stop(self):
        self.running = False

    # ── un ciclo ──────────────────────────────────────────────────────────

    def step(self, asset: Optional[str] = None) -> StepReport:
        now = self.feed.now()
        report = StepReport(timestamp=now)
        self.stats.cycles += 1

        self._roll_daily(now)
        report.resolved = self.resolve_due_trades(now)
        report.shadows_resolved = len(self.resolve_due_shadows(now))

        # APRENDIZAJE PERIODICO, no por operacion. Recalcular cuantiles y
        # Benjamini-Hochberg en cada cierre seria caro y, peor, invitaria a mirar
        # la estadistica demasiado a menudo: con suficientes miradas, cualquier
        # condicion acaba pareciendo significativa. Es la misma razon por la que
        # `SetupEvaluator` decide solo en checkpoints geometricos.
        if (self.stats.cycles - self._last_learn_cycle) >= self.learn_every_cycles:
            self._last_learn_cycle = self.stats.cycles
            try:
                learned = self.failure_memory.learn()
                activados = learned.get("activated") or []
                desactivados = learned.get("deactivated") or []
                if activados or desactivados:
                    logger.warning(
                        "memoria de fallos: %d vetos activados, %d desactivados",
                        len(activados), len(desactivados))
                    for a in activados:
                        logger.warning("  NUEVO VETO %s :: %s (n=%s, tasa %s, "
                                       "base %s, q=%s)",
                                       a["slug"], a["condition"], a["n"],
                                       a.get("loss_rate"), a.get("baseline_loss_rate"),
                                       a.get("q_value"))
            except Exception as exc:                          # noqa: BLE001
                logger.warning("failure_memory.learn fallo: %s", exc)

        # Sin feed no se opera. Ni simulado, ni "de mientras": sin mercado
        # observado no hay nada que analizar.
        if not self.assets:
            report.rejection_stage = "no_feed"
            report.rejection_reason = "sin activos disponibles"
            self.stats.reject("no_feed")
            return report

        target = asset or self.assets[self._asset_cursor % len(self.assets)]
        self._asset_cursor += 1
        report.asset = target

        candidates = self._scan(target, now, report)
        if not candidates:
            return report

        # Se registran SOMBRAS de todos los candidatos antes de operar: si se
        # hiciera despues, el candidato operado quedaria fuera de la sombra y
        # su setup no acumularia la observacion de las otras estrategias.
        self._record_shadows(candidates, now)
        self._process(target, candidates, now, report)
        return report

    def _scan(self, asset: str, now: datetime, report: StepReport) -> Optional[dict]:
        report.scanned = True
        self.stats.scans += 1

        candles = self.feed.candle_set(asset)
        m1, m5, m15 = candles.get(self._tf(1)), candles.get(self._tf(5)), candles.get(self._tf(15))
        if not m1 or not m5 or not m15:
            report.rejection_stage = "no_data"
            report.rejection_reason = (
                f"velas cerradas insuficientes (M1={len(m1 or [])} "
                f"M5={len(m5 or [])} M15={len(m15 or [])})"
            )
            self.stats.reject("no_data")
            return None

        try:
            # La vela en formacion va SOLO al agente de timing. Ver
            # `MarketFeed.forming_candle`: es observable en tiempo real, no es
            # look-ahead, pero las estrategias no deben verla.
            try:
                forming = self.feed.forming_candle(asset, Timeframe.M1)
            except Exception:                                 # noqa: BLE001
                forming = None
            candidates = self.signal_agent.scan_all(
                m15, m5, m1, asset=asset, account_equity=self.equity,
                timestamp=now, payout=self.feed.payout(asset, 180),
                risk_manager=self.risk_manager, forming_m1=forming)
        except Exception as exc:                    # noqa: BLE001
            logger.exception("scan fallo en %s", asset)
            report.rejection_stage = "error"
            report.rejection_reason = f"{type(exc).__name__}: {exc}"
            self.stats.reject("error")
            return None

        candidates = [c for c in candidates if not c.get("error")]
        if not candidates:
            report.rejection_stage = "no_signal"
            report.rejection_reason = "ninguna estrategia encontro un setup valido"
            self.stats.reject("no_signal")
            return None

        self.stats.signals += len(candidates)
        report.candidates = len(candidates)
        best = candidates[0]["signal"]
        report.direction = best["direction"].value
        report.strategy = best.get("strategy_name") or best.get("strategy", "")
        report.confidence = float(best.get("confidence", 0.0))
        regime = best.get("market_regime")
        report.regime = regime.value if isinstance(regime, MarketRegime) else str(regime or "")
        return candidates

    def _process(self, asset: str, candidates: list[dict], now: datetime,
                 report: StepReport) -> None:
        """Recorre los candidatos en orden y opera el primero que pase los vetos.

        El orden lo puso `SignalAgent._rank`: setups con edge DEMOSTRADO antes
        que setups con confianza alta y cero muestra. La evidencia manda sobre
        la opinion.
        """
        last_stage, last_reason = "no_candidate", ""
        for candidate in candidates:
            outcome = self._try_candidate(asset, candidate, now, report)
            if outcome == "traded":
                return
            last_stage, last_reason = outcome
        report.rejection_stage = last_stage
        report.rejection_reason = last_reason
        self.stats.reject(last_stage, last_reason)

    def _try_candidate(self, asset: str, candidate: dict, now: datetime,
                       report: StepReport) -> str | tuple[str, str]:
        """Intenta operar un candidato. "traded" o (etapa, motivo) del veto."""
        signal = candidate["signal"]
        direction = signal["direction"]
        strategy = signal.get("strategy_name") or signal.get("strategy", "")
        regime = signal.get("market_regime") or MarketRegime.UNKNOWN
        confidence = float(signal.get("confidence", 0.0))
        expiry = int(candidate["expiry"]["selected_expiry"])
        payout = float(candidate["expiry"].get("payout") or self.feed.payout(asset, expiry))
        timing = candidate["entry_timing"]
        edge = candidate["edge_validation"]
        risk = candidate.get("risk_approval")

        key = SetupKey(asset, strategy, direction, regime, expiry)
        setup = self.setup_evaluator.current(key)
        report.setup_state = setup.state.value

        decision = TradeDecision(
            timestamp=now, asset=asset, direction=direction, strategy=strategy,
            confidence=confidence,
            opportunity_score=float(candidate.get("rank_score", confidence)),
            market_regime=regime, entry_timing=timing.get("timing"),
            expiry=expiry, payout=payout,
            risk_decision=RiskDecision.REJECTED,
            edge_approved=bool(edge.get("approved")),
            edge_details=edge,
        )

        # Orden de los vetos: timing -> edge -> riesgo. El riesgo va ultimo
        # porque es el que fija el tamano y el corte global; los otros dos
        # dicen si la oportunidad existe.
        if not timing.get("enter_now", False):
            reason = f"Timing: {timing.get('rationale', 'unknown')}"
            decision.risk_reason = reason
            self._save_decision(decision)
            return ("timing", reason)

        if not edge.get("approved", False):
            reason = f"Edge: {'; '.join(edge.get('reasons', []))}"
            decision.risk_reason = reason
            self._save_decision(decision)
            return ("edge", reason)

        # ── MEMORIA DE FALLOS: no repetir la misma entrada ─────────────────
        # Va despues del gate de edge y antes del de riesgo: el edge dice si el
        # setup merece la pena en general, la memoria dice si ESTA entrada
        # concreta tiene las condiciones que historicamente precedieron a una
        # perdida. El riesgo va al final porque es el que fija el tamano.
        #
        # Solo se usan condiciones observables en el instante de entrada. Nada de
        # MAE/MFE ni de recorrido posterior: eso es diagnostico post-hoc y
        # consultarlo al decidir seria look-ahead.
        entry_features = signal.get("features") or {}
        try:
            memory = self.failure_memory.consult(key.slug, entry_features)
        except Exception as exc:                              # noqa: BLE001
            logger.warning("failure_memory.consult fallo: %s", exc)
            memory = {"vetoed": False, "reasons": []}
        if memory.get("vetoed"):
            self.vetoes_applied += 1
            reason = f"Memoria de fallos: {'; '.join(memory.get('reasons', []))}"
            decision.risk_reason = reason
            decision.edge_details = {**(decision.edge_details or {}),
                                     "failure_memory": memory}
            self._save_decision(decision)
            logger.info("entrada vetada por memoria de fallos en %s/%s: %s",
                        strategy, asset, memory.get("conditions"))
            return ("failure_memory", reason)

        if risk is None or risk.get("decision") != RiskDecision.APPROVED:
            decision.risk_decision = (risk or {}).get("decision", RiskDecision.REJECTED)
            reason = f"Risk: {'; '.join((risk or {}).get('reasons', ['sin decision de riesgo']))}"
            decision.risk_reason = reason
            self._save_decision(decision)
            if decision.risk_decision == RiskDecision.HALTED:
                self.stats.halted = True
                return ("halted", reason)
            return ("risk", reason)

        # El multiplicador del setup YA esta aplicado dentro de
        # `RiskManagerAgent.approve(stake_multiplier=...)`. Volver a aplicarlo
        # aqui era un doble descuento: el trade salia a 1/4 de 1/4 del tamano y,
        # peor, `on_trade_opened` guardaba ese stake encogido como `last_stake`.
        # En el ciclo siguiente el gestor calculaba el stake correcto, veia que
        # "subia" respecto al anterior y el anti-martingala lo rechazaba como si
        # fuera una escalada de perdidas. En una corrida de 120 ciclos eso
        # produjo 25 rechazos falsos y 1 sola operacion.
        #
        # El gestor de riesgo es la UNICA fuente del tamano. Nadie mas lo toca.
        stake = float(risk.get("stake", 0.0))
        multiplier = setup.stake_multiplier
        report.stake, report.payout = stake, payout

        decision.risk_decision = RiskDecision.APPROVED
        decision.risk_reason = (f"stake={stake} (mult={multiplier}) payout={payout} "
                                f"sizing={risk.get('sizing_basis', '')}")
        self._save_decision(decision)

        entry_price = self.feed.last_price(asset)
        if entry_price is None:
            return ("no_entry_price",
                    "el feed no tiene precio en el instante de entrada")

        trade = self.broker.buy(
            asset, direction, stake, expiry,
            meta={
                "strategy": strategy, "market_regime": regime,
                "confidence": confidence, "payout": payout,
                "entry_price": entry_price, "entry_time": now,
                "expiry_time": now + timedelta(seconds=expiry),
                "data_source": self.feed.data_source,
                "setup_slug": key.slug, "stake_multiplier": multiplier,
                "features": {**(signal.get("features") or {}),
                             "rank_score": candidate.get("rank_score"),
                             "mtf": candidate.get("multi_timeframe"),
                             "edge_n": edge.get("n")},
                "entry_timing": timing.get("timing"),
            },
        )
        if trade is None:
            return ("broker", "el broker rechazo o no pudo enviar la orden")

        # El trade operado deja de ser sombra: ya tiene su propia observacion.
        self._shadow_open = [
            sh for sh in self._shadow_open
            if sh.features.get("setup_slug") != key.slug
            or sh.timestamp != now
        ]
        self.risk_manager.on_trade_opened(trade)
        self.stats.trades += 1
        report.traded = True
        report.trade = trade
        return "traded"

    # ── evaluacion sombra ─────────────────────────────────────────────────

    def _record_shadows(self, candidates: list[dict], now: datetime) -> None:
        """Abre una observacion sombra por cada senal generada.

        QUE ES Y POR QUE ES LEGITIMA
        ----------------------------
        Una binaria se liquida comparando el precio de entrada con el precio en
        un instante futuro. Ese resultado NO depende de si se puso dinero:
        queda determinado por el mercado. Asi que una senal no operada, resuelta
        contra el precio real observado, es una observacion estadisticamente
        valida del setup.

        Esto resuelve dos problemas de una vez:

        1. La circularidad del arranque en frio. Sin sombras, cada setup
           necesita 200 operaciones PROPIAS para salir de exploracion, y como
           solo se opera el mejor candidato, las demas estrategias tardan
           semanas en acumular muestra. Con sombras, TODAS acumulan desde el
           primer ciclo.

        2. La comparabilidad. `AGENTS.md` pide comparar Estrategia A vs B vs C
           continuamente. Eso exige que las tres tengan muestra sobre el mismo
           periodo y el mismo mercado. Sin sombras solo se mide la que gana el
           ranking, y nunca se sabra si las otras eran mejores.

        LIMITACIONES, dichas explicitamente
        -----------------------------------
        Una sombra mide CALIDAD DE SENAL, no PnL realizado. No incluye:
          * riesgo de ejecucion (que el broker no acepte la orden, o la acepte
            a otro precio);
          * cambios de payout entre la senal y la entrada;
          * el efecto de operar varias a la vez sobre el saldo disponible.
        Por eso `SetupEvaluator` cuenta `n` (todas las observaciones) y
        `n_traded` (solo las operadas de verdad), y el multiplicador de tamano
        en PRODUCCION sube progresivamente con `n_traded`. Un setup puede tener
        edge demostrado en sombra y aun asi operar a medio tamano hasta que la
        ejecucion real lo confirme.

        Solo se registran si el feed es fuente de evidencia. Sombras sobre el
        simulador se registran igual (sirven para ejercitar el pipeline) pero
        `EVIDENCE_SQL` las descarta, igual que a los trades.
        """
        for candidate in candidates:
            signal = candidate["signal"]
            direction = signal.get("direction")
            if direction in (None, Direction.NO_TRADE):
                continue
            strategy = signal.get("strategy_name") or signal.get("strategy", "")
            regime = signal.get("market_regime") or MarketRegime.UNKNOWN
            expiry = int(candidate["expiry"]["selected_expiry"] or 0)
            if expiry <= 0:
                continue
            payout = float(candidate["expiry"].get("payout")
                           or self.feed.payout(candidate["asset"], expiry))
            key = SetupKey(candidate["asset"], strategy, direction, regime, expiry)
            entry_price = self.feed.last_price(candidate["asset"])
            if entry_price is None:
                continue

            shadow = TradeResult(
                timestamp=now,
                asset=candidate["asset"], direction=direction, strategy=strategy,
                expiry=expiry, payout=payout,
                # Stake unitario: lo que interesa de una sombra es el win rate y
                # la expectancy POR UNIDAD, no un PnL. Poner el stake real
                # duplicaria la exposicion contable.
                stake=1.0, result=0.0,
                execution_state=ExecutionState.SENT,
                market_regime=regime,
                confidence=float(signal.get("confidence", 0.0)),
                entry_timing=candidate["entry_timing"].get("timing"),
                features={
                    "shadow": True,
                    "setup_slug": key.slug,
                    "rank_score": candidate.get("rank_score"),
                    "edge_n": (candidate.get("edge_validation") or {}).get("n"),
                    **(signal.get("features") or {}),
                },
                entry_price=entry_price,
                entry_time=now,
                expiry_time=now + timedelta(seconds=expiry),
                resolution_source=ResolutionSource.UNRESOLVED,
                data_source=self.feed.data_source,
            )
            self._shadow_open.append(shadow)
            self.shadow_observations += 1

    def resolve_due_shadows(self, now: Optional[datetime] = None) -> list[TradeResult]:
        """Resuelve las sombras vencidas contra el precio observado.

        No tocan el balance del broker: no son operaciones, son mediciones.
        """
        now = now or self.feed.now()
        resolved: list[TradeResult] = []
        still_open: list[TradeResult] = []
        for shadow in self._shadow_open:
            expiry_time = shadow.expiry_time or (shadow.timestamp + timedelta(seconds=shadow.expiry))
            if now < expiry_time:
                still_open.append(shadow)
                continue
            exit_price = self.feed.price_at(shadow.asset, expiry_time)
            if exit_price is None or shadow.entry_price is None:
                if (now - expiry_time).total_seconds() < self.RESOLVE_TIMEOUT_SEC:
                    still_open.append(shadow)
                continue
            delta = exit_price - shadow.entry_price
            if delta == 0:
                # Empate: ni victoria ni derrota. Se descarta la observacion en
                # lugar de forzarla a un lado, que sesgaria el win rate.
                shadow.execution_state = ExecutionState.UNKNOWN
                shadow.resolution_source = ResolutionSource.UNRESOLVED
                shadow.exit_price = exit_price
                shadow.resolved_at = now
                continue
            won = delta > 0 if shadow.direction == Direction.CALL else delta < 0
            shadow.exit_price = exit_price
            shadow.result = shadow.stake * (shadow.payout if won else -1.0)
            shadow.execution_state = ExecutionState.WON if won else ExecutionState.LOST
            shadow.resolution_source = ResolutionSource.CANDLE
            shadow.resolved_at = now
            if self.persist:
                self.repo.save_trade_result(shadow)
            resolved.append(shadow)
        self._shadow_open = still_open
        if resolved:
            self.setup_evaluator.ingest(resolved)
            # Las sombras tambien alimentan la memoria de fallos, y son la mayor
            # parte de la muestra. Es legitimo aqui por la misma razon que en el
            # evaluador: el resultado de una binaria lo determina el mercado, no
            # el haber puesto dinero. Lo que una sombra NO mide es el riesgo de
            # ejecucion, y por eso la memoria produce VETOS (evitar una entrada)
            # y no cambios de tamano.
            self._learn_from(resolved)
        return resolved

    # ── resolucion contra evidencia ───────────────────────────────────────

    def resolve_due_trades(self, now: Optional[datetime] = None) -> list[TradeResult]:
        """Resuelve las operaciones vencidas. Solo contra precio observado."""
        now = now or self.feed.now()
        resolved: list[TradeResult] = []
        still_open: list[TradeResult] = []

        for trade in list(self.broker.open_trades):
            expiry_time = trade.expiry_time or (trade.timestamp + timedelta(seconds=trade.expiry))
            if now < expiry_time:
                still_open.append(trade)
                continue
            if trade.execution_state not in (ExecutionState.SENT, ExecutionState.PENDING):
                still_open.append(trade)
                continue

            outcome = self._resolve_one(trade, now)
            if outcome is None:
                if (now - expiry_time).total_seconds() < self.RESOLVE_TIMEOUT_SEC:
                    still_open.append(trade)
                    continue
                # Sin evidencia tras el timeout: UNKNOWN y fuera de la estadistica.
                trade.execution_state = ExecutionState.UNKNOWN
                trade.resolution_source = ResolutionSource.UNRESOLVED
                trade.resolved_at = now
                trade.result = 0.0
                trade.error = "sin evidencia tras timeout"
                self.stats.unresolved += 1
                self.risk_manager.on_trade_closed(trade)
                self._save_result(trade)
                logger.warning("orden %s sin evidencia tras %ss: UNKNOWN",
                               trade.broker_order_id or trade.asset, self.RESOLVE_TIMEOUT_SEC)
                resolved.append(trade)
                continue

            self.risk_manager.on_trade_closed(trade)
            self._save_result(trade)
            self._account(trade)
            resolved.append(trade)

        self.broker.open_trades = still_open
        self.risk_manager.set_open_positions(len(still_open))
        if resolved:
            self.setup_evaluator.ingest(resolved)
            # Cada operacion cerrada se diagnostica Y alimenta la memoria. Es lo
            # que convierte una perdida en informacion util: el evaluador ya
            # actualizo el win rate del setup, y ahora el forense dice que fallo
            # y la memoria aprende que condicion de entrada lo precedio.
            self._learn_from(resolved)
        return resolved

    def _learn_from(self, trades: Sequence[TradeResult]) -> None:
        """Forense + memoria de fallos sobre operaciones ya cerradas.

        Nunca lanza: el aprendizaje es un añadido, y un fallo aqui no puede
        costar una operacion ni detener el motor.
        """
        try:
            self.failure_memory.observe(trades)
        except Exception as exc:                              # noqa: BLE001
            logger.warning("failure_memory.observe fallo: %s", exc)

        for trade in trades:
            if trade.execution_state not in (ExecutionState.WON, ExecutionState.LOST):
                continue
            try:
                entry = trade.entry_time or trade.timestamp
                expiry = trade.expiry_time or (
                    entry + timedelta(seconds=trade.expiry or 0))
                # Ventana de analisis: la operacion mas la ventana siguiente (que
                # es la que revela si la expiracion se quedo corta) mas margen
                # para el ATR de referencia.
                minutes = int((expiry - entry).total_seconds() // 60) * 2 + 40
                candles = self.feed.candles(trade.asset, Timeframe.M1, max(60, minutes))
                report = self.forensics.analyse(trade, candles)
            except Exception as exc:                          # noqa: BLE001
                logger.warning("forense fallo en %s: %s", trade.asset, exc)
                continue
            self.forensic_reports += 1
            if self.persist:
                try:
                    self.repo.save_forensic_report(report)
                except Exception as exc:                      # noqa: BLE001
                    logger.warning("no se pudo guardar el forense: %s", exc)
            if report.mode.value not in ("no_es_fallo", "insuficiente"):
                logger.info("forense %s %s: %s | %s",
                            trade.asset, trade.direction.value,
                            report.mode.value, report.rule)

    def _resolve_one(self, trade: TradeResult, now: datetime) -> Optional[bool]:
        """Devuelve True/False si gano, None si AUN no hay evidencia.

        Nunca inventa un resultado. Las tres salidas posibles son:
          * PnL reportado por el broker  -> evidencia BROKER (la mejor)
          * precio observado en expiry   -> evidencia CANDLE
          * nada                         -> None, se reintenta
        """
        # 1) El broker es la fuente de verdad cuando sabe contestar.
        order_id = (trade.features or {}).get("order_id")
        if order_id is not None:
            pnl = self.broker.resolve_order(order_id)
            if pnl is not None:
                won = pnl > 0
                if pnl == 0:
                    self.broker.refund(trade, "broker reporto PnL 0")
                    self.stats.ties += 1
                    return True  # ya liquidada (reembolso), no es evidencia
                self.broker.settle(trade, won, trade.payout or 0.85,
                                   resolution_source=ResolutionSource.BROKER,
                                   data_source=DataSource.BROKER)
                trade.resolved_at = now
                return won

        # 2) Precio observado en el instante exacto de expiracion.
        entry_price = trade.entry_price
        exit_price = self.feed.price_at(trade.asset,
                                        trade.expiry_time or (trade.timestamp + timedelta(seconds=trade.expiry)))
        if entry_price is None or exit_price is None:
            return None
        delta = exit_price - entry_price
        if delta == 0:
            # Empate: el broker devuelve el stake. No es derrota. Contarlo como
            # derrota sesgaria el win rate a la baja de forma sistematica.
            self.broker.refund(trade, f"empate en {entry_price}")
            trade.resolved_at = now
            self.stats.ties += 1
            return True
        won = delta > 0 if trade.direction == Direction.CALL else delta < 0
        self.broker.settle(trade, won, trade.payout or 0.85, exit_price=exit_price,
                           resolution_source=ResolutionSource.CANDLE,
                           data_source=self.feed.data_source)
        trade.resolved_at = now
        return won

    def _account(self, trade: TradeResult):
        if trade.execution_state == ExecutionState.WON:
            self.stats.wins += 1
            self.stats.gross_profit += max(0.0, trade.result)
        elif trade.execution_state == ExecutionState.LOST:
            self.stats.losses += 1
            self.stats.gross_loss += abs(min(0.0, trade.result))
        if trade.data_source.is_evidence:
            self.stats.evidence_trades += 1
        else:
            self.stats.simulated_trades += 1

    # ── libro diario y curva de equity ────────────────────────────────────

    def _roll_daily(self, now: datetime):
        key = now.date()
        if self._daily_key == key:
            return
        self._daily_key = key
        self.risk_manager.reset_daily(self.equity)

    def _mark_equity(self, now: datetime):
        eq = self.equity
        self._equity_curve.append((now, eq))
        if eq > self._peak_equity:
            self._peak_equity = eq
        if self._peak_equity > 0:
            dd = (self._peak_equity - eq) / self._peak_equity * 100.0
            if dd > self._max_drawdown_pct:
                self._max_drawdown_pct = dd

    # ── persistencia ──────────────────────────────────────────────────────

    def _save_decision(self, decision: TradeDecision):
        if self.persist:
            self.repo.save_decision(decision)

    def _save_result(self, trade: TradeResult):
        if self.persist:
            self.repo.save_trade_result(trade)

    @staticmethod
    def _tf(minutes: int) -> Timeframe:
        return {1: Timeframe.M1, 5: Timeframe.M5, 15: Timeframe.M15}[minutes]

    # ── informe ───────────────────────────────────────────────────────────

    def summary(self) -> dict:
        now = self.feed.now()
        self._mark_equity(now)
        data = self.stats.as_dict()
        data.update({
            "mode_feed": self.feed.data_source.value,
            "now": now.isoformat(),
            "equity": round(self.equity, 2),
            "start_equity": round(self._start_equity, 2),
            "peak_equity": round(self._peak_equity, 2),
            "max_drawdown_pct": round(self._max_drawdown_pct, 2),
            "open_positions": len(self.broker.open_trades),
            "open_shadows": len(self._shadow_open),
            "shadow_observations": self.shadow_observations,
            # Que el aprendizaje sea visible. Un motor que diagnostica y veta en
            # silencio no se puede auditar, y la auditoria es lo unico que
            # distingue esto de una caja negra que un dia empieza a rechazar
            # entradas sin que nadie sepa por que.
            "forensic_reports": self.forensic_reports,
            "vetoes_applied": self.vetoes_applied,
            "failure_memory": self.failure_memory.report(limit=10)
            if self.failure_memory is not None else {},
            "assets": list(self.assets),
            "risk_state": self.risk_manager.state(),
        })
        return data
