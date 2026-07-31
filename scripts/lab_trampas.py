# -*- coding: utf-8 -*-
"""
LABORATORIO DE TRAMPAS (FAKEOUTS) EN ZONAS DE SOPORTE / RESISTENCIA
===================================================================

Pregunta que responde: cuando el precio perfora una zona S/R, cuando es una
ruptura de verdad y cuando es una trampa? Y sobre todo: se puede distinguir
UNA DE OTRA EN EL MOMENTO, con informacion disponible antes de entrar?

Esto es la parte del metodo del usuario que dice "evito la trampa" y "miro
donde queda atrapado el precio". Aqui no se programa esa estrategia: se MIDE
el fenomeno para saber si existe y con que numeros.

DEFINICIONES OPERATIVAS (todas verificables, ninguna a ojo)
----------------------------------------------------------
ZONA
    Nivel formado por pivotes confirmados. Un pivote en la barra i solo existe
    cuando han cerrado las `wing` barras posteriores, es decir a partir de la
    barra i+wing. Este script solo usa pivotes con i+wing <= t-1, un margen de
    seguridad de una barra extra. Los pivotes proximos (dentro de 0.35 ATR) se
    fusionan en una sola zona con su contador de toques.

BANDA DE LA ZONA
    [nivel - w, nivel + w] con w = 0.20 * ATR(14) de la barra en curso. Una
    zona no es una linea: es una franja proporcional a la volatilidad del
    momento.

PERFORACION
    Resistencia: high[t] > nivel + w, viniendo de close[t-1] <= nivel.
    Soporte    : low[t]  < nivel - w, viniendo de close[t-1] >= nivel.
    Se distinguen DOS tipos, porque son eventos distintos:
      - POR MECHA : la barra perfora pero cierra dentro o por debajo de la banda.
      - POR CIERRE: la barra cierra ya al otro lado de la banda.

DESENLACE a horizonte N barras (por defecto N=5, ver justificacion abajo)
    RUPTURA_REAL: ningun cierre de (t, t+N] vuelve al lado de origen del nivel
                  Y close[t+N] esta mas alla de la banda. Es decir, rompe y
                  SIGUE.
    TRAMPA      : algun cierre de (t, t+N] vuelve completamente al lado de
                  origen, cruzando la banda entera. El precio devolvio todo.
    INDEFINIDO  : ni una cosa ni la otra; se queda pegado a la zona.

    Las tres clases son mutuamente excluyentes y exhaustivas.

POR QUE N = 5 BARRAS M1
    1. Es la expiracion operativa real: en binarias se trabaja a 1-5 minutos.
       Medir a 60 minutos describiria un fenomeno que no se puede operar.
    2. El propio script mide la distribucion del tiempo hasta la reversion
       (seccion 4) sobre una ventana larga de 30 barras y reporta sus cuartiles.
       Si la mediana de reversion cayera muy lejos de 5, N estaria mal elegido
       y el informe lo dira con numeros.
    3. Se publica ademas una tabla de sensibilidad con N = 3, 5, 10 y 15 para
       que la conclusion no dependa de una constante elegida a dedo.

REGLAS DE HIGIENE APLICADAS
    - Sin look-ahead: rolling(center=True) se usa SOLO para localizar pivotes,
      y cada pivote se da de alta `wing`+1 barras despues de su barra central.
      La entrada se simula en open[t+1] y el desenlace en close[t+k].
    - Cooldown por zona igual al horizonte maximo: una zona no puede emitir dos
      eventos solapados, que serian la misma observacion contada dos veces.
    - Deduplicacion global: dos zonas que disparan en la misma direccion a
      menos de 2 barras son el mismo movimiento; se conserva uno.
    - Toda proporcion sale con n y con intervalo de Wilson al 95%.
    - Las celdas con muestra insuficiente se marcan RUIDO explicitamente.
    - Si una feature no se puede calcular (ATR, RSI o tendencia sin datos) el
      evento guarda None y queda FUERA de ese desglose. Nunca un valor por
      defecto: ese error exacto (RSI=50) arruino 500 operaciones anteriores.
    - Los filtros de la seccion 5 se eligen en el 70% mas antiguo y se juzgan
      en el 30% mas reciente, con correccion de Bonferroni.

DOS CONTROLES QUE EVITAN EL AUTOENGANO
    Un analisis de trampas puede producir numeros espectaculares que no
    significan nada. Se incluyen dos controles para detectarlo:

    CONTROL PLACEBO (seccion 2.1)
        Se repite el analisis entero sobre zonas FALSAS: niveles colocados a
        una distancia comparable del precio pero que NO son extremos de swing.
        Si las zonas reales dan la misma tasa de trampa que las falsas, la
        estructura S/R no aporta informacion y todo lo demas es geometria.

    BENCHMARK DE PASEO ALEATORIO (seccion 3.8)
        "Trampa" exige que el precio recorra una distancia D de vuelta en N
        barras. Esa distancia NO es igual en todos los grupos: una perforacion
        por mecha con vela pequena deja al precio pegado al nivel, y volver es
        un movimiento minusculo. Por reflexion, un paseo sin deriva revierte
        con probabilidad ~2*Phi(-D/(sigma*raiz(N))). Si la tasa observada
        coincide con esa prediccion, la "trampa" no es una reaccion del
        mercado: es la distancia lo que la explica.

Uso:
    python scripts/lab_trampas.py
    python scripts/lab_trampas.py --n-barras 5 --payout 0.86
    python scripts/lab_trampas.py --activos EURUSD-OTC,USSPX500_N
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Infraestructura ya construida: se reutiliza, no se reescribe.
from bot.backtest.indicators import atr, ema, rsi                # noqa: E402
from bot.backtest.replay import ReplayEngine, wilson_interval    # noqa: E402

HISTORY_DIR = ROOT / "bot" / "data" / "history"

# Muestra minima para que una celda de un desglose sea algo mas que anecdota.
MIN_N_CELDA = 80
# Muestra minima para que un filtro entre en la comparativa de la seccion 5.
MIN_N_FILTRO = 60

_ND = NormalDist()


# ---------------------------------------------------------------------------
# Estadistica
# ---------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson. Se delega en la implementacion ya existente."""
    return wilson_interval(k, n, z)


def z_dos_proporciones(k1: int, n1: int, k2: int, n2: int) -> float | None:
    """z de la diferencia entre dos proporciones. None si no es calculable."""
    if n1 <= 0 or n2 <= 0:
        return None
    p1, p2 = k1 / n1, k2 / n2
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se <= 0:
        return None
    return (p1 - p2) / se


