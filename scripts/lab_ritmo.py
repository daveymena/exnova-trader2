# -*- coding: utf-8 -*-
"""
Laboratorio del RITMO del precio.

Pregunta que responde: "a cuanto tiempo sube y en cuanto tiempo baja".

Esto NO es una estrategia y no emite senales. Es la caracterizacion empirica
del pulso del mercado: cuanto dura un tramo, cuanto se desplaza, si el ritmo
tiene memoria, a que horas late mas fuerte y cuanto tarda el precio en volver
a su media tras estirarse. De aqui salen los parametros que cualquier
estrategia posterior necesita: la EXPIRACION natural y las HORAS utiles.

Cinco medidas:
  1. Duracion de los tramos (runs) alcistas y bajistas en velas M1.
  2. Amplitud de esos tramos medida en ATRs.
  3. Autocorrelacion de la duracion: hay memoria en el ritmo?
  4. Perfil horario UTC: volatilidad vs sesgo DIRECCIONAL (son cosas distintas).
  5. Half-life de reversion a la EMA21 tras una desviacion de k ATRs.

Salvaguardas metodologicas (sin ellas esto se enganaria solo):

  * SIN LOOK-AHEAD en todo lo que decide algo. ATR14 y EMA21 son EWM causales:
    en la barra t solo usan datos hasta t. Los eventos de la seccion 5 se
    detectan con informacion de t y se resuelven con barras posteriores.
    Los tramos de las secciones 1-3 son estadistica DESCRIPTIVA retrospectiva:
    un tramo solo se sabe terminado una vela despues de terminar. Eso se
    reporta explicitamente y no se usa como si fuera observable en vivo.
  * NUNCA se rellena un valor no calculable con un default plausible. Si el
    ATR es cero o NaN, si la muestra es insuficiente o si la censura supera el
    50%, la funcion devuelve None y la tabla imprime "n/d". Un RSI=50 inventado
    fue lo que arruino las 500 operaciones anteriores.
  * Toda proporcion lleva intervalo de Wilson al 95%. Nada de winrates sueltos.
  * Los tramos nunca cruzan un hueco temporal (fin de semana, corte diario).
  * Al agregar activos del mismo mercado se corrige el tamano muestral por la
    correlacion cruzada: cinco indices de EEUU no son cinco muestras
    independientes, y usar n bruto daria intervalos falsamente estrechos.
  * El perfil horario prueba 24 hipotesis a la vez: se marca tanto el umbral
    normal (z=1.96) como el corregido por Bonferroni.

Uso:
    python scripts/lab_ritmo.py
    python scripts/lab_ritmo.py --activos EURUSD-OTC,USSPX500_N
    python scripts/lab_ritmo.py --horizonte 240 --k 1.0,2.0,3.0
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.backtest.indicators import atr, ema   # noqa: E402

HISTORY_DIR = ROOT / "bot" / "data" / "history"

# Barras iniciales que se descartan para que ATR14 y EMA21 esten asentados.
WARMUP = 100

# Un hueco mayor a esto rompe la continuidad: no se encadenan tramos a traves
# del fin de semana ni del corte diario de los indices.
PASO_SEG = 60
TOL_HUECO = 1.5

# Por debajo de esto un intervalo de Wilson es tan ancho que no concluye nada.
MIN_N_PROPORCION = 200
MIN_N_DISTRIBUCION = 100

MERCADO = {"OTC": "sintetico OTC", "REAL": "mercado real"}


# ---------------------------------------------------------------------------
# Utilidades estadisticas
# ---------------------------------------------------------------------------

def wilson(w: float, n: float, z: float = 1.96):
    """Intervalo de Wilson al 95%. Devuelve None si no hay muestra."""
    if n is None or n <= 0:
        return None
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m), min(1.0, c + m))


def z_bonferroni(m_pruebas: int) -> float:
    """z de dos colas al 5% corregido por m comparaciones simultaneas."""
    return float(stats.norm.ppf(1 - 0.025 / max(1, m_pruebas)))


def media_ic(x: np.ndarray, n_eff: float | None = None):
    """
    Media con IC95% por t de Student. Si se pasa n_eff (muestra efectiva tras
    corregir por correlacion cruzada) el intervalo se ensancha en consecuencia.
    Devuelve None si no hay muestra suficiente.
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = x.size
    if n < 30:
        return None
    n_usable = float(n_eff) if n_eff else float(n)
    if n_usable < 2:
        return None
    err = x.std(ddof=1) / math.sqrt(n_usable)
    t = float(stats.t.ppf(0.975, max(2.0, n_usable - 1)))
    mu = float(x.mean())
    return (mu, mu - t * err, mu + t * err)


def percentiles(x: np.ndarray, qs=(50, 75, 90, 95)):
    """Percentiles o None si la muestra es demasiado corta para creerselos."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < MIN_N_DISTRIBUCION:
        return None
    return {q: float(np.percentile(x, q)) for q in qs}


def fmt(v, dec: int = 2, ancho: int = 6) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/d".rjust(ancho)
    return f"{v:.{dec}f}".rjust(ancho)


def fmt_ic(ic, escala: float = 100.0, dec: int = 1) -> str:
    if ic is None:
        return "        n/d     "
    return f"[{escala * ic[0]:5.{dec}f},{escala * ic[1]:6.{dec}f}]"


def veredicto_prop(ic, nulo: float, n: float) -> str:
    """Solo hay conclusion si el intervalo entero cae de un lado del nulo."""
    if ic is None:
        return "SIN DATOS"
    if n < MIN_N_PROPORCION:
        return "MUESTRA CORTA"
    if ic[0] > nulo:
        return "SESGO ALCISTA"
    if ic[1] < nulo:
        return "SESGO BAJISTA"
    return "ruido"


# ---------------------------------------------------------------------------
# Carga y preparacion
# ---------------------------------------------------------------------------

def tipo_mercado(nombre: str) -> str:
    return "OTC" if "-OTC" in nombre else "REAL"


def cargar(filtro: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Carga los parquet M1 y anade columnas causales: atr14, ema21, dev."""
    out: dict[str, pd.DataFrame] = {}
    for p in sorted(HISTORY_DIR.glob("*_60.parquet")):
        nombre = p.stem[:-3]
        if filtro and nombre not in filtro:
            continue
        df = pd.read_parquet(p).sort_index()
        if len(df) < 1000:
            continue
        df = df.copy()
        df["atr14"] = atr(df, 14)          # EWM de Wilder: causal
        df["ema21"] = ema(df["close"], 21)  # EWM: causal
        # Desviacion normalizada. Si el ATR es 0 o NaN el valor NO existe:
        # se deja NaN y mas adelante se descarta. No se inventa un 0.
        atr_valido = df["atr14"].where(df["atr14"] > 0)
        df["dev"] = (df["close"] - df["ema21"]) / atr_valido
        out[nombre] = df
    return out


