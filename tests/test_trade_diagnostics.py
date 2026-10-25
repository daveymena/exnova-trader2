import pandas as pd

from bot.core.trade_diagnostics import diagnose_price_path
from bot.core.trade_journal import TradeJournal
from bot.brain.trade_evaluator import TradeEvaluator


def _candles(rows):
    index = pd.to_datetime([r[0] for r in rows], unit="s", utc=True)
    return pd.DataFrame(
        {"open": [r[3] for r in rows], "high": [r[1] for r in rows], "low": [r[2] for r in rows],
         "close": [r[3] for r in rows]}, index=index
    )


def test_loss_that_recovers_after_expiry_keeps_broker_loss_label():
    candles = _candles([
        (0, 101, 99, 99.5),       # contract: CALL ends out of money
        (60, 101.8, 99.4, 101.2), # +1m after expiry: favorable recovery
    ])
    diag = diagnose_price_path(candles, entry_time=0, entry_price=100,
        direction="CALL", expiry_seconds=60, broker_result="LOSS", observed_at=120)
    assert diag["broker_result"] == "LOSS"
    assert diag["timing_class"] == "late_recovery_after_expiry"
    assert diag["post_expiry_return_pct"]["1m"] > 0
    assert len(diag["chart_candles"]) == 2


def test_put_uses_inverse_directional_return_and_excludes_unclosed_bar():
    candles = _candles([
        (0, 101, 99, 100.5),
        (60, 99.8, 98.8, 99.0),
        (120, 98.5, 97.5, 98), # still open at observed_at=179
    ])
    diag = diagnose_price_path(candles, entry_time=0, entry_price=100,
        direction="PUT", expiry_seconds=60, broker_result="LOSS", observed_at=179)
    assert diag["post_expiry_return_pct"]["1m"] > 0
    assert diag["post_expiry_return_pct"]["3m"] is None


def test_no_price_recovery_does_not_claim_late_recovery():
    candles = _candles([(0, 99.9, 98.8, 99), (60, 99.5, 98, 98.5)])
    diag = diagnose_price_path(candles, entry_time=0, entry_price=100,
        direction="CALL", expiry_seconds=60, broker_result="LOSS", observed_at=120)
    assert diag["timing_class"] == "no_favorable_move_before_expiry"
    assert diag["late_recovery"] is False


def test_unresolved_result_is_neutral_and_missing_entry_evidence_is_not_a_cause():
    evaluator = TradeEvaluator()
    unresolved = evaluator.evaluate({"result": "UNRESOLVED", "asset": "EURUSD",
        "direction": "CALL"}, {}, {})
    assert unresolved["primary_cause"] == "unresolved_broker_result"
    assert unresolved["secondary_causes"] == []

    loss = evaluator.evaluate({"result": "LOSS", "asset": "EURUSD",
        "direction": "CALL"}, {}, {})
    assert "zone_too_weak" not in loss["secondary_causes"]
    assert "no_rejection_wick" not in loss["secondary_causes"]


def test_journal_folds_append_only_diagnostic_updates(tmp_path):
    journal = TradeJournal(tmp_path / "trades.jsonl")
    trade = journal.open_trade("EURUSD", "CALL", "strategy", "setup",
        1, 60, features={"entry_time": 1000, "entry_price": 1.1})
    journal.close_trade(trade.trade_id, "LOSS", -1)
    journal.update_diagnostic(trade.trade_id, {"timing_class": "late_recovery_after_expiry"})
    rows = journal.load().to_dict("records")
    assert len(rows) == 1
    assert rows[0]["post_trade_diagnostic"]["timing_class"] == "late_recovery_after_expiry"


def test_reconstructed_chart_includes_pre_entry_structure_and_emas():
    rows = []
    for i in range(22):
        close = 100 + i * 0.1
        rows.append((-1320 + i * 60, close + .05, close - .05, close))
    rows.append((0, 102.3, 102.0, 102.2))
    diag = diagnose_price_path(_candles(rows), entry_time=0, entry_price=102.2,
        direction="CALL", expiry_seconds=60, broker_result="WIN", observed_at=60)
    assert diag["chart_analysis"]["quality"] == "complete"
    assert diag["chart_analysis"]["trend_ema8_21"] == "up"
    assert len(diag["chart_candles"]) == 23
    assert diag["chart_candles"][-1]["phase"] == "contract"
    assert diag["chart_candles"][-1]["ema8"] is not None


def test_mid_candle_contract_is_marked_as_coarse_m1_proxy():
    candles = _candles([(0, 101, 99, 100.2), (60, 101.2, 99.5, 100.5)])
    diag = diagnose_price_path(candles, entry_time=30, entry_price=100,
        direction="CALL", expiry_seconds=60, broker_result="WIN", observed_at=120)
    assert diag["contract_bars"] == 2
    assert diag["data_quality"] == "m1_overlap_proxy"
