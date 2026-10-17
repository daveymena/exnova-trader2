Audit inicial de Exnova Trader
Fecha: 17 octubre 2026

Codigo
- El replay barra a barra confundia el vencimiento: 1 minuto liquidaba al cierre de la vela siguiente despues de la entrada; la formula vectorizada tenia la misma desviacion. Corregido para entrar en la apertura siguiente y vencer al cierre del minuto exacto.
- El replay admitia temporalidades altas parcialmente formadas; ahora solo expone velas completas.
- Huecos de datos podian alargar vencimientos y completar muestras con expiraciones inexistentes. Se validan OHLC, frecuencia, vencimientos y alineacion de senales.
- Errores de estrategia se ocultaban como falta de senal; ahora fallan claramente para que los ensayos no cuenten datos sesgados.
- El reporte del playbook ahora calcula el limite de Wilson con correccion Bonferroni exacta para todas las comparaciones; separa entreno/prueba sin dejar cruzar el vencimiento, y admite historico CSV y parquet.

Verificacion
72 pruebas pasan, incluyendo nueve estrategias sobre escenarios sinteticos alcista, lateral y bajista y vencimientos 1, 3, 5 minutos. Son pruebas de funcionamiento, no evidencia de rentabilidad.
El comparador requiere velas reales en bot/data/history. El repositorio no contiene el historico; la rama de trabajo parte del commit main descargado desde GitHub.

Servidor EasyPanel
El monitor informa PRACTICE: 932 operaciones, 472 ganadoras, 457 perdedoras, 3 empate, 50.6% de aciertos y PnL acumulado -204.51. En los ultimos 500 registros consultables por el monitor: 253 ganadas, 244 perdidas, 3 empate; PnL -42.45. La tasa de acierto excluyendo empate es 50.9%. El payout observado en las ganadoras es aproximadamente 85.41%; su punto de equilibrio ronda 53.92%. El intervalo Wilson 95% de los ultimos 497 resultados decisivos incluye valores por debajo del equilibrio, asi que no demuestra edge.
La mayor muestra por patron en esos ultimos 500 es pin_bar_bearish (68/117=58.1%, PnL +11.87), pero el intervalo 95% (49.1%-66.7%) incluye el equilibrio; no demuestra una ventaja. Resultado del monitor no expone IDs de orden ni fuente de resolucion para verificar cada cierre.
El codigo live tambien convierte falta de confirmacion del broker en perdida ficticia, tanto en la ruta principal como en una ruta de operaciones virtuales. Por tanto, esos recuentos no son evidencia broker-a-broker hasta auditar la confirmacion de cada orden.

Acceso al servidor
La pagina publica del monitor responde y declara PRACTICE; el inicio de sesion de EasyPanel rechazo las dos variantes provistas. Tras subir los cambios a main, el monitor reporto un heartbeat nuevo y el log mostro que run_live.py estaba evaluando señales en PRACTICE. El ciclo consultado tenia cero operaciones nuevas. No se cambiaron parametros de la cuenta ni se emitieron ordenes desde esta sesion.

Para descargar historico desde terminal EasyPanel, en el contenedor del servicio que tenga el repositorio:
python scripts/fetch_history.py --assets EURUSD-OTC,GBPUSD-OTC,AUDJPY-OTC,US30-OTC,ATOMUSD-OTC --days 7 --timeframes 60
Luego comprimir bot/data/history y adjuntarlo a esta conversacion; nunca adjuntar .env ni datos de acceso. Si el contenedor no incluye el repositorio scripts/, descargar por separado las velas a CSV en bot/data/history.

Pendiente: con velas recuperadas, ejecutar walk-forward de todas las estrategias y expiraciones con el payout real medido; separar OTC y mercados abiertos, corregir comparaciones multiples, reportar expectancy y drawdown fuera de muestra; comparar despues con forward test de practice y confirmaciones reales.

Incidente observado el 17 de octubre de 2026
El endpoint /api/health responde, pero /api/status da bot_alive=false y el heartbeat lleva mas de ocho horas sin actualizarse. El ultimo log dice que se perdio el WebSocket de Exnova; el watchdog detecto 601 s sin latido y termino run_live.py con rc=3.
La causa de que no se recuperara esta en docker-entrypoint.sh: el entrypoint activa `set -e` y ejecutaba run_live.py como comando simple dentro del subshell del bucle. Al devolver rc=3, errexit terminaba el propio supervisor antes de escribir el registro de reinicio o volver a lanzar el bot. Corregido localmente ejecutando el proceso dentro de una condicion `if`, capturando su codigo y continuando el bucle.
Verificado con `bash -n` y una simulacion de dos ciclos que devuelve rc=3; el bucle sobrevive. Subido a main en a5a72b41d3c4ee2043a6f085d58736c785a0db97. Despues del push, el heartbeat avanzo al ciclo 30 y el registro mostro actividad del bot en PRACTICE; el monitor reporto bot_alive=true.
