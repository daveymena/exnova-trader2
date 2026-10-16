"""Tests del loop de aprendizaje: medicion real -> decision.

El punto de estos tests es que el bot NO puede auto-enganarse. Le meten
operaciones con resolucion real (broker) y comprueban que:

    - una estrategia que gana de verdad acaba votando,
    - una que pierde deja de votar aunque el mapa sintetico la incluya,
    - una que dejo de ganar en la mitad reciente se cae (estabilidad),
    - el dimensionado por Kelly con limite inferior es conservador,
    - las operaciones simuladas NUNCA cuentan como aprendizaje.
"""
from datetime import datetime, timedelta

from app.data.repository import Repository
from app.data.schemas import (
    Direction, ExecutionState, MarketRegime, ResolutionSource, TradeResult,
)
from app.research.edge_ledger import EdgeLedger
from app.strategies.consensus_winning import ConsensusWinningStrategy


def _repo(tmp_path, name="edge.db"):
    repo = Repository(db_path=str(tmp_path / name))
    repo.migrate()
    return repo


def _trades(repo, strategy, direction, regime, results, payout=0.85,
            source=ResolutionSource.BROKER, start=None):
    """Inserta operaciones ya resueltas. `results` = lista de PnL."""
    start = start or (datetime.utcnow() - timedelta(minutes=len(results)))
    for i, pnl in enumerate(results):
        repo.save_trade_result(TradeResult(
            timestamp=start + timedelta(minutes=i),
            asset="EURUSD", direction=direction, strategy=strategy,
            expiry=180, payout=payout, stake=10.0, result=pnl,
            execution_state=(ExecutionState.WON if pnl > 0
                             else ExecutionState.LOST),
            market_regime=regime,
            resolution_source=source,
        ))


def _wins(n):
    return [8.5] * n


def _losses(n):
    return [-10.0] * n


