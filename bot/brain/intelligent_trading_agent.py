"""
🤖 AGENTE INTELIGENTE DE TRADING
Trader experimentado con IA integrada
- Contexto completo del sistema
- Detecta y corrige incoherencias automáticamente
- Usa IA estratégicamente (ahorra tokens)
- Toma decisiones propias
- Mejora continuamente
"""
import json
import time
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from datetime import datetime

from .copilot_auth_real import get_copilot_auth_real
from .incoherence_detector import get_incoherence_detector
from .local_ai_predictor import get_local_ai_predictor
from .trade_persistence import get_trade_persistence
from .github_models_client import get_github_models_client
from .opencode_ai_client import get_opencode_client


class IntelligentTradingAgent:
    """
    Agente de trading inteligente
    - Trader experimentado
    - Contexto completo
    - IA integrada estratégicamente
    """

    def __init__(self, github_token: str):
        self.name = "Intelligent Trading Agent v2.0"
        self.version = "2.0"
        self.github_token = github_token
        
        # Componentes
        self.auth = get_copilot_auth_real(github_token)
        self.detector = get_incoherence_detector()
        self.predictor = get_local_ai_predictor()
        self.persistence = get_trade_persistence()
        self.github_models = get_github_models_client(github_token)
        # Motor de IA principal — EasyPanel OpenCode (OpenAI-compatible)
        self.opencode = get_opencode_client()
        
        # Estado del agente
        self.authenticated = False
        self.context = {
            'trades_analyzed': 0,
            'incoherences_fixed': 0,
            'ai_calls_made': 0,
            'ai_calls_saved': 0,
            'decisions_made': 0,
            'win_rate': 0.524,
            'pnl_total': 160.15,
            'last_analysis': None,
            'learned_rules': []
        }
        
        # Historial de decisiones
        self.decisions = []
        self.corrections_applied = []
        self.ai_analyses = []
        
        # Reglas aprendidas (para evitar llamadas a IA)
        self.learned_rules = self._initialize_learned_rules()
        
        # Modelos de GitHub Models
        self.models_config = {
            'fast': 'openai/gpt-4.1-mini',      # Rápido, tier bajo
            'quality': 'openai/gpt-4.1',         # Mejor calidad, tier alto
            'alternative': 'meta/llama-3.3-70b-instruct'  # Alternativa a Claude
        }
        
        print(f"[OK] {self.name} inicializado")
        self._initialize()

    # ═══════════════════════════════════════════════════════════════════════════════
    # INICIALIZACIÓN
    # ═══════════════════════════════════════════════════════════════════════════════

    def _initialize(self) -> None:
        """Inicializa el agente"""
        
        print(f"\n[*] Inicializando agente...")
        
        # Autenticar
        if self.auth.verify_token():
            self.authenticated = True
            print(f"[OK] Autenticado con GitHub Copilot")
        else:
            print(f"[!] No autenticado - modo local")
        
        # Cargar modelos de GitHub Models
        print(f"\n[*] Cargando modelos de GitHub Models...")
        models = self.github_models.load_available_models()
        if models:
            print(f"[OK] {len(models)} modelos cargados")
        else:
            print(f"[!] No se pudieron cargar modelos de GitHub Models")
        
        # Cargar contexto
        self._load_context()
        
        print(f"[OK] Agente listo")

    def _load_context(self) -> None:
        """Carga contexto completo del sistema"""
        
        print(f"\n[*] Cargando contexto del sistema...")
        
        # Trades
        trades = self.persistence.trades
        self.context['trades_analyzed'] = len(trades)
        
        # Análisis
        analysis = self.predictor.analyze_trades()
        self.context['win_rate'] = analysis.get('win_rate', 0.524)
        self.context['pnl_total'] = analysis.get('pnl_total', 160.15)
        
        # Incoherencias
        incoherences = self.detector.detect_all_incoherences()
        self.context['incoherences_detected'] = len(incoherences)
        
        # Activos
        self.context['best_assets'] = analysis.get('best_assets', [])
        self.context['worst_assets'] = analysis.get('worst_assets', [])
        
        # Patrones
        self.context['best_patterns'] = analysis.get('best_patterns', [])
        self.context['worst_patterns'] = analysis.get('worst_patterns', [])
        
        print(f"[OK] Contexto cargado")
        print(f"    Trades: {self.context['trades_analyzed']}")
        print(f"    Win Rate: {self.context['win_rate']:.1%}")
        print(f"    Incoherencias: {self.context.get('incoherences_detected', 0)}")

    def _initialize_learned_rules(self) -> Dict:
        """Inicializa reglas aprendidas (evita llamadas a IA)"""
        
        return {
            'zone_logic': {
                'support': 'CALL',      # Comprar en soporte
                'resistance': 'PUT',    # Vender en resistencia
                'confidence': 0.95      # Muy confiable
            },
            'rsi_logic': {
                'oversold': {'threshold': 30, 'direction': 'CALL'},
                'overbought': {'threshold': 70, 'direction': 'PUT'},
                'confidence': 0.85
            },
            'pattern_logic': {
                'pin_bar_bullish': {'direction': 'CALL', 'confidence': 0.75},
                'pin_bar_bearish': {'direction': 'PUT', 'confidence': 0.75},
                'bullish_engulfing': {'direction': 'CALL', 'confidence': 0.70},
                'bearish_engulfing': {'direction': 'PUT', 'confidence': 0.70},
                'micro_structure': {'direction': 'NEUTRAL', 'confidence': 0.55},
                'none': {'direction': 'NEUTRAL', 'confidence': 0.30}
            },
            'asset_logic': {
                'EURJPY-OTC': {'bias': 'CALL', 'confidence': 0.60, 'volume_mult': 1.5},
                'GBPUSD-OTC': {'bias': 'NEUTRAL', 'confidence': 0.80, 'volume_mult': 1.3},
                'EURUSD-OTC': {'bias': 'NEUTRAL', 'confidence': 0.75, 'volume_mult': 1.2},
                'AUDUSD-OTC': {'status': 'ACTIVE', 'bias': 'NEUTRAL', 'confidence': 0.60, 'volume_mult': 0.8}
            },
            'validation_rules': {
                'require_pattern': False,
                'pattern_confidence_min': 0.30,
                'rsi_extremes_only': False,
                'zone_hold_rate_min': 0.30,
                'min_confidence': 0.30
            }
        }

    # ═══════════════════════════════════════════════════════════════════════════════
    # ANÁLISIS DE TRADE (CONTEXTO COMPLETO)
    # ═══════════════════════════════════════════════════════════════════════════════

    def analyze_trade_opportunity(self, market_context: Dict) -> Dict:
        """
        Analiza oportunidad de trade con contexto completo
        Detecta incoherencias automáticamente
        """
        
        asset = market_context.get('asset', 'UNKNOWN')
        price = market_context.get('price', 0)
        rsi = market_context.get('rsi', 50)
        trend = market_context.get('trend', 'NEUTRAL')
        pattern = market_context.get('pattern', 'none')
        zone_type = market_context.get('zone_type', 'unknown')
        zone = market_context.get('zone', 'unknown')
        
        analysis = {
            'timestamp': time.time(),
            'asset': asset,
            'market_context': market_context,
            'decision': 'WAIT',
            'direction': 'NEUTRAL',
            'confidence': 0,
            'reasoning': [],
            'incoherences_detected': [],
            'corrections_applied': [],
            'ai_used': False,
            'ai_reason': None
        }
        
        # ─────────────────────────────────────────────────────────────────────────
        # PASO 1: Validaciones Básicas (Sin IA)
        # ─────────────────────────────────────────────────────────────────────────
        
        # Verificar si activo está pausado
        if asset in self.learned_rules['asset_logic']:
            asset_rule = self.learned_rules['asset_logic'][asset]
            if asset_rule.get('status') == 'PAUSED':
                analysis['decision'] = 'SKIP'
                analysis['reasoning'].append(f"Activo pausado: {asset_rule.get('reason')}")
                return analysis
        
        # ─────────────────────────────────────────────────────────────────────────
        # PASO 2: Aplicar Reglas Aprendidas (Sin IA)
        # ─────────────────────────────────────────────────────────────────────────
        
        # Regla 1: Lógica de Zonas
        if zone_type in self.learned_rules['zone_logic']:
            expected_direction = self.learned_rules['zone_logic'][zone_type]
            analysis['reasoning'].append(f"Zona {zone_type} → {expected_direction}")
            
            # Detectar incoherencia
            if zone_type == 'resistance' and market_context.get('direction') == 'CALL':
                incoherence = {
                    'type': 'WRONG_DIRECTION_FOR_ZONE',
                    'detected': f"COMPRA en RESISTENCIA",
                    'correction': f"Cambiar a {expected_direction}"
                }
                analysis['incoherences_detected'].append(incoherence)
                analysis['corrections_applied'].append(incoherence['correction'])
                analysis['direction'] = expected_direction
            elif zone_type == 'support' and market_context.get('direction') == 'PUT':
                incoherence = {
                    'type': 'WRONG_DIRECTION_FOR_ZONE',
                    'detected': f"VENTA en SOPORTE",
                    'correction': f"Cambiar a {expected_direction}"
                }
                analysis['incoherences_detected'].append(incoherence)
                analysis['corrections_applied'].append(incoherence['correction'])
                analysis['direction'] = expected_direction
            else:
                analysis['direction'] = expected_direction
            
            analysis['confidence'] += self.learned_rules['zone_logic']['confidence'] * 100
        
        # Regla 2: Lógica de RSI
        if rsi < self.learned_rules['rsi_logic']['oversold']['threshold']:
            rsi_direction = self.learned_rules['rsi_logic']['oversold']['direction']
            analysis['reasoning'].append(f"RSI {rsi} (sobreventa) → {rsi_direction}")
            analysis['confidence'] += self.learned_rules['rsi_logic']['confidence'] * 100
            
            # Detectar incoherencia
            if analysis['direction'] != rsi_direction and analysis['direction'] != 'NEUTRAL':
                incoherence = {
                    'type': 'RSI_DIRECTION_MISMATCH',
                    'detected': f"RSI {rsi} pero dirección {analysis['direction']}",
                    'correction': f"Cambiar a {rsi_direction}"
                }
                analysis['incoherences_detected'].append(incoherence)
                analysis['corrections_applied'].append(incoherence['correction'])
                analysis['direction'] = rsi_direction
            else:
                analysis['direction'] = rsi_direction
        
        elif rsi > self.learned_rules['rsi_logic']['overbought']['threshold']:
            rsi_direction = self.learned_rules['rsi_logic']['overbought']['direction']
            analysis['reasoning'].append(f"RSI {rsi} (sobrecompra) → {rsi_direction}")
            analysis['confidence'] += self.learned_rules['rsi_logic']['confidence'] * 100
            
            # Detectar incoherencia
            if analysis['direction'] != rsi_direction and analysis['direction'] != 'NEUTRAL':
                incoherence = {
                    'type': 'RSI_DIRECTION_MISMATCH',
                    'detected': f"RSI {rsi} pero dirección {analysis['direction']}",
                    'correction': f"Cambiar a {rsi_direction}"
                }
                analysis['incoherences_detected'].append(incoherence)
                analysis['corrections_applied'].append(incoherence['correction'])
                analysis['direction'] = rsi_direction
            else:
                analysis['direction'] = rsi_direction
        
        # Regla 3: Lógica de Patrones
        if pattern in self.learned_rules['pattern_logic']:
            pattern_rule = self.learned_rules['pattern_logic'][pattern]
            pattern_direction = pattern_rule['direction']
            pattern_confidence = pattern_rule['confidence']
            
            if pattern_direction != 'NEUTRAL':
                analysis['reasoning'].append(f"Patrón {pattern} → {pattern_direction}")
                analysis['confidence'] += pattern_confidence * 100
                
                if analysis['direction'] == 'NEUTRAL':
                    analysis['direction'] = pattern_direction
            elif pattern == 'micro_structure':
                analysis['reasoning'].append(f"Patrón {pattern} detectado (conf {pattern_confidence})")
                analysis['confidence'] += pattern_confidence * 100
            else:
                analysis['reasoning'].append(f"Patrón {pattern} es débil (conf {pattern_confidence})")
                analysis['confidence'] -= 20
        
        # ─────────────────────────────────────────────────────────────────────────
        # PASO 3: Validación de Confianza
        # ─────────────────────────────────────────────────────────────────────────
        
        analysis['confidence'] = min(100, max(0, analysis['confidence']))
        
        if analysis['confidence'] >= 55:
            analysis['decision'] = 'STRONG_ENTER'
        elif analysis['confidence'] >= 20:
            analysis['decision'] = 'ENTER'
        else:
            analysis['decision'] = 'WAIT'
        
        # ─────────────────────────────────────────────────────────────────────────
        # PASO 4: Usar IA Solo Si Es Necesario (Ahorra Tokens)
        # ─────────────────────────────────────────────────────────────────────────
        
        # Usar IA si:
        # 1. Hay incoherencias complejas
        # 2. Confianza está entre 45-55% (dudoso)
        # 3. Patrón es desconocido
        
        should_use_ai = False
        ai_reason = None
        
        if len(analysis['incoherences_detected']) > 1:
            should_use_ai = True
            ai_reason = "Múltiples incoherencias detectadas"
        elif 45 <= analysis['confidence'] <= 55:
            should_use_ai = True
            ai_reason = "Confianza dudosa (45-55%)"
        elif pattern not in self.learned_rules['pattern_logic']:
            should_use_ai = True
            ai_reason = f"Patrón desconocido: {pattern}"
        
        _opencode_ready = (
            self.opencode is not None
            and self.opencode.api_key not in (None, "", "ollama-local")
        )
        if should_use_ai and (self.authenticated or _opencode_ready):
            analysis['ai_used'] = True
            analysis['ai_reason'] = ai_reason
            
            # Llamar a IA para análisis profundo
            ai_analysis = self._call_ai_for_analysis(market_context, analysis)
            
            if ai_analysis:
                analysis['ai_response'] = ai_analysis
                analysis['confidence'] = ai_analysis.get('confidence', analysis['confidence'])
                analysis['direction'] = ai_analysis.get('direction', analysis['direction'])
                # IA solo puede mejorar una decisión o bloquear si es SKIP
                ai_decision = ai_analysis.get('decision', analysis['decision'])
                if ai_decision == 'SKIP':
                    analysis['decision'] = 'SKIP'
                elif analysis['decision'] in ('ENTER', 'STRONG_ENTER'):
                    pass  # mantener decisión local si ya era ENTER
                elif ai_decision == 'ENTER' and analysis['decision'] == 'WAIT':
                    analysis['decision'] = 'ENTER'  # IA mejoró la decisión
                elif ai_decision == 'WAIT':
                    pass  # mantener decisión local si IA no está segura
                else:
                    analysis['decision'] = ai_decision
                
                self.context['ai_calls_made'] += 1
        else:
            self.context['ai_calls_saved'] += 1
        
        # ─────────────────────────────────────────────────────────────────────────
        # PASO 5: Decisión Final
        # ─────────────────────────────────────────────────────────────────────────
        
        if analysis['direction'] == 'NEUTRAL':
            if analysis['decision'] in ('ENTER', 'STRONG_ENTER'):
                # Usar dirección del motor si las reglas locales no definieron una
                analysis['direction'] = market_context.get('direction', 'CALL')
            else:
                analysis['decision'] = 'WAIT'
        
        self.decisions.append(analysis)
        self.context['decisions_made'] += 1
        
        return analysis

    def _call_ai_for_analysis(self, market_context: Dict, current_analysis: Dict) -> Optional[Dict]:
        """
        Llama al motor de IA (OpenCode EasyPanel) para análisis profundo.
        Prioriza el razonamiento multi-incoherencia con el modelo profundo.
        """
        incoherences = current_analysis.get('incoherences_detected', [])
        use_deep     = len(incoherences) > 1  # Usar modelo de razonamiento si hay conflictos

        try:
            print(f"[*] OpenCode AI: analizando {market_context.get('asset','?')} (deep={use_deep})...")
        except Exception:
            pass

        # Enriquecer el contexto con el win_rate del bot
        enriched = dict(current_analysis)
        enriched['win_rate_bot'] = self.context.get('win_rate', 0.52)

        ai_result = self.opencode.analyze_trade(
            market_context   = market_context,
            current_analysis = enriched,
            deep             = use_deep,
        )

        if not ai_result and self.authenticated:
            try:
                print("[*] OpenCode sin tokens/respuesta. Intentando fallback a GitHub Models...")
                model_to_use = None
                
                # Cargar el catálogo si no está cargado
                if not self.github_models.models_loaded:
                    self.github_models.load_available_models()
                    
                if use_deep:
                    for mid in self.github_models.available_models.keys():
                        if 'gpt-4o' in mid.lower() and 'mini' not in mid.lower():
                            model_to_use = mid
                            break
                if not model_to_use:
                    for mid in self.github_models.available_models.keys():
                        if 'gpt-4o-mini' in mid.lower():
                            model_to_use = mid
                            break
                if not model_to_use:
                    for mid in self.github_models.available_models.keys():
                        if 'gpt-4' in mid.lower() and 'mini' in mid.lower():
                            model_to_use = mid
                            break
                if not model_to_use:
                    for mid in self.github_models.available_models.keys():
                        if 'gpt-4' in mid.lower():
                            model_to_use = mid
                            break
                if not model_to_use and self.github_models.available_models:
                    model_to_use = list(self.github_models.available_models.keys())[0]
                if not model_to_use:
                    model_to_use = self.models_config.get('fast', 'openai/gpt-4o-mini')

                print(f"[*] Fallback: usando GitHub Model: {model_to_use}")
                from opencode_ai_client import SYSTEM_PROMPT_TRADER
                
                asset       = market_context.get("asset",    "UNKNOWN")
                price       = market_context.get("price",    0)
                rsi         = market_context.get("rsi",      50)
                trend       = market_context.get("trend",    "NEUTRAL")
                pattern     = market_context.get("pattern",  "none")
                zone_type   = market_context.get("zone_type","unknown")
                zone_level  = market_context.get("zone",     0)
                zone_str    = market_context.get("zone_strength", 0.0)
                session     = market_context.get("session",  "DESCONOCIDA")
                win_rate    = enriched.get("win_rate_bot", 0.52)
                local_dir   = enriched.get("direction", "NEUTRAL")
                local_conf  = enriched.get("confidence", 0)
                local_reason= enriched.get("reasoning", [])

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

                github_resp = self.github_models.call_model(
                    model_id = model_to_use,
                    messages = [
                        {"role": "system", "content": SYSTEM_PROMPT_TRADER},
                        {"role": "user", "content": prompt}
                    ],
                    temperature = 0.3,
                    max_tokens = 400
                )
                if github_resp and github_resp.get('content'):
                    ai_result = self.opencode._parse_json(github_resp['content'])
            except Exception as e:
                print(f"[!] Error al usar GitHub Models como fallback: {e}")

        if ai_result:
            self.ai_analyses.append(ai_result)
            self.context['ai_calls_made'] += 1
            # Normalizar campos por si el modelo usa nombres distintos
            ai_result.setdefault('decision',   'WAIT')
            ai_result.setdefault('direction',  current_analysis.get('direction', 'NEUTRAL'))
            ai_result.setdefault('confidence', current_analysis.get('confidence', 0))
            try:
                print(f"[AI] Veredicto (GitHub Fallback): {ai_result['decision']} {ai_result['direction']} "
                      f"({ai_result['confidence']:.0f}%) — {ai_result.get('reasoning','')[:80]}")
            except Exception:
                pass
        else:
            try:
                print("[!] OpenCode AI y GitHub Models sin respuesta — usando análisis local")
            except Exception:
                pass

        return ai_result

    # ═══════════════════════════════════════════════════════════════════════════════
    # CORRECCIÓN AUTOMÁTICA DE INCOHERENCIAS
    # ═══════════════════════════════════════════════════════════════════════════════

    def auto_correct_incoherence(self, incoherence: Dict) -> Dict:
        """
        Corrige automáticamente una incoherencia detectada
        """
        
        correction = {
            'timestamp': time.time(),
            'incoherence_type': incoherence['type'],
            'detected': incoherence['detected'],
            'correction': incoherence['correction'],
            'applied': True,
            'reason': 'Regla aprendida'
        }
        
        self.corrections_applied.append(correction)
        self.context['incoherences_fixed'] += 1
        
        return correction

    # ═══════════════════════════════════════════════════════════════════════════════
    # APRENDIZAJE CONTINUO
    # ═══════════════════════════════════════════════════════════════════════════════

    def learn_from_trade_result(self, trade: Dict) -> None:
        """
        Aprende de cada resultado de trade.
        1) Ajuste local inmediato de pesos.
        2) Consulta a OpenCode AI para lecciones profundas (en background, no bloquea).
        """
        import threading

        result  = trade.get('result', '')
        pnl     = trade.get('pnl', 0)
        pattern = trade.get('pattern', 'none')

        # ── Ajuste local inmediato ────────────────────────────────────────────
        delta = +0.02 if result in ('WIN', 'HOLD') else -0.02
        if pattern in self.learned_rules['pattern_logic']:
            self.learned_rules['pattern_logic'][pattern]['confidence'] += delta

        # Limitar confianza entre 0 y 1
        for pr in self.learned_rules['pattern_logic'].values():
            pr['confidence'] = max(0.0, min(1.0, pr['confidence']))

        # ── Aprendizaje profundo con IA (hilo separado, no bloquea el bot) ───
        def _ai_lesson():
            try:
                lesson = self.opencode.learn_from_result(
                    trade_data   = trade,
                    trade_result = result,
                    pnl          = pnl,
                )
                
                if not lesson and self.authenticated:
                    try:
                        print("[*] OpenCode sin tokens/respuesta en aprendizaje. Intentando fallback a GitHub Models...")
                        model_to_use = None
                        
                        if not self.github_models.models_loaded:
                            self.github_models.load_available_models()
                            
                        for mid in self.github_models.available_models.keys():
                            if 'gpt-4o-mini' in mid.lower():
                                model_to_use = mid
                                break
                        if not model_to_use and self.github_models.available_models:
                            model_to_use = list(self.github_models.available_models.keys())[0]
                        if not model_to_use:
                            model_to_use = self.models_config.get('fast', 'openai/gpt-4o-mini')

                        from opencode_ai_client import SYSTEM_PROMPT_TRADER
                        
                        asset       = trade.get("asset",    "UNKNOWN")
                        direction   = trade.get("direction","NEUTRAL")
                        trade_pat   = trade.get("pattern",  "none")
                        trade_zstr  = trade.get("zone_strength", 0.0)
                        rsi_entry   = trade.get("rsi_at_touch", 50)
                        trend_align = trade.get("trend_aligned", False)

                        prompt = f"""Analiza el resultado de este trade cerrado y extrae una lección de mejora:

TRADE EJECUTADO:
- Activo: {asset}
- Dirección: {direction}
- Patrón: {trade_pat}
- Fuerza de zona: {trade_zstr:.2f}
- RSI en entrada: {rsi_entry:.1f}
- Tendencia alineada: {"SI" if trend_align else "NO"}
- Resultado: {result}
- PnL: {"+$" if pnl >= 0 else "-$"}{abs(pnl):.2f}

INSTRUCCIÓN: Identifica por qué {("ganó" if result=="WIN" else "perdió")} este trade.
Proporciona una regla de mejora concreta y ajuste de confianza para futuros trades similares.

RESPONDE SOLO CON ESTE JSON:
{{
    "lesson": "lección principal en español (máximo 150 caracteres)",
    "pattern_confidence_delta": número entre -0.15 y +0.15,
    "zone_rule": "descripción de qué hacer en zonas similares (máximo 100 caracteres)",
    "avoid_condition": "condición a evitar en el futuro (máximo 100 caracteres) o null",
    "reinforce_condition": "condición a reforzar (máximo 100 caracteres) o null"
}}"""

                        github_resp = self.github_models.call_model(
                            model_id = model_to_use,
                            messages = [
                                {"role": "system", "content": SYSTEM_PROMPT_TRADER},
                                {"role": "user", "content": prompt}
                            ],
                            temperature = 0.3,
                            max_tokens = 400
                        )
                        if github_resp and github_resp.get('content'):
                            lesson = self.opencode._parse_json(github_resp['content'])
                    except Exception as e:
                        print(f"[!] Error al usar GitHub Models como fallback en aprendizaje: {e}")

                if lesson:
                    # Aplicar ajuste de confianza sugerido por la IA
                    delta_ai = lesson.get('pattern_confidence_delta', 0)
                    if pattern in self.learned_rules['pattern_logic'] and delta_ai != 0:
                        self.learned_rules['pattern_logic'][pattern]['confidence'] += delta_ai
                        for pr in self.learned_rules['pattern_logic'].values():
                            pr['confidence'] = max(0.0, min(1.0, pr['confidence']))

                    # Guardar lección en log
                    lesson_entry = {
                        'timestamp':  time.time(),
                        'asset':      trade.get('asset'),
                        'result':     result,
                        'pnl':        pnl,
                        'lesson':     lesson.get('lesson', ''),
                        'zone_rule':  lesson.get('zone_rule', ''),
                        'avoid':      lesson.get('avoid_condition', ''),
                        'reinforce':  lesson.get('reinforce_condition', ''),
                    }
                    self.context.setdefault('ai_lessons', []).append(lesson_entry)
                    # Mantener solo las últimas 30 lecciones en memoria
                    if len(self.context['ai_lessons']) > 30:
                        self.context['ai_lessons'] = self.context['ai_lessons'][-30:]
                    try:
                        print(f"[LEARN] IA (Fallback): {lesson.get('lesson','')[:90]}")
                    except Exception:
                        pass
            except Exception as ex:
                try:
                    print(f"[!] Error en aprendizaje IA: {ex}")
                except Exception:
                    pass

        t = threading.Thread(target=_ai_lesson, daemon=True)
        t.start()

    def evaluate_session(self) -> None:
        """
        Ejecuta evaluación de sesión con IA (razonamiento profundo).
        Llama en un hilo separado para no bloquear el bot.
        Ajusta selectividad y pausa activos según recomendación.
        """
        import threading

        session_trades = self.persistence.get_recent_trades(15)
        if len(session_trades) < 3:
            return  # No hay suficientes trades para evaluar

        def _run_eval():
            try:
                eval_result = self.opencode.evaluate_session_performance(session_trades)
                
                if not eval_result and self.authenticated:
                    try:
                        print("[*] OpenCode sin tokens/respuesta en evaluacion de sesion. Intentando fallback a GitHub Models...")
                        model_to_use = None
                        
                        if not self.github_models.models_loaded:
                            self.github_models.load_available_models()
                            
                        for mid in self.github_models.available_models.keys():
                            if 'gpt-4o' in mid.lower() and 'mini' not in mid.lower():
                                model_to_use = mid
                                break
                        if not model_to_use and self.github_models.available_models:
                            model_to_use = list(self.github_models.available_models.keys())[0]
                        if not model_to_use:
                            model_to_use = self.models_config.get('quality', 'openai/gpt-4o')

                        from opencode_ai_client import SYSTEM_PROMPT_TRADER
                        wins   = sum(1 for t in session_trades if t.get("result") == "WIN")
                        losses = sum(1 for t in session_trades if t.get("result") == "LOSS")
                        total  = len(session_trades)
                        pnl    = sum(t.get("pnl", 0) for t in session_trades)

                        trade_summary = []
                        for t in session_trades[-8:]:
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

                        github_resp = self.github_models.call_model(
                            model_id = model_to_use,
                            messages = [
                                {"role": "system", "content": SYSTEM_PROMPT_TRADER},
                                {"role": "user", "content": prompt}
                            ],
                            temperature = 0.3,
                            max_tokens = 400
                        )
                        if github_resp and github_resp.get('content'):
                            eval_result = self.opencode._parse_json(github_resp['content'])
                    except Exception as e:
                        print(f"[!] Error al usar GitHub Models como fallback en evaluacion: {e}")

                if not eval_result:
                    return

                grade       = eval_result.get('session_grade', 'B')
                rec         = eval_result.get('recommendation', '')
                to_pause    = eval_result.get('assets_to_pause', [])
                conf_mult   = eval_result.get('confidence_multiplier', 1.0)
                more_select = eval_result.get('increase_selectivity', False)

                try:
                    print(f"[AI] Eval. sesion (Fallback): Grado={grade} | {rec[:80]}")
                    if to_pause:
                        print(f"[AI] Activos a pausar: {to_pause}")
                except Exception:
                    pass

                # Pausar activos recomendados
                for a in (to_pause or []):
                    if a in self.learned_rules['asset_logic']:
                        self.learned_rules['asset_logic'][a]['status'] = 'PAUSED'
                        self.learned_rules['asset_logic'][a]['reason'] = f'IA-eval-{grade}'

                # Aumentar umbral mínimo de confianza si IA lo recomienda
                if more_select and conf_mult < 1.0:
                    self.learned_rules['validation_rules']['min_confidence'] = min(
                        0.70,
                        self.learned_rules['validation_rules'].get('min_confidence', 0.50) + 0.05
                    )

                # Guardar resultado en contexto
                self.context['last_session_eval'] = eval_result

            except Exception as ex:
                try:
                    print(f"[!] Error en evaluacion de sesion: {ex}")
                except Exception:
                    pass

        threading.Thread(target=_run_eval, daemon=True).start()

    # ═══════════════════════════════════════════════════════════════════════════════
    # REPORTES Y MONITOREO
    # ═══════════════════════════════════════════════════════════════════════════════

    def get_status(self) -> Dict:
        """Estado actual del agente"""
        return {
            'name': self.name,
            'version': self.version,
            'authenticated': self.authenticated,
            'context': self.context,
            'decisions_made': len(self.decisions),
            'incoherences_fixed': self.context['incoherences_fixed'],
            'ai_calls_made': self.context['ai_calls_made'],
            'ai_calls_saved': self.context['ai_calls_saved'],
            'efficiency': f"{(self.context['ai_calls_saved'] / (self.context['ai_calls_made'] + self.context['ai_calls_saved'] + 1)) * 100:.1f}%"
        }

    def generate_report(self) -> str:
        """Genera reporte del agente"""
        
        status = self.get_status()
        
        report = f"""
================================================================================
                    REPORTE DEL AGENTE INTELIGENTE
================================================================================

[ESTADO DEL AGENTE]
  - Nombre: {status['name']}
  - Version: {status['version']}
  - Autenticado: {'Si' if status['authenticated'] else 'No'}
  - Estado: ACTIVO

[CONTEXTO DEL SISTEMA]
  - Trades analizados: {status['context']['trades_analyzed']}
  - Win Rate: {status['context']['win_rate']:.1%}
  - PnL Total: {status['context']['pnl_total']:+.2f}
  - Incoherencias detectadas: {status['context'].get('incoherences_detected', 0)}

[DECISIONES]
  - Total: {status['decisions_made']}
  - Incoherencias corregidas: {status['incoherences_fixed']}

[USO DE IA]
  - Llamadas realizadas: {status['ai_calls_made']}
  - Llamadas ahorradas: {status['ai_calls_saved']}
  - Eficiencia: {status['efficiency']}

[MEJORES ACTIVOS]
"""
        
        for asset_info in status['context'].get('best_assets', [])[:3]:
            report += f"  - {asset_info['asset']}: WR {asset_info['wr']:.1%}\n"
        
        report += f"""
[PEORES ACTIVOS]
"""
        
        for asset_info in status['context'].get('worst_assets', [])[:3]:
            report += f"  - {asset_info['asset']}: WR {asset_info['wr']:.1%}\n"
        
        report += f"""
{'='*80}
"""
        
        return report

    def get_summary(self) -> Dict:
        """Resumen ejecutivo"""
        return {
            'name': self.name,
            'version': self.version,
            'authenticated': self.authenticated,
            'trades_analyzed': self.context['trades_analyzed'],
            'win_rate': self.context['win_rate'],
            'pnl_total': self.context['pnl_total'],
            'incoherences_fixed': self.context['incoherences_fixed'],
            'ai_efficiency': f"{(self.context['ai_calls_saved'] / (self.context['ai_calls_made'] + self.context['ai_calls_saved'] + 1)) * 100:.1f}%",
            'status': 'ACTIVE'
        }


# Singleton
_agent: Optional[IntelligentTradingAgent] = None


def get_intelligent_trading_agent(github_token: str) -> IntelligentTradingAgent:
    global _agent
    if _agent is None:
        _agent = IntelligentTradingAgent(github_token)
    return _agent


if __name__ == "__main__":
    # Token de GitHub
    token = os.environ.get("GITHUB_TOKEN", "")
    
    agent = get_intelligent_trading_agent(token)
    
    # Mostrar estado
    print(agent.generate_report())
    
    # Ejemplo de análisis
    market_context = {
        'asset': 'EURJPY-OTC',
        'price': 150.5,
        'rsi': 25,
        'trend': 'DOWN',
        'pattern': 'pin_bar_bullish',
        'zone_type': 'support',
        'zone': 150.0
    }
    
    print("\n[*] Analizando oportunidad de trade...")
    analysis = agent.analyze_trade_opportunity(market_context)
    
    print(f"\nDecisión: {analysis['decision']}")
    print(f"Dirección: {analysis['direction']}")
    print(f"Confianza: {analysis['confidence']:.0f}%")
    print(f"IA usada: {analysis['ai_used']}")
    print(f"Incoherencias corregidas: {len(analysis['corrections_applied'])}")
