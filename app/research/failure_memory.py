# -*- coding: utf-8 -*-
"""Memoria de fallos: que la misma entrada equivocada no se repita.

LO QUE PIDE EL USUARIO
----------------------
"Que una perdida sea una experiencia para aprender por que se perdio, ir
recalibrando las entradas, y que la entrada este estudiada antes para no cometer
el mismo error de entrada otra vez."

`app/research/loss_forensics.py` responde POR QUE se perdio. Este modulo cierra
el bucle: convierte ese diagnostico en una condicion comprobable ANTES de entrar.

EL PELIGRO, DICHO PRIMERO
-------------------------
Aprender filtros de las perdidas es la forma mas rapida de reconstruir el bug que
hundio las ~500 operaciones anteriores. Si el sistema ve 6 perdidas con RSI > 68
y deduce "no entrar con RSI > 68", no ha aprendido nada: con n=6 eso es ruido. El
intervalo de Wilson al 95% para 6/6 es [62%, 100%] -- compatible con casi todo.

Asi que una condicion solo se convierte en veto cuando:

  1. Tiene muestra minima propia (30 observaciones por defecto).
  2. Su cota INFERIOR de Wilson para la tasa de perdida supera la tasa de perdida
     incondicional del setup. O sea: no basta con que las operaciones con esa
     condicion perdieran; tiene que estar demostrado que perdieron MAS que el
     resto, con margen estadistico.
  3. Sobrevive a Benjamini-Hochberg. Se prueban muchas condiciones a la vez
     (cada feature numerica x 4 cortes x 2 direcciones), y con tantas pruebas
     siempre hay alguna que parece significativa por azar. BH controla la tasa de
     falsos descubrimientos exactamente igual que en `SetupEvaluator` y en el
     motor de mejora.
  4. Es observable EN EL INSTANTE DE ENTRADA. Solo se usan claves de
     `trade.features`, que las estrategias rellenan al generar la senal. Nada de
     MAE/MFE ni de recorrido posterior: eso es diagnostico post-hoc y usarlo al
     decidir seria look-ahead, el bug del que venimos.

Y todo veto es versionado, reversible, y se registra cada vez que se activa. Una
memoria que no se puede deshacer no es memoria, es una condena.

QUE HACE CON LO QUE APRENDE
---------------------------
Dos salidas, no una:

  * VETO INMEDIATO: si la condicion esta demostrada, la entrada se bloquea con el
    motivo escrito. No vuelve a cometerse.
  * PROPUESTA AL MOTOR DE MEJORA: el veto es un parche local sobre UN setup. La
    causa raiz suele ser un parametro de la estrategia, y eso lo arregla
    `ImprovementEngine` con su sandbox, walk-forward y rollback. El veto protege
    mientras tanto; no sustituye al arreglo.
"""
from __future__ import annotations

import json
import logging
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from app.config import config
from app.data.schemas import ExecutionState, TradeResult
from app.stats.core import benjamini_hochberg, binomial_pvalue_upper, wilson_interval

logger = logging.getLogger(__name__)


