# -*- coding: utf-8 -*-
"""
Mide cuanto debe durar la operacion. No compra nada.

  1. Compras del bot en IQ: recorrido del precio cada 30 s tras la entrada.
  2. Operaciones del usuario: acierto si hubiera cerrado a 1-5 min.
  3. Senales de las reglas del bot en el historial de 15 s de IQ, con el vencimiento
     real de las binarias (siempre en minuto exacto, iqoptionapi/expiration.py):
     acierto por vencimiento, mitad dev / mitad val, y por volatilidad y espacio.

Uso: python scripts/medir_vencimiento.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
import azura_live as al                                          # noqa: E402
from backtest_playbook import wilson                             # noqa: E402
from bot.backtest import regla_guia as rg                        # noqa: E402
from bot.vision.ejemplos_usuario import H, _load                 # noqa: E402
from gemma_live import AVANCE_MAX, ESPACIO_MIN_ATR, GUIA, POS30_MAX, POS_MAX  # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402
from iq_probe import connect                                     # noqa: E402

PASOS = range(30, 301, 30)
EXPS = (1, 2, 3, 4, 5)


def fin_binaria(ent: pd.DatetimeIndex, exp: int) -> pd.DatetimeIndex:
    """Vencimiento real: primer minuto con mas de 30 s por delante, mas exp-1 minutos."""
    m = ent.floor("min")
    falta = (m + pd.Timedelta(minutes=1) - ent).total_seconds()
    primero = m + pd.to_timedelta(np.where(falta > 30, 60, 120), unit="s")
    return primero + pd.Timedelta(minutes=exp - 1)


def senales(df: pd.DataFrame, vela: str = "confirma", comienzo: bool = False,
            primera: bool = False, tendencia: bool = False) -> pd.DataFrame:
    """Las reglas de gemma_live.py en forma vectorizada (entrada al cierre de la vela).
    vela: "confirma" exige vela a favor, "contra" entra tras una vela del retroceso, "" no mira la vela."""
    cl, op, hi, lo = df["close"], df["open"], df["high"], df["low"]
    atr = (hi - lo).rolling(20).mean().shift(1).replace(0, np.nan)
    e20 = cl.ewm(span=20, adjust=False).mean()
    lado = np.sign(cl - e20)
    ult = np.sign(cl - op)
    dist = (cl - e20).abs() / atr
    d1m = rg.features_series(df)["dist_1m"]
    hi20, lo20 = hi.rolling(20).max(), lo.rolling(20).min()
    pos = ((cl - lo20) / (hi20 - lo20)).where(lado > 0, (hi20 - cl) / (hi20 - lo20))
    esp = ((hi.rolling(120).max().shift(1) - cl) / atr).where(lado > 0, (cl - lo.rolling(120).min().shift(1)) / atr)
    toco_c = (lo <= e20 + 0.35 * atr).rolling(7).max() > 0
    toco_p = (hi >= e20 - 0.35 * atr).rolling(7).max() > 0
    toco = toco_c.where(lado > 0, toco_p)
    ok = (lado != 0) & (dist <= GUIA.max_dist_atr) & (d1m <= GUIA.max_dist_1m) \
        & ((cl - op).abs() / atr <= GUIA.k_impulso) & toco & (esp >= ESPACIO_MIN_ATR) & (pos <= POS_MAX)
    if vela == "confirma":
        ok &= ult == lado
    elif vela == "contra":
        ok &= ult == -lado
    if tendencia:
        e50m = cl.resample("1min").last().dropna().ewm(span=50, adjust=False).mean().shift(1)
        ok &= lado * (cl - e50m.reindex(df.index, method="ffill")) > 0
    if primera:
        ok &= ult.shift(1) != lado
    if comienzo:
        res, sop = hi.rolling(120).max().shift(1), lo.rolling(120).min().shift(1)
        b_c, b_p = lo.rolling(40).min(), hi.rolling(40).max()
        ok &= ((cl - sop) / (res - sop)).where(lado > 0, (res - cl) / (res - sop)) <= POS30_MAX
        ok &= ((cl - b_c) / (res - b_c)).where(lado > 0, (b_p - cl) / (b_p - sop)) <= AVANCE_MAX
    s = pd.DataFrame({"lado": lado, "esp": esp, "vol": atr / atr.rolling(400).median(), "p": cl})[ok]
    s = s[s.vol.notna()]
    keep, last = [], None
    for t in s.index:                       # una a la vez: 4 min entre entradas del mismo activo
        if last is None or (t - last).total_seconds() >= 240:
            keep.append(t)
            last = t
    return s.loc[keep]


def historial() -> pd.DataFrame:
    out = []
    for fp in sorted(H.glob("*_15.parquet")):
        a = fp.stem.rsplit("_", 1)[0]
        df = _load(a)
        s = senales(df)
        if s.empty:
            continue
        ent = s.index + pd.Timedelta(seconds=16)
        for e in EXPS:
            sal = df["close"].reindex(fin_binaria(ent, e) - pd.Timedelta(seconds=15)).to_numpy()
            mov = s["lado"].to_numpy() * (sal - s["p"].to_numpy())
            s[f"m{e}"] = np.sign(mov)
        s["activo"] = a
        out.append(s)
    return pd.concat(out).sort_index()


def tabla(t: pd.DataFrame, nombre: str) -> None:
    filas = []
    for e in EXPS:
        x = t[f"m{e}"].dropna()
        x = x[x != 0]
        g, n = int((x > 0).sum()), len(x)
        lo, hi = wilson(g, n) if n else (0, 0)
        filas.append(f"{e}m {100 * g / max(n, 1):.1f}% [{100 * lo:.1f}-{100 * hi:.1f}] n={n}")
    print(f"{nombre}: " + " | ".join(filas))


def bot() -> None:
    api = connect()
    for nombre in ("gemma_lugar_live.csv",):
        with open(ROOT / "bot" / "data" / nombre, encoding="utf-8") as f:
            ops = [o for o in csv.DictReader(f) if o["status"] in ("win", "loose")]
        for o in ops:
            t0 = pd.Timestamp(o["signal_candle_utc"], tz="UTC").timestamp() + 16
            d = 1 if o["direction"] == "call" else -1
            v = al.closed_candles(api, o["asset"], 15, t0 + 330, 40)
            ent = float(o["entry"])
            pts = []
            atr = float((v["high"] - v["low"]).mean())
            for s in PASOS:
                u = v[v.index <= pd.Timestamp(t0 + s, unit="s")]
                pts.append(f"{s}s {d * (float(u['close'].iloc[-1]) - ent) / atr:+.1f}")
            print(o["signal_candle_utc"], o["asset"], o["direction"], o["status"], "| en rangos de vela:", " ".join(pts))


def usuario() -> None:
    trades = json.load(open(ROOT / "reports" / "graficos_rs_data.json", encoding="utf-8"))["trades"]
    filas, cache = [], {}
    for t in trades:
        a = MAP[t["asset"]]
        cache.setdefault(a, _load(a))
        df, d = cache[a], 1 if t["dir"] == "CALL" else -1
        ini = pd.Timestamp(t["entry_ts"], unit="s")
        fila = {"res": t["res"]}
        for s in PASOS:
            u = df[df.index + pd.Timedelta(seconds=15) <= ini + pd.Timedelta(seconds=s)]
            cerca = len(u) and (ini + pd.Timedelta(seconds=s) - u.index[-1]).total_seconds() <= 45
            fila[s] = np.sign(d * (u["close"].iloc[-1] - t["p_in"])) if cerca else np.nan
        filas.append(fila)
    t = pd.DataFrame(filas)
    print("Tus operaciones, % a favor si cierra en:",
          " ".join(f"{s}s {100 * (t[s].dropna() > 0).mean():.0f}%(n{t[s].notna().sum()})" for s in PASOS))
    p = t[t.res == "PERDIDA"]
    print(f"De tus {len(p)} perdidas, iban ganando en algun momento antes de vencer:",
          int((p[list(PASOS)[:6]] > 0).any(axis=1).sum()))


def main() -> int:
    bot()
    usuario()
    t = historial()
    corte = t.index[len(t) // 2]
    print(f"\nSenales de las reglas: {len(t)}, {t.activo.nunique()} activos, {t.index[0]} a {t.index[-1]}")
    tabla(t, "Todas")
    tabla(t[t.index < corte], "Dev")
    tabla(t[t.index >= corte], "Val")
    tabla(t[t.lado > 0], "CALL")
    tabla(t[t.lado < 0], "PUT")
    for col, cortes, nombres in (("vol", (0.8, 1.2), ("vol baja", "vol media", "vol alta")),
                                 ("esp", (5, 12), ("espacio 2-5", "espacio 5-12", "espacio >12"))):
        g = np.digitize(t[col], cortes)
        for i, n in enumerate(nombres):
            tabla(t[g == i], n)
    a1, a3 = t["m1"] > 0, t["m3"] < 0
    print(f"A 1 min iban ganando y a 3 min perdian: {100 * (a1 & a3).sum() / max(a1.sum(), 1):.1f}% de las que iban ganando")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    import os
    os._exit(code)
