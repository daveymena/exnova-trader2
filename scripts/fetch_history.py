# -*- coding: utf-8 -*-
"""
Descarga y persiste velas historicas desde Exnova para poder backtestear
fuera de linea.

Sin historico guardado no existe validacion posible: hoy el bot solo puede
"probar" ideas arriesgando dinero real. Esto rompe esa dependencia.

La API entrega como maximo ~1000 velas por peticion, asi que paginamos hacia
atras usando el timestamp mas antiguo recibido como nuevo end_time.

Uso:
    python scripts/fetch_history.py --assets EURUSD,GBPUSD --days 30
    python scripts/fetch_history.py --assets EURUSD-OTC --days 7 --timeframes 60,300
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd


def safe_name(asset: str) -> str:
    """Los indices reales se llaman 'USSPX500:N' y ':' es invalido en Windows."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", asset)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bot"))

DATA_DIR = ROOT / "bot" / "data" / "history"
CHUNK = 1000          # velas por peticion (limite practico de la API)
PAUSE = 0.35          # respiro entre peticiones para no saturar el websocket
MAX_EMPTY = 3         # peticiones vacias seguidas antes de rendirse


def parquet_or_csv(df: pd.DataFrame, path_base: Path) -> Path:
    """Guarda en parquet si hay engine disponible; si no, csv."""
    try:
        target = path_base.with_suffix(".parquet")
        df.to_parquet(target)
        return target
    except Exception:
        target = path_base.with_suffix(".csv")
        df.to_csv(target)
        return target


def load_existing(path_base: Path) -> pd.DataFrame:
    for suffix in (".parquet", ".csv"):
        p = path_base.with_suffix(suffix)
        if not p.exists():
            continue
        try:
            if suffix == ".parquet":
                return pd.read_parquet(p)
            return pd.read_csv(p, index_col=0, parse_dates=True)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def fetch_asset(handler, asset: str, timeframe: int, days: int) -> pd.DataFrame:
    """Pagina hacia atras hasta cubrir `days` dias de velas."""
    target_span = days * 86400
    end_time = time.time()
    oldest_wanted = end_time - target_span
    frames: list[pd.DataFrame] = []
    empty_streak = 0

    while end_time > oldest_wanted:
        df = handler.get_candles(asset, timeframe, CHUNK, end_time)
        if df is None or df.empty:
            empty_streak += 1
            if empty_streak >= MAX_EMPTY:
                break
            end_time -= CHUNK * timeframe
            time.sleep(PAUSE)
            continue

        empty_streak = 0
        frames.append(df)
        first_ts = df.index[0].timestamp()

        # Si la API deja de retroceder, no hay mas historico disponible.
        if first_ts >= end_time - timeframe:
            break
        end_time = first_ts - timeframe

        got = sum(len(f) for f in frames)
        print(f"    {asset} tf={timeframe}s: {got} velas, hasta {df.index[0]}", flush=True)
        time.sleep(PAUSE)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out[out.index >= pd.to_datetime(oldest_wanted, unit="s")]


def main() -> int:
    ap = argparse.ArgumentParser(description="Descarga velas historicas de Exnova")
    ap.add_argument("--assets", required=True,
                    help="Lista separada por comas, ej: EURUSD,GBPUSD,EURUSD-OTC")
    ap.add_argument("--days", type=int, default=30, help="Dias de historico (default 30)")
    ap.add_argument("--timeframes", default="60,300,900",
                    help="Timeframes en segundos separados por comas (default 60,300,900)")
    args = ap.parse_args()

    assets = [a.strip() for a in args.assets.split(",") if a.strip()]
    timeframes = [int(t) for t in args.timeframes.split(",") if t.strip()]

    # load_dotenv() PRIMERO: si no, se comprueban variables que aun no existen.
    from dotenv import load_dotenv
    load_dotenv()

    if not os.getenv("EXNOVA_EMAIL") or not os.getenv("EXNOVA_PASSWORD"):
        print("ERROR: faltan EXNOVA_EMAIL / EXNOVA_PASSWORD en el entorno o .env")
        return 1

    from data.market_data import MarketDataHandler

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # La descarga es de solo lectura, pero conectamos en PRACTICE por seguridad:
    # este script nunca debe tocar el saldo real.
    handler = MarketDataHandler(broker_name="exnova", account_type="PRACTICE")
    if not handler.connect(os.getenv("EXNOVA_EMAIL"), os.getenv("EXNOVA_PASSWORD")):
        print("ERROR: no se pudo conectar a Exnova")
        return 1

    print(f"Descargando {len(assets)} activos x {len(timeframes)} timeframes x {args.days} dias\n")

    total_rows = 0
    for asset in assets:
        for tf in timeframes:
            base = DATA_DIR / f"{safe_name(asset)}_{tf}"
            print(f"  -> {asset} @ {tf}s")
            df = fetch_asset(handler, asset, tf, args.days)

            if df.empty:
                print(f"     sin datos para {asset} @ {tf}s")
                continue

            previous = load_existing(base)
            if not previous.empty:
                df = pd.concat([previous, df])
                df = df[~df.index.duplicated(keep="last")].sort_index()

            saved = parquet_or_csv(df, base)
            total_rows += len(df)
            print(f"     guardadas {len(df)} velas en {saved.name} "
                  f"({df.index[0]} -> {df.index[-1]})")

    print(f"\nListo. {total_rows} velas totales en {DATA_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
