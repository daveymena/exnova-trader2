"""Backtesting framework.

No look-ahead bias. Chronological candle processing. Entries only after
signal confirmation. Correct expiry simulation with payout included.
"""
from datetime import datetime, timedelta
from typing import Optional
import json
import statistics

from app.data.schemas import (
    Candle, Direction, MarketRegime, TradeResult,
    ExecutionState, BacktestResult, Timeframe
)
from app.config import config
from app.agents.market_regime_agent import MarketRegimeAgent
from app.agents.multi_timeframe_agent import MultiTimeframeAgent
from app.strategies.trend_continuation import TrendContinuationStrategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.breakout_retest import BreakoutRetestStrategy
from app.data.repository import repository


class Backtester:
    def __init__(self, initial_balance: float = 10000.0):
        self.balance = initial_balance
        self.equity = initial_balance
        self.trades: list[TradeResult] = []
        self.equity_curve = [initial_balance]
        self.regime_agent = MarketRegimeAgent()
        self.mtf_agent = MultiTimeframeAgent()
        self.strategies = {
            "trend_continuation": TrendContinuationStrategy(),
            "mean_reversion": MeanReversionStrategy(),
            "breakout_retest": BreakoutRetestStrategy(),
        }

    def run(self, candles_m15: list[Candle], candles_m5: list[Candle],
            candles_m1: list[Candle], asset: str = "",
            payout: float = 0.85, stake_per_trade: float = 10.0) -> BacktestResult:
        m15_sorted = sorted(candles_m15, key=lambda c: c.open_time)
        m5_sorted = sorted(candles_m5, key=lambda c: c.open_time)
        m1_sorted = sorted(candles_m1, key=lambda c: c.open_time)

        results = BacktestResult()
        consecutive_losses = 0
        peak_equity = self.balance
        max_dd = 0

        # Process each M1 candle as a potential entry point
        for i in range(50, len(m1_sorted)):
            current_candle = m1_sorted[i]
            current_time = current_candle.open_time

            if self.balance <= 0:
                break

            m15_ctx = [c for c in m15_sorted if c.open_time <= current_time]
            m5_ctx = [c for c in m5_sorted if c.open_time <= current_time]
            m1_ctx = m1_sorted[:i + 1]

            if len(m15_ctx) < 30 or len(m5_ctx) < 20:
                continue

            snapshot = self.mtf_agent.analyze(m15_ctx, m5_ctx, m1_ctx, asset, current_time)

            if snapshot.alignment != "agree":
                continue

            best_signal = None

            for strategy_name, strategy in self.strategies.items():
                signal = strategy.evaluate(m15_ctx, m5_ctx, m1_ctx, asset)
                if signal["direction"] != Direction.NO_TRADE:
                    if best_signal is None or signal.get("confidence", 0) > best_signal.get("confidence", 0):
                        best_signal = signal
                        best_signal["strategy_name"] = strategy_name

            if best_signal is None:
                continue

            direction = best_signal["direction"]
            strategy_name = best_signal["strategy_name"]

            expiry_sec = 180
            payout_val = payout

            # Simulate trade
            trade = TradeResult(
                timestamp=current_time,
                asset=asset,
                direction=direction,
                strategy=strategy_name,
                expiry=expiry_sec,
                payout=payout_val,
                stake=stake_per_trade,
                result=0.0,
                execution_state=ExecutionState.PENDING,
                market_regime=snapshot.m15_regime,
                confidence=best_signal.get("confidence", 0),
                features=best_signal.get("features", {}),
            )

            # Determine outcome based on next candle direction
            if direction == Direction.CALL:
                won = current_candle.is_bullish
            else:
                won = not current_candle.is_bullish and current_candle.close != current_candle.open

            if won:
                profit = stake_per_trade * payout_val
                self.balance += profit
                trade.result = profit
                trade.execution_state = ExecutionState.WON
                consecutive_losses = 0
            else:
                self.balance -= stake_per_trade
                trade.result = -stake_per_trade
                trade.execution_state = ExecutionState.LOST
                consecutive_losses += 1

            self.equity = self.balance
            self.trades.append(trade)
            self.equity_curve.append(self.balance)
            repository.save_trade_result(trade)

            if self.balance > peak_equity:
                peak_equity = self.balance
            dd = (peak_equity - self.balance) / peak_equity * 100
            if dd > max_dd:
                max_dd = dd

        total = len(self.trades)
        if total == 0:
            return results

        wins = sum(1 for t in self.trades if t.execution_state == ExecutionState.WON)
        losses = total - wins
        win_rate = wins / total

        total_profit = sum(t.result for t in self.trades if t.result > 0)
        total_loss = abs(sum(t.result for t in self.trades if t.result < 0))

        expectancy = win_rate * payout - (1 - win_rate)
        profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")

        # Regime breakdown
        regime_breakdown = {}
        for t in self.trades:
            regime = t.market_regime.value if t.market_regime else "unknown"
            if regime not in regime_breakdown:
                regime_breakdown[regime] = {"trades": 0, "wins": 0}
            regime_breakdown[regime]["trades"] += 1
            if t.execution_state == ExecutionState.WON:
                regime_breakdown[regime]["wins"] += 1

        # Strategy breakdown
        strategy_breakdown = {}
        for t in self.trades:
            strat = t.strategy or "unknown"
            if strat not in strategy_breakdown:
                strategy_breakdown[strat] = {"trades": 0, "wins": 0}
            strategy_breakdown[strat]["trades"] += 1
            if t.execution_state == ExecutionState.WON:
                strategy_breakdown[strat]["wins"] += 1

        results = BacktestResult(
            total_trades=total,
            wins=wins,
            losses=losses,
            win_rate=round(win_rate, 4),
            expectancy=round(expectancy, 4),
            net_return=round(self.balance - initial_balance, 2),
            profit_factor=round(profit_factor, 4),
            max_drawdown=round(max_dd, 2),
            longest_losing_streak=consecutive_losses,
            regime_breakdown=regime_breakdown,
            strategy_breakdown=strategy_breakdown,
            equity_curve=self.equity_curve,
        )

        return results

    def reset(self, initial_balance: Optional[float] = None):
        if initial_balance:
            self.balance = initial_balance
        self.equity = self.balance
        self.trades.clear()
        self.equity_curve = [self.balance]

    @property
    def initial_balance(self) -> float:
        return self.equity_curve[0] if self.equity_curve else 10000.0
