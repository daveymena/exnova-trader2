# -*- coding: utf-8 -*-
"""
Forense de operaciones: donde se gana, donde se pierde, donde refinar.

Lee el diario de `bot/data/trade_journal.jsonl` y disecciona los resultados por
cada dimension registrada: hora, activo, estrategia, tendencia, volatilidad,
RSI, extension respecto a la media, racha previa...

Lo que distingue a esta herramienta de un simple "winrate por grupo" es que
**marca explicitamente que conclusiones son solidas y cuales son ruido**. La
version anterior de este bot ajusto reglas sobre muestras de 1, 6, 7 y 9
operaciones; ese es exactamente el error que este script hace imposible pasar
por alto.

Uso:
    python scripts/forensics.py
    python scripts/forensics.py --payout 0.86 --min-n 30
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

JOURNAL = ROOT / "bot" / "data" / "trade_journal.jsonl"

# Dimensiones categoricas que se analizan tal cual.
CATEGORICAL = ["asset", "strategy", "setup", "direction", "hour_utc", "weekday",
               "pattern", "trend_m5", "trend_m15", "zone_type", "synthetic"]

# Dimensiones continuas que se trocean en cuantiles antes de analizar.
CONTINUOUS = {
    "rsi": "RSI en la entrada",
    "stoch_k": "Estocastico %K",
    "atr_pct": "Volatilidad (ATR % del precio)",
    "dist_ema21_atr": "Extension sobre EMA21 (en ATRs)",
    "bb_position": "Posicion en las bandas de Bollinger",
    "body_atr": "Tamano del cuerpo (en ATRs)",
    "streak": "Racha de velas previas",
    "confidence": "Confianza declarada por el motor",
    "zone_strength": "Fuerza de la zona",
}


def wilson(w: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m), min(1.0, c + m))


def verdict(lo: float, hi: float, be: float, n: int, min_n: int) -> str:
    if n < min_n:
        return "MUESTRA INSUFICIENTE"
    if lo > be:
        return "GANADOR SOLIDO"
    if hi < be:
        return "PERDEDOR SOLIDO"
    return "ruido"


def analyse_group(df: pd.DataFrame, col: str, be: float, min_n: int,
                  label: str | None = None) -> list[str]:
    if col not in df.columns or df[col].isna().all():
        return []
    lines = [f"\n{'=' * 86}", f"POR {label or col.upper()}", "=" * 86,
             f"  {'grupo':<26}{'n':>6}{'wr':>8}{'pnl':>10}   {'IC95%':<18}veredicto"]

    rows = []
    for value, sub in df.groupby(col, dropna=True):
        n = len(sub)
        w = int((sub["result"] == "WIN").sum())
        pnl = float(sub["pnl"].sum())
        lo, hi = wilson(w, n)
        rows.append((str(value), n, w / n if n else 0, pnl, lo, hi))

    rows.sort(key=lambda r: -r[1])
    for value, n, wr, pnl, lo, hi in rows:
        v = verdict(lo, hi, be, n, min_n)
        lines.append(f"  {value[:26]:<26}{n:>6}{100 * wr:>7.1f}%{pnl:>10.2f}   "
                     f"[{100 * lo:5.1f}%,{100 * hi:5.1f}%]  {v}")
    return lines


def analyse_continuous(df: pd.DataFrame, col: str, desc: str, be: float,
                       min_n: int, bins: int = 4) -> list[str]:
    if col not in df.columns:
        return []
    series = pd.to_numeric(df[col], errors="coerce")
    valid = series.notna()
    if valid.sum() < min_n * 2:
        return []
    if series[valid].nunique() < bins:
        return []

    try:
        buckets = pd.qcut(series[valid], bins, duplicates="drop")
    except ValueError:
        return []

    sub = df[valid].copy()
    sub["_bucket"] = buckets.astype(str)
    return analyse_group(sub, "_bucket", be, min_n, label=desc)


def main() -> int:
    ap = argparse.ArgumentParser(description="Forense de operaciones")
    ap.add_argument("--journal", default=str(JOURNAL))
    ap.add_argument("--payout", type=float, default=0.86)
    ap.add_argument("--min-n", type=int, default=30,
                    help="Minimo de operaciones para permitir una conclusion")
    args = ap.parse_args()

    path = Path(args.journal)
    if not path.exists():
        print(f"No existe el diario {path}")
        print("Se genera solo cuando el bot opera con bot/core/trade_journal.py activo.")
        return 1

    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    import json
                    rows.append(json.loads(line))
                except Exception:
                    continue
    df = pd.DataFrame(rows)
    if df.empty:
        print("El diario esta vacio.")
        return 1

    df = df[df["result"].isin(["WIN", "LOSS"])].copy()
    if df.empty:
        print("No hay operaciones cerradas todavia.")
        return 1

    be = 1 / (1 + args.payout)
    n, w = len(df), int((df["result"] == "WIN").sum())
    lo, hi = wilson(w, n)

    print("=" * 86)
    print("FORENSE DE OPERACIONES")
    print("=" * 86)
    print(f"Operaciones cerradas : {n}")
    print(f"Winrate global       : {100 * w / n:.2f}%  IC95% [{100 * lo:.1f}%, {100 * hi:.1f}%]")
    print(f"Break-even (payout {args.payout:.2f}) : {100 * be:.2f}%")
    print(f"PnL                  : {df['pnl'].sum():.2f}")
    print(f"Veredicto global     : {verdict(lo, hi, be, n, args.min_n)}")

    # Salud del dataset: si una feature vuelve a ser constante, hay que saberlo ya.
    print(f"\n{'=' * 86}")
    print("SALUD DE LAS FEATURES (una constante no sirve para refinar nada)")
    print("=" * 86)
    for col in list(CONTINUOUS) + ["pattern", "trend_m5"]:
        if col not in df.columns:
            continue
        s = df[col]
        filled = s.notna().sum()
        if filled == 0:
            print(f"  {col:<20} SIN DATOS — no se esta registrando")
            continue
        uniq = s.nunique(dropna=True)
        top_share = s.value_counts(dropna=True).iloc[0] / filled if filled else 0
        flag = ""
        if uniq <= 1:
            flag = "  <-- CONSTANTE, INUTIL"
        elif top_share > 0.8:
            flag = f"  <-- {100 * top_share:.0f}% un solo valor"
        print(f"  {col:<20} n={filled:<6} distintos={uniq:<6}{flag}")

    for col in CATEGORICAL:
        for line in analyse_group(df, col, be, args.min_n):
            print(line)

    for col, desc in CONTINUOUS.items():
        for line in analyse_continuous(df, col, desc, be, args.min_n):
            print(line)

    # Conclusiones accionables, y solo las que aguantan.
    print(f"\n{'=' * 86}")
    print("REFINAMIENTOS CON RESPALDO ESTADISTICO")
    print("=" * 86)
    found = []
    for col in CATEGORICAL:
        if col not in df.columns:
            continue
        for value, sub in df.groupby(col, dropna=True):
            k = len(sub)
            if k < args.min_n:
                continue
            wins = int((sub["result"] == "WIN").sum())
            l, h = wilson(wins, k)
            if h < be:
                found.append(f"  EVITAR  {col}={value}  ->  {100 * wins / k:.1f}% "
                             f"(n={k}), techo del IC {100 * h:.1f}% < break-even")
            elif l > be:
                found.append(f"  FAVORECER {col}={value}  ->  {100 * wins / k:.1f}% "
                             f"(n={k}), suelo del IC {100 * l:.1f}% > break-even")
    if found:
        print("\n".join(found))
    else:
        print("  Ninguna todavia. Hacen falta mas operaciones por grupo:")
        print(f"  con {n} operaciones y {args.min_n} minimo por grupo, la mayoria")
        print("  de los cortes aun no tienen muestra para concluir nada.")
        print("\n  Recordatorio: distinguir 57% de 54.4% exige ~800 operaciones")
        print("  del MISMO setup. Concentrar en pocos activos acelera esto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
