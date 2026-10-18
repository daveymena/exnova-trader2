# -*- coding: utf-8 -*-
"""Simulador de microestructura OTC para opciones binarias.

PARA QUE SIRVE (y para que NO)
------------------------------
SIRVE para:
  * ejercitar el pipeline completo de punta a punta sin broker: feed -> regime
    -> estrategia -> timing -> edge -> riesgo -> ejecucion -> resolucion ->
    medicion -> motor de mejora;
  * tener un CONTROL NEGATIVO: con `alpha=0.0` (el defecto) el mercado es
    esencialmente impredecible, asi que cualquier estrategia honesta debe dar
    ~50% de aciertos y quedar POR DEBAJO del break-even (54.05% a payout
    0.85). Si un backtest sobre este simulador reporta edge con alpha=0, el
    backtest esta mal, no la estrategia es buena. Es la prueba de que el
    sistema sabe decir "no".
  * tener un CONTROL POSITIVO: con `alpha>0` se inyecta predictibilidad real y
    medible. Sirve para comprobar que el motor de deteccion de edge ENCUENTRA
    el edge cuando existe, y que el walk-forward lo confirma fuera de muestra.

NO SIRVE para:
  * concluir nada sobre rentabilidad real. Todo lo que salga de aqui lleva
    `DataSource.SIMULATOR`, que NO pasa `EVIDENCE_SQL`. Un resultado de
    simulador jamas alimenta al EdgeValidator ni asciende un setup a
    PRODUCCION. Esa separacion es estructural, no una convencion: es lo que
    impide que el sistema se autoconvenza con datos inventados.

QUE MODELIZA
------------
Los feeds OTC de fin de semana no son el mercado interbancario: los genera el
propio broker, que controla el feed, el payout y la liquidacion, y cuyos
precios no pueden verificarse contra ningun mercado externo. Eso tiene firma
estadistica propia, y un simulador que no la reproduzca haria que las
estrategias se probaran contra un mercado que no se parece al real:

  1. Regimenes con persistencia (Markov): tendencia alcista/bajista, rango y
     alta volatilidad. No se sortea por vela.
  2. Clustering de volatilidad (OU sobre log-vol): los movimientos grandes van
     juntos. Es lo que hace que ATR y los percentiles de volatilidad signifiquen
     algo.
  3. Barridos de liquidez / stop-hunt: mecha larga que atraviesa el swing
     high/low reciente y cierre de vuelta dentro del rango. Es el patron mas
     caracteristico de OTC y el que mas estrategias de "breakout" ingenuas
     destruye.
  4. Spread bid/ask asimetrico: el precio al que liquidas no es el mid.
  5. Eventos de calidad de datos: vela stale (close==open), duplicada y gaps.
     Un sistema que no los tolera se cae en produccion.
  6. Estacionalidad por sesion: volumen/volatilidad segun hora UTC.

TICKS, NO VELAS
---------------
Se generan ticks de 1 segundo y las velas se agregan despues. Es importante:
una binaria de 180s se liquida contra el precio de un INSTANTE concreto, no
contra el cierre de la vela siguiente. Generar velas y resolver con ellas
introduce exactamente el look-ahead que se corrigio en el backtester.
"""
from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from app.data.schemas import Candle, DataQuality, DataSource, Timeframe

REGIMES = ("trend_up", "trend_down", "range", "high_vol")

# Probabilidad de permanecer en el mismo regime. 0.98 por tick de regime
# (evaluado cada 60s) da una duracion media de ~50 minutos por regime: lo
# bastante largo para que una estrategia de tendencia tenga algo que seguir,
# lo bastante corto para que un backtest vea los cuatro.
REGIME_PERSISTENCE = 0.985

_REGIME_TRANSITIONS = {
    "trend_up":   {"trend_up": REGIME_PERSISTENCE, "range": 0.008, "trend_down": 0.003, "high_vol": 0.004},
    "trend_down": {"trend_down": REGIME_PERSISTENCE, "range": 0.008, "trend_up": 0.003, "high_vol": 0.004},
    "range":      {"range": REGIME_PERSISTENCE, "trend_up": 0.005, "trend_down": 0.005, "high_vol": 0.005},
    "high_vol":   {"high_vol": 0.97, "range": 0.015, "trend_up": 0.0075, "trend_down": 0.0075},
}

