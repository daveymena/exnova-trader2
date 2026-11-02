# -*- coding: utf-8 -*-
"""
Azura Conteo v10 en vivo contra IQ Option PRACTICE (forward test).

Al cierre de cada vela del timeframe recalcula el indicador; si la vela recien
cerrada tiene flecha y cae dentro de las horas permitidas, abre una binaria en
la cuenta demo. Cada senal queda en bot/data/azura_live.csv con dos
resultados:
  candle_result -> el mismo criterio del backtest (apertura de la vela
                   siguiente vs cierre `expiry` minutos despues)
  broker        -> lo que pago de verdad el broker

Nunca opera en REAL: el balance se fuerza a PRACTICE y se comprueba.

Configuracion candidata (scripts/azura_filters.py, filtro "sesion"):
    python scripts/azura_live.py --tf 300 --expiry 15 --hours 13,14,15,16 --days 30
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bot.backtest.azura import azura_signals     # noqa: E402
from bot.backtest.choque import choque_features, choque_signals  # noqa: E402
from bot.backtest.patron_c import BARS as PATRON_C_BARS, patron_c_features, patron_c_signals  # noqa: E402
from iq_probe import connect, open_binaries      # noqa: E402

def retroceso_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Fin del retroceso con las reglas de lugar; misma logica que el historial."""
    from medir_vencimiento import senales
    s = senales(df, "contra")
    lado = s["lado"].iloc[-1] if len(s) and s.index[-1] == df.index[-1] else 0
    return pd.DataFrame({"call": [lado > 0], "put": [lado < 0]})


STRATEGIES = {
    "azura": lambda df, a: azura_signals(df),
    "retroceso": lambda df, a: retroceso_signals(df),
    "choque": lambda df, a: choque_signals(df, a.threshold),
    "patron_c": lambda df, a: patron_c_signals(df),
}
# Contexto de cada senal guardado en el CSV: con el tiempo dice en que
# condiciones gana la estrategia (scripts/revisar_live.py).
FEATURES = {"choque": choque_features, "patron_c": patron_c_features}
BARS = {"patron_c": PATRON_C_BARS, "retroceso": 500}

FIELDS = ["signal_candle_utc", "strategy", "asset", "tf", "expiry_min", "direction", "amount",
          "order_id", "entry", "exit", "candle_result", "broker_profit", "status", "features"]
REAL_ASSETS = "EURUSD-op,GBPUSD-op,USDJPY-op,XAUUSD-op,USSPX500:N,USNDAQ100:N,US30:N"
RESERVAS = ROOT / "bot" / "data" / "operaciones_abiertas.json"
EJEMPLOS: list[tuple[str, str]] = []
lock = threading.Lock()
# iqoptionapi guarda las velas pedidas en un unico buffer compartido: dos
# get_candles a la vez (bucle principal + hilos resolve) se cruzan los datos
# de activos distintos. Se serializan todas las peticiones.
candles_lock = threading.Lock()


def reservar(asset: str, segundos: float) -> bool:
    """Reserva el activo entre todos los bots: una sola operacion por activo a la vez."""
    cerrojo = RESERVAS.with_suffix(".lock")
    for _ in range(100):
        try:
            fd = os.open(cerrojo, os.O_CREAT | os.O_EXCL)
            break
        except FileExistsError:
            time.sleep(0.02)
    else:
        cerrojo.unlink(missing_ok=True)             # cerrojo abandonado por un bot detenido
        return False
    try:
        ahora = time.time()
        abiertas = json.loads(RESERVAS.read_text()) if RESERVAS.exists() else {}
        abiertas = {a: t for a, t in abiertas.items() if t > ahora}
        libre = asset not in abiertas
        if libre:
            abiertas[asset] = ahora + segundos
            RESERVAS.write_text(json.dumps(abiertas))
        return libre
    finally:
        os.close(fd)
        os.unlink(cerrojo)


def lectura_aprueba(api, asset: str, direction: str, ts: float, strategy: str) -> dict | None:
    """Gemma lee las velas antes de comprar; sin lectura aprobada no hay operacion."""
    from bot.vision.ejemplos_usuario import PANORAMA, leer_como_usuario
    lado = direction.upper()
    df = closed_candles(api, asset, 15, ts, PANORAMA)
    if len(df) < 300:
        return None
    try:
        r = leer_como_usuario(df, asset, EJEMPLOS, timeout=12, propuesta=lado)
    except Exception as e:
        print(f"  {asset}: sin lectura de Gemma, no se opera: {e!r}"[:160], flush=True)
        return None
    ok = r["decision"] == lado and r["confianza"] >= 70
    ruta = ROOT / "bot" / "data" / f"lectura_{strategy}.csv"
    nuevo = not ruta.exists()
    with lock, ruta.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["hora_utc", "activo", "propuesta", "gemma", "confianza", "aprobada", "razon"])
        w.writerow([datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), asset, lado, r["decision"],
                    r["confianza"], ok, r["razon"]])
    return r if ok else None


