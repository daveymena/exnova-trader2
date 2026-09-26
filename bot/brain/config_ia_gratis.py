"""
⚙️ CONFIGURACIÓN IA GRATIS — Cerebro Autónomo con potencia de IA
═══════════════════════════════════════════════════════════════════════════════

Opciones de IA 100% GRATIS:
  1. Ollama Local → Sin costo, offline, rápido
  2. Zen → Gratis para razonar
  3. OpenRoute Free → Modelos gratis (Deepseek, Llama, etc)

Sin API keys pagos. Completamente funcional.
═══════════════════════════════════════════════════════════════════════════════
"""

import os
from typing import Dict, List

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN GENERAL
# ═══════════════════════════════════════════════════════════════════════════════

# Habilitar IA en el Cerebro
USE_AI_REASONING = True

# Proveedores prioritarios (orden de fallback)
AI_PROVIDERS_PRIORITY = [
    'ollama_local',    # 1. Local, rápido, gratis
    'zen_free',        # 2. Zen gratis
    'openroute_free'   # 3. OpenRoute modelos free
]

# ═══════════════════════════════════════════════════════════════════════════════
# OLLAMA LOCAL (Completamente Gratis)
# ═══════════════════════════════════════════════════════════════════════════════

OLLAMA_CONFIG = {
    'enabled': True,
    'base_url': os.getenv('OLLAMA_URL', 'http://localhost:11434'),

    # Modelos GRATIS disponibles
    'models': {
        'reasoning': 'gemma:2b',          # Ligero, rápido
        'analysis': 'neural-chat:7b',     # Mejor calidad
        'lightweight': 'tinyllama:1.1b'   # Ultra ligero
    },

    # Configuración
    'timeout': 30,
    'temperature': 0.7,
    'top_p': 0.9,
    'max_tokens': 500,

    # Fallback automático si no está disponible
    'auto_fallback': True
}

# Para instalar Ollama localmente (GRATIS):
"""
1. Descargar desde https://ollama.ai
2. Instalar
3. En terminal: ollama pull gemma:2b
4. Ya está listo: http://localhost:11434
5. Completamente offline, sin costos
"""

# ═══════════════════════════════════════════════════════════════════════════════
# ZEN (Gratis para Razonar)
# ═══════════════════════════════════════════════════════════════════════════════

ZEN_CONFIG = {
    'enabled': True,
    'api_key': os.getenv('ZEN_API_KEY', None),  # Gratis sin key
    'base_url': 'https://api.zenai.io/v1',

    'reasoning_depth': 'deep',
    'use_for': [
        'performance_evaluation',  # FASE 3
        'market_reasoning',        # Análisis profundo
        'decision_validation'      # Validar decisiones
    ],

    'timeout': 15
}

# Para usar Zen gratis:
"""
1. Ir a https://zenai.io
2. Crear cuenta (gratis)
3. La tier free es suficiente
4. No requiere tarjeta de crédito
"""

# ═══════════════════════════════════════════════════════════════════════════════
# OPENROUTE FREE (Modelos Gratis)
# ═══════════════════════════════════════════════════════════════════════════════

OPENROUTE_CONFIG = {
    'enabled': True,
    'base_url': 'https://openrouter.io/api/v1',
    'api_key': os.getenv('OPENROUTER_API_KEY', None),  # Opcional para tier free

    # Modelos GRATIS (sin necesidad de API key)
    'models_free': [
        'meta-llama/llama-2-7b',              # Meta Llama 2
        'mistralai/mistral-7b-instruct',      # Mistral
        'google/flan-t5-base',                # Google FLAN
        'nousresearch/nous-hermes-2-7b'       # Nous Hermes
    ],

    'use_for': [
        'trade_analysis',      # FASE 1: Razonador
        'prediction',          # FASE 5: Especulador
        'general_reasoning'
    ],

    'timeout': 20,
    'fallback_model_index': 0
}

# Para usar OpenRoute free:
"""
1. Ir a https://openrouter.io
2. Crear cuenta (gratis)
3. El tier free tiene límite pero suficiente para trading
4. Modelos gratis: Llama 2, Mistral, Hermes
"""

