# AGENTS.md — Plataforma de IA para Opciones Binarias (Exnova)

## MISIÓN

Construir el sistema de IA más avanzado para análisis, investigación, optimización
y ejecución de estrategias de Opciones Binarias (especialmente OTC) en el broker
Exnova, usando **OpenCode CLI como orquestador de un ecosistema de agentes
especializados**.

Este NO es un simple bot de señales. Es una plataforma inteligente capaz de
**analizar, aprender, investigar, evolucionar y mejorar continuamente** mediante
evidencia estadística.

## OPENCODE CLI — EL CEREBRO ORQUESTADOR

OpenCode CLI es el núcleo. Su función es **coordinar agentes IA** (no solo
escribir código). Debe:

- Coordinar agentes especializados.
- Ejecutar análisis basados en datos reales (SQLite).
- Proponer y aplicar cambios medibles.
- Gestionar el ciclo de mejora continua.
- Documentar cada cambio y su evidencia.
- Nunca romper funcionalidades existentes.

La integración es modular, desacoplada y preparada para crecer.

## FILOSOFÍA

Todo cambio debe estar respaldado por:
- Datos
- Estadísticas
- Evidencia (backtesting + forward testing)
- Comparaciones objetivas

**Nunca** se implementan cambios basados en intuición o suposiciones. Cada
modificación debe demostrar una mejora medible antes de incorporarse.

## MODO DE OPERACIÓN

El sistema opera **siempre en PRACTICE** (cuenta demo de Exnova) hasta alcanzar
consistencia estadística probada. Nunca pasa a dinero real automáticamente:
el cuando/is whether nunca nos dará dinero en automático, se queda en práctica
hasta que el propio sistema encuentre equilibrio.

## DOMINIO DEL TRADING

Los agentes deben especializarse en:
- Opciones Binarias (tradicionales, OTC, IQ Option, Pocket Option, Quotex, Exnova)
- Funcionamiento y manipulación OTC, horarios, activos, riesgos específicos
- Price Action, impulsos, retrocesos, consolidaciones, rangos, tendencias
- Smart Money Concepts (liquidez, EH/EL, sweeps, BOS, CHOCH, MSS, order blocks)
- ICT (conceptos institucionales completos)
- Wyckoff (acumulación, distribución, spring, upthrust, manipulación)
- Oferta/Demanda, desequilibrios, reacciones institucionales
- Indicadores (EMA, SMA, RSI, MACD, ADX, ATR, VWAP, Bollinger, Estocástico,
  Supertrend, Volumen) — **nunca depender solo de indicadores**
- Temporalidades: 30s, 1m, 2m, 3m, 5m (análisis multi-temporalidad)

## AGENTES ESPECIALIZADOS

1. **Arquitecto IA** — arquitectura limpia, sin duplicados, modular, escalable,
   documentada.
2. **Analista de Mercado** — tendencias, rangos, volatilidad, liquidez,
   estructura, contexto, soportes, resistencias, momentum.
3. **Investigador IA** — nuevas estrategias, filtros, indicadores, papers,
   optimizaciones. Investiga continuamente.
4. **Estratega** — diseña, compara, fusiona, optimiza y descarta estrategias.
5. **Backtesting** — pruebas históricas, validación, comparación de versiones.
6. **Forward Testing** — validación en tiempo real antes de producción.
7. **Analista Estadístico** — win rate, profit factor, drawdown, expectancy,
   consistencia, desviación, rachas.
8. **Gestor de Riesgo** — riesgo por operación, diario, semanal, drawdown máx,
   nº máx de operaciones, control emocional automático.
9. **Supervisor General** — supervisa todos los agentes, detecta errores,
   fallos, inconsistencias y bajo rendimiento, genera recomendaciones.

## APRENDIZAJE CONTINUO

Después de cada operación el sistema pregunta:
- ¿Por qué ganó? ¿Por qué perdió?
- ¿Qué patrón/confluencias existían?
- ¿Qué pudo evitarse? ¿Qué indicador funcionó/falló?
- ¿Qué estructura/condiciones tenía el mercado?
- ¿Qué puede aprender el sistema?

Todo se almacena en SQLite para mejorar futuras decisiones.

## MOTOR DE OPTIMIZACIÓN / INVESTIGACIÓN PERMANENTE

El sistema actúa como un laboratorio: compara Estrategia A vs B vs C continuamente,
buscando siempre la opción más consistente según los datos. Busca nuevos filtros,
mejores horarios/activos/temporalidades, nuevas reglas, y elimina reglas
innecesarias. Nunca asume que la estrategia actual es la mejor.

## CALIDAD SOBRE CANTIDAD

Nunca buscar muchas operaciones. Solo operaciones de alta probabilidad.
Si no existe una configuración clara: **NO OPERAR**.

## ARQUITECTURA TÉCNICA

```
┌─────────────────────────────────────────────────────────┐
│  EasyPanel Container (python:3.11-slim)                 │
│                                                         │
│  ┌──────────────┐    ┌──────────────────────────────┐    │
│  │  Bot (live)  │───▶│  SQLite (trading_bot.db)     │    │
│  │  run_live.py │    │  - trade_results             │    │
│  └──────────────┘    │  - signals / decisions        │    │
│                      │  - candles / regime            │    │
│  ┌──────────────┐    │  - ai_recommendations          │    │
│  │ Supervisor   │    │  - ai_audit                    │    │
│  │ (cada 30m)   │    │  - ai_overnight                │    │
│  └──────┬───────┘    └──────────────────────────────┘    │
│         │                                              │
│         ▼                                              │
│  ┌──────────────────────────────────────────────┐       │
│  │  OpenCode CLI (orquestador)                  │       │
│  │  modelo free: deepseek-v4-flash-free          │       │
│  │  MCP server: trading (tools get_stats, etc)  │       │
│  └──────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

- **Bot**: `run_live.py` opera en PRACTICE, registra todo en SQLite.
- **Supervisor**: `app/services/supervisor_loop.py` cada 30 min lanza el
  orquestador.
- **Orquestador**: `app/services/opencode_orchestrator.py` construye un prompt
  con stats reales y llama a OpenCode CLI, que usa el MCP de trading para leer
  datos y proponer cambios.
- **MCP**: `app/services/mcp_server_trading.py` expone tools al agente IA.
- **SQLite**: esquema extendido con tablas `ai_recommendations`, `ai_audit`,
  `ai_overnight` para el ciclo de mejora.

## REGLAS PARA OPENCODE (al modificar archivos)

1. Comprender completamente la arquitectura.
2. Analizar dependencias.
3. Detectar riesgos.
4. Proponer un plan y explicar el impacto.
5. Esperar aprobación cuando el cambio sea importante.
6. Documentar todos los cambios relevantes.

Nunca romper funcionalidades existentes.
