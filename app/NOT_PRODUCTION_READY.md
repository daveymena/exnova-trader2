# app/ — NO ESTA LISTO PARA PRODUCCION

Auditado el 2026-07-31. Este directorio es una arquitectura de agentes de
trading paralela e independiente de `bot/` (el sistema que realmente se
despliega, ver `docker-entrypoint.sh` en la raiz). Hoy `app/main.py` no lo
invoca nada en el despliegue Docker — solo se ejecuta la migracion de esquema
SQLite y, si se activa a mano, el supervisor de OpenCode
(`app/services/supervisor_loop.py`).

**No conectar `app/main.py` a ningun despliegue, y no activar
`SUPERVISOR_ENABLED=true` en `apply_change`, hasta corregir lo siguiente.**
Cada punto fue verificado leyendo el codigo completo, no es especulacion.

## Bugs criticos verificados

1. **Sizing ~100x sobredimensionado.** `app/agents/risk_manager_agent.py`
   comenta "0.5 = 0.5% of equity" pero el codigo usa `0.5` directo sin dividir
   entre 100. Con confianza tipica 0.5-0.95, el stake resultante es 35%-50%
   del equity **por operacion**, no 0.5%.

2. **Las operaciones se resuelven con una moneda al azar, no con el broker.**
   `app/main.py::_resolve_expired_trades()` usa `random.random() < 0.55`
   incluso cuando la orden se envio de verdad a Exnova. El sistema nunca sabe
   si gano o perdio dinero real.

3. **`Repository.get_historical_edge()` esta rota por `NameError`.**
   Llama a `wilson_lower_bound()`, funcion que no existe en ningun archivo de
   `app/`. Se rompe en cuanto hay evidencia repetida de la misma combinacion
   asset/strategy/direction/regimen/expiracion.

4. **El validador de edge ignora su propia cota de Wilson.**
   `EdgeValidatorAgent.validate()` usa el winrate puntual + margen fijo de 3
   puntos, no la cota inferior de Wilson que `repository.py` ya calcula (y que
   esta rota por el punto 3). Es exactamente el sesgo que sobreestima edge con
   muestra pequena que se identifico en el resto del proyecto.

5. **El minimo de muestra baja a 3 en modo practice**
   (`config.py: backtest_min_sample_size=100`, pero `edge_validator_agent.py`
   lo reduce a `3 if is_practice else 100`). Sin correccion por comparaciones
   multiples en ningun punto.

6. **`ExnovaBroker.buy()` pierde las ordenes reales aceptadas** — nunca las
   anade a `self.open_trades`, asi que `_resolve_expired_trades()` jamas las
   ve, jamas se guardan, y el balance interno nunca se actualiza.

7. **El contador de perdidas consecutivas recibe el dato invertido.**
   Para `PaperBroker`, el resultado se inicializa en `-amount` (siempre
   negativo al abrir) asi que cuenta perdidas que aun no ocurrieron. Para
   `ExnovaBroker` se inicializa en `0.0` (nunca `<0`) asi que el contador se
   resetea en cada trade real sin importar cuantas veces pierda de verdad — el
   corte de seguridad por rachas de perdidas no puede dispararse nunca en modo
   real/practice.

8. **Segunda integracion del broker no versionada.**
   `app/services/exnova_broker.py` busca `exnovaapi` en una carpeta personal
   fuera del repo (`Nueva carpeta (2)/bot-reversiones-iq-new`). Si no existe
   en el entorno de despliegue, cae a `PaperBroker` en silencio pero el log
   sigue diciendo "REAL MONEY TRADING ACTIVE".

9. **`trading_apply_change` (MCP) no tiene ningun freno estadistico.**
   La unica validacion antes de escribir en `data/ai_overrides.json` es un
   filtro de texto trivialmente evadible (`"real" in str(change) and
   "practice" not in str(change)`). No hay Wilson, no hay n minimo, no hay
   referencia a `bot/core/self_evaluator.py`. Ver ese archivo para el estandar
   que si cumple: min 200 observaciones, Wilson + Bonferroni/BH, retirada
   permanente con reapertura topada.

10. **La unica estrategia realmente en vivo (`sr_bounce.py`, via
    `signal_agent.py`) nunca fue backtesteada.** El backtester
    (`app/research/backtester.py`) solo evalua otras tres estrategias, y
    ademas tiene look-ahead bias: usa la misma vela para generar la senal y
    para decidir si "gano".

## Que SI esta bien disenado (para no tirar el trabajo)

El esquema SQLite (`app/data/schemas.py`) distingue evidencia real
(`resolution_source IN ('broker','candle')`) de simulada, con una migracion
de cuarentena que marca el historico previo como `'simulated'`. Es la idea
correcta — el problema es que nada en el codigo actual llega a producir una
fila con `resolution_source=BROKER` o `CANDLE`, asi que el filtro nunca recibe
datos que filtrar.

## Antes de reactivar esto

Usar `bot/core/self_evaluator.py` como referencia de lo que un gate
estadistico real necesita, y corregir los 10 puntos de arriba. El typo del
punto 9 relacionado (`propososals` en `opencode_orchestrator.py:204`) ya se
corrigio el 2026-07-31.