def get_candles(api, asset: str, tf: int, n: int, end_ts: float) -> list:
    with candles_lock:
        return api.get_candles(asset, tf, n, end_ts)


def log_path(strategy: str) -> Path:
    # El forward test de Azura empezo escribiendo en azura_live.csv: se conserva.
    name = "azura_live.csv" if strategy == "azura" else f"{strategy}_live.csv"
    return ROOT / "bot" / "data" / name


def log_row(row: dict) -> None:
    with lock:
        log = log_path(row["strategy"])
        new = not log.exists()
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)


def closed_candles(api, asset: str, tf: int, server_ts: float, n: int = 150) -> pd.DataFrame:
    raw = get_candles(api, asset, tf, n, server_ts)
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw).rename(columns={"max": "high", "min": "low"})
    df = df[df["from"] + tf <= server_ts]          # descarta la vela en formacion
    df.index = pd.to_datetime(df["from"], unit="s")
    return df[["open", "high", "low", "close"]].astype(float)


def iq_expiry_min(entry_ts: int, minutes: int) -> int:
    """Duracion real de una binaria de IQ: mas de 5 min vence en el cuarto de
    hora (:00/:15/:30/:45) mas cercano a la duracion pedida (iqoptionapi
    expiration.get_expiration_time)."""
    if minutes <= 5:
        return minutes
    cands = [m for m in range(6, 61) if ((entry_ts // 60 + m) % 15) == 0]
    return min(cands, key=lambda m: abs(m - minutes))


def resolve(api, row: dict, entry_ts: int, expiry_min: int) -> None:
    """Espera el resultado del broker y lo compara con el criterio del backtest."""
    try:
        time.sleep(max(0, entry_ts + expiry_min * 60 - time.time()) + 5)
        if row["order_id"]:
            # check_win_v4 de la libreria es un bucle activo sin timeout.
            closed = api.api.socket_option_closed
            limit = time.time() + 300
            while time.time() < limit and closed.get(row["order_id"]) is None:
                time.sleep(1)
            msg = (closed.get(row["order_id"]) or {}).get("msg")
            if msg:
                win = msg["win"]
                profit = (0 if win == "equal" else -float(msg["sum"]) if win == "loose"
                          else float(msg["win_amount"]) - float(msg["sum"]))
                row["broker_profit"] = round(profit, 2)
                row["status"] = win
            else:
                row["status"] = "sin respuesta del broker"

        m1 = get_candles(api, row["asset"], 60, expiry_min + 5, time.time())
        by_ts = {x["from"]: x for x in m1}
        first, last = by_ts.get(entry_ts), by_ts.get(entry_ts + (expiry_min - 1) * 60)
        if first and last:
            row["entry"], row["exit"] = first["open"], last["close"]
            if last["close"] == first["open"]:
                row["candle_result"] = "TIE"
            else:
                up = last["close"] > first["open"]
                row["candle_result"] = "WIN" if up == (row["direction"] == "call") else "LOSS"
    except Exception as e:
        row["status"] = f"error: {e}"
    log_row(row)
    print(f"  -> {row['asset']} {row['direction'].upper()} vela={row['candle_result']} "
          f"broker={row['status']} {row['broker_profit']}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="azura", choices=sorted(STRATEGIES))
    ap.add_argument("--threshold", type=float, default=3.0, help="choque: cuerpo minimo en ATRs")
    ap.add_argument("--assets", default=REAL_ASSETS)
    ap.add_argument("--tf", type=int, default=300, help="timeframe en segundos")
    ap.add_argument("--expiry", type=int, default=15, help="expiracion en minutos")
    ap.add_argument("--hours", default="13,14,15,16", help="horas UTC de la vela de senal")
    ap.add_argument("--amount", type=float, default=1.0)
    ap.add_argument("--days", type=float, default=30)
    ap.add_argument("--max-open", type=int, default=1,
                    help="operaciones abiertas a la vez en toda la cuenta")
    ap.add_argument("--no-trade", action="store_true")
    ap.add_argument("--lectura", action="store_true", help="Gemma debe aprobar el grafico antes de comprar")
    args = ap.parse_args()
    assets = [a.strip() for a in args.assets.split(",") if a.strip()]
    hours = {int(h) for h in args.hours.split(",") if h.strip()}

    if args.lectura:
        from bot.vision.ejemplos_usuario import seleccionar
        from graficos_operaciones import MAP
        EJEMPLOS.extend(seleccionar(MAP))
    api = connect()
    if api.get_balance_mode() != "PRACTICE":
        print("ABORTADO: la cuenta no esta en PRACTICE")
        return 1
    print(f"IQ Option PRACTICE | estrategia {args.strategy} | balance demo {api.get_balance()} | tf={args.tf}s "
          f"exp={args.expiry}min horas UTC={sorted(hours)} | {assets} | "
          f"{'SOLO SENALES' if args.no_trade else f'opera ${args.amount}'}", flush=True)

    deadline = time.time() + args.days * 86400
    open_now: set[str] = set()
    open_until: list[float] = []            # vencimiento de cada operacion abierta
    last_refresh = 0.0
    while time.time() < deadline:
        # Despierta 1 s despues del cierre de cada vela, en hora del servidor.
        now = api.get_server_timestamp()
        time.sleep(max(0.0, args.tf - (now % args.tf) + 1))
        server_ts = api.get_server_timestamp()

        try:
            if not api.check_connect():
                print("Reconectando...", flush=True)
                api = connect()
            if time.time() - last_refresh > 600:
                open_now = {n for n, _ in open_binaries(api).get("turbo", [])} | \
                           {n for n, _ in open_binaries(api).get("binary", [])}
                last_refresh = time.time()
        except Exception as e:
            print(f"Error de conexion: {e}", flush=True)
            continue

        stamp = datetime.fromtimestamp(server_ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        # Una operacion a la vez: se espera su resultado antes de abrir otra.
        open_until = [t for t in open_until if t > server_ts]
        slots = args.max_open - len(open_until)
        if slots <= 0:
            continue
        candidates = []
        for asset in assets:
            if asset not in open_now:
                continue
            try:
                df = closed_candles(api, asset, args.tf, server_ts, BARS.get(args.strategy, 150))
            except Exception:
                continue
            if len(df) < 60 or df.index[-1].hour not in hours:
                continue
            sig = STRATEGIES[args.strategy](df, args).iloc[-1]
            direction = "call" if sig["call"] else "put" if sig["put"] else None
            if not direction:
                continue
            feats = FEATURES[args.strategy](df) if args.strategy in FEATURES else {}
            candidates.append((abs(feats.get("body_atr", 0)), asset, direction, df, feats))

        # Varias senales en la misma vela: primero el choque mas fuerte.
        candidates.sort(key=lambda c: -c[0])
        for _, asset, direction, df, feats in candidates[:slots]:
            if args.lectura:
                lectura = lectura_aprueba(api, asset, direction, server_ts, args.strategy)
                if lectura is None:
                    continue
                feats = {**feats, "lectura": lectura["razon"], "confianza": lectura["confianza"]}
            entry_ts = int(df.index[-1].timestamp()) + args.tf
            exp = iq_expiry_min(entry_ts, args.expiry)
            if not args.no_trade and not reservar(asset, exp * 60 + 45):
                continue
            open_until.append(entry_ts + exp * 60 + 35)
            row = {"signal_candle_utc": df.index[-1].strftime("%Y-%m-%d %H:%M"),
                   "strategy": args.strategy, "asset": asset, "tf": args.tf, "expiry_min": exp,
                   "direction": direction, "amount": args.amount, "order_id": "",
                   "entry": "", "exit": "", "candle_result": "", "broker_profit": "",
                   "status": "no-trade", "features": json.dumps(feats) if feats else ""}
            if len(candidates) > slots:
                print(f"[{stamp} UTC] {len(candidates)} senales a la vez; se opera solo la mas fuerte",
                      flush=True)
            if not args.no_trade:
                ok, oid = api.buy(args.amount, asset, direction, args.expiry)
                row["order_id"] = oid if ok else ""
                row["status"] = "sent" if ok else f"rechazada: {oid}"
            print(f"[{stamp} UTC] SENAL {direction.upper()} {asset} "
                  f"(vela {row['signal_candle_utc']}) {row['status']}", flush=True)
            threading.Thread(target=resolve, args=(api, row, entry_ts, exp),
                             daemon=True).start()

    time.sleep(args.expiry * 60 + 120)       # deja terminar las ultimas resoluciones
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
