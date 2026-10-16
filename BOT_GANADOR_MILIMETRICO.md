# Revisión de todos los sistemas de binarias → un bot ganador milimétrico

**Fecha:** 2026-10-16
**Rama:** `arena/95dffe11-exnova-trader2`
**Filosofía aplicada:** nada se implementó sin medirlo antes. Cada arreglo
aparece aquí con el número que lo justifica.

---

## 1. Qué se revisó

El repo contiene **tres familias de sistemas de trading** que nunca se habían
cruzado:

| Familia | Dónde vive | Estrategias |
|---|---|---|
| `app/` (motor nuevo) | `app/strategies/` | `sr_bounce`, `trend_continuation`, `breakout_retest`, `mean_reversion`, `breakout_direct` |
| `bot/strategies/` (familia PCR) | `bot/strategies/` | `pcr_simple`, `pcr_complete`, `pcr_hybrid` + 8 "porteros" validadores |
| `bot/backtest/` (playbook) | `bot/backtest/strategies_book.py` | 10 estrategias de investigación (Triple EMA, SAR, fractales…) |

La única estrategia **conectada al bot en vivo** era `sr_bounce`
(`app/agents/signal_agent.py`). Es decir: el sistema tenía cinco estrategias
written, tres escritas, diez escritas más, y operaba con una.

---

## 2. Cómo se midió (sin inventar nada)

Se construyó `scripts/research_strategy_audit.py`, que:

- genera series OHLC reproducibles (semilla fija) en 6 regímenes: tendencia
  alcista, tendencia bajista, rango lateral, alta volatilidad, baja
  volatilidad y mercado sin dirección;
- ejecuta **cada estrategia por separado** sobre exactamente la misma serie;
- resuelve cada operación contra el **cierre de la vela de expiración**
  (nunca contra la vela de entrada, que ya se vio al entrar);
- compara contra el break-even real del payout 0.85 → **54.05%**.

Punto de partida: `payout=0.85`, break-even `1/(1+0.85) = 0.5405`.

---

## 3. Lo que la medición destapó

### 3.1 `sr_bounce` estaba perdiendo dinero de forma sistemática

Era la estrategia en vivo. Su lado PUT acertaba **1.9%** en tendencia alcista
(2.720 operaciones) y su lado CALL **2.7%** en tendencia bajista (2.717
operaciones). No era mala suerte: era un bug.

`_check_rejection()` aceptaba "rebote" con que una de las últimas 3 velas
hubiera **rozado** el nivel y la vela actual no fuera alcista. En una tendencia
alcista, cualquier vela roja cerca de la resistencia contaba como rechazo.
Operaba en casi todas las velas, siempre en contra de la tendencia.

**Arreglo:** ahora exige las tres pruebas de un rechazo real —
(1) el nivel fue tocado, (2) la vela de entrada tiene **mecha larga hacia el
nivel** (≥35% del rango), (3) el cierre queda **separado** del nivel.

| `sr_bounce` | antes | después |
|---|---|---|
| PUT en tendencia alcista | 1.9% (2.720 trades) | **60.0%** (30 trades) |
| CALL con régimen desconocido | 12.7% (3.360 trades) | **57.1%** (21 trades) |
| CALL en rango | 73.6% (311) | **75.8%** (33) |

Pasó de 5.400 operaciones perdedoras a 122 con edge.

### 3.2 El clasificador de régimen no podía detectar tendencias bajistas

`_compute_ema_slope()` devolvía `ema - _compute_ema([0])`, o sea el **nivel**
de la EMA — siempre positivo con precios positivos. La condición
`ema_slope < 0` era **inalcanzable**: `TREND_DOWN` no existía.

Consecuencia: todas las tendencias bajistas caían en `UNKNOWN`, y cualquier
filtro por régimen se quedaba ciego en la mitad del mercado.

**Arreglo:** pendiente real = `(EMA_hoy - EMA_hace_5_velas) / EMA_hace_5_velas`.

### 3.3 "Régimen desconocido" se trataba como "timeframes en conflicto"

`MultiTimeframeAgent` sólo sabía de `agree / partial / conflict`. Cuando los
tres timeframes venían `UNKNOWN`, caía en `conflict` y **bloqueaba toda señal**.
No opinar no es contradecirse.

**Arreglo:** se añade `neutral` (menos de 2 timeframes con opinión). `conflict`
ahora significa de verdad que dos timeframes con opinión se contradicen.

### 3.4 `breakout_direct`: un roce del nivel contaba como ruptura

Medido con el feature `distancia_de_ruptura / ATR`:

| Escenario | WR | dist/ATR medio |
|---|---|---|
| Tendencia alcista | 93.8% | 1.30 |
| Tendencia bajista | 93.8% | 1.25 |
| Rango lateral | 38.3% | 0.45 |
| Alta volatilidad | 47.7% | 0.55 |

