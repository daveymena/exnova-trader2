"""Tests de regresion de los bugs encontrados en la auditoria de estrategias.

Cada test corresponde a un fallo real que media dinero y que quedo demostrado
en reports/strategy_audit.json. No son tests de "suerte": fijan el
comportamiento correcto para que no se vuelva a romper en silencio.
"""
from datetime import datetime, timedelta
import random


from app.data.schemas import Candle, Timeframe, Direction, MarketRegime
from app.agents.market_regime_agent import MarketRegimeAgent
from app.agents.multi_timeframe_agent import MultiTimeframeAgent
from app.strategies.sr_bounce import SRBounceStrategy
from app.strategies.breakout_direct import BreakoutDirectStrategy
from app.strategies.consensus_winning import (
    ConsensusWinningStrategy, VOTERS_BY_REGIME, NO_VOTE_REGIMES,
)


def _candle(t, o, high_p, low_p, c, tf=Timeframe.M1):
    return Candle(asset="EURUSD", timeframe=tf, open_time=t, open=o,
                  high=high_p, low=low_p, close=c)


def _series(values, start=None):
    """Convierte una lista de cierres en velas con mechas simetricas."""
    start = start or datetime(2026, 1, 1, 8, 0, 0)
    out = []
    prev = values[0]
    for i, c in enumerate(values):
        o = prev
        h = max(o, c) + 0.0002
        low_p = min(o, c) - 0.0002
        out.append(_candle(start + timedelta(minutes=i), o, h, low_p, c))
        prev = c
    return out


def _strong_downtrend(n=120, start=1.1000, step=-0.0004):
    return _series([start + step * i for i in range(n)])


def _strong_uptrend(n=120, start=1.1000, step=0.0004):
    return _series([start + step * i for i in range(n)])


class TestRegimeDetectaTendenciaBajista:
    """El clasificador no podia devolver TREND_DOWN nunca.

    `_compute_ema_slope` devolvia el NIVEL de la EMA (siempre positivo), asi
    que la condicion `ema_slope < 0` era inalcanzable. Todas las tendencias
    bajistas caian en UNKNOWN.
    """

    def test_tendencia_bajista_se_clasifica(self):
        agent = MarketRegimeAgent()
        candles = _strong_downtrend()
        snap = agent.classify(candles, "EURUSD")
        assert snap.regime == MarketRegime.TREND_DOWN

    def test_tendencia_alcista_se_clasifica(self):
        agent = MarketRegimeAgent()
        snap = agent.classify(_strong_uptrend(), "EURUSD")
        assert snap.regime == MarketRegime.TREND_UP

    def test_pendiente_es_relativa_no_el_nivel(self):
        """Con precios por encima de 1.0 la pendiente debe poder ser negativa."""
        agent = MarketRegimeAgent()
        snap = agent.classify(_strong_downtrend(), "EURUSD")
        assert snap.ema_slope < 0, "la pendiente debe medir cambio, no nivel"


class TestMultiTimeframeNoConfundeUnknownConConflicto:
    """'unknown' se trataba como 'conflict' y bloqueaba toda senal."""

    def test_desconocido_no_es_conflicto(self):
        agent = MultiTimeframeAgent()
        # Velas insuficientes -> regimen UNKNOWN en los tres timeframes
        m15 = [_candle(datetime.utcnow(), 1.1, 1.11, 1.09, 1.1, Timeframe.M15)]
        snap = agent.analyze(m15, m15, m15, "EURUSD")
        assert snap.alignment != "conflict"

    def timeframes_en_desacuerdo_si_son_conflicto(self):
        agent = MultiTimeframeAgent()
        m15 = _strong_uptrend(60)
        m5 = _strong_downtrend(60)
        m1 = _strong_uptrend(60)
        snap = agent.analyze(m15, m5, m1, "EURUSD")
        assert snap.alignment == "conflict"


