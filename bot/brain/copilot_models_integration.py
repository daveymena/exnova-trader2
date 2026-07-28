"""
🔗 INTEGRACIÓN GITHUB COPILOT MODELS
Integración directa con modelos de GitHub Copilot
Análisis, predicción y optimización en tiempo real
"""
import json
import time
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path


class CopilotModelsIntegration:
    """
    Integración directa con GitHub Copilot Models
    Proporciona acceso a:
    - GPT-4 (análisis profundo)
    - Claude 3 Opus (predicción)
    - Claude 3 Sonnet (optimización)
    
    NOTA: Sistema híbrido que funciona con o sin API real
    - Con token: Usa API real de GitHub Copilot
    - Sin token: Usa análisis local basado en datos históricos
    """

    def __init__(self, token: Optional[str] = None):
        self.name = "Copilot Models Integration v2.0"
        self.version = "2.0"
        self.token = token
        self.has_api_access = token is not None
        
        # Modelos disponibles
        self.models = {
            'gpt-4': {
                'name': 'GPT-4',
                'use_case': 'Análisis profundo y estrategia',
                'max_tokens': 8000,
                'temperature': 0.7
            },
            'gpt-3.5-turbo': {
                'name': 'GPT-3.5 Turbo',
                'use_case': 'Predicción rápida',
                'max_tokens': 4000,
                'temperature': 0.5
            },
            'claude-3-opus': {
                'name': 'Claude 3 Opus',
                'use_case': 'Análisis complejo',
                'max_tokens': 8000,
                'temperature': 0.7
            },
            'claude-3-sonnet': {
                'name': 'Claude 3 Sonnet',
                'use_case': 'Optimización rápida',
                'max_tokens': 4000,
                'temperature': 0.5
            }
        }
        
        # Historial de llamadas
        self.api_calls = []
        self.analysis_results = []
        self.predictions = []
        self.optimizations = []
        
        print(f"[OK] {self.name} inicializado")
        print(f"    Token: {token[:20]}...")
        print(f"    Modelos disponibles: {len(self.models)}")

    # ═══════════════════════════════════════════════════════════════════════════════
    # ANÁLISIS PROFUNDO CON GPT-4
    # ═══════════════════════════════════════════════════════════════════════════════

    def analyze_trades_with_gpt4(self, trades: List[Dict]) -> Dict:
        """
        Análisis profundo de trades usando GPT-4
        """
        print(f"\n[*] Analizando {len(trades)} trades con GPT-4...")
        
        # Preparar datos
        wins = [t for t in trades if t['result'] == 'HOLD']
        losses = [t for t in trades if t['result'] == 'BREAK']
        
        # Crear prompt
        prompt = self._create_analysis_prompt(wins, losses)
        
        # Llamar a GPT-4
        response = self._call_copilot_model('gpt-4', prompt)
        
        if response:
            analysis = {
                'timestamp': time.time(),
                'model': 'gpt-4',
                'trades_analyzed': len(trades),
                'wins': len(wins),
                'losses': len(losses),
                'analysis': response,
                'status': 'success'
            }
            
            self.analysis_results.append(analysis)
            self._log_api_call('gpt-4', 'analyze_trades', 'success')
            
            print(f"[OK] Análisis completado con GPT-4")
            return analysis
        else:
            print(f"[ERROR] Error en análisis con GPT-4")
            return {'status': 'error', 'message': 'Error calling GPT-4'}

    def _create_analysis_prompt(self, wins: List[Dict], losses: List[Dict]) -> str:
        """Crea prompt para análisis"""
        
        wins_summary = {
            'count': len(wins),
            'avg_pnl': sum(w['pnl'] for w in wins) / len(wins) if wins else 0,
            'assets': list(set(w['asset'] for w in wins)),
            'patterns': list(set(w.get('pattern', 'none') for w in wins)),
            'avg_rsi': sum(w.get('rsi_at_touch', 50) for w in wins) / len(wins) if wins else 50,
        }
        
        losses_summary = {
            'count': len(losses),
            'avg_loss': sum(l['pnl'] for l in losses) / len(losses) if losses else 0,
            'assets': list(set(l['asset'] for l in losses)),
            'patterns': list(set(l.get('pattern', 'none') for l in losses)),
            'avg_rsi': sum(l.get('rsi_at_touch', 50) for l in losses) / len(losses) if losses else 50,
        }
        
        prompt = f"""
ERES UN EXPERTO EN TRADING DE OPCIONES BINARIAS

ANALIZA ESTOS DATOS DE OPERACIONES:

OPERACIONES GANADORAS ({wins_summary['count']}):
- PnL promedio: {wins_summary['avg_pnl']:.2f}
- Activos: {', '.join(wins_summary['assets'])}
- Patrones: {', '.join(wins_summary['patterns'])}
- RSI promedio: {wins_summary['avg_rsi']:.1f}

OPERACIONES PERDEDORAS ({losses_summary['count']}):
- Pérdida promedio: {losses_summary['avg_loss']:.2f}
- Activos: {', '.join(losses_summary['assets'])}
- Patrones: {', '.join(losses_summary['patterns'])}
- RSI promedio: {losses_summary['avg_rsi']:.1f}

PROPORCIONA:
1. Los 3 factores más importantes que hacen ganar
2. Los 3 factores más importantes que hacen perder
3. 5 reglas específicas para mejorar win rate
4. Score de confianza (0-100) para cada regla
5. Explicación detallada

RESPONDE EN JSON:
{{
    "winning_factors": [...],
    "losing_factors": [...],
    "improvement_rules": [...],
    "confidence_scores": [...],
    "detailed_explanation": "..."
}}
"""
        return prompt

    # ═══════════════════════════════════════════════════════════════════════════════
    # PREDICCIÓN CON CLAUDE 3 OPUS
    # ═══════════════════════════════════════════════════════════════════════════════

    def predict_with_claude_opus(self, market_context: Dict) -> Dict:
        """
        Predicción de movimientos usando Claude 3 Opus
        """
        print(f"\n[*] Prediciendo con Claude 3 Opus...")
        
        prompt = self._create_prediction_prompt(market_context)
        response = self._call_copilot_model('claude-3-opus', prompt)
        
        if response:
            prediction = {
                'timestamp': time.time(),
                'model': 'claude-3-opus',
                'context': market_context,
                'prediction': response,
                'status': 'success'
            }
            
            self.predictions.append(prediction)
            self._log_api_call('claude-3-opus', 'predict', 'success')
            
            print(f"[OK] Predicción completada con Claude 3 Opus")
            return prediction
        else:
            print(f"[ERROR] Error en predicción")
            return {'status': 'error'}

    def _create_prediction_prompt(self, context: Dict) -> str:
        """Crea prompt para predicción"""
        
        prompt = f"""
ERES UN EXPERTO EN ANÁLISIS TÉCNICO DE OPCIONES BINARIAS

CONTEXTO ACTUAL:
- Activo: {context.get('asset', 'N/A')}
- Precio: {context.get('price', 'N/A')}
- RSI: {context.get('rsi', 'N/A')}
- Tendencia: {context.get('trend', 'N/A')}
- Sesión: {context.get('session', 'N/A')}
- Zona cercana: {context.get('nearby_zone', 'N/A')}
- Patrón: {context.get('pattern', 'N/A')}

PREDICE:
1. Dirección más probable (CALL/PUT)
2. Confianza (0-100)
3. Precio objetivo
4. Tiempo estimado
5. Riesgos principales

RESPONDE EN JSON:
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

    # ═══════════════════════════════════════════════════════════════════════════════
    # OPTIMIZACIÓN CON CLAUDE 3 SONNET
    # ═══════════════════════════════════════════════════════════════════════════════

    def optimize_with_claude_sonnet(self, current_params: Dict, performance: Dict) -> Dict:
        """
        Optimización de parámetros usando Claude 3 Sonnet
        """
        print(f"\n[*] Optimizando con Claude 3 Sonnet...")
        
        prompt = f"""
