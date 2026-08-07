"""Bucle de mejora continua por LOTES (no pegado a cada trade).

Cada N trades nuevos (o cada X minutos, lo que ocurra primero), toma el
lote de operaciones cerradas, le pide a la IA (opencode-go via REST) una
AUTOPSIA profesional: donde se perdio, donde debio entrar, si la
expiracion fue mala, que reforzar. La IA devuelve refinamientos que se
aplican a `strategy_adjustments.json`, que el bot live lee antes de
operar. Asi la estrategia se vuelve "nuestra", calibrada ciclo a ciclo.

NO requiere el CLI de opencode (lo quitamos del Dockerfile). Usa REST.
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

BOT = Path(__file__).absolute().parents[1]
if str(BOT) not in sys.path:
    sys.path.insert(0, str(BOT))

TRADES_JSON = BOT / "brain" / "trade_history.json"

from brain import strategy_adjustments as ADJ

# ─── Configuracion (env) ───────────────────────────────────────────────────────
OPENCODE_BASE_URL = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1")
OPENCODE_API_KEY = os.getenv("OPENCODE_API_KEY", "")
OPENCODE_MODEL = os.getenv("IMPROVEMENT_MODEL", os.getenv("OPENCODE_MODEL_DEEP", "qwen3.7-max"))
OPENCODE_MODEL_FAST = os.getenv("IMPROVEMENT_MODEL_FAST", os.getenv("OPENCODE_MODEL_FAST", "deepseek-v4-flash-free"))

BATCH_N_TRADES = int(os.getenv("IMPROVEMENT_BATCH_TRADES", "10"))
BATCH_MIN_MINUTES = int(os.getenv("IMPROVEMENT_BATCH_MIN_MINUTES", "20"))
BATCH_MIN_SECONDS = BATCH_MIN_MINUTES * 60
TIMEOUT_SEC = int(os.getenv("IMPROVEMENT_TIMEOUT", "90"))
ENABLED = os.getenv("IMPROVEMENT_ENABLED", "true").lower() == "true"

SYSTEM_PROMPT = (
    "Eres un TRADER PROFESIONAL realizando la autopsia de un lote de operaciones "
    "de opciones binarias OTC en Exnova. Tu objetivo es hacer la estrategia MAS "
    "CERTEA, no cambiar por cambiar. Analizas donde se debio entrar, si la "
    "expiracion fue la correcta, y que reforzar de lo que gano. "
    "NO asumas que toda perdida fue mala entrada: a veces el setup era correcto "
    "y fue volatilidad/blow. Devuelves SIEMPRE un unico objeto JSON valido, "
    "sin texto fuera del JSON, sin markdown."
)


def _log(msg: str) -> None:
    print(f"[improvement] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def _read_trades() -> List[Dict]:
    try:
        if not TRADES_JSON.exists():
            return []
        with open(TRADES_JSON, "r", encoding="utf-8") as f:
            return (json.load(f) or {}).get("trades", [])
    except Exception as e:
        _log(f"ERR leyendo trades: {e}")
        return []


def _call_opencode(model: str, prompt: str) -> Optional[Dict]:
    """Llama al endpoint OpenAI-compatible de opencode-go y parsea el JSON."""
    if not OPENCODE_API_KEY:
        _log("sin OPENCODE_API_KEY; bucle inactivo")
        return None
    headers = {
        "Authorization": f"Bearer {OPENCODE_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "opencode/1.0",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 2500,
    }
    for attempt in range(1, 3):
        t0 = time.time()
        try:
            r = requests.post(
                f"{OPENCODE_BASE_URL}/chat/completions",
                headers=headers, json=body, timeout=TIMEOUT_SEC,
            )
            dt = time.time() - t0
            if r.status_code != 200:
                _log(f"HTTP {r.status_code} (intent {attempt}): {r.text[:140]}")
                if attempt == 2:
                    return None
                time.sleep(4)
                continue
            content = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            parsed = _parse_json(content)
            if parsed is not None:
                _log(f"IA respondio OK en {dt:.1f}s (model={model}, len={len(content)})")
                return parsed
            _log(f"JSON invalido (intent {attempt}): {content[:120]}")
            if attempt == 2:
                return None
            time.sleep(3)
        except requests.exceptions.Timeout:
            _log(f"timeout (intent {attempt})")
            if attempt == 2:
                return None
        except Exception as e:
            _log(f"ERR (intent {attempt}): {e}")
            if attempt == 2:
                return None
            time.sleep(4)
    return None


def _parse_json(content: str) -> Optional[Dict]:
    try:
        return json.loads(content)
    except Exception:
        pass
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None


def _summarize_trades(trades: List[Dict]) -> Dict:
    wins = [t for t in trades if (t.get("result", "") or "").upper() == "WIN"]
    losses = [t for t in trades if (t.get("result", "") or "").upper() == "LOSS"]
    pnl = sum(t.get("pnl", 0.0) for t in trades)
    by_asset = {}
    for t in trades:
        a = t.get("asset", "?")
        by_asset.setdefault(a, {"win": 0, "loss": 0})
        if (t.get("result") or "").upper() == "WIN":
            by_asset[a]["win"] += 1
        elif (t.get("result") or "").upper() == "LOSS":
            by_asset[a]["loss"] += 1
    return {
        "n": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(trades), 3) if trades else 0,
        "pnl": round(pnl, 2),
        "by_asset": by_asset,
    }


def _build_prompt(batch: List[Dict], current: Dict, summary: Dict) -> str:
    lessons = current.get("recent_lessons") or []
    lessons_txt = "\n".join(f"- {l.get('text','')}" for l in lessons[-6:]) or "(ninguna)"
    cfg = {
        "min_confidence_actual": current.get("min_confidence"),
        "expiry_por_activo": current.get("expiry_by_asset"),
        "activos_pausados": current.get("assets_pause"),
    }
    # Lote compacto (solo campos utiles) para no inflar tokens
    compact = []
    for t in batch[-BATCH_N_TRADES:]:
        compact.append({
            "asset": t.get("asset"), "dir": t.get("direction"),
            "result": t.get("result"), "pnl": t.get("pnl"),
            "conf": t.get("confidence") or t.get("score"),
            "expiry_min": t.get("expiry_minutes") or t.get("exp_min"),
            "rsi": t.get("rsi_at_touch"), "pattern": t.get("pattern"),
            "zone": t.get("zone"), "zone_str": t.get("zone_strength"),
            "trend_aligned": t.get("trend_aligned"),
        })
    return (
        f"Analiza este LOTE de {len(compact)} operaciones recientes y refina la "
        f"estrategia para hacerla mas cierta. NO cambies por cambiar.\n\n"
        f"CONFIG ACTUAL:\n{json.dumps(cfg, ensure_ascii=False)}\n\n"
        f"RESUMEN LOTE: {json.dumps(summary, ensure_ascii=False)}\n\n"
        f"TRADES DEL LOTE:\n{json.dumps(compact, ensure_ascii=False)}\n\n"
        f"LECCIONES PREVIAS (refuerza o corrige):\n{lessons_txt}\n\n"
        f"INSTRUCCION: Para cada perdida diagnostica la causa real (entrada, "
        f"timing, expiracion, activo o volatilidad) y propón refinamientos "
        f"concretos y conservadores. Refuerza lo que gano. Puedes proponer "
        f"pausar un activo si muestra edge negativo claro (min 4 muestras).\n\n"
        f"Responde SOLO este JSON:\n"
        "{\n"
        "  \"losses_diagnosis\": [{\"asset\":\"\",\"root_cause\":\"\",\"better_entry\":\"\",\"better_expiry_min\":0}],\n"
        "  \"wins_reinforce\": [{\"asset\":\"\",\"what_worked\":\"\"}],\n"
        "  \"refinements\": [{\"param\":\"min_confidence|expiry_by_asset.<ACT>\"|assets_pause\",\"old\":0,\"new\":0,\"reason\":\"\",\"expected_impact\":\"\"}],\n"
        "  \"assets_pause\": [\"ACT-OTC\"],\n"
        "  \"new_lessons\": [\"leccion breve en español\"],\n"
        "  \"overall_adjust\": \"resumen de 1 linea\"\n"
        "}"
    )


def _apply_refinements(parsed: Dict, batch_summary: Dict) -> Dict:
    """Aplica los refinamientos de la IA a la memoria. Devuelve el diff aplicado."""
    data = ADJ.load()
    data["cycle"] = int(data.get("cycle", 0)) + 1
    applied = []

    # 1) min_confidence
    refined_mc = None
    for r in (parsed.get("refinements") or []):
        if r.get("param") == "min_confidence":
            try:
                refined_mc = float(r.get("new"))
            except Exception:
                pass
            break
    if refined_mc is not None:
        lo, hi = ADJ.MIN_CONF_RANGE
        refined_mc = round(max(lo, min(hi, refined_mc)), 3)
        old = data.get("min_confidence")
        data["min_confidence"] = refined_mc
        applied.append(f"MIN_CONF: {old} -> {refined_mc}")

    # 2) expiry_by_asset
    ea = dict(data.get("expiry_by_asset") or {})
    for r in (parsed.get("refinements") or []):
        p = r.get("param", "")
        if p.startswith("expiry_by_asset."):
            asset = p.split(".", 1)[1].strip()
            try:
                v = int(round(float(r.get("new"))))
            except Exception:
                continue
            v = max(ADJ.EXPIRY_RANGE[0], min(ADJ.EXPIRY_RANGE[1], v))
            ea[asset] = v
            applied.append(f"EXPIRY {asset}: -> {v}min")
    data["expiry_by_asset"] = ea

    # 3) assets_pause: ADITIVO (union con lo ya pausado), nunca lo reemplaza.
    # El prompt solo pide activos a pausar segun el lote actual - no le pide
    # a la IA que re-liste los ya pausados de lotes anteriores. Un lote que
    # no toca esos activos no es evidencia de que ya esten bien; interpretar
    # "no los menciono" como "reabrir todos" (como hacia antes) deshacia casi
    # cualquier pausa un ciclo despues de aplicarse.
    ap_new = [a for a in (parsed.get("assets_pause") or []) if isinstance(a, str)]
    if ap_new:
        current_pause = list(data.get("assets_pause") or [])
        merged = current_pause + [a for a in ap_new if a not in current_pause]
        data["assets_pause"] = merged[:40]
        applied.append(f"PAUSE: {data['assets_pause']}")

    # 4) lecciones (acumula nuevas, cap MAX_LESSONS)
    lessons = list(data.get("lessons") or [])
    for l in (parsed.get("new_lessons") or []):
        if isinstance(l, str) and l.strip():
            lessons.append({"ts": time.time(), "text": l.strip()[:200]})
    data["lessons"] = lessons[-ADJ.MAX_LESSONS:]

    # 5) historial (auditable)
    hist = list(data.get("history") or [])
    hist.append({
        "ts": time.time(),
        "cycle": data["cycle"],
        "batch": batch_summary,
        "overall_adjust": parsed.get("overall_adjust", ""),
        "applied": applied,
    })
    data["history"] = hist[-30:]

    ADJ.save(data)
    return {"cycle": data["cycle"], "applied": applied,
            "overall_adjust": parsed.get("overall_adjust", "")}


def _run_cycle(last_ts: float) -> float:
    """Corre un ciclo si hay >=BATCH_N_TRADES nuevos o si paso BATCH_MIN_SEGUNDOS.
    Devuelve el nuevo last_ts (timestamp del ultimo trade analizado)."""
    trades = _read_trades()
    if not trades:
        return last_ts
    # trades nuevos desde last_ts
    new = [t for t in trades if float(t.get("timestamp", 0) or 0) > last_ts]
    last_trade_ts = float(trades[-1].get("timestamp", 0) or 0)
    since_last = time.time() - last_ts if last_ts else 1e12
    if len(new) < BATCH_N_TRADES and since_last < BATCH_MIN_SECONDS:
        return last_ts  # no toca aun

    if not new:
        return last_ts

    batch = new[-BATCH_N_TRADES:]
    summary = _summarize_trades(batch)
    current = ADJ.export_for_prompt()
    prompt = _build_prompt(batch, current, summary)

    _log(f"ciclo {current.get('cycle',0)+1}: lote={summary['n']} WR={summary['win_rate']} pnl={summary['pnl']}")
    parsed = _call_opencode(OPENCODE_MODEL, prompt)
    if parsed is None:
        _log("fallback a modelo rapido")
        parsed = _call_opencode(OPENCODE_MODEL_FAST, prompt)
    if parsed is None:
        _log("ciclo fallido (sin respuesta IA)")
        return last_trade_ts  # avanzar igual para no reintentar el mismo lote

    try:
        res = _apply_refinements(parsed, summary)
        _log(f"ciclo {res['cycle']} aplicado: {res['applied']} | {res['overall_adjust']}")
    except Exception as e:
        _log(f"ERR aplicando refinamientos: {e}")
    return last_trade_ts


def loop() -> None:
    _log(f"arrancando. modelo={OPENCODE_MODEL} | lote cada {BATCH_N_TRADES} trades o {BATCH_MIN_MINUTES}min | enabled={ENABLED}")
    if not ENABLED:
        _log("deshabilitado (IMPROVEMENT_ENABLED=false)")
        return
    last_ts = 0.0
    # arrancar: last_ts = ultimo trade existente (para no analizar historico viejo)
    trades = _read_trades()
    if trades:
        last_ts = float(trades[-1].get("timestamp", 0) or 0)
        _log(f"arranque: last_ts={last_ts} ({len(trades)} trades historicos no analizados)")
    hb_path = BOT / "brain" / "improvement_heartbeat.json"
    while True:
        try:
            # heartbeat: confirma que el loop vive
            with open(hb_path, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "last_cycle": last_ts}, f)
            last_ts = _run_cycle(last_ts)
        except Exception as e:
            _log(f"ERR ciclo: {e}")
        time.sleep(60)  # revisar cada 1 min si hay lote nuevo


if __name__ == "__main__":
    loop()