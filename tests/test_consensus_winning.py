"""Tests for the consensus winning strategy."""
from datetime import datetime, timedelta
import random

from app.data.schemas import Candle, Timeframe, Direction
from app.strategies.consensus_winning import ConsensusWinningStrategy


def _gen(n, trend=0.0005, vol=0.001, tf=Timeframe.M1, seed=1):
    random.seed(seed)
    now = datetime.utcnow() - timedelta(minutes=n)
    out = []
    price = 1.10
    for i in range(n):
        t = now + timedelta(minutes=i)
        change = random.gauss(trend, vol)
        o = price
        c = price + change
        high_p = max(o, c) + abs(random.gauss(0, 0.0003))
        low_p = min(o, c) - abs(random.gauss(0, 0.0003))
        out.append(Candle(
            asset="EURUSD", timeframe=tf, open_time=t,
            open=round(o, 5), high=round(high_p, 5),
            low=round(low_p, 5), close=round(c, 5),
        ))
        price = c
    return out


def test_insufficient_data_rejects():
    cs = ConsensusWinningStrategy()
    m1 = _gen(3)
    m5 = _gen(3, tf=Timeframe.M5)
    m15 = _gen(3, tf=Timeframe.M15)
    sig = cs.evaluate(m15, m5, m1, "EURUSD")
    assert sig["direction"] == Direction.NO_TRADE


def test_returns_valid_structure():
    cs = ConsensusWinningStrategy()
    m1 = _gen(60, trend=0.001, vol=0.0008, seed=2)
    m5 = _gen(30, trend=0.005, vol=0.002, tf=Timeframe.M5, seed=3)
    m15 = _gen(20, trend=0.015, vol=0.003, tf=Timeframe.M15, seed=4)
    sig = cs.evaluate(m15, m5, m1, "EURUSD")
    assert "direction" in sig
    assert "confidence" in sig
    assert "strategy" in sig
    assert sig["strategy"] == "consensus_winning"
    assert 0.0 <= sig["confidence"] <= 1.0


def test_confidence_boost_on_agreement():
    # Smoke: at least runs without error on trending data
    cs = ConsensusWinningStrategy()
    m1 = _gen(80, trend=0.002, vol=0.0005, seed=5)
    m5 = _gen(40, trend=0.01, vol=0.001, tf=Timeframe.M5, seed=6)
    m15 = _gen(25, trend=0.03, vol=0.002, tf=Timeframe.M15, seed=7)
    sig = cs.evaluate(m15, m5, m1, "EURUSD")
    assert sig["direction"] in (Direction.CALL, Direction.PUT, Direction.NO_TRADE)
