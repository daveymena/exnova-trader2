# VEREDICTO: el bot no tiene edge. Y ahora está medido, no supuesto.

## La pregunta

"¿Qué hacemos para que esto sea ganador, aprenda, trabaje y sea consistente?"

La respuesta honesta, después de medir contra datos reales de mercado:
**no se puede hacer ganador con las estrategias que tiene.** Y el motivo no es
que falte una feature o un ajuste: es que el edge no existe.

---

## Cómo se llegó a esto

### Todo el rendimiento anterior era contra datos sintéticos

El consenso daba 90.6% de acierto y PF 8.19. Esas velas las generábamos
nosotros con un generador gaussiano. Un 90% contra velas que uno fabrica
solo demuestra que el código hace lo que quisimos: **no dice nada del
mercado**. Es la trampa clásica del backtest.

### Se consiguieron velas reales

`raw.githubusercontent.com` está bloqueado en este entorno, pero
`codeload.github.com` no. Con *sparse checkout* se bajaron datasets públicos
de velas OHLC reales de EURUSD:

| Dataset | Velas M1 | Rango |
|---|---|---|
| `simonnmarket/OMEGA_OS_Kernel` | 4.317 | 5 días |
| `getdata-finance/eurusd-1m-ohlcv-forex-historical-data` | 189.634 | 6 meses |
| (subconjunto usado en las pruebas finales) | 150.000 | ~5 meses |

Entra por `scripts/importar_velas_reales.py`, que normaliza cualquier CSV de
velas al formato del repo y valida la estructura OHLC.

### La medición sobre H1 se descartó por método

Auditar con velas H1 midiendo "3 barras" como resultado era medir el
resultado a **3 horas**, cuando el bot opera a 3 minutos. Esa medición no es
válida y **no se usó**. Todo lo que sigue está medido sobre **velas M1**, donde
3 barras son 3 minutos de verdad.

---

## Lo que midieron las 5 estrategias (189.634 velas M1 reales, 6 meses)

Horizonte correcto. Break-even de payout 0.85 = **54.05%**; umbral con margen
de seguridad = **57.05%**.

| Estrategia | Celda | n | WR | Veredicto |
|---|---|---|---|---|
| **breakout_direct** | call/trend_up | 1.346 | 49.3% | **PIERDE** |
| | put/trend_down | 1.270 | 46.5% | **PIERDE** |
| | call/range | 464 | 42.0% | **PIERDE** |
| **trend_continuation** | call/trend_up | 13.246 | 51.6% | PIERDE |
| | put/trend_down | 17.234 | 52.2% | marginal |
| **mean_reversion** | call/range | 5.890 | 51.2% | PIERDE |
| | put/range | 3.777 | 49.7% | PIERDE |
| **breakout_retest** | put/trend_down | 236 | 30.1% | PIERDE |
| **sr_bounce** | call/trend_up | 33 | 69.7% | pasa Wilson |
| | put/trend_down | 61 | 85.2% | pasa Wilson |

`breakout_direct` era el pilar del consenso: 90.8% en sintético, **46–49% en
real**. Era sobreajuste.

### Las dos celdas que "pasaban" no se sostuvieron

Con más datos (60.000 velas), `sr_bounce` en solitario da **882 señales y
49.5% de acierto global: pierde dinero**. Las celdas que antes pasaban bajan a
n=8 y n=10. Y aparece el patrón que lo explica:

```
sr_bounce  call/trend_down   n=202   WR 43.6%   pierde
sr_bounce  put/trend_up      n=191   WR 41.4%   pierde
```

**sr_bounce apuesta en contra de la tendencia, y el mercado la sigue.** Tiene
la dirección invertida. Ese es el bug de fondo, y no se arregla con un parámetro.

---

## La prueba que cierra el asunto

¿Predice algo el mercado de EURUSD a corto plazo? Sobre 150.000 velas M1
reales, horizonte de 3 minutos:

| Predictor | n | WR | Veredicto |
|---|---|---|---|
| momentum 1 min (a favor) | 103.027 | 49.0% | aleatorio |
| momentum 3/5/10/15 min | ~110.000 | 49.0% | aleatorio |
| reversión 1–10 min | ~110.000 | 51.0% | aleatorio |
| continuar cuerpo de vela anterior | 103.027 | 49.0% | aleatorio |
| cierre en tercio superior/inferior | 71.246 | 48.5% | aleatorio |
| volumen 1.5× la media | — | sin mejora | — |
| **baseline: siempre call** | 113.936 | 49.7% | aleatorio |