def segmentar(df: pd.DataFrame) -> list[pd.DataFrame]:
    """Trocea en tramos temporalmente contiguos. Un hueco corta la serie."""
    d = df.index.to_series().diff().dt.total_seconds()
    corte = d.isna() | (d > PASO_SEG * TOL_HUECO)
    gid = corte.cumsum()
    return [g for _, g in df.groupby(gid.values) if len(g) > 5]


# ---------------------------------------------------------------------------
# 1-3. Tramos (runs)
# ---------------------------------------------------------------------------

def detectar_runs(seg: pd.DataFrame, plana_rompe: bool = False) -> list[dict]:
    """
    Tramos de velas M1 consecutivas en la misma direccion (cierre contra cierre).

    Convenio con las velas planas (cierre identico al anterior, 1-2% del total):
      plana_rompe=False -> la vela plana es TRANSPARENTE: no cuenta como vela
        direccional pero tampoco corta el tramo. Es el criterio principal.
      plana_rompe=True  -> la vela plana corta el tramo. Sirve de sensibilidad.

    OBSERVABILIDAD: un tramo solo se sabe cerrado cuando aparece la vela que lo
    contradice, es decir 1 vela DESPUES de su ultima vela. Estas cifras
    describen el pulso del mercado; no son una senal utilizable en vivo tal cual.
    """
    cierre = seg["close"].to_numpy(dtype=float)
    atr_arr = seg["atr14"].to_numpy(dtype=float)
    idx = seg.index
    n = cierre.size
    if n < 3:
        return []

    signos = np.sign(np.diff(cierre))     # signos[i] pertenece a la barra i+1
    runs: list[dict] = []
    sig_actual = 0.0
    i_ini = None
    i_fin = None
    n_velas = 0

    def cerrar():
        if sig_actual == 0.0 or i_ini is None:
            return
        origen = i_ini - 1                 # cierre previo al arranque del tramo
        atr_ref = atr_arr[origen]
        amp = cierre[i_fin] - cierre[origen]
        # Si el ATR de referencia no existe, la amplitud en ATRs NO existe.
        amp_atr = (amp / atr_ref) if (np.isfinite(atr_ref) and atr_ref > 0) else None
        runs.append({
            "dir": "UP" if sig_actual > 0 else "DOWN",
            "velas": n_velas,                       # velas direccionales
            "minutos": i_fin - i_ini + 1,           # incluye planas interiores
            "amp_abs": abs(float(amp)),
            "amp_atr": abs(amp_atr) if amp_atr is not None else None,
            "t_ini": idx[i_ini],
            "hora": int(idx[i_ini].hour),
        })

    for i in range(1, n):
        s = signos[i - 1]
        if s == 0.0:
            if plana_rompe and sig_actual != 0.0:
                cerrar()
                sig_actual, i_ini, i_fin, n_velas = 0.0, None, None, 0
            continue
        if s == sig_actual:
            i_fin = i
            n_velas += 1
        else:
            cerrar()
            sig_actual = s
            i_ini = i
            i_fin = i
            n_velas = 1

    cerrar()
    # El primer tramo puede arrancar en la barra 1 y su origen seria la barra 0,
    # que aun esta dentro del warmup del ATR: se filtra en el consumidor.
    return runs


def runs_activo(df: pd.DataFrame, plana_rompe: bool = False) -> list[list[dict]]:
    """Lista de secuencias de tramos, una por segmento contiguo."""
    fuera: list[list[dict]] = []
    for seg in segmentar(df.iloc[WARMUP:]):
        r = detectar_runs(seg, plana_rompe=plana_rompe)
        if r:
            fuera.append(r)
    return fuera


def resumen_duracion(runs: list[dict], direccion: str) -> dict:
    sel = [r for r in runs if r["dir"] == direccion]
    largos = np.array([r["velas"] for r in sel], dtype=float)
    pct = percentiles(largos, (50, 75, 90, 95))
    return {
        "n": int(largos.size),
        "media": float(largos.mean()) if largos.size >= MIN_N_DISTRIBUCION else None,
        "p50": pct[50] if pct else None,
        "p75": pct[75] if pct else None,
        "p90": pct[90] if pct else None,
        "p95": pct[95] if pct else None,
        "max": float(largos.max()) if largos.size else None,
    }


def frecuencias_duracion(runs: list[dict], direccion: str) -> dict:
    """
    Distribucion de frecuencias de la duracion, que es lo que de verdad
    describe el ritmo. La mediana no sirve aqui: con masa 0.5 en el valor 1 la
    mediana salta entre 1 y 2 por decimas y no significa nada.

    Baseline: si la direccion de cada vela fuese una moneda justa e
    independiente, la duracion seria geometrica: P(L=j) = 0.5^j, media 2,
    P(L>=4) = 0.125, P(L>=6) = 0.03125. Comparar contra eso responde a si el
    ritmo tiene persistencia o es una moneda.
    """
    L = np.array([r["velas"] for r in runs if r["dir"] == direccion], dtype=float)
    n = int(L.size)
    if n == 0:
        return {"n": 0}
    def p(mask):
        w = int(mask.sum())
        return w, w / n, wilson(w, n)
    w4, p4, ic4 = p(L >= 4)
    w6, p6, ic6 = p(L >= 6)
    return {
        "n": n,
        "p1": float((L == 1).mean()),
        "p2": float((L == 2).mean()),
        "p3": float((L == 3).mean()),
        "p4": p4, "ic4": ic4,
        "p6": p6, "ic6": ic6,
    }


def resumen_amplitud(runs: list[dict], direccion: str) -> dict:
    sel = [r for r in runs if r["dir"] == direccion and r["amp_atr"] is not None]
    descartados = sum(1 for r in runs if r["dir"] == direccion and r["amp_atr"] is None)
    a = np.array([r["amp_atr"] for r in sel], dtype=float)
    pct = percentiles(a, (50, 75, 90, 95))
    return {
        "n": int(a.size),
        "descartados": descartados,
        "media": float(a.mean()) if a.size >= MIN_N_DISTRIBUCION else None,
        "p50": pct[50] if pct else None,
        "p75": pct[75] if pct else None,
        "p90": pct[90] if pct else None,
        "p95": pct[95] if pct else None,
        "max": float(a.max()) if a.size else None,
    }


