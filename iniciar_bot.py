#!/usr/bin/env python3
"""
INICIADOR SEGURO - Verifica antes de ejecutar el bot
"""
import os
import sys
import subprocess
from pathlib import Path

# Agregar directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot_lock import check_bot_running, kill_running_bot

def main():
    print("\n" + "="*80)
    print("INICIADOR SEGURO - BOT CON IA")
    print("="*80)
    
    # 1. Verificar si ya hay un bot corriendo
    print("\n[1] Verificando si ya hay un bot corriendo...")
    running, pid = check_bot_running()
    
    if running:
        print(f"   ⚠️ ADVERTENCIA: Ya hay un bot corriendo (PID: {pid})")
        print(f"\n   Opciones:")
        print(f"   1. Detener el bot actual y ejecutar uno nuevo")
        print(f"   2. Cancelar y dejar el bot actual corriendo")
        
        opcion = input("\n   ¿Qué deseas hacer? (1/2): ").strip()
        
        if opcion == "1":
            print("\n   Deteniendo bot anterior...")
            if kill_running_bot():
                print("   ✅ Bot anterior detenido")
            else:
                print("   ❌ No se pudo detener el bot anterior")
                return False
        else:
            print("\   Cancelando...")
            return False
    else:
        print("   ✅ No hay bots corriendo")
    
    # 2. Ejecutar el bot corregido
    print("\n[2] Iniciando bot con IA corregido...")
    print("="*80)
    
    try:
        # Importar y ejecutar el bot
        import bot_con_ia_corregido
        bot_con_ia_corregido.main()
    except KeyboardInterrupt:
        print("\n\n[STOP] Bot detenido por usuario")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)