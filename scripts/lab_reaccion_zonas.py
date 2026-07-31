# -*- coding: utf-8 -*-
"""
Laboratorio de reaccion del precio en zonas de soporte y resistencia.

PREGUNTA QUE RESPONDE, con numeros y no con opiniones:
cuando el precio toca una zona S/R confirmada, cuanto sube, cuanto baja, y en
cuanto tiempo. Y sobre todo: existe algun horizonte de expiracion donde la
probabilidad a favor supere el break-even del payout (53.76% con payout 0.86)?

NO reimplementa la estrategia del usuario. Mide el terreno sobre el que esa
estrategia opera: la excursion favorable (MFE), la adversa (MAE), el tiempo
hasta cada una, y donde la zona engana (trampa: el precio la atraviesa antes
de reaccionar, o no reacciona nunca).

SALVAGUARDAS, sin las cuales esto se enganaria a si mismo:

1. CERO LOOK-AHEAD. El pivote con wing=5 se detecta con una ventana centrada,
   pero el nivel NO existe hasta la barra i+wing, y solo se usa a partir de
   i+wing+1. El ATR es causal (ewm). La entrada es la apertura de la vela
   siguiente al toque, que en el momento de decidir aun no se habia visto.
2. CONTIGUIDAD TEMPORAL. Los indices reales cierran (hueco maximo medido:
   49 horas). Un horizonte de 30 minutos que cruza un fin de semana no es un
   horizonte de 30 minutos. Cada horizonte exige que sus barras sean
   consecutivas de 60s; si no lo son, esa observacion se descarta PARA ESE
   horizonte (no se rellena, no se aproxima).
3. TODO CON WILSON. Ningun winrate puntual suelto. Y con dos lecturas: IC95%
   normal e IC ajustado por Bonferroni sobre el numero real de celdas
   probadas, porque probar ~100 celdas al 5% fabrica ~5 hallazgos falsos.
4. MUESTRA INDEPENDIENTE. Las ventanas de 30 min de toques cercanos se solapan
   y eso estrecha artificialmente los intervalos. Las tablas cabecera se
   repiten sobre un subconjunto con separacion minima de 30 barras.
5. NUNCA UN DEFAULT PLAUSIBLE. Si un valor no se puede calcular se devuelve
   None y se cuenta como descarte. Ese error exacto (RSI=50 por defecto)
   arruino las 500 operaciones anteriores.

Uso:
    python scripts/lab_reaccion_zonas.py
    python scripts/lab_reaccion_zonas.py --payout 0.86 --wing 5 --zona 0.5
    python scripts/lab_reaccion_zonas.py --activos EURUSD-OTC,USSPX500_N
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.backtest.indicators import atr as atr_indicador          # noqa: E402
from bot.backtest.replay import wilson_interval as wilson         # noqa: E402

HISTORY_DIR = ROOT / "bot" / "data" / "history"

# Horizontes de expiracion a medir, en minutos.
HORIZONTES = (1, 3, 5, 10, 15, 30)
H_MAX = max(HORIZONTES)

# Umbrales de excursion para la carrera favorable/adverso, en ATRs.
UMBRALES_ATR = (0.5, 1.0)

# Por debajo de esto el intervalo es tan ancho que no concluye nada.
MIN_N = 200

SINTETICOS = ("EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "XAUUSD-OTC", "LTCUSD-OTC")
REALES = ("USSPX500_N", "USNDAQ100_N", "US30_N", "US2000_N", "JAPAN225_N")

BLOQUES_UTC = (
    ("00-06 asia", 0, 6),
    ("06-13 europa", 6, 13),
    ("13-15 apertura NY", 13, 15),
    ("15-21 tarde NY", 15, 21),
    ("21-24 cierre", 21, 24),
)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def tipo_mercado(activo: str) -> str:
    if activo in SINTETICOS:
        return "sintetico_otc"
    if activo in REALES:
        return "indice_real"
    return "desconocido"


def cargar(activo: str) -> pd.DataFrame | None:
    """Carga las velas M1 de un activo. Devuelve None si no se puede."""
    ruta = HISTORY_DIR / f"{activo}_60.parquet"
    if not ruta.exists():
        return None
    try:
        df = pd.read_parquet(ruta).sort_index()
    except Exception as exc:
        print(f"  aviso: no se pudo leer {ruta.name}: {exc}")
        return None
    if len(df) < 500:
        return None
    return df


def pctl(valores, q: float) -> float | None:
    """Percentil, o None si no hay muestra. Nunca un valor inventado."""
    v = [x for x in valores if x is not None and np.isfinite(x)]
    if not v:
        return None
    return float(np.percentile(v, q))


def f(x: float | None, nd: int = 2, ancho: int = 6) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/d".rjust(ancho)
    return f"{x:{ancho}.{nd}f}"


def grupo_fino(n: int) -> str:
    """Reparto mas fino del numero de toque; el grupo '4+' pedido es un cajon
    de sastre que aqui se abre para ver si dentro pasa algo."""
    if n <= 3:
        return str(n)
    if n <= 6:
        return "4-6"
    if n <= 12:
        return "7-12"
    return "13+"


def veredicto(lo: float, hi: float, be: float) -> str:
    """
    Un winrate por debajo del break-even NO es un edge invertido salvo que
    el complementario tambien supere el break-even (hi < 1-be).
    """
    if lo > be:
        return "EDGE A FAVOR"
    if hi < 1.0 - be:
        return "EDGE INVERSO"
    return "ruido"


# ---------------------------------------------------------------------------
# Deteccion de zonas: pivotes confirmados, sin mirar al futuro
# ---------------------------------------------------------------------------

@dataclass
class Zona:
    precio: float
    tipo: str                 # "pivote_alto" o "pivote_bajo" (origen, informativo)
    barra_confirmacion: int
    barra_refresco: int
    toques: int = 0
    ultima_barra_toque: int = -10 ** 9
    pivotes: int = 1          # cuantos pivotes distintos han caido en esta zona


def pivotes_confirmados(df: pd.DataFrame, wing: int) -> list[tuple[int, float, str]]:
    """
    Pivotes de swing con `wing` barras a cada lado.

    La ventana es centrada, asi que el pivote de la barra i NO se conoce hasta
    la barra i+wing. Se devuelve (barra_confirmacion, precio, tipo) con
    barra_confirmacion = i + wing: antes de esa barra el nivel no existe.
    """
    alto = df["high"]
    bajo = df["low"]
    ventana = 2 * wing + 1
    max_centrado = alto.rolling(ventana).max().shift(-wing)
    min_centrado = bajo.rolling(ventana).min().shift(-wing)

    es_alto = (alto == max_centrado).to_numpy()
    es_bajo = (bajo == min_centrado).to_numpy()
    ah = alto.to_numpy()
    al = bajo.to_numpy()

    salida: list[tuple[int, float, str]] = []
    n = len(df)
    for i in range(wing, n - wing):
        if es_alto[i]:
            salida.append((i + wing, float(ah[i]), "pivote_alto"))
        if es_bajo[i]:
            salida.append((i + wing, float(al[i]), "pivote_bajo"))
    salida.sort(key=lambda x: x[0])
    return salida


def racha_contigua(idx: pd.DatetimeIndex) -> np.ndarray:
    """
    racha[i] = numero de velas consecutivas de 60s que terminan en i.
    Las barras t..t+H son contiguas si racha[t+H] >= H+1.
    """
    seg = idx.to_series().diff().dt.total_seconds().to_numpy()
    n = len(idx)
    racha = np.ones(n, dtype=np.int64)
    for i in range(1, n):
        racha[i] = racha[i - 1] + 1 if seg[i] == 60.0 else 1
    return racha


# ---------------------------------------------------------------------------
# Extraccion de toques y medicion de la reaccion
# ---------------------------------------------------------------------------

@dataclass
class Config:
    wing: int = 5
    zona_atr: float = 0.5          # semiancho de la zona, en ATRs
    max_edad: int = 1440           # barras que una zona sigue viva sin refresco
    sep_min_toques: int = 5        # barras minimas entre toques de la MISMA zona
    payout: float = 0.86

    @property
    def breakeven(self) -> float:
        return 1.0 / (1.0 + self.payout)


@dataclass
class Descartes:
    sin_atr: int = 0
    sin_entrada: int = 0
    lado_ambiguo: int = 0
    barras: int = 0
    barras_en_zona: int = 0
    suma_zonas_activas: int = 0
    sin_contiguidad: dict = field(default_factory=lambda: {h: 0 for h in HORIZONTES})

    @property
    def zonas_activas_medias(self) -> float | None:
        if self.barras == 0:
            return None
        return self.suma_zonas_activas / self.barras


def extraer_toques(df: pd.DataFrame, activo: str, cfg: Config,
                   desc: Descartes) -> list[dict]:
    """
    Recorre las velas en orden y registra cada TOQUE de una zona confirmada.

    Un toque es: la vela t intersecta la zona y la vela t-1 NO la intersectaba
    (entrada fresca en la zona). El lado lo decide POR DONDE VIENE el precio,
    no el tipo de pivote: si venia de arriba la zona actua de soporte (se
    espera rebote al alza, CALL); si venia de abajo actua de resistencia (PUT).
    Asi se tratan bien los niveles rotos que cambian de rol.

    La entrada es la APERTURA de la vela t+1, que en el momento de detectar el
    toque (cierre de t) todavia no existia.
    """
    idx = df.index
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    n = len(df)

    atr_ser = atr_indicador(df, 14).to_numpy(dtype=float)
    racha = racha_contigua(idx)
    piv = pivotes_confirmados(df, cfg.wing)
    mercado = tipo_mercado(activo)

    zonas: list[Zona] = []
    puntero = 0
    inicio = max(cfg.wing * 2 + 20, 30)
    registros: list[dict] = []

    for t in range(inicio, n - 1):
        atr_t = atr_ser[t]
        if not np.isfinite(atr_t) or atr_t <= 0:
            desc.sin_atr += 1
            continue
        semi = cfg.zona_atr * atr_t

        # Alta de zonas ya confirmadas (estrictamente antes de la barra actual).
        while puntero < len(piv) and piv[puntero][0] < t:
            b_conf, precio, tipo = piv[puntero]
            puntero += 1
            atr_conf = atr_ser[b_conf]
            tol = cfg.zona_atr * atr_conf if np.isfinite(atr_conf) and atr_conf > 0 else semi
            fusionada = False
            for z in zonas:
                if abs(z.precio - precio) <= tol:
                    z.barra_refresco = b_conf      # el nivel se reafirma
                    z.pivotes += 1
                    fusionada = True
                    break
            if not fusionada:
                zonas.append(Zona(precio=precio, tipo=tipo,
                                  barra_confirmacion=b_conf, barra_refresco=b_conf))

        # Caducidad de zonas viejas.
        if zonas:
            zonas = [z for z in zonas if t - z.barra_refresco <= cfg.max_edad]
        desc.barras += 1
        desc.suma_zonas_activas += len(zonas)
        if not zonas:
            continue
        # Cobertura: cuanto del recorrido del precio esta "dentro de alguna zona".
        # Si esto se acerca al 100%, decir "el precio esta en zona" no informa nada.
        if any(abs(z.precio - c[t]) <= semi for z in zonas):
            desc.barras_en_zona += 1

        # Candidatas tocadas ahora y no antes.
        mejor: Zona | None = None
        mejor_dist = float("inf")
        for z in zonas:
            sup, inf = z.precio + semi, z.precio - semi
            toca = (l[t] <= sup) and (h[t] >= inf)
            if not toca:
                continue
            toca_prev = (l[t - 1] <= sup) and (h[t - 1] >= inf)
            if toca_prev:
                continue
            if t - z.ultima_barra_toque < cfg.sep_min_toques:
                continue
            d = abs(z.precio - c[t])
            if d < mejor_dist:
                mejor, mejor_dist = z, d

        if mejor is None:
            continue

        # De donde venia el precio. Si la vela previa no tocaba la zona, una de
        # las dos condiciones se cumple por fuerza; si no, se descarta.
        sup, inf = mejor.precio + semi, mejor.precio - semi
        if l[t - 1] > sup:
            lado, direccion = "soporte", "CALL"
        elif h[t - 1] < inf:
            lado, direccion = "resistencia", "PUT"
        else:
            desc.lado_ambiguo += 1
            continue

        # Un toque NO alarga la vida de la zona: la vigencia de un nivel viene
        # de su estructura de pivotes, no de que el precio lo cruce. Si se
        # refrescara aqui, las zonas serian inmortales y el grupo "4+" se
        # comeria toda la muestra.
        mejor.toques += 1
        mejor.ultima_barra_toque = t
        n_toques = mejor.toques

        # Entrada en la apertura de t+1: exige contiguidad t -> t+1.
        if t + 1 >= n or racha[t + 1] < 2:
            desc.sin_entrada += 1
            continue
        entrada = o[t + 1]

        reg = {
            "activo": activo,
            "mercado": mercado,
            "barra": t,
            "hora": idx[t],
            "hora_utc": int(idx[t].hour),
            "zona": mejor.precio,
            "atr": float(atr_t),
            "lado": lado,
            "direccion": direccion,
            "n_toques": n_toques,
            "grupo_toques": "4+" if n_toques >= 4 else str(n_toques),
            "grupo_fino": grupo_fino(n_toques),
            "pivotes_zona": mejor.pivotes,
            "fuerza": ("1 pivote" if mejor.pivotes == 1
                       else "2 pivotes" if mejor.pivotes == 2 else "3+ pivotes"),
            "entrada": float(entrada),
        }

        # ---- excursiones por horizonte -----------------------------------
        for H in HORIZONTES:
            if t + H >= n or racha[t + H] < H + 1:
                desc.sin_contiguidad[H] += 1
                reg[f"mfe_{H}"] = None
                reg[f"mae_{H}"] = None
                reg[f"res_{H}"] = None
                continue
            hh = h[t + 1:t + H + 1]
            ll = l[t + 1:t + H + 1]
            cierre = c[t + H]
            if direccion == "CALL":
                mfe = hh.max() - entrada
                mae = entrada - ll.min()
                gana = cierre > entrada
                pierde = cierre < entrada
            else:
                mfe = entrada - ll.min()
                mae = hh.max() - entrada
                gana = cierre < entrada
                pierde = cierre > entrada
            reg[f"mfe_{H}"] = float(mfe / atr_t)
            reg[f"mae_{H}"] = float(mae / atr_t)
            reg[f"res_{H}"] = "WIN" if gana else ("LOSS" if pierde else "TIE")

        # ---- tiempos hasta el extremo y carrera, en la ventana de 30 min --
        if t + H_MAX < n and racha[t + H_MAX] >= H_MAX + 1:
            hh = h[t + 1:t + H_MAX + 1]
            ll = l[t + 1:t + H_MAX + 1]
            if direccion == "CALL":
                fav = hh - entrada          # excursion favorable por vela
                adv = entrada - ll          # excursion adversa por vela
            else:
                fav = entrada - ll
                adv = hh - entrada
            # argmax devuelve la PRIMERA vela que alcanza el extremo, que es lo
            # que se quiere: el minuto en que la reaccion llega a su maximo.
            reg["t_mfe"] = int(np.argmax(fav) + 1)
            reg["t_mae"] = int(np.argmax(adv) + 1)
            for u in UMBRALES_ATR:
                lim = u * atr_t
                i_f = np.argmax(fav >= lim) + 1 if (fav >= lim).any() else None
                i_a = np.argmax(adv >= lim) + 1 if (adv >= lim).any() else None
                if i_f is None and i_a is None:
                    quien = "ninguno"
                elif i_a is None:
                    quien = "favor"
                elif i_f is None:
                    quien = "adverso"
                elif i_f < i_a:
                    quien = "favor"
                elif i_a < i_f:
                    quien = "adverso"
                else:
                    quien = "misma_vela"
                reg[f"carrera_{u}"] = quien
        else:
            reg["t_mfe"] = None
            reg["t_mae"] = None
            for u in UMBRALES_ATR:
                reg[f"carrera_{u}"] = None

        registros.append(reg)

    return registros


# ---------------------------------------------------------------------------
# Agregacion y reporte
# ---------------------------------------------------------------------------

def celda(sub: pd.DataFrame, H: int) -> dict:
    """Estadistico de una celda: n, winrate, Wilson, empates y no calculables."""
    col = sub[f"res_{H}"]
    wins = int((col == "WIN").sum())
    loss = int((col == "LOSS").sum())
    ties = int((col == "TIE").sum())
    nulos = int(col.isna().sum())
    n = wins + loss
    lo, hi = wilson(wins, n) if n else (None, None)
    return {"n": n, "wins": wins, "ties": ties, "nulos": nulos,
            "wr": (wins / n) if n else None, "lo": lo, "hi": hi}


def wilson_z(wins: int, n: int, z: float) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    d = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / d
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, ctr - m), min(1.0, ctr + m))


def muestra_independiente(df: pd.DataFrame, sep: int = H_MAX) -> pd.DataFrame:
    """
    Selecciona toques con separacion minima `sep` barras dentro de cada activo,
    para que las ventanas de medicion no se solapen entre si.
    """
    guardar = []
    for _, g in df.groupby("activo", sort=False):
        ultima = -10 ** 9
        for barra, i in zip(g["barra"].to_numpy(), g.index):
            if barra - ultima >= sep:
                guardar.append(i)
                ultima = barra
    return df.loc[guardar]


def linea_prob(etq: str, sub: pd.DataFrame, H: int, be: float, z_bonf: float) -> str:
    e = celda(sub, H)
    if e["n"] == 0:
        return f"  {etq:<26} h={H:<3} n=0      SIN DATOS"
    lo_b, hi_b = wilson_z(e["wins"], e["n"], z_bonf)
    marca = veredicto(e["lo"], e["hi"], be)
    if e["n"] < MIN_N:
        marca = "MUESTRA INSUFICIENTE"
    elif marca == "EDGE A FAVOR" and lo_b <= be:
        marca = "ruido (cae con Bonferroni)"
    return (f"  {etq:<26} h={H:<3} n={e['n']:<5} wr={100 * e['wr']:5.2f}% "
            f"IC95[{100 * e['lo']:5.2f},{100 * e['hi']:5.2f}] "
            f"ICbonf[{100 * lo_b:5.2f},{100 * hi_b:5.2f}] empates={e['ties']:<4} {marca}")


def tabla_probabilidad(df: pd.DataFrame, titulo: str, be: float, z_bonf: float,
                       grupos: list[tuple[str, pd.Series]]) -> list[str]:
    out = ["", titulo, "-" * len(titulo)]
    for etq, mask in grupos:
        sub = df[mask]
        for H in HORIZONTES:
            out.append(linea_prob(etq, sub, H, be, z_bonf))
        out.append("")
    return out


def tabla_excursiones(df: pd.DataFrame, grupos: list[tuple[str, pd.Series]]) -> list[str]:
    out = ["", "EXCURSIONES EN ATRs (MFE favorable / MAE adversa) POR HORIZONTE",
           "-" * 78,
           "  grupo                      h    n     MFE p50 MFE p75  MAE p50 MAE p75  "
           "%MFE>=1  %MAE>=1"]
    for etq, mask in grupos:
        sub = df[mask]
        for H in HORIZONTES:
            mfe = sub[f"mfe_{H}"].dropna().to_numpy(dtype=float)
            mae = sub[f"mae_{H}"].dropna().to_numpy(dtype=float)
            n = len(mfe)
            if n == 0:
                out.append(f"  {etq:<26} {H:<4} 0     SIN DATOS")
                continue
            p_mfe1 = float((mfe >= 1.0).mean())
            p_mae1 = float((mae >= 1.0).mean())
            out.append(
                f"  {etq:<26} {H:<4} {n:<5} {f(pctl(mfe, 50))}  {f(pctl(mfe, 75))}  "
                f"{f(pctl(mae, 50))}  {f(pctl(mae, 75))}  "
                f"{100 * p_mfe1:6.1f}%  {100 * p_mae1:6.1f}%")
        out.append("")
    return out


def tabla_tiempos(df: pd.DataFrame, grupos: list[tuple[str, pd.Series]]) -> list[str]:
    out = ["", "TIEMPO HASTA EL EXTREMO dentro de la ventana de 30 min (minutos)",
           "-" * 78,
           "  grupo                      n     tMFE p25 p50 p75   tMAE p25 p50 p75   "
           "%MFE<=5min  %MAE<=5min"]
    for etq, mask in grupos:
        sub = df[mask]
        tf = sub["t_mfe"].dropna().to_numpy(dtype=float)
        ta = sub["t_mae"].dropna().to_numpy(dtype=float)
        if len(tf) == 0:
            out.append(f"  {etq:<26} 0     SIN DATOS")
            continue
        out.append(
            f"  {etq:<26} {len(tf):<5} "
            f"{f(pctl(tf, 25), 1, 4)} {f(pctl(tf, 50), 1, 4)} {f(pctl(tf, 75), 1, 4)}    "
            f"{f(pctl(ta, 25), 1, 4)} {f(pctl(ta, 50), 1, 4)} {f(pctl(ta, 75), 1, 4)}    "
            f"{100 * float((tf <= 5).mean()):7.1f}%  {100 * float((ta <= 5).mean()):7.1f}%")
    return out


def tabla_trampa(df: pd.DataFrame, grupos: list[tuple[str, pd.Series]]) -> list[str]:
    out = ["", "TRAMPA: quien llega primero en 30 min, la excursion favorable o la adversa",
           "-" * 78,
           "  grupo                      umbral  n     %favor  %adverso  %misma  %ninguno"]
    for etq, mask in grupos:
        sub = df[mask]
        for u in UMBRALES_ATR:
            col = sub[f"carrera_{u}"].dropna()
            n = len(col)
            if n == 0:
                out.append(f"  {etq:<26} {u:<7} 0     SIN DATOS")
                continue
            vc = col.value_counts()
            g = lambda k: 100.0 * int(vc.get(k, 0)) / n      # noqa: E731
            out.append(f"  {etq:<26} {u:<7} {n:<5} {g('favor'):6.1f}%  "
                       f"{g('adverso'):7.1f}%  {g('misma_vela'):5.1f}%  {g('ninguno'):6.1f}%")
        out.append("")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Perfil de reaccion en zonas S/R")
    ap.add_argument("--payout", type=float, default=0.86)
    ap.add_argument("--wing", type=int, default=5)
    ap.add_argument("--zona", type=float, default=0.5, help="semiancho en ATRs")
    ap.add_argument("--max-edad", type=int, default=1440)
    ap.add_argument("--sep-toques", type=int, default=5)
    ap.add_argument("--activos", type=str, default="")
    args = ap.parse_args()

    cfg = Config(wing=args.wing, zona_atr=args.zona, max_edad=args.max_edad,
                 sep_min_toques=args.sep_toques, payout=args.payout)
    be = cfg.breakeven

    activos = ([a.strip() for a in args.activos.split(",") if a.strip()]
               or list(SINTETICOS) + list(REALES))

    print("=" * 100)
    print("LABORATORIO DE REACCION EN ZONAS DE SOPORTE Y RESISTENCIA")
    print("=" * 100)
    print(f"Pivotes wing={cfg.wing} confirmados en i+{cfg.wing}, usables desde i+{cfg.wing}+1")
    print(f"Zona = nivel +- {cfg.zona_atr} * ATR14   |   caducidad {cfg.max_edad} barras   |   "
          f"separacion minima entre toques {cfg.sep_min_toques} barras")
    print(f"Payout {cfg.payout:.2f} -> break-even {100 * be:.2f}%")
    print("Direccion: zona tocada desde arriba = soporte -> CALL; desde abajo = "
          "resistencia -> PUT")
    print("Entrada = apertura de la vela SIGUIENTE al toque. Empates excluidos del "
          "denominador.")
    print()

    filas: list[dict] = []
    print("INVENTARIO POR ACTIVO")
    print("-" * 100)
    print("  activo            velas   pivotes  zonas_viv  toques  %barras  %cierres "
          "en zona  sin_entrada  sin_contig(h30)")
    for act in activos:
        df = cargar(act)
        if df is None:
            print(f"  {act:<17} SIN DATOS UTILIZABLES")
            continue
        desc = Descartes()
        piv = pivotes_confirmados(df, cfg.wing)
        regs = extraer_toques(df, act, cfg, desc)
        filas.extend(regs)
        zv = desc.zonas_activas_medias
        pct_barras = (100.0 * len(regs) / desc.barras) if desc.barras else None
        pct_cobertura = (100.0 * desc.barras_en_zona / desc.barras) if desc.barras else None
        print(f"  {act:<17} {len(df):<7} {len(piv):<8} {f(zv, 1, 9)}  {len(regs):<7} "
              f"{f(pct_barras, 1, 6)}%  {f(pct_cobertura, 1, 13)}%  "
              f"{desc.sin_entrada:<12} {desc.sin_contiguidad[30]}")

    if not filas:
        print("\nNo se extrajo ningun toque. Nada que concluir.")
        return 1

    df = pd.DataFrame(filas)
    df_ind = muestra_independiente(df, H_MAX)

    print()
    print(f"TOTAL toques medidos: {len(df)}   |   muestra independiente "
          f"(>={H_MAX} barras entre toques): {len(df_ind)}")
    print("Los toques solapados comparten futuro: sus IC son mas estrechos de lo "
          "legitimo. Por eso")
    print("toda conclusion se exige tambien sobre la muestra independiente.")
    nt = df["n_toques"].to_numpy()
    print(f"Distribucion del numero de toque: p50={f(pctl(nt, 50), 1, 4)} "
          f"p90={f(pctl(nt, 90), 1, 4)} max={int(nt.max())}   |   reparto "
          + "  ".join(f"{g}:{int((df['grupo_toques'] == g).sum())}"
                      for g in ("1", "2", "3", "4+")))

    # ---- registro unico de cortes -----------------------------------------
    # Se define aqui una sola vez para que el recuento de Bonferroni y el
    # rastreo final de candidatos no puedan divergir del que se imprime.
    grupos_mercado = [
        ("TODOS", pd.Series(True, index=df.index)),
        ("sintetico_otc", df["mercado"] == "sintetico_otc"),
        ("indice_real", df["mercado"] == "indice_real"),
    ]
    grupos_toques = {
        m: [(f"{m} toque {g}", (df["mercado"] == m) & (df["grupo_toques"] == g))
            for g in ("1", "2", "3", "4+")]
        for m in ("sintetico_otc", "indice_real")
    }
    grupos_sesion = {
        m: [(f"{m} {etq}", (df["mercado"] == m) & (df["hora_utc"] >= a)
             & (df["hora_utc"] < b))
            for etq, a, b in BLOQUES_UTC]
        for m in ("sintetico_otc", "indice_real")
    }
    grupos_lado = [("soporte (CALL)", df["lado"] == "soporte"),
                   ("resistencia (PUT)", df["lado"] == "resistencia")]
    grupos_fuerza = [(fz, df["fuerza"] == fz)
                     for fz in ("1 pivote", "2 pivotes", "3+ pivotes")]
    grupos_fino = [(f"toque {g}", df["grupo_fino"] == g)
                   for g in ("1", "2", "3", "4-6", "7-12", "13+")]

    todos_los_cortes = (grupos_mercado
                        + grupos_toques["sintetico_otc"] + grupos_toques["indice_real"]
                        + grupos_sesion["sintetico_otc"] + grupos_sesion["indice_real"]
                        + grupos_lado + grupos_fuerza + grupos_fino)

    # Numero de celdas de probabilidad probadas, para Bonferroni.
    n_celdas = len(HORIZONTES) * len(todos_los_cortes)
    z_bonf = NormalDist().inv_cdf(1 - 0.025 / n_celdas)
    print(f"Cortes probados: {len(todos_los_cortes)} x {len(HORIZONTES)} horizontes "
          f"= {n_celdas} celdas -> z Bonferroni = {z_bonf:.3f}")

    lineas: list[str] = []
    lineas += ["", "=" * 100,
               "1) PROBABILIDAD DE ESTAR A FAVOR AL VENCIMIENTO = WINRATE DE LA BINARIA",
               "=" * 100]
    lineas += tabla_probabilidad(df, "TODAS LAS MUESTRAS (solapadas)", be, z_bonf,
                                 grupos_mercado)
    grupos_ind = [
        ("TODOS indep.", pd.Series(True, index=df_ind.index)),
        ("sintetico_otc indep.", df_ind["mercado"] == "sintetico_otc"),
        ("indice_real indep.", df_ind["mercado"] == "indice_real"),
    ]
    lineas += tabla_probabilidad(df_ind, "MUESTRA INDEPENDIENTE (sin solape)", be,
                                 z_bonf, grupos_ind)

    lineas += ["", "=" * 100, "2) CUANTO SUBE Y CUANTO BAJA", "=" * 100]
    lineas += tabla_excursiones(df, grupos_mercado)

    lineas += ["", "=" * 100, "3) EN CUANTO TIEMPO", "=" * 100]
    lineas += tabla_tiempos(df, grupos_mercado)
    lineas += tabla_trampa(df, grupos_mercado)

    lineas += ["", "=" * 100,
               "4) DESGLOSE POR NUMERO DE TOQUES PREVIOS DE LA ZONA",
               "=" * 100,
               "   toque 1 = primer retest despues de confirmarse el pivote"]
    for mercado in ("sintetico_otc", "indice_real"):
        grupos_t = grupos_toques[mercado]
        lineas += tabla_probabilidad(df, f"probabilidad a favor - {mercado}", be,
                                     z_bonf, grupos_t)
        lineas += tabla_excursiones(df, grupos_t)

    lineas += ["", "=" * 100,
               "5) DESGLOSE HORARIO (UTC). El pico de volatilidad real esta en 13-15h",
               "=" * 100]
    for mercado in ("sintetico_otc", "indice_real"):
        lineas += tabla_probabilidad(df, f"probabilidad a favor por sesion - {mercado}",
                                     be, z_bonf, grupos_sesion[mercado])

    lineas += ["", "=" * 100, "6) DESGLOSE POR LADO DE LA ZONA", "=" * 100]
    lineas += tabla_probabilidad(df, "probabilidad a favor por lado", be, z_bonf,
                                 grupos_lado)

    lineas += ["", "=" * 100,
               "7) DESGLOSE POR FUERZA DE LA ZONA (pivotes distintos que la formaron)",
               "=" * 100,
               "   Es el filtro de calidad: una zona tocada por 3 pivotes es la que un",
               "   operador dibujaria; una de 1 solo pivote es cualquier maximo local."]
    lineas += tabla_probabilidad(df, "probabilidad a favor por fuerza de zona", be,
                                 z_bonf, grupos_fuerza)
    lineas += tabla_excursiones(df, grupos_fuerza)

    lineas += ["", "=" * 100,
               "8) EL CAJON '4+' ABIERTO: reparto fino del numero de toque", "=" * 100]
    lineas += tabla_probabilidad(df, "probabilidad a favor por numero de toque (fino)",
                                 be, z_bonf, grupos_fino)

    print("\n".join(lineas))

    # ---- veredicto final -------------------------------------------------
    print("=" * 100)
    print("VEREDICTO: EXISTE UN HORIZONTE CON PROBABILIDAD > BREAK-EVEN?")
    print("=" * 100)
    candidatos = []
    mejor_celda = None
    for etq, mask in todos_los_cortes:
        sub = df[mask]
        for H in HORIZONTES:
            e = celda(sub, H)
            if e["n"] < MIN_N or e["wr"] is None:
                continue
            lo_b, _ = wilson_z(e["wins"], e["n"], z_bonf)
            if e["lo"] > be:
                candidatos.append((etq, H, e, lo_b, lo_b > be))
            if mejor_celda is None or e["wr"] > mejor_celda[2]["wr"]:
                mejor_celda = (etq, H, e)

    if not candidatos:
        print("NO. Con n>=%d y IC95%% de Wilson, ninguno de los %d cortes probados "
              % (MIN_N, len(todos_los_cortes)))
        print("(mercado, numero de toques, sesion, lado, fuerza de la zona) alcanza "
              f"un limite inferior")
        print(f"por encima del break-even de {100 * be:.2f}% en ninguno de los "
              f"horizontes {list(HORIZONTES)}.")
        if mejor_celda is not None:
            etq, H, e = mejor_celda
            print()
            print("La celda mas alta de todo el barrido, que aun asi NO concluye:")
            print(f"  {etq:<30} h={H:<3} n={e['n']:<6} wr={100 * e['wr']:5.2f}% "
                  f"IC95[{100 * e['lo']:5.2f},{100 * e['hi']:5.2f}] "
                  f"-> el break-even {100 * be:.2f}% cae DENTRO del intervalo")
        print()
        print("Traducido: tocar una zona S/R no da, por si solo, ninguna expiracion "
              "rentable en estos")
        print("datos. El filtro que falta no esta en la zona: esta en lo que pasa "
              "DESPUES del toque.")
    else:
        print("Celdas cuyo IC95% queda ENTERO por encima del break-even:")
        for etq, H, e, lo_b, sobrevive in sorted(candidatos, key=lambda x: -x[2]["wr"]):
            marca = "SOBREVIVE A BONFERRONI" if sobrevive else "cae con Bonferroni"
            print(f"  {etq:<30} h={H:<3} n={e['n']:<5} wr={100 * e['wr']:5.2f}% "
                  f"IC95[{100 * e['lo']:5.2f},{100 * e['hi']:5.2f}]  {marca}")
        print()
        print("Comprobacion obligatoria en la muestra independiente (sin solape):")
        for etq, H, e, _, sobrevive in sorted(candidatos, key=lambda x: -x[2]["wr"])[:12]:
            m = etq.split(" ")[0]
            sub = df_ind[df_ind["mercado"] == m] if m in ("sintetico_otc", "indice_real") \
                else df_ind
            e2 = celda(sub, H)
            if e2["n"] == 0:
                print(f"  {etq:<30} h={H:<3} sin muestra independiente")
                continue
            print(f"  {etq:<30} h={H:<3} n={e2['n']:<5} wr={100 * e2['wr']:5.2f}% "
                  f"IC95[{100 * e2['lo']:5.2f},{100 * e2['hi']:5.2f}]")

    print()
    print("LECTURA DE LAS TABLAS")
    print("  - 'ruido' significa que el IC95% cruza el break-even: no se puede "
          "afirmar nada, ni a favor")
    print("    ni en contra. No es 'casi rentable': es desconocido.")
    print("  - 'MUESTRA INSUFICIENTE' es n < %d. Esos numeros no se deben citar." % MIN_N)
    print("  - MFE y MAE estan en ATRs del momento del toque, comparables entre "
          "activos y regimenes.")
    print("  - El tiempo hasta el extremo se mide dentro de la ventana de 30 min; "
          "un extremo en el")
    print("    minuto 30 puede ser un extremo truncado por el borde de la ventana.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
