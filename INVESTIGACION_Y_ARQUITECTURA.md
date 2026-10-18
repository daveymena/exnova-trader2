# Investigación de repos y estrategias de opciones binarias, y qué se construyó sobre este repo

Fecha: 2026-10-17 · Rama: `arena/e290f1d3-exnova-trader2` · Base: commit `cec7c64`

---

## 1. Lo que dice la investigación, sin adornos

### 1.1 La aritmética decide antes que cualquier estrategia

Una binaria paga `payout` si aciertas y pierde el 100% si fallas. El win rate de
equilibrio es:

```
break_even = 1 / (1 + payout)
```

| payout | break-even |
|---|---|
| 0.70 | 58.82 % |
| 0.80 | 55.56 % |
| **0.85** | **54.05 %** |
| 0.88 | 53.19 % |
| 0.90 | 52.63 % |
| 0.95 | 51.28 % |

Expectancy por unidad apostada = `WR · payout − (1 − WR)`. **A payout 0.85, un
50 % de acierto pierde 7.5 % por operación.** No hay gestión de capital que
arregle una expectancy negativa: solo cambia la velocidad a la que se pierde.

Esto es lo primero que hay que tener claro, porque condiciona todo lo demás. La
mayoría de los repos públicos no lo menciona.

### 1.2 Repos investigados

Se buscaron en la API de GitHub repos de opciones binarias (IQ Option, Pocket
Option, Quotex, Exnova) y se leyeron los READMEs y la estructura de los más
relevantes:

| Repo | ★ | Aporte real |
|---|---|---|
| `bozidar-quant/quant-strategy-backtester` | 1 | **El más valioso.** Resultado negativo publicado en vez de escondido. Metodología a copiar. |
| `VitalySvyatyuk/pocket_option_trading_bot` | 142 | Arquitectura de señales por websocket normalizadas a 1 s. **Usa martingala** (stack `[1,3,7,15,31,...]`), prohibida en tu `AGENTS.md`. |
| `metheuspsc/Iq_Option_Bots` | 134 | Volumen, poco método. |
| `tradervitaly/pocket-option-bot-pro` | 101 | Ídem. |
| `razielapps/chfjpy_bot` | 90 | Un solo par, sin validación out-of-sample. |
| `ChipaDevTeam/BinaryOptionsToolsV1` | 54 | Centrado en Discord y monetización por afiliados. Bajo valor metodológico. |
| `carlosrod723/Quotex-Trading-Bot` | 45 | — |
| `ByteSupreme/QuotexAutoTradeBot` | 35 | — |
| `FlatrockITSolutions/Pocket-Option-Bot` | 30 | — |
| `khokan4466/quotex-signal-bot` | 29 | Ideas SMC/ICT (barridos de liquidez). |
| `ezozu/NeuralEdge` | 25 | RL (DQN/PPO/A2C) sobre ticks + cuantización. Fuera de alcance sin `torch`. |
| `TopTrenDev/pocketoption-signal-bot` | 26 | EMA + RSI. |
| `mindflarevortx-maker/Trading-Bot-Zai-v1` | 3 | Confluencia de 7 capas + walk-forward antes de cada señal. Arquitectura útil; **su claim de "95 %+ de precisión" no es creíble**. |
| `Losomon/binary-options-trading-simulator` | 0 | Checklist educativo de indicadores. |
| `TheAngelTrader/ADX_Wilder_RMA_Strategy` | 0 | ADX de Wilder + DI + Stochastic. |

**El hallazgo más importante no es una estrategia, es un resultado negativo.**
`bozidar-quant/quant-strategy-backtester` aplicó la metodología correcta —
partición train/test estricta, parámetros elegidos solo en train, juicio solo en
test no visto, sin cherry-picking de la rejilla — y publicó que:

- Binarias *Touch*: ~23–25 % de acierto contra un 52.6 % necesario → **estructuralmente inviables**.
- Binarias *Up/Down*: 48.9 % → por debajo de la línea.
- **Ninguna de las cuatro familias de estrategias mostró edge out-of-sample.**

