"""
🧠 CEREBRO AUTÓNOMO PARA EXNOVA TRADER v2
═══════════════════════════════════════════════════════════════════════════════

5 FASES INTEGRADAS:
  1. RAZONADOR      — Piensa 3 opciones + scores
  2. MEMORIA        — Busca contexto histórico
  3. AUTONOMÍA      — Auto-mejora sin intervención
  4. PLANIFICADOR   — Árbol de decisiones + rollback
  5. ESPECULADOR    — Anticipa Next Move + hedging

Estado actual del bot:
  - Win Rate: 49.8% (peor que azar)
  - PNL: -$192.53
  - IA CALLS: 0 (nunca actúa)

Objetivo: 55%+ win rate, acción autónoma, auto-mejora continua
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import time
import sqlite3
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("AutonomousCerebro")


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 1: RAZONADOR — Piensa 3 opciones
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TradeOption:
    """Una opción de trade con análisis"""
    direction: str  # "CALL" o "PUT"
    confidence: float  # 0-1
    reasoning: str  # Por qué esta opción
    risk_score: float  # Riesgo relativo
    reward_score: float  # Potencial de ganancia
    time_frame: str  # Plazo (30s, 1m, 5m, etc)

    def score(self) -> float:
        """Score combinado: confianza + risk/reward ratio"""
        if self.risk_score == 0:
            return self.confidence * self.reward_score
        rr_ratio = self.reward_score / self.risk_score
        return self.confidence * (1 + rr_ratio)


class Reasoner:
    """Genera 3 opciones de trade razonadas"""

    def __init__(self):
        self.name = "Reasoner (Fase 1)"
        log.info(f"[{self.name}] Inicializado")

    def think_options(self, market_context: Dict) -> List[TradeOption]:
        """
        Analiza mercado y genera 3 opciones

        market_context debe contener:
          - price: float
          - volume: float
          - trend: str ("UP", "DOWN", "RANGE")
          - volatility: float
          - momentum: float (-1 a 1)
          - structure: dict (soportes, resistencias)
          - indicators: dict
        """
        options = []

        try:
            price = market_context.get('price', 0)
            trend = market_context.get('trend', 'RANGE')
            momentum = market_context.get('momentum', 0)
            volatility = market_context.get('volatility', 0.5)
            volume = market_context.get('volume', 0)

            # Opción 1: Trend-following (confianza en tendencia existente)
            if trend == "UP":
                opt1 = TradeOption(
                    direction="CALL",
                    confidence=min(0.9, 0.5 + abs(momentum) * 0.4),
                    reasoning=f"Trend UP, momentum={momentum:.2f}. Seguir tendencia alcista.",
                    risk_score=volatility,
                    reward_score=1.5 + abs(momentum),
                    time_frame="1m"
                )
            else:  # DOWN o RANGE
                opt1 = TradeOption(
                    direction="PUT",
                    confidence=min(0.9, 0.5 + abs(momentum) * 0.4),
                    reasoning=f"Trend DOWN, momentum={momentum:.2f}. Seguir tendencia bajista.",
                    risk_score=volatility,
                    reward_score=1.5 + abs(momentum),
                    time_frame="1m"
                )
            options.append(opt1)

            # Opción 2: Mean-reversion (contra-tendencia)
            opposite = "PUT" if trend == "UP" else "CALL"
            opt2 = TradeOption(
                direction=opposite,
                confidence=max(0.3, 0.7 - abs(momentum) * 0.5),
                reasoning=f"Mean-reversion contra {trend}. Esperando rebote.",
                risk_score=volatility * 1.5,
                reward_score=1.0 + volatility,
                time_frame="30s"
            )
            options.append(opt2)

            # Opción 3: Volume-based (decisión por volumen)
            if volume > 100:  # Alto volumen
                opt3 = TradeOption(
                    direction=opt1.direction,
                    confidence=0.6 + (volume / 500) * 0.2,
                    reasoning=f"Alto volumen ({volume}). Confirma dirección principal.",
                    risk_score=volatility * 0.8,
                    reward_score=2.0,
                    time_frame="2m"
                )
            else:
                opt3 = TradeOption(
                    direction="CALL" if momentum > 0 else "PUT",
                    confidence=0.4,
                    reasoning=f"Bajo volumen ({volume}). Esperar confirmación.",
                    risk_score=volatility * 2.0,
                    reward_score=0.8,
                    time_frame="5m"
                )
            options.append(opt3)

            # Ordenar por score
            options.sort(key=lambda x: x.score(), reverse=True)

            log.info(f"[{self.name}] 3 opciones generadas:")
            for i, opt in enumerate(options, 1):
                log.info(f"  Opción {i}: {opt.direction} (score={opt.score():.3f}, conf={opt.confidence:.2f})")

            return options

        except Exception as e:
            log.error(f"[{self.name}] Error en think_options: {e}")
            return []


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 2: MEMORIA — Busca contexto histórico
# ═══════════════════════════════════════════════════════════════════════════════

class Memory:
    """Almacena y recupera contexto histórico"""

    def __init__(self, db_path: str = "trading_bot.db"):
        self.name = "Memory (Fase 2)"
        self.db_path = db_path
        self._init_db()
        log.info(f"[{self.name}] Inicializada")

    def _init_db(self):
        """Crea tabla de memoria si no existe"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                CREATE TABLE IF NOT EXISTS memory_contexts (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT,
                    market_conditions TEXT,
                    decision_made TEXT,
                    outcome TEXT,
                    pnl REAL,
                    confidence REAL
                )
            ''')
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning(f"[{self.name}] No se pudo inicializar DB: {e}")

    def store_context(self, market_context: Dict, decision: str, outcome: str, pnl: float, confidence: float):
        """Almacena un contexto para futuras referencias"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                INSERT INTO memory_contexts
                (timestamp, market_conditions, decision_made, outcome, pnl, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                json.dumps(market_context),
                decision,
                outcome,
                pnl,
                confidence
            ))
            conn.commit()
            conn.close()
            log.debug(f"[{self.name}] Contexto almacenado: {decision} → {outcome} (PNL={pnl})")
        except Exception as e:
            log.error(f"[{self.name}] Error al almacenar contexto: {e}")

    def find_similar_contexts(self, current_context: Dict, limit: int = 5) -> List[Dict]:
        """Busca contextos similares en el pasado"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            # Búsqueda simple: últimos N trades con outcome similar
            c.execute('''
                SELECT * FROM memory_contexts
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))

            rows = c.fetchall()
            conn.close()

            results = []
            for row in rows:
                results.append({
                    'timestamp': row[1],
                    'market_conditions': json.loads(row[2]),
                    'decision': row[3],
                    'outcome': row[4],
                    'pnl': row[5],
                    'confidence': row[6]
                })

            log.debug(f"[{self.name}] Encontrados {len(results)} contextos similares")
            return results

        except Exception as e:
            log.error(f"[{self.name}] Error al buscar contextos: {e}")
            return []

    def get_winrate_for_pattern(self, pattern_key: str) -> Tuple[int, int]:
        """Retorna (wins, total) para un patrón específico"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()

            c.execute('''
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins
                FROM memory_contexts
                WHERE market_conditions LIKE ?
            ''', (f'%{pattern_key}%',))

            total, wins = c.fetchone()
            conn.close()

            wins = wins or 0
            total = total or 0

            return wins, total

        except Exception as e:
            log.error(f"[{self.name}] Error al obtener win rate: {e}")
            return 0, 0


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 3: AUTONOMÍA — Auto-mejora sin intervención
# ═══════════════════════════════════════════════════════════════════════════════

class AutonomousImprover:
    """Mejora el sistema automáticamente basado en resultados"""

    def __init__(self):
        self.name = "AutonomousImprover (Fase 3)"
        self.metrics = {
            'min_confidence_threshold': 0.55,
            'risk_reward_ratio_min': 1.5,
            'max_consecutive_losses': 5,
            'learning_rate': 0.01
        }
        log.info(f"[{self.name}] Inicializado")

    def evaluate_performance(self, trades_history: List[Dict]) -> Dict:
        """Evalúa rendimiento reciente"""
        if not trades_history:
            return {'status': 'NO_DATA'}

        recent = trades_history[-50:]  # Últimas 50 operaciones
        wins = sum(1 for t in recent if t.get('outcome') == 'WIN')
        total = len(recent)
        wr = wins / total if total > 0 else 0

        pnl = sum(t.get('pnl', 0) for t in recent)
        avg_confidence = sum(t.get('confidence', 0) for t in recent) / total if total > 0 else 0

        return {
            'win_rate': wr,
            'pnl': pnl,
            'total_trades': total,
            'avg_confidence': avg_confidence,
            'status': 'GOOD' if wr > 0.55 else 'NEEDS_IMPROVEMENT'
        }

    def propose_improvements(self, performance: Dict) -> List[str]:
        """Propone ajustes automáticos"""
        improvements = []

        wr = performance.get('win_rate', 0)

        if wr < 0.50:
            improvements.append("CRITICAL: Win rate < 50%. Aumentar confidence threshold a 0.65")
            improvements.append("CRITICAL: Revisar estrategia de entrada. Usar solo tops patterns.")
            improvements.append("CRITICAL: Reducir tamaño de posición a $0.50")
        elif wr < 0.55:
            improvements.append("WARNING: Win rate < 55%. Mejorar filtros de entrada")
            improvements.append("SUGGESTION: Aumentar min_confidence a 0.60")
        else:
            improvements.append("✓ Win rate en rango aceptable. Mantener estrategia.")

        avg_conf = performance.get('avg_confidence', 0)
        if avg_conf < 0.50:
            improvements.append("WARNING: Confianza promedio baja. Revisar indicadores")

        return improvements

    def apply_improvement(self, improvement_desc: str, current_config: Dict) -> Dict:
        """Aplica mejora al config (propuesta)"""
        new_config = current_config.copy()

        if "confidence threshold" in improvement_desc.lower():
            # Extraer el valor
            parts = improvement_desc.split()
            for i, part in enumerate(parts):
                if part.startswith('0.'):
                    try:
                        new_config['min_confidence_threshold'] = float(part)
                    except:
                        pass

        log.info(f"[{self.name}] Mejora propuesta: {improvement_desc[:50]}...")
        return new_config


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 4: PLANIFICADOR — Árbol de decisiones + rollback
# ═══════════════════════════════════════════════════════════════════════════════

class Planner:
    """Planifica la ejecución con puntos de rollback"""

    def __init__(self):
        self.name = "Planner (Fase 4)"
        self.execution_plan = None
        log.info(f"[{self.name}] Inicializado")

    def create_execution_plan(self,
                             best_option: TradeOption,
                             market_context: Dict) -> Dict:
        """
        Crea plan de ejecución con puntos de control

        Plan:
          1. Entrada: ejecutar trade
          2. TP: take profit en X% arriba
          3. SL: stop loss en X% abajo
          4. Monitor: cada 5 segundos
          5. Rollback: si cierra en contra
        """

        price = market_context.get('price', 0)
        volatility = market_context.get('volatility', 0.5)

        # Calcular TP/SL basado en volatilidad
        tp_offset = price * volatility * 0.5
        sl_offset = price * volatility * 0.3

        plan = {
            'step_1_entry': {
                'action': 'ENTER',
                'direction': best_option.direction,
                'price': price,
                'time_frame': best_option.time_frame,
                'confidence': best_option.confidence,
                'checkpoint': 'EXECUTE_IF_CONFIDENCE > 0.55',
                'status': 'PENDING'
            },
            'step_2_tp': {
                'action': 'TAKE_PROFIT',
                'target_pnl_pct': 2.0,  # 2% ganancia
                'checkpoint': 'REACHED_PRICE_TARGET',
                'status': 'MONITORING'
            },
            'step_3_sl': {
                'action': 'STOP_LOSS',
                'max_loss_pct': 1.0,  # 1% máximo
                'checkpoint': 'HIT_SL_LEVEL',
                'status': 'MONITORING'
            },
            'step_4_monitor': {
                'action': 'MONITOR',
                'interval_seconds': 5,
                'check_for': ['REVERSAL', 'BREAKOUT', 'SL_HIT'],
                'status': 'ACTIVE'
            },
            'step_5_rollback': {
                'action': 'ROLLBACK',
                'trigger': 'TRADE_AGAINST_BIAS OR TIME_EXCEEDED',
                'max_time_seconds': 60,
                'status': 'STANDBY'
            },
            'metadata': {
                'created_at': datetime.now().isoformat(),
                'market_context_snapshot': market_context,
                'reasoning': best_option.reasoning
            }
        }

        self.execution_plan = plan
        log.info(f"[{self.name}] Plan creado: {best_option.direction} a ${price}")

        return plan

    def should_execute_step(self, step_name: str, current_price: float) -> bool:
        """Decide si ejecutar un paso específico"""
        if not self.execution_plan:
            return False

        step = self.execution_plan.get(step_name)
        if not step:
            return False

        # Lógica de checkpoint
        checkpoint = step.get('checkpoint', '')

        if 'CONFIDENCE' in checkpoint:
            confidence = self.execution_plan.get('step_1_entry', {}).get('confidence', 0)
            return confidence > 0.55

        return True


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 5: ESPECULADOR — Anticipa Next Move + hedging
# ═══════════════════════════════════════════════════════════════════════════════

class Speculator:
    """Anticipa el próximo movimiento y propone hedging"""

    def __init__(self):
        self.name = "Speculator (Fase 5)"
        self.prediction_history = []
        log.info(f"[{self.name}] Inicializado")

    def predict_next_move(self, market_context: Dict, history_trades: List[Dict]) -> Dict:
        """
        Anticipa el próximo movimiento del precio

        Retorna: {'direction': 'UP'|'DOWN'|'RANGE', 'probability': 0-1, 'reasoning': str}
        """

        try:
            momentum = market_context.get('momentum', 0)
            trend = market_context.get('trend', 'RANGE')
            volume = market_context.get('volume', 0)

            # Análisis simple de momentum
            if momentum > 0.5:
                prediction = {
                    'direction': 'UP',
                    'probability': min(0.95, 0.6 + abs(momentum) * 0.3),
                    'reasoning': f'Momentum alcista fuerte: {momentum:.2f}'
                }
            elif momentum < -0.5:
                prediction = {
                    'direction': 'DOWN',
                    'probability': min(0.95, 0.6 + abs(momentum) * 0.3),
                    'reasoning': f'Momentum bajista fuerte: {momentum:.2f}'
                }
            else:
                prediction = {
                    'direction': 'RANGE',
                    'probability': 0.5,
                    'reasoning': 'Momentum neutral, mercado en rango'
                }

            # Revisar últimos resultados para ajustar
            if len(history_trades) >= 3:
                recent_outcomes = [t.get('outcome') for t in history_trades[-3:]]
                win_count = sum(1 for o in recent_outcomes if o == 'WIN')

                if win_count == 3:
                    prediction['probability'] = min(0.98, prediction['probability'] + 0.1)
                    prediction['reasoning'] += " (3 wins en fila, momentum confirmado)"

            self.prediction_history.append(prediction)
            log.info(f"[{self.name}] Predicción: {prediction['direction']} "
                    f"(prob={prediction['probability']:.2f})")

            return prediction

        except Exception as e:
            log.error(f"[{self.name}] Error en predicción: {e}")
            return {'direction': 'RANGE', 'probability': 0.5, 'reasoning': 'Error'}

    def suggest_hedging(self, current_trade: Dict, prediction: Dict) -> Optional[Dict]:
        """Sugiere hedging si predicción contradice trade actual"""

        trade_direction = current_trade.get('direction')
        predicted_direction = prediction.get('direction')
        predicted_prob = prediction.get('probability', 0)

        # Si predicción contradice con alta probabilidad, sugerir hedge
        if trade_direction == 'CALL' and predicted_direction == 'DOWN' and predicted_prob > 0.75:
            return {
                'action': 'HEDGE',
                'hedge_direction': 'PUT',
                'size_pct': 0.3,  # 30% del tamaño original
                'reasoning': f'Predicción DOWN con {predicted_prob:.0%} de probabilidad'
            }
        elif trade_direction == 'PUT' and predicted_direction == 'UP' and predicted_prob > 0.75:
            return {
                'action': 'HEDGE',
                'hedge_direction': 'CALL',
                'size_pct': 0.3,
                'reasoning': f'Predicción UP con {predicted_prob:.0%} de probabilidad'
            }

        return None


# ═══════════════════════════════════════════════════════════════════════════════
# ORQUESTADOR CENTRAL — Integra las 5 fases
# ═══════════════════════════════════════════════════════════════════════════════

class AutonomousCerebro:
    """
    Orquestador central: integra las 5 fases en un flujo coherente
    """

    def __init__(self, db_path: str = "trading_bot.db"):
        self.name = "🧠 AutonomousCerebro"

        # Inicializar 5 fases
        self.reasoner = Reasoner()
        self.memory = Memory(db_path)
        self.improver = AutonomousImprover()
        self.planner = Planner()
        self.speculator = Speculator()

        # Estado
        self.trades_executed = []
        self.current_plan = None
        self.config = self.improver.metrics.copy()

        log.info(f"{'='*70}")
        log.info(f"[{self.name}] ✅ INICIALIZADO - 5 FASES LISTAS")
        log.info(f"{'='*70}")

    def analyze_and_decide(self, market_context: Dict) -> Dict:
        """
        Pipeline completo: analiza mercado y toma decisión

        1. RAZONADOR: Genera 3 opciones
        2. MEMORIA: Busca contextos similares
        3. AUTONOMÍA: Evalúa mejoras aplicables
        4. PLANIFICADOR: Crea plan de ejecución
        5. ESPECULADOR: Predice next move

        Retorna: decision completa con plan
        """

        log.info(f"\n{'─'*70}")
        log.info(f"[{self.name}] ANÁLISIS DE MERCADO INICIADO")
        log.info(f"{'─'*70}")

        # FASE 1: RAZONADOR
        options = self.reasoner.think_options(market_context)
        if not options:
            log.warning(f"[{self.name}] No se generaron opciones")
            return {'decision': 'SKIP', 'reason': 'no_options_generated'}

        best_option = options[0]  # Top-1 por score

        # FASE 2: MEMORIA
        similar_contexts = self.memory.find_similar_contexts(market_context, limit=5)

        # Calcular histórico de aciertos
        wins, total = self.memory.get_winrate_for_pattern(best_option.direction)
        historical_wr = (wins / total) if total > 0 else 0.5

        log.info(f"[{self.name}] MEMORIA: {total} contextos similares, WR histórico={historical_wr:.1%}")

        # FASE 3: AUTONOMÍA
        performance = self.improver.evaluate_performance(self.trades_executed)
        improvements = self.improver.propose_improvements(performance)

        log.info(f"[{self.name}] AUTONOMÍA: Performance={performance.get('status')}, "
                f"WR={performance.get('win_rate', 0):.1%}")
        for imp in improvements[:2]:
            log.info(f"  → {imp}")

        # FASE 4: PLANIFICADOR
        execution_plan = self.planner.create_execution_plan(best_option, market_context)
        self.current_plan = execution_plan

        # FASE 5: ESPECULADOR
        next_move = self.speculator.predict_next_move(market_context, self.trades_executed)
        hedge = self.speculator.suggest_hedging({'direction': best_option.direction}, next_move)

        # Decisión final
        decision = {
            'action': 'ENTER' if best_option.confidence > self.config['min_confidence_threshold'] else 'SKIP',
            'direction': best_option.direction,
            'confidence': best_option.confidence,
            'option_score': best_option.score(),
            'reasoning': best_option.reasoning,
            'plan': execution_plan,
            'next_move_prediction': next_move,
            'hedge_suggestion': hedge,
            'performance_metrics': performance,
            'timestamp': datetime.now().isoformat()
        }

        log.info(f"\n[{self.name}] DECISIÓN FINAL: {decision['action']} {decision['direction']} "
                f"(conf={decision['confidence']:.2f})")
        if hedge:
            log.info(f"  ⚠️  HEDGE SUGERIDO: {hedge['action']} {hedge['hedge_direction']}")
        log.info(f"{'─'*70}\n")

        return decision

    def log_trade_result(self, decision_id: str, outcome: str, pnl: float, direction: str, confidence: float, market_context: Dict):
        """Registra resultado de un trade para aprendizaje"""
        trade_record = {
            'decision_id': decision_id,
            'outcome': outcome,  # WIN, LOSS, BREAKEVEN
            'pnl': pnl,
            'direction': direction,
            'confidence': confidence,
            'timestamp': datetime.now().isoformat()
        }

        self.trades_executed.append(trade_record)
        self.memory.store_context(market_context, direction, outcome, pnl, confidence)

        log.info(f"[{self.name}] Trade registrado: {outcome} (PNL=${pnl:.2f})")

    def get_status(self) -> Dict:
        """Retorna estado actual del cerebro"""
        if not self.trades_executed:
            return {'status': 'INITIALIZING', 'trades': 0}

        recent_trades = self.trades_executed[-50:]
        wins = sum(1 for t in recent_trades if t['outcome'] == 'WIN')
        losses = len(recent_trades) - wins
        wr = (wins / len(recent_trades)) if recent_trades else 0
        pnl = sum(t['pnl'] for t in recent_trades)

        return {
            'status': 'RUNNING',
            'trades_total': len(self.trades_executed),
            'recent_trades': len(recent_trades),
            'win_rate': wr,
            'wins': wins,
            'losses': losses,
            'pnl': pnl,
            'current_plan': self.current_plan is not None,
            'config': self.config
        }


# ═══════════════════════════════════════════════════════════════════════════════
# EJEMPLO DE USO
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Crear cerebro
    cerebro = AutonomousCerebro()

    # Simular contexto de mercado
    mock_market = {
        'price': 1.2345,
        'volume': 150,
        'trend': 'UP',
        'volatility': 0.02,
        'momentum': 0.65,
        'structure': {'support': 1.23, 'resistance': 1.24}
    }

    # Análisis
    decision = cerebro.analyze_and_decide(mock_market)

    print("\n" + "="*70)
    print(f"DECISIÓN FINAL:")
    print("="*70)
    print(json.dumps({
        'action': decision['action'],
        'direction': decision['direction'],
        'confidence': f"{decision['confidence']:.2f}",
        'score': f"{decision['option_score']:.3f}",
        'next_move': decision['next_move_prediction']['direction']
    }, indent=2, ensure_ascii=False))

    # Simular resultado
    cerebro.log_trade_result(
        decision_id="test_001",
        outcome="WIN",
        pnl=2.50,
        direction=decision['direction'],
        confidence=decision['confidence'],
        market_context=mock_market
    )

    print("\nESTADO DEL CEREBRO:")
    print(json.dumps(cerebro.get_status(), indent=2, ensure_ascii=False))