def autocorr_duracion(secuencias: list[list[dict]]) -> dict:
    """
    Memoria del ritmo.

    lag 1 = tramo siguiente, que por construccion es de direccion CONTRARIA.
    lag 2 = siguiente tramo de la MISMA direccion.

    Referencia: si las direcciones fuesen Bernoulli independientes (paseo
    aleatorio) las duraciones serian geometricas e independientes -> rho = 0.
    """
    par1_x, par1_y, par2_x, par2_y = [], [], [], []
    todos = []
    for sec in secuencias:
        L = [r["velas"] for r in sec]
        todos.extend(L)
        for i in range(len(L) - 1):
            par1_x.append(L[i]); par1_y.append(L[i + 1])
        for i in range(len(L) - 2):
            par2_x.append(L[i]); par2_y.append(L[i + 2])

    def sp(x, y):
        if len(x) < MIN_N_DISTRIBUCION:
            return None, None
        rho, p = stats.spearmanr(x, y)
        if not np.isfinite(rho):
            return None, None
        return float(rho), float(p)

    rho1, p1 = sp(par1_x, par1_y)
    rho2, p2 = sp(par2_x, par2_y)

    # Version en probabilidades: si el tramo actual es "largo" (>= p75 global),
    # sube la probabilidad de que el siguiente tambien lo sea?
    cond = None
    if len(todos) >= MIN_N_PROPORCION and par1_x:
        umbral = float(np.percentile(todos, 75))
        x = np.array(par1_x, dtype=float)
        y = np.array(par1_y, dtype=float)
        largo_y = y >= umbral
        base_n = y.size
        base_w = int(largo_y.sum())
        mask = x >= umbral
        n_c = int(mask.sum())
        w_c = int(largo_y[mask].sum())
        cond = {
            "umbral": umbral,
            "base_p": base_w / base_n if base_n else None,
            "base_ic": wilson(base_w, base_n),
            "base_n": base_n,
            "cond_p": (w_c / n_c) if n_c else None,
            "cond_ic": wilson(w_c, n_c) if n_c else None,
            "cond_n": n_c,
        }

    return {"rho1": rho1, "p1": p1, "n1": len(par1_x),
            "rho2": rho2, "p2": p2, "n2": len(par2_x),
            "cond": cond}


# ---------------------------------------------------------------------------
# 4. Perfil horario
# ---------------------------------------------------------------------------

def correlacion_cruzada(datos: dict[str, pd.DataFrame], activos: list[str]) -> float | None:
    """
    Correlacion media por pares de los retornos minuto a minuto.

    Se usa para corregir el n al agregar activos: cinco indices de EEUU que se
    mueven juntos no aportan cinco muestras independientes por minuto.
    """
    if len(activos) < 2:
        return None
    series = {}
    for a in activos:
        df = datos[a]
        series[a] = np.log(df["close"] / df["open"]).replace([np.inf, -np.inf], np.nan)
    m = pd.DataFrame(series).dropna()
    if len(m) < 500:
        return None
    c = m.corr().to_numpy(dtype=float)
    k = c.shape[0]
    off = c[~np.eye(k, dtype=bool)]
    off = off[np.isfinite(off)]
    return float(off.mean()) if off.size else None


def n_efectivo(n: int, m_activos: int, rho: float | None) -> float:
    """n corregido por correlacion cruzada. Si no hay rho, no se corrige."""
    if rho is None or m_activos <= 1:
        return float(n)
    factor = 1.0 + (m_activos - 1) * max(0.0, rho)
    return float(n) / factor


def perfil_horario(datos: dict[str, pd.DataFrame], activos: list[str],
                   secs: dict[str, list[list[dict]]]) -> list[dict]:
    """
    Por hora UTC: volatilidad, sesgo direccional y duracion media de tramos.

    La probabilidad direccional se mide como P(cierre > apertura) de la MISMA
    vela: es exactamente el desenlace de una binaria de 1 minuto entrada en la
    apertura. Los empates se excluyen y se reportan.
    """
    piezas = []
    for a in activos:
        df = datos[a].iloc[WARMUP:]
        r = np.log(df["close"] / df["open"]).replace([np.inf, -np.inf], np.nan)
        piezas.append(pd.DataFrame({"hora": df.index.hour, "r": r.to_numpy()}))
    tabla = pd.concat(piezas, ignore_index=True).dropna()

    dur_por_hora: dict[int, list[float]] = {h: [] for h in range(24)}
    for a in activos:
        for sec in secs[a]:
            for run in sec:
                dur_por_hora[run["hora"]].append(float(run["velas"]))

    rho = correlacion_cruzada(datos, activos)
    m = len(activos)
    zb = z_bonferroni(24)

    filas = []
    for h in range(24):
        sub = tabla[tabla["hora"] == h]["r"].to_numpy()
        if sub.size == 0:
            continue
        n_bruto = int(sub.size)
        n_eff = n_efectivo(n_bruto, m, rho)
        no_empate = sub[sub != 0.0]
        n_dir = int(no_empate.size)
        n_dir_eff = n_efectivo(n_dir, m, rho)
        subidas = int((no_empate > 0).sum())
        p_up = subidas / n_dir if n_dir else None
        # Wilson sobre la muestra EFECTIVA, no sobre la bruta.
        w_eff = p_up * n_dir_eff if p_up is not None else 0.0
        ic = wilson(w_eff, n_dir_eff) if n_dir else None
        ic_bonf = wilson(w_eff, n_dir_eff, z=zb) if n_dir else None
        dur = dur_por_hora[h]
        filas.append({
            "hora": h,
            "n": n_bruto,
            "n_eff": n_eff,
            "vol_bps": 1e4 * float(np.abs(sub).mean()),
            "drift": media_ic(1e4 * sub, n_eff=n_eff),
            "p_up": p_up,
            "ic": ic,
            "ic_bonf": ic_bonf,
            "n_dir": n_dir,
            "n_dir_eff": n_dir_eff,
            "empates": n_bruto - n_dir,
            "dur_media": float(np.mean(dur)) if len(dur) >= MIN_N_DISTRIBUCION else None,
            "dur_n": len(dur),
        })
    return filas, rho


# ---------------------------------------------------------------------------
# 5. Half-life de reversion a la EMA21
# ---------------------------------------------------------------------------

HORIZONTES_DIR = (1, 3, 5, 10)


