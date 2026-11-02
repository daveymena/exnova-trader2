# Laboratorio experimental: retroceso a favor en 10 segundos

Este módulo es independiente, sin conexión al broker y sin envío de órdenes. Recibe velas OHLC reales de un solo activo en CSV (timestamp,open,high,low,close), ordenadas y separadas exactamente 10 segundos. El timestamp es la hora de apertura en Unix UTC o ISO 8601 con zona. Los datos deben proceder del broker y verificarse antes de usarlos.

Ejecutar desde la raíz:

    python lab/retroceso_lab.py velas.csv --payout 0.85 --output informe.json
    python -m unittest discover -s lab -v

El payout es una hipótesis fija expresada como decimal, no un payout histórico verificado. El resultado usa apertura de la siguiente vela tras la señal y cierre 180 segundos después; no simula ejecución real, latencia, diferencias de cotización ni liquidación de IQ Option. Los empates cuentan cero de manera provisional. Una posición por activo y pausa de seis velas después del vencimiento.

La EMA usa inicialización en el primer cierre; ATR es EMA de 14 rangos verdaderos. Para operacionalizar el impulso, la versión experimental usa el rango de las 12 velas anteriores al retroceso; tamaño medio de cuerpos a favor versus cuerpos del retroceso. Estas son aproximaciones, no equivalen necesariamente al detector mencionado en el PDF. La estructura compara dos pivotes locales confirmados (dos velas a cada lado) en una ventana de 90 velas; es una definición experimental. Después de una pérdida bloquea el cambio de dirección durante 12 velas a partir de la resolución; después de tres pérdidas consecutivas detiene el laboratorio. No existe conexión al flujo de señales o al bot. La igualdad de condiciones con una entrada manual no está demostrada.

No utilizar el informe de este laboratorio como prueba de rentabilidad. Falta validar con datos reales de 10 segundos, cotejar entradas históricas individuales, validar la definición de pivotes contra las entradas manuales, probar ventanas separadas cronológicamente, verificar precios de liquidación y hacer seguimiento prospectivo en práctica. No habilita operaciones reales o demo.

## Comparación exploratoria de expiraciones

    python lab/comparar_expiraciones.py velas.csv --payout 0.85 --output comparacion.json

Compara 60, 120, 180 y 300 segundos para cada señal causal del detector, con entrada hipotética en la apertura siguiente. Separa cronológicamente desarrollo y evaluación final y excluye señales que crucen el límite. Los resultados pueden solaparse: no equivalen a operaciones independientes, no aplican las pausas del simulador, no incluyen latencia, ni precios de ejecución, payout histórico o liquidaciones confirmadas. El payout es un supuesto y los empates se tratan como reembolso. No elegir el mejor resultado de la muestra final y llamarlo validado. No abre órdenes ni cambia la estrategia.
