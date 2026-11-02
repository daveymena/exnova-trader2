# -*- coding: utf-8 -*-
"""
Datos para la pagina visual (reports/graficos_rs.template.html):
  - las operaciones reales del usuario (29 oct y 1 nov) sobre velas de 15 s
    de IQ con EMA 20/50/200, entrada y vencimiento;
  - momentos del historial con el mismo dibujo del setup B/A (EMAs ordenadas,
    retroceso que toca la EMA20, vela gatillo), elegidos al azar sin mirar el
    resultado, para comparar a ojo.
Uso: python scripts/graficos_operaciones.py csv29 csv01
"""
from __future__ import annotations
import json, random, sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parent.parent
H = ROOT / "bot" / "data" / "history"
MAP = {"US 30": "US30_N", "GBP/USD": "GBPUSD-op", "US 500": "USSPX500_N", "OpenAI (OTC)": "OpenAI-OTC",
       "PEN/USD (OTC)": "PENUSD-OTC", "AUD/CAD (OTC)": "AUDCAD-OTC", "1000Sats (OTC)": "SATSUSD-OTC",
       "Pepe (OTC)": "PEPEUSD-OTC", "Snap Inc. (OTC)": "SNAP-OTC", "EUR/USD (OTC)": "EURUSD-OTC",
       "USD/ZAR (OTC)": "USDZAR-OTC", "Jupiter (OTC)": "JUPUSD-OTC"}
PRE, POST = 100, 8          # velas de 15 s antes de la entrada / despues del vencimiento


def load(a):
    df = pd.read_parquet(H / f"{a}_15.parquet")[["open", "high", "low", "close"]].astype(float)
    df = df[~df.index.duplicated()].sort_index()
    for n in (20, 50, 200):
        df[f"e{n}"] = df["close"].ewm(span=n, adjust=False).mean()
    return df


def window(df, entry, end):
    i = df.index.searchsorted(entry) - 1          # vela que cierra justo antes de la entrada
    j = df.index.searchsorted(end)
    w = df.iloc[max(0, i - PRE): j + POST]
    dig = max(0, 6 - int(np.floor(np.log10(abs(w["close"].iloc[-1]) or 1))))
    r = lambda x: round(float(x), dig)
    return {"t0": int(w.index[0].timestamp()),
            "c": [[r(x.open), r(x.high), r(x.low), r(x.close)] for x in w.itertuples()],
            "e": [[r(x.e20), r(x.e50), r(x.e200)] for x in w.itertuples()]}


def trades(csv29, csv01):
    out, cache = [], {}
    for path, kind in ((csv29, 29), (csv01, 1)):
        for _, r in pd.read_csv(path).iterrows():
            a = MAP.get(r["activo"])
            if a is None:
                continue
            fecha = r["fecha"] if kind == 29 else r["fecha_cierre"]
            hc, hv = str(r["hora_compra"])[:8], str(r["hora_vencimiento"])[:8]
            ent = pd.Timestamp(f"{fecha} {hc}")
            if kind == 1 and hc > hv:
                ent -= pd.Timedelta(days=1)
            ent += pd.Timedelta(hours=5)
            end = ent + pd.Timedelta(minutes=float(r["duracion_min"]))
            if a not in cache:
                cache[a] = load(a)
            df = cache[a]
            if not (df.index[0] + pd.Timedelta(hours=1) < ent < df.index[-1]):
                continue
            setup = r["familia_setup"] if kind == 29 else r["setup_pre_entrada"]
            out.append({"id": r["id_opcion"], "asset": r["activo"], "dir": r["direccion"].upper(),
                        "res": r["resultado"], "pg": float(r["pg_usd"]), "setup": str(setup),
                        "hora": f"{(ent - pd.Timedelta(hours=5)):%d %b %H:%M:%S}", "exp_min": float(r["duracion_min"]),
                        "entry_ts": int(ent.timestamp()), "end_ts": int(end.timestamp()),
                        "p_in": float(r["precio_apertura"]), "p_out": float(r["precio_cierre"]),
                        "nota": str(r["contexto_grafico"]), **window(df, ent, end)})
    return out


def parecidos(n=48, seed=7):
    """Mismo dibujo del setup B (CALL) / A (PUT) en 15 s: EMAs 20>50>200 y la 20
    subiendo, retroceso de 1-6 velas que toca la EMA20 (<= 0.35 ATR) sin cerrar
    bajo la EMA50, vela gatillo verde que cierra sobre el maximo anterior.
    Vencimiento 3 min (12 velas), entrada al cierre del gatillo."""
    cands = []
    for f in sorted(H.glob("*_15.parquet")):
        a = f.stem.rsplit("_", 1)[0]
        df = load(a)
        o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        e20, e50, e200 = (df[k].to_numpy() for k in ("e20", "e50", "e200"))
        pc = np.r_[c[0], c[:-1]]
        atr = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy()
        ts = df.index.as_unit("s").asi8
        for s in (1, -1):
            trend = (s * (e20 - e50) > 0) & (s * (e50 - e200) > 0) & (s * (e20 - np.r_[np.full(5, np.nan), e20[:-5]]) > 0.15 * atr)
            ext = pd.Series(l if s == 1 else -h).rolling(6).min().shift(1).to_numpy() * (1 if s == 1 else -1)
            touch = (s * (ext - e20) <= 0.35 * atr)
            held = pd.Series(s * (c - e50) > 0).rolling(6).min().to_numpy() == 1
            trig = (s * (c - o) > 0) & (s * (c - (np.r_[np.nan, h[:-1]] if s == 1 else np.r_[np.nan, l[:-1]])) > 0)
            sig = np.flatnonzero(trend & touch & held & trig)
            last = -99
            for i in sig:
                if i < 300 or i - last < 20 or i + 12 >= len(c) or ts[i + 12] - ts[i] != 180:
                    continue
                last = i
                cands.append((a, s, i, df))
    random.Random(seed).shuffle(cands)
    out, wins = [], 0
    allres = []
    for a, s, i, df in cands:
        c = df["close"].to_numpy()
        allres.append(1 if s * (c[i + 12] - c[i]) > 0 else 0 if c[i + 12] == c[i] else -1)
    for a, s, i, df in cands[:n]:
        ent = df.index[i] + pd.Timedelta(seconds=15)
        end = ent + pd.Timedelta(minutes=3)
        c = df["close"].to_numpy()
        res = "GANADA" if s * (c[i + 12] - c[i]) > 0 else "EMPATE" if c[i + 12] == c[i] else "PERDIDA"
        out.append({"id": f"P{len(out) + 1:02d}", "asset": a, "dir": "CALL" if s == 1 else "PUT", "res": res,
                    "hora": f"{(ent - pd.Timedelta(hours=5)):%d %b %H:%M:%S}", "exp_min": 3,
                    "entry_ts": int(ent.timestamp()), "end_ts": int(end.timestamp()),
                    "p_in": float(c[i]), "p_out": float(c[i + 12]), **window(df, ent, end)})
    r = np.array(allres)
    tot = {"n": int((r != 0).sum()), "g": int((r == 1).sum())}
    return out, tot


if __name__ == "__main__":
    t = trades(sys.argv[1], sys.argv[2])
    p, tot = parecidos()
    data = {"trades": t, "parecidos": p, "total_parecidos": tot}
    js = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    (ROOT / "reports" / "graficos_rs_data.json").write_text(js, encoding="utf-8")
    print(len(t), "operaciones,", len(p), "parecidos;", tot, f"{len(js)/1e6:.2f} MB")
    from collections import Counter
    print(Counter(x["res"] for x in t), Counter(x["res"] for x in p))
