# -*- coding: utf-8 -*-
"""
¿Cuando esta "loco" el mercado? Volatilidad reciente frente a lo normal del activo y
horario, sobre las senales de las reglas con velas de 15 s de IQ. No compra nada.
Uso: python scripts/medir_mercado.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
from backtest_playbook import wilson                             # noqa: E402
from bot.vision.ejemplos_usuario import H, _load                 # noqa: E402
from medir_vencimiento import fin_binaria, senales               # noqa: E402


def acierto(x: pd.Series) -> str:
    x = x[x != 0].dropna()
    g, n = int((x > 0).sum()), len(x)
    lo, hi = wilson(g, n) if n else (0, 0)
    return f"{100 * g / max(n, 1):.1f}% [{100 * lo:.1f}-{100 * hi:.1f}] n={n}"


def main() -> int:
    out, todos = [], []
    for fp in sorted(H.glob("*_15.parquet")):
        a = fp.stem.rsplit("_", 1)[0]
        df = _load(a)
        r = df["high"] - df["low"]
        base = r.rolling(760).mean().shift(40)
        vr, salto = r.rolling(20).mean() / base, r.rolling(20).max() / base
        todos.append(pd.DataFrame({"vr": vr, "salto": salto}).dropna().iloc[::20])
        s = senales(df, "confirma", comienzo=True, tendencia=True)
        if s.empty:
            continue
        sal = df["close"].reindex(fin_binaria(s.index + pd.Timedelta(seconds=16), 3) - pd.Timedelta(seconds=15)).to_numpy()
        s["r"] = np.sign(s["lado"].to_numpy() * (sal - s["p"].to_numpy()))
        s["vr"], s["salto"], s["otc"] = vr.reindex(s.index), salto.reindex(s.index), "OTC" in a
        out.append(s)
    q = pd.concat(todos)
    print("vr p50/p90/p95/p99:", q.vr.quantile([.5, .9, .95, .99]).round(2).tolist(),
          "| salto p50/p90/p95/p99:", q.salto.quantile([.5, .9, .95, .99]).round(2).tolist())
    t = pd.concat(out).dropna(subset=["vr", "salto"]).sort_index()
    print("Senales con reglas actuales:", acierto(t.r))
    for vmax, smax in ((1.3, 4), (1.5, 5), (1.8, 6), (2.5, 8)):
        m = (t.vr > vmax) | (t.salto > smax)
        print(f"  loco si vr>{vmax} o salto>{smax}: se bloquea {100 * m.mean():.0f}% | bloqueadas {acierto(t.r[m])} | resto {acierto(t.r[~m])}")
    h = (t.index - pd.Timedelta(hours=5)).hour
    for nombre, m in (("Noche 20-24 Colombia", (h >= 20)), ("Madrugada 0-6", (h < 6)), ("Manana 6-12", (h >= 6) & (h < 12)),
                      ("Tarde 12-20", (h >= 12) & (h < 20))):
        print(f"  {nombre}: {acierto(t.r[m])} | real {acierto(t.r[m & ~t.otc])} | OTC {acierto(t.r[m & t.otc])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