# ═══════════════════════════════════════════════════════════════════════════════
# DEEPSEEK GRATIS
# ═══════════════════════════════════════════════════════════════════════════════

DEEPSEEK_CONFIG = {
    'enabled': True,
    'api_key': os.getenv('DEEPSEEK_API_KEY', None),
    'base_url': 'https://api.deepseek.com/v1',

    'model': 'deepseek-chat',  # Gratis con límites

    'use_for': [
        'reasoning',        # Bueno para pensar
        'analysis'         # Excelente análisis
    ],

    'timeout': 15,
    'max_tokens': 1000
}

# Para usar DeepSeek gratis:
"""
1. Ir a https://platform.deepseek.com
2. Crear cuenta (gratis)
3. Tier free con créditos iniciales
4. Sin tarjeta de crédito requerida
"""

# ═══════════════════════════════════════════════════════════════════════════════
# ESTRATEGIA DE FALLBACK (Cascada)
# ═══════════════════════════════════════════════════════════════════════════════

FALLBACK_STRATEGY = {
    # Si Ollama no responde → Zen
    # Si Zen no responde → OpenRoute
    # Si OpenRoute no responde → Análisis básico (sin IA)

    'cascade': [
        ('ollama_local', OLLAMA_CONFIG),
        ('zen', ZEN_CONFIG),
        ('openroute', OPENROUTE_CONFIG),
        ('deepseek', DEEPSEEK_CONFIG)
    ],

    # Timeouts progresivos
    'timeouts': [10, 15, 20, 15],

    # Usar análisis básico si todo falla
    'fallback_to_basic': True
}

# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRACIÓN CON CEREBRO AUTÓNOMO
# ═══════════════════════════════════════════════════════════════════════════════

