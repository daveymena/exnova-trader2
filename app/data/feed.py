# -*- coding: utf-8 -*-
"""Capa de mercado: reloj, feeds y la invariante de causalidad.

LA INVARIANTE
-------------
Ningun feed devuelve una vela que no este CERRADA respecto a `now()`. Se aplica
en un unico sitio (`MarketFeed._visible`) y vale para los tres feeds por igual.

Por que importa tanto: el backtester anterior de `app/research/backtester.py`
generaba la senal con la vela `i` y decidia si ganaba con ESA MISMA vela
(`current_candle.is_bullish`). Es decir, el resultado del trade era una de las
entradas de la senal. Eso no es un backtest optimista, es un backtest que no
mide nada: reporta el win rate de "la vela en la que mi estrategia ve algo",
que por construccion esta sesgado hacia la direccion que la estrategia acaba
de predecir. Punto 10 de `app/NOT_PRODUCTION_READY.md`.

Al obligar a que toda lectura pase por `feed.candles(...)`, el motor de trading
y el backtester se vuelven EL MISMO CODIGO. Ya no hay dos implementaciones que
puedan divergir (que es como se cuela el look-ahead: en la copia). El backtest
es simplemente el motor corriendo sobre un `ReplayFeed` con el reloj virtual
avanzado a toda velocidad.

RELOJ
-----
`now()` lo da el feed, no `datetime.utcnow()`. Sin reloj virtual no se puede
reproducir un historico; con dos relojes distintos (uno en vivo, otro en
backtest) el codigo se bifurca y aparecen bugs que solo existen en uno de los
dos modos.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

from app.data.csv_loader import build_timeframes, load_candles
from app.data.market_sim import MarketSimulator, SimConfig
from app.data.schemas import Candle, DataQuality, DataSource, Timeframe

logger = logging.getLogger(__name__)


class Clock:
    """Reloj. `WallClock` para vivo, `VirtualClock` para replay/backtest."""

    def now(self) -> datetime:
        raise NotImplementedError

    def advance(self, seconds: float) -> None:
        raise NotImplementedError


class WallClock(Clock):
    """Reloj de pared, en UTC naive (convencion del resto del proyecto)."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def advance(self, seconds: float) -> None:
        # El reloj de pared no se adelanta: si algo intenta hacerlo es un bug
        # de quien lo llama, no una operacion silenciosa.
        raise RuntimeError("WallClock no permite advance(): usa VirtualClock")


class VirtualClock(Clock):
    """Reloj virtual determinista. Es lo que hace reproducible un backtest."""

    def __init__(self, start: datetime):
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("el reloj virtual no retrocede")
        self._now = self._now + timedelta(seconds=seconds)

    def set(self, when: datetime) -> None:
        if when < self._now:
            raise ValueError("el reloj virtual no retrocede")
        self._now = when


