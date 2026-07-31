"""Report generation for backtest results."""
import csv
import json
from datetime import datetime
from pathlib import Path

from app.data.schemas import BacktestResult


class ReportGenerator:
    def __init__(self, reports_dir: str = "reports"):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_text(self, result: BacktestResult, title: str = "Backtest Report") -> str:
        lines = [
            "=" * 60,
            f"  {title}",
            f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 60,
            "",
            f"  Total Trades:     {result.total_trades}",
            f"  Wins:             {result.wins}",
            f"  Losses:           {result.losses}",
            f"  Win Rate:         {result.win_rate:.2%}",
            f"  Expectancy:       {result.expectancy:.4f}",
            f"  Net Return:       ${result.net_return:.2f}",
            f"  Profit Factor:    {result.profit_factor:.4f}",
            f"  Max Drawdown:     {result.max_drawdown:.2f}%",
            f"  Longest Loss Streak: {result.longest_losing_streak}",
            "",
            "--- Regime Breakdown ---",
        ]

        for regime, data in result.regime_breakdown.items():
            wr = data["wins"] / data["trades"] if data["trades"] > 0 else 0
            lines.append(f"  {regime:20s}: {data['trades']:4d} trades, {data['wins']:4d} wins ({wr:.1%})")

        lines.extend(["", "--- Strategy Breakdown ---"])
        for strategy, data in result.strategy_breakdown.items():
            wr = data["wins"] / data["trades"] if data["trades"] > 0 else 0
            lines.append(f"  {strategy:25s}: {data['trades']:4d} trades, {data['wins']:4d} wins ({wr:.1%})")

        lines.append("")
        return "\n".join(lines)

    def save_report(self, result: BacktestResult, filename: str = ""):
        if not filename:
            filename = f"backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        text = self.generate_text(result)
        text_path = self.reports_dir / f"{filename}.txt"
        text_path.write_text(text, encoding="utf-8")

        json_path = self.reports_dir / f"{filename}.json"
        json_path.write_text(json.dumps({
            "total_trades": result.total_trades,
            "wins": result.wins,
            "losses": result.losses,
            "win_rate": result.win_rate,
            "expectancy": result.expectancy,
            "net_return": result.net_return,
            "profit_factor": result.profit_factor,
            "max_drawdown": result.max_drawdown,
            "longest_losing_streak": result.longest_losing_streak,
            "regime_breakdown": result.regime_breakdown,
            "strategy_breakdown": result.strategy_breakdown,
            "equity_curve": result.equity_curve,
            "generated": datetime.now().isoformat(),
        }, indent=2), encoding="utf-8")

        print(f"Report saved: {text_path}")
        print(f"Report saved: {json_path}")
