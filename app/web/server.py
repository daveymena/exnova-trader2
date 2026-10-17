"""Web dashboard + API for the Exnova trading bot.

Provides:
  - Login form (authenticates against DASHBOARD_USER / DASHBOARD_PASSWORD,
    falling back to EXNOVA_EMAIL / EXNOVA_PASSWORD).
  - Dashboard with live status, trades, config, strategies and Exnova test.
  - JSON API consumed by the dashboard.
"""
import json
import os
import time
import asyncio
import hmac
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]          # repo root
BOT = ROOT / "bot"
TRADES_JSON = BOT / "brain" / "trade_history.json"
PRACTICE_JSON = BOT / "brain" / "practice_trades.json"
LEARNING_JSON = BOT / "data" / "learning_progress.json"
PID_FILE = BOT / "run_live.lock"
IMPROVE_HEARTBEAT = BOT / "brain" / "improvement_heartbeat.json"
BOT_HEARTBEAT = ROOT / "data" / "bot_heartbeat.json"
ADJUSTMENTS_JSON = BOT / "brain" / "strategy_adjustments.json"
RUNTIME_CONFIG = ROOT / "data" / "runtime_config.json"

load_dotenv(ROOT / ".env")
load_dotenv(Path("/app/.env"))

DASHBOARD_USER = os.getenv("DASHBOARD_USER", os.getenv("EXNOVA_EMAIL", "admin"))
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", os.getenv("EXNOVA_PASSWORD", ""))
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "change-me-secret")
SESSION_SECRET = os.getenv("SESSION_SECRET", DASHBOARD_TOKEN or "session-secret")
PORT = int(os.getenv("MONITOR_PORT", os.getenv("PORT", "8000")))

_BOT_THREAD = None
_BOT_INSTANCE = None
_BOT_STATUS = {"running": False, "mode": None, "error": None}


