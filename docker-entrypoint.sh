#!/bin/bash
set -e

echo "============================================================"
echo "  Exnova Trading Bot + OpenCode Supervisor (PRACTICE mode)"
echo "============================================================"

# 0. Persistencia de estado del bot. /app/data es el VOLUMEN persistente de
# EasyPanel, pero el bot guarda estado en bot/brain/ y bot/data/. Redirigimos
# esos dirs al volumen via symlink para que sobrevivan reinicios.
mkdir -p /app/data/bot_brain /app/data/bot_data
# Mover contenido existente (primer arranque) y crear symlinks
if [ -d /app/bot/brain ] && [ ! -L /app/bot/brain ]; then
    cp -rn /app/bot/brain/. /app/data/bot_brain/ 2>/dev/null || true
    rm -rf /app/bot/brain
fi
[ -e /app/bot/brain ] || ln -s /app/data/bot_brain /app/bot/brain
if [ -d /app/bot/data ] && [ ! -L /app/bot/data ]; then
    cp -rn /app/bot/data/. /app/data/bot_data/ 2>/dev/null || true
    rm -rf /app/bot/data
fi
[ -e /app/bot/data ] || ln -s /app/data/bot_data /app/bot/data
echo "[entrypoint] Persistencia: bot/brain -> /app/data/bot_brain, bot/data -> /app/data/bot_data"
ls -la /app/bot/ | grep -E "brain|data" || true

# 1. Inicializar SQLite (migrate) antes de arrancar nada.
echo "[entrypoint] Ejecutando migrate de la base SQLite..."
python3 -c "from app.data.repository import repository; repository.migrate(); print('[entrypoint] migrate OK')" || {
    echo "[entrypoint] WARN: migrate fallo, el bot arrancara igual (las tablas se crean bajo demanda)."
}

# 2. Bot de trading (foreground del PID 1 no; lo arrancamos en background).
# bot/run_live.py es el UNICO runner canonico (fusion del que vivia en la raiz
# con el de bot/, ver comentario al inicio de ese archivo).
echo "[entrypoint] Arrancando bot de trading (bot/run_live.py)..."
python3 -u bot/run_live.py &
BOT_PID=$!
echo "[entrypoint] Bot PID: $BOT_PID"

# 3. Monitor HTTP (dashboard + API JSON en puerto PORT=8000).
# Lee los JSON de persistencia del bot (read-only) y expone /api/* y dashboard.
echo "[entrypoint] Arrancando monitor HTTP (bot/monitor/server.py, puerto ${PORT:-8000})..."
python3 -u bot/monitor/server.py &
MON_PID=$!
echo "[entrypoint] Monitor PID: $MON_PID"

# 3b. Bucle de mejora continua por lotes (IA via REST opencode-go, sin CLI).
# Cada N trades nuevos analiza el lote, refina entradas/expiracion/activos y
# escribe strategy_adjustments.json que run_live.py lee antes de operar.
if [ "${IMPROVEMENT_ENABLED:-true}" = "true" ]; then
    echo "[entrypoint] Arrancando bucle de mejora IA (bot/brain/improvement_loop.py)..."
    python3 -u bot/brain/improvement_loop.py &
    IMP_PID=$!
    echo "[entrypoint] Improvement PID: $IMP_PID"
else
    IMP_PID=""
fi

# 4. Supervisor IA periodico (cada SUPERVISOR_INTERVAL_SECONDS=1800s por defecto).
# El default del fallback (":-false") es deliberado: si SUPERVISOR_ENABLED no
# esta definido, el supervisor de auto-aplicacion de codigo NO debe arrancar.
if [ "${SUPERVISOR_ENABLED:-false}" = "true" ]; then
    echo "[entrypoint] Arrancando supervisor IA (cada ${SUPERVISOR_INTERVAL_SECONDS:-1800}s)..."
    python3 -u -m app.services.supervisor_loop &
    SUP_PID=$!
    echo "[entrypoint] Supervisor PID: $SUP_PID"
else
    echo "[entrypoint] Supervisor deshabilitado (SUPERVISOR_ENABLED=false)."
    SUP_PID=""
fi

# 5. Trap de señales: al recibir SIGTERM/SIGINT matar a los hijos graceful.
trap 'echo "[entrypoint] signal recibida, deteniendo..."; kill $BOT_PID 2>/dev/null; kill $MON_PID 2>/dev/null; [ -n "$IMP_PID" ] && kill $IMP_PID 2>/dev/null; [ -n "$SUP_PID" ] && kill $SUP_PID 2>/dev/null; exit 0' TERM INT

# 6. Esperar a que el bot termine; si muere, salir.
wait $BOT_PID
BOT_RC=$?
echo "[entrypoint] Bot termino con rc=$BOT_RC"
kill $MON_PID 2>/dev/null
[ -n "$IMP_PID" ] && kill $IMP_PID 2>/dev/null
[ -n "$SUP_PID" ] && kill $SUP_PID 2>/dev/null
exit $BOT_RC