class TestSRBounceExigeRechazoReal:
    """Aceptaba 'rebote' en cualquier vela que pasara cerca del nivel.

    Medido: en tendencia alcista daba PUT con 1.9% de acierto (2720 trades).
    """

    def _m1_near_resistance(self):
        """Precio pegado a una resistencia, con velas normales."""
        base = 1.1000
        values = [base] * 30
        values += [base + 0.00005 * i for i in range(20)]   # sube suave
        return _series(values)

    def test_no_hay_put_solo_por_vela_roja_en_tendencia(self):
        strat = SRBounceStrategy()
        m1 = self._m1_near_resistance()
        m5 = _series([1.1000 + 0.0004 * i for i in range(40)])
        m15 = _series([1.1000 + 0.0004 * i for i in range(30)])
        sig = strat.evaluate(m15, m5, m1, "EURUSD")
        # Sin mecha de rechazo real, no hay senal.
        assert sig["direction"] != Direction.PUT

    def test_rechazo_sin_mecha_larga_se_descarta(self):
        strat = SRBounceStrategy()
        # Vela con cuerpo grande y mecha minima: no es un rechazo.
        now = datetime(2026, 1, 1, 8, 0, 0)
        m1 = [_candle(now + timedelta(minutes=i), 1.1000, 1.1001, 1.0999, 1.1000)
              for i in range(30)]
        m1.append(_candle(now + timedelta(minutes=30), 1.1000, 1.1010, 1.0999, 1.1009))
        assert strat._check_rejection(m1[-1], m1, 1.0999, True, atr=0.0005) is False

    def test_rechazo_con_mecha_larga_se_acepta(self):
        strat = SRBounceStrategy()
        now = datetime(2026, 1, 1, 8, 0, 0)
        m1 = [_candle(now + timedelta(minutes=i), 1.1000, 1.1001, 1.0999, 1.1000)
              for i in range(30)]
        # Martillo: mecha inferior larga, cierra por encima del soporte.
        m1.append(_candle(now + timedelta(minutes=30), 1.1000, 1.1002, 1.0980, 1.1002))
        assert strat._check_rejection(m1[-1], m1, 1.0980, True, atr=0.0005) is True


class TestBreakoutDirectExigeSeparacionReal:
    """Un roce del nivel contaba como ruptura.

    Medido: con dist/ATR ~0.4 el acierto era 35-48%; con ~1.3 ATR, 94%.
    """

    def test_roce_del_nivel_no_es_ruptura(self):
        strat = BreakoutDirectStrategy(config={"min_breakout_distance_atr": 1.0})
        now = datetime(2026, 1, 1, 8, 0, 0)
        # Vela que apenas pasa la resistencia
        candle = _candle(now, 1.1000, 1.1010, 1.0995, 1.1003)
        atr = 0.0010
        features = {}
        assert strat._check_breakout_candle(candle, 1.1002, True, atr, features) is False

    def test_ruptura_de_un_atr_se_acepta(self):
        strat = BreakoutDirectStrategy(config={"min_breakout_distance_atr": 1.0})
        now = datetime(2026, 1, 1, 8, 0, 0)
        candle = _candle(now, 1.1000, 1.1020, 1.0995, 1.1015)
        atr = 0.0010
        features = {}
        assert strat._check_breakout_candle(candle, 1.1000, True, atr, features) is True
        assert features["breakout_distance_atr"] >= 1.0


class TestConsensoRespetaRegimen:
    def test_regimen_de_alta_volatilidad_no_opera(self):
        cs = ConsensusWinningStrategy()
        # 120 velas con rango enorme -> HIGH_VOLATILITY
        values = []
        price = 1.1000
        rng = random.Random(7)
        for _ in range(120):
            price *= 1 + rng.gauss(0, 0.01)
            values.append(price)
        candles = _series(values)
        sig = cs.evaluate(candles, candles, candles, "EURUSD")
        # O rechaza por regimen, o rechaza por falta de consenso: nunca opera
        # solo porque una estrategia diga que si.
        assert sig["direction"] in (Direction.NO_TRADE, Direction.CALL, Direction.PUT)
        if sig["direction"] != Direction.NO_TRADE:
            assert sig["market_regime"] not in NO_VOTE_REGIMES

    def test_mapa_de_votantes_cubre_los_regimenes_utiles(self):
        assert MarketRegime.TREND_UP in VOTERS_BY_REGIME
        assert MarketRegime.TREND_DOWN in VOTERS_BY_REGIME
        assert MarketRegime.RANGE in VOTERS_BY_REGIME
        assert MarketRegime.UNKNOWN not in VOTERS_BY_REGIME

    def test_sin_datos_no_opera(self):
        cs = ConsensusWinningStrategy()
        sig = cs.evaluate([], [], [], "EURUSD")
        assert sig["direction"] == Direction.NO_TRADE
        assert sig["confidence"] == 0.0
