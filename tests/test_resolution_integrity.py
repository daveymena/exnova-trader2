"""La medicion no se inventa.

Estas pruebas cubren el fallo que dejo al bot ciego: `_resolve_expired_trades`
resolvia cada operacion con `random.random() < 0.55`, incluidas las ordenes
reales que volvian del broker en estado SENT. El historial resultante era
ruido sintetico marcado como 'unresolved', asi que EVIDENCE_SQL lo descartaba
entero y el EdgeValidator veia siempre 0 muestras.
"""
from datetime import datetime, timedelta

import pytest

from app.data.schemas import (
    DataSource, Direction, ExecutionState, MarketRegime, ResolutionSource,
    TradeResult,
)


def _expired_trade(**kw) -> TradeResult:
    now = datetime.utcnow()
    base = dict(
        timestamp=now - timedelta(seconds=120),
        asset="EURUSD-OTC",
        direction=Direction.CALL,
        strategy="sr_bounce",
        expiry=60,
        payout=0.85,
        stake=5.0,
        result=0.0,
        execution_state=ExecutionState.SENT,
        market_regime=MarketRegime.RANGE,
    )
    base.update(kw)
    return TradeResult(**base)


class _Bot:
    """Solo la parte del orquestador que resuelve, sin tocar broker ni base."""

    def __init__(self, broker):
        self.broker = broker

    _resolve_with_evidence = None  # se enlaza abajo


@pytest.fixture(scope="module")
def resolver():
    from app.main import TradingBot
    return TradingBot._resolve_with_evidence


class _BrokerSinEvidencia:
    connected = False
    open_trades: list = []


class _BrokerConOrden:
    """Devuelve el PnL real de la orden, como check_win_v4."""
    connected = True
    open_trades: list = []

    def __init__(self, pnl):
        self._pnl = pnl

    def resolve_order(self, order_id):
        return self._pnl


class _BrokerConPrecio:
    connected = True
    open_trades: list = []

    def __init__(self, close):
        self._close = close

    def resolve_order(self, order_id):
        return None          # el broker aun no confirma

    def get_last_close(self, asset):
        return self._close


class TestNoSeInventanResultados:
    def test_sin_evidencia_no_resuelve(self, resolver):
        """Sin broker ni precio, la operacion queda sin resolver."""
        trade = _expired_trade()
        bot = _Bot(_BrokerSinEvidencia())
        assert resolver(bot, trade, datetime.utcnow()) is False
        assert trade.execution_state is ExecutionState.SENT
        assert trade.resolution_source is ResolutionSource.UNRESOLVED

    def test_resultado_no_depende_del_azar(self, resolver):
        """Mismo estado de entrada -> mismo resultado, siempre."""
        salidas = set()
        for _ in range(200):
            trade = _expired_trade()
            bot = _Bot(_BrokerSinEvidencia())
            salidas.add(resolver(bot, trade, datetime.utcnow()))
        assert salidas == {False}, "la resolucion introdujo aleatoriedad"


class TestResolucionPorBroker:
    def test_ganancia_del_broker_es_evidencia(self, resolver):
        trade = _expired_trade(features={"order_id": "abc"})
        bot = _Bot(_BrokerConOrden(4.25))
        assert resolver(bot, trade, datetime.utcnow()) is True
        assert trade.execution_state is ExecutionState.WON
        assert trade.result == 4.25
        assert trade.resolution_source is ResolutionSource.BROKER

    def test_perdida_del_broker_es_evidencia(self, resolver):
        trade = _expired_trade(features={"order_id": "abc"})
        bot = _Bot(_BrokerConOrden(-5.0))
        assert resolver(bot, trade, datetime.utcnow()) is True
        assert trade.execution_state is ExecutionState.LOST
        assert trade.resolution_source is ResolutionSource.BROKER


