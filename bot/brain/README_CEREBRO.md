# 🧠 AUTONOMOUS CEREBRO PARA EXNOVA TRADER v2

## MISIÓN

Transformar el bot de trading Exnova (parado, 49.8% win rate, -$192.53 PNL) en un sistema **inteligente, autónomo y auto-mejorante** capaz de:

- ✅ Pensar en 3 opciones antes de decidir
- ✅ Aprender del historial de trades
- ✅ Mejorarse a sí mismo sin intervención humana
- ✅ Planificar ejecuciones con rollback automático
- ✅ Anticipar próximos movimientos

**Objetivo:** 55%+ win rate, operaciones autónomas, mejora continua

---

## 🏗️ ARQUITECTURA — 5 FASES INTEGRADAS

```
┌─────────────────────────────────────────────────────────────┐
│         🧠 AUTONOMOUS CEREBRO (Orquestador Central)        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  FASE 1: RAZONADOR                                          │
│  ├─ Lee: Precio, volumen, trend, momentum, volatilidad      │
│  └─ Genera: 3 opciones de trade con scores                 │
│                                                             │
│  FASE 2: MEMORIA                                            │
│  ├─ Busca: Contextos históricos similares                  │
│  ├─ Calcula: Win rate por patrón                           │
│  └─ Aprende: De trades anteriores                          │
│                                                             │
│  FASE 3: AUTONOMÍA                                          │
│  ├─ Evalúa: Rendimiento reciente (últimas 50 ops)          │
│  ├─ Propone: Ajustes automáticos (confidence, filtros)     │
│  └─ Auto-mejora: Sin intervención humana                   │
│                                                             │
│  FASE 4: PLANIFICADOR                                       │
│  ├─ Crea: Plan de ejecución (entrada, TP, SL)             │
│  ├─ Checkpoints: Puntos de control automáticos             │
│  └─ Rollback: Cancela si condiciones cambian               │
│                                                             │
│  FASE 5: ESPECULADOR                                        │
│  ├─ Predice: Siguiente movimiento del precio               │
│  ├─ Sugiere: Hedging si predicción contradice              │
│  └─ Anticipa: Posibles reversiones                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 ESTRUCTURA DE ARCHIVOS

```
bot/brain/
├─ autonomous_cerebro.py          # Motor central (5 fases)
├─ integration_wrapper.py         # Adaptador para motor existente
├─ test_cerebro.py                # Suite de pruebas
├─ README_CEREBRO.md              # Esta documentación
│
├─ (existentes)
├─ agent_trading_engine.py        # Motor existente (no modificar)
├─ adaptive_learner.py            # Sistema de aprendizaje existente
└─ ...
```

---

## 🚀 GUÍA DE INICIO

### 1. Instalar dependencias

```bash
# El Cerebro solo usa librerías standard (json, sqlite3, logging, dataclasses)
# No require instalaciones adicionales
```

### 2. Usar en el motor existente

**Opción A: Integración directa (recomendado)**

```python
from brain.integration_wrapper import CerebroTradingAdapter

# Crear adaptador
adapter = CerebroTradingAdapter(db_path="trading_bot.db")

# Usar como reemplazo de AgentTradingEngine
market_data = {
    'price': 1.2345,
    'indicators': {'rsi': 65, 'atr': 0.0025},
    'volume': 150
}

should_trade, analysis = adapter.should_trade(market_data)

# Registrar resultado
adapter.log_trade_result(outcome='WIN', pnl=2.50)
```

**Opción B: Parche automático (zero-change)**

```python
from brain.integration_wrapper import patch_agent_trading_engine

# Parchea el motor existente automáticamente
patch_agent_trading_engine()

# Ahora AgentTradingEngine usa Cerebro Autónomo sin cambios en el código
```

### 3. Monitoreo en tiempo real

```python
from brain.integration_wrapper import CerebroMonitor

monitor = CerebroMonitor(adapter)

# Status en vivo para dashboard
status = monitor.get_live_status()
# {'status': 'RUNNING', 'trades': 50, 'win_rate': '54.0%', 'pnl': '$127.50'}

# Decisión más reciente
last_decision = monitor.get_last_decision()

# Estado de las 5 fases
phases = monitor.get_5phases_status()
```

---

## 🧪 TESTING

Ejecutar suite completa:

```bash
cd bot/brain/
python test_cerebro.py
```

Resultados esperados:
```
✓ FASE 1: OK     (Razonador genera 3 opciones)
✓ FASE 2: OK     (Memoria almacena y busca)
✓ FASE 3: OK     (Autonomía propone mejoras)
✓ FASE 4: OK     (Planificador crea planes)
✓ FASE 5: OK     (Especulador predice)
✓ PIPELINE: OK   (5 fases integradas)
✓ INTEGRATION: OK (Adaptador funciona)

✅ ALL TESTS PASSED
```

---

## 📊 EJEMPLO DE USO COMPLETO

```python
from brain.autonomous_cerebro import AutonomousCerebro

# Crear cerebro
cerebro = AutonomousCerebro()

