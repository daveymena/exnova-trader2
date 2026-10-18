# -*- coding: utf-8 -*-
"""MOTOR DE MEJORA CONTINUA, supervisado por IA y frenado por estadistica.

QUE HACE
--------
Ciclo completo: DIAGNOSTICAR -> PROPONER -> VALIDAR -> FILTRAR -> APLICAR ->
REVISAR. Cada vuelta parte de la evidencia acumulada y termina o con un cambio
de parametros versionado y medido, o con una lista de propuestas rechazadas y el
motivo. Un motor de mejora que solo sabe aplicar no es un motor de mejora.

POR QUE EL LLM NO DECIDE SOLO
-----------------------------
El usuario eligio supervision LLM-driven, y asi es: el LLM diagnostica, propone
y explica. Pero NO aplica. Entre su propuesta y el disco hay un freno
determinista que no depende de ningun modelo:

  1. SANDBOX. Cada estrategia declara `param_space`. Nada fuera de ese rango se
     acepta; lo que se sale se recorta y se registra. Un LLM que proponga
     `min_confidence=0.0` consigue `0.30` y una linea en el log diciendo que se
     le recorto.

  2. WALK-FORWARD. La propuesta se valida ajustando en train y juzgando en test.
     Lo que se mira es el resultado OUT-OF-SAMPLE.

  3. CORRECCION POR TESTEO MULTIPLE (Benjamini-Hochberg). Es el punto que casi
     nadie implementa y el que separa un motor de mejora de una maquina de
     autoenganarse. Si se prueban 20 variantes de parametros y se conserva la
     mejor, esa "mejor" es casi seguro la que tuvo mas suerte: con 20 pruebas al
     5% hay ~64% de probabilidad de al menos un falso positivo. BH ajusta los
     p-valores por el numero de hipotesis probadas a la vez. Sin esto, el motor
     "mejoraria" indefinidamente sobre ruido.

  4. TOPE DE CAMBIOS. Maximo N aplicaciones por periodo. Un motor que puede
     cambiar 50 cosas al dia no esta mejorando: esta haciendo random search con
     presupuesto ilimitado.

  5. REVISION Y ROLLBACK. Tras aplicar, se mide el rendimiento real. Si degrada,
     se revierte y se registra. `ParamStore` guarda historial y `previous`
     precisamente para que deshacer sea una operacion, no una reconstruccion.

ESTO NO ES DESCONFIANZA DEL MODELO, ES EL DISENO. La auditoria interna del repo
(`app/NOT_PRODUCTION_READY.md`, punto 9) documenta que `trading_apply_change`
del servidor MCP aplicaba cambios sin freno estadistico, con un filtro de texto
evadible. Y `bot/core/self_evaluator.py` -- el estandar que se porto a
`app/research/setup_evaluator.py` -- existe porque el bot anterior ascendio
reglas ajustadas con n=1, 6, 7 y 9 observaciones: a payout 0.86 el break-even es
53.76%, asi que 6/9 (66.7%) PARECE edge y es ruido (IC 95%: 35%-88%). Ese
mecanismo hundio las ~500 operaciones anteriores. Un LLM sin freno reproduce ese
mecanismo con mejor prosa.

SIN LLM TAMBIEN FUNCIONA
------------------------
Si `openai` no esta instalado o no hay proveedor disponible, el motor degrada a
busqueda local determinista sobre `param_space`. Sigue diagnosticando, validando
y filtrando igual. El LLM anade hipotesis y explicaciones; no es un punto unico
de fallo.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Optional, Sequence

from app.data.repository import repository as default_repository
from app.data.schemas import (
    BacktestRun, DataSource, ImprovementProposal, SetupState,
)

# Estados de una propuesta. El esquema los guarda como texto plano
# (`ImprovementProposal.status`), no como enum: se mantienen aqui como
# constantes para no escribir "aplied" en un sitio y compararlo contra "applied"
# en otro.
STATUS_PROPOSED = "proposed"
STATUS_VALIDATED = "validated"
STATUS_APPLIED = "applied"
STATUS_REJECTED = "rejected"
STATUS_ROLLED_BACK = "rolled_back"
from app.research.backtester import Backtester, BacktestReport
from app.stats.core import (
    benjamini_hochberg, binomial_pvalue_upper, breakeven_winrate,
)
from app.strategies.registry import ParamStore, StrategyRegistry, validate_params

logger = logging.getLogger(__name__)


@dataclass
class ImprovementConfig:
    """Limites del motor. Todos son conservadores a proposito."""

    #: Maximo de cambios aplicados por periodo (ver `change_window_hours`).
    max_changes_per_window: int = 3
    change_window_hours: int = 24

    #: Minimo de observaciones out-of-sample para que una propuesta cuente.
    #: Por debajo de esto, cualquier "mejora" es indistinguible del ruido.
    min_oos_observations: int = 60

    #: Degradacion maxima train->test tolerada en expectancy. Mas alla de esto
    #: la propuesta es overfit aunque el in-sample sea bonito.
    max_degradation: float = 0.05

    #: FDR para Benjamini-Hochberg.
    fdr: float = 0.10

    #: Exceso minimo sobre el break-even que debe acreditar el out-of-sample.
    min_oos_margin_over_breakeven: float = 0.0

    #: Pliegues del walk-forward de validacion.
    folds: int = 3
    train_ratio: float = 0.6

    #: Margen de seguridad al comparar contra la linea base.
    require_beats_baseline: bool = True

    @classmethod
    def from_app_config(cls) -> "ImprovementConfig":
        from app.config import config
        return cls(
            fdr=getattr(config, "backtest_alpha", 0.05),
            min_oos_observations=max(
                60, int(getattr(config, "backtest_min_sample_size", 100)) // 2),
        )


@dataclass
class ValidationReport:
    """Resultado de validar UNA propuesta.

    `basis` declara SOBRE QUE se midio: "shadow:estrategia", "shadow:portfolio"
    o "traded". Un win rate sin su base de medicion no significa nada, y
    recuperar la base olfateando el texto de `reason` seria fragil.
    """
    proposal_id: str
    accepted: bool
    reason: str
    basis: str = ""
    p_value: Optional[float] = None
    q_value: Optional[float] = None
    baseline: dict = field(default_factory=dict)
    candidate: dict = field(default_factory=dict)
    degradation: dict = field(default_factory=dict)
    walk_forward: dict = field(default_factory=dict)
    validated_at: Optional[datetime] = None

    def as_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id, "accepted": self.accepted,
            "reason": self.reason, "basis": self.basis,
            "p_value": self.p_value,
            "q_value": self.q_value, "baseline": self.baseline,
            "candidate": self.candidate, "degradation": self.degradation,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
        }


class ImprovementEngine:
    """Diagnostica, propone, valida, filtra, aplica y revisa."""

    def __init__(self, registry: Optional[StrategyRegistry] = None,
                 repository=None,
                 ai=None,
                 config: Optional[ImprovementConfig] = None,
                 backtester_factory: Optional[Callable[[], Backtester]] = None,
                 feed_factory: Optional[Callable[[], object]] = None):
        """
        `feed_factory` devuelve un feed NUEVO en cada llamada. Es imprescindible
        que sea una fabrica y no una instancia: el walk-forward recorre varias
        ventanas y un feed ya consumido no se puede rebobinar (su reloj virtual
        no retrocede por diseño).
        """
        self.registry = registry or StrategyRegistry()
        self.repo = repository or default_repository
        self.cfg = config or ImprovementConfig.from_app_config()
        self.ai = ai
        self.backtester_factory = backtester_factory or (lambda: Backtester())
        self.feed_factory = feed_factory
        self.store = self.registry.store

    # =======================================================================
    # 1. DIAGNOSTICO
    # =======================================================================

    def diagnose(self, limit: int = 40) -> dict:
        """Foto de donde esta el problema, a partir de evidencia acumulada.

        No adivina ni prioriza por intuicion: lista los setups con muestra
        suficiente y dice cual esta por debajo de la linea. Un diagnostico sin
        numeros no es un diagnostico, es una opinion.
        """
        rows = []
        try:
            rows = self.repo.list_setups(limit=limit)
        except Exception as exc:                              # noqa: BLE001
            logger.warning("no se pudieron listar setups: %s", exc)

        problems, healthy, exploring = [], [], []
        for r in rows:
            entry = {
                "slug": r.slug, "asset": r.asset, "strategy": r.strategy,
                "direction": r.direction, "regime": r.market_regime,
                "expiry": r.expiry, "n": r.n, "n_traded": r.n_traded,
                "wins": r.wins, "win_rate": r.win_rate,
                "win_rate_lower": r.win_rate_lower,
                "break_even": r.break_even, "expectancy": r.expectancy,
                "expectancy_lower": r.expectancy_lower,
                "state": r.state.value, "verdict": r.verdict.value,
                "looks": r.looks, "reopened": r.reopened,
            }
            if r.n < self.cfg.min_oos_observations:
                exploring.append(entry)
            elif r.state == SetupState.RETIRADO or (r.verdict.value == "perdedor"):
                problems.append(entry)
            elif r.expectancy_lower is not None and r.expectancy_lower > 0:
                healthy.append(entry)
            else:
                problems.append(entry)

        # Parametros vigentes: el LLM necesita saber desde donde se parte.
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "param_store_version": self.store.version,
            "strategies": self.registry.describe(),
            "counts": {
                "setups": len(rows),
                "con_muestra": len(problems) + len(healthy),
                "problematicos": len(problems),
                "sanos": len(healthy),
                "explorando": len(exploring),
            },
            "problematicos": sorted(problems, key=lambda e: -(e["n"] or 0))[:20],
            "sanos": sorted(healthy, key=lambda e: -(e["expectancy_lower"] or 0))[:20],
            "explorando": exploring[:20],
        }

    # =======================================================================
    # 2. PROPUESTAS
    # =======================================================================

    def propose(self, diagnosis: Optional[dict] = None,
                max_proposals: int = 8) -> list[ImprovementProposal]:
        """Genera propuestas. Intenta con el LLM; degrada a busqueda local.

        El orden importa: se prueba el LLM primero porque puede proponer
        hipotesis que una busqueda local no explora (combinaciones de filtros,
        no solo mover un numero). Pero si falla, el ciclo sigue: un motor de
        mejora que se para porque no hay proveedor de IA no es un motor.
        """
        diagnosis = diagnosis or self.diagnose()
        proposals = self._propose_llm(diagnosis, max_proposals)
        if not proposals:
            logger.info("sin propuestas del LLM; se usa busqueda local determinista")
            proposals = self._propose_local(diagnosis, max_proposals)
        return proposals[:max_proposals]

    def _propose_llm(self, diagnosis: dict, max_proposals: int) -> list[ImprovementProposal]:
        if self.ai is None:
            return []
        prompt = self._build_prompt(diagnosis, max_proposals)
        try:
            raw = self.ai.chat([
                {"role": "system", "content": (
                    "Eres el supervisor estadistico de un sistema de trading de "
                    "opciones binarias en modo DEMO. Tu trabajo es proponer "
                    "AJUSTES DE PARAMETROS pequenos y justificables, nunca "
                    "reescrituras. Responde SOLO con JSON valido, sin texto "
                    "alrededor."
                )},
                {"role": "user", "content": prompt},
            ], max_tokens=1800, temperature=0.2)
        except Exception as exc:                              # noqa: BLE001
            logger.warning("el proveedor de IA fallo al proponer: %s", exc)
            return []
        if not raw:
            return []
        return self._parse_proposals(raw, origin="llm")

    def _build_prompt(self, diagnosis: dict, max_proposals: int) -> str:
        """Prompt con el sandbox EXPLICITO.

        Se le dice al modelo que rangos existen y que cualquier cosa fuera se
        recorta. Ocultarle el sandbox solo produce propuestas que se descartan.
        """
        sandbox = {
            name: {
                "param_space": spec.param_space,
                "vigentes": self.registry.params(name),
                "legado_no_ajustable": spec.is_legacy,
            }
            for name, spec in self.registry.specs.items()
        }
        return json.dumps({
            "instruccion": (
                "Diagnostica y propone como maximo "
                f"{max_proposals} ajustes de parametros. Cada propuesta debe "
                "citar la evidencia concreta (setup, n, win_rate, "
                "expectancy_lower) que la motiva. No propongas nada que no "
                "este respaldado por esos numeros."
            ),
            "reglas": [
                "Los parametros deben estar dentro de param_space; lo que se salga se recorta.",
                "Las estrategias marcadas como legado_no_ajustable no aceptan cambios.",
                "No propongas bajar min_confidence por debajo de su minimo: es el filtro de calidad.",
                "Un setup con n pequeno NO es evidencia. No lo uses para justificar nada.",
                "Propon cambios pequenos y aislados: un cambio a la vez es medible, cinco a la vez no.",
            ],
            "formato_salida": {
                "proposals": [{
                    "strategy": "nombre exacto de la lista",
                    "params": {"clave": "valor numerico"},
                    "hypothesis": "que se espera mejorar y por que",
                    "evidence": ["slug o metrica concreta que la respalda"],
                }],
            },
            "diagnostico": diagnosis,
            "sandbox": sandbox,
        }, ensure_ascii=False, default=str)

    def _parse_proposals(self, raw: str, origin: str) -> list[ImprovementProposal]:
        """Extrae JSON de la respuesta del modelo, tolerando prosa alrededor.

        Los modelos envuelven el JSON en ```json ... ``` o añaden explicaciones.
        Rechazar todo por eso dejaria el motor sin propuestas de forma
        intermitente y nadie sabria por que.
        """
        bloques = re.findall(r"\{.*\}", raw, flags=re.DOTALL)
        for bloque in bloques:
            try:
                data = json.loads(bloque)
            except json.JSONDecodeError:
                continue
            items = data.get("proposals") if isinstance(data, dict) else None
            if not isinstance(items, list):
                continue
            out = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                strategy = str(item.get("strategy", "")).strip()
                params = item.get("params") or {}
                if strategy not in self.registry.specs or not isinstance(params, dict):
                    logger.info("propuesta descartada: estrategia o params invalidos (%r)",
                                strategy)
                    continue
                evidence = item.get("evidence")
                out.append(ImprovementProposal(
                    id=str(uuid.uuid4()),
                    created_at=datetime.utcnow(),
                    origin=origin,
                    action="tune_param",
                    target=f"strategy:{strategy}",
                    payload=dict(params),
                    rationale=str(item.get("hypothesis", "")),
                    # El esquema declara `evidence` como DICT, no como lista: se
                    # normaliza para que guarde algo coherente con la columna.
                    evidence={"cited": list(evidence)} if isinstance(evidence, list)
                    else (dict(evidence) if isinstance(evidence, dict) else {}),
                    status=STATUS_PROPOSED,
                ))
            return out
        logger.warning("no se pudo extraer JSON de la respuesta del modelo")
        return []

    def _propose_local(self, diagnosis: dict, max_proposals: int) -> list[ImprovementProposal]:
        """Busqueda local determinista: vecinos dentro del sandbox.

        No es elegante, pero es reproducible y no depende de ningun proveedor.
        Para cada estrategia ajustable propone endurecer y relajar ligeramente el
        filtro de calidad, que es el parametro con mas efecto sobre la precision.
        """
        out: list[ImprovementProposal] = []
        problematicos = diagnosis.get("problematicos") or []
        for name, spec in self.registry.specs.items():
            if spec.is_legacy or not spec.param_space:
                continue
            current = self.registry.params(name)
            if "min_confidence" not in spec.param_space:
                continue
            lo, hi = spec.param_space["min_confidence"]
            base = float(current.get("min_confidence", (lo + hi) / 2))
            for delta, etiqueta in ((+0.05, "endurecer"), (-0.05, "relajar")):
                value = min(hi, max(lo, round(base + delta, 4)))
                if abs(value - base) < 1e-9:
                    continue
                out.append(ImprovementProposal(
                    id=str(uuid.uuid4()), created_at=datetime.utcnow(),
                    origin="local_search", action="tune_param",
                    target=f"strategy:{name}",
                    payload={"min_confidence": value},
                    rationale=(f"busqueda local: {etiqueta} min_confidence de "
                               f"{base} a {value} (sandbox [{lo}, {hi}])"),
                    evidence={"problematicos": [p["slug"] for p in problematicos[:3]]},
                    status=STATUS_PROPOSED,
                ))
            if len(out) >= max_proposals:
                break
        return out[:max_proposals]

    # =======================================================================
    # 3. VALIDACION
    # =======================================================================

    @staticmethod
    def _strategy_of(proposal: ImprovementProposal) -> str:
        """`target` viene como "strategy:<nombre>"; aqui se usa el nombre solo.

        El prefijo existe porque `ImprovementProposal.target` puede apuntar a
        otras cosas ("risk", "expiry"). Este motor solo ajusta estrategias, y lo
        comprueba en lugar de asumirlo.
        """
        target = proposal.target or ""
        return target.split(":", 1)[1] if ":" in target else target

    def validate(self, proposal: ImprovementProposal,
                 baseline: Optional[dict] = None) -> ValidationReport:
        """Valida UNA propuesta con walk-forward sobre datos reales."""
        now = datetime.utcnow()
        if self.feed_factory is None:
            return ValidationReport(
                proposal_id=proposal.id, accepted=False, validated_at=now,
                reason=("sin feed de validacion configurado: no se puede medir la "
                        "propuesta. Una propuesta no validada NO se aplica, "
                        "aunque el razonamiento suene bien."),
            )

        strategy = self._strategy_of(proposal)
        if not (proposal.target or "").startswith("strategy:"):
            return ValidationReport(
                proposal_id=proposal.id, accepted=False, validated_at=now,
                reason=(f"este motor solo ajusta estrategias; el target es "
                        f"{proposal.target!r}. Los cambios sobre riesgo o "
                        f"expiracion necesitan su propio gate, no este."))
        spec = self.registry.specs.get(strategy)
        if spec is None:
            return ValidationReport(proposal_id=proposal.id, accepted=False,
                                    validated_at=now,
                                    reason=f"estrategia desconocida: {strategy}")
        if spec.is_legacy:
            return ValidationReport(
                proposal_id=proposal.id, accepted=False, validated_at=now,
                reason=(f"{strategy} es una estrategia heredada sin "
                        f"param_space declarado: no hay sandbox donde validar "
                        f"un cambio, asi que no se acepta."))

        accepted, rejected = validate_params(strategy, proposal.payload,
                                             spec.param_space)
        if not accepted:
            return ValidationReport(
                proposal_id=proposal.id, accepted=False, validated_at=now,
                reason=f"todos los parametros fuera del sandbox: {rejected}")
        if rejected:
            logger.warning("propuesta %s recortada: %s", proposal.id, rejected)

        baseline = baseline or self._measure(None)
        candidate = self._measure({strategy: accepted})
        if not candidate or candidate.get("error"):
            return ValidationReport(
                proposal_id=proposal.id, accepted=False, validated_at=now,
                reason=f"la validacion fallo: {candidate.get('error') if candidate else 'sin datos'}",
                baseline=baseline or {})

        oos = candidate.get("out_of_sample") or {}
        # BASE DE MEDICION. Un cambio de parametros afecta a la GENERACION de
        # senales, y las sombras miden exactamente eso: cada senal generada se
        # resuelve contra el precio real observado, se opere o no. Son cientos
        # de observaciones por ventana frente a las decenas de trades operados
        # (limitados por riesgo, cooldowns y tope de operaciones/hora).
        #
        # Se usa la base con muestra suficiente, y se DECLARA cual se uso: un
        # numero sin su base de medicion no significa nada.
        n_shadow = int(oos.get("shadow_resolved") or 0)
        n_traded = int(oos.get("resolved") or 0)
        # PRIMERO LA ESTRATEGIA OBJETIVO. Comparar el agregado del portfolio no
        # sirve: cambiar un parametro de UNA estrategia mueve 3 senales de cada
        # 700, y el agregado sale identico con y sin el cambio. Eso hacia que
        # toda propuesta se rechazara con "no supera a la linea base" mostrando
        # el mismo numero a ambos lados -- un rechazo que parece rigor y en
        # realidad es incapacidad de medir.
        target = (oos.get("shadow_by_strategy") or {}).get(strategy) or {}
        n_target = int(target.get("n") or 0)
        if n_target >= self.cfg.min_oos_observations:
            basis = "shadow:estrategia"
            n_oos = n_target
            wr = target.get("win_rate") or 0.0
            wr_lo = target.get("win_rate_lower")
            be = target.get("break_even") or breakeven_winrate(0.85)
            exp = target.get("expectancy")
            exp_lo = target.get("expectancy_lower")
            wins = int(target.get("wins") or 0)
        elif n_shadow >= self.cfg.min_oos_observations:
            # Sin muestra propia se cae al portfolio, y se DECLARA. Es una
            # medicion mas debil: dice algo del sistema, poco del cambio.
            basis = "shadow:portfolio"
            n_oos = n_shadow
            wr = oos.get("shadow_win_rate") or 0.0
            wr_lo = oos.get("shadow_win_rate_lower")
            be = oos.get("shadow_break_even") or breakeven_winrate(0.85)
            exp = oos.get("shadow_expectancy")
            exp_lo = oos.get("shadow_expectancy_lower")
            wins = int(oos.get("shadow_wins") or 0)
        elif n_traded >= self.cfg.min_oos_observations:
            basis = "traded"
            n_oos = n_traded
            wr = oos.get("win_rate") or 0.0
            wr_lo = oos.get("win_rate_lower")
            be = oos.get("break_even") or breakeven_winrate(0.85)
            exp = oos.get("expectancy")
            exp_lo = oos.get("expectancy_lower")
            wins = int(oos.get("wins") or 0)
        else:
            return ValidationReport(
                proposal_id=proposal.id, accepted=False, validated_at=now,
                reason=(f"muestra out-of-sample insuficiente: {n_shadow} sombras "
                        f"y {n_traded} trades operados, minimo "
                        f"{self.cfg.min_oos_observations}. Con tan pocas "
                        f"observaciones no se distingue una mejora de la suerte."),
                baseline=baseline, candidate=candidate)
        margin = wr - be
        if margin <= self.cfg.min_oos_margin_over_breakeven:
            return ValidationReport(
                proposal_id=proposal.id, accepted=False, validated_at=now,
                reason=(f"out-of-sample por debajo del break-even: WR {wr:.2%} "
                        f"vs {be:.2%} (margen {margin:+.2%}). No hay edge que "
                        f"afinar."),
                baseline=baseline, candidate=candidate,
                degradation=candidate.get("degradation") or {})

        logger.info("propuesta %s validada sobre base=%s (n=%d)",
                    proposal.id[:8], basis, n_oos)
        # La degradacion se toma de la MISMA base y del MISMO alcance que el win
        # rate. Comparar un win rate de la estrategia contra una degradacion del
        # portfolio -- o contra la de trades operados -- es mezclar unidades, y
        # con 1 o 2 operaciones ese numero es ruido puro: el filtro de overfit se
        # disparaba siempre y bloqueaba cualquier mejora.
        degradation = self._degradation_for(candidate, basis, strategy)
        if degradation is not None and degradation < -self.cfg.max_degradation:
            return ValidationReport(
                proposal_id=proposal.id, accepted=False, validated_at=now,
                reason=(f"overfit sobre {basis}: la expectancy cae "
                        f"{degradation:+.4f} al salir de muestra (maximo "
                        f"tolerado {-self.cfg.max_degradation:+.4f})."),
                baseline=baseline, candidate=candidate,
                degradation=candidate.get("degradation") or {})

        if self.cfg.require_beats_baseline and baseline:
            b_wr, b_exp = self._baseline_metric(baseline, basis, strategy)
            c_exp = exp or 0.0
            if c_exp <= b_exp and wr <= b_wr:
                return ValidationReport(
                    proposal_id=proposal.id, accepted=False, validated_at=now,
                    reason=(f"no supera a la linea base (base={basis}): "
                            f"expectancy {c_exp:+.4f} vs {b_exp:+.4f}, "
                            f"WR {wr:.2%} vs {b_wr:.2%}. Una propuesta que no "
                            f"mejora nada medible no se aplica, por muy "
                            f"razonable que suene su justificacion."),
                    baseline=baseline, candidate=candidate,
                    degradation=candidate.get("degradation") or {})

        # p-valor unilateral: P(observar >= wins | p = break-even). Es la
        # pregunta correcta -- "esto supera el azar?" -- y no "esto es bonito?".
        p_value = binomial_pvalue_upper(wins, n_oos, be)

        return ValidationReport(
            proposal_id=proposal.id, accepted=True, validated_at=now,
            basis=basis, p_value=p_value,
            reason=(f"out-of-sample sobre {basis} n={n_oos} WR={wr:.2%} "
                    f"(break-even {be:.2%}, cota inferior "
                    f"{(wr_lo if wr_lo is not None else float('nan')):.2%}), "
                    f"expectancy {exp}, degradacion "
                    f"{degradation if degradation is None else round(degradation, 4)}"),
            baseline=baseline, candidate=candidate,
            degradation=candidate.get("degradation") or {},
            walk_forward=candidate.get("folds") or {})

    @staticmethod
    def _bucket_for(measurement: dict, basis: str, strategy: str) -> dict:
        """Devuelve el bucket que corresponde a `basis`, sin mezclar alcances."""
        oos = (measurement or {}).get("out_of_sample") or {}
        if basis == "shadow:estrategia":
            return (oos.get("shadow_by_strategy") or {}).get(strategy) or {}
        if basis == "shadow:portfolio":
            return {
                "win_rate": oos.get("shadow_win_rate"),
                "win_rate_lower": oos.get("shadow_win_rate_lower"),
                "break_even": oos.get("shadow_break_even"),
                "expectancy": oos.get("shadow_expectancy"),
                "expectancy_lower": oos.get("shadow_expectancy_lower"),
                "n": oos.get("shadow_resolved"),
            }
        return {
            "win_rate": oos.get("win_rate"),
            "win_rate_lower": oos.get("win_rate_lower"),
            "break_even": oos.get("break_even"),
            "expectancy": oos.get("expectancy"),
            "expectancy_lower": oos.get("expectancy_lower"),
            "n": oos.get("resolved"),
        }

    def _baseline_metric(self, baseline: dict, basis: str,
                         strategy: str) -> tuple[float, float]:
        """(win_rate, expectancy) de la linea base sobre la MISMA base."""
        b = self._bucket_for(baseline, basis, strategy)
        return (b.get("win_rate") or 0.0), (b.get("expectancy") or 0.0)

    @staticmethod
    def _degradation_for(candidate: dict, basis: str,
                         strategy: str) -> Optional[float]:
        """Degradacion train->test en la base que se esta usando.

        Para "shadow:estrategia" se calcula pliegue a pliegue sobre ESA
        estrategia; para las demas se usa el agregado del walk-forward. Medir la
        degradacion en otro alcance que el de la decision es mezclar unidades:
        con 1 o 2 trades operados el numero es ruido y el filtro de overfit se
        dispararia siempre.
        """
        degradation = (candidate or {}).get("degradation") or {}
        if basis != "shadow:estrategia":
            key = {"shadow:portfolio": "shadow_expectancy",
                   "traded": "expectancy"}.get(basis, "expectancy")
            return degradation.get(key)
        # Muestra minima POR PLIEGUE para que la degradacion signifique algo.
        # Calcularla con 1 observacion in-sample contra 1 out-of-sample da un
        # numero enorme y puramente aleatorio, y el filtro de overfit rechaza la
        # propuesta con una justificacion que parece rigor. "No se puede medir la
        # degradacion" NO es "hay overfit": se devuelve None y el filtro se omite
        # (los demas siguen activos).
        min_fold = 10
        values = []
        for fold in (candidate or {}).get("folds_detail") or []:
            ins = ((fold.get("in_sample") or {}).get("shadow_by_strategy")
                   or {}).get(strategy) or {}
            oos = ((fold.get("out_of_sample") or {}).get("shadow_by_strategy")
                   or {}).get(strategy) or {}
            if int(ins.get("n") or 0) < min_fold or int(oos.get("n") or 0) < min_fold:
                continue
            if ins.get("expectancy") is None or oos.get("expectancy") is None:
                continue
            values.append(oos["expectancy"] - ins["expectancy"])
        return (sum(values) / len(values)) if values else None

    def _measure(self, overrides: Optional[dict]) -> dict:
        """Corre el walk-forward con `overrides` aplicados sobre un feed nuevo."""
        if self.feed_factory is None:
            return {"error": "sin feed"}
        try:
            feed = self.feed_factory()
        except Exception as exc:                              # noqa: BLE001
            return {"error": f"feed_factory fallo: {exc}"}
        if feed is None:
            return {"error": "feed_factory devolvio None"}

        store_path = self.store.path
        saved = {name: self.store.get(name) for name in self.store.all()}
        if overrides:
            for name, params in overrides.items():
                self.store.set_params(name, params, origin="validacion",
                                      reason="medicion de propuesta")
        try:
            bt = self.backtester_factory()
            result = bt.walk_forward(feed, folds=self.cfg.folds,
                                     train_ratio=self.cfg.train_ratio,
                                     label="validacion")
        except Exception as exc:                              # noqa: BLE001
            logger.warning("walk_forward fallo: %s", exc)
            result = {"error": f"{type(exc).__name__}: {exc}"}
        finally:
            # RESTAURAR SIEMPRE. Medir una propuesta no debe dejar sus
            # parametros aplicados: eso seria validar y aplicar a la vez, y el
            # filtro perderia todo su sentido.
            for name, params in saved.items():
                if params:
                    self.store.set_params(name, params, origin="validacion_rollback",
                                          reason="restaurar tras medir")
        if isinstance(result, dict) and "error" in result:
            return result

        folds = result.get("results") or []

        def avg_deg(key):
            vals = [f["degradation"][key] for f in folds
                    if f.get("degradation", {}).get(key) is not None]
            return (sum(vals) / len(vals)) if vals else None

        return {
            "out_of_sample": result.get("out_of_sample_aggregate") or {},
            # Una degradacion por base. Quien decide elige la suya, y asi la
            # comparacion es homogenea: sombras contra sombras, operadas contra
            # operadas. La version anterior solo media la degradacion de trades
            # operados, y con 1 o 2 operaciones ese numero es ruido puro -- el
            # filtro de overfit se disparaba siempre y bloqueaba cualquier
            # mejora, aunque la base de decision (sombras) tuviera muestra.
            "degradation": {
                "expectancy": avg_deg("expectancy"),
                "win_rate": avg_deg("win_rate"),
                "shadow_expectancy": avg_deg("shadow_expectancy"),
                "shadow_win_rate": avg_deg("shadow_win_rate"),
            },
            "folds": len(folds),
            # Detalle por pliegue: permite calcular la degradacion de UNA
            # estrategia (su in-sample contra su out-of-sample) en lugar de la
            # del portfolio entero.
            "folds_detail": folds,
            "verdict": result.get("verdict", ""),
            "params_version": store_path and str(store_path),
        }

    # =======================================================================
    # 4. FILTRO POR TESTEO MULTIPLE
    # =======================================================================

    def gate(self, validations: Sequence[ValidationReport]) -> list[ValidationReport]:
        """Aplica Benjamini-Hochberg sobre las propuestas aceptadas.

        POR QUE ES IMPRESCINDIBLE
        -------------------------
        Cada propuesta validada es una hipotesis. Si se prueban K hipotesis al
        nivel alpha y se conservan las que pasan, la probabilidad de colar al
        menos un falso positivo crece con K. Con K=10 y alpha=0.05 hay ~40% de
        probabilidad de aceptar algo que es puro ruido -- y ese "algo" se
        convierte en un cambio permanente de parametros que luego parece
        funcionar porque ya esta aplicado.

        BH controla la tasa de falsos descubrimientos: ordena los p-valores y
        compara cada uno contra (rango/K)*fdr. Es lo mismo que hace
        `SetupEvaluator.reevaluate_all` sobre los setups, y por la misma razon.
        """
        accepted = [v for v in validations if v.accepted and v.p_value is not None]
        for v in validations:
            if not v.accepted:
                continue
            if v.p_value is None:
                v.accepted = False
                v.reason += " | sin p-valor: no se puede corregir, se descarta."

        if not accepted:
            return list(validations)

        ps = [v.p_value for v in accepted]
        q_values, rejected = benjamini_hochberg(ps, self.cfg.fdr)
        for v, q, ok in zip(accepted, q_values, rejected):
            v.q_value = q
            if not ok:
                v.accepted = False
                v.reason += (
                    f" | NO sobrevive a Benjamini-Hochberg (p={v.p_value:.4f}, "
                    f"q={q if q is None else round(q, 4)}, fdr={self.cfg.fdr}). "
                    f"Probablemente sea la suerte de haber probado varias "
                    f"variantes a la vez."
                )
        return list(validations)

    # =======================================================================
    # 5. APLICACION
    # =======================================================================

    def _changes_in_window(self) -> int:
        window = datetime.utcnow() - timedelta(hours=self.cfg.change_window_hours)
        count = 0
        for entry in self.store.history(limit=200):
            if entry.get("origin") not in ("improvement", "llm", "local_search"):
                continue
            try:
                at = datetime.fromisoformat(entry["at"])
            except (KeyError, ValueError, TypeError):
                continue
            if at >= window:
                count += 1
        return count

    def apply(self, proposal: ImprovementProposal,
              validation: ValidationReport) -> dict:
        """Aplica una propuesta YA validada y YA filtrada. Versionada.

        Este es el unico camino de escritura. `mcp_server_trading.trading_apply_change`
        debe pasar por aqui: la version anterior del servidor MCP escribia
        directamente en `data/ai_overrides.json` con un filtro de texto que se
        podia esquivar con sinonimos, y sin ninguna comprobacion estadistica.
        """
        remaining = self.cfg.max_changes_per_window - self._changes_in_window()
        if remaining <= 0:
            return {"applied": False,
                    "reason": (f"tope de cambios alcanzado "
                               f"({self.cfg.max_changes_per_window} en "
                               f"{self.cfg.change_window_hours}h). El motor sigue "
                               f"diagnosticando y validando; aplicar se reanuda "
                               f"cuando pase la ventana.")}
        if not validation.accepted:
            return {"applied": False, "reason": f"no validada: {validation.reason}"}

        strategy = self._strategy_of(proposal)
        spec = self.registry.specs.get(strategy)
        if spec is None or spec.is_legacy:
            return {"applied": False,
                    "reason": f"{strategy} no es ajustable (sandbox ausente)"}

        accepted, rejected = validate_params(strategy, proposal.payload,
                                             spec.param_space)
        if not accepted:
            return {"applied": False, "reason": f"fuera del sandbox: {rejected}"}

        metrics = {
            "p_value": validation.p_value,
            "q_value": validation.q_value,
            "oos": (validation.candidate or {}).get("out_of_sample", {}),
            "degradation": validation.degradation,
        }
        version = self.store.set_params(
            strategy, accepted, origin="improvement",
            reason=(f"{proposal.rationale} | {validation.reason}"),
            metrics=metrics)

        # Los campos de medicion antes/despues del esquema. Sin ellos un
        # "applied" no dice si mejoro algo, y entonces no hay mejora continua:
        # hay cambio continuo.
        #
        # Se compara expectancy sobre la MISMA base en ambos lados, usando
        # `validation.basis` y no olfateando el texto del motivo. Mezclar
        # "expectancy de sombras" contra "expectancy de trades" daria una mejora
        # inventada por el cambio de unidad, no por el cambio de parametros.
        _, proposal.baseline_metric = self._baseline_metric(
            validation.baseline or {}, validation.basis, strategy)
        _, proposal.candidate_metric = self._baseline_metric(
            validation.candidate or {}, validation.basis, strategy)
        if (proposal.baseline_metric is not None
                and proposal.candidate_metric is not None):
            proposal.improvement = round(
                proposal.candidate_metric - proposal.baseline_metric, 6)
        proposal.status = STATUS_APPLIED
        proposal.decided_at = validation.validated_at or datetime.utcnow()
        self._persist(proposal, validation)
        self.registry.reload()
        logger.info("propuesta %s aplicada en %s (version %d): %s",
                    proposal.id[:8], strategy, version, accepted)
        return {"applied": True, "version": version, "params": accepted,
                "clamped": rejected, "remaining_in_window": remaining - 1}

    def _persist(self, proposal: ImprovementProposal, validation: ValidationReport):
        try:
            self.repo.save_proposal(proposal)
            self.repo.save_backtest_run(BacktestRun(
                id=f"val-{proposal.id}",
                created_at=validation.validated_at or datetime.utcnow(),
                label=f"validacion:{self._strategy_of(proposal)}",
                data_source=DataSource.CSV,
                strategy=self._strategy_of(proposal),
                params=proposal.payload,
                in_sample=(validation.baseline or {}),
                out_of_sample=(validation.candidate or {}).get("out_of_sample", {}),
                walk_forward=validation.walk_forward,
                verdict="aceptada" if validation.accepted else "rechazada",
                honest_note=validation.reason,
            ))
        except Exception as exc:                              # noqa: BLE001
            # Persistir el historial de mejoras es importante pero no puede
            # tumbar el ciclo. Se registra y se sigue.
            logger.warning("no se pudo persistir la propuesta %s: %s",
                           proposal.id, exc)

    # =======================================================================
    # 6. CICLO COMPLETO
    # =======================================================================

    def cycle(self, max_proposals: int = 6) -> dict:
        """Una vuelta completa. Devuelve un informe legible y auditable."""
        started = datetime.utcnow()
        diagnosis = self.diagnose()
        proposals = self.propose(diagnosis, max_proposals)
        if not proposals:
            return {
                "started_at": started.isoformat(),
                "finished_at": datetime.utcnow().isoformat(),
                "proposals": 0,
                "applied": [],
                "rejected": [],
                "diagnosis_counts": diagnosis["counts"],
                "note": ("sin propuestas. No es un fallo: si la evidencia no "
                         "senala nada accionable, no proponer es la respuesta "
                         "correcta. `AGENTS.md`: calidad sobre cantidad."),
            }

        baseline = self._measure(None)
        validations = [self.validate(p, baseline=baseline) for p in proposals]
        validations = self.gate(validations)

        applied, rejected = [], []
        by_id = {p.id: p for p in proposals}
        # Se aplican en orden de p-valor: la mejor evidencia primero, y el tope
        # de cambios corta la cola. Aplicar por orden de llegada haria que la
        # propuesta mas debil pudiera gastar el presupuesto.
        for v in sorted(validations, key=lambda x: (not x.accepted,
                                                    x.p_value if x.p_value is not None else 1.0)):
            proposal = by_id.get(v.proposal_id)
            if proposal is None:
                continue
            if not v.accepted:
                proposal.status = STATUS_REJECTED
                proposal.decided_at = v.validated_at or datetime.utcnow()
                proposal.rejection_reason = v.reason
                self._persist(proposal, v)
                rejected.append({"id": proposal.id[:8], "target": proposal.target,
                                 "params": proposal.payload, "reason": v.reason,
                                 "q_value": v.q_value})
                continue
            outcome = self.apply(proposal, v)
            if outcome.get("applied"):
                applied.append({"id": proposal.id[:8], "target": proposal.target,
                                "params": outcome["params"],
                                "version": outcome["version"],
                                "q_value": v.q_value,
                                "clamped": outcome.get("clamped")})
            else:
                proposal.status = STATUS_REJECTED
                proposal.decided_at = datetime.utcnow()
                proposal.rejection_reason = outcome.get("reason", "")
                self._persist(proposal, v)
                rejected.append({"id": proposal.id[:8], "target": proposal.target,
                                 "params": proposal.payload,
                                 "reason": outcome.get("reason", "")})

        return {
            "started_at": started.isoformat(),
            "finished_at": datetime.utcnow().isoformat(),
            "param_store_version": self.store.version,
            "proposals": len(proposals),
            "applied": applied,
            "rejected": rejected,
            "diagnosis_counts": diagnosis["counts"],
            "baseline_oos": (baseline or {}).get("out_of_sample", {}),
            "changes_remaining_in_window": (
                self.cfg.max_changes_per_window - self._changes_in_window()),
        }

    # =======================================================================
    # 7. REVISION Y ROLLBACK
    # =======================================================================

    def review_applied(self, since_hours: int = 24) -> dict:
        """Mide el rendimiento REAL tras aplicar y revierte lo que degrada.

        Un motor que aplica y no revisa asume que su validacion fue perfecta. No
        lo fue: la validacion es sobre historico, la revision es sobre lo que
        paso despues. Sin este paso el sistema solo puede acumular cambios, y
        acumular cambios sin medir es deriva.
        """
        cutoff = datetime.utcnow() - timedelta(hours=since_hours)
        applied = []
        for entry in self.store.history(limit=200):
            if entry.get("origin") != "improvement":
                continue
            try:
                if datetime.fromisoformat(entry["at"]) < cutoff:
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            applied.append(entry)

        live = self._live_performance(cutoff)
        rolled_back = []
        for entry in applied:
            strategy = entry.get("strategy")
            stats = live.get(strategy)
            if not stats or not stats["n"]:
                continue
            wr = stats["wins"] / stats["n"]
            be = breakeven_winrate(stats.get("payout") or 0.85) or 0.5405
            if stats["n"] >= 20 and wr < be:
                # Solo se revierte con muestra minima: revertir por 3 trades
                # malos es exactamente el error simetrico al de aplicar por 3
                # trades buenos.
                version = self.store.rollback(
                    strategy, origin="improvement_rollback",
                    reason=(f"rendimiento real tras aplicar: {stats['wins']}/{stats['n']} "
                            f"({wr:.2%}) por debajo del break-even ({be:.2%})"))
                if version:
                    rolled_back.append({"strategy": strategy, "version": version,
                                        "live": stats, "win_rate": round(wr, 4),
                                        "break_even": round(be, 4)})
        if rolled_back:
            self.registry.reload()
        return {"applied_in_window": len(applied), "live_performance": live,
                "rolled_back": rolled_back,
                "min_sample_for_rollback": 20}

    def _live_performance(self, since: datetime) -> dict:
        """Win rate real por estrategia desde `since`. Solo evidencia."""
        out: dict[str, dict] = {}
        try:
            trades = self.repo.get_trade_results(limit=5000, evidence_only=True)
        except Exception as exc:                              # noqa: BLE001
            logger.warning("no se pudo leer el rendimiento real: %s", exc)
            return out
        for t in trades:
            if t.timestamp and t.timestamp < since:
                continue
            if (t.features or {}).get("shadow"):
                continue     # solo lo operado de verdad
            key = t.strategy or "?"
            b = out.setdefault(key, {"n": 0, "wins": 0, "losses": 0,
                                     "pnl": 0.0, "payout": t.payout})
            won = t.execution_state.value == "won"
            lost = t.execution_state.value == "lost"
            if not (won or lost):
                continue
            b["n"] += 1
            b["wins" if won else "losses"] += 1
            b["pnl"] = round(b["pnl"] + (t.result or 0.0), 2)
        return out