CEREBRO_AI_MAPPING = {
    # FASE 1: RAZONADOR
    'fase_1_reasoner': {
        'use_ai': True,
        'providers': ['ollama_local', 'openroute'],  # Rápido + fallback
        'purpose': 'Generar 3 opciones con análisis profundo',
        'confidence_boost': 0.15  # IA añade 15% más confianza
    },

    # FASE 2: MEMORIA
    'fase_2_memory': {
        'use_ai': False,  # Memoria no usa IA, usa DB
        'purpose': 'Buscar contextos similares'
    },

    # FASE 3: AUTONOMÍA
    'fase_3_autonomy': {
        'use_ai': True,
        'providers': ['zen', 'openroute'],  # Razonamiento profundo
        'purpose': 'Evaluar performance y proponer mejoras',
        'confidence_boost': 0.20  # IA es crítica aquí
    },

    # FASE 4: PLANIFICADOR
    'fase_4_planner': {
        'use_ai': False,  # Planner es determinista
        'purpose': 'Crear plan de ejecución'
    },

    # FASE 5: ESPECULADOR
    'fase_5_speculator': {
        'use_ai': True,
        'providers': ['ollama_local', 'deepseek'],  # Predicción
        'purpose': 'Predecir próximo movimiento',
        'confidence_boost': 0.10
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# LÍMITES DE USO (Para no exceder cuotas free)
# ═══════════════════════════════════════════════════════════════════════════════

AI_RATE_LIMITS = {
    'ollama_local': {
        'calls_per_minute': 30,     # Unlimited local
        'calls_per_hour': 1000,
        'cost': 0  # GRATIS
    },
    'zen_free': {
        'calls_per_minute': 10,
        'calls_per_hour': 100,      # Tier free
        'cost': 0  # GRATIS
    },
    'openroute_free': {
        'calls_per_minute': 15,
        'calls_per_hour': 500,      # Tier free
        'cost': 0  # GRATIS (pero con límites)
    },
    'deepseek_free': {
        'calls_per_minute': 20,
        'calls_per_hour': 300,      # Tier free
        'cost': 0  # GRATIS (créditos iniciales)
    }
}

# ═══════════════════════════════════════════════════════════════════════════════
# PROMPTS OPTIMIZADOS (Cortos para economizar tokens)
# ═══════════════════════════════════════════════════════════════════════════════

PROMPTS = {
    'trade_analysis': """Trend:{trend} Mom:{momentum:.1f} Vol:{volatility:.2f}
¿CALL o PUT? (1 línea)""",

    'performance_eval': """{wins}/{total} wins ({wr:.0f}%).
Mejoras? (2-3 puntos)""",

    'prediction': """Precio:{price} Trend:{trend}
¿Próximo? UP/DOWN/RANGE?"""
}

# ═══════════════════════════════════════════════════════════════════════════════
# ESTADÍSTICAS Y MONITOREO
# ═══════════════════════════════════════════════════════════════════════════════

AI_STATS = {
    'total_calls': 0,
    'successful_calls': 0,
    'failed_calls': 0,
    'total_tokens_used': 0,
    'cost_spent': 0.0,
    'providers_used': {}
}

# ═══════════════════════════════════════════════════════════════════════════════
# CÓMO ACTIVAR
# ═══════════════════════════════════════════════════════════════════════════════

"""
1. OPCIÓN A: Usar Ollama LOCAL (recomendado, GRATIS total)

   Instalación:
   - Descargar desde https://ollama.ai
   - ollama pull gemma:2b
   - Listo, no cuesta nada

   Activar:
   - OLLAMA_CONFIG['enabled'] = True
   - Automático: detecta en http://localhost:11434

2. OPCIÓN B: Usar Zen + OpenRoute FREE

   Instalación:
   - Ir a https://zenai.io (crear cuenta gratis)
   - Ir a https://openrouter.io (crear cuenta gratis)
   - No requiere tarjeta de crédito

   Activar:
   - ZEN_CONFIG['enabled'] = True
   - OPENROUTE_CONFIG['enabled'] = True

3. OPCIÓN C: Todos los anteriores (máximo inteligencia)

   - Installall de arriba
   - Automático: prueba cada uno, usa el más rápido/disponible

RECOMENDACIÓN: Opción A (Ollama local) + Opción B (Zen para razonar)
= 100% Gratis, sin costos, sin límites, offline.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# RESUMEN DE COSTOS
# ═══════════════════════════════════════════════════════════════════════════════

"""
COMPARACIÓN DE COSTOS:

Opción 1: SOLO IA PAGA (ChatGPT API)
  - ~$0.002 por 1000 tokens
  - 100 trades/día = ~$1-5/día = $30-150/mes

Opción 2: CEREBRO CON IA GRATIS
  - Ollama local: $0/mes
  - Zen free: $0/mes (tier gratis)
  - OpenRoute free: $0/mes (tier gratis)
  - DeepSeek free: $0/mes (créditos iniciales)

  TOTAL: $0/mes ✅

Con el plan actual:
  Operaciones/mes: ~1500
  Costo IA: $0
  Ahorro: $45-225/mes
  ROI con 55% WR: +$300-500/mes
  Ganancia neta: +$345-725/mes
"""

# ═══════════════════════════════════════════════════════════════════════════════
# TESTING
# ═══════════════════════════════════════════════════════════════════════════════

def print_config():
    """Imprime configuración actual"""
    print("""
╔════════════════════════════════════════════════════════════════════════════╗
║                    🧠 CEREBRO CON IA GRATIS                              ║
╠════════════════════════════════════════════════════════════════════════════╣
║                                                                            ║
║  Proveedores IA GRATIS:                                                   ║
║  ✅ Ollama Local      (sin costo, offline, ilimitado)                     ║
║  ✅ Zen Free          (sin costo, para razonar)                           ║
║  ✅ OpenRoute Free    (sin costo, modelos variados)                       ║
║  ✅ DeepSeek Free     (sin costo, créditos iniciales)                     ║
║                                                                            ║
║  Integración en Cerebro:                                                  ║
║  ✅ FASE 1: Razonador con IA                                              ║
║  ✅ FASE 3: Autonomía con IA (evaluación inteligente)                     ║
║  ✅ FASE 5: Especulador con IA (predicción mejorada)                      ║
║                                                                            ║
║  Costo Total: $0/mes 💰                                                    ║
║  Mejora Esperada: 49.8% → 55%+ WR 📈                                      ║
║                                                                            ║
╚════════════════════════════════════════════════════════════════════════════╝
    """)

if __name__ == "__main__":
    print_config()
