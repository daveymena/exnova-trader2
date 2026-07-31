# -*- coding: utf-8 -*-
"""
Diario de operaciones con features REALES.

Este modulo existe por un motivo concreto: en las 500 operaciones anteriores
`rsi_at_touch` valia 50 en 495 de ellas, `pattern` decia "demo" en 253 y
`zone_strength` era 1.0 en la mitad. Todo eran defaults. Un sistema que
aprende sobre constantes no aprende nada, y por eso 500 operaciones no
mejoraron el resultado ni un punto.

Aqui cada operacion se registra con lo que de verdad habia en el mercado en el
instante de entrar, mas el contexto necesario para responder despues a las tres
preguntas que importan: donde se gana, donde se pierde, y donde se refina.

Regla de oro: si un valor no se pudo calcular se guarda `None`, NUNCA un
default plausible. Un hueco es honesto; un 50 inventado contamina el dataset.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "trade_journal.jsonl"


def _f(value: Any) -> float | None:
    """Convierte a float, o None si no es un numero utilizable."""
    try:
        if value is None:
            return None
        out = float(value)
        return None if (np.isnan(out) or np.isinf(out)) else out
    except (TypeError, ValueError):
        return None


@dataclass
class TradeRecord:
    """Una operacion, con todo lo necesario para auditarla despues."""

    # --- identidad ---
    trade_id: str
    asset: str
    direction: str
    timestamp: float
    hour_utc: int
    weekday: int
    synthetic: bool                     # activo -OTC generado por el broker

    # --- decision ---
    strategy: str                       # que estrategia disparo la entrada
    setup: str                          # variante concreta del setup
    confidence: float | None
    expiration_seconds: int
    amount: float
    payout: float | None

    # --- estado real del mercado en la entrada (None si no se pudo calcular) ---
    price: float | None = None
    rsi: float | None = None
    stoch_k: float | None = None
    stoch_d: float | None = None
    atr: float | None = None
    atr_pct: float | None = None        # ATR relativo al precio: volatilidad comparable
    ema8: float | None = None
    ema21: float | None = None
    ema50: float | None = None
    dist_ema21_atr: float | None = None  # cuan extendido esta el precio, en ATRs
    bb_position: float | None = None     # -1 banda inferior, +1 superior
    body_atr: float | None = None        # cuerpo de la vela en ATRs
    streak: int | None = None            # velas consecutivas en la misma direccion
    trend_m5: str | None = None
    trend_m15: str | None = None
    pattern: str | None = None
    zone_type: str | None = None
    zone_strength: float | None = None
    zone_touches: int | None = None
    dist_zone_atr: float | None = None

    # --- resultado (se rellena al cerrar) ---
    result: str | None = None           # WIN / LOSS / TIE
    pnl: float | None = None
    exit_price: float | None = None
    closed_at: float | None = None

    extra: dict = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        return self.result is None


def features_from_candles(df_m1: pd.DataFrame,
                          df_m5: pd.DataFrame | None = None,
                          df_m15: pd.DataFrame | None = None) -> dict:
    """
    Calcula el estado real del mercado a partir de las velas CERRADAS.

    Devuelve None en cada campo que no se pueda calcular con fiabilidad, en
    lugar de un valor por defecto. Ese es justamente el error que arruino el
    dataset anterior.
    """
    # run_live.py mete bot/ y bot/core en sys.path e importa `core` como paquete
    # de primer nivel, asi que el import relativo no siempre es valido. Se
    # intentan las dos formas: sin esto el diario se quedaria sin features y
    # habriamos repetido exactamente el fallo que este modulo viene a corregir.
    try:
        from ..backtest.indicators import atr as _atr, ema, rsi, sma, stochastic
    except (ImportError, ValueError):
        try:
            from bot.backtest.indicators import atr as _atr, ema, rsi, sma, stochastic
        except ImportError:
            from backtest.indicators import atr as _atr, ema, rsi, sma, stochastic

    out: dict[str, Any] = {}
    if df_m1 is None or len(df_m1) < 30:
        return out

    c = df_m1["close"]
    out["price"] = _f(c.iloc[-1])

    if len(df_m1) >= 15:
        out["rsi"] = _f(rsi(c, 14).iloc[-1])
        k, d = stochastic(df_m1, 14, 3, 3)
        out["stoch_k"] = _f(k.iloc[-1])
        out["stoch_d"] = _f(d.iloc[-1])
        a = _atr(df_m1, 14).iloc[-1]
        out["atr"] = _f(a)
        if _f(a) and out["price"]:
            out["atr_pct"] = _f(a / out["price"] * 100)

    for span, key in ((8, "ema8"), (21, "ema21"), (50, "ema50")):
        if len(df_m1) >= span:
            out[key] = _f(ema(c, span).iloc[-1])

    if out.get("ema21") and out.get("atr"):
        out["dist_ema21_atr"] = _f((out["price"] - out["ema21"]) / out["atr"])

    if len(df_m1) >= 20:
        mid = sma(c, 20).iloc[-1]
        sd = c.rolling(20).std().iloc[-1]
        if _f(sd):
            out["bb_position"] = _f((out["price"] - mid) / (2 * sd))

    last = df_m1.iloc[-1]
    if out.get("atr"):
        out["body_atr"] = _f(abs(last["close"] - last["open"]) / out["atr"])

    # Racha de velas consecutivas en la misma direccion.
    ups = (c > c.shift(1)).to_numpy()
    streak = 0
    for i in range(len(ups) - 1, 0, -1):
        if streak == 0:
            streak = 1 if ups[i] else -1
        elif (streak > 0) == bool(ups[i]):
            streak += 1 if ups[i] else -1
        else:
            break
    out["streak"] = int(streak)

    def trend_of(df: pd.DataFrame | None) -> str | None:
        if df is None or len(df) < 21:
            return None
        cc = df["close"]
        e8, e21 = ema(cc, 8).iloc[-1], ema(cc, 21).iloc[-1]
        if e8 > e21:
            return "UP"
        if e8 < e21:
            return "DOWN"
        return "FLAT"

    out["trend_m5"] = trend_of(df_m5)
    out["trend_m15"] = trend_of(df_m15)
    return out


class TradeJournal:
    """
    Diario append-only en JSONL, seguro entre hilos.

    JSONL y no JSON: el bot escribe desde varios hilos y un fichero unico que
    se reescribe entero se corrompe en cuanto hay un fallo a media escritura.
    """

    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._open: dict[str, TradeRecord] = {}

    # -- escritura --------------------------------------------------------

    def open_trade(self, asset: str, direction: str, strategy: str, setup: str,
                   amount: float, expiration_seconds: int,
                   confidence: float | None = None, payout: float | None = None,
                   features: dict | None = None, **extra) -> TradeRecord:
        now = time.time()
        dt = datetime.fromtimestamp(now, tz=timezone.utc)
        rec = TradeRecord(
            trade_id=uuid.uuid4().hex[:12],
            asset=asset,
            direction=direction,
            timestamp=now,
            hour_utc=dt.hour,
            weekday=dt.weekday(),
            synthetic="-OTC" in asset.upper(),
            strategy=strategy,
            setup=setup,
            confidence=_f(confidence),
            expiration_seconds=int(expiration_seconds),
            amount=float(amount),
            payout=_f(payout),
            extra=extra or {},
        )
        for key, value in (features or {}).items():
            if hasattr(rec, key):
                setattr(rec, key, value)

        with self._lock:
            self._open[rec.trade_id] = rec
        return rec

    def close_trade(self, trade_id: str, result: str, pnl: float,
                    exit_price: float | None = None) -> TradeRecord | None:
        with self._lock:
            rec = self._open.pop(trade_id, None)
        if rec is None:
            return None
        rec.result = result
        rec.pnl = _f(pnl)
        rec.exit_price = _f(exit_price)
        rec.closed_at = time.time()
        self._append(rec)
        return rec

    def _append(self, rec: TradeRecord) -> None:
        line = json.dumps(asdict(rec), ensure_ascii=False)
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())

    # -- lectura ----------------------------------------------------------

    def load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame()
        rows = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue          # una linea truncada no invalida el resto
        return pd.DataFrame(rows)

    @property
    def open_count(self) -> int:
        with self._lock:
            return len(self._open)

    def open_assets(self) -> set[str]:
        with self._lock:
            return {r.asset for r in self._open.values()}


_journal: TradeJournal | None = None


def get_journal(path: Path | str = DEFAULT_PATH) -> TradeJournal:
    global _journal
    if _journal is None:
        _journal = TradeJournal(path)
    return _journal
