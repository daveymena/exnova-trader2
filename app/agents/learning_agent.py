"""Learning agent - offline analysis only.

Stores every candidate signal, executed trades, rejected signals.
Runs analysis offline. Never modifies config automatically.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from collections import defaultdict

from app.data.schemas import TradeResult, TradeDecision, Signal, Direction
from app.data.repository import repository


class LearningAgent:
    def __init__(self, base_dir: str = "data"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def analyze_performance(self) -> dict:
        trades = repository.get_trade_results(limit=5000)
        if not trades:
            return {"status": "no_trades", "recommendations": []}

        total = len(trades)
        wins = sum(1 for t in trades if t.execution_state.value == "won")
        losses = total - wins
        win_rate = wins / total if total > 0 else 0

        strategy_perf = defaultdict(lambda: {"trades": 0, "wins": 0, "total_result": 0})
        for t in trades:
            strat = t.strategy or "unknown"
            strategy_perf[strat]["trades"] += 1
            if t.execution_state.value == "won":
                strategy_perf[strat]["wins"] += 1
            strategy_perf[strat]["total_result"] += t.result

        recommendations = []
        for strat, perf in strategy_perf.items():
            if perf["trades"] >= 30:
                wr = perf["wins"] / perf["trades"]
                if wr < 0.4:
                    recommendations.append(
                        f"DISABLE {strat}: win rate {wr:.1%} below threshold"
                    )
                elif perf["total_result"] < 0:
                    recommendations.append(
                        f"REVIEW {strat}: negative total return {perf['total_result']:.2f}"
                    )

        return {
            "status": "analyzed",
            "total_trades": total,
            "win_rate": round(win_rate, 4),
            "strategy_performance": dict(strategy_perf),
            "recommendations": recommendations,
            "analysis_time": datetime.utcnow().isoformat(),
        }

    def detect_drift(self, strategy: str, window: int = 100) -> dict:
        trades = repository.get_trade_results(strategy=strategy, limit=window * 2)
        if len(trades) < window:
            return {"status": "insufficient_data", "samples": len(trades)}

        recent = trades[:window]
        older = trades[window:window * 2]

        recent_wr = sum(1 for t in recent if t.execution_state.value == "won") / len(recent)
        older_wr = sum(1 for t in older if t.execution_state.value == "won") / len(older) if older else 0

        drift = recent_wr - older_wr

        return {
            "status": "analyzed",
            "strategy": strategy,
            "recent_win_rate": round(recent_wr, 4),
            "older_win_rate": round(older_wr, 4),
            "drift": round(drift, 4),
            "drift_detected": drift < -0.05,
            "recommendation": "PAUSE_STRATEGY" if drift < -0.1 else "MONITOR" if drift < -0.05 else "NORMAL",
        }

    def save_analysis_report(self, filename: str = "learning_analysis.json"):
        perf = self.analyze_performance()
        report_path = self.base_dir / filename
        report_path.write_text(json.dumps(perf, indent=2, default=str), encoding="utf-8")
        return str(report_path)
