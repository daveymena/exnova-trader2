"""MCP server de trading para OpenCode CLI.

Expone tools (JSON-RPC sobre stdio) para que el agente IA orquestado pueda:
- leer estadísticas y trades reales desde SQLite,
- proponer y aplicar cambios de configuración medibles,
- registrar auditoría.

No ejecuta operaciones de trading. No toca cuenta REAL.
"""
from __future__ import annotations

import json
import os
import sys
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

# Asegurar que app/ es importable cuando se ejecuta como script standalone.
_APP_DIR = Path(__file__).resolve().parent.parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app.data.repository import repository  # noqa: E402


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "trading-mcp"
SERVER_VERSION = "1.0.0"

# Archivo de overrides que el agente IA puede modificar (no toca código).
OVERRIDES_PATH = _APP_DIR / "data" / "ai_overrides.json"


# ─── Helpers de acceso a datos ──────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    repository.connect()
    return repository._conn  # type: ignore[attr-defined]


def _get_stats() -> dict[str, Any]:
    try:
        stats = repository.get_global_stats()
        return stats
    except Exception as e:  # pragma: no cover
        return {"error": f"get_global_stats failed: {e}"}


def _get_trades(limit: int = 50) -> list[dict[str, Any]]:
    conn = _conn()
    rows = conn.execute(
        "SELECT id, timestamp, asset, direction, strategy, expiry, payout, "
        "stake, result, execution_state, market_regime, confidence, "
        "entry_timing, features, entry_price, exit_price, entry_time, "
        "expiry_time, resolution_source, error "
        "FROM trade_results ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    cols = [d[0] for d in rows.description] if rows.description else []
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        try:
            d["features"] = json.loads(d.get("features") or "{}")
        except Exception:
            pass
        out.append(d)
    return out


def _get_perf_breakdown(dim: str = "strategy") -> list[dict[str, Any]]:
    allowed = {"strategy", "asset", "market_regime", "expiry", "direction"}
    dim = dim if dim in allowed else "strategy"
    conn = _conn()
    rows = conn.execute(
        f"SELECT {dim} AS dim, COUNT(*) AS n, "
        f"SUM(CASE WHEN execution_state='won' THEN 1 ELSE 0 END) AS wins, "
        f"COALESCE(SUM(result), 0) AS pnl, "
        f"COALESCE(AVG(confidence), 0) AS avg_conf "
        f"FROM trade_results WHERE resolution_source IN ('broker','candle') "
        f"GROUP BY {dim} ORDER BY n DESC",
    ).fetchall()
    return [dict(zip([d[0] for d in rows.description], r)) for r in rows]


def _get_recommendations(status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
    return repository.get_recommendations(status=status, limit=limit)


def _propose_change(agent: str, category: str, recommendation: str,
                    proposed_config_change: Any, severity: str = "info",
                    evidence: str = "") -> dict[str, Any]:
    change_str = proposed_config_change if isinstance(proposed_config_change, str) \
        else json.dumps(proposed_config_change, ensure_ascii=False)
    cycle_id = repository.next_cycle_id()
    rec_id = repository.add_recommendation(
        cycle_id=cycle_id, agent=agent, category=category,
        recommendation=recommendation, proposed_config_change=change_str,
        severity=severity, evidence=evidence,
    )
    repository.audit_log(cycle_id, agent, "proposal_created",
                         f"rec_id={rec_id} category={category} severity={severity}")
    return {"recommendation_id": rec_id, "cycle_id": cycle_id,
            "status": "pending", "note": "Change proposed, awaiting review."}


def _load_overrides() -> dict[str, Any]:
    if OVERRIDES_PATH.exists():
        try:
            return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_overrides(data: dict[str, Any]) -> None:
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                              encoding="utf-8")


def _apply_change(rec_id: int) -> dict[str, Any]:
    recs = repository.get_recommendations(status="pending", limit=1000)
    rec = next((r for r in recs if r["id"] == rec_id), None)
    if rec is None:
        return {"error": f"No pending recommendation with id={rec_id}"}
    try:
        change = json.loads(rec["proposed_config_change"] or "{}")
    except Exception as e:
        repository.update_recommendation_status(rec_id, "rejected",
                                                 f"invalid json: {e}")
        return {"error": f"invalid proposed_config_change JSON: {e}"}

    # Por seguridad: nunca aplicar cambios que afecten cuenta REAL.
    if str(change).lower().find("real") >= 0 and \
       str(change).lower().find("practice") < 0:
        repository.update_recommendation_status(rec_id, "rejected",
                                                "change touches REAL mode")
        return {"error": "Change touches REAL mode; rejected for safety."}

    # Fusionar en overrides json.
    overrides = _load_overrides()
    target = change.get("target", "general")
    overrides[target] = {**overrides.get(target, {}), **change.get("values", {})}
    _save_overrides(overrides)

    repository.update_recommendation_status(rec_id, "applied")
    repository.audit_log(rec["cycle_id"], rec["agent"], "change_applied",
                        f"rec_id={rec_id} target={target}")
    return {"recommendation_id": rec_id, "status": "applied",
            "target": target,
            "applied_values": change.get("values", {}),
            "overrides_path": str(OVERRIDES_PATH)}


def _reject_change(rec_id: int, reason: str) -> dict[str, Any]:
    recs = repository.get_recommendations(status="pending", limit=1000)
    rec = next((r for r in recs if r["id"] == rec_id), None)
    if rec is None:
        return {"error": f"No pending recommendation with id={rec_id}"}
    repository.update_recommendation_status(rec_id, "rejected", reason)
    repository.audit_log(rec["cycle_id"], rec["agent"], "change_rejected",
                         f"rec_id={rec_id} reason={reason}")
    return {"recommendation_id": rec_id, "status": "rejected", "reason": reason}


def _run_backtest(strategy: str = "", limit: int = 200) -> dict[str, Any]:
    """Intenta ejecutar un backtest rápido. Si no es seguro, registra la solicitud."""
    run_backtest_path = _APP_DIR / "run_backtest.py"
    if not run_backtest_path.exists():
        cycle_id = repository.next_cycle_id()
        repository.audit_log(cycle_id, "backtesting", "backtest_requested",
                             f"strategy={strategy} (run_backtest.py not found)")
        return {"status": "manual_required",
                "message": "run_backtest.py no encontrado. "
                           "Ejecuta el backtest manualmente."}
    try:
        proc = subprocess.run(
            [sys.executable, str(run_backtest_path), "--strategy", strategy,
             "--limit", str(limit)],
            cwd=str(_APP_DIR), capture_output=True, text=True, timeout=120,
        )
        cycle_id = repository.next_cycle_id()
        repository.audit_log(cycle_id, "backtesting", "backtest_executed",
                             f"strategy={strategy} rc={proc.returncode}")
        return {"status": "executed", "returncode": proc.returncode,
                "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-1000:]}
    except Exception as e:
        return {"error": f"backtest execution failed: {e}"}


def _get_audit_log(limit: int = 100) -> list[dict[str, Any]]:
    return repository.get_audit_log(limit=limit)


# ─── Definición de tools (schema MCP) ────────────────────────────────────────

def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "trading_get_stats",
            "description": "Devuelve métricas de edge (win rate, profit factor, "
                           "expectancy, drawdown, nº trades) desde la base SQLite.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "trading_get_trades",
            "description": "Devuelve los últimos N trades con features completas.",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 50}},
                "required": [],
            },
        },
        {
            "name": "trading_get_perf_breakdown",
            "description": "Desglose de rendimiento por dimensión "
                           "(strategy, asset, market_regime, expiry, direction).",
            "inputSchema": {
                "type": "object",
                "properties": {"dim": {"type": "string", "default": "strategy"}},
                "required": [],
            },
        },
        {
            "name": "trading_get_recommendations",
            "description": "Lista recomendaciones de mejora pendientes (o por estado).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "default": "pending"},
                    "limit": {"type": "integer", "default": 100},
                },
                "required": [],
            },
        },
        {
            "name": "trading_propose_change",
            "description": "Registra una propuesta de cambio de configuración. "
                           "No la aplica: queda pendiente de revisión/aplicación.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "category": {"type": "string"},
                    "recommendation": {"type": "string"},
                    "proposed_config_change": {"type": "string",
                        "description": "JSON string: {target, values}"},
                    "severity": {"type": "string", "default": "info"},
                    "evidence": {"type": "string", "default": ""},
                },
                "required": ["agent", "category", "recommendation",
                             "proposed_config_change"],
            },
        },
        {
            "name": "trading_apply_change",
            "description": "Aplica una propuesta de cambio (id) escribiéndola en "
                           "data/ai_overrides.json. Rechaza cambios que afecten "
                           "cuenta REAL.",
            "inputSchema": {
                "type": "object",
                "properties": {"recommendation_id": {"type": "integer"}},
                "required": ["recommendation_id"],
            },
        },
        {
            "name": "trading_reject_change",
            "description": "Rechaza una propuesta de cambio con un motivo.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "recommendation_id": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["recommendation_id", "reason"],
            },
        },
        {
            "name": "trading_run_backtest",
            "description": "Ejecuta (o registra la solicitud de) un backtest.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "strategy": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 200},
                },
                "required": [],
            },
        },
        {
            "name": "trading_get_audit_log",
            "description": "Devuelve los últimos N eventos de auditoría IA.",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 100}},
                "required": [],
            },
        },
    ]


