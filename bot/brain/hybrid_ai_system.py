"""
ðŸ§  SISTEMA HÃBRIDO DE IA
Combina predictor local + IA opcional
- Funciona 100% sin IA (predictor local)
- Opcionalmente usa OpenAI o Anthropic si hay token
"""
import json
import time
from typing import Dict, List, Optional
from pathlib import Path

from .local_ai_predictor import get_local_ai_predictor
from .incoherence_detector import get_incoherence_detector


class HybridAISystem:
    """
    Sistema hÃ­brido que funciona con o sin IA
    """

    def __init__(self, openai_token: Optional[str] = None, anthropic_token: Optional[str] = None):
        self.name = "Hybrid AI System v1.0"
        self.version = "1.0"
        
        # Componentes locales (siempre funcionan)
        self.predictor = get_local_ai_predictor()
        self.detector = get_incoherence_detector()
        
        # Tokens opcionales
        self.openai_token = openai_token
        self.anthropic_token = anthropic_token
        
        # Estado
        self.has_openai = openai_token is not None
        self.has_anthropic = anthropic_token is not None
        self.ai_available = self.has_openai or self.has_anthropic
        
        print(f"[OK] {self.name} inicializado")
        print(f"    Predictor local: âœ“ (siempre disponible)")
        print(f"    OpenAI: {'âœ“' if self.has_openai else 'âœ—'}")
        print(f"    Anthropic: {'âœ“' if self.has_anthropic else 'âœ—'}")

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # ANÃLISIS CON PREDICTOR LOCAL (SIEMPRE FUNCIONA)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def analyze_with_local_predictor(self, market_context: Dict) -> Dict:
        """
        AnÃ¡lisis usando predictor local
        Funciona 100% sin IA
        """
        
        print(f"\n[*] Analizando con predictor local...")
        
        # Obtener predicciÃ³n
        prediction = self.predictor.predict_next_move(market_context)
        
        # Detectar incoherencias
        incoherences = self.detector.detect_all_incoherences()
        
        analysis = {
            'timestamp': time.time(),
            'method': 'local_predictor',
            'prediction': prediction,
            'incoherences_detected': len(incoherences),
            'status': 'success'
        }
        
        print(f"[OK] AnÃ¡lisis completado")
        print(f"    DirecciÃ³n: {prediction['direction']}")
        print(f"    Confianza: {prediction['confidence']:.0f}%")
        print(f"    Incoherencias: {len(incoherences)}")
        
        return analysis

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # ANÃLISIS CON IA (OPCIONAL)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def analyze_with_openai(self, prompt: str) -> Optional[str]:
        """
        AnÃ¡lisis usando OpenAI
        Requiere token de OpenAI
        """
        
        if not self.has_openai:
            print(f"[!] OpenAI no disponible")
            return None
        
        print(f"\n[*] Analizando con OpenAI...")
        
        try:
            import requests
            
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.openai_token}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "gpt-4-mini",
                "messages": [
                    {"role": "system", "content": "Eres un experto en trading de opciones binarias."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 500,
                "temperature": 0.7
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                print(f"[OK] Respuesta recibida")
                return content
            else:
                print(f"[!] Error {response.status_code}")
                return None
                
        except ImportError:
            print(f"[!] requests no instalado")
            return None
        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    def analyze_with_anthropic(self, prompt: str) -> Optional[str]:
        """
        AnÃ¡lisis usando Anthropic (Claude)
        Requiere token de Anthropic
        """
        
        if not self.has_anthropic:
            print(f"[!] Anthropic no disponible")
            return None
        
        print(f"\n[*] Analizando con Anthropic...")
        
        try:
            import requests
            
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": self.anthropic_token,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            
            data = {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 1024,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                content = result['content'][0]['text']
                print(f"[OK] Respuesta recibida")
                return content
            else:
                print(f"[!] Error {response.status_code}")
                return None
                
        except ImportError:
            print(f"[!] requests no instalado")
            return None
        except Exception as e:
            print(f"[ERROR] {e}")
            return None

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # ANÃLISIS HÃBRIDO (LOCAL + IA OPCIONAL)
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def analyze_hybrid(self, market_context: Dict, use_ai: bool = False) -> Dict:
        """
        AnÃ¡lisis hÃ­brido
        Siempre usa predictor local
        Opcionalmente usa IA si estÃ¡ disponible
        """
        
        print(f"\n[*] AnÃ¡lisis hÃ­brido...")
        
        # Paso 1: AnÃ¡lisis local (siempre)
        local_analysis = self.analyze_with_local_predictor(market_context)
        
        # Paso 2: AnÃ¡lisis con IA (opcional)
        ai_analysis = None
        
        if use_ai and self.ai_available:
            prompt = f"""
Eres un trader experto. Analiza esta oportunidad:

Activo: {market_context.get('asset')}
RSI: {market_context.get('rsi')}
PatrÃ³n: {market_context.get('pattern')}
Zona: {market_context.get('zone_type')}

PredicciÃ³n local: {local_analysis['prediction']['direction']} ({local_analysis['prediction']['confidence']:.0f}%)

Â¿EstÃ¡s de acuerdo? Â¿Hay algo que cambiarÃ­as?
Responde en JSON: {{"direction": "CALL/PUT", "confidence": 0-100, "reasoning": "..."}}
"""
            
            if self.has_openai:
                ai_response = self.analyze_with_openai(prompt)
            elif self.has_anthropic:
                ai_response = self.analyze_with_anthropic(prompt)
            else:
                ai_response = None
            
            if ai_response:
                try:
                    ai_analysis = json.loads(ai_response)
                except:
                    ai_analysis = {"raw_response": ai_response}
        
        # Paso 3: Combinar resultados
        result = {
            'timestamp': time.time(),
            'local_analysis': local_analysis,
            'ai_analysis': ai_analysis,
            'final_direction': ai_analysis.get('direction') if ai_analysis else local_analysis['prediction']['direction'],
            'final_confidence': ai_analysis.get('confidence', local_analysis['prediction']['confidence']) if ai_analysis else local_analysis['prediction']['confidence'],
            'method': 'hybrid_with_ai' if ai_analysis else 'local_only'
        }
        
        return result

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # UTILIDADES
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_status(self) -> Dict:
        """Estado del sistema"""
        return {
            'name': self.name,
            'version': self.version,
            'local_predictor': 'available',
            'openai': 'available' if self.has_openai else 'not_available',
            'anthropic': 'available' if self.has_anthropic else 'not_available',
            'ai_available': self.ai_available,
            'status': 'ACTIVE'
        }

    def get_summary(self) -> str:
        """Resumen del sistema"""
        
        summary = f"""
â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—
â•‘                    ðŸ§  SISTEMA HÃBRIDO DE IA                                   â•‘
â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

ðŸ“Š COMPONENTES:

  âœ“ Predictor Local
    - Funciona 100% sin IA
    - AnÃ¡lisis de 42 trades histÃ³ricos
    - Reglas aprendidas
    - DetecciÃ³n de incoherencias

  {'âœ“' if self.has_openai else 'âœ—'} OpenAI (ChatGPT 4 Mini)
    - Requiere token de OpenAI
    - AnÃ¡lisis rÃ¡pido
    - PredicciÃ³n

  {'âœ“' if self.has_anthropic else 'âœ—'} Anthropic (Claude 3.5 Sonnet)
    - Requiere token de Anthropic
    - AnÃ¡lisis profundo
    - DetecciÃ³n de patrones

ðŸŽ¯ MODO DE OPERACIÃ“N:

  1. Siempre usa predictor local (funciona sin IA)
  2. Opcionalmente usa IA si estÃ¡ disponible
  3. Combina resultados para decisiÃ³n final

ðŸ“ˆ VENTAJAS:

  âœ“ Funciona sin IA (predictor local)
  âœ“ Mejora con IA si estÃ¡ disponible
  âœ“ Flexible y adaptable
  âœ“ Sin dependencias externas

{'='*80}
"""
        
        return summary


# Singleton
_system: Optional[HybridAISystem] = None


def get_hybrid_ai_system(openai_token: Optional[str] = None, anthropic_token: Optional[str] = None) -> HybridAISystem:
    global _system
    if _system is None:
        _system = HybridAISystem(openai_token, anthropic_token)
    return _system


if __name__ == "__main__":
    # Crear sistema sin IA (solo predictor local)
    system = get_hybrid_ai_system()
    
    print(system.get_summary())
    
    # Ejemplo de anÃ¡lisis
    market_context = {
        'asset': 'EURJPY-OTC',
        'price': 150.5,
        'rsi': 25,
        'trend': 'DOWN',
        'pattern': 'pin_bar_bullish',
        'zone_type': 'support',
        'zone': 150.0
    }
    
    print("\n[*] Analizando oportunidad...")
    result = system.analyze_hybrid(market_context, use_ai=False)
    
    print(f"\nResultado:")
    print(f"  DirecciÃ³n: {result['final_direction']}")
    print(f"  Confianza: {result['final_confidence']:.0f}%")
    print(f"  MÃ©todo: {result['method']}")

