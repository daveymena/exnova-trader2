# -*- coding: utf-8 -*-
"""Forense de perdidas: POR QUE se perdio, no solo que se perdio.

EL HUECO QUE LLENA
------------------
`SetupEvaluator` responde "este setup gana o pierde" con rigor estadistico. Pero
un 45% de acierto no dice que arreglar. Dos setups con el mismo win rate pueden
estar fallando por razones opuestas:

  * uno entra en la direccion correcta y la expiracion le corta antes de tiempo;
  * otro entra en direccion equivocada desde el primer segundo.

El primero se arregla alargando la expiracion. El segundo se arregla endureciendo
el filtro de tendencia -- y alargarle la expiracion lo empeoraria. Tratarlos igual
porque comparten win rate es la receta para "mejorar" un sistema en la direccion
equivocada.

MAE/MFE: LA HERRAMIENTA QUE LO DISTINGUE
----------------------------------------
MAE (Maximun Adverse Excursion) y MFE (Maximum Favorable Excursion) es el analisis
de excursion estandar en trading. Para cada operacion se mide cuanto se movio el
precio A FAVOR y EN CONTRA durante la ventana, no solo donde termino.

Con eso, una perdida se clasifica de forma determinista:

  MFE ~ 0 y MAE grande      -> la direccion era equivocada
  MFE grande y perdio       -> la direccion era correcta; fallo la expiracion o
                               hubo reversion
  Y la prueba definitiva: se mira el recorrido DESPUES de la expiracion. Si el
  precio habria terminado a favor con mas tiempo, fue un problema de EXPIRACION,
  no de direccion.

Esa ultima parte es diagnostico POST-HOC y esta claramente separado: `post_expiry`
solo se usa para explicar una operacion ya cerrada. Usarlo al decidir la entrada
seria look-ahead, que es el bug del que venimos (punto 10 de la auditoria). Las
condiciones que si se consultan antes de entrar viven en
`app/research/failure_memory.py` y son exclusivamente observables en el instante
de entrada.

NORMALIZACION EN ATR
--------------------
Las excursiones se expresan en unidades de ATR, no en pips ni en porcentaje. Un
movimiento de 15 pips es ruido en un activo volatil y una tendencia en otro; sin
normalizar, los modos de fallo se mezclarían entre activos y regimenes de
volatilidad y el diagnostico no seria comparable.

HONESTIDAD SOBRE LA MUESTRA
---------------------------
Un modo de fallo observado 3 veces no es un patron. `ForensicDigest` reporta el
n junto a cada modo y marca cuales tienen muestra suficiente, igual que hace
`scripts/forensics.py` con los win rates por grupo. La taxonomia sirve para
orientar; lo que autoriza un cambio de parametros es el gate estadistico de
`app/services/improvement_engine.py`.
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Sequence

from app.data.schemas import (
    Candle, DataSource, Direction, ExecutionState, Timeframe, TradeResult,
)
from app.strategies.base import atr, closes, is_stale

logger = logging.getLogger(__name__)


class FailureMode(enum.Enum):
    """Taxonomia de por que se perdio una operacion.

    Los nombres importan: cada modo se mapea a una FAMILIA DE PARAMETROS
    concreta en `ImprovementEngine.propose_from_forensics`. Si la taxonomia es
    vaga, el mapeo es vago y la propuesta tambien.
    """

    #: El precio nunca fue a favor. MAE inmediata, MFE practicamente nula.
    #: -> endurecer filtro de direccion/tendencia, no tocar la expiracion.
    DIRECCION_EQUIVOCADA = "direccion_equivocada"

    #: Iba a favor y habria ganado con mas tiempo: el recorrido favorable
    #: despues de la expiracion supera al de dentro.
    #: -> alargar expiracion. Es el unico modo que justifica alargarla.
    EXPIRACION_CORTA = "expiracion_corta"

    #: Iba a favor y se dio la vuelta antes de la expiracion.
    #: -> acortar expiracion o endurecer el timing de entrada.
    REVERSION = "reversion"

    #: El movimiento favorable ocurrio demasiado pronto y se agoto: entro tarde
    #: respecto al impulso que detecto.
    #: -> ajustar el timing de entrada, no la expiracion.
    ENTRADA_TARDIA = "entrada_tardia"

    #: Ventana sin recorrido en ninguna direccion: puro ruido lateral.
    #: -> exigir mas volatilidad direccional (ADX), no mas expiracion.
    SIN_MOVIMIENTO = "sin_movimiento"

    #: La volatilidad de la ventana era extrema: el resultado quedo dominado por
    #: ruido, no por la senal.
    #: -> bajar el techo de percentil de ATR admitido.
    VOLATILIDAD_EXTREMA = "volatilidad_extrema"

    #: No hay informacion suficiente para clasificar (precio faltante, vela
    #: stale, operacion sin entry_price). NO se inventa un diagnostico.
    INSUFICIENTE = "insuficiente"

    #: Reembolso, empate o estado UNKNOWN. No es un fallo de la estrategia:
    #: contarlo como tal sesgaria el diagnostico.
    NO_ES_FALLO = "no_es_fallo"


@dataclass
class Excursions:
    """Recorrido del precio durante la ventana de la operacion, en ATR."""

    atr: Optional[float] = None
    #: Maximo recorrido a favor dentro de la ventana (unidades de ATR).
    mfe_atr: Optional[float] = None
    #: Maximo recorrido en contra dentro de la ventana (unidades de ATR).
    mae_atr: Optional[float] = None
    #: En que fraccion de la ventana ocurrio el MFE (0=entrada, 1=expiracion).
    #: Distingue "se agoto pronto" de "iba camino y lo cortaron".
    mfe_time_frac: Optional[float] = None
    #: Recorrido a favor en la ventana IGUAL de larga justo DESPUES de expirar.
    #: Solo diagnostico post-hoc.
    post_expiry_mfe_atr: Optional[float] = None
    #: Recorrido en contra en esa misma ventana posterior.
    post_expiry_mae_atr: Optional[float] = None
    #: Muestras de precio usadas. Con pocas, el diagnostico no vale.
    samples: int = 0
    #: Desplazamiento final normalizado (el que decide win/loss).
    final_atr: Optional[float] = None


@dataclass
class ForensicReport:
    """Diagnostico de UNA operacion."""

    trade_id: Optional[int] = None
    asset: str = ""
    strategy: str = ""
    direction: str = ""
    setup_slug: str = ""
    expiry: int = 0
    won: Optional[bool] = None
    mode: FailureMode = FailureMode.INSUFICIENTE
    #: Etiquetas secundarias: una perdida puede ser a la vez reversion y
    #: volatilidad extrema. El modo primario es el accionable; las secundarias
    #: dan contexto.
    tags: list = field(default_factory=list)
    excursions: dict = field(default_factory=dict)
    #: Regla concreta que produjo la clasificacion. Sin esto el diagnostico no
    #: es auditable ni discutible.
    rule: str = ""
    #: Que familia de parametros abordaria este fallo.
    actionable_hint: str = ""
    confidence_in_diagnosis: str = "baja"
    analysed_at: Optional[datetime] = None
    features_at_entry: dict = field(default_factory=dict)
    is_evidence: bool = False
    data_source: str = "unknown"

    def as_dict(self) -> dict:
        return {
            "trade_id": self.trade_id, "asset": self.asset,
            "strategy": self.strategy, "direction": self.direction,
            "setup_slug": self.setup_slug, "expiry": self.expiry,
            "won": self.won, "mode": self.mode.value, "tags": list(self.tags),
            "excursions": dict(self.excursions), "rule": self.rule,
            "actionable_hint": self.actionable_hint,
            "confidence_in_diagnosis": self.confidence_in_diagnosis,
            "analysed_at": self.analysed_at.isoformat() if self.analysed_at else None,
            "is_evidence": self.is_evidence, "data_source": self.data_source,
        }


#: Umbrales de clasificacion, en unidades de ATR. Documentados porque DE ellos
#: sale el diagnostico: si se cambian, cambia lo que el sistema cree que le pasa.
#: No son arbitrarios: 0.15 ATR es movimiento por debajo del ruido de spread en
#: la mayoria de pares OTC; 0.5 ATR es un recorrido que un operador humano
#: llamaria "la operacion iba bien".
THRESHOLD_MFE_NEGLIGIBLE = 0.15
THRESHOLD_MFE_MEANINGFUL = 0.50
THRESHOLD_MAE_LARGE = 0.50
THRESHOLD_FLAT_WINDOW = 0.10
THRESHOLD_MFE_EARLY_FRAC = 0.40
THRESHOLD_HIGH_VOL_PERCENTILE = 0.90
#: Muestras de precio minimas para atreverse a diagnosticar.
MIN_SAMPLES = 3


#: Mapeo modo -> familia de parametros. Es DETERMINISTA y explicito: el
#: diagnostico no depende de que un modelo acierte a adivinar que tocar.
ACTIONABLE_HINTS = {
    FailureMode.DIRECCION_EQUIVOCADA: (
        "endurecer el filtro de direccion (min_confidence, adx_min, acuerdo "
        "multi-temporal). NO tocar la expiracion: mas tiempo en direccion "
        "equivocada es perder mas."),
    FailureMode.EXPIRACION_CORTA: (
        "alargar la expiracion declarada por la estrategia. Es el unico modo de "
        "fallo que justifica alargarla."),
    FailureMode.REVERSION: (
        "acortar la expiracion o endurecer el timing de entrada: el impulso se "
        "agota antes de la liquidacion."),
    FailureMode.ENTRADA_TARDIA: (
        "ajustar el timing de entrada (la senal llega despues del impulso). La "
        "expiracion no es el problema."),
    FailureMode.SIN_MOVIMIENTO: (
        "exigir mas volatilidad direccional: subir adx_min o bajar el techo de "
        "percentil de ATR admitido. Mas expiracion en un lateral no ayuda."),
    FailureMode.VOLATILIDAD_EXTREMA: (
        "bajar max_atr_percentile: en volatilidad extrema el resultado lo decide "
        "el ruido, no la senal."),
    FailureMode.INSUFICIENTE: (
        "sin diagnostico posible. No proponer nada: falta informacion, no sobra "
        "edge."),
    FailureMode.NO_ES_FALLO: (
        "no es un fallo de estrategia (empate/reembolso/UNKNOWN). Excluir de "
        "cualquier ajuste de parametros."),
}


class LossForensics:
    """Analiza el recorrido de una operacion y diagnostica por que perdio."""

    def __init__(self, min_samples: int = MIN_SAMPLES):
        self.min_samples = min_samples

    # ── excursiones ───────────────────────────────────────────────────────

    def excursions(self, trade: TradeResult,
                   candles_m1: Sequence[Candle]) -> Excursions:
        """Calcula MAE/MFE dentro de la ventana y despues de ella.

        Usa las velas M1 cuyo `open_time` cae dentro del intervalo, tomando su
        high y su low: son los extremos OBSERVADOS, no interpolaciones. Con una
        binaria lo que decide es el signo del precio en un instante, pero para
        diagnosticar importa el recorrido, y el recorrido real esta en los
        high/low.
        """
        ex = Excursions()
        entry_time = trade.entry_time or trade.timestamp
        expiry_time = trade.expiry_time or (
            entry_time + timedelta(seconds=trade.expiry or 0))
        if trade.entry_price is None or not candles_m1:
            return ex

        # ATR de referencia: el declarado por la estrategia al entrar si lo hay,
        # y si no, calculado sobre las velas previas. Normalizar por el ATR de
        # DESPUES de entrar contaminaria la medida con el movimiento que se
        # intenta medir.
        prior = [c for c in candles_m1 if c.open_time < entry_time]
        atr_value = None
        features = trade.features or {}
        for key in ("atr_m1", "atr", "atr_m5"):
            value = features.get(key)
            if isinstance(value, (int, float)) and value > 0:
                atr_value = float(value)
                break
        if atr_value is None and len(prior) >= 20:
            atr_value = atr(prior[-60:], 14)
        if not atr_value or atr_value <= 0:
            # Sin ATR no se puede normalizar y, sin normalizar, comparar
            # excursiones entre activos o regimenes no significa nada. Se
            # devuelve vacio en lugar de inventar una escala.
            logger.debug("forense sin ATR para %s: no se normaliza", trade.asset)
            return ex
        ex.atr = round(atr_value, 8)

        window = [c for c in candles_m1
                  if entry_time <= c.open_time <= expiry_time and not is_stale(c)]
        after = [c for c in candles_m1
                 if expiry_time < c.open_time
                 <= expiry_time + (expiry_time - entry_time)
                 and not is_stale(c)]
        ex.samples = len(window)

        signed = 1.0 if trade.direction == Direction.CALL else -1.0
        if window:
            best, worst, best_idx = 0.0, 0.0, 0
            for i, c in enumerate(window):
                fav = (signed * (c.high - trade.entry_price)) / atr_value
                adv = (signed * (trade.entry_price - c.low)) / atr_value
                if fav > best:
                    best, best_idx = fav, i
                if adv > worst:
                    worst = adv
            ex.mfe_atr = round(best, 4)
            ex.mae_atr = round(worst, 4)
            ex.mfe_time_frac = round(best_idx / max(1, len(window) - 1), 3)
            if trade.exit_price is not None:
                ex.final_atr = round(
                    (signed * (trade.exit_price - trade.entry_price)) / atr_value, 4)
        if after:
            best_a, worst_a = 0.0, 0.0
            for c in after:
                fav = (signed * (c.high - trade.entry_price)) / atr_value
                adv = (signed * (trade.entry_price - c.low)) / atr_value
                best_a = max(best_a, fav)
                worst_a = max(worst_a, adv)
            ex.post_expiry_mfe_atr = round(best_a, 4)
            ex.post_expiry_mae_atr = round(worst_a, 4)
        return ex

    # ── clasificacion ─────────────────────────────────────────────────────

    def classify(self, trade: TradeResult, ex: Excursions) -> tuple[FailureMode, list, str]:
        """Devuelve (modo primario, etiquetas secundarias, regla aplicada)."""
        tags: list[str] = []
        won = trade.execution_state == ExecutionState.WON

        # Empate, reembolso o sin resolver: no es un fallo de la estrategia.
        if trade.execution_state not in (ExecutionState.WON, ExecutionState.LOST):
            return FailureMode.NO_ES_FALLO, tags, (
                f"execution_state={trade.execution_state.value}: sin resultado "
                f"direccional que diagnosticar")

        features = trade.features or {}
        vol_pct = features.get("atr_percentile_m5") or features.get("atr_percentile")
        if isinstance(vol_pct, (int, float)) and vol_pct >= THRESHOLD_HIGH_VOL_PERCENTILE:
            tags.append(f"volatilidad_alta(percentil {vol_pct:.2f})")

        if ex.samples < self.min_samples or ex.mfe_atr is None or ex.mae_atr is None:
            return FailureMode.INSUFICIENTE, tags, (
                f"muestras={ex.samples} < {self.min_samples} o excursiones no "
                f"calculables: no se diagnostica")

        mfe, mae = ex.mfe_atr, ex.mae_atr

        # ORDEN DE LAS COMPROBACIONES, que no es arbitrario:
        #   1. ganadora            -> no es fallo
        #   2. recorrido posterior -> expiracion corta (la prueba mas fuerte)
        #   3. ventana plana       -> sin movimiento
        #   4. MFE despreciable    -> direccion equivocada
        #   5. MFE clara           -> reversion
        #
        # La comprobacion de "ventana plana" iba ANTES de la de ganadora, con lo
        # que una operacion ganada en un rango estrecho se diagnosticaba como
        # SIN_MOVIMIENTO. No es un fallo grave (no se actua sobre ganancias) pero
        # contaminaba el digest: un modo de fallo que en realidad era una
        # victoria. Cada comprobacion va despues de la que tiene mas autoridad.
        if won:
            # Una ganancia tambien se explica: sirve de contraste y para detectar
            # que se esta ganando por suerte y no por la senal.
            if mae > THRESHOLD_MAE_LARGE and mfe < THRESHOLD_MFE_MEANINGFUL:
                tags.append("gano_pese_a_mae_alta")
            return FailureMode.NO_ES_FALLO, tags, "operacion ganadora"

        # ── perdidas ──────────────────────────────────────────────────────
        #
        # EL RECORRIDO POSTERIOR VA PRIMERO, y esto es una correccion.
        #
        # La version anterior exigia MFE >= 0.50 ATR DENTRO de la ventana antes
        # de mirar el recorrido posterior. Con eso, una operacion que se movio
        # 0.45 ATR a favor y perdio por poco, pero que habria recorrido 3.05 ATR
        # a favor con mas tiempo, caia al fallback y se diagnosticaba como
        # DIRECCION_EQUIVOCADA -- cuyo hint dice literalmente "NO tocar la
        # expiracion". O sea: el diagnostico mandaba a endurecer el filtro de
        # tendencia justo en el caso en que la tendencia era correcta, y prohibia
        # el unico cambio que lo arreglaba. Un diagnostico invertido es peor que
        # no tener diagnostico, porque se actua sobre el con confianza.
        #
        # Si el precio fue claramente a favor DESPUES de expirar, la direccion
        # estaba validada por lo que ocurrio a continuacion, independientemente
        # de cuanto se hubiera movido dentro. Esa es la prueba mas fuerte
        # disponible y por eso se evalua antes que ninguna.
        post = ex.post_expiry_mfe_atr
        if post is not None and post >= THRESHOLD_MFE_MEANINGFUL and \
                post > mfe * 1.15:
            return FailureMode.EXPIRACION_CORTA, tags, (
                f"MFE {mfe:.2f} ATR dentro de la ventana y {post:.2f} ATR en la "
                f"ventana siguiente: la direccion era correcta y falto tiempo")

        flat = max(mfe, mae) < THRESHOLD_FLAT_WINDOW
        if flat:
            return FailureMode.SIN_MOVIMIENTO, tags, (
                f"max(MFE {mfe:.2f}, MAE {mae:.2f}) < {THRESHOLD_FLAT_WINDOW} ATR: "
                f"la ventana no se movio en ninguna direccion")

        if mfe < THRESHOLD_MFE_NEGLIGIBLE:
            return FailureMode.DIRECCION_EQUIVOCADA, tags, (
                f"MFE {mfe:.2f} ATR < {THRESHOLD_MFE_NEGLIGIBLE}: el precio nunca "
                f"fue a favor (MAE {mae:.2f}). La direccion era incorrecta")

        if mfe >= THRESHOLD_MFE_MEANINGFUL:
            # Iba claramente a favor, el recorrido posterior NO lo mejora, y
            # perdio: se dio la vuelta dentro de la ventana.
            if ex.mfe_time_frac is not None and ex.mfe_time_frac <= THRESHOLD_MFE_EARLY_FRAC:
                return FailureMode.REVERSION, tags, (
                    f"MFE {mfe:.2f} ATR alcanzado en la fraccion "
                    f"{ex.mfe_time_frac:.2f} de la ventana y luego se dio la "
                    f"vuelta (final {ex.final_atr} ATR)")
            return FailureMode.REVERSION, tags, (
                f"MFE {mfe:.2f} ATR y cierre en {ex.final_atr} ATR: reversion "
                f"dentro de la ventana")

        # MFE intermedia: ni despreciable ni clara. Si ocurrio muy pronto, la
        # entrada llego tarde al impulso.
        if ex.mfe_time_frac is not None and ex.mfe_time_frac <= THRESHOLD_MFE_EARLY_FRAC \
                and mae > mfe:
            return FailureMode.ENTRADA_TARDIA, tags, (
                f"MFE {mfe:.2f} ATR en la fraccion {ex.mfe_time_frac:.2f} y MAE "
                f"{mae:.2f} ATR mayor: el impulso ya habia pasado al entrar")

        mode = FailureMode.VOLATILIDAD_EXTREMA if (
            isinstance(vol_pct, (int, float))
            and vol_pct >= THRESHOLD_HIGH_VOL_PERCENTILE) else FailureMode.DIRECCION_EQUIVOCADA
        return mode, tags, (
            f"MFE {mfe:.2f} / MAE {mae:.2f} ATR sin patron claro"
            + (f"; percentil de ATR {vol_pct:.2f}" if mode is FailureMode.VOLATILIDAD_EXTREMA
               else ""))

    # ── informe completo ──────────────────────────────────────────────────

    def analyse(self, trade: TradeResult, candles_m1: Sequence[Candle],
                trade_id: Optional[int] = None) -> ForensicReport:
        """Diagnostica una operacion. Nunca lanza: un forense que rompe el
        motor seria peor que no tener forense."""
        try:
            ex = self.excursions(trade, candles_m1)
            mode, tags, rule = self.classify(trade, ex)
        except Exception as exc:                              # noqa: BLE001
            logger.warning("forense fallo en %s: %s", trade.asset, exc)
            return ForensicReport(
                trade_id=trade_id, asset=trade.asset, strategy=trade.strategy,
                mode=FailureMode.INSUFICIENTE, rule=f"error: {exc}",
                actionable_hint=ACTIONABLE_HINTS[FailureMode.INSUFICIENTE],
                analysed_at=datetime.utcnow(),
                data_source=trade.data_source.value)

        features = trade.features or {}
        return ForensicReport(
            trade_id=trade_id,
            asset=trade.asset,
            strategy=trade.strategy,
            direction=trade.direction.value,
            setup_slug=str(features.get("setup_slug") or ""),
            expiry=int(trade.expiry or 0),
            won=(trade.execution_state == ExecutionState.WON),
            mode=mode,
            tags=tags,
            excursions={
                "atr": ex.atr, "mfe_atr": ex.mfe_atr, "mae_atr": ex.mae_atr,
                "mfe_time_frac": ex.mfe_time_frac,
                "post_expiry_mfe_atr": ex.post_expiry_mfe_atr,
                "post_expiry_mae_atr": ex.post_expiry_mae_atr,
                "final_atr": ex.final_atr, "samples": ex.samples,
            },
            rule=rule,
            actionable_hint=ACTIONABLE_HINTS.get(mode, ""),
            # La confianza del diagnostico depende de cuantas muestras de precio
            # hubo, no de cuan bonita sea la explicacion.
            confidence_in_diagnosis=(
                "alta" if ex.samples >= 10 else
                "media" if ex.samples >= self.min_samples else "baja"),
            analysed_at=datetime.utcnow(),
            features_at_entry={k: v for k, v in features.items()
                               if isinstance(v, (int, float, str, bool))},
            is_evidence=trade.is_evidence,
            data_source=trade.data_source.value,
        )

    # ── digest agregado ───────────────────────────────────────────────────

    @staticmethod
    def digest(reports: Sequence[ForensicReport],
               min_n_for_pattern: int = 10) -> dict:
        """Agrega diagnosticos. Marca explicitamente cuales tienen muestra.

        Es lo que se le pasa al supervisor de IA: no una lista cruda de
        perdidas, sino donde esta el fallo recurrente y con cuanta evidencia.
        Un patron visto 2 veces se reporta como anécdota, no como conclusion.
        """
        losses = [r for r in reports if r.won is False
                  and r.mode not in (FailureMode.NO_ES_FALLO,)]
        by_mode: dict[str, dict] = {}
        by_setup_mode: dict[str, dict] = {}
        for r in losses:
            slot = by_mode.setdefault(r.mode.value, {"n": 0, "solido": False,
                                                     "hint": r.actionable_hint,
                                                     "ejemplo": r.rule})
            slot["n"] += 1
            key = f"{r.setup_slug or r.strategy}|{r.mode.value}"
            s2 = by_setup_mode.setdefault(key, {"n": 0, "setup": r.setup_slug or r.strategy,
                                                "mode": r.mode.value,
                                                "hint": r.actionable_hint})
            s2["n"] += 1
        for slot in by_mode.values():
            slot["solido"] = slot["n"] >= min_n_for_pattern
        for slot in by_setup_mode.values():
            slot["solido"] = slot["n"] >= min_n_for_pattern

        total = len(losses)
        return {
            "perdidas_analizadas": total,
            "sin_diagnostico": sum(1 for r in losses
                                   if r.mode == FailureMode.INSUFICIENTE),
            "por_modo": dict(sorted(by_mode.items(), key=lambda kv: -kv[1]["n"])),
            "por_setup_y_modo": dict(sorted(by_setup_mode.items(),
                                            key=lambda kv: -kv[1]["n"])),
            "modos_solidos": [k for k, v in by_mode.items() if v["solido"]],
            "modos_anecdoticos": [k for k, v in by_mode.items() if not v["solido"]],
            "min_n_para_patron": min_n_for_pattern,
            "nota": (
                "Un modo con muestra por debajo del minimo es una anecdota, no "
                "un patron. No proponer cambios basados en los modos anecdoticos: "
                "es exactamente como el bot anterior acabo ascendiendo reglas "
                "ajustadas con n=1, 6, 7 y 9."
            ),
        }
