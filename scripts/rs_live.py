# -*- coding: utf-8 -*-
"""
Estrategia "Rechazo y Soporte" (bot/backtest/rs.py) en vivo, cuenta PRACTICE.

Al cierre de cada vela de 15 s recalcula la estrategia en cada activo; si hay
senal (setup A/B/C sin filtro), la anota ANTES de comprar en
bot/data/rs_live_senales.csv y abre una binaria. El resultado del broker va a
bot/data/rs_live.csv.

Gestion del paquete (seccion 6), con la hora del dia en UTC-5:
  monto fijo (1 % del saldo demo al arrancar, salvo --amount), sin martingala,
  max 2 abiertas en total y 1 por activo, enfriamiento F5 (tras vencer, esperar
  a que cierre una vela de 1 min nueva), 3 perdidas seguidas -> pausa 30 min,
  fin del dia con 5 perdidas o -5 % del saldo, max 25 operaciones por dia.

Nunca opera en REAL: el balance se fuerza a PRACTICE y se comprueba.

    python scripts/rs_live.py --broker exnova
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.backtest.rs import rs_signals      # noqa: E402

TF = 15
HIST_BARS = 2400                 # 10 h: suficiente para el percentil del rango (F7)
UTC5 = timezone(timedelta(hours=-5))
ASSETS = {"exnova": "US30:N,GBPUSD-op,USSPX500:N,OpenAI-OTC,PENUSD-OTC",
          "iq": "US30:N,GBPUSD-op,USSPX500:N,OpenAI-OTC,PENUSD-OTC"}
PRE_FIELDS = ["hora_utc5", "activo", "direccion", "setup", "pos", "r_max", "r_min",
              "vencimiento_min", "monto", "condiciones"]
FIELDS = PRE_FIELDS + ["order_id", "entrada", "salida_15s", "resultado_velas",
                       "resultado_broker", "pg_usd"]
SIG_LOG = ROOT / "bot" / "data" / "rs_live_senales.csv"
LOG = ROOT / "bot" / "data" / "rs_live.csv"
SETUP_TXT = {"A": "PUT rechazo de maximo en tercio alto, 1a vela bajista, sin minimos crecientes 1m",
             "B": "CALL con minimos crecientes 15s, retroceso sin romper minimo, pos<=0.66",
             "C": "CALL desde piso tocado 2+ veces, pos<=0.33, rechazo inferior o vela verde"}
lock = threading.Lock()
candles_lock = threading.Lock()  # buffer de velas compartido en la libreria


def append(path: Path, fields: list[str], row: dict) -> None:
    with lock:
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)


def connect(broker: str):
    load_dotenv(ROOT / ".env")
    if broker == "exnova":
        from exnovaapi.stable_api import Exnova
        import exnovaapi.constants as OP_code
        api = Exnova(os.getenv("NOVA_EMAIL"), os.getenv("NOVA_PASSWORD"), active_account_type="PRACTICE")
    else:
        from iqoptionapi.stable_api import IQ_Option
        import iqoptionapi.constants as OP_code
        api = IQ_Option(os.getenv("EXNOVA_EMAIL"), os.getenv("EXNOVA_PASSWORD"))
    ok, reason = api.connect()
    if not ok:
        raise SystemExit(f"ERROR de conexion: {reason}")
    api.change_balance("PRACTICE")
    init = api.get_all_init_v2() or {}
    for kind in ("turbo", "binary"):
        for active_id, a in (init.get(kind) or {}).get("actives", {}).items():
            OP_code.ACTIVES[str(a["name"]).split(".")[-1]] = int(active_id)
    return api


def open_now(api) -> set[str]:
    init = api.get_all_init_v2() or {}
    out = set()
    for kind in ("turbo", "binary"):
        for a in (init.get(kind) or {}).get("actives", {}).values():
            if a.get("enabled") and not a.get("is_suspended"):
                out.add(str(a["name"]).split(".")[-1])
    return out


def fetch(api, asset: str, n: int, end_ts: float) -> pd.DataFrame:
    frames, end = [], end_ts
    while n > 0:
        with candles_lock:
            raw = api.get_candles(asset, TF, min(n, 1000), end)
        if not raw:
            break
        df = pd.DataFrame(raw).rename(columns={"max": "high", "min": "low"})
        frames.append(df)
        n -= len(df)
        end = df["from"].min() - 1
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).drop_duplicates("from").sort_values("from")
    df = df[df["from"] + TF <= end_ts]                  # solo velas cerradas
    df.index = pd.to_datetime(df["from"], unit="s")
    return df[["open", "high", "low", "close"]].astype(float)


class Session:
    """Limites de la seccion 6 del paquete; el dia va de 00:00 a 24:00 UTC-5."""

    def __init__(self, a):
        self.a, self.day, self.trades, self.losses, self.streak = a, None, 0, 0, 0
        self.pause_until, self.day_start_bal, self.day_pl = 0.0, None, 0.0

    def roll(self, balance: float) -> None:
        d = datetime.now(UTC5).date()
        if d != self.day:
            self.day, self.trades, self.losses, self.streak, self.day_pl = d, 0, 0, 0, 0.0
            self.day_start_bal = balance

    def blocked(self) -> str:
        if self.trades >= self.a.max_day:
            return "max operaciones del dia"
        if self.losses >= 5:
            return "5 perdidas en el dia"
        if self.day_start_bal and self.day_pl <= -0.05 * self.day_start_bal:
            return "-5 % del saldo del dia"
        if time.time() < self.pause_until:
            return "pausa por 3 perdidas seguidas"
        return ""

    def result(self, profit: float | None) -> None:
        with lock:
            if profit is None:
                return
            self.day_pl += profit
            if profit < 0:
                self.losses += 1
                self.streak += 1
                if self.streak >= 3:
                    self.pause_until = time.time() + 30 * 60
                    self.streak = 0
            elif profit > 0:
                self.streak = 0


def resolve(api, row: dict, entry_ts: int, exp: int, sess: Session, busy: dict, open_ids: set) -> None:
    profit = None
    try:
        time.sleep(max(0, entry_ts + exp * 60 + 60 - time.time()))
        closed = api.api.socket_option_closed
        limit = time.time() + 300
        while time.time() < limit and closed.get(row["order_id"]) is None:
            time.sleep(1)
        msg = (closed.get(row["order_id"]) or {}).get("msg")
        if msg:
            win = msg["win"]
            profit = (0.0 if win == "equal" else -float(msg["sum"]) if win == "loose"
                      else float(msg["win_amount"]) - float(msg["sum"]))
            row["resultado_broker"] = {"win": "GANADA", "loose": "PERDIDA", "equal": "EMPATE"}.get(win, win)
            row["pg_usd"] = round(profit, 2)
        else:
            row["resultado_broker"] = "sin respuesta"
        with candles_lock:
            c = api.get_candles(row["activo"], TF, exp * 4 + 12, time.time())
        by = {x["from"]: x for x in c or []}
        last = by.get(entry_ts + exp * 60 - TF)
        if last:
            row["salida_15s"] = last["close"]
            e = float(row["entrada"])
            row["resultado_velas"] = ("EMPATE" if last["close"] == e else
                                      "GANADA" if (last["close"] > e) == (row["direccion"] == "call") else "PERDIDA")
    except Exception as ex:
        row["resultado_broker"] = f"error: {ex}"
    sess.result(profit)
    append(LOG, FIELDS, row)
    # F5: el activo queda libre cuando cierre una vela de 1 min nueva tras vencer
    end = entry_ts + exp * 60
    with lock:
        busy[row["activo"]] = (end // 60 + 1) * 60 + 60
        open_ids.discard(row["order_id"])
    print(f"  -> {row['activo']} {row['direccion'].upper()} setup {row['setup']}: "
          f"{row['resultado_broker']} {row['pg_usd']} | velas={row['resultado_velas']} | "
          f"dia: {sess.trades} ops, P/G {sess.day_pl:+.2f}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="exnova", choices=("exnova", "iq"))
    ap.add_argument("--assets")
    ap.add_argument("--amount", type=float, help="monto fijo; por defecto 1 %% del saldo demo")
    ap.add_argument("--max-open", type=int, default=2)
    ap.add_argument("--max-day", type=int, default=25)
    ap.add_argument("--hours", default="", help="horas UTC-5 permitidas, p. ej. 21,22,23 (vacio = todas)")
    ap.add_argument("--days", type=float, default=30)
    args = ap.parse_args()
    assets = [a.strip() for a in (args.assets or ASSETS[args.broker]).split(",") if a.strip()]
    hours = {int(h) for h in args.hours.split(",") if h.strip()}

    api = connect(args.broker)
    if api.get_balance_mode() != "PRACTICE":
        print("ABORTADO: la cuenta no esta en PRACTICE")
        return 1
    bal = float(api.get_balance())
    amount = args.amount or max(1.0, round(bal * 0.01))
    print(f"{args.broker.upper()} PRACTICE | RS v1.0 | saldo demo {bal:.2f} | monto fijo ${amount} | "
          f"{assets} | horas UTC-5 {sorted(hours) or 'todas'}", flush=True)

    cache: dict[str, pd.DataFrame] = {}
    busy: dict[str, float] = {}          # activo -> libre desde (epoch)
    open_ids: set = set()
    sess = Session(args)
    deadline = time.time() + args.days * 86400
    last_refresh, available = 0.0, set(assets)
    while time.time() < deadline:
        now = api.get_server_timestamp()
        time.sleep(max(0.0, TF - (now % TF) + 1))
        server_ts = api.get_server_timestamp()
        try:
            if not api.check_connect():
                print("Reconectando...", flush=True)
                api = connect(args.broker)
            if time.time() - last_refresh > 600:
                available = open_now(api) & set(assets)
                last_refresh = time.time()
                sess.roll(float(api.get_balance()))
        except Exception as e:
            print(f"Error de conexion: {e}", flush=True)
            continue
        sess.roll(sess.day_start_bal or bal)
        stamp = datetime.fromtimestamp(server_ts, UTC5)
        if hours and stamp.hour not in hours:
            continue

        for asset in assets:
            if asset not in available:
                continue
            try:
                old = cache.get(asset)
                if old is None or len(old) < 200:
                    df = fetch(api, asset, HIST_BARS, server_ts)
                else:
                    new = fetch(api, asset, 20, server_ts)
                    df = pd.concat([old, new])
                    df = df[~df.index.duplicated(keep="last")].iloc[-HIST_BARS:]
                cache[asset] = df
            except Exception as e:
                print(f"  {asset}: error de velas {e}", flush=True)
                continue
            if len(df) < 200 or (server_ts - df.index[-1].timestamp()) > 2 * TF:
                continue                                     # sin datos frescos
            with lock:
                if busy.get(asset, 0) > server_ts or len(open_ids) >= args.max_open:
                    continue
            why = sess.blocked()
            if why:
                continue
            sig = rs_signals(df.iloc[-1500:]).iloc[-1]
            if not sig["dir"]:
                continue

            exp = int(sig["exp_min"])
            entry_ts = int(df.index[-1].timestamp()) + TF
            row = {"hora_utc5": stamp.strftime("%Y-%m-%d %H:%M:%S"), "activo": asset,
                   "direccion": sig["dir"], "setup": sig["setup"], "pos": round(float(sig["pos"]), 3),
                   "r_max": sig["rmax"], "r_min": sig["rmin"], "vencimiento_min": exp, "monto": amount,
                   "condiciones": SETUP_TXT[sig["setup"]], "order_id": "", "entrada": df["close"].iloc[-1],
                   "salida_15s": "", "resultado_velas": "", "resultado_broker": "", "pg_usd": ""}
            append(SIG_LOG, PRE_FIELDS, row)                  # registro ANTES de abrir
            ok, oid = api.buy(amount, asset, sig["dir"], exp)
            if not ok:
                print(f"[{row['hora_utc5']}] {asset} {sig['dir'].upper()} rechazada por el broker: {oid}", flush=True)
                continue
            row["order_id"] = oid
            with lock:
                sess.trades += 1
                open_ids.add(oid)
                busy[asset] = float("inf")
            print(f"[{row['hora_utc5']} UTC-5] {sig['dir'].upper()} {asset} setup {sig['setup']} "
                  f"pos={row['pos']} exp={exp}m ${amount}", flush=True)
            threading.Thread(target=resolve, args=(api, row, entry_ts, exp, sess, busy, open_ids),
                             daemon=True).start()

    time.sleep(6 * 60)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