# ─── Dispatch de tools ──────────────────────────────────────────────────────

def _handle_tool_call(name: str, args: dict[str, Any]) -> Any:
    if name == "trading_get_stats":
        return _get_stats()
    if name == "trading_get_trades":
        return _get_trades(int(args.get("limit", 50)))
    if name == "trading_get_perf_breakdown":
        return _get_perf_breakdown(str(args.get("dim", "strategy")))
    if name == "trading_get_recommendations":
        return _get_recommendations(str(args.get("status", "pending")),
                                    int(args.get("limit", 100)))
    if name == "trading_propose_change":
        return _propose_change(
            agent=str(args.get("agent", "supervisor")),
            category=str(args.get("category", "general")),
            recommendation=str(args.get("recommendation", "")),
            proposed_config_change=args.get("proposed_config_change", "{}"),
            severity=str(args.get("severity", "info")),
            evidence=str(args.get("evidence", "")),
        )
    if name == "trading_apply_change":
        return _apply_change(int(args["recommendation_id"]))
    if name == "trading_reject_change":
        return _reject_change(int(args["recommendation_id"]),
                              str(args.get("reason", "")))
    if name == "trading_run_backtest":
        return _run_backtest(str(args.get("strategy", "")),
                             int(args.get("limit", 200)))
    if name == "trading_get_audit_log":
        return _get_audit_log(int(args.get("limit", 100)))
    return {"error": f"unknown tool: {name}"}


