"""Agente especializado en trading de opciones binarias.

Consolida:
- Analisis de mercado multi-timeframe.
- Decision inteligente de compra/venta (IA con fallback reglado).
- Gestion de cuenta (riesgo, balance, limites).
- Auto-mejora de la estrategia a partir de resultados historicos.

Diseñado para operar con Exnova (PRACTICE/REAL) y para evolucionar
continuamente segun la evidencia estadistica.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from app.config import config, TradingMode
from app.data.schemas import (
    Candle, Direction, MarketRegime, TradeResult, ExecutionState,
    ResolutionSource, RiskDecision,
)
from app.agents.signal_agent import SignalAgent
from app.agents.risk_manager_agent import RiskManagerAgent
from app.agents.market_regime_agent import MarketRegimeAgent
from app.agents.multi_timeframe_agent import MultiTimeframeAgent
from app.agents.edge_validator_agent import EdgeValidatorAgent
from app.agents.expiry_selector import ExpirySelector


@dataclass
class AccountState:
    balance: float = 10000.0
    equity: float = 10000.0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    trades_today: int = 0
    last_trade_time: Optional[datetime] = None
    halted: bool = False
    halt_reason: str = ""


@dataclass
class StrategyParams:
    min_confidence: float = 0.65
    max_position_pct: float = 0.5
    max_consecutive_losses: int = 3
    cooldown_after_loss_sec: int = 300
    min_between_trades_sec: int = 180
    preferred_expiry: int = 180


class TradingAgent:
    """Agente de trading autonomo y auto-mejorable."""

    def __init__(self, broker=None, ai_provider=None,
                 params: Optional[StrategyParams] = None):
        self.broker = broker
        self.ai_provider = ai_provider
        self.params = params or StrategyParams(
            min_confidence=config.strategy_min_confidence,
            max_consecutive_losses=config.risk_max_consecutive_losses,
            cooldown_after_loss_sec=config.risk_cooldown_after_loss_sec,
            max_position_pct=config.risk_max_position_pct,
        )

        self.signal_agent = SignalAgent()
        self.risk_manager = RiskManagerAgent()
        self.regime_agent = MarketRegimeAgent()
        self.mtf_agent = MultiTimeframeAgent()
        self.edge_validator = EdgeValidatorAgent()
        self.expiry_selector = ExpirySelector()

        self.account = AccountState(
            balance=getattr(broker, "balance", 10000.0) if broker else 10000.0
        )
        self.account.equity = self.account.balance

        self.trade_history: list[TradeResult] = []
        self.performance: dict[str, Any] = {
            "trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "profit_factor": 0.0,
            "by_strategy": {}, "by_asset": {},
        }
        self._ai_available = ai_provider is not None

    # ------------------------------------------------------------------ analysis
    def analyze_market(self, candles_m15, candles_m5, candles_m1, asset=""):
        """Analiza el mercado y devuelve un dict con senal y contexto."""
        if not candles_m15 or not candles_m5 or not candles_m1:
            return {"direction": Direction.NO_TRADE, "confidence": 0.0,
                    "reason": "datos_insuficientes", "features": {}}

        m15_sorted = sorted(candles_m15, key=lambda c: c.open_time)
        m5_sorted = sorted(candles_m5, key=lambda c: c.open_time)
        m1_sorted = sorted(candles_m1, key=lambda c: c.open_time)

        snapshot = self.mtf_agent.analyze(m15_sorted, m5_sorted, m1_sorted,
                                         asset, m1_sorted[-1].open_time)
        regime = self.regime_agent.classify(m15_sorted, asset)

        scan = self.signal_agent.scan(m15_sorted, m5_sorted, m1_sorted,
                                     asset=asset,
                                     account_equity=self.account.equity)
        signal = scan.get("signal", {})
        direction = signal.get("direction", Direction.NO_TRADE)
        confidence = float(signal.get("confidence", 0.0) or 0.0)
        strategy = signal.get("strategy", "no_trade")

        # Validacion de edge
        edge = self.edge_validator.validate(
            asset, strategy, direction, regime.regime if hasattr(regime, "regime") else MarketRegime.UNKNOWN,
            self.params.preferred_expiry, 0.85, confidence,
        )

        # IA: razonamiento adicional si esta disponible
        ai_reasoning = ""
        if self._ai_available and direction != Direction.NO_TRADE:
            ai_reasoning = self._ai_reason(asset, direction, confidence,
                                          regime, snapshot)

        return {
            "asset": asset,
            "direction": direction,
            "confidence": confidence,
            "strategy": strategy,
            "regime": getattr(regime, "regime", MarketRegime.UNKNOWN),
            "mtf_alignment": getattr(snapshot, "alignment", "unknown"),
            "edge_approved": edge.get("approved", False),
            "edge": edge,
            "scan": scan,
            "ai_reasoning": ai_reasoning,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _ai_reason(self, asset, direction, confidence, regime, snapshot):
        if not self.ai_provider:
            return ""
        try:
            prompt = (
                f"Activo {asset}. Direccion propuesta {direction.value}. "
                f"Confianza {confidence:.2f}. Regimen {getattr(regime,'regime',regime)}. "
                f"Alineacion MTF {getattr(snapshot,'alignment','?')}. "
                "Responde en una frase si es una buena operacion y por que."
            )
            res = self.ai_provider.chat(
                [{"role": "user", "content": prompt}], max_tokens=64, temperature=0
            )
            return res or ""
        except Exception:
            return ""

    # ------------------------------------------------------------------ decision
    def decide(self, analysis: dict) -> dict:
        """Devuelve {action: BUY/SELL/HOLD, stake, expiry, reasons}."""
        reasons = []
        direction = analysis.get("direction", Direction.NO_TRADE)
        confidence = analysis.get("confidence", 0.0)
        asset = analysis.get("asset", "")

        if self.account.halted:
            return {"action": "HOLD", "stake": 0.0, "expiry": 0,
                    "reasons": [f"cuenta detenida: {self.account.halt_reason}"]}

        if direction == Direction.NO_TRADE:
            return {"action": "HOLD", "stake": 0.0, "expiry": 0,
                    "reasons": ["sin senal valida"]}

        if confidence < self.params.min_confidence:
            reasons.append(f"confianza {confidence:.2f} < {self.params.min_confidence}")
            return {"action": "HOLD", "stake": 0.0, "expiry": 0, "reasons": reasons}

        if not analysis.get("edge_approved", False):
            reasons.append("edge no aprobado")
            return {"action": "HOLD", "stake": 0.0, "expiry": 0, "reasons": reasons}

        # Cooldown entre trades
        if self.account.last_trade_time:
            elapsed = (datetime.utcnow() - self.account.last_trade_time).total_seconds()
            if elapsed < self.params.min_between_trades_sec:
                reasons.append(f"cooldown {elapsed:.0f}s < {self.params.min_between_trades_sec}s")
                return {"action": "HOLD", "stake": 0.0, "expiry": 0, "reasons": reasons}

        # Riesgo
        risk = self.risk_manager.approve(
            asset, direction, analysis.get("strategy", "unknown"),
            analysis.get("regime", MarketRegime.UNKNOWN), confidence,
            self.account.equity,
        )
        if risk.get("decision") != RiskDecision.APPROVED:
            reasons.append(f"riesgo: {risk.get('reasons', [])}")
            return {"action": "HOLD", "stake": 0.0, "expiry": 0, "reasons": reasons}

        stake = float(risk.get("stake", 0.0) or 0.0)
        if stake <= 0:
            stake = self.account.equity * (self.params.max_position_pct / 100.0)
            stake = max(0.5, min(stake, self.account.equity * 0.05))

        expiry = analysis.get("scan", {}).get("expiry", {}).get("selected_expiry",
                self.params.preferred_expiry)
        if not expiry:
            expiry = self.params.preferred_expiry

        action = "BUY" if direction == Direction.CALL else "SELL"
        return {"action": action, "direction": direction, "stake": round(stake, 2),
                "expiry": int(expiry), "reasons": ["ok"],
                "strategy": analysis.get("strategy", "unknown"),
                "confidence": confidence}

    # ------------------------------------------------------------------ account mgmt
    def update_account(self, broker=None):
        b = broker or self.broker
        if b is not None:
            try:
                self.account.balance = float(b.get_balance())
                self.account.equity = float(b.get_equity()) if hasattr(b, "get_equity") else self.account.balance
            except Exception:
                pass
        # Halt conditions
        if self.account.consecutive_losses >= self.params.max_consecutive_losses:
            self.account.halted = True
            self.account.halt_reason = (
                f"{self.account.consecutive_losses} perdidas consecutivas"
            )
        dd_pct = 0.0
        if self.account.balance > 0:
            dd_pct = (self.account.equity - self.account.balance) / max(self.account.balance, 1) * 100
        if dd_pct < -config.risk_max_daily_loss_pct:
            self.account.halted = True
            self.account.halt_reason = f"drawdown diario {dd_pct:.1f}%"

    def record_trade(self, trade: TradeResult):
        self.trade_history.append(trade)
        self.account.trades_today += 1
        self.account.last_trade_time = datetime.utcnow()
        if trade.execution_state == ExecutionState.WON:
            self.account.consecutive_losses = 0
        elif trade.execution_state == ExecutionState.LOST:
            self.account.consecutive_losses += 1
        self._update_performance()
        self.update_account(self.broker)

    def _update_performance(self):
        closed = [t for t in self.trade_history
                  if t.execution_state in (ExecutionState.WON, ExecutionState.LOST)]
        self.performance["trades"] = len(closed)
        self.performance["wins"] = sum(1 for t in closed if t.execution_state == ExecutionState.WON)
        self.performance["losses"] = len(closed) - self.performance["wins"]
        self.performance["win_rate"] = (
            self.performance["wins"] / len(closed) if closed else 0.0
        )
        # por estrategia
        by_strat = {}
        for t in closed:
            s = t.strategy or "unknown"
            by_strat.setdefault(s, {"trades": 0, "wins": 0})
            by_strat[s]["trades"] += 1
            if t.execution_state == ExecutionState.WON:
                by_strat[s]["wins"] += 1
        for s, d in by_strat.items():
            d["win_rate"] = d["wins"] / d["trades"] if d["trades"] else 0.0
        self.performance["by_strategy"] = by_strat

        # por activo
        by_asset = {}
        for t in closed:
            a = t.asset or "unknown"
            by_asset.setdefault(a, {"trades": 0, "wins": 0})
            by_asset[a]["trades"] += 1
            if t.execution_state == ExecutionState.WON:
                by_asset[a]["wins"] += 1
        for a, d in by_asset.items():
            d["win_rate"] = d["wins"] / d["trades"] if d["trades"] else 0.0
        self.performance["by_asset"] = by_asset

    # ------------------------------------------------------------------ self-improvement
    def self_improve(self) -> dict:
        """Ajusta parametros segun evidencia historica. Solo cambios medibles."""
        changes = {}
        closed = [t for t in self.trade_history
                  if t.execution_state in (ExecutionState.WON, ExecutionState.LOST)]
        if len(closed) < 10:
            return {"changes": changes, "reason": "muestra_insuficiente"}

        wr = self.performance["win_rate"]
        # Si win rate bajo, subir confianza minima
        if wr < 0.5:
            old = self.params.min_confidence
            self.params.min_confidence = min(0.85, old + 0.05)
            if self.params.min_confidence != old:
                changes["min_confidence"] = (old, self.params.min_confidence)
        elif wr > 0.65:
            old = self.params.min_confidence
            self.params.min_confidence = max(0.55, old - 0.03)
            if self.params.min_confidence != old:
                changes["min_confidence"] = (old, self.params.min_confidence)

        # Desactivar activos con win rate < 40% con >=5 trades
        bad_assets = [a for a, d in self.performance["by_asset"].items()
                      if d["trades"] >= 5 and d["win_rate"] < 0.4]
        if bad_assets:
            changes["assets_to_pause"] = bad_assets

        # Estrategias con win rate < 40% -> subir su umbral
        bad_strats = [s for s, d in self.performance["by_strategy"].items()
                      if d["trades"] >= 5 and d["win_rate"] < 0.4]
        if bad_strats:
            changes["strategies_to_review"] = bad_strats

        return {"changes": changes, "performance": self.performance}

    # ------------------------------------------------------------------ scan (compat with SignalAgent)
    def scan(self, candles_m15, candles_m5, candles_m1, asset="",
             account_equity=10000.0):
        """Compatibilidad con SignalAgent.scan: devuelve el mismo formato."""
        analysis = self.analyze_market(candles_m15, candles_m5, candles_m1, asset)
        result = self.signal_agent.scan(candles_m15, candles_m5, candles_m1,
                                       asset=asset, account_equity=account_equity)
        decision = self.decide(analysis)
        result["trading_agent_analysis"] = analysis
        result["trading_agent_decision"] = decision
        # Si el agente decide HOLD, anular la senal para no operar
        if (decision.get("action") == "HOLD"
                and result.get("signal", {}).get("direction") != Direction.NO_TRADE):
            result["signal"]["direction"] = Direction.NO_TRADE
            result["signal"]["entry_rationale"] = "; ".join(
                decision.get("reasons", ["hold"])
            )
        return result

    # ------------------------------------------------------------------ cycle
    def run_cycle(self, candles_m15, candles_m5, candles_m1, asset="") -> dict:
        analysis = self.analyze_market(candles_m15, candles_m5, candles_m1, asset)
        decision = self.decide(analysis)
        self.update_account(self.broker)
        return {"analysis": analysis, "decision": decision,
                "account": self.account.__dict__, "performance": self.performance}

    def reset_daily(self):
        self.account.trades_today = 0
        self.account.daily_pnl = 0.0
        self.account.halted = False
        self.account.halt_reason = ""

    def status(self) -> dict:
        return {
            "account": self.account.__dict__,
            "params": self.params.__dict__,
            "performance": self.performance,
            "ai_available": self._ai_available,
        }