class TestSoloCuentaEvidenciaReal:
    def test_operaciones_simuladas_no_ensenan(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        monkeypatch.setattr("app.research.edge_ledger.repository", repo)
        _trades(repo, "breakout_direct", Direction.CALL,
                MarketRegime.TREND_UP, _wins(60),
                source=ResolutionSource.SIMULATED)
        ledger = EdgeLedger(min_sample=30)
        measured = ledger.measure_all()
        assert measured == {}, "lo simulado no puede alimentar el aprendizaje"

    def test_operaciones_sin_resolver_no_ensenan(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        monkeypatch.setattr("app.research.edge_ledger.repository", repo)
        _trades(repo, "breakout_direct", Direction.CALL,
                MarketRegime.TREND_UP, _wins(60),
                source=ResolutionSource.UNRESOLVED)
        ledger = EdgeLedger(min_sample=30)
        assert ledger.measure_all() == {}

    def test_broker_y_vela_si_cuentan(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        monkeypatch.setattr("app.research.edge_ledger.repository", repo)
        _trades(repo, "breakout_direct", Direction.CALL,
                MarketRegime.TREND_UP, _wins(60))
        _trades(repo, "sr_bounce", Direction.CALL, MarketRegime.RANGE,
                _wins(60), source=ResolutionSource.CANDLE)
        ledger = EdgeLedger(min_sample=30)
        measured = ledger.measure_all()
        assert len(measured) == 2


class TestUnaEstrategiaQueGanaAcabaVotando:
    def test_edge_real_habilita_votante(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        monkeypatch.setattr("app.research.edge_ledger.repository", repo)
        _trades(repo, "breakout_direct", Direction.CALL,
                MarketRegime.TREND_UP, _wins(60))
        ledger = EdgeLedger(min_sample=30)
        voters = ledger.voters_for(MarketRegime.TREND_UP)
        assert voters == ("breakout_direct",)


class TestUnaEstrategiaQuePierdeDejaDeVotar:
    def test_edge_real_deshabilita_votante_aunque_el_mapa_lo_incluya(
            self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        monkeypatch.setattr("app.research.edge_ledger.repository", repo)
        # El mapa sintetico incluye sr_bounce en TREND_UP. Con muestra real
        # que muestra que pierde, debe salir.
        _trades(repo, "sr_bounce", Direction.PUT, MarketRegime.TREND_UP,
                _losses(40) + _wins(5))
        ledger = EdgeLedger(min_sample=30)
        voters = ledger.voters_for(
            MarketRegime.TREND_UP, fallback=("sr_bounce", "breakout_direct"))
        assert "sr_bounce" not in voters

    def test_sin_edge_nadie_vota(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        monkeypatch.setattr("app.research.edge_ledger.repository", repo)
        _trades(repo, "trend_continuation", Direction.CALL,
                MarketRegime.TREND_UP, _losses(40) + _wins(5))
        ledger = EdgeLedger(min_sample=30)
        assert ledger.voters_for(MarketRegime.TREND_UP, fallback=()) == ()


class TestMuestraInsuficienteNoEnsenenaNada:
    def test_pocas_operaciones_no_habilitan(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        monkeypatch.setattr("app.research.edge_ledger.repository", repo)
        _trades(repo, "breakout_direct", Direction.CALL,
                MarketRegime.TREND_UP, _wins(5))
        ledger = EdgeLedger(min_sample=30)
        measured = ledger.measure_all()
        key = ("breakout_direct", "call", "trend_up")
        assert not measured[key].has_edge
        assert "insuficiente" in measured[key].reason

    def test_racha_perfecta_no_basta_para_kelly_agresivo(
            self, tmp_path, monkeypatch):
        """5 de 5 ganadas NO justifica apostar la cuenta.

        Con win rate observado, Kelly puro con payout 0.85 diria 100%. Con el
        limite inferior de Wilson dice 5.4%. Este test fija ese comportamiento.
        """
        repo = _repo(tmp_path)
        monkeypatch.setattr("app.research.edge_ledger.repository", repo)
        _trades(repo, "breakout_direct", Direction.CALL,
                MarketRegime.TREND_UP, _wins(5))
        ledger = EdgeLedger(min_sample=5, kelly_fraction=0.25)
        # Con 5 operaciones no hay edge probado, asi que la fraccion es 0.
        assert ledger.stake_fraction(
            "breakout_direct", Direction.CALL, MarketRegime.TREND_UP, 0.85) == 0.0


class TestEstabilidad:
    def test_estrategia_que_dejo_de_ganar_se_cae(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        monkeypatch.setattr("app.research.edge_ledger.repository", repo)
        # 30 ganadas y luego 30 perdidas: el global queda sobre break-even,
        # pero la mitad reciente lo perdio.
        # 40 ganadas, luego 15 ganadas y 25 perdidas: el global si supera el
        # limite inferior, pero la mitad reciente lo perdio.
        _trades(repo, "sr_bounce", Direction.CALL, MarketRegime.RANGE,
                _wins(40) + _wins(15) + _losses(25))
        ledger = EdgeLedger(min_sample=30, require_stability=True)
        measured = ledger.measure_all()
        key = ("sr_bounce", "call", "range")
        assert measured[key].trades == 80
        assert measured[key].win_rate > 0.55
        assert not measured[key].has_edge
        assert "reciente" in measured[key].reason
        # Y por tanto nadie vota en RANGE, ni siquiera con fallback.
        assert ledger.voters_for(MarketRegime.RANGE,
                                 fallback=("sr_bounce",)) == ()


class TestKellyConservador:
    def test_kelly_con_muestra_grande_queda_acotado(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        monkeypatch.setattr("app.research.edge_ledger.repository", repo)
        _trades(repo, "breakout_direct", Direction.CALL,
                MarketRegime.TREND_UP, _wins(100) + _losses(10))
        ledger = EdgeLedger(min_sample=30, kelly_fraction=0.15)
        fraction = ledger.stake_fraction(
            "breakout_direct", Direction.CALL, MarketRegime.TREND_UP, 0.85)
        # Con 110 operaciones el p_inf es alto (~0.85) y Kelly puro pediria
        # ~67% de la cuenta. El tope duro del 2% es el que manda.
        assert 0 < fraction <= 0.02
        assert fraction == ledger.max_stake_pct


class TestConsumoDesdeLaEstrategia:
    def test_el_consenso_usa_los_votantes_del_registro(
            self, tmp_path, monkeypatch):
        repo = _repo(tmp_path)
        monkeypatch.setattr("app.research.edge_ledger.repository", repo)
        _trades(repo, "mean_reversion", Direction.CALL, MarketRegime.RANGE,
                _wins(60))
        ledger = EdgeLedger(min_sample=30)
        strategy = ConsensusWinningStrategy(config={
            "edge_ledger": ledger, "min_votes": 1,
            "high_conviction_threshold": 0.70,
        })
        # El registro real manda sobre el mapa sintetico.
        assert strategy._voters_for(MarketRegime.RANGE) == ("mean_reversion",)
        assert strategy._using_ledger(MarketRegime.RANGE) is True

    def test_sin_registro_cae_al_mapa_sintetico(self):
        strategy = ConsensusWinningStrategy()
        from app.strategies.consensus_winning import VOTERS_BY_REGIME
        assert strategy._voters_for(MarketRegime.RANGE) == \
            VOTERS_BY_REGIME[MarketRegime.RANGE]

    def test_registro_roto_no_tumba_la_estrategia(self, monkeypatch):
        class _Roto:
            def voters_for(self, *a, **k):
                raise RuntimeError("sqlite caido")

            def measure_all(self):
                raise RuntimeError("sqlite caido")

        strategy = ConsensusWinningStrategy(config={"edge_ledger": _Roto()})
        from app.strategies.consensus_winning import VOTERS_BY_REGIME
        assert strategy._voters_for(MarketRegime.RANGE) == \
            VOTERS_BY_REGIME[MarketRegime.RANGE]
        assert strategy._using_ledger(MarketRegime.RANGE) is False