**Arreglo:** exigir que el cierre se separe del nivel **≥ 1 ATR**. Es una regla
estándar de calidad de rupturas, no un número sacado del aire.

| `breakout_direct` | antes | después |
|---|---|---|
| Win rate | 78.8% | **90.8%** |
| Profit factor | 3.16 | **8.43** |
| Drawdown máximo | $337 | **$41.5** |
| Racha perdedora | 12 | **3** |

### 3.5 Dos bugs críticos encontrados de paso (no medidos: reproducidos)

**(a) `wilson_lower_bound` no existía.** `get_historical_edge()` la llamaba sin
que estuviera definida en ningún módulo. En cuanto el `EdgeValidatorAgent`
tenía **≥3 operaciones reales** (modo PRACTICE) o ≥100 (modo REAL), la consulta
reventaba con `NameError`, la excepión subía hasta el scan loop y **el bot
dejaba de operar en silencio** — justo cuando empezaba a tener datos.
Reproducido y arregado con la implementación real del intervalo de Wilson.
Ahora el edge se mide con el límite inferior al 95% (3/3 aciertos → 43.8%, no
100%), que es la medida honesta.

**(b) Escribir antes de `migrate()` tumbaba el proceso.** El
`MarketRegimeAgent` guarda un snapshot en cada clasificacion. Con una base
nueva (arranque en frío, o tests) eso moría con `no such table`. Ahora
`connect()` auto-repara el esquema si falta.

**(c) El `EntryTimingAgent` bloqueaba toda ruptura.** Está diseñado para
rebotes (espera mecha de rechazo y vela cerrada) y rechazaba las señales de
`breakout_direct` como *"Candle 100% complete - too late"*. Como la ruptura se
mide entrando en el cierre de la vela de ruptura, ahora la propia estrategia
declara su momento de entrada.

### 3.6 Estrategias que la medición descarta

| Estrategia | Resultado | Veredicto |
|---|---|---|
| `trend_continuation` | 38–48% WR | **Fuera del pool de votantes** |
| `breakout_retest` | 36–45% WR | **Fuera del pool de votantes** |
| `mean_reversion` PUT en rango | 52.0% | Por debajo del break-even |
| Familia PCR (`pcr_*`) | Sólo probada sobre **datos sintéticos propios**, sin serie real común | No incorporada: no hay evidencia comparable |

Se midió también un filtro de momentum M1 ("2 de 3 últimas velas a favor"):
**empeoraba** en rango (48% vs 69%) y era neutro en tendencia. Se descartó.

---

## 4. El bot resultante: `ConsensusWinningStrategy`

`app/strategies/consensus_winning.py`

No es un promedio de estrategias. Es una **votación con portero de régimen**:

1. Se clasifica el régimen en M15.
2. **Sólo votan las estrategias con edge medido en ese régimen**:

   | Régimen | Votantes |
   |---|---|
   | `TREND_UP` / `TREND_DOWN` | `sr_bounce`, `breakout_direct` |
   | `RANGE` | `sr_bounce`, `mean_reversion` |
   | `UNKNOWN` | nadie |
   | `HIGH_VOLATILITY` / `LOW_LIQUIDITY` / `NEWS_RISK` | nadie |

   `UNKNOWN` se excluyó a propósito: agrupaba tendencias suaves (78% de
   acierto) y mercados de volatilidad uniforme (42%). Sin etiqueta fiable no
   hay forma de separar los dos casos.
3. Portero de volatilidad: percentil de ATR fuera de `[0.10, 0.85]` → no operar.
4. Ganar exige **≥2 votos** en la misma dirección, o **1 voto con confianza
   ≥0.70** y timeframes no neutrales.
5. Confianza final = `max(confianzas) + 0.05` por voto extra, tope 0.95.
6. Multi-timeframe en `conflict` → **no operar**.

---

## 5. Resultado

Muestra interna (semillas 1-2, 1.500 velas × 6 escenarios):

| Estrategia | Trades | WR | Expectancy | PF | maxDD | Racha P | Sharpe |
|---|---|---|---|---|---|---|---|
| `sr_bounce` | 122 | 59.0% | +0.092 | 1.22 | $71 | 5 | 1.93 |
| `mean_reversion` | 290 | 59.0% | +0.091 | 1.22 | $81 | 7 | 1.06 |
| `trend_continuation` | 176 | 48.3% | −0.107 | 0.79 | $172 | 6 | −0.56 |
| `breakout_retest` | 38 | 44.7% | −0.172 | 0.69 | $40 | 4 | −0.43 |
| `breakout_direct` | 1.408 | 90.8% | +0.681 | 8.43 | $41 | 3 | 7.46 |
| **CONSENSO_WINNING** | **691** | **90.6%** | **+0.676** | **8.19** | **$43** | **3** | **12.52** |

**Fuera de muestra** (semillas 11-12, mismas reglas, datos no usados para
decidir nada):

