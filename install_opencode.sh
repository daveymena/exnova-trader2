#!/bin/bash
# Script para instalar OpenCode en el proyecto

echo "🚀 Instalando OpenCode..."

# Verificar si Node.js está instalado
if ! command -v node &> /dev/null; then
    echo "⚠️  Node.js no encontrado. Instalando..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi

# Instalar OpenCode globalmente
echo "📦 Instalando OpenCode CLI..."
npm install -g opencode-ai

# Verificar instalación
if command -v opencode &> /dev/null; then
    echo "✅ OpenCode instalado correctamente"
    opencode --version
else
    echo "❌ Error instalando OpenCode"
    exit 1
fi

echo ""
echo "📝 Configuración:"
echo "   Para usar OpenCode, ejecuta: opencode"
echo "   Para configurar API keys: opencode auth login"
echo ""
echo "⚠️  IMPORTANTE: OpenCode es para desarrollo, no para producción"