# Drift por minuto (en fraccion del precio) segun regime.
_REGIME_DRIFT = {"trend_up": 1.0, "trend_down": -1.0, "range": 0.0, "high_vol": 0.0}
# Volatilidad base por minuto segun regime.
_REGIME_VOL = {"trend_up": 1.0, "trend_down": 1.0, "range": 0.75, "high_vol": 2.2}


@dataclass
class SimConfig:
    """Parametros del generador. Todo determinista bajo `seed`."""
    start_price: float = 1.08500
    # Volatilidad anualizada aparente -> por minuto. 0.10 anual en FX da
    # movimientos M1 del orden de unos pocos pips, que es lo observado.
    base_vol_per_min: float = 0.00035
    vol_of_vol: float = 0.35          # OU sobre log-vol: clustering
    vol_mean_reversion: float = 0.06  # phi del proceso OU
    spread_pips: float = 1.2          # spread bid/ask en "pips" (1e-4)
    sweep_probability: float = 0.02   # P(barrido de liquidez) por minuto
    sweep_wick_mult: float = 2.8      # cuan lejos atraviesa el nivel
    gap_probability: float = 0.004    # P(gap) por minuto
    gap_size_mult: float = 6.0
    stale_probability: float = 0.006  # P(vela stale: close==open) por minuto
    duplicate_probability: float = 0.004

    # ── CONTROL DE EDGE INYECTADO ────────────────────────────────────────
    # alpha=0.0 -> el siguiente movimiento NO es predecible a partir del
    # historico. Es el defecto deliberado: el simulador no debe regalar edge.
    # alpha>0 -> se inyecta un factor de momentum latente con peso `alpha`,
    # de modo que una estrategia de continuacion de tendencia PUEDE captarlo.
    # Se usa como control positivo del motor de deteccion, nunca como
    # demostracion de rentabilidad.
    # `alpha` es la relacion senal/ruido del siguiente minuto, en unidades de
    # volatilidad: alpha=0.25 da ~60% de acierto direccional teorico sobre M1.
    # Es MUCHO mas de lo que existe en un mercado real; por eso el defecto es 0.
    alpha: float = 0.0
    alpha_decay: float = 0.82         # persistencia del factor latente

    # Escala del drift aportado por el REGIMEN (tendencia alcista/bajista).
    # 0.0 = martingala pura: sin ninguna deriva predecible. Con el valor por
    # defecto hay tendencias visibles -- como en un mercado real -- pero el
    # SNR por minuto es bajo. Ponerlo a 0.0 es lo que convierte al generador
    # en un CONTROL NEGATIVO de verdad (ver `SimConfig.null_market`).
    regime_drift_scale: float = 0.55

    session_effect: bool = True       # estacionalidad por hora UTC
    seed: Optional[int] = None
    tick_seconds: int = 1
    max_ticks: int = 400_000          # ~4.6 dias de ticks de 1s

    @classmethod
    def null_market(cls, seed: Optional[int] = None) -> "SimConfig":
        """CONTROL NEGATIVO: martingala pura, cero estructura explotable.

        Sin drift de regimen, sin senal latente y sin barridos direccionales.
        La precision direccional teorica de CUALQUIER estrategia aqui es 50%,
        y el break-even a payout 0.85 es 54.05%: por construccion, todo
        sistema debe PERDER. Si un backtest sobre esta configuracion reporta
        edge, el backtest tiene look-ahead o el medidor esta mal. Es la prueba
        de que el sistema sabe decir "no", y deberia correr en CI.
        """
        return cls(seed=seed, alpha=0.0, regime_drift_scale=0.0)

    @classmethod
    def positive_control(cls, alpha: float = 0.30,
                         seed: Optional[int] = None) -> "SimConfig":
        """CONTROL POSITIVO: senal predecible inyectada a proposito.

        Sirve para comprobar que el motor de deteccion de edge ENCUENTRA el
        edge cuando existe, y que el walk-forward lo confirma fuera de muestra.
        Un detector que solo sabe decir "no hay edge" es tan inutil como uno
        que solo sabe decir "si".
        """
        return cls(seed=seed, alpha=alpha, regime_drift_scale=0.55)


# Volatilidad relativa por hora UTC (sesion asiatica baja, solape Londres/NY alta).
_SESSION_VOL = {
    0: 0.75, 1: 0.70, 2: 0.68, 3: 0.70, 4: 0.75, 5: 0.85, 6: 0.95, 7: 1.10,
    8: 1.25, 9: 1.30, 10: 1.25, 11: 1.20, 12: 1.15, 13: 1.30, 14: 1.35,
    15: 1.30, 16: 1.20, 17: 1.05, 18: 0.95, 19: 0.90, 20: 0.88, 21: 0.85,
    22: 0.80, 23: 0.77,
}


