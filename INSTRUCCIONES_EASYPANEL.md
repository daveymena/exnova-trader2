# 🚀 INSTRUCCIONES FINALES PARA EASYPANEL

## ⚠️ PROBLEMA CON GITHUB

El push fue bloqueado porque el token secreto estaba en el historial de commits.
Se hizo un reset al commit anterior, pero los archivos nuevos se perdieron.

---

## 📋 ARCHIVOS QUE NECESITAS PARA EASYPANEL

### **Bot Principal (usar el que ya existe):**
```
bot_con_ia.py  ← Este archivo existe
```

### **Archivos que necesitas crear:**

1. **ai_learning.py** - Sistema de IA con fallbacks
2. **bot_con_contexto.py** - Detector de contexto de precio
3. **bot_con_ia_corregido.py** - Bot con cooldown y expiración dinámica

---

## 🔧 LO QUE NECESITAS HACER

### **Opción 1: Recrear los archivos (Recomendado)**

Ejecuta estos comandos en orden:

```bash
# 1. Crear ai_learning.py (sin token secreto)
# 2. Crear bot_con_contexto.py
# 3. Crear bot_con_ia_corregido.py
# 4. Agregar archivos a Git
# 5. Commit y push
```

### **Opción 2: Usar bot_con_ia.py existente**

```bash
# Este archivo ya existe, pero NO tiene:
# - Cooldown por activo
# - Expiración dinámica
# - Sistema de bloqueo

# Puedes usarlo temporalmente mientras recreas los otros archivos
```

---

## 📦 ARCHIVOS MÍNIMOS NECESARIOS

### **Para que el bot funcione en Easypanel:**

```
config.py                    # Ya existe
bot_con_ia.py               # Ya existe (versión sin cooldown)
core/                        # Ya existe
data/                        # Ya existe
strategies/                  # Ya existe
requirements-easypanel.txt   # Necesitas crear
Dockerfile.easypanel         # Necesitas crear
.env                         # Configurar en Easypanel
```

---

## 🚀 PASOS PARA EASYPANEL

### **1. Crear requirements-easypanel.txt:**
```
requests>=2.31.0
pandas>=2.0.0
numpy>=1.24.0
ta-lib>=0.4.28
pandas-ta>=0.3.14b
websocket-client>=1.6.0
python-dotenv>=1.0.0
colorlog>=6.7.0
```

### **2. Crear Dockerfile.easypanel:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
COPY requirements-easypanel.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY config.py .
COPY bot_con_ia.py bot.py
COPY core/ core/
COPY data/ data/
COPY strategies/ strategies/
ENV PYTHONUNBUFFERED=1
ENV ACCOUNT_TYPE=PRACTICE
CMD ["python", "bot.py"]
```

### **3. Configurar variables de entorno en Easypanel:**
```bash
EXNOVA_EMAIL=tu_email
EXNOVA_PASSWORD=tu_password
ACCOUNT_TYPE=PRACTICE

# IA - GitHub Models (SIN TOKEN EN EL CÓDIGO)
GITHUB_TOKEN=tu_token_aqui
GITHUB_MODEL=gpt-4o-mini

# IA - Ollama Easypanel
OLLAMA_CUSTOM_URL=https://biblia-ollama.ginee6.easypanel.host
OLLAMA_CUSTOM_MODEL=minimax-m2.7:cloud

# IA - Ollama Local
OLLAMA_LOCAL_URL=http://localhost:11434
OLLAMA_LOCAL_MODEL=glm-5:cloud
```

---

## ⚠️ IMPORTANTE

### **NO SUBIR A GITHUB:**
- ❌ Tokens secretos
- ❌ Archivos .env
- ❌ Archivos .log
- ❌ operation_memory.json
- ❌ bot.lock

### **USAR .gitignore:**
```gitignore
*.log
*.pyc
__pycache__/
.env
operation_memory.json
bot.lock
```

---

## 🎯 RESUMEN

**Tienes dos opciones:**

1. **Usar bot_con_ia.py existente** (sin cooldown, sin expiración dinámica)
2. **Recrear los archivos** (con todas las mejoras)

**Para la Opción 1:**
```bash
git add bot_con_ia.py core/ data/ strategies/ config.py
git add requirements-easypanel.txt Dockerfile.easypanel .gitignore
git commit -m "Bot listo para Easypanel"
git push origin main
```

**Para la Opción 2:**
Necesito recrear los archivos:
- ai_learning.py
- bot_con_contexto.py
- bot_con_ia_corregido.py

**¿Qué opción prefieres?**