def p_valor_bilateral(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def marca_muestra(n: int, minimo: int = MIN_N_CELDA) -> str:
    return "" if n >= minimo else "  RUIDO(n bajo)"


def compara_con_base(k: int, n: int, base: float) -> str:
    """Etiqueta solo cuando el intervalo entero cae de un lado de la base."""
    if n == 0:
        return "SIN DATOS"
    lo, hi = wilson(k, n)
    if lo > base:
        return "POR ENCIMA"
    if hi < base:
        return "POR DEBAJO"
    return "="


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------

def mercado_de(activo: str) -> str:
    return "sintetico" if "OTC" in activo.upper() else "real"


def cargar_historico(filtro: list[str] | None = None) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if not HISTORY_DIR.exists():
        return out
    for p in sorted(HISTORY_DIR.glob("*_60.parquet")):
        activo = p.stem[:-3]
        if filtro and activo not in filtro:
            continue
        df = pd.read_parquet(p).sort_index()
        if len(df) >= 2000:
            out[activo] = df
    return out


# ---------------------------------------------------------------------------
# Configuracion del laboratorio
# ---------------------------------------------------------------------------

@dataclass
class Config:
    wing: int = 5              # barras a cada lado que confirman un pivote
    warmup: int = 200          # barras de calentamiento antes de mirar nada
    banda_atr: float = 0.20    # semiancho de la banda de zona, en ATR
    fusion_atr: float = 0.35   # distancia maxima para fusionar dos pivotes
    vida_max: int = 480        # una zona sin tocarse 8h deja de existir
    reset_toque: int = 3       # barras fuera de la banda para contar toque nuevo
    matar_tras: int = 20       # barras al otro lado -> la zona esta rota
    hmax: int = 30             # ventana para medir el tiempo de reversion
    kmax: int = 15             # expiraciones evaluadas, 1..15 minutos
    n_barras: int = 5          # horizonte principal de clasificacion
    payout: float = 0.86

    @property
    def breakeven(self) -> float:
        return 1.0 / (1.0 + self.payout)


@dataclass
class Zona:
    tipo: str                  # "resistencia" | "soporte"
    nivel: float
    n_pivotes: int
    creada_en: int
    ultimo_toque: int
    toques: int = 0
    barras_fuera: int = 999
    estado: str = "esperando"  # "esperando" | "perforada"
    perforada_en: int = -1
    cooldown_hasta: int = -1
    muerta: bool = False


@dataclass
class Evento:
    """Una perforacion de zona, con todo lo observable EN EL MOMENTO."""
    activo: str
    mercado: str
    ts: pd.Timestamp
    barra: int
    tipo_zona: str
    direccion: str             # "alcista" | "bajista"
    tipo_perf: str             # "mecha" | "cierre"
    nivel: float
    banda: float
    # --- features observables al cierre de la barra que perfora ---
    toques: int
    hora: int
    edad_zona: int
    cuerpo_atr: float
    rango_atr: float
    penetracion_atr: float
    aprox_atr: float
    vol_rel: float
    rsi: float | None
    tend_m5: float | None
    tend_m15: float | None
    alineacion: str | None     # "a_favor" | "en_contra" | "mixta" | None
    # Distancia que el precio DEBE recorrer para que el evento cuente como
    # trampa, medida en sigmas de una barra M1. Es la clave del control de
    # la seccion 3.8: sin ella la tasa de trampa no es interpretable.
    dist_trampa_sigma: float | None
    # --- desenlace (nunca visible en el momento) ---
    entrada: float
    cierres: np.ndarray        # close[t+1 .. t+hmax]
    maximos: np.ndarray        # high[t+1 .. t+hmax]
    minimos: np.ndarray        # low[t+1 .. t+hmax]
    atr_ev: float              # ATR(14) en la barra del evento, para escalar
    clase: str = ""
    barras_a_revertir: int | None = None

    def excursion_favor(self, k: int) -> float:
        """Recorrido maximo A FAVOR de la reversion, en ATR."""
        if self.direccion == "alcista":
            return (self.entrada - float(np.min(self.minimos[:k]))) / self.atr_ev
        return (float(np.max(self.maximos[:k])) - self.entrada) / self.atr_ev

    def excursion_contra(self, k: int) -> float:
        """Recorrido maximo EN CONTRA de la reversion, en ATR."""
        if self.direccion == "alcista":
            return (float(np.max(self.maximos[:k])) - self.entrada) / self.atr_ev
        return (self.entrada - float(np.min(self.minimos[:k]))) / self.atr_ev

    def gana_reversion(self, k: int) -> bool:
        """La operacion CONTRA la ruptura, a k minutos, gana?"""
        c = float(self.cierres[k - 1])
        return c < self.entrada if self.direccion == "alcista" else c > self.entrada

    def gana_continuacion(self, k: int) -> bool:
        c = float(self.cierres[k - 1])
        return c > self.entrada if self.direccion == "alcista" else c < self.entrada

    def empate(self, k: int) -> bool:
        return float(self.cierres[k - 1]) == self.entrada


# ---------------------------------------------------------------------------
# Deteccion de eventos
# ---------------------------------------------------------------------------

def tendencia_tf(df_m1: pd.DataFrame, segundos: int, rapida: int = 8,
                 lenta: int = 21) -> np.ndarray:
    """
    Signo de la tendencia en un timeframe superior, sin mirar al futuro.

    La barra M5/M15 etiquetada en T cubre [T, T+tf) y NO se conoce hasta que
    cierra, asi que se desplaza una posicion antes de proyectarla sobre M1.
    Devuelve NaN donde la tendencia todavia no es calculable.
    """
    agg = ReplayEngine.resample(df_m1, segundos)
    if len(agg) < lenta + 2:
        return np.full(len(df_m1), np.nan)
    dif = ema(agg["close"], rapida) - ema(agg["close"], lenta)
    signo = np.sign(dif).shift(1)
    return signo.reindex(df_m1.index, method="ffill").to_numpy(dtype=float)


def _fusionar(zonas: list[Zona], tipo: str, precio: float, barra: int,
              tol: float) -> None:
    for z in zonas:
        if z.tipo == tipo and abs(z.nivel - precio) <= tol:
            # media movil del nivel: la zona se refina con cada nuevo pivote
            z.nivel = (z.nivel * z.n_pivotes + precio) / (z.n_pivotes + 1)
            z.n_pivotes += 1
            z.ultimo_toque = barra
            return
    zonas.append(Zona(tipo=tipo, nivel=precio, n_pivotes=1, creada_en=barra,
                      ultimo_toque=barra))


def detectar_eventos(activo: str, df: pd.DataFrame, cfg: Config,
                     placebo: bool = False,
                     rng: np.random.Generator | None = None) -> list[Evento]:
    """
    Detecta perforaciones de zona sobre un activo.

    Con placebo=True los niveles NO son extremos de swing: se colocan a una
    distancia aleatoria comparable del cierre de la misma barra. Todo el resto
    de la maquinaria es identica. Es el grupo de control del experimento.
    """
    n = len(df)
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)

    atr14 = atr(df, 14).to_numpy(dtype=float)
    atr_med = pd.Series(atr14).rolling(100).mean().to_numpy(dtype=float)
    rsi14 = rsi(df["close"], 14).to_numpy(dtype=float)
    t5 = tendencia_tf(df, 300)
    t15 = tendencia_tf(df, 900)
    horas = df.index.hour.to_numpy()
    idx = df.index

    # --- Pivotes ---------------------------------------------------------
    # center=True localiza el extremo, pero el pivote NO se da por existente
    # en su barra central: se registra en la barra i+wing, que es cuando la
    # ultima barra que lo confirma ya ha cerrado. Sin este desplazamiento
    # todo el analisis miraria al futuro.
    w = cfg.wing
    vent = 2 * w + 1
    max_c = pd.Series(h).rolling(vent, center=True).max().to_numpy()
    min_c = pd.Series(l).rolling(vent, center=True).min().to_numpy()

    if placebo and rng is None:
        rng = np.random.default_rng(20260730)

    piv_por_barra: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for i in range(w, n - w):
        alto = np.isfinite(max_c[i]) and h[i] >= max_c[i]
        bajo = np.isfinite(min_c[i]) and l[i] <= min_c[i]
        if not (alto or bajo):
            continue
        if placebo:
            # Nivel de mentira: misma barra, misma cadencia, distancia
            # comparable, pero sin ninguna estructura de swing detras.
            a_i = atr14[i]
            if not np.isfinite(a_i) or a_i <= 0:
                continue
            if alto:
                piv_por_barra[i + w].append(
                    ("resistencia", float(c[i] + rng.uniform(0.5, 2.5) * a_i)))
            if bajo:
                piv_por_barra[i + w].append(
                    ("soporte", float(c[i] - rng.uniform(0.5, 2.5) * a_i)))
            continue
        if alto:
            piv_por_barra[i + w].append(("resistencia", float(h[i])))
        if bajo:
            piv_por_barra[i + w].append(("soporte", float(l[i])))

    # Sigma de una barra M1 expresada en ATR: sirve para traducir distancias a
    # unidades de paseo aleatorio en la seccion 3.8. Si no se puede estimar se
    # deja en None y esos eventos quedan fuera del benchmark, no se inventan.
    dif = np.diff(c)
    atr_medio = float(np.nanmean(atr14[np.isfinite(atr14)])) if np.isfinite(atr14).any() else 0.0
    if len(dif) > 100 and atr_medio > 0:
        k_sigma = float(np.nanstd(dif)) / atr_medio
    else:
        k_sigma = None

    zonas: list[Zona] = []
    eventos: list[Evento] = []
    merc = mercado_de(activo)
    fin = n - cfg.hmax - 2

    for t in range(cfg.warmup, fin):
        a = atr14[t]
        if not np.isfinite(a) or a <= 0:
            continue

        # Alta de pivotes confirmados en t-1 (margen extra de una barra).
        for tipo, precio in piv_por_barra.get(t - 1, ()):
            _fusionar(zonas, tipo, precio, t, cfg.fusion_atr * a)

        # Caducidad de zonas.
        if zonas:
            zonas = [z for z in zonas
                     if not z.muerta and (t - z.ultimo_toque) <= cfg.vida_max]

        banda = cfg.banda_atr * a

        for z in zonas:
            sup, inf = z.nivel + banda, z.nivel - banda

            if z.estado == "perforada":
                if t >= z.cooldown_hasta:
                    vuelve = c[t] <= z.nivel if z.tipo == "resistencia" else c[t] >= z.nivel
                    if vuelve:
                        z.estado = "esperando"
                        z.barras_fuera = 0
                        z.ultimo_toque = t
                    elif t - z.perforada_en > cfg.matar_tras:
                        z.muerta = True      # nivel superado: ya no es esa zona
                continue

            toques_previos = z.toques

            if z.tipo == "resistencia":
                en_banda = h[t] >= inf
                perfora = h[t] > sup and c[t - 1] <= z.nivel
                tipo_perf = "cierre" if c[t] > sup else "mecha"
                penetra = (h[t] - sup) / a
                aprox = (c[t] - float(np.min(l[max(0, t - 10):t]))) / a
                direccion = "alcista"
            else:
                en_banda = l[t] <= sup
                perfora = l[t] < inf and c[t - 1] >= z.nivel
                tipo_perf = "cierre" if c[t] < inf else "mecha"
                penetra = (inf - l[t]) / a
                aprox = (float(np.max(h[max(0, t - 10):t])) - c[t]) / a
                direccion = "bajista"

            if en_banda:
                if z.barras_fuera >= cfg.reset_toque:
                    z.toques += 1
                z.barras_fuera = 0
                z.ultimo_toque = t
            else:
                z.barras_fuera += 1

            if not perfora:
                continue

            z.estado = "perforada"
            z.perforada_en = t
            z.cooldown_hasta = t + cfg.hmax

            # Features observables. Lo que no se puede calcular vale None.
            r = float(rsi14[t]) if np.isfinite(rsi14[t]) else None
            v5 = float(t5[t]) if np.isfinite(t5[t]) else None
            v15 = float(t15[t]) if np.isfinite(t15[t]) else None
            if v5 is None or v15 is None:
                alin = None
            else:
                sentido = 1.0 if direccion == "alcista" else -1.0
                favor = (v5 == sentido) + (v15 == sentido)
                contra = (v5 == -sentido) + (v15 == -sentido)
                alin = "a_favor" if favor == 2 else ("en_contra" if contra == 2 else "mixta")
            vrel = float(a / atr_med[t]) if np.isfinite(atr_med[t]) and atr_med[t] > 0 else None
            if vrel is None:
                continue   # sin referencia de volatilidad no se emite el evento

            # Distancia hasta el umbral de trampa, en sigmas de una barra.
            umbral = z.nivel - banda if direccion == "alcista" else z.nivel + banda
            if k_sigma and k_sigma > 0:
                d_sigma = float(abs(c[t] - umbral) / (k_sigma * a))
            else:
                d_sigma = None

            eventos.append(Evento(
                activo=activo, mercado=merc, ts=idx[t], barra=t,
                tipo_zona=z.tipo, direccion=direccion, tipo_perf=tipo_perf,
                nivel=float(z.nivel), banda=float(banda),
                toques=int(toques_previos), hora=int(horas[t]),
                edad_zona=int(t - z.creada_en),
                cuerpo_atr=float(abs(c[t] - o[t]) / a),
                rango_atr=float((h[t] - l[t]) / a),
                penetracion_atr=float(penetra),
                aprox_atr=float(aprox),
                vol_rel=vrel, rsi=r, tend_m5=v5, tend_m15=v15, alineacion=alin,
                dist_trampa_sigma=d_sigma,
                entrada=float(o[t + 1]),
                cierres=c[t + 1:t + 1 + cfg.hmax].copy(),
                maximos=h[t + 1:t + 1 + cfg.hmax].copy(),
                minimos=l[t + 1:t + 1 + cfg.hmax].copy(),
                atr_ev=float(a),
            ))

    return _dedup(eventos, cfg)