La mayoría de los repos con muchas estrellas no hacen esa partición. Reportan el
mejor rincón de su rejilla de parámetros sobre el mismo historial donde la
buscaron. Eso no es un backtest, es un ajuste de curva.

### 1.3 Benchmarks realistas de win rate por temporalidad

De la literatura del dominio (learn.binany.com y equivalentes):

| Temporalidad | WR realista | Nota |
|---|---|---|
| 1 min | 50–57 % | Domina el ruido; habitualmente no rentable |
| 3 min | 53–59 % | Marginal |
| 5 min | 56–63 % | Con confirmación + filtro ADX |
| 15 min | 58–67 % | La más viable |

Mínimo ~50 operaciones para una estimación usable; **por debajo de 20 la
varianza domina por completo**. Hay que medir el WR separado por activo, sesión
horaria y temporalidad — no agregado.

### 1.4 Datos de reguladores

- ESMA (investigación previa a la prohibición): **70–90 % de las cuentas minoristas de binarias pierden dinero**.
- Dukascopy: hacen falta ~55–60 % de acierto para no perder; **la expiración fija impide cortar pérdidas y dejar correr ganancias**, que son las dos palancas con las que cualquier sistema de trading gestiona su expectancy.

### 1.5 Riesgo específico de los activos OTC

Los precios OTC **los genera el propio broker**, no un mercado interbancario. El
broker controla el feed, el payout y la liquidación, y nada de eso es verificable
externamente. Además se documenta que a veces **suben el payout precisamente en
los activos OTC más volátiles e ilíquidos**, donde el win rate cae más de lo que
sube el payout. Hay que mirar las dos cifras juntas, nunca el payout aislado.

**Consecuencia de diseño:** este proyecto trata los datos OTC como no verificables
y etiqueta la procedencia de cada precio (`DataSource`), porque no se puede
medir edge sobre un precio que no se puede auditar.

---

## 2. Qué estaba mal en este repo

Tu propio `app/NOT_PRODUCTION_READY.md` (auditoría interna del 2026-07-31) ya
listaba 10 bugs críticos. Tenía razón, y el diagnóstico de fondo era peor que la
lista.

### 2.1 El mecanismo que hundió las ~500 operaciones anteriores

`bot/core/self_evaluator.py` existe por una razón concreta, documentada en él:
el bot anterior **ascendió reglas ajustadas con n = 1, 6, 7 y 9 observaciones**.
A payout 0.86 el break-even es 53.76 %, así que 6/9 (66.7 %) *parece* edge.

No lo es. El intervalo de Wilson al 95 % para 6/9 es **[35 %, 88 %]**. Es decir:
los datos eran compatibles con un sistema que pierde dinero de forma severa.
Promover sobre ese intervalo es promover ruido, y el ruido no tiene por qué
seguir siéndolo la semana siguiente.

El histórico lo confirma: **49.8 % de acierto, PnL −$192.53, racha perdedora
máxima de 302** (`RESUMEN_EJECUTIVO.md`). Un 49.8 % a payout 0.85 tiene
expectancy negativa garantizada.

### 2.2 Bugs corregidos en esta sesión

| # | Bug | Efecto real | Estado |
|---|---|---|---|
| 1 | Sizing: `max_position_pct * confidence` sobre el equity | **35–50 % del capital por operación**. Ruina en 2–3 trades malos | Corregido: `/100` + límites absolutos |
| 3 | `wilson_lower_bound` sin definir (`repository.py:592`) | `NameError` al consultar el edge | Corregido |
| 4 | Gate sobre win rate puntual | Promovía ruido (el bug de las 500 operaciones) | Corregido: cota inferior de Wilson |
| 5 | `edge_validator`: muestra mínima dependiente del modo, y **payout mínimo saltado en practice** | Acumulaba "evidencia" sobre instrumentos matemáticamente inviables | Corregido: piso de payout incondicional |
| 7 | `_open_positions` decremento incondicional + racha invertida | Contadores de riesgo falsos | Corregido: `on_trade_opened`/`on_trade_closed` |
| 8 | `exnova_broker._EXNOVA_PATHS` con carpetas personales hardcodeadas; cae a PaperBroker **logueando "REAL MONEY TRADING ACTIVE"** | Mensaje falso sobre dinero real | Parcial (ver §5) |
| 9 | `trading_apply_change` sin freno estadístico, solo filtro de texto evadible | El LLM aplicaba lo que quisiera | **Corregido**: pasa por el gate |
| 10 | Backtester con **look-ahead**: `won = current_candle.is_bullish` sobre la vela que generó la señal | No medía nada; medía su propia entrada | **Corregido**: reescrito |

