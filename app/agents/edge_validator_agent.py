"""Edge validator agent.

Validates whether similar historical setups have positive payout-adjusted
statistical edge. This is the gatekeeper before any trade execution.
"""
import statistics
from datetime import datetime
from typing import Optional

from app.data.schemas import (
    Direction, MarketRegime, TradeResult, ExecutionState
)
from app.data.repository import repository
from app.config import config, TradingMode


class EdgeValidatorAgent:
    def __init__(self):
        self.min_sample_size = config.backtest_min_sample_size
        self.min_payout = config.backtest_min_payout
        self.safety_margin = config.backtest_safety_margin
        self.calibrated_confidence = {}

    def validate(self, asset: str, strategy: str, direction: Direction,
                 market_regime: MarketRegime, expiry: int, payout: float,
                 confidence: float, entry_timing_type: str = "enter_now") -> dict:
        reasons = []
        warnings = []
        is_practice = config.mode == TradingMode.PRACTICE

        if payout < self.min_payout and not is_practice:
            reasons.append(f"Payout {payout:.2f} below minimum {self.min_payout}")
            return self._reject(reasons)

        edge_data = repository.get_historical_edge(
            asset, strategy, direction, market_regime, expiry
        )
        total = edge_data.get("total", 0)

        min_needed = 3 if is_practice else self.min_sample_size
        if total < min_needed:
            if is_practice:
                return {
                    "approved": True,
                    "reasons": [],
                    "warnings": ["Practice mode: bypassing historical edge"],
                    "edge_data": edge_data,
                    "safety_margin_applied": 0,
                    "break_even_wr": 0,
                    "required_wr": 0,
                    "current_wr": 0,
                    "expectancy": 0,
                    "profit_factor": 0,
                }
            reasons.append(
                f"Insufficient edge data: {total} samples (need {min_needed})"
            )
            return self._reject(reasons, {"samples": total, "needed": min_needed})

        win_rate = edge_data["win_rate"]
        expectancy = edge_data["expectancy"]
        break_even = edge_data["break_even_wr"]
        avg_payout = edge_data.get("avg_payout", payout)

        safety_margin_wr = break_even + self.safety_margin
        if win_rate < safety_margin_wr:
            reasons.append(
                f"Win rate {win_rate:.4f} below safety threshold {safety_margin_wr:.4f} "
                f"(break-even {break_even:.4f} + margin {self.safety_margin:.2f})"
            )
            return self._reject(reasons, edge_data)

        if expectancy <= 0:
            reasons.append(f"Expected value {expectancy:.4f} is not positive")
            return self._reject(reasons, edge_data)

        if avg_payout < self.min_payout:
            reasons.append(
                f"Average payout {avg_payout:.2f} below minimum {self.min_payout}"
            )
            return self._reject(reasons, edge_data)

        profit_factor = edge_data.get("profit_factor", 0)
        if profit_factor < 1.0:
            warnings.append(f"Profit factor {profit_factor:.4f} below 1.0")

        return {
            "approved": True,
            "reasons": [],
            "warnings": warnings,
            "edge_data": edge_data,
            "safety_margin_applied": self.safety_margin,
            "break_even_wr": break_even,
            "required_wr": safety_margin_wr,
            "current_wr": win_rate,
            "expectancy": expectancy,
            "profit_factor": profit_factor,
        }

    def _reject(self, reasons: list, data: Optional[dict] = None) -> dict:
        return {
            "approved": False,
            "reasons": reasons,
            "warnings": [],
            "edge_data": data or {},
            "safety_margin_applied": self.safety_margin,
            "break_even_wr": 0,
            "required_wr": 0,
            "current_wr": 0,
            "expectancy": 0,
            "profit_factor": 0,
        }
