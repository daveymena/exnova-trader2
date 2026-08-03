#!/bin/bash
# Script para descargar datos reales y ejecutar backtesting de PCR

echo "🚀 PCR Real Backtest - Descarga y Prueba"
echo "=========================================="
echo ""

# Validar credenciales
if [ -z "$EXNOVA_EMAIL" ] || [ -z "$EXNOVA_PASSWORD" ]; then
    echo "❌ ERROR: Falta EXNOVA_EMAIL y/o EXNOVA_PASSWORD"
    echo ""
    echo "Configurar variables de entorno:"
    echo "  export EXNOVA_EMAIL='tu@email.com'"
    echo "  export EXNOVA_PASSWORD='tu_contraseña'"
    echo ""
    exit 1
fi

echo "✓ Credenciales encontradas"
echo ""

# Descargar datos históricos de activos REALES (no OTC)
echo "📥 Descargando 180 días de datos reales..."
echo ""

REAL_ASSETS="USSPX500:N,USNDAQ100:N,US30:N,US2000:N,JAPAN225:N,DXY,EXY,AXY,BXY,ETHUSD-op"
TIMEFRAMES="60,300,900"  # 1m, 5m, 15m

python scripts/fetch_history.py \
    --assets "$REAL_ASSETS" \
    --timeframes "$TIMEFRAMES" \
    --days 180

if [ $? -ne 0 ]; then
    echo "❌ Error descargando datos"
    exit 1
fi

echo ""
echo "✓ Datos descargados"
echo ""

# Ejecutar backtesting
echo "📊 Ejecutando backtesting PCR Simple + PCR Complete..."
echo ""

python bot/backtest/pcr_backtest.py

echo ""
echo "✅ Backtesting completado"
echo ""
echo "📈 Resultados guardados en: pcr_backtest_results.json"
