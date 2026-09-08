"""Signal agent - scans assets and generates consolidated signals.

Orchestrates market regime, multi-timeframe, and strategy agents.
"""
from datetime import datetime
from typing import Optional

from app.data.schemas import (
    Candle, Direction, MarketRegime, Signal, Timeframe, EntryTiming, RiskDecision
)
from app.data.repository import repository
from app.agents.market_regime_agent import MarketRegimeAgent
from app.agents.multi_timeframe_agent import MultiTimeframeAgent
from app.agents.entry_timing_agent import EntryTimingAgent
from app.agents.edge_validator_agent import EdgeValidatorAgent
from app.agents.risk_manager_agent import RiskManagerAgent
from app.agents.expiry_selector import ExpirySelector
from app.strategies.sr_bounce import SRBounceStrategy
from app.strategies.trend_continuation import TrendContinuationStrategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.breakout_retest import BreakoutRetestStrategy
from app.config import config, TradingMode


class SignalAgent:
    def __init__(self):
        practice = config.mode == TradingMode.PRACTICE
        entry_kwargs = {"min_wick_to_body_ratio": 0.1, "max_candle_age_ratio": 0.98, "min_age_ratio": 0.1, "min_body_pct": 0.0005} if practice else {"min_wick_to_body_ratio": 1.5}
        self.entry_timing = EntryTimingAgent(config=entry_kwargs)
        self.edge_validator = EdgeValidatorAgent()
        self.risk_manager = RiskManagerAgent()
        self.expiry_selector = ExpirySelector()
        sr_cfg = {"min_confidence": 0.40, "level_distance_atr": 2.5, "min_rejection_wick_ratio": 1.2, "default_expiry": 300} if practice else {"min_confidence": 0.65}
        self.strategies = {
            "sr_bounce": SRBounceStrategy(config=sr_cfg),
            "trend_continuation": TrendContinuationStrategy(),
            "mean_reversion": MeanReversionStrategy(),
            "breakout_retest": BreakoutRetestStrategy(),
        }

    def scan(self, candles_m15: list[Candle], candles_m5: list[Candle],
             candles_m1: list[Candle], asset: str = "",
             account_equity: float = 10000.0) -> dict:
        timestamp = datetime.utcnow()

        candidates = []
        for name, strategy in self.strategies.items():
            signal = strategy.evaluate(candles_m15, candles_m5, candles_m1, asset)
            signal["strategy_name"] = name
            if signal["direction"] == Direction.NO_TRADE:
                continue
            candidates.append(signal)

        rejection_reasons = []
        for signal in sorted(candidates, key=lambda item: item.get("confidence", 0), reverse=True):
            direction = signal["direction"]
            regime = signal.get("market_regime", MarketRegime.UNKNOWN)
            strategy_name = signal["strategy_name"]
            confidence = signal["confidence"]

            expiry_result = self.expiry_selector.select(
                asset, strategy_name, direction, regime, confidence, 0.85
            )

            if signal.get("skip_entry_timing"):
                timing = {"timing": EntryTiming.ENTER_NOW, "rationale": "estrategia confirmo rebote", "enter_now": True, "features": {}}
            else:
                timing = self.entry_timing.evaluate(
                    candles_m1, candles_m5, direction, None, timestamp
                )
            if not timing.get("enter_now", False):
                rejection_reasons.append(
                    f"{strategy_name}: timing {timing.get('rationale', 'not ready')}"
                )
                continue

            edge = self.edge_validator.validate(
                asset, strategy_name, direction, regime, expiry_result["selected_expiry"], 0.85, confidence
            )
            if not edge.get("approved", False):
                rejection_reasons.append(
                    f"{strategy_name}: edge {'; '.join(edge.get('reasons', []))}"
                )
                continue

            risk = self.risk_manager.approve(
                asset, direction, strategy_name, regime, confidence, account_equity
            )
            if risk.get("decision") != RiskDecision.APPROVED:
                rejection_reasons.append(
                    f"{strategy_name}: risk {'; '.join(risk.get('reasons', []))}"
                )
                continue

            return {
                "signal": signal,
                "entry_timing": timing,
                "expiry": expiry_result,
                "edge_validation": edge,
                "risk_approval": risk,
                "asset": asset,
                "timestamp": timestamp.isoformat(),
            }

        return self._no_trade(
            "; ".join(rejection_reasons) if rejection_reasons
            else "No strategy found a valid setup"
        )

    def _no_trade(self, reason: str) -> dict:
        return {
            "signal": {
                "direction": Direction.NO_TRADE,
                "strategy": "no_trade",
                "entry_rationale": reason,
                "confidence": 0.0,
            },
            "multi_timeframe": {"alignment": "unknown"},
            "entry_timing": {"enter_now": False, "rationale": "no_signal"},
            "expiry": {"selected_expiry": 0, "reason": "no_signal"},
            "edge_validation": {"approved": False, "reasons": [reason]},
            "risk_approval": {"decision": "rejected", "reasons": [reason]},
            "asset": "",
            "timestamp": datetime.utcnow().isoformat(),
        }