class MarketSimulator:
    """Generador de ticks con microestructura OTC.

    Uso:
        sim = MarketSimulator("EURUSD-OTC", SimConfig(seed=7))
        sim.advance(minutes=1440)          # un dia de historial
        m1  = sim.candles(Timeframe.M1, 200)
        px  = sim.price_at(datetime.utcnow())
    """

    def __init__(self, asset: str, config: Optional[SimConfig] = None,
                 start_time: Optional[datetime] = None):
        self.asset = asset
        self.cfg = config or SimConfig()
        self._rng = random.Random(self.cfg.seed)
        self._t0 = start_time or datetime.now(timezone.utc).replace(microsecond=0)

        self._price = self.cfg.start_price
        self._logvol = 0.0                 # desvio de log-vol respecto a la base
        self._regime = "range"
        self._latent = 0.0                 # factor de momentum latente (control alpha)
        self._minutes_in_regime = 0

        self._ticks: deque[tuple[datetime, float]] = deque(maxlen=self.cfg.max_ticks)
        self._ticks.append((self._t0, self._price))
        self._clock = self._t0
        self._last_minute = self._floor_minute(self._t0)
        self._sweep_armed: Optional[dict] = None
        self._streak_high: Optional[float] = None
        self._streak_low: Optional[float] = None
        self._recent_minutes: deque[dict] = deque(maxlen=240)
        # Contadores de eventos, para poder AUDITAR el generador: un simulador
        # cuyos barridos nunca disparan produciria un mercado donde las
        # estrategias de breakout parecen rentables, y nadie se enteraria.
        self.events = {"sweeps": 0, "gaps": 0, "stale": 0, "regime_changes": 0}
        self._regime_minutes: dict[str, int] = {r: 0 for r in REGIMES}

        # AGREGACION INCREMENTAL. La version anterior recorria TODOS los ticks
        # (hasta 400k) en cada llamada a `candles()`, y el motor pide M1, M5 y
        # M15 por ciclo: 3 pasadas completas por minuto simulado. Con 1500
        # ciclos eso eran 240 segundos, lo que hace inviable un backtest de
        # varios meses. Aqui cada tick actualiza el bucket en curso de cada
        # temporalidad y, al cambiar de bucket, el anterior se cierra y se
        # encola. `candles()` pasa a ser O(count) en vez de O(ticks).
        self._tf_buckets: dict[Timeframe, dict] = {}
        self._tf_closed: dict[Timeframe, deque] = {
            tf: deque(maxlen=4000) for tf in (Timeframe.M1, Timeframe.M5,
                                              Timeframe.M15, Timeframe.M30, Timeframe.H1)
        }
        for tf in self._tf_closed:
            self._tf_buckets[tf] = {"key": None, "o": 0.0, "h": 0.0, "l": 0.0, "c": 0.0}
        # RNG UNICA para eventos de calidad de datos, consumida en el orden en
        # que los buckets cierran. Es importante que sea una sola y que se use
        # al cerrar: la version anterior derivaba la semilla de `len(closed)`
        # dentro de `candles()`, asi que la MISMA vela podia salir STALE en una
        # llamada y NORMAL en la siguiente. Un feed que cambia de opinion sobre
        # sus propios datos historicos no es reproducible y envenena cualquier
        # backtest que se corra dos veces.
        self._quality_rng = random.Random(None if self.cfg.seed is None
                                          else self.cfg.seed + 9_999_1)

    # ── utilidades ────────────────────────────────────────────────────────

    @staticmethod
    def _floor_minute(dt: datetime) -> datetime:
        return dt.replace(second=0, microsecond=0)

    @property
    def regime(self) -> str:
        return self._regime

    @property
    def clock(self) -> datetime:
        return self._clock

    @property
    def last_price(self) -> float:
        return self._price

    def bid_ask(self) -> tuple[float, float]:
        """Bid/ask alrededor del mid, con el spread configurado."""
        half = self.cfg.spread_pips * 1e-4 / 2.0
        return self._price - half, self._price + half

    # ── generacion ────────────────────────────────────────────────────────

    def advance(self, minutes: int = 1, seconds: Optional[int] = None):
        """Avanza el reloj y genera ticks. `seconds` tiene prioridad."""
        total_seconds = seconds if seconds is not None else minutes * 60
        step = max(1, self.cfg.tick_seconds)
        for _ in range(int(total_seconds / step)):
            self._step(step)

    def _step(self, seconds: int):
        prev_minute = self._last_minute
        self._clock = self._clock + timedelta(seconds=seconds)

        # Cambio de minuto: regimen, eventos y libro de rangos se evaluan aqui.
        new_minute = self._floor_minute(self._clock)
        if new_minute != prev_minute:
            self._roll_minute(new_minute)
            self._last_minute = new_minute

        frac = seconds / 60.0
        vol = self.cfg.base_vol_per_min * math.exp(self._logvol) * math.sqrt(frac)
        if self.cfg.session_effect:
            vol *= _SESSION_VOL.get(self._clock.hour, 1.0)

        drift = (_REGIME_DRIFT[self._regime] * self.cfg.base_vol_per_min
                 * self.cfg.regime_drift_scale * frac)

        # Control de edge inyectado: el factor latente empuja el drift.
        # Con alpha=0 esta linea no aporta nada y el mercado queda sin senal.
        #
        # `_latent` es un AR(1) con innovaciones N(0,1), cuya desviacion
        # estacionaria es 1/sqrt(1-decay^2) (~2.2 con decay=0.88). Si se
        # aplicara crudo, el alpha efectivo seria 2-3 veces el pedido y la
        # serie derivaria un 15% en 12 horas: un "control positivo" que no se
        # parece a ningun mercado. Se normaliza a varianza unitaria para que
        # alpha sea literalmente la relacion senal/ruido por minuto.
        #
        # OJO con la escala temporal. `vol` ya lleva sqrt(frac) porque es la
        # desviacion de UN tick; si el drift predecible se multiplicara por
        # `vol`, al sumar los 60 ticks del minuto el alpha efectivo quedaria
        # multiplicado por sqrt(60) ~= 7.75, y un "alpha=0.15" derivaria el
        # precio un 8% en dos dias. El drift se acumula LINEALMENTE, asi que
        # escala con `frac` igual que el drift de regimen. Con esto `alpha` es
        # literalmente la relacion senal/ruido por minuto: alpha=0.30 implica
        # ~62% de acierto direccional teorico en M1.
        if self.cfg.alpha:
            latent_unit = self._latent * math.sqrt(1.0 - self.cfg.alpha_decay ** 2)
            session = _SESSION_VOL.get(self._clock.hour, 1.0) if self.cfg.session_effect else 1.0
            drift += (self.cfg.alpha * latent_unit * self.cfg.base_vol_per_min
                      * frac * session)

        shock = self._rng.gauss(0.0, vol)
        self._price = max(1e-6, self._price + drift + shock)

        # Barrido de liquidez en curso: empuja el precio a atravesar el nivel.
        if self._sweep_armed is not None:
            self._apply_sweep(seconds)

        self._aggregate_tick()

        # Actualizar la vela del minuto en curso. Sin esto el libro de swing
        # high/low guardaria solo el precio de apertura de cada minuto, y los
        # barridos apuntarian a niveles que no son los maximos/minimos reales.
        if self._recent_minutes:
            cur = self._recent_minutes[-1]
            cur["high"] = max(cur["high"], self._price)
            cur["low"] = min(cur["low"], self._price)
            cur["close"] = self._price

        self._ticks.append((self._clock, self._price))

    def _roll_minute(self, minute: datetime):
        """Transicion de regimen + eventos de calidad + libro de swing."""
        self._minutes_in_regime += 1

        # Markov sobre regimenes.
        table = _REGIME_TRANSITIONS[self._regime]
        r = self._rng.random()
        acc = 0.0
        for name, prob in table.items():
            acc += prob
            if r <= acc:
                if name != self._regime:
                    self._regime = name
                    self._minutes_in_regime = 0
                    self.events["regime_changes"] += 1
                break
        self._regime_minutes[self._regime] = self._regime_minutes.get(self._regime, 0) + 1

        # Proceso OU sobre log-vol, con media 0 -> clustering de volatilidad.
        # vol_t = exp(logvol_t) * base: los choques grandes se agrupan porque
        # logvol es persistente (phi pequeno = reversion lenta), pero vuelve a
        # la base. La desviacion del ruido escala con sqrt(phi) para que la
        # varianza estacionaria sea vol_of_vol^2/2 y no explote.
        phi = self.cfg.vol_mean_reversion
        self._logvol = (self._logvol * (1.0 - phi)
                        + self._rng.gauss(0.0, self.cfg.vol_of_vol * math.sqrt(phi)))

        # Factor latente de momentum (solo tiene efecto si alpha > 0).
        self._latent = self._latent * self.cfg.alpha_decay + self._rng.gauss(0.0, 1.0)

        # Libro de swing highs/lows sobre los ultimos 20 minutos: es lo que
        # barren los sweeps y lo que usan las estrategias de S/R.
        if self._recent_minutes:
            window = list(self._recent_minutes)[-20:]
            self._streak_high = max(m["high"] for m in window)
            self._streak_low = min(m["low"] for m in window)

        # Evento: barrido de liquidez.
        if (self._sweep_armed is None and self._streak_high is not None
                and self._rng.random() < self.cfg.sweep_probability):
            direction = 1 if self._rng.random() < 0.5 else -1
            level = self._streak_high if direction > 0 else self._streak_low
            # Objetivo: un margen mas alla del nivel, proporcional a la
            # volatilidad. Si el margen fuera fijo, en activos caros (BTC-OTC)
            # el barrido no atravesaria nada y en baratos seria un gap enorme.
            target = level + direction * abs(self._price) \
                * self.cfg.base_vol_per_min * self.cfg.sweep_wick_mult
            self._sweep_armed = {
                "direction": direction, "level": level, "target": target,
                "ticks_left": self._rng.randint(8, 25),
                "phase": "out",
            }
            self.events["sweeps"] += 1

        # Evento: gap.
        if self._rng.random() < self.cfg.gap_probability:
            self.events["gaps"] += 1
            sign = 1 if self._rng.random() < 0.5 else -1
            self._price += sign * abs(self._price) * self.cfg.base_vol_per_min \
                * self.cfg.gap_size_mult

        # Se abre el bucket del minuto nuevo. `_step` ira rellenando high/low.
        self._recent_minutes.append(
            {"t": minute, "open": self._price, "high": self._price,
             "low": self._price, "close": self._price}
        )

    def _apply_sweep(self, seconds: int):
        """Fase de ida (atraviesa el nivel) y fase de vuelta (rechazo).

        Es el patron que mas estrategias de breakout ingenuas destruye en OTC:
        el precio perfora el swing high/low reciente, activa los stops y las
        entradas por ruptura, y cierra de vuelta dentro del rango. Un
        simulador sin esto hace que `breakout_direct` parezca rentable.
        """
        s = self._sweep_armed
        if s is None:
            return
        s["ticks_left"] -= 1
        # 'out' empuja a atravesar el nivel; 'back' tira de vuelta hacia dentro.
        pull = 0.22 if s["phase"] == "out" else -0.30
        step = abs(self._price) * self.cfg.base_vol_per_min \
            * math.sqrt(seconds / 60.0) * pull
        self._price = max(1e-6, self._price + s["direction"] * step)
        if s["phase"] == "out" and (
            (s["direction"] > 0 and self._price >= s["target"]) or
            (s["direction"] < 0 and self._price <= s["target"])
        ):
            s["phase"] = "back"
            s["ticks_left"] = min(s["ticks_left"], 18)
        if s["ticks_left"] <= 0:
            # Rechazo completado: el precio vuelve hacia dentro del rango.
            self._price += (s["level"] - self._price) * 0.35
            self._sweep_armed = None

    # ── lectura ───────────────────────────────────────────────────────────

    def _aggregate_tick(self):
        """Cierra los buckets que cambiaron y actualiza el bucket en curso."""
        epoch = int(self._clock.timestamp())
        for tf, closed in self._tf_closed.items():
            bucket = self._tf_buckets[tf]
            key = epoch - (epoch % tf.value)
            if bucket["key"] is None:
                bucket.update({"key": key, "o": self._price, "h": self._price,
                               "l": self._price, "c": self._price})
                continue
            if key != bucket["key"]:
                # El bucket anterior cerro: se encola como vela completa, con su
                # calidad ya fijada de forma determinista e inmutable.
                closed.append((bucket["key"], bucket["o"], bucket["h"],
                               bucket["l"], bucket["c"], self._roll_quality()))
                bucket.update({"key": key, "o": self._price, "h": self._price,
                               "l": self._price, "c": self._price})
            else:
                if self._price > bucket["h"]:
                    bucket["h"] = self._price
                elif self._price < bucket["l"]:
                    bucket["l"] = self._price
                bucket["c"] = self._price

    def forming_candle(self, timeframe: Timeframe) -> Optional[Candle]:
        """Bucket EN CURSO: open/high/low/ultimo precio. NUNCA el cierre.

        Es lo unico que un observador en tiempo real puede ver de la vela
        abierta, y por eso no es look-ahead. Entregar aqui el cierre futuro si
        lo seria.
        """
        bucket = self._tf_buckets.get(timeframe)
        if bucket is None or bucket["key"] is None:
            return None
        return Candle(
            asset=self.asset, timeframe=timeframe,
            open_time=datetime.fromtimestamp(bucket["key"], tz=timezone.utc).replace(tzinfo=None),
            open=round(bucket["o"], 6), high=round(bucket["h"], 6),
            low=round(bucket["l"], 6), close=round(bucket["c"], 6),
            source="simulator_forming", quality=DataQuality.NORMAL,
            data_source=DataSource.SIMULATOR,
        )

    def _roll_quality(self) -> DataQuality:
        """Sortea la calidad de una vela AL CERRARLA. Resultado inmutable."""
        roll = self._quality_rng.random()
        if roll < self.cfg.stale_probability:
            return DataQuality.STALE
        if roll < self.cfg.stale_probability + self.cfg.duplicate_probability:
            return DataQuality.DUPLICATE
        return DataQuality.NORMAL

    def price_at(self, when: datetime) -> Optional[float]:
        """Precio observado en `when` (o el tick anterior mas cercano).

        Devuelve None si `when` es anterior al primer tick: no se extrapola
        hacia atras, porque inventar un precio historico es exactamente lo que
        este modulo no debe hacer.
        """
        best = None
        for ts, px in self._ticks:
            if ts <= when:
                best = px
            else:
                break
        return best

    def ticks(self, since: Optional[datetime] = None) -> list[tuple[datetime, float]]:
        return [(t, p) for t, p in self._ticks if since is None or t >= since]

    def candles(self, timeframe: Timeframe, count: int,
                quality_events: bool = True) -> list[Candle]:
        """Velas CERRADAS de `timeframe`, de mas antigua a mas nueva.

        Solo salen velas cuyo bucket ya cerro: el bucket en curso se queda fuera.
        Entregar una vela a medio formar como si estuviera cerrada es otra forma
        de look-ahead, y es facil de colar al agregar sobre la marcha.

        La calidad de cada vela se fijo al cerrarla (`_roll_quality`), asi que
        dos llamadas sobre el mismo historico devuelven exactamente lo mismo.
        `quality_events=False` solo omite marcarlas; no cambia los precios.
        """
        closed = self._tf_closed.get(timeframe)
        if closed is None:
            raise ValueError(f"timeframe no soportada por el simulador: {timeframe}")

        out: list[Candle] = []
        for key, o, h, l, c, quality in list(closed)[-count:]:
            if quality == DataQuality.STALE:
                # Vela stale: el feed no actualizo. Sin rango y sin cuerpo. Se
                # aplica al materializar (no al cerrar) para que el bucket
                # guardado conserve el recorrido real del tick.
                if quality_events:
                    c = o
                    h = l = o
                else:
                    quality = DataQuality.NORMAL
            elif not quality_events:
                quality = DataQuality.NORMAL
            out.append(Candle(
                asset=self.asset,
                timeframe=timeframe,
                open_time=datetime.fromtimestamp(key, tz=timezone.utc).replace(tzinfo=None),
                open=round(o, 6), high=round(h, 6), low=round(l, 6), close=round(c, 6),
                source="simulator",
                quality=quality,
                data_source=DataSource.SIMULATOR,
            ))
        return out

    def snapshot(self) -> dict:
        """Estado interno, para el dashboard y para depurar el generador."""
        return {
            "asset": self.asset,
            "clock": self._clock.isoformat(),
            "price": round(self._price, 6),
            "regime": self._regime,
            "minutes_in_regime": self._minutes_in_regime,
            "logvol": round(self._logvol, 4),
            "latent": round(self._latent, 4),
            "alpha": self.cfg.alpha,
            "sweep_active": self._sweep_armed is not None,
            "ticks": len(self._ticks),
            "events": dict(self.events),
            "regime_minutes": dict(self._regime_minutes),
            "bid": round(self.bid_ask()[0], 6),
            "ask": round(self.bid_ask()[1], 6),
        }
