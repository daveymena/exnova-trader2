# -*- coding: utf-8 -*-
"""
Motor de auto-evaluacion: decide que setups se operan y cuales se retiran.

CONTEXTO. La version anterior del bot "aprendia" promoviendo reglas ajustadas
sobre n=1, n=6, n=7, n=9 observaciones. Con payout 0.86 el break-even esta en
53.76%: con 9 operaciones, 6 aciertos (66.7%) parecen un edge y son ruido puro
(el IC95% va de 35% a 88%). Ese es el mecanismo exacto que hundio las 500
operaciones previas, y todo este modulo existe para hacerlo imposible.

QUE PROTEGE, por orden de impacto medido:

  1. Minimo de observaciones. Por debajo de `min_observaciones` (>=200) NUNCA
     se emite un veredicto distinto de INSUFICIENTE. Sin excepciones.
  2. Se exige que el LIMITE INFERIOR de Wilson supere el break-even, no el
     winrate puntual. Un 60% con n=20 tiene IC [39%, 78%]: no dice nada.
  3. Correccion por comparaciones multiples entre setups (Benjamini-Hochberg).
     Probar 40 variantes y quedarse con la mejor produce un "ganador" aparente
     aunque las 40 sean monedas al aire.
  4. Correccion por miradas repetidas. Mirar el mismo setup despues de cada
     operacion es probar la misma hipotesis 500 veces; aqui solo se decide en
     checkpoints geometricos (200, 400, 800...) y el numero de miradas penaliza
     el umbral (Bonferroni sobre miradas).
  5. Retirada PERMANENTE. Reabrir un setup rechazado, o reintentar la misma
     familia con parametros nuevos hasta que uno pase, es una busqueda sobre
     ruido disfrazada de mejora. Hay tope de reaperturas y tope de variantes
     por familia.

ASIMETRIA DELIBERADA. Para declarar GANADOR se usa el umbral corregido (caro
equivocarse: se opera a tamano completo). Para declarar PERDEDOR se usa un
umbral sin corregir (barato equivocarse: solo se deja de operar, y existe
`reopen`). No es descuido, es la asimetria de costes.

REGLA 4 DEL PROYECTO. Si un valor no se puede calcular se devuelve None, nunca
un default plausible. `stats()` con n=0 devuelve winrate None, no 0.0.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "self_evaluator.json"
VERSION_ESTADO = 1

# --- estados operativos (los tres del enunciado, sin estados ocultos) --------
EXPLORACION = "EXPLORACION"   # setup nuevo o degradado: se opera a tamano MINIMO
PRODUCCION = "PRODUCCION"     # veredicto GANADOR vigente: tamano normal
RETIRADO = "RETIRADO"         # no se opera; permanente salvo reopen() explicito

# --- veredictos estadisticos ------------------------------------------------
INSUFICIENTE = "INSUFICIENTE"  # no hay muestra para concluir nada
RUIDO = "RUIDO"                # hay muestra y el IC cruza el break-even
GANADOR = "GANADOR"            # IC entero por encima del break-even
PERDEDOR = "PERDEDOR"          # IC entero por debajo del break-even


class EstadoCorrupto(RuntimeError):
    """El fichero de estado no se pudo leer ni verificar."""


# ===========================================================================
# Utilidades estadisticas (sin dependencias externas: esto corre en el bot)
# ===========================================================================

def _phi(x: float) -> float:
    """Funcion de distribucion normal estandar."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


_Z_CACHE: dict[float, float] = {}


def z_desde_alpha(alpha: float) -> float:
    """
    Cuantil normal 1-alpha (una cola). alpha=0.05 -> 1.6449, 0.025 -> 1.9600.

    Aproximacion de Acklam mas un refinamiento de Halley: error < 1e-12, que es
    mas que suficiente y evita arrastrar scipy hasta el runtime del bot.
    """
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha fuera de rango: {alpha}")
    cached = _Z_CACHE.get(alpha)
    if cached is not None:
        return cached

    p = 1.0 - alpha
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1.0 - 0.02425

    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= phigh:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)

    # Refinamiento de Halley sobre el error residual.
    e = 0.5 * math.erfc(-x / math.sqrt(2.0)) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    x = x - u / (1.0 + x * u / 2.0)

    _Z_CACHE[alpha] = x
    return x


def intervalo_wilson(exitos: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """
    Intervalo de Wilson. Devuelve (None, None) si n==0.

    Se devuelve None y no (0.0, 1.0): un intervalo (0,1) invita a compararlo
    con el break-even y a "concluir" algo. Sin datos no hay intervalo.
    """
    if n <= 0:
        return (None, None)
    p = exitos / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centro = (p + z2 / (2 * n)) / denom
    margen = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def _log_binom_pmf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + k * math.log(p) + (n - k) * math.log(1.0 - p))


def pvalor_binomial_superior(exitos: int, n: int, p0: float) -> float | None:
    """P(X >= exitos) bajo H0: p = p0. Binomial exacta. None si n==0."""
    if n <= 0:
        return None
    if exitos <= 0:
        return 1.0
    if exitos > n:
        return 0.0
    media = n * p0
    sd = math.sqrt(n * p0 * (1 - p0))
    corte = int(math.ceil(media + 12 * sd)) + 5   # cola despreciable mas alla
    total = 0.0
    for k in range(exitos, min(n, corte) + 1):
        total += math.exp(_log_binom_pmf(k, n, p0))
    return min(1.0, max(0.0, total))


def pvalor_binomial_inferior(exitos: int, n: int, p0: float) -> float | None:
    """P(X <= exitos) bajo H0: p = p0. None si n==0."""
    if n <= 0:
        return None
    return pvalor_binomial_superior(n - exitos, n, 1.0 - p0)


def z_dos_proporciones(w1: int, n1: int, w2: int, n2: int) -> float | None:
    """
    Estadistico z de comparacion de dos proporciones (grupo1 - grupo2).
    Devuelve None si algun grupo esta vacio o la varianza es nula.
    """
    if n1 <= 0 or n2 <= 0:
        return None
    p1, p2 = w1 / n1, w2 / n2
    pool = (w1 + w2) / (n1 + n2)
    var = pool * (1 - pool) * (1.0 / n1 + 1.0 / n2)
    if var <= 0:
        return None
    return (p1 - p2) / math.sqrt(var)


