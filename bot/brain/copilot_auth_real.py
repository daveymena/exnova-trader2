"""
🔐 AUTENTICACIÓN REAL CON GITHUB COPILOT
Usa token de GitHub para acceder a modelos gratis:
- ChatGPT 4 Mini
- Claude 3.5 Sonnet
"""
import json
import os
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path


class CopilotAuthReal:
    """
    Autenticación real con GitHub Copilot
    Usa token de GitHub para acceder a modelos gratis
    """

    def __init__(self, github_token: str):
        self.name = "Copilot Auth Real v1.0"
        self.version = "1.0"
        self.github_token = github_token
        
        # Modelos disponibles (GRATIS)
        self.available_models = {
            'gpt-4-mini': {
                'name': 'ChatGPT 4 Mini',
                'provider': 'OpenAI',
                'use_case': 'Análisis rápido y predicción',
                'max_tokens': 4096,
                'cost': 'GRATIS'
            },
            'claude-3.5-sonnet': {
                'name': 'Claude 3.5 Sonnet',
                'provider': 'Anthropic',
                'use_case': 'Análisis profundo y detección de incoherencias',
                'max_tokens': 8192,
                'cost': 'GRATIS'
            }
        }
        
        # Estado
        self.authenticated = False
        self.token_valid = False
        self.user_info = None
        
        print(f"[OK] {self.name} inicializado")
        print(f"    Token: {github_token[:20]}...")
        print(f"    Modelos disponibles: {len(self.available_models)}")

    # ═══════════════════════════════════════════════════════════════════════════════
    # VERIFICACIÓN DE TOKEN
    # ═══════════════════════════════════════════════════════════════════════════════

    def verify_token(self) -> bool:
        """
        Verifica que el token de GitHub sea válido
        """
        print(f"\n[*] Verificando token de GitHub...")
        
        try:
            import requests
            
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            response = requests.get("https://api.github.com/user", headers=headers, timeout=10)
            
            if response.status_code == 200:
                self.user_info = response.json()
                self.token_valid = True
                self.authenticated = True
                
                print(f"[OK] Token válido")
                print(f"    Usuario: {self.user_info.get('login')}")
                print(f"    Nombre: {self.user_info.get('name')}")
                
                return True
            else:
                print(f"[ERROR] Token inválido (status {response.status_code})")
                return False
                
        except ImportError:
            print(f"[!] requests no instalado - usando verificación local")
            # Verificación básica: token debe tener formato correcto
            if self.github_token.startswith('ghp_') and len(self.github_token) > 30:
                self.token_valid = True
                self.authenticated = True
                print(f"[OK] Token tiene formato válido")
                return True
            else:
                print(f"[ERROR] Token no tiene formato válido")
                return False
        except Exception as e:
            print(f"[ERROR] Error verificando token: {e}")
            return False

    # ═══════════════════════════════════════════════════════════════════════════════
    # LLAMADAS A MODELOS
    # ═══════════════════════════════════════════════════════════════════════════════

    def call_gpt4_mini(self, prompt: str, system_prompt: str = None) -> Optional[str]:
        """
        Llama a ChatGPT 4 Mini
        """
        if not self.authenticated:
            print(f"[ERROR] No autenticado")
            return None
        
        print(f"\n[*] Llamando a ChatGPT 4 Mini...")
        
        try:
            import requests
            
            # Endpoint de GitHub Copilot para modelos
            url = "https://api.github.com/copilot/completions"
            
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28"
            }
            
            data = {
                "model": "gpt-4-mini",
                "messages": [
                    {"role": "system", "content": system_prompt or "Eres un experto en trading de opciones binarias."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 4096,
                "temperature": 0.7
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    content = result['choices'][0].get('message', {}).get('content', '')
                    print(f"[OK] Respuesta recibida ({len(content)} caracteres)")
                    return content
            else:
                print(f"[!] Error {response.status_code}: {response.text[:200]}")
                return None
                
        except ImportError:
            print(f"[!] requests no instalado")
            return None
        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    def call_claude_sonnet(self, prompt: str, system_prompt: str = None) -> Optional[str]:
        """
        Llama a Claude 3.5 Sonnet
        """
        if not self.authenticated:
            print(f"[ERROR] No autenticado")
            return None
        
        print(f"\n[*] Llamando a Claude 3.5 Sonnet...")
        
        try:
            import requests
            
            # Endpoint de GitHub Copilot para modelos
            url = "https://api.github.com/copilot/completions"
            
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28"
            }
            
            data = {
                "model": "claude-3.5-sonnet",
                "messages": [
                    {"role": "system", "content": system_prompt or "Eres un experto en trading de opciones binarias."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 8192,
                "temperature": 0.7
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    content = result['choices'][0].get('message', {}).get('content', '')
                    print(f"[OK] Respuesta recibida ({len(content)} caracteres)")
                    return content
            else:
                print(f"[!] Error {response.status_code}: {response.text[:200]}")
                return None
                
        except ImportError:
            print(f"[!] requests no instalado")
            return None
        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════════════════
    # UTILIDADES
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_available_models(self) -> Dict:
        """Lista modelos disponibles"""
        return self.available_models

    def get_status(self) -> Dict:
        """Estado de autenticación"""
        return {
            'name': self.name,
            'version': self.version,
            'authenticated': self.authenticated,
            'token_valid': self.token_valid,
            'user': self.user_info.get('login') if self.user_info else None,
            'models_available': len(self.available_models),
            'models': list(self.available_models.keys())
        }

    def get_summary(self) -> str:
        """Resumen de autenticación"""
        status = self.get_status()
        
        summary = f"""
╔════════════════════════════════════════════════════════════════════════════════╗
║                    🔐 AUTENTICACIÓN GITHUB COPILOT                            ║
╚════════════════════════════════════════════════════════════════════════════════╝

✅ ESTADO:
  • Autenticado: {'Sí' if status['authenticated'] else 'No'}
  • Token válido: {'Sí' if status['token_valid'] else 'No'}
  • Usuario: {status['user'] or 'N/A'}

🤖 MODELOS DISPONIBLES (GRATIS):
"""
        
        for model_id, model_info in self.available_models.items():
            summary += f"""
  • {model_info['name']}
    - ID: {model_id}
    - Proveedor: {model_info['provider']}
    - Uso: {model_info['use_case']}
    - Max tokens: {model_info['max_tokens']}
    - Costo: {model_info['cost']}
"""
        
        summary += f"""
{'='*80}
"""
        
        return summary


# Singleton
_auth: Optional[CopilotAuthReal] = None


def get_copilot_auth_real(github_token: str) -> CopilotAuthReal:
    global _auth
    if _auth is None:
        _auth = CopilotAuthReal(github_token)
    return _auth


if __name__ == "__main__":
    # Usar token de variable de entorno
    token = os.environ.get("GITHUB_TOKEN", "")
    
    auth = get_copilot_auth_real(token)
    
    # Verificar token
    if auth.verify_token():
        print(auth.get_summary())
    else:
        print("[ERROR] No se pudo autenticar")
