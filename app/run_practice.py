# -*- coding: utf-8 -*-
"""Arranque en modo PRACTICE contra el broker real: datos reales, dinero demo.

PARA QUE EXISTE ESTE FICHERO
----------------------------
`app/main.py` no esta recableado al `TradingEngine`, asi que ejecutarlo hoy
correria el camino viejo: sin los gates estadisticos, sin el forense de perdidas
y sin la memoria de fallos. Este fichero es el camino de arranque correcto
mientras `main.py` no se reescribe.

Es tambien la unica forma de producir EVIDENCIA DE VERDAD. Todo lo medido hasta
ahora viene del simulador, que falla `is_evidence()` por diseno: ningun setup
puede ascender a PRODUCCION con datos simulados. La cuenta practice del broker
da datos reales (`data_source=BROKER`) sin dinero real en juego, y BROKER +
resolucion CANDLE si satisface `is_evidence()`. Es el forward test que falta.

DECISIONES DE SEGURIDAD, TODAS DELIBERADAS
------------------------------------------
1. `account_type` esta FIJO en "PRACTICE" y no es configurable por parametro ni
   por variable de entorno. Pasar a dinero real exige editar este fichero, que es
   exactamente el "doble opt-in manual" acordado. Un interruptor que se puede
   activar desde el entorno es un interruptor que se activa por accidente.

2. Las credenciales se leen de variables de entorno, NUNCA de argv. Los
   argumentos de linea de comandos quedan en el historial del shell y en la lista
   de procesos, visible para cualquier usuario de la maquina.

3. Si el broker no conecta, el proceso SALE CON CODIGO DE ERROR. No hay
   degradacion a PaperBroker: en modo practice el peligro no es perder dinero, es
   creer que se probo contra el broker cuando se probo contra una simulacion
   local. El respaldo silencioso produce justo eso.

4. Se comprueba `broker.data_source` DESPUES de conectar. Si no es BROKER, las
   operaciones no contarian como evidencia y toda la corrida seria inutil: mejor
   saberlo antes de dejarlo horas operando.

USO
---
    export EXNOVA_EMAIL="tu@correo.com"
    export EXNOVA_PASSWORD="..."          # o ponlos en .env (ya esta gitignoreado)
    python -m app.run_practice --assets EURUSD-OTC --cycles 500

Requiere `websocket-client`: sin el, la API vendida en bot/exnovaapi/ no carga y
el conector se niega a arrancar diciendo exactamente eso.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime

from app.config import config          # importa load_dotenv() -> lee .env
from app.data.feed import BrokerFeed
from app.data.schemas import DataSource
from app.core.engine import TradingEngine
from app.research.failure_memory import FailureMemory
from app.research.loss_forensics import LossForensics
from app.services.exnova_broker import EXNOVA_IMPORT_ERROR, ExnovaBroker

logger = logging.getLogger("practice")

#: Fijo a proposito. Ver la nota 1 del docstring: no se puede cambiar desde
#: fuera sin editar este fichero.
ACCOUNT_TYPE = "PRACTICE"


def _fail(msg: str, code: int = 1) -> None:
    print(f"\n[NO ARRANCA] {msg}\n", file=sys.stderr)
    raise SystemExit(code)


def build_broker() -> ExnovaBroker:
    """Conecta al broker en cuenta practice o aborta. Nunca degrada en silencio."""
    email = os.getenv("EXNOVA_EMAIL", "").strip()
    password = os.getenv("EXNOVA_PASSWORD", "").strip()
    if not email or not password:
        _fail(
            "Faltan credenciales. Define EXNOVA_EMAIL y EXNOVA_PASSWORD como "
            "variables de entorno o en un fichero .env en la raiz del repo "
            "(.gitignore ya lo cubre).\n"
            "  export EXNOVA_EMAIL=\"tu@correo.com\"\n"
            "  export EXNOVA_PASSWORD=\"...\"\n"
            "No las pases por argumento de linea de comandos: quedan en el "
            "historial del shell y en la lista de procesos."
        )

    broker = ExnovaBroker(email, password, account_type=ACCOUNT_TYPE,
                          allow_paper_fallback=False)
    print(f"[EXNOVA] conectando en cuenta {ACCOUNT_TYPE} como {email} ...")
    if not broker.connect():
        causa = EXNOVA_IMPORT_ERROR or "el broker rechazo la conexion"
        _fail(
            f"No se pudo conectar al broker.\n"
            f"  Causa: {causa}\n"
            f"  Si dice 'No module named websocket': pip install websocket-client\n"
            f"  Si no: revisa credenciales y que la cuenta {ACCOUNT_TYPE} exista.\n"
            f"No se degrada a PaperBroker a proposito: una corrida que simula en "
            f"local mientras parece operar contra el broker no produce evidencia, "
            f"produce confianza equivocada."
        )

    # Comprobacion de procedencia. Si esto no es BROKER, nada de lo que se
    # opere va a contar como evidencia y la corrida no sirve para lo unico que
    # sirve: demostrar edge sobre datos reales.
    if broker.data_source != DataSource.BROKER:
        _fail(
            f"Conectado, pero data_source={broker.data_source.value} en vez de "
            f"BROKER. Las operaciones no contarian como evidencia."
        )

    equity = broker.get_balance()
    print(f"[EXNOVA] conectado. data_source=BROKER  balance practice={equity}")
    return broker


def run(assets: list[str], cycles: int, interval: float,
        learn_every: int, payout: float) -> int:
    broker = build_broker()
    feed = BrokerFeed(broker, default_payout=payout)

    if not feed.assets():
        print("[AVISO] el broker no devolvio activos abiertos; se usan los "
              "indicados por linea de comandos.")

    memory = FailureMemory()
    engine = TradingEngine(
        feed=feed,
        broker=broker,
        repo=None,                    # usa el Repository por defecto (BD real)
        assets=assets,
        persist=True,
        forensics=LossForensics(),
        failure_memory=memory,
        learn_every_cycles=learn_every,
    )

    stop = {"now": False}

    def _on_signal(signum, frame):
        # Parada limpia: un Ctrl-C a mitad de ciclo no debe dejar operaciones
        # abiertas sin resolver ni la memoria de fallos sin guardar.
        print("\n[STOP] senal recibida; termino el ciclo actual y guardo...")
        stop["now"] = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    print(f"\n{'='*74}")
    print(f"  FORWARD TEST EN CUENTA PRACTICE — datos reales, dinero demo")
    print(f"  activos={assets}  ciclos={cycles}  intervalo={interval}s")
    print(f"  payout={payout}  aprendizaje cada {learn_every} ciclos")
    print(f"  Cada operacion cerrada se diagnostica (MAE/MFE) y alimenta la")
    print(f"  memoria de fallos. Ninguna entrada se repite si ya esta vetada.")
    print(f"{'='*74}\n")

    started = time.time()
    done = 0
    for i in range(cycles):
        if stop["now"]:
            break
        try:
            report = engine.step()
        except RuntimeError as exc:
            # El conector lanza RuntimeError en vez de degradar a simulacion.
            # Si el broker se cae a mitad de la corrida, se para: seguir
            # operando sin feed real fabricaria datos.
            _fail(f"el broker dejo de estar disponible: {exc}")
        except Exception as exc:                          # noqa: BLE001
            logger.error("ciclo %d fallo: %s", i, exc, exc_info=True)
        done = i + 1

        if report.traded:
            exp = getattr(report.trade, "expiry", 0) if report.trade else 0
            print(f"  [ciclo {i}] OPERA {report.asset} {report.direction} "
                  f"{exp}s stake={report.stake}")
        if report.rejection_stage == "failure_memory":
            print(f"  [ciclo {i}] VETADO por memoria de fallos: "
                  f"{report.rejection_reason[:100]}")
        if report.resolved:
            for t in report.resolved:
                print(f"  [ciclo {i}] CIERRA {t.asset} {t.direction.value} -> "
                      f"{t.execution_state.value} evidencia={t.is_evidence}")

        if done % 25 == 0:
            s = engine.summary()
            print(f"  --- ciclo {done}: trades={s['trades']} W={s['wins']} "
                  f"L={s['losses']} | sombras={s['shadow_observations']} | "
                  f"forenses={s['forensic_reports']} vetos={s['vetoes_applied']} "
                  f"| balance={s['balance']}")

        if not stop["now"]:
            time.sleep(interval)

    s = engine.summary()
    ev = engine.setup_evaluator.report()
    elapsed = time.time() - started
    print(f"\n{'='*74}")
    print(f"  RESUMEN TRAS {done} CICLOS ({elapsed/60:.1f} min)")
    print(f"{'='*74}")
    print(f"  trades operados   : {s['trades']}  (W {s['wins']} / L {s['losses']} "
          f"/ empates {s['ties']} / sin resolver {s['unresolved']})")
    print(f"  observaciones sombra: {s['shadow_observations']}")
    print(f"  balance practice  : {s['balance']}   drawdown max: "
          f"{s['max_drawdown_pct']}%")
    print(f"  diagnosticos forenses: {s['forensic_reports']}")
    print(f"  vetos aplicados   : {s['vetoes_applied']}")
    print(f"  detenido por riesgo: {s['risk_state'].get('day_halted', False)}")

    # LO UNICO QUE IMPORTA AL FINAL. Todo lo anterior es actividad; esto es
    # si hay edge demostrado sobre datos reales.
    print(f"\n  --- EVIDENCIA (lo que decide si esto sirve para algo) ---")
    probados = 0
    for row in (ev.get("setups") or [])[:20]:
        n = row.get("n") or 0
        if n == 0:
            continue
        wr = row.get("win_rate")
        est = row.get("state") or row.get("status")
        evid = row.get("evidence_n") or row.get("n_evidence")
        if est == "PRODUCCION":
            probados += 1
        print(f"    {str(row.get('slug'))[:46]:<46} n={n:<5} "
              f"evidencia={evid} wr={wr} estado={est}")
    print(f"\n  setups con edge PROBADO sobre datos reales: {probados}")
    if probados == 0:
        print("  Todavia ninguno. Es lo esperable con pocas horas de corrida:")
        print("  el umbral son 200 observaciones con la cota inferior de Wilson")
        print("  por encima del break-even, y Benjamini-Hochberg por encima.")
        print("  HASTA QUE ESO NO OCURRA, DINERO REAL NO. No es cautela")
        print("  decorativa: es el unico requisito que separa esto de las ~500")
        print("  operaciones que el bot anterior perdio ascendiendo reglas")
        print("  ajustadas con n=1, 6, 7 y 9.")
    print(f"{'='*74}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Forward test en cuenta PRACTICE del broker (datos reales, "
                    "dinero demo). Las credenciales van por entorno, no por aqui.")
    parser.add_argument("--assets", default="EURUSD-OTC",
                        help="activos separados por coma (defecto: EURUSD-OTC)")
    parser.add_argument("--cycles", type=int, default=500,
                        help="ciclos a ejecutar (defecto: 500)")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="segundos entre ciclos (defecto: 5)")
    parser.add_argument("--learn-every", type=int, default=500,
                        help="cada cuantos ciclos reaprende la memoria de fallos")
    parser.add_argument("--payout", type=float, default=0.85,
                        help="payout por defecto si el broker no lo reporta")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("app.data", "app.strategies", "app.agents",
                  "app.research.setup_evaluator", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    assets = [a.strip() for a in args.assets.split(",") if a.strip()]
    if not assets:
        _fail("no se indico ningun activo")
    return run(assets, args.cycles, args.interval, args.learn_every, args.payout)


if __name__ == "__main__":
    raise SystemExit(main())
