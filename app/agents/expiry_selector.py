# -*- coding: utf-8 -*-
"""Selector de expiracion.

DOS CORRECCIONES
----------------
1. ROTURA POR CLAVES. Leía `edge.get("total", 0)` y `edge.get("win_rate", 0)`,
   pero `get_historical_edge()` devolvia `n` y `win_rate=None` cuando no hay
   muestra. Con `.get(..., 0)` sobre un `None` presente en el dict, `total`
   valia siempre 0 y `expectancy` nunca se comparaba bien: el selector no
   elegia nada, devolvia el defecto y lo justificaba como "mejor expectancy".

2. ELEGIA POR EXPECTANCY PUNTUAL. `max(valid, key=expectancy)` sobre buckets
   con 3 muestras es exactamente el sesgo que el resto del proyecto intenta
   eliminar: el bucket con mejor media muestral es, con muestra pequena, el que
   tuvo mas suerte. Ahora se ordena por `expectancy_lower` (la cota inferior de
   Wilson proyectada al payoff), que es la unica cifra que la muestra sostiene.

3. Los candidatos ya no dependen del modo de trading. Antes eran
   `[300, 180]` en practice y `[60, 120, 180, 300]` en el resto: dos sistemas
   distintos midiendo cosas distintas. Los candidatos los declara la estrategia
   (`Strategy.expiries`) y son los mismos siempre.

ARRANQUE EN FRIO
----------------
Si ninguna expiracion tiene muestra, no se finge elegir la mejor: se devuelve
la del medio del rango declarado y se marca `reason="arranque en frio"`. Elegir
"la de mejor expectancy" con cero datos es inventarse una decision.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from app.data.repository import repository as default_repository
from app.data.schemas import Direction, MarketRegime
from app.stats.core import breakeven_winrate

logger = logging.getLogger(__name__)


class ExpirySelector:
    """Elige la expiracion con mejor expectancy CON COTA INFERIOR."""

    #: Muestra minima para que una expiracion cuente como "validada".
    MIN_SAMPLES_FOR_CHOICE = 30

    def __init__(self, candidate_expiries: Optional[Sequence[int]] = None,
                 repository=None, persist: bool = True,
                 default_payout: float = 0.85):
        self.repo = repository or default_repository
        self.persist = persist
        self.default_payout = default_payout
        self.candidate_expiries = list(candidate_expiries) if candidate_expiries \
            else [60, 180, 300]

    def select(self, asset: str, strategy: str, direction: Direction,
               market_regime: MarketRegime, confidence: float,
               payout: Optional[float] = None,
               candidates_expiries: Optional[Sequence[int]] = None) -> dict:
        """Devuelve `{selected_expiry, payout, candidates, reason, ...}`."""
        candidates = list(candidates_expiries or self.candidate_expiries)
        if not candidates:
            candidates = [180]
        effective_payout = payout if payout and payout > 0 else self.default_payout
        break_even = breakeven_winrate(effective_payout)

        rows = []
        for expiry in candidates:
            try:
                edge = self.repo.get_historical_edge(
                    asset, strategy, direction, market_regime, expiry,
                    payout=effective_payout)
            except Exception as exc:                          # noqa: BLE001
                logger.warning("get_historical_edge fallo para %ss: %s", expiry, exc)
                edge = {"n": 0, "expectancy": None, "expectancy_lower": None,
                        "win_rate": None, "win_rate_lower": None}
            rows.append({
                "expiry": expiry,
                "samples": int(edge.get("n") or 0),
                "win_rate": edge.get("win_rate"),
                "win_rate_lower": edge.get("win_rate_lower"),
                "expectancy": edge.get("expectancy"),
                # La cota inferior de la expectancy: es lo que se compara.
                "expectancy_lower": edge.get("expectancy_lower"),
                "profit_factor": edge.get("profit_factor"),
                "break_even_wr": round(break_even, 4) if break_even else None,
            })

        validated = [r for r in rows
                     if r["samples"] >= self.MIN_SAMPLES_FOR_CHOICE
                     and r["expectancy_lower"] is not None]

        if not validated:
            # Arranque en frio: sin muestra no hay "mejor expiracion". Se toma
            # la del medio del rango declarado, que es la eleccion con menos
            # supuesto implicito (ni la mas rapida, que es puro ruido, ni la mas
            # lenta, que expone a mas recorrido adverso).
            ordered = sorted(candidates)
            chosen = ordered[len(ordered) // 2]
            return {
                "selected_expiry": chosen,
                "payout": effective_payout,
                "candidates": rows,
                "reason": (f"arranque en frio: ninguna expiracion tiene "
                           f"{self.MIN_SAMPLES_FOR_CHOICE}+ muestras; se usa {chosen}s "
                           f"(centro del rango declarado)"),
                "cold_start": True,
                "validated": [],
            }

        # Ordenar por cota INFERIOR de expectancy, no por la puntual.
        best = max(validated, key=lambda r: r["expectancy_lower"])
        positive = [r for r in validated if r["expectancy_lower"] > 0]
        return {
            "selected_expiry": best["expiry"],
            "payout": effective_payout,
            "candidates": rows,
            "reason": (
                f"expectancy_lower {best['expectancy_lower']:.4f} a {best['expiry']}s "
                f"con n={best['samples']} (break-even WR {break_even:.2%})"
                if best["expectancy_lower"] is not None else
                f"mejor candidata {best['expiry']}s con n={best['samples']}"
            ),
            "cold_start": False,
            "validated": positive,
            "best_expectancy": best["expectancy"],
            "best_expectancy_lower": best["expectancy_lower"],
            "best_win_rate": best["win_rate"],
        }
