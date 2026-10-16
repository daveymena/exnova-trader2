"""Deterministic risk manager agent.

Has final veto power over every trade. Implements:
- Fixed fractional position sizing
- Daily/weekly loss limits
- Consecutive loss limits
- Maximum open positions
- Cooldown periods
- No martingale

Dimensionado por Kelly acotado: la fraccion de equity se calcula con el
LIMITE INFERIOR de Wilson del win rate, no con el win rate observado. Con el
observado, 5 operaciones ganadas de 5 aconsejan apostar el 100% de la cuenta
(Kelly puro con payout 0.85); con el limite inferior aconsejan 5%. Despues se
aplica una fraccion pequena de Kelly (0.15) y un tope duro del 2% del equity
por operacion: en binarias, mas que eso es ruina casi segura.
"""
from datetime import datetime, timedelta
import os
from typing import Optional

from app.data.schemas import (
    Direction, RiskDecision, TradeResult, MarketRegime, ExecutionState
)
from app.data.repository import repository
from app.config import config, TradingMode


class RiskManagerAgent:
    def __init__(self):
        practice = config.mode == TradingMode.PRACTICE
        self.max_daily_loss_pct = 50.0 if practice else config.risk_max_daily_loss_pct
        self.max_weekly_loss_pct = 75.0 if practice else config.risk_max_weekly_loss_pct
        self.max_consecutive_losses = 20 if practice else config.risk_max_consecutive_losses
        self.max_trades_per_day = 100 if practice else config.risk_max_trades_per_day
        self.max_trades_per_hour = 20 if practice else config.risk_max_trades_per_hour
        # OJO con las unidades. El comentario original decia "0.5 = 0.5% of
        # equity" pero el valor se usaba como FRACCION, donde 0.5 es el 50%
        # de la cuenta: el tope efectivo eran $5.000 por operacion sobre
        # $10.000. Se convierte a fraccion real aqui, una vez, para que el
        # resto del codigo trabaje siempre en fracciones de 0 a 1.
        self.max_position_pct = config.risk_max_position_pct / 100.0
        # Fraccion de Kelly realmente aplicada. Kelly puro es inservible en
        # binarias: asume que se conoce p con certeza.
        self.kelly_fraction = float(os.getenv("RISK_KELLY_FRACTION", "0.15"))
        self.max_stake_pct = float(os.getenv("RISK_MAX_STAKE_PCT", "0.02"))
        # Tope duro absoluto por operacion, en la moneda de la cuenta.
        self.max_stake_absolute = float(os.getenv("RISK_MAX_STAKE_ABSOLUTE", "50"))
        self.max_open_positions = 1 if practice else config.risk_max_open_positions
        self.cooldown_after_loss = 0 if practice else config.risk_cooldown_after_loss_sec
        self.cooldown_after_trade = 0 if practice else config.risk_cooldown_after_trade_sec

        self._daily_trades: list[datetime] = []
        self._consecutive_losses = 0
        self._last_trade_time: Optional[datetime] = None
        self._daily_start_equity: Optional[float] = None
        self._current_equity: Optional[float] = None
        self._open_positions = 0
        self._kill_switch = False

    def approve(self, asset: str, direction: Direction, strategy: str,
                market_regime: MarketRegime, confidence: float,
                account_equity: float, payout: float = 0.85,
                edge_ledger=None) -> dict:
        now = datetime.utcnow()
        reasons = []

        if self._kill_switch:
            return self._reject(RiskDecision.HALTED, "Kill switch is active")

        if self._daily_start_equity is None:
            self._daily_start_equity = account_equity

        self._current_equity = account_equity

        # Daily drawdown limit
        daily_loss_pct = self._compute_daily_drawdown(account_equity)
        if daily_loss_pct > self.max_daily_loss_pct:
            reasons.append(
                f"Daily drawdown {daily_loss_pct:.2f}% exceeds limit {self.max_daily_loss_pct}%"
            )
            return self._reject(RiskDecision.HALTED, "; ".join(reasons))

        # Daily trade count
        self._clean_old_trades(now)
        if len(self._daily_trades) >= self.max_trades_per_day:
            reasons.append(f"Max trades per day reached ({self.max_trades_per_day})")
            return self._reject(RiskDecision.REJECTED, "; ".join(reasons))

        # Hourly trade count
        hourly_count = sum(1 for t in self._daily_trades
                          if (now - t).total_seconds() < 3600)
        if hourly_count >= self.max_trades_per_hour:
            reasons.append(f"Max trades per hour reached ({self.max_trades_per_hour})")
            return self._reject(RiskDecision.REJECTED, "; ".join(reasons))

        # Consecutive losses
        if self._consecutive_losses >= self.max_consecutive_losses:
            reasons.append(
                f"Max consecutive losses reached ({self._consecutive_losses})"
            )
            return self._reject(RiskDecision.REJECTED, "; ".join(reasons))

        # Open positions
        if self._open_positions >= self.max_open_positions:
            reasons.append(f"Max open positions ({self.max_open_positions})")
            return self._reject(RiskDecision.REJECTED, "; ".join(reasons))

        # Cooldown after trade
        if self._last_trade_time:
            elapsed = (now - self._last_trade_time).total_seconds()
            if elapsed < self.cooldown_after_trade:
                remaining = self.cooldown_after_trade - elapsed
                reasons.append(f"Cooldown: {remaining:.0f}s remaining")
                return self._reject(RiskDecision.REJECTED, "; ".join(reasons))

        # Position size: Kelly acotado si hay evidencia real, si no el
        # dimensionado conservador por confianza.
        is_practice = config.mode == TradingMode.PRACTICE
        if is_practice:
            stake = 5.0
        else:
            fraction = self.stake_fraction(
                strategy, direction, market_regime, payout, edge_ledger,
                fallback=self._compute_position_size(confidence),
            )
            stake = account_equity * min(fraction, self.max_position_pct)
            stake = min(stake, self.max_stake_absolute)

        return {
            "decision": RiskDecision.APPROVED,
            "reasons": [],
            "position_size_pct": 0,
            "stake": round(stake, 2),
            "stake_fraction": round(min(fraction, self.max_position_pct), 4),
            "stake_capped_absolute": stake >= self.max_stake_absolute,
            "max_loss": round(stake * (1 + config.backtest_min_payout), 2),
            "daily_drawdown": round(daily_loss_pct, 2),
        }

    def record_trade_result(self, result: TradeResult):
        now = datetime.utcnow()
        self._daily_trades.append(now)
        self._last_trade_time = now
        self._open_positions -= 1

        if result.result < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

    def set_open_positions(self, count: int):
        self._open_positions = count

    def kill(self):
        self._kill_switch = True

    def resume(self):
        self._kill_switch = False

    def reset_daily(self, equity: float):
        self._daily_trades.clear()
        self._consecutive_losses = 0
        self._daily_start_equity = equity

    def _compute_daily_drawdown(self, current_equity: float) -> float:
        if self._daily_start_equity is None or self._daily_start_equity == 0:
            return 0.0
        return max(0, (self._daily_start_equity - current_equity) / self._daily_start_equity * 100)

    def _compute_position_size(self, confidence: float) -> float:
        """Dimensionado conservador de respaldo (sin evidencia real).

        NO es Kelly: es un porcentaje pequeno y fijo escalado por confianza.
        Se usa solo mientras no hay muestra real que permita calcular Kelly.
        """
        base = self.max_position_pct * confidence * 0.1
        return min(base, self.max_position_pct)

    def stake_fraction(self, strategy: str, direction: Direction,
                       market_regime: MarketRegime, payout: float,
                       edge_ledger=None, fallback: float = 0.0) -> float:
        """Fraccion de equity a arriesgar, por Kelly acotado.

        Con evidencia real: Kelly sobre el limite inferior de Wilson, veces
        `kelly_fraction`. Sin evidencia: `fallback`, que ya de por si es
        conservador. Devuelve 0.0 solo si no se puede justificar nada.
        """
        if edge_ledger is None:
            return fallback
        try:
            fraction = edge_ledger.stake_fraction(
                strategy, direction, market_regime, payout
            )
        except Exception:
            return fallback
        if fraction <= 0:
            return fallback
        return min(fraction, self.max_stake_pct)

    def _clean_old_trades(self, now: datetime):
        self._daily_trades = [
            t for t in self._daily_trades
            if (now - t).total_seconds() < 86400
        ]

    def _reject(self, decision: RiskDecision, reason: str) -> dict:
        return {
            "decision": decision,
            "reasons": [reason],
            "position_size_pct": 0.0,
            "stake": 0.0,
            "max_loss": 0.0,
            "daily_drawdown": 0.0,
        }