Los puntos 2 y 6 ya estaban arreglados en el repo antes de esta sesión y no se
tocaron.

### 2.3 Bugs encontrados durante la reescritura (no estaban en la auditoría)

- **`_find_pool` lanzaba `ZeroDivisionError` en la primera iteración.** La
  estrategia de barridos quedaba inutilizada *en silencio*: el motor captura la
  excepción y sigue, así que el bot simplemente dejaba de ver barridos para
  siempre sin que nadie lo notara.
- **`entry_timing_agent` usaba `datetime.utcnow()` en vez del `signal_timestamp`
  que recibía.** En vivo la diferencia era pequeña; en un backtest con reloj
  virtual la vela tenía meses de "antigüedad" y salía `Candle 41129692 %
  complete`. El backtest entero quedaba sin timing válido. Regla general: ningún
  componente de decisión puede consultar el reloj de pared.
- **El multiplicador del setup se aplicaba dos veces** (en `RiskManagerAgent.approve`
  y otra vez en el motor). El trade salía a 1/4 de 1/4 del tamaño y, peor,
  `on_trade_opened` guardaba ese stake encogido como `last_stake`: al ciclo
  siguiente el anti-martingala veía una "subida" legítima y la rechazaba. **25
  rechazos falsos en 120 ciclos, 1 sola operación.**
- **El agente de timing confundía "la vela cerró" con "llegué tarde".** Con un
  feed causal y un ciclo alineado al minuto, la última vela tiene *siempre*
  exactamente 100 % de edad → `TOO_LATE` en cada ciclo.
- **`settle()` no propagaba el `data_source` del broker.** Un paper-trade sobre
  replay CSV real se quedaba en `UNKNOWN` y **nunca contaba como evidencia**,
  rompiendo justo lo que hace útil al forward test.
- **Regresión que introduje y detecté:** la calidad de las velas del simulador
  dependía de `len(closed)`, así que la misma vela podía salir `STALE` en una
  llamada y `NORMAL` en la siguiente. Un feed que cambia de opinión sobre su
  propio histórico no es reproducible.
- **Los tests codificaban el bug.** `test_stake_based_on_equity` afirmaba
  `stake <= 10000 * max_position_pct`, o sea 5.000 sobre una cuenta de 10.000.
  Un test que reproduce la interpretación equivocada no detecta el bug: lo
  blinda. Se reescribió para afirmar la cota correcta (`equity * pct / 100`) y se
  añadió una guarda explícita de regresión.

---

## 3. Qué se construyó

### 3.1 Decisión de diseño que debes conocer

Elegiste **supervisión LLM-driven**. Está implementada así: el LLM diagnostica,
propone y explica. **Pero no aplica.** Entre su propuesta y el disco hay un freno
determinista que no depende de ningún modelo.

No es desconfianza del modelo, es el diseño. La auditoría de tu propio repo
documenta que el mecanismo que hundió las operaciones anteriores fue exactamente
un LLM aplicando cambios sin gate. Un LLM sin freno reproduce ese mecanismo con
mejor prosa.

El freno tiene cinco capas:

1. **Sandbox.** Cada estrategia declara `param_space`. Lo que se sale se recorta
   y se registra. Un LLM que proponga `min_confidence=0.0` consigue `0.30` y una
   línea en el log.
2. **Walk-forward.** Ajuste en train, juicio solo en test no visto.
3. **Benjamini-Hochberg.** Si pruebas 20 variantes y te quedas con la mejor, esa
   "mejor" es casi seguro la que tuvo más suerte: con 20 pruebas al 5 % hay ~64 %
   de probabilidad de al menos un falso positivo. BH ajusta por el número de
   hipótesis probadas a la vez. **Sin esto el motor "mejoraría" indefinidamente
   sobre ruido.**
