# -*- coding: utf-8 -*-
"""
¿Se puede ver donde termina el impulso? Sobre las senales de las reglas del bot:
cuanto llevaba recorrido el tramo al entrar y hasta donde llego despues (3 min).
Dev fija los cortes, val confirma. Tambien compara con las operaciones del usuario.
No compra nada. Uso: python scripts/medir_impulso.py
"""
from __future__ import annotations

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
from backtest_playbook import wilson                             # noqa: E402
from bot.vision.ejemplos_usuario import H, _load                 # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402
from medir_vencimiento import fin_binaria, senales               # noqa: E402

BE = 1 / 1.85
VENTANA = 12         # 3 min de velas de 15 s


def rasgos(df: pd.DataFrame) -> pd.DataFrame:
    cl, op, hi, lo = df["close"], df["open"], df["high"], df["low"]
    atr = (hi - lo).rolling(20).mean().shift(1).replace(0, np.nan)
    dirv = np.sign(cl - op)
    grupo = (dirv != dirv.shift()).cumsum()
    f = pd.DataFrame(index=df.index)
    f["atr"] = atr
    f["seg"] = dirv.groupby(grupo).cumcount() + 1
    f["rec_call"] = (cl - lo.rolling(20).min()) / atr          # tramo recorrido desde el extremo de 5 min
    f["rec_put"] = (hi.rolling(20).max() - cl) / atr
    f["vel_call"] = (cl - cl.shift(4)) / atr                   # velocidad del ultimo minuto
    f["vel_put"] = (cl.shift(4) - cl) / atr
    f["fav_call"] = (hi[::-1].rolling(VENTANA).max()[::-1].shift(-1) - cl) / atr
    f["fav_put"] = (cl - lo[::-1].rolling(VENTANA).min()[::-1].shift(-1)) / atr
    f["con_call"] = (cl - lo[::-1].rolling(VENTANA).min()[::-1].shift(-1)) / atr
    f["con_put"] = (hi[::-1].rolling(VENTANA).max()[::-1].shift(-1) - cl) / atr
    return f


def base() -> pd.DataFrame:
    out = []
    for fp in sorted(H.glob("*_15.parquet")):
        a = fp.stem.rsplit("_", 1)[0]
        df = _load(a)
        s = senales(df)
        if s.empty:
            continue
        f = rasgos(df).loc[s.index]
        c = s["lado"] > 0
        s["seg"] = f["seg"]
        for k, cc, pp in (("rec", "rec_call", "rec_put"), ("vel", "vel_call", "vel_put"),
                          ("alcance", "fav_call", "fav_put"), ("contra", "con_call", "con_put")):
            s[k] = f[cc].where(c, f[pp])
        sal = df["close"].reindex(fin_binaria(s.index + pd.Timedelta(seconds=16), 3) - pd.Timedelta(seconds=15))
        s["r"] = np.sign(s["lado"].to_numpy() * (sal.to_numpy() - s["p"].to_numpy()))
        out.append(s)
    t = pd.concat(out).sort_index().dropna(subset=["r", "rec", "alcance"])
    return t[t.r != 0]


def acierto(x: pd.DataFrame) -> str:
    g, n = int((x.r > 0).sum()), len(x)
    lo, hi = wilson(g, n) if n else (0, 0)
    return f"{100 * g / max(n, 1):.1f}% [{100 * lo:.1f}-{100 * hi:.1f}] n={n}"


def main() -> int:
    t = base()
    corte = t.index[len(t) // 2]
    dev, val = t[t.index < corte], t[t.index >= corte]
    print(f"Senales {len(t)}. Alcance a favor en 3 min, mediana {t.alcance.median():.2f} rangos; en contra {t.contra.median():.2f}")
    print("Ganadas: alcance", round(t[t.r > 0].alcance.median(), 2), "contra", round(t[t.r > 0].contra.median(), 2),
          "| perdidas: alcance", round(t[t.r < 0].alcance.median(), 2), "contra", round(t[t.r < 0].contra.median(), 2))
    for col, nombre in (("rec", "tramo ya recorrido (rangos)"), ("vel", "velocidad ultimo minuto"), ("seg", "velas seguidas a favor")):
        q = dev[col].quantile([.25, .5, .75]).to_numpy()
        print(f"\n{nombre}: cortes dev {np.round(q, 2).tolist()}")
        gd, gv = np.digitize(dev[col], q), np.digitize(val[col], q)
        for i in range(4):
            print(f"  grupo {i + 1}: dev {acierto(dev[gd == i])} | val {acierto(val[gv == i])}")
    trades = json.load(open(ROOT / "reports" / "graficos_rs_data.json", encoding="utf-8"))["trades"]
    filas, cache = [], {}
    for x in trades:
        a = MAP[x["asset"]]
        if a not in cache:
            cache[a] = (_load(a), None)
            cache[a] = (cache[a][0], rasgos(cache[a][0]))
        df, f = cache[a]
        i = df.index.searchsorted(pd.Timestamp(x["entry_ts"], unit="s") - pd.Timedelta(seconds=15), side="right") - 1
        r = f.iloc[i]
        s = "call" if x["dir"] == "CALL" else "put"
        filas.append({"res": x["res"], "rec": r[f"rec_{s}"], "vel": r[f"vel_{s}"], "alcance": r[f"fav_{s}"], "contra": r[f"con_{s}"]})
    u = pd.DataFrame(filas)
    print("\nTus operaciones, medianas por resultado:")
    print(u.groupby("res")[["rec", "vel", "alcance", "contra"]].median().round(2).to_string())
    print(f"Senales del bot, medianas: rec {t.rec.median():.2f} vel {t.vel.median():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