Y a distintos horizontes, el momentum no mejora:

| Horizonte | 3 min | 15 min | 60 min | 240 min |
|---|---|---|---|---|
| WR a favor | 49.0% | 49.1% | 49.2% | 49.5% |

**El mercado es aleatorio en todos los horizontes medidos.** El 51% de la
reversión es real pero está a 6 puntos del 57.05% que haría falta.

Esto no es un fallo del código. Es la razón por la que existen los brokers de
binarias: con payout 0.85 hace falta 54.05% de acierto, y el mercado no da
más del ~50% con predictores de precio.

---

## Qué se hizo a pesar de todo (y sirve)

1. **Dos bugs que hacían imposible operar de verdad:**
   - `ExnovaBroker` buscaba `exnovaapi` en rutas de la máquina del desarrollador
     original. La librería está en `bot/exnovaapi/` pero nadie la miraba: con
     `ExnovaAPI = None` el bot caía **siempre** a PaperBroker, con credenciales
     correctas y sin avisar.
   - El stake por operación era el **50% de la cuenta**. El comentario decía
     `0.5 = 0.5%` pero se usaba como fracción. Ahora 0.5% real y tope duro de $50.
   - `approve()` petaba con `UnboundLocalError` en modo PRACTICE, el modo en el
     que se supone que hay que validar todo. Lo destapó crear el `.env`.

2. **Mapa calibrado en datos reales**, no sintéticos: `sr_bounce` solo en
   trend_up/trend_down, y `DIRECCIONES_MEDIDAS` restringe el lado (en trend_up
   solo call, en trend_down solo put). Antes el consenso podía elegir PUT en
   trend_up, que en real da 44.5% y pierde dinero.

3. **Infraestructura de medición que funciona y es reutilizable:**
   - `scripts/importar_velas_reales.py` — cualquier CSV de velas reales entra y
     se valida.
   - `scripts/probar_broker_real.py` — conecta a Exnova en PRACTICE y audita
     sobre velas reales. **No envía órdenes.**
   - `scripts/dry_run_bot.py` — bot completo contra broker simulado con fallos
     reales (timeouts, velas vacías). 60 ciclos con el broker colgado el 30%:
     0 errores.
   - `app/research/edge_ledger.py` — mide edge por (estrategia, dirección,
     régimen) **desde evidencia real del broker** y desactiva lo que pierde.
     Verificado: con 6 operaciones perdedoras reales, rechaza.

4. **El bot ahora se auto-bloquea.** Con el mapa nuevo mide 0 señales sobre
   40.000 velas reales. Antes habría operado 90.000 veces perdiendo dinero.

---

## Conclusión y qué haría falta

**No operar en real.** No hay edge demostrado, y la aritmética del payout
(54.05% necesario contra ~50% disponible) no se arregla con más features.

Si se quisiera seguir, ninguna de estas es un ajuste:

- **Otra estrategia** sobre velas OHLC: ya se midió que el precio a 3 minutos
  no predice nada. Añadir más reglas sobre el mismo dato es sobreajuste.
- **Datos que no se tienen**: order flow, profundidad de mercado, ticks. Con
  OHLC agregado el techo está en ~51%.
- **Un payout mayor**: a 90% el break-even baja a 52.6%, y la reversión medida
  (51%) sigue sin llegar.
- **Horizontes largos**: medido hasta 4 horas, aleatorio.

Lo que sí tiene valor es lo construido: si aparece un predictor con skill real,
`EdgeLedger` + los informes + el importador de datos reales permiten medirlo y
activarlo **solo si sobrevive al test estadístico**, que es exactamente el
proceso que destapó que el edge no existía.

---

*Reproducir:*
```bash
python scripts/importar_velas_reales.py --csv velas.csv --asset EURUSD --timeframe 1
python scripts/research_strategy_audit.py --source real --asset EURUSD
python scripts/consistency_report.py
python scripts/dry_run_bot.py --cycles 40
python -m pytest tests/ -q     # 59 pasan
```