class MarketFeed(ABC):
    """Interfaz unica de mercado para vivo, replay y simulacion."""

    #: Proveniencia de los precios. Decide si lo derivado es evidencia.
    data_source: DataSource = DataSource.UNKNOWN

    def __init__(self, clock: Optional[Clock] = None):
        self.clock = clock or WallClock()

    def now(self) -> datetime:
        return self.clock.now()

    # ── API que consume el motor ─────────────────────────────────────────

    @abstractmethod
    def assets(self) -> list[str]:
        ...

    @abstractmethod
    def raw_candles(self, asset: str, timeframe: Timeframe,
                    count: int) -> list[Candle]:
        """Velas SIN filtrar por causalidad. Solo lo llama `_visible`."""

    def candles(self, asset: str, timeframe: Timeframe,
                count: int = 100) -> list[Candle]:
        """Velas CERRADAS respecto a `now()`, ordenadas de mas antigua a mas nueva.

        Este es el unico punto por el que el motor ve el mercado. Filtrar aqui
        (y no en cada estrategia) es lo que hace imposible el look-ahead por
        descuido.
        """
        # Se piden velas de sobra en `raw_candles` porque `_visible` descarta
        # las que aun no cerraron; aqui se recorta a `count` para que el
        # contrato sea exactamente "las ultimas `count` velas cerradas".
        visible = self._visible(self.raw_candles(asset, timeframe, count), timeframe)
        return visible[-count:] if len(visible) > count else visible

    def _visible(self, candles: Sequence[Candle], timeframe: Timeframe) -> list[Candle]:
        now = self.now()
        # Una vela abierta en T esta cerrada en T + timeframe. Usar `<= now`
        # sobre open_time dejaria pasar la vela en curso: media vela de futuro.
        cutoff = now - timedelta(seconds=timeframe.value)
        closed = [c for c in candles if c.open_time <= cutoff]
        closed.sort(key=lambda c: c.open_time)
        return closed

    @abstractmethod
    def price_at(self, asset: str, when: datetime) -> Optional[float]:
        """Precio observado en `when`. None si no hay dato (nunca se extrapola)."""

    def last_price(self, asset: str) -> Optional[float]:
        return self.price_at(asset, self.now())

    @abstractmethod
    def payout(self, asset: str, expiry_sec: int) -> float:
        """Payout que el "broker" ofrece para ese activo y expiracion."""

    def advance(self, seconds: float) -> None:
        """Avanza el feed. Solo tiene sentido en simulacion/replay."""
        self.clock.advance(seconds)

    # ── utilidades compartidas ───────────────────────────────────────────

    def candle_set(self, asset: str) -> dict[Timeframe, list[Candle]]:
        """M1/M5/M15 cerradas, listas para el motor multi-temporalidad."""
        return {
            Timeframe.M1: self.candles(asset, Timeframe.M1, 200),
            Timeframe.M5: self.candles(asset, Timeframe.M5, 150),
            Timeframe.M15: self.candles(asset, Timeframe.M15, 120),
        }


# ===========================================================================
# Feed simulado
# ===========================================================================

class SimulatedFeed(MarketFeed):
    """Feed de microestructura sintetica. `data_source=SIMULATOR`.

    Dos modos de reloj:
      * `realtime=True`  -> WallClock; el simulador se pone al dia en cada
        lectura. Es el modo "paper trading en vivo sin broker": sirve para
        dejar el motor corriendo y observar su comportamiento.
      * `realtime=False` -> VirtualClock; se avanza explicitamente. Es el modo
        backtest rapido sobre datos sinteticos.

    En ambos casos los resultados NO son evidencia: `DataSource.SIMULATOR` no
    pasa `EVIDENCE_SQL`, asi que nada de lo que se mida aqui puede ascender un
    setup a PRODUCCION. Ver `app/data/market_sim.py` para los controles
    negativo (`SimConfig.null_market`) y positivo (`SimConfig.positive_control`).
    """

    data_source = DataSource.SIMULATOR

    def __init__(self, asset_names: Sequence[str],
                 config: Optional[SimConfig] = None,
                 warmup_minutes: int = 600,
                 realtime: bool = False,
                 clock: Optional[Clock] = None,
                 payouts: Optional[dict[str, float]] = None):
        if realtime and clock is not None and isinstance(clock, VirtualClock):
            raise ValueError("realtime=True exige WallClock (o ningun reloj)")
        start = (datetime.now(timezone.utc).replace(tzinfo=None)
                 - timedelta(minutes=warmup_minutes)) if realtime \
            else datetime(2026, 1, 5, 0, 0)
        super().__init__(clock or (WallClock() if realtime else VirtualClock(start)))
        self.cfg = config or SimConfig()
        self.realtime = realtime
        self._sims: dict[str, MarketSimulator] = {}
        for i, name in enumerate(asset_names):
            seed = None if self.cfg.seed is None else self.cfg.seed + i
            sub = SimConfig(**{**self.cfg.__dict__, "seed": seed})
            self._sims[name] = MarketSimulator(name, sub, start_time=start)
        self._payouts = payouts or {}
        self._default_payout = 0.85
        if warmup_minutes and not realtime:
            for sim in self._sims.values():
                sim.advance(minutes=warmup_minutes)
            self.clock.advance(warmup_minutes * 60)

    def assets(self) -> list[str]:
        return list(self._sims)

    def sim(self, asset: str) -> MarketSimulator:
        return self._sims[asset]

    def raw_candles(self, asset: str, timeframe: Timeframe, count: int) -> list[Candle]:
        sim = self._sims.get(asset)
        if sim is None:
            return []
        if self.realtime:
            # Poner el generador al dia con el reloj de pared.
            behind = (self.now() - sim.clock).total_seconds()
            if behind > 0:
                sim.advance(seconds=int(behind))
        return sim.candles(timeframe, count + 2)

    def forming_candle(self, asset: str, timeframe: Timeframe) -> Optional[Candle]:
        """Bucket EN CURSO del simulador: open/high/low/ultimo precio."""
        sim = self._sims.get(asset)
        if sim is None:
            return None
        if self.realtime:
            behind = (self.now() - sim.clock).total_seconds()
            if behind > 0:
                sim.advance(seconds=int(behind))
        return sim.forming_candle(timeframe)

    def price_at(self, asset: str, when: datetime) -> Optional[float]:
        sim = self._sims.get(asset)
        if sim is None:
            return None
        if self.realtime:
            behind = (self.now() - sim.clock).total_seconds()
            if behind > 0:
                sim.advance(seconds=int(behind))
        return sim.price_at(when)

    def payout(self, asset: str, expiry_sec: int) -> float:
        return self._payouts.get(asset, self._default_payout)

    def advance(self, seconds: float) -> None:
        if self.realtime:
            raise RuntimeError("SimulatedFeed en realtime no se avanza a mano")
        for sim in self._sims.values():
            sim.advance(seconds=int(seconds))
        self.clock.advance(seconds)

    def snapshot(self) -> dict:
        return {name: sim.snapshot() for name, sim in self._sims.items()}


