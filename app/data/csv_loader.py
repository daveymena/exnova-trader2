# -*- coding: utf-8 -*-
"""Carga de historico real desde CSV.

Es la unica fuente de datos que, junto al broker en vivo, produce EVIDENCIA.
`DataSource.CSV` pasa `EVIDENCE_SQL`; `DataSource.SIMULATOR` no. Esa diferencia
es la que impide que un backtest sobre datos inventados ascienda un setup a
PRODUCCION.

FORMATOS ACEPTADOS
------------------
Se detectan las columnas por nombre, en varios idiomas y convenciones, porque
el historico de binarias llega de sitios muy distintos (export del broker,
Dukascopy, TradingView, MT4/MT5, CSV de un data vendor):

  fecha/hora : timestamp, time, date, datetime, fecha, hora, "GMT timestamp",
               "<DATE>", "<TIME>" (formato MT4 en dos columnas)
  OHLC       : open/high/low/close, apertura/maximo/minimo/cierre,
               Open/High/Low/Close, o/high/l/c
  volumen    : volume, vol, volumen, "<VOLUME>", tick_volume
  activo     : symbol, asset, pair, activo, ticker  (si falta, se usa el
               nombre del fichero)

Timestamps: epoch en segundos o milisegundos, ISO-8601, o formatos habituales
(`%Y.%m.%d %H:%M:%S` de MT4, `%d/%m/%Y %H:%M`, `%Y-%m-%d %H:%M:%S`).

REMEDIO AL LOOK-AHEAD
---------------------
`resample()` construye M5/M15/M30/H1 a partir de M1. Una vela agregada solo se
emite si esta COMPLETA: si el CSV termina a las 12:07, la vela M5 de 12:05 no
existe todavia y no se devuelve. Entregar una vela parcial como si estuviera
cerrada es la forma mas comun de inflar un backtest de binarias, porque la
senal se genera con informacion que en vivo no estaria disponible.
"""
from __future__ import annotations

import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

from app.data.schemas import Candle, DataQuality, DataSource, Timeframe

# ── alias de columnas (minusculas, sin espacios ni signos) ────────────────
_TIME_ALIASES = {
    "timestamp", "time", "date", "datetime", "fecha", "hora", "fechahora",
    "gmttimestamp", "gmttime", "date1", "time1", "opentime", "candleopentime",
    "fechaapertura", "unixtime", "epoch",
}
_DATE_ONLY_ALIASES = {"date", "fecha", "<date>", "date1"}
_TIME_ONLY_ALIASES = {"time", "hora", "<time>", "time1"}
_OPEN_ALIASES = {"open", "apertura", "o", "openprice", "precioapertura", "bidopen"}
_HIGH_ALIASES = {"high", "maximo", "max", "h", "highprice", "maximodelperiodo"}
_LOW_ALIASES = {"low", "minimo", "min", "l", "lowprice", "minimodelperiodo"}
_CLOSE_ALIASES = {"close", "cierre", "c", "closeprice", "preciocierre", "bidclose", "last"}
_VOLUME_ALIASES = {"volume", "vol", "volumen", "tickvolume", "tickvol", "volume1"}
_ASSET_ALIASES = {"symbol", "asset", "pair", "activo", "ticker", "instrument", "instrumento"}

_TIMEFRAME_BY_SECONDS = {tf.value: tf for tf in Timeframe}


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").strip().lower())


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if not math.isnan(value) else None
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    # Separador decimal coma (export europeo): "1,08500".
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    elif "," in text and "." in text:
        # "1,085.50" -> el punto es decimal; "1.085,50" -> la coma es decimal.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    try:
        out = float(text)
    except ValueError:
        return None
    return out if not math.isnan(out) else None


_EXPLICIT_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%d.%m.%Y %H:%M:%S",
    "%Y%m%d%H%M%S", "%Y-%m-%d", "%d/%m/%Y",
)


def _parse_timestamp(value, date_part=None, time_part=None) -> Optional[datetime]:
    """Devuelve datetime NAIVE en UTC (convencion del resto del proyecto)."""
    raw = value if value is not None else ""
    text = str(raw).strip()
    if date_part is not None and time_part is not None:
        text = f"{str(date_part).strip()} {str(time_part).strip()}"
    if not text:
        return None

    # Epoch numerico.
    numeric = _to_float(text)
    if numeric is not None and re.fullmatch(r"\d+(\.\d+)?", text):
        # >1e12 solo puede ser milisegundos; >1e15, microsegundos.
        seconds = numeric / 1000.0 if numeric > 1e12 else (
            numeric / 1_000_000.0 if numeric > 1e15 else numeric)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None

    for fmt in _EXPLICIT_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=None) if dt.tzinfo is None \
                else dt.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo is None \
            else dt.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


