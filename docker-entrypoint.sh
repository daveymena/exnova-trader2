#!/bin/bash
set -e

echo "============================================================"
echo "  Exnova Trading Bot + OpenCode Supervisor (PRACTICE mode)"
echo "============================================================"

# 1. Inicializar SQLite (migrate) antes de arrancar nada.
echo "[entrypoint] Ejecutando migrate de la base SQLite..."
python3 -c "from app.data.repository import repository; repository.migrate(); print('[entrypoint] migrate OK')" || {
    echo "[entrypoint] WARN: migrate fallo, el bot arrancara igual (las tablas se crean bajo demanda)."
}

# 2. Bot de trading (foreground del PID 1 no; lo arrancamos en background).
echo "[entrypoint] Arrancando bot de trading (run_live.py)..."
python3 -u run_live.py &
BOT_PID=$!
echo "[entrypoint] Bot PID: $BOT_PID"

# 3. Supervisor IA periodico (cada SUPERVISOR_INTERVAL_SECONDS=1800s por defecto).
if [ "${SUPERVISOR_ENABLED:-true}" = "true" ]; then
    echo "[entrypoint] Arrancando supervisor IA (cada ${SUPERVISOR_INTERVAL_SECONDS:-1800}s)..."
    python3 -u -m app.services.supervisor_loop &
    SUP_PID=$!
    echo "[entrypoint] Supervisor PID: $SUP_PID"
else
    echo "[entrypoint] Supervisor deshabilitado (SUPERVISOR_ENABLED=false)."
    SUP_PID=""
fi

# 4. Trap de señales: al recibir SIGTERM/SIGINT matar a los hijos graceful.
trap 'echo "[entrypoint] signal recibida, deteniendo..."; kill $BOT_PID 2>/dev/null; [ -n "$SUP_PID" ] && kill $SUP_PID 2>/dev/null; exit 0' TERM INT

# 5. Esperar a que el bot termine; si muere, salir.
wait $BOT_PID
BOT_RC=$?
echo "[entrypoint] Bot termino con rc=$BOT_RC"
[ -n "$SUP_PID" ] && kill $SUP_PID 2>/dev/null
exit $BOT_RC
