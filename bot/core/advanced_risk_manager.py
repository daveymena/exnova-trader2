"""
Advanced Risk Manager v3.0 - Gestión de Riesgo Profesional
Kelly Criterion | Drawdown Protection | Position Sizing Dinámico
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import json


@dataclass
class RiskConfig:
    max_drawdown_daily: float = 0.10
    max_drawdown_weekly: float = 0.20
    max_drawdown_monthly: float = 0.30
    kelly_ceiling: float = 0.15
    kelly_floor: float = 0.01
    max_trades_per_hour: int = 999   # sin límite horario — la sesión lo regula
    max_trades_per_day: int = 999    # sin límite diario — el riesgo lo regula
    cooldown_after_loss_seconds: int = 120
    stop_after_consecutive_losses: int = 4
    min_confidence_threshold: float = 0.40  # Bajado de 0.65 para permitir patterns con conf 40-65%
    volatility_adjustment: bool = True


@dataclass
class TradingStats:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    consecutive_losses: int = 0
    last_loss_time: Optional[datetime] = None


class AdvancedRiskManager:
    """
    Gestor de Riesgo con Kelly Criterion + Protección de Drawdown
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self.stats = TradingStats()
        self.initial_balance = 0.0
        self.current_balance = 0.0
        self.peak_balance = 0.0
        self.trades_today: List[Dict] = []
        self.trades_this_hour: List[Dict] = []
        self.daily_pnl: Dict[str, float] = {}
        self.weekly_pnl: Dict[int, float] = {}
        self.monthly_pnl: Dict[str, float] = {}
        self.is_stopped = False
        self.stop_reason: Optional[str] = None
        self.last_trade_time: Optional[datetime] = None
        self.last_trade_was_loss = False

    def initialize(self, balance: float):
        self.initial_balance = balance
        self.current_balance = balance
        self.peak_balance = balance

    def update_balance(self, new_balance: float, trade_result: Optional[Dict] = None):
        pnl = new_balance - self.current_balance
        was_profitable = pnl > 0

        self.current_balance = new_balance
        if new_balance > self.peak_balance:
            self.peak_balance = new_balance

        self.stats.total_trades += 1
        if was_profitable:
            self.stats.winning_trades += 1
            self.stats.total_profit += pnl
            self.stats.consecutive_losses = 0
        else:
            self.stats.losing_trades += 1
            self.stats.total_loss += abs(pnl)
            self.stats.consecutive_losses += 1
            self.stats.last_loss_time = datetime.now()

        if self.stats.winning_trades > 0:
            self.stats.avg_win = self.stats.total_profit / self.stats.winning_trades
        if self.stats.losing_trades > 0:
            self.stats.avg_loss = self.stats.total_loss / self.stats.losing_trades
        if self.stats.total_trades > 0:
            self.stats.win_rate = self.stats.winning_trades / self.stats.total_trades
        if self.stats.total_loss > 0:
            self.stats.profit_factor = self.stats.total_profit / self.stats.total_loss

        record = {
            'time': datetime.now(),
            'pnl': pnl,
            'profitable': was_profitable,
            **(trade_result or {})
        }
        self.trades_today.append(record)
        self.trades_this_hour.append(record)
        self._update_period_pnl(pnl)
        self._check_drawdowns()
        self.last_trade_time = datetime.now()
        self.last_trade_was_loss = not was_profitable

    def _update_period_pnl(self, pnl: float):
        now = datetime.now()
        today_key = now.strftime('%Y-%m-%d')
        week_key = now.isocalendar()[1]
        month_key = now.strftime('%Y-%m')
        self.daily_pnl[today_key] = self.daily_pnl.get(today_key, 0.0) + pnl
        self.weekly_pnl[week_key] = self.weekly_pnl.get(week_key, 0.0) + pnl
        self.monthly_pnl[month_key] = self.monthly_pnl.get(month_key, 0.0) + pnl

    def _check_drawdowns(self):
        if self.peak_balance <= 0:
            return
        today_key = datetime.now().strftime('%Y-%m-%d')
        daily_dd = abs(min(0, self.daily_pnl.get(today_key, 0.0))) / max(1, self.initial_balance)

        if daily_dd >= self.config.max_drawdown_daily:
            self.is_stopped = True
            self.stop_reason = f"Drawdown diario: {daily_dd*100:.1f}%"
        elif self.stats.consecutive_losses >= self.config.stop_after_consecutive_losses:
            self.is_stopped = True
            self.stop_reason = f"{self.config.stop_after_consecutive_losses} pérdidas consecutivas"
        else:
            self.is_stopped = False
            self.stop_reason = None

    def calculate_kelly(self) -> float:
        if self.stats.total_trades < 8:
            return self.config.kelly_floor

        win_rate = self.stats.win_rate
        if self.stats.avg_loss == 0:
            return self.config.kelly_floor

        profit_ratio = self.stats.avg_win / max(self.stats.avg_loss, 0.01)
        kelly = win_rate - ((1 - win_rate) / profit_ratio)
        kelly = max(self.config.kelly_floor, min(self.config.kelly_ceiling, kelly))
        # Quarter Kelly para seguridad
        kelly *= 0.25

        if self.stats.consecutive_losses >= 2:
            kelly *= 0.5
        elif self.stats.consecutive_losses >= 1:
            kelly *= 0.75

        return kelly

    def calculate_position_size(self, confidence: float = 0.5,
                                atr: Optional[float] = None,
                                asset_volatility: float = 1.0) -> float:
        if self.is_stopped:
            return 0.0

        if self.last_trade_was_loss and self.last_trade_time:
            elapsed = (datetime.now() - self.last_trade_time).total_seconds()
            if elapsed < self.config.cooldown_after_loss_seconds:
                return 0.0

        if not self._can_trade_more():
            return 0.0

        if confidence < self.config.min_confidence_threshold:
            return 0.0

        kelly_fraction = self.calculate_kelly()
        confidence_adj = confidence

        streak_adj = 1.0
        if self.stats.consecutive_losses >= 3:
            streak_adj = 0.6
        elif self.stats.consecutive_losses >= 2:
            streak_adj = 0.75

        base = self.current_balance * kelly_fraction
        final = base * confidence_adj * streak_adj * asset_volatility

        min_pos = max(1.0, self.current_balance * 0.01)
        max_pos = self.current_balance * self.config.kelly_ceiling

        return round(max(min_pos, min(max_pos, final)), 2)

    def _can_trade_more(self) -> bool:
        now = datetime.now()
        hour_ago = now - timedelta(hours=1)
        self.trades_this_hour = [t for t in self.trades_this_hour if t['time'] > hour_ago]
        if len(self.trades_this_hour) >= self.config.max_trades_per_hour:
            return False
        today_key = now.strftime('%Y-%m-%d')
        trades_today = len([t for t in self.trades_today
                            if t['time'].strftime('%Y-%m-%d') == today_key])
        return trades_today < self.config.max_trades_per_day

    def get_status_report(self) -> Dict:
        drawdown = ((self.peak_balance - self.current_balance) / self.peak_balance
                    if self.peak_balance > 0 else 0)
        return {
            'balance': self.current_balance,
            'peak_balance': self.peak_balance,
            'initial_balance': self.initial_balance,
            'total_pnl': self.current_balance - self.initial_balance,
            'drawdown': drawdown,
            'is_stopped': self.is_stopped,
            'stop_reason': self.stop_reason,
            'stats': {
                'total_trades': self.stats.total_trades,
                'win_rate': self.stats.win_rate * 100,
                'profit_factor': self.stats.profit_factor,
                'consecutive_losses': self.stats.consecutive_losses,
                'avg_win': self.stats.avg_win,
                'avg_loss': self.stats.avg_loss,
            },
            'kelly_fraction': self.calculate_kelly(),
            'trades_today': len([t for t in self.trades_today
                                 if t['time'].strftime('%Y-%m-%d') == datetime.now().strftime('%Y-%m-%d')]),
            'trades_this_hour': len(self.trades_this_hour),
        }

    def reset_daily_counters(self):
        self.trades_today = []
        self.is_stopped = False
        self.stop_reason = None

    def export_stats(self) -> str:
        return json.dumps({
            'stats': {
                'total_trades': self.stats.total_trades,
                'winning_trades': self.stats.winning_trades,
                'losing_trades': self.stats.losing_trades,
                'win_rate': self.stats.win_rate,
                'profit_factor': self.stats.profit_factor,
                'avg_win': self.stats.avg_win,
                'avg_loss': self.stats.avg_loss,
            },
            'balance': self.current_balance,
            'peak': self.peak_balance,
            'initial': self.initial_balance,
            'kelly': self.calculate_kelly(),
        }, indent=2)


_risk_manager_instance: Optional[AdvancedRiskManager] = None


def get_risk_manager() -> AdvancedRiskManager:
    global _risk_manager_instance
    if _risk_manager_instance is None:
        _risk_manager_instance = AdvancedRiskManager()
    return _risk_manager_instance


def initialize_risk_manager(balance: float,
                            config: Optional[RiskConfig] = None) -> AdvancedRiskManager:
    global _risk_manager_instance
    _risk_manager_instance = AdvancedRiskManager(config)
    _risk_manager_instance.initialize(balance)
    return _risk_manager_instance
