# Observador de investigación para Exnova

Integrado en el contenedor existente del bot y desactivado por defecto. Para probar en EasyPanel configurar `RESEARCH_OBSERVER_ENABLED=true`, con `BROKER_NAME=exnova` y las credenciales Exnova existentes. Opcional: `RESEARCH_ASSETS=EURUSD-OTC,GBPUSD-OTC` y `RESEARCH_DATABASE_PATH=/app/data/research.db`. Verificar que `/app/data` sea persistente. No poner credenciales en Git.

El observador abre una segunda sesión PRACTICE de solo lectura y no envía órdenes. El bot principal conserva su configuración de ejecución. La segunda sesión podría interrumpir la primera según el broker: supervisar ambos procesos y, si ocurre, desactivarla. Revisar los logs `[OBSERVADOR]` para confirmar conexión y velas recientes. La API es comunitaria; el soporte de velas de 10 segundos no se ha verificado en vivo.

SQLite guarda velas cerradas de 10 segundos, señales experimentales y contactos M1. La comparación histórica `python lab/comparar_expiraciones.py velas.csv --payout 0.85 --output comparacion.json` requiere datos reales verificados, no ejecuta órdenes y usa precios hipotéticos. No incluye capturas, análisis visual ni aprendizaje autónomo y no constituye validación de rentabilidad. No hay purga automática: vigilar espacio de disco.
