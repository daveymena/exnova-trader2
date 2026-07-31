# -*- coding: utf-8 -*-
"""
Motor de backtest por replay de velas.

Reglas de diseno, todas orientadas a no enganarse a uno mismo:

1. **Sin look-ahead.** La estrategia solo ve velas CERRADAS hasta el instante de
   decision. El desenlace se resuelve con velas posteriores que la estrategia
   nunca tuvo delante.
2. **Payout realista.** Se usa el payout medido en la cuenta (0.838), no el 85%
   de folleto. La diferencia decide si un sistema es rentable o no.
3. **Veredicto con intervalo de confianza.** Un winrate puntual no significa
   nada; solo concluimos si el IC95% entero cae de un lado del break-even.
4. **Walk-forward.** El split in-sample / out-of-sample es cronologico, nunca
   aleatorio: mezclar el tiempo filtra informacion del futuro.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Protocol

import pandas as pd

# Timeframes derivados que se ofrecen a la estrategia, en segundos.
DERIVED_TFS = (300, 900)


@dataclass
class Signal:
    """Decision de entrada emitida por una estrategia."""
    direction: str                      # "CALL" o "PUT"
    expiration_seconds: int
    setup: str                          # nombre del setup, para atribuir resultados
    confidence: float = 1.0
    meta: dict = field(default_factory=dict)


class Strategy(Protocol):
    """Contrato minimo que debe cumplir cualquier estrategia backtesteable."""

    name: str

    def evaluate(self, frames: dict[int, pd.DataFrame], now: pd.Timestamp) -> Optional[Signal]:
        """Devuelve una Signal o None. `frames` solo contiene velas cerradas."""
        ...


@dataclass
class BacktestConfig:
    payout: float = 0.838
    stake: float = 1.0
    warmup_bars: int = 200              # velas M1 necesarias antes de operar
    min_bars_between_trades: int = 3    # evita apilar entradas sobre la misma senal
    oos_fraction: float = 0.30          # ultimo 30% del historico reservado
    max_trades: int | None = None

    @property
    def breakeven_winrate(self) -> float:
        return 1.0 / (1.0 + self.payout)


@dataclass
class BacktestTrade:
    time: pd.Timestamp
    asset: str
    setup: str
    direction: str
    entry_price: float
    exit_price: float
    expiration_seconds: int
    result: str                         # WIN / LOSS / TIE
    pnl: float
    segment: str                        # "in_sample" u "out_of_sample"
    confidence: float = 1.0


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


@dataclass
class StrategyResult:
    """Resultado agregado, con el veredicto estadistico ya calculado."""
    strategy: str
    trades: list[BacktestTrade]
    config: BacktestConfig

    def _subset(self, segment: str | None = None, setup: str | None = None) -> list[BacktestTrade]:
        out = self.trades
        if segment:
            out = [t for t in out if t.segment == segment]
        if setup:
            out = [t for t in out if t.setup == setup]
        return [t for t in out if t.result != "TIE"]

    def stats(self, segment: str | None = None, setup: str | None = None) -> dict:
        subset = self._subset(segment, setup)
        n = len(subset)
        wins = sum(1 for t in subset if t.result == "WIN")
        pnl = sum(t.pnl for t in subset)
        lo, hi = wilson_interval(wins, n)
        be = self.config.breakeven_winrate

        if n == 0:
            verdict = "SIN DATOS"
        elif lo > be:
            verdict = "EDGE REAL"
        elif hi < be:
            verdict = "PERDEDOR REAL"
        else:
            verdict = "RUIDO (indistinguible)"

        return {
            "n": n,
            "wins": wins,
            "winrate": wins / n if n else 0.0,
            "ci_low": lo,
            "ci_high": hi,
            "breakeven": be,
            "pnl": pnl,
            "expectancy": (pnl / n) if n else 0.0,
            "max_drawdown": self._max_drawdown(subset),
            "verdict": verdict,
        }

    @staticmethod
    def _max_drawdown(trades: list[BacktestTrade]) -> float:
        equity, peak, worst = 0.0, 0.0, 0.0
        for t in trades:
            equity += t.pnl
            peak = max(peak, equity)
            worst = min(worst, equity - peak)
        return worst

    @property
    def setups(self) -> list[str]:
        return sorted({t.setup for t in self.trades})

    def report(self) -> str:
        lines = [
            "=" * 78,
            f"BACKTEST: {self.strategy}",
            "=" * 78,
            f"Payout {self.config.payout:.4f} -> break-even {100 * self.config.breakeven_winrate:.2f}%",
            "",
        ]
        for segment in ("in_sample", "out_of_sample"):
            s = self.stats(segment)
            lines.append(
                f"{segment:<14} n={s['n']:<5} wr={100 * s['winrate']:5.1f}% "
                f"IC95%[{100 * s['ci_low']:5.1f}%,{100 * s['ci_high']:5.1f}%] "
                f"pnl={s['pnl']:8.2f} dd={s['max_drawdown']:7.2f}  {s['verdict']}"
            )

        lines.append("")
        lines.append("POR SETUP (out-of-sample, que es el unico que cuenta):")
        for setup in self.setups:
            s = self.stats("out_of_sample", setup)
            if not s["n"]:
                continue
            lines.append(
                f"  {setup[:26]:<26} n={s['n']:<5} wr={100 * s['winrate']:5.1f}% "
                f"IC95%[{100 * s['ci_low']:5.1f}%,{100 * s['ci_high']:5.1f}%] "
                f"pnl={s['pnl']:8.2f}  {s['verdict']}"
            )

        oos = self.stats("out_of_sample")
        lines.append("")
        if oos["verdict"] == "EDGE REAL":
            lines.append("CONCLUSION: edge sostenido fuera de muestra. Candidato a produccion.")
        elif oos["verdict"] == "RUIDO (indistinguible)":
            needed = self._samples_needed(oos["winrate"])
            lines.append(
                f"CONCLUSION: sin evidencia. Con este winrate harian falta ~{needed:,} "
                f"trades para concluir algo. NO promover a produccion."
            )
        else:
            lines.append("CONCLUSION: pierde dinero de forma demostrable. Descartar.")
        return "\n".join(lines)

    def _samples_needed(self, p_true: float) -> int:
        p_null = self.config.breakeven_winrate
        if abs(p_true - p_null) < 1e-6:
            return 10 ** 9
        z_a, z_b = 1.96, 0.84
        pooled = (p_true + p_null) / 2
        num = z_a * math.sqrt(2 * pooled * (1 - pooled)) + z_b * math.sqrt(
            p_true * (1 - p_true) + p_null * (1 - p_null)
        )
        return math.ceil((num / (p_true - p_null)) ** 2)


class ReplayEngine:
    """Reproduce velas M1 barra a barra y resuelve cada entrada con datos futuros."""

    def __init__(self, config: BacktestConfig | None = None):
        self.config = config or BacktestConfig()

    @staticmethod
    def resample(df_m1: pd.DataFrame, seconds: int) -> pd.DataFrame:
        """Agrega M1 a un timeframe mayor. Solo velas completas."""
        rule = f"{seconds // 60}min"
        agg = df_m1.resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        )
        return agg.dropna()

    def run(self, strategy: Strategy, df_m1: pd.DataFrame, asset: str) -> StrategyResult:
        cfg = self.config
        df_m1 = df_m1.sort_index()
        trades: list[BacktestTrade] = []

        if len(df_m1) < cfg.warmup_bars + 10:
            return StrategyResult(strategy.name, trades, cfg)

        split_idx = int(len(df_m1) * (1 - cfg.oos_fraction))
        last_trade_bar = -10 ** 9

        for i in range(cfg.warmup_bars, len(df_m1) - 1):
            if cfg.max_trades and len(trades) >= cfg.max_trades:
                break
            if i - last_trade_bar < cfg.min_bars_between_trades:
                continue

            # Solo velas cerradas: el corte es exclusivo en i.
            window = df_m1.iloc[:i]
            now = df_m1.index[i]

            frames = {60: window}
            for tf in DERIVED_TFS:
                frames[tf] = self.resample(window, tf)

            try:
                signal = strategy.evaluate(frames, now)
            except Exception:
                continue
            if signal is None:
                continue

            # La entrada ocurre en la apertura de la vela i (la primera no vista).
            entry_price = float(df_m1["open"].iloc[i])
            bars_ahead = max(1, signal.expiration_seconds // 60)
            exit_idx = i + bars_ahead
            if exit_idx >= len(df_m1):
                break
            exit_price = float(df_m1["close"].iloc[exit_idx])

            if exit_price == entry_price:
                result, pnl = "TIE", 0.0
            elif (signal.direction == "CALL") == (exit_price > entry_price):
                result, pnl = "WIN", cfg.stake * cfg.payout
            else:
                result, pnl = "LOSS", -cfg.stake

            trades.append(
                BacktestTrade(
                    time=now,
                    asset=asset,
                    setup=signal.setup,
                    direction=signal.direction,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    expiration_seconds=signal.expiration_seconds,
                    result=result,
                    pnl=pnl,
                    segment="in_sample" if i < split_idx else "out_of_sample",
                    confidence=signal.confidence,
                )
            )
            last_trade_bar = i

        return StrategyResult(strategy.name, trades, cfg)

    def run_many(self, strategy: Strategy,
                 datasets: Iterable[tuple[str, pd.DataFrame]]) -> StrategyResult:
        """Ejecuta la misma estrategia sobre varios activos y agrega resultados."""
        all_trades: list[BacktestTrade] = []
        for asset, df in datasets:
            all_trades.extend(self.run(strategy, df, asset).trades)
        all_trades.sort(key=lambda t: t.time)
        return StrategyResult(strategy.name, all_trades, self.config)