def _read_json(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        return {"__read_error__": str(e)}


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


def _session_token(user: str) -> str:
    return hmac.new(SESSION_SECRET.encode(), user.encode(), hashlib.sha256).hexdigest()


def _is_authed(request: Request) -> bool:
    cookie = request.cookies.get("exnova_session", "")
    if not cookie or not DASHBOARD_USER:
        return False
    expected = _session_token(DASHBOARD_USER)
    return hmac.compare_digest(cookie, expected)


def _admin_allowed(request: Request) -> bool:
    supplied = request.headers.get("x-dashboard-token", "")
    if DASHBOARD_TOKEN and hmac.compare_digest(supplied, DASHBOARD_TOKEN):
        return True
    return _is_authed(request)


app = FastAPI(title="Exnova Trading Bot - Web", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# ------------------------------------------------------------------ auth
@app.get("/login", response_class=HTMLResponse)
def login_page():
    return HTMLResponse(LOGIN_HTML)


@app.post("/login")
def login_submit(username: str = Form(...), password: str = Form(...)):
    if (username == DASHBOARD_USER and password == DASHBOARD_PASSWORD
            and DASHBOARD_PASSWORD):
        resp = RedirectResponse(url="/", status_code=303)
        resp.set_cookie("exnova_session", _session_token(DASHBOARD_USER),
                        httponly=True, samesite="lax")
        return resp
    return HTMLResponse(LOGIN_HTML.replace("{{ERROR}}",
                                            "Credenciales invalidas"), status_code=401)


@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie("exnova_session")
    return resp


# ------------------------------------------------------------------ api
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
    trades = data.get("trades", [])
    last_trade = trades[-1] if trades else None
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
        "last_update": data.get("updated"),
        "learning": learning if learning else None,
        "ai": ai,
        "assets": os.getenv("ASSETS", os.getenv("DEFAULT_ASSET", "")),
    }


@app.get("/api/practice")
def practice_status():
    data = _read_json(PRACTICE_JSON)
    rows = data.get("trades", []) if isinstance(data, dict) else []
    closed = [t for t in rows if t.get("result") in {"WIN", "LOSS"}]
    wins = sum(t.get("result") == "WIN" for t in closed)
    losses = sum(t.get("result") == "LOSS" for t in closed)
    pnl = sum(float(t.get("pnl", 0) or 0) for t in closed)
    return {
        "trades": len(rows), "closed": len(closed), "wins": wins, "losses": losses,
        "win_rate": round(wins / len(closed) * 100, 1) if closed else 0.0,
        "pnl": round(pnl, 2), "pending": len(rows) - len(closed),
        "recent": rows[-20:],
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


@app.get("/api/strategies")
def strategies():
    names = []
    try:
        from app.strategies import (breakout_direct, breakout_retest, mean_reversion,
                                    no_trade, sr_bounce, trend_continuation)
        for m in (breakout_direct, breakout_retest, mean_reversion, no_trade,
                  sr_bounce, trend_continuation):
            names.append(m.__name__.split(".")[-1])
    except Exception as e:
        names.append(f"error:{e}")
    return {"strategies": names}


@app.post("/api/exnova/test")
def exnova_test(request: Request):
    if not _admin_allowed(request):
        return JSONResponse({"error": "auth requerida"}, status_code=401)
    email = os.getenv("EXNOVA_EMAIL", "")
    password = os.getenv("EXNOVA_PASSWORD", "")
    if not email or not password:
        return JSONResponse({"ok": False, "error": "sin credenciales"}, status_code=400)
    try:
        import sys
        sys.path.insert(0, str(ROOT / "bot"))
        from app.services.exnova_broker import ExnovaBroker
        b = ExnovaBroker(email=email, password=password,
                         account_type=os.getenv("ACCOUNT_TYPE", "PRACTICE"))
        ok = b.connect()
        bal = b.get_balance() if ok else None
        b.disconnect()
        return {"ok": bool(ok), "balance": bal}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/exnova/connect")
def exnova_connect(payload: dict, request: Request):
    if not _admin_allowed(request):
        return JSONResponse({"error": "auth requerida"}, status_code=401)
    email = str(payload.get("email", "")).strip()
    password = str(payload.get("password", "")).strip()
    account_type = str(payload.get("account_type", "PRACTICE")).upper()
    if not email or not password:
        return JSONResponse({"ok": False, "error": "email y password requeridos"}, status_code=400)
    try:
        import sys
        sys.path.insert(0, str(ROOT / "bot"))
        from app.services.exnova_broker import ExnovaBroker
        b = ExnovaBroker(email=email, password=password, account_type=account_type)
        ok = b.connect()
        bal = b.get_balance() if ok else None
        assets = b.get_open_assets(min_profit=70) if ok else []
        b.disconnect()
        if ok:
            os.environ["EXNOVA_EMAIL"] = email
            os.environ["EXNOVA_PASSWORD"] = password
            os.environ["ACCOUNT_TYPE"] = account_type
            return {"ok": True, "balance": bal,
                    "assets_count": len(assets),
                    "sample_assets": [a["name"] for a in assets[:8]]}
        return {"ok": False, "balance": None, "assets_count": 0,
                "sample_assets": [],
                "error": "No se pudo conectar (credenciales, red o tipo de cuenta)"}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


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
        return JSONResponse({"error": "auth requerida"}, status_code=401)
    mode = str(payload.get("mode", "paper")).lower()
    if mode not in {"paper", "practice"}:
        return JSONResponse({"error": "Solo paper y practice"}, status_code=400)
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
        return JSONResponse({"error": f"Config invalida: {exc}"}, status_code=400)
    _write_json(RUNTIME_CONFIG, data)
    return {"ok": True, "apply_mode": "hot", "config": data}


# ------------------------------------------------------------------ pages
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not _is_authed(request):
        return RedirectResponse(url="/login", status_code=303)
    return HTMLResponse(DASHBOARD_HTML)


# ------------------------------------------------------------------ html
LOGIN_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Exnova Bot - Login</title>
<style>
  *{box-sizing:border-box;font-family:-apple-system,Segoe UI,Roboto,sans-serif}
  body{background:#0b1020;color:#e6edf3;margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center}
  .card{background:#121a2b;border:1px solid #1f2a44;border-radius:14px;padding:32px;width:360px;box-shadow:0 10px 40px #0008}
  h1{margin:0 0 6px;font-size:22px;color:#58a6ff}
  .sub{color:#8b949e;font-size:13px;margin-bottom:22px}
  label{display:block;font-size:12px;color:#8b949e;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}
  input{width:100%;padding:10px 12px;background:#0b1020;border:1px solid #1f2a44;border-radius:8px;color:#e6edf3;font-size:14px;margin-bottom:14px}
  button{width:100%;padding:11px;background:#238636;color:#fff;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer}
  button:hover{background:#2ea043}
  .err{color:#f85149;font-size:13px;margin-bottom:10px}
</style></head><body>
<div class="card">
  <h1>Exnova Trading Bot</h1>
  <div class="sub">Inicia sesion para acceder al dashboard</div>
  {{ERROR}}
  <form method="post" action="/login">
    <label>Usuario</label>
    <input name="username" autocomplete="username" required>
    <label>Contrasena</label>
    <input name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Entrar</button>
  </form>
</div></body></html>"""


DASHBOARD_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Exnova Bot - Dashboard</title>
<style>
  *{box-sizing:border-box;font-family:-apple-system,Segoe UI,Roboto,sans-serif}
  body{background:#0b1020;color:#e6edf3;margin:0}
  .top{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;background:#121a2b;border-bottom:1px solid #1f2a44}
  .top h1{margin:0;font-size:18px;color:#58a6ff}
  .top a{color:#8b949e;text-decoration:none;font-size:13px}
  .wrap{max-width:1200px;margin:0 auto;padding:24px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
  .card{background:#121a2b;border:1px solid #1f2a44;border-radius:12px;padding:16px}
  .card .k{color:#8b949e;font-size:11px;text-transform:uppercase;letter-spacing:.5px}
  .card .v{font-size:26px;font-weight:700;margin-top:6px}
  .ok{color:#3fb950}.bad{color:#f85149}.warn{color:#d29922}.ai{color:#58a6ff}
  h3{color:#58a6ff;margin:24px 0 10px;font-size:15px}
  table{width:100%;border-collapse:collapse;font-size:13px;background:#121a2b;border-radius:12px;overflow:hidden}
  th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #1f2a44}
  th{color:#8b949e;font-size:11px;text-transform:uppercase;background:#0d1424}
  .tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
  .win{background:#1a3a2a;color:#3fb950}.loss{background:#3a1a1a;color:#f85149}.draw{background:#2a2a1a;color:#d29922}.ai{background:#1a2233;color:#58a6ff}
  button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:8px 14px;cursor:pointer;font-size:13px}
  button:hover{background:#30363d}
  .cfg{background:#121a2b;border:1px solid #1f2a44;border-radius:12px;padding:16px;font-size:13px;line-height:1.7}
  .cfg b{color:#58a6ff}
  pre{margin:0;white-space:pre-wrap;font-family:inherit}
  .row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}
</style></head><body>
<div class="top"><h1>Exnova Trading Bot - Dashboard</h1><a href="/logout">Salir</a></div>
<div class="wrap">
  <div class="row">
    <button onclick="load()">Recargar</button>
    <button onclick="testExnova()">Probar conexion Exnova (env)</button>
    <button onclick="startBot()">Iniciar bot (paper)</button>
    <button onclick="stopBot()">Detener bot</button>
  </div>
  <div class="cfg" style="margin-bottom:16px">
    <b>Probar credenciales de Exnova en vivo</b><br>
    <input id="exEmail" placeholder="email" style="width:40%;padding:8px;margin:6px 4px;background:#0b1020;border:1px solid #1f2a44;color:#e6edf3;border-radius:6px">
    <input id="exPass" type="password" placeholder="password" style="width:30%;padding:8px;margin:6px 4px;background:#0b1020;border:1px solid #1f2a44;color:#e6edf3;border-radius:6px">
    <select id="exType" style="padding:8px;margin:6px 4px;background:#0b1020;border:1px solid #1f2a44;color:#e6edf3;border-radius:6px">
      <option>PRACTICE</option><option>REAL</option>
    </select>
    <button onclick="connectExnova()">Conectar</button>
    <div id="exResult" style="margin-top:8px;color:#8b949e"></div>
  </div>
  <div class="grid" id="cards"></div>
  <h3>Operaciones recientes</h3>
  <table><thead><tr><th>Hora</th><th>Activo</th><th>Dir</th><th>Resultado</th><th>PnL</th><th>IA</th></tr></thead>
  <tbody id="tbl"></tbody></table>
  <h3>Configuracion e IA</h3>
  <div class="cfg" id="cfg"></div>
  <h3>Estrategias</h3>
  <div class="cfg" id="strats"></div>
  <h3>Log en vivo</h3>
  <div class="cfg"><pre id="log" style="max-height:260px;overflow:auto"></pre></div>
</div>
<script>
async function get(p){const r=await fetch(p);return r.json();}
function esc(s){return String(s??'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));}
async function load(){
  try{
    const [s,t,c,st]=await Promise.all([get('/api/status'),get('/api/trades?limit=30'),get('/api/config'),get('/api/strategies')]);
    const alive=s.bot_alive;
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
      const ts=tr.timestamp?new Date((typeof tr.timestamp==='number'?tr.timestamp*1000:tr.timestamp)).toLocaleString('es-CO'):'-';
      const res=(tr.result||'').toUpperCase();
      const rc=res==='WIN'?'win':res==='LOSS'?'loss':'draw';
      const ai=tr.ai_used?'<span class="tag ai">IA</span>':'';
      const dir=tr.direction||'-';
      const pnlV=(tr.pnl||0); const pc=pnlV>=0?'ok':'bad';
      return `<tr><td>${esc(ts)}</td><td>${esc(tr.asset||'-')}</td><td>${esc(dir)}</td><td><span class="tag ${rc}">${res||'-'}</span></td><td class="${pc}">${pnlV>=0?'+':''}${Number(pnlV).toFixed(2)}</td><td>${ai}</td></tr>`;
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
    document.getElementById('strats').innerHTML=`<pre>${esc((st.strategies||[]).join(', '))}</pre>`;
  }catch(e){console.error(e);}
}
async function testExnova(){
  const r=await fetch('/api/exnova/test',{method:'POST'});
  const d=await r.json();
  alert('Exnova: '+(d.ok?'OK balance '+d.balance:'FALLO - '+(d.error||'')));
}
async function connectExnova(){
  const email=document.getElementById('exEmail').value;
  const password=document.getElementById('exPass').value;
  const account_type=document.getElementById('exType').value;
  const r=await fetch('/api/exnova/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password,account_type})});
  const d=await r.json();
  const el=document.getElementById('exResult');
  if(d.ok){
    el.innerHTML='<span style="color:#3fb950">OK</span> balance: '+d.balance+' | activos: '+d.assets_count+' ('+(d.sample_assets||[]).join(', ')+')';
  } else {
    el.innerHTML='<span style="color:#f85149">FALLO</span>: '+(d.error||'sin detalle');
  }
}
async function startBot(){
  const mode=prompt('Modo (paper/practice):','paper');
  const email=document.getElementById('exEmail').value;
  const password=document.getElementById('exPass').value;
  const r=await fetch('/api/bot/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:mode,email:email||undefined,password:password||undefined})});
  const d=await r.json();
  alert(d.ok?'Bot iniciado: '+d.mode:'Error: '+(d.error||''));
  load();
}
async function stopBot(){
  const r=await fetch('/api/bot/stop',{method:'POST'});
  const d=await r.json();
  alert(d.ok?'Bot detenido':'Error');
  load();
}
const ws=new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/ws/logs');
ws.onmessage=e=>{document.getElementById('log').textContent=e.data;};
load(); setInterval(load, 5000);
</script></body></html>"""




@app.get("/api/improvement")
def improvement():
    hb = _read_json(IMPROVE_HEARTBEAT)
    adj = _read_json(ADJUSTMENTS_JSON)
    now = time.time()
    hb_ts = hb.get("ts") if isinstance(hb, dict) else None
    alive = isinstance(hb_ts, (int, float)) and (now - hb_ts) < 180
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
    log_path = ROOT / "data" / "bot.log"
    tail = ""
    try:
        if log_path.exists():
            tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-60:])
    except Exception:
        pass
    return {"exists": log_path.exists(), "tail": tail}


def _architect():
    import sys
    sys.path.insert(0, str(ROOT / "bot" / "monitor"))
    from architect import architect as _a
    return _a


@app.post("/api/architect/chat")
def architect_chat(payload: dict, request: Request):
    if not _admin_allowed(request):
        return JSONResponse({"error": "auth requerida"}, status_code=401)
    message = str(payload.get("message", "")).strip()[:500]
    if not message:
        return JSONResponse({"error": "Mensaje vacio"}, status_code=400)
    try:
        return _architect().chat(message)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.get("/api/architect/state")
def architect_state(request: Request):
    if not _admin_allowed(request):
        return JSONResponse({"error": "auth requerida"}, status_code=401)
    try:
        a = _architect()
        return {"state": a.get_state(), "analysis": a.analyze(), "memory": a.memory}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/api/architect/apply")
def architect_apply(payload: dict, request: Request):
    if not _admin_allowed(request):
        return JSONResponse({"error": "auth requerida"}, status_code=401)
    proposal = payload.get("proposal") or {}
    reason = str(payload.get("reason", "")).strip()[:300]
    if not isinstance(proposal, dict) or not proposal:
        return JSONResponse({"error": "Propuesta vacia"}, status_code=400)
    try:
        return _architect().apply_proposal(proposal, reason=reason, mode_ok=True)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

# ------------------------------------------------------------------ bot control
@app.get("/api/bot/status")
def bot_status():
    alive = _BOT_THREAD is not None and _BOT_THREAD.is_alive()
    _BOT_STATUS["running"] = alive
    return dict(_BOT_STATUS)


@app.post("/api/bot/start")
def bot_start(payload: dict = None, request: Request = None):
    global _BOT_THREAD, _BOT_INSTANCE
    if request is not None and not _admin_allowed(request):
        return JSONResponse({"error": "auth requerida"}, status_code=401)
    if _BOT_THREAD is not None and _BOT_THREAD.is_alive():
        return {"ok": False, "error": "Bot ya esta corriendo"}
    payload = payload or {}
    mode = str(payload.get("mode", "paper")).lower()
    email = payload.get("email")
    password = payload.get("password")
    try:
        import os as _os
        _os.environ["TRADING_MODE"] = mode
        _os.environ["ACCOUNT_TYPE"] = mode
        from app.main import TradingBot
        import threading
        bot = TradingBot(email=email, password=password, account_type=mode)
        _BOT_INSTANCE = bot
        def _run():
            try:
                bot.start()
            except Exception as e:
                _BOT_STATUS["error"] = str(e)
            finally:
                _BOT_STATUS["running"] = False
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        _BOT_THREAD = t
        _BOT_STATUS.update({"running": True, "mode": mode, "error": None})
        return {"ok": True, "mode": mode}
    except Exception as e:
        _BOT_STATUS["error"] = str(e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/bot/stop")
def bot_stop(request: Request = None):
    global _BOT_INSTANCE
    if request is not None and not _admin_allowed(request):
        return JSONResponse({"error": "auth requerida"}, status_code=401)
    if _BOT_INSTANCE is not None:
        try:
            _BOT_INSTANCE.stop()
        except Exception as e:
            pass
    _BOT_STATUS["running"] = False
    return {"ok": True}



@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    try:
        last = ""
        while True:
            log_path = ROOT / "data" / "bot.log"
            tail = ""
            try:
                if log_path.exists():
                    tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-20:])
            except Exception:
                pass
            if tail != last:
                await websocket.send_text(tail)
                last = tail
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
