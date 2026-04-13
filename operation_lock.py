"""
🔒 SISTEMA DE LOCK ROBUSTO - Previene operaciones simultáneas
Usa archivo lock atómico con identificador de proceso
"""
import os
import time
import json
import psutil
from pathlib import Path
from datetime import datetime


class OperationLock:
    """
    Lock robusto que:
    1. Verifica si hay operación en curso
    2. Crea lock atómicamente (solo si no existe)
    3. Verifica si el proceso dueño sigue vivo
    4. Limpia locks "huérfanos" automáticamente
    """

    def __init__(self, lock_dir="data/locks"):
        self.lock_dir = Path(lock_dir)
        self.lock_dir.mkdir(parents=True, exist_ok=True)

        # Archivo principal de lock
        self.lock_file = self.lock_dir / "operation.lock"

    def is_locked(self):
        """Verifica si hay un lock activo y válido"""
        if not self.lock_file.exists():
            return False

        try:
            with open(self.lock_file, 'r') as f:
                lock_data = json.load(f)

            pid = lock_data.get('pid')
            timestamp = lock_data.get('timestamp', 0)

            # Si el lock tiene más de 20 minutos, es stale
            if time.time() - timestamp > 1200:  # 20 minutos
                print(f"   🔓 Lock expirado (más de 20 min), limpiando...")
                self.release()
                return False

            # Verificar si el proceso dueño sigue vivo
            if pid and psutil.pid_exists(pid):
                return True  # Lock válido
            else:
                # Proceso muerto, lock huérfano
                print(f"   🔓 Lock huérfano (PID {pid} no existe), limpiando...")
                self.release()
                return False

        except Exception as e:
            print(f"   ⚠️ Error leyendo lock: {e}, limpiando...")
            self.release()
            return False

    def acquire(self, operation_data=None):
        """
        Intenta adquirir el lock de forma atómica
        Retorna True si se adquirió, False si ya existe
        """
        # Verificación doble (check-then-act pattern)
        if self.is_locked():
            return False

        # Intentar crear el lock
        try:
            lock_data = {
                'pid': os.getpid(),
                'timestamp': time.time(),
                'created_at': datetime.now().isoformat(),
                'operation': operation_data or {}
            }

            # Crear archivo temporal y renombrar (operación atómica)
            temp_file = self.lock_dir / f"operation.lock.tmp.{os.getpid()}"
            with open(temp_file, 'w') as f:
                json.dump(lock_data, f, indent=2)

            # Renombrar atómicamente
            os.replace(temp_file, self.lock_file)

            # Verificación final
            if self.lock_file.exists():
                print(f"   🔒 Lock adquirido (PID: {os.getpid()})")
                return True
            else:
                return False

        except Exception as e:
            print(f"   ⚠️ Error creando lock: {e}")
            return False

    def release(self):
        """Libera el lock"""
        try:
            if self.lock_file.exists():
                self.lock_file.unlink()
                print(f"   🔓 Lock liberado")

            # Limpiar archivos temporales
            for temp in self.lock_dir.glob("operation.lock.tmp.*"):
                try:
                    temp.unlink()
                except:
                    pass

            return True
        except Exception as e:
            print(f"   ⚠️ Error liberando lock: {e}")
            return False

    def get_lock_info(self):
        """Obtiene información del lock actual"""
        if not self.is_locked():
            return None

        try:
            with open(self.lock_file, 'r') as f:
                return json.load(f)
        except:
            return None

    def force_release(self):
        """Fuerza la liberación del lock (uso de emergencia)"""
        print(f"   ⚠️ Forzando liberación de lock...")
        try:
            # Matar proceso dueño si existe
            info = self.get_lock_info()
            if info and 'pid' in info:
                try:
                    os.kill(info['pid'], 9)  # SIGKILL
                    print(f"   💀 Proceso {info['pid']} terminado")
                except:
                    pass

            self.release()
            return True
        except Exception as e:
            print(f"   ❌ Error forzando liberación: {e}")
            return False


# Instancia global
_lock_instance = None

def get_lock():
    """Obtiene la instancia global del lock"""
    global _lock_instance
    if _lock_instance is None:
        _lock_instance = OperationLock()
    return _lock_instance


def emergency_release():
    """Libera el lock forzosamente (uso de emergencia)"""
    lock = get_lock()
    return lock.force_release()


# Test
if __name__ == "__main__":
    print("🔒 Probando sistema de lock...")
    lock = get_lock()

    print(f"\nEstado inicial: {'🔒 Bloqueado' if lock.is_locked() else '🔓 Libre'}")

    print("\nIntentando adquirir lock...")
    if lock.acquire({'test': 'data'}):
        print("✅ Lock adquirido")
        print(f"Info: {lock.get_lock_info()}")

        print("\nIntentando segundo lock (debe fallar)...")
        if lock.acquire():
            print("❌ ERROR: Segundo lock adquirido!")
        else:
            print("✅ Segundo lock rechazado correctamente")

        print("\nLiberando lock...")
        lock.release()
    else:
        print("⚠️ No se pudo adquirir lock")

    print(f"\nEstado final: {'🔒 Bloqueado' if lock.is_locked() else '🔓 Libre'}")
