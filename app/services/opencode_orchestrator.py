"""Orquestador OpenCode CLI para supervisión de trading.

Construye un prompt de supervisión con datos reales (SQLite), lanza OpenCode CLI
(modelo free por defecto: deepseek-v4-flash-free), captura la respuesta, parsea
propuestas de cambio en JSON y las registra como recomendaciones pendientes.

El agente NO ejecuta trades ni modifica lógica de ejecución: solo propone
cambres de filtros/umbrales que quedan en data/ai_overrides.json tras revisión.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_APP_DIR = Path(__file__).resolve().parent.parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app.data.repository import repository  # noqa: E402

MODEL_DEFAULT = os.getenv("OPENCODE_MODEL", "deepseek-v4-flash-free")
TIMEOUT_DEFAULT = int(os.getenv("OPENCODE_TIMEOUT", "300"))
AGENTS_MD_PATH = _APP_DIR / "AGENTS.md"


def _load_agents_md() -> str:
    if AGENTS_MD_PATH.exists():
        text = AGENTS_MD_PATH.read_text(encoding="utf-8")
        # Resumir: primeras ~3000 chars para no saturar el contexto.
        return text[:3000]
    return (
        "Plataforma de IA para Opciones Binarias (Exnova). El sistema opera en "
        "modo PRACTICE. Agentes: analista de mercado, investigador, estratega, "
        "backtesting, estadístico, gestor de riesgo, supervisor general. "
        "Filosofía: todo cambio respaldado por datos y backtesting."
    )


def _build_prompt(stats: dict, breakdown: list[dict],
                  trades: list[dict], recs: list[dict]) -> str:
    agents_md = _load_agents_md()
    return f"""Eres el SUPERVISOR GENERAL de una plataforma de trading de opciones
binarias (Exnova, modo PRACTICE). Operas con OpenCode CLI y tienes acceso a un
MCP de trading con tools: trading_get_stats, trading_get_trades,
trading_get_perf_breakdown, trading_get_recommendations,
trading_propose_change, trading_apply_change, trading_reject_change,
trading_run_backtest, trading_get_audit_log.

CONTEXTO DEL PROYECTO:
{agents_md}

ESTADÍSTICAS ACTUALES (evidencia real, broker/candle):
{json.dumps(stats, ensure_ascii=False, indent=2, default=str)}

DESGLANCE DE RENDIMIENTO POR ESTRATEGIA/ACTIVO:
{json.dumps(breakdown[:10], ensure_ascii=False, indent=2, default=str)}

ÚLTIMOS TRADES:
{json.dumps(trades[:15], ensure_ascii=False, indent=2, default=str)}

RECOMENDACIONES PENDIENTES:
{json.dumps(recs[:10], ensure_ascii=False, indent=2, default=str)}

TU MISIÓN ( Supervisor General ):
1. Analiza los datos. Identifica debilidades: estrategias perdedoras, horas
   malas, activos con bajo win rate, mala gestión de riesgo, inconsistencias.
2. Propón mejoras CONCRETAS y MEDIBLES. Cada propuesta debe ser un bloque
   JSON con esta estructura exacta:
   ```json
   {{
     "agent": "supervisor_general",
     "category": "filtro|threshold|estrategia|riesgo|horario|activo",
     "severity": "info|warning|critical",
     "recommendation": "descripción breve de la mejora",
     "proposed_config_change": {{
       "target": "filters|thresholds|risk|strategy",
       "values": {{ "clave": "valor" }}
     }},
     "evidence": "qué dato respalda este cambio"
   }}
   ```
3. NO ejecutes trades. NO modifiques archivo de ejecución. NO toques cuenta
   REAL. Usa trading_propose_change para registrar cada propuesta.
4. Sé honesto: si una muestra es insuficiente (n<30), dilo. No inventes edge.
5. Prioriza CALIDAD sobre CANTIDAD: mejor proponer 2 cambios sólidos que 10
   especulativos.

