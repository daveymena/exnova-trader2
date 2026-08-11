"""
Monitor HTTP ligero para el bot PCR (read-only).
Lee los JSON de persistencia del bot y expone un dashboard + API JSON.
No toca la logica de trading; corre en paralelo con run_live.py.

Endpoints:
  GET /                -> dashboard HTML auto-contenido
  GET /api/health      -> {status, ts}
  GET /api/status      -> metricas (balance opcional, WR, trades, pnl, ia)
  GET /api/trades       -> ultimos trades
  GET /api/config       -> config de IA y trading (sin secretos)
"""
import json
import os
import time
import hmac
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv(dotenv_path="/app/.env")

ROOT = Path(__file__).resolve().parents[2]  # /app
BOT = Path(__file__).resolve().parents[1]   # /app/bot
TRADES_JSON = BOT / "brain" / "trade_history.json"
PRACTICE_JSON = BOT / "brain" / "practice_trades.json"
LEARNING_JSON = BOT / "data" / "learning_progress.json"
# run_live.py escribe su PID en run_live.lock (lock de instancia unica)
PID_FILE = BOT / "run_live.lock"
# improvement_loop escribe un heartbeat aqui cada minuto
IMPROVE_HEARTBEAT = BOT / "brain" / "improvement_heartbeat.json"
BOT_HEARTBEAT = ROOT / "data" / "bot_heartbeat.json"
ADJUSTMENTS_JSON = BOT / "brain" / "strategy_adjustments.json"
RUNTIME_CONFIG = ROOT / "data" / "runtime_config.json"
DASHBOARD_HTML = Path(__file__).with_name("dashboard.html")
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")

try:
    from .architect import architect
except ImportError:  # ejecución directa (python bot/monitor/server.py)
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from architect import architect

PORT = int(os.getenv("MONITOR_PORT", os.getenv("PORT", "8000")))


