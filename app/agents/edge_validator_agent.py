# -*- coding: utf-8 -*-
"""Validador de edge: el portero antes de ejecutar.

DOS BUGS CORREGIDOS
-------------------
1. DECIDIA CON EL WIN RATE PUNTUAL (punto 4 de la auditoria). Comparaba
   `win_rate < break_even + 3 puntos`. Un 66.7% sobre n=9 pasa ese filtro y su
   intervalo de Wilson va de 35% a 88%: no dice nada. Ahora se exige que la
   COTA INFERIOR de Wilson supere el break-even, que es la unica afirmacion
   que la muestra sostiene.

2. EL MINIMO DE MUESTRA BAJABA A 3 SEGUN EL MODO (punto 5), y el filtro de
   payout se saltaba entero en practice. Relajar el gate segun el modo
   convertia la validacion en adorno justo donde el sistema pasa semanas
   acumulando datos. Ahora:
     * el minimo de muestra NO depende del modo;
     * el payout minimo se exige SIEMPRE, porque no es una politica sino
       aritmetica: con payout 0.60 el break-even es 62.5% y no hay estrategia
       de binarias que sostenga eso de forma consistente.

UNA SOLA AUTORIDAD ESTADISTICA
------------------------------
Este modulo NO re-decide si hay edge: lo decide `SetupEvaluator`, que es quien
aplica Wilson, el margen de seguridad, la penalizacion por miradas repetidas y
la correccion por comparaciones multiples dentro de la familia.

Si aqui se recalculara el intervalo con un z fijo de 1.96, los dos gates
acabarian contradiciendose: el evaluador diria RUIDO (porque el setup lleva 5
miradas y su alpha esta penalizado) mientras este diria "edge probado", o al
reves. Dos autoridades sobre la misma pregunta es la receta del deadlock --
setup en PRODUCCION cuyas operaciones bloquea el validador, o setup en
EXPLORACION operando a tamano completo.

Cuando se le pasa el `SetupRecord`, este modulo actua como GATE DE ADMISION:
comprueba payout, estado del setup y arranque en frio, y DELEGA el veredicto
estadistico. Solo recalcula el intervalo por su cuenta cuando se usa aislado
(backtests, scripts, tests unitarios), y entonces aplica exactamente el mismo
umbral: break-even + safety_margin sobre la cota inferior de Wilson.

LA CIRCULARIDAD, RESUELTA SIN TRAMPAS
-------------------------------------
El problema real: no se puede operar sin evidencia, y no se acumula evidencia
sin operar. La version anterior lo "resolvia" bajando el minimo a 3, que es
volver al bug 1 por la puerta de atras.

La solucion correcta es separar las dos preguntas:
  * "tiene este setup edge DEMOSTRADO?"  -> requiere n >= min_observations y
    cota de Wilson sobre el break-even. Mientras no, la respuesta es NO.
  * "se puede operar para averiguarlo?"  -> SI, en estado EXPLORACION y a
    tamano reducido (lo decide el SetupEvaluator, no este modulo).

Asi el sistema compra informacion barata y solo escala cuando la estadistica lo
sostiene. `approved` significa "autorizado a operar en su estado actual", y
`edge_proven` significa "tiene edge demostrado"; son cosas distintas y el
diccionario devuelto las separa explicitamente.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.config import config, TradingMode
from app.data.repository import repository as default_repository
from app.data.schemas import Direction, MarketRegime, SetupRecord, SetupState
from app.stats.core import breakeven_winrate, summarize_binomial

logger = logging.getLogger(__name__)


class EdgeValidatorAgent:
    """Portero estadistico. Determinista: no consulta IA ni red."""

    def __init__(self, repository=None,
                 min_sample_size: Optional[int] = None,
                 min_payout: Optional[float] = None,
                 safety_margin: Optional[float] = None,
                 exploration_min_observations: int = 30):
        self.repo = repository or default_repository
        self.min_sample_size = min_sample_size if min_sample_size is not None \
            else config.backtest_min_sample_size
        self.min_payout = min_payout if min_payout is not None else config.backtest_min_payout
        self.safety_margin = safety_margin if safety_margin is not None \
            else config.backtest_safety_margin
        self.exploration_min_observations = exploration_min_observations

    def validate(self, asset: str, strategy: str, direction: Direction,
                 market_regime: MarketRegime, expiry: int, payout: float,
                 confidence: float = 0.0,
                 entry_timing_type: str = "enter_now",
                 setup_state: SetupState = SetupState.EXPLORACION,
                 setup: Optional[SetupRecord] = None,
                 summary: Optional[dict] = None) -> dict:
        """Devuelve el dict de validacion. Nunca lanza.

        `setup` es el `SetupRecord` del evaluador. Cuando se pasa, su veredicto
        es autoritativo y este modulo solo aplica las politicas de admision.
        """
        reasons: list[str] = []
        warnings: list[str] = []
        break_even = breakeven_winrate(payout)
        if setup is not None:
            # El estado real del setup manda sobre el que se haya pasado suelto:
            # permitir que el llamante declare "PRODUCCION" sin que el evaluador
            # lo respalde seria abrir la puerta a operar a tamano completo sin
            # evidencia, que es justo lo que este gate existe para impedir.
            setup_state = setup.state

        # ── 1. payout: SIEMPRE se comprueba, en todos los modos ───────────
        # No es una politica configurable por modo: es aritmetica. La version
        # anterior lo saltaba en practice (`and not is_practice`), permitiendo
        # acumular "evidencia" sobre instrumentos matematicamente inviables.
        if break_even is None:
            return self._reject(["payout invalido: no se puede calcular el break-even"],
                                payout=payout)
        if payout < self.min_payout:
            return self._reject(
                [f"payout {payout:.2f} por debajo del minimo {self.min_payout:.2f} "
                 f"(break-even {break_even:.2%})"], payout=payout, break_even=break_even)

        # ── 2. setup retirado: no se opera, tenga la muestra que tenga ────
        if setup_state == SetupState.RETIRADO:
            return self._reject(
                ["setup RETIRADO por el evaluador estadistico"],
                payout=payout, break_even=break_even, setup_state=setup_state)

        # ── 3. evidencia historica ────────────────────────────────────────
        if summary is None:
            try:
                summary = self.repo.get_historical_edge(
                    asset, strategy, direction, market_regime, expiry, payout=payout)
            except Exception as exc:                          # noqa: BLE001
                logger.exception("get_historical_edge fallo")
                return self._reject([f"error consultando el edge: {exc}"],
                                    payout=payout, break_even=break_even)
        n = int(summary.get("n") or 0)

        base = {
            "payout": payout,
            "break_even_wr": round(break_even, 4),
            "required_wr": round(break_even + self.safety_margin, 4),
            "edge_data": summary,
            "safety_margin_applied": self.safety_margin,
            "n": n,
            "current_wr": summary.get("win_rate"),
            "win_rate_lower": summary.get("win_rate_lower"),
            "expectancy": summary.get("expectancy"),
            "expectancy_lower": summary.get("expectancy_lower"),
            "profit_factor": summary.get("profit_factor"),
            "setup_state": setup_state.value,
            "mode": config.mode.value,
        }

        # ── 3a. arranque en frio: se autoriza EXPLORAR, no se afirma edge ──
        if n < self.exploration_min_observations:
            if setup_state != SetupState.EXPLORACION:
                # Un setup en PRODUCCION que de repente no tiene muestra es una
                # inconsistencia de estado: se rechaza y se degrada.
                return self._reject(
                    [f"estado {setup_state.value} sin muestra (n={n})"],
                    **base)
            return {
                **base,
                "approved": True,
                "edge_proven": False,
                "exploration": True,
                "reasons": [],
                "warnings": [
                    f"arranque en frio: n={n} < {self.exploration_min_observations}. "
                    f"Se autoriza en EXPLORACION a tamano reducido para comprar "
                    f"muestra. Esto NO afirma ningun edge."
                ],
            }

        # ── 3b. hay muestra pero por debajo del minimo para concluir ──────
        if n < self.min_sample_size:
            return {
                **base,
                "approved": setup_state == SetupState.EXPLORACION,
                "edge_proven": False,
                "exploration": setup_state == SetupState.EXPLORACION,
                "reasons": [] if setup_state == SetupState.EXPLORACION else [
                    f"muestra insuficiente para PRODUCCION: n={n} < {self.min_sample_size}"
                ],
                "warnings": [
                    f"n={n} < {self.min_sample_size}: el veredicto estadistico sigue "
                    f"siendo INSUFICIENTE. Se opera reducido, no se escala."
                ],
            }

        # ── 4. veredicto. Si hay SetupRecord, MANDA el evaluador ──────────
        # Es la unica autoridad estadistica: ya aplico Wilson, el margen de
        # seguridad, la penalizacion por miradas repetidas y la correccion por
        # comparaciones multiples dentro de la familia. Recalcular aqui con un z
        # distinto daria dos respuestas contradictorias a la misma pregunta.
        if setup is not None and n >= self.min_sample_size:
            if setup_state == SetupState.PRODUCCION:
                if setup.looks > 1:
                    warnings.append(
                        f"veredicto del evaluador: {setup.verdict.value} con n={setup.n} "
                        f"tras {setup.looks} miradas (alpha penalizado). "
                        f"IC_inf={setup.win_rate_lower}"
                    )
                return {
                    **base,
                    "approved": True,
                    "edge_proven": True,
                    "exploration": False,
                    "reasons": [],
                    "warnings": warnings,
                    "verdict": setup.verdict.value,
                    "looks": setup.looks,
                }
            return self._reject(
                [f"el evaluador no acredita edge: veredicto={setup.verdict.value}, "
                 f"n={setup.n}, IC_inf={setup.win_rate_lower}, umbral="
                 f"{round((break_even or 0) + self.safety_margin, 4)}"],
                **{**base, "verdict": setup.verdict.value, "looks": setup.looks})

        # ── 4b. uso aislado (sin evaluador): mismo umbral, calculado aqui ──
        wr_lower = summary.get("win_rate_lower")
        wr = summary.get("win_rate")
        if wr_lower is None or wr is None:
            return self._reject(["muestra presente pero sin intervalo calculable"],
                                **base)

        required = break_even + self.safety_margin
        if wr_lower <= required:
            reasons.append(
                f"cota inferior de Wilson {wr_lower:.4f} <= break-even+margen "
                f"{required:.4f} (WR puntual {wr:.4f}, n={n}). El win rate puntual "
                f"NO es suficiente: con este IC no se puede afirmar edge."
            )
            return self._reject(reasons, **base)

        expectancy_lower = summary.get("expectancy_lower")
        if expectancy_lower is not None and expectancy_lower <= 0:
            reasons.append(
                f"expectancy con cota inferior {expectancy_lower:.4f} no es positiva"
            )
            return self._reject(reasons, **base)

        if summary.get("profit_factor") is not None and summary["profit_factor"] < 1.0:
            warnings.append(f"profit factor {summary['profit_factor']:.4f} < 1.0")

        return {
            **base,
            "approved": True,
            "edge_proven": True,
            "exploration": False,
            "reasons": [],
            "warnings": warnings,
        }

    def _reject(self, reasons: list, **extra) -> dict:
        out = {
            "approved": False,
            "edge_proven": False,
            "exploration": False,
            "reasons": reasons,
            "warnings": [],
            "edge_data": {},
            "safety_margin_applied": self.safety_margin,
            "break_even_wr": None,
            "required_wr": None,
            "current_wr": None,
            "win_rate_lower": None,
            "expectancy": None,
            "expectancy_lower": None,
            "profit_factor": None,
            "n": 0,
            "setup_state": SetupState.EXPLORACION.value,
            "mode": config.mode.value,
        }
        # Normalizar enums y datetimes ANTES de volcarlos. Los llamadores pasan
        # `setup_state=<enum>` (correcto en Python, inutil en JSON) y `update`
        # pisaba el `.value` que el dict base ya traia bien. El resultado era un
        # TypeError dentro de `repository.save_decision` que subia hasta
        # `engine.step()` y tumbaba el motor. El contrato de este dict es
        # "serializable", y se cumple aqui, en la frontera.
        for key, value in (extra or {}).items():
            if hasattr(value, "value") and not isinstance(value, (str, int, float)):
                value = value.value
            out[key] = value
        if "edge_data" in extra and extra["edge_data"]:
            out["edge_data"] = extra["edge_data"]
        return out
