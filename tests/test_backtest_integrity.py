"""Contract timing and causal signals; synthetic fixtures are not trading evidence."""
import numpy as np
import pandas as pd
import pytest

from bot.backtest.replay import BacktestConfig, ReplayEngine, Signal
from bot.backtest.vectorized import PLAYBOOK, evaluate_signals


def candles(n=360, seed=42, drift=0.0):
    rng = np.random.default_rng(seed)
    closes = 100 + np.cumsum(rng.normal(drift, 0.08, n))
    opens = np.r_[100, closes[:-1]]
    return pd.DataFrame(dict(open=opens, close=closes,
        high=np.maximum(opens, closes) + 0.03,
        low=np.minimum(opens, closes) - 0.03, volume=np.ones(n)),
        index=pd.date_range('2026-01-01', periods=n, freq='min'))


class Once:
    name = 'timing_fixture'

    def __init__(self, expiry=60, direction='CALL', at=20):
        self.expiry, self.direction, self.at = expiry, direction, at

    def evaluate(self, frames, now):
        for tf, frame in frames.items():
            assert (frame.index + pd.Timedelta(seconds=tf) <= now).all()
        if len(frames[60]) == self.at:
            return Signal(self.direction, self.expiry, self.name)


def engine():
    return ReplayEngine(BacktestConfig(warmup_bars=20, min_bars_between_trades=1))


@pytest.mark.parametrize('minutes', [1, 2, 3, 5])
@pytest.mark.parametrize('direction', ['CALL', 'PUT'])
def test_exact_expiry_and_vectorized_agreement(minutes, direction):
    df = candles()
    trade = engine().run(Once(minutes * 60, direction), df, 'FIXTURE').trades[0]
    assert trade.entry_price == df.open.iloc[20]
    assert trade.exit_price == df.close.iloc[20 + minutes - 1]
    sig = pd.DataFrame(False, index=df.index, columns=['call', 'put'])
    sig.iloc[19, 0 if direction == 'CALL' else 1] = True
    result = evaluate_signals(df, sig, minutes)
    assert bool(result.win.iloc[0]) == (trade.result == 'WIN')
    assert result.entry_time.iloc[0] == trade.time
    assert result.expiry_time.iloc[0] == trade.time + pd.Timedelta(minutes=minutes)


def test_partial_higher_timeframes_are_excluded():
    df = candles(22)
    assert len(ReplayEngine.resample(df, 300)) == 4
    assert len(ReplayEngine.resample(df, 900)) == 1
    assert len(ReplayEngine.resample(df.drop(df.index[2]), 300)) == 3


def test_missing_minutes_never_extend_contract():
    df = candles().drop(candles().index[21])
    assert engine().run(Once(180), df, 'FIXTURE').trades == []
    sig = pd.DataFrame(False, index=df.index, columns=['call', 'put'])
    sig.iloc[19, 0] = True
    assert evaluate_signals(df, sig, 3).empty


def test_training_outcome_does_not_cross_holdout():
    df = candles(100)
    assert engine().run(Once(180, at=69), df, 'FIXTURE').trades == []


def test_tie_is_refund():
    df = candles()
    df.loc[df.index[20], 'close'] = df.open.iloc[20]
    trade = engine().run(Once(), df, 'FIXTURE').trades[0]
    assert (trade.result, trade.pnl) == ('TIE', 0.0)


def test_bad_strategy_does_not_silently_disappear():
    class Broken:
        name = 'broken'
        def evaluate(self, frames, now):
            raise RuntimeError('strategy failed')
    with pytest.raises(RuntimeError, match='strategy failed'):
        engine().run(Broken(), candles(), 'FIXTURE')


@pytest.mark.parametrize('expiry', [0, -60, 30, 90])
def test_unsupported_expiry_rejected(expiry):
    with pytest.raises(ValueError):
        engine().run(Once(expiry), candles(), 'FIXTURE')


@pytest.mark.parametrize('damage', ['duplicate', 'nan', 'infinity', 'negative', 'bad_high'])
def test_invalid_candles_rejected(damage):
    df = candles()
    if damage == 'duplicate':
        df = pd.concat([df, df.iloc[[0]]])
    else:
        df.loc[df.index[10], 'high' if damage == 'bad_high' else 'close'] = {
            'nan': np.nan, 'infinity': np.inf, 'negative': -1, 'bad_high': 1}[damage]
    with pytest.raises(ValueError):
        engine().run(Once(), df, 'FIXTURE')


@pytest.mark.parametrize('name', list(PLAYBOOK))
@pytest.mark.parametrize('drift', [-0.02, 0.0, 0.02])
def test_playbook_signals_causal_across_market_scenarios(name, drift):
    df = candles(drift=drift)
    fn = PLAYBOOK[name]
    full = fn(df)
    prefix = fn(df.iloc[:280])
    pd.testing.assert_frame_equal(full.iloc[:280], prefix)
    assert not (full.call & full.put).any()
    for minutes in (1, 3, 5):
        results = evaluate_signals(df, full, minutes)
        assert (results.expiry_time - results.entry_time == pd.Timedelta(minutes=minutes)).all()