# ===========================================================================
# Feed de replay sobre historico real (CSV)
# ===========================================================================

class ReplayFeed(MarketFeed):
    """Reproduce historico REAL cargado desde CSV. `data_source=CSV`.

    Es la fuente de evidencia para backtesting: los precios son reales, el
    reloj es virtual y `candles()` solo entrega velas cerradas respecto a ese
    reloj. Un trade abierto en T y con expiracion 180s se liquida contra
    `price_at(T+180s)`, que es el precio real de ese instante -- no contra la
    vela que genero la senal.

    `price_at` interpola linealmente entre los dos M1 que rodean el instante
    pedido. Interpolar es una aproximacion y esta DOCUMENTADA como tal: con
    velas M1 y expiraciones de 60-300s el error es pequeno, pero no es cero, y
    en un instrumento que se liquida por comparacion de un punto exacto
    conviene saberlo. Para expiraciones sub-minuto habria que alimentar ticks.
    """

    data_source = DataSource.CSV

    def __init__(self, data: dict[str, Sequence[Candle]],
                 payouts: Optional[dict[str, float]] = None,
                 default_payout: float = 0.85,
                 start: Optional[datetime] = None,
                 clock: Optional[Clock] = None):
        if not data:
            raise ValueError("ReplayFeed necesita al menos un activo con velas M1")
        self._tf: dict[str, dict[Timeframe, list[Candle]]] = {}
        for asset, m1 in data.items():
            ordered = sorted(m1, key=lambda c: c.open_time)
            self._tf[asset] = build_timeframes(ordered)
        first = min(v[Timeframe.M1][0].open_time for v in self._tf.values()
                    if v.get(Timeframe.M1))
        self._first = start or first
        super().__init__(clock or VirtualClock(self._first))
        self._default_payout = default_payout
        self._payouts = payouts or {}
        self._reports: dict[str, dict] = {}

    @classmethod
    def from_csv(cls, paths: dict[str, str | Path] | Sequence[str | Path],
                 timeframe: Timeframe = Timeframe.M1, **kwargs) -> "ReplayFeed":
        """Construye el feed desde ficheros CSV.

        `paths` puede ser {asset: ruta} o una lista de rutas (el activo se toma
        del nombre del fichero). Los informes de carga quedan en `.load_reports`
        para poder auditar cuantas filas se descartaron y por que.
        """
        if isinstance(paths, dict):
            items = list(paths.items())
        else:
            items = [(Path(p).stem.split(".")[0].upper(), p) for p in paths]
        data: dict[str, list[Candle]] = {}
        reports: dict[str, dict] = {}
        for asset, path in items:
            candles, report = load_candles(path, asset=asset, timeframe=timeframe)
            reports[asset] = report.as_dict()
            if candles:
                data[asset] = candles
            else:
                logger.warning("CSV sin velas utilizables: %s (%s)", path,
                               report.drop_reasons)
        feed = cls(data, **kwargs)
        feed._reports = reports
        return feed

    @property
    def load_reports(self) -> dict[str, dict]:
        return dict(self._reports)

    def assets(self) -> list[str]:
        return list(self._tf)

    def raw_candles(self, asset: str, timeframe: Timeframe, count: int) -> list[Candle]:
        series = self._tf.get(asset, {}).get(timeframe)
        if not series:
            return []
        # Bisecar sobre el reloj virtual y devolver solo lo anterior: cortar
        # por `count` desde el final del fichero entregaria futuro.
        now = self.now()
        hi = _bisect_right(series, now)
        lo = max(0, hi - count)
        return series[lo:hi]

    def price_at(self, asset: str, when: datetime) -> Optional[float]:
        series = self._tf.get(asset, {}).get(Timeframe.M1)
        if not series:
            return None
        idx = _bisect_right(series, when)
        if idx == 0:
            # Antes del primer dato: no hay precio. No se extrapola hacia atras.
            return None
        prev = series[idx - 1]
        if idx >= len(series):
            # Despues del ultimo dato: fuera del historico cargado.
            return None
        nxt = series[idx]
        span = (nxt.open_time - prev.open_time).total_seconds()
        if span <= 0:
            return prev.close
        frac = (when - prev.open_time).total_seconds() / span
        if frac <= 0.0:
            return prev.close
        if frac >= 1.0:
            # `when` cae dentro de la vela siguiente: se usa su apertura como
            # mejor aproximacion disponible sin inventar recorrido intravela.
            return nxt.open
        # Interpolacion lineal entre el cierre de la vela anterior y la
        # apertura de la siguiente. Aproximacion DOCUMENTADA: con M1 y
        # expiraciones de 60-300s el error es pequeno pero no es cero, y una
        # binaria se liquida comparando un punto exacto.
        return prev.close + (nxt.open - prev.close) * frac

    def forming_candle(self, asset: str, timeframe: Timeframe) -> Optional[Candle]:
        """Vela en curso reconstruida con las M1 cerradas dentro del bucket.

        Si el reloj esta justo en el limite del minuto no hay ninguna M1 dentro
        del bucket nuevo y se devuelve None. Ese es el caso normal en un backtest
        con ciclo de 60s, y es tambien el mejor momento para entrar: la vela
        anterior acabo de cerrar y la senal se genero con velas cerradas.
        """
        m1 = self._tf.get(asset, {}).get(Timeframe.M1)
        if not m1:
            return None
        now = self.now()
        epoch = int((now - datetime(1970, 1, 1)).total_seconds())
        start = datetime.utcfromtimestamp(epoch - (epoch % timeframe.value))
        inside = [c for c in m1 if start <= c.open_time < now]
        if not inside:
            return None
        return Candle(
            asset=asset, timeframe=timeframe, open_time=start,
            open=inside[0].open,
            high=max(c.high for c in inside),
            low=min(c.low for c in inside),
            close=inside[-1].close,
            source="replay_forming", quality=DataQuality.NORMAL,
            data_source=inside[-1].data_source,
        )

    def payout(self, asset: str, expiry_sec: int) -> float:
        return self._payouts.get(asset, self._default_payout)

    def advance(self, seconds: float) -> None:
        self.clock.advance(seconds)

    def span(self) -> tuple[Optional[datetime], Optional[datetime]]:
        starts, ends = [], []
        for series in self._tf.values():
            m1 = series.get(Timeframe.M1) or []
            if m1:
                starts.append(m1[0].open_time)
                ends.append(m1[-1].open_time)
        return (min(starts) if starts else None, max(ends) if ends else None)

    def fork(self, start: Optional[datetime] = None) -> "ReplayFeed":
        """Nuevo feed sobre el MISMO historico ya preparado, con otro reloj.

        Existe para el walk-forward: hay que recorrer varias ventanas del mismo
        fichero, y volver a agregar M1->M5/M15/M30/H1 en cada ventana seria
        tirar el tiempo. Se comparte `_tf` (que es de solo lectura) y se crea un
        `VirtualClock` nuevo.

        No es "rebobinar" el reloj existente -- eso violaria la invariante de que
        el reloj virtual nunca retrocede, y ademas dejaria objetos vivos
        apuntando a un instante pasado. Es un feed nuevo.
        """
        feed = ReplayFeed.__new__(ReplayFeed)
        MarketFeed.__init__(feed, VirtualClock(start or self._first))
        feed._tf = self._tf
        feed._first = start or self._first
        feed._default_payout = self._default_payout
        feed._payouts = dict(self._payouts)
        feed._reports = dict(self._reports)
        return feed

    def total_candles(self) -> int:
        return sum(len(s.get(Timeframe.M1) or []) for s in self._tf.values())


