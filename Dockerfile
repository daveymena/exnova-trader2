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
    gcc g++ git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Copiar requirements primero (para cachear mejor)
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copiar código del bot (estructura completa)
COPY bot/ ./bot/
COPY run_live.py ./run_live.py
COPY .env.example ./.env.example

# 3. Crear directorios persistentes
RUN mkdir -p /app/bot/data /app/bot/logs /app/bot/models /app/logs

# 4. Variables de entorno (sobreescribir en EasyPanel)
# ⚠️  Para cuenta REAL: ACCOUNT_TYPE=REAL y REAL_ACCOUNT_CONFIRMED=true
ENV BROKER_NAME="exnova" \
    ACCOUNT_TYPE="PRACTICE" \
    REAL_ACCOUNT_CONFIRMED="false" \
    EXNOVA_EMAIL="" \
    EXNOVA_PASSWORD="" \
    OPENCODE_API_KEY="" \
    OPENCODE_BASE_URL="https://tecnovariedades-provedor-ia.er7iaf.easypanel.host/v1" \
    OPENCODE_MODEL_FAST="opencode/deepseek-v4-flash-free" \
    OPENCODE_MODEL_DEEP="opencode/qwen3.6-plus-free" \
    GITHUB_TOKEN="" \
    MIN_CONFIDENCE="0.65" \
    MAX_CONSEC_LOSSES="4" \
    COOLDOWN_AFTER_LOSS="300" \
    MIN_BETWEEN_TRADES="180" \
    LOG_LEVEL="INFO"

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os,time; f='/app/bot/data/learning_progress.json'; \
        exit(0) if os.path.exists(f) and time.time()-os.path.getmtime(f)<300 else exit(1)"

CMD ["python", "-u", "bot/run_live.py"]
