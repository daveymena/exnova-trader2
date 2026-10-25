"""Time-aligned, descriptive post-trade price-path diagnostics.

Broker settlement remains authoritative. Candle paths explain timing around
the contract expiry; they never relabel a losing option as a winning trade.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def diagnose_price_path(
    candles: pd.DataFrame | None,
    *,
    entry_time: float,
    entry_price: float,
    direction: str,
    expiry_seconds: int,
    broker_result: str,
    observed_at: float | None = None,
    candle_seconds: int = 60,
) -> dict[str, Any]:
    """Describe movement inside the contract and at +1/+3/+5 min after it.

    Only fully closed bars wholly inside a time window count. Missing history
    is reported as unavailable rather than guessed from row position.
    """
    base = {
        "version": 1,
        "source": "broker_candles",
        "broker_result": broker_result,
        "entry_time": _finite(entry_time),
        "entry_price": _finite(entry_price),
        "expiry_seconds": int(expiry_seconds),
        "contract_bars": 0,
        "post_expiry_close": {"1m": None, "3m": None, "5m": None},
        "post_expiry_return_pct": {"1m": None, "3m": None, "5m": None},
        "data_quality": "insufficient_data",
        "timing_class": "insufficient_data",
        "mfe_pct": None,
        "mae_pct": None,
        "expiry_close_proxy": None,
        "expiry_return_proxy_pct": None,
        "late_recovery": False,
        "chart_candles": [],
        "chart_analysis": {},
    }
    entry_time = _finite(entry_time)
    entry_price = _finite(entry_price)
    if (candles is None or candles.empty or direction not in {"CALL", "PUT"}
            or entry_time is None or entry_price is None
            or entry_price <= 0 or expiry_seconds <= 0):
        return base
    required = {"high", "low", "close"}
    if not required.issubset(candles.columns) or not isinstance(candles.index, pd.DatetimeIndex):
        return base

    frame = candles.copy()
    frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    frame = frame.loc[~frame.index.isna()].sort_index()
    frame = frame.loc[~frame.index.duplicated(keep="last")]
    for col in ("open", "high", "low", "close"):
        if col not in frame.columns:
            continue
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=list(required))
    frame = frame.loc[(frame.high >= frame.low) & (frame.low > 0) & (frame.close > 0)]
    if frame.empty:
        return base

    starts = frame.index.asi8 / 1e9
    ends = starts + candle_seconds
    as_of = float(observed_at if observed_at is not None else pd.Timestamp.now(tz="UTC").timestamp())
    closed = ends <= as_of
    expiry_time = float(entry_time + expiry_seconds)
    # Treinta velas previas permiten reconstruir estructura, tendencia y zona;
    # cinco posteriores muestran si el movimiento llegó después del contrato.
    chart_window = frame.loc[closed & (starts >= entry_time - 30 * 60)
                             & (starts <= expiry_time + 5 * 60)].copy()
    ema8 = frame["close"].ewm(span=8, adjust=False).mean()
    ema21 = frame["close"].ewm(span=21, adjust=False).mean()
    base["chart_candles"] = [
        {"time": float(ts.timestamp()), "open": _finite(row.get("open")),
         "high": _finite(row.get("high")), "low": _finite(row.get("low")),
         "close": _finite(row.get("close")), "ema8": _finite(ema8.get(ts)),
         "ema21": _finite(ema21.get(ts)),
         "phase": ("pre_entry" if float(ts.timestamp()) + candle_seconds <= entry_time
                   else "contract" if float(ts.timestamp()) < expiry_time
                   else "post_expiry")}
        for ts, row in chart_window.iterrows()
        if all(_finite(row.get(col)) is not None for col in ("open", "high", "low", "close"))
    ]
    pre_entry = frame.loc[closed & (ends <= entry_time)].tail(30)
    base["chart_analysis"] = _entry_chart_analysis(pre_entry)
    # Una orden suele abrir a mitad de una vela M1. Se incluyen las velas que
    # solapan el contrato, marcándolas como proxy: OHLC no revela el recorrido
    # exacto dentro de esos segundos parciales.
    contract_mask = closed & (starts < expiry_time) & (ends > entry_time)
    post_mask = closed & (starts >= expiry_time)
    contract = frame.loc[contract_mask]
    post = frame.loc[post_mask]
    base["contract_bars"] = int(len(contract))
    base["observed_post_expiry_bars"] = int(len(post))
    expected_contract_bars = max(1, int(np.ceil(expiry_seconds / candle_seconds)))
    boundaries_aligned = (entry_time % candle_seconds) < 1
    if len(contract) >= expected_contract_bars and boundaries_aligned:
        base["data_quality"] = "complete"
    elif len(contract) >= expected_contract_bars:
        base["data_quality"] = "m1_overlap_proxy"
    elif len(contract):
        base["data_quality"] = "partial_contract_bars"
    else:
        base["data_quality"] = "insufficient_contract_bars"

    if len(contract):
        if direction == "CALL":
            mfe = max(0.0, float(contract.high.max()) - entry_price)
            mae = min(0.0, float(contract.low.min()) - entry_price)
            expiry_return = (float(contract.close.iloc[-1]) / entry_price - 1.0) * 100
        else:
            mfe = max(0.0, entry_price - float(contract.low.min()))
            mae = min(0.0, entry_price - float(contract.high.max()))
            expiry_return = (entry_price / float(contract.close.iloc[-1]) - 1.0) * 100
        base["mfe_pct"] = mfe / entry_price * 100
        base["mae_pct"] = mae / entry_price * 100
        base["expiry_close_proxy"] = float(contract.close.iloc[-1])
        base["expiry_return_proxy_pct"] = expiry_return

    post_ends = ends[post_mask]
    post_closes = post.close.to_numpy(dtype=float)
    for minutes in (1, 3, 5):
        key = f"{minutes}m"
        target = expiry_time + minutes * 60
        later = np.flatnonzero(post_ends >= target)
        if not len(later):
            continue
        i = int(later[0])
        # Gaps must not silently turn a +1m measurement into +20m.
        if post_ends[i] - target > candle_seconds:
            continue
        close = float(post_closes[i])
        base["post_expiry_close"][key] = close
        if direction == "CALL":
            ret = (close / entry_price - 1.0) * 100
        else:
            ret = (entry_price / close - 1.0) * 100
        base["post_expiry_return_pct"][key] = ret

    available_returns = [v for v in base["post_expiry_return_pct"].values() if v is not None]
    if broker_result == "UNRESOLVED":
        base["timing_class"] = "market_path_only" if len(contract) else "insufficient_data"
    elif broker_result == "WIN":
        base["timing_class"] = "broker_win"
    elif broker_result == "TIE":
        base["timing_class"] = "broker_tie"
    elif broker_result == "LOSS":
        base["late_recovery"] = any(ret > 0 for ret in available_returns)
        if base["late_recovery"]:
            base["timing_class"] = "late_recovery_after_expiry"
        elif base["mfe_pct"] is not None and base["mfe_pct"] > 0 and base["expiry_return_proxy_pct"] is not None and base["expiry_return_proxy_pct"] <= 0:
            base["timing_class"] = "favorable_move_then_reversal"
        elif base["mfe_pct"] == 0:
            base["timing_class"] = "no_favorable_move_before_expiry"
        else:
            base["timing_class"] = "loss_path_ambiguous"
    else:
        base["timing_class"] = "unknown_broker_result"
    return base


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _entry_chart_analysis(pre_entry: pd.DataFrame) -> dict[str, Any]:
    """Mechanical visual context from candles closed before the order."""
    if pre_entry is None or len(pre_entry) < 2 or "open" not in pre_entry.columns:
        return {"bars": int(len(pre_entry)) if pre_entry is not None else 0,
                "quality": "insufficient_pre_entry_bars", "pattern_candidates": []}
    closes = pre_entry["close"]
    ema8 = closes.ewm(span=8, adjust=False).mean()
    ema21 = closes.ewm(span=21, adjust=False).mean()
    last, previous = pre_entry.iloc[-1], pre_entry.iloc[-2]
    candle_range = float(last.high - last.low)
    body = abs(float(last.close - last.open))
    upper_wick = float(last.high - max(last.open, last.close))
    lower_wick = float(min(last.open, last.close) - last.low)
    candidates: list[str] = []
    if last.close > last.open and previous.close < previous.open \
            and last.open <= previous.close and last.close >= previous.open:
        candidates.append("bullish_engulfing")
    if last.close < last.open and previous.close > previous.open \
            and last.open >= previous.close and last.close <= previous.open:
        candidates.append("bearish_engulfing")
    if candle_range > 0 and lower_wick >= max(body * 2, candle_range * .45):
        candidates.append("lower_rejection")
    if candle_range > 0 and upper_wick >= max(body * 2, candle_range * .45):
        candidates.append("upper_rejection")
    lookback = pre_entry.tail(20)
    support, resistance = float(lookback.low.min()), float(lookback.high.max())
    span = resistance - support
    position = ((float(last.close) - support) / span) if span > 0 else None
    if len(pre_entry) < 21:
        trend = "insufficient"
    elif ema8.iloc[-1] > ema21.iloc[-1]:
        trend = "up"
    elif ema8.iloc[-1] < ema21.iloc[-1]:
        trend = "down"
    else:
        trend = "flat"
    return {
        "bars": int(len(pre_entry)), "quality": "complete" if len(pre_entry) >= 21 else "partial",
        "trend_ema8_21": trend, "support_proxy": support,
        "resistance_proxy": resistance, "range_position": _finite(position),
        "last_body_to_range": _finite(body / candle_range) if candle_range > 0 else None,
        "pattern_candidates": candidates,
    }
