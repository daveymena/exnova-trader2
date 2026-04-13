#!/usr/bin/env python3
"""
SISTEMA DE BLOQUEO - Evita múltiples instancias del bot
"""
import os
import sys
import fcntl
import time
from pathlib import Path

class BotLock:
    """
    Sistema de bloqueo para evitar múltiples instancias
    """
    
    def __init__(self, lock_file="bot.lock"):
        self.lock_file = Path(lock_file)
        self.lock_fd = None
    
    def acquire(self):
        """
        Intenta adquirir el bloqueo
        Retorna True si lo consigue, False si ya hay otro bot corriendo
        """
        try:
            # Crear archivo de bloqueo
            self.lock_fd = open(self.lock_file, 'w')
            
            # Intentar bloquear el archivo
            fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            # Escribir PID del proceso actual
            self.lock_fd.write(f"{os.getpid()}\n")
            self.lock_fd.flush()
            
            return True
            
        except (IOError, OSError):
            # Ya hay otro bot corriendo
            if self.lock_fd:
                self.lock_fd.close()
            return False
    
    def release(self):
        """
        Libera el bloqueo
        """
        if self.lock_fd:
            try:
                fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
                self.lock_fd.close()
                self.lock_file.unlink(missing_ok=True)
            except:
                pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


def check_bot_running():
    """
    Verifica si ya hay un bot corriendo
    Retorna: (bool, int) - (está_corriendo, pid)
    """
    lock_file = Path("bot.lock")
    
    if not lock_file.exists():
        return False, 0
    
    try:
        with open(lock_file, 'r') as f:
            pid = int(f.read().strip())
        
        # Verificar si el proceso existe
        try:
            os.kill(pid, 0)  # No mata el proceso, solo verifica si existe
            return True, pid
        except OSError:
            # El proceso no existe, eliminar archivo de bloqueo
            lock_file.unlink(missing_ok=True)
            return False, 0
            
    except:
        return False, 0


def kill_running_bot():
    """
    Mata el bot que está corriendo
    """
    running, pid = check_bot_running()
    
    if running:
        try:
            os.kill(pid, 9)  # SIGKILL
            time.sleep(1)
            Path("bot.lock").unlink(missing_ok=True)
            return True
        except:
            return False
    
    return False


if __name__ == "__main__":
    print("=== VERIFICADOR DE BOTS ===\n")
    
    running, pid = check_bot_running()
    
    if running:
        print(f"⚠️ HAY UN BOT CORRIENDO")
        print(f"   PID: {pid}")
        print(f"\nPara detenerlo ejecuta:")
        print(f"   python bot_lock.py --kill")
    else:
        print("✅ No hay bots corriendo")
    
    # Verificar argumentos
    if len(sys.argv) > 1:
        if sys.argv[1] == "--kill":
            print("\nDeteniendo bot...")
            if kill_running_bot():
                print("✅ Bot detenido")
            else:
                print("❌ No se pudo detener el bot")