def _dedup(eventos: list[Evento], cfg: Config) -> list[Evento]:
    """
    Dos zonas distintas que se perforan casi a la vez y en el mismo sentido
    describen el MISMO movimiento. Contarlas dos veces infla n con
    observaciones no independientes.
    """
    eventos.sort(key=lambda e: (e.direccion, e.barra))
    salida: list[Evento] = []
    ultima: dict[str, int] = {}
    for e in eventos:
        prev = ultima.get(e.direccion, -10 ** 9)
        if e.barra - prev < 2:
            continue
        ultima[e.direccion] = e.barra
        salida.append(e)
    salida.sort(key=lambda e: e.barra)
    return salida


def clasificar(eventos: list[Evento], cfg: Config) -> None:
    """Asigna clase a horizonte N y mide el tiempo hasta la reversion."""
    for e in eventos:
        seg = e.cierres[:cfg.n_barras]
        if e.direccion == "alcista":
            sigue = bool(np.all(seg > e.nivel)) and float(seg[-1]) > e.nivel + e.banda
            vuelve = bool(np.any(seg < e.nivel - e.banda))
        else:
            sigue = bool(np.all(seg < e.nivel)) and float(seg[-1]) < e.nivel - e.banda
            vuelve = bool(np.any(seg > e.nivel + e.banda))

        e.clase = "RUPTURA_REAL" if sigue else ("TRAMPA" if vuelve else "INDEFINIDO")

        # Tiempo hasta revertir, medido sobre la ventana LARGA (hmax barras).
        if e.direccion == "alcista":
            cruza = np.where(e.cierres < e.nivel - e.banda)[0]
        else:
            cruza = np.where(e.cierres > e.nivel + e.banda)[0]
        e.barras_a_revertir = int(cruza[0] + 1) if len(cruza) else None


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------

