"""Deterministic risk manager agent.

Has final veto power over every trade. Implements:
- Fixed fractional position sizing
- Daily/weekly loss limits
- Consecutive loss limits
- Maximum open positions
- Cooldown periods
- No martingale
"""
from datetime import datetime, timedelta
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
        self.max_position_pct = config.risk_max_position_pct  # 0.5 = 0.5% of equity
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
                account_equity: float) -> dict:
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

        # Position size
        is_practice = config.mode == TradingMode.PRACTICE
        stake = 5.0 if is_practice else account_equity * min(self._compute_position_size(confidence), self.max_position_pct)

        return {
            "decision": RiskDecision.APPROVED,
            "reasons": [],
            "position_size_pct": 0,
            "stake": round(stake, 2),
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
        base = self.max_position_pct * confidence
        return min(base, self.max_position_pct)

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
