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
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[2]  # /app
BOT = Path(__file__).resolve().parents[1]   # /app/bot
TRADES_JSON = BOT / "brain" / "trade_history.json"
LEARNING_JSON = BOT / "data" / "learning_progress.json"
PID_FILE = BOT / "bot.pid"

PORT = int(os.getenv("MONITOR_PORT", os.getenv("PORT", "8000")))


def _read_json(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        return {"__read_error__": str(e)}


def _bot_alive() -> bool:
    try:
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


@app.get("/api/trades")
def trades(limit: int = 50):
    data = _read_json(TRADES_JSON)
    rows = data.get("trades", [])
    return {"trades": rows[-min(max(limit, 1), 500):], "count": len(rows)}


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


DASHBOARD_HTML = """<!doctype html>
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
    return HTMLResponse(DASHBOARD_HTML)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")