def umbral_benjamini_hochberg(pvalores: list[float], q: float) -> float:
    """
    Umbral de rechazo de Benjamini-Hochberg sobre una familia de p-valores.

    POR QUE BH Y NO BONFERRONI (justificacion pedida):
    Bonferroni controla FWER, es decir la probabilidad de cometer *aunque sea
    un* falso positivo. Con un catalogo que crece (el bot acumula decenas de
    setups a lo largo de meses) el umbral alpha/m se vuelve inalcanzable: con
    m=200 haria falta z=3.9, o sea miles de operaciones por setup solo para
    detectar un edge de 4 puntos. Eso no protege: paraliza, y en la practica
    lleva a desactivar la correccion "porque es demasiado estricta".
    Lo que aqui importa no es "cero falsos positivos jamas", sino "de los
    setups que mando a produccion, que pocos sean falsos". Eso es exactamente
    la tasa de falsos descubrimientos (FDR), que es lo que controla BH. Ademas
    BH sigue siendo valido bajo dependencia positiva (PRDS), que es el regimen
    real aqui porque todos los setups leen el mismo mercado.
    Se deja `correccion="bonferroni"` disponible para quien quiera FWER.

    Devuelve el umbral efectivo: se rechaza toda hipotesis con p <= umbral.
    Si no hay ningun rechazo devuelve el umbral mas exigente (q/m), que es el
    que habria hecho falta superar.
    """
    m = len(pvalores)
    if m == 0:
        return q
    ordenados = sorted(pvalores)
    k_estrella = 0
    for k in range(1, m + 1):
        if ordenados[k - 1] <= k * q / m:
            k_estrella = k
    return max(k_estrella, 1) * q / m


# ===========================================================================
# Configuracion
# ===========================================================================

@dataclass
class EvaluatorConfig:
    """Todos los umbrales, en un solo sitio auditable."""

    payout: float = 0.86                  # payout REAL medido, no el de folleto
    alpha: float = 0.05                   # nivel FDR (q) para declarar GANADOR
    alpha_perdedor: float = 0.05          # nivel SIN corregir para retirar
    correccion: str = "bh"                # "bh" | "bonferroni"

    min_observaciones: int = 200          # nunca se concluye por debajo de esto
    crecimiento_checkpoint: float = 2.0   # miradas en 200, 400, 800, 1600...
    penalizar_miradas: bool = True        # Bonferroni sobre numero de miradas

    max_obs_exploracion: int = 1500       # presupuesto de exploracion por epoca
    tamano_exploracion: float = 0.25      # fraccion del stake normal explorando

    ventana_degradacion: int = 100        # operaciones de la ventana movil
    revisar_degradacion_cada: int = 50    # ventanas semi-solapadas, no continuas
    alpha_degradacion: float = 0.01       # deriva vs el resto de la epoca
    max_degradaciones: int = 2            # a la tercera, retirada definitiva

    max_reaperturas: int = 1              # reabrir un retirado, una sola vez
    max_variantes_familia: int = 4        # variantes rechazadas por familia

    max_eventos_por_setup: int = 60       # historial acotado en el JSON
    max_valores_por_feature: int = 64     # cardinalidad maxima que se cuenta

    @property
    def breakeven(self) -> float:
        """Winrate minimo para no perder dinero: 1/(1+payout)."""
        return 1.0 / (1.0 + self.payout)

    @property
    def esperanza_bajo_ruido(self) -> float:
        """Perdida esperada por operacion si el setup es una moneda al aire."""
        return 0.5 * self.payout - 0.5

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> "EvaluatorConfig":
        validos = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**validos)


# ===========================================================================
# Evidencia acumulada por setup
# ===========================================================================

def _nueva_feature() -> dict:
    return {"n": 0, "n_nulos": 0, "numerico": True,
            "suma": 0.0, "suma2": 0.0, "minimo": None, "maximo": None,
            "conteos": {}, "desbordado": False,
            "n_win": 0, "suma_win": 0.0, "n_loss": 0, "suma_loss": 0.0}


@dataclass
class SetupEvidence:
    """
    Evidencia de un setup. Distingue LO ACUMULADO EN LA EPOCA ACTUAL de lo
    acumulado en toda su vida.

    Por que epocas: cuando un setup se degrada o se reabre, arrastrar su
    historial ganador antiguo lo re-promociona al instante aunque ahora sea
    ruido. Cada epoca es una hipotesis nueva y exige evidencia nueva.
    """

    setup: str
    familia: str
    creado_en: float = field(default_factory=time.time)
    estado: str = EXPLORACION

    # --- epoca actual ---
    epoca: int = 0
    n_epoca: int = 0          # resueltas sin empate (denominador del winrate)
    wins_epoca: int = 0
    ties_epoca: int = 0
    miradas: int = 0          # veces que se ha decidido sobre esta epoca
    proximo_checkpoint: int = 0
    proxima_revision_degradacion: int = 0

    # --- vida entera ---
    n_total: int = 0
    wins_total: int = 0
    ties_total: int = 0
    pnl_total: float = 0.0

    # --- ventana movil ---
    ventana: list[int] = field(default_factory=list)

    # --- historial de decisiones ---
    degradaciones: int = 0
    reaperturas: int = 0
    promovido_en: float | None = None
    retirado_en: float | None = None
    motivo_retirada: str | None = None
    ultimo_veredicto: str = INSUFICIENTE
    alguna_vez_ganador: bool = False
    ultimo_p_ajustado: float | None = None

    features: dict[str, dict] = field(default_factory=dict)
    eventos: list[dict] = field(default_factory=list)

    @property
    def clave_hipotesis(self) -> str:
        return f"{self.setup}#e{self.epoca}"

    @property
    def winrate_epoca(self) -> float | None:
        return (self.wins_epoca / self.n_epoca) if self.n_epoca else None

    @property
    def winrate_ventana(self) -> float | None:
        return (sum(self.ventana) / len(self.ventana)) if self.ventana else None

    def anota(self, evento: str, detalle: str, cfg: EvaluatorConfig) -> None:
        self.eventos.append({"ts": time.time(), "n": self.n_epoca,
                             "evento": evento, "detalle": detalle})
        if len(self.eventos) > cfg.max_eventos_por_setup:
            del self.eventos[:-cfg.max_eventos_por_setup]

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> "SetupEvidence":
        validos = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**validos)


# ===========================================================================
# Motor
# ===========================================================================