# ─── Bucle MCP stdio (Content-Length framing) ───────────────────────────────

def _send(msg: dict[str, Any]) -> None:
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode())
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _read_msg() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n", b""):
            break
        if b":" in line:
            k, v = line.decode("utf-8", "replace").split(":", 1)
            headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def main() -> None:
    sys.stderr.write(f"[{SERVER_NAME}] MCP server started (stdio)\n")
    sys.stderr.flush()
    while True:
        try:
            msg = _read_msg()
        except Exception as e:
            sys.stderr.write(f"[{SERVER_NAME}] read error: {e}\n")
            continue
        if msg is None:
            break
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {}) or {}

        if method == "initialize":
            _send({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    "capabilities": {"tools": {}},
                },
            })
            continue
        if method == "tools/list":
            _send({"jsonrpc": "2.0", "id": msg_id,
                   "result": {"tools": _tool_definitions()}})
            continue
        if method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {}) or {}
            try:
                result = _handle_tool_call(tool_name, tool_args)
                _send({"jsonrpc": "2.0", "id": msg_id,
                       "result": {"content": [
                           {"type": "text",
                            "text": json.dumps(result, ensure_ascii=False,
                                               default=str)}
                       ]}})
            except Exception as e:
                _send({"jsonrpc": "2.0", "id": msg_id,
                       "error": {"code": -32000, "message": str(e)}})
            continue
        if method == "notifications/initialized":
            continue
        if msg_id is not None:
            _send({"jsonrpc": "2.0", "id": msg_id,
                   "error": {"code": -32601,
                             "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main()
