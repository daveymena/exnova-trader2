# 🚀 CONFIGURACIÓN PARA AMBAS PLATAFORMAS

## ✅ ESTADO ACTUAL

### **Local (Windows):**
```
✅ Bot ejecutándose: bot_que_opera.py
✅ Conectado a Exnova PRACTICE
✅ Balance: $9,771.21
✅ Operaciones ejecutándose automáticamente
```

### **Easypanel (Servidor):**
```
⏳ Pendiente de configurar
```

---

## 📋 CONFIGURACIÓN PARA EASYPANEL

### **1. Variables de Entorno Completas:**

```env
# ============= BROKER =============
BROKER_NAME=exnova
ACCOUNT_TYPE=PRACTICE

# Credenciales Exnova
EXNOVA_EMAIL=daveymena16@gmail.com
EXNOVA_PASSWORD=6715320Dvd.

# ============= TRADING =============
DEFAULT_ASSET=EURUSD-OTC
CAPITAL_PER_TRADE=1
EXPIRATION_TIME=60
TIMEFRAME=60

# ============= RISK MANAGEMENT =============
MAX_MARTINGALE=3
STOP_LOSS_PERCENT=20
TAKE_PROFIT_PERCENT=10

# ============= AI/LLM =============
USE_LLM=True
USE_GROQ=False

# ============= IA - GITHUB MODELS =============
# Obtener token en: https://github.com/settings/tokens
GITHUB_TOKEN=tu_github_token_aqui
GITHUB_MODEL=gpt-4o-mini

# ============= IA - OLLAMA EASYPANEL =============
VITE_OLLAMA_BASE_URL=https://biblia-ollama.ginee6.easypanel.host
VITE_OLLAMA_MODEL=minimax-m2.7:cloud
OLLAMA_CUSTOM_URL=https://biblia-ollama.ginee6.easypanel.host
OLLAMA_CUSTOM_MODEL=minimax-m2.7:cloud

# ============= IA - OLLAMA LOCAL =============
OLLAMA_LOCAL_URL=http://localhost:11434
OLLAMA_LOCAL_MODEL=glm-5:cloud

# ============= HORARIO DE OPERACIÓN =============
TRADING_START_HOUR=0
TRADING_END_HOUR=23
TRADING_END_MINUTE=59
MIN_VOLATILITY_TO_START=0.05

# ============= CONFIGURACIÓN ADICIONAL =============
COOLDOWN_SEGUNDOS=300
EXPIRATION_MIN_MINUTES=3
EXPIRATION_MAX_MINUTES=7
MIN_VELAS_CONFIRMACION=2
MAX_VELAS_CAIDA_LIBRE=4
```

---

## 🚀 PASOS PARA EASYPANEL

### **1. Subir a GitHub:**

```bash
# Agregar archivos necesarios
git add bot_que_opera.py config.py core/ data/ strategies/
git add requirements-easypanel.txt Dockerfile.easypanel .gitignore

# Commit
git commit -m "Bot listo para Easypanel"

# Push
git push origin main
```

### **2. Crear requirements-easypanel.txt:**

```txt
requests>=2.31.0
pandas>=2.0.0
numpy>=1.24.0
websocket-client>=1.6.0
python-dotenv>=1.0.0
colorlog>=6.7.0
```

### **3. Crear Dockerfile.easypanel:**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
COPY requirements-easypanel.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY config.py .
COPY bot_que_opera.py bot.py
COPY core/ core/
COPY data/ data/
COPY strategies/ strategies/
ENV PYTHONUNBUFFERED=1
ENV ACCOUNT_TYPE=PRACTICE
CMD ["python", "bot.py"]
```

### **4. Configurar en Easypanel:**

1. Crear nuevo servicio
2. Seleccionar "Git Repository"
3. URL: `https://github.com/daveymena/exnova-trader2.git`
4. Branch: `main`
5. Build: `Dockerfile.easypanel`
6. Agregar variables de entorno (las de arriba)

---

## ⚠️ IMPORTANTE

### **Para evitar conflictos:**

**NO ejecutar ambos bots al mismo tiempo en la misma cuenta:**
- ❌ Si Easypanel está activo, detener el local
- ❌ Si local está activo, no activar Easypanel

### **Recomendación:**

**Usar Easypanel como principal:**
- ✅ Corre 24/7 sin interrupciones
- ✅ No depende de tu PC
- ✅ Sistema de IA disponible

**Usar local solo para pruebas:**
- ✅ Probar nuevas configuraciones
- ✅ Debugging
- ✅ Desarrollo

---

## 📊 COMPARACIÓN

| Característica | Local | Easypanel |
|----------------|-------|-----------|
| Disponibilidad | Solo cuando PC encendida | 24/7 |
| IA Ollama | ✅ Local | ✅ Easypanel |
| IA GitHub | ✅ | ✅ |
| Estabilidad | Depende de PC | Alta |
| Velocidad | Más rápido | Ligeramente más lento |

---

## 🎯 RECOMENDACIÓN FINAL

**Configurar Easypanel como principal:**

1. Subir código a GitHub
2. Configurar en Easypanel
3. Agregar variables de entorno
4. Deploy
5. Monitorear logs
6. Detener bot local

**¿Quieres que te ayude a subir a GitHub ahora?**