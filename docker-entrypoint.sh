#!/bin/bash
set -e

# EasyPanel puede crear el archivo .env sin exportarlo al proceso PID 1.
# Cargarlo aquí garantiza que bot, monitor e improvement_loop compartan la
# misma configuración sin copiar secretos al código fuente.
if [ -f /app/.env ]; then
    set -a
    . /app/.env
    set +a
fi
echo "[entrypoint] Exnova env: email=${EXNOVA_EMAIL:+set} password_len=${#EXNOVA_PASSWORD} dotenv=$( [ -f /app/.env ] && echo yes || echo no )"

if [ "${RESET_STATE:-false}" = "true" ]; then
    echo "[entrypoint] RESET_STATE activo: limpiando estado persistido del servicio"
    rm -f /app/data/brain/*.json /app/data/botdata/*.json
    rm -f /app/bot/brain/*.json /app/bot/data/*.json
fi

echo "============================================================"
echo "  Exnova Trading Bot + OpenCode Supervisor (PRACTICE mode)"
echo "============================================================"

# 0. Persistencia de estado del bot. /app/data es el VOLUMEN persistente de
# EasyPanel. El bot escribe estado en bot/brain/*.json y bot/data/*.json.
# Symlineamos SOLO los archivos de estado (no directorios, para no romper los
# imports de Python) hacia /app/data/brain/ y /app/data/botdata/.
mkdir -p /app/data/brain /app/data/botdata
persist_link() {
    local f="$1" dest="$2"
    [ -f "$f" ] || return 0
    if [ ! -L "$f" ]; then
        [ ! -e "$dest" ] && cp "$f" "$dest"
        rm -f "$f"
    fi
    [ -e "$f" ] || ln -s "$dest" "$f"
}
for f in /app/bot/brain/*.json; do
    persist_link "$f" "/app/data/brain/$(basename "$f")"
done
for f in /app/bot/data/*.json; do
    persist_link "$f" "/app/data/botdata/$(basename "$f")"
done
echo "[entrypoint] Estado persistente en /app/data/brain y /app/data/botdata (symlinks por archivo)"

# 1. Inicializar SQLite (migrate) antes de arrancar nada.
echo "[entrypoint] Ejecutando migrate de la base SQLite..."
python3 -c "from app.data.repository import repository; repository.migrate(); print('[entrypoint] migrate OK')" || {
    echo "[entrypoint] WARN: migrate fallo, el bot arrancara igual (las tablas se crean bajo demanda)."
}

# 2. Bot de trading (foreground del PID 1 no; lo arrancamos en background).
# bot/run_live.py es el UNICO runner canonico (fusion del que vivia en la raiz
# con el de bot/, ver comentario al inicio de ese archivo).
# Resiliencia: si el bot crashea o es matado (OOM, token expirado, error no
# capturado), se REARranca solo. El contenedor no debe morir: monitor e
# improvement deben seguir vivos siempre.
echo "[entrypoint] Arrancando bot de trading (bot/run_live.py) con auto-restart..."
(
    while true; do
        echo "[bot] === arranque $(date -u +%FT%TZ) ===" >> /app/data/bot.log
        python3 -u bot/run_live.py >> /app/data/bot.log 2>&1
        echo "[bot] === bot salio con rc=$? a las $(date -u +%FT%TZ) — reiniciando en 10s ===" >> /app/data/bot.log
        sleep 10
    done
) &
BOT_PID=$!
echo "[entrypoint] Bot supervisor PID: $BOT_PID (log: /app/data/bot.log)"

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
    python3 -u bot/brain/improvement_loop.py > /app/data/improvement_loop.log 2>&1 &
    IMP_PID=$!
    echo "[entrypoint] Improvement PID: $IMP_PID (log: /app/data/improvement_loop.log)"
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

# 6. Mantener el contenedor vivo mientras corran los procesos hijas. El bot se
# auto-reinicia (loop en background), asi que esperamos indefinidamente y solo
# salimos por señal.
while true; do
    sleep 30
done
