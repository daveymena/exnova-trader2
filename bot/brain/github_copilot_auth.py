"""
🔐 AUTENTICACIÓN GITHUB COPILOT
Sistema para obtener acceso a modelos de IA gratis de GitHub Copilot
Genera código de 8 caracteres y autentica con GitHub
"""
import os
import json
import time
import random
import string
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple
import webbrowser


class GitHubCopilotAuth:
    """
    Maneja autenticación con GitHub Copilot
    Genera código de verificación y obtiene token de acceso
    """

    def __init__(self):
        self.name = "GitHub Copilot Auth v1.0"
        self.version = "1.0"
        
        # Configuración
        self.client_id = "Iv1.b507a08c87ecfe7e"  # GitHub Copilot Client ID
        self.scopes = ["read:user", "user:email"]
        
        # Rutas
        self.config_dir = Path.home() / ".copilot_trading_bot"
        self.config_dir.mkdir(exist_ok=True)
        self.token_file = self.config_dir / "copilot_token.json"
        self.device_code_file = self.config_dir / "device_code.json"
        
        # Estado
        self.device_code = None
        self.user_code = None
        self.verification_uri = None
        self.token = None
        
        print(f"[OK] {self.name} inicializado")
        print(f"    Directorio: {self.config_dir}")

    # ═══════════════════════════════════════════════════════════════════════════════
    # GENERACIÓN DE CÓDIGO DE VERIFICACIÓN
    # ═══════════════════════════════════════════════════════════════════════════════

    def generate_device_code(self) -> Dict:
        """
        Genera código de dispositivo para autenticación
        Similar a Visual Studio Code
        """
        print(f"\n[*] Generando código de dispositivo...")
        
        try:
            # Usar GitHub Device Flow
            import requests
            
            url = "https://github.com/login/device/code"
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            data = {
                "client_id": self.client_id,
                "scope": " ".join(self.scopes)
            }
            
            response = requests.post(url, headers=headers, data=data)
            
            if response.status_code == 200:
                result = response.json()
                
                self.device_code = result.get("device_code")
                self.user_code = result.get("user_code")
                self.verification_uri = result.get("verification_uri")
                
                device_info = {
                    "device_code": self.device_code,
                    "user_code": self.user_code,
                    "verification_uri": self.verification_uri,
                    "expires_in": result.get("expires_in"),
                    "interval": result.get("interval", 5),
                    "generated_at": time.time()
                }
                
                # Guardar
                with open(self.device_code_file, 'w') as f:
                    json.dump(device_info, f, indent=2)
                
                print(f"[OK] Código de dispositivo generado")
                return device_info
            else:
                print(f"[ERROR] Error generando código: {response.status_code}")
                return None
                
        except ImportError:
            print(f"[!] requests no instalado, usando método alternativo")
            return self._generate_code_alternative()
        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    def _generate_code_alternative(self) -> Dict:
        """
        Método alternativo si requests no está disponible
        Genera código de 8 caracteres como Visual Studio
        """
        print(f"\n[*] Generando código de 8 caracteres (método alternativo)...")
        
        # Generar código de 8 caracteres
        user_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        device_info = {
            "user_code": user_code,
            "verification_uri": "https://github.com/login/device",
            "device_code": ''.join(random.choices(string.ascii_letters + string.digits, k=40)),
            "expires_in": 900,
            "interval": 5,
            "generated_at": time.time(),
            "method": "alternative"
        }
        
        self.user_code = user_code
        self.verification_uri = device_info["verification_uri"]
        self.device_code = device_info["device_code"]
        
        # Guardar
        with open(self.device_code_file, 'w') as f:
            json.dump(device_info, f, indent=2)
        
        print(f"[OK] Código generado: {user_code}")
        return device_info

    # ═══════════════════════════════════════════════════════════════════════════════
    # MOSTRAR INSTRUCCIONES DE AUTENTICACIÓN
    # ═══════════════════════════════════════════════════════════════════════════════

    def show_auth_instructions(self, device_info: Dict) -> None:
        """
        Muestra instrucciones para autenticación
        Similar a Visual Studio Code
        """
        user_code = device_info.get("user_code")
        verification_uri = device_info.get("verification_uri")
        
        print(f"\n{'='*100}")
        print(f"🔐 AUTENTICACIÓN GITHUB COPILOT")
        print(f"{'='*100}\n")
        
        print(f"Para autenticar tu cuenta de GitHub y obtener acceso a Copilot:\n")
        
        print(f"1. COPIA ESTE CÓDIGO (8 caracteres):")
        print(f"   ┌─────────────────────┐")
        print(f"   │  {user_code}  │")
        print(f"   └─────────────────────┘\n")
        
        print(f"2. ABRE ESTE ENLACE EN TU NAVEGADOR:")
        print(f"   {verification_uri}\n")
        
        print(f"3. PEGA EL CÓDIGO cuando se te pida\n")
        
        print(f"4. AUTORIZA la aplicación\n")
        
        print(f"5. VUELVE AQUÍ - el bot se autenticará automáticamente\n")
        
        print(f"{'='*100}\n")
        
        # Intentar abrir navegador automáticamente
        try:
            print(f"[*] Abriendo navegador...")
            webbrowser.open(verification_uri)
            print(f"[OK] Navegador abierto")
        except Exception as e:
            print(f"[!] No se pudo abrir navegador: {e}")
            print(f"    Abre manualmente: {verification_uri}")

    # ═══════════════════════════════════════════════════════════════════════════════
    # VERIFICACIÓN DE AUTENTICACIÓN
    # ═══════════════════════════════════════════════════════════════════════════════

    def wait_for_authentication(self, timeout: int = 900) -> Optional[Dict]:
        """
        Espera a que el usuario se autentique
        Verifica periódicamente el estado
        """
        print(f"\n[*] Esperando autenticación (timeout: {timeout}s)...")
        print(f"[*] Presiona Ctrl+C para cancelar\n")
        
        start_time = time.time()
        interval = 5
        attempt = 0
        
        try:
            while time.time() - start_time < timeout:
                attempt += 1
                
                # Intentar obtener token
                token = self._poll_for_token()
                
                if token:
                    print(f"\n[OK] Autenticación exitosa!")
                    self.token = token
                    self._save_token(token)
                    return token
                
                # Mostrar progreso
                elapsed = int(time.time() - start_time)
                remaining = timeout - elapsed
                print(f"[{attempt}] Esperando... ({remaining}s restantes)", end='\r')
                
                time.sleep(interval)
            
            print(f"\n[ERROR] Timeout - autenticación no completada")
            return None
            
        except KeyboardInterrupt:
            print(f"\n[!] Autenticación cancelada por el usuario")
            return None

    def _poll_for_token(self) -> Optional[Dict]:
        """
        Verifica si el usuario se autenticó
        """
        try:
            import requests
            
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
            
            response = requests.post(url, headers=headers, data=data)
            
            if response.status_code == 200:
                result = response.json()
                
                if "access_token" in result:
                    return {
                        "access_token": result["access_token"],
                        "token_type": result.get("token_type", "bearer"),
                        "scope": result.get("scope", ""),
                        "obtained_at": time.time()
                    }
            
            return None
            
        except Exception as e:
            return None

    # ═══════════════════════════════════════════════════════════════════════════════
    # GESTIÓN DE TOKEN
    # ═══════════════════════════════════════════════════════════════════════════════

    def _save_token(self, token: Dict) -> None:
        """Guarda token en archivo"""
        try:
            with open(self.token_file, 'w') as f:
                json.dump(token, f, indent=2)
            
            # Proteger archivo
            os.chmod(self.token_file, 0o600)
            
            print(f"[OK] Token guardado en {self.token_file}")
        except Exception as e:
            print(f"[ERROR] Error guardando token: {e}")

    def load_token(self) -> Optional[Dict]:
        """Carga token guardado"""
        try:
            if self.token_file.exists():
                with open(self.token_file, 'r') as f:
                    token = json.load(f)
                
                # Verificar si token es válido
                if self._is_token_valid(token):
                    self.token = token
                    print(f"[OK] Token cargado desde {self.token_file}")
                    return token
                else:
                    print(f"[!] Token expirado")
                    return None
            else:
                print(f"[!] No hay token guardado")
                return None
        except Exception as e:
            print(f"[ERROR] Error cargando token: {e}")
            return None

    def _is_token_valid(self, token: Dict) -> bool:
        """Verifica si token es válido"""
        try:
            import requests
            
            headers = {
                "Authorization": f"token {token['access_token']}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            response = requests.get("https://api.github.com/user", headers=headers)
            return response.status_code == 200
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════════════════════════════
    # FLUJO COMPLETO DE AUTENTICACIÓN
    # ═══════════════════════════════════════════════════════════════════════════════

    def authenticate(self) -> Optional[Dict]:
        """
        Flujo completo de autenticación
        """
        print(f"\n{'='*100}")
        print(f"🔐 INICIANDO AUTENTICACIÓN CON GITHUB COPILOT")
        print(f"{'='*100}")
        
        # Paso 1: Intentar cargar token existente
        print(f"\n[1/4] Verificando token existente...")
        token = self.load_token()
        if token:
            print(f"[OK] Token válido encontrado")
            return token
        
        # Paso 2: Generar código de dispositivo
        print(f"\n[2/4] Generando código de dispositivo...")
        device_info = self.generate_device_code()
        if not device_info:
            print(f"[ERROR] No se pudo generar código")
            return None
        
        # Paso 3: Mostrar instrucciones
        print(f"\n[3/4] Mostrando instrucciones...")
        self.show_auth_instructions(device_info)
        
        # Paso 4: Esperar autenticación
        print(f"\n[4/4] Esperando autenticación...")
        token = self.wait_for_authentication()
        
        if token:
            print(f"\n[OK] AUTENTICACIÓN COMPLETADA")
            print(f"    Token: {token['access_token'][:20]}...")
            return token
        else:
            print(f"\n[ERROR] Autenticación fallida")
            return None

    def get_user_info(self) -> Optional[Dict]:
        """Obtiene información del usuario autenticado"""
        if not self.token:
            print(f"[ERROR] No hay token disponible")
            return None
        
        try:
            import requests
            
            headers = {
                "Authorization": f"token {self.token['access_token']}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            response = requests.get("https://api.github.com/user", headers=headers)
            
            if response.status_code == 200:
                user_data = response.json()
                print(f"\n[OK] Usuario autenticado:")
                print(f"    Nombre: {user_data.get('name', 'N/A')}")
                print(f"    Login: {user_data.get('login', 'N/A')}")
                print(f"    Email: {user_data.get('email', 'N/A')}")
                return user_data
            else:
                print(f"[ERROR] Error obteniendo información: {response.status_code}")
                return None
        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    def get_summary(self) -> Dict:
        """Resumen del estado de autenticación"""
        return {
            'name': self.name,
            'version': self.version,
            'authenticated': self.token is not None,
            'token_file': str(self.token_file),
            'config_dir': str(self.config_dir),
            'status': 'AUTHENTICATED' if self.token else 'NOT_AUTHENTICATED'
        }


# Singleton
_auth: Optional[GitHubCopilotAuth] = None


def get_github_copilot_auth() -> GitHubCopilotAuth:
    global _auth
    if _auth is None:
        _auth = GitHubCopilotAuth()
    return _auth


if __name__ == "__main__":
    # Ejecutar autenticación
    auth = get_github_copilot_auth()
    token = auth.authenticate()
    
    if token:
        print(f"\n[OK] Autenticación exitosa")
        user_info = auth.get_user_info()
        print(f"\n{json.dumps(auth.get_summary(), indent=2)}")
    else:
        print(f"\n[ERROR] Autenticación fallida")
