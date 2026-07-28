"""
🤖 ACCESO DIRECTO A MODELOS
ChatGPT 4 Mini y Claude 3.5 Sonnet
Sin pasar por GitHub API
"""
import json
import time
from typing import Dict, Optional


class DirectModelsAccess:
    """
    Acceso directo a modelos
    - ChatGPT 4 Mini (OpenAI)
    - Claude 3.5 Sonnet (Anthropic)
    """

    def __init__(self):
        self.name = "Direct Models Access v1.0"
        self.version = "1.0"
        
        # Modelos disponibles
        self.models = {
            'gpt-4-mini': {
                'name': 'ChatGPT 4 Mini',
                'provider': 'OpenAI',
                'use_case': 'Análisis rápido y predicción',
                'max_tokens': 4096,
                'endpoint': 'https://api.openai.com/v1/chat/completions',
                'requires': 'OPENAI_API_KEY'
            },
            'claude-3.5-sonnet': {
                'name': 'Claude 3.5 Sonnet',
                'provider': 'Anthropic',
                'use_case': 'Análisis profundo',
                'max_tokens': 8192,
                'endpoint': 'https://api.anthropic.com/v1/messages',
                'requires': 'ANTHROPIC_API_KEY'
            }
        }
        
        # Historial
        self.calls = []
        self.responses = []
        
        print(f"[OK] {self.name} inicializado")
        print(f"    Modelos: {len(self.models)}")

    # ═══════════════════════════════════════════════════════════════════════════════
    # ACCESO A MODELOS
    # ═══════════════════════════════════════════════════════════════════════════════

    def call_gpt4_mini(self, prompt: str, api_key: str = None) -> Optional[str]:
        """
        Llama a ChatGPT 4 Mini
        Requiere: OPENAI_API_KEY
        """
        
        if not api_key:
            import os
            api_key = os.getenv('OPENAI_API_KEY')
        
        if not api_key:
            print(f"[ERROR] OPENAI_API_KEY no configurada")
            print(f"        Configura: export OPENAI_API_KEY=sk-...")
            return None
        
        print(f"\n[*] Llamando a ChatGPT 4 Mini...")
        
        try:
            import requests
            
            url = "https://api.openai.com/v1/chat/completions"
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "gpt-4-mini",
                "messages": [
                    {"role": "system", "content": "Eres un experto en trading de opciones binarias."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 4096,
                "temperature": 0.7
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                
                if 'choices' in result and len(result['choices']) > 0:
                    content = result['choices'][0]['message']['content']
                    
                    self.calls.append({
                        'timestamp': time.time(),
                        'model': 'gpt-4-mini',
                        'status': 'success'
                    })
                    
                    print(f"[OK] Respuesta recibida")
                    return content
            else:
                print(f"[!] Error {response.status_code}")
                print(f"    {response.text[:200]}")
                
                self.calls.append({
                    'timestamp': time.time(),
                    'model': 'gpt-4-mini',
                    'status': 'error',
                    'error_code': response.status_code
                })
                
                return None
                
        except ImportError:
            print(f"[!] requests no instalado")
            return None
        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    def call_claude_sonnet(self, prompt: str, api_key: str = None) -> Optional[str]:
        """
        Llama a Claude 3.5 Sonnet
        Requiere: ANTHROPIC_API_KEY
        """
        
        if not api_key:
            import os
            api_key = os.getenv('ANTHROPIC_API_KEY')
        
        if not api_key:
            print(f"[ERROR] ANTHROPIC_API_KEY no configurada")
            print(f"        Configura: export ANTHROPIC_API_KEY=sk-ant-...")
            return None
        
        print(f"\n[*] Llamando a Claude 3.5 Sonnet...")
        
        try:
            import requests
            
            url = "https://api.anthropic.com/v1/messages"
            
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            
            data = {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 8192,
                "system": "Eres un experto en trading de opciones binarias.",
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                
                if 'content' in result and len(result['content']) > 0:
                    content = result['content'][0]['text']
                    
                    self.calls.append({
                        'timestamp': time.time(),
                        'model': 'claude-3.5-sonnet',
                        'status': 'success'
                    })
                    
                    print(f"[OK] Respuesta recibida")
                    return content
            else:
                print(f"[!] Error {response.status_code}")
                print(f"    {response.text[:200]}")
                
                self.calls.append({
                    'timestamp': time.time(),
                    'model': 'claude-3.5-sonnet',
                    'status': 'error',
                    'error_code': response.status_code
                })
                
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
        return self.models

    def get_usage_stats(self) -> Dict:
        """Estadísticas de uso"""
        return {
            'total_calls': len(self.calls),
            'successful_calls': len([c for c in self.calls if c['status'] == 'success']),
            'failed_calls': len([c for c in self.calls if c['status'] == 'error'])
        }

    def get_summary(self) -> Dict:
        """Resumen"""
        return {
            'name': self.name,
            'version': self.version,
            'models_available': len(self.models),
            'models': list(self.models.keys()),
            'usage': self.get_usage_stats(),
            'status': 'ACTIVE'
        }


# Singleton
_access: Optional[DirectModelsAccess] = None


def get_direct_models_access() -> DirectModelsAccess:
    global _access
    if _access is None:
        _access = DirectModelsAccess()
    return _access


if __name__ == "__main__":
    import os
    
    print(f"\n{'='*100}")
    print(f"🤖 ACCESO DIRECTO A MODELOS")
    print(f"{'='*100}\n")
    
    access = get_direct_models_access()
    
    # Mostrar modelos
    print("Modelos disponibles:\n")
    
    for model_id, model_info in access.get_available_models().items():
        print(f"• {model_info['name']}")
        print(f"  ID: {model_id}")
        print(f"  Proveedor: {model_info['provider']}")
        print(f"  Requiere: {model_info['requires']}\n")
    
    # Verificar variables de entorno
    print("Variables de entorno:\n")
    
    openai_key = os.getenv('OPENAI_API_KEY')
    anthropic_key = os.getenv('ANTHROPIC_API_KEY')
    
    print(f"OPENAI_API_KEY: {'✓ Configurada' if openai_key else '✗ No configurada'}")
    print(f"ANTHROPIC_API_KEY: {'✓ Configurada' if anthropic_key else '✗ No configurada'}\n")
    
    if not openai_key and not anthropic_key:
        print("Para usar los modelos, configura las variables de entorno:")
        print("\n  OpenAI:")
        print("    export OPENAI_API_KEY=sk-...")
        print("    https://platform.openai.com/api-keys")
        print("\n  Anthropic:")
        print("    export ANTHROPIC_API_KEY=sk-ant-...")
        print("    https://console.anthropic.com/")