| | Trades | WR | Expectancy | PF | maxDD | Racha P | Sharpe |
|---|---|---|---|---|---|---|---|
| `breakout_direct` | 1.350 | 91.6% | +0.695 | 9.30 | $73 | 6 | 6.40 |
| **CONSENSO_WINNING** | **628** | **89.3%** | **+0.653** | **7.12** | **$43** | **4** | **9.43** |

El resultado se mantiene fuera de muestra (89-91% de acierto, expectancy
+0.65 por operación, profit factor 7-8). El consenso opera **la mitad de
veces** que la mejor estrategia individual con el mismo win rate, la mitad de
drawdown y mejor Sharpe: es el perfil "milimétrico" que se pedía.

Por escenario (muestra interna):

| Escenario | Trades | WR | PnL |
|---|---|---|---|
| Tendencia alcista | 257 | 91.8% | +$1.796 |
| Tendencia bajista | 345 | 96.8% | +$2.729 |
| Rango lateral | 29 | 62.1% | +$43 |
| Baja volatilidad | 19 | 78.9% | +$87 |
| Sin dirección | 20 | 65.0% | +$40 |
| Alta volatilidad | 21 | 47.6% | −$25 |

---

## 6. Archivos

### Nuevos
- `app/strategies/consensus_winning.py` — el bot de consenso
- `scripts/research_strategy_audit.py` — auditoría por estrategia/régimen
- `scripts/research_consensus_edge.py` — consenso vs estrategias
- `tests/test_consensus_winning.py` — tests de la estrategia nueva
- `tests/test_strategy_fixes.py` — regresión de cada bug encontrado
- `reports/strategy_audit.json`, `reports/consensus_edge_research.json`,
  `reports/consensus_edge_oos_seeds11_12.json`

### Modificados
- `app/strategies/sr_bounce.py` — exige rechazo real (3 pruebas)
- `app/strategies/breakout_direct.py` — exige ≥1 ATR de separación
- `app/agents/market_regime_agent.py` — pendiente de EMA real + percentil de
  ATR acotado (el backtest pasaba de O(n²) a lineal)
- `app/agents/multi_timeframe_agent.py` — `neutral` ≠ `conflict`
- `app/agents/signal_agent.py` — usa el consenso, sin fallback
- `app/research/backtester.py` — resuelve contra la vela de expiración;
  incluye el consenso; acepta alineación parcial
- `app/data/repository.py` — `wilson_lower_bound()` implementada (no existía),
  `connect()` auto-repara el esquema, `BOT_DISABLE_PERSISTENCE=1` para backtests
- `app/strategies/breakout_direct.py` — declara su momento de entrada

---

## 7. Cómo reproducirlo

```bash
pip install -r requirements.txt

# Auditoría: qué estrategia gana/pierde en qué régimen
BOT_DISABLE_PERSISTENCE=1 python scripts/research_strategy_audit.py --seeds 2 --candles 1500

# Consenso vs estrategias individuales
BOT_DISABLE_PERSISTENCE=1 python scripts/research_consensus_edge.py --seeds 2 --candles 1500

# Fuera de muestra (semillas distintas)
BOT_DISABLE_PERSISTENCE=1 python scripts/research_consensus_edge.py --seeds 2 --candles 1500 --seed-offset 10

# Tests (42 tests: financial logic, integridad de resolución, regresión de bugs)
python -m pytest tests/ -q
```

---

## 8. Lo que Falta (honestidad)

1. **Los datos siguen siendo sintéticos.** El generador es un GBM con deriva:
   las tendencias son más limpias que las reales. Los números de arriba son
   una **hipótesis validada**, no una promesa. El siguiente paso obligatorio es
   repetir la auditoría con velas reales de Exnova
   (`scripts/fetch_history.py --assets … --days 180`) y volver a medir.
2. **Nunca se pasó a dinero real.** El bot sigue en `PRACTICE`. Que una
   estrategia tenga edge en backtest no la habilita: hace falta forward
   testing y que el `EdgeValidatorAgent` acumule muestra real.
3. **La familia PCR no se incorporó** porque sólo está validada sobre sus
   propios datos sintéticos, sin una serie común con las demás. Para entrar al
   pool necesita pasar la misma auditoría.
4. **`trend_continuation` y `breakout_retest` quedan fuera del pool**, no
   borradas: si una futura auditoría las muestra con edge, se reincorporan
   cambiando `VOTERS_BY_REGIME`.
5. **El bot nunca se ha ejecutado contra Exnova real en esta sesión.** Lo que
   se verificó es el pipeline completo (`SignalAgent.scan` → timing → edge →
   riesgo) sobre velas sintéticas: de 31 señales generadas, 23 llegaron
   aprobadas hasta el risk manager. Falta correrlo en `PRACTICE` contra el
   broker y dejar que el `EdgeValidatorAgent` acumule muestra real.