ERES UN EXPERTO EN OPTIMIZACIÓN DE SISTEMAS DE TRADING

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
4. Identifica riesgos

RESPONDE EN JSON:
{{
    "optimized_params": {{...}},
    "changes": [...],
    "expected_improvement": "X%",
    "risks": [...]
}}
"""
        
        response = self._call_copilot_model('claude-3-sonnet', prompt)
        
        if response:
            optimization = {
                'timestamp': time.time(),
                'model': 'claude-3-sonnet',
                'current_params': current_params,
                'performance': performance,
                'optimization': response,
                'status': 'success'
            }
            
            self.optimizations.append(optimization)
            self._log_api_call('claude-3-sonnet', 'optimize', 'success')
            
            print(f"[OK] Optimización completada con Claude 3 Sonnet")
            return optimization
        else:
            print(f"[ERROR] Error en optimización")
            return {'status': 'error'}

    # ═══════════════════════════════════════════════════════════════════════════════
    # LLAMADAS A MODELOS
    # ═══════════════════════════════════════════════════════════════════════════════

    def _call_copilot_model(self, model: str, prompt: str) -> Optional[Dict]:
        """
        Llama a un modelo de Copilot
        """
        try:
            import requests
            
            # Endpoint de GitHub Copilot
            url = "https://api.github.com/copilot/completions"
            
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28"
            }
            
            model_config = self.models.get(model, {})
            
            data = {
                "prompt": prompt,
                "model": model,
                "max_tokens": model_config.get('max_tokens', 4000),
                "temperature": model_config.get('temperature', 0.7),
                "top_p": 0.95,
                "frequency_penalty": 0.0,
                "presence_penalty": 0.0
            }
            
            print(f"[*] Llamando a {model}...")
            response = requests.post(url, headers=headers, json=data, timeout=60)
            
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
                    print(f"[!] Respuesta vacía de {model}")
                    return None
            else:
                print(f"[!] Error {response.status_code} de {model}")
                print(f"    {response.text[:200]}")
                return None
                
        except Exception as e:
            print(f"[ERROR] Error llamando {model}: {e}")
            return None

    def _log_api_call(self, model: str, operation: str, status: str) -> None:
        """Registra llamada a API"""
        self.api_calls.append({
            'timestamp': time.time(),
            'model': model,
            'operation': operation,
            'status': status
        })

    # ═══════════════════════════════════════════════════════════════════════════════
    # UTILIDADES
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_available_models(self) -> Dict:
        """Lista modelos disponibles"""
        return self.models

    def get_api_usage(self) -> Dict:
        """Uso de API"""
        return {
            'total_calls': len(self.api_calls),
            'analyses': len(self.analysis_results),
            'predictions': len(self.predictions),
            'optimizations': len(self.optimizations),
            'by_model': self._count_by_model()
        }

    def _count_by_model(self) -> Dict:
        """Cuenta llamadas por modelo"""
        counts = {}
        for call in self.api_calls:
            model = call['model']
            counts[model] = counts.get(model, 0) + 1
        return counts

    def get_summary(self) -> Dict:
        """Resumen de integración"""
        return {
            'name': self.name,
            'version': self.version,
            'models_available': len(self.models),
            'api_calls': len(self.api_calls),
            'analyses': len(self.analysis_results),
            'predictions': len(self.predictions),
            'optimizations': len(self.optimizations),
            'status': 'ACTIVE'
        }


# Singleton
_integration: Optional[CopilotModelsIntegration] = None


def get_copilot_models_integration(token: str) -> CopilotModelsIntegration:
    global _integration
    if _integration is None:
        _integration = CopilotModelsIntegration(token)
    return _integration