class SelfEvaluator:
    """
    Lleva la cuenta de cada setup y decide si se opera, con que tamano, y
    cuando se retira. Todas las decisiones quedan registradas con su motivo.
    """

    def __init__(self, config: EvaluatorConfig | None = None,
                 path: Path | str = DEFAULT_PATH):
        self.cfg = config or EvaluatorConfig()
        self.path = Path(path)
        self.setups: dict[str, SetupEvidence] = {}
        # Registro MONOTONO de hipotesis probadas: clave "setup#epoca" -> p ajustado.
        # No se borra nunca. Si al retirar un setup se descontara del recuento,
        # bastaria con ir borrando los fracasos para blanquear la multiplicidad.
        self.hipotesis: dict[str, float] = {}
        self.registradas_totales: int = 0
        self.avisos_carga: list[str] = []
        self._lock = threading.RLock()

    # -- 1. acumular evidencia -------------------------------------------

    def register(self, setup: str, features: dict | None, result: Any,
                 familia: str | None = None, pnl: float | None = None) -> dict:
        """
        Acumula una operacion resuelta.

        `result` admite "WIN"/"LOSS"/"TIE", bool, o un pnl numerico. Un valor
        no reconocido LEVANTA excepcion: interpretarlo como LOSS "por si acaso"
        seria inventar datos, que es el error que este modulo persigue.

        Devuelve un dict con el estado resultante y los eventos disparados.
        """
        res = self._normaliza_resultado(result)
        with self._lock:
            ev = self._obtener(setup, familia)
            self.registradas_totales += 1

            if res == "TIE":
                ev.ties_epoca += 1
                ev.ties_total += 1
            else:
                gano = 1 if res == "WIN" else 0
                ev.n_epoca += 1
                ev.n_total += 1
                ev.wins_epoca += gano
                ev.wins_total += gano
                ev.ventana.append(gano)
                if len(ev.ventana) > self.cfg.ventana_degradacion:
                    del ev.ventana[:-self.cfg.ventana_degradacion]

            if pnl is not None:
                try:
                    ev.pnl_total += float(pnl)
                except (TypeError, ValueError):
                    pass

            self._acumula_features(ev, features, res)

            eventos: list[str] = []
            if res != "TIE":
                # Los empates no aportan informacion sobre la direccion: no
                # cuentan como observacion ni disparan decisiones.
                eventos += self._quiza_degradar(ev)
                eventos += self._quiza_checkpoint(ev)

            return {"setup": setup, "estado": ev.estado,
                    "veredicto": ev.ultimo_veredicto,
                    "n": ev.n_epoca, "eventos": eventos}

    @staticmethod
    def _normaliza_resultado(result: Any) -> str:
        if isinstance(result, str):
            r = result.strip().upper()
            if r in ("WIN", "GANADA", "GANADO", "W"):
                return "WIN"
            if r in ("LOSS", "LOSE", "PERDIDA", "PERDIDO", "L"):
                return "LOSS"
            if r in ("TIE", "DRAW", "EMPATE", "EQUAL", "T"):
                return "TIE"
            raise ValueError(f"resultado no reconocido: {result!r}")
        if isinstance(result, bool):
            return "WIN" if result else "LOSS"
        if isinstance(result, (int, float)):
            valor = float(result)
            if math.isnan(valor) or math.isinf(valor):
                raise ValueError(f"resultado no numerico utilizable: {result!r}")
            if valor > 0:
                return "WIN"
            if valor < 0:
                return "LOSS"
            return "TIE"
        raise ValueError(f"resultado no reconocido: {result!r}")

    def _obtener(self, setup: str, familia: str | None = None) -> SetupEvidence:
        ev = self.setups.get(setup)
        if ev is not None:
            return ev

        fam = familia or setup.split("#")[0].split(":")[0]
        ev = SetupEvidence(setup=setup, familia=fam,
                           proximo_checkpoint=self.cfg.min_observaciones,
                           proxima_revision_degradacion=self.cfg.ventana_degradacion)
        self.setups[setup] = ev

        # Tope de variantes por familia: reintentar la misma idea con
        # parametros nuevos tras cada rechazo es una busqueda sobre ruido.
        rechazadas = sum(1 for s in self.setups.values()
                         if s.familia == fam and s.estado == RETIRADO
                         and s.setup != setup)
        if rechazadas >= self.cfg.max_variantes_familia:
            ev.estado = RETIRADO
            ev.retirado_en = time.time()
            ev.motivo_retirada = (f"familia '{fam}' agotada: {rechazadas} variantes "
                                  f"ya rechazadas, no se admiten mas reintentos")
            ev.anota("BLOQUEADO_FAMILIA", ev.motivo_retirada, self.cfg)
        return ev

    def _acumula_features(self, ev: SetupEvidence, features: dict | None,
                          res: str) -> None:
        """
        Guarda estadistica por feature para detectar el fallo del dataset
        anterior: RSI=50 en el 99% de las filas. Un valor ausente se cuenta
        como nulo, JAMAS se imputa.
        """
        if not features:
            return
        for nombre, valor in features.items():
            st = ev.features.get(nombre)
            if st is None:
                st = _nueva_feature()
                ev.features[nombre] = st
            st["n"] += 1

            if valor is None:
                st["n_nulos"] += 1
                continue
            if isinstance(valor, float) and (math.isnan(valor) or math.isinf(valor)):
                st["n_nulos"] += 1
                continue

            if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                v = float(valor)
                st["suma"] += v
                st["suma2"] += v * v
                st["minimo"] = v if st["minimo"] is None else min(st["minimo"], v)
                st["maximo"] = v if st["maximo"] is None else max(st["maximo"], v)
                if res == "WIN":
                    st["n_win"] += 1
                    st["suma_win"] += v
                elif res == "LOSS":
                    st["n_loss"] += 1
                    st["suma_loss"] += v
                clave = f"{round(v, 4):g}"
            else:
                st["numerico"] = False
                clave = str(valor)[:40]

            conteos = st["conteos"]
            if clave in conteos:
                conteos[clave] += 1
            elif not st["desbordado"]:
                if len(conteos) >= self.cfg.max_valores_por_feature:
                    st["desbordado"] = True   # alta cardinalidad: deja de contar
                else:
                    conteos[clave] = 1

    # -- 2. veredicto -----------------------------------------------------

    def stats(self, setup: str, ventana: bool = False) -> dict:
        """
        Estadistica de la epoca actual (o de la ventana movil).
        winrate y limites son None cuando no hay datos: sin muestra no hay cifra.
        """
        with self._lock:
            ev = self.setups.get(setup)
            if ev is None:
                return {"existe": False, "n": 0, "wins": 0, "winrate": None,
                        "ci_low": None, "ci_high": None,
                        "breakeven": self.cfg.breakeven}

            if ventana:
                n, wins = len(ev.ventana), sum(ev.ventana)
                z = z_desde_alpha(self.cfg.alpha_perdedor)
            else:
                n, wins = ev.n_epoca, ev.wins_epoca
                z = z_desde_alpha(self._alpha_ic(ev))

            lo, hi = intervalo_wilson(wins, n, z)
            return {
                "existe": True, "estado": ev.estado, "familia": ev.familia,
                "epoca": ev.epoca, "n": n, "wins": wins,
                "winrate": (wins / n) if n else None,
                "ci_low": lo, "ci_high": hi, "z": z,
                "breakeven": self.cfg.breakeven,
                "miradas": ev.miradas,
                "n_total_vida": ev.n_total,
                "pnl_total": ev.pnl_total,
            }

    def verdict(self, setup: str) -> str:
        """
        INSUFICIENTE / RUIDO / GANADOR / PERDEDOR sobre la EPOCA ACTUAL.

        Consultar el veredicto NO cuenta como mirada: las miradas solo las
        gastan los checkpoints, que son los que deciden de verdad. Si contase,
        imprimir un informe endureceria el umbral, lo cual seria absurdo.
        """
        with self._lock:
            ev = self.setups.get(setup)
            if ev is None:
                return INSUFICIENTE
            return self._veredicto(ev)

    def _veredicto(self, ev: SetupEvidence) -> str:
        cfg = self.cfg
        n, wins = ev.n_epoca, ev.wins_epoca

        # Barrera dura. Aqui murieron las reglas de n=6 y n=9.
        if n < cfg.min_observaciones:
            return INSUFICIENTE

        be = cfg.breakeven

        # Lado PERDEDOR: sin corregir, porque retirar es barato y reversible.
        z_p = z_desde_alpha(cfg.alpha_perdedor)
        _, hi = intervalo_wilson(wins, n, z_p)
        if hi is not None and hi < be:
            return PERDEDOR

        # Lado GANADOR: umbral corregido por multiplicidad y por miradas.
        alpha_ic = self._alpha_ic(ev)
        lo, _ = intervalo_wilson(wins, n, z_desde_alpha(alpha_ic))
        p_crudo = pvalor_binomial_superior(wins, n, be)
        if lo is not None and lo > be and p_crudo is not None and p_crudo <= alpha_ic:
            return GANADOR
        return RUIDO

    def _alpha_ic(self, ev: SetupEvidence) -> float:
        """
        Nivel efectivo (una cola) para el lado GANADOR de este setup:
        alpha_familia / miradas.

        `alpha_familia` sale de BH sobre todos los p-valores ya ajustados por
        miradas. Dividir despues entre las miradas de este setup devuelve el
        nivel con el que hay que construir su intervalo de Wilson, de modo que
        el test y el intervalo que se imprime digan exactamente lo mismo.
        """
        alpha_fam = self._alpha_familia()
        miradas = max(1, ev.miradas) if self.cfg.penalizar_miradas else 1
        return max(1e-12, alpha_fam / miradas)

    def _alpha_familia(self) -> float:
        cfg = self.cfg
        m = max(1, len(self.hipotesis))
        if cfg.correccion == "bonferroni":
            return cfg.alpha / m
        return umbral_benjamini_hochberg(list(self.hipotesis.values()), cfg.alpha)

    # -- 3. maquina de estados -------------------------------------------

    def should_trade(self, setup: str, familia: str | None = None) -> bool:
        """True si se puede operar. El TAMANO lo da `size_factor`."""
        return self.decision(setup, familia)["permitido"]

    def size_factor(self, setup: str, familia: str | None = None) -> float:
        """0.0 retirado, `tamano_exploracion` explorando, 1.0 en produccion."""
        return self.decision(setup, familia)["tamano_relativo"]

    def state(self, setup: str, familia: str | None = None) -> str:
        return self.decision(setup, familia)["estado"]

    def decision(self, setup: str, familia: str | None = None) -> dict:
        """
        Decision completa y auditable. Tres estados explicitos:

          EXPLORACION -> se opera a tamano MINIMO solo para recoger datos.
                         Cuesta dinero a proposito: si el setup es ruido puro
                         se pierde `esperanza_bajo_ruido` por unidad y trade.
          PRODUCCION  -> veredicto GANADOR vigente, tamano normal.
          RETIRADO    -> no se opera. Permanente salvo reopen() explicito.
        """
        with self._lock:
            ev = self._obtener(setup, familia)
            v = self._veredicto(ev)
            ev.ultimo_veredicto = v

            if ev.estado == RETIRADO:
                return {"setup": setup, "estado": RETIRADO, "permitido": False,
                        "tamano_relativo": 0.0, "veredicto": v,
                        "motivo": ev.motivo_retirada or "retirado"}

            if ev.estado == PRODUCCION:
                return {"setup": setup, "estado": PRODUCCION, "permitido": True,
                        "tamano_relativo": 1.0, "veredicto": v,
                        "motivo": f"ganador confirmado con n={ev.n_epoca}"}

            faltan = max(0, self.cfg.min_observaciones - ev.n_epoca)
            motivo = (f"exploracion: faltan {faltan} observaciones para poder concluir"
                      if faltan else
                      f"exploracion: n={ev.n_epoca} sin edge demostrable todavia ({v})")
            return {"setup": setup, "estado": EXPLORACION, "permitido": True,
                    "tamano_relativo": self.cfg.tamano_exploracion,
                    "veredicto": v, "motivo": motivo}

    def _quiza_checkpoint(self, ev: SetupEvidence) -> list[str]:
        """Decide solo en checkpoints geometricos: menos miradas, menos ruido."""
        cfg = self.cfg
        if ev.estado == RETIRADO or ev.n_epoca < ev.proximo_checkpoint:
            return []

        ev.miradas += 1
        ev.proximo_checkpoint = max(
            ev.n_epoca + 1,
            int(math.ceil(ev.proximo_checkpoint * cfg.crecimiento_checkpoint)))

        # Registra/actualiza la hipotesis ANTES de aplicar BH: el p-valor de
        # este setup forma parte de la familia que corrige a todos.
        p_crudo = pvalor_binomial_superior(ev.wins_epoca, ev.n_epoca, cfg.breakeven)
        if p_crudo is None:
            return []
        p_ajustado = min(1.0, p_crudo * (ev.miradas if cfg.penalizar_miradas else 1))
        ev.ultimo_p_ajustado = p_ajustado
        self.hipotesis[ev.clave_hipotesis] = p_ajustado

        v = self._veredicto(ev)
        ev.ultimo_veredicto = v
        eventos: list[str] = []

        if v == GANADOR:
            ev.alguna_vez_ganador = True
            if ev.estado != PRODUCCION:
                ev.estado = PRODUCCION
                ev.promovido_en = time.time()
                lo, _ = intervalo_wilson(ev.wins_epoca, ev.n_epoca,
                                         z_desde_alpha(self._alpha_ic(ev)))
                detalle = (f"n={ev.n_epoca} wr={100 * ev.wins_epoca / ev.n_epoca:.1f}% "
                           f"IC_inf={100 * (lo or 0):.1f}% > be={100 * cfg.breakeven:.2f}% "
                           f"(mirada {ev.miradas}, m={len(self.hipotesis)})")
                ev.anota("PROMOVIDO", detalle, cfg)
                eventos.append(f"PROMOVIDO a PRODUCCION: {detalle}")

        elif v == PERDEDOR:
            _, hi = intervalo_wilson(ev.wins_epoca, ev.n_epoca,
                                     z_desde_alpha(cfg.alpha_perdedor))
            detalle = (f"n={ev.n_epoca} wr={100 * ev.wins_epoca / ev.n_epoca:.1f}% "
                       f"IC_sup={100 * (hi or 0):.1f}% < be={100 * cfg.breakeven:.2f}%")
            eventos.append(self._retirar(ev, f"perdedor demostrado: {detalle}"))

        elif v == RUIDO and ev.n_epoca >= cfg.max_obs_exploracion:
            # Explorar indefinidamente no es neutral: bajo H0 cada operacion
            # tiene esperanza negativa y ademas engorda la multiplicidad de
            # todos los demas setups.
            coste = abs(cfg.esperanza_bajo_ruido) * cfg.tamano_exploracion * ev.n_epoca
            detalle = (f"presupuesto de exploracion agotado ({ev.n_epoca} obs) sin "
                       f"edge demostrable; coste aproximado {coste:.1f} stakes")
            eventos.append(self._retirar(ev, detalle))

        return eventos

    def _retirar(self, ev: SetupEvidence, motivo: str) -> str:
        ev.estado = RETIRADO
        ev.retirado_en = time.time()
        ev.motivo_retirada = motivo
        ev.anota("RETIRADO", motivo, self.cfg)
        return f"RETIRADO {ev.setup}: {motivo}"

    # -- 5. degradacion ---------------------------------------------------

    def _quiza_degradar(self, ev: SetupEvidence) -> list[str]:
        """
        Un GANADOR cuyo rendimiento RECIENTE cae de forma significativa vuelve
        a EXPLORACION (tamano minimo) y empieza epoca nueva.

        Dos alarmas, cualquiera basta:
          a) la ventana movil es demostrablemente perdedora (IC_sup < break-even)
          b) la ventana es significativamente peor que el resto de la epoca

        La ventana se revisa cada `revisar_degradacion_cada` operaciones, no
        despues de cada una: mirar continuamente fabrica falsas alarmas. Aqui
        si se acepta cierta tasa de falsas alarmas porque degradar solo baja el
        tamano, no destruye evidencia.
        """
        cfg = self.cfg
        if ev.estado != PRODUCCION:
            return []
        if len(ev.ventana) < cfg.ventana_degradacion:
            return []
        if ev.n_epoca < ev.proxima_revision_degradacion:
            return []
        ev.proxima_revision_degradacion = ev.n_epoca + cfg.revisar_degradacion_cada

        n_v, w_v = len(ev.ventana), sum(ev.ventana)
        _, hi = intervalo_wilson(w_v, n_v, z_desde_alpha(cfg.alpha_perdedor))
        motivo = None
        if hi is not None and hi < cfg.breakeven:
            motivo = (f"ventana reciente perdedora: n={n_v} wr={100 * w_v / n_v:.1f}% "
                      f"IC_sup={100 * hi:.1f}% < be={100 * cfg.breakeven:.2f}%")
        else:
            n_r, w_r = ev.n_epoca - n_v, ev.wins_epoca - w_v
            z = z_dos_proporciones(w_v, n_v, w_r, n_r) if n_r > 0 else None
            if z is not None and z < -z_desde_alpha(cfg.alpha_degradacion):
                motivo = (f"deriva: ventana {100 * w_v / n_v:.1f}% vs resto "
                          f"{100 * w_r / n_r:.1f}% (z={z:.2f})")
        if motivo is None:
            return []

        ev.degradaciones += 1
        if ev.degradaciones >= cfg.max_degradaciones:
            return [self._retirar(
                ev, f"degradado {ev.degradaciones} veces; {motivo}")]

        ev.anota("DEGRADADO", motivo, cfg)
        self._nueva_epoca(ev)
        return [f"DEGRADADO {ev.setup} -> EXPLORACION: {motivo}"]

    def _nueva_epoca(self, ev: SetupEvidence) -> None:
        """
        Epoca nueva = hipotesis nueva. Se borran los contadores de la epoca
        (no los de la vida) para que el historial ganador antiguo no vuelva a
        promocionar el setup sin evidencia fresca.
        """
        ev.epoca += 1
        ev.n_epoca = 0
        ev.wins_epoca = 0
        ev.ties_epoca = 0
        ev.miradas = 0
        ev.ventana.clear()
        ev.proximo_checkpoint = self.cfg.min_observaciones
        ev.proxima_revision_degradacion = self.cfg.ventana_degradacion
        ev.estado = EXPLORACION
        ev.promovido_en = None
        ev.ultimo_veredicto = INSUFICIENTE
        ev.ultimo_p_ajustado = None

    # -- reapertura explicita ---------------------------------------------

    def reopen(self, setup: str, motivo: str) -> bool:
        """
        Reabre un setup RETIRADO. Devuelve False si no procede.

        Exige un motivo escrito y esta topado: el patron "rechazado -> lo
        reabro con otro parametro -> rechazado -> lo reabro otra vez" es
        literalmente una busqueda de p<0.05 sobre ruido. Cada reapertura abre
        epoca nueva, asi que hay que volver a ganarse las 200 observaciones.
        """
        motivo = (motivo or "").strip()
        if not motivo:
            raise ValueError("reopen exige un motivo escrito y no vacio")
        with self._lock:
            ev = self.setups.get(setup)
            if ev is None or ev.estado != RETIRADO:
                return False
            if ev.reaperturas >= self.cfg.max_reaperturas:
                ev.anota("REAPERTURA_DENEGADA",
                         f"tope de {self.cfg.max_reaperturas} alcanzado: {motivo}",
                         self.cfg)
                return False
            ev.reaperturas += 1
            ev.retirado_en = None
            ev.motivo_retirada = None
            ev.anota("REABIERTO", motivo, self.cfg)
            self._nueva_epoca(ev)
            return True

    # -- diagnostico de features ------------------------------------------

    def feature_health(self, setup: str) -> list[str]:
        """
        Detecta el fallo que arruino las 500 operaciones anteriores: features
        constantes o casi siempre ausentes. Un modelo entrenado sobre RSI=50
        en el 99% de las filas no aprende nada.
        """
        with self._lock:
            ev = self.setups.get(setup)
            if ev is None:
                return []
            avisos = []
            for nombre, st in sorted(ev.features.items()):
                n = st["n"]
                if n < 30:
                    continue
                frac_nula = st["n_nulos"] / n
                if frac_nula >= 0.5:
                    avisos.append(f"{nombre}: ausente en {100 * frac_nula:.0f}% de las obs")
                    continue
                observados = n - st["n_nulos"]
                if observados <= 0:
                    continue
                conteos = st["conteos"]
                if conteos and not st["desbordado"]:
                    valor, cuenta = max(conteos.items(), key=lambda kv: kv[1])
                    dom = cuenta / observados
                    if dom >= 0.9:
                        avisos.append(
                            f"{nombre}: valor '{valor}' en {100 * dom:.0f}% de las obs "
                            f"-> CONSTANTE, no aporta informacion")
            return avisos

    def feature_split(self, setup: str) -> list[tuple[str, float, float, int, int]]:
        """
        Media de cada feature numerica en aciertos vs fallos.

        DIAGNOSTICO, NO base para crear reglas. Comparar k features y quedarse
        con la que mas separa es exactamente la fabrica de falsos positivos que
        este modulo intenta cerrar. Sirve para generar hipotesis que luego hay
        que probar como un setup mas, con sus 200 observaciones.
        """
        with self._lock:
            ev = self.setups.get(setup)
            if ev is None:
                return []
            out = []
            for nombre, st in sorted(ev.features.items()):
                if not st["numerico"] or st["n_win"] < 30 or st["n_loss"] < 30:
                    continue
                out.append((nombre, st["suma_win"] / st["n_win"],
                            st["suma_loss"] / st["n_loss"], st["n_win"], st["n_loss"]))
            return out

    # -- 6. informe --------------------------------------------------------

    def report(self, detalle: bool = False) -> str:
        with self._lock:
            cfg = self.cfg
            be = cfg.breakeven
            alpha_fam = self._alpha_familia()
            lineas = [
                "=" * 86,
                "AUTO-EVALUACION DE SETUPS",
                "=" * 86,
                f"Payout {cfg.payout:.3f} -> break-even {100 * be:.2f}%   "
                f"(operar ruido cuesta {cfg.esperanza_bajo_ruido:+.3f} por stake y trade)",
                f"Minimo para concluir: {cfg.min_observaciones} obs.   "
                f"Correccion: {cfg.correccion.upper()} sobre m={len(self.hipotesis)} "
                f"hipotesis probadas -> alpha familia {alpha_fam:.2e}"
                + ("   + Bonferroni por miradas" if cfg.penalizar_miradas else ""),
                f"Operaciones registradas: {self.registradas_totales}",
                "",
                f"{'SETUP':<26}{'ESTADO':<12}{'N':>6}{'WR':>8}"
                f"{'IC95 INF':>10}{'IC SUP':>9}{'MIR':>5}  VEREDICTO",
                "-" * 86,
            ]

            if not self.setups:
                lineas.append("  (sin setups registrados)")

            for nombre in sorted(self.setups):
                ev = self.setups[nombre]
                v = self._veredicto(ev)
                ev.ultimo_veredicto = v
                n, w = ev.n_epoca, ev.wins_epoca
                if n:
                    z_g = z_desde_alpha(self._alpha_ic(ev))
                    lo, _ = intervalo_wilson(w, n, z_g)
                    _, hi = intervalo_wilson(w, n, z_desde_alpha(cfg.alpha_perdedor))
                    txt_wr = f"{100 * w / n:6.2f}%"
                    txt_lo = f"{100 * lo:8.2f}%"
                    txt_hi = f"{100 * hi:7.2f}%"
                else:
                    txt_wr, txt_lo, txt_hi = "     --", "      --", "     --"
                marca = "*" if ev.epoca else " "
                lineas.append(
                    f"{nombre[:25]:<25}{marca}{ev.estado:<12}{n:>6}{txt_wr:>8}"
                    f"{txt_lo:>10}{txt_hi:>9}{ev.miradas:>5}  {v}")

            lineas.append("-" * 86)
            lineas.append("* = el setup va por su segunda epoca o posterior "
                          "(degradado o reabierto): su historial antiguo no cuenta.")
            lineas.append("IC INF usa el nivel corregido (decidir GANADOR); "
                          "IC SUP usa el nivel sin corregir (decidir PERDEDOR).")

            retirados = [e for e in self.setups.values() if e.estado == RETIRADO]
            if retirados:
                lineas.append("")
                lineas.append("RETIRADOS:")
                for ev in sorted(retirados, key=lambda e: e.setup):
                    lineas.append(f"  {ev.setup[:30]:<30} {ev.motivo_retirada}")

            avisos = []
            for nombre in sorted(self.setups):
                for a in self.feature_health(nombre):
                    avisos.append(f"  {nombre[:24]:<24} {a}")
            if avisos:
                lineas.append("")
                lineas.append("FEATURES SOSPECHOSAS (el error que arruino el dataset previo):")
                lineas.extend(avisos)

            if detalle:
                for nombre in sorted(self.setups):
                    split = self.feature_split(nombre)
                    if not split:
                        continue
                    lineas.append("")
                    lineas.append(f"MEDIAS WIN/LOSS de {nombre} "
                                  f"(diagnostico, NO regla operable):")
                    for f, mw, ml, nw, nl in split:
                        lineas.append(f"  {f[:22]:<22} win={mw:10.4f} (n={nw:<5}) "
                                      f"loss={ml:10.4f} (n={nl})")
                    for ev_ in (self.setups[nombre],):
                        if ev_.eventos:
                            lineas.append(f"  eventos de {nombre}:")
                            for e in ev_.eventos[-6:]:
                                lineas.append(f"    n={e['n']:<6}{e['evento']:<22}"
                                              f"{e['detalle']}")

            en_prod = sum(1 for e in self.setups.values() if e.estado == PRODUCCION)
            lineas.append("")
            lineas.append(f"RESUMEN: {en_prod} en produccion, "
                          f"{sum(1 for e in self.setups.values() if e.estado == EXPLORACION)} "
                          f"en exploracion, {len(retirados)} retirados.")
            if en_prod == 0:
                lineas.append("Ningun setup ha demostrado edge todavia. Operar solo a "
                              "tamano de exploracion es la conducta correcta, no un fallo.")
            return "\n".join(lineas)

    def resumen(self) -> dict:
        with self._lock:
            return {
                "setups": len(self.setups),
                "en_produccion": sorted(s for s, e in self.setups.items()
                                        if e.estado == PRODUCCION),
                "en_exploracion": sorted(s for s, e in self.setups.items()
                                         if e.estado == EXPLORACION),
                "retirados": sorted(s for s, e in self.setups.items()
                                    if e.estado == RETIRADO),
                "hipotesis_probadas": len(self.hipotesis),
                "alpha_familia": self._alpha_familia(),
                "breakeven": self.cfg.breakeven,
                "operaciones": self.registradas_totales,
            }

    # -- 7. persistencia ---------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": VERSION_ESTADO,
            "guardado_en": time.time(),
            "config": self.cfg.to_dict(),
            "hipotesis": dict(self.hipotesis),
            "registradas_totales": self.registradas_totales,
            "setups": {k: v.to_dict() for k, v in self.setups.items()},
        }

    @staticmethod
    def _firma(payload: dict) -> str:
        crudo = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(crudo.encode("utf-8")).hexdigest()

    def guardar(self, path: Path | str | None = None) -> Path:
        """
        Escritura atomica con copia de seguridad y firma.

        Un corte a media escritura no puede dejar el fichero principal a
        medias: se escribe en .tmp, se hace fsync, se copia el bueno anterior
        a .bak y solo entonces se hace os.replace (atomico tambien en Windows).
        La firma sha256 detecta ademas un fichero truncado por otras vias.
        """
        with self._lock:
            destino = Path(path or self.path)
            destino.parent.mkdir(parents=True, exist_ok=True)
            payload = self.to_dict()
            payload["firma"] = self._firma(payload)

            tmp = destino.with_name(destino.name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1)
                fh.flush()
                os.fsync(fh.fileno())

            if destino.exists():
                try:
                    shutil.copy2(destino, destino.with_name(destino.name + ".bak"))
                except OSError:
                    pass
            os.replace(tmp, destino)
            return destino

    @classmethod
    def cargar(cls, path: Path | str = DEFAULT_PATH,
               config: EvaluatorConfig | None = None,
               permitir_estado_vacio: bool = False) -> "SelfEvaluator":
        """
        Carga el estado. Si el fichero principal esta corrupto usa el .bak.

        Si ambos fallan LEVANTA EstadoCorrupto en lugar de empezar de cero en
        silencio: arrancar vacio equivale a olvidar que un setup fue retirado y
        volver a operarlo, que es exactamente el fallo que hay que evitar.
        """
        destino = Path(path)
        candidatos = [destino, destino.with_name(destino.name + ".bak")]
        avisos: list[str] = []

        for i, cand in enumerate(candidatos):
            if not cand.exists():
                continue
            try:
                with open(cand, encoding="utf-8") as fh:
                    datos = json.load(fh)
                firma = datos.pop("firma", None)
                if firma is not None and firma != cls._firma(datos):
                    raise ValueError("firma sha256 no coincide (fichero incompleto)")
            except (json.JSONDecodeError, ValueError, OSError) as exc:
                avisos.append(f"{cand.name} ilegible: {exc}")
                continue

            ev = cls(config or EvaluatorConfig.from_dict(datos.get("config", {})),
                     path=destino)
            ev.hipotesis = {str(k): float(v)
                            for k, v in (datos.get("hipotesis") or {}).items()}
            ev.registradas_totales = int(datos.get("registradas_totales", 0))
            for nombre, d in (datos.get("setups") or {}).items():
                ev.setups[nombre] = SetupEvidence.from_dict(d)
            if i == 1:
                avisos.append("recuperado desde la copia .bak: puede faltar la "
                              "ultima sesion de operaciones")
            ev.avisos_carga = avisos
            return ev

        if avisos and not permitir_estado_vacio:
            raise EstadoCorrupto(
                "no se pudo cargar el estado de auto-evaluacion: " + "; ".join(avisos)
                + ". Arrancar vacio reabriria setups ya retirados; pasa "
                  "permitir_estado_vacio=True si de verdad es lo que quieres.")

        nuevo = cls(config or EvaluatorConfig(), path=destino)
        nuevo.avisos_carga = avisos
        return nuevo


