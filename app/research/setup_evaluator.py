# -*- coding: utf-8 -*-
"""Evaluador de setups: decide QUE se opera, a QUE tamano y QUE se retira.

Es el freno estadistico del motor de mejora continua. Sin esto, "mejorarse a si
mismo" significa ajustar parametros hasta que la curva de equity se vea bien,
que es exactamente lo que hundio las 500 operaciones historicas de este
proyecto: se promovieron reglas ajustadas sobre n=1, n=6, n=7 y n=9
observaciones.

EL NUMERO QUE LO EXPLICA TODO
-----------------------------
Con payout 0.85 el break-even es 1/1.85 = 54.05%. Un setup con 6 aciertos de 9
(66.7%) parece tener edge. Su intervalo de Wilson al 95% va de 35.4% a 87.9%:
no dice absolutamente nada. Operar eso no es trading, es leer el ruido y
llamarlo senal.

Por eso `min_observations` es 200 por defecto y NO SE PUEDE bajar por
configuracion a menos de 30. Con n=200 y 57.5% de aciertos la cota inferior de
Wilson es 50.6%, que sigue POR DEBAJO del break-even: el veredicto correcto es
RUIDO, y el setup sigue en exploracion a tamano reducido. Es un resultado
decepcionante y es el correcto.

CINCO PROTECCIONES, por orden de impacto
----------------------------------------
1. Minimo de observaciones. Por debajo de `min_observations` el veredicto es
   SIEMPRE `INSUFICIENTE`. Sin excepciones y sin "modo practice lo relaja":
   relajar el minimo segun el modo era el punto 5 de la auditoria, y convertia
   el gate en adorno.
2. Se exige que la COTA INFERIOR de Wilson supere el break-even, no el win rate
   puntual.
3. Correccion por comparaciones multiples. Probar 40 variantes y quedarse con
   la mejor produce un ganador aparente aunque las 40 sean monedas al aire.
   Bonferroni para ASCENDER (caro equivocarse: se opera a tamano completo) y
   Benjamini-Hochberg para RETIRAR (barato equivocarse: solo se deja de operar).
4. Correccion por miradas repetidas. Mirar el mismo setup despues de cada
   operacion es testear la misma hipotesis cientos de veces. Aqui solo se
   decide en checkpoints geometricos (200, 400, 800...) y el numero de miradas
   penaliza el alpha.
5. Retirada PERMANENTE con tope de reaperturas y tope de variantes por familia.
   Reabrir un setup rechazado, o reintentar la misma familia con parametros
   nuevos hasta que uno pase, es busqueda sobre ruido disfrazada de mejora.

ASIMETRIA DELIBERADA
--------------------
Para declarar GANADOR se usa el umbral corregido. Para declarar PERDEDOR, el
sin corregir. No es descuido: equivocarse al ascender cuesta dinero en cada
operacion subsiguiente; equivocarse al retirar solo cuesta dejar de operar algo
que quiza funcionaba, y existe `reopen()`.

ESTADOS
-------
EXPLORACION  se opera a tamano reducido (0.25x por defecto). El objetivo es
             comprar informacion, no ganar dinero. Es tambien la respuesta a la
             circularidad "no puedo operar sin evidencia / no tengo evidencia
             sin operar": se opera, pero barato.
PRODUCCION   veredicto GANADOR vigente. Tamano completo.
RETIRADO     no se opera.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional, Sequence

from app.data.repository import Repository, repository as default_repository
from app.data.schemas import (
    ExecutionState, MarketRegime, SetupKey, SetupRecord, SetupState,
    SetupVerdict, TradeResult,
)
from app.stats.core import (
    benjamini_hochberg, binomial_pvalue_upper, breakeven_winrate,
    geometric_checkpoints, summarize_binomial, wilson_interval, z_from_alpha,
)

logger = logging.getLogger(__name__)

#: Suelo absoluto del minimo de observaciones. No es negociable por config.
HARD_MIN_OBSERVATIONS = 30


@dataclass
class EvaluatorConfig:
    # n minimo para emitir un veredicto que no sea INSUFICIENTE.
    min_observations: int = 200
    # n minimo para que el gate de edge empiece a aplicar la cota de Wilson.
    # Por debajo el setup esta en EXPLORACION y se opera reducido: se esta
    # comprando la muestra, no afirmando un edge.
    exploration_min_observations: int = 30
    alpha_winner: float = 0.05       # se corrige por miradas Y por comparaciones
    alpha_loser: float = 0.05        # se corrige solo por miradas
    checkpoint_factor: int = 2       # 200, 400, 800...
    max_reopens: int = 2             # reaperturas de un setup RETIRADO
    max_variants_per_family: int = 5
    exploration_stake_multiplier: float = 0.25
    production_stake_multiplier: float = 1.0
    # Observaciones OPERADAS (no sombra) necesarias para que un setup en
    # PRODUCCION alcance el tamano completo. Empieza en
    # `production_ramp_start` y sube linealmente hasta 1.0.
    #
    # POR QUE: un setup puede acreditar edge con observaciones en sombra, que
    # miden calidad de senal pero no riesgo de ejecucion (orden rechazada,
    # payout que cambio, saldo insuficiente). Escalar a tamano completo en cuanto
    # la estadistica de sombra lo dice seria confiar en una medicion que no
    # incluye como se ejecuta de verdad. La rampa hace que el dinero real
    # acompanne a la evidencia real.
    production_ramp_traded: int = 50
    production_ramp_start: float = 0.5
    # Ventana reciente para detectar DEGRADACION: un setup que fue GANADOR y
    # deja de serlo debe volver a EXPLORACION, no quedarse en PRODUCCION para
    # siempre con el veredicto de hace 2000 operaciones.
    degrade_window: int = 150
    payout_floor: float = 0.70       # por debajo el break-even es inalcanzable
    # Margen exigido POR ENCIMA del break-even para declarar GANADOR. Debe ser
    # EL MISMO que usa `EdgeValidatorAgent.safety_margin` (viene de
    # `config.backtest_safety_margin`). Si no lo es, el evaluador asciende un
    # setup a PRODUCCION y el validador de edge le bloquea todas las
    # operaciones: un deadlock donde el sistema "tiene edge probado" y a la vez
    # no puede operar. Un solo criterio, un solo sitio donde se decide.
    safety_margin: float = 0.03

    def __post_init__(self):
        if self.min_observations < HARD_MIN_OBSERVATIONS:
            logger.warning(
                "min_observations=%s por debajo del suelo duro %s: se fuerza",
                self.min_observations, HARD_MIN_OBSERVATIONS,
            )
            self.min_observations = HARD_MIN_OBSERVATIONS
        if self.exploration_min_observations > self.min_observations:
            self.exploration_min_observations = self.min_observations

    @classmethod
    def from_app_config(cls) -> "EvaluatorConfig":
        """Construye la config tomando el margen de `app.config`.

        Es la garantia de que evaluador y validador de edge usan EL MISMO
        umbral: los dos leen `config.backtest_safety_margin`.
        """
        from app.config import config as app_config
        return cls(safety_margin=app_config.backtest_safety_margin,
                   payout_floor=app_config.backtest_min_payout - 0.10)


class SetupEvaluator:
    """Ciclo de vida estadistico de cada setup.

    Un setup es (activo, estrategia, direccion, regimen, expiracion). No la
    estrategia entera: `sr_bounce` puede ser GANADOR en EURUSD-OTC con M15 en
    tendencia y expiracion 300s, y PERDEDOR en BTC-OTC en rango con 60s.
    Promover o retirar estrategias completas es la granularidad equivocada, y es
    la que hace que un motor de mejora tire el edge de un contexto bueno junto
    al ruido de uno malo.
    """

    def __init__(self, config: Optional[EvaluatorConfig] = None,
                 repository: Optional[Repository] = None,
                 persist: bool = True):
        self.cfg = config or EvaluatorConfig()
        self.repo = repository or default_repository
        self.persist = persist
        self._cache: dict[str, SetupRecord] = {}
        self._params: dict[str, dict] = {}
        self._family_variants: dict[str, int] = {}
        # Historial reciente por setup, para la deteccion de degradacion.
        self._recent: dict[str, list[bool]] = {}
        if persist:
            # migrate() es idempotente (CREATE TABLE IF NOT EXISTS). Sin esta
            # llamada, construir el evaluador contra una BD recien creada hacia
            # que cada upsert fallara con "no such table: setups" y el estado se
            # perdiera en silencio al reiniciar.
            try:
                self.repo.migrate()
            except Exception as exc:                      # noqa: BLE001
                logger.warning("migracion de esquema fallo: %s", exc)
            self._load()

    # ── carga / persistencia ──────────────────────────────────────────────

    def _load(self):
        try:
            for rec in self.repo.list_setups(limit=100_000):
                self._cache[rec.key.slug] = rec
        except Exception as exc:                          # noqa: BLE001
            logger.warning("no se pudieron cargar los setups: %s", exc)

    def _save(self, rec: SetupRecord):
        self._cache[rec.key.slug] = rec
        if self.persist:
            try:
                self.repo.upsert_setup(rec, self._params.get(rec.key.slug))
            except Exception as exc:                      # noqa: BLE001
                logger.warning("no se pudo persistir el setup %s: %s", rec.key.slug, exc)

    # ── lectura ───────────────────────────────────────────────────────────

    def current(self, key: SetupKey) -> SetupRecord:
        """Estado vigente del setup. Si no existe, se crea en EXPLORACION."""
        slug = key.slug
        rec = self._cache.get(slug)
        if rec is None:
            rec = SetupRecord(
                key=key,
                state=SetupState.EXPLORACION,
                verdict=SetupVerdict.INSUFICIENTE,
                avg_payout=0.85,
                break_even=breakeven_winrate(0.85),
                next_checkpoint=self.cfg.min_observations,
                stake_multiplier=self.cfg.exploration_stake_multiplier,
                updated_at=datetime.utcnow(),
            )
            self._cache[slug] = rec
        return rec

    def is_operable(self, key: SetupKey) -> bool:
        return self.current(key).state != SetupState.RETIRADO

    def stake_multiplier(self, key: SetupKey) -> float:
        return self.current(key).stake_multiplier

    # ── ingestion de resultados ───────────────────────────────────────────

    def ingest(self, trades: Iterable[TradeResult]) -> list[SetupRecord]:
        """Consume resultados cerrados y reevalua SOLO en los checkpoints.

        Filtra por `trade.is_evidence`: un trade resuelto contra el simulador no
        cuenta. Si contara, el motor ascenderia setups a PRODUCCION basandose en
        ruido sintetico y la "mejora continua" seria autoficcion.
        """
        touched: dict[str, SetupRecord] = {}
        for trade in trades:
            if trade.execution_state not in (ExecutionState.WON, ExecutionState.LOST):
                continue
            slug = (trade.features or {}).get("setup_slug")
            key = self._key_from_trade(trade)
            if slug and slug != key.slug:
                # El slug registrado manda: lleva el expiry/regimen con los que
                # se abrio la operacion, que pueden diferir de los del trade.
                try:
                    key = SetupKey.from_slug(slug)
                except (ValueError, KeyError):
                    pass
            rec = self.current(key)
            won = trade.execution_state == ExecutionState.WON
            rec.n += 1
            if not (trade.features or {}).get("shadow"):
                # Solo las observaciones con dinero puesto cuentan aqui. Las
                # sombras miden calidad de senal, no PnL realizado.
                rec.n_traded += 1
            rec.wins += 1 if won else 0
            payout = trade.payout or rec.avg_payout or 0.85
            rec.avg_payout = round(
                ((rec.avg_payout or payout) * (rec.n - 1) + payout) / rec.n, 4
            ) if rec.n > 1 else payout
            rec.break_even = breakeven_winrate(rec.avg_payout or payout)

            recent = self._recent.setdefault(key.slug, [])
            recent.append(won)
            if len(recent) > self.cfg.degrade_window * 2:
                del recent[:-self.cfg.degrade_window]

            touched[key.slug] = rec

        decided: list[SetupRecord] = []
        for slug, rec in touched.items():
            if self._is_checkpoint(rec):
                self.reevaluate(rec)
                decided.append(rec)
            else:
                self._save(rec)
        return decided

    def _key_from_trade(self, trade: TradeResult) -> SetupKey:
        return SetupKey(
            asset=trade.asset,
            strategy=trade.strategy or "",
            direction=trade.direction,
            market_regime=trade.market_regime or MarketRegime.UNKNOWN,
            expiry=int(trade.expiry or 0),
        )

    def _is_checkpoint(self, rec: SetupRecord) -> bool:
        """Solo se decide en 200, 400, 800... (o al cruzar el minimo por primera vez)."""
        if rec.n < self.cfg.exploration_min_observations:
            return False
        if rec.next_checkpoint <= 0:
            return rec.n >= self.cfg.min_observations
        return rec.n >= rec.next_checkpoint

    # ── veredicto ─────────────────────────────────────────────────────────

    def reevaluate(self, rec: SetupRecord,
                   family_size: int = 1) -> SetupRecord:
        """Reevalua un setup y actualiza su estado. Devuelve el registro.

        `family_size` es cuantos setups se estan evaluando a la vez; se usa
        para la correccion por comparaciones multiples al ASCENDER.
        """
        rec.looks += 1
        payout = rec.avg_payout or 0.85
        be = breakeven_winrate(payout)
        summary = summarize_binomial(rec.wins, rec.n, payout)
        rec.win_rate = summary["win_rate"]
        rec.win_rate_lower = summary["win_rate_lower"]
        rec.win_rate_upper = summary["win_rate_upper"]
        rec.expectancy = summary["expectancy"]
        rec.expectancy_lower = summary["expectancy_lower"]
        rec.break_even = be
        rec.updated_at = datetime.utcnow()

        # ── 1. muestra insuficiente: no se concluye nada ──────────────────
        if rec.n < self.cfg.min_observations:
            rec.verdict = SetupVerdict.INSUFICIENTE
            if rec.state == SetupState.PRODUCCION:
                # Perdio la muestra (degradacion): vuelve a exploracion.
                rec.state = SetupState.EXPLORACION
                rec.stake_multiplier = self.cfg.exploration_stake_multiplier
            elif rec.state == SetupState.EXPLORACION:
                rec.stake_multiplier = self.cfg.exploration_stake_multiplier
            # RETIRADO no se toca: la retirada es permanente salvo reopen().
            rec.next_checkpoint = self._next_checkpoint(rec.n)
            self._save(rec)
            return rec

        # ── 2. alpha penalizado por miradas repetidas ─────────────────────

        alpha_win = self.cfg.alpha_winner / max(1, rec.looks)
        alpha_lose = self.cfg.alpha_loser / max(1, rec.looks)
        # Y por comparaciones multiples dentro de la familia (solo al ascender).
        alpha_win_family = alpha_win / max(1, family_size)

        z_win = z_from_alpha(alpha_win_family / 2.0)
        z_lose = z_from_alpha(alpha_lose / 2.0)

        lo_win, _ = wilson_interval(rec.wins, rec.n, z_win)
        _, hi_lose = wilson_interval(rec.wins, rec.n, z_lose)

        # GANADOR exige la cota inferior de Wilson por encima del break-even
        # MAS el margen de seguridad. El margen no es timidez: el payout puede
        # bajar sin aviso (los brokers OTC lo mueven), y un edge de 0.4 puntos
        # sobre el break-even desaparece con un cambio de payout de medio punto.
        threshold = (be + self.cfg.safety_margin) if be is not None else None
        winner = (lo_win is not None and threshold is not None
                  and lo_win > threshold)
        loser = hi_lose is not None and be is not None and hi_lose < be

        if winner:
            rec.verdict = SetupVerdict.GANADOR
            rec.state = SetupState.PRODUCCION
            rec.stake_multiplier = self._production_multiplier(rec)
        elif loser:
            rec.verdict = SetupVerdict.PERDEDOR
            rec.state = SetupState.RETIRADO
            rec.stake_multiplier = 0.0
            logger.info("setup %s RETIRADO: WR=%.1f%% IC_sup=%.1f%% < break-even=%.2f%% (n=%d)",
                        rec.key.slug, (rec.win_rate or 0) * 100, hi_lose * 100,
                        be * 100, rec.n)
        else:
            rec.verdict = SetupVerdict.RUIDO
            logger.debug("setup %s RUIDO: IC_inf=%.4f <= umbral=%.4f (n=%d)",
                         rec.key.slug, lo_win or 0, threshold or 0, rec.n)
            if rec.state == SetupState.PRODUCCION:
                # Era GANADOR y ya no se sostiene: se degrada, no se mantiene.
                rec.state = SetupState.EXPLORACION
                rec.stake_multiplier = self.cfg.exploration_stake_multiplier
                logger.info("setup %s degradado a EXPLORACION (veredicto RUIDO, n=%d)",
                            rec.key.slug, rec.n)
            else:
                rec.stake_multiplier = self.cfg.exploration_stake_multiplier

        # ── 3. suelo de payout: filtro de EXPLORACION, no veto absoluto ───
        # Con payout 0.65 el break-even es 60.6%: el margen de error es finisimo
        # y el broker puede bajar el payout en cualquier momento. Pero un setup
        # que ya DEMOSTRO edge con ese payout (75% de aciertos -> expectancy
        # +0.24 por unidad) es rentable y retirarlo seria tirar dinero por una
        # politica. La version anterior de este modulo lo retiraba siempre, y
        # estaba mal: el suelo sirve para no gastar presupuesto de exploracion
        # en instrumentos inviables, no para anular un GANADOR probado.
        if payout < self.cfg.payout_floor and rec.state != SetupState.PRODUCCION:
            rec.verdict = SetupVerdict.PERDEDOR
            rec.state = SetupState.RETIRADO
            rec.stake_multiplier = 0.0
            logger.info(
                "setup %s retirado por payout %.2f < %.2f (break-even %.1f%%): "
                "no se gasta exploracion en instrumentos con margen tan fino",
                rec.key.slug, payout, self.cfg.payout_floor, (be or 0) * 100,
            )
        elif payout < self.cfg.payout_floor:
            logger.warning(
                "setup %s en PRODUCCION con payout %.2f bajo el suelo %.2f: se "
                "mantiene porque el edge esta probado, pero el margen es fino",
                rec.key.slug, payout, self.cfg.payout_floor,
            )

        rec.next_checkpoint = self._next_checkpoint(rec.n)
        self._save(rec)
        return rec

    def _production_multiplier(self, rec: SetupRecord) -> float:
        """Tamano en PRODUCCION, con rampa segun observaciones OPERADAS.

        Con `n_traded=0` (edge acreditado solo por sombras) se opera a
        `production_ramp_start` (0.5x). Al llegar a `production_ramp_traded`
        (50) se opera a 1.0x. Lineal entre medias.
        """
        lo = self.cfg.production_ramp_start
        hi = self.cfg.production_stake_multiplier
        need = max(1, self.cfg.production_ramp_traded)
        if rec.n_traded >= need:
            return hi
        progress = min(1.0, max(0.0, rec.n_traded / need))
        return round(lo + (hi - lo) * progress, 4)

    def _next_checkpoint(self, n: int) -> int:
        """Siguiente n geometrico en el que se volvera a decidir."""
        for cp in geometric_checkpoints(self.cfg.min_observations,
                                        self.cfg.checkpoint_factor,
                                        max_n=10_000_000):
            if cp > n:
                return cp
        return n * self.cfg.checkpoint_factor

    def reevaluate_all(self, family_size: Optional[int] = None) -> dict:
        """Reevalua toda la familia de setups con correccion multiple.

        Se usa desde el motor de mejora y desde el CLI (`evaluate`). Al evaluar
        todo junto se puede aplicar Bonferroni/BH sobre la familia completa,
        que es lo unico que evita ascender al mejor de N ruidos.
        """
        records = [r for r in self._cache.values()
                   if r.n >= self.cfg.exploration_min_observations]
        size = family_size or max(1, len(records))
        counts = {v.value: 0 for v in SetupVerdict}
        for rec in records:
            self.reevaluate(rec, family_size=size)
            counts[rec.verdict.value] += 1

        # Benjamini-Hochberg sobre TODA la familia a la vez. `reevaluate` ya
        # aplica la correccion al ASCENDER (caro equivocarse: se opera a tamano
        # completo); aqui se calcula el q-value de cada setup contra su
        # break-even para que el motor de mejora vea la familia COMPLETA y no
        # setup a setup. Sin esa vista global, "el mejor de 40 variantes"
        # parece un descubrimiento y es aritmetica del ruido.
        pvalues = []
        for rec in records:
            be = rec.break_even or breakeven_winrate(rec.avg_payout or 0.85)
            pvalues.append(
                binomial_pvalue_upper(rec.wins, rec.n, be) if be and rec.n else None
            )
        bh = benjamini_hochberg(pvalues, alpha=self.cfg.alpha_loser)
        for rec, row in zip(records, bh):
            if row.get("q") is not None:
                self._params.setdefault(rec.key.slug, {})["q_value_bh"] = round(row["q"], 6)
                self._save(rec)

        return {
            "evaluated": len(records),
            "family_size_used_for_correction": size,
            "verdicts": counts,
            "states": {st.value: sum(1 for r in self._cache.values() if r.state == st)
                       for st in SetupState},
            # Cuantos sobreviven a la correccion por comparaciones multiples.
            # Es la cifra que debe mirar el motor de mejora antes de creerse nada.
            "significant_after_bh": sum(1 for row in bh if row["rejected"]),
            "bh": [
                {"slug": rec.key.slug, "n": rec.n, "wins": rec.wins,
                 "p": row["p"], "q": row["q"], "significant": row["rejected"]}
                for rec, row in zip(records, bh)
            ],
        }

    # ── reapertura y variantes ────────────────────────────────────────────

    def reopen(self, key: SetupKey) -> tuple[bool, str]:
        """Reabre un setup RETIRADO. Topado a `max_reopens`.

        Sin tope, "retirada permanente" es ficcion: basta con reabrir hasta que
        una racha de suerte lo vuelva a ascender. Con tope, el sistema agota las
        oportunidades y el setup queda fuera de verdad.
        """
        rec = self.current(key)
        if rec.state != SetupState.RETIRADO:
            return False, f"el setup no esta retirado (estado={rec.state.value})"
        if rec.reopened >= self.cfg.max_reopens:
            return False, (f"reaperturas agotadas ({rec.reopened}/"
                           f"{self.cfg.max_reopens}): retirada definitiva")
        rec.reopened += 1
        rec.state = SetupState.EXPLORACION
        rec.verdict = SetupVerdict.INSUFICIENTE
        rec.stake_multiplier = self.cfg.exploration_stake_multiplier
        rec.n = 0
        rec.wins = 0
        rec.looks = 0
        rec.next_checkpoint = self.cfg.min_observations
        rec.updated_at = datetime.utcnow()
        self._recent.pop(key.slug, None)
        self._save(rec)
        return True, f"reabierto ({rec.reopened}/{self.cfg.max_reopens})"

    def register_variant(self, family: str) -> tuple[bool, str]:
        """Registra una variante de parametros de una familia. Topada.

        Es la defensa contra "probar parametros nuevos hasta que uno pase": eso
        no es mejorar, es buscar sobre ruido. Cada variante consume presupuesto.
        """
        used = self._family_variants.get(family, 0)
        if used >= self.cfg.max_variants_per_family:
            return False, (f"variantes agotadas para {family} "
                           f"({used}/{self.cfg.max_variants_per_family})")
        self._family_variants[family] = used + 1
        return True, f"variante {used + 1}/{self.cfg.max_variants_per_family} para {family}"

    # ── informes ──────────────────────────────────────────────────────────

    def report(self, limit: int = 40) -> dict:
        records = sorted(self._cache.values(), key=lambda r: -r.n)[:limit]
        return {
            "config": {
                "min_observations": self.cfg.min_observations,
                "exploration_min_observations": self.cfg.exploration_min_observations,
                "alpha_winner": self.cfg.alpha_winner,
                "alpha_loser": self.cfg.alpha_loser,
                "max_reopens": self.cfg.max_reopens,
                "max_variants_per_family": self.cfg.max_variants_per_family,
                "degrade_window": self.cfg.degrade_window,
                "payout_floor": self.cfg.payout_floor,
            },
            "totals": {
                "setups": len(self._cache),
                "produccion": sum(1 for r in self._cache.values() if r.state == SetupState.PRODUCCION),
                "exploracion": sum(1 for r in self._cache.values() if r.state == SetupState.EXPLORACION),
                "retirado": sum(1 for r in self._cache.values() if r.state == SetupState.RETIRADO),
                "evidence_trades": sum(r.n for r in self._cache.values()),
            },
            "setups": [
                {
                    "slug": r.key.slug, "n": r.n, "wins": r.wins,
                    "win_rate": r.win_rate, "win_rate_lower": r.win_rate_lower,
                    "win_rate_upper": r.win_rate_upper,
                    "break_even": r.break_even, "avg_payout": r.avg_payout,
                    "expectancy": r.expectancy, "expectancy_lower": r.expectancy_lower,
                    "state": r.state.value, "verdict": r.verdict.value,
                    "looks": r.looks, "next_checkpoint": r.next_checkpoint,
                    "reopened": r.reopened, "n_traded": r.n_traded,
                    "stake_multiplier": r.stake_multiplier,
                }
                for r in records
            ],
        }