4. **Tope de cambios** por ventana temporal.
5. **Revisión y rollback.** Tras aplicar se mide el rendimiento real; si degrada
   con muestra mínima, se revierte y se registra.

Y si no hay `openai` instalado, el motor degrada a búsqueda local determinista.
El LLM añade hipótesis; no es un punto único de fallo.

### 3.2 Arquitectura

```
app/stats/core.py            Wilson, p-valores binomiales, BH, Bonferroni, Kelly,
                             drawdown, rachas, break-even. Python puro, sin deps.
                             Si algo no se puede calcular devuelve None: nunca 0.
      │
app/data/
  ├── schemas.py             + DataSource, SetupRecord/State/Verdict/Key,
  │                            ImprovementProposal, BacktestRun
  ├── repository.py          connect() auto-migra. EVIDENCE_SQL aísla el histórico
  │                            sintético del real
  ├── market_sim.py          Microestructura OTC con alpha inyectable +
  │                            null_market() y positive_control()
  ├── csv_loader.py          Ingesta de histórico real
  └── feed.py                MarketFeed (único punto de causalidad),
                             SimulatedFeed, ReplayFeed (+fork), BrokerFeed
      │
app/strategies/
  ├── base.py                UNA implementación de cada indicador (Wilder
  │                            RSI/ATR/ADX/DI, EMA, Bollinger, Stochastic,
  │                            fractales, patrones) + ABC Strategy
  ├── liquidity_sweep_reversal.py   NUEVA: SMC/ICT + Wyckoff spring/upthrust
  ├── engulfing_momentum.py         NUEVA: envolvente a favor de tendencia M15
  ├── registry.py                   Registro + ParamStore versionado con rollback
  └── (5 heredadas, envueltas sin reescribir)
      │
app/research/setup_evaluator.py     Autoridad estadística ÚNICA. Veredictos
                                    INSUFICIENTE/RUIDO/GANADOR/PERDEDOR, estados
                                    EXPLORACIÓN/PRODUCCIÓN/RETIRADO, checkpoints
                                    geométricos, Bonferroni por miradas repetidas
      │
app/agents/                         edge_validator (gate de admisión, delega en el
                                    evaluador), risk_manager, signal_agent
                                    (evalúa TODAS y rankea), expiry_selector,
                                    entry_timing, regime, multi_timeframe
      │
app/core/engine.py                  TradingEngine + evaluación SOMBRA
      │
app/research/backtester.py          Wrapper fino sobre el motor + walk-forward
app/services/improvement_engine.py  Diagnosticar→proponer→validar→filtrar→aplicar→revisar
```

### 3.3 Causalidad por construcción, no por disciplina

El backtester anterior tenía look-ahead porque **podía** tenerlo: recibía las
velas como listas y nada le impedía mirar hacia adelante.

Ahora el motor solo ve el mercado a través de `MarketFeed.candles()`, que
devuelve únicamente velas **cerradas** respecto a `feed.now()`. La información
futura no está al alcance del código, así que no se puede escribir por descuido.
En backtest el reloj es virtual; en vivo es el de pared. El mismo motor, los
mismos agentes, las mismas estrategias.

### 3.4 Evaluación sombra: cómo se resuelve el arranque en frío

Una binaria se liquida comparando el precio de entrada con el precio en un
instante futuro. Ese resultado **no depende de si se puso dinero**: queda
determinado por el mercado. Así que una señal no operada, resuelta contra el
precio real observado, es una observación estadísticamente válida del setup.

Esto resuelve dos problemas a la vez:

1. **La circularidad del arranque en frío.** Sin sombras, cada setup necesita 200
   operaciones *propias* para salir de exploración; como solo se opera el mejor
   candidato, las demás estrategias tardan semanas en acumular muestra. Con
   sombras, todas acumulan desde el primer ciclo (700+ observaciones por corrida
   frente a ~15 trades operados).
2. **La comparabilidad.** Tu `AGENTS.md` pide "comparar Estrategia A vs B vs C
   continuamente". Eso exige que las tres tengan muestra sobre el mismo periodo y
   el mismo mercado. Sin sombras solo se mide la que gana el ranking.

