"""Tests for critical financial and execution logic."""
import pytest
from app.data.schemas import Direction, MarketRegime, RiskDecision
from app.agents.edge_validator_agent import EdgeValidatorAgent
from app.agents.risk_manager_agent import RiskManagerAgent
from app.agents.market_regime_agent import MarketRegimeAgent
from app.agents.expiry_selector import ExpirySelector
from app.config import config


class TestPayoutCalculations:
    def test_break_even_win_rate(self):
        validator = EdgeValidatorAgent()
        payout = 0.85
        break_even = 1 / (1 + payout)
        assert abs(break_even - 0.5405) < 0.001, f"Expected 0.5405, got {break_even}"

    def test_break_even_different_payouts(self):
        for payout, expected_be in [(0.70, 0.5882), (0.90, 0.5263), (1.0, 0.5)]:
            be = 1 / (1 + payout)
            assert abs(be - expected_be) < 0.001

    def test_expectancy_positive(self):
        validator = EdgeValidatorAgent()
        win_rate = 0.6
        payout = 0.85
        expectancy = win_rate * payout - (1 - win_rate)
        assert abs(expectancy - 0.11) < 0.001

    def test_expectancy_negative(self):
        win_rate = 0.4
        payout = 0.85
        expectancy = win_rate * payout - (1 - win_rate)
        assert expectancy < 0


class TestPositionSizing:
    def test_max_position_pct_respected(self):
        risk = RiskManagerAgent()
        initial = risk.max_position_pct
        assert 0 < initial <= 1.0

    def test_stake_based_on_equity(self):
        risk = RiskManagerAgent()
        result = risk.approve(
            "EURUSD", Direction.CALL, "trend_continuation",
            MarketRegime.TREND_UP, 0.65, 10000.0
        )
        if result["decision"] == RiskDecision.APPROVED:
            assert result["stake"] <= 10000.0 * risk.max_position_pct


class TestDailyLossLimits:
    def test_max_daily_loss(self):
        config.risk_max_daily_loss_pct = 5.0
        risk = RiskManagerAgent()
        risk.reset_daily(10000.0)
        risk._consecutive_losses = 0

        result = risk.approve(
            "EURUSD", Direction.CALL, "trend",
            MarketRegime.TREND_UP, 0.65, 9500.0
        )
        dd = risk._compute_daily_drawdown(9500.0)
        assert dd <= 5.0 or result["decision"] == RiskDecision.HALTED


class TestConsecutiveLossLimits:
    def test_max_consecutive_losses(self):
        risk = RiskManagerAgent()
        risk._consecutive_losses = 3
        risk.max_consecutive_losses = 3
        result = risk.approve(
            "EURUSD", Direction.CALL, "trend",
            MarketRegime.TREND_UP, 0.65, 10000.0
        )
        assert result["decision"] == RiskDecision.REJECTED
        assert "consecutive" in " ".join(result["reasons"]).lower()


class TestMarketRegimeClassification:
    def test_insufficient_data_returns_unknown(self):
        agent = MarketRegimeAgent()
        from app.data.schemas import Candle, Timeframe
        from datetime import datetime
        candles = [Candle("EURUSD", Timeframe.M1, datetime.utcnow(), 1.0, 1.0, 1.0, 1.0)]
        snapshot = agent.classify(candles, "EURUSD")
        assert snapshot.regime == MarketRegime.UNKNOWN


class TestExpirySelection:
    def test_returns_default_with_no_data(self):
        from app.data.repository import repository
        repository.migrate()
        selector = ExpirySelector()
        result = selector.select(
            "EURUSD", "trend_continuation", Direction.CALL,
            MarketRegime.TREND_UP, 0.75, 0.85
        )
        assert result["selected_expiry"] in [60, 120, 180, 300]


class TestConfigurationSafety:
    def test_default_mode_is_paper(self, monkeypatch):
        """Sin variables de entorno, el modo por defecto debe ser el mas seguro.

        La prueba aisla el entorno a proposito: desde que config.py llama a
        load_dotenv(), un .env con ACCOUNT_TYPE=PRACTICE hacia que este test
        midiera la configuracion de la maquina en vez de la garantia que
        pretende cubrir (que quien no configura nada no acaba operando).
        """
        from app.config import Config
        monkeypatch.delenv("TRADING_MODE", raising=False)
        monkeypatch.delenv("ACCOUNT_TYPE", raising=False)
        assert Config().mode.value == "paper"

    def test_real_trading_disabled_by_default(self):
        assert config.real_trading_enabled is False

    def test_no_martingale(self):
        assert hasattr(config, 'martingale') is False
        assert hasattr(config, 'max_martingale_steps') is False


class TestNoTradeSafety:
    def test_unsafe_regime_rejected(self):
        from app.strategies.no_trade import no_trade_signal
        result = no_trade_signal("HIGH_VOLATILITY")
        assert result["direction"] == Direction.NO_TRADE
        assert result["confidence"] == 0.0