Responde primero un breve análisis (3-5 lineas) y luego las propuestas en
bloques JSON. Si no hay datos suficientes, indícalo y no propongas cambios.
"""


def _parse_proposals(text: str) -> list[dict[str, Any]]:
    """Extrae bloques JSON de propuestas de la respuesta del agente."""
    proposals: list[dict[str, Any]] = []
    # Bloques ```json ... ```
    for m in re.finditer(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL):
        try:
            proposals.append(json.loads(m.group(1)))
        except Exception:
            pass
    # JSON suelto que contenga los campos esperados.
    if not proposals:
        for m in re.finditer(r'\{[^{}]*"recommendation"[^{}]*\}', text, re.DOTALL):
            try:
                proposals.append(json.loads(m.group(0)))
            except Exception:
                pass
    # Filtrar: solo los que tengan 'recommendation'.
    return [p for p in proposals if isinstance(p, dict) and "recommendation" in p]


def _register_proposals(cycle_id: int, proposals: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for p in proposals:
        try:
            change = p.get("proposed_config_change", {})
            change_str = change if isinstance(change, str) else json.dumps(
                change, ensure_ascii=False)
            rec_id = repository.add_recommendation(
                cycle_id=cycle_id,
                agent=str(p.get("agent", "supervisor_general")),
                category=str(p.get("category", "general")),
                recommendation=str(p.get("recommendation", "")),
                proposed_config_change=change_str,
                severity=str(p.get("severity", "info")),
                evidence=str(p.get("evidence", "")),
            )
            ids.append(rec_id)
            repository.audit_log(cycle_id, p.get("agent", "supervisor"),
                                 "proposal_created", f"rec_id={rec_id}")
        except Exception as e:
            repository.audit_log(cycle_id, "orchestrator",
                                 "proposal_register_error", str(e))
    return ids


def _launch_opencode(prompt: str) -> tuple[str, int]:
    """Lanza `opencode run` (no interactivo) y captura stdout."""
    env = os.environ.copy()
    cmd = [os.getenv("OPENCODE_BIN", "opencode"), "run", prompt]
    try:
        proc = subprocess.run(
            cmd, cwd=str(_APP_DIR), capture_output=True, text=True,
            timeout=TIMEOUT_DEFAULT, env=env,
        )
        return proc.stdout + (proc.stderr or ""), proc.returncode
    except FileNotFoundError:
        return ("[orchestrator] opencode CLI no encontrado en PATH", 127)
    except subprocess.TimeoutExpired:
        return ("[orchestrator] timeout", 124)
    except Exception as e:
        return (f"[orchestrator] error lanzando opencode: {e}", 1)


def run_cycle() -> dict[str, Any]:
    """Ejecuta un ciclo completo de supervisión IA.

    Returns: reporte estructurado del ciclo.
    """
    t0 = time.time()
    cycle_id = repository.next_cycle_id()
    repository.audit_log(cycle_id, "supervisor", "cycle_started", "")

    stats = repository.get_global_stats()
    breakdown: list[dict] = []
    trades: list[dict] = []
    recs: list[dict] = []
    try:
        # Reutiliza helpers del MCP para desglose y trades.
        from app.services.mcp_server_trading import _get_perf_breakdown, _get_trades
        breakdown = _get_perf_breakdown("strategy")
        trades = _get_trades(30)
        recs = repository.get_recommendations(status="pending", limit=50)
    except Exception as e:
        repository.audit_log(cycle_id, "orchestrator", "data_load_error",
                             f"stats ok, breakdown/trades err: {e}")

    prompt = _build_prompt(stats, breakdown, trades, recs)
    repository.audit_log(cycle_id, "orchestrator", "prompt_built",
                         f"len={len(prompt)} model={MODEL_DEFAULT}")

    response, rc = _launch_opencode(prompt)
    repository.audit_log(cycle_id, "orchestrator", "agent_response",
                         f"rc={rc} len={len(response)}")
    repository.audit_log(cycle_id, "orchestrator", "agent_response_text",
                         response[:2000])

    proposals = _parse_proposals(response)
    rec_ids = _register_proposals(cycle_id, proposals)

    duration = round(time.time() - t0, 1)
    report = {
        "cycle_id": cycle_id,
        "model": MODEL_DEFAULT,
        "returncode": rc,
        "response_len": len(response),
        "n_proposals": len(proposals),
        "proposal_ids": rec_ids,
        "duration_sec": duration,
    }
    repository.audit_log(cycle_id, "supervisor", "cycle_completed",
                         json.dumps(report, ensure_ascii=False))
    print(f"[orchestrator] ciclo {cycle_id} OK | {len(proposals)} propuestas | "
          f"{duration}s rc={rc}")
    return report


if __name__ == "__main__":
    print(json.dumps(run_cycle(), indent=2, ensure_ascii=False))
