"""Smoke tests for the specialized trading agent."""
import random
from datetime import datetime, timedelta

from app.agents.trading_agent import TradingAgent, StrategyParams
from app.data.schemas import Candle, Timeframe, Direction


def _candles(n, tf, tf_min):
    out = []
    t = datetime.utcnow() - timedelta(minutes=n * tf_min)
    p = 1.1
    for i in range(n):
        o = p
        c = p + random.uniform(-0.001, 0.001)
        h = max(o, c) + 0.0005
        l = min(o, c) - 0.0005
        out.append(Candle("EURUSD-OTC", tf, t, o, h, l, c))
        t += timedelta(minutes=tf_min)
        p = c
    return out


def test_analyze_and_decide():
    agent = TradingAgent()
    m15 = _candles(60, Timeframe.M15, 15)
    m5 = _candles(200, Timeframe.M5, 5)
    m1 = _candles(500, Timeframe.M1, 1)
    analysis = agent.analyze_market(m15, m5, m1, "EURUSD-OTC")
    assert "direction" in analysis
    decision = agent.decide(analysis)
    assert "action" in decision
    assert decision["action"] in ("BUY", "SELL", "HOLD")


def test_self_improve_insufficient():
    agent = TradingAgent()
    res = agent.self_improve()
    assert "changes" in res
    assert res.get("reason") == "muestra_insuficiente"


def test_status():
    agent = TradingAgent()
    st = agent.status()
    assert "account" in st
    assert "performance" in st
