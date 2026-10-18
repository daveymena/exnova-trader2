# -*- coding: utf-8 -*-
"""Backtesting causal con walk-forward, sobre EL MISMO motor que opera en vivo.

LO QUE ESTABA MAL
-----------------
El backtester anterior decidia el resultado del trade con la MISMA vela que
generaba la senal:

    for i in range(50, len(m1_sorted)):
        current_candle = m1_sorted[i]
        ...
        signal = strategy.evaluate(m15_ctx, m5_ctx, m1_ctx, asset)   # usa vela i
        ...
        if direction == Direction.CALL:
            won = current_candle.is_bullish                          # ... y vela i

Eso no es un backtest optimista: es un backtest que no mide nada. `won` es una
entrada de la senal, asi que el resultado reportado es "con que frecuencia mi
estrategia ve una vela alcista cuando acaba de predecir alcista" -- sesgado por
construccion hacia el acierto. Punto 10 de `app/NOT_PRODUCTION_READY.md`.

Ademas: solo evaluaba 3 de las 4 estrategias registradas (la unica que estaba
en vivo, `sr_bounce`, nunca se backtesteaba), reportaba `longest_losing_streak`
como la racha VIGENTE al final en lugar de la maxima, y escribia cada trade en
la base de datos de vivo (`repository.save_trade_result`), contaminando el
historico real con resultados sinteticos que despues alimentaban al
EdgeValidator.

COMO SE ARREGLA
---------------
No hay un segundo motor. `Backtester` construye un `ReplayFeed` sobre datos
reales (CSV) o un `SimulatedFeed`, y corre el `TradingEngine` de produccion con
el reloj virtual avanzando. Como el motor solo ve el mercado a traves de
`feed.candles()` -- que unicamente devuelve velas CERRADAS respecto a
`feed.now()` -- el look-ahead es estructuralmente imposible: no se puede
escribir por descuido porque la informacion futura no esta al alcance del codigo.

Una binaria se liquida contra `feed.price_at(entry + expiry)`, el precio real de
ese instante. No contra la vela que genero la senal.

AISLAMIENTO
-----------
El backtest usa una base de datos EN MEMORIA y un `SetupEvaluator` propio. Nunca
escribe en la BD de vivo. Si lo hiciera, una corrida sobre datos simulados
podria ascender setups a PRODUCCION y el bot empezaria a operarlos a tamano
completo basandose en ruido sintetico. Es la razon de ser de `DataSource` y de
`EVIDENCE_SQL`, y se aplica tambien aqui.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Sequence

from app.agents.edge_validator_agent import EdgeValidatorAgent
from app.agents.risk_manager_agent import RiskLimits, RiskManagerAgent
from app.agents.signal_agent import SignalAgent
from app.config import config
from app.core.engine import TradingEngine
from app.data.feed import MarketFeed, ReplayFeed, SimulatedFeed
from app.data.market_sim import SimConfig
from app.data.repository import Repository
from app.data.schemas import (
    BacktestResult, Candle, DataSource, Direction, ExecutionState, SetupState,
    Timeframe, TradeResult,
)
from app.research.setup_evaluator import EvaluatorConfig, SetupEvaluator
from app.services.paper_broker import PaperBroker
from app.stats.core import (
    binary_sharpe, breakeven_winrate, longest_streak, max_drawdown_pct,
    summarize_binomial, wilson_interval,
)
from app.strategies.registry import ParamStore, StrategyRegistry

logger = logging.getLogger(__name__)


@dataclass
class BacktestReport:
    """Informe completo. `metrics` es el resumen; el resto da el detalle."""
    id: str = ""
    label: str = ""
    created_at: Optional[datetime] = None
    data_source: DataSource = DataSource.UNKNOWN
    asset: str = ""
    strategies: list = field(default_factory=list)
    window: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)
    by_strategy: dict = field(default_factory=dict)
    by_regime: dict = field(default_factory=dict)
    by_expiry: dict = field(default_factory=dict)
    by_direction: dict = field(default_factory=dict)
    shadows_by_strategy: dict = field(default_factory=dict)
    setups: dict = field(default_factory=dict)
    rejections: dict = field(default_factory=dict)
    risk: dict = field(default_factory=dict)
    equity_curve: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    shadows: int = 0
    honest_note: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "data_source": self.data_source.value, "asset": self.asset,
            "strategies": list(self.strategies), "window": dict(self.window),
            "metrics": dict(self.metrics), "by_strategy": dict(self.by_strategy),
            "by_regime": dict(self.by_regime), "by_expiry": dict(self.by_expiry),
            "by_direction": dict(self.by_direction),
            "shadows_by_strategy": dict(self.shadows_by_strategy),
            "setups": dict(self.setups),
            "rejections": dict(self.rejections), "risk": dict(self.risk),
            "shadows": self.shadows, "honest_note": self.honest_note,
        }

    def to_backtest_result(self) -> BacktestResult:
        """Compatibilidad con `app/research/reporting.py` y codigo heredado."""
        m = self.metrics
        return BacktestResult(
            total_trades=int(m.get("trades", 0)),
            wins=int(m.get("wins", 0)),
            losses=int(m.get("losses", 0)),
            win_rate=float(m.get("win_rate") or 0.0),
            expectancy=float(m.get("expectancy") or 0.0),
            net_return=float(m.get("net_pnl", 0.0)),
            profit_factor=float(m.get("profit_factor") or 0.0),
            max_drawdown=float(m.get("max_drawdown_pct", 0.0)),
            longest_losing_streak=int(m.get("longest_losing_streak", 0)),
            regime_breakdown=dict(self.by_regime),
            strategy_breakdown=dict(self.by_strategy),
            equity_curve=list(self.equity_curve),
        )


def _merge_shadow_by_strategy(reports: Sequence[BacktestReport]) -> dict:
    """Suma n/wins por estrategia entre pliegues y recalcula Wilson y expectancy.

    No se promedian los win rates de cada pliegue: se suman exitos y ensayos y
    se recalcula. Promediar porcentajes de muestras desiguales es un error
    clasico y aqui sesgaria justo la cifra con la que se decide.
    """
    payout = (reports[0].metrics.get("payout") or 0.85) if reports else 0.85
    acc: dict[str, dict] = {}
    for r in reports:
        for name, b in (r.metrics.get("shadow_by_strategy") or {}).items():
            slot = acc.setdefault(name, {"n": 0, "wins": 0})
            slot["n"] += int(b.get("n") or 0)
            slot["wins"] += int(b.get("wins") or 0)
    out: dict[str, dict] = {}
    for name, slot in acc.items():
        summary = summarize_binomial(slot["wins"], slot["n"], payout) if slot["n"] else {}
        out[name] = {
            "n": slot["n"], "wins": slot["wins"],
            "losses": slot["n"] - slot["wins"],
            "win_rate": summary.get("win_rate"),
            "win_rate_lower": summary.get("win_rate_lower"),
            "win_rate_upper": summary.get("win_rate_upper"),
            "break_even": summary.get("break_even"),
            "expectancy": summary.get("expectancy"),
            "expectancy_lower": summary.get("expectancy_lower"),
            "edge_proven": summary.get("edge_proven"),
        }
    return out


class Backtester:
    """Corre el motor de produccion sobre un feed historico o simulado."""

    def __init__(self, initial_balance: float = 10_000.0,
                 payout: float = 0.85,
                 strategies: Optional[Sequence[str]] = None,
                 risk_limits: Optional[RiskLimits] = None,
                 evaluator_config: Optional[EvaluatorConfig] = None,
                 cycle_seconds: int = 60,
                 db_path: str = ":memory:",
                 params_path: Optional[str] = None,
                 stake: Optional[float] = None):
        """
        `db_path=":memory:"` por defecto: un backtest NO toca la BD de vivo.
        `stake` fija el tamano por operacion; si es None lo decide el gestor de
        riesgo (Kelly fraccionado sobre la cota de Wilson).
        """
        self.initial_balance = initial_balance
        self.payout = payout
        self.strategies = list(strategies) if strategies else None
        self.risk_limits = risk_limits
        self.evaluator_config = evaluator_config or EvaluatorConfig()
        self.cycle_seconds = cycle_seconds
        self.db_path = db_path
        self.params_path = params_path
        self.fixed_stake = stake

    # ── construccion del entorno aislado ──────────────────────────────────

    def _build(self, feed: MarketFeed) -> tuple[TradingEngine, StrategyRegistry,
                                                SetupEvaluator, Repository]:
        repo = Repository(self.db_path)
        repo.migrate()
        registry = StrategyRegistry(
            store=ParamStore(self.params_path) if self.params_path else ParamStore(),
            only=self.strategies,
        )
        # Evaluator propio y SIN persistencia cruzada: escribe en la BD del
        # backtest, nunca en la de vivo.
        # `persist=True` SIEMPRE, tambien con `db_path=":memory:"`. El
        # aislamiento no viene de apagar la escritura sino de usar un
        # Repository propio: una BD en memoria desaparece al cerrar el backtest,
        # y mientras dure hay que poder consultarla. La version anterior ponia
        # persist=False con ":memory:" y despues intentaba RECOLECTAR los trades
        # de esa misma BD -- es decir, nunca se guardaba nada y el informe salia
        # con cero operaciones.
        evaluator = SetupEvaluator(config=self.evaluator_config, repository=repo,
                                   persist=True)
        signal_agent = SignalAgent(registry=registry, setup_evaluator=evaluator,
                                   persist=False)
        risk = RiskManagerAgent(limits=self.risk_limits)
        broker = PaperBroker(initial_balance=self.initial_balance,
                             data_source=feed.data_source)
        engine = TradingEngine(
            feed=feed, broker=broker, signal_agent=signal_agent,
            risk_manager=risk, setup_evaluator=evaluator, repo=repo,
            persist=True,
            equity_start=self.initial_balance,
        )
        return engine, registry, evaluator, repo

    # ── corrida simple ────────────────────────────────────────────────────

    def run_feed(self, feed: MarketFeed, cycles: Optional[int] = None,
                 label: str = "", asset: Optional[str] = None,
                 until: Optional[datetime] = None) -> BacktestReport:
        """Corre el motor sobre `feed` y devuelve el informe."""
        engine, registry, evaluator, repo = self._build(feed)
        if self.fixed_stake is not None:
            # Tamano fijo: util para aislar el rendimiento de la SENAL del
            # efecto del sizing. Un backtest que mezcla ambos no permite saber
            # si mejoro la estrategia o el gestor de riesgo.
            # Ambos limites al MISMO valor: un rango [10, 50] no fija nada, el
            # gestor seguia eligiendo 50. La version anterior hacia min/max en
            # el sentido equivocado y el stake declarado se ignoraba (una
            # operacion de 10 reportaba PnL de 42.5).
            engine.risk_manager.limits.min_stake = self.fixed_stake
            engine.risk_manager.limits.max_stake = self.fixed_stake
            engine.risk_manager.limits.exploration_position_pct = 100.0
            engine.risk_manager.limits.max_position_pct = 100.0

        started = feed.now()
        if until is None and cycles is None:
            span_end = None
            if isinstance(feed, ReplayFeed):
                _, span_end = feed.span()
            cycles = None if span_end else 1000
            until = span_end

        n = 0
        while True:
            if cycles is not None and n >= cycles:
                break
            if until is not None and feed.now() >= until:
                break
            engine.step(asset=asset)
            feed.advance(self.cycle_seconds)
            n += 1

        # Cerrar lo que quedo abierto al final de la ventana: sin esto, las
        # ultimas operaciones desaparecen del informe y el win rate se calcula
        # sobre una muestra truncada por el final del fichero.
        tail = engine.resolve_due_trades(feed.now() + timedelta(days=2))
        tail += engine.resolve_due_shadows(feed.now() + timedelta(days=2))

        report = self._report(engine, registry, evaluator, feed,
                              started, feed.now(), n, label, asset, tail)
        return report

    def run(self, candles_m15: Sequence[Candle] = (), candles_m5: Sequence[Candle] = (),
            candles_m1: Sequence[Candle] = (), asset: str = "",
            payout: Optional[float] = None, stake_per_trade: Optional[float] = None,
            **kwargs) -> BacktestReport:
        """API compatible con la firma antigua, pero causal.

        Acepta listas de velas M1/M5/M15 y construye un `ReplayFeed` a partir de
        las M1 (re-muestreando M5/M15 para que sean consistentes). Si no se
        pasan velas, genera mercado simulado: antes eso devolvia un informe
        vacio, que es la peor respuesta posible porque parece un backtest que
        no encontro operaciones en lugar de uno al que no le dieron datos.

        Las velas heredadas llevan `data_source` por defecto UNKNOWN, que NO es
        evidencia. Se marcan explicitamente segun su procedencia real.
        """
        if payout is not None:
            self.payout = payout
        if stake_per_trade is not None:
            self.fixed_stake = stake_per_trade

        m1 = [c for c in (candles_m1 or []) if c.timeframe == Timeframe.M1]
        if not m1:
            logger.warning("Backtester.run sin velas M1: se usa mercado simulado. "
                           "Los resultados NO son evidencia.")
            feed = SimulatedFeed([asset or "SIM-OTC"], SimConfig(seed=1),
                                 warmup_minutes=600)
            return self.run_feed(feed, asset=asset or "SIM-OTC", **kwargs)

        marked = []
        for c in sorted(m1, key=lambda x: x.open_time):
            if c.data_source == DataSource.UNKNOWN:
                # Una vela de procedencia desconocida NO puede convertirse en
                # evidencia. Se marca SIMULATOR: es lo mas conservador, y obliga
                # a quien carga datos a declarar de donde vienen.
                c.data_source = DataSource.SIMULATOR
                c.source = c.source if c.source not in ("unknown", "") else "unmarked"
            marked.append(c)

        data = {marked[0].asset: marked}
        feed = ReplayFeed(data, default_payout=self.payout,
                          start=marked[0].open_time + timedelta(minutes=60))
        return self.run_feed(feed, asset=marked[0].asset, **kwargs)

    # ── walk-forward ──────────────────────────────────────────────────────

    def walk_forward(self, feed: MarketFeed, folds: int = 4,
                     train_ratio: float = 0.6,
                     label: str = "walk_forward",
                     asset: Optional[str] = None,
                     param_tuner=None) -> dict:
        """Validacion walk-forward: ajustar en train, juzgar en test.

        POR QUE ES OBLIGATORIO
        ----------------------
        Un backtest sobre todo el historico con los parametros elegidos mirando
        ese mismo historico no mide nada: mide la capacidad del ajuste para
        reproducir el pasado. `bozidar-quant/quant-strategy-backtester` --
        el repositorio mas honesto del dominio -- documenta exactamente esto y
        publica un resultado NEGATIVO en lugar de esconderlo detras de una curva
        de equity cherry-picked: cuatro familias de estrategias, ninguna con
        edge out-of-sample.

        Aqui cada pliegue parte la ventana en train/test. `param_tuner` recibe
        el informe de train y devuelve parametros; esos parametros se aplican al
        test y NUNCA se vuelven a ajustar con datos de test. Lo que se reporta
        como resultado es el agregado OUT-OF-SAMPLE.

        Si `param_tuner` es None, los parametros se congelan: el walk-forward
        sigue siendo util porque mide estabilidad temporal (un edge que solo
        existe en un trimestre no es un edge).
        """
        if not isinstance(feed, ReplayFeed):
            raise TypeError("walk_forward necesita un ReplayFeed (historico real)")
        start, end = feed.span()
        if not start or not end:
            return {"error": "el feed no tiene historico"}
        total = (end - start).total_seconds()
        if total <= 0:
            return {"error": "historico de longitud cero"}
        if not 0.0 < train_ratio < 1.0:
            raise ValueError("train_ratio debe estar en (0,1)")

        fold_len = total / folds
        results = []
        oos_reports = []
        current_params: Optional[dict] = None

        for i in range(folds):
            fold_start = start + timedelta(seconds=fold_len * i)
            train_end = fold_start + timedelta(seconds=fold_len * train_ratio)
            fold_end = fold_start + timedelta(seconds=fold_len)
            if fold_end > end:
                break

            # --- train ---
            train_feed = feed.fork(fold_start)
            self.params_path = self.params_path  # se mantiene el almacen
            if current_params:
                self._apply_params(current_params)
            train_report = self.run_feed(
                train_feed, until=train_end, asset=asset,
                label=f"{label}_fold{i}_train")

            # --- ajuste (solo con datos de train) ---
            tuned = None
            if param_tuner is not None:
                try:
                    tuned = param_tuner(train_report, i)
                except Exception as exc:                      # noqa: BLE001
                    logger.warning("param_tuner fallo en el pliegue %d: %s", i, exc)
                    tuned = None
            if tuned:
                current_params = tuned
                self._apply_params(tuned)

            # --- test: parametros CONGELADOS, datos que el ajuste no vio ---
            test_feed = feed.fork(train_end)
            test_report = self.run_feed(
                test_feed, until=fold_end, asset=asset,
                label=f"{label}_fold{i}_test")
            oos_reports.append(test_report)

            results.append({
                "fold": i,
                "train_window": [fold_start.isoformat(), train_end.isoformat()],
                "test_window": [train_end.isoformat(), fold_end.isoformat()],
                "in_sample": train_report.metrics,
                "out_of_sample": test_report.metrics,
                "tuned_params": tuned,
                "degradation": self._degradation(train_report.metrics,
                                                 test_report.metrics),
            })

        aggregate = self._aggregate_oos(oos_reports)
        return {
            "label": label,
            "folds": len(results),
            "train_ratio": train_ratio,
            "results": results,
            "out_of_sample_aggregate": aggregate,
            # La cifra que importa. Un sistema que reporta solo in-sample esta
            # reportando su capacidad de autoenganarse.
            "verdict": self._verdict(aggregate, results),
        }

    def _apply_params(self, params: dict):
        store = ParamStore(self.params_path) if self.params_path else ParamStore()
        for strategy, values in (params or {}).items():
            store.set_params(strategy, values, origin="walk_forward",
                             reason="ajuste sobre ventana de train")
        self.params_path = str(store.path)

    @staticmethod
    def _degradation(ins: dict, oos: dict) -> dict:
        """Cuanto cae el rendimiento al salir de muestra. Es LA senal de overfit."""
        def delta(key):
            a, b = ins.get(key), oos.get(key)
            if a is None or b is None:
                return None
            return round(b - a, 4)
        return {
            "win_rate": delta("win_rate"),
            "expectancy": delta("expectancy"),
            "profit_factor": delta("profit_factor"),
            "trades": delta("trades"),
            # Degradacion medida sobre SOMBRAS tambien. Es la que usa el motor
            # de mejora cuando decide sobre base sombra: mezclar bases -- win
            # rate de sombras contra degradacion de trades operados -- hacia que
            # el filtro de overfit se disparara siempre, porque con 1 o 2 trades
            # operados la "degradacion" es ruido puro y no dice nada.
            "shadow_win_rate": delta("shadow_win_rate"),
            "shadow_expectancy": delta("shadow_expectancy"),
        }

    @staticmethod
    def _aggregate_oos(reports: Sequence[BacktestReport]) -> dict:
        if not reports:
            return {}
        wins = sum(int(r.metrics.get("wins", 0)) for r in reports)
        losses = sum(int(r.metrics.get("losses", 0)) for r in reports)
        trades = sum(int(r.metrics.get("trades", 0)) for r in reports)
        resolved = wins + losses
        shadows = sum(int(r.metrics.get("shadow_observations", 0)) for r in reports)
        sh_wins = sum(int(r.metrics.get("shadow_wins", 0)) for r in reports)
        sh_res = sum(int(r.metrics.get("shadows_resolved", 0)) for r in reports)
        sh_exps = [r.metrics.get("shadow_expectancy") for r in reports
                   if r.metrics.get("shadow_expectancy") is not None]
        gp = sum(float(r.metrics.get("gross_profit", 0.0)) for r in reports)
        gl = sum(float(r.metrics.get("gross_loss", 0.0)) for r in reports)
        exps = [r.metrics.get("expectancy") for r in reports
                if r.metrics.get("expectancy") is not None]
        dds = [float(r.metrics.get("max_drawdown_pct", 0.0)) for r in reports]
        payout = reports[0].metrics.get("payout") or 0.85
        summary = summarize_binomial(wins, resolved, payout) if resolved else {}
        # DESPUES de definir `payout`: la version anterior de este bloque estaba
        # colocada mas arriba y lanzaba UnboundLocalError en cuanto habia alguna
        # sombra resuelta, lo que hacia fallar TODA validacion del motor de
        # mejora. El error se capturaba y se reportaba como "la validacion
        # fallo", asi que no tumbaba nada pero tampoco dejaba medir.
        sh_summary = summarize_binomial(sh_wins, sh_res, payout) if sh_res else {}
        return {
            "folds": len(reports),
            "trades": trades,
            "resolved": resolved,
            "wins": wins,
            "losses": losses,
            "win_rate": summary.get("win_rate"),
            "win_rate_lower": summary.get("win_rate_lower"),
            "win_rate_upper": summary.get("win_rate_upper"),
            "break_even": summary.get("break_even"),
            "expectancy": round(sum(exps) / len(exps), 4) if exps else None,
            "expectancy_min_fold": round(min(exps), 4) if exps else None,
            "expectancy_positive_folds": sum(1 for e in exps if e > 0),
            "profit_factor": round(gp / gl, 4) if gl > 0 else None,
            "gross_profit": round(gp, 2),
            "gross_loss": round(gl, 2),
            "net_pnl": round(gp - gl, 2),
            "max_drawdown_pct_worst_fold": round(max(dds), 2) if dds else None,
            "shadow_observations": shadows,
            "edge_proven": summary.get("edge_proven", False),
            # Out-of-sample medido sobre sombras: es la base con la que el motor
            # de mejora decide, porque tiene muestra suficiente para distinguir
            # una mejora real de la suerte.
            "shadow_resolved": sh_res,
            "shadow_wins": sh_wins,
            "shadow_losses": sh_res - sh_wins,
            "shadow_win_rate": sh_summary.get("win_rate"),
            "shadow_win_rate_lower": sh_summary.get("win_rate_lower"),
            "shadow_break_even": sh_summary.get("break_even"),
            "shadow_expectancy": (round(sum(sh_exps) / len(sh_exps), 4)
                                  if sh_exps else None),
            "shadow_expectancy_lower": sh_summary.get("expectancy_lower"),
            "shadow_edge_proven": sh_summary.get("edge_proven", False),
            # Por estrategia, sumando pliegues. Es lo que el motor de mejora
            # necesita para juzgar UN cambio concreto.
            "shadow_by_strategy": _merge_shadow_by_strategy(reports),
        }

    @staticmethod
    def _verdict(agg: dict, results: list[dict]) -> str:
        """Veredicto en texto. Sin eufemismos."""
        if not agg or not agg.get("resolved"):
            return ("SIN MUESTRA: el walk-forward no resolvio ninguna operacion. "
                    "No se puede concluir nada -- y 'no se puede concluir nada' "
                    "NO es 'funciona'.")
        wr = agg.get("win_rate") or 0.0
        lo = agg.get("win_rate_lower")
        be = agg.get("break_even") or breakeven_winrate(0.85)
        folds_ok = agg.get("expectancy_positive_folds", 0)
        folds = agg.get("folds", 0)
        degradations = [r["degradation"]["expectancy"] for r in results
                        if r["degradation"].get("expectancy") is not None]
        avg_degradation = (sum(degradations) / len(degradations)) if degradations else None

        parts = [
            f"OUT-OF-SAMPLE n={agg['resolved']} WR={wr:.2%} "
            f"IC95%=[{(lo or 0):.2%}, {(agg.get('win_rate_upper') or 0):.2%}] "
            f"break-even={be:.2%}."
        ]
        if agg.get("edge_proven"):
            parts.append("EDGE DEMOSTRADO: la cota inferior del IC supera el "
                         "break-even fuera de muestra.")
        else:
            parts.append("SIN EDGE DEMOSTRADO: la cota inferior del IC no supera "
                         "el break-even fuera de muestra. Operar esto es apostar.")
        if folds:
            parts.append(f"Expectancy positiva en {folds_ok}/{folds} pliegues.")
        if avg_degradation is not None:
            parts.append(f"Degradacion media train->test: {avg_degradation:+.4f} "
                         f"de expectancy por operacion "
                         f"({'overfit probable' if avg_degradation < -0.05 else 'aceptable'}).")
        return " ".join(parts)

    # ── informe ───────────────────────────────────────────────────────────

    def _report(self, engine: TradingEngine, registry: StrategyRegistry,
                evaluator: SetupEvaluator, feed: MarketFeed,
                started: datetime, ended: datetime, cycles: int,
                label: str, asset: Optional[str],
                tail: Sequence[TradeResult]) -> BacktestReport:
        stats = engine.stats
        trades = self._collect_trades(engine)
        shadows = [t for t in trades if (t.features or {}).get("shadow")]
        trades = [t for t in trades if not (t.features or {}).get("shadow")]

        resolved = [t for t in trades
                    if t.execution_state in (ExecutionState.WON, ExecutionState.LOST)]
        wins = sum(1 for t in resolved if t.execution_state == ExecutionState.WON)
        losses = len(resolved) - wins
        payout = self.payout
        summary = summarize_binomial(wins, len(resolved), payout)

        outcomes = [t.execution_state == ExecutionState.WON for t in resolved]
        best_win, best_loss = longest_streak(outcomes) if outcomes else (0, 0)

        # Medicion sobre SOMBRAS. Importa tanto como la de trades operados:
        # un cambio de parametros afecta a la GENERACION de senales, y las
        # sombras miden exactamente eso con mucho mas volumen. Un backtest que
        # solo cuenta trades operados necesita semanas de historico para tener
        # muestra; con sombras la misma ventana da cientos de observaciones.
        shadow_wins = sum(1 for t in shadows if t.execution_state == ExecutionState.WON)
        shadow_resolved = sum(1 for t in shadows
                              if t.execution_state in (ExecutionState.WON,
                                                       ExecutionState.LOST))
        shadow_summary = summarize_binomial(shadow_wins, shadow_resolved, payout) \
            if shadow_resolved else {}

        equity = [self.initial_balance] + engine.equity_curve
        per_trade = [(t.result / t.stake) if t.stake else 0.0 for t in resolved]

        metrics = {
            "cycles": cycles,
            "trades": stats.trades,
            "resolved": len(resolved),
            "wins": wins,
            "losses": losses,
            "ties": stats.ties,
            "unresolved": stats.unresolved,
            "payout": payout,
            "break_even_wr": summary.get("break_even"),
            "win_rate": summary.get("win_rate"),
            "win_rate_lower": summary.get("win_rate_lower"),
            "win_rate_upper": summary.get("win_rate_upper"),
            "expectancy": summary.get("expectancy"),
            "expectancy_lower": summary.get("expectancy_lower"),
            "edge_proven": summary.get("edge_proven"),
            "no_edge_proven": summary.get("no_edge_proven"),
            "profit_factor": summary.get("profit_factor"),
            "binary_sharpe": binary_sharpe(per_trade),
            "net_pnl": round(engine.equity - self.initial_balance, 2),
            "net_return_pct": round((engine.equity - self.initial_balance)
                                    / self.initial_balance * 100, 4)
            if self.initial_balance else None,
            "max_drawdown_pct": round(max_drawdown_pct(equity), 4),
            # CORRREGIDO: la racha MAXIMA, no la vigente al final. La maxima es
            # la que dimensiona el riesgo de ruina.
            "longest_winning_streak": best_win,
            "longest_losing_streak": best_loss,
            "signals": stats.signals,
            "gross_profit": round(stats.gross_profit, 2),
            "gross_loss": round(stats.gross_loss, 2),
            "shadow_observations": engine.shadow_observations,
            "shadows_resolved": shadow_resolved,
            "shadow_wins": shadow_wins,
            "shadow_losses": shadow_resolved - shadow_wins,
            "shadow_win_rate": shadow_summary.get("win_rate"),
            "shadow_win_rate_lower": shadow_summary.get("win_rate_lower"),
            "shadow_win_rate_upper": shadow_summary.get("win_rate_upper"),
            "shadow_break_even": shadow_summary.get("break_even"),
            "shadow_expectancy": shadow_summary.get("expectancy"),
            "shadow_expectancy_lower": shadow_summary.get("expectancy_lower"),
            "shadow_edge_proven": shadow_summary.get("edge_proven"),
            "evidence_trades": stats.evidence_trades,
            "simulated_trades": stats.simulated_trades,
            "final_equity": round(engine.equity, 2),
        }

        # Resumen de sombras POR ESTRATEGIA, dentro de `metrics` a proposito:
        # asi viaja por `in_sample`/`out_of_sample` de cada pliegue del
        # walk-forward. Sin esto el motor de mejora solo puede comparar el
        # agregado del portfolio, y el efecto de cambiar un parametro de UNA
        # estrategia queda ahogado por las otras seis -- mediamos exactamente lo
        # mismo con y sin el cambio, y toda propuesta salia "no supera a la base".
        metrics["shadow_by_strategy"] = {
            name: {
                "n": b["trades"], "wins": b["wins"], "losses": b["losses"],
                "win_rate": b["win_rate"],
                "break_even": round(breakeven_winrate(payout), 4) if payout else None,
                "expectancy": (round(b["win_rate"] * payout - (1 - b["win_rate"]), 4)
                               if b["win_rate"] is not None and payout else None),
            }
            for name, b in self._bucket(shadows, lambda t: t.strategy or "?").items()
        }

        report = BacktestReport(
            id=str(uuid.uuid4()),
            label=label,
            created_at=datetime.utcnow(),
            data_source=feed.data_source,
            asset=asset or (feed.assets()[0] if feed.assets() else ""),
            strategies=registry.names(),
            window={"start": started.isoformat(), "end": ended.isoformat(),
                    "minutes": int((ended - started).total_seconds() // 60)},
            metrics=metrics,
            by_strategy=self._bucket(trades, lambda t: t.strategy or "?"),
            by_regime=self._bucket(trades, lambda t: t.market_regime.value
                                   if t.market_regime else "?"),
            by_expiry=self._bucket(trades, lambda t: str(t.expiry)),
            by_direction=self._bucket(trades, lambda t: t.direction.value),
            # EL DESGLOSE QUE IMPORTA para el motor de mejora: cuanta muestra
            # tiene cada estrategia -- operada Y en sombra -- sobre el mismo
            # periodo y el mismo mercado. Sin esto solo se mide la que gana el
            # ranking y nunca se puede comparar A vs B vs C, que es lo que pide
            # AGENTS.md ("compara Estrategia A vs B vs C continuamente").
            shadows_by_strategy=self._bucket(shadows, lambda t: t.strategy or "?"),
            setups=self._setups(evaluator),
            rejections=dict(stats.rejections),
            risk=engine.risk_manager.state(),
            equity_curve=[round(v, 2) for v in equity],
            trades=[self._trade_dict(t) for t in trades[-500:]],
            shadows=engine.shadow_observations,
            honest_note=self._honest_note(feed, metrics, stats),
        )
        return report

    def _collect_trades(self, engine: TradingEngine) -> list[TradeResult]:
        """Recolecta los trades cerrados. El motor los persiste; aqui se leen."""
        try:
            return engine.repo.get_trade_results(limit=100_000, evidence_only=False)
        except Exception as exc:                              # noqa: BLE001
            logger.warning("no se pudieron recolectar trades: %s", exc)
            return []

    @staticmethod
    def _bucket(trades: Sequence[TradeResult], key_fn) -> dict:
        """Agrupa por una dimension. Se hace sobre trades REALES, no sombras."""
        out: dict[str, dict] = {}
        for t in trades:
            if t.execution_state not in (ExecutionState.WON, ExecutionState.LOST):
                continue
            key = str(key_fn(t))
            b = out.setdefault(key, {"trades": 0, "wins": 0, "losses": 0,
                                     "win_rate": None, "pnl": 0.0})
            b["trades"] += 1
            won = t.execution_state == ExecutionState.WON
            b["wins" if won else "losses"] += 1
            b["pnl"] = round(b["pnl"] + (t.result or 0.0), 2)
        for b in out.values():
            b["win_rate"] = round(b["wins"] / b["trades"], 4) if b["trades"] else None
        return out

    @staticmethod
    def _setups(evaluator: SetupEvaluator) -> dict:
        rep = evaluator.report(limit=50)
        return {"totals": rep["totals"],
                "top": rep["setups"][:20]}

    @staticmethod
    def _trade_dict(t: TradeResult) -> dict:
        return {
            "timestamp": t.timestamp.isoformat() if t.timestamp else None,
            "asset": t.asset, "direction": t.direction.value,
            "strategy": t.strategy, "expiry": t.expiry,
            "stake": t.stake, "payout": t.payout, "result": t.result,
            "state": t.execution_state.value,
            "entry_price": t.entry_price, "exit_price": t.exit_price,
            "resolution_source": t.resolution_source.value,
            "data_source": t.data_source.value,
            "shadow": bool((t.features or {}).get("shadow")),
            "setup": (t.features or {}).get("setup_slug"),
            "confidence": t.confidence,
        }

    @staticmethod
    def _honest_note(feed: MarketFeed, metrics: dict, stats) -> str:
        """Nota de honestidad. Se escribe SIEMPRE, tambien cuando va bien."""
        notes = []
        if feed.data_source == DataSource.SIMULATOR:
            notes.append(
                "DATOS SIMULADOS: este informe NO es evidencia de nada. Los "
                "precios son microestructura sintetica; `data_source='simulator'` "
                "no pasa EVIDENCE_SQL, asi que ningun setup puede ascender a "
                "PRODUCCION con estos datos. Sirve para verificar que el "
                "pipeline funciona, no que la estrategia gane."
            )
        elif feed.data_source == DataSource.CSV:
            notes.append(
                "Datos historicos reales (CSV). Los precios de liquidacion estan "
                "INTERPOLADOS entre velas M1: una binaria se liquida comparando "
                "un instante exacto y aqui se aproxima. Con expiraciones de "
                "60-300s el error es pequeno, pero no es cero."
            )
        if not metrics.get("resolved"):
            notes.append(
                "CERO OPERACIONES RESUELTAS. No es 'el sistema es selectivo': es "
                'que no hay nada que medir. Ver `rejections` para ver donde se '
                "paro cada candidato."
            )
        elif metrics.get("edge_proven"):
            notes.append(
                "La cota inferior de Wilson supera el break-even EN ESTA "
                "VENTANA. Eso no es garantia de nada hacia adelante: confirme con "
                "walk-forward out-of-sample y con operaciones reales antes de "
                "creerlo."
            )
        else:
            notes.append(
                "SIN EDGE DEMOSTRADO en esta ventana: la cota inferior del IC no "
                "supera el break-even. Un win rate puntual alto con esta nota al "
                "lado es ruido, no habilidad."
            )
        if metrics.get("simulated_trades") and not metrics.get("evidence_trades"):
            notes.append(
                "Todas las operaciones son de simulacion: nada de esto entra en "
                "la estadistica de edge."
            )
        return " ".join(notes)
