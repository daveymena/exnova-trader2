"""AI Provider Registry - Multi-provider fallback system.

Uses OpenAI-compatible API format for all providers.
Supports: OpenCode Zen, NVIDIA NIM, OpenRouter, GitHub Models, Ollama.
All providers have usable free tiers.
"""
import os
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable
from openai import OpenAI

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    models: list[str]
    default_model: str
    timeout: float = 10.0
    rpm_limit: int = 30
    enabled: bool = True
    priority: int = 100


@dataclass
class ProviderStatus:
    name: str
    healthy: bool = True
    last_failure: float = 0.0
    consecutive_failures: int = 0
    cooldown_until: float = 0.0


class AIProviderRegistry:
    def __init__(self):
        self.providers: dict[str, ProviderConfig] = {}
        self.status: dict[str, ProviderStatus] = {}
        self.clients: dict[str, OpenAI] = {}
        self._load_providers()

    def _load_providers(self):
        providers = []

        # 1. FastOpenAI / FreeModel (Hermes Engine) -- opt-in via environment key
        #    Models: gpt-5.5, deepseek-v4-flash-free, deepseek-v3-ultra-free, big-pickle
        #    Si quieres sobreescribir la key, usa FAST_OPENAI_API_KEY o FREEMODEL_API_KEY
        fast_openai_key = os.getenv("FAST_OPENAI_API_KEY") or os.getenv("FREEMODEL_API_KEY", "")
        fast_openai_url = (
            os.getenv("FAST_OPENAI_API_URL") or
            os.getenv("FREEMODEL_API_URL") or
            "https://api.freemodel.dev/v1"
        )
        if fast_openai_key:
            providers.append(ProviderConfig(
                name="fast_openai",
                base_url=fast_openai_url,
                api_key=fast_openai_key,
                models=[
                # GPT
                "gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex",
                # DeepSeek
                "deepseek-v4-flash-free", "deepseek-v3-ultra-free",
                # Claude
                "claude-fable-5", "claude-sonnet-4-6",
                "claude-haiku-4-5-20251001", "claude-opus-4-6",
                "claude-opus-4-7", "claude-opus-4-8",
                # Fallback
                "big-pickle",
            ],
                default_model=os.getenv("FAST_OPENAI_MODEL", "gpt-5.5"),
                priority=5,
            ))

        # 2. OpenCode Zen (primary)
        if os.getenv("OPENCODE_ZEN_API_KEY") or os.getenv("OPENCODE_API_KEY"):
            key = os.getenv("OPENCODE_ZEN_API_KEY") or os.getenv("OPENCODE_API_KEY", "")
            providers.append(ProviderConfig(
                name="opencode_zen",
                base_url=os.getenv("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1"),
                api_key=key,
                models=[
                    "deepseek-v4-flash-free", "deepseek-v3-ultra-free",
                    "big-pickle", "opencode/qwen3.6-plus-free",
                    "gpt-5.4-mini", "gpt-5.5",
                ],
                default_model=os.getenv("AI_MODEL", "deepseek-v4-flash-free"),
                priority=10,
            ))

        # 3. NVIDIA NIM (free tier - 40 RPM, 100+ models)
        if os.getenv("NVIDIA_API_KEY"):
            providers.append(ProviderConfig(
                name="nvidia_nim",
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=os.getenv("NVIDIA_API_KEY", ""),
                models=[
                    "meta/llama-3.3-70b-instruct",
                    "meta/llama-3.1-8b-instruct",
                    "meta/llama-3.1-405b-instruct",
                    "mistralai/mistral-7b-instruct-v0.3",
                ],
                default_model=os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
                timeout=15.0,
                priority=20,
            ))

        # 3. NVIDIA NIM Bridge (local proxy)
        if os.getenv("NVIDIA_NIM_BRIDGE_URL"):
            providers.append(ProviderConfig(
                name="nvidia_bridge",
                base_url=os.getenv("NVIDIA_NIM_BRIDGE_URL", "http://localhost:3000/v1"),
                api_key=os.getenv("NVIDIA_NIM_BRIDGE_API_KEY", "no-key-required"),
                models=["moonshotai/kimi-k2.6"],
                default_model=os.getenv("NVIDIA_NIM_BRIDGE_MODEL", "moonshotai/kimi-k2.6"),
                timeout=8.0,
                priority=25,
            ))

        # 4. GitHub Models / Azure (free - gpt-4o-mini, Llama, etc.)
        if os.getenv("GITHUB_TOKEN"):
            providers.append(ProviderConfig(
                name="github_models",
                base_url="https://models.inference.ai.azure.com",
                api_key=os.getenv("GITHUB_TOKEN", ""),
                models=[
                    "gpt-4o-mini", "gpt-4o",
                    "meta-llama-3.3-70b-instruct",
                    "claude-sonnet-4-20250514",
                    "claude-haiku-4-5",
                ],
                default_model=os.getenv("GITHUB_MODEL", "gpt-4o-mini"),
                timeout=8.0,
                priority=30,
            ))

        # 5. OpenRouter (free models with rate limits)
        if os.getenv("OPENROUTER_API_KEY"):
            free_models = os.getenv(
                "OPENROUTER_MODELS_FREE",
                "meta-llama/llama-3.1-8b-instruct,mistralai/mistral-7b-instruct"
            ).split(",")
            providers.append(ProviderConfig(
                name="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key=os.getenv("OPENROUTER_API_KEY", ""),
                models=[m.strip() for m in free_models],
                default_model="openrouter/auto",
                timeout=10.0,
                priority=40,
            ))

        # 6. Ollama local + cloud
        # Local models (confirmed working): llama-free, llama3.2:1b, minicpm-v
        # Cloud models (via ollama.com): minimax-m3, kimi-k2.5, gemma4:31b, qwen3-vl:235b
        ollama_url = os.getenv("OLLAMA_LOCAL_URL", "http://localhost:11434")
        ollama_model = os.getenv("OLLAMA_LOCAL_MODEL", "llama-free:latest")
        ollama_models = [
            # Local (fast/lightweight)
            "llama-free:latest", "llama3.2:1b", "minicpm-v:latest",
            # Cloud (via ollama.com)
            "minimax-m3:cloud", "kimi-k2.5:cloud",
            "gemma4:31b-cloud", "qwen3-vl:235b-cloud",
            # Explicit env override
            ollama_model,
        ]
        # Deduplicate
        ollama_models = list(dict.fromkeys(ollama_models))
        providers.append(ProviderConfig(
            name="ollama",
            base_url=ollama_url,
            api_key="ollama",
            models=ollama_models,
            default_model=ollama_model,
            timeout=30.0,
            priority=50,
        ))

        # 7. Bridge Local
        if os.getenv("BRIDGE_LOCAL_URL"):
            providers.append(ProviderConfig(
                name="bridge_local",
                base_url=os.getenv("BRIDGE_LOCAL_URL", "http://localhost:8000/api/v1"),
                api_key=os.getenv("BRIDGE_LOCAL_API_KEY", ""),
                models=[os.getenv("BRIDGE_LOCAL_MODEL", "deepseek-v4-flash")],
                default_model=os.getenv("BRIDGE_LOCAL_MODEL", "deepseek-v4-flash"),
                timeout=8.0,
                priority=60,
            ))

        for p in providers:
            self.providers[p.name] = p
            self.status[p.name] = ProviderStatus(name=p.name)
            self.clients[p.name] = OpenAI(
                base_url=p.base_url,
                api_key=p.api_key,
                timeout=p.timeout,
            )

    def get_available_providers(self) -> list[str]:
        now = time.time()
        return [
            name for name, status in self.status.items()
            if status.healthy and now >= status.cooldown_until
            and self.providers[name].enabled
        ]

    def chat(self, messages: list[dict], model: Optional[str] = None,
             provider: Optional[str] = None, max_tokens: int = 1024,
             temperature: float = 0.7) -> Optional[str]:
        if provider:
            return self._chat_with_provider(provider, messages, model, max_tokens, temperature)

        available = self.get_available_providers()
        available.sort(key=lambda n: self.providers[n].priority)

        for prov_name in available:
            result = self._chat_with_provider(prov_name, messages, model, max_tokens, temperature)
            if result is not None:
                return result

        logger.error("All AI providers failed")
        return None

    def _chat_with_provider(self, name: str, messages: list[dict],
                            model: Optional[str], max_tokens: int,
                            temperature: float) -> Optional[str]:
        provider = self.providers.get(name)
        status = self.status.get(name)
        if not provider or not status:
            return None

        try:
            client = self.clients[name]
            model_id = model or provider.default_model

            response = client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            status.consecutive_failures = 0
            status.healthy = True
            return response.choices[0].message.content

        except Exception as e:
            status.consecutive_failures += 1
            status.last_failure = time.time()
            if status.consecutive_failures >= 3:
                status.cooldown_until = time.time() + 30
                logger.warning(f"Provider {name} cooling down for 30s after {status.consecutive_failures} failures")
            if status.consecutive_failures >= 10:
                status.healthy = False
                logger.error(f"Provider {name} marked unhealthy after {status.consecutive_failures} failures")
            logger.warning(f"Provider {name} failed: {e}")
            return None

    def list_models(self, provider: Optional[str] = None) -> list[dict]:
        result = []
        for name, prov in self.providers.items():
            if provider and name != provider:
                continue
            for model in prov.models:
                result.append({
                    "provider": name,
                    "model": model,
                    "base_url": prov.base_url,
                    "priority": prov.priority,
                    "healthy": self.status[name].healthy,
                })
        return result

    def summarize(self, text: str, max_length: int = 200) -> Optional[str]:
        return self.chat([
            {"role": "system", "content": f"Resume el siguiente texto en menos de {max_length} caracteres. Responde solo el resumen."},
            {"role": "user", "content": text},
        ], max_tokens=max_length // 2)

    def analyze_signal(self, signal_data: dict) -> Optional[str]:
        return self.chat([
            {"role": "system", "content": (
                "Eres un auditor de trading no-autoritativo. Explica la señal de trading "
                "de forma clara. No recomiendes ejecutar. Solo analiza."
            )},
            {"role": "user", "content": str(signal_data)},
        ], max_tokens=300)

    def explain_rejection(self, signal: dict, reason: str) -> Optional[str]:
        return self.chat([
            {"role": "system", "content": "Explica por qué esta señal de trading fue rechazada. Máximo 2 oraciones."},
            {"role": "user", "content": f"Señal: {signal}\nRazón: {reason}"},
        ], max_tokens=150)


ai_registry = AIProviderRegistry()
