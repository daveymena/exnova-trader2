"""Bucle de mejora continua - Usa OpenCode en EasyPanel
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
# CONFIGURACIÓN OPENCODE EN EASYPANEL
# ═══════════════════════════════════════════════════════════════════════════════

# URLs de OpenCode en EasyPanel
OPENCODE_URLS = [
    os.getenv("OPENCODE_BASE_URL", "http://opencode:3000"),  # Interno EasyPanel
    "http://opencode-clean:3000",  # Alternativo
    "http://localhost:3000",  # Dev local
]

OPENCODE_API_KEY = os.getenv("OPENCODE_API_KEY", "")

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

def _find_opencode_url() -> Optional[str]:
    """Detecta URL disponible de OpenCode"""
    for url in OPENCODE_URLS:
        try:
            response = requests.get(f"{url}/api/health", timeout=2)
            if response.status_code == 200:
                _log(f"OpenCode encontrado en {url}")
                return url
        except:
            pass

    _log("ADVERTENCIA: OpenCode NO encontrado en ninguna URL")
    return None

def _call_opencode(opencode_url: str, prompt: str) -> Optional[Dict]:
    """Llama a OpenCode con chat endpoint"""
    try:
        headers = {
            "Content-Type": "application/json",
        }

        # Usar endpoint de chat de OpenCode
        response = requests.post(
            f"{opencode_url}/api/chat",
            json={
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                "model": "default"
            },
            headers=headers,
            timeout=TIMEOUT_SEC
        )

        if response.status_code == 200:
            data = response.json()
            content = data.get('message', {}).get('content', '')

            # Parse JSON response
            try:
                if content.startswith('{'):
                    json_part = content[:content.rfind('}')+1]
                    result = json.loads(json_part)
                    return result
            except:
                _log(f"No JSON en respuesta: {content[:100]}")
                return None

    except Exception as e:
        _log(f"Error llamando OpenCode: {e}")

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

    opencode_url = _find_opencode_url()
    if not opencode_url:
        _log("OpenCode NO disponible. Esperando...")
        while True:
            time.sleep(30)
            opencode_url = _find_opencode_url()
            if opencode_url:
                break

    _log(f"OpenCode detectado: {opencode_url}")
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

            # Llamar OpenCode
            result = _call_opencode(opencode_url, prompt)

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