# Contexto de mercado
market_context = {
    'price': 1.2345,
    'trend': 'UP',
    'momentum': 0.70,
    'volatility': 0.015,
    'volume': 180
}

# Análisis completo (las 5 fases)
decision = cerebro.analyze_and_decide(market_context)

print(f"Acción: {decision['action']}")           # ENTER o SKIP
print(f"Dirección: {decision['direction']}")     # CALL o PUT
print(f"Confianza: {decision['confidence']:.2f}") # 0-1
print(f"Score: {decision['option_score']:.3f}")  # Score combinado
print(f"Plan: {decision['plan']['step_1_entry']}")
print(f"Siguiente: {decision['next_move_prediction']['direction']}")
print(f"Hedge: {decision['hedge_suggestion']}")

# Ejecutar trade...

# Registrar resultado para aprendizaje
cerebro.log_trade_result(
    decision_id="trade_001",
    outcome="WIN",      # WIN, LOSS, BREAKEVEN
    pnl=2.50,          # Ganancia/pérdida
    direction="CALL",
    confidence=0.78,
    market_context=market_context
)

# Status del cerebro
status = cerebro.get_status()
print(f"Win Rate: {status['win_rate']:.1%}")
print(f"PNL Total: ${status['pnl']:.2f}")
print(f"Trades: {status['trades_total']}")
```

---

## 🎯 FASE POR FASE

### FASE 1: RAZONADOR
**Qué hace:** Analiza el mercado y genera 3 opciones de trade rankeadas por score.

```
Entrada: Contexto de mercado
  - price, trend, momentum, volatility, volume, structure

Proceso:
  1. Opción 1: Trend-following (seguir tendencia)
  2. Opción 2: Mean-reversion (contra-tendencia)
  3. Opción 3: Volume-based (decisión por volumen)

  Cada opción tiene:
  - direction: CALL o PUT
  - confidence: 0-1
  - score: confianza * ratio risk/reward

Salida: [Option1(score=95), Option2(score=85), Option3(score=10)]
```

**Código:**
```python
from brain.autonomous_cerebro import Reasoner

reasoner = Reasoner()
options = reasoner.think_options(market_context)

for i, opt in enumerate(options, 1):
    print(f"{i}. {opt.direction} (score={opt.score():.3f})")
```

---

### FASE 2: MEMORIA
**Qué hace:** Busca contextos similares en el historial y calcula win rates.

```
Base de datos: SQLite (memory_contexts)
  - timestamp
  - market_conditions
  - decision_made (CALL/PUT)
  - outcome (WIN/LOSS)
  - pnl
  - confidence

Operaciones:
  - store_context(): Almacena nuevo contexto
  - find_similar_contexts(): Busca similares
  - get_winrate_for_pattern(): WR histórico de un patrón
```

**Código:**
```python
from brain.autonomous_cerebro import Memory

memory = Memory(db_path="trading_bot.db")

# Almacenar
memory.store_context(market_context, 'CALL', 'WIN', 2.50, 0.85)

# Buscar
similar = memory.find_similar_contexts(market_context, limit=5)

# Win rate
wins, total = memory.get_winrate_for_pattern('CALL')
wr = wins / total if total > 0 else 0.5
print(f"CALL win rate: {wr:.1%}")
```

---

### FASE 3: AUTONOMÍA
**Qué hace:** Evalúa rendimiento y propone mejoras automáticas.

```
Métricas:
  - win_rate: últimas 50 operaciones
  - pnl: ganancia/pérdida total
  - avg_confidence: confianza promedio
  - status: GOOD, NEEDS_IMPROVEMENT, CRITICAL

Mejoras propuestas:
  - Si WR < 50%: aumentar confidence threshold
  - Si WR < 55%: mejorar filtros de entrada
  - Si confianza baja: revisar indicadores
  - Reducir size de posición si es crítico
```

**Código:**
```python
from brain.autonomous_cerebro import AutonomousImprover

improver = AutonomousImprover()

# Evaluar
performance = improver.evaluate_performance(trades_history)

# Proponer mejoras
improvements = improver.propose_improvements(performance)
for imp in improvements:
    print(f"→ {imp}")

# Aplicar
new_config = improver.apply_improvement(improvements[0], current_config)
```

---

### FASE 4: PLANIFICADOR
**Qué hace:** Crea plan de ejecución con puntos de control automáticos.

```
Plan de ejecución:
  ├─ Step 1: ENTRY (ejecutar trade si conf > threshold)
  ├─ Step 2: TAKE_PROFIT (target 2% ganancia)
  ├─ Step 3: STOP_LOSS (máx 1% pérdida)
  ├─ Step 4: MONITOR (cada 5 segundos)
  └─ Step 5: ROLLBACK (si condiciones cambian)

Checkpoints:
  - ¿Confianza > 55%? Ejecutar entrada
  - ¿Llegó a TP? Cerrar con ganancia
  - ¿Llegó a SL? Cerrar con pérdida
  - ¿Tiempo excedido? Rollback
