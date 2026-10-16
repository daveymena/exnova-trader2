# Qué se midió contra datos reales de mercado

## El problema de fondo

Todo el edge medido hasta ahora venía de **datos sintéticos generados por
nosotros mismos**. Un 90.8% de acierto sobre velas que nosotros fabricamos
solo demuestra que el código hace lo que quisimos: no demuestra nada sobre el
mercado. Esta es la trampa clásica del backtest, y es la razón por la que el
bot podía parecer ganador sin haber operado nunca.

## Qué se intentó y qué se encontró

### 1. Conectar a Exnova: imposible desde este entorno

El camino estaba roto en dos sitios, y los dos se arreglaron:

- `ExnovaBroker` buscaba la librería `exnovaapi` en `Nueva carpeta (2)/bot-reversiones-iq-new`
  y `~/Videos/Nueva carpeta (2)/...`, rutas de la máquina del desarrollador
  original. La librería **sí está** en el repo, en `bot/exnovaapi/`, pero nadie
  la miraba. Con `ExnovaAPI = None`, `connect()` devolvía `False` y el bot
  caía **siempre** a `PaperBroker`: ponías credenciales correctas y seguía
  operando en papel sin avisarte.
- El stake por operación era el **50% de la cuenta**. El comentario decía
  `0.5 = 0.5% of equity`, pero el valor se usaba como fracción, donde `0.5`
  es 50%. El dry run lo destapó: ejecutaba a $400 sobre $10.000. Ahora hay
  tope del 0.5% y un duro de $50 por operación.

Con eso arreglado, la conexión sigue fallando: el sandbox solo tiene salida a
GitHub/npm/PyPI. `github.com` completa el handshake TLS; `ws.trade.exnova.com`
lo corta el proxy (`SSLZeroReturnError`). **No es la contraseña ni el código.**
Hay que ejecutar `scripts/probar_broker_real.py` en una máquina con salida a
Exnova.

### 2. Conseguir velas reales: sí se pudo

`raw.githubusercontent.com` también está bloqueado, pero `codeload.github.com`
no. Con *sparse checkout* se bajaron datasets públicos de velas OHLC reales
de EURUSD sin traerse los 146MB de repo completos:

| Dataset | Velas | Rango |
|---|---|---|
| `simonnmarket/OMEGA_OS_Kernel` M1 | 4.317 | 5 días (feb–mar 2026) |
| `simonnmarket/OMEGA_OS_Kernel` H1 | 15.686 | 3 años (2023–2026) |
| `getdata-finance/eurusd-1m-ohlcv-forex-historical-data` M1 | **189.634** | **6 meses (mar–sep 2026)** |

Todo entra por `scripts/importar_velas_reales.py`, que normaliza cualquier CSV
de velas al formato del repo y valida la estructura OHLC.

### 3. La medición sobre H1 quedó invalidada por método

Auditar con velas H1 midiendo "3 barras" como resultado era medir el
resultado a **3 horas**, cuando el bot opera a 3 minutos. Esa medición no es
válida y **no se usa**. Se descarta.

Lo que sí es válido es la medición sobre **velas M1**, donde 3 barras son
3 minutos de verdad.

## Limitación que sigue en pie

Estas velas son del mercado spot real de divisas, **no las velas OTC del
broker de binarias**. Son un proxy honesto —mil veces mejor que sintético—
pero no idéntico. El edge que sobreviva aquí es una hipótesis sólida que
**hay que confirmar en PRACTICE contra el broker** antes de operar.
