#!/bin/bash
# Script seguro para iniciar el bot (previene múltiples instancias)

PID_FILE="/tmp/bot.pid"
LOCK_FILE="/tmp/bot.lock"

# Verificar si ya está corriendo
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "⚠️  El bot YA está corriendo (PID: $PID)"
        echo "    Para ver logs: tail -f logs/bot.log"
        echo "    Para detener: kill $PID"
        exit 0
    fi
fi

# Verificar lock file
if [ -f "$LOCK_FILE" ]; then
    echo "⚠️  Archivo de lock existe. Limpiando..."
    rm -f "$LOCK_FILE"
fi

# Crear lock
 touch "$LOCK_FILE"
 echo $$ > "$PID_FILE"

echo "🚀 Iniciando Bot de Trading..."
echo "   Modo: ${ACCOUNT_TYPE:-PRACTICE}"
echo "   PID: $$"
echo ""

# Ejecutar bot
python bot_con_ia.py

# Limpiar al salir
rm -f "$LOCK_FILE" "$PID_FILE"
echo "🛑 Bot detenido"
