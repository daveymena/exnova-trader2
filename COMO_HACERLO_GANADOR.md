# Cómo hacer que este bot sea ganador, aprenda, trabaje y sea consistente

**Fecha:** 2026-10-16
**Rama:** `arena/95dffe11-exnova-trader2`

Este documento responde a una pregunta concreta: *qué falta*. No repite lo que
ya funciona — eso está en `BOT_GANADOR_MILIMETRICO.md`. Aquí está el mapa de lo
que impide hoy que el bot pase de "backtest prometedor" a "cuenta que crece".

---

## El diagnóstico en una frase

> El bot **mide** bien y **decide** con datos sintéticos. No hay nada que
> conecte una cosa con la otra, y no hay ni una vela real descargada.

Concretamente, tres huecos:

| # | Hueco | Consecuencia |
|---|---|---|
| 1 | **Cero datos reales.** `bot/data/history/` vacío, sin `.env` | El 90% del backtest es una hipótesis, no un hecho |
| 2 | **El mapa de votantes está hardcodeado** en `VOTERS_BY_REGIME` | El bot no puede aprender: su "conocimiento" es una constante de Python |
| 3 | **El dimensionado no es Kelly.** `_compute_position_size` = `confianza × 0.5%` | Con win rate observado, Kelly puro diría apostar el 100% de la cuenta tras 5 aciertos |

Los sistemas de aprendizaje de `bot/brain/` (`adaptive_learner`,
`improvement_loop`, `strategy_refiner`, `supervised_zone_learner`) **existen
pero nadie lee su salida**. Generan recomendaciones en JSON que el bot en
funcionamiento nunca consulta.

---

## Lo que ya está hecho (esta sesión)

### 1. El puente entre medir y decidir: `EdgeLedger`

`app/research/edge_ledger.py`

Lee las operaciones **reales** ya resueltas (solo `resolution_source` broker o
vela observada) y recalcula qué estrategias tienen edge en cada régimen.
Cuando hay muestra suficiente, su respuesta **reemplaza** al mapa sintético.

Reglas de seguridad — son el punto del diseño, no un detalle:

1. Solo cuenta evidencia real. Una operación simulada no enseña nada.
2. Muestra mínima por celda (estrategia × dirección × régimen): 30.
3. El **límite inferior de Wilson al 95%** debe superar el break-even + 3%.
   El win rate observado miente; el límite inferior no.
4. **Estabilidad:** la mitad reciente debe mantener el edge. Una estrategia
   que ganaba y dejó de ganar se cae sola.
5. Si ya se midió algo en un régimen, la medición manda — aunque sea para
   descubrir que todo pierde. No se vuelve al mapa sintético para rescatar a
   una estrategia que ya demostró que pierde.

Verificado con datos inyectados:

```
sr_bounce     PUT  trend_up   n=50  WR=10.0%  -> FUERA de los votantes
breakout_direct CALL trend_up n=70  WR=88.6%  inf95=79.0% -> VOTA
mean_reversion CALL range     n=65  WR=84.6%  inf95=73.9% -> VOTA
```

`sr_bounce` estaba en el mapa sintético para `TREND_UP`. Con muestra real que
muestra que pierde, sale. Eso es aprender.

### 2. Dimensionado por Kelly acotado

`RiskManagerAgent.stake_fraction()` — calcula la fracción de equity con Kelly
sobre el **límite inferior** de Wilson, no sobre el win rate observado:

| Muestra | Kelly con WR observado | Kelly con límite inferior |
|---|---|---|
| 5/5 ganadas | **100%** de la cuenta | 5.4% |
| 9/10 | 78.2% | 12.0% |
| 92/100 | 82.6% | 67.4% |

Después se aplica fracción 0.15 y un **tope duro del 2%** del equity por
operación. En binarias con payout 0.85, más que eso es ruina casi segura.

### 3. El informe de consistencia

`scripts/consistency_report.py` — responde "¿es consistente o fue suerte?".

No pregunta el win rate global. Lo parte en ventanas temporales y regímenes, y
exige que **todas** las ventanas con muestra suficiente se mantengan sobre el
break-even. Un bot con 90% una semana y 45% la siguiente no pasa.

Hoy dice, correctamente: *"NO HAY NADA QUE MEDIR TODAVÍA"*.

---

## Lo que FALTA, en orden de prioridad

### Prioridad 1 — Conseguir datos reales (bloquea todo lo demás)

Sin velas reales de Exnova no se puede validar nada. El script ya existe:

```bash
# 1. Credenciales en .env (EXNOVA_EMAIL / EXNOVA_PASSWORD)
cp .env.example .env

# 2. Descargar histórico: 180 días, varios activos, M1 y M5
python scripts/fetch_history.py --assets EURUSD,GBPUSD,USDJPY --days 180
python scripts/fetch_history.py --assets EURUSD --days 180 --timeframes 60,300
```

**Qué hacer con esos datos:**

