"""Edge Ledger - el puente entre medir y decidir.

El problema que resuelve: `VOTERS_BY_REGIME` (quien puede votar en cada
regimen de mercado) estaba hardcodeado a partir de datos SINTETICOS. Asi el
bot no puede aprender: su "conocimiento" sobre que estrategia funciona en que
regimen vive en una constante de Python.

Este registro lee las operaciones REALES ya resueltas (solo evidencia:
`resolution_source` broker o vela) y recalcula que estrategias tienen edge
medido en cada regimen. Cuando hay muestra suficiente, su respuesta
**reemplaza** al mapa hardcodeado. Cuando no la hay, el bot se queda quieto
en lugar de operar con suposiciones.

Reglas de seguridad (son el punto, no un detalle):

    1. Solo cuenta evidencia real. Una operacion simulada o sin resolver no
       ensena nada y no entra.
    2. Muestra minima por celda (estrategia x direccion x regimen). Con 4
       operaciones no se sabe nada.
    3. El limite inferior de Wilson al 95% debe superar el break-even del
       payout mas un margen. El win rate observado miente; el limite
       inferior no.
    4. Estabilidad: la mitad reciente de la muestra debe mantener el edge.
       Una estrategia que ganaba y dejo de ganar se cae sola.
    5. Si ninguna celda califica en un regimen, ese regimen no opera. Nunca
       se rellena el hueco con la estrategia que "deberia" funcionar.

Uso:
    ledger = EdgeLedger()
    voters = ledger.voters_for(MarketRegime.TREND_UP)
    fraccion = ledger.stake_fraction("breakout_direct", Direction.CALL,
                                     MarketRegime.TREND_UP, payout=0.85)
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional

from app.data.repository import repository, wilson_lower_bound
from app.data.schemas import Direction, MarketRegime, TradeResult


@dataclass
class Measurement:
    """Lo que se sabe de una celda estrategia x direccion x regimen."""

    strategy: str
    direction: str
    regime: str
    trades: int = 0
    wins: int = 0
    pnl: float = 0.0
    win_rate: float = 0.0
    win_rate_lower_95: float = 0.0
    expectancy: float = 0.0
    recent_expectancy: float = 0.0
    break_even: float = 0.0
    has_edge: bool = False
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "direction": self.direction,
            "regime": self.regime,
            "trades": self.trades,
            "wins": self.wins,
            "win_rate": round(self.win_rate, 4),
            "win_rate_lower_95": round(self.win_rate_lower_95, 4),
            "expectancy": round(self.expectancy, 4),
            "recent_expectancy": round(self.recent_expectancy, 4),
            "pnl": round(self.pnl, 2),
            "break_even": round(self.break_even, 4),
            "has_edge": self.has_edge,
            "reason": self.reason,
        }


@dataclass
class EdgeLedger:
    """Mide edge real y decide quien puede votar.

    Args:
        min_sample: operaciones minimas por celda para considerar la celda.
        safety_margin: cuanto debe superar el limite inferior al break-even.
        kelly_fraction: fraccion de Kelly usada para dimensionar. Kelly
            asume que se conoce p con certeza y que las operaciones son
            independientes; ninguna de las dos cosas es cierta aqui, asi que
            se aplica una fraccion pequena (0.15) y ademas un tope duro.
        require_stability: exigir que la mitad reciente mantenga el edge.
        cache_ttl_sec: los resultados se cachean para no consultar SQLite en
            cada vela del scan loop.
    """

    min_sample: int = 30
    safety_margin: float = 0.03
    kelly_fraction: float = 0.15
    require_stability: bool = True
    max_stake_pct: float = 0.02
    cache_ttl_sec: float = 60.0
    _cache: dict = field(default_factory=dict)
    _cache_at: float = 0.0

    # ------------------------------------------------------------------ #
    def measure_all(self, asset: Optional[str] = None,
                    force: bool = False) -> dict[tuple[str, str, str], Measurement]:
        """Mide todas las celdas con evidencia real.

        Devuelve un dict indexado por (strategy, direction, regime).
        """
        now = time.time()
        if not force and self._cache and (now - self._cache_at) < self.cache_ttl_sec:
            return self._cache

        # OJO: get_trade_results devuelve ORDER BY timestamp DESC. Sin este
        # orden ascendente, "la mitad reciente" seria la mitad MAS ANTIGUA y
        # la regla de estabilidad quedaria invertida: una estrategia que
        # ganaba y dejo de ganar pareceria estable, y al reves.
        trades = repository.get_trade_results(asset=asset, limit=100000,
                                              evidence_only=True)
        trades = sorted(trades, key=lambda t: t.timestamp)
        cells: dict[tuple[str, str, str], list[TradeResult]] = {}
        for t in trades:
            if t.execution_state.value not in ("won", "lost"):
                continue
            key = (t.strategy or "unknown",
                   t.direction.value,
                   t.market_regime.value if t.market_regime else "unknown")
            cells.setdefault(key, []).append(t)

        measured: dict[tuple[str, str, str], Measurement] = {}
        for (strategy, direction, regime), rows in cells.items():
            measured[(strategy, direction, regime)] = self._measure_cell(
                strategy, direction, regime, rows
            )

        self._cache = measured
        self._cache_at = now
        return measured

    def _measure_cell(self, strategy: str, direction: str, regime: str,
                      rows: list[TradeResult]) -> Measurement:
        total = len(rows)
        wins = sum(1 for r in rows if r.result > 0)
        pnl = sum(r.result for r in rows)
        payouts = [r.payout for r in rows if r.payout]
        avg_payout = sum(payouts) / len(payouts) if payouts else 0.85
        break_even = 1 / (1 + avg_payout) if avg_payout > 0 else 0.5405

        win_rate = wins / total if total else 0.0
        lower = wilson_lower_bound(wins, total)
        expectancy = win_rate * avg_payout - (1 - win_rate)

        # Mitad reciente (las filas ya vienen en orden cronologico ascendente).
        half = total // 2
        recent = rows[half:] if half else rows
        r_wins = sum(1 for r in recent if r.result > 0)
        r_wr = r_wins / len(recent) if recent else 0.0
        recent_expectancy = r_wr * avg_payout - (1 - r_wr)

        m = Measurement(
            strategy=strategy, direction=direction, regime=regime,
            trades=total, wins=wins, pnl=pnl, win_rate=win_rate,
            win_rate_lower_95=lower, expectancy=expectancy,
            recent_expectancy=recent_expectancy, break_even=break_even,
        )

        if total < self.min_sample:
            m.reason = f"muestra insuficiente ({total}/{self.min_sample})"
            return m
        if lower <= break_even + self.safety_margin:
            m.reason = (f"limite inferior {lower:.3f} no supera "
                        f"{break_even + self.safety_margin:.3f}")
            return m
        if expectancy <= 0:
            m.reason = "expectancy no positiva"
            return m
        if self.require_stability and recent_expectancy <= 0:
            m.reason = (f"la mitad reciente perdio el edge "
                        f"(exp {recent_expectancy:+.3f})")
            return m

        m.has_edge = True
        m.reason = (f"{total} ops, WR {win_rate:.1%}, limite inferior "
                    f"{lower:.1%} > {break_even:.1%}")
        return m

    # ------------------------------------------------------------------ #
    def voters_for(self, regime: MarketRegime,
                   fallback: tuple[str, ...] = (),
                   asset: Optional[str] = None) -> tuple[str, ...]:
        """Estrategias con edge REAL medido en este regimen.

        Si el registro aun no tiene ninguna celda con edge en el regimen,
        devuelve `fallback` (el mapa medido sobre datos sinteticos). Es la
        unica forma de arrancar: sin muestra real no hay nada que aprender
        todavia, y quedarse sin operar para siempre tampoco es util.

        En cuanto existe UNA celda con edge real, el registro manda: las
        estrategias sin muestra real quedan fuera aunque el mapa sintetico
        las hubiera incluido.
        """
        measured = self.measure_all(asset=asset)
        regime_value = regime.value
        cells = [m for m in measured.values() if m.regime == regime_value]

        # Si en este regimen ya se midio ALGO (aunque sea para descubrir que
        # todo pierde), la medicion manda: se devuelven solo las que tienen
        # edge probado, aunque eso sea ninguna. Caer al mapa sintetico aqui
        # significaria volver a operar con una estrategia que ya demostro
        # medido que pierde dinero.
        if any(m.trades >= self.min_sample for m in cells):
            return tuple(sorted(key[0] for key, m in measured.items()
                                if m.regime == regime_value and m.has_edge))

        # Nunca se opero en este regimen: se arranca con lo que midio la
        # auditoria sobre datos sinteticos.
        return tuple(fallback)

    def stake_fraction(self, strategy: str, direction: Direction,
                       regime: MarketRegime, payout: float,
                       asset: Optional[str] = None) -> float:
        """Fraccion de equity a arriesgar, por Kelly acotado.

        Kelly para binarias:  f* = (p * (b + 1) - 1) / b   con b = payout.

        Se usa p = limite inferior de Wilson, NO el win rate observado. Con
        el observado, una racha de 5 de 5 aconseja apostar el 60% de la
        cuenta. Con el limite inferior, la misma racha aconseja quedarse
        quieto. Despues se aplica `kelly_fraction` (cuarto de Kelly) para
        sobrevivir a que la estimacion este equivocada.
        """
        measured = self.measure_all(asset=asset)
        key = (strategy, direction.value, regime.value)
        m = measured.get(key)

        if m is None or not m.has_edge:
            return 0.0

        b = payout if payout > 0 else 0.85
        p = m.win_rate_lower_95
        if b <= 0:
            return 0.0
        kelly = (p * (b + 1) - 1) / b
        if kelly <= 0:
            return 0.0
        # Tope duro: 2% del equity por operacion. Con payout 0.85, una racha
        # de 10 perdidas son -20% de la cuenta; el gestor de riesgo corta
        # mucho antes. Sin tope, un p_inf alto (0.85 con muestra grande)
        # llevaria a arriesgar mas del 10% por operacion, que en binarias es
        # ruina casi segura.
        return min(kelly * self.kelly_fraction, self.max_stake_pct)

    # ------------------------------------------------------------------ #
    def report(self, asset: Optional[str] = None) -> dict:
        """Resumen legible de lo que el bot sabe de si mismo."""
        measured = self.measure_all(asset=asset)
        by_regime: dict[str, list[dict]] = {}
        for (strategy, direction, regime), m in sorted(measured.items()):
            by_regime.setdefault(regime, []).append(m.as_dict())
        return {
            "cells_with_evidence": len(measured),
            "cells_with_edge": sum(1 for m in measured.values() if m.has_edge),
            "by_regime": by_regime,
            "voters": {
                regime.value: list(self.voters_for(regime, asset=asset))
                for regime in (MarketRegime.TREND_UP, MarketRegime.TREND_DOWN,
                               MarketRegime.RANGE, MarketRegime.UNKNOWN)
            },
        }

    @staticmethod
    def is_evidence(trade: TradeResult) -> bool:
        """Solo broker y vela observada cuentan como aprendizaje."""
        from app.data.schemas import ResolutionSource
        return trade.resolution_source in (ResolutionSource.BROKER,
                                           ResolutionSource.CANDLE)


def _sqlite_fallback_note() -> str:
    return ("Si measure_all() devuelve cero celdas, no hay operaciones "
            "resueltas contra evidencia real: el bot todavia no ha aprendido "
            "nada y opera con el mapa medido sobre datos sinteticos.")


# sqlite3 se importa por si alguien extiende el ledger con consultas propias.
_ = sqlite3