**Limitaciones, dichas explícitamente.** Una sombra mide *calidad de señal*, no
PnL realizado. No incluye riesgo de ejecución, cambios de payout entre señal y
entrada, ni el efecto de operar varias a la vez sobre el saldo. Por eso
`SetupRecord` cuenta `n` (todas) y `n_traded` (solo las operadas), y el
multiplicador de tamaño en PRODUCCIÓN **sube en rampa con `n_traded`**: 0.5× con
edge acreditado solo en sombra, 1.0× a las 50 observaciones operadas.

### 3.5 Hallazgo medido durante el desarrollo

Sobre 1.500 ciclos de mercado simulado, la frecuencia de señal de cada
estrategia:

| Estrategia | Frecuencia |
|---|---|
| `sr_bounce` | **48.73 %** |
| `breakout_direct` | 29.87 % |
| `trend_continuation` | 15.60 % |
| `mean_reversion` | 2.07 % |
| `engulfing_momentum` | 1.67 % |
| `breakout_retest` | 1.53 % |
| `liquidity_sweep_reversal` | 0.13 % |

`sr_bounce` dispara en **casi la mitad de los minutos**. No detecta lo que dice
detectar (un rechazo con mecha larga en un nivel S/R): una señal que aparece la
mitad del tiempo no es selectiva, es ruido con forma de señal.

Y como el `signal_agent` anterior devolvía *la primera* que disparaba, las demás
casi nunca llegaban a evaluarse. **No se puede medir lo que nunca se selecciona.**

Ese fue el motivo directo de reescribir `signal_agent` para evaluar todas y
rankear, y de añadir la evaluación sombra.

---

## 4. Verificación ejecutada

Nada de esto se da por bueno sin ejecutarlo.

### 4.1 La prueba decisiva: mercado nulo contra mercado con alpha

Se corrió el backtester completo (700 ciclos) sobre dos mercados:

| | **MERCADO NULO** | **MERCADO CON ALPHA** |
|---|---|---|
| Trades resueltos | 15 (7W/8L) | 15 (10W/5L) |
| Win rate | **46.67 %** | **66.67 %** |
| Expectancy | **−0.1367** | **+0.2333** |
| PnL | **−$20.50** | **+$35.00** |
| WR sombras | 48.98 % | 52.13 % |
| `EDGE_PROVEN` | False | False |
| Setups | 9 en exploración | 9 exploración + **1 RETIRADO** |

**Sobre un mercado con cero edge el sistema pierde dinero.** El backtester
anterior habría reportado un win rate por encima del break-even incluso aquí,
porque `won = current_candle.is_bullish` medía su propia entrada. Esa es la
prueba de que el look-ahead está realmente eliminado.

`EDGE_PROVEN=False` en ambos casos es correcto: n=15 está muy lejos de las 200
observaciones mínimas. Que el mercado con alpha gane 66.7 % **no** autoriza a
operarlo, y el sistema no lo autoriza.

### 4.2 Simulador: controles negativo y positivo

`SimConfig(alpha=0)` **no es un mercado nulo**: solo la deriva de régimen le da a
una sonda EMA20/50 un 59 % de acierto. Un control negativo de verdad necesita
también `regime_drift_scale=0.0`; de ahí `SimConfig.null_market()`.

Sonda EMA20/50, expiración 3 min, 4320 min, n=1419, payout 0.85:

| Configuración | WR | Expectancy |
|---|---|---|
| `null_market()` | **48.91 %** | **−0.0952** ← pierde, correcto |
| por defecto | 59.06 % | +0.0925 |
| `positive_control(alpha=0.2)` | 58.28 % | +0.0782 |
| `alpha=0.35` | 57.36 % | +0.0612 |
| `alpha=0.5` | 55.88 % | +0.0339 |

Persistencia de momentum a 1 min (debe crecer con alpha): nulo 50.9 %,
`alpha=0.10/0.20/0.30/0.50` → 55.0 / 55.7 / 56.1 / 59.8 %. **Monótono ✓**

### 4.3 El gate unificado, 0 incoherencias