@dataclass
class LoadReport:
    """Que paso al cargar. Sin esto un CSV mal parseado produce velas basura
    en silencio, y el backtest mide sobre basura."""
    path: str = ""
    rows_read: int = 0
    rows_parsed: int = 0
    rows_dropped: int = 0
    drop_reasons: dict = None
    asset: str = ""
    timeframe: Timeframe = Timeframe.M1
    first: Optional[datetime] = None
    last: Optional[datetime] = None
    duplicates_merged: int = 0
    columns_used: dict = None
    ok: bool = False

    def __post_init__(self):
        self.drop_reasons = self.drop_reasons or {}
        self.columns_used = self.columns_used or {}

    def as_dict(self) -> dict:
        return {
            "path": self.path, "rows_read": self.rows_read,
            "rows_parsed": self.rows_parsed, "rows_dropped": self.rows_dropped,
            "drop_reasons": dict(self.drop_reasons), "asset": self.asset,
            "timeframe": self.timeframe.name,
            "first": self.first.isoformat() if self.first else None,
            "last": self.last.isoformat() if self.last else None,
            "duplicates_merged": self.duplicates_merged,
            "columns_used": dict(self.columns_used), "ok": self.ok,
        }


def _detect_columns(fieldnames: Sequence[str]) -> dict:
    norm = {_normalize(f): f for f in fieldnames if f}
    found: dict[str, str] = {}

    def pick(aliases: Iterable[str], key: str) -> Optional[str]:
        for a in aliases:
            n = _normalize(a)
            if n in norm:
                return norm[n]
        # Coincidencia parcial: "gmttimestamp", "bidclose", "<CLOSE>".
        for n, original in norm.items():
            for a in aliases:
                if _normalize(a) and _normalize(a) in n:
                    return original
        return None

    found["open"] = pick(_OPEN_ALIASES, "open")
    found["high"] = pick(_HIGH_ALIASES, "high")
    found["low"] = pick(_LOW_ALIASES, "low")
    found["close"] = pick(_CLOSE_ALIASES, "close")
    found["volume"] = pick(_VOLUME_ALIASES, "volume")
    found["asset"] = pick(_ASSET_ALIASES, "asset")
    found["time"] = pick(_TIME_ALIASES, "time")
    found["date_only"] = next((norm[n] for n in norm if n in _DATE_ONLY_ALIASES), None)
    found["time_only"] = next((norm[n] for n in norm if n in _TIME_ONLY_ALIASES), None)
    return found


def load_candles(path: str | Path, asset: Optional[str] = None,
                 timeframe: Timeframe = Timeframe.M1,
                 delimiter: Optional[str] = None,
                 max_rows: Optional[int] = None) -> tuple[list[Candle], LoadReport]:
    """Carga velas desde CSV. Devuelve (velas ordenadas por open_time, informe).

    Las velas salen con `data_source=DataSource.CSV`: son historico REAL y por
    tanto SI cuentan como evidencia estadistica.
    """
    path = Path(path)
    report = LoadReport(path=str(path))
    if not path.exists():
        report.drop_reasons["file_not_found"] = 1
        return [], report

    if asset is None:
        asset = path.stem.split(".")[0].upper()
    report.asset = asset
    report.timeframe = timeframe

    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        if delimiter is None:
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = ","
        reader = csv.DictReader(fh, delimiter=delimiter)
        if not reader.fieldnames:
            report.drop_reasons["no_header"] = 1
            return [], report

        cols = _detect_columns(reader.fieldnames)
        report.columns_used = {k: v for k, v in cols.items() if v}

        missing = [k for k in ("open", "high", "low", "close") if not cols.get(k)]
        has_time = bool(cols.get("time")) or (cols.get("date_only") and cols.get("time_only"))
        if missing or not has_time:
            report.drop_reasons["missing_columns:" + ",".join(missing or ["time"])] = 1
            return [], report

        buckets: dict[datetime, list] = {}
        for row in reader:
            report.rows_read += 1
            if max_rows and report.rows_read > max_rows:
                break

            if cols.get("time"):
                ts = _parse_timestamp(row.get(cols["time"]))
            else:
                ts = _parse_timestamp(None, row.get(cols["date_only"]),
                                      row.get(cols["time_only"]))
            if ts is None:
                report.drop_reasons["bad_timestamp"] = \
                    report.drop_reasons.get("bad_timestamp", 0) + 1
                continue

            o = _to_float(row.get(cols["open"]))
            h = _to_float(row.get(cols["high"]))
            l = _to_float(row.get(cols["low"]))
            c = _to_float(row.get(cols["close"]))
            if None in (o, h, l, c):
                report.drop_reasons["bad_ohlc"] = report.drop_reasons.get("bad_ohlc", 0) + 1
                continue
            if h < l or h < min(o, c) or l > max(o, c):
                # OHLC inconsistente: el high por debajo del low, o el cuerpo
                # fuera del rango. No se "repara" reordenando, porque una vela
                # reparada es una vela inventada. Se descarta y se cuenta.
                report.drop_reasons["inconsistent_ohlc"] = \
                    report.drop_reasons.get("inconsistent_ohlc", 0) + 1
                continue

            volume = _to_float(row.get(cols["volume"])) if cols.get("volume") else None
            row_asset = (row.get(cols["asset"]) or asset).strip() if cols.get("asset") else asset

            # Alinear al inicio del bucket de la temporalidad pedida.
            epoch = int(ts.replace(second=0, microsecond=0).timestamp())
            aligned = datetime.fromtimestamp(epoch - (epoch % timeframe.value))

            key = aligned
            if key in buckets:
                b = buckets[key]
                b[1] = max(b[1], h); b[2] = min(b[2], l); b[3] = c
                if volume is not None:
                    b[4] = (b[4] or 0.0) + volume
                b[5] = row_asset
                report.duplicates_merged += 1
            else:
                buckets[key] = [o, h, l, c, volume, row_asset]
            report.rows_parsed += 1

    candles: list[Candle] = []
    for ts in sorted(buckets):
        o, h, l, c, volume, row_asset = buckets[ts]
        quality = DataQuality.NORMAL
        if h == l == o == c:
            # Vela plana: o el mercado estuvo cerrado o el feed no actualizo.
            # Se marca STALE para que las estrategias puedan ignorarla; una
            # vela plana no es informacion direccional, es ausencia de dato.
            quality = DataQuality.STALE
        candles.append(Candle(
            asset=row_asset, timeframe=timeframe, open_time=ts,
            open=o, high=h, low=l, close=c, volume=volume,
            source=f"csv:{path.name}", quality=quality,
            data_source=DataSource.CSV,
        ))

    if candles:
        report.first = candles[0].open_time
        report.last = candles[-1].open_time
        report.ok = True
    return candles, report


