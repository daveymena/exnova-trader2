#!/usr/bin/env python3
"""
Script de diagnóstico para probar la conexión a Exnova.

Verifica en orden:
  0. Red: ¿se puede alcanzar TLS ws.trade.exnova.com / auth.trade.exnova.com?
  1. Login con las credenciales (PRACTICE).
  2. Balance de la cuenta demo.
  3. Actualización de activos.

Si el paso 0 falla, el problema es de RED (firewall/proxy/país bloqueando
Cloudflare), NO de credenciales ni del bot.
"""
import sys
import os
import socket
import ssl
from dotenv import load_dotenv

# Cargar variables de entorno (.env en la raíz del repo o cwd)
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


def preflight_network(hosts=("ws.trade.exnova.com", "auth.trade.exnova.com")):
    """Chequeo TCP+TLS. Devuelve (ok: bool, detalle: str)."""
    print("0. Verificando conectividad de red a Exnova...")
    for host in hosts:
        try:
            ip = socket.gethostbyname(host)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            raw = socket.create_connection((host, 443), timeout=10)
            s = ctx.wrap_socket(raw, server_hostname=host)
            s.close()
            print(f"   [OK] {host} ({ip}) — TLS responde")
        except Exception as e:
            print(f"   [RED-BLOQUEADA] {host}: {type(e).__name__} {str(e)[:80]}")
            print("   -> La RED corta la conexión (firewall/proxy/país). No es")
            print("      problema del bot ni de las credenciales. Usa una red")
            print("      que llegue a exnova.com (EasyPanel/VPS) o configura proxy.")
            return False
    print()
    return True


# Importar la API
from exnovaapi.stable_api import Exnova

def test_connection():
    email = os.getenv("EXNOVA_EMAIL", "")
    password = os.getenv("EXNOVA_PASSWORD", "")
    
    print(f"===================================================")
    print(f"  TEST DE CONEXION A EXNOVA")
    print(f"===================================================")
    print(f"Email: {email}")
    print(f"Password: {'*' * len(password)}")
    print(f"Tipo de cuenta: PRACTICE")
    print(f"===================================================\n")
    
    # Paso 0: red. Si no hay ruta TLS a Exnova, no se gasta tiempo en el login.
    if not preflight_network():
        return False
    
    try:
        print("1. Creando instancia de Exnova API...")
        api = Exnova(email, password, active_account_type="PRACTICE")
        print("   [OK] Instancia creada\n")
        
        print("2. Intentando conectar...")
        check, reason = api.connect()
        
        if check:
            print("   [OK] CONEXION EXITOSA!\n")
            
            print("3. Verificando conexion...")
            if api.check_connect():
                print("   [OK] Conexion verificada\n")
                
                print("4. Obteniendo balance...")
                balance = api.get_balance()
                print(f"   [OK] Balance: ${balance:,.2f}\n")
                
                print("5. Obteniendo activos disponibles...")
                try:
                    api.update_ACTIVES_OPCODE()
                    print("   [OK] Activos actualizados\n")
                except Exception as e:
                    print(f"   [WARN] Error actualizando activos: {e}\n")
                
                print("===================================================")
                print("  [OK] TODAS LAS PRUEBAS PASARON")
                print("===================================================")
                return True
            else:
                print("   [FAIL] Conexion no verificada\n")
                return False
        else:
            print(f"   [FAIL] CONEXION FALLIDA\n")
            print(f"Razon: {reason}\n")
            print("===================================================")
            print("  [FAIL] PRUEBA FALLIDA")
            print("===================================================")
            return False
            
    except Exception as e:
        print(f"\n[FAIL] ERROR CRITICO: {e}\n")
        import traceback
        traceback.print_exc()
        print("\n===================================================")
        print("  [FAIL] PRUEBA FALLIDA CON EXCEPCION")
        print("===================================================")
        return False

if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
