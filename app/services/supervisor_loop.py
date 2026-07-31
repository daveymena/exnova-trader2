"""Bucle de supervisión periódica.

Cada SUPERVISOR_INTERVAL_SECONDS (default 1800 = 30 min) ejecuta
opencode_orchestrator.run_cycle(). Maneja errores, loggea y reintenta.
Diseñado para correr en background dentro del contenedor EasyPanel.
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent.parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app.services.opencode_orchestrator import run_cycle  # noqa: E402
from app.data.repository import repository  # noqa: E402

INTERVAL = int(os.getenv("SUPERVISOR_INTERVAL_SECONDS", "1800"))
MAX_ERRORS = int(os.getenv("SUPERVISOR_MAX_CONSECUTIVE_ERRORS", "5"))
BACKOFF_SEC = int(os.getenv("SUPERVISOR_ERROR_BACKOFF_SEC", "300"))


def loop() -> None:
    sys.stdout.write(f"[supervisor] arrancando. intervalo={INTERVAL}s\n")
    sys.stdout.flush()
    consecutive_errors = 0
    cycle = 0
    while True:
        cycle += 1
        try:
            repository.audit_log(cycle, "supervisor", "tick_started", "")
            report = run_cycle()
            consecutive_errors = 0
            sys.stdout.write(
                f"[supervisor] ciclo {cycle} ok: "
                f"{report.get('n_proposals', 0)} propuestas, "
                f"rc={report.get('returncode')}\n"
            )
            sys.stdout.flush()
        except Exception as e:
            consecutive_errors += 1
            err_detail = f"{e}\n{traceback.format_exc()[-1000:]}"
            try:
                repository.audit_log(cycle, "supervisor", "tick_error",
                                     f"err={consecutive_errors} {err_detail}")
            except Exception:
                pass
            sys.stderr.write(f"[supervisor] error: {e}\n")
            sys.stderr.flush()
            if consecutive_errors >= MAX_ERRORS:
                sys.stderr.write(
                    f"[supervisor] {MAX_ERRORS} errores consecutivos. "
                    f"Esperando {BACKOFF_SEC}s antes de reintentar.\n"
                )
                time.sleep(BACKOFF_SEC)
                consecutive_errors = 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    loop()