def _bisect_right(series: Sequence[Candle], when: datetime) -> int:
    """Primer indice cuyo open_time es > when (busqueda binaria)."""
    lo, hi = 0, len(series)
    while lo < hi:
        mid = (lo + hi) // 2
        if series[mid].open_time <= when:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ===========================================================================
# Feed de broker en vivo
# ===========================================================================

class BrokerFeed(MarketFeed):
    """Envuelve un broker conectado (Exnova). `data_source=BROKER`.

    Es la unica fuente que produce evidencia en vivo. Si el broker no esta
    conectado, `candles()` devuelve [] y el motor NO opera: sin feed real no
    se inventa mercado. Eso ya estaba en `app/main.py::_scan_and_trade` y se
    conserva como contrato del feed.
    """

    data_source = DataSource.BROKER

    def __init__(self, broker, default_payout: float = 0.85):
        super().__init__(WallClock())
        self.broker = broker
        self._default_payout = default_payout

    @property
    def connected(self) -> bool:
        return bool(getattr(self.broker, "connected", False))

    def assets(self) -> list[str]:
        if not self.connected:
            return []
        getter = getattr(self.broker, "get_open_assets", None)
        if not getter:
            return []
        try:
            info = getter(min_profit=70) or []
            return [a["name"] for a in info if isinstance(a, dict) and a.get("name")]
        except Exception as exc:            # noqa: BLE001 - el broker falla a menudo
            logger.warning("get_open_assets fallo: %s", exc)
            return []

    def raw_candles(self, asset: str, timeframe: Timeframe, count: int) -> list[Candle]:
        if not self.connected:
            return []
        getter = getattr(self.broker, "get_candles_as_schema", None)
        if not getter:
            return []
        try:
            candles = getter(asset, timeframe, count + 2) or []
        except Exception as exc:            # noqa: BLE001
            logger.warning("get_candles fallo en %s: %s", asset, exc)
            return []
        for c in candles:
            # Los precios del broker son reales: se marcan explicitamente para
            # que pasen EVIDENCE_SQL. Sin esta linea saldrian UNKNOWN y todo lo
            # operado en vivo quedaria fuera de la estadistica.
            c.data_source = DataSource.BROKER
        return candles

    def price_at(self, asset: str, when: datetime) -> Optional[float]:
        if not self.connected:
            return None
        getter = getattr(self.broker, "get_last_close", None)
        if getter is None:
            return None
        try:
            return getter(asset)
        except Exception as exc:            # noqa: BLE001
            logger.warning("get_last_close fallo en %s: %s", asset, exc)
            return None

    def payout(self, asset: str, expiry_sec: int) -> float:
        getter = getattr(self.broker, "get_payout", None)
        if getter:
            try:
                value = getter(asset, expiry_sec)
                if value and 0 < value < 5:
                    return float(value)
            except Exception as exc:        # noqa: BLE001
                logger.warning("get_payout fallo en %s: %s", asset, exc)
        return self._default_payout