def _read_json(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        return {"__read_error__": str(e)}


def _admin_allowed(request: Request) -> bool:
    supplied = request.headers.get("x-dashboard-token", "")
    return bool(DASHBOARD_TOKEN) and hmac.compare_digest(supplied, DASHBOARD_TOKEN)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _bot_alive() -> bool:
    try:
        heartbeat = _read_json(BOT_HEARTBEAT)
        heartbeat_ts = heartbeat.get("ts") if isinstance(heartbeat, dict) else None
        if isinstance(heartbeat_ts, (int, float)) and time.time() - heartbeat_ts < 120:
            return True
        if not PID_FILE.exists():
            return False
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


app = FastAPI(title="Exnova PCR Bot Monitor", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.get("/api/health")
def health():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/api/status")
def status():
    data = _read_json(TRADES_JSON)
    learning = _read_json(LEARNING_JSON)
    total = data.get("total_trades", 0)
    wins = data.get("total_wins", 0)
    losses = data.get("total_losses", 0)
    pnl = data.get("total_pnl", 0.0)
    wr = round(wins / total * 100, 1) if total else 0.0
    updated = data.get("updated")
    trades = data.get("trades", [])
    last_trade = trades[-1] if trades else None
    # info de IA (from env, sin exponer key)
    ai = {
        "enabled": bool(os.getenv("OPENCODE_API_KEY")),
        "endpoint": os.getenv("OPENCODE_BASE_URL", ""),
        "model_fast": os.getenv("OPENCODE_MODEL_FAST", os.getenv("OPENCODE_MODEL", "")),
        "model_deep": os.getenv("OPENCODE_MODEL_DEEP", ""),
        "supervisor_enabled": os.getenv("SUPERVISOR_ENABLED", "false").lower() == "true",
        "ai_calls_in_history": len([t for t in trades if t.get("ai_used")]),
    }
    return {
        "bot_alive": _bot_alive(),
        "bot_heartbeat": _read_json(BOT_HEARTBEAT),
        "account_type": os.getenv("ACCOUNT_TYPE", "PRACTICE"),
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": wr,
        "total_pnl": round(pnl, 2),
        "last_trade": last_trade,
        "last_update": datetime.fromtimestamp(updated, timezone.utc).isoformat() if isinstance(updated, (int, float)) else updated,
        "learning": learning if learning else None,
        "ai": ai,
        "assets": os.getenv("ASSETS", os.getenv("DEFAULT_ASSET", "")),
    }


@app.get("/api/practice")
def practice_status():
    """Resultados virtuales para forward testing sin riesgo de broker."""
    data = _read_json(PRACTICE_JSON)
    rows = data.get("trades", []) if isinstance(data, dict) else []
    closed = [t for t in rows if t.get("result") in {"WIN", "LOSS"}]
    wins = sum(t.get("result") == "WIN" for t in closed)
    losses = sum(t.get("result") == "LOSS" for t in closed)
    pnl = sum(float(t.get("pnl", 0) or 0) for t in closed)
    return {
        "trades": len(rows),
        "closed": len(closed),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(closed) * 100, 1) if closed else 0.0,
        "pnl": round(pnl, 2),
        "pending": len(rows) - len(closed),
        "recent": rows[-20:],
    }


@app.get("/api/trades")
def trades(limit: int = 50):
    data = _read_json(TRADES_JSON)
    rows = data.get("trades", [])
    return {"trades": rows[-min(max(limit, 1), 500):], "count": len(rows)}


@app.get("/api/improvement")
def improvement():
    """Estado del bucle de mejora IA: heartbeat + refinamientos aplicados."""
    hb = _read_json(IMPROVE_HEARTBEAT)
    adj = _read_json(ADJUSTMENTS_JSON)
    now = time.time()
    hb_ts = hb.get("ts") if isinstance(hb, dict) else None
    alive = isinstance(hb_ts, (int, float)) and (now - hb_ts) < 180
    # log del improvement loop (escrito por entrypoint a /app/data/improvement_loop.log)
    log_path = ROOT / "data" / "improvement_loop.log"
    log_tail = ""
    try:
        if log_path.exists():
            log_tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-20:])
    except Exception:
        pass
    return {
        "loop_alive": alive,
        "last_heartbeat": hb if hb else None,
        "cycle": adj.get("cycle", 0) if isinstance(adj, dict) else 0,
        "min_confidence": adj.get("min_confidence") if isinstance(adj, dict) else None,
        "expiry_by_asset": adj.get("expiry_by_asset") if isinstance(adj, dict) else {},
        "assets_pause": adj.get("assets_pause") if isinstance(adj, dict) else [],
        "lessons": (adj.get("lessons") or [])[-8:] if isinstance(adj, dict) else [],
        "recent_history": (adj.get("history") or [])[-3:] if isinstance(adj, dict) else [],
        "loop_log_tail": log_tail,
    }


@app.get("/api/botlog")
def botlog():
    """Tail del log del bot (escrito por entrypoint a /app/data/bot.log)."""
    log_path = ROOT / "data" / "bot.log"
    tail = ""
    try:
        if log_path.exists():
            tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-60:])
    except Exception:
        pass
    return {"exists": log_path.exists(), "tail": tail}


@app.get("/api/config")
def config():
    def _hide(v):
        return f"{str(v)[:6]}..." if v else ""
    return {
        "account_type": os.getenv("ACCOUNT_TYPE", "PRACTICE"),
        "broker": os.getenv("BROKER_NAME", "exnova"),
        "email": os.getenv("EXNOVA_EMAIL", ""),
        "assets": os.getenv("ASSETS", os.getenv("DEFAULT_ASSET", "")),
        "ai": {
            "endpoint": os.getenv("OPENCODE_BASE_URL", ""),
            "model_fast": os.getenv("OPENCODE_MODEL_FAST", os.getenv("OPENCODE_MODEL", "")),
            "model_deep": os.getenv("OPENCODE_MODEL_DEEP", ""),
            "key_hint": _hide(os.getenv("OPENCODE_API_KEY")),
        },
        "min_confidence": os.getenv("MIN_CONFIDENCE"),
        "max_consec_losses": os.getenv("MAX_CONSEC_LOSSES"),
        "cooldown_after_loss": os.getenv("COOLDOWN_AFTER_LOSS"),
        "min_between_trades": os.getenv("MIN_BETWEEN_TRADES"),
        "supervisor_enabled": os.getenv("SUPERVISOR_ENABLED", "false").lower() == "true",
        "monitor_port": PORT,
    }