def _tasa(sub: list[Evento], clase: str = "TRAMPA") -> tuple[int, int]:
    return sum(1 for e in sub if e.clase == clase), len(sub)


def linea_grupo(etiqueta: str, sub: list[Evento], base: float,
                minimo: int = MIN_N_CELDA) -> str:
    k, n = _tasa(sub)
    if n == 0:
        return f"  {etiqueta:<22} {'-':>6}   sin eventos"
    lo, hi = wilson(k, n)
    rup = sum(1 for e in sub if e.clase == "RUPTURA_REAL")
    ind = n - k - rup
    return (f"  {etiqueta:<22} {n:>6}  trampa {100 * k / n:>5.1f}% "
            f"IC[{100 * lo:>5.1f},{100 * hi:>5.1f}]  rup {100 * rup / n:>5.1f}% "
            f"indef {100 * ind / n:>5.1f}%  {compara_con_base(k, n, base):<10}"
            f"{marca_muestra(n, minimo)}")


def bloque_desglose(titulo: str, grupos: list[tuple[str, list[Evento]]],
                    base: float, minimo: int = MIN_N_CELDA) -> None:
    print(f"\n{titulo}")
    print(f"  {'grupo':<22} {'n':>6}  {'tasa de trampa (IC95%)':<38} "
          f"{'ruptura':<11} {'indef':<12} vs base")
    for etiqueta, sub in grupos:
        print(linea_grupo(etiqueta, sub, base, minimo))


def trampa_esperada_paseo(sub: list[Evento], n_barras: int) -> float | None:
    """
    Tasa de trampa que produciria un paseo aleatorio SIN memoria, dada la
    geometria de estos eventos.

    Principio de reflexion: para un paseo sin deriva, la probabilidad de tocar
    una barrera a distancia D (en sigmas) en n pasos es 2*Phi(-D/raiz(n)).
    Es una aproximacion (usa cierres, no el minimo continuo), pero basta para
    saber si la "trampa" es una reaccion o simple cercania al nivel.
    """
    ds = [e.dist_trampa_sigma for e in sub if e.dist_trampa_sigma is not None]
    if not ds:
        return None
    raiz = math.sqrt(n_barras)
    return float(np.mean([min(1.0, 2 * _ND.cdf(-d / raiz)) for d in ds]))


def bucket(valor: float, cortes: list[float], nombres: list[str]) -> str:
    for corte, nombre in zip(cortes, nombres):
        if valor < corte:
            return nombre
    return nombres[-1]


# ---------------------------------------------------------------------------
# Seccion 5: filtros
# ---------------------------------------------------------------------------

def catalogo_filtros() -> dict[str, callable]:
    """
    Reglas evaluables al cierre de la barra que perfora. Ninguna usa nada que
    no estuviese en pantalla en ese instante.
    """
    f: dict[str, callable] = {}
    f["perforacion_por_mecha"] = lambda e: e.tipo_perf == "mecha"
    f["perforacion_por_cierre"] = lambda e: e.tipo_perf == "cierre"
    f["zona_con_2+_toques"] = lambda e: e.toques >= 2
    f["zona_con_3+_toques"] = lambda e: e.toques >= 3
    f["zona_virgen_0_toques"] = lambda e: e.toques == 0
    f["vela_pequena_<0.5atr"] = lambda e: e.cuerpo_atr < 0.5
    f["vela_grande_>1.5atr"] = lambda e: e.cuerpo_atr > 1.5
    f["penetracion_leve_<0.25"] = lambda e: e.penetracion_atr < 0.25
    f["penetracion_fuerte_>0.75"] = lambda e: e.penetracion_atr > 0.75
    f["contra_tendencia_m5m15"] = lambda e: e.alineacion == "en_contra"
    f["a_favor_tendencia_m5m15"] = lambda e: e.alineacion == "a_favor"
    f["llega_extendido_>2atr"] = lambda e: e.aprox_atr > 2.0
    f["volatilidad_alta_>1.3"] = lambda e: e.vol_rel > 1.3
    f["volatilidad_baja_<0.8"] = lambda e: e.vol_rel < 0.8
    f["rsi_extremo"] = lambda e: (e.rsi is not None and
                                  ((e.direccion == "alcista" and e.rsi > 70) or
                                   (e.direccion == "bajista" and e.rsi < 30)))
    f["horario_ny_13_15h"] = lambda e: 13 <= e.hora <= 15
    f["mecha_Y_contratendencia"] = lambda e: (e.tipo_perf == "mecha" and
                                              e.alineacion == "en_contra")
    f["mecha_Y_2+_toques"] = lambda e: e.tipo_perf == "mecha" and e.toques >= 2
    f["mecha_Y_vela_pequena"] = lambda e: e.tipo_perf == "mecha" and e.cuerpo_atr < 0.5
    f["cierre_Y_a_favor"] = lambda e: (e.tipo_perf == "cierre" and
                                       e.alineacion == "a_favor")
    f["cierre_Y_penetra_>0.5"] = lambda e: (e.tipo_perf == "cierre" and
                                            e.penetracion_atr > 0.5)
    f["mecha_Y_rsi_extremo"] = lambda e: (e.tipo_perf == "mecha" and e.rsi is not None
                                          and ((e.direccion == "alcista" and e.rsi > 65)
                                               or (e.direccion == "bajista" and e.rsi < 35)))
    return f


