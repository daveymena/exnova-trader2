"""Signal agent - scans assets and generates consolidated signals.

Una sola fuente de senales: `ConsensusWinningStrategy`, que hace votar a las
estrategias del sistema solo en los regimenes de mercado donde la auditoria
(scripts/research_strategy_audit.py) demostro que tienen edge. No hay
fallback: si el consenso no aprueba, no se opera.
"""
from datetime import datetime

from app.data.schemas import Candle, Direction, MarketRegime, EntryTiming
from app.agents.market_regime_agent import MarketRegimeAgent
from app.agents.multi_timeframe_agent import MultiTimeframeAgent
from app.agents.entry_timing_agent import EntryTimingAgent
from app.agents.edge_validator_agent import EdgeValidatorAgent
from app.agents.risk_manager_agent import RiskManagerAgent
from app.agents.expiry_selector import ExpirySelector
from app.strategies.consensus_winning import ConsensusWinningStrategy
from app.config import config, TradingMode


class SignalAgent:
    def __init__(self):
        practice = config.mode == TradingMode.PRACTICE
        entry_kwargs = (
            {"min_wick_to_body_ratio": 0.1, "max_candle_age_ratio": 0.98,
             "min_age_ratio": 0.1, "min_body_pct": 0.0005}
            if practice else {"min_wick_to_body_ratio": 1.5}
        )
        self.entry_timing = EntryTimingAgent(config=entry_kwargs)
        self.edge_validator = EdgeValidatorAgent()
        self.risk_manager = RiskManagerAgent()
        self.expiry_selector = ExpirySelector()
        self.mtf_agent = MultiTimeframeAgent()
        self.market_regime = MarketRegimeAgent()

        self.strategy = ConsensusWinningStrategy(config={
            "min_confidence": config.strategy_min_confidence,
            "min_votes": 2,
            "high_conviction_threshold": 0.70,
            "unknown_conviction": 0.80,
            "sr_bounce": {
                "min_confidence": 0.40,
                "level_distance_atr": 2.5,
                "min_rejection_wick_ratio": 1.2,
                "default_expiry": 300,
            },
            "breakout_direct": {
                "min_breakout_body_pct": 0.4,
                "min_breakout_distance_atr": 1.0,
                "min_confidence": 0.55,
                "default_expiry": 180,
            },
        })

    def scan(self, candles_m15: list[Candle], candles_m5: list[Candle],
             candles_m1: list[Candle], asset: str = "",
             account_equity: float = 10000.0) -> dict:
        timestamp = datetime.utcnow()

        signal = self.strategy.evaluate(candles_m15, candles_m5, candles_m1, asset)
        signal["strategy_name"] = "consensus_winning"

        if signal["direction"] == Direction.NO_TRADE:
            return self._no_trade(signal.get("entry_rationale", "No valid setup"))

        direction = signal["direction"]
        regime = signal.get("market_regime", MarketRegime.UNKNOWN)
        strategy_name = signal["strategy_name"]
        confidence = signal["confidence"]

        expiry_result = self.expiry_selector.select(
            asset, strategy_name, direction, regime, confidence, 0.85
        )
        # La estrategia propone su propia expiracion; el selector solo ajusta.
        own_expiry = signal.get("expiry") or 0
        if own_expiry > 0:
            expiry_result["selected_expiry"] = own_expiry

        if signal.get("skip_entry_timing"):
            timing = {
                "timing": EntryTiming.ENTER_NOW,
                "rationale": "estrategia confirmo rebote",
                "enter_now": True,
                "features": {},
            }
        else:
            timing = self.entry_timing.evaluate(
                candles_m1, candles_m5, direction, None, timestamp
            )

        selected_expiry = expiry_result["selected_expiry"]
        edge = self.edge_validator.validate(
            asset, strategy_name, direction, regime, selected_expiry, 0.85, confidence
        )

        risk = self.risk_manager.approve(
            asset, direction, strategy_name, regime, confidence, account_equity
        )

        return {
            "signal": signal,
            "entry_timing": timing,
            "expiry": expiry_result,
            "edge_validation": edge,
            "risk_approval": risk,
            "asset": asset,
            "timestamp": timestamp.isoformat(),
        }

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
