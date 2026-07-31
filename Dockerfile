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
    gcc g++ git curl ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Instalar OpenCode CLI (orquestador de agentes IA).
# El flag de supervisión free usa OPENCODE_ZEN_API_KEY (registro gratis en opencode.ai).
RUN npm install -g @anthropic-ai/opencode 2>/dev/null || npm install -g opencode 2>/dev/null || echo "WARN: opencode CLI no instalado (se usara AUTO_SUPERVISOR_OFFLINE)"

WORKDIR /app

# 1. Copiar requirements primero (para cachear mejor)
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copiar código del bot + app + supervisor + opencode config
COPY bot/ ./bot/
COPY app/ ./app/
COPY run_live.py ./run_live.py
COPY opencode.json ./opencode.json
COPY AGENTS.md ./AGENTS.md
COPY docker-entrypoint.sh ./docker-entrypoint.sh
COPY .env.example ./.env.example

# 3. Crear directorios persistentes
RUN mkdir -p /app/bot/data /app/bot/logs /app/bot/models /app/logs /app/data
RUN chmod +x /app/docker-entrypoint.sh

# 4. Variables de entorno (sobrescribir en EasyPanel)
# ⚠️  Para cuenta REAL: ACCOUNT_TYPE=REAL y REAL_ACCOUNT_CONFIRMED=true
ENV BROKER_NAME="exnova" \
    ACCOUNT_TYPE="PRACTICE" \
    REAL_ACCOUNT_CONFIRMED="false" \
    EXNOVA_EMAIL="" \
    EXNOVA_PASSWORD="" \
    OPENCODE_API_KEY="" \
    OPENCODE_ZEN_API_KEY="" \
    OPENCODE_BASE_URL="https://opencode.ai/zen/v1" \
    OPENCODE_MODEL="opencode/deepseek-v4-flash-free" \
    OPENCODE_MODEL_FAST="opencode/deepseek-v4-flash-free" \
    OPENCODE_MODEL_DEEP="opencode/qwen3.6-plus-free" \
    GITHUB_TOKEN="" \
    MIN_CONFIDENCE="0.65" \
    MAX_CONSEC_LOSSES="4" \
    COOLDOWN_AFTER_LOSS="300" \
    MIN_BETWEEN_TRADES="180" \
    LOG_LEVEL="INFO" \
    SUPERVISOR_ENABLED="true" \
    SUPERVISOR_INTERVAL_SECONDS="1800" \
    OPENCODE_TIMEOUT="300"

EXPOSE 8000

HEALTHCHECK --interval=120s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import os,time; f='/app/bot/data/learning_progress.json'; \
        exit(0) if os.path.exists(f) and time.time()-os.path.getmtime(f)<600 else exit(1)"

CMD ["/app/docker-entrypoint.sh"]