Payout 0.85 → break-even 54.05 % → umbral **57.05 %** (break-even + margen de
seguridad 0.03). Se exige que la **cota inferior de Wilson** supere el umbral, no
el win rate puntual:

| wins/n | WR | Wilson-lo | Evaluador | Validador |
|---|---|---|---|---|
| 115/200 | 57.5 % | 0.5057 | ruido/exploración | rechazado |
| 130/200 | 65.0 % | 0.5816 | ganador/producción | aprobado + probado |
| 240/400 | 60.0 % | 0.5513 | ruido/exploración | rechazado |
| 300/400 | 75.0 % | 0.7053 | ganador/producción | aprobado + probado |
| 90/200 | 45.0 % | 0.3826 | perdedor/retirado | rechazado |
| 160/250 | 64.0 % | 0.5788 | ganador/producción | aprobado + probado |
| 600/1000 | 60.0 % | 0.5693 | ruido/exploración | rechazado |
| 50/60 | 83.3 % | 0.7197 | insuficiente | aprobado, **no probado** (arranque en frío) |

Fíjate en 240/400: un 60 % de acierto con 400 operaciones **se rechaza**. Su cota
inferior (0.5513) no supera el umbral de 0.5705. Ese es el filtro funcionando:
antes ese setup se habría promovido.

**Una sola autoridad estadística.** `SetupEvaluator` y `EdgeValidatorAgent` eran
dos autoridades sobre la misma pregunta y producían veredictos contradictorios
(riesgo de deadlock: un setup en PRODUCCIÓN cuyas operaciones el validador
bloquea). Ahora el evaluador decide y el validador es solo un gate de admisión
que **delega** en él. Verificado: 0 incoherencias en 8 casos.

### 4.4 Tests

`python3 -m pytest tests/ -q`:

| | Antes | Después |
|---|---|---|
| Pasan | 65 | **92** |
| Errores de colección | 7 | **0** |
| Fallos | 0 | **0** |

Los 7 errores eran `ModuleNotFoundError: openai` propagado por
`app/main.py → ai_auditor_agent → ai_provider`. Una dependencia opcional del
supervisor tumbaba la colección de tests que no tenían nada que ver con la IA.

### 4.5 Rendimiento

El simulador re-agregaba **todos** los ticks (hasta 400 k) en cada llamada a
`candles()`, y el motor pide M1, M5 y M15 por ciclo. Con agregación incremental:
**160 ms/ciclo → 1.4 ms/ciclo (114×)**. Un mes de M1 pasa de ~2 h a ~52 s, que es
lo que hace viable el walk-forward.

---

## 5. Lo que NO está hecho

Honestidad sobre el estado, que es lo que faltaba en este repo:

1. **`exnova_broker._EXNOVA_PATHS` sigue con carpetas personales hardcodeadas**
   (`Nueva carpeta (2)/bot-reversiones-iq-new`). El conector queda cableado para
   tu máquina, pero hay que poner rutas reales. Mientras tanto cae a PaperBroker
   — el fallo seguro — aunque el log diga lo contrario. **Ese mensaje debe
   corregirse antes de usarlo.**
2. **`app/main.py` no está recableado al `TradingEngine` nuevo.** Sigue el camino
   antiguo. El motor nuevo está probado vía `Backtester` y es lo que debe
   orquestar `main.py`.
3. **Sin dashboard operativo** sobre el motor nuevo (`app/dashboard/app.py` sigue
   apuntando al camino viejo y no bindea `0.0.0.0`).
4. **Ningún setup tiene edge demostrado con datos reales.** Todo lo medido aquí es
   sobre el simulador, que está etiquetado `DataSource.SIMULATOR` y **no pasa
   `EVIDENCE_SQL`**: ningún setup puede ascender a PRODUCCIÓN con esos datos.
   Para tener evidencia hace falta histórico CSV real (`scripts/fetch_history.py`)
   y luego forward test en paper.
5. `liquidity_sweep_reversal` y `engulfing_momentum` están probadas en imports,
   clamping de parámetros y frecuencia de señal, pero **no tienen validación
   estadística propia todavía** — necesitan muestra, que es justo lo que el
   sistema está diseñado para acumular.