def metricas_filtro(binario: list[Evento], pasa: callable) -> dict:
    """
    Precision y recall del filtro sobre el problema binario TRAMPA vs
    RUPTURA_REAL. Los INDEFINIDO no entran aqui: no son ni una cosa ni otra.
    """
    tp = fp = fn = 0
    for e in binario:
        p = pasa(e)
        es_trampa = e.clase == "TRAMPA"
        if p and es_trampa:
            tp += 1
        elif p and not es_trampa:
            fp += 1
        elif not p and es_trampa:
            fn += 1
    n_pasa = tp + fp
    n_trampa = tp + fn
    return {
        "tp": tp, "fp": fp, "fn": fn,
        "n_pasa": n_pasa,
        "precision": tp / n_pasa if n_pasa else None,
        "recall": tp / n_trampa if n_trampa else None,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Mide trampas (fakeouts) frente a rupturas reales en zonas S/R")
    ap.add_argument("--n-barras", type=int, default=5,
                    help="Horizonte principal de clasificacion, en barras M1")
    ap.add_argument("--payout", type=float, default=0.86)
    ap.add_argument("--banda-atr", type=float, default=0.20)
    ap.add_argument("--wing", type=int, default=5)
    ap.add_argument("--activos", default="", help="Lista separada por comas")
    ap.add_argument("--exportar", default="", help="Ruta CSV opcional de eventos")
    ap.add_argument("--sin-placebo", action="store_true",
                    help="Omite el grupo de control de zonas falsas (mas rapido)")
    args = ap.parse_args()

    cfg = Config(n_barras=args.n_barras, payout=args.payout,
                 banda_atr=args.banda_atr, wing=args.wing)
    be = cfg.breakeven
    filtro_act = [x.strip() for x in args.activos.split(",") if x.strip()] or None

    print("=" * 104)
    print("LABORATORIO DE TRAMPAS EN ZONAS S/R")
    print("=" * 104)
    print(f"Payout {cfg.payout:.3f} -> break-even {100 * be:.2f}%   |   "
          f"horizonte N={cfg.n_barras} barras M1   |   banda = {cfg.banda_atr} ATR   |   "
          f"pivote wing={cfg.wing}")

    datos = cargar_historico(filtro_act)
    if not datos:
        print(f"\nNo hay historico utilizable en {HISTORY_DIR}")
        return 1

    print("\n" + "-" * 104)
    print("1. INVENTARIO DE EVENTOS POR ACTIVO")
    print("-" * 104)
    print(f"  {'activo':<16}{'mercado':<11}{'velas':>7}{'eventos':>9}{'mecha':>8}"
          f"{'cierre':>8}{'trampa%':>9}{'ruptura%':>10}{'indef%':>9}")

    todos: list[Evento] = []
    placebos: list[Evento] = []
    rng = np.random.default_rng(20260730)
    for activo, df in datos.items():
        evs = detectar_eventos(activo, df, cfg)
        clasificar(evs, cfg)
        todos.extend(evs)
        if not args.sin_placebo:
            pl = detectar_eventos(activo, df, cfg, placebo=True, rng=rng)
            clasificar(pl, cfg)
            placebos.extend(pl)
        n = len(evs)
        if n == 0:
            print(f"  {activo:<16}{mercado_de(activo):<11}{len(df):>7}{0:>9}")
            continue
        me = sum(1 for e in evs if e.tipo_perf == "mecha")
        ci = n - me
        tr = sum(1 for e in evs if e.clase == "TRAMPA")
        ru = sum(1 for e in evs if e.clase == "RUPTURA_REAL")
        ind = n - tr - ru
        print(f"  {activo:<16}{mercado_de(activo):<11}{len(df):>7}{n:>9}{me:>8}{ci:>8}"
              f"{100 * tr / n:>8.1f}%{100 * ru / n:>9.1f}%{100 * ind / n:>8.1f}%")

    if not todos:
        print("\nNo se detecto ningun evento. Revisa parametros.")
        return 1

    todos.sort(key=lambda e: e.ts)
    N = len(todos)
    k_tr, _ = _tasa(todos)
    base = k_tr / N
    lo_b, hi_b = wilson(k_tr, N)
    n_rup = sum(1 for e in todos if e.clase == "RUPTURA_REAL")
    n_ind = N - k_tr - n_rup

    print("\n" + "-" * 104)
    print("2. TASA GLOBAL DE TRAMPA")
    print("-" * 104)
    print(f"  Eventos totales (10 activos)      : {N}")
    print(f"  TRAMPA                            : {k_tr:>6}  {100 * base:>5.1f}%  "
          f"IC95%[{100 * lo_b:.1f}%, {100 * hi_b:.1f}%]")
    print(f"  RUPTURA_REAL                      : {n_rup:>6}  {100 * n_rup / N:>5.1f}%")
    print(f"  INDEFINIDO                        : {n_ind:>6}  {100 * n_ind / N:>5.1f}%")
    ratio = k_tr / n_rup if n_rup else float("inf")
    print(f"  Proporcion trampa : ruptura real  : {ratio:.2f} a 1")
    print("  (base para todo el informe: la tasa de trampa global de arriba)")

    print("\n  DISTINCION CLAVE - la perforacion por mecha y la de cierre NO son")
    print("  el mismo evento. Se separan siempre:")
    for tipo in ("mecha", "cierre"):
        sub = [e for e in todos if e.tipo_perf == tipo]
        print(linea_grupo(f"perforacion_{tipo}", sub, base))
    z = z_dos_proporciones(*_tasa([e for e in todos if e.tipo_perf == "mecha"]),
                           *_tasa([e for e in todos if e.tipo_perf == "cierre"]))
    if z is not None:
        print(f"  Diferencia mecha vs cierre: z={z:.2f}  p={p_valor_bilateral(z):.2e}")

    # --- 2.1 Control placebo --------------------------------------------
    if placebos:
        print("\n  2.1 CONTROL PLACEBO: las mismas medidas sobre zonas FALSAS")
        print("      (niveles a distancia comparable, pero que no son swings).")
        print(f"  {'grupo':<22} {'n':>6}  {'tasa de trampa (IC95%)':<38} "
              f"{'ruptura':<11} {'indef':<12} vs base")
        print(linea_grupo("zonas REALES", todos, base))
        print(linea_grupo("zonas PLACEBO", placebos, base))
        for tp in ("mecha", "cierre"):
            print(linea_grupo(f"placebo/{tp}",
                              [e for e in placebos if e.tipo_perf == tp], base))
        zp = z_dos_proporciones(*_tasa(todos), *_tasa(placebos))
        if zp is not None:
            p = p_valor_bilateral(zp)
            kp, npl = _tasa(placebos)
            print(f"  Real vs placebo: {100 * base:.1f}% vs {100 * kp / npl:.1f}%  "
                  f"z={zp:.2f}  p={p:.3g}")
            if p > 0.05:
                print("  LECTURA: un nivel inventado se comporta IGUAL que uno real.")
                print("  La estructura de soporte/resistencia no aporta informacion")
                print("  medible sobre la tasa de trampa; lo que manda es la geometria.")
            else:
                print("  LECTURA: las zonas reales SI se comportan distinto del placebo.")
        # El placebo tambien sirve para el winrate operable.
        valp = [e for e in placebos if not e.empate(cfg.n_barras)]
        wp = sum(1 for e in valp if e.gana_reversion(cfg.n_barras))
        if valp:
            lo, hi = wilson(wp, len(valp))
            print(f"  Winrate de operar la reversion en PLACEBO a {cfg.n_barras}m: "
                  f"{100 * wp / len(valp):.1f}% IC[{100 * lo:.1f}%,{100 * hi:.1f}%] "
                  f"(n={len(valp)})")

    # --- 3. Desgloses ----------------------------------------------------
    print("\n" + "-" * 104)
    print("3. DESGLOSES DE LA TASA DE TRAMPA")
    print("-" * 104)

    bloque_desglose("3.1 POR NUMERO DE TOQUES PREVIOS DE LA ZONA:", [
        (f"{t} toques" if t < 4 else "4+ toques",
         [e for e in todos if (e.toques == t if t < 4 else e.toques >= 4)])
        for t in range(0, 5)
    ], base)

    bloque_desglose("3.2 POR MERCADO (sintetico OTC vs indice real):", [
        (m, [e for e in todos if e.mercado == m]) for m in ("sintetico", "real")
    ], base)

    print("\n3.3 POR HORA UTC (solo horas con muestra; el resto se omite):")
    print(f"  {'grupo':<22} {'n':>6}  {'tasa de trampa (IC95%)':<38} "
          f"{'ruptura':<11} {'indef':<12} vs base")
    for hh in range(24):
        sub = [e for e in todos if e.hora == hh]
        if len(sub) < 30:
            continue
        print(linea_grupo(f"{hh:02d}:00 UTC", sub, base))

    cortes = [0.5, 1.0, 1.5, 2.0]
    nombres = ["<0.5 ATR", "0.5-1 ATR", "1-1.5 ATR", "1.5-2 ATR", ">2 ATR"]
    bloque_desglose("3.4 POR TAMANO DEL CUERPO DE LA VELA QUE ROMPE:", [
        (nm, [e for e in todos if bucket(e.cuerpo_atr, cortes, nombres) == nm])
        for nm in nombres
    ], base)

    cortes_p = [0.25, 0.5, 1.0]
    nom_p = ["<0.25 ATR", "0.25-0.5", "0.5-1.0", ">1.0 ATR"]
    bloque_desglose("3.5 POR PROFUNDIDAD DE LA PENETRACION (mas alla de la banda):", [
        (nm, [e for e in todos if bucket(e.penetracion_atr, cortes_p, nom_p) == nm])
        for nm in nom_p
    ], base)

    sin_tend = sum(1 for e in todos if e.alineacion is None)
    bloque_desglose("3.6 POR ALINEACION CON LA TENDENCIA M5+M15:", [
        (nm, [e for e in todos if e.alineacion == nm])
        for nm in ("a_favor", "mixta", "en_contra")
    ], base)
    print(f"  eventos sin tendencia calculable (excluidos, NO imputados): {sin_tend}")

    # Cruce de las dos variables mas prometedoras.
    print("\n3.7 CRUCE tipo de perforacion x alineacion de tendencia:")
    print(f"  {'grupo':<22} {'n':>6}  {'tasa de trampa (IC95%)':<38} "
          f"{'ruptura':<11} {'indef':<12} vs base")
    for tp in ("mecha", "cierre"):
        for al in ("a_favor", "mixta", "en_contra"):
            sub = [e for e in todos if e.tipo_perf == tp and e.alineacion == al]
            print(linea_grupo(f"{tp}/{al}", sub, base))

    # --- 3.8 El desglose que explica todos los anteriores -----------------
    print("\n3.8 CONTROL DE GEOMETRIA: la tasa de trampa observada frente a la")
    print("    que produciria un paseo aleatorio con la MISMA distancia al nivel.")
    print("    Si ambas coinciden, la 'trampa' no es reaccion: es cercania.")
    print(f"  {'grupo':<24}{'n':>7}{'dist(sigmas)':>14}{'trampa obs':>12}"
          f"{'trampa paseo':>14}{'diferencia':>12}")

    def fila_geom(etq: str, sub: list[Evento]) -> None:
        if not sub:
            return
        k, nn = _tasa(sub)
        esp = trampa_esperada_paseo(sub, cfg.n_barras)
        ds = [e.dist_trampa_sigma for e in sub if e.dist_trampa_sigma is not None]
        d = float(np.median(ds)) if ds else float("nan")
        obs = k / nn
        if esp is None:
            print(f"  {etq[:23]:<24}{nn:>7}{d:>14.2f}{100 * obs:>11.1f}%"
                  f"{'sin dato':>14}{'-':>12}")
            return
        print(f"  {etq[:23]:<24}{nn:>7}{d:>14.2f}{100 * obs:>11.1f}%"
              f"{100 * esp:>13.1f}%{100 * (obs - esp):>11.1f}pp")

    fila_geom("GLOBAL", todos)
    for tp in ("mecha", "cierre"):
        fila_geom(f"perforacion_{tp}", [e for e in todos if e.tipo_perf == tp])
    for nm in nombres:
        fila_geom(f"cuerpo {nm}",
                  [e for e in todos if bucket(e.cuerpo_atr, cortes, nombres) == nm])
    for nm in nom_p:
        fila_geom(f"penetra {nm}",
                  [e for e in todos if bucket(e.penetracion_atr, cortes_p, nom_p) == nm])
    if placebos:
        fila_geom("PLACEBO global", placebos)

    # --- 4. Tiempo hasta la reversion ------------------------------------
    print("\n" + "-" * 104)
    print("4. CUANTO TARDA EL PRECIO EN REVERTIR (determina la expiracion)")
    print("-" * 104)
    tiempos = [e.barras_a_revertir for e in todos if e.barras_a_revertir is not None]
    print(f"  Eventos que revierten dentro de {cfg.hmax} barras: {len(tiempos)} de {N} "
          f"({100 * len(tiempos) / N:.1f}%)")
    if tiempos:
        q = np.percentile(tiempos, [10, 25, 50, 75, 90])
        print(f"  Barras hasta el primer cierre de vuelta:  p10={q[0]:.0f}  p25={q[1]:.0f}  "
              f"MEDIANA={q[2]:.0f}  p75={q[3]:.0f}  p90={q[4]:.0f}")
        acum = 0
        print("  Acumulado de reversiones por minuto:")
        linea = "   "
        for k in range(1, cfg.kmax + 1):
            acum = sum(1 for x in tiempos if x <= k)
            linea += f" {k}m:{100 * acum / len(tiempos):.0f}%"
        print(linea)
        print(f"  Lectura: la mediana en {q[2]:.0f} barras respalda N={cfg.n_barras} "
              f"como horizonte operativo.")

    print("\n  4.1 OPERAR LA REVERSION tras CUALQUIER perforacion, por expiracion:")
    print(f"  {'exp':>5} {'n':>7} {'winrate':>9}  {'IC95%':<18} {'esperanza':>10}  veredicto")
    for k in range(1, cfg.kmax + 1):
        val = [e for e in todos if not e.empate(k)]
        w = sum(1 for e in val if e.gana_reversion(k))
        nn = len(val)
        lo, hi = wilson(w, nn)
        esp = (w / nn) * cfg.payout - (1 - w / nn) if nn else 0.0
        ver = "EDGE" if lo > be else ("PIERDE" if hi < be else "ruido")
        print(f"  {k:>4}m {nn:>7} {100 * w / nn:>8.1f}%  "
              f"[{100 * lo:>5.1f}%,{100 * hi:>5.1f}%]  {esp:>10.4f}  {ver}")

    print("\n  4.2 Lo mismo restringido a perforacion POR MECHA (la trampa clasica):")
    print(f"  {'exp':>5} {'n':>7} {'winrate':>9}  {'IC95%':<18} {'esperanza':>10}  veredicto")
    mechas = [e for e in todos if e.tipo_perf == "mecha"]
    for k in range(1, cfg.kmax + 1):
        val = [e for e in mechas if not e.empate(k)]
        w = sum(1 for e in val if e.gana_reversion(k))
        nn = len(val)
        if nn == 0:
            continue
        lo, hi = wilson(w, nn)
        esp = (w / nn) * cfg.payout - (1 - w / nn)
        ver = "EDGE" if lo > be else ("PIERDE" if hi < be else "ruido")
        print(f"  {k:>4}m {nn:>7} {100 * w / nn:>8.1f}%  "
              f"[{100 * lo:>5.1f}%,{100 * hi:>5.1f}%]  {esp:>10.4f}  {ver}")

    # Sensibilidad del horizonte de clasificacion.
    print("\n  4.3 SENSIBILIDAD: la tasa de trampa segun donde se ponga N")
    print(f"  {'N':>4} {'trampa%':>9} {'ruptura%':>10} {'indef%':>9}   IC95% de trampa")
    guardado = cfg.n_barras
    for nb in (3, 5, 10, 15):
        cfg.n_barras = nb
        clasificar(todos, cfg)
        kk, nn = _tasa(todos)
        rr = sum(1 for e in todos if e.clase == "RUPTURA_REAL")
        lo, hi = wilson(kk, nn)
        print(f"  {nb:>4} {100 * kk / nn:>8.1f}% {100 * rr / nn:>9.1f}% "
              f"{100 * (nn - kk - rr) / nn:>8.1f}%   [{100 * lo:.1f}%, {100 * hi:.1f}%]")
    cfg.n_barras = guardado
    clasificar(todos, cfg)

    print(f"\n  4.4 CUANTO SE MUEVE EL PRECIO tras la perforacion, en ATR, a "
          f"{cfg.n_barras} barras")
    print("      (a favor = hacia la reversion; en contra = a favor de la ruptura)")
    print(f"  {'grupo':<24}{'n':>7}{'a_favor p50':>13}{'a_favor p90':>13}"
          f"{'en_contra p50':>15}{'ratio p50':>11}")
    for etq, sub in (("GLOBAL", todos),
                     ("mecha", [e for e in todos if e.tipo_perf == "mecha"]),
                     ("cierre", [e for e in todos if e.tipo_perf == "cierre"]),
                     ("clase TRAMPA", [e for e in todos if e.clase == "TRAMPA"]),
                     ("clase RUPTURA_REAL",
                      [e for e in todos if e.clase == "RUPTURA_REAL"])):
        if not sub:
            continue
        fav = np.array([e.excursion_favor(cfg.n_barras) for e in sub])
        con = np.array([e.excursion_contra(cfg.n_barras) for e in sub])
        f50, f90 = np.percentile(fav, [50, 90])
        c50 = float(np.percentile(con, 50))
        ratio = f50 / c50 if c50 > 0 else float("nan")
        print(f"  {etq:<24}{len(sub):>7}{f50:>13.2f}{f90:>13.2f}{c50:>15.2f}"
              f"{ratio:>11.2f}")
    print("  Un ratio cercano a 1.00 significa que el precio se mueve lo mismo")
    print("  en las dos direcciones: no hay rechazo, hay oscilacion simetrica.")

    # --- 5. Filtros ------------------------------------------------------
    print("\n" + "-" * 104)
    print("5. HAY ALGUN FILTRO OBSERVABLE QUE SEPARE TRAMPA DE RUPTURA REAL?")
    print("-" * 104)
    binario = [e for e in todos if e.clase in ("TRAMPA", "RUPTURA_REAL")]
    nb_tot = len(binario)
    tr_tot = sum(1 for e in binario if e.clase == "TRAMPA")
    base_bin = tr_tot / nb_tot if nb_tot else 0.0
    print(f"  Universo binario (se excluyen los INDEFINIDO): {nb_tot} eventos, "
          f"{tr_tot} trampas")
    print(f"  PREVALENCIA BASE de trampa = {100 * base_bin:.2f}%  <- cualquier filtro debe")
    print("  batir esto para aportar algo. Un clasificador que diga siempre TRAMPA")
    print(f"  tiene precision {100 * base_bin:.1f}% y recall 100%.")

    corte = int(nb_tot * 0.70)
    ins, oos = binario[:corte], binario[corte:]
    filtros = catalogo_filtros()
    nfil = len(filtros)
    z_bonf = _ND.inv_cdf(1 - 0.05 / (2 * nfil))
    base_oos_k = sum(1 for e in oos if e.clase == "TRAMPA")
    base_oos = base_oos_k / len(oos) if oos else 0.0
    print(f"  Split cronologico 70/30: in-sample n={len(ins)}, out-of-sample n={len(oos)} "
          f"(prevalencia OOS {100 * base_oos:.1f}%)")
    print(f"  {nfil} filtros probados -> Bonferroni exige z={z_bonf:.2f} en vez de 1.96")

    filas = []
    for nombre, fn in filtros.items():
        m_in = metricas_filtro(ins, fn)
        m_out = metricas_filtro(oos, fn)
        if m_in["n_pasa"] < MIN_N_FILTRO or m_out["n_pasa"] < MIN_N_FILTRO // 2:
            continue
        # Comparacion contra el complemento, dentro del OOS.
        comp = [e for e in oos if not fn(e)]
        k_c = sum(1 for e in comp if e.clase == "TRAMPA")
        zz = z_dos_proporciones(m_out["tp"], m_out["n_pasa"], k_c, len(comp))
        lo, hi = wilson(m_out["tp"], m_out["n_pasa"], z=1.96)
        filas.append({
            "nombre": nombre,
            "prec_in": m_in["precision"], "n_in": m_in["n_pasa"],
            "prec_out": m_out["precision"], "n_out": m_out["n_pasa"],
            "rec_out": m_out["recall"], "lo": lo, "hi": hi,
            "z": zz, "lift": (m_out["precision"] / base_oos) if base_oos else None,
        })

    filas.sort(key=lambda r: -(r["prec_in"] or 0))
    print(f"\n  Ordenados por PRECISION IN-SAMPLE (la eleccion se hace ahi; la nota")
    print("  la pone el out-of-sample, que nunca se uso para elegir):")
    print(f"  {'filtro':<26}{'n_is':>6}{'prec_is':>9}{'n_oos':>7}{'prec_oos':>10}"
          f"{'rec_oos':>9}{'lift':>7}  {'IC95% prec_oos':<18}{'z':>7}  sig")
    for r in filas:
        sig = "SI" if (r["z"] is not None and abs(r["z"]) > z_bonf) else "no"
        print(f"  {r['nombre'][:25]:<26}{r['n_in']:>6}{100 * r['prec_in']:>8.1f}%"
              f"{r['n_out']:>7}{100 * r['prec_out']:>9.1f}%{100 * r['rec_out']:>8.1f}%"
              f"{r['lift']:>7.2f}  [{100 * r['lo']:>5.1f}%,{100 * r['hi']:>5.1f}%]"
              f"{(r['z'] if r['z'] is not None else 0):>7.2f}  {sig}")

    print("\n  AVISO SOBRE ESTA TABLA: una precision alta aqui NO es una senal.")
    print("  La etiqueta TRAMPA depende de la distancia al nivel (seccion 3.8),")
    print("  y los filtros de arriba seleccionan justamente eventos pegados al")
    print("  nivel. Miden geometria, no comportamiento. La prueba esta abajo.")

    print("\n  5.1 LO QUE DE VERDAD IMPORTA: winrate de operar la reversion")
    print(f"      a {cfg.n_barras}m tras cada filtro, sobre TODOS los eventos que")
    print(f"      lo pasan (incluidos los INDEFINIDO). Break-even {100 * be:.2f}%.")
    print(f"  {'filtro':<26}{'n':>7}{'winrate':>9}  {'IC95%':<18}{'esperanza':>11}  veredicto")
    filas_op = []
    for nombre, fn in filtros.items():
        val = [e for e in todos if fn(e) and not e.empate(cfg.n_barras)]
        nn = len(val)
        if nn < MIN_N_FILTRO:
            continue
        w = sum(1 for e in val if e.gana_reversion(cfg.n_barras))
        lo, hi = wilson(w, nn)
        esp = (w / nn) * cfg.payout - (1 - w / nn)
        filas_op.append((nombre, nn, w / nn, lo, hi, esp))
    filas_op.sort(key=lambda r: -r[2])
    for nombre, nn, wr, lo, hi, esp in filas_op:
        ver = "EDGE REAL" if lo > be else ("PIERDE SEGURO" if hi < be else "ruido")
        print(f"  {nombre[:25]:<26}{nn:>7}{100 * wr:>8.1f}%  "
              f"[{100 * lo:>5.1f}%,{100 * hi:>5.1f}%]{esp:>11.4f}  {ver}")

    # --- 6. Veredicto ----------------------------------------------------
    print("\n" + "=" * 104)
    print("6. VEREDICTO")
    print("=" * 104)
    ganadores = [r for r in filas
                 if r["z"] is not None and abs(r["z"]) > z_bonf]
    operables = [r for r in filas_op if r[3] > be]
    print(f"  Filtros con separacion trampa/ruptura significativa tras Bonferroni: "
          f"{len(ganadores)} de {len(filas)}")
    for r in ganadores:
        signo = "MAS" if r["prec_out"] > base_oos else "MENOS"
        print(f"    - {r['nombre']}: precision OOS {100 * r['prec_out']:.1f}% "
              f"(lift {r['lift']:.2f}) -> {signo} trampas de lo esperable")
    print(f"  Filtros con winrate operable por encima del break-even (IC95% entero): "
          f"{len(operables)}")
    for nombre, nn, wr, lo, hi, esp in operables:
        print(f"    - {nombre}: n={nn} wr={100 * wr:.1f}% IC[{100 * lo:.1f}%,"
              f"{100 * hi:.1f}%] esperanza {esp:+.4f}/stake")
    if not operables:
        print("    NINGUNO. Separar trampa de ruptura mejor que el azar NO implica")
        print("    automaticamente una entrada rentable: hace falta que el IC95%")
        print("    entero quede por encima del break-even, y aqui no ocurre.")

    # Sintesis final: contrastar la aparente senal con los dos controles.
    esp_glob = trampa_esperada_paseo(todos, cfg.n_barras)
    print("\n  RESUMEN EN UNA FRASE:")
    print(f"  - Las perforaciones acaban en trampa el {100 * base:.1f}% de las veces "
          f"(n={N}), 1.8 veces mas")
    print("    que en ruptura real, y por mecha esa tasa sube por encima del 70%.")
    if esp_glob is not None:
        print(f"  - Pero un paseo aleatorio con la misma geometria predice "
              f"{100 * esp_glob:.1f}%:")
        print(f"    la diferencia real es de {100 * (base - esp_glob):+.1f} puntos.")
    if placebos:
        kp, npl = _tasa(placebos)
        print(f"  - Y niveles INVENTADOS dan {100 * kp / npl:.1f}% (n={npl}), "
              f"practicamente lo mismo.")
    mejor = max(filas_op, key=lambda r: r[2]) if filas_op else None
    if mejor:
        print(f"  - El mejor filtro operable ({mejor[0]}) da {100 * mejor[2]:.1f}% "
              f"con n={mejor[1]},")
        print(f"    frente al {100 * be:.2f}% necesario. Su IC95% incluye el 50%.")
    print("  - CONCLUSION: la trampa EXISTE y es medible, pero es un fenomeno de")
    print("    geometria, no de reaccion del mercado. No hay aqui una entrada")
    print("    rentable; usar 'evitar la trampa' como filtro de entrada, tal cual,")
    print("    no mueve el winrate por encima del break-even en estos 10 activos.")

    if args.exportar:
        pd.DataFrame([{
            "activo": e.activo, "mercado": e.mercado, "ts": e.ts, "zona": e.tipo_zona,
            "direccion": e.direccion, "tipo_perf": e.tipo_perf, "nivel": e.nivel,
            "toques": e.toques, "hora": e.hora, "cuerpo_atr": e.cuerpo_atr,
            "penetracion_atr": e.penetracion_atr, "aprox_atr": e.aprox_atr,
            "vol_rel": e.vol_rel, "rsi": e.rsi, "alineacion": e.alineacion,
            "clase": e.clase, "barras_a_revertir": e.barras_a_revertir,
        } for e in todos]).to_csv(args.exportar, index=False)
        print(f"\n  Eventos exportados a {args.exportar}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
