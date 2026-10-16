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


class TestWilsonLowerBound:
    """wilson_lower_bound se usaba sin estar definida: el EdgeValidator
    reventaba con NameError en cuanto habia >=3 operaciones reales y el bot
    dejaba de operar en silencio."""

    def test_funcion_existe_y_es_monotona(self):
        from app.data.repository import wilson_lower_bound
        assert wilson_lower_bound(3, 3) < wilson_lower_bound(30, 30)
        assert wilson_lower_bound(30, 30) < wilson_lower_bound(100, 100)

    def test_muestra_pequena_no_permite_prometer_100(self):
        from app.data.repository import wilson_lower_bound
        assert wilson_lower_bound(3, 3) < 0.6

    def test_sin_datos_devuelve_cero(self):
        from app.data.repository import wilson_lower_bound
        assert wilson_lower_bound(0, 0) == 0.0

    def test_get_historical_edge_no_revienta(self, tmp_path):
        from app.data.repository import Repository
        from app.data.schemas import (
            TradeResult, ExecutionState, ResolutionSource,
        )
        from datetime import datetime, timedelta

        # Base propia: el repository es un singleton sobre data/trading_bot.db
        # y acumularia operaciones de un test a otro.
        repo = Repository(db_path=str(tmp_path / "edge.db"))
        repo.migrate()
        for i in range(4):
            trade = TradeResult(
                timestamp=datetime.utcnow() - timedelta(minutes=i + 1),
                asset="EURUSD", direction=Direction.CALL,
                strategy="consensus_winning", expiry=180, payout=0.85,
                stake=10.0, result=8.5 if i % 2 else -10.0,
                execution_state=(ExecutionState.WON if i % 2
                                 else ExecutionState.LOST),
                market_regime=MarketRegime.TREND_UP,
                resolution_source=ResolutionSource.BROKER,
            )
            repo.save_trade_result(trade)

        edge = repo.get_historical_edge(
            "EURUSD", "consensus_winning", Direction.CALL,
            MarketRegime.TREND_UP, 180,
        )
        assert edge["total"] == 4
        assert edge["win_rate"] == 0.5
        assert "win_rate_lower_95" in edge
        assert edge["break_even_wr"] > 0


class TestUnidadesDeRiesgo:
    """El comentario decia '0.5 = 0.5% of equity' pero se usaba como fraccion.

    Con 0.5 interpretado como fraccion, el tope por operacion era el 50% de
    la cuenta: $5.000 sobre $10.000. En binarias eso es ruina en una sola
    racha. Estos tests fijan que max_position_pct sea una fraccion de verdad.
    """

    def test_max_position_pct_es_porcentaje_no_fraccion_invertida(self):
        risk = RiskManagerAgent()
        assert 0 < risk.max_position_pct <= 0.05, (
            f"max_position_pct={risk.max_position_pct} debe ser un porcentaje "
            "pequeno expresado como fraccion (0.5% = 0.005)"
        )

    def test_stake_nunca_supera_el_tope_absoluto(self):
        risk = RiskManagerAgent()
        risk.max_position_pct = 0.5  # incluso si alguien lo configura mal
        result = risk.approve(
            "EURUSD", Direction.CALL, "consensus_winning",
            MarketRegime.TREND_UP, 0.95, 100000.0,
        )
        assert result["stake"] <= risk.max_stake_absolute

    def test_stake_es_proporcional_a_la_cuenta(self):
        risk = RiskManagerAgent()
        chica = risk.approve("EURUSD", Direction.CALL, "s",
                             MarketRegime.TREND_UP, 0.7, 1000.0)
        grande = risk.approve("EURUSD", Direction.CALL, "s",
                              MarketRegime.TREND_UP, 0.7, 100000.0)
        assert chica["stake"] < grande["stake"]

    def test_tope_absoluto_manda_sobre_cuentas_grandes(self):
        """Con $1.000.000 el 0.5% serian $5.000: el tope duro debe cortar."""
        risk = RiskManagerAgent()
        result = risk.approve(
            "EURUSD", Direction.CALL, "consensus_winning",
            MarketRegime.TREND_UP, 0.95, 1000000.0,
        )
        assert result["stake"] == risk.max_stake_absolute
        assert result["stake_capped_absolute"] is True
