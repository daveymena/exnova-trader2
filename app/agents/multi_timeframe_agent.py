"""Multi-timeframe analysis agent.

Uses M15 for broad direction, M5 for structure, M1 for entry timing.
Records alignment status and trend direction for each timeframe.
"""
from datetime import datetime
from typing import Optional

from app.data.schemas import Candle, MarketRegime, MultiTimeframeSnapshot
from app.data.repository import repository
from app.agents.market_regime_agent import MarketRegimeAgent


class MultiTimeframeAgent:
    def __init__(self):
        self.regime_agent = MarketRegimeAgent()

    def analyze(self, candles_m15: list[Candle], candles_m5: list[Candle],
                candles_m1: list[Candle], asset: str = "",
                timestamp: Optional[datetime] = None) -> MultiTimeframeSnapshot:
        if timestamp is None:
            timestamp = datetime.utcnow()

        m15_snapshot = self.regime_agent.classify(candles_m15, asset, timestamp)
        m5_snapshot = self.regime_agent.classify(candles_m5, asset, timestamp)
        m1_snapshot = self.regime_agent.classify(candles_m1, asset, timestamp)

        m15_trend = self._trend_from_regime(m15_snapshot.regime)
        m5_trend = self._trend_from_regime(m5_snapshot.regime)
        m1_trend = self._trend_from_regime(m1_snapshot.regime)

        known = [t for t in (m15_trend, m5_trend, m1_trend) if t != "none"]

        if len(known) < 2:
            # Sin al menos dos timeframes con opinion no hay conflicto: no
            # opinar no es contradecirse. Antes "unknown" caia en "conflict"
            # y bloqueaba toda senal en mercados que el clasificador no sabia
            # etiquetar (por ejemplo todas las tendencias bajistas).
            alignment = "neutral"
        elif len(set(known)) > 1:
            alignment = "conflict"
        elif m1_trend == "none":
            alignment = "partial"
        else:
            alignment = "agree"

        snapshot = MultiTimeframeSnapshot(
            timestamp=timestamp,
            asset=asset,
            m15_regime=m15_snapshot.regime,
            m5_regime=m5_snapshot.regime,
            m1_regime=m1_snapshot.regime,
            alignment=alignment,
            m15_trend=m15_trend,
            m5_trend=m5_trend,
            m1_trend=m1_trend,
        )

        repository.save_multi_timeframe_snapshot(snapshot)
        return snapshot

    def _trend_from_regime(self, regime: MarketRegime) -> str:
        if regime in (MarketRegime.TREND_UP,):
            return "up"
        elif regime in (MarketRegime.TREND_DOWN,):
            return "down"
        return "none"
