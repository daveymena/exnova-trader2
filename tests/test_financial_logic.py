"""Tests for critical financial and execution logic."""
from datetime import datetime

import pytest

from app.data.schemas import (
    DataSource, Direction, ExecutionState, MarketRegime, ResolutionSource,
    RiskDecision, TradeResult,
)
from app.agents.edge_validator_agent import EdgeValidatorAgent
from app.agents.risk_manager_agent import RiskLimits, RiskManagerAgent
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
    """El tamano esta acotado por un PORCENTAJE del equity.

    CORREGIDO, Y EL MOTIVO IMPORTA. El test antiguo hacia:

        assert result["stake"] <= 10000.0 * risk.max_position_pct

    con `max_position_pct = 0.5`, o sea una cota de 5.000 sobre una cuenta de
    10.000: permitia apostar el 50% del capital en UNA operacion. Ese era
    exactamente el defecto #1 de `app/NOT_PRODUCTION_READY.md` -- el codigo
    hacia `max_position_pct * confidence` sobre el equity -- y el test no lo
    detectaba porque reproducia la misma interpretacion equivocada. Un test que
    codifica el bug no lo encuentra: lo blinda.

    `max_position_pct` es un porcentaje (0.5 == 0.5%), asi que la cota correcta
    es `equity * pct / 100`.
    """

    def test_max_position_pct_es_un_porcentaje_sano(self):
        risk = RiskManagerAgent()
        pct = risk.limits.max_position_pct
        # Un porcentaje por operacion tiene que ser pequeno. Si alguien lo pone
        # a 50 "porque es una fraccion", este test lo para.
        assert 0 < pct <= 5.0, f"max_position_pct={pct} no parece un porcentaje"

    def test_stake_dentro_de_la_cota_porcentual(self):
        equity = 10000.0
        risk = RiskManagerAgent()
        result = risk.approve(
            "EURUSD", Direction.CALL, "trend_continuation",
            MarketRegime.TREND_UP, 0.65, equity
        )
        if result["decision"] == RiskDecision.APPROVED:
            cota = equity * risk.limits.max_position_pct / 100.0
            assert result["stake"] <= cota, (
                f"stake {result['stake']} supera {cota} "
                f"({risk.limits.max_position_pct}% de {equity})")
            assert result["stake"] >= risk.limits.min_stake
            assert result["stake"] <= risk.limits.max_stake

    def test_regresion_no_confundir_porcentaje_con_fraccion(self):
        """Guarda explicita del defecto #1.

        Con 0.5% sobre 10.000 la cota es 50. La interpretacion antigua daba
        5.000. Se comprueba el numero concreto, no la relacion, para que un
        cambio de unidades no pase desapercibido.
        """
        risk = RiskManagerAgent(limits=RiskLimits(max_position_pct=0.5))
        result = risk.approve(
            "EURUSD", Direction.CALL, "trend", MarketRegime.TREND_UP, 0.65, 10000.0)
        if result["decision"] == RiskDecision.APPROVED:
            assert result["stake"] <= 50.0, (
                f"stake {result['stake']}: max_position_pct se esta tratando "
                f"como fraccion (0.5 == 50%) en vez de como porcentaje (0.5%)")

    def test_stake_fuera_de_limites_se_rechaza_no_se_recorta(self):
        """Fuera de limites -> RECHAZADO.

        Decision de diseno: recortar en silencio un stake que el gestor no
        autorizo es operar con un tamano que nadie aprobo. Se rechaza y se
        cuenta, para que el rechazo sea visible.
        """
        risk = RiskManagerAgent(limits=RiskLimits(min_stake=500.0, max_stake=600.0))
        result = risk.approve(
            "EURUSD", Direction.CALL, "trend", MarketRegime.TREND_UP, 0.65, 10000.0)
        assert result["decision"] == RiskDecision.REJECTED
        assert risk.state()["rejected_limits"] >= 1


