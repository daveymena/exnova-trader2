# -*- coding: utf-8 -*-
"""
Gemma operando en IQ Option PRACTICE: lee el grafico como un humano y compra.

Cada vela de 15 s, en dos tiempos: Gemma analiza ANTICIPO segundos antes del
cierre, con la vela aun en formacion; al cerrar, el codigo comprueba la vela de
confirmacion y solo entonces compra lo que Gemma ya habia aprobado.
  1. pide al broker las ultimas 400 velas de 15 s de cada activo abierto;
  2. filtros de la guia del usuario sin IA (bot/backtest/regla_guia.py): la
     direccion es el lado de la EMA 20 de 15 s; F1 no en el extremo (<= 2.5 ATR
     de la EMA 20 y <= 4 % de la EMA 20 de 1 min); F2 no tras vela de impulso a
     favor (> 1.5 ATR). Son el contorno de sus 64 operaciones reales;
     lugar y confirmacion (bot/backtest/confirmacion.py, informe v1.2): vela de 15 s
     cerrada a favor, retroceso que toco la EMA 20 y comienzo del movimiento: como
     maximo 60 % del rango de 30 min y 45 % del camino hasta la resistencia (CALL) o
     el soporte (PUT) (percentil 75 de sus operaciones). Ademas, a favor de la
     tendencia de 1 min: precio del lado correcto de la EMA 50 de 1 min. Fuera del
     15 % extremo del rango de 5 min: no comprar arriba ni vender abajo (informe v1.2);
     Sin esto no se le pregunta a Gemma;
  3. dibuja los graficos y Gemma, a la vez en todos los activos, decide CALL /
     PUT / NO comparando con ejemplos reales del usuario (bot/vision/ejemplos_usuario.py);
     cada respuesta queda en gemma_previo_analisis.csv;
  4. de las que coinciden con el lado de la EMA 20 toma UNA sola, la de mayor
     confianza, la registra en gemma_lugar_senales.csv ANTES de comprar y compra
     en PRACTICE; el resultado del broker queda en gemma_lugar_live.csv.
Gestion (guia): una operacion por analisis, un solo activo a la vez, vencimiento
3 min, no voltear la direccion en un activo justo despues de perder alli (F3),
tope diario y pausa de 30 min tras 3 perdidas seguidas.

Uso:
  python scripts/gemma_live.py --assets SNAP-OTC,SATSUSD-OTC --amount 1
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(ROOT / ".env")
import azura_live as al                                          # noqa: E402
from bot.backtest import regla_guia as rg                        # noqa: E402
from bot.backtest.confirmacion import cruces_e20, revisar, tendencia_1m  # noqa: E402
from bot.vision.ejemplos_usuario import PANORAMA, imagen, leer_como_usuario, seleccionar  # noqa: E402
from graficos_operaciones import MAP                             # noqa: E402
from iq_probe import connect, open_binaries                      # noqa: E402

TF, BARS = 15, PANORAMA
OFFSETS = range(-60, 61, 15)
RECIENTES = 4        # operaciones propias repasadas que Gemma ve junto a los ejemplos del usuario
SENALES = ROOT / "bot" / "data" / "gemma_lugar_senales.csv"
ANALISIS = ROOT / "bot" / "data" / "gemma_previo_analisis.csv"
APRENDIZAJE = ROOT / "bot" / "data" / "gemma_repaso.csv"
CONFIG = ROOT / "bot" / "data" / "gemma_config.json"
PARAR = ROOT / "bot" / "data" / "PARAR_REAL"     # crear este archivo detiene el bot en real
FINALIZADO = ROOT / "bot" / "data" / "REAL_FINALIZADO"
CUENTA = ROOT / "bot" / "data" / "REAL_OPS"        # operaciones de la tanda, por si el vigia lo relanza
DEFAULT_ASSETS = ("SATSUSD-OTC,SNAP-OTC,PEPEUSD-OTC,JUPUSD-OTC,AUDCAD-OTC,USDZAR-OTC,EURUSD-OTC,"
                  "GBPUSD-OTC,USDJPY-OTC,EURUSD-op,GBPUSD-op,USDJPY-op,XAUUSD-op,USSPX500:N,US30:N")


GUIA = rg.P(max_dist_atr=2.5, max_dist_1m=0.04, k_impulso=1.5)
ESPACIO_MIN_ATR, POS_MAX = 2.0, 0.85
POS30_MAX, AVANCE_MAX = 0.60, 0.45
POS3H_MAX, CRUCES_MAX = 0.80, 6     # fuera de la zona alta de la panoramica y sin lateral (scripts/medir_filtros.py)
VOL_MAX, SALTO_MAX = 1.8, 6.0       # bloquean el 3 % mas extremo (scripts/medir_mercado.py)
MADRUGADA = (5, 11)                 # horas UTC: 00:00 a 06:00 de Colombia, el peor tramo medido
ANTICIPO, GEMMA_TIMEOUT = 13, 11


def direccion_guia(df: pd.DataFrame, precio: float) -> str | None:
    """CALL/PUT por el lado de la EMA 20, o None si F1 o F2 prohiben entrar."""
    f = rg.features(df, precio)
    if f is None or f["lado"] == 0:
        return None
    if f["dist_atr"] > GUIA.max_dist_atr or f["dist_1m"] > GUIA.max_dist_1m:
        return None
    if f["ult_dir"] == f["lado"] and f["cuerpo_atr"] > GUIA.k_impulso:
        return None
    return "CALL" if f["lado"] > 0 else "PUT"


def vencimiento(defecto: int) -> int:
    """El que haya validado scripts/ciclo_mejora.py, o el de siempre."""
    try:
        return int(json.loads(CONFIG.read_text())["vencimiento_min"])
    except (OSError, ValueError, KeyError):
        return defecto


def mercado_loco(df: pd.DataFrame) -> bool:
    """Volatilidad de los ultimos 5 min muy por encima de lo normal del activo en 3 h."""
    r = df["high"] - df["low"]
    base = r.iloc[-800:-40].mean()
    return not base > 0 or r.iloc[-20:].mean() / base > VOL_MAX or r.iloc[-20:].max() / base > SALTO_MAX


def lugar_ok(df: pd.DataFrame, direccion: str, exigir_confirma: bool = True) -> dict | None:
    """Datos del lugar si hay espacio (y confirmacion, si se exige); None si no se puede entrar."""
    r = revisar(df, direccion)
    t = tendencia_1m(df, direccion)
    cruces = cruces_e20(df)
    if r and t and t["sobre_e50"] and r["toco_e20"] and r["pos30"] <= POS30_MAX and r["avance"] <= AVANCE_MAX \
            and r["pos_lado"] <= POS_MAX and t["pos_3h"] <= POS3H_MAX and cruces <= CRUCES_MAX \
            and (r["confirma"] or not exigir_confirma):
        return {**r, "pos_3h": t["pos_3h"], "cruces": cruces}
    return None


def registrar(row: dict, path: Path = SENALES) -> None:
    nuevo = not path.exists()
    with al.lock, path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if nuevo:
            w.writeheader()
        w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default=DEFAULT_ASSETS)
    ap.add_argument("--amount", type=float, default=1.0)
    ap.add_argument("--max-open", type=int, default=1)
    ap.add_argument("--max-dia", type=int, default=40)
    ap.add_argument("--max-gemma", type=int, default=4)
    ap.add_argument("--temprana", action="store_true", help="no espera la vela de confirmacion")
    ap.add_argument("--conf-min", type=int, default=70)
    ap.add_argument("--real", action="store_true", help="opera con dinero real; exige --confirmo-real")
    ap.add_argument("--confirmo-real", action="store_true")
    ap.add_argument("--max-ops", type=int, default=20, help="real: operaciones en total")
    ap.add_argument("--saldo-base", type=float, default=0.0, help="real: saldo inicial si se reanuda una tanda")
    ap.add_argument("--ops-hechas", type=int, default=0, help="real: operaciones ya hechas si se reanuda una tanda")
    ap.add_argument("--stop-perdida", type=float, default=20.0, help="real: perdida maxima en dolares")
    ap.add_argument("--stop-ganancia", type=float, default=60.0, help="real: ganancia a la que se detiene")
    ap.add_argument("--parar-al-perder", action="store_true", help="real: se detiene en la primera perdida")
    ap.add_argument("--con-madrugada", action="store_true", help="real: opera tambien de 00:00 a 06:00 de Colombia")
    ap.add_argument("--days", type=float, default=30)
    args = ap.parse_args()
    if args.real and (not args.confirmo_real or args.temprana or args.amount > 2 or args.max_open != 1):
        print("ABORTADO: real exige --confirmo-real, confirmacion de vela, una operacion a la vez y maximo $2")
        return 1
    modo = "REAL" if args.real else "PRACTICE"
    estrategia = "gemma_real" if args.real else "gemma_temprana" if args.temprana else "gemma_lugar"
    senales = SENALES.with_name(f"{estrategia}_senales.csv")
    analisis = ANALISIS.with_name(f"{estrategia}_analisis.csv") if args.real or args.temprana else ANALISIS
    assets = [a.strip() for a in args.assets.split(",") if a.strip()]

    def conectar():
        a = connect()
        if args.real:
            a.change_balance("REAL")
        return a

    api = conectar()
    if api.get_balance_mode() != modo:
        print(f"ABORTADO: la cuenta no esta en {modo}")
        return 1
    saldo_inicial = args.saldo_base or api.get_balance()
    print(f"IQ Option {modo} | Gemma lector de graficos | saldo {saldo_inicial} | "
          f"${args.amount} | {assets}", flush=True)
    real = {"ops": args.ops_hechas, "pnl": api.get_balance() - saldo_inicial, "pendiente": False, "parar": ""}
    aviso = [""]

    def avisar(texto: str) -> None:
        if texto != aviso[0]:
            print(f"[{datetime.now(timezone.utc):%H:%M:%S} UTC] {texto}", flush=True)
            aviso[0] = texto

    def motivo_parada() -> str:
        """Cualquier duda detiene el bot: nunca se abre una operacion que pueda pasar del tope."""
        perdida = saldo_inicial - api.get_balance()
        if PARAR.exists():
            return "archivo PARAR_REAL"
        if real["parar"]:
            return real["parar"]
        if api.get_balance_mode() != "REAL":
            return "la cuenta dejo de estar en REAL"
        if real["ops"] >= args.max_ops:
            return f"{args.max_ops} operaciones hechas"
        if real["pnl"] >= args.stop_ganancia:
            return f"ganancia de ${args.stop_ganancia:.0f} alcanzada"
        if real["pnl"] - args.amount < -args.stop_perdida or perdida + args.amount > args.stop_perdida:
            return f"tope de perdida de ${args.stop_perdida:.0f}"
        return ""

    ejemplos = seleccionar(MAP)
    print(f"{len(ejemplos)} ejemplos del usuario cargados", flush=True)
    giro = 0
    busy: dict[str, float] = {}
    abiertas: list[float] = []
    dia, ops_dia, perdidas_seguidas, pausa_hasta = None, 0, [0], [0.0]
    open_now, last_refresh = set(), 0.0

    ultima_perdida: dict[str, tuple[str, float]] = {}

    recientes: list[tuple[str, str]] = []

    def repasar(row, exp, df, lugar):
        """Mueve la entrada de -60 a +60 s con la misma duracion y lo deja como ejemplo para Gemma."""
        time.sleep(100)                                    # espera las velas posteriores a +60 s
        v = al.closed_candles(api, row["asset"], TF, api.get_server_timestamp(), 60)
        t0 = df.index[-1] + pd.Timedelta(seconds=TF + 1)
        d = 1 if row["direction"] == "call" else -1
        # IQ vence en minuto exacto: la duracion real va de exp - 15 s a exp + 30 s.
        minuto = t0.floor("min") + pd.Timedelta(minutes=1)
        primero = minuto if (minuto - t0).total_seconds() > 30 else minuto + pd.Timedelta(minutes=1)
        dur = primero + pd.Timedelta(minutes=exp - 1) - t0

        def precio(t):
            u = v[v.index + pd.Timedelta(seconds=TF) <= t]
            return float(u["close"].iloc[-1]) if len(u) else None

        gana = []
        for o in OFFSETS:
            ini = t0 + pd.Timedelta(seconds=o)
            a, b = precio(ini), precio(ini + dur)
            if a is not None and b is not None and d * (b - a) > 0:
                gana.append(o)
        registrar({"hora_utc": row["signal_candle_utc"], "activo": row["asset"], "direccion": row["direction"],
                   "resultado": row["status"], "duracion_s": int(dur.total_seconds()),
                   "pos30": round(lugar["pos30"], 3), "avance": round(lugar["avance"], 3),
                   "habria_ganado_s": " ".join(f"{o:+d}" for o in gana)}, APRENDIZAJE)
        if row["status"] == "win":
            etiqueta = f"El bot entro {row['direction'].upper()} aqui y gano"
        elif gana:
            etiqueta = f"El bot entro {row['direction'].upper()} aqui y perdio; habria ganado entrando {gana[0]:+d} s"
        else:
            etiqueta = f"El bot entro {row['direction'].upper()} aqui y perdio; no debia entrar"
        recientes.append((imagen(df, row["asset"]), etiqueta))

    def al_resolver(row, entry_ts, exp, df, lugar):
        al.resolve(api, row, entry_ts, exp)
        if args.real:
            if row["status"] in ("win", "loose", "equal"):
                real["pnl"] += float(row["broker_profit"] or 0)
            else:
                real["parar"] = f"sin resultado confirmado en {row['asset']}"
            real["pendiente"] = False
            print(f"  REAL: {real['ops']} operaciones, resultado {real['pnl']:+.2f}", flush=True)
        if row["status"] == "loose":
            ultima_perdida[row["asset"]] = (row["direction"].upper(), time.time())
            if args.real and args.parar_al_perder:
                real["parar"] = f"perdida en {row['asset']}"
        perdidas_seguidas[0] = perdidas_seguidas[0] + 1 if row["status"] == "loose" else 0
        if perdidas_seguidas[0] >= 3:
            pausa_hasta[0] = time.time() + 1800
            perdidas_seguidas[0] = 0
            print("  3 perdidas seguidas: pausa de 30 min", flush=True)
        try:
            repasar(row, exp, df, lugar)
        except Exception as e:
            print(f"  repaso fallido {row['asset']}: {e!r}", flush=True)

    deadline = time.time() + args.days * 86400
    while time.time() < deadline:
        now = api.get_server_timestamp()
        cierre = (int(now) // TF + 1) * TF                 # cierre de la vela en formacion
        if cierre - now < ANTICIPO:
            cierre += TF
        time.sleep(max(0.0, cierre - ANTICIPO - now))
        server_ts = api.get_server_timestamp()
        try:
            if not api.check_connect():
                print("Reconectando...", flush=True)
                api = conectar()
            if time.time() - last_refresh > 600:
                ob = open_binaries(api)
                open_now = {n for n, _ in ob.get("turbo", [])} | {n for n, _ in ob.get("binary", [])}
                last_refresh = time.time()
        except Exception as e:
            print(f"Error de conexion: {e}", flush=True)
            continue
        if args.real:
            if real["pendiente"]:
                continue
            motivo = motivo_parada()
            if motivo:
                print(f"REAL DETENIDO: {motivo}. {real['ops']} operaciones, resultado {real['pnl']:+.2f}, "
                      f"saldo {api.get_balance()}", flush=True)
                if not PARAR.exists():                     # el vigia no lo relanza tras un tope
                    FINALIZADO.write_text(motivo, encoding="utf-8")
                    CUENTA.unlink(missing_ok=True)
                break
        hoy = datetime.now(timezone.utc).date()
        if hoy != dia:
            dia, ops_dia = hoy, 0
        abiertas = [t for t in abiertas if t > server_ts]
        if ops_dia >= args.max_dia or time.time() < pausa_hasta[0]:
            continue
        if len(abiertas) >= args.max_open:
            continue
        if args.real and not args.con_madrugada and MADRUGADA[0] <= datetime.now(timezone.utc).hour < MADRUGADA[1]:
            avisar("Madrugada: sin operaciones hasta las 06:00 de Colombia")
            continue
        candidatos, vistos, locos = [], 0, 0
        giro = (giro + args.max_gemma) % len(assets)       # Gemma no alcanza para todos: se turnan
        for asset in assets[giro:] + assets[:giro]:
            if len(candidatos) >= args.max_gemma:
                break
            if asset not in open_now or busy.get(asset, 0) > server_ts:
                continue
            try:
                df = al.closed_candles(api, asset, TF, cierre, BARS)   # incluye la vela en formacion
            except Exception:
                continue
            if len(df) < 300 or cierre - df.index[-1].timestamp() > 2 * TF:
                continue
            vistos += 1
            if mercado_loco(df):
                locos += 1
                continue
            guia = direccion_guia(df, float(df["close"].iloc[-1]))
            if guia is None:
                continue
            perdio = ultima_perdida.get(asset)
            if perdio and perdio[0] != guia and time.time() - perdio[1] < 300:
                continue                                   # F3: no voltear tras perder
            if lugar_ok(df, guia, exigir_confirma=False) is None:
                continue
            candidatos.append((asset, df, guia))
        if vistos >= 4 and locos * 2 >= vistos:
            pausa_hasta[0] = time.time() + 300
            avisar(f"Mercado inestable ({locos} de {vistos} activos): pausa de 5 min")
            continue
        avisar("Mercado normal")
        if not candidatos:
            continue

        def preguntar(c):
            try:
                return leer_como_usuario(c[1], c[0], ejemplos + recientes[-RECIENTES:], timeout=GEMMA_TIMEOUT,
                                         propuesta=c[2])
            except Exception as e:
                return {"decision": "ERROR", "vencimiento_min": 3, "confianza": 0, "razon": repr(e)[:120]}

        with ThreadPoolExecutor(max_workers=len(candidatos)) as ex:
            respuestas = list(ex.map(preguntar, candidatos))
        time.sleep(max(0.0, cierre + 1 - api.get_server_timestamp()))
        server_ts = api.get_server_timestamp()
        stamp = datetime.fromtimestamp(server_ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        buenos = []
        for r, c in zip(respuestas, candidatos):
            lugar = None
            if r["decision"] == c[2] and r["confianza"] >= args.conf_min:
                try:
                    df = al.closed_candles(api, c[0], TF, server_ts, BARS)
                except Exception:
                    df = pd.DataFrame()
                # La vela ya cerro: la condicion se decide aqui, con el cierre real.
                if len(df) >= 300 and df.index[-1].timestamp() == cierre - TF \
                        and direccion_guia(df, float(df["close"].iloc[-1])) == c[2]:
                    lugar = lugar_ok(df, c[2], exigir_confirma=not args.temprana)
                if lugar:
                    buenos.append((r, (c[0], df, c[2], lugar)))
            registrar({"hora_utc": stamp, "activo": c[0], "guia": c[2], "gemma": r["decision"],
                       "confianza": r["confianza"], "confirmo_al_cierre": lugar is not None,
                       "razon": r["razon"]}, analisis)
        if not buenos:
            continue
        r, (asset, df, _, lugar) = max(buenos, key=lambda x: x[0]["confianza"])   # una sola por analisis
        exp = vencimiento(r["vencimiento_min"])
        if not al.reservar(asset, exp * 60 + 75):           # una operacion por activo, entre todos los bots
            continue
        registrar({"hora_utc": stamp, "activo": asset, "decision": r["decision"], "vencimiento_min": exp,
                   "confianza": r["confianza"], "razon": r["razon"], "monto": args.amount}, senales)
        row = {"signal_candle_utc": df.index[-1].strftime("%Y-%m-%d %H:%M:%S"), "strategy": estrategia,
               "asset": asset, "tf": TF, "expiry_min": exp, "direction": r["decision"].lower(),
               "amount": args.amount, "order_id": "", "entry": "", "exit": "", "candle_result": "",
               "broker_profit": "", "status": "", "features": json.dumps({**r, **lugar}, ensure_ascii=False)}
        if args.real:
            if api.get_balance_mode() != "REAL" or motivo_parada():
                continue                                   # el bucle lo detiene con el motivo
            real["pendiente"] = True
            real["ops"] += 1
            CUENTA.write_text(str(real["ops"]), encoding="utf-8")
        ok, oid = api.buy(args.amount, asset, r["decision"].lower(), exp)
        row["order_id"] = oid if ok else ""
        row["status"] = "sent" if ok else f"rechazada: {oid}"
        print(f"[{stamp} UTC] {r['decision']} {asset} {exp}m conf={r['confianza']} {row['status']} | {r['razon']}",
              flush=True)
        if not ok:
            busy[asset] = server_ts + 600                  # IQ no lo vende ahora: 10 min sin consultarlo
            if args.real:
                real["pendiente"] = False
                real["ops"] -= 1
            continue
        ops_dia += 1
        entry_ts = int(api.get_server_timestamp()) // 60 * 60 + 60
        fin = server_ts + exp * 60 + 75
        busy[asset] = fin
        abiertas.append(fin)
        threading.Thread(target=al_resolver, args=(row, entry_ts, exp, df, lugar), daemon=True).start()
    time.sleep(6 * 60)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    import os
    os._exit(code)
