"""
ARCHITECT IA - Motor de control del bot de trading.

Replica el patrón del "Arquitecto IA" de VentasPro (analiza -> propone ->
aprueba -> ejecuta -> refina) adaptado al dominio de trading:

  - MEMORIA   : lee el estado real (trades, learning, adjustments, runtime)
  - ANALISIS  : calcula métricas reales y detecta problemas/oportunidades
  - PROPUESTA : genera cambios concretos y medibles (stake, confianza, activos)
  - EJECUCION : escribe runtime_config.json -> el bot lo aplica EN CALIENTE
  - REFINAMIENTO : cada ciclo re-evalúa con datos nuevos; nunca propone por
    intuición, solo por evidencia (misma filosofía que core/self_evaluator.py).

Solo paper/practice: este motor JAMÁS activa dinero real ni cambia la cuenta.
"""
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]       # /app
BOT = Path(__file__).resolve().parents[1]         # /app/bot
TRADES_JSON = BOT / "brain" / "trade_history.json"
LEARNING_JSON = BOT / "data" / "learning_progress.json"
ADJUSTMENTS_JSON = BOT / "brain" / "strategy_adjustments.json"
IMPROVE_HEARTBEAT = BOT / "brain" / "improvement_heartbeat.json"
RUNTIME_CONFIG = ROOT / "data" / "runtime_config.json"
HISTORY_FILE = ROOT / "data" / "architect_history.json"

MIN_SAMPLE = 20          # muestra mínima para proponer cambios de confianza
MIN_RECENT = 10          # muestra mínima para hablar de tendencia reciente
STAKE_MIN, STAKE_MAX = 0.5, 100.0