1. Correr la auditoría sobre velas reales (ya implementado):
   ```bash
   python scripts/research_strategy_audit.py --source real --asset EURUSD
   ```
   Lee de `bot/data/history/{ACTIVO}_60.csv` (o `.parquet`), que es exactamente
   el nombre y formato que escribe `fetch_history.py`.
2. Si el edge sobrevive → el mapa de votantes sintético se sustituye por el
   medido en real.
3. Si el edge **no** sobrevive → se ha aprendido el dato más valioso posible
   sin arriesgar un peso, y hay que rediseñar la estrategia.

**Este es el paso que decide si el proyecto sirve o no.** Todo lo demás es
detalle hasta que exista.

### Prioridad 2 — Forward testing en PRACTICE

Con datos reales validando el backtest, toca acumular muestra real:

```bash
# .env
ACCOUNT_TYPE=PRACTICE
TRADING_MODE=PRACTICE

# arrancar
python -m app.main
```

Y dejarlo correr. El `EdgeValidatorAgent` ya mide el edge real del
`consensus_winning` y **bloquea las operaciones si no supera el break-even +
margen**. El `EdgeLedger` además dice qué votante concreto falla.

Cada ~30 operaciones:

```bash
python scripts/consistency_report.py
```

Criterios para seguir (no son opinión, son los que mide el informe):

- Límite inferior 95% sobre el break-even
- Todas las ventanas sobre el break-even
- Drawdown máximo dentro del límite diario configurado
- Racha perdedora máxima conocida y tolerada por el gestor de riesgo

### Prioridad 3 — Cerrar el loop sin intervención humana

Hoy el `EdgeLedger` se consulta en cada `scan()`, así que el bot **ya se
auto-ajusta**: si una estrategia deja de tener edge, sale de la votación sin
que nadie toque código. Lo que falta es que alguien lo ejecute y lo registre:

- Un job periódico (el `supervisor_loop.py` ya existe) que corra
  `consistency_report.py` y guarde el resultado en `ai_overnight`.
- Un **circuit breaker**: si el informe marca "no consistente", el bot no
  arranca. Que decida el dato, no las ganas.

### Prioridad 4 — Lo que el repo ya tiene y conviene conectar

No hay que construir más: hay que **conectar** lo que existe.

| Sistema existente | Para qué sirve | Estado |
|---|---|---|
| `EdgeValidatorAgent` | Veto maestro sobre el edge real del compuesto | Conectado |
| `RiskManagerAgent` | Límites diarios/semanales, rachas, sin martingale | Conectado |
| `EdgeLedger` (nuevo) | Ajuste fino por votante y régimen | Conectado |
| `bot/brain/strategy_refiner.py` | Refinar parámetros de estrategias | **Sin conectar** |
| `bot/brain/adaptive_learner.py` | Aprender de resultados | **Sin conectar** |
| `bot/core/trade_journal.py` | Diario de operaciones | **Sin conectar** |
| `bot/core/self_evaluator.py` | Auto-evaluación | **Sin conectar** |

La recomendación es **no** conectarlos todos. Cada sistema de aprendizaje que
se añade sin una métrica que lo juzgue es otra forma de sobreajustar. Primero
hacer que el `EdgeLedger` funcione con datos reales; los demás solo si
demuestran mejorar algo medible.

---

## El orden correcto, resumido

```
1. Descargar velas reales de Exnova          <- SIN ESTO, NADA
2. Auditar las estrategias sobre datos reales
3. Si el edge sobrevive: forward testing en PRACTICE
4. Acumular 30+ operaciones reales por régimen
5. El EdgeLedger toma el mando del mapa de votantes
6. El consistency_report decide si se sube exposición
7. Solo entonces, pensar en dinero real
```

## Lo que NO hay que hacer

- **No subir exposición porque el backtest dio 90%.** El backtest es sobre
  datos sintéticos con tendencias más limpias que las reales.
- **no operar en régimen `UNKNOWN`** hasta tener evidencia propia. Está
  excluido a propósito: agrupaba tendencias suaves (78% de acierto) y mercados
  de volatilidad uniforme (42%).
- **No pasar a REAL** sin que el `consistency_report` diga "consistente"
  durante varias semanas consecutivas.
- **No añadir más sistemas de aprendizaje** sin una métrica que los juzgue.

---

## Archivos de esta sesión

| Archivo | Qué hace |
|---|---|
| `app/research/edge_ledger.py` | Mide edge real y decide quién vota |
| `scripts/consistency_report.py` | Informe de consistencia por ventana y régimen |
| `tests/test_edge_ledger.py` | 13 tests del loop de aprendizaje |
| `scripts/research_strategy_audit.py` | Añadido modo `--source real` |
| `app/agents/risk_manager_agent.py` | Kelly acotado desde el límite inferior |
| `app/strategies/consensus_winning.py` | Consulta al `EdgeLedger` |

```bash
python -m pytest tests/ -q        # 55 tests
python scripts/consistency_report.py
```
