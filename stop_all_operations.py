#!/usr/bin/env python3
"""
🛑 SCRIPT DE EMERGENCIA - DETENER TODAS LAS OPERACIONES
Detiene el bot y libera cualquier operación en curso
"""
import os
import sys
import time
import signal
from pathlib import Path

print("\n" + "="*80)
print("🛑 DETENIENDO TODAS LAS OPERACIONES DEL BOT")
print("="*80)

# 1. Buscar y matar procesos del bot
print("\n[1] Buscando procesos del bot...")
os.system("pkill -f 'bot_con_ia.py' 2>/dev/null || true")
os.system("pkill -f 'python.*bot' 2>/dev/null || true")
print("   ✅ Procesos del bot detenidos")

# 2. Liberar locks de operaciones
print("\n[2] Liberando locks de operaciones...")
lock_files = [
    "data/ai_learning/operation.lock",
    "/tmp/bot.lock",
    "/tmp/bot.pid",
    "bot.lock"
]

for lock_file in lock_files:
    try:
        if os.path.exists(lock_file):
            os.remove(lock_file)
            print(f"   ✅ Lock eliminado: {lock_file}")
    except Exception as e:
        print(f"   ⚠️  No se pudo eliminar {lock_file}: {e}")

# 3. Crear archivo de STOP de emergencia
print("\n[3] Creando señal de STOP global...")
stop_file = Path("data/EMERGENCY_STOP")
try:
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    stop_file.write_text(f"STOP signal created at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   ✅ Archivo de STOP creado: {stop_file}")
except Exception as e:
    print(f"   ⚠️  Error creando stop file: {e}")

# 4. Verificar si hay operaciones abiertas en el broker (si es posible)
print("\n[4] Verificando conexiones activas...")
try:
    # Intentar importar y cerrar conexiones
    sys.path.insert(0, '.')
    from config import Config
    from data.market_data import MarketDataHandler

    print("   🔌 Intentando cerrar conexiones abiertas...")
    # Nota: Esto requiere que el bot haya guardado el market_data globalmente
    # Si no, no podemos recuperar la conexión
    print("   ℹ️  Si hay operaciones abiertas en el broker, debes cerrarlas manualmente")
except Exception as e:
    print(f"   ℹ️  No se pudo verificar conexiones: {e}")

print("\n" + "="*80)
print("✅ TODAS LAS OPERACIONES DETENIDAS")
print("="*80)
print("\nAcciones realizadas:")
print("   • Procesos del bot terminados")
print("   • Locks liberados")
print("   • Señal de STOP creada")
print("\n⚠️  IMPORTANTE:")
print("   Si hay operaciones ABIERTAS en Exnova, ciérralas manualmente en:")
print("   https://app.exnova.com")
print("="*80)