def _read_json(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class ArchitectAI:
    """Motor maestro: memoria + análisis + propuesta + ejecución."""

    def __init__(self):
        self.memory = self._load_history()

    # ── MEMORIA ──────────────────────────────────────────────────────────
    def _load_history(self) -> dict:
        hist = _read_json(HISTORY_FILE)
        return {
            "proposals": hist.get("proposals", []),
            "applied": hist.get("applied", []),
            "rejected": hist.get("rejected", []),
        }

    def _remember(self, kind: str, entry: dict) -> None:
        key = "proposals" if kind == "proposal" else kind
        self.memory.setdefault(key, []).append(
            {"ts": datetime.now(timezone.utc).isoformat(), **entry}
        )
        self.memory[key] = self.memory[key][-50:]
        _write_json(HISTORY_FILE, self.memory)

    # ── MEMORIA / ESTADO REAL ────────────────────────────────────────────
    def get_state(self) -> dict:
        """Snapshot del estado real del sistema (todo con evidencia)."""
        trades = _read_json(TRADES_JSON)
        learning = _read_json(LEARNING_JSON)
        adj = _read_json(ADJUSTMENTS_JSON)
        hb = _read_json(IMPROVE_HEARTBEAT)
        runtime = _read_json(RUNTIME_CONFIG)
        rows = trades.get("trades", []) if isinstance(trades, dict) else []

        total = len(rows)
        wins = sum(1 for t in rows if t.get("result") == "WIN")
        losses = sum(1 for t in rows if t.get("result") == "LOSS")
        pnl = sum(float(t.get("pnl") or 0) for t in rows)

        recent = rows[-MIN_RECENT:] if total else []
        recent_wins = sum(1 for t in recent if t.get("result") == "WIN")
        recent_pnl = sum(float(t.get("pnl") or 0) for t in recent)

        by_asset: dict = {}
        for t in rows:
            a = t.get("asset", "?")
            d = by_asset.setdefault(a, {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
            d["trades"] += 1
            d["wins"] += 1 if t.get("result") == "WIN" else 0
            d["losses"] += 1 if t.get("result") == "LOSS" else 0
            d["pnl"] += float(t.get("pnl") or 0)

        hb_ts = hb.get("ts") if isinstance(hb, dict) else None
        return {
            "total": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total * 100, 1) if total else 0.0,
            "pnl": round(pnl, 2),
            "recent": {
                "count": len(recent),
                "wins": recent_wins,
                "win_rate": round(recent_wins / len(recent) * 100, 1) if recent else 0.0,
                "pnl": round(recent_pnl, 2),
            },
            "by_asset": dict(sorted(by_asset.items(), key=lambda kv: kv[1]["pnl"], reverse=True)[:12]),
            "learning": learning,
            "adjustments": adj,
            "improvement_alive": isinstance(hb_ts, (int, float)) and (time.time() - hb_ts) < 180,
            "runtime": runtime,
            "current": {
                "mode": runtime.get("mode", os.getenv("ACCOUNT_TYPE", "PRACTICE").lower()),
                "asset": runtime.get("asset", os.getenv("DEFAULT_ASSET", "EURUSD-OTC")),
                "strategy": runtime.get("strategy", "auto"),
                "stake": runtime.get("stake", 0),
                "min_confidence": runtime.get("min_confidence", float(os.getenv("MIN_CONFIDENCE", "0.65"))),
                "max_consecutive_losses": runtime.get("max_consecutive_losses", int(os.getenv("MAX_CONSEC_LOSSES", "4"))),
                "cooldown_after_loss": runtime.get("cooldown_after_loss", int(os.getenv("COOLDOWN_AFTER_LOSS", "300"))),
                "min_between_trades": runtime.get("min_between_trades", int(os.getenv("MIN_BETWEEN_TRADES", "180"))),
            },
        }

    # ── ANÁLISIS (reglas basadas en evidencia, no intuición) ─────────────
    def analyze(self) -> dict:
        s = self.get_state()
        issues: list[str] = []
        opportunities: list[str] = []
        proposal: dict = {}

        if s["total"] == 0:
            return {
                "verdict": "cold",
                "summary": "Sin muestra todavía. El bot debe acumular operaciones en practice antes de proponer cambios.",
                "issues": ["No hay datos suficientes (0 trades)."],
                "proposal": {},
                "state": s,
            }

        # 1) Tendencia reciente
        if s["recent"]["count"] >= MIN_RECENT and s["recent"]["pnl"] < 0:
            issues.append(
                f"Tendencia reciente negativa: {s['recent']['pnl']:+.2f} USDT "
                f"en {s['recent']['count']} trades (WR {s['recent']['win_rate']}%)."
            )
        elif s["recent"]["count"] >= MIN_RECENT and s["recent"]["win_rate"] >= 60 and s["recent"]["pnl"] > 0:
            opportunities.append(
                f"Tendencia reciente positiva ({s['recent']['win_rate']}% WR, "
                f"{s['recent']['pnl']:+.2f} USDT)."
            )

        # 2) Win rate general bajo -> subir confianza mínima
        cur_conf = float(s["current"]["min_confidence"])
        if s["total"] >= MIN_SAMPLE and s["win_rate"] < 50:
            new_conf = min(round(cur_conf + 0.05, 2), 0.85)
            if new_conf != cur_conf:
                proposal["min_confidence"] = new_conf
                issues.append(
                    f"WR general {s['win_rate']}% < 50%. Subir confianza mínima "
                    f"de {cur_conf} a {new_conf}."
                )

        # 3) Activos perdedores con muestra -> pausar/cambiar
        losers = [
            a for a, d in s["by_asset"].items()
            if d["trades"] >= 10 and d["pnl"] < 0
            and (d["wins"] / d["trades"]) < 0.45
        ]
        if losers:
            issues.append(f"Activos perdedores (muestra >=10, WR<45%): {', '.join(losers[:5])}.")
            # sugerir mover el activo principal al mejor activo con muestra
            good = [
                a for a, d in s["by_asset"].items()
                if d["trades"] >= 10 and d["wins"] / d["trades"] >= 0.55
            ]
            if good and s["current"]["asset"] in losers:
                proposal["asset"] = good[0]
                opportunities.append(f"Cambiar activo principal {s['current']['asset']} -> {good[0]} (mejor WR con muestra).")

        # 4) Stake: si tendencia positiva y WR alto -> subir (con cota)
        cur_stake = float(s["current"]["stake"] or 0)
        if s["recent"]["count"] >= MIN_RECENT and s["recent"]["win_rate"] >= 60 and s["recent"]["pnl"] > 0:
            new_stake = round(min(cur_stake * 1.5 if cur_stake else 2.0, STAKE_MAX), 2)
            if cur_stake == 0 or new_stake > cur_stake:
                proposal["stake"] = new_stake
                opportunities.append(
                    f"Subir stake a ${new_stake:.2f} (tendencia positiva sostenida)."
                )
        elif s["recent"]["count"] >= MIN_RECENT and s["recent"]["pnl"] < 0:
            new_stake = round(max(cur_stake * 0.75, STAKE_MIN), 2) if cur_stake else 0
            if cur_stake and new_stake < cur_stake:
                proposal["stake"] = new_stake
                issues.append(
                    f"Reducir stake a ${new_stake:.2f} (tendencia negativa)."
                )

        # 5) Estrategia con WR bajo y muestra grande -> exigir más calidad
        if s["total"] >= MIN_SAMPLE and s["win_rate"] < 45:
            new_cooldown = max(int(s["current"]["cooldown_after_loss"]), 300)
            if new_cooldown != int(s["current"]["cooldown_after_loss"]):
                proposal["cooldown_after_loss"] = new_cooldown
                issues.append("Rendimiento pobre: aumentar cooldown tras pérdida a 300s.")

        if not proposal and not issues and not opportunities:
            return {
                "verdict": "stable",
                "summary": "Sin cambios propuestos: el sistema opera dentro de parámetros estables.",
                "issues": [],
                "opportunities": [],
                "proposal": {},
                "state": s,
            }

        verdict = "improve" if opportunities else ("warn" if issues else "stable")
        summary_parts = issues + opportunities
        return {
            "verdict": verdict,
            "summary": " ".join(summary_parts) if summary_parts else "Estado estable.",
            "issues": issues,
            "opportunities": opportunities,
            "proposal": proposal,
            "state": s,
        }

    # ── PROPUESTA → EJECUCIÓN ────────────────────────────────────────────
    def propose(self, reason: str = "") -> dict:
        analysis = self.analyze()
        self._remember("proposal", {"reason": reason, "proposal": analysis["proposal"]})
        return analysis

    def apply_proposal(self, proposal: dict, reason: str = "", mode_ok: bool = False) -> dict:
        """Aplica una propuesta (o un payload directo) a runtime_config.json."""
        if not isinstance(proposal, dict) or not proposal:
            return {"ok": False, "error": "Propuesta vacía."}
        current = _read_json(RUNTIME_CONFIG)
        data = {**current}
        allowed = {"min_confidence", "max_consecutive_losses", "cooldown_after_loss",
                   "min_between_trades", "asset", "strategy", "stake", "mode"}
        applied = {}
        for k, v in proposal.items():
            if k not in allowed:
                continue
            if k == "mode":
                if mode_ok and str(v).lower() in {"paper", "practice"}:
                    data["mode"] = str(v).lower()
                    applied[k] = str(v).lower()
                continue
            if k in {"min_confidence"}:
                v = min(max(float(v), 0.5), 0.99)
            elif k in {"cooldown_after_loss", "min_between_trades"}:
                v = min(max(int(v), 30), 3600)
            elif k == "max_consecutive_losses":
                v = min(max(int(v), 1), 10)
            elif k == "stake":
                v = round(min(max(float(v), STAKE_MIN), STAKE_MAX), 2)
            elif k == "asset":
                v = str(v).strip()[:80]
            elif k == "strategy":
                v = str(v).strip()[:80]
            data[k] = v
            applied[k] = v
        data["reason"] = str(reason)[:300]
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(RUNTIME_CONFIG, data)
        if applied:
            self._remember("applied", {"reason": reason, "applied": applied})
        return {"ok": True, "applied": applied, "apply_mode": "hot",
                "note": "El bot aplica estos cambios en caliente (próximo ciclo)."}

    # ── CHAT DE ÓRDENES ──────────────────────────────────────────────────
    _NUM = r"([0-9]+(?:\.[0-9]+)?)"

    def chat(self, message: str) -> dict:
        """Procesa una orden del usuario en lenguaje natural."""
        msg = (message or "").strip().lower()
        if not msg:
            return {"reply": "Di algo. Escribe 'ayuda' para ver los comandos."}

        # ── Ayuda / estado
        if msg in {"ayuda", "help", "comandos", "?"}:
            return {"reply": (
                "Comandos disponibles:\n"
                "• 'estado' / 'análisis' → veo el rendimiento real y propongo ajustes\n"
                "• 'aplica' → aplico la última propuesta\n"
                "• 'stake a 5' → monto por operación (0.5-100)\n"
                "• 'confianza a 0.7' → confianza mínima (0.5-0.99)\n"
                "• 'activo a EURUSD-OTC' → activo principal\n"
                "• 'max pérdidas a 4' → pérdidas consecutivas máx (1-10)\n"
                "• 'cooldown a 300' → pausa tras pérdida en segundos (30-3600)\n"
                "• 'entre trades a 180' → mínimo entre operaciones (30-3600)\n"
                "• 'estado' → resumen actual")}

        if msg in {"estado", "status", "resumen"}:
            s = self.get_state()
            r = s["recent"]
            return {"reply": (
                f"Bot: {s['current']['mode'].upper()} | Activo: {s['current']['asset']}\n"
                f"Stake: ${s['current']['stake']:.2f} | Conf mín: {s['current']['min_confidence']}\n"
                f"Trades: {s['total']} (W:{s['wins']}/L:{s['losses']}) WR:{s['win_rate']}% PnL:{s['pnl']:+.2f}\n"
                f"Recientes ({r['count']}): WR {r['win_rate']}% PnL {r['pnl']:+.2f}\n"
                f"Mejora IA viva: {'sí' if s['improvement_alive'] else 'no'}")}

        # ── Análisis / propuesta
        if msg in {"análisis", "analisis", "analiza", "recomienda", "recomendación", "propuesta", "que hago", "qué hago"}:
            analysis = self.analyze()
            lines = [f"[ANÁLISIS] {analysis['summary']}"]
            if analysis["issues"]:
                lines.append("⚠️ " + " | ".join(analysis["issues"]))
            if analysis["opportunities"]:
                lines.append("✅ " + " | ".join(analysis["opportunities"]))
            if analysis["proposal"]:
                lines.append("📋 Propuesta lista: " + json.dumps(analysis["proposal"], ensure_ascii=False))
                lines.append("Responde 'aplica' para ejecutarla en caliente.")
            else:
                lines.append("Sin cambios propuestos por ahora.")
            return {"reply": "\n".join(lines), "proposal": analysis["proposal"], "analysis": analysis}

        # ── Aplicar propuesta pendiente
        if msg == "aplica" or msg.startswith("aplica "):
            pending = None
            if self.memory["proposals"]:
                pending = self.memory["proposals"][-1].get("proposal") or {}
            if not pending:
                return {"reply": "No hay una propuesta pendiente. Escribe 'análisis' primero."}
            res = self.apply_proposal(pending, reason="aprobado por chat")
            if res["ok"]:
                return {"reply": "✅ Aplicado en caliente: " + json.dumps(res["applied"], ensure_ascii=False)}
            return {"reply": "❌ " + res.get("error", "no se pudo aplicar")}

        # ── Órdenes puntuales
        m = re.search(r"(?:stake|monto|presupuesto|importe|por operación|por operacion)\s*(?:a|de|en)?\s*" + self._NUM, msg)
        if m:
            v = round(float(m.group(1)), 2)
            return self._set("stake", v, f"stake a ${v:.2f}")

        m = re.search(r"(?:confianza|confidence|conf)\s*(?:mínima|minima|min)?\s*(?:a|de)?\s*" + self._NUM, msg)
        if m:
            v = float(m.group(1))
            return self._set("min_confidence", v, f"confianza mínima a {v}")

        m = re.search(r"(?:activo|asset|par|symbol)\s*(?:a|de|en)?\s*([a-z0-9\-\.]+)", msg)
        if m:
            v = m.group(1).upper()
            return self._set("asset", v, f"activo a {v}")

        m = re.search(r"(?:max|máximo|maximo|máx)\s*(?:pérdidas|perdidas|perdidas consecutivas|pérdidas consecutivas|losses)\s*(?:a|de)?\s*" + self._NUM, msg)
        if m:
            v = int(float(m.group(1)))
            return self._set("max_consecutive_losses", v, f"máx pérdidas consecutivas a {v}")

        m = re.search(r"(?:cooldown|enfriamiento)\s*(?:a|de)?\s*" + self._NUM, msg)
        if m:
            v = int(float(m.group(1)))
            return self._set("cooldown_after_loss", v, f"cooldown a {v}s")

        m = re.search(r"(?:entre trades|entre operaciones|espaciado|tiempo mínimo)\s*(?:a|de)?\s*" + self._NUM, msg)
        if m:
            v = int(float(m.group(1)))
            return self._set("min_between_trades", v, f"mínimo entre trades a {v}s")

        if re.search(r"(modo|cuenta|account)\s*(?:a|de|en)?\s*(paper|practice|demo)", msg):
            mode = re.search(r"(paper|practice|demo)", msg).group(1)
            if mode == "demo":
                mode = "practice"
            return self._set("mode", mode, f"modo a {mode}", mode_ok=True)

        return {"reply": (
            "No entendí. Comandos: 'estado', 'análisis', 'aplica', "
            "'stake a X', 'confianza a X', 'activo a X', 'max pérdidas a X', "
            "'cooldown a X', 'modo paper/practice'. O 'ayuda'.")}

    def _set(self, key: str, value, label: str, mode_ok: bool = False) -> dict:
        res = self.apply_proposal({key: value}, reason=label, mode_ok=mode_ok)
        if res["ok"]:
            return {"reply": f"✅ {label} aplicado en caliente.", "applied": res["applied"]}
        return {"reply": "❌ " + res.get("error", "valor no válido")}


architect = ArchitectAI()
