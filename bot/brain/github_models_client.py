"""
🔗 CLIENTE GITHUB MODELS - CORRECTO
Acceso a modelos de GitHub Models vía REST API
Endpoint correcto: https://models.github.ai/
Autenticación: Token de GitHub con scope models:read
"""
import json
import requests
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path


class GitHubModelsClient:
    """
    Cliente para GitHub Models
    Acceso a ChatGPT 4 Mini, Claude 3.5 Sonnet y otros modelos
    """

    def __init__(self, github_token: str):
        self.name = "GitHub Models Client v1.0"
        self.version = "1.0"
        self.github_token = github_token
        
        # Endpoint correcto de GitHub Models
        self.base_url = "https://models.github.ai"
        self.catalog_url = f"{self.base_url}/catalog/models"
        self.inference_url = f"{self.base_url}/inference/chat/completions"
        
        # Headers
        self.headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2026-03-10"
        }
        
        # Modelos disponibles (se cargan dinámicamente)
        self.available_models = {}
        self.models_loaded = False
        
        # Historial
        self.api_calls = []
        self.responses = []
        
        print(f"[OK] {self.name} inicializado")
        print(f"    Token: {github_token[:20]}...")
        print(f"    Endpoint: {self.base_url}")

    # ═══════════════════════════════════════════════════════════════════════════════
    # CARGAR MODELOS DISPONIBLES
    # ═══════════════════════════════════════════════════════════════════════════════

    def load_available_models(self) -> Dict:
        """
        Carga lista de modelos disponibles desde GitHub Models
        """
        print(f"\n[*] Cargando modelos disponibles...")
        
        try:
            response = requests.get(
                self.catalog_url,
                headers=self.headers,
                timeout=30
            )
            
            if response.status_code == 200:
                models = response.json()
                
                # Procesar modelos
                for model in models:
                    model_id = model.get('id')
                    self.available_models[model_id] = {
                        'name': model.get('name'),
                        'publisher': model.get('publisher'),
                        'summary': model.get('summary'),
                        'capabilities': model.get('capabilities', []),
                        'limits': model.get('limits', {}),
                        'rate_limit_tier': model.get('rate_limit_tier'),
                        'supported_input_modalities': model.get('supported_input_modalities', []),
                        'supported_output_modalities': model.get('supported_output_modalities', []),
                        'tags': model.get('tags', [])
                    }
                
                self.models_loaded = True
                
                print(f"[OK] {len(self.available_models)} modelos cargados")
                
                # Mostrar modelos disponibles
                self._print_available_models()
                
                return self.available_models
            
            else:
                print(f"[ERROR] Error {response.status_code} cargando modelos")
                print(f"    {response.text[:200]}")
                return {}
        
        except Exception as e:
            print(f"[ERROR] Error cargando modelos: {e}")
            return {}

    def _print_available_models(self) -> None:
        """Imprime modelos disponibles"""
        print(f"\n* MODELOS DISPONIBLES:")
        
        for model_id, model_info in self.available_models.items():
            print(f"\n  - {model_id}")
            print(f"    Nombre: {model_info['name']}")
            print(f"    Publisher: {model_info['publisher']}")
            print(f"    Tier: {model_info['rate_limit_tier']}")
            print(f"    Capacidades: {', '.join(model_info['capabilities'])}")
            print(f"    Entrada: {', '.join(model_info['supported_input_modalities'])}")
            print(f"    Salida: {', '.join(model_info['supported_output_modalities'])}")

    # ═══════════════════════════════════════════════════════════════════════════════
    # LLAMADAS A MODELOS
    # ═══════════════════════════════════════════════════════════════════════════════

    def call_model(
        self,
        model_id: str,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 4000,
        stream: bool = False
    ) -> Optional[Dict]:
        """
        Llama a un modelo de GitHub Models
        
        Args:
            model_id: ID del modelo (ej: "openai/gpt-4-mini" o "anthropic/claude-3.5-sonnet")
            messages: Lista de mensajes [{"role": "user", "content": "..."}]
            temperature: Creatividad (0-1)
            max_tokens: Máximo de tokens en respuesta
            stream: Si usar streaming
        
        Returns:
            Dict con respuesta del modelo
        """
        
        print(f"\n[*] Llamando a {model_id}...")
        
        # Validar modelo
        if model_id not in self.available_models and not self.models_loaded:
            print(f"[!] Modelo no cargado. Cargando catálogo...")
            self.load_available_models()
        
        if model_id not in self.available_models:
            print(f"[ERROR] Modelo {model_id} no disponible")
            print(f"    Modelos disponibles: {list(self.available_models.keys())}")
            return None
        
        # Preparar payload
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }
        
        try:
            # Hacer llamada
            start_time = time.time()
            
            response = requests.post(
                self.inference_url,
                headers=self.headers,
                json=payload,
                timeout=60
            )
            
            elapsed = time.time() - start_time
            
            # Registrar llamada
            self.api_calls.append({
                'timestamp': datetime.now().isoformat(),
                'model': model_id,
                'status_code': response.status_code,
                'elapsed_seconds': elapsed,
                'tokens_in': self._count_tokens(messages),
                'tokens_out': max_tokens
            })
            
            if response.status_code == 200:
                result = response.json()
                
                # Extraer respuesta
                if 'choices' in result and len(result['choices']) > 0:
                    message = result['choices'][0].get('message', {})
                    content = message.get('content', '')
                    
                    response_data = {
                        'model': model_id,
                        'content': content,
                        'role': message.get('role', 'assistant'),
                        'timestamp': datetime.now().isoformat(),
                        'elapsed_seconds': elapsed,
                        'status': 'success'
                    }
                    
                    self.responses.append(response_data)
                    
                    print(f"[OK] Respuesta recibida en {elapsed:.2f}s")
                    print(f"    Contenido: {content[:100]}...")
                    
                    return response_data
                else:
                    print(f"[ERROR] Respuesta vacía del modelo")
                    return None
            
            else:
                print(f"[ERROR] Error {response.status_code}")
                print(f"    {response.text[:300]}")
                return None
        
        except Exception as e:
            print(f"[ERROR] Error llamando modelo: {e}")
            return None

    def call_gpt4_mini(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """
        Llama a GPT-4 Mini (ChatGPT 4 Mini)
        Disponible en GitHub Models como openai/gpt-4.1-mini
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        # Buscar modelo GPT-4 Mini
        gpt4_mini_id = None
        for model_id in self.available_models.keys():
            if 'gpt-4' in model_id.lower() and 'mini' in model_id.lower():
                gpt4_mini_id = model_id
                break
        
        if not gpt4_mini_id:
            print(f"[!] GPT-4 Mini no encontrado. Buscando alternativa...")
            for model_id in self.available_models.keys():
                if 'gpt-4' in model_id.lower():
                    gpt4_mini_id = model_id
                    break
        
        if not gpt4_mini_id:
            print(f"[ERROR] No se encontró modelo GPT-4")
            return None
        
        result = self.call_model(gpt4_mini_id, messages, temperature=0.7, max_tokens=2000)
        
        if result:
            return result['content']
        return None

    def call_claude_sonnet(self, prompt: str, system_prompt: Optional[str] = None) -> Optional[str]:
        """
        Llama a Claude 3.5 Sonnet
        NOTA: Claude NO está disponible en GitHub Models
        Usamos Llama 3.3 70B como alternativa (similar capacidad)
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        # Buscar modelo alternativo (Llama 3.3 70B es muy bueno)
        model_id = None
        
        # Preferencia: Llama 3.3 70B (similar a Claude Sonnet)
        for mid in self.available_models.keys():
            if 'llama-3.3-70b' in mid.lower():
                model_id = mid
                break
        
        # Alternativa: Mistral Large
        if not model_id:
            for mid in self.available_models.keys():
                if 'mistral' in mid.lower() and 'large' in mid.lower():
                    model_id = mid
                    break
        
        # Alternativa: Cualquier modelo de tier alto
        if not model_id:
            for mid, info in self.available_models.items():
                if info.get('rate_limit_tier') == 'high':
                    model_id = mid
                    break
        
        if not model_id:
            print(f"[ERROR] No se encontró modelo alternativo a Claude")
            return None
        
        print(f"[*] Usando {model_id} como alternativa a Claude Sonnet")
        
        result = self.call_model(model_id, messages, temperature=0.7, max_tokens=2000)
        
        if result:
            return result['content']
        return None

    # ═══════════════════════════════════════════════════════════════════════════════
    # UTILIDADES
    # ═══════════════════════════════════════════════════════════════════════════════

    def _count_tokens(self, messages: List[Dict]) -> int:
        """Estimación aproximada de tokens"""
        total = 0
        for msg in messages:
            content = msg.get('content', '')
            # Aproximación: 1 token ≈ 4 caracteres
            total += len(content) // 4
        return total

    def get_api_usage(self) -> Dict:
        """Obtiene estadísticas de uso"""
        return {
            'total_calls': len(self.api_calls),
            'total_responses': len(self.responses),
            'models_available': len(self.available_models),
            'api_calls': self.api_calls[-10:],  # Últimas 10 llamadas
            'responses': self.responses[-10:]   # Últimas 10 respuestas
        }

    def get_summary(self) -> Dict:
        """Resumen del cliente"""
        return {
            'name': self.name,
            'version': self.version,
            'endpoint': self.base_url,
            'models_loaded': self.models_loaded,
            'models_available': len(self.available_models),
            'api_calls': len(self.api_calls),
            'status': 'READY' if self.models_loaded else 'INITIALIZING'
        }


# Singleton
_client: Optional[GitHubModelsClient] = None


def get_github_models_client(github_token: str) -> GitHubModelsClient:
    global _client
    if _client is None:
        _client = GitHubModelsClient(github_token)
    return _client
