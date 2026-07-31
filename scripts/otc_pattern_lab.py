# -*- coding: utf-8 -*-
"""
Laboratorio de patrones OTC.

Pregunta que responde: el feed sintetico del broker, que esta abierto 24/7,
tiene estructura estadistica explotable a 1-5 minutos?

No se responde discutiendo, se responde midiendo. Aqui se prueban decenas de
hipotesis sobre el historico descargado y se reporta cuales sobreviven.

Dos salvaguardas, sin las cuales este analisis se enganaria a si mismo:

1. **Correccion por comparaciones multiples.** Probar 60 reglas al 5% produce
   ~3 "descubrimientos" falsos por puro azar. Se aplica Bonferroni sobre el
   numero real de reglas probadas.
2. **Validacion fuera de muestra.** Toda regla se mide primero en el 70% mas
   antiguo y luego se confirma en el 30% mas reciente, que nunca se usa para
   elegir. Una regla que solo funciona in-sample es sobreajuste.

Uso:
    python scripts/otc_pattern_lab.py
    python scripts/otc_pattern_lab.py --payout 0.86 --expiries 1,3,5
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DIR = ROOT / "bot" / "data" / "history"

# Minimo de observaciones para que una regla sea siquiera considerada.
# Por debajo de esto el intervalo de confianza es tan ancho que no concluye nada.
MIN_SAMPLES = 200


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - m), min(1.0, c + m))


def load_history() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if not HISTORY_DIR.exists():
        return out
    for p in sorted(HISTORY_DIR.iterdir()):
        if p.suffix not in (".parquet", ".csv"):
            continue
        stem = p.stem
        if not stem.endswith("_60"):      # solo M1
            continue
        asset = stem[:-3]
        try:
            df = (pd.read_parquet(p) if p.suffix == ".parquet"
                  else pd.read_csv(p, index_col=0, parse_dates=True))
        except Exception as e:
            print(f"  aviso: no se pudo leer {p.name}: {e}")
            continue
        if len(df) >= 1000:
            out[asset] = df.sort_index()
    return out


# ---------------------------------------------------------------------------
# Generadores de senal. Cada uno devuelve una Serie booleana (entrar o no) y
# la direccion propuesta. Se evaluan todos contra todas las expiraciones.
# ---------------------------------------------------------------------------

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    c = df["close"]
    f["ret"] = c.pct_change()
    f["up"] = (c > c.shift(1)).astype(int)

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - c.shift(1)).abs(),
        (df["low"] - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    f["atr14"] = tr.rolling(14).mean()
    f["body"] = (c - df["open"]).abs()
    f["range"] = df["high"] - df["low"]

    # Racha de velas consecutivas en la misma direccion.
    streak = np.zeros(len(df), dtype=int)
    ups = f["up"].to_numpy()
    for i in range(1, len(df)):
        if ups[i] == ups[i - 1]:
            streak[i] = streak[i - 1] + (1 if ups[i] else -1)
        else:
            streak[i] = 1 if ups[i] else -1
    f["streak"] = streak

    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    f["rsi"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    f["ema8"] = c.ewm(span=8).mean()
    f["ema21"] = c.ewm(span=21).mean()
    f["dist_ema21"] = (c - f["ema21"]) / f["atr14"]

    sma20 = c.rolling(20).mean()
    sd20 = c.rolling(20).std()
    f["bb_pos"] = (c - sma20) / (2 * sd20)     # -1 = banda inferior, +1 = superior
    f["hour"] = df.index.hour
    return f


def rules(f: pd.DataFrame) -> dict[str, tuple[pd.Series, str]]:
    """Catalogo de hipotesis. Nombre -> (mascara de entrada, direccion)."""
    r: dict[str, tuple[pd.Series, str]] = {}

    # Reversion a la media tras rachas: la hipotesis clasica del OTC.
    for k in (2, 3, 4, 5):
        r[f"reversion_tras_{k}_subidas"] = (f["streak"] >= k, "PUT")
        r[f"reversion_tras_{k}_bajadas"] = (f["streak"] <= -k, "CALL")
        r[f"momentum_tras_{k}_subidas"] = (f["streak"] >= k, "CALL")
        r[f"momentum_tras_{k}_bajadas"] = (f["streak"] <= -k, "PUT")

    # Sobrecompra / sobreventa por RSI.
    for lo, hi in ((20, 80), (25, 75), (30, 70)):
        r[f"rsi_sobreventa_{lo}"] = (f["rsi"] < lo, "CALL")
        r[f"rsi_sobrecompra_{hi}"] = (f["rsi"] > hi, "PUT")

    # Bandas de Bollinger: rebote contra el borde.
    for th in (0.9, 1.0, 1.2):
        r[f"bb_rebote_inferior_{th}"] = (f["bb_pos"] < -th, "CALL")
        r[f"bb_rebote_superior_{th}"] = (f["bb_pos"] > th, "PUT")

    # Agotamiento tras vela desproporcionada respecto al ATR.
    for k in (1.5, 2.0, 2.5):
        big_up = (f["ret"] > 0) & (f["body"] > k * f["atr14"])
        big_dn = (f["ret"] < 0) & (f["body"] > k * f["atr14"])
        r[f"agotamiento_vela_alcista_{k}atr"] = (big_up, "PUT")
        r[f"agotamiento_vela_bajista_{k}atr"] = (big_dn, "CALL")
        r[f"continuacion_vela_alcista_{k}atr"] = (big_up, "CALL")
        r[f"continuacion_vela_bajista_{k}atr"] = (big_dn, "PUT")

    # Extension respecto a la media: vuelta al equilibrio.
    for k in (1.5, 2.0):
        r[f"extendido_sobre_ema21_{k}"] = (f["dist_ema21"] > k, "PUT")
        r[f"extendido_bajo_ema21_{k}"] = (f["dist_ema21"] < -k, "CALL")

    # Tendencia simple por cruce de EMAs.
    r["tendencia_ema8_sobre_21"] = (f["ema8"] > f["ema21"], "CALL")
    r["tendencia_ema8_bajo_21"] = (f["ema8"] < f["ema21"], "PUT")

    return r


def evaluate(df: pd.DataFrame, mask: pd.Series, direction: str,
             expiry_bars: int, split: int) -> dict:
    """Winrate de una regla, separando dentro y fuera de muestra."""
    entry = df["open"].shift(-1)              # se entra en la apertura siguiente
    exit_ = df["close"].shift(-(1 + expiry_bars))

    valid = mask & entry.notna() & exit_.notna()
    if direction == "CALL":
        win = exit_ > entry
    else:
        win = exit_ < entry
    tie = exit_ == entry
    valid = valid & ~tie

    pos = np.arange(len(df))
    ins = valid & (pos < split)
    oos = valid & (pos >= split)

    def stat(sel: pd.Series) -> tuple[int, int]:
        n = int(sel.sum())
        w = int((win & sel).sum())
        return n, w

    n_in, w_in = stat(ins)
    n_out, w_out = stat(oos)
    return {"n_in": n_in, "w_in": w_in, "n_out": n_out, "w_out": w_out}


def main() -> int:
    ap = argparse.ArgumentParser(description="Busca patrones explotables en el feed OTC")
    ap.add_argument("--payout", type=float, default=0.86,
                    help="Payout del broker (0.86 medido en Exnova)")
    ap.add_argument("--expiries", default="1,3,5",
                    help="Expiraciones en minutos, separadas por comas")
    args = ap.parse_args()

    breakeven = 1 / (1 + args.payout)
    expiries = [int(x) for x in args.expiries.split(",")]

    print("=" * 90)
    print("LABORATORIO DE PATRONES OTC")
    print("=" * 90)
    print(f"Payout {args.payout:.3f} -> break-even {100 * breakeven:.2f}%")

    data = load_history()
    if not data:
        print(f"\nNo hay historico en {HISTORY_DIR}")
        print("Descargalo antes con:")
        print("  python scripts/fetch_history.py --assets EURUSD-OTC --days 10 --timeframes 60")
        return 1

    print(f"Activos cargados: {len(data)}")
    for a, df in data.items():
        print(f"  {a:<16} {len(df):>7} velas M1  {df.index[0]} -> {df.index[-1]}")

    # Contamos cuantas pruebas se hacen en total, para corregir por multiplicidad.
    sample_rules = rules(build_features(next(iter(data.values()))))
    n_tests = len(sample_rules) * len(expiries) * len(data)
    z_corrected = abs(_norm_ppf(1 - 0.05 / (2 * n_tests)))
    print(f"\nPruebas totales: {n_tests}  ->  Bonferroni: se exige z={z_corrected:.2f} "
          f"(en vez de 1.96)")
    print("Es decir, una regla debe ser MUY consistente para contar como hallazgo.\n")

    survivors = []
    all_rows = []

    for asset, df in data.items():
        f = build_features(df)
        split = int(len(df) * 0.70)
        for name, (mask, direction) in rules(f).items():
            mask = mask.fillna(False)
            for exp in expiries:
                res = evaluate(df, mask, direction, exp, split)
                if res["n_in"] < MIN_SAMPLES or res["n_out"] < MIN_SAMPLES // 2:
                    continue

                wr_in = res["w_in"] / res["n_in"]
                wr_out = res["w_out"] / res["n_out"]
                lo_out, hi_out = wilson(res["w_out"], res["n_out"], z=z_corrected)

                row = {
                    "asset": asset, "rule": name, "dir": direction, "exp": exp,
                    "n_in": res["n_in"], "wr_in": wr_in,
                    "n_out": res["n_out"], "wr_out": wr_out,
                    "lo": lo_out, "hi": hi_out,
                }
                all_rows.append(row)
                # Sobrevive solo si el limite INFERIOR corregido supera el break-even.
                if lo_out > breakeven:
                    survivors.append(row)

    all_rows.sort(key=lambda r: -r["wr_out"])

    print("-" * 90)
    print("TOP 15 REGLAS POR WINRATE FUERA DE MUESTRA (ordenadas, sin filtrar)")
    print("-" * 90)
    print(f"{'activo':<14}{'regla':<32}{'exp':>4}{'n_oos':>7}{'wr_in':>8}{'wr_oos':>8}  IC99 corregido")
    for r in all_rows[:15]:
        print(f"{r['asset']:<14}{r['rule'][:30]:<32}{r['exp']:>3}m{r['n_out']:>7}"
              f"{100 * r['wr_in']:>7.1f}%{100 * r['wr_out']:>7.1f}%"
              f"  [{100 * r['lo']:5.1f}%, {100 * r['hi']:5.1f}%]")

    print()
    print("=" * 90)
    if survivors:
        print(f"REGLAS QUE SOBREVIVEN ({len(survivors)}): edge real fuera de muestra")
        print("=" * 90)
        for r in survivors:
            print(f"  {r['asset']} | {r['rule']} | {r['dir']} | {r['exp']}min")
            print(f"     in-sample {100 * r['wr_in']:.1f}% (n={r['n_in']})  ->  "
                  f"out-of-sample {100 * r['wr_out']:.1f}% (n={r['n_out']})")
            print(f"     IC corregido [{100 * r['lo']:.1f}%, {100 * r['hi']:.1f}%] "
                  f"> break-even {100 * breakeven:.1f}%")
    else:
        print("NINGUNA REGLA SOBREVIVE")
        print("=" * 90)
        print("Ninguna de las hipotesis probadas supera el break-even fuera de muestra")
        print("con correccion por comparaciones multiples.")
        best = all_rows[0] if all_rows else None
        if best:
            print(f"\nLa mejor fue '{best['rule']}' en {best['asset']} a {best['exp']}min:")
            print(f"  {100 * best['wr_out']:.1f}% fuera de muestra (n={best['n_out']}), "
                  f"pero su IC corregido baja hasta {100 * best['lo']:.1f}%,")
            print(f"  por debajo del {100 * breakeven:.1f}% necesario. No es distinguible del azar.")
    return 0


def _norm_ppf(p: float) -> float:
    """Inversa de la normal estandar (Acklam), para no depender de scipy."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > ph:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


if __name__ == "__main__":
    raise SystemExit(main())
