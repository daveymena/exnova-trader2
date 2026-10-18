# -*- coding: utf-8 -*-
"""Registro de estrategias + almacen versionado de parametros.

DOS TRABAJOS
------------
1. Dar al motor UNA lista de estrategias con un contrato uniforme. Antes
   `SignalAgent.__init__` instanciaba a mano una sola (`sr_bounce`) con un
   `if practice else` que le cambiaba los parametros segun el modo. Eso significa
   que el sistema en practice y el sistema en real NO son el mismo sistema, y lo
   que se mide en uno no vale para el otro. Aqui la configuracion es una sola y
   explicita.

2. Ser el punto de escritura del motor de mejora continua. Los parametros viven
   en un JSON versionado (`data/strategy_params.json`) con historial, de modo
   que cada cambio queda registrado, es auditable y se puede revertir. Un motor
   que "mejora" sin poder deshacer no es un motor de mejora, es una fuga.

SANDBOX DE PARAMETROS
---------------------
Cada estrategia declara `param_space`: el rango de cada parametro ajustable.
Nada fuera de ese rango se acepta, venga de donde venga -- incluido el LLM.
Es la diferencia entre "el agente de IA afina la estrategia" y "el agente de IA
escribe lo que quiere en un fichero que el bot ejecuta". Lo segundo es como se
acaba con un `min_confidence = 0.0` y el bot operando cada vela.

Las 5 estrategias heredadas (`sr_bounce`, `trend_continuation`,
`mean_reversion`, `breakout_retest`, `breakout_direct`) se envuelven en
`LegacyStrategy` en lugar de reescribirlas: funcionan, tienen tests y
reescribirlas solo para que hereden de una clase base romperia el historial
estadistico de sus setups (el nombre de la estrategia forma parte del
`SetupKey`).
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence, Type

from app.config import config
from app.data.schemas import Candle, Direction, MarketRegime
from app.strategies.base import Strategy

logger = logging.getLogger(__name__)


# ===========================================================================
# Adaptador para las estrategias heredadas
# ===========================================================================

class LegacyStrategy:
    """Envuelve una estrategia con el API antiguo (`config=` + `evaluate`).

    Las cinco heredadas comparten firma exacta, asi que un unico adaptador
    sirve para todas. Se preserva su logica intacta: reescribirlas no aportaria
    nada y romperia la continuidad de sus setups en la base de datos.
    """

    def __init__(self, name: str, impl, family: str = "legacy",
                 expiries: tuple = (60, 180, 300),
                 param_space: Optional[dict] = None):
        self.name = name
        self.family = family
        self.expiries = expiries
        self.param_space = param_space or {}
        self._impl = impl
        self.params = dict(getattr(impl, "config", {}) or {})

    @classmethod
    def default_params(cls) -> dict:
        return {}

    def evaluate(self, candles_m15: Sequence[Candle], candles_m5: Sequence[Candle],
                 candles_m1: Sequence[Candle], asset: str = "") -> dict:
        out = self._impl.evaluate(list(candles_m15), list(candles_m5),
                                  list(candles_m1), asset) or {}
        # Normalizacion al contrato comun. Las heredadas no devuelven todas las
        # claves, y el motor no debe tener que preguntar "existe esta clave?"
        # en cada sitio.
        out.setdefault("direction", Direction.NO_TRADE)
        out.setdefault("confidence", 0.0)
        out.setdefault("strategy", self.name)
        out.setdefault("market_regime", MarketRegime.UNKNOWN)
        out.setdefault("entry_rationale", out.get("reasons", [""])[0]
                       if isinstance(out.get("reasons"), list) and out.get("reasons")
                       else "")
        out.setdefault("invalidation", "")
        out.setdefault("features", {})
        out.setdefault("opportunity_score", float(out.get("confidence", 0.0)))
        out.setdefault("skip_entry_timing", False)
        if out["strategy"] != self.name:
            out["strategy"] = self.name
        return out


# ===========================================================================
# Especificacion y registro
# ===========================================================================

@dataclass
class StrategySpec:
    name: str
    factory: object                 # clase Strategy o callable(params) -> obj
    family: str = "generic"
    expiries: tuple = (60, 180, 300)
    param_space: dict = field(default_factory=dict)
    enabled: bool = True
    is_legacy: bool = False


def _load_specs() -> dict[str, StrategySpec]:
    """Construye las especificaciones. Los imports van aqui dentro para que un
    fallo en una estrategia no impida cargar las demas."""
    specs: dict[str, StrategySpec] = {}

    from app.strategies.liquidity_sweep_reversal import LiquiditySweepReversal
    from app.strategies.engulfing_momentum import EngulfingMomentum
    specs[LiquiditySweepReversal.name] = StrategySpec(
        name=LiquiditySweepReversal.name, factory=LiquiditySweepReversal,
        family=LiquiditySweepReversal.family, expiries=LiquiditySweepReversal.expiries,
        param_space=dict(LiquiditySweepReversal.param_space),
    )
    specs[EngulfingMomentum.name] = StrategySpec(
        name=EngulfingMomentum.name, factory=EngulfingMomentum,
        family=EngulfingMomentum.family, expiries=EngulfingMomentum.expiries,
        param_space=dict(EngulfingMomentum.param_space),
    )

    legacy = [
        ("sr_bounce", "app.strategies.sr_bounce", "SRBounceStrategy", "mean_reversion"),
        ("trend_continuation", "app.strategies.trend_continuation",
         "TrendContinuationStrategy", "trend_continuation"),
        ("mean_reversion", "app.strategies.mean_reversion",
         "MeanReversionStrategy", "mean_reversion"),
        ("breakout_retest", "app.strategies.breakout_retest",
         "BreakoutRetestStrategy", "breakout"),
        ("breakout_direct", "app.strategies.breakout_direct",
         "BreakoutDirectStrategy", "breakout"),
    ]
    for name, module_path, class_name, family in legacy:
        try:
            import importlib
            module = importlib.import_module(module_path)
            impl_cls = getattr(module, class_name)

            def make_factory(cls=impl_cls, n=name, f=family):
                def factory(params: dict):
                    return LegacyStrategy(n, cls(config=dict(params)), family=f)
                return factory

            specs[name] = StrategySpec(
                name=name, factory=make_factory(), family=family,
                expiries=(60, 180, 300), param_space={}, is_legacy=True,
            )
        except Exception as exc:                          # noqa: BLE001
            logger.warning("no se pudo cargar la estrategia heredada %s: %s", name, exc)

    return specs


class ParamStore:
    """Almacen JSON versionado de parametros, con historial y rollback.

    Formato:
        {
          "version": 7,
          "updated_at": "...",
          "params": {"sr_bounce": {"min_confidence": 0.62}, ...},
          "history": [{"version":6,"at":"...","origin":"llm","change":{...},
                       "reason":"...","metrics":{...}}, ...]
        }

    El historial se conserva integro (con tope) porque "mejora continua" sin
    registro de que se cambio, por que y con que medicion no es mejora: es
    deriva. Y sin `rollback` no hay forma de deshacer un cambio malo, que es lo
    primero que hace falta cuando el motor se equivoca.
    """

    MAX_HISTORY = 200

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path or (Path(config.database_path).parent / "strategy_params.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._read()

    def _read(self) -> dict:
        if not self.path.exists():
            return {"version": 0, "updated_at": None, "params": {}, "history": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data.setdefault("version", 0)
            data.setdefault("params", {})
            data.setdefault("history", [])
            return data
        except (json.JSONDecodeError, OSError) as exc:
            # Un fichero corrupto no debe tumbar el bot. Se aparta y se empieza
            # de cero: perder los parametros ajustados es malo; operar con una
            # config a medias leida de un JSON roto es peor.
            backup = self.path.with_suffix(f".corrupto.{datetime.utcnow():%Y%m%d%H%M%S}.json")
            try:
                shutil.copy2(self.path, backup)
                logger.error("strategy_params.json corrupto (%s); copiado a %s", exc, backup)
            except OSError:
                logger.error("strategy_params.json corrupto (%s)", exc)
            return {"version": 0, "updated_at": None, "params": {}, "history": []}

    def _write(self):
        self._data["updated_at"] = datetime.utcnow().isoformat()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False, default=str),
                       encoding="utf-8")
        # Escritura atomica: si el proceso muere a mitad, no queda un JSON a
        # medias que el siguiente arranque intente leer.
        tmp.replace(self.path)

    @property
    def version(self) -> int:
        return int(self._data.get("version", 0))

    def get(self, strategy: str) -> dict:
        return dict(self._data["params"].get(strategy, {}))

    def all(self) -> dict:
        return {k: dict(v) for k, v in self._data["params"].items()}

    def history(self, limit: int = 50) -> list[dict]:
        return list(self._data["history"])[-limit:]

    def set_params(self, strategy: str, params: dict, origin: str = "manual",
                   reason: str = "", metrics: Optional[dict] = None) -> int:
        """Guarda parametros y registra el cambio. Devuelve la nueva version."""
        current = self._data["params"].get(strategy, {})
        merged = {**current, **params}
        self._data["params"][strategy] = merged
        self._data["version"] = int(self._data.get("version", 0)) + 1
        self._data["history"].append({
            "version": self._data["version"],
            "at": datetime.utcnow().isoformat(),
            "origin": origin,
            "strategy": strategy,
            "change": dict(params),
            "previous": dict(current),
            "reason": reason,
            "metrics": dict(metrics or {}),
        })
        del self._data["history"][:-self.MAX_HISTORY]
        self._write()
        return self._data["version"]

    def rollback(self, strategy: str, origin: str = "rollback",
                 reason: str = "") -> Optional[int]:
        """Deshace el ultimo cambio de una estrategia. None si no hay historial."""
        for entry in reversed(self._data["history"]):
            if entry.get("strategy") != strategy or "previous" not in entry:
                continue
            self._data["params"][strategy] = dict(entry["previous"])
            self._data["version"] = int(self._data.get("version", 0)) + 1
            self._data["history"].append({
                "version": self._data["version"],
                "at": datetime.utcnow().isoformat(),
                "origin": origin, "strategy": strategy,
                "change": dict(entry["previous"]),
                "previous": dict(entry.get("change", {})),
                "reason": reason or f"rollback a la version {entry['version']}",
                "metrics": {},
            })
            del self._data["history"][:-self.MAX_HISTORY]
            self._write()
            return self._data["version"]
        return None


def validate_params(strategy: str, params: dict,
                    param_space: dict) -> tuple[dict, list[str]]:
    """Recorta `params` al sandbox declarado. Devuelve (aceptados, rechazos).

    Todo lo que este fuera de rango se RECORTA al limite y se registra en la
    lista de rechazos, en lugar de aceptarse en silencio o de tumbar la
    propuesta entera. Recortar y avisar es lo unico seguro: aceptar un
    `min_confidence=0.0` porque lo pidio un LLM es entregarle el bot.
    """
    accepted: dict = {}
    rejected: list[str] = []
    for key, value in (params or {}).items():
        spec = param_space.get(key)
        if spec is None:
            rejected.append(f"{strategy}.{key}: parametro no declarada en param_space")
            continue
        low, high = spec
        if isinstance(value, bool):
            rejected.append(f"{strategy}.{key}: booleano fuera del sandbox numerico")
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            rejected.append(f"{strategy}.{key}={value!r}: no numerico")
            continue
        if numeric < low or numeric > high:
            clamped = min(max(numeric, low), high)
            rejected.append(
                f"{strategy}.{key}={numeric} fuera de [{low}, {high}]: "
                f"recortado a {clamped}"
            )
            numeric = clamped
        # Enteros declarados como rango entero se devuelven como int.
        accepted[key] = int(numeric) if isinstance(low, int) and isinstance(high, int) \
            and float(numeric).is_integer() else numeric
    return accepted, rejected


class StrategyRegistry:
    """Lista unica de estrategias operativas, con sus parametros vigentes."""

    def __init__(self, store: Optional[ParamStore] = None,
                 only: Optional[Sequence[str]] = None,
                 enabled: Optional[dict[str, bool]] = None):
        self.store = store or ParamStore()
        self.specs = _load_specs()
        self._only = set(only) if only else None
        self._enabled = dict(enabled or {})
        self._instances: dict[str, object] = {}
        self._build()

    def _build(self):
        for name, spec in self.specs.items():
            if self._only is not None and name not in self._only:
                continue
            if name in self._enabled and not self._enabled[name]:
                continue
            if not spec.enabled:
                continue
            overrides = self.store.get(name)
            accepted, rejected = validate_params(name, overrides, spec.param_space)
            for reason in rejected:
                logger.warning("parametro descartado del almacen: %s", reason)
            self._instances[name] = self._instantiate(spec, accepted)

    @staticmethod
    def _instantiate(spec: StrategySpec, params: dict):
        try:
            if isinstance(spec.factory, type) and issubclass(spec.factory, Strategy):
                return spec.factory(params=params or None)
            return spec.factory(params or {})
        except Exception as exc:                          # noqa: BLE001
            logger.error("no se pudo instanciar %s: %s", spec.name, exc)
            return None

    # ── acceso ────────────────────────────────────────────────────────────

    def names(self) -> list[str]:
        return [n for n, i in self._instances.items() if i is not None]

    def strategies(self) -> dict[str, object]:
        return {n: i for n, i in self._instances.items() if i is not None}

    def get(self, name: str):
        return self._instances.get(name)

    def spec(self, name: str) -> Optional[StrategySpec]:
        return self.specs.get(name)

    def expiries(self, name: str) -> tuple:
        spec = self.specs.get(name)
        return tuple(spec.expiries) if spec else (60, 180, 300)

    def params(self, name: str) -> dict:
        instance = self._instances.get(name)
        if instance is None:
            return {}
        return dict(getattr(instance, "params", {}) or {})

    def reload(self):
        """Relee el almacen y reconstruye. Se llama tras aplicar un cambio."""
        self.store = ParamStore(self.store.path)
        self._instances.clear()
        self._build()
        logger.info("registro de estrategias recargado (version %s): %s",
                    self.store.version, ", ".join(self.names()) or "ninguna")

    def describe(self) -> dict:
        """Foto del registro, para el dashboard y para el prompt del LLM."""
        return {
            "param_store_version": self.store.version,
            "param_store_path": str(self.store.path),
            "strategies": {
                name: {
                    "family": spec.family,
                    "expiries": list(spec.expiries),
                    "legacy": spec.is_legacy,
                    "active": name in self._instances and self._instances[name] is not None,
                    "params": self.params(name),
                    "tunable": sorted(spec.param_space),
                }
                for name, spec in self.specs.items()
            },
        }
