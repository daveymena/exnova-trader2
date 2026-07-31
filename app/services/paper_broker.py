"""Paper broker for deterministic simulation.

No external API calls. Simulates order placement, expiry, and results.
"""
from datetime import datetime, timedelta
from typing import Optional
import random

from app.data.schemas import (
    Direction, ExecutionState, TradeResult, TradingMode, MarketRegime
)
from app.data.repository import repository


class PaperBroker:
    def __init__(self, initial_balance: float = 10000.0):
        self.balance = initial_balance
        self.equity = initial_balance
        self.open_trades: list[TradeResult] = []
        self.mode = TradingMode.PAPER

    def buy(self, asset: str, direction: Direction, amount: float,
            expiry_sec: int, strategy: str = "",
            market_regime: str = "",
            confidence: float = 0.0) -> TradeResult:
        now = datetime.utcnow()
        trade_id = f"paper_{now.timestamp()}_{asset}_{direction.value}"

        result = TradeResult(
            timestamp=now,
            asset=asset,
            direction=direction,
            strategy=strategy,
            expiry=expiry_sec,
            payout=0.0,
            stake=amount,
            result=-amount,
            execution_state=ExecutionState.SENT,
            market_regime=MarketRegime(market_regime) if market_regime else None,
            confidence=confidence,
            features={"trade_id": trade_id, "mode": "paper"},
        )

        self.balance -= amount
        self.open_trades.append(result)
        return result

    def resolve_trade(self, trade: TradeResult, won: bool, payout: float) -> TradeResult:
        if won:
            profit = trade.stake * payout
            self.balance += trade.stake + profit
            trade.result = profit
            trade.execution_state = ExecutionState.WON
        else:
            trade.execution_state = ExecutionState.LOST

        trade.payout = payout
        self.equity = self.balance
        self.open_trades = [t for t in self.open_trades if t.timestamp != trade.timestamp]

        repository.save_trade_result(trade)
        return trade

    def expire_all(self, current_prices: dict[str, float],
                   get_payout: callable) -> list[TradeResult]:
        now = datetime.utcnow()
        resolved = []
        still_open = []

        for trade in self.open_trades:
            expiry_time = trade.timestamp + timedelta(seconds=trade.expiry)
            if now < expiry_time:
                still_open.append(trade)
                continue

            price = current_prices.get(trade.asset)
            if price is None:
                trade.execution_state = ExecutionState.UNKNOWN
                still_open.append(trade)
                continue

            payout = get_payout(trade.asset, trade.expiry)
            won = self._simulate_result(trade.direction, payout)
            self.resolve_trade(trade, won, payout)
            resolved.append(trade)

        self.open_trades = still_open
        return resolved

    def _simulate_result(self, direction: Direction, payout: float) -> bool:
        return random.random() < 0.5

    def get_balance(self) -> float:
        return self.balance

    def get_equity(self) -> float:
        return self.equity - sum(t.stake for t in self.open_trades)
