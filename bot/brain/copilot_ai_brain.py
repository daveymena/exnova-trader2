"""
🧠 COPILOT AI BRAIN
Sistema de IA usando GitHub Copilot Models
Análisis profundo, predicción y optimización automática
"""
import json
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from github_copilot_auth import get_github_copilot_auth


class CopilotAIBrain:
    """
    Cerebro de IA usando GitHub Copilot
    Proporciona:
    1. Análisis profundo de operaciones
    2. Predicción de movimientos
    3. Generación de estrategias
    4. Optimización automática
    """

    def __init__(self):
        self.name = "Copilot AI Brain v1.0"
        self.version = "1.0"
        
        # Autenticación
        self.auth = get_github_copilot_auth()
        self.token = None
        
        # Modelos disponibles
        self.available_models = [
            "gpt-4",
            "gpt-3.5-turbo",
            "claude-3-opus",
            "claude-3-sonnet",
        ]
        
        # Historial de análisis
        self.analysis_history = []
        self.predictions_history = []
        self.strategies_generated = []
        
        print(f"[OK] {self.name} inicializado")

    # ═══════════════════════════════════════════════════════════════════════════════
    # AUTENTICACIÓN
    # ═══════════════════════════════════════════════════════════════════════════════

    def authenticate(self) -> bool:
        """Autentica con GitHub Copilot"""
        print(f"\n[*] Autenticando con GitHub Copilot...")
        
        # Intentar cargar token existente
        token = self.auth.load_token()
        
        if not token:
            # Ejecutar flujo de autenticación
            token = self.auth.authenticate()
        
        if token:
            self.token = token
            print(f"[OK] Autenticación exitosa")
            return True
        else:
            print(f"[ERROR] Autenticación fallida")
            return False

    # ═══════════════════════════════════════════════════════════════════════════════
    # ANÁLISIS PROFUNDO CON IA
    # ═══════════════════════════════════════════════════════════════════════════════

    def analyze_trades_with_ai(self, trades: List[Dict]) -> Dict:
        """
        Análisis profundo de trades usando IA
        """
        print(f"\n[*] Analizando {len(trades)} trades con IA...")
        
        # Preparar datos
        wins = [t for t in trades if t['result'] == 'HOLD']
        losses = [t for t in trades if t['result'] == 'BREAK']
        
        # Crear prompt para IA
        prompt = self._create_analysis_prompt(wins, losses)
        
        # Obtener análisis de IA
        analysis = self._call_copilot_api(prompt, "analysis")
        
        if analysis:
            self.analysis_history.append({
                'timestamp': time.time(),
                'trades_count': len(trades),
                'analysis': analysis
            })
            return analysis
        else:
            return self._fallback_analysis(wins, losses)

    def _create_analysis_prompt(self, wins: List[Dict], losses: List[Dict]) -> str:
        """Crea prompt para análisis de IA"""
        
        # Estadísticas básicas
        wins_stats = {
            'count': len(wins),
            'avg_pnl': sum(w['pnl'] for w in wins) / len(wins) if wins else 0,
            'assets': list(set(w['asset'] for w in wins)),
            'patterns': list(set(w.get('pattern', 'none') for w in wins)),
        }
        
        losses_stats = {
            'count': len(losses),
            'avg_loss': sum(l['pnl'] for l in losses) / len(losses) if losses else 0,
            'assets': list(set(l['asset'] for l in losses)),
            'patterns': list(set(l.get('pattern', 'none') for l in losses)),
        }
        
        prompt = f"""
Eres un experto en trading de opciones binarias. Analiza estos datos de operaciones:

OPERACIONES GANADORAS ({wins_stats['count']}):
- PnL promedio: {wins_stats['avg_pnl']:.2f}
- Activos: {', '.join(wins_stats['assets'])}
- Patrones: {', '.join(wins_stats['patterns'])}

OPERACIONES PERDEDORAS ({losses_stats['count']}):
- Pérdida promedio: {losses_stats['avg_loss']:.2f}
- Activos: {', '.join(losses_stats['assets'])}
- Patrones: {', '.join(losses_stats['patterns'])}

TAREAS:
1. Identifica los 3 factores más importantes que hacen que una operación gane
2. Identifica los 3 factores más importantes que hacen que una operación pierda
3. Sugiere 5 reglas específicas para mejorar el win rate
4. Proporciona un score de confianza (0-100) para cada regla
5. Explica por qué cada regla funcionaría

Responde en JSON con estructura:
{{
    "winning_factors": [...],
    "losing_factors": [...],
    "improvement_rules": [...],
    "confidence_scores": [...],
    "explanations": [...]
}}
"""
        return prompt

    def _call_copilot_api(self, prompt: str, analysis_type: str) -> Optional[Dict]:
        """
        Llama a la API de Copilot
        """
        if not self.token:
            print(f"[!] No hay token de autenticación")
            return None
        
        try:
            import requests
            
            # Usar endpoint de GitHub Copilot
            url = "https://api.github.com/copilot/completions"
            
            headers = {
                "Authorization": f"token {self.token['access_token']}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            data = {
                "prompt": prompt,
                "max_tokens": 2000,
                "temperature": 0.7,
                "model": "gpt-4"
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                
                # Extraer respuesta
                if 'choices' in result and len(result['choices']) > 0:
                    completion = result['choices'][0].get('text', '')
                    
                    # Intentar parsear JSON
                    try:
                        return json.loads(completion)
                    except:
                        return {'raw_response': completion}
            else:
                print(f"[!] Error API: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"[!] Error llamando API: {e}")
            return None

    def _fallback_analysis(self, wins: List[Dict], losses: List[Dict]) -> Dict:
        """Análisis fallback si IA no está disponible"""
        print(f"[!] Usando análisis fallback (IA no disponible)")
        
        return {
            'status': 'fallback',
            'message': 'IA no disponible, usando análisis básico',
            'winning_factors': [
                'Operaciones en EURJPY-OTC',
                'Patrones pin_bar_bullish',
                'RSI en rango 50-60'
            ],
            'losing_factors': [
                'Operaciones en AUDUSD-OTC',
                'Sin patrón específico',
                'Tendencia invertida'
            ],
            'improvement_rules': [
                'Pausar AUDUSD-OTC',
                'Aumentar volumen en EURJPY-OTC',
                'Requerir patrón específico'
            ]
        }

    # ═══════════════════════════════════════════════════════════════════════════════
    # PREDICCIÓN CON IA
    # ═══════════════════════════════════════════════════════════════════════════════

    def predict_next_move(self, current_context: Dict) -> Dict:
        """
        Predice el próximo movimiento usando IA
        """
        print(f"\n[*] Prediciendo próximo movimiento con IA...")
        
        prompt = self._create_prediction_prompt(current_context)
        prediction = self._call_copilot_api(prompt, "prediction")
        
        if prediction:
            self.predictions_history.append({
                'timestamp': time.time(),
                'context': current_context,
                'prediction': prediction
            })
            return prediction
        else:
            return self._fallback_prediction(current_context)

    def _create_prediction_prompt(self, context: Dict) -> str:
        """Crea prompt para predicción"""
        
        prompt = f"""
Eres un experto en análisis técnico de opciones binarias. Basándote en este contexto:

CONTEXTO ACTUAL:
- Activo: {context.get('asset', 'N/A')}
- Precio: {context.get('price', 'N/A')}
- RSI: {context.get('rsi', 'N/A')}
- Tendencia: {context.get('trend', 'N/A')}
- Sesión: {context.get('session', 'N/A')}
- Zona cercana: {context.get('nearby_zone', 'N/A')}
- Patrón detectado: {context.get('pattern', 'N/A')}

PREDICE:
1. Dirección más probable (CALL/PUT)
2. Confianza (0-100)
3. Precio objetivo
4. Tiempo estimado
5. Riesgos principales

Responde en JSON:
{{
    "direction": "CALL/PUT",
    "confidence": 0-100,
    "target_price": 0.0,
    "estimated_time": "segundos",
    "risks": [...],
    "reasoning": "explicación"
}}
"""
        return prompt

    def _fallback_prediction(self, context: Dict) -> Dict:
        """Predicción fallback"""
        return {
            'status': 'fallback',
            'direction': 'CALL',
            'confidence': 50,
            'message': 'IA no disponible'
        }

    # ═══════════════════════════════════════════════════════════════════════════════
    # GENERACIÓN DE ESTRATEGIAS
    # ═══════════════════════════════════════════════════════════════════════════════

    def generate_strategy(self, market_conditions: Dict) -> Dict:
        """
        Genera estrategia personalizada usando IA
        """
        print(f"\n[*] Generando estrategia con IA...")
        
        prompt = self._create_strategy_prompt(market_conditions)
        strategy = self._call_copilot_api(prompt, "strategy")
        
        if strategy:
            self.strategies_generated.append({
                'timestamp': time.time(),
                'conditions': market_conditions,
                'strategy': strategy
            })
            return strategy
        else:
            return self._fallback_strategy()

    def _create_strategy_prompt(self, conditions: Dict) -> str:
        """Crea prompt para generación de estrategia"""
        
        prompt = f"""
Eres un experto en trading algorítmico. Genera una estrategia personalizada para:

CONDICIONES DE MERCADO:
- Volatilidad: {conditions.get('volatility', 'media')}
- Tendencia: {conditions.get('trend', 'neutral')}
- Sesión: {conditions.get('session', 'EUROPE')}
- Activos disponibles: {', '.join(conditions.get('assets', []))}
- Win rate actual: {conditions.get('current_wr', 0.5):.1%}

GENERA:
1. 5 reglas de entrada específicas
2. 3 reglas de salida
3. Gestión de riesgo
4. Parámetros de optimización
5. Métricas de éxito

Responde en JSON:
{{
    "entry_rules": [...],
    "exit_rules": [...],
    "risk_management": {{...}},
    "optimization_params": {{...}},
    "success_metrics": [...]
}}
"""
        return prompt

    def _fallback_strategy(self) -> Dict:
        """Estrategia fallback"""
        return {
            'status': 'fallback',
            'entry_rules': [
                'Esperar confirmación de zona',
                'RSI en extremos',
                'Patrón específico'
            ],
            'message': 'IA no disponible'
        }

    # ═══════════════════════════════════════════════════════════════════════════════
    # OPTIMIZACIÓN AUTOMÁTICA
    # ═══════════════════════════════════════════════════════════════════════════════

    def optimize_parameters(self, current_params: Dict, performance: Dict) -> Dict:
        """
        Optimiza parámetros automáticamente con IA
        """
        print(f"\n[*] Optimizando parámetros con IA...")
        
        prompt = f"""
Eres un experto en optimización de sistemas de trading. Optimiza estos parámetros:

PARÁMETROS ACTUALES:
{json.dumps(current_params, indent=2)}

DESEMPEÑO:
- Win Rate: {performance.get('wr', 0.5):.1%}
- PnL: {performance.get('pnl', 0):.2f}
- Sharpe Ratio: {performance.get('sharpe', 0):.2f}

OPTIMIZA:
1. Ajusta cada parámetro
2. Explica por qué
3. Proyecta mejora esperada
4. Riesgos potenciales

Responde en JSON:
{{
    "optimized_params": {{...}},
    "changes": [...],
    "expected_improvement": "X%",
    "risks": [...]
}}
"""
        
        optimization = self._call_copilot_api(prompt, "optimization")
        return optimization or {'status': 'fallback', 'message': 'IA no disponible'}

    # ═══════════════════════════════════════════════════════════════════════════════
    # RESUMEN Y ESTADO
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_summary(self) -> Dict:
        """Resumen del estado del AI Brain"""
        return {
            'name': self.name,
            'version': self.version,
            'authenticated': self.token is not None,
            'analysis_count': len(self.analysis_history),
            'predictions_count': len(self.predictions_history),
            'strategies_generated': len(self.strategies_generated),
            'status': 'ACTIVE' if self.token else 'NOT_AUTHENTICATED'
        }


# Singleton
_brain: Optional[CopilotAIBrain] = None


def get_copilot_ai_brain() -> CopilotAIBrain:
    global _brain
    if _brain is None:
        _brain = CopilotAIBrain()
    return _brain


if __name__ == "__main__":
    # Inicializar y autenticar
    brain = get_copilot_ai_brain()
    
    if brain.authenticate():
        print(f"\n[OK] AI Brain listo")
        print(f"{json.dumps(brain.get_summary(), indent=2)}")
    else:
        print(f"\n[ERROR] No se pudo autenticar")