_evaluator: SelfEvaluator | None = None


def get_evaluator(path: Path | str = DEFAULT_PATH,
                  config: EvaluatorConfig | None = None) -> SelfEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = SelfEvaluator.cargar(path, config)
    return _evaluator


# ===========================================================================
# Auto-verificacion
# ===========================================================================

def _simular(ev: SelfEvaluator, setup: str, p: float, n: int, rng,
             familia: str | None = None, exacto: bool = False) -> None:
    """Alimenta `n` resultados. Con exacto=True el numero de aciertos es
    exactamente round(p*n) barajado: se prueba la REGLA, no el muestreo."""
    if exacto:
        wins = round(p * n)
        seq = [1] * wins + [0] * (n - wins)
        rng.shuffle(seq)
    else:
        seq = [1 if rng.random() < p else 0 for _ in range(n)]
    for i, g in enumerate(seq):
        ev.register(setup, {"rsi": 50.0 + 10 * rng.random(), "hora": i % 24},
                    "WIN" if g else "LOSS", familia=familia)


def _autoverificacion(repeticiones_mc: int = 200) -> int:
    import random
    import tempfile

    fallos = 0

    def check(titulo: str, ok: bool, extra: str = "") -> None:
        nonlocal fallos
        if not ok:
            fallos += 1
        print(f"  [{'OK ' if ok else 'FALLO'}] {titulo}{(' -> ' + extra) if extra else ''}")

    cfg = EvaluatorConfig()
    print("=" * 86)
    print("AUTO-VERIFICACION DEL MOTOR DE AUTO-EVALUACION")
    print("=" * 86)
    print(f"payout={cfg.payout}  break-even={100 * cfg.breakeven:.2f}%  "
          f"min_observaciones={cfg.min_observaciones}  alpha={cfg.alpha} ({cfg.correccion})")
    print()

    rng = random.Random(20260730)
    tmpdir = Path(tempfile.mkdtemp(prefix="selfeval_"))
    ev = SelfEvaluator(cfg, path=tmpdir / "estado.json")

    # --- 1) moneda al aire, 5000 lanzamientos --------------------------
    print("1) MONEDA AL AIRE, 5000 lanzamientos (p=0.50)")
    _simular(ev, "moneda_al_aire", 0.50, 5000, rng, familia="control")
    st = ev.stats("moneda_al_aire")
    e = ev.setups["moneda_al_aire"]
    print(f"   n={st['n']} wr={100 * st['winrate']:.2f}% "
          f"IC[{100 * st['ci_low']:.2f}%, {100 * st['ci_high']:.2f}%] "
          f"veredicto={ev.verdict('moneda_al_aire')} estado={e.estado}")
    print(f"   motivo: {e.motivo_retirada}")
    check("la moneda NUNCA alcanzo el veredicto GANADOR",
          not e.alguna_vez_ganador)
    check("la moneda NUNCA llego a PRODUCCION", e.promovido_en is None)
    check("should_trade() = False para la moneda", not ev.should_trade("moneda_al_aire"))
    print()

    # --- 2) setup real al 60% con 500 observaciones --------------------
    print("2) SETUP CON EDGE REAL, 60% y 500 observaciones")
    _simular(ev, "sr_confirmado_m5", 0.60, 500, rng, familia="sr", exacto=True)
    st = ev.stats("sr_confirmado_m5")
    e = ev.setups["sr_confirmado_m5"]
    print(f"   n={st['n']} wr={100 * st['winrate']:.2f}% "
          f"IC_inf={100 * st['ci_low']:.2f}% (z={st['z']:.3f}, miradas={st['miradas']}, "
          f"m={len(ev.hipotesis)}) veredicto={ev.verdict('sr_confirmado_m5')} "
          f"estado={e.estado}")
    check("veredicto GANADOR", ev.verdict("sr_confirmado_m5") == GANADOR)
    check("estado PRODUCCION", e.estado == PRODUCCION)
    check("tamano relativo 1.0", ev.size_factor("sr_confirmado_m5") == 1.0)
    print()

    # --- 3) 58% pero solo 30 observaciones -----------------------------
    print("3) SETUP APARENTEMENTE BUENO, 58% pero solo 30 observaciones")
    _simular(ev, "fakeout_rapido", 0.58, 30, rng, familia="fakeout", exacto=True)
    st = ev.stats("fakeout_rapido")
    print(f"   n={st['n']} wr={100 * st['winrate']:.2f}% "
          f"IC[{100 * st['ci_low']:.2f}%, {100 * st['ci_high']:.2f}%] "
          f"veredicto={ev.verdict('fakeout_rapido')} "
          f"estado={ev.state('fakeout_rapido')}")
    check("veredicto INSUFICIENTE", ev.verdict("fakeout_rapido") == INSUFICIENTE)
    check("estado EXPLORACION", ev.state("fakeout_rapido") == EXPLORACION)
    check("tamano relativo minimo",
          ev.size_factor("fakeout_rapido") == cfg.tamano_exploracion)
    print()

    # --- 4) degradacion -------------------------------------------------
    print("4) DEGRADACION de un ganador que deja de funcionar")
    ev2 = SelfEvaluator(EvaluatorConfig(), path=tmpdir / "deg.json")
    _simular(ev2, "tendencia_ny", 0.62, 400, rng, familia="tend", exacto=True)
    estado_antes = ev2.state("tendencia_ny")
    _simular(ev2, "tendencia_ny", 0.35, 150, rng, familia="tend", exacto=True)
    e2 = ev2.setups["tendencia_ny"]
    print(f"   antes={estado_antes} -> despues={e2.estado} epoca={e2.epoca} "
          f"degradaciones={e2.degradaciones}")
    for x in e2.eventos[-2:]:
        print(f"   evento: {x['evento']} :: {x['detalle']}")
    check("estaba en PRODUCCION antes de degradarse", estado_antes == PRODUCCION)
    check("detecto la degradacion", e2.degradaciones >= 1)
    check("volvio a EXPLORACION con epoca nueva y contadores a cero",
          e2.estado in (EXPLORACION, RETIRADO) and e2.epoca >= 1)
    print()

    # --- 5) retirada permanente y reapertura topada --------------------
    print("5) RETIRADA PERMANENTE Y REAPERTURA TOPADA")
    ok_reabrir = ev.reopen("moneda_al_aire", "quiero probar otra vez con otro horario")
    ok_reabrir2 = ev.reopen("moneda_al_aire", "y otra vez mas")
    print(f"   primera reapertura={ok_reabrir}  segunda reapertura={ok_reabrir2} "
          f"(tope={cfg.max_reaperturas})")
    check("la primera reapertura exige motivo y abre epoca nueva",
          ok_reabrir and ev.setups["moneda_al_aire"].epoca == 1)
    check("la segunda reapertura se deniega", ok_reabrir2 is False)
    ev3 = SelfEvaluator(EvaluatorConfig(), path=tmpdir / "fam.json")
    for k in range(6):
        _simular(ev3, f"variante_{k}", 0.50, 900, rng, familia="misma_idea")
    bloqueados = [s for s, e in ev3.setups.items()
                  if e.motivo_retirada and "familia" in e.motivo_retirada]
    print(f"   variantes de la misma familia bloqueadas de entrada: {bloqueados}")
    check("la familia se agota tras varias variantes rechazadas", len(bloqueados) >= 1)
    print()

    # --- 6) persistencia ------------------------------------------------
    print("6) PERSISTENCIA JSON")
    p = ev.guardar()
    # guardar() solo respalda a .bak la version ANTERIOR al escribir; con una
    # sola llamada no hay "anterior" que respaldar. Se guarda dos veces, como
    # ocurre en produccion (cada cierre de operacion dispara un guardar()),
    # para que exista un .bak real antes de simular el corte a media escritura.
    p = ev.guardar()
    recargado = SelfEvaluator.cargar(p)
    igual = (recargado.resumen() == ev.resumen())
    with open(p, "r+", encoding="utf-8") as fh:   # simula corte a media escritura
        contenido = fh.read()
        fh.seek(0)
        fh.write(contenido[: len(contenido) // 2])
        fh.truncate()
    recuperado = SelfEvaluator.cargar(p)
    print(f"   estado recargado identico: {igual}")
    print(f"   tras truncar el fichero: {recuperado.avisos_carga[:1]}")
    check("recarga fiel del estado", igual)
    # moneda_al_aire ya no esta en RETIRADO en este punto: la seccion 5 la
    # reabrio (epoca 1). El .bak debe reflejar ESE estado, no el de retirada
    # original; comparar epoca es lo que de verdad prueba que se recupero la
    # sesion correcta y no una version vieja o vacia.
    check("un fichero truncado se recupera del .bak",
          any("bak" in a for a in recuperado.avisos_carga)
          and recuperado.setups["moneda_al_aire"].estado == ev.setups["moneda_al_aire"].estado
          and recuperado.setups["moneda_al_aire"].epoca == ev.setups["moneda_al_aire"].epoca == 1)
    try:
        (p.with_name(p.name + ".bak")).unlink()
        SelfEvaluator.cargar(p)
        check("sin .bak valido se levanta EstadoCorrupto", False)
    except EstadoCorrupto:
        check("sin .bak valido se levanta EstadoCorrupto", True)
    print()

    # --- 7) potencia real y tasa de falsos positivos --------------------
    print(f"7) MONTE CARLO ({repeticiones_mc} repeticiones): cuantas veces se")
    print("   promociona de verdad cada tipo de setup, con muestreo aleatorio")
    prom_edge = prom_moneda = 0
    for r in range(repeticiones_mc):
        rr = random.Random(1000 + r)
        m1 = SelfEvaluator(EvaluatorConfig(), path=tmpdir / "mc.json")
        _simular(m1, "ruido_acompanante", 0.50, 260, rr)   # 2a hipotesis, m=2
        _simular(m1, "edge60", 0.60, 500, rr)
        if m1.setups["edge60"].alguna_vez_ganador:
            prom_edge += 1
        m2 = SelfEvaluator(EvaluatorConfig(), path=tmpdir / "mc2.json")
        _simular(m2, "ruido_acompanante", 0.50, 260, rr)
        _simular(m2, "moneda", 0.50, 1000, rr)
        if m2.setups["moneda"].alguna_vez_ganador:
            prom_moneda += 1
    lo_e, hi_e = intervalo_wilson(prom_edge, repeticiones_mc)
    lo_m, hi_m = intervalo_wilson(prom_moneda, repeticiones_mc)
    print(f"   edge real 60% n=500 : promovido {prom_edge}/{repeticiones_mc} "
          f"= {100 * prom_edge / repeticiones_mc:.1f}%  IC95[{100 * lo_e:.1f}%, {100 * hi_e:.1f}%]")
    print(f"   moneda 50%  n=1000  : promovido {prom_moneda}/{repeticiones_mc} "
          f"= {100 * prom_moneda / repeticiones_mc:.1f}%  IC95[{100 * lo_m:.1f}%, {100 * hi_m:.1f}%]")
    check("la moneda se promociona en menos del 2% de las repeticiones",
          prom_moneda / repeticiones_mc < 0.02,
          f"{prom_moneda}/{repeticiones_mc}")
    check("el edge real se detecta en mas del 50% de las repeticiones",
          prom_edge / repeticiones_mc > 0.50,
          f"{prom_edge}/{repeticiones_mc}")
    print()

    # --- 8) features degeneradas ---------------------------------------
    print("8) DETECCION DE FEATURES DEGENERADAS (el bug del RSI=50)")
    ev4 = SelfEvaluator(EvaluatorConfig(), path=tmpdir / "feat.json")
    for i in range(300):
        rsi = 50.0 if i % 100 else 61.0        # constante en el 99% de los casos
        ev4.register("setup_con_features_malas",
                     {"rsi_at_touch": rsi, "zone_strength": None,
                      "atr_pct": 0.01 + 0.001 * rng.random()},
                     "WIN" if rng.random() < 0.5 else "LOSS")
    avisos = ev4.feature_health("setup_con_features_malas")
    for a in avisos:
        print(f"   aviso: {a}")
    check("detecta la feature constante",
          any("rsi_at_touch" in a and "CONSTANTE" in a for a in avisos))
    check("detecta la feature siempre ausente",
          any("zone_strength" in a and "ausente" in a for a in avisos))
    check("no marca la feature sana",
          not any("atr_pct" in a for a in avisos))
    print()

    print(ev.report())
    print()
    print("=" * 86)
    print(f"RESULTADO: {'TODAS LAS COMPROBACIONES PASAN' if fallos == 0 else str(fallos) + ' COMPROBACIONES FALLIDAS'}")
    print("=" * 86)
    return fallos


if __name__ == "__main__":
    import sys
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    raise SystemExit(1 if _autoverificacion(reps) else 0)
