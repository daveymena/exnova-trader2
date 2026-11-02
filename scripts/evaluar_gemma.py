# -*- coding: utf-8 -*-
"""
Examen a ciegas del lector de graficos (bot/vision/lector_gemma.py) antes de
dejarlo operar: momentos al azar del historial de 15 s, el modelo solo ve el
grafico hasta ese instante y decide CALL/PUT/NO + vencimiento 2/3/5 min; luego
se mira que paso. Cada respuesta queda en reports/evaluar_gemma.csv (se puede
cortar y seguir).

Uso:
  python scripts/evaluar_gemma.py --modelos          # comprobar key y modelos
  python scripts/evaluar_gemma.py --n 300            # examen
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                       # noqa: E402
load_dotenv(ROOT / ".env")
from backtest_playbook import wilson                 # noqa: E402
from bot.vision.lector_gemma import leer, modelos   # noqa: E402

OUT = ROOT / "reports" / "evaluar_gemma.csv"
BE = 1 / 1.85


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--modelos", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    if a.modelos:
        print(modelos())
        return
    data = {}
    for f in sorted((ROOT / "bot" / "data" / "history").glob("*_15.parquet")):
        df = pd.read_parquet(f)[["open", "high", "low", "close"]].astype(float)
        data[f.stem.rsplit("_", 1)[0]] = df[~df.index.duplicated()].sort_index()
    rnd = random.Random(a.seed)
    puntos = []
    while len(puntos) < a.n:
        k = rnd.choice(sorted(data))
        df = data[k]
        i = rnd.randrange(400, len(df) - 25)
        seguidas = (df.index[i + 20] - df.index[i]).total_seconds() == 300
        if seguidas and (df.index[i] - df.index[i - 399]).total_seconds() < 400 * 15 * 1.2:
            puntos.append((k, i))
    hechos = set()
    out = Path(a.out)
    if out.exists():
        with open(out, encoding="utf-8") as fh:
            hechos = {(r["activo"], int(r["i"])) for r in csv.DictReader(fh)}
    nuevo = not out.exists()
    with open(out, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if nuevo:
            w.writerow(["activo", "i", "hora_utc", "decision", "vencimiento_min", "confianza", "razon", "resultado"])
        for n, (k, i) in enumerate(puntos, 1):
            if (k, i) in hechos:
                continue
            df = data[k]
            try:
                r = leer(df.iloc[i - 399:i + 1], k)
            except Exception as e:
                print(f"  error del modelo: {e}", flush=True)
                time.sleep(5)
                continue
            res = ""
            if r["decision"] != "NO":
                j = i + r["vencimiento_min"] * 4
                d = 1 if r["decision"] == "CALL" else -1
                c0, c1 = df["close"].iloc[i], df["close"].iloc[j]
                res = "EMPATE" if c0 == c1 else "GANADA" if d * (c1 - c0) > 0 else "PERDIDA"
            w.writerow([k, i, f"{df.index[i]:%Y-%m-%d %H:%M:%S}", r["decision"], r["vencimiento_min"],
                        r["confianza"], r["razon"], res])
            fh.flush()
            print(f"[{n}/{len(puntos)}] {k} {r['decision']} {r['vencimiento_min']}m "
                  f"conf={r['confianza']} {res}  {r['razon']}", flush=True)
    t = pd.read_csv(out)
    op = t[t.resultado.isin(["GANADA", "PERDIDA"])]
    g, n = int((op.resultado == "GANADA").sum()), len(op)
    print(f"\nmomentos vistos {len(t)} | opero en {n} ({100 * n / max(len(t), 1):.0f} %)")
    if n:
        lo, hi = wilson(g, n)
        print(f"acierto {100 * g / n:.1f} %  IC95 [{100 * lo:.1f}, {100 * hi:.1f}]  (hace falta > {100 * BE:.1f} %)")
        for v, gg in op.groupby("vencimiento_min"):
            print(f"  venc {v} min: {int((gg.resultado == 'GANADA').sum())}/{len(gg)}")


if __name__ == "__main__":
    main()