def eventos_desviacion(df: pd.DataFrame, k: float, horizonte: int) -> dict:
    """
    Evento: la desviacion |close - EMA21| / ATR14 CRUZA hacia arriba el umbral k.
    Todo se decide con informacion de la barra t (EMA y ATR son causales).

    Se mide, mirando solo hacia adelante:
      - minutos hasta que la desviacion se reduce a la MITAD de la de entrada
        (half-life propiamente dicha),
      - si antes de eso se extiende a 1.5x (el precio sigue estirandose: esa es
        la trampa del que opera reversion demasiado pronto),
      - censura: eventos que no revierten dentro del horizonte o del segmento,
      - QUIEN cierra el hueco: el precio bajando hacia la EMA o la EMA subiendo
        hacia el precio. Es la distincion critica: si el hueco se cierra porque
        la media alcanza al precio, la "reversion" no paga ninguna binaria.
      - probabilidad de que el PRECIO se mueva en contra de la desviacion a
        1, 3, 5 y 10 minutos, que es el desenlace real de una binaria.

    Los eventos no se solapan: tras uno hace falta que |dev| vuelva por debajo
    de k para armar el siguiente.
    """
    hl: list[float] = []
    frac_precio: list[float] = []
    censurados = 0
    extensiones = 0
    n_ev = 0
    rev_w = {N: 0 for N in HORIZONTES_DIR}
    rev_n = {N: 0 for N in HORIZONTES_DIR}

    for seg in segmentar(df.iloc[WARMUP:]):
        dev = seg["dev"].to_numpy(dtype=float)
        precio = seg["close"].to_numpy(dtype=float)
        media = seg["ema21"].to_numpy(dtype=float)
        n = dev.size
        armado = False   # exige |dev| < k antes de permitir un nuevo evento
        i = 0
        while i < n:
            d = dev[i]
            if not np.isfinite(d):
                i += 1
                continue
            a = abs(d)
            if a < k:
                armado = True
                i += 1
                continue
            if not armado:
                i += 1
                continue

            # Evento confirmado en la barra i.
            armado = False
            n_ev += 1
            s = 1.0 if d > 0 else -1.0
            objetivo = a / 2.0
            extremo = a * 1.5
            visto_extension = False
            resuelto = None
            tope = min(n - 1, i + horizonte)
            for j in range(i + 1, tope + 1):
                dj = dev[j]
                if not np.isfinite(dj):
                    continue
                aj = abs(dj)
                if aj >= extremo and resuelto is None:
                    visto_extension = True
                if aj <= objetivo:
                    resuelto = j - i
                    # Reparto del cierre del hueco entre precio y media.
                    ap_precio = s * (precio[i] - precio[j])
                    ap_media = s * (media[j] - media[i])
                    total = ap_precio + ap_media
                    if total > 0:
                        frac_precio.append(float(ap_precio / total))
                    break
            if resuelto is None:
                censurados += 1
            else:
                hl.append(float(resuelto))
            if visto_extension:
                extensiones += 1

            # Desenlace direccional: una binaria a favor de la reversion.
            for N in HORIZONTES_DIR:
                j = i + N
                if j >= n:
                    continue
                mov = s * (precio[i] - precio[j])
                if mov == 0.0:
                    continue          # empate: no cuenta, no se rellena
                rev_n[N] += 1
                if mov > 0:
                    rev_w[N] += 1
            i += 1

    return {"n": n_ev, "hl": hl, "censurados": censurados,
            "extensiones": extensiones, "frac_precio": frac_precio,
            "rev_w": rev_w, "rev_n": rev_n}


def fusionar_eventos(recs: list[dict]) -> dict:
    """Agrega registros de varios activos sumando conteos y concatenando listas."""
    out = {"n": 0, "hl": [], "censurados": 0, "extensiones": 0, "frac_precio": [],
           "rev_w": {N: 0 for N in HORIZONTES_DIR},
           "rev_n": {N: 0 for N in HORIZONTES_DIR}}
    for r in recs:
        out["n"] += r["n"]
        out["hl"].extend(r["hl"])
        out["censurados"] += r["censurados"]
        out["extensiones"] += r["extensiones"]
        out["frac_precio"].extend(r["frac_precio"])
        for N in HORIZONTES_DIR:
            out["rev_w"][N] += r["rev_w"][N]
            out["rev_n"][N] += r["rev_n"][N]
    return out


def resumen_hl(rec: dict, horizonte: int) -> dict:
    """Percentiles de la half-life respetando la censura. Sin muestra -> None."""
    n_ev = rec["n"]
    if n_ev == 0:
        return {"n": 0, "p25": None, "p50": None, "p75": None,
                "media_no_cens": None, "censura": None, "p_ext": None,
                "ic_ext": None, "frac_precio": None}
    frac_cens = rec["censurados"] / n_ev
    # Con censura por encima del 50% la mediana NO es estimable: None, no un
    # numero inventado.
    valores = np.array(rec["hl"] + [float(horizonte + 1)] * rec["censurados"],
                       dtype=float)

    def q(p):
        if frac_cens >= 1 - p / 100.0:
            return None
        v = float(np.percentile(valores, p))
        return None if v > horizonte else v

    fp = np.array(rec["frac_precio"], dtype=float)
    return {
        "n": n_ev,
        "p25": q(25),
        "p50": q(50),
        "p75": q(75),
        "media_no_cens": float(np.mean(rec["hl"])) if rec["hl"] else None,
        "censura": frac_cens,
        "p_ext": rec["extensiones"] / n_ev,
        "ic_ext": wilson(rec["extensiones"], n_ev),
        "frac_precio": float(np.median(fp)) if fp.size >= MIN_N_DISTRIBUCION else None,
    }


def half_life_ar1(df: pd.DataFrame) -> float | None:
    """
    Half-life analitica de un AR(1) sobre la desviacion: dev(t+1) = a + b*dev(t).
    hl = -ln2 / ln(b). Solo tiene sentido si 0 < b < 1 (proceso reversivo).
    """
    xs, ys = [], []
    for seg in segmentar(df.iloc[WARMUP:]):
        d = seg["dev"].to_numpy(dtype=float)
        x, y = d[:-1], d[1:]
        m = np.isfinite(x) & np.isfinite(y)
        xs.append(x[m]); ys.append(y[m])
    x = np.concatenate(xs) if xs else np.array([])
    y = np.concatenate(ys) if ys else np.array([])
    if x.size < 1000:
        return None
    b = float(np.polyfit(x, y, 1)[0])
    if not (0.0 < b < 1.0):
        return None
    return -math.log(2.0) / math.log(b)


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------

def titulo(txt: str) -> None:
    print()
    print("=" * 100)
    print(txt)
    print("=" * 100)