@dataclass
class Condition:
    """Una condicion observable en la entrada: `feature >= value` o `<= value`."""

    feature: str
    op: str                      # ">=" | "<="
    value: float
    n: int = 0                   # observaciones que cumplen la condicion
    losses: int = 0
    loss_rate: Optional[float] = None
    loss_rate_lower: Optional[float] = None
    p_value: Optional[float] = None
    q_value: Optional[float] = None
    #: Tasa de perdida del setup SIN condicionar. Es el contraste necesario:
    #: "perdio el 70% de las veces" no significa nada si el setup pierde el 70%
    #: en general.
    baseline_loss_rate: Optional[float] = None
    active: bool = False
    activated_at: Optional[datetime] = None
    times_triggered: int = 0

    def as_key(self) -> str:
        return f"{self.feature} {self.op} {self.value}"

    def matches(self, features: dict) -> bool:
        raw = (features or {}).get(self.feature)
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            return False
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return False
        return value >= self.value if self.op == ">=" else value <= self.value

    def as_dict(self) -> dict:
        return {
            "feature": self.feature, "op": self.op, "value": self.value,
            "n": self.n, "losses": self.losses, "loss_rate": self.loss_rate,
            "loss_rate_lower": self.loss_rate_lower, "p_value": self.p_value,
            "q_value": self.q_value, "baseline_loss_rate": self.baseline_loss_rate,
            "active": self.active, "times_triggered": self.times_triggered,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Condition":
        activated = data.get("activated_at")
        return cls(
            feature=str(data.get("feature", "")), op=str(data.get("op", ">=")),
            value=float(data.get("value", 0.0)), n=int(data.get("n") or 0),
            losses=int(data.get("losses") or 0),
            loss_rate=data.get("loss_rate"),
            loss_rate_lower=data.get("loss_rate_lower"),
            p_value=data.get("p_value"), q_value=data.get("q_value"),
            baseline_loss_rate=data.get("baseline_loss_rate"),
            active=bool(data.get("active")),
            times_triggered=int(data.get("times_triggered") or 0),
            activated_at=datetime.fromisoformat(activated) if activated else None,
        )


@dataclass
class SetupMemory:
    """Lo aprendido sobre UN setup."""

    slug: str
    n: int = 0
    losses: int = 0
    loss_rate: Optional[float] = None
    conditions: list = field(default_factory=list)
    last_updated: Optional[datetime] = None

    @property
    def active_vetoes(self) -> list:
        return [c for c in self.conditions if c.active]

    def as_dict(self) -> dict:
        return {
            "slug": self.slug, "n": self.n, "losses": self.losses,
            "loss_rate": self.loss_rate,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "conditions": [c.as_dict() for c in self.conditions],
        }


class FailureMemory:
    """Memoria de condiciones de entrada que preceden a perdidas."""

    #: Muestra minima por condicion. Por debajo no se aprende nada.
    MIN_CONDITION_SAMPLE = 30
    #: Muestra minima del setup para siquiera mirar condiciones.
    MIN_SETUP_SAMPLE = 40
    #: Maximo de features numericas analizadas por setup. Acota el numero de
    #: hipotesis simultaneas, que es lo que BH tiene que corregir.
    MAX_FEATURES = 8
    #: Cortes probados por feature, sobre los cuantiles observados.
    QUANTILE_CUTS = (0.50, 0.75, 0.90)
    #: FDR para Benjamini-Hochberg.
    FDR = 0.10
    MAX_HISTORY = 200

    def __init__(self, path: Optional[str | Path] = None,
                 min_condition_sample: Optional[int] = None,
                 fdr: Optional[float] = None):
        self.path = Path(path or (Path(config.database_path).parent
                                  / "failure_memory.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if min_condition_sample:
            self.MIN_CONDITION_SAMPLE = int(min_condition_sample)
        if fdr:
            self.FDR = float(fdr)
        #: slug -> [(features_dict, won_bool)]
        self._observations: dict[str, list] = defaultdict(list)
        self._memory: dict[str, SetupMemory] = {}
        self._history: list[dict] = []
        self._load()

    # ── persistencia ──────────────────────────────────────────────────────

    def _load(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            backup = self.path.with_suffix(
                f".corrupto.{datetime.utcnow():%Y%m%d%H%M%S}.json")
            try:
                shutil.copy2(self.path, backup)
                logger.error("failure_memory.json corrupto (%s); copiado a %s",
                             exc, backup)
            except OSError:
                logger.error("failure_memory.json corrupto (%s)", exc)
            return
        for slug, raw in (data.get("setups") or {}).items():
            memory = SetupMemory(slug=slug, n=int(raw.get("n") or 0),
                                 losses=int(raw.get("losses") or 0),
                                 loss_rate=raw.get("loss_rate"))
            last = raw.get("last_updated")
            memory.last_updated = datetime.fromisoformat(last) if last else None
            memory.conditions = [Condition.from_dict(c)
                                 for c in (raw.get("conditions") or [])]
            self._memory[slug] = memory
        self._history = list(data.get("history") or [])[-self.MAX_HISTORY:]

    def _save(self):
        payload = {
            "version": 1,
            "updated_at": datetime.utcnow().isoformat(),
            "fdr": self.FDR,
            "min_condition_sample": self.MIN_CONDITION_SAMPLE,
            "setups": {slug: m.as_dict() for slug, m in self._memory.items()},
            "history": self._history[-self.MAX_HISTORY:],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                       encoding="utf-8")
        # Escritura atomica: si el proceso muere a mitad, no queda un JSON a
        # medias que el siguiente arranque intente leer.
        tmp.replace(self.path)

    # ── observaciones ─────────────────────────────────────────────────────

    def observe(self, trades: Sequence[TradeResult]) -> int:
        """Registra resultados. Acepta trades operados Y sombras.

        Las sombras son la mayor parte de la muestra y son legitimas aqui por la
        misma razon que en `SetupEvaluator`: el resultado de una binaria queda
        determinado por el mercado, no por haber puesto dinero. Lo que una sombra
        no mide es el riesgo de ejecucion, y por eso esto produce VETOS (que
        evitan una entrada) y no cambios de tamano.
        """
        added = 0
        for trade in trades:
            if trade.execution_state not in (ExecutionState.WON, ExecutionState.LOST):
                continue     # empate/UNKNOWN no informa sobre la entrada
            features = trade.features or {}
            slug = str(features.get("setup_slug") or "")
            if not slug:
                continue
            numeric = {k: float(v) for k, v in features.items()
                       if isinstance(v, (int, float)) and not isinstance(v, bool)}
            if not numeric:
                continue
            won = trade.execution_state == ExecutionState.WON
            self._observations[slug].append((numeric, won))
            memory = self._memory.setdefault(slug, SetupMemory(slug=slug))
            memory.n += 1
            memory.losses += 0 if won else 1
            memory.last_updated = datetime.utcnow()
            added += 1
        if added:
            for slug in {str((t.features or {}).get("setup_slug") or "")
                         for t in trades}:
                memory = self._memory.get(slug)
                if memory and memory.n:
                    memory.loss_rate = round(memory.losses / memory.n, 4)
        return added

    # ── aprendizaje ───────────────────────────────────────────────────────

    def learn(self, slug: Optional[str] = None) -> dict:
        """Reevalua las condiciones de un setup (o de todos).

        Devuelve que se activo y que se desactivo, con los numeros. Se llama
        periodicamente, no en cada operacion: recalcular cuantiles y BH por trade
        seria caro y ademas invitaria a mirar la estadistica demasiado a menudo,
        que es justo lo que `SetupEvaluator` evita con sus checkpoints
        geometricos.
        """
        slugs = [slug] if slug else list(self._observations)
        report = {"activated": [], "deactivated": [], "insufficient": []}
        for target in slugs:
            observations = self._observations.get(target) or []
            memory = self._memory.get(target)
            if memory is None or len(observations) < self.MIN_SETUP_SAMPLE:
                report["insufficient"].append(
                    {"slug": target, "n": len(observations),
                     "minimo": self.MIN_SETUP_SAMPLE})
                continue
            result = self._learn_one(memory, observations)
            report["activated"] += result["activated"]
            report["deactivated"] += result["deactivated"]
        if report["activated"] or report["deactivated"]:
            self._save()
        return report

    def _learn_one(self, memory: SetupMemory, observations: list) -> dict:
        n_total = len(observations)
        losses_total = sum(1 for _, won in observations if not won)
        baseline = losses_total / n_total if n_total else 0.0

        # Features presentes en casi todas las observaciones. Una feature que
        # aparece en 3 de 500 no puede sostener un veto.
        presence: dict[str, int] = defaultdict(int)
        for features, _ in observations:
            for key in features:
                presence[key] += 1
        eligible = [k for k, c in presence.items()
                    if c >= max(self.MIN_CONDITION_SAMPLE, n_total * 0.5)]
        # Orden estable: por frecuencia y luego alfabetico, para que dos corridas
        # sobre los mismos datos aprendan lo mismo.
        eligible.sort(key=lambda k: (-presence[k], k))
        eligible = eligible[:self.MAX_FEATURES]

        candidates: list[Condition] = []
        for feature in eligible:
            values = sorted(f[feature] for f, _ in observations if feature in f)
            if len(values) < self.MIN_CONDITION_SAMPLE:
                continue
            for quantile in self.QUANTILE_CUTS:
                idx = min(len(values) - 1, int(quantile * len(values)))
                threshold = values[idx]
                for op in (">=", "<="):
                    cond = Condition(feature=feature, op=op, value=round(threshold, 8))
                    matching = [(f, won) for f, won in observations
                                if cond.matches(f)]
                    cond.n = len(matching)
                    if cond.n < self.MIN_CONDITION_SAMPLE:
                        continue
                    # Una condicion que se cumple en TODAS las observaciones no
                    # condiciona nada: su tasa es la incondicional por construccion.
                    if cond.n >= n_total * 0.98:
                        continue
                    cond.losses = sum(1 for _, won in matching if not won)
                    cond.loss_rate = cond.losses / cond.n
                    _, lower = None, wilson_interval(cond.losses, cond.n)[0]
                    cond.loss_rate_lower = lower
                    cond.baseline_loss_rate = round(baseline, 4)
                    # H1: con esta condicion se pierde MAS que el break-even de
                    # la tasa incondicional. Unilateral, que es la pregunta real.
                    cond.p_value = binomial_pvalue_upper(
                        cond.losses, cond.n, baseline)
                    candidates.append(cond)

        activated, deactivated = [], []
        if not candidates:
            return {"activated": activated, "deactivated": deactivated}

        # `benjamini_hochberg` devuelve una lista de dicts con index/p/q/rejected,
        # no dos listas. Se desempacaba mal y lanzaba ValueError en cuanto habia
        # alguna condicion candidata -- o sea, siempre que la memoria tenia datos
        # suficientes para aprender algo.
        bh = benjamini_hochberg([c.p_value for c in candidates], self.FDR)
        for cond, row in zip(candidates, bh):
            cond.q_value = row.get("q")
            lower = cond.loss_rate_lower
            # Los cuatro criterios a la vez. Falta uno -> no hay veto.
            cond.active = bool(
                row.get("rejected")
                and cond.n >= self.MIN_CONDITION_SAMPLE
                and lower is not None
                and lower > (cond.baseline_loss_rate or 0.0)
            )

        previous = {c.as_key(): c for c in memory.conditions}
        for cond in candidates:
            if not cond.active:
                continue
            key = cond.as_key()
            old = previous.get(key)
            cond.times_triggered = old.times_triggered if old else 0
            cond.activated_at = (old.activated_at if old and old.active
                                 else datetime.utcnow())
            if old is None or not old.active:
                activated.append({
                    "slug": memory.slug, "condition": key, "n": cond.n,
                    "losses": cond.losses,
                    "loss_rate": round(cond.loss_rate, 4) if cond.loss_rate is not None else None,
                    "loss_rate_lower": round(lower, 4) if lower is not None else None,
                    "baseline_loss_rate": cond.baseline_loss_rate,
                    "p_value": cond.p_value, "q_value": cond.q_value,
                })
                self._history.append({
                    "at": datetime.utcnow().isoformat(), "slug": memory.slug,
                    "action": "veto_activado", "condition": key,
                    "n": cond.n, "q_value": cond.q_value,
                    "reason": (f"tasa de perdida {cond.loss_rate:.2%} "
                               f"(cota inferior {lower:.2%}) contra "
                               f"{baseline:.2%} incondicional, n={cond.n}, "
                               f"q={cond.q_value if cond.q_value is None else round(cond.q_value, 6)}"),
                })
        # Los vetos que dejan de estar sostenidos se DESACTIVAN. Una memoria que
        # solo acumula prohibiciones acaba sin operar nada, y una condicion que
        # dejo de ser cierta no debe seguir bloqueando entradas.
        surviving = {c.as_key() for c in candidates if c.active}
        for key, old in previous.items():
            if old.active and key not in surviving:
                deactivated.append({"slug": memory.slug, "condition": key,
                                    "reason": "ya no esta sostenida por la muestra"})
                self._history.append({
                    "at": datetime.utcnow().isoformat(), "slug": memory.slug,
                    "action": "veto_desactivado", "condition": key,
                    "reason": "la muestra dejo de sostenerlo",
                })
        memory.conditions = [c for c in candidates if c.active] + \
                            [c for c in previous.values()
                             if not c.active and c.as_key() not in
                             {x.as_key() for x in candidates}]
        memory.loss_rate = round(baseline, 4)
        memory.n = n_total
        memory.losses = losses_total
        del self._history[:-self.MAX_HISTORY]
        return {"activated": activated, "deactivated": deactivated}

    # ── consulta en la entrada ────────────────────────────────────────────

    def consult(self, slug: str, features: dict) -> dict:
        """Se llama ANTES de entrar. Devuelve si hay veto y por que.

        Solo se usan features observables en el instante de entrada. Si no hay
        nada aprendido para este setup, no veta: la ausencia de memoria no es una
        razon para bloquear una entrada.
        """
        memory = self._memory.get(slug)
        if memory is None:
            return {"vetoed": False, "reasons": [], "conditions": []}
        hits = []
        for cond in memory.active_vetoes:
            if cond.matches(features):
                cond.times_triggered += 1
                hits.append(cond)
        if not hits:
            return {"vetoed": False, "reasons": [], "conditions": [],
                    "vetos_activos": len(memory.active_vetoes)}
        reasons = [
            f"{c.as_key()}: perdio {c.losses}/{c.n} "
            f"({(c.loss_rate or 0):.1%}, cota inferior "
            f"{(c.loss_rate_lower or 0):.1%}) contra "
            f"{(c.baseline_loss_rate or 0):.1%} incondicional del setup"
            for c in hits
        ]
        return {
            "vetoed": True,
            "reasons": reasons,
            "conditions": [c.as_key() for c in hits],
            "vetos_activos": len(memory.active_vetoes),
            "note": ("Veto estadisticamente sostenido, no intuicion. Es reversible: "
                     "se desactiva solo cuando la muestra deja de sostenerlo."),
        }

    # ── introspeccion ─────────────────────────────────────────────────────

    def report(self, limit: int = 30) -> dict:
        """Foto completa, para el dashboard y para el prompt del supervisor."""
        setups = sorted(self._memory.values(),
                        key=lambda m: -len(m.active_vetoes))[:limit]
        return {
            "path": str(self.path),
            "setups_con_memoria": len(self._memory),
            "setups_observados": len(self._observations),
            "vetos_activos": sum(len(m.active_vetoes) for m in self._memory.values()),
            "min_condition_sample": self.MIN_CONDITION_SAMPLE,
            "min_setup_sample": self.MIN_SETUP_SAMPLE,
            "fdr": self.FDR,
            "setups": [{
                "slug": m.slug, "n": m.n, "losses": m.losses,
                "loss_rate": m.loss_rate,
                "vetos": [c.as_dict() for c in m.active_vetoes],
            } for m in setups],
            "history": self._history[-20:],
        }

    def forget(self, slug: str) -> bool:
        """Borra la memoria de un setup. Reversibilidad explicita."""
        existed = slug in self._memory
        self._memory.pop(slug, None)
        self._observations.pop(slug, None)
        if existed:
            self._history.append({
                "at": datetime.utcnow().isoformat(), "slug": slug,
                "action": "memoria_olvidada", "reason": "solicitud explicita"})
            del self._history[:-self.MAX_HISTORY]
            self._save()
        return existed

    def clear(self):
        self._memory.clear()
        self._observations.clear()
        self._history.append({
            "at": datetime.utcnow().isoformat(), "slug": "*",
            "action": "memoria_vaciada", "reason": "solicitud explicita"})
        self._save()