---

## 6. Cómo se usa

### Arranque mínimo (sin dependencias opcionales)

```bash
pip install pyyaml numpy pandas python-dotenv requests
python3 -m pytest tests/ -q          # 92 pasan
```

### Backtest causal sobre histórico real

```python
from app.data.feed import ReplayFeed
from app.research.backtester import Backtester

feed = ReplayFeed.from_csv("data/history/", default_payout=0.85)
bt = Backtester(payout=0.85, cycle_seconds=60, stake=10.0)
report = bt.run_feed(feed, asset="EURUSD-OTC")
print(report.metrics["win_rate"], report.metrics["edge_proven"])
print(report.honest_note)          # se escribe SIEMPRE, también cuando va bien
```

El backtest usa una BD **en memoria** por defecto. Nunca escribe en la de vivo:
si lo hiciera, una corrida sobre datos simulados podría ascender setups a
PRODUCCIÓN y el bot empezaría a operarlos a tamaño completo basándose en ruido.

### Walk-forward

```python
wf = bt.walk_forward(feed, folds=4, train_ratio=0.6)
print(wf["verdict"])                        # el agregado OUT-OF-SAMPLE
print(wf["out_of_sample_aggregate"])
```

El `verdict` no tiene eufemismos: dice `SIN EDGE DEMOSTRADO` cuando la cota
inferior del IC no supera el break-even fuera de muestra, y reporta la
degradación media train→test (`overfit probable` por debajo de −0.05).

### Ciclo de mejora

```python
from app.services.improvement_engine import ImprovementEngine, ImprovementConfig
from app.strategies.registry import StrategyRegistry

engine = ImprovementEngine(
    registry=StrategyRegistry(),
    config=ImprovementConfig.from_app_config(),
    backtester_factory=lambda: Backtester(payout=0.85, cycle_seconds=60),
    feed_factory=lambda: ReplayFeed.from_csv("data/history/"),  # NUEVO cada vez
)
resultado = engine.cycle(max_proposals=6)
```

`feed_factory` debe ser una **fábrica**, no una instancia: el walk-forward
recorre varias ventanas y un feed ya consumido no se puede rebobinar (su reloj
virtual no retrocede por diseño; `ReplayFeed.fork()` crea un feed nuevo sobre el
mismo histórico ya preparado).

El ciclo devuelve `applied` y `rejected` **con el motivo de cada rechazo**. Un
motor de mejora que solo sabe aplicar no es un motor de mejora.

### Parámetros versionados y rollback

```python
from app.strategies.registry import ParamStore
store = ParamStore()
store.set_params("engulfing_momentum", {"adx_min": 25}, origin="human",
                 reason="...", metrics={...})     # -> nueva versión
store.rollback("engulfing_momentum")              # deshace el último cambio
```

`data/strategy_params.json` guarda `version`, `params` e `history` (con
`previous` y `metrics` por entrada). Escritura atómica vía `.tmp` + `replace()`.
Un fichero corrupto se aparta a `*.corrupto.<ts>.json` y se empieza de cero:
perder parámetros ajustados es malo, operar con una config leída a medias es
peor.

---

## 7. Lo que esto no es

No es un sistema que gana dinero. Es un sistema que **no puede engañarse a sí
mismo sobre si gana dinero**, que es el paso previo y necesario.

Dada la aritmética del §1.1, los datos de reguladores del §1.4 y el resultado
negativo publicado del §1.2, la expectativa razonable es que la mayoría de las
estrategias no tengan edge out-of-sample. Este sistema está construido para
**decirlo pronto, con números, y parar** — que es exactamente lo que el bot
anterior no pudo hacer durante 500 operaciones.

Si aparece un setup que sostiene la cota inferior de Wilson por encima del
break-even tras walk-forward, corrección por testeo múltiple y forward test en
paper sobre precios reales, entonces habrá algo que discutir. Hasta que esos
números existan, la respuesta correcta es no operar.

`AGENTS.md` ya lo decía: *"Si no hay un setup claro, NO OPERAR."* Ahora el código
lo cumple.
