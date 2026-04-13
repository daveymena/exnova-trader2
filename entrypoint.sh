#!/bin/bash
# Entrypoint flexible - puede ejecutar bot u OpenCode
# Previene múltiples instancias con archivo de lock

set -e

LOCK_FILE="/tmp/bot.lock"
PID_FILE="/tmp/bot.pid"

echo "🚀 Trading Bot + OpenCode Environment"
echo "====================================="
echo "Hora: $(date)"
echo "Modo: ${ACCOUNT_TYPE:-PRACTICE}"
echo ""

# Función para verificar si el bot ya está corriendo
check_bot_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            echo "⚠️  El bot ya está corriendo (PID: $PID)"
            echo "    Para reiniciar, elimina el archivo: rm $PID_FILE"
            return 0
        fi
    fi
    return 1
}

# Función para limpiar al salir
cleanup() {
    echo ""
    echo "🛑 Deteniendo servicio..."
    rm -f "$PID_FILE" "$LOCK_FILE"
    exit 0
}

trap cleanup SIGTERM SIGINT

# Verificar instalación de OpenCode
if command -v opencode &> /dev/null; then
    echo "✅ OpenCode disponible"
    opencode --version 2>/dev/null || true
else
    echo "⚠️  OpenCode no encontrado"
fi

echo ""
echo "📁 Directorio: $(pwd)"
echo ""

# Si se pasa 'opencode' como argumento, ejecutar opencode
if [ "$1" = "opencode" ]; then
    echo "🤖 Iniciando OpenCode..."
    echo "💡 Comandos útiles:"
    echo "   opencode --help"
    echo "   opencode auth login"
    echo ""
    exec opencode "${@:2}"

# Si se pasa 'shell' o 'bash', abrir terminal
elif [ "$1" = "shell" ] || [ "$1" = "bash" ]; then
    echo "🐚 Abriendo shell..."
    exec /bin/bash

# Si se pasa 'bot', ejecutar el bot de trading
elif [ "$1" = "bot" ]; then
    # Verificar si ya está corriendo
    if check_bot_running; then
        echo "❌ Abortando: Ya hay una instancia del bot activa"
        echo "    Esperando 60 segundos..."
        sleep 60
        exit 1
    fi

    echo "🤖 Iniciando Bot de Trading..."
    echo "   Modo: ${ACCOUNT_TYPE:-PRACTICE}"
    echo ""

    # Verificar variables necesarias
    if [ -z "$EXNOVA_EMAIL" ] || [ -z "$EXNOVA_PASSWORD" ]; then
        echo "❌ ERROR: EXNOVA_EMAIL o EXNOVA_PASSWORD no configurados"
        echo "   Configura estas variables en Easypanel:"
        echo "   - EXNOVA_EMAIL"
        echo "   - EXNOVA_PASSWORD"
        echo "   - ACCOUNT_TYPE (PRACTICE o REAL)"
        exit 1
    fi

    # Guardar PID
    echo $$ > "$PID_FILE"

    # Ejecutar bot con manejo de errores
    echo "🚀 Ejecutando: python bot_con_ia.py"
    echo "================================"
    exec python bot_con_ia.py || {
        echo ""
        echo "❌ El bot se detuvo con error"
        rm -f "$PID_FILE"
        exit 1
    }

# Si no hay argumentos específicos, mantener contenedor vivo (para Easypanel)
else
    echo "⏳ Modo espera activado"
    echo "   El contenedor está vivo. Usa la Terminal de Easypanel para ejecutar comandos:"
    echo "   - opencode     → Iniciar OpenCode"
    echo "   - bot          → Iniciar el bot de trading"
    echo "   - shell        → Abrir shell interactivo"
    echo ""
    echo "   Para iniciar el bot automáticamente, cambia el comando a: 'bot'"
    echo ""

    # Mantener contenedor vivo
    while true; do
        sleep 3600
    done
fi
