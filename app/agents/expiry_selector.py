"""Expiry selector agent.

Tests and chooses the best expiry for each combination of asset, strategy,
direction, market regime, and volatility band.
"""
from typing import Optional
import statistics

from app.data.schemas import Direction, MarketRegime, TradeResult
from app.data.repository import repository


class ExpirySelector:
    def __init__(self, candidate_expiries: Optional[list[int]] = None):
        from app.config import config, TradingMode
        defaults = [300, 180] if config.mode in (TradingMode.PRACTICE, TradingMode.REAL) else [60, 120, 180, 300]
        self.candidate_expiries = candidate_expiries or defaults

    def select(self, asset: str, strategy: str, direction: Direction,
               market_regime: MarketRegime, confidence: float,
               payout: float) -> dict:
        results = []
        for expiry in self.candidate_expiries:
            edge = repository.get_historical_edge(
                asset, strategy, direction, market_regime, expiry
            )
            total = edge.get("total", 0)
            expectancy = edge.get("expectancy", 0)

            results.append({
                "expiry": expiry,
                "samples": total,
                "expectancy": expectancy,
                "win_rate": edge.get("win_rate", 0),
                "profit_factor": edge.get("profit_factor", 0),
            })

        valid = [r for r in results if r["samples"] >= 30 and r["expectancy"] > 0]

        if not valid:
            valid = [r for r in results if r["expectancy"] > 0]

        if not valid:
            return {
                "selected_expiry": self.candidate_expiries[0],
                "candidates": results,
                "reason": "No historically validated expiry, using default",
            }

        best = max(valid, key=lambda r: r["expectancy"])

        return {
            "selected_expiry": best["expiry"],
            "candidates": results,
            "reason": f"Best expectancy {best['expectancy']:.4f} at {best['expiry']}s",
            "best_expectancy": best["expectancy"],
            "best_win_rate": best["win_rate"],
        }
