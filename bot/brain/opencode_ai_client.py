"""
OPENCODE AI CLIENT — Motor de Razonamiento Principal
Cliente HTTP generico contra cualquier servidor compatible con la API de
chat completions de OpenAI. Pensado para apuntar a un Ollama propio (local
en desarrollo, o desplegado en EasyPanel en produccion) en vez de servicios
de terceros -- asi el "cerebro" de validacion por operacion no depende de
infraestructura ajena.

El endpoint anterior (tecnovariedades-provedor-ia.er7iaf.easypanel.host) y el
modelo por defecto (opencode/deepseek-v4-flash-free) ya no existen; el
default local (localhost:11434, la API OpenAI-compatible que expone Ollama)
se verifico funcionando el 2026-07-31.
"""
import json
import os
import time
import requests
import re
from typing import Dict, List, Optional


# ─── Configuracion del servidor (lee del entorno; default = Ollama local) ──────
OPENCODE_BASE_URL   = os.environ.get("OPENCODE_BASE_URL", "http://localhost:11434/v1")
# Ollama no exige API key para su servidor local/propio; el header
# Authorization se envia igual (algunos proxies lo requieren) pero con un
# valor neutro. NUNCA hardcodear aqui una key real: la anterior quedo
# expuesta en texto plano en el historial de git.
OPENCODE_API_KEY    = os.environ.get("OPENCODE_API_KEY", "ollama-local")
# gemma4:cloud verificado el 2026-07-31: responde en ~1.8s con JSON valido,
# necesario para el timeout de 40s de este cliente. Modelos locales puros
# (no ":cloud") tardan >90s en este hardware -- inviables para validacion
# de operacion en tiempo real, solo sirven para tareas sin limite de tiempo.
OPENCODE_MODEL_FAST = os.environ.get("OPENCODE_MODEL_FAST", "gemma4:cloud")
OPENCODE_MODEL_DEEP = os.environ.get("OPENCODE_MODEL_DEEP", "gemma4:cloud")
TIMEOUT_SECONDS     = 40   # El servidor puede tardar hasta 35s en responder

SYSTEM_PROMPT_TRADER = """Eres un trader profesional con 10 años de experiencia en opciones binarias OTC.
Tu rol es analizar señales de trading y proporcionar veredictos precisos en formato JSON.
Siempre respondes ÚNICAMENTE con un objeto JSON válido, sin texto adicional, sin markdown.
Tu análisis considera: zonas de soporte/resistencia, RSI, patrones de vela, tendencia y coherencia técnica.
Eres conservador: si hay duda, prefieres WAIT sobre ENTER."""


