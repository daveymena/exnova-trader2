# -*- coding: utf-8 -*-
"""
Estrategia "Rechazo y Soporte" (RS) v1.0 de Duvier, convertida en reglas
mecanicas (paquete estrategia_RS_paquete_agente, 29 oct 2026).

Grafico de entrada: velas de 15 s. Contexto: velas de 1 min construidas con
esas mismas velas. Todo es causal: un maximo/minimo de swing (K velas a cada
lado) solo existe cuando ya cerraron las K velas posteriores.

Setups (seccion 4 del paquete):
  A  PUT  rechazo de maximo: sin minimos crecientes en 1m, senal (vela de
          rechazo superior o maximo decreciente) en el tercio alto, entrada en
          la 1a vela bajista posterior sin superar el maximo, pos >= 0.50
  B  CALL minimos crecientes en 15 s (ultimos 5 min) sin maximos decrecientes;
          retroceso que no rompe el ultimo minimo + vela verde, o 1er
          retroceso tras vela de impulso; pos <= 0.66
  C  CALL soporte tocado 2+ veces en 5 min, pos <= 0.33, vela de rechazo
          inferior o 1a vela verde sobre el piso
Filtros F1-F3, F7 y F8 se aplican aqui; F4-F6 y la gestion de capital en el
simulador (scripts/lab_rs.py) y en el bot en vivo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

P = dict(W=20,            # 5 min en velas de 15 s (LOOKBACK_RANGO)
         ZONA_ALTA=0.66, ZONA_BAJA=0.33, PUT_POS_MIN=0.50,
         K=2, F_MECHA=1.5, F_IMPULSO=2.0, TOL=0.10,
         PCT_RANGO_MIN=0.25, CTX_MIN=15, SENAL_VIGENTE=4,
         SESION_BARS=5760)  # 24 h de velas de 15 s para percentiles del rango


def _swings(high: np.ndarray, low: np.ndarray, k: int):
    """Indices de swing high / low; el swing i se conoce en la vela i+k."""
    n = len(high)
    sh = np.ones(n, bool)
    sl = np.ones(n, bool)
    for j in range(1, k + 1):
        sh &= (high > np.r_[np.full(j, np.inf), high[:-j]]) & (high > np.r_[high[j:], np.full(j, np.inf)])
        sl &= (low < np.r_[np.full(j, -np.inf), low[:-j]]) & (low < np.r_[low[j:], np.full(j, -np.inf)])
    return np.flatnonzero(sh), np.flatnonzero(sl)


def _structure(vals: np.ndarray, idx: np.ndarray, n: int, k: int, window: int, rising: bool,
               close: np.ndarray, active: bool = True) -> np.ndarray:
    """En cada vela t: los 2 ultimos swings confirmados (i <= t-k, i > t-window)
    son crecientes (rising) / decrecientes y la estructura sigue viva
    (cierre por encima del ultimo minimo / por debajo del ultimo maximo)."""
    out = np.zeros(n, bool)
    if len(idx) < 2:
        return out
    # para cada t, posicion del ultimo swing confirmado
    conf = idx + k
    pos = np.searchsorted(conf, np.arange(n), side="right") - 1
    ok = pos >= 1
    last = np.where(ok, idx[np.clip(pos, 0, None)], 0)
    prev = np.where(ok, idx[np.clip(pos - 1, 0, None)], 0)
    t = np.arange(n)
    ok &= prev > t - window
    lv, pv = vals[last], vals[prev]
    ok &= (lv > pv) if rising else (lv < pv)
    if active:
        ok &= (close > lv) if rising else (close < lv)
    out[ok] = True
    return out


def to_1m(df15: pd.DataFrame) -> pd.DataFrame:
    g = df15.groupby(df15.index.floor("1min"))
    m = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                      "low": g["low"].min(), "close": g["close"].last(), "n": g.size()})
    return m[m["n"] == 4].drop(columns="n")


def rs_signals(df: pd.DataFrame, p: dict | None = None) -> pd.DataFrame:
    """Senal en cada vela cerrada de 15 s. Columnas: dir (call/put/''), setup,
    pos, rmax, rmin, exp_min, f7 (rango estrecho), mas banderas de contexto."""
    p = {**P, **(p or {})}
    W, K = p["W"], p["K"]
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    n = len(df)
    rmax = pd.Series(h).rolling(W, min_periods=W).max().to_numpy()
    rmin = pd.Series(l).rolling(W, min_periods=W).min().to_numpy()
    rng = rmax - rmin
    with np.errstate(divide="ignore", invalid="ignore"):
        pos = np.where(rng > 0, (c - rmin) / rng, np.nan)
        pos_h = np.where(rng > 0, (h - rmin) / rng, np.nan)

    body = np.abs(c - o)
    top, bot = np.maximum(o, c), np.minimum(o, c)
    up_wick, lo_wick = h - top, bot - l
    mid = (h + l) / 2
    rej_up = (up_wick >= p["F_MECHA"] * np.maximum(body, 1e-12)) & (c <= mid) & (h > l)
    rej_lo = (lo_wick >= p["F_MECHA"] * np.maximum(body, 1e-12)) & (c >= mid) & (h > l)
    avg_body = pd.Series(body).rolling(10).mean().shift(1).to_numpy()
    impulse = body >= p["F_IMPULSO"] * avg_body
    green, red = c > o, c < o

    # Estructura en 15 s (ultimos 5 min)
    shi, sli = _swings(h, l, K)
    hl15 = _structure(l, sli, n, K, W, True, c)
    lh15 = _structure(h, shi, n, K, W, False, c, active=False)
    # maximo decreciente recien confirmado en 15 s (evento, para el setup A)
    lh_event = np.zeros(n, bool)
    for a, b in zip(shi[:-1], shi[1:]):
        if h[b] < h[a] and b - a < W and b + K < n:
            lh_event[b + K] = True

    # Estructura en 1 min (ultimos 15 min), alineada a cada vela de 15 s
    m1 = to_1m(df)
    hl1 = np.zeros(n, bool)
    lh1 = np.zeros(n, bool)
    if len(m1) > 10:
        mh, ml, mc = (m1[x].to_numpy(float) for x in ("high", "low", "close"))
        a_sh, a_sl = _swings(mh, ml, K)
        m_hl = _structure(ml, a_sl, len(m1), K, p["CTX_MIN"], True, mc)
        m_lh = _structure(mh, a_sh, len(m1), K, p["CTX_MIN"], False, mc)
        # la vela de 1m que empieza en T cierra en T+60: visible desde la vela
        # de 15 s que cierra en T+60, es decir la que empieza en T+45
        avail = m1.index + pd.Timedelta(seconds=45)
        k = np.searchsorted(avail.values, df.index.values, side="right") - 1
        valid = k >= 0
        hl1[valid] = m_hl[k[valid]]
        lh1[valid] = m_lh[k[valid]]      # vigencia evaluada con el cierre de 1m

    # F7 / vencimiento: percentiles del rango de 5 min en las ultimas 24 h
    rs = pd.Series(rng)
    win = p["SESION_BARS"]
    q25 = rs.rolling(win, min_periods=win // 4).quantile(p["PCT_RANGO_MIN"]).shift(1).to_numpy()
    q50 = rs.rolling(win, min_periods=win // 4).median().shift(1).to_numpy()
    f7 = ~(rng >= q25)          # nan cuenta como rango estrecho (sin historia = no operar)
    exp_min = np.where(rng > q50, 3, 2)

    sig_dir = np.array([""] * n, dtype=object)
    setup = np.array([""] * n, dtype=object)
    S = p["SENAL_VIGENTE"]
    for t in range(max(W, 12), n):
        if not np.isfinite(pos[t]):
            continue
        puts, calls = [], []
        # ---- Setup A ----
        if not hl1[t] and red[t] and pos[t] >= p["PUT_POS_MIN"]:
            for j in range(t - 1, max(t - 1 - S, 0), -1):
                if not (pos_h[j] >= p["ZONA_ALTA"] and (rej_up[j] or lh_event[j])):
                    continue
                between = slice(j + 1, t)
                if red[between].any():       # no es la 1a vela bajista tras la senal
                    break
                if h[j + 1:t + 1].max(initial=-np.inf) > h[j]:
                    break                    # supero el maximo: senal invalida
                puts.append("A")
                break
        # ---- Setup B ----
        if hl15[t] and not lh15[t] and not lh1[t] and pos[t] <= p["ZONA_ALTA"] and not impulse[t]:
            last_low_i = sli[np.searchsorted(sli + K, t, side="right") - 1]
            pullback = green[t] and red[t - 1] and l[t - 1] > l[last_low_i] and l[t] > l[last_low_i]
            after_imp = red[t] and impulse[t - 1] and green[t - 1] and l[t] > l[last_low_i]
            if pullback or after_imp:
                calls.append("B")
        # ---- Setup C ----
        if pos[t] <= p["ZONA_BAJA"]:
            floor = l[t - W:t].min()
            r = h[t - W:t].max() - floor
            if r > 0 and c[t] >= floor:
                touch = l[t - W:t] <= floor + p["TOL"] * r
                episodes = int(touch[0]) + int(np.sum(touch[1:] & ~touch[:-1]))
                trig = rej_lo[t] or (green[t] and not green[t - 1] and c[t] > floor)
                if episodes >= 2 and trig:
                    calls.append("C")
        # ---- Filtros ----
        if puts and (pos[t] <= p["ZONA_BAJA"] or hl1[t]):            # F1, F3
            puts = []
        if calls and ((pos[t] >= p["ZONA_ALTA"] and (impulse[t] or impulse[t - 1])) or lh1[t]):  # F2, F3
            calls = []
        if f7[t]:                                                     # F7
            puts, calls = [], []
        if puts and calls:                                            # F8 ambigua
            continue
        if puts:
            sig_dir[t], setup[t] = "put", puts[0]
        elif calls:
            sig_dir[t], setup[t] = "call", calls[0]

    return pd.DataFrame({"dir": sig_dir, "setup": setup, "pos": pos, "rmax": rmax, "rmin": rmin,
                         "exp_min": exp_min, "f7": f7, "hl1": hl1, "lh1": lh1}, index=df.index)
