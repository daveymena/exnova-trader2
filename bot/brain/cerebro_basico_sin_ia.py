"""
🧠 CEREBRO BÁSICO SIN IA - Fallback Final
═══════════════════════════════════════════════════════════════════════════════

Si TODAS las IAs se agotan/fallan:
  - Ollama caído
  - OpenRouter sin crédito
  - OpenCode no responde
  - DeepSeek sin créditos
  - Zen no disponible

→ El Cerebro funciona con lógica PURA matemática/estadística

5 fases sin IA, 100% determinista, 100% confiable
═══════════════════════════════════════════════════════════════════════════════
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime
import statistics

log = logging.getLogger("CerebroBasico")


class CerebroBasicoSinIA:
    """Cerebro autónomo sin dependencias de IA externa"""

    def __init__(self):
        self.name = "Cerebro Basico (Sin IA)"
        self.trade_history: List[Dict] = []
        self.parameters = {
            'confidence_threshold': 0.55,
            'tp_percent': 2.0,
            'sl_percent': 1.0,
            'max_consecutive_losses': 5
        }
        log.info("[CerebroBasico] Inicializado - Modo fallback 100% sin IA")

    # ═════════════════════════════════════════════════════════════════════════
    # FASE 1: RAZONADOR (Generar 3 opciones sin IA)
    # ═════════════════════════════════════════════════════════════════════════

    def fase_1_razonador(self, market_context: Dict) -> Dict:
        """
        Genera 3 opciones usando SOLO matemática

        Inputs:
          - trend: UP/DOWN/RANGE
          - momentum: -1.0 a +1.0
          - volatility: 0.0 a 1.0
          - volume: número
          - rsi: 0-100
        """
        trend = market_context.get('trend', 'RANGE')
        momentum = market_context.get('momentum', 0.0)
        volatility = market_context.get('volatility', 0.5)
        rsi = market_context.get('rsi', 50)
        volume = market_context.get('volume', 100)

        opciones = []

        # ─────────────────────────────────────────────────────────────────
        # OPCIÓN 1: TREND FOLLOWING (Sigue la tendencia)
        # ─────────────────────────────────────────────────────────────────
        if trend == 'UP' or momentum > 0.3:
            direction1 = 'CALL'
        elif trend == 'DOWN' or momentum < -0.3:
            direction1 = 'PUT'
        else:
            direction1 = 'SKIP'

        # Confianza basada en momentum
        confidence1 = min(0.9, 0.5 + abs(momentum) * 0.3)

        opciones.append({
            'num': 1,
            'direction': direction1,
            'confidence': confidence1,
            'strategy': 'TREND_FOLLOWING',
            'reasoning': f"Trend {trend}, momentum {momentum:.2f}",
            'score': confidence1 * (1 + volatility * 5)
        })

        # ─────────────────────────────────────────────────────────────────
        # OPCIÓN 2: MEAN REVERSION (Apuesta contra extremos)
        # ─────────────────────────────────────────────────────────────────
        if rsi > 70:  # Sobrecompra
            direction2 = 'PUT'
            confidence2 = 0.6 + (rsi - 70) / 30 * 0.2  # Más confianza si más extremo
        elif rsi < 30:  # Sobreventa
            direction2 = 'CALL'
            confidence2 = 0.6 + (30 - rsi) / 30 * 0.2
        else:
            direction2 = 'SKIP'
            confidence2 = 0.3

        opciones.append({
            'num': 2,
            'direction': direction2,
            'confidence': confidence2,
            'strategy': 'MEAN_REVERSION',
            'reasoning': f"RSI {rsi}, contra-tendencia",
            'score': confidence2 * 0.8
        })

        # ─────────────────────────────────────────────────────────────────
        # OPCIÓN 3: VOLUMEN CONFIRMADO (Valida con volumen)
        # ─────────────────────────────────────────────────────────────────
        direction3 = direction1  # Mismo que trend following

        if volume > 150:
            confidence3 = 0.7  # Alto volumen confirma
        elif volume < 50:
            confidence3 = 0.4  # Bajo volumen = débil
        else:
            confidence3 = 0.55  # Normal

        opciones.append({
            'num': 3,
            'direction': direction3,
            'confidence': confidence3,
            'strategy': 'VOLUME_CONFIRMED',
            'reasoning': f"Volume {volume}, {'confirma' if volume > 150 else 'débil'}",
            'score': confidence3 * (1.0 + volume / 200)
        })

        # Ordenar por score
        opciones.sort(key=lambda x: x['score'], reverse=True)

        log.info(f"[Fase 1] 3 opciones generadas. Mejor: {opciones[0]['direction']} ({opciones[0]['confidence']:.2f})")

        return {
            'status': 'success',
            'provider': 'cerebro_basico',
            'options': opciones,
            'best': opciones[0]
        }

    # ═════════════════════════════════════════════════════════════════════════
    # FASE 2: MEMORIA (Buscar contextos similares)
    # ═════════════════════════════════════════════════════════════════════════

    def fase_2_memoria(self) -> Dict:
        """Analiza historial sin IA"""
        if not self.trade_history:
            return {
                'status': 'no_data',
                'win_rate': 0.5,
                'context': 'Sin historial'
            }

        recent = self.trade_history[-20:]
        wins = sum(1 for t in recent if t.get('outcome') == 'WIN')
        wr = wins / len(recent) if recent else 0.5

        # Detectar racha
        consecutive_losses = 0
        for t in reversed(recent):
            if t.get('outcome') == 'LOSS':
                consecutive_losses += 1
            else:
                break

        log.info(f"[Fase 2] WR: {wr:.1%}, Racha: {consecutive_losses} pérdidas")

        return {
            'status': 'success',
            'provider': 'memory',
            'win_rate': wr,
            'recent_trades': len(recent),
            'consecutive_losses': consecutive_losses
        }

    # ═════════════════════════════════════════════════════════════════════════
    # FASE 3: AUTONOMÍA (Auto-mejora sin IA)
    # ═════════════════════════════════════════════════════════════════════════

    def fase_3_autonomia(self, memory: Dict) -> Dict:
        """Auto-ajusta parámetros basado en performance"""
        wr = memory.get('win_rate', 0.5)
        consecutive_losses = memory.get('consecutive_losses', 0)

        # Ajuste automático del threshold
        if wr < 0.48:  # Crítico
            self.parameters['confidence_threshold'] = 0.65
            action = "CRITICO: Aumentar threshold a 0.65"
        elif wr < 0.52:  # Bajo
            self.parameters['confidence_threshold'] = 0.60
            action = "BAJO: Aumentar threshold a 0.60"
        elif wr > 0.56:  # Bueno
            self.parameters['confidence_threshold'] = 0.50
            action = "BUENO: Bajar threshold a 0.50 (más agresivo)"
        else:  # Normal
            self.parameters['confidence_threshold'] = 0.55
            action = "NORMAL: Mantener threshold 0.55"

        # Control de racha perdedora
        if consecutive_losses >= 3:
            self.parameters['sl_percent'] = 0.7  # Stop loss más apretado
            action += " | SL apretado por racha"
        elif consecutive_losses <= 1:
            self.parameters['sl_percent'] = 1.0  # Normal

        log.info(f"[Fase 3] {action}")

        return {
            'status': 'success',
            'provider': 'autonomy',
            'action': action,
            'new_threshold': self.parameters['confidence_threshold'],
            'new_sl': self.parameters['sl_percent']
        }

    # ═════════════════════════════════════════════════════════════════════════
    # FASE 4: PLANIFICADOR (Crear plan de ejecución)
    # ═════════════════════════════════════════════════════════════════════════

    def fase_4_planificador(self, decision: Dict, price: float) -> Dict:
        """Crea plan de entrada/TP/SL"""
        direction = decision.get('direction')
        tp_pct = self.parameters['tp_percent']
        sl_pct = self.parameters['sl_percent']

        tp = price * (1 + tp_pct / 100) if direction == 'CALL' else price * (1 - tp_pct / 100)
        sl = price * (1 - sl_pct / 100) if direction == 'CALL' else price * (1 + sl_pct / 100)

        log.info(f"[Fase 4] PLAN: {direction} @ {price:.4f} → TP {tp:.4f} / SL {sl:.4f}")

        return {
            'status': 'success',
            'direction': direction,
            'entry': price,
            'tp': tp,
            'sl': sl,
            'duration': 60,
            'expiration_time': 'T+60s'
        }

    # ═════════════════════════════════════════════════════════════════════════
    # FASE 5: ESPECULADOR (Predecir siguiente movimiento)
    # ═════════════════════════════════════════════════════════════════════════

    def fase_5_especulador(self, market_context: Dict, memory: Dict) -> Dict:
        """Predice próximo movimiento sin IA"""
        momentum = market_context.get('momentum', 0)
        wr = memory.get('win_rate', 0.5)

        # Predicción basada en momentum
        if momentum > 0.3:
            prediction = 'UP'
            prob = 0.5 + abs(momentum) * 0.3
        elif momentum < -0.3:
            prediction = 'DOWN'
            prob = 0.5 + abs(momentum) * 0.3
        else:
            prediction = 'RANGE'
            prob = 0.5

        # Ajustar probabilidad por WR histórico
        if wr > 0.55:
            prob = min(0.95, prob + 0.05)  # Confianza extra si gana
        elif wr < 0.45:
            prob = max(0.45, prob - 0.05)  # Menos confianza si pierde

        log.info(f"[Fase 5] Predicción: {prediction} ({prob:.0%})")

        return {
            'status': 'success',
            'prediction': prediction,
            'probability': prob,
            'reasoning': f"Momentum {momentum:.2f}, WR histórico {wr:.1%}"
        }

    # ═════════════════════════════════════════════════════════════════════════
    # CICLO COMPLETO
    # ═════════════════════════════════════════════════════════════════════════

    def ciclo_completo(self, market_context: Dict, current_price: float) -> Dict:
        """Ejecuta el ciclo completo del Cerebro sin IA"""

        log.info("="*80)
        log.info("[CerebroBasico] CICLO COMPLETO - SIN IA")
        log.info("="*80)

        # Fase 1: Razonador
        razonador = self.fase_1_razonador(market_context)
        if razonador['best']['direction'] == 'SKIP':
            log.info("[Decision] SKIP - Esperando mejor setup")
            return {'decision': 'SKIP', 'reason': 'Confidence too low'}

        # Fase 2: Memoria
        memoria = self.fase_2_memoria()

        # Fase 3: Autonomía
        autonomia = self.fase_3_autonomia(memoria)

        # Decidir si entra
        best_option = razonador['best']
        threshold = self.parameters['confidence_threshold']

        if best_option['confidence'] < threshold:
            log.info(f"[Decision] SKIP - Confidence {best_option['confidence']:.2f} < threshold {threshold}")
            return {'decision': 'SKIP', 'reason': 'Below threshold'}

        # Fase 4: Planificador
        plan = self.fase_4_planificador(best_option, current_price)

        # Fase 5: Especulador
        especulador = self.fase_5_especulador(market_context, memoria)

        # DECISIÓN FINAL
        log.info(f"[Decision] ENTRAR {best_option['direction']} (conf: {best_option['confidence']:.2f})")

        return {
            'status': 'success',
            'decision': 'ENTER',
            'phase_1': razonador,
            'phase_2': memoria,
            'phase_3': autonomia,
            'phase_4': plan,
            'phase_5': especulador,
            'timestamp': datetime.now().isoformat()
        }

    def registrar_resultado(self, direction: str, outcome: str, pnl: float):
        """Registra resultado de la operación"""
        self.trade_history.append({
            'direction': direction,
            'outcome': outcome,
            'pnl': pnl,
            'timestamp': datetime.now().isoformat()
        })

        log.info(f"[Resultado] {outcome} {pnl:+.2f} | Trades: {len(self.trade_history)}")


# ═════════════════════════════════════════════════════════════════════════════
# PRUEBA
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )

    cerebro = CerebroBasicoSinIA()

    # Simular mercado
    market = {
        'trend': 'UP',
        'momentum': 0.72,
        'volatility': 0.025,
        'volume': 180,
        'rsi': 65
    }

    print("\n" + "="*80)
    print("🧠 CEREBRO BÁSICO SIN IA - DEMO")
    print("="*80 + "\n")

    resultado = cerebro.ciclo_completo(market, 1.2350)

    if resultado['decision'] == 'ENTER':
        print(f"\n✅ Decisión: ENTRAR {resultado['phase_4']['direction']}")
        print(f"   Entry: {resultado['phase_4']['entry']:.4f}")
        print(f"   TP: {resultado['phase_4']['tp']:.4f}")
        print(f"   SL: {resultado['phase_4']['sl']:.4f}")

        # Simular resultado
        cerebro.registrar_resultado(
            resultado['phase_4']['direction'],
            'WIN',
            2.50
        )

    print("\n" + "="*80)
    print("✅ CEREBRO BÁSICO FUNCIONA SIN NECESIDAD DE IA")
    print("="*80)
