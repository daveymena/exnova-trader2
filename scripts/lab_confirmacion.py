# -*- coding: utf-8 -*-
"""
Laboratorio del VALOR DE ESPERAR CONFIRMACION en zonas de soporte/resistencia.

Pregunta que responde
---------------------
El metodo del usuario dice "espero confirmacion". Esperar cuesta: el precio ya
se movio, la entrada es peor y algunas senales se pierden. La pregunta empirica
es si esa espera COMPRA INFORMACION o solo RETRASA la misma apuesta.

Aqui se mide, sobre los mismos toques de zona S/R confirmada, que pasa con:

  inmediato        entrar al cierre de la vela que toca la zona
  demoraN          esperar N velas SIN pedir nada (control puro de retraso)
  confN            esperar N velas que cierren a favor del rebote
  rechazo          exigir vela de rechazo (mecha contra la zona >= 50% del rango
                   y cierre del lado correcto)
  stoch_giro       exigir giro del estocastico (%K cruza %D viniendo de extremo)
  combinaciones    rechazo+conf, conf+stoch, rechazo+stoch

El control `demoraN` es la pieza clave del diseno: si `conf2` y `demora2` dan el
mismo winrate, entonces las dos velas de confirmacion no aportan informacion,
solo desplazan la entrada. Sin ese control cualquier filtro parece util.

Salvaguardas (sin ellas este analisis se engana solo)
----------------------------------------------------
1. Sin look-ahead. Un pivote de fractal en la barra i solo se conoce en la barra
   i+wing; la zona no existe antes. Toda condicion se evalua sobre velas ya
   cerradas y la entrada es SIEMPRE la apertura de la vela siguiente.
2. Continuidad temporal. Una entrada solo vale si las velas de la operacion son
   minutos consecutivos: en los indices reales hay huecos de noche y fin de
   semana, y una expiracion de 5 min que salta un fin de semana no es un trade.
3. Todo winrate va con intervalo de Wilson al 95%, y ademas con correccion de
   Bonferroni por el numero total de pruebas lanzadas.
4. Trade-off explicito. Un filtro que sube el winrate del 50% al 52% pero deja
   40 senales de 2000 NO es una mejora: se reporta senales retenidas, esperanza
   por senal y esperanza TOTAL acumulada, que es lo que se lleva a la cuenta.
5. Nada de valores por defecto. Si el ATR, el estocastico o el nivel no se
   pueden calcular, la funcion devuelve None y el toque se descarta. El default
   plausible (RSI=50) es lo que arruino las 500 operaciones anteriores.

Uso:
    python scripts/lab_confirmacion.py
    python scripts/lab_confirmacion.py --payout 0.86 --expiries 1,3,5
    python scripts/lab_confirmacion.py --wing 3 --tol-atr 0.25 --vigencia 240
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.backtest.indicators import atr, fractals, stochastic   # noqa: E402
from bot.backtest.replay import wilson_interval                 # noqa: E402

HISTORY_DIR = ROOT / "bot" / "data" / "history"

# Muestra minima para que un resultado se considere algo mas que anecdota.
MIN_MUESTRA = 200

# Umbrales del estocastico para considerar "zona extrema".
STOCH_BAJO = 20.0
STOCH_ALTO = 80.0

# Fraccion minima del rango que debe ocupar la mecha para llamarlo rechazo.
MECHA_MIN = 0.50


# ---------------------------------------------------------------------------
# Utilidades estadisticas
# ---------------------------------------------------------------------------

def norm_ppf(p: float) -> float:
    """Inversa de la normal estandar por biseccion sobre erf. Sin scipy."""
    if not 0.0 < p < 1.0:
        return float("nan")
    lo, hi = -12.0, 12.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def z_dos_proporciones(w1: int, n1: int, w2: int, n2: int) -> float | None:
    """
    z de diferencia de proporciones (variante filtrada frente a inmediato).

    Aviso: las dos muestras NO son independientes, la filtrada es subconjunto de
    la otra, asi que este z es orientativo y conservador en el sentido malo
    (tiende a exagerar la significacion). Sirve para descartar diferencias
    obviamente ruidosas, no para declarar hallazgos.
    """
    if n1 <= 0 or n2 <= 0:
        return None
    p1, p2 = w1 / n1, w2 / n2
    pool = (w1 + w2) / (n1 + n2)
    var = pool * (1 - pool) * (1 / n1 + 1 / n2)
    if var <= 0:
        return None
    return (p1 - p2) / math.sqrt(var)


# ---------------------------------------------------------------------------
# Carga y preparacion
# ---------------------------------------------------------------------------

def cargar_historico(filtro: str | None = None) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if not HISTORY_DIR.exists():
        return out
    pedidos = [a.strip() for a in filtro.split(",")] if filtro else None
    for p in sorted(HISTORY_DIR.glob("*_60.parquet")):
        activo = p.stem[:-3]
        if pedidos and activo not in pedidos:
            continue
        try:
            df = pd.read_parquet(p).sort_index()
        except Exception as e:                      # pragma: no cover
            print(f"  aviso: no se pudo leer {p.name}: {e}")
            continue
        if len(df) >= 1000:
            out[activo] = df
    return out


def grupo_de(activo: str) -> str:
    """Los feeds sinteticos del broker y el mercado real no son lo mismo."""
    return "OTC" if "-OTC" in activo.upper() else "REAL"


@dataclass
class Contexto:
    """Arrays del activo ya alineados. Todo indice es posicion de vela M1."""
    activo: str
    n: int
    apertura: np.ndarray
    maximo: np.ndarray
    minimo: np.ndarray
    cierre: np.ndarray
    atr: np.ndarray
    k: np.ndarray
    d: np.ndarray
    piv_alto: np.ndarray
    piv_bajo: np.ndarray
    minuto: np.ndarray          # minuto absoluto, para exigir velas consecutivas


def preparar(df: pd.DataFrame, activo: str, wing: int) -> Contexto | None:
    """Calcula indicadores. Devuelve None si el historico no da para nada."""
    if len(df) < 500:
        return None
    serie_atr = atr(df, 14)
    k, d = stochastic(df, 14, 3, 3)
    piv_alto, piv_bajo = fractals(df, wing=wing)
    minuto = df.index.astype("int64").to_numpy() // 60_000_000_000
    return Contexto(
        activo=activo,
        n=len(df),
        apertura=df["open"].to_numpy(dtype=float),
        maximo=df["high"].to_numpy(dtype=float),
        minimo=df["low"].to_numpy(dtype=float),
        cierre=df["close"].to_numpy(dtype=float),
        atr=serie_atr.to_numpy(dtype=float),
        k=k.to_numpy(dtype=float),
        d=d.to_numpy(dtype=float),
        piv_alto=piv_alto.to_numpy(dtype=bool),
        piv_bajo=piv_bajo.to_numpy(dtype=bool),
        minuto=minuto,
    )


# ---------------------------------------------------------------------------
# Deteccion de zonas y toques, sin look-ahead
# ---------------------------------------------------------------------------

@dataclass
class Toque:
    """Un toque de zona ya confirmada. `t` es la vela que toca (cerrada)."""
    t: int
    nivel: float
    tipo: str                   # "soporte" o "resistencia"
    direc: int                  # +1 rebote alcista (CALL), -1 bajista (PUT)
    tol: float


class _Zona:
    __slots__ = ("nivel", "tipo", "muere", "viva")

    def __init__(self, nivel: float, tipo: str, muere: int):
        self.nivel = nivel
        self.tipo = tipo
        self.muere = muere
        self.viva = True


def detectar_toques(ctx: Contexto, wing: int, tol_atr: float,
                    vigencia: int, sep_min: int) -> tuple[list[Toque], int]:
    """
    Recorre las velas una a una manteniendo las zonas vivas.

    Reglas anti look-ahead:
      - un pivote en la vela i solo se conoce cuando cierra la vela i+wing, asi
        que la zona se da de alta exactamente en esa vela y ni un minuto antes;
      - la decision se toma al CIERRE de la vela t, con lo cual todo lo que se
        mira (ATR, estocastico, la propia vela t) ya ocurrio.

    Reglas para que un toque sea un toque y no ruido repetido:
      - la vela entra en la banda nivel +- tol y la anterior estaba fuera
        (aproximacion limpia, no veinte velas pegadas al nivel contadas veinte
        veces);
      - la zona muere si el precio cierra al otro lado por mas de tol (nivel
        roto ya no es soporte) o si caduca por antiguedad;
      - separacion minima entre toques aceptados del mismo activo, para que las
        operaciones no se solapen tanto que el intervalo de confianza mienta.

    Devuelve (toques, zonas_dadas_de_alta).
    """
    toques: list[Toque] = []
    vivas: list[_Zona] = []
    altas = 0
    ultimo_toque = -10 ** 9

    for t in range(wing + 1, ctx.n):
        # 1. Alta de zonas cuyo pivote acaba de confirmarse en esta vela.
        i = t - wing
        if ctx.piv_alto[i]:
            altas += _alta_zona(vivas, float(ctx.maximo[i]), "resistencia",
                                t + vigencia, ctx.atr[t], tol_atr)
        if ctx.piv_bajo[i]:
            altas += _alta_zona(vivas, float(ctx.minimo[i]), "soporte",
                                t + vigencia, ctx.atr[t], tol_atr)

        # 2. Caducidad.
        if vivas:
            vivas = [z for z in vivas if z.viva and z.muere > t]
        if not vivas:
            continue

        a = ctx.atr[t]
        if not np.isfinite(a) or a <= 0:
            continue                    # sin ATR no hay tolerancia: se descarta
        tol = tol_atr * a

        # 3. Deteccion de toque (una zona como mucho por vela: la mas cercana).
        candidata: _Zona | None = None
        mejor_dist = float("inf")
        for z in vivas:
            if z.tipo == "soporte":
                dentro = ctx.minimo[t] <= z.nivel + tol and ctx.maximo[t] >= z.nivel - tol
                fuera_antes = ctx.minimo[t - 1] > z.nivel + tol
            else:
                dentro = ctx.maximo[t] >= z.nivel - tol and ctx.minimo[t] <= z.nivel + tol
                fuera_antes = ctx.maximo[t - 1] < z.nivel - tol
            if dentro and fuera_antes:
                dist = abs(ctx.cierre[t] - z.nivel)
                if dist < mejor_dist:
                    mejor_dist, candidata = dist, z

        if candidata is not None and t - ultimo_toque >= sep_min:
            toques.append(Toque(
                t=t,
                nivel=candidata.nivel,
                tipo=candidata.tipo,
                direc=1 if candidata.tipo == "soporte" else -1,
                tol=tol,
            ))
            ultimo_toque = t

        # 4. Muerte por ruptura, DESPUES de contar el toque de esta vela.
        for z in vivas:
            if z.tipo == "soporte" and ctx.cierre[t] < z.nivel - tol:
                z.viva = False
            elif z.tipo == "resistencia" and ctx.cierre[t] > z.nivel + tol:
                z.viva = False

    return toques, altas


def _alta_zona(vivas: list[_Zona], nivel: float, tipo: str, muere: int,
               a: float, tol_atr: float) -> int:
    """Alta de zona fusionando niveles casi identicos, para no duplicar toques."""
    if not np.isfinite(nivel):
        return 0
    if np.isfinite(a) and a > 0:
        tol = tol_atr * a
        for z in vivas:
            if z.tipo == tipo and abs(z.nivel - nivel) <= tol:
                z.muere = max(z.muere, muere)       # zona reforzada, no nueva
                z.viva = True
                return 0
    vivas.append(_Zona(nivel, tipo, muere))
    return 1


# ---------------------------------------------------------------------------
# Primitivas de confirmacion. Devuelven None cuando el dato no existe.
# ---------------------------------------------------------------------------

def vela_a_favor(ctx: Contexto, j: int, direc: int) -> bool | None:
    if j < 0 or j >= ctx.n:
        return None
    o, c = ctx.apertura[j], ctx.cierre[j]
    if not (np.isfinite(o) and np.isfinite(c)):
        return None
    if c == o:
        return False                    # doji: no confirma nada
    return (c > o) if direc > 0 else (c < o)


def vela_rechazo(ctx: Contexto, j: int, nivel: float, direc: int) -> bool | None:
    """
    Rechazo explicito: mecha CONTRA la zona >= MECHA_MIN del rango de la vela y
    cierre del lado correcto del nivel.
    """
    if j < 0 or j >= ctx.n:
        return None
    h, l = ctx.maximo[j], ctx.minimo[j]
    o, c = ctx.apertura[j], ctx.cierre[j]
    if not (np.isfinite(h) and np.isfinite(l) and np.isfinite(o) and np.isfinite(c)):
        return None
    rango = h - l
    if rango <= 0:
        return None                     # vela plana: el ratio no esta definido
    if direc > 0:
        mecha = min(o, c) - l           # mecha inferior, el rechazo del soporte
        return mecha >= MECHA_MIN * rango and c > nivel
    mecha = h - max(o, c)               # mecha superior, rechazo de resistencia
    return mecha >= MECHA_MIN * rango and c < nivel


def giro_estocastico(ctx: Contexto, j: int, direc: int) -> bool | None:
    """%K cruza a %D viniendo de zona extrema. Solo con velas cerradas."""
    if j < 1 or j >= ctx.n:
        return None
    k0, k1 = ctx.k[j - 1], ctx.k[j]
    d0, d1 = ctx.d[j - 1], ctx.d[j]
    if not (np.isfinite(k0) and np.isfinite(k1) and np.isfinite(d0) and np.isfinite(d1)):
        return None
    if direc > 0:
        return k1 > d1 and k0 <= d0 and k0 <= STOCH_BAJO
    return k1 < d1 and k0 >= d0 and k0 >= STOCH_ALTO


def _primer_rechazo(ctx: Contexto, tq: Toque, ventana: int) -> int | None:
    for j in range(tq.t, tq.t + ventana):
        r = vela_rechazo(ctx, j, tq.nivel, tq.direc)
        if r is None:
            return None
        if r:
            return j
    return None


def _primer_giro(ctx: Contexto, tq: Toque, ventana: int) -> int | None:
    for j in range(tq.t, tq.t + ventana):
        g = giro_estocastico(ctx, j, tq.direc)
        if g is None:
            return None
        if g:
            return j
    return None


def _n_velas_a_favor(ctx: Contexto, tq: Toque, k: int) -> bool | None:
    for j in range(tq.t + 1, tq.t + 1 + k):
        v = vela_a_favor(ctx, j, tq.direc)
        if v is None:
            return None
        if not v:
            return False
    return True


# ---------------------------------------------------------------------------
# Variantes. Cada una devuelve la vela de ENTRADA o None si no hay senal.
# La entrada es siempre la apertura de una vela posterior a todo lo evaluado.
# ---------------------------------------------------------------------------

def v_inmediato(ctx, tq):
    return tq.t + 1


def _v_demora(k: int):
    def f(ctx, tq):
        return tq.t + 1 + k
    return f


def _v_conf(k: int):
    def f(ctx, tq):
        ok = _n_velas_a_favor(ctx, tq, k)
        if ok is None or not ok:
            return None
        return tq.t + 1 + k
    return f


def v_rechazo(ctx, tq):
    r = vela_rechazo(ctx, tq.t, tq.nivel, tq.direc)
    if r is None or not r:
        return None
    return tq.t + 1


def _v_rechazo_ventana(ventana: int):
    def f(ctx, tq):
        j = _primer_rechazo(ctx, tq, ventana)
        return None if j is None else j + 1
    return f


def _v_stoch(ventana: int):
    def f(ctx, tq):
        j = _primer_giro(ctx, tq, ventana)
        return None if j is None else j + 1
    return f


def _v_rechazo_conf(k: int):
    def f(ctx, tq):
        r = vela_rechazo(ctx, tq.t, tq.nivel, tq.direc)
        if r is None or not r:
            return None
        ok = _n_velas_a_favor(ctx, tq, k)
        if ok is None or not ok:
            return None
        return tq.t + 1 + k
    return f


def v_rechazo_stoch(ctx, tq):
    r = vela_rechazo(ctx, tq.t, tq.nivel, tq.direc)
    if r is None or not r:
        return None
    j = _primer_giro(ctx, tq, 3)
    if j is None:
        return None
    return max(tq.t, j) + 1


def _v_conf_stoch(k: int):
    """conf{k} filtrado por giro del estocastico DENTRO de esas mismas velas.

    La entrada cae en la misma vela que `conf{k}`, asi que la comparacion entre
    ambas aisla el aporte del estocastico sin mezclar el efecto del retraso.
    """
    def f(ctx, tq):
        ok = _n_velas_a_favor(ctx, tq, k)
        if ok is None or not ok:
            return None
        j = _primer_giro(ctx, tq, k + 1)
        if j is None:
            return None
        return tq.t + 1 + k
    return f


VARIANTES: list[tuple[str, str, object]] = [
    ("inmediato",       "entrar al cierre de la vela que toca",          v_inmediato),
    ("demora1",         "esperar 1 vela sin pedir nada (control)",       _v_demora(1)),
    ("demora2",         "esperar 2 velas sin pedir nada (control)",      _v_demora(2)),
    ("demora3",         "esperar 3 velas sin pedir nada (control)",      _v_demora(3)),
    ("conf1",           "1 vela cerrando a favor",                       _v_conf(1)),
    ("conf2",           "2 velas cerrando a favor",                      _v_conf(2)),
    ("conf3",           "3 velas cerrando a favor",                      _v_conf(3)),
    ("rechazo",         "mecha contra zona >=50% y cierre correcto",     v_rechazo),
    ("rechazo_v3",      "primer rechazo dentro de 3 velas",              _v_rechazo_ventana(3)),
    ("stoch_giro",      "cruce %K/%D desde extremo, ventana 4",          _v_stoch(4)),
    ("rechazo+conf1",   "rechazo y luego 1 vela a favor",                _v_rechazo_conf(1)),
    ("rechazo+conf2",   "rechazo y luego 2 velas a favor",               _v_rechazo_conf(2)),
    ("rechazo+stoch",   "rechazo y giro del estocastico",                v_rechazo_stoch),
    ("conf1+stoch",     "1 vela a favor y giro del estocastico",         _v_conf_stoch(1)),
    ("conf2+stoch",     "2 velas a favor y giro del estocastico",        _v_conf_stoch(2)),
]


# ---------------------------------------------------------------------------
# Resolucion de la operacion
# ---------------------------------------------------------------------------

def resolver(ctx: Contexto, e: int, direc: int, barras: int) -> str | None:
    """
    Entrada en la apertura de la vela `e`, salida en el cierre de `e+barras-1`.
    Eso son exactamente `barras` minutos de recorrido.

    Devuelve None (no se opera) si falta vela, si hay hueco temporal entre la
    decision y la entrada, o si la operacion saltaria un hueco de sesion.
    """
    salida = e + barras - 1
    if e <= 0 or salida >= ctx.n:
        return None
    if ctx.minuto[e] - ctx.minuto[e - 1] != 1:
        return None                     # hueco entre decidir y entrar
    if ctx.minuto[salida] - ctx.minuto[e] != barras - 1:
        return None                     # la operacion cruzaria un hueco
    entrada, cierre = ctx.apertura[e], ctx.cierre[salida]
    if not (np.isfinite(entrada) and np.isfinite(cierre)):
        return None
    if cierre == entrada:
        return "EMPATE"
    gano = (cierre > entrada) if direc > 0 else (cierre < entrada)
    return "GANA" if gano else "PIERDE"


# ---------------------------------------------------------------------------
# Agregacion
# ---------------------------------------------------------------------------

class Acumulador:
    __slots__ = ("n", "w", "empates")

    def __init__(self):
        self.n = 0
        self.w = 0
        self.empates = 0

    def add(self, res: str) -> None:
        if res == "EMPATE":
            self.empates += 1
            return
        self.n += 1
        if res == "GANA":
            self.w += 1

    @property
    def wr(self) -> float | None:
        return self.w / self.n if self.n else None


def esperanza(wr: float, payout: float) -> float:
    """Esperanza por operacion, en unidades de stake."""
    return wr * payout - (1 - wr)


def muestra_necesaria(p_real: float, p_nula: float) -> int | None:
    """Operaciones necesarias para distinguir p_real de p_nula con potencia 80%."""
    if abs(p_real - p_nula) < 1e-9:
        return None                     # identicas: no hay tamano que valga
    z_a, z_b = 1.96, 0.84
    pool = (p_real + p_nula) / 2
    num = z_a * math.sqrt(2 * pool * (1 - pool)) + z_b * math.sqrt(
        p_real * (1 - p_real) + p_nula * (1 - p_nula))
    return math.ceil((num / (p_real - p_nula)) ** 2)


def veredicto(lo: float, hi: float, be: float, n: int) -> str:
    if n < MIN_MUESTRA:
        return "MUESTRA INSUFICIENTE"
    if lo > be:
        return "EDGE REAL"
    if hi < be:
        return "PERDEDOR REAL"
    return "RUIDO"


# ---------------------------------------------------------------------------
# Programa
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Mide si esperar confirmacion en S/R aporta algo o solo retrasa")
    ap.add_argument("--payout", type=float, default=0.86)
    ap.add_argument("--expiries", default="1,3,5", help="expiraciones en minutos")
    ap.add_argument("--wing", type=int, default=3, help="alas del fractal (confirmacion del pivote)")
    ap.add_argument("--tol-atr", type=float, default=0.25, help="ancho de la zona en ATR")
    ap.add_argument("--vigencia", type=int, default=240, help="vida de una zona en velas")
    ap.add_argument("--sep", type=int, default=10, help="separacion minima entre toques")
    ap.add_argument("--assets", default=None, help="lista de activos, por defecto todos")
    args = ap.parse_args()

    expiries = [int(x) for x in args.expiries.split(",")]
    be = 1 / (1 + args.payout)

    print("=" * 112)
    print("LABORATORIO DE CONFIRMACION EN ZONAS S/R  -  cuanto vale esperar")
    print("=" * 112)
    print(f"Payout {args.payout:.3f}  ->  break-even {100 * be:.2f}%")
    print(f"Zona: pivote fractal wing={args.wing} (confirmado {args.wing} velas despues), "
          f"ancho +-{args.tol_atr:g}*ATR14, vigencia {args.vigencia} velas")
    print(f"Toques separados >= {args.sep} velas. Expiraciones: {expiries} min")
    print("Entrada = apertura de la vela siguiente a toda condicion evaluada. "
          "Salida = cierre a los N minutos.")

    datos = cargar_historico(args.assets)
    if not datos:
        print(f"\nNo hay historico en {HISTORY_DIR}")
        return 1

    # acumuladores[(grupo, variante, exp)] y por activo para la mejor variante
    acc: dict[tuple[str, str, int], Acumulador] = {}
    acc_activo: dict[tuple[str, str, str, int], Acumulador] = {}
    resumen_activos: list[tuple[str, str, int, int, int]] = []

    print("\n" + "-" * 112)
    print("ZONAS Y TOQUES DETECTADOS (sin look-ahead)")
    print("-" * 112)
    print(f"{'activo':<16}{'grupo':<7}{'velas':>8}{'zonas':>8}{'toques':>8}"
          f"{'soportes':>10}{'resist.':>9}   periodo")

    for activo, df in datos.items():
        ctx = preparar(df, activo, args.wing)
        if ctx is None:
            print(f"{activo:<16} historico insuficiente, se descarta")
            continue
        toques, zonas = detectar_toques(ctx, args.wing, args.tol_atr,
                                        args.vigencia, args.sep)
        g = grupo_de(activo)
        n_sop = sum(1 for tq in toques if tq.direc > 0)
        print(f"{activo:<16}{g:<7}{ctx.n:>8}{zonas:>8}{len(toques):>8}"
              f"{n_sop:>10}{len(toques) - n_sop:>9}   "
              f"{df.index[0]:%Y-%m-%d %H:%M} -> {df.index[-1]:%Y-%m-%d %H:%M}")
        resumen_activos.append((activo, g, ctx.n, zonas, len(toques)))

        for nombre, _desc, func in VARIANTES:
            for tq in toques:
                e = func(ctx, tq)
                if e is None:
                    continue
                for exp in expiries:
                    res = resolver(ctx, e, tq.direc, exp)
                    if res is None:
                        continue
                    acc.setdefault((g, nombre, exp), Acumulador()).add(res)
                    acc.setdefault(("TODOS", nombre, exp), Acumulador()).add(res)
                    acc_activo.setdefault((activo, g, nombre, exp), Acumulador()).add(res)

    if not acc:
        print("\nNo se detecto ningun toque resoluble. Revisa los parametros.")
        return 1

    # Correccion por multiplicidad: cuantas pruebas se han lanzado de verdad.
    # Se cuentan los dos grupos (OTC y REAL) y los dos sentidos (rebote y ruptura),
    # porque mirar el sentido inverso tambien es una prueba mas.
    n_pruebas = len(VARIANTES) * len(expiries) * 2 * 2
    z_corr = norm_ppf(1 - 0.05 / (2 * n_pruebas))
    print(f"\nPruebas lanzadas: {n_pruebas} (variantes x expiraciones x grupos x sentidos). "
          f"Bonferroni exige z={z_corr:.2f} en vez de 1.96.")

    def bloque(grupo: str, titulo: str) -> None:
        print("\n" + "=" * 112)
        print(titulo)
        print("=" * 112)
        base = {exp: acc.get((grupo, "inmediato", exp)) for exp in expiries}
        print(f"{'variante':<16}{'exp':>4}{'n':>7}{'reten':>7}{'wr':>8}"
              f"{'  IC95%':<18}{'IC Bonf.':<18}{'EV/op':>8}{'EV tot':>9}  veredicto")
        for nombre, _desc, _f in VARIANTES:
            for exp in expiries:
                a = acc.get((grupo, nombre, exp))
                if a is None or a.n == 0:
                    print(f"{nombre:<16}{exp:>3}m{0:>7}      -       -"
                          f"{'  sin senales':<36}       -        -  SIN DATOS")
                    continue
                wr = a.wr
                lo, hi = wilson_interval(a.w, a.n)
                lo_c, hi_c = wilson_interval(a.w, a.n, z=z_corr)
                b = base.get(exp)
                reten = (100 * a.n / b.n) if (b and b.n) else float("nan")
                ev = esperanza(wr, args.payout)
                print(f"{nombre:<16}{exp:>3}m{a.n:>7}{reten:>6.0f}%{100 * wr:>7.1f}%"
                      f"  [{100 * lo:5.1f},{100 * hi:5.1f}]   [{100 * lo_c:5.1f},{100 * hi_c:5.1f}] "
                      f"{ev:>+8.3f}{ev * a.n:>+9.1f}  {veredicto(lo, hi, be, a.n)}")

    bloque("TODOS", "TODOS LOS ACTIVOS AGREGADOS (10 activos)")
    bloque("OTC", "SOLO SINTETICOS OTC (paseo aleatorio conocido: control negativo)")
    bloque("REAL", "SOLO INDICES DE MERCADO REAL")

    # -------------------------------------------------------------------
    # Trade-off explicito: que compra y que cuesta cada filtro
    # -------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("TRADE-OFF DE CADA FILTRO FRENTE A ENTRAR INMEDIATAMENTE (todos los activos)")
    print("=" * 112)
    print("d_wr = puntos porcentuales ganados.  senales = las que sobreviven.")
    print("EV total = esperanza acumulada en stakes: es lo unico que llega a la cuenta.")
    print("Aviso: con EV/op negativa, un EV total menos negativo solo significa operar")
    print("menos y perder menos. Eso NO es una ventaja, es filtrar hacia no operar.")
    print(f"{'variante':<16}{'exp':>4}{'senales':>9}{'reten':>7}{'d_wr(pp)':>10}"
          f"{'z_dif':>8}{'EV tot':>9}{'EV tot base':>12}   lectura")
    for nombre, _desc, _f in VARIANTES:
        if nombre == "inmediato":
            continue
        for exp in expiries:
            a = acc.get(("TODOS", nombre, exp))
            b = acc.get(("TODOS", "inmediato", exp))
            if not a or not b or a.n == 0 or b.n == 0:
                continue
            d = 100 * (a.wr - b.wr)
            z = z_dos_proporciones(a.w, a.n, b.w, b.n)
            ev_a, ev_b = esperanza(a.wr, args.payout) * a.n, esperanza(b.wr, args.payout) * b.n
            if a.n < MIN_MUESTRA:
                lectura = "muestra corta: no concluye"
            elif z is not None and abs(z) < 1.96:
                lectura = "diferencia dentro del ruido"
            elif d > 0:
                lectura = "sube el winrate de forma medible"
            else:
                lectura = "baja el winrate de forma medible"
            zs = f"{z:>8.2f}" if z is not None else "       -"
            print(f"{nombre:<16}{exp:>3}m{a.n:>9}{100 * a.n / b.n:>6.0f}%{d:>+10.2f}"
                  f"{zs}{ev_a:>+9.1f}{ev_b:>+12.1f}   {lectura}")

    # -------------------------------------------------------------------
    # Ranking honesto: por limite INFERIOR del intervalo, no por winrate
    # -------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("RANKING POR LIMITE INFERIOR DEL IC95% (lo unico que se puede defender)")
    print("=" * 112)
    print("Se incluye el sentido INVERSO de cada variante (operar la ruptura en vez")
    print("del rebote). Es gratis de calcular y es la unica forma de ver si el toque")
    print("de zona informa algo aunque sea en la direccion contraria a la esperada.")
    filas = []
    for (g, nombre, exp), a in acc.items():
        if a.n < MIN_MUESTRA:
            continue
        for sentido, w in (("rebote", a.w), ("ruptura", a.n - a.w)):
            lo, hi = wilson_interval(w, a.n)
            lo_c, _ = wilson_interval(w, a.n, z=z_corr)
            filas.append((lo, hi, lo_c, g, nombre, exp, sentido, a.n, w))
    filas.sort(key=lambda r: -r[0])
    print(f"{'grupo':<7}{'variante':<16}{'exp':>4} {'sentido':<9}{'n':>7}{'wr':>8}"
          f"{'IC95 inf':>10}{'IC95 sup':>10}{'Bonf inf':>10}  supera BE {100 * be:.2f}%?")
    for lo, hi, lo_c, g, nombre, exp, sentido, n, w in filas[:15]:
        marca = "SI" if lo > be else ("SI (Bonf.)" if lo_c > be else "no")
        print(f"{g:<7}{nombre:<16}{exp:>3}m {sentido:<9}{n:>7}{100 * w / n:>7.1f}%"
              f"{100 * lo:>9.1f}%{100 * hi:>9.1f}%{100 * lo_c:>9.1f}%  {marca}")

    ganadoras = [f for f in filas if f[0] > be]

    # -------------------------------------------------------------------
    # Desglose por activo de la mejor combinacion, por si la sostiene uno solo
    # -------------------------------------------------------------------
    if filas:
        _lo, _hi, _loc, g_b, n_b, e_b, s_b, _n, _w = filas[0]
        print("\n" + "-" * 112)
        print(f"DESGLOSE POR ACTIVO DE LA MEJOR COMBINACION: {n_b} @ {e_b}min "
              f"sentido {s_b} ({g_b})")
        print("Si un solo activo sostiene el resultado, no hay hallazgo, hay un activo.")
        print("-" * 112)
        print(f"{'activo':<16}{'n':>7}{'wr':>8}{'IC95%':>20}   veredicto")
        for (activo, g, nombre, exp), a in sorted(acc_activo.items()):
            if nombre != n_b or exp != e_b:
                continue
            if g_b != "TODOS" and g != g_b:
                continue
            if a.n == 0:
                continue
            w = a.w if s_b == "rebote" else a.n - a.w
            lo, hi = wilson_interval(w, a.n)
            print(f"{activo:<16}{a.n:>7}{100 * w / a.n:>7.1f}%"
                  f"   [{100 * lo:5.1f}%, {100 * hi:5.1f}%]   {veredicto(lo, hi, be, a.n)}")

    # -------------------------------------------------------------------
    # Pregunta previa: el setup contiene informacion direccional, aunque no
    # llegue para ser rentable? Se contrasta contra el 50% puro, no contra el
    # break-even. Son dos preguntas distintas y conviene no mezclarlas.
    # -------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("CONTIENE INFORMACION DIRECCIONAL? (contraste contra el 50% del azar)")
    print("=" * 112)
    print("Superar el 50% no da dinero con payout 0.86, hace falta 53.76%. Pero si ni")
    print("siquiera se separa del 50%, el setup no sabe nada y no hay nada que afinar.")
    informativas = []
    for (g, nombre, exp), a in acc.items():
        if g == "TODOS" or a.n < MIN_MUESTRA:
            continue
        lo, hi = wilson_interval(a.w, a.n)
        if lo > 0.50 or hi < 0.50:
            informativas.append((abs(a.wr - 0.50), g, nombre, exp, a, lo, hi))
    informativas.sort(reverse=True, key=lambda r: r[0])
    if informativas:
        print(f"{'grupo':<7}{'variante':<16}{'exp':>4}{'n':>7}{'wr rebote':>11}"
              f"{'IC95%':>18}   lectura")
        for _d, g, nombre, exp, a, lo, hi in informativas:
            sesgo = ("el rebote gana al azar" if lo > 0.50 else
                     "el rebote PIERDE contra el azar: la zona rompe mas que rebota")
            print(f"{g:<7}{nombre:<16}{exp:>3}m{a.n:>7}{100 * a.wr:>10.1f}%"
                  f"   [{100 * lo:5.1f}%, {100 * hi:5.1f}%]   {sesgo}")
        print("Recordatorio: separarse del 50% no basta. Ninguna de estas alcanza el "
              f"{100 * be:.2f}%.")
    else:
        print("Ninguna variante con muestra suficiente se separa del 50%: los toques de")
        print("zona, con o sin confirmacion, no contienen informacion direccional medible.")

    # -------------------------------------------------------------------
    # Veredicto
    # -------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("VEREDICTO")
    print("=" * 112)
    print(f"Break-even con payout {args.payout:.2f}: {100 * be:.2f}%")
    if ganadoras:
        print(f"Combinaciones cuyo IC95% completo supera el break-even: {len(ganadoras)}")
        for lo, hi, lo_c, g, nombre, exp, sentido, n, w in ganadoras:
            sello = ("aguanta Bonferroni" if lo_c > be else
                     "NO aguanta Bonferroni (probable ruido de multiplicidad)")
            print(f"  {g} | {nombre} | {exp}min | {sentido} | n={n} | "
                  f"wr={100 * w / n:.1f}% | IC95 inf={100 * lo:.1f}% | {sello}")
    else:
        print("NINGUNA combinacion de confirmacion + expiracion tiene el IC95% entero")
        print(f"por encima del break-even. Con muestra >= {MIN_MUESTRA} no hay ni una,")
        print("ni operando el rebote ni operando la ruptura.")
        if filas:
            lo, hi, lo_c, g, nombre, exp, sentido, n, w = filas[0]
            print(f"La mejor fue {nombre} @ {exp}min ({sentido}) en {g}: "
                  f"{100 * w / n:.1f}% con n={n},")
            print(f"pero su IC95% baja hasta {100 * lo:.1f}%, por debajo del "
                  f"{100 * be:.2f}% necesario. No es distinguible del azar.")
            faltan = muestra_necesaria(w / n, be)
            if faltan is not None:
                print(f"Para poder concluir algo con ese winrate harian falta ~{faltan:,} "
                      f"operaciones (hay {n}).")

    # Comparacion confirmacion frente a control de retraso puro: el nucleo.
    print("\nESPERAR, INFORMA O SOLO RETRASA? (confN frente a demoraN, mismos toques)")
    print(f"{'exp':>4}  {'par':<22}{'wr_conf':>9}{'wr_demora':>11}{'d(pp)':>8}{'z':>8}   lectura")
    for exp in expiries:
        for k in (1, 2, 3):
            a = acc.get(("TODOS", f"conf{k}", exp))
            b = acc.get(("TODOS", f"demora{k}", exp))
            if not a or not b or a.n == 0 or b.n == 0:
                continue
            z = z_dos_proporciones(a.w, a.n, b.w, b.n)
            d = 100 * (a.wr - b.wr)
            lectura = ("la confirmacion no aporta informacion"
                       if (z is None or abs(z) < 1.96) else
                       ("la confirmacion aporta" if d > 0 else "la confirmacion resta"))
            zs = f"{z:>8.2f}" if z is not None else "       -"
            print(f"{exp:>3}m  {f'conf{k} vs demora{k}':<22}{100 * a.wr:>8.1f}%"
                  f"{100 * b.wr:>10.1f}%{d:>+8.2f}{zs}   {lectura}")

    print("\nADVERTENCIAS DE LECTURA")
    print("- Los toques del mismo activo estan separados >= "
          f"{args.sep} velas, pero con expiracion de 5 min")
    print("  dos operaciones pueden solaparse: los IC son algo mas estrechos de lo real.")
    print("- Las variantes comparten los mismos toques, no son muestras independientes;")
    print("  el z de diferencia es orientativo, no una prueba formal.")
    print("- Los sinteticos OTC ya se sabe que son paseo aleatorio: ahi sirven de")
    print("  control negativo. Si un filtro 'funciona' en OTC, es sobreajuste.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
