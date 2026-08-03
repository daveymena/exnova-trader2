"""
DeepSeek AI Optimizer - Usa DeepSeek Flash (GRATIS) para analizar y mejorar
La IA analiza trades en tiempo real y genera mejoras inteligentes
NO son reglas simples, es IA REAL analizando
"""
import json
import requests
from typing import Dict, List, Optional, Any
from datetime import datetime
import os


class DeepSeekOptimizer:
    """
    Integración con DeepSeek Flash (API GRATIS)
    Analiza cada trade con IA real y genera mejoras
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Args:
            api_key: DeepSeek API key (o env var DEEPSEEK_API_KEY)
        """
        self.api_key = api_key or os.getenv('DEEPSEEK_API_KEY')
        self.base_url = "https://api.deepseek.com/v1"
        self.model = "deepseek-chat"  # DeepSeek Flash (gratuito)
        self.conversation_history = []
        self.analysis_history = []

    def analyze_trade(self, trade: Dict) -> Dict:
        """
        Usa IA REAL para analizar un trade

        Args:
            trade: Trade ejecutado con todos sus datos

        Returns:
            Análisis inteligente de IA
        """
        prompt = f"""
Analiza este trade de trading de opciones binarias y genera mejoras inteligentes:

DATOS DEL TRADE:
- Asset: {trade.get('asset')}
- Signal: {trade.get('signal')}
- Confidence: {trade.get('confidence')}%
- Entry Price: {trade.get('entry_price')}
- Exit Price: {trade.get('exit_price')}
- Result: {trade.get('result')}
- PnL: ${trade.get('pnl')}
- Strategy Used: {trade.get('strategy')}
- Volatility: {trade.get('volatility', 'N/A')}
- Zone Touches: {trade.get('zone_touches', 'N/A')}
- Time to Close: {trade.get('time_to_close')} seconds

ANÁLISIS REQUERIDO:
1. ¿Por qué ganó/perdió este trade? (Análisis profundo, no superficial)
2. ¿Qué patrones ves en los datos?
3. ¿Qué parámetro debería ajustarse? (sea específico)
4. ¿Cómo mejorar la próxima operación similar?
5. ¿Hay alertas o riesgos detectados?

IMPORTANTE:
- Sé específico y accionable
- Sugiere valores numéricos reales (ej: cambiar threshold de 60 a 68)
- Piensa como un trader experimentado
- Considera el riesgo/recompensa
"""

        response = self._call_deepseek(prompt)

        analysis = {
            'timestamp': datetime.now().isoformat(),
            'trade_id': trade.get('id'),
            'asset': trade.get('asset'),
            'ai_analysis': response,
            'recommendations': self._extract_recommendations(response),
            'parameter_adjustments': self._extract_adjustments(response)
        }

        # Guardar en historial
        self.analysis_history.append(analysis)

        return analysis

    def detect_patterns_across_trades(self, trades: List[Dict]) -> Dict:
        """
        Usa IA para detectar patrones complejos en múltiples trades
        (Mucho más inteligente que detección simple)
        """
        if len(trades) < 10:
            return {'status': 'NOT_ENOUGH_DATA', 'trades': len(trades)}

        # Preparar datos
        trades_summary = self._prepare_trades_summary(trades[-50:])

        prompt = f"""
Analiza estos 50 últimos trades de opciones binarias y detecta patrones PROFUNDOS:

DATOS:
{trades_summary}

ANÁLISIS REQUERIDO:
1. ¿Cuál es el patrón principal de pérdidas? (No obvio)
2. ¿Hay factores externos que afecten? (Volatilidad, hora, asset específico)
3. ¿Qué estrategia estaría funcionando mejor?
4. ¿Cuál es el problema raíz que no se ve a simple vista?
5. ¿Cómo reorganizar los parámetros de forma INTEGRAL?

PIENSA COMO:
- Un analista cuantitativo profesional
- Un trader experimentado
- Un especialista en machine learning

Genera un análisis profundo que revele lo que no se ve en superficie.
"""

        response = self._call_deepseek(prompt)

        return {
            'timestamp': datetime.now().isoformat(),
            'trades_analyzed': len(trades),
            'deep_analysis': response,
            'strategic_recommendations': self._extract_strategic_recs(response),
            'system_improvements': self._extract_system_improvements(response)
        }

    def optimize_parameters_with_ai(self, current_params: Dict, performance_data: Dict) -> Dict:
        """
        Usa IA para REALMENTE OPTIMIZAR parámetros basado en desempeño
        No son ajustes simples, es optimización inteligente
        """
        prompt = f"""
Eres un experto en optimización de estrategias de trading.
Teniendo en cuenta el desempeño actual, OPTIMIZA estos parámetros de forma INTELIGENTE:

PARÁMETROS ACTUALES:
{json.dumps(current_params, indent=2)}

DESEMPEÑO:
{json.dumps(performance_data, indent=2)}

TAREA:
1. Analiza por qué estos parámetros no funcionan bien
2. PROPÓN nuevos valores ESPECÍFICOS para cada parámetro
3. Explica la lógica detrás de cada cambio
4. Estima el impacto esperado (WR antes/después)
5. Propón un plan de prueba (A/B testing)

IMPORTANTE:
- Sé ESPECÍFICO con números
- Justifica cada cambio con lógica de trading
- Considera el balance risk/reward
- Piensa en implementación práctica

FORMATO DE RESPUESTA:
Para cada parámetro:
- Nombre: X
- Valor actual: Y
- Valor propuesto: Z
- Razón: [explicación profunda]
- Impacto esperado: [cambio en WR estimado]
"""

        response = self._call_deepseek(prompt)

        return {
            'timestamp': datetime.now().isoformat(),
            'optimization_plan': response,
            'proposed_parameters': self._extract_proposed_params(response),
            'expected_improvement': self._extract_expected_improvement(response)
        }

    def diagnose_failure(self, failed_trades: List[Dict]) -> Dict:
        """
        Usa IA para DIAGNOSTICAR por qué está fallando la estrategia
        Análisis profundo, no superficial
        """
        if not failed_trades:
            return {'status': 'NO_FAILURES'}

        prompt = f"""
Tu tarea es hacer un DIAGNÓSTICO MÉDICO de esta estrategia de trading:

TRADES QUE FALLARON (últimos):
{json.dumps(failed_trades[-10:], indent=2, default=str)}

ANÁLISIS CLÍNICO REQUERIDO:
1. ¿Cuál es el síntoma observable? (baja WR)
2. ¿Cuál es la causa raíz? (no el síntoma, la CAUSA)
3. ¿Qué está roto en la estrategia?
4. ¿Es un problema de:
   - Entrada (señales malas)?
   - Validación (filtros insuficientes)?
   - Parámetros (valores incorrectos)?
   - Contexto (no lee el mercado)?
   - Algo más?
5. ¿Cuál es el TRATAMIENTO (solución)?

IMPORTANTE:
- Piensa profundamente
- No des respuestas obvias
- Cuestiona los supuestos
- Busca la causa raíz, no el síntoma

Proporciona un diagnóstico médico riguroso de la estrategia.
"""

        response = self._call_deepseek(prompt)

        return {
            'timestamp': datetime.now().isoformat(),
            'diagnosis': response,
            'root_cause': self._extract_root_cause(response),
            'treatment_plan': self._extract_treatment(response),
            'severity': self._assess_severity(response)
        }

    def suggest_strategy_changes(self, current_strategy: str, performance: Dict) -> Dict:
        """
        Usa IA para sugerir cambios de estrategia si es necesario
        ¿Cambiar a PCRComplete? ¿Híbrida? ¿Otra cosa?
        """
        prompt = f"""
El sistema de trading está usando: {current_strategy}
Con este desempeño: {json.dumps(performance, indent=2)}

EVALÚA:
1. ¿Es la estrategia actual la correcta para estas condiciones?
2. ¿Debería cambiar a otra? (PCRSimple vs Complete vs Hybrid?)
3. ¿Hay una estrategia MEJOR alternativa?
4. ¿Qué ganancia esperada habría con el cambio?
5. ¿Cuál es el riesgo de cambiar?

PROPORCIONA:
- Veredicto: Mantener/Cambiar
- Estrategia recomendada
- Razones específicas
- Plan de transición
- Métricas de éxito esperadas

Sé honesto: ¿Está roota la estrategia o solo necesita ajustes?
"""

        response = self._call_deepseek(prompt)

        return {
            'timestamp': datetime.now().isoformat(),
            'strategy_evaluation': response,
            'recommendation': self._extract_strategy_rec(response),
            'should_change': self._extract_should_change(response),
            'new_strategy': self._extract_new_strategy(response)
        }

    def _call_deepseek(self, prompt: str) -> str:
        """
        Llama a DeepSeek Flash API (GRATIS)
        """
        if not self.api_key:
            return "ERROR: No DeepSeek API key configured. Set DEEPSEEK_API_KEY env var."

        try:
            # Agregar a conversación
            self.conversation_history.append({
                "role": "user",
                "content": prompt
            })

            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": self.conversation_history,
                    "temperature": 0.7,
                    "max_tokens": 2000
                },
                timeout=30
            )

            if response.status_code != 200:
                return f"API Error: {response.status_code} - {response.text}"

            data = response.json()
            assistant_message = data['choices'][0]['message']['content']

            # Guardar en historial
            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message
            })

            return assistant_message

        except Exception as e:
            return f"ERROR calling DeepSeek: {str(e)}"

    def _extract_recommendations(self, analysis: str) -> List[str]:
        """Extrae recomendaciones del análisis de IA"""
        # Simple pattern matching para extraer recomendaciones
        lines = analysis.split('\n')
        recommendations = []
        for line in lines:
            if any(keyword in line.lower() for keyword in ['debería', 'recomiendo', 'sugiero', 'cambiar', 'ajustar']):
                recommendations.append(line.strip())
        return recommendations[:5]  # Top 5

    def _extract_adjustments(self, analysis: str) -> Dict:
        """Extrae ajustes de parámetros sugeridos"""
        adjustments = {}
        # Buscar patrones como "confidence_threshold: 60 -> 70"
        import re
        pattern = r'(\w+)\s*[:\-]\s*(\d+\.?\d*)\s*[->]+\s*(\d+\.?\d*)'
        matches = re.findall(pattern, analysis)
        for param, old_val, new_val in matches:
            adjustments[param] = {
                'current': float(old_val),
                'proposed': float(new_val),
                'change_pct': ((float(new_val) - float(old_val)) / float(old_val) * 100) if float(old_val) != 0 else 0
            }
        return adjustments

    def _extract_strategic_recs(self, analysis: str) -> List[str]:
        """Extrae recomendaciones estratégicas"""
        lines = analysis.split('\n')
        return [line.strip() for line in lines if len(line.strip()) > 20][:3]

    def _extract_system_improvements(self, analysis: str) -> Dict:
        """Extrae mejoras del sistema sugeridas"""
        return {
            'analysis': analysis,
            'timestamp': datetime.now().isoformat()
        }

    def _extract_proposed_params(self, analysis: str) -> Dict:
        """Extrae parámetros propuestos del análisis de optimización"""
        return self._extract_adjustments(analysis)

    def _extract_expected_improvement(self, analysis: str) -> Dict:
        """Extrae mejora esperada"""
        import re
        pattern = r'(\d+\.?\d*)%'
        matches = re.findall(pattern, analysis)
        if matches:
            return {
                'expected_wr_improvement': float(matches[0]),
                'unit': '%'
            }
        return {'expected_wr_improvement': 0}

    def _extract_root_cause(self, diagnosis: str) -> str:
        """Extrae causa raíz del diagnóstico"""
        lines = diagnosis.split('\n')
        for line in lines:
            if 'causa' in line.lower() or 'root' in line.lower():
                return line.strip()
        return diagnosis[:200]

    def _extract_treatment(self, diagnosis: str) -> str:
        """Extrae plan de tratamiento"""
        lines = diagnosis.split('\n')
        for line in lines:
            if 'tratamiento' in line.lower() or 'solución' in line.lower():
                return line.strip()
        return "Ver análisis completo"

    def _assess_severity(self, diagnosis: str) -> str:
        """Evalúa severidad basada en lenguaje"""
        if any(word in diagnosis.lower() for word in ['crítico', 'grave', 'fatal']):
            return 'CRITICAL'
        elif any(word in diagnosis.lower() for word in ['problema', 'fallo', 'error']):
            return 'HIGH'
        elif any(word in diagnosis.lower() for word in ['ajuste', 'mejora', 'optimizar']):
            return 'MEDIUM'
        return 'LOW'

    def _extract_strategy_rec(self, evaluation: str) -> str:
        """Extrae recomendación de estrategia"""
        if 'cambiar' in evaluation.lower():
            return 'CHANGE'
        elif 'mantener' in evaluation.lower():
            return 'KEEP'
        else:
            return 'REVIEW'

    def _extract_should_change(self, evaluation: str) -> bool:
        """¿Debería cambiar de estrategia?"""
        return 'cambiar' in evaluation.lower() or 'reemplazar' in evaluation.lower()

    def _extract_new_strategy(self, evaluation: str) -> Optional[str]:
        """Extrae nueva estrategia sugerida"""
        for strategy in ['PCRSimple', 'PCRComplete', 'PCRHybrid', 'PCRHybridStrict']:
            if strategy in evaluation:
                return strategy
        return None

    def _prepare_trades_summary(self, trades: List[Dict]) -> str:
        """Prepara resumen de trades para enviar a IA"""
        summary = "ÚLTIMOS 50 TRADES:\n"
        for i, trade in enumerate(trades[-50:], 1):
            summary += f"{i}. {trade.get('asset')} {trade.get('signal')} "
            summary += f"conf:{trade.get('confidence')}% result:{trade.get('result')} "
            summary += f"pnl:${trade.get('pnl')}\n"
        return summary

    def get_analysis_history(self) -> List[Dict]:
        """Retorna historial de análisis"""
        return self.analysis_history

    def print_analysis_report(self, analysis: Dict):
        """Imprime reporte de análisis de IA"""
        print(f"\n{'='*80}")
        print(f"🤖 ANÁLISIS DE IA - DeepSeek Flash")
        print(f"{'='*80}")
        print(f"\n📊 Trade ID: {analysis.get('trade_id')}")
        print(f"Asset: {analysis.get('asset')}")
        print(f"\n🧠 ANÁLISIS DE IA:")
        print(analysis.get('ai_analysis'))
        print(f"\n💡 RECOMENDACIONES:")
        for rec in analysis.get('recommendations', []):
            print(f"  • {rec}")
        print(f"\n⚙️ AJUSTES PROPUESTOS:")
        for param, adjustment in analysis.get('parameter_adjustments', {}).items():
            print(f"  {param}: {adjustment.get('current')} → {adjustment.get('proposed')} "
                  f"({adjustment.get('change_pct', 0):+.1f}%)")
        print(f"\n{'='*80}")
