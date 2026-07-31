"""Optional, non-authoritative AI auditor.

May explain signals, detect contradictions, summarize results,
and suggest research experiments. Never overrides risk or execution.
Uses AIProviderRegistry for multi-model free inference.
"""
import json
from typing import Optional

from app.data.schemas import Direction, MarketRegime, TradeDecision
from app.services.ai_provider import ai_registry


class AIAuditorAgent:
    def __init__(self, enabled: bool = False, provider: Optional[str] = None,
                 model: Optional[str] = None):
        self.enabled = enabled
        self.provider = provider
        self.model = model
        self._avail = ai_registry.get_available_providers()

    def explain_signal(self, decision: TradeDecision) -> str:
        if not self.enabled:
            return "AI auditor disabled"

        prompt = (
            f"Explica esta señal de trading en un párrafo claro y conciso:\n"
            f"- Activo: {decision.asset}\n"
            f"- Dirección: {decision.direction.value}\n"
            f"- Estrategia: {decision.strategy}\n"
            f"- Confianza: {decision.confidence:.2f}\n"
            f"- Régimen de Mercado: {decision.market_regime.value if decision.market_regime else 'desconocido'}\n"
            f"- Timing de Entrada: {decision.entry_timing.value if decision.entry_timing else 'desconocido'}\n"
            f"- Decisión de Riesgo: {decision.risk_decision.value}\n"
        )
        if decision.risk_reason:
            prompt += f"- Razón de Riesgo: {decision.risk_reason}\n"
        prompt += "\nNo recomiendes ejecutar ni des consejo financiero. Solo analiza."

        result = ai_registry.chat(
            [{"role": "system", "content": "Eres un analista de trading explicativo. Responde en español."},
             {"role": "user", "content": prompt}],
            model=self.model, provider=self.provider,
            max_tokens=300, temperature=0.5,
        )
        return result if result else self._fallback_text(decision)

    def _fallback_text(self, decision: TradeDecision) -> str:
        parts = [
            f"Signal: {decision.asset} {decision.direction.value}",
            f"Strategy: {decision.strategy}",
            f"Confidence: {decision.confidence:.2f}",
            f"Market Regime: {decision.market_regime.value if decision.market_regime else 'unknown'}",
            f"Entry Timing: {decision.entry_timing.value if decision.entry_timing else 'unknown'}",
            f"Risk Decision: {decision.risk_decision.value}",
        ]
        if decision.risk_reason:
            parts.append(f"Risk Reason: {decision.risk_reason}")
        if decision.edge_approved:
            parts.append("Edge Validation: Approved")
        else:
            parts.append("Edge Validation: Rejected")
        return "\n".join(parts)

    def detect_contradictions(self, decisions: list[TradeDecision]) -> list[str]:
        contradictions = []
        if not self.enabled or len(decisions) < 2:
            return contradictions

        assets = set(d.asset for d in decisions)
        for asset in assets:
            same = [d for d in decisions if d.asset == asset]
            dirs = set(d.direction.value for d in same)
            if len(dirs) > 1:
                contradictions.append(
                    f"Contradiction on {asset}: agents suggest {', '.join(dirs)}"
                )

        if contradictions and self._avail:
            prompt = (
                f"Analiza estas contradicciones detectadas entre agentes de trading:\n"
                + "\n".join(contradictions) +
                "\n\nSugiere una posible explicación (máximo 2 oraciones). No des consejo."
            )
            result = ai_registry.chat(
                [{"role": "system", "content": "Eres un analista neutral."},
                 {"role": "user", "content": prompt}],
                max_tokens=200, temperature=0.3,
            )
            if result:
                contradictions.append(f"(AI analysis: {result})")

        return contradictions

    def summarize_session(self, decisions: list[TradeDecision]) -> str:
        if not self.enabled:
            return "AI auditor disabled"
        total = len(decisions)
        approved = sum(1 for d in decisions if d.risk_decision.value == "approved")
        rejected = total - approved
        base = f"Session: {total} decisions, {approved} approved, {rejected} rejected"

        if self._avail and total > 3:
            summary = ai_registry.summarize(base, max_length=200)
            return summary if summary else base
        return base

    def suggest_experiment(self, recent_results: list) -> str:
        if not self.enabled or not recent_results:
            return "No experiments suggested (auditor disabled or no data)"

        if self._avail:
            prompt = (
                f"Dados estos resultados recientes de trading:\n{json.dumps(recent_results, default=str)[:1500]}\n\n"
                "Sugiere 1 experimento de investigación para mejorar el rendimiento. "
                "Sé específico pero breve. No recomiendes ejecutar trades."
            )
            result = ai_registry.chat(
                [{"role": "system", "content": "Eres un investigador cuantitativo."},
                 {"role": "user", "content": prompt}],
                max_tokens=300, temperature=0.7,
            )
            return result if result else "No experiments suggested"
        return "No experiments suggested (no AI providers available)"
