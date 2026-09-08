# ─────────────────────────────────────────────────────────────────────────────
# Exnova Trading Bot v5.0 — Dockerfile para EasyPanel
# Motor IntelligentEngine + IA de razonamiento continuo
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# OpenCode CLI (orquestador del supervisor) NO se instala: pesa mucho y el
# supervisor esta desactivado por defecto (SUPERVISOR_ENABLED=false). El bot
# llama al puente IA de OpenCode via REST (requests -> OPENCODE_BASE_URL),
# sin necesidad del CLI. Si se activa el supervisor, poner AUTO_SUPERVISOR_OFFLINE
# o instalar el CLI en una etapa posterior.

WORKDIR /app

# 1. Copiar requirements primero (para cachear mejor)
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copiar código del bot + app + supervisor + opencode config
# run_live.py vive en bot/ (COPY bot/ lo incluye). Ya no existe una copia en
# la raiz: habia dos run_live.py divergentes (distintos parametros de riesgo
# para cuenta REAL) y el Dockerfile ejecutaba uno mientras se desarrollaba el
# otro. Se fusionaron en bot/run_live.py, que es ahora el unico canonico.
COPY bot/ ./bot/
COPY app/ ./app/
COPY opencode.json ./opencode.json
COPY docker-entrypoint.sh ./docker-entrypoint.sh
COPY .env.example ./.env.example
# EasyPanel genera este archivo desde sus variables de entorno. No existe en
# Git; se copia solo durante el build del servicio para que entrypoint.sh y
# los procesos Python puedan cargarlo desde /app/.env.
RUN touch /app/.env

# 3. Crear directorios persistentes
RUN mkdir -p /app/bot/data /app/bot/logs /app/bot/models /app/logs /app/data
RUN chmod +x /app/docker-entrypoint.sh

# 4. Variables de entorno (sobrescribir en EasyPanel)
# ⚠️  Para cuenta REAL: ACCOUNT_TYPE=REAL y REAL_ACCOUNT_CONFIRMED=true
ARG DEMO_ZONE_EXECUTION=false
ARG EXNOVA_EMAIL=""
ARG EXNOVA_PASSWORD=""
ARG ACCOUNT_TYPE="PRACTICE"
ARG RESET_STATE=false
ARG DASHBOARD_TOKEN=""
ARG OPENCODE_API_KEY=""
ARG IMPROVEMENT_MODEL="hy3-free"
ARG IMPROVEMENT_MODEL_FAST="nemotron-3.5-lightning-free"
ARG IMPROVEMENT_MODEL_FALLBACK="mimo-v2.5-free"
ARG IMPROVEMENT_ENABLED="true"
ARG IMPROVEMENT_BATCH_TRADES="20"
ARG IMPROVEMENT_BATCH_MIN_MINUTES="15"
ARG IMPROVEMENT_MIN_EVIDENCE="200"
ARG GIT_SHA=""

ENV BROKER_NAME="exnova" \
    ACCOUNT_TYPE="PRACTICE" \
    REAL_ACCOUNT_CONFIRMED="false" \
    EXNOVA_EMAIL="" \
    EXNOVA_PASSWORD="" \
    OPENCODE_API_KEY="" \
    OPENCODE_ZEN_API_KEY="" \
    OPENCODE_BASE_URL="https://opencode.ai/zen/v1" \
    OPENCODE_MODEL="hy3-free" \
    OPENCODE_MODEL_FAST="nemotron-3.5-lightning-free" \
    OPENCODE_MODEL_DEEP="hy3-free" \
    DEMO_ZONE_EXECUTION="false" \
    RESET_STATE="false" \
    DASHBOARD_TOKEN="" \
    IMPROVEMENT_MODEL="hy3-free" \
    IMPROVEMENT_MODEL_FAST="nemotron-3.5-lightning-free" \
    IMPROVEMENT_MODEL_FALLBACK="mimo-v2.5-free" \
    IMPROVEMENT_ENABLED="true" \
    IMPROVEMENT_BATCH_TRADES="20" \
    IMPROVEMENT_BATCH_MIN_MINUTES="15" \
    IMPROVEMENT_MIN_EVIDENCE="200" \
    ASSET_SCAN_LIST="AUDUSD-OTC,AMAZON-OTC,GOOGLE-OTC" \
    FIXED_STAKE="1" \
    MAX_TRADES_PER_HOUR="4" \
    MAX_TRADES_PER_DAY="12" \
    DAILY_LOSS_LIMIT="10" \
    GITHUB_TOKEN="" \
    MIN_CONFIDENCE="0.65" \
    MAX_CONSEC_LOSSES="4" \
    COOLDOWN_AFTER_LOSS="300" \
    MIN_BETWEEN_TRADES="180" \
    LOG_LEVEL="INFO" \
    SUPERVISOR_ENABLED="false" \
    SUPERVISOR_INTERVAL_SECONDS="1800" \
    OPENCODE_TIMEOUT="300"
# SUPERVISOR_ENABLED por defecto en "false": este supervisor puede APLICAR
# cambios de codigo de forma autonoma (ver app/services/mcp_server_trading.py).
# Hasta que su ruta de apply_change tenga el mismo freno estadistico que
# bot/core/self_evaluator.py (Wilson + minimo de observaciones), no debe
# arrancar solo porque se despliegue el contenedor. Activar explicitamente
# con SUPERVISOR_ENABLED=true en EasyPanel solo tras revisar ese freno.

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/api/health" > /dev/null || exit 1

CMD ["/app/docker-entrypoint.sh"]