def resample(candles: Sequence[Candle], target: Timeframe,
             drop_incomplete: bool = True) -> list[Candle]:
    """Agrega velas de una temporalidad menor a `target`.

    `drop_incomplete=True` (defecto) descarta el ultimo bucket si no cubre el
    periodo entero. Es la defensa contra el look-ahead de agregacion: con un
    CSV que termina a las 12:07, la vela M15 de 12:00 NO esta cerrada, y
    entregarla como cerrada permitiria generar una senal M15 con 8 minutos de
    futuro que en vivo no existirian.
    """
    if not candles:
        return []
    source_tf = candles[0].timeframe
    if target.value <= source_tf.value:
        raise ValueError(
            f"resample: target {target.name} no es mayor que source {source_tf.name}"
        )
    if target.value % source_tf.value != 0:
        raise ValueError(
            f"resample: {target.name} no es multiplo entero de {source_tf.name}"
        )

    per_bucket = target.value // source_tf.value
    groups: dict[int, list[Candle]] = defaultdict(list)
    for c in candles:
        epoch = int(c.open_time.timestamp())
        groups[epoch - (epoch % target.value)].append(c)

    last_epoch = int(candles[-1].open_time.timestamp())
    last_bucket = last_epoch - (last_epoch % target.value)

    out: list[Candle] = []
    for key in sorted(groups):
        bucket = sorted(groups[key], key=lambda c: c.open_time)
        if drop_incomplete and key == last_bucket and len(bucket) < per_bucket:
            continue
        out.append(Candle(
            asset=bucket[0].asset, timeframe=target,
            open_time=datetime.fromtimestamp(key),
            open=bucket[0].open,
            high=max(c.high for c in bucket),
            low=min(c.low for c in bucket),
            close=bucket[-1].close,
            volume=(sum(c.volume for c in bucket if c.volume is not None)
                    if any(c.volume is not None for c in bucket) else None),
            source=bucket[0].source,
            quality=(DataQuality.NORMAL
                     if all(c.quality == DataQuality.NORMAL for c in bucket)
                     else DataQuality.SUSPECT),
            data_source=bucket[0].data_source,
        ))
    return out


def build_timeframes(m1: Sequence[Candle]) -> dict[Timeframe, list[Candle]]:
    """Construye M5/M15/M30/H1 a partir de M1, todas sin velas incompletas."""
    out: dict[Timeframe, list[Candle]] = {Timeframe.M1: list(m1)}
    for tf in (Timeframe.M5, Timeframe.M15, Timeframe.M30, Timeframe.H1):
        try:
            out[tf] = resample(m1, tf)
        except ValueError:
            out[tf] = []
    return out
