#!/usr/bin/env python3
"""Importa velas REALES de mercado al formato que usa el repo.

Sirve para cualquier CSV con velas OHLC(V). Detecta solo las columnas, las
normaliza al formato de scripts/fetch_history.py y las deja en
bot/data/history/{ASSET}_60.csv, que es donde mira
research_strategy_audit.py --source real.

OJO con lo que se importa. Estos datos son velas REALES de mercado, no las
velas OTC del broker de binarias. Son un proxy honesto (mejor que sintetico)
pero NO son identicas: el broker de opciones puede anadir desplazamiento y
sus propias velas. El edge medido aqui hay que confirmarlo en PRACTICE.

Uso:
    # desde un CSV ya descargado
    python scripts/importar_velas_reales.py --csv EURUSD_H1.csv --asset EURUSD

    # desde el dataset publico de GitHub (sparse checkout, sin traerse 146MB)
    python scripts/importar_velas_reales.py --github simonnmarket/OMEGA_OS_Kernel \\
        --ruta OHLCV_DATA/EURUSD --asset EURUSD --timeframe 60
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

# Nombres de columna que se aceptan para cada campo.
_TIMESTAMP = {"time", "timestamp", "date", "datetime", "from", "open_time"}
_OPEN = {"open", "o", "open_price"}
_HIGH = {"high", "h", "max", "high_price"}
_LOW = {"low", "l", "min", "low_price"}
_CLOSE = {"close", "c", "close_price"}


# Minutos -> nombre de fichero tal como lo publica cada dataset.
# D1/H1/H4 son horas/dias, no minutos.
_NOMBRE_POR_MINUTOS = {1: "M1", 5: "M5", 15: "M15", 30: "M30", 60: "H1",
                       240: "H4", 1440: "D1"}


def _find(cols, wanted):
    for c in cols:
        if c.strip().lower() in wanted:
            return c
    return None


def normalizar_csv(origen: Path) -> pd.DataFrame:
    """Convierte cualquier CSV de velas al formato indice-datetime + OHLC."""
    df = pd.read_csv(origen)
    cols = list(df.columns)

    ts = _find(cols, _TIMESTAMP)
    o = _find(cols, _OPEN)
    h = _find(cols, _HIGH)
    lo = _find(cols, _LOW)
    c = _find(cols, _CLOSE)

    faltan = [n for n, v in (("timestamp", ts), ("open", o), ("high", h),
                             ("low", lo), ("close", c)) if v is None]
    if faltan:
        raise SystemExit(
            f"No se encontraron las columnas {faltan} en {origen.name}.\n"
            f"Columnas disponibles: {cols}"
        )

    out = pd.DataFrame({
        "open": pd.to_numeric(df[o], errors="coerce"),
        "high": pd.to_numeric(df[h], errors="coerce"),
        "low": pd.to_numeric(df[lo], errors="coerce"),
        "close": pd.to_numeric(df[c], errors="coerce"),
    })
    out.index = pd.to_datetime(df[ts], errors="coerce")
    out.index.name = "timestamp"

    antes = len(out)
    out = out.dropna()
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="first")]
    if antes != len(out):
        print(f"  Descartadas {antes - len(out)} filas invalidas o duplicadas")

    return out


def validar(df: pd.DataFrame, asset: str) -> list[str]:
    """Comprueba que las velas tienen sentido. Devuelve una lista de avisos."""
    avisos = []
    if df.empty:
        return ["El fichero no tiene ninguna vela valida"]

    mal_hl = (df["high"] < df["low"] - 1e-9).sum()
    if mal_hl:
        avisos.append(f"{mal_hl} velas con high < low")

    mal_oc = ((df["open"] > df["high"] + 1e-9) | (df["open"] < df["low"] - 1e-9)).sum()
    if mal_oc:
        avisos.append(f"{mal_oc} velas con open fuera del rango high-low")

    mal_cc = ((df["close"] > df["high"] + 1e-9) | (df["close"] < df["low"] - 1e-9)).sum()
    if mal_cc:
        avisos.append(f"{mal_cc} velas con close fuera del rango high-low")

    huecos = df.index.to_series().diff().dropna()
    mediana = huecos.median()
    if mediana and (huecos > mediana * 3).sum() > len(df) * 0.05:
        avisos.append(
            f"{(huecos > mediana * 3).sum()} huecos grandes (fin de semana?)")

    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        avisos.append("hay precios <= 0")

    return avisos


def descargar_de_github(repo: str, ruta: str, destino_dir: Path) -> Path:
    """Sparse checkout de un subdirectorio. No baja el resto del repo."""
    print(f"Descargando {repo}:{ruta} (solo ese subdirectorio)...")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--no-checkout",
             "--depth", "1", f"https://github.com/{repo}.git", tmp],
            check=True, capture_output=True, timeout=900,
        )
        subprocess.run(["git", "-C", tmp, "sparse-checkout", "set", ruta],
                       check=True, capture_output=True, timeout=300)
        subprocess.run(["git", "-C", tmp, "checkout"],
                       check=True, capture_output=True, timeout=900)
        src = Path(tmp) / ruta
        if not src.is_dir():
            raise SystemExit(f"La ruta {ruta} no existe en {repo}")
        destino_dir.mkdir(parents=True, exist_ok=True)
        for f in src.glob("*.csv"):
            shutil.copy2(f, destino_dir / f.name)
            print(f"  {f.name} ({f.stat().st_size / 1024:.0f} KB)")
        return destino_dir


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="CSV local a importar")
    ap.add_argument("--github", help="repo GitHub, p.ej. simonnmarket/OMEGA_OS_Kernel")
    ap.add_argument("--ruta", help="subdirectorio dentro del repo GitHub")
    ap.add_argument("--asset", default="EURUSD")
    ap.add_argument("--timeframe", type=int, default=60,
                    help="minutos de cada vela del fichero de entrada")
    ap.add_argument("--destino", default="bot/data/history")
    args = ap.parse_args()

    print("=" * 78)
    print("IMPORTAR VELAS REALES DE MERCADO")
    print("=" * 78)

    destino = ROOT / args.destino
    destino.mkdir(parents=True, exist_ok=True)

    if args.github:
        if not args.ruta:
            raise SystemExit("Con --github hace falta --ruta")
        d = descargar_de_github(args.github, args.ruta, destino / "_descargado")
        disponibles = sorted(f.name for f in d.glob("*.csv"))
        if not disponibles:
            raise SystemExit(f"No hay CSV en {args.ruta}")
        nombre = _NOMBRE_POR_MINUTOS.get(args.timeframe)
        cand = [f for f in d.glob(f"*_{nombre}.csv")] if nombre else []
        if not cand:
            raise SystemExit(
                f"No hay fichero de timeframe {nombre} (M{args.timeframe}).\n"
                f"Disponibles: {disponibles}\n"
                f"Usa --timeframe con uno de esos."
            )
        csv = cand[0]
        print(f"\nUsando {csv.name} (timeframe {nombre})")
    elif args.csv:
        csv = Path(args.csv)
        if not csv.is_absolute():
            csv = ROOT / csv
        if not csv.exists():
            raise SystemExit(f"No existe {csv}")
    else:
        raise SystemExit("Hace falta --csv o --github")

    print(f"\nNormalizando {csv.name}...")
    df = normalizar_csv(csv)
    if df.empty:
        raise SystemExit("El fichero no tiene velas validas")

    avisos = validar(df, args.asset)
    print(f"  Velas validas: {len(df)}")
    print(f"  Rango: {df.index[0]:%Y-%m-%d %H:%M} -> {df.index[-1]:%Y-%m-%d %H:%M}")
    print(f"  Precio: {df['close'].iloc[0]:.5f} -> {df['close'].iloc[-1]:.5f}")
    if avisos:
        print("  AVISOS:")
        for a in avisos:
            print(f"    - {a}")
    else:
        print("  Estructura OHLC coherente")

    # Guardar en el formato que espera research_strategy_audit --source real
    salida = destino / f"{args.asset}_{args.timeframe}.csv"
    df.to_csv(salida)
    print(f"\nGuardado en {salida.relative_to(ROOT)}")

    # Verificar que el repo puede leerlo
    from scripts.research_strategy_audit import load_real_series
    m15, m5, m1 = load_real_series(args.asset, args.timeframe, str(destino))
    print(f"Verificacion: el auditor lee {len(m1)} velas M1, "
          f"{len(m5)} M5, {len(m15)} M15")

    # Limpiar la carpeta temporal de descarga
    desc = destino / "_descargado"
    if desc.is_dir():
        shutil.rmtree(desc)

    print()
    print("IMPORTANTE - que son y que no son estos datos:")
    print("  Son velas REALES del mercado de divisas.")
    print("  NO son las velas OTC del broker de binarias.")
    print("  El edge medido aqui es una hipotesis solida, pero hay que")
    print("  confirmarla en PRACTICE contra el broker antes de operar.")
    print()
    print("Siguiente paso:")
    print(f"  python scripts/research_strategy_audit.py --source real "
          f"--asset {args.asset}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
