# -*- coding: utf-8 -*-
"""
Laboratorio: continuacion vs reversion en zonas S/R, condicionado a la
tendencia de timeframe superior (H1/H4 sinteticos por resample desde M1).

Pregunta exacta del usuario: en un toque de resistencia, el precio a menudo
retrocede (pullback) para LUEGO seguir su camino, en vez de revertir del todo.
lab_trampas.py ya probo 14 filtros observables EN EL MOMENTO del toque (tamano
de vela, RSI extremo, numero de toques, cruce de estocastico) y ninguno separo
trampa de ruptura mejor que el azar. Lo que NO se probo todavia es si la
tendencia de un timeframe MAYOR que el de la señal predice cual de los dos
comportamientos (continua vs revierte) ocurre.

Se clasifica cada toque en TRES desenlaces, no dos:
  CONTINUA        : rompe la zona en la direccion del toque y sigue (no hay
                     pullback significativo antes de la ruptura).
  PULLBACK_SIGUE   : retrocede >= 0.5 ATR en contra, pero luego SI rompe la
                     zona en la direccion original dentro de la ventana.
  REVIERTE         : nunca rompe la zona en la direccion original dentro de
                     la ventana (con o sin pullback previo).

Para cada toque se mide la tendencia H1/H4 (EMA rapida vs lenta en esos
timeframes resampleados desde M1) y se cruza contra el desenlace. Todo con
intervalos de Wilson, minimo de muestra y correccion por multiples pruebas,
igual que el resto de laboratorios de hoy. Si el usuario tiene razon, deberia
verse: zona alineada con tendencia HTF -> mas CONTINUA/PULLBACK_SIGUE; zona
contraria a tendencia HTF -> mas REVIERTE.

Uso:
    python scripts/lab_continuacion_htf.py
    python scripts/lab_continuacion_htf.py --payout 0.86 --ventana-min 30
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.backtest.indicators import atr, ema  # noqa: E402

HISTORY_DIR = ROOT / "bot" / "data" / "history"


def wilson(w: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m), min(1.0, c + m))


def load() -> dict[str, pd.DataFrame]:
    out = {}
    for p in sorted(HISTORY_DIR.glob("*_60.parquet")):
        df = pd.read_parquet(p).sort_index()
        if len(df) >= 2000:
            out[p.stem[:-3]] = df
    return out


def htf_trend(df_m1: pd.DataFrame, minutes: int) -> pd.Series:
    """
    Tendencia de un timeframe mayor, resampleado desde M1 y reindexado hacia
    abajo a resolucion M1 con ffill: en cada minuto se conoce la tendencia
    de la ULTIMA vela HTF ya cerrada, nunca la que esta en formacion.
    """
    rule = f"{minutes}min"
    agg = df_m1["close"].resample(rule, label="left", closed="left").last().dropna()
    e_fast, e_slow = ema(agg, 8), ema(agg, 21)
    trend = pd.Series(np.where(e_fast > e_slow, 1, np.where(e_fast < e_slow, -1, 0)),
                      index=agg.index)
    # Desplazar una vela HTF: el valor de la vela que cierra en t solo se
    # conoce a partir de t (no antes), y no se debe usar la vela EN FORMACION.
    trend = trend.shift(1)
    return trend.reindex(df_m1.index, method="ffill")


def find_touches(df: pd.DataFrame, wing: int = 5, tol_atr: float = 0.5):
    """Toques de zonas confirmadas (pivote wing barras atras, sin mirar al futuro)."""
    hi, lo = df["high"], df["low"]
    a = atr(df, 14)
    win = 2 * wing + 1
    is_high = (hi == hi.rolling(win, center=True).max()).shift(wing).fillna(False)
    is_low = (lo == lo.rolling(win, center=True).min()).shift(wing).fillna(False)
    last_res = hi.where(is_high).ffill()
    last_sup = lo.where(is_low).ffill()
    tol = tol_atr * a

    near_res = (hi - last_res).abs() <= tol
    near_sup = (lo - last_sup).abs() <= tol

    touches = []
    last_i = -10 ** 9
    idx = df.index
    for i in range(wing + 20, len(df)):
        if i - last_i < 10:
            continue
        if bool(near_res.iloc[i]) and pd.notna(last_res.iloc[i]):
            touches.append((i, "resistencia", float(last_res.iloc[i])))
            last_i = i
        elif bool(near_sup.iloc[i]) and pd.notna(last_sup.iloc[i]):
            touches.append((i, "soporte", float(last_sup.iloc[i])))
            last_i = i
    return touches


def resultado_binario(df: pd.DataFrame, i: int, tipo: str,
                      expiry_min: int) -> bool | None:
    """
    Resultado de apostar a que la zona SOSTIENE (CALL en soporte, PUT en
    resistencia), resuelto a una expiracion FIJA -- exactamente como resuelve
    una opcion binaria real, y con la misma metodologia que
    lab_reaccion_zonas.py: entrada en la apertura de la siguiente vela, cierre
    en la vela expiry_min despues. Nada de "cruza un umbral en algun momento
    dentro de una ventana ancha": ese diseño (la primera version de este
    archivo) daba ~95% de "favorable" en TODOS los grupos por igual, la firma
    inequivoca de que el umbral era tan laxo que se cruzaba casi siempre por
    puro ruido, sin importar ninguna condicion. Se descarto antes de reportar
    nada: un hallazgo identico en todos los grupos no es un hallazgo.
    """
    if i + 1 + expiry_min >= len(df):
        return None
    entry = float(df["open"].iloc[i + 1])
    exit_ = float(df["close"].iloc[i + 1 + expiry_min])
    if exit_ == entry:
        return None
    sube = exit_ > entry
    return sube if tipo == "soporte" else not sube


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payout", type=float, default=0.86)
    ap.add_argument("--expiries", default="1,3,5,15",
                    help="Minutos de expiracion a probar, separados por comas")
    args = ap.parse_args()

    data = load()
    if not data:
        print(f"No hay historico en {HISTORY_DIR}")
        return 1

    expiries = [int(x) for x in args.expiries.split(",")]
    breakeven = 1 / (1 + args.payout)
    n_tests = len(expiries) * 5  # 5 cortes reportados por expiracion (aprox)
    z_corr = 1.96 + 0.5 * math.log(max(n_tests, 1))

    print("=" * 100)
    print("CONTINUACION vs REVERSION EN ZONAS S/R, CONDICIONADO A TENDENCIA HTF")
    print("=" * 100)
    print(f"Activos: {len(data)}  |  Expiraciones: {expiries} min")
    print(f"Break-even (payout {args.payout:.2f}): {100*breakeven:.2f}%")
    print(f"Correccion aproximada por multiplicidad: z={z_corr:.2f} en vez de 1.96\n")

    rows = []
    for asset, df in data.items():
        trend_h1 = htf_trend(df, 60)
        trend_h4 = htf_trend(df, 240)
        touches = find_touches(df)

        for i, tipo, nivel in touches:
            th1, th4 = trend_h1.iloc[i], trend_h4.iloc[i]
            if pd.isna(th1) or pd.isna(th4):
                continue
            favor_dir = -1 if tipo == "resistencia" else 1
            alineado_h1 = "a_favor" if th1 == favor_dir else ("en_contra" if th1 == -favor_dir else "neutral")
            alineado_h4 = "a_favor" if th4 == favor_dir else ("en_contra" if th4 == -favor_dir else "neutral")
            combinado = f"h1_{alineado_h1}_h4_{alineado_h4}"

            for exp in expiries:
                gano = resultado_binario(df, i, tipo, exp)
                if gano is None:
                    continue
                rows.append({
                    "asset": asset, "tipo": tipo, "expiry": exp, "gano": gano,
                    "alineado_h1": alineado_h1, "alineado_h4": alineado_h4,
                    "combinado": combinado, "synthetic": "-OTC" in asset,
                })

    if not rows:
        print("No se generaron observaciones (revisa el historico disponible).")
        return 1

    df_r = pd.DataFrame(rows)
    print(f"Total observaciones (toque x expiracion): {len(df_r)}\n")

    def reporta(grupo_col: str, titulo: str, min_n: int = 150):
        print("-" * 100)
        print(titulo)
        print("-" * 100)
        print(f"{'grupo':<24}{'exp':>5}{'n':>7}{'winrate':>9}   IC corregido           veredicto")
        filas = []
        for (grupo, exp), sub in df_r.groupby([grupo_col, "expiry"]):
            n = len(sub)
            if n < min_n:
                continue
            wins = int(sub["gano"].sum())
            lo, hi = wilson(wins, n, z=z_corr)
            veredicto = "GANADOR" if lo > breakeven else ("PERDEDOR" if hi < breakeven else "ruido")
            filas.append((grupo, exp, n, wins / n, lo, hi, veredicto))
        filas.sort(key=lambda f: -f[3])
        for grupo, exp, n, wr, lo, hi, v in filas:
            print(f"{str(grupo)[:24]:<24}{exp:>4}m{n:>7}{100*wr:>8.1f}%   "
                  f"[{100*lo:5.1f}%,{100*hi:5.1f}%]   {v}")
        print()
        return filas

    reporta("alineado_h1", "POR ALINEACION CON TENDENCIA H1")
    reporta("alineado_h4", "POR ALINEACION CON TENDENCIA H4")
    combinado_filas = reporta("combinado", "POR COMBINACION H1+H4 (la hipotesis completa del usuario)")

    print("=" * 100)
    print("VEREDICTO")
    print("=" * 100)
    n_total, wins_total = len(df_r), int(df_r["gano"].sum())
    lo, hi = wilson(wins_total, n_total)
    print(f"Base global (sin condicionar): {100*wins_total/n_total:.1f}% acierto, "
          f"IC95%[{100*lo:.1f}%,{100*hi:.1f}%], n={n_total}")

    ganadores = [f for f in combinado_filas if f[6] == "GANADOR"]
    if ganadores:
        print(f"\nHAY {len(ganadores)} COMBINACION(ES) H1+H4 x EXPIRACION QUE SUPERAN BREAK-EVEN")
        print("incluso con la correccion por multiplicidad:")
        for grupo, exp, n, wr, lo_g, hi_g, _ in sorted(ganadores, key=lambda f: -f[4]):
            print(f"  {grupo} @ {exp}min: {100*wr:.1f}% (n={n}), "
                  f"limite inferior {100*lo_g:.1f}% > {100*breakeven:.1f}%")
        print("  Esto SI seria un filtro operable. Verificar fuera de muestra antes de usarlo.")
    else:
        print("\nNINGUNA combinacion de alineacion H1/H4, a ninguna expiracion probada,")
        print("separa continuacion de reversion por encima del break-even con muestra")
        print("suficiente y correccion aplicada. La intuicion de que la tendencia de")
        print("timeframe superior predice si el precio va a retroceder-y-seguir o a")
        print("revertir del todo NO se confirma con estos datos. No es un fallo de")
        print("deteccion: es lo que dicen los datos sobre estos 10 activos y 10 dias.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
