"""NO_TRADE strategy - returned when no valid opportunity exists."""
from app.data.schemas import Direction, MarketRegime


def no_trade_signal(reason: str = "no_valid_setup") -> dict:
    return {
        "direction": Direction.NO_TRADE,
        "strategy": "no_trade",
        "market_regime": MarketRegime.UNKNOWN,
        "entry_rationale": reason,
        "invalidation": "not_applicable",
        "confidence": 0.0,
        "features": {},
        "expiry": 0,
        "reasons": [reason],
    }