```

**Código:**
```python
from brain.autonomous_cerebro import Planner

planner = Planner()

# Crear plan
plan = planner.create_execution_plan(best_option, market_context)

# Ejecutar pasos
if planner.should_execute_step('step_1_entry', current_price):
    execute_trade()

if planner.should_execute_step('step_2_tp', current_price):
    take_profit()
```

---

### FASE 5: ESPECULADOR
**Qué hace:** Anticipa próximo movimiento y sugiere hedging.

```
Predicción del siguiente movimiento:
  - direction: UP, DOWN o RANGE
  - probability: 0-1
  - reasoning: por qué esta predicción

Hedging:
  - Si predicción contradice con alta probabilidad: sugerir hedge
  - Ejemplo: Si tenemos CALL pero predice DOWN 75%: sugerir PUT hedge 30%
```

**Código:**
```python
from brain.autonomous_cerebro import Speculator

speculator = Speculator()

# Predicción
next_move = speculator.predict_next_move(market_context, history)
print(f"Siguiente: {next_move['direction']} (prob={next_move['probability']:.1%})")

# Hedge
hedge = speculator.suggest_hedging(current_trade, next_move)
if hedge:
    print(f"Hedge: {hedge['action']} {hedge['hedge_direction']}")
```

---

## 🔄 FLUJO DE DECISIÓN

```
┌──────────────────────┐
│  Mercado (tick)      │
│  - precio, volumen   │
│  - indicadores       │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────────┐
│ ADAPTADOR DE INTEGRACIÓN             │
│ (convierte format legacy → cerebro)  │
└──────────┬──────────────────────────┘
           │
           ▼
┌──────────────────────────────────────┐
│ 🧠 ANÁLISIS DE MERCADO               │
│ (ENTER en pipeline de 5 fases)       │
└──────┬──────────────────────────────┘
       │
       ├─→ FASE 1: RAZONADOR
       │   (3 opciones + scores)
       │
       ├─→ FASE 2: MEMORIA
       │   (contextos históricos)
       │
       ├─→ FASE 3: AUTONOMÍA
       │   (mejoras aplicables)
       │
       ├─→ FASE 4: PLANIFICADOR
       │   (plan de ejecución)
       │
       └─→ FASE 5: ESPECULADOR
           (predicción next move)
           │
           ▼
        DECISIÓN FINAL
        ├─ Action: ENTER o SKIP
        ├─ Direction: CALL o PUT
        ├─ Confidence: 0-1
        ├─ Plan: Pasos de ejecución
        ├─ Hedge: Si aplica
        └─ Timestamp
           │
           ▼
        ¿Ejecutar trade?
        │
        YES ──→ TRADE EJECUTADO
        │
        NO ──→ ESPERAR PRÓXIMO TICK
           │
           ▼
        RESULTADO REGISTRADO
        └─→ APRENDIZAJE (FASE 2/3)
```

---

## 📈 MEJORAS ESPERADAS

| Métrica | Antes | Esperado | Mecanismo |
|---------|-------|----------|-----------|
| Win Rate | 49.8% | 55%+ | 3 opciones + memory + autonomía |
| PNL | -$192.53 | +$500+ | Mejor entrada + TP/SL |
| IA CALLS | 0 | 50+ | Autonomía ejecuta sin pausa |
| Confianza | N/A | 0.70+ | Filtros mejorados |
| Racha pérdidas | 302 | <10 | Autonomía detiene & reajusta |

---

## ⚙️ CONFIGURACIÓN

```python
# En autonomous_cerebro.py
config = {
    'min_confidence_threshold': 0.55,  # Mínima confianza para entrar
    'risk_reward_ratio_min': 1.5,      # Ratio mínimo risk/reward
    'max_consecutive_losses': 5,       # Pérdidas máximas seguidas
    'learning_rate': 0.01              # Velocidad de aprendizaje
}
```

Estas se ajustan automáticamente vía FASE 3 (Autonomía).

---

## 🐛 TROUBLESHOOTING

**Q: El Cerebro dice "SKIP" en todos los mercados**
A: Confidence threshold muy alto. Baja a 0.50 en config.

**Q: Win Rate sigue bajo**
A: Espera 50+ trades para que la FASE 2 (Memoria) tenga datos.

**Q: No se registran trades en memoria**
A: Verifica que trading_bot.db tenga permisos de escritura.

**Q: ImportError en integration_wrapper**
A: Asegúrate de ejecutar desde bot/brain/ o añade a sys.path.

---

## 📞 SOPORTE

Para dudas, revisar:
- `autonomous_cerebro.py` — Documentación en docstrings
- `test_cerebro.py` — Ejemplos de uso
- `integration_wrapper.py` — Adaptador y API
- Logs en `logging.INFO` — Trazabilidad completa

---

**Estado:** ✅ PRODUCCIÓN LISTA
**Última actualización:** 2026-09-26
**Versión:** 1.0 (5 Fases Integradas)

**🚀 ¡A cambiar el juego! 🚀**