class OpenCodeAIClient:
    """
    Cliente para el servidor OpenAI-compatible en EasyPanel.
    Provee razonamiento IA profundo para el bot de trading.
    """

    def __init__(self):
        self.base_url   = OPENCODE_BASE_URL
        self.api_key    = OPENCODE_API_KEY
        self.model_fast = OPENCODE_MODEL_FAST
        self.model_deep = OPENCODE_MODEL_DEEP
        self.headers    = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        self.calls_made    = 0
        self.calls_failed  = 0
        self.calls_saved   = 0
        self.avg_resp_time = 0.0
        self._resp_times   = []

        print("[OK] OpenCode AI Client inicializado")
        print(f"    Endpoint: {self.base_url}")
        print(f"    Modelo rapido: {self.model_fast}")
        print(f"    Modelo profundo: {self.model_deep}")

    # ── API Principal ──────────────────────────────────────────────────────────

    def analyze_trade(
        self,
        market_context: Dict,
        current_analysis: Dict,
        deep: bool = False
    ) -> Optional[Dict]:
        """
        Analiza una oportunidad de trade usando IA.

        Args:
            market_context:    Datos del mercado (activo, precio, RSI, patrón, etc.)
            current_analysis:  Análisis previo del sistema local
            deep:              Si True, usa el modelo de razonamiento profundo

        Returns:
            Dict con {direction, confidence, decision, reasoning} o None si falla
        """
        model = self.model_deep if deep else self.model_fast

        asset       = market_context.get("asset",    "UNKNOWN")
        price       = market_context.get("price",    0)
        rsi         = market_context.get("rsi",      50)
        trend       = market_context.get("trend",    "NEUTRAL")
        pattern     = market_context.get("pattern",  "none")
        zone_type   = market_context.get("zone_type","unknown")
        zone_level  = market_context.get("zone",     0)
        zone_str    = market_context.get("zone_strength", 0.0)
        session     = market_context.get("session",  "DESCONOCIDA")
        win_rate    = current_analysis.get("win_rate_bot", 0.52)
        incoherences= current_analysis.get("incoherences_detected", [])
        local_dir   = current_analysis.get("direction", "NEUTRAL")
        local_conf  = current_analysis.get("confidence", 0)
        local_reason= current_analysis.get("reasoning", [])

        prompt = f"""Analiza esta señal de trading en opciones binarias OTC y devuelve un JSON:

MERCADO:
- Activo: {asset}
- Precio actual: {price}
- RSI: {rsi:.1f}
- Tendencia: {trend}
- Patrón de vela: {pattern}
- Zona técnica: {zone_type} @ {zone_level} (fuerza={zone_str:.2f})
- Sesión: {session}

ANÁLISIS LOCAL:
- Dirección propuesta: {local_dir}
- Confianza local: {local_conf:.0f}%
- Incoherencias detectadas: {len(incoherences)}
- Razonamiento: {'; '.join(local_reason[:3])}
- Win Rate actual del bot: {win_rate:.1%}

INSTRUCCIÓN: Analiza la coherencia técnica. Revisa si la dirección propuesta tiene sentido con el RSI, zona y patrón.
Si hay incoherencias, corrígelas. Sé conservador.

RESPONDE SOLO CON ESTE JSON (sin ningún otro texto):
{{
    "direction": "CALL" o "PUT" o "NEUTRAL",
    "confidence": número entre 0 y 100,
    "decision": "ENTER" o "WAIT" o "SKIP",
    "reasoning": "explicación técnica breve en español (máximo 120 caracteres)",
    "risk_level": "LOW" o "MEDIUM" o "HIGH",
    "correction_applied": true o false
}}"""

        return self._call(
            model    = model,
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT_TRADER},
                {"role": "user",   "content": prompt}
            ],
            tag = f"TRADE-{asset}"
        )

    def learn_from_result(
        self,
        trade_data: Dict,
        trade_result: str,
        pnl: float
    ) -> Optional[Dict]:
        """
        Consulta a la IA qué lección extraer de un trade ya cerrado.
        Produce reglas de mejora continua.

        Returns:
            Dict con {lesson, rule_update, confidence_adjustment} o None
        """
        asset       = trade_data.get("asset",    "UNKNOWN")
        direction   = trade_data.get("direction","NEUTRAL")
        pattern     = trade_data.get("pattern",  "none")
        zone_str    = trade_data.get("zone_strength", 0.0)
        rsi_entry   = trade_data.get("rsi_at_touch", 50)
        trend_align = trade_data.get("trend_aligned", False)

        prompt = f"""Analiza el resultado de este trade cerrado y extrae una lección de mejora:

TRADE EJECUTADO:
- Activo: {asset}
- Dirección: {direction}
- Patrón: {pattern}
- Fuerza de zona: {zone_str:.2f}
- RSI en entrada: {rsi_entry:.1f}
- Tendencia alineada: {"SI" if trend_align else "NO"}
- Resultado: {trade_result}
- PnL: {"+$" if pnl >= 0 else "-$"}{abs(pnl):.2f}

INSTRUCCIÓN: Identifica por qué {("ganó" if trade_result=="WIN" else "perdió")} este trade.
Proporciona una regla de mejora concreta y ajuste de confianza para futuros trades similares.

RESPONDE SOLO CON ESTE JSON:
{{
    "lesson": "lección principal en español (máximo 150 caracteres)",
    "pattern_confidence_delta": número entre -0.15 y +0.15,
    "zone_rule": "descripción de qué hacer en zonas similares (máximo 100 caracteres)",
    "avoid_condition": "condición a evitar en el futuro (máximo 100 caracteres) o null",
    "reinforce_condition": "condición a reforzar (máximo 100 caracteres) o null"
}}"""

        return self._call(
            model    = self.model_fast,
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT_TRADER},
                {"role": "user",   "content": prompt}
            ],
            tag = f"LEARN-{asset}-{trade_result}"
        )

    def evaluate_session_performance(self, session_trades: List[Dict]) -> Optional[Dict]:
        """
        Evalúa el rendimiento de la sesión actual y sugiere ajustes estratégicos.
        Usa el modelo de razonamiento profundo.
        """
        if not session_trades:
            return None

        wins   = sum(1 for t in session_trades if t.get("result") == "WIN")
        losses = sum(1 for t in session_trades if t.get("result") == "LOSS")
        total  = len(session_trades)
        pnl    = sum(t.get("pnl", 0) for t in session_trades)

        # Resumir los trades para no sobrecargar el prompt
        trade_summary = []
        for t in session_trades[-8:]:  # Últimos 8
            trade_summary.append(
                f"{t.get('asset','?')} {t.get('direction','?')} "
                f"({t.get('pattern','?')}) → {t.get('result','?')}"
            )

        prompt = f"""Evalúa el desempeño de esta sesión de trading y proporciona ajustes estratégicos:

SESIÓN ACTUAL:
- Total trades: {total}
- Wins: {wins} | Losses: {losses}
- Win Rate: {(wins/total*100) if total > 0 else 0:.1f}%
- PnL Total: {'+$' if pnl >= 0 else '-$'}{abs(pnl):.2f}

ÚLTIMOS TRADES:
{chr(10).join(trade_summary)}

INSTRUCCIÓN: Analiza si hay patrones de error recurrentes. ¿Hay activos o patrones que están fallando?
¿Debe el bot aumentar o disminuir la selectividad? ¿Pausar algún activo?

RESPONDE SOLO CON ESTE JSON:
{{
    "session_grade": "A" o "B" o "C" o "D",
    "main_issue": "principal problema identificado en español (máximo 120 caracteres)",
    "recommendation": "acción concreta a tomar (máximo 120 caracteres)",
    "assets_to_pause": ["lista de activos a pausar, puede estar vacía"],
    "increase_selectivity": true o false,
    "confidence_multiplier": número entre 0.7 y 1.3
}}"""

        return self._call(
            model    = self.model_deep,
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT_TRADER},
                {"role": "user",   "content": prompt}
            ],
            tag = "SESSION-EVAL"
        )

    # ── Interno ────────────────────────────────────────────────────────────────

    def _call(self, model: str, messages: List[Dict], tag: str = "") -> Optional[Dict]:
        """Realiza la llamada al endpoint OpenAI-compatible con reintentos y parsea el JSON."""
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(1, max_retries + 1):
            t0 = time.time()
            try:
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=self.headers,
                    json={
                        "model":       model,
                        "messages":    messages,
                        "temperature": 0.3,
                        "max_tokens":  400,
                    },
                    timeout=TIMEOUT_SECONDS,
                )
                elapsed = time.time() - t0
                self._track_time(elapsed)

                if resp.status_code == 200:
                    data    = resp.json()
                    content = data["choices"][0]["message"]["content"].strip()
                    result  = self._parse_json(content)

                    if result is not None:
                        self.calls_made += 1
                        try:
                            print(f"[AI] OpenCode [{tag}] OK en {elapsed:.1f}s | modelo={model.split('/')[-1]}")
                        except Exception:
                            pass
                        return result
                    else:
                        try:
                            print(f"[!] OpenCode AI [{tag}] JSON inválido en intento {attempt}/{max_retries}: {content[:150]}")
                        except Exception:
                            pass
                        if attempt < max_retries:
                            time.sleep(retry_delay)
                            continue
                        self.calls_failed += 1
                        return None
                
                elif resp.status_code == 429:
                    try:
                        print(f"[!] OpenCode AI [{tag}] Límite de velocidad (429) en intento {attempt}/{max_retries}. Esperando {retry_delay}s...")
                    except Exception:
                        pass
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                        continue
                    self.calls_failed += 1
                    return None
                else:
                    try:
                        print(f"[!] OpenCode AI [{tag}] Error HTTP {resp.status_code} en intento {attempt}/{max_retries}: {resp.text[:200]}")
                    except Exception:
                        pass
                    if attempt < max_retries:
                        time.sleep(retry_delay)
                        continue
                    self.calls_failed += 1
                    return None

            except requests.exceptions.Timeout:
                try:
                    print(f"[!] OpenCode AI [{tag}] Timeout en intento {attempt}/{max_retries}...")
                except Exception:
                    pass
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                self.calls_failed += 1
                return None
            except Exception as e:
                try:
                    print(f"[!] OpenCode AI [{tag}] Error en intento {attempt}/{max_retries}: {e}")
                except Exception:
                    pass
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                self.calls_failed += 1
                return None
        return None

    def _parse_json(self, content: str) -> Optional[Dict]:
        """Extrae y parsea el primer objeto JSON de un texto."""
        # Intentar directo
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Buscar bloque JSON entre llaves
        match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Buscar bloque de código markdown
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        return None

    def _track_time(self, elapsed: float) -> None:
        self._resp_times.append(elapsed)
        if len(self._resp_times) > 20:
            self._resp_times.pop(0)
        self.avg_resp_time = sum(self._resp_times) / len(self._resp_times)

    def get_stats(self) -> Dict:
        total = self.calls_made + self.calls_failed
        return {
            "calls_made":    self.calls_made,
            "calls_failed":  self.calls_failed,
            "success_rate":  f"{(self.calls_made / total * 100) if total > 0 else 0:.1f}%",
            "avg_resp_time": f"{self.avg_resp_time:.1f}s",
            "model_fast":    self.model_fast,
            "model_deep":    self.model_deep,
        }


# Singleton
_client: Optional[OpenCodeAIClient] = None


def get_opencode_client() -> OpenCodeAIClient:
    global _client
    if _client is None:
        _client = OpenCodeAIClient()
    return _client
