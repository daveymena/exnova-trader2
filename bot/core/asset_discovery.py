# -*- coding: utf-8 -*-
"""
Descubrimiento de activos operables preguntando al BROKER.

Sustituye a las listas fijas de bot/config_assets.py, que son la razon por la
que el bot solo opera sinteticos: `get_activos_activos()` devuelve siempre los
107 activos -OTC y solo anade mercado real entre las 08:00 y las 12:00 hora de
Colombia, un horario inventado que no corresponde al del mercado subyacente.
La API ya expone `get_all_open_time()`, pero no habia ni una sola llamada a esa
funcion en todo el proyecto.

Aqui se consulta que esta realmente abierto, de que tipo es y con que payout,
y se prioriza el mercado real sobre el sintetico.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Tipos de opcion binaria, en orden de preferencia para expiraciones cortas.
#   turbo   -> 1-5 min, es lo que necesita este bot
#   binary  -> 15 min en adelante, a horas fijas
#   digital -> strike variable; payout distinto y ejecucion por otra ruta
BINARY_KINDS = ("turbo", "binary", "digital")

# Cuanto vale una consulta antes de refrescarla. El broker abre y cierra
# activos a lo largo del dia, asi que no puede cachearse indefinidamente.
CACHE_TTL_SECONDS = 300


def is_otc(name: str) -> bool:
    """True si el activo es un feed sintetico generado por el broker."""
    upper = name.upper()
    return "-OTC" in upper or upper.endswith("_OTC")


@dataclass(frozen=True)
class TradableAsset:
    name: str
    kind: str                 # turbo / binary / digital
    payout: float | None      # 0.84 = ganas 0.84 por cada 1 arriesgado
    synthetic: bool

    @property
    def breakeven_winrate(self) -> float | None:
        """Winrate necesario solo para no perder dinero con este payout."""
        if not self.payout:
            return None
        return 1.0 / (1.0 + self.payout)

    def __str__(self) -> str:
        tipo = "OTC-sintetico" if self.synthetic else "mercado-real"
        if self.payout:
            return (f"{self.name} [{self.kind}/{tipo}] payout={self.payout:.2f} "
                    f"be={100 * self.breakeven_winrate:.1f}%")
        return f"{self.name} [{self.kind}/{tipo}] payout=n/d"


class AssetDiscovery:
    """Consulta y cachea los activos realmente operables en el broker."""

    def __init__(self, api, cache_ttl: int = CACHE_TTL_SECONDS):
        self.api = api
        self.cache_ttl = cache_ttl
        self._cache: list[TradableAsset] = []
        self._cached_at: float = 0.0

    # -- consulta ---------------------------------------------------------

    def _fetch(self) -> list[TradableAsset]:
        try:
            open_time = self.api.get_all_open_time()
        except Exception as e:
            logger.error("No se pudo consultar get_all_open_time(): %s", e)
            return []

        try:
            profits = self.api.get_all_profit()
        except Exception as e:
            logger.warning("No se pudo consultar payouts: %s", e)
            profits = {}

        assets: list[TradableAsset] = []
        for kind in BINARY_KINDS:
            for name, info in (open_time.get(kind) or {}).items():
                if not isinstance(info, dict) or not info.get("open"):
                    continue

                payout = None
                entry = profits.get(name)
                if isinstance(entry, dict):
                    raw = entry.get(kind)
                    if isinstance(raw, (int, float)) and raw > 0:
                        payout = float(raw)

                assets.append(TradableAsset(
                    name=name,
                    kind=kind,
                    payout=payout,
                    synthetic=is_otc(name),
                ))
        return assets

    def all_open(self, force: bool = False) -> list[TradableAsset]:
        if force or not self._cache or (time.time() - self._cached_at) > self.cache_ttl:
            fetched = self._fetch()
            if fetched:
                self._cache = fetched
                self._cached_at = time.time()
        return list(self._cache)

    # -- seleccion --------------------------------------------------------

    def tradable(
        self,
        min_payout: float = 0.75,
        allow_synthetic: bool = True,
        kinds: tuple[str, ...] = ("turbo",),
        force: bool = False,
    ) -> list[TradableAsset]:
        """
        Activos operables ahora, ordenados por payout descendente.

        `min_payout` no es cosmetico: con payout 0.75 el break-even sube al
        57.1%, frente al 54.4% de un payout de 0.838. Aceptar payouts bajos
        sube la barrera de acierto que hay que superar.
        """
        candidates = [
            a for a in self.all_open(force=force)
            if a.kind in kinds
            and (allow_synthetic or not a.synthetic)
            and (a.payout is None or a.payout >= min_payout)
        ]
        # Mercado real primero, y dentro de cada grupo el mejor payout.
        candidates.sort(key=lambda a: (a.synthetic, -(a.payout or 0.0)))
        return candidates

    def real_market(self, min_payout: float = 0.75, **kw) -> list[TradableAsset]:
        """Solo activos de mercado real, excluyendo sinteticos del broker."""
        return self.tradable(min_payout=min_payout, allow_synthetic=False, **kw)

    def summary(self) -> str:
        assets = self.all_open()
        if not assets:
            return "Sin datos del broker (get_all_open_time() no devolvio nada)"

        lines = []
        for kind in BINARY_KINDS:
            of_kind = [a for a in assets if a.kind == kind]
            if not of_kind:
                continue
            real = sum(1 for a in of_kind if not a.synthetic)
            lines.append(f"{kind}: {len(of_kind)} abiertos ({real} reales, "
                         f"{len(of_kind) - real} OTC)")
        return " | ".join(lines) if lines else "Ningun activo abierto"