class TestDailyLossLimits:
    def test_max_daily_loss_para_la_sesion(self):
        """Al superar la perdida diaria maxima la decision es HALTED."""
        risk = RiskManagerAgent(limits=RiskLimits(max_daily_loss_pct=5.0))
        risk.reset_daily(10000.0)

        # 4.9% de caida: por debajo del limite, se sigue operando.
        ok = risk.approve("EURUSD", Direction.CALL, "trend",
                          MarketRegime.TREND_UP, 0.65, 9510.0)
        assert ok["decision"] != RiskDecision.HALTED

        # 6% de caida: por encima, la sesion se para.
        halted = risk.approve("EURUSD", Direction.CALL, "trend",
                              MarketRegime.TREND_UP, 0.65, 9400.0)
        assert halted["decision"] == RiskDecision.HALTED
        assert risk.state()["day_halted"] is True

    def test_drawdown_publico(self):
        """`state()` expone la caida; el test no entra en metodos privados."""
        risk = RiskManagerAgent()
        risk.reset_daily(10000.0)
        st = risk.state()
        assert st["day_start_equity"] == 10000.0


class TestConsecutiveLossLimits:
    """El corte por racha se prueba metiendo PERDIDAS REALES, no tocando
    atributos internos.

    El test antiguo hacia `risk._consecutive_losses = 3`. Al reescribir el
    agente el contador paso a `risk.s.consecutive_losses`, asi que la asignacion
    creaba un atributo nuevo que nadie leia y el agente veia cero perdidas:
    el test fallaba aunque el codigo fuera correcto. Acoplarse a internals hace
    que los tests mientan en las dos direcciones.
    """

    @staticmethod
    def _perdida() -> TradeResult:
        return TradeResult(
            timestamp=datetime.utcnow(), asset="EURUSD-OTC",
            direction=Direction.CALL, strategy="trend", expiry=180,
            payout=0.85, stake=10.0, result=-10.0,
            execution_state=ExecutionState.LOST,
            market_regime=MarketRegime.RANGE,
            resolution_source=ResolutionSource.CANDLE,
            data_source=DataSource.CSV,
        )

    def test_max_consecutive_losses_rechaza(self):
        risk = RiskManagerAgent(limits=RiskLimits(
            max_consecutive_losses=3, halt_day_after_consecutive_losses=6))
        risk.reset_daily(10000.0)

        def motivo() -> str:
            return " ".join(risk.approve(
                "EURUSD", Direction.CALL, "trend",
                MarketRegime.TREND_UP, 0.65, 10000.0)["reasons"]).lower()

        for _ in range(2):
            risk.on_trade_opened(self._perdida())
            risk.on_trade_closed(self._perdida())
        assert risk.state()["consecutive_losses"] == 2
        # Con 2 perdidas el veto por racha (limite 3) NO debe dispararse. Se
        # comprueba el MOTIVO y no la decision, porque despues de perder entra
        # en juego el anti-martingala, que puede rechazar por su cuenta: son dos
        # reglas distintas y aqui solo interesa que la de rachas no se adelante.
        assert "consecutiv" not in motivo()

        risk.on_trade_opened(self._perdida())
        risk.on_trade_closed(self._perdida())
        assert risk.state()["consecutive_losses"] == 3

        result = risk.approve("EURUSD", Direction.CALL, "trend",
                              MarketRegime.TREND_UP, 0.65, 10000.0)
        assert result["decision"] == RiskDecision.REJECTED
        assert "consecutiv" in " ".join(result["reasons"]).lower()

    def test_anti_martingala_no_deja_subir_el_stake_tras_perder(self):
        """Regla aparte, probada aparte: tras una perdida no se sube el stake.

        Es la invariante que `AGENTS.md` exige ("no martingala") y la unica que
        impide que el motor de mejora continua -- o un LLM -- escale el tamano
        justo cuando la racha va mal, que es como se arruina una cuenta.

        Se pone `last_stake` muy por debajo de lo que el sizing va a calcular:
        ese es el escenario natural de martingala (el trade anterior fue pequeno
        y ahora se quiere apostar mas justo despues de perder). No se tocan
        `min_stake`/`max_stake` porque el veto de limites se evalua ANTES que el
        anti-martingala y enmascararia la regla que se quiere probar.
        """
        risk = RiskManagerAgent(limits=RiskLimits(max_consecutive_losses=10))
        risk.reset_daily(10000.0)
        base = risk.approve("EURUSD", Direction.CALL, "trend",
                            MarketRegime.TREND_UP, 0.65, 10000.0)
        assert base["decision"] == RiskDecision.APPROVED
        assert base["stake"] > 1.0, "el sizing base debe superar 1 para ejercitar la regla"

        risk.s.last_stake = 1.0        # trade anterior, pequeno
        risk.s.consecutive_losses = 1  # ... y se perdio

        out = risk.approve("EURUSD", Direction.CALL, "trend",
                           MarketRegime.TREND_UP, 0.65, 10000.0)
        assert out["decision"] == RiskDecision.REJECTED, out
        assert "martingala" in " ".join(out["reasons"]).lower()

    def test_el_stake_puede_escalar_con_la_cuenta(self):
        """Subir el stake es legitimo cuando la CUENTA crecio, no cuando se perdio.

        La invariante real de `_check_no_martingale` tiene dos clausulas: no subir
        tras una perdida, y no ganar PESO RELATIVO sobre el equity. Un salto de
        1.0 a 10.0 con la cuenta plana incumple la segunda, y debe incumplirla.
        Lo que si tiene que permitirse es escalar proporcionalmente: si el dia
        empezo con 10.000 y se apostaba 10 (0.1%), con 20.000 se puede apostar
        20 (0.1%) -- mismo riesgo relativo, cuenta mas grande.

        Sin este test el anti-martingala pareceria correcto aunque bloqueara todo
        crecimiento legitimo, que es el falso positivo que aparecio cuando el
        motor aplicaba el multiplicador del setup dos veces.
        """
        risk = RiskManagerAgent(limits=RiskLimits(max_consecutive_losses=10))
        risk.reset_daily(10000.0)
        base = risk.approve("EURUSD", Direction.CALL, "trend",
                            MarketRegime.TREND_UP, 0.65, 10000.0)
        assert base["decision"] == RiskDecision.APPROVED

        # La cuenta se duplica; el stake anterior se mantiene como referencia.
        risk.s.last_stake = base["stake"]
        risk.s.consecutive_losses = 0
        out = risk.approve("EURUSD", Direction.CALL, "trend",
                           MarketRegime.TREND_UP, 0.65, 20000.0)
        assert out["decision"] == RiskDecision.APPROVED, out
        assert out["stake"] >= base["stake"], "con el doble de cuenta el tamano no deberia bajar"

    def test_subir_el_peso_relativo_con_cuenta_plana_se_rechaza(self):
        """La segunda clausula, probada por su cuenta."""
        risk = RiskManagerAgent(limits=RiskLimits(max_consecutive_losses=10))
        risk.reset_daily(10000.0)
        risk.s.last_stake = 1.0          # 0.01% del equity inicial
        risk.s.consecutive_losses = 0    # sin perdidas: solo pesa la clausula 2
        out = risk.approve("EURUSD", Direction.CALL, "trend",
                           MarketRegime.TREND_UP, 0.65, 10000.0)
        assert out["decision"] == RiskDecision.REJECTED, out
        assert "peso relativo" in " ".join(out["reasons"])

    def test_una_victoria_reinicia_la_racha(self):
        risk = RiskManagerAgent(limits=RiskLimits(max_consecutive_losses=2))
        risk.reset_daily(10000.0)
        for _ in range(2):
            risk.on_trade_closed(self._perdida())
        assert risk.state()["consecutive_losses"] == 2
        victoria = self._perdida()
        victoria.execution_state = ExecutionState.WON
        victoria.result = 8.5
        risk.on_trade_closed(victoria)
        assert risk.state()["consecutive_losses"] == 0

    def test_empate_y_desconocido_no_cuentan_como_perdida(self):
        """Contabilizar un empate como derrota sesgaria el contador de rachas."""
        risk = RiskManagerAgent()
        risk.reset_daily(10000.0)
        for estado in (ExecutionState.UNKNOWN, ExecutionState.SENT):
            t = self._perdida()
            t.execution_state = estado
            risk.on_trade_closed(t)
        assert risk.state()["consecutive_losses"] == 0


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
