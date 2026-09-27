"""Bucle de mejora continua - Usa Groq API directamente
Auto-analiza trades y propone mejoras inteligentes
"""
import json
import os
import sys
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional

import requests

log = logging.getLogger("improvement_loop")

BOT = Path(__file__).absolute().parents[1]
if str(BOT) not in sys.path:
    sys.path.insert(0, str(BOT))

TRADES_JSON = BOT / "brain" / "trade_history.json"

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN GROQ API (proveedor que funciona)
# ═══════════════════════════════════════════════════════════════════════════════

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_FALLBACK_MODELS = [
    m.strip() for m in os.getenv(
        "GROQ_FALLBACK_MODELS",
        "openai/gpt-oss-120b,openai/gpt-oss-20b"
    ).split(",") if m.strip()
]

BATCH_N_TRADES = int(os.getenv("IMPROVEMENT_BATCH_TRADES", "30"))
BATCH_MIN_MINUTES = int(os.getenv("IMPROVEMENT_BATCH_MIN_MINUTES", "20"))
TIMEOUT_SEC = int(os.getenv("IMPROVEMENT_TIMEOUT", "90"))
ENABLED = os.getenv("IMPROVEMENT_ENABLED", "true").lower() == "true"

SYSTEM_PROMPT = (
    "Eres un TRADER PROFESIONAL analizando operaciones de opciones binarias OTC en Exnova. "
    "Tu objetivo es encontrar patrones ganadores y proponer mejoras precisas. "
    "Devuelve SIEMPRE un JSON valido sin markdown."
)

def _log(msg: str) -> None:
    ts = time.strftime('%H:%M:%S')
    print(f"[improvement] {ts} {msg}", flush=True)
    log.info(msg)

def _find_ai_provider() -> Optional[str]:
    """Verifica que Groq API esté disponible"""
    if not GROQ_API_KEY:
        _log("ADVERTENCIA: GROQ_API_KEY no configurada")
        return None

    try:
        response = requests.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            timeout=5
        )
        if response.status_code == 200:
            _log(f"Groq API disponible (modelo: {GROQ_MODEL})")
            return "groq"
    except Exception as e:
        _log(f"ADVERTENCIA: Groq API no accesible: {e}")

    return None

def _call_ai(prompt: str) -> Optional[Dict]:
    """Llama a Groq API con fallback de modelos"""
    models_to_try = [GROQ_MODEL] + GROQ_FALLBACK_MODELS

    for model in models_to_try:
        try:
            response = requests.post(
                GROQ_API_URL,
                json={
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ],
                    "model": model,
                    "max_tokens": 1000,
                    "temperature": 0.7
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {GROQ_API_KEY}"
                },
                timeout=TIMEOUT_SEC
            )

            if response.status_code == 200:
                data = response.json()
                choices = data.get('choices', [])
                if choices:
                    content = choices[0].get('message', {}).get('content', '')

                    # Parse JSON response
                    try:
                        if content.startswith('{'):
                            json_part = content[:content.rfind('}')+1]
                            result = json.loads(json_part)
                            _log(f"Modelo {model} respondió OK")
                            return result
                        elif '```json' in content:
                            # Extraer de bloque markdown
                            start = content.find('```json') + 7
                            end = content.find('```', start)
                            if end > start:
                                result = json.loads(content[start:end].strip())
                                _log(f"Modelo {model} respondió OK (markdown)")
                                return result
                    except json.JSONDecodeError:
                        _log(f"JSON inválido de {model}: {content[:100]}")
                        continue

            elif response.status_code == 429:
                _log(f"Rate limit en {model}, probando siguiente...")
                time.sleep(2)
                continue
            else:
                _log(f"Error {response.status_code} de {model}")

        except requests.Timeout:
            _log(f"Timeout en {model}")
            continue
        except Exception as e:
            _log(f"Error llamando {model}: {e}")
            continue

    return None

def _read_trades() -> List[Dict]:
    """Lee historial de trades"""
    try:
        if not TRADES_JSON.exists():
            return []
        with open(TRADES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
            return data.get("trades", [])
    except Exception as e:
        _log(f"Error leyendo trades: {e}")
        return []

def _should_run(last_run_time: Optional[float]) -> bool:
    """Determina si debe ejecutar análisis"""
    if last_run_time is None:
        return True

    elapsed = time.time() - last_run_time
    min_elapsed = BATCH_MIN_MINUTES * 60

    trades = _read_trades()
    if len(trades) % BATCH_N_TRADES < 5:
        return elapsed > min_elapsed * 0.5

    return elapsed > min_elapsed

def main():
    """Bucle principal de mejora"""
    if not ENABLED:
        _log("Deshabilitado (IMPROVEMENT_ENABLED=false)")
        return

    provider = _find_ai_provider()
    if not provider:
        _log("IA NO disponible. Esperando...")
        while True:
            time.sleep(30)
            provider = _find_ai_provider()
            if provider:
                break

    _log(f"Proveedor IA detectado: {provider}")
    _log("Bucle de mejora iniciado")

    last_run = None

    while True:
        try:
            if not _should_run(last_run):
                time.sleep(60)
                continue

            trades = _read_trades()
            if len(trades) < BATCH_N_TRADES:
                _log(f"Esperando {BATCH_N_TRADES - len(trades)} trades ({len(trades)}/{BATCH_N_TRADES})")
                time.sleep(60)
                continue

            # Tomar últimos N trades
            batch = trades[-BATCH_N_TRADES:]
            wins = sum(1 for t in batch if t.get('outcome') == 'WIN')
            wr = (wins / len(batch)) * 100 if batch else 0

            _log(f"Analizando {len(batch)} trades (WR: {wr:.1f}%)")

            # Preparar prompt
            prompt = f"""Analiza estos {len(batch)} trades de opciones binarias:
Win Rate: {wr:.1f}%
Wins: {wins}/{len(batch)}
Últimos resultados: {json.dumps(batch[-5:], default=str)[:500]}

Propuestas de mejora para next session:
1. Qué estrategia reforzar
2. Qué condiciones agregar/quitar
3. Ajustes recomendados
Devuelve JSON con: {{recommendations: [...], confidence: 0-1}}"""

            # Llamar IA
            result = _call_ai(prompt)

            if result:
                _log(f"Recomendaciones: {json.dumps(result)[:200]}")
                last_run = time.time()
            else:
                _log("No se pudo obtener recomendaciones")

            time.sleep(60)

        except Exception as e:
            _log(f"Error en bucle: {e}")
            time.sleep(60)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='[%(name)s] %(message)s'
    )
    main()