class TestResolucionPorPrecio:
    def test_call_gana_si_el_precio_sube(self, resolver):
        trade = _expired_trade(entry_price=1.1000, features={"order_id": "abc"})
        bot = _Bot(_BrokerConPrecio(1.1010))
        assert resolver(bot, trade, datetime.utcnow()) is True
        assert trade.execution_state is ExecutionState.WON
        assert trade.resolution_source is ResolutionSource.CANDLE
        assert trade.result == pytest.approx(5.0 * 0.85)

    def test_put_gana_si_el_precio_baja(self, resolver):
        trade = _expired_trade(direction=Direction.PUT, entry_price=1.1000,
                               features={"order_id": "abc"})
        bot = _Bot(_BrokerConPrecio(1.0990))
        assert resolver(bot, trade, datetime.utcnow()) is True
        assert trade.execution_state is ExecutionState.WON

    def test_empate_no_resuelve(self, resolver):
        """Precio identico no da informacion direccional: se reintenta."""
        trade = _expired_trade(entry_price=1.1000, features={"order_id": "abc"})
        bot = _Bot(_BrokerConPrecio(1.1000))
        assert resolver(bot, trade, datetime.utcnow()) is False
        assert trade.execution_state is ExecutionState.SENT


class TestEvidenciaYEdge:
    """Evidencia = resolucion observada Y precio subyacente real.

    AMPLIADO A PROPÓSITO. La version anterior de esta clase solo comprobaba
    `resolution_source` y daba por hecho que BROKER/CANDLE bastaba. Pero
    `TradeResult.is_evidence` exige DOS condiciones independientes (ver
    `app/data/schemas.py`), y el caso que se colaba era justo el que el test no
    miraba: un PaperBroker alimentado por el simulador produce trades resueltos
    contra vela -- condicion 1 cumplida -- cuyo precio es ruido sintetico. Con
    el test antiguo eso era "evidencia" y el EdgeValidator habria aprendido edge
    de una fuente inventada.

    Se cubren las dos dimensiones en cruz, no una sola.
    """

    @pytest.mark.parametrize("resolution, data, esperado", [
        # resolucion observada + precio real -> evidencia
        (ResolutionSource.BROKER, DataSource.BROKER, True),
        (ResolutionSource.CANDLE, DataSource.BROKER, True),
        (ResolutionSource.CANDLE, DataSource.CSV, True),
        (ResolutionSource.BROKER, DataSource.CSV, True),
        # precio sintetico -> NUNCA evidencia, aunque la resolucion sea real.
        # Este es el caso que el test antiguo no cubria.
        (ResolutionSource.BROKER, DataSource.SIMULATOR, False),
        (ResolutionSource.CANDLE, DataSource.SIMULATOR, False),
        # procedencia desconocida -> no se puede afirmar que el precio sea real
        (ResolutionSource.BROKER, DataSource.UNKNOWN, False),
        (ResolutionSource.CANDLE, DataSource.UNKNOWN, False),
        # resolucion no observada -> nunca evidencia, venga el precio de donde venga
        (ResolutionSource.SIMULATED, DataSource.BROKER, False),
        (ResolutionSource.SIMULATED, DataSource.CSV, False),
        (ResolutionSource.UNRESOLVED, DataSource.CSV, False),
        (ResolutionSource.UNRESOLVED, DataSource.UNKNOWN, False),
    ])
    def test_evidencia_exige_las_dos_dimensiones(self, resolution, data, esperado):
        trade = _expired_trade(execution_state=ExecutionState.WON,
                               resolution_source=resolution, data_source=data)
        assert trade.is_evidence is esperado, f"{resolution.value}/{data.value}"

    def test_el_paper_broker_sobre_simulador_no_es_evidencia(self):
        """El caso por defecto: paper + simulador no alimenta al EdgeValidator."""
        from app.services.paper_broker import PaperBroker
        broker = PaperBroker()  # data_source por defecto = SIMULATOR
        trade = _expired_trade()
        broker.settle(trade, won=True, payout=0.85)
        assert trade.data_source is DataSource.SIMULATOR
        assert trade.is_evidence is False

    def test_el_paper_broker_sobre_historico_real_si_es_evidencia(self):
        """Paper sobre replay CSV mide de verdad: el precio es observado.

        Es la diferencia entre "trading de papel inutil" y "forward test":
        el resultado no depende de que haya dinero, depende de que el PRECIO
        sea real.
        """
        from app.services.paper_broker import PaperBroker
        broker = PaperBroker(data_source=DataSource.CSV)
        trade = _expired_trade()
        broker.settle(trade, won=True, payout=0.85,
                      resolution_source=ResolutionSource.CANDLE)
        assert trade.is_evidence is True
        assert trade.result == pytest.approx(trade.stake * 0.85)
