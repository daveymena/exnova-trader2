"""
LiquiditySweepDetector — Barrido de liquidez + reclaim (Smart Money)
=====================================================================
Concepto SMC adaptado a binarias OTC de 30s-5m:

El precio a menudo "caza" liquidez antes de un movimiento real: barre el
extremo opuesto de la zona (soporte→mínimos/stop-loss; resistencia→máximos)
y luego la RECONQUISTA. Ese sweep+reclaim es la firma de manipulación/
precio-justo que marca la entrada institucional.

Este detector complementa a ``_detect_bounce_stage`` del motor: primero el
sweep (manipulación), luego el reclaim (interés real); el rebote confirmado
del motor cierra la secuencia.

Afinado con datos del sistema (500 trades OTC): el edge direccional real
está en operar a favor de tendencia (~54.7% WR) tras una falsa ruptura del
nivel; sin sweep el setup pierde fuerza.
"""

from typing import Dict, Optional

import numpy as np
import pandas as pd


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    """ATR simple sobre high-low de las velas disponibles."""
    if df is None or len(df) < 3:
        return 0.0
    hl = df["high"] - df["low"]
    if len(hl) < period:
        return float(hl.max())
    return float(hl.tail(period).mean())


class LiquiditySweepDetector:
    """Detecta barrido de liquidez (sweep) + reconquista (reclaim) en M1/M5."""

    def __init__(self, lookback: int = 8, max_fresh_bars: int = 2,
                 buffer_atr_mult: float = 0.30, reclaim_close_mult: float = 0.20):
        self.lookback = lookback
        self.max_fresh_bars = max_fresh_bars
        self.buffer_atr_mult = buffer_atr_mult
        self.reclaim_close_mult = reclaim_close_mult

    # ------------------------------------------------------------------
    def analyze(self, df: Optional[pd.DataFrame], zone_level: float,
                zone_type: str = "support", price: Optional[float] = None) -> Dict:
        """
        zone_type: 'support' (CALL) o 'resistance' (PUT).
        Soporte  -> sweep bajista: barre mínimo bajo el soporte y reconquista.
        Resist.  -> sweep alcista: barre máximo sobre la resistencia y reconquista.
        """
        empty = {
            "detected": False, "side": "none", "stage": "NONE",
            "reason": "sin barrido", "extent_pct": 0.0, "bars_since": 99,
        }
        if df is None or len(df) < 5 or not zone_level:
            return empty
        if zone_type not in {"support", "resistance"}:
            return empty

        df_work = df.copy()
        recent = df_work.tail(self.lookback)
        atr = _atr(df_work)
        if atr <= 0:
            return empty

        base_buffer = max(atr * self.buffer_atr_mult, zone_level * 0.0004)
        price = float(price) if price is not None else float(df_work["close"].iloc[-1])
        last_close = float(df_work["close"].iloc[-1])

        if zone_type == "support":
            swept = recent["low"] <= (zone_level - base_buffer)
            candles_since = None
            extreme_idx = None
            for i in range(len(recent) - 1, -1, -1):
                if recent.iloc[i]["low"] <= (zone_level - base_buffer):
                    extreme_idx = i
                    candles_since = len(recent) - 1 - i
                else:
                    break
            if not swept.any():
                return empty
            if last_close <= zone_level:
                return {
                    "detected": False, "side": "bullish_pending", "stage": "NO_RECLAIM",
                    "reason": "sweep bajo soporte sin reconquista aun",
                    "extent_pct": self._extent(recent, zone_level, "low", "below", extreme_idx),
                    "bars_since": candles_since or 0,
                }
            stage = "FRESH" if (candles_since is not None and candles_since <= self.max_fresh_bars) else "STALE"
            return {
                "detected": True, "side": "bullish", "stage": stage,
                "reason": "sweep bajo soporte + reclaim alcista",
                "extent_pct": self._extent(recent, zone_level, "low", "below", extreme_idx),
                "bars_since": candles_since or 0,
                "reclaim_pct": max(0.0, (last_close - zone_level) / zone_level * 100.0),
            }

        # resistance
        swept = recent["high"] >= (zone_level + base_buffer)
        extreme_idx = None
        candles_since = None
        for i in range(len(recent) - 1, -1, -1):
            if recent.iloc[i]["high"] >= (zone_level + base_buffer):
                extreme_idx = i
                candles_since = len(recent) - 1 - i
            else:
                break
        if not swept.any():
            return empty
        if last_close >= zone_level:
            return {
                "detected": False, "side": "bearish_pending", "stage": "NO_RECLAIM",
                "reason": "sweep sobre resistencia sin reconquista aun",
                "extent_pct": self._extent(recent, zone_level, "high", "above", extreme_idx),
                "bars_since": candles_since or 0,
            }
        stage = "FRESH" if (candles_since is not None and candles_since <= self.max_fresh_bars) else "STALE"
        return {
            "detected": True, "side": "bearish", "stage": stage,
            "reason": "sweep sobre resistencia + reclaim bajista",
            "extent_pct": self._extent(recent, zone_level, "high", "above", extreme_idx),
            "bars_since": candles_since or 0,
            "reclaim_pct": max(0.0, (zone_level - last_close) / zone_level * 100.0),
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _extent(recent: pd.DataFrame, zone_level: float, col: str,
                side: str, extreme_idx: Optional[int]) -> float:
        """Qué tan profundo barrió el precio la zona (%)."""
        if extreme_idx is None:
            return 0.0
        extreme = float(recent.iloc[extreme_idx][col])
        if zone_level <= 0:
            return 0.0
        if side == "below":
            return max(0.0, (zone_level - extreme) / zone_level * 100.0)
        return max(0.0, (extreme - zone_level) / zone_level * 100.0)