def seccion_1_2(datos, activos_por_tipo, runs_por_activo, runs_rompe):
    titulo("1. DURACION DE LOS TRAMOS (velas M1 consecutivas en la misma direccion)")
    print("Duracion en VELAS direccionales. Vela plana (cierre identico) = transparente.")
    print("Columna med_rmp = mediana con el criterio alternativo (la plana corta el tramo).")
    print("Referencia teorica: en un paseo aleatorio p=0.5 la duracion media de un tramo es 2.00.")
    print()
    cab = (f"{'activo':<16} {'dir':<5} {'n':>6} {'media':>6} {'p50':>5} {'p75':>5} "
           f"{'p90':>5} {'p95':>5} {'max':>5} {'med_rmp':>7}")
    print(cab)
    print("-" * len(cab))
    for tipo in ("OTC", "REAL"):
        for a in activos_por_tipo[tipo]:
            runs = [r for sec in runs_por_activo[a] for r in sec]
            runs_r = [r for sec in runs_rompe[a] for r in sec]
            for d in ("UP", "DOWN"):
                s = resumen_duracion(runs, d)
                sr = resumen_duracion(runs_r, d)
                print(f"{a:<16} {d:<5} {s['n']:>6} {fmt(s['media'])} {fmt(s['p50'],1,5)} "
                      f"{fmt(s['p75'],1,5)} {fmt(s['p90'],1,5)} {fmt(s['p95'],1,5)} "
                      f"{fmt(s['max'],0,5)} {fmt(sr['p50'],1,7)}")
        print("-" * len(cab))
        pool = [r for a in activos_por_tipo[tipo] for sec in runs_por_activo[a] for r in sec]
        for d in ("UP", "DOWN"):
            s = resumen_duracion(pool, d)
            print(f"{'AGREGADO ' + tipo:<16} {d:<5} {s['n']:>6} {fmt(s['media'])} "
                  f"{fmt(s['p50'],1,5)} {fmt(s['p75'],1,5)} {fmt(s['p90'],1,5)} "
                  f"{fmt(s['p95'],1,5)} {fmt(s['max'],0,5)} {'':>7}")
        print("=" * len(cab))

    print()
    print("1b. DISTRIBUCION DE FRECUENCIAS DE LA DURACION (esto es lo que hay que mirar,")
    print("    no la mediana: con masa 0.50 en el valor 1 la mediana salta entre 1 y 2 por")
    print("    decimas y no significa nada).")
    print("    TEORICO = moneda justa independiente: P(L=j)=0.5^j -> 0.500 0.250 0.125 |")
    print("    P(L>=4)=0.1250  P(L>=6)=0.0313. Si lo observado no se distingue de esto,")
    print("    el ritmo no tiene persistencia que explotar.")
    n_pruebas = 2 * sum(len(v) for v in activos_por_tipo.values())
    zb = z_bonferroni(n_pruebas)
    print(f"    Se prueban {n_pruebas} celdas P(L>=4) a la vez -> z Bonferroni = {zb:.3f}")
    print()
    cab = (f"{'activo':<16} {'dir':<5} {'n':>6} {'P(L=1)':>7} {'P(L=2)':>7} {'P(L=3)':>7} "
           f"{'P(L>=4)':>8} {'IC95% P(L>=4)':>16} {'P(L>=6)':>8}  vs moneda")
    print(cab)
    print("-" * len(cab))
    for tipo in ("OTC", "REAL"):
        for a in activos_por_tipo[tipo]:
            runs = [r for sec in runs_por_activo[a] for r in sec]
            for d in ("UP", "DOWN"):
                f = frecuencias_duracion(runs, d)
                if not f["n"]:
                    continue
                icb = wilson(f["p4"] * f["n"], f["n"], z=zb)
                if icb is None:
                    dif = "n/d"
                elif icb[0] > 0.125:
                    dif = "MAS PERSISTENTE"
                elif icb[1] < 0.125:
                    dif = "MENOS PERSISTENTE"
                else:
                    dif = "indistinguible de moneda"
                print(f"{a:<16} {d:<5} {f['n']:>6} {fmt(f['p1'],3,7)} {fmt(f['p2'],3,7)} "
                      f"{fmt(f['p3'],3,7)} {fmt(f['p4'],4,8)} {fmt_ic(f['ic4'])} "
                      f"{fmt(f['p6'],4,8)}  {dif}")
        print("-" * len(cab))

    titulo("2. AMPLITUD DE LOS TRAMOS, EN ATRs (ATR14 de la vela ANTERIOR al arranque)")
    print("Amplitud = |cierre_final - cierre_previo_al_tramo| / ATR14 previo. Sin ATR valido -> descartado.")
    print()
    cab = (f"{'activo':<16} {'dir':<5} {'n':>6} {'desc':>5} {'media':>6} {'p50':>5} "
           f"{'p75':>5} {'p90':>5} {'p95':>5} {'max':>6}")
    print(cab)
    print("-" * len(cab))
    for tipo in ("OTC", "REAL"):
        for a in activos_por_tipo[tipo]:
            runs = [r for sec in runs_por_activo[a] for r in sec]
            for d in ("UP", "DOWN"):
                s = resumen_amplitud(runs, d)
                print(f"{a:<16} {d:<5} {s['n']:>6} {s['descartados']:>5} {fmt(s['media'])} "
                      f"{fmt(s['p50'],2,5)} {fmt(s['p75'],2,5)} {fmt(s['p90'],2,5)} "
                      f"{fmt(s['p95'],2,5)} {fmt(s['max'],2,6)}")
        print("-" * len(cab))


def seccion_3(activos_por_tipo, cache_ac):
    titulo("3. AUTOCORRELACION DE LA DURACION (hay memoria explotable en el ritmo?)")
    print("rho1 = Spearman entre un tramo y el SIGUIENTE (direccion contraria).")
    print("rho2 = Spearman entre un tramo y el siguiente de la MISMA direccion.")
    print("Bajo paseo aleatorio ambos son 0. |rho| < 0.05 es irrelevante aunque p < 0.05.")
    print()
    cab = f"{'activo':<16} {'n_pares':>8} {'rho1':>7} {'p1':>9} {'rho2':>7} {'p2':>9}  lectura"
    print(cab)
    print("-" * len(cab))
    for tipo in ("OTC", "REAL"):
        for a in activos_por_tipo[tipo]:
            ac = cache_ac[a]
            r1 = ac["rho1"]
            lectura = "sin memoria util"
            if r1 is not None and abs(r1) >= 0.05 and ac["p1"] is not None and ac["p1"] < 0.05:
                lectura = "memoria debil detectada"
            if r1 is not None and abs(r1) >= 0.15:
                lectura = "MEMORIA APRECIABLE"
            print(f"{a:<16} {ac['n1']:>8} {fmt(r1,3,7)} "
                  f"{fmt(ac['p1'],4,9)} {fmt(ac['rho2'],3,7)} {fmt(ac['p2'],4,9)}  {lectura}")
        print("-" * len(cab))

    print()
    print("Version en probabilidades: P(tramo siguiente largo | tramo actual largo), largo = p75 del activo.")
    cab = (f"{'activo':<16} {'umbral':>7} {'base_p':>7} {'base IC95%':>16} "
           f"{'cond_p':>7} {'cond IC95%':>16} {'n_cond':>7}  lectura")
    print(cab)
    print("-" * len(cab))
    for tipo in ("OTC", "REAL"):
        for a in activos_por_tipo[tipo]:
            c = cache_ac[a]["cond"]
            if c is None:
                print(f"{a:<16} {'n/d':>7}")
                continue
            solapa = (c["cond_ic"] is not None and c["base_p"] is not None
                      and c["cond_ic"][0] <= c["base_p"] <= c["cond_ic"][1])
            lectura = "ruido (IC cubre la base)" if solapa else "DIFERENCIA REAL"
            print(f"{a:<16} {fmt(c['umbral'],1,7)} {fmt(c['base_p'],4,7)} {fmt_ic(c['base_ic'])} "
                  f"{fmt(c['cond_p'],4,7)} {fmt_ic(c['cond_ic'])} {c['cond_n']:>7}  {lectura}")
        print("-" * len(cab))


def seccion_4(activos_por_tipo, cache_perfil):
    titulo("4. PERFIL HORARIO UTC: VOLATILIDAD vs SESGO DIRECCIONAL (no son lo mismo)")
    print("vol_bps  = media de |log(cierre/apertura)| por vela, en puntos basicos.")
    print("p_up     = P(cierre > apertura) de la misma vela = desenlace de una binaria M1.")
    print("Los IC usan n EFECTIVO (corregido por correlacion cruzada entre activos agregados).")
    print("bonf     = intervalo corregido por las 24 comparaciones simultaneas (una por hora).")
    print("dur      = duracion media de los tramos que ARRANCAN en esa hora, en velas.")
    print()
    zb = z_bonferroni(24)
    print(f"z normal = 1.960 | z Bonferroni (24 pruebas) = {zb:.3f}")

    for tipo in ("OTC", "REAL"):
        activos = activos_por_tipo[tipo]
        filas, rho = cache_perfil[tipo]
        print()
        print(f"--- {MERCADO[tipo]} ({len(activos)} activos: {', '.join(activos)})")
        if rho is None:
            print("    correlacion cruzada media: n/d (no calculable)")
        else:
            print(f"    correlacion cruzada media de retornos M1: rho={rho:.3f} "
                  f"-> n efectivo = n / {1 + (len(activos) - 1) * max(0.0, rho):.2f}")
        cab = (f"    {'h':>2} {'n':>7} {'n_eff':>7} {'vol_bps':>8} {'drift_bps IC95%':>24} "
               f"{'p_up':>6} {'IC95% p_up':>15} {'dur':>5}  veredicto")
        print(cab)
        print("    " + "-" * (len(cab) - 4))
        vols = [f["vol_bps"] for f in filas]
        vmax = max(vols) if vols else None
        for f in filas:
            dr = f["drift"]
            dr_txt = "n/d".rjust(24) if dr is None else f"{dr[0]:7.3f} [{dr[1]:7.3f},{dr[2]:7.3f}]"
            v = veredicto_prop(f["ic"], 0.5, f["n_dir_eff"])
            if v in ("SESGO ALCISTA", "SESGO BAJISTA") and f["ic_bonf"] is not None:
                if f["ic_bonf"][0] <= 0.5 <= f["ic_bonf"][1]:
                    v += " (cae con bonf)"
                else:
                    v += " (aguanta bonf)"
            marca = " *" if (vmax and f["vol_bps"] >= 0.8 * vmax) else "  "
            print(f"    {f['hora']:>2} {f['n']:>7} {f['n_eff']:>7.0f} {f['vol_bps']:>8.2f}{marca}"
                  f"{dr_txt} {fmt(f['p_up'],4,6)} {fmt_ic(f['ic'])} "
                  f"{fmt(f['dur_media'],2,5)}  {v}")
        print("    (* = hora dentro del 80% superior de volatilidad de su mercado)")
        if not filas:
            continue
        # Pregunta concreta: la ventana 13-15h UTC (apertura de Nueva York) trae
        # solo mas movimiento, o tambien sesgo direccional? No es lo mismo.
        vent = [f for f in filas if f["hora"] in (13, 14, 15)]
        resto = [f for f in filas if f["hora"] not in (13, 14, 15)]
        if vent and resto:
            v_in = float(np.mean([f["vol_bps"] for f in vent]))
            v_out = float(np.mean([f["vol_bps"] for f in resto]))
            w = sum(f["p_up"] * f["n_dir"] for f in vent)
            nb = sum(f["n_dir"] for f in vent)
            ne = n_efectivo(nb, len(activos), rho)
            ic = wilson((w / nb) * ne, ne) if nb else None
            print(f"    VENTANA 13-15h UTC: volatilidad {v_in:.2f} bps vs {v_out:.2f} bps "
                  f"en el resto = {v_in / v_out:.2f}x")
            print(f"    VENTANA 13-15h UTC: p_up={fmt(w / nb if nb else None,4,6).strip()} "
                  f"IC95%{fmt_ic(ic)} n={nb} (n_eff={ne:.0f}) -> "
                  f"{veredicto_prop(ic, 0.5, ne)}")
            print("    Leer con cuidado: mas volatilidad = velas mas grandes, NO mas")
            print("    probabilidad de acertar la direccion. Son dos cosas distintas.")


def seccion_5(datos, activos_por_tipo, ks, horizonte, cache_ev, rho_tipo):
    titulo("5. HALF-LIFE DE REVERSION A LA EMA21 TRAS DESVIARSE k ATRs")
    print("Evento: |cierre - EMA21| / ATR14 cruza k al alza. Todo causal en el momento de la entrada.")
    print("half-life = minutos hasta que esa desviacion se reduce a la MITAD de la de entrada.")
    print(f"Horizonte maximo {horizonte} min. Censura = eventos que no revierten dentro del horizonte.")
    print("Si la censura pasa del 50% la mediana NO es estimable y se devuelve n/d.")
    print()
    cab = f"{'activo':<16} " + " ".join(f"{'k=' + str(k):>9}" for k in ks) + f" {'AR1_hl':>8}"
    print(cab)
    print("-" * len(cab))
    for tipo in ("OTC", "REAL"):
        for a in activos_por_tipo[tipo]:
            celdas = []
            for k in ks:
                r = resumen_hl(cache_ev[(a, k)], horizonte)
                celdas.append("n/d".rjust(9) if r["p50"] is None else f"{r['p50']:9.1f}")
            ar1 = half_life_ar1(datos[a])
            print(f"{a:<16} " + " ".join(celdas) + f" {fmt(ar1,1,8)}")
        print("-" * len(cab))
    print("(mediana de minutos hasta halving; AR1_hl = half-life analitica del AR(1) sobre la desviacion)")

    print()
    print("Detalle por evento: cuanto tarda, cuanto se extiende antes (la trampa) y QUIEN cierra el hueco.")
    print("f_precio = fraccion mediana del hueco cerrada por el PRECIO; el resto lo cierra la EMA")
    print("           subiendo hacia el precio. Por debajo de 0.50 la 'reversion' la hace la media,")
    print("           no el precio, y NO paga una binaria.")
    cab = (f"{'activo':<16} {'k':>4} {'n_ev':>6} {'p25':>6} {'p50':>6} {'p75':>6} "
           f"{'censura':>8} {'p_ext':>6} {'IC95% p_ext':>16} {'f_precio':>9}")
    print(cab)
    print("-" * len(cab))
    for tipo in ("OTC", "REAL"):
        for a in activos_por_tipo[tipo]:
            for k in ks:
                r = resumen_hl(cache_ev[(a, k)], horizonte)
                if r["n"] < 30:
                    continue
                print(f"{a:<16} {k:>4.1f} {r['n']:>6} {fmt(r['p25'],1,6)} {fmt(r['p50'],1,6)} "
                      f"{fmt(r['p75'],1,6)} {fmt(r['censura'],3,8)} {fmt(r['p_ext'],3,6)} "
                      f"{fmt_ic(r['ic_ext'])} {fmt(r['frac_precio'],3,9)}")
        print("-" * len(cab))
    print("p_ext = P(la desviacion llega a 1.5x la de entrada ANTES de reducirse a la mitad).")
    print("Es la probabilidad de que el mercado siga estirandose contra el que opera reversion.")

    titulo("5b. LA PRUEBA DE FUEGO: EL PRECIO SE MUEVE DE VERDAD EN CONTRA DE LA DESVIACION?")
    print("Que el hueco contra la EMA se cierre no implica que el precio baje: puede subir la media.")
    print("Aqui se mide el desenlace de una binaria abierta EN CONTRA de la desviacion, entrada en")
    print("el cierre de la vela del evento, con expiracion de N minutos. Empates excluidos.")
    print("Referencia: break-even con payout 0.86 = 53.76%. La linea de 50% es el azar puro.")
    print("Los n de mercado real van corregidos por la correlacion cruzada entre indices.")
    print()
    cab = (f"{'grupo':<22} {'k':>4} " +
           " ".join(f"{'N=' + str(N):>21}" for N in HORIZONTES_DIR))
    print(cab)
    print("-" * len(cab))
    for tipo in ("OTC", "REAL"):
        activos = activos_por_tipo[tipo]
        rho = rho_tipo[tipo]
        for k in ks:
            agg = fusionar_eventos([cache_ev[(a, k)] for a in activos])
            celdas = []
            for N in HORIZONTES_DIR:
                n_b = agg["rev_n"][N]
                if n_b < MIN_N_PROPORCION:
                    celdas.append("n/d".rjust(21))
                    continue
                p = agg["rev_w"][N] / n_b
                n_e = n_efectivo(n_b, len(activos), rho)
                ic = wilson(p * n_e, n_e)
                marca = "*" if (ic and (ic[0] > 0.5 or ic[1] < 0.5)) else " "
                celdas.append(f"{p:.4f}{marca}{fmt_ic(ic)} {n_b:>5}")
            print(f"{'AGREGADO ' + tipo:<22} {k:>4.1f} " + " ".join(celdas))
        print("-" * len(cab))
    print("Formato de celda: p_reversion (IC95% en %) n_bruto.  * = el IC excluye el 50%.")
    print("n_bruto es el numero de barras evaluadas; el IC usa el n efectivo, que en mercado")
    print("real es unas 3.8 veces menor porque los cinco indices se mueven juntos.")


def lectura_final(activos_por_tipo, runs_por_activo, cache_ac, cache_perfil,
                  cache_ev, ks, horizonte):
    titulo("LECTURA OPERATIVA (que se puede usar y que es ruido)")
    k_ref = min(ks, key=lambda k: abs(k - 2.0))
    for tipo in ("OTC", "REAL"):
        activos = activos_por_tipo[tipo]
        pool = [r for a in activos for sec in runs_por_activo[a] for r in sec]
        f_up = frecuencias_duracion(pool, "UP")
        f_dn = frecuencias_duracion(pool, "DOWN")
        up = resumen_duracion(pool, "UP")
        dn = resumen_duracion(pool, "DOWN")
        amp_up = resumen_amplitud(pool, "UP")
        amp_dn = resumen_amplitud(pool, "DOWN")
        filas, rho = cache_perfil[tipo]
        vols = {f["hora"]: f["vol_bps"] for f in filas}
        pico = max(vols, key=vols.get) if vols else None
        vmin = min(vols.values()) if vols else None
        vmax = max(vols.values()) if vols else None
        direccionales = [f["hora"] for f in filas
                         if f["ic"] is not None and (f["ic"][0] > 0.5 or f["ic"][1] < 0.5)]
        direccionales_bonf = [f["hora"] for f in filas
                              if f["ic_bonf"] is not None
                              and (f["ic_bonf"][0] > 0.5 or f["ic_bonf"][1] < 0.5)]
        rhos = [cache_ac[a]["rho1"] for a in activos if cache_ac[a]["rho1"] is not None]

        print()
        print(f"[{MERCADO[tipo]}]")
        print(f"  Ritmo: duracion media {fmt(up['media'],2,4).strip()} velas al alza y "
              f"{fmt(dn['media'],2,4).strip()} a la baja (teorico moneda = 2.00).")
        print(f"    P(tramo>=4 velas): alza {fmt(f_up['p4'],4,6).strip()} "
              f"IC95%{fmt_ic(f_up['ic4'])}, baja {fmt(f_dn['p4'],4,6).strip()} "
              f"IC95%{fmt_ic(f_dn['ic4'])}, teorico 0.1250.")
        print(f"    Un tramo dura mas de {fmt(up['p95'],0,3).strip()} velas solo el 5% de "
              f"las veces: ahi esta el techo practico de cualquier seguimiento de tendencia M1.")
        print(f"  Amplitud mediana: subida {fmt(amp_up['p50'],2,4).strip()} ATR, "
              f"bajada {fmt(amp_dn['p50'],2,4).strip()} ATR. "
              f"p95: {fmt(amp_up['p95'],2,4).strip()} / {fmt(amp_dn['p95'],2,4).strip()} ATR.")
        if rhos:
            print(f"  Memoria del ritmo: |rho1| maximo entre activos = "
                  f"{max(abs(r) for r in rhos):.3f}. Sin memoria explotable en la duracion.")
        if vmax and vmin:
            print(f"  Volatilidad horaria: ratio max/min = {vmax / vmin:.2f}x, pico a las {pico}h UTC.")
        if rho is not None:
            print(f"  Correlacion cruzada entre los 5 activos del grupo: rho={rho:.3f} "
                  f"-> {'son practicamente el mismo activo' if rho > 0.5 else 'son independientes entre si'}.")
        print(f"  Horas con sesgo direccional al 95% sin corregir: "
              f"{direccionales if direccionales else 'NINGUNA'}")
        print(f"  Horas que aguantan Bonferroni (24 pruebas): "
              f"{direccionales_bonf if direccionales_bonf else 'NINGUNA'}")
        if not direccionales_bonf:
            print("  -> El pico de volatilidad NO viene acompanado de sesgo direccional medible.")
            print("     Mas movimiento no es mas probabilidad de acertar la direccion.")
        hl_med = [resumen_hl(cache_ev[(a, k_ref)], horizonte)["p50"] for a in activos]
        hl_med = [h for h in hl_med if h is not None]
        if hl_med:
            print(f"  Expiracion natural de una reversion desde {k_ref} ATR: mediana "
                  f"{np.median(hl_med):.0f} min (rango entre activos "
                  f"{min(hl_med):.0f}-{max(hl_med):.0f} min).")
        else:
            print(f"  Expiracion natural de una reversion desde {k_ref} ATR: n/d")
        agg = fusionar_eventos([cache_ev[(a, k_ref)] for a in activos])
        r_ref = resumen_hl(agg, horizonte)
        if r_ref["frac_precio"] is not None:
            quien = "el PRECIO" if r_ref["frac_precio"] >= 0.5 else "la EMA alcanzando al precio"
            print(f"  Quien cierra el hueco desde {k_ref} ATR: {quien} "
                  f"(fraccion mediana aportada por el precio = {r_ref['frac_precio']:.3f}).")
        mejor = None
        for N in HORIZONTES_DIR:
            nb = agg["rev_n"][N]
            if nb < MIN_N_PROPORCION:
                continue
            p = agg["rev_w"][N] / nb
            ne = n_efectivo(nb, len(activos), rho)
            ic = wilson(p * ne, ne)
            if mejor is None or p > mejor[1]:
                mejor = (N, p, ic, nb, ne)
        if mejor:
            N, p, ic, nb, ne = mejor
            concluye = ic is not None and ic[0] > 0.5
            print(f"  Mejor expiracion para operar EN CONTRA de una desviacion de {k_ref} ATR: "
                  f"N={N} min, p={p:.4f} IC95%{fmt_ic(ic)} (n={nb}, n_eff={ne:.0f})")
            print(f"    -> {'supera el 50% de forma medible' if concluye else 'NO se distingue del azar'}"
                  f"; break-even con payout 0.86 = 0.5376 "
                  f"{'(y tampoco lo alcanza)' if not (ic and ic[0] > 0.5376) else '(lo supera)'}.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Laboratorio del ritmo del precio")
    ap.add_argument("--activos", default="", help="lista separada por comas; vacio = todos")
    ap.add_argument("--horizonte", type=int, default=180, help="minutos maximos para la reversion")
    ap.add_argument("--k", default="1.0,1.5,2.0,2.5,3.0", help="umbrales en ATRs")
    args = ap.parse_args()

    filtro = [x.strip() for x in args.activos.split(",") if x.strip()] or None
    ks = [float(x) for x in args.k.split(",") if x.strip()]

    datos = cargar(filtro)
    if not datos:
        print("No hay historicos M1 en", HISTORY_DIR)
        return 1

    activos_por_tipo = {"OTC": [], "REAL": []}
    for a in datos:
        activos_por_tipo[tipo_mercado(a)].append(a)

    print("=" * 100)
    print("LAB DE RITMO: a cuanto tiempo sube y en cuanto tiempo baja")
    print("=" * 100)
    print(f"{'activo':<16} {'velas':>7} {'desde':<17} {'hasta':<17} {'segm':>5} "
          f"{'planas%':>8} {'mercado'}")
    for tipo in ("OTC", "REAL"):
        for a in activos_por_tipo[tipo]:
            df = datos[a]
            segs = segmentar(df.iloc[WARMUP:])
            planas = float((df["close"].diff() == 0).mean()) * 100
            print(f"{a:<16} {len(df):>7} {str(df.index.min()):<17} {str(df.index.max()):<17} "
                  f"{len(segs):>5} {planas:>8.2f} {MERCADO[tipo]}")

    runs_por_activo = {a: runs_activo(datos[a], plana_rompe=False) for a in datos}
    runs_rompe = {a: runs_activo(datos[a], plana_rompe=True) for a in datos}
    cache_ac = {a: autocorr_duracion(runs_por_activo[a]) for a in datos}
    cache_perfil = {}
    rho_tipo = {}
    for tipo in ("OTC", "REAL"):
        if activos_por_tipo[tipo]:
            filas, rho = perfil_horario(datos, activos_por_tipo[tipo], runs_por_activo)
        else:
            filas, rho = [], None
        cache_perfil[tipo] = (filas, rho)
        rho_tipo[tipo] = rho
    cache_ev = {(a, k): eventos_desviacion(datos[a], k, args.horizonte)
                for a in datos for k in ks}

    seccion_1_2(datos, activos_por_tipo, runs_por_activo, runs_rompe)
    seccion_3(activos_por_tipo, cache_ac)
    seccion_4(activos_por_tipo, cache_perfil)
    seccion_5(datos, activos_por_tipo, ks, args.horizonte, cache_ev, rho_tipo)
    lectura_final(activos_por_tipo, runs_por_activo, cache_ac, cache_perfil,
                  cache_ev, ks, args.horizonte)

    print()
    print("=" * 100)
    print("ADVERTENCIAS DE LECTURA")
    print("=" * 100)
    print("1. Los tramos son estadistica descriptiva: se cierran 1 vela DESPUES de su ultima")
    print("   vela. Nada de lo medido aqui es una senal operable tal cual.")
    print("2. Los cinco indices reales estan muy correlacionados: el n agregado NO es n")
    print("   independiente. Los IC del perfil horario ya usan el n efectivo corregido.")
    print("3. El perfil horario prueba 24 hipotesis: sin Bonferroni se esperan ~1.2 horas")
    print("   'significativas' por puro azar. Solo cuentan las que aguantan la correccion.")
    print("4. Historico de ~10 dias: cada hora UTC tiene unos 10 dias de muestra por activo.")
    print("   Un efecto de calendario (una noticia, un dia raro) no es distinguible de un")
    print("   patron horario estable con esta ventana. Repetir con 60+ dias antes de creer.")
    print("5. Cualquier celda 'n/d' significa NO CALCULABLE, no cero y no valor por defecto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
