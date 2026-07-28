"""
🔐 FLUJO DE AUTENTICACIÓN COPILOT DEVICE
Genera código → Usuario autoriza → Obtiene token → Accede a modelos
"""
import json
import time
import random
import string
from typing import Dict, Optional
from pathlib import Path


class CopilotDeviceFlow:
    """
    Flujo completo de autenticación Copilot Device
    1. POST /copilot-device-code → Código (ABCD-1234)
    2. Usuario abre github.com/device → Escribe código
    3. POST /copilot-device-token → Polling cada 5 seg
    4. GET copilot_internal/v2/token → Intercambio interno
    5. Token guardado → Acceso a modelos
    """

    def __init__(self):
        self.name = "Copilot Device Flow v1.0"
        self.version = "1.0"
        
        # Configuración
        self.client_id = "Iv1.b507a08c87ecfe7e"
        self.device_code = None
        self.user_code = None
        self.access_token = None
        self.copilot_token = None
        
        # Rutas
        self.config_dir = Path.home() / ".copilot_trading_bot"
        self.config_dir.mkdir(exist_ok=True)
        self.token_file = self.config_dir / "copilot_token.json"
        
        print(f"[OK] {self.name} inicializado")

    # ═══════════════════════════════════════════════════════════════════════════════
    # PASO 1: POST /copilot-device-code
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_device_code(self) -> Optional[Dict]:
        """
        Paso 1: Obtener código de dispositivo
        POST /copilot-device-code
        """
        print(f"\n[PASO 1] Obteniendo código de dispositivo...")
        
        try:
            import requests
            
            url = "https://github.com/login/device/code"
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            data = {
                "client_id": self.client_id,
                "scope": "read:user user:email"
            }
            
            response = requests.post(url, headers=headers, data=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                
                self.device_code = result.get("device_code")
                self.user_code = result.get("user_code")
                
                print(f"[OK] Código generado: {self.user_code}")
                print(f"    Device code: {self.device_code[:20]}...")
                
                return result
            else:
                print(f"[ERROR] {response.status_code}")
                return None
                
        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════════════════
    # PASO 2: Usuario autoriza en github.com/device
    # ═══════════════════════════════════════════════════════════════════════════════

    def show_authorization_prompt(self) -> None:
        """
        Paso 2: Mostrar instrucciones para que usuario autorice
        Usuario abre github.com/device y escribe el código
        """
        print(f"\n[PASO 2] Esperando autorización del usuario...")
        print(f"\n{'='*100}")
        print(f"🔐 AUTORIZA EN GITHUB")
        print(f"{'='*100}\n")
        
        print(f"1. Abre: https://github.com/login/device")
        print(f"2. Escribe este código: {self.user_code}")
        print(f"3. Haz clic en 'Autorizar'")
        print(f"4. Vuelve aquí\n")
        
        print(f"{'='*100}\n")

    # ═══════════════════════════════════════════════════════════════════════════════
    # PASO 3: POST /copilot-device-token (Polling)
    # ═══════════════════════════════════════════════════════════════════════════════

    def poll_for_access_token(self, timeout: int = 900) -> Optional[Dict]:
        """
        Paso 3: Polling para obtener access_token
        POST /copilot-device-token cada 5 segundos
        """
        print(f"\n[PASO 3] Esperando confirmación (polling cada 5 seg)...")
        print(f"[*] Timeout: {timeout}s\n")
        
        start_time = time.time()
        attempt = 0
        
        try:
            import requests
            
            while time.time() - start_time < timeout:
                attempt += 1
                
                url = "https://github.com/login/oauth/access_token"
                
                headers = {
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
                
                data = {
                    "client_id": self.client_id,
                    "device_code": self.device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
                }
                
                response = requests.post(url, headers=headers, data=data, timeout=10)
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if "access_token" in result:
                        self.access_token = result["access_token"]
                        
                        print(f"\n[OK] ✅ Access token obtenido!")
                        print(f"    Token: {self.access_token[:20]}...")
                        
                        return result
                
                # Mostrar progreso
                elapsed = int(time.time() - start_time)
                remaining = timeout - elapsed
                print(f"[{attempt}] Esperando... ({remaining}s restantes)", end='\r')
                
                time.sleep(5)
            
            print(f"\n[ERROR] ❌ Timeout - usuario no autorizó")
            return None
            
        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════════════════
    # PASO 4: GET copilot_internal/v2/token (Intercambio interno)
    # ═══════════════════════════════════════════════════════════════════════════════

    def exchange_for_copilot_token(self) -> Optional[Dict]:
        """
        Paso 4: Intercambio interno para obtener token Copilot
        GET copilot_internal/v2/token
        """
        print(f"\n[PASO 4] Intercambiando por token Copilot...")
        
        if not self.access_token:
            print(f"[ERROR] No hay access_token")
            return None
        
        try:
            import requests
            
            url = "https://api.github.com/copilot_internal/v2/token"
            
            headers = {
                "Authorization": f"token {self.access_token}",
                "Accept": "application/json"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                
                self.copilot_token = result.get("token")
                
                print(f"[OK] ✅ Token Copilot obtenido!")
                print(f"    Token: {self.copilot_token[:20]}...")
                
                return result
            else:
                print(f"[!] Error {response.status_code}")
                print(f"    {response.text[:200]}")
                return None
                
        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════════════════
    # PASO 5: Guardar token
    # ═══════════════════════════════════════════════════════════════════════════════

    def save_token(self) -> bool:
        """
        Paso 5: Guardar token en DB local
        """
        print(f"\n[PASO 5] Guardando token...")
        
        if not self.copilot_token:
            print(f"[ERROR] No hay token para guardar")
            return False
        
        try:
            token_data = {
                "copilot_token": self.copilot_token,
                "access_token": self.access_token,
                "user_code": self.user_code,
                "saved_at": time.time()
            }
            
            with open(self.token_file, 'w') as f:
                json.dump(token_data, f, indent=2)
            
            print(f"[OK] ✅ Token guardado en {self.token_file}")
            
            return True
            
        except Exception as e:
            print(f"[ERROR] {e}")
            return False

    # ═══════════════════════════════════════════════════════════════════════════════
    # FLUJO COMPLETO
    # ═══════════════════════════════════════════════════════════════════════════════

    def authenticate(self) -> bool:
        """
        Flujo completo de autenticación
        """
        print(f"\n{'='*100}")
        print(f"🔐 FLUJO DE AUTENTICACIÓN COPILOT DEVICE")
        print(f"{'='*100}")
        
        # Paso 1: Obtener código
        device_code_result = self.get_device_code()
        if not device_code_result:
            print(f"[ERROR] No se pudo obtener código de dispositivo")
            return False
        
        # Paso 2: Mostrar instrucciones
        self.show_authorization_prompt()
        
        # Paso 3: Polling
        access_token_result = self.poll_for_access_token()
        if not access_token_result:
            print(f"[ERROR] No se pudo obtener access_token")
            return False
        
        # Paso 4: Intercambio
        copilot_token_result = self.exchange_for_copilot_token()
        if not copilot_token_result:
            print(f"[ERROR] No se pudo obtener token Copilot")
            return False
        
        # Paso 5: Guardar
        if not self.save_token():
            print(f"[ERROR] No se pudo guardar token")
            return False
        
        print(f"\n{'='*100}")
        print(f"✅ AUTENTICACIÓN COMPLETADA")
        print(f"{'='*100}\n")
        
        return True

    def load_token(self) -> Optional[Dict]:
        """Carga token guardado"""
        try:
            if self.token_file.exists():
                with open(self.token_file, 'r') as f:
                    token_data = json.load(f)
                
                self.copilot_token = token_data.get("copilot_token")
                self.access_token = token_data.get("access_token")
                
                print(f"[OK] Token cargado desde {self.token_file}")
                return token_data
            else:
                print(f"[!] No hay token guardado")
                return None
        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    def get_summary(self) -> Dict:
        """Resumen del estado"""
        return {
            'name': self.name,
            'version': self.version,
            'authenticated': self.copilot_token is not None,
            'token_file': str(self.token_file),
            'status': 'AUTHENTICATED' if self.copilot_token else 'NOT_AUTHENTICATED'
        }


# Singleton
_flow: Optional[CopilotDeviceFlow] = None


def get_copilot_device_flow() -> CopilotDeviceFlow:
    global _flow
    if _flow is None:
        _flow = CopilotDeviceFlow()
    return _flow


if __name__ == "__main__":
    flow = get_copilot_device_flow()
    
    # Intentar cargar token existente
    print(f"\n[*] Verificando token existente...")
    token = flow.load_token()
    
    if token:
        print(f"[OK] Token válido encontrado")
    else:
        print(f"[*] Iniciando autenticación...")
        
        if flow.authenticate():
            print(f"\n[OK] ✅ Autenticación exitosa")
        else:
            print(f"\n[ERROR] ❌ Autenticación fallida")
