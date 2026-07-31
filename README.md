# Exnova Trading Bot - Multi-Agent Trading Research Platform

A modular, research-first intelligent trading platform for IQ Option / Exnova.
Built for backtesting, paper trading, and practice/demo trading.
**Real-money trading is disabled by default.**

## ⚠️ Important Disclaimer

**This software is for research and educational purposes only.**
- No profitability is promised or implied.
- Past performance does not guarantee future results.
- Real-money trading carries significant financial risk.
- The developers assume no liability for any financial losses.

## Quick Start

```bash
# 1. Clone or navigate to the project
cd C:\Users\ADMIN\Videos\Exnova-Trading-Bot

# 2. Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and configure environment
copy .env.example .env
# Edit .env: defaults are safe (PAPER mode)

# 5. Initialize database
python -c "from app.data.repository import repository; repository.migrate()"

# 6. Run backtest with sample data
python -c "
from app.research.backtester import Backtester
from app.research.reporting import ReportGenerator
bt = Backtester()
result = bt.run([], [], [])  # Use mock candles
ReportGenerator().save_report(result, 'sample_backtest')
"

# 7. Run paper trading bot
python -m app.main
```

## Modes

| Mode | Description | Configuration |
|---|---|---|
| `paper` | Deterministic simulation, no broker connection | `TRADING_MODE=paper` (default) |
| `practice` | Connects to broker demo account | `TRADING_MODE=practice` + credentials |
| `real` | Real money trading | `TRADING_MODE=real` + `REAL_TRADING_ENABLED=true` |

## Project Structure

```
project/
├── app/
│   ├── main.py              # Orchestrator
│   ├── config.py            # Centralized configuration
│   ├── settings/            # Default settings
│   ├── agents/              # Multi-agent system
│   │   ├── market_regime_agent.py
│   │   ├── multi_timeframe_agent.py
│   │   ├── signal_agent.py
│   │   ├── entry_timing_agent.py
│   │   ├── edge_validator_agent.py
│   │   ├── risk_manager_agent.py
│   │   ├── expiry_selector.py
│   │   ├── ai_auditor_agent.py
│   │   └── learning_agent.py
│   ├── strategies/          # Trading strategies
│   │   ├── trend_continuation.py
│   │   ├── mean_reversion.py
│   │   ├── breakout_retest.py
│   │   └── no_trade.py
│   ├── research/            # Backtesting & research
│   │   ├── backtester.py
│   │   └── reporting.py
│   ├── data/                # Data layer
│   │   ├── schemas.py
│   │   └── repository.py
│   ├── services/            # Broker adapters
│   │   └── paper_broker.py
│   └── dashboard/
├── tests/                   # Test suite
├── data/                    # Database & data files
├── logs/                    # Log files
├── reports/                 # Generated reports
├── .env.example
├── ARCHITECTURE.md
├── AUDIT_REPORT.md
└── requirements.txt
```

## How It Works

1. **Market Data** - Normalized candles from broker API or local storage
2. **Market Regime** - Deterministic classification (TREND_UP/DOWN, RANGE, HIGH_VOLATILITY, etc.)
3. **Multi-Timeframe** - M15 for direction, M5 for structure, M1 for entry
4. **Strategy** - Three families: trend continuation, mean reversion, breakout/retest
5. **Entry Timing** - Validates candle confirmation, distance, latency
6. **Edge Validation** - Checks historical statistical edge for each setup bucket
7. **Risk Manager** - Final deterministic veto (position sizing, drawdown limits, cooldowns)
8. **AI Auditor** - Optional non-authoritative explanation layer
9. **Execution** - Paper broker or practice/demo adapter

## Key Safety Features

- **No martingale** - Removed entirely from the codebase
- **No automatic stake increases** - Fixed fractional position sizing
- **Paper mode by default** - No broker connection required
- **Real mode gated** - Requires explicit `REAL_TRADING_ENABLED=true`
- **Edge gatekeeper** - Trades rejected without sufficient historical evidence
- **Risk veto** - Risk manager has final say on every trade
- **Kill switch** - Immediate halt capability
- **Full audit logging** - Every decision recorded

## Running a Backtest

```python
from app.research.backtester import Backtester
from app.research.reporting import ReportGenerator
from app.data.repository import repository

repository.migrate()

bt = Backtester(initial_balance=10000)
# In production, load real candle data from the database
result = bt.run(mock_m15_candles, mock_m5_candles, mock_m1_candles)

ReportGenerator().save_report(result, "my_backtest")
print(ReportGenerator().generate_text(result))
```

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## Known Limitations

- Requires historical trade data for edge validation to function (starts cold)
- Strategies use simple deterministic rules (configurable thresholds)
- Broker integration (IQ Option Adapter) requires separate setup
- AI Auditor is optional and requires an API key
- Dashboard is currently CLI-only (web UI pending)

## First Recommended Research Experiment

Run a backtest on a single asset with the trend continuation strategy using 3 months
of M1/M5/M15 data. Compare results by:
- Market regime (trending vs ranging periods)
- Hour of day (session behavior)
- Expiry (60s vs 180s vs 300s)

This will establish baseline expectancy for the simplest strategy before adding
reversal or breakout setups.