@app.get("/api/runtime-config")
def runtime_config():
    current = _read_json(RUNTIME_CONFIG)
    return {
        "mode": current.get("mode", os.getenv("ACCOUNT_TYPE", "PRACTICE").lower()),
        "asset": current.get("asset", os.getenv("DEFAULT_ASSET", "EURUSD-OTC")),
        "strategy": current.get("strategy", "auto"),
        "stake": current.get("stake", float(os.getenv("FIXED_STAKE", "0") or 0)),
        "min_confidence": current.get("min_confidence", os.getenv("MIN_CONFIDENCE", "0.65")),
        "max_consecutive_losses": current.get("max_consecutive_losses", os.getenv("MAX_CONSEC_LOSSES", "4")),
        "cooldown_after_loss": current.get("cooldown_after_loss", os.getenv("COOLDOWN_AFTER_LOSS", "300")),
        "min_between_trades": current.get("min_between_trades", os.getenv("MIN_BETWEEN_TRADES", "180")),
        "ai_model": current.get("ai_model", os.getenv("OPENCODE_MODEL", "deepseek-v4-flash-free")),
        "updated_at": current.get("updated_at"),
        "reason": current.get("reason", ""),
        "apply_mode": "hot",
    }


@app.post("/api/runtime-config")
def update_runtime_config(payload: dict, request: Request):
    if not _admin_allowed(request):
        return JSONResponse({"error": "Dashboard token requerido"}, status_code=401)
    mode = str(payload.get("mode", "paper")).lower()
    if mode not in {"paper", "practice"}:
        return JSONResponse({"error": "Solo paper y practice se pueden configurar desde el dashboard."}, status_code=400)
    try:
        data = {
            "mode": mode,
            "asset": str(payload.get("asset", "EURUSD-OTC")).strip()[:80],
            "strategy": str(payload.get("strategy", "auto")).strip()[:80],
            "stake": round(min(max(float(payload.get("stake", 0)), 0.5), 100.0), 2),
            "min_confidence": min(max(float(payload.get("min_confidence", .65)), .5), .99),
            "max_consecutive_losses": min(max(int(payload.get("max_consecutive_losses", 4)), 1), 10),
            "cooldown_after_loss": min(max(int(payload.get("cooldown_after_loss", 300)), 30), 3600),
            "min_between_trades": min(max(int(payload.get("min_between_trades", 180)), 30), 3600),
            "reason": str(payload.get("reason", "")).strip()[:300],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except (TypeError, ValueError) as exc:
        return JSONResponse({"error": f"Configuración inválida: {exc}"}, status_code=400)
    _write_json(RUNTIME_CONFIG, data)
    return {"ok": True, "apply_mode": "hot", "config": data}


@app.post("/api/ai/test")
def test_ai(payload: dict, request: Request):
    if not _admin_allowed(request):
        return JSONResponse({"error": "Dashboard token requerido"}, status_code=401)
    """Test the configured OpenAI-compatible provider without exposing its key."""
    try:
        from app.services.ai_provider import AIProviderRegistry
        registry = AIProviderRegistry()
        result = registry.chat(
            [{"role": "user", "content": str(payload.get("prompt", "Responde OK."))[:1000]}],
            model=str(payload.get("model", "")).strip() or None,
            max_tokens=64,
            temperature=0,
        )
        if result is None:
            return JSONResponse({"ok": False, "error": "Todos los proveedores IA fallaron", "providers": registry.get_available_providers()}, status_code=502)
        return {"ok": True, "response": result, "providers": registry.get_available_providers()}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/api/architect/chat")
def architect_chat(payload: dict, request: Request):
    """Arquitecto IA: recibe una orden en lenguaje natural y la ejecuta
    (solo paper/practice). Misma filosofía que el Arquitecto de VentasPro:
    memoria -> análisis -> propuesta -> aprobación -> ejecución en caliente."""
    if not _admin_allowed(request):
        return JSONResponse({"error": "Dashboard token requerido"}, status_code=401)
    message = str(payload.get("message", "")).strip()[:500]
    if not message:
        return JSONResponse({"error": "Mensaje vacío"}, status_code=400)
    try:
        result = architect.chat(message)
        return result
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.get("/api/architect/state")
def architect_state(request: Request):
    """Estado real + análisis del arquitecto (read-only)."""
    if not _admin_allowed(request):
        return JSONResponse({"error": "Dashboard token requerido"}, status_code=401)
    try:
        return {"state": architect.get_state(), "analysis": architect.analyze(),
                "memory": architect.memory}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/api/architect/apply")
def architect_apply(payload: dict, request: Request):
    """Aplica una propuesta concreta dict (o la última propuesta) en caliente."""
    if not _admin_allowed(request):
        return JSONResponse({"error": "Dashboard token requerido"}, status_code=401)
    proposal = payload.get("proposal") or {}
    reason = str(payload.get("reason", "")).strip()[:300]
    if not isinstance(proposal, dict) or not proposal:
        return JSONResponse({"error": "Propuesta vacía. Ejecuta /api/architect/chat primero."}, status_code=400)
    try:
        res = architect.apply_proposal(proposal, reason=reason, mode_ok=True)
        return res
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


DASHBOARD_HTML_FALLBACK = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Exnova PCR Bot — Monitor</title>
<style>
  *{box-sizing:border-box;font-family:-apple-system,Segoe UI,Roboto,monospace}
  body{background:#0d1117;color:#c9d1d9;margin:0;padding:24px}
  .wrap{max-width:980px;margin:0 auto}
  h1{color:#58a6ff;font-size:20px;margin:0 0 4px}
  .sub{color:#8b949e;font-size:13px;margin-bottom:18px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
  .card .k{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
  .card .v{font-size:24px;font-weight:600;margin-top:4px}
  .ok{color:#3fb950}.bad{color:#f85149}.warn{color:#d29922}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #21262d}
  th{color:#8b949e;font-size:11px;text-transform:uppercase}
  .tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
  .win{background:#1a3a2a;color:#3fb950}.loss{background:#3a1a1a;color:#f85149}.draw{background:#2a2a1a;color:#d29922}
  .ai{background:#1a2233;color:#58a6ff}
  button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:8px 14px;cursor:pointer;font-size:13px}
  button:hover{background:#30363d}
  .cfg{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;font-size:13px}
  .cfg b{color:#58a6ff}
  pre{margin:0;white-space:pre-wrap}
</style></head><body><div class="wrap">
<h1>Exnova PCR Bot — Monitor</h1>
<div class="sub" id="upd">cargando...</div>
<div class="grid" id="cards"></div>
<button onclick="load()">Recargar</button>
<h3 style="color:#58a6ff;margin:18px 0 8px">Operaciones recientes</h3>
<table><thead><tr>
  <th>Hora</th><th>Activo</th><th>Dir</th><th class="r">Resultado</th><th class="r">PnL</th><th>IA</th>
</tr></thead><tbody id="tbl"></tbody></table>
<h3 style="color:#58a6ff;margin:18px 0 8px">Configuracion e IA</h3>
<div class="cfg" id="cfg"></div>
</div>
<script>
const fmt={year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'};
async function get(p){const r=await fetch(p);return r.json();}
function esc(s){return String(s??'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));}
async function load(){
  try{
    const [s,t,c]=await Promise.all([get('/api/status'),get('/api/trades?limit=30'),get('/api/config')]);
    const alive=s.bot_alive;
    document.getElementById('upd').textContent='Actualizado: '+new Date().toLocaleString('es-CO')+(alive?' | Bot vivo (PID)':' | Bot NO detectado');
    const wr=s.win_rate; const wrClass=wr>=60?'ok':wr>=50?'warn':'bad';
    const pnl=s.total_pnl; const pnlClass=pnl>=0?'ok':'bad';
    const cards=[
      ['Bot', alive?'VIVO':'CAIDO', alive?'ok':'bad'],
      ['Cuenta', s.account_type, ''],
      ['Trades', s.total_trades, ''],
      ['Win Rate', wr.toFixed(1)+'%', wrClass],
      ['Wins', s.wins||0, 'ok'],
      ['Losses', s.losses||0, 'bad'],
      ['PnL Total', (pnl>=0?'+':'')+pnl.toFixed(2), pnlClass],
      ['IA calls', (s.ai&&s.ai.ai_calls_in_history)||0, 'ai'],
    ];
    document.getElementById('cards').innerHTML=cards.map(x=>`<div class="card"><div class="k">${x[0]}</div><div class="v ${x[2]||''}">${x[1]}</div></div>`).join('');
    let rows=(t.trades||[]).slice().reverse();
    document.getElementById('tbl').innerHTML=rows.map(tr=>{
      const ts=tr.timestamp?new Date(tr.timestamp*1000).toLocaleString('es-CO',fmt):'-';
      const res=(tr.result||'').toUpperCase();
      const rc=res==='WIN'?'win':res==='LOSS'?'loss':'draw';
      const ai=tr.ai_used?'<span class="tag ai">IA</span>':'';
      const dir=tr.direction||'-';
      const pnlV=(tr.pnl||0); const pc=pnlV>=0?'ok':'bad';
      return `<tr><td>${esc(ts)}</td><td>${esc(tr.asset||'-')}</td><td>${esc(dir)}</td><td class="r"><span class="tag ${rc}">${res||'-'}</span></td><td class="r ${pc}">${pnlV>=0?'+':''}${pnlV.toFixed(2)}</td><td>${ai}</td></tr>`;
    }).join('')||'<tr><td colspan=6 style="color:#8b949e;text-align:center">Sin trades aun</td></tr>';
    const a=c.ai||{};
    document.getElementById('cfg').innerHTML=`<pre>
<b>Broker:</b> ${esc(c.broker)} | <b>Cuenta:</b> ${esc(c.account_type)} | <b>Email:</b> ${esc(c.email)}
<b>Activos:</b> ${esc(c.assets)}
<b>Min confidence:</b> ${esc(c.min_confidence)} | <b>Max consec losses:</b> ${esc(c.max_consec_losses)} | <b>Cooldown:</b> ${esc(c.cooldown_after_loss)}s
<b>IA endpoint:</b> ${esc(a.endpoint)}
<b>Modelo rapido:</b> ${esc(a.model_fast)} | <b>Modelo profundo:</b> ${esc(a.model_deep)}
<b>IA key:</b> ${esc(a.key_hint||'(no set)')} | <b>Supervisor:</b> ${c.supervisor_enabled?'ON':'OFF'}
<b>Monitor port:</b> ${esc(c.monitor_port)}</pre>`;
  }catch(e){document.getElementById('upd').textContent='Error: '+e;}
}
load(); setInterval(load, 5000);
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    if DASHBOARD_HTML.exists():
        return HTMLResponse(DASHBOARD_HTML.read_text(encoding="utf-8"))
    return HTMLResponse(DASHBOARD_HTML_FALLBACK)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
