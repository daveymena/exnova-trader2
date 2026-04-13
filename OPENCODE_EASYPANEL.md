# OpenCode en Easypanel - Guía de Instalación

Esta guía te permite tener OpenCode disponible dentro de tu contenedor de Easypanel para manipular el código del proyecto.

---

## 📦 Archivos Creados

| Archivo | Descripción |
|---------|-------------|
| `Dockerfile.opencode` | Dockerfile con Python + Node.js + OpenCode |
| `entrypoint.sh` | Script flexible para ejecutar bot u OpenCode |
| `docker-compose.opencode.yml` | Configuración de Docker Compose |

---

## 🚀 Instalación en Easypanel

### Paso 1: Subir archivos a Git

```bash
git add Dockerfile.opencode entrypoint.sh docker-compose.opencode.yml OPENCODE_EASYPANEL.md
git commit -m "Add OpenCode integration for Easypanel"
git push origin main
```

### Paso 2: Configurar en Easypanel

#### Opción A: Usando Docker Compose (Recomendado)

1. En Easypanel, crea un nuevo servicio tipo **Docker Compose**
2. Selecciona tu repositorio
3. Especifica el archivo: `docker-compose.opencode.yml`
4. Configura las variables de entorno (ver abajo)

#### Opción B: Usando Dockerfile

1. En Easypanel, crea un nuevo servicio tipo **Docker**
2. Selecciona tu repositorio
3. Especifica el Dockerfile: `Dockerfile.opencode`
4. En **Command**, escribe: `opencode` (para iniciar OpenCode)
5. O deja vacío para ejecutar el bot por defecto

---

## ⚙️ Variables de Entorno

Configura estas variables en Easypanel:

### Requeridas para el Bot:
```
EXNOVA_EMAIL=tu_email@ejemplo.com
EXNOVA_PASSWORD=tu_password
ACCOUNT_TYPE=PRACTICE
```

### Para OpenCode (API Keys de IA):
```
# Opcional - OpenCode puede usar cualquiera de estas:
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GROQ_API_KEY=gsk_...
GITHUB_TOKEN=tu_token_github
```

### Para Ollama (local):
```
OLLAMA_BASE_URL=https://ollama-ollama.ginee6.easypanel.host
OLLAMA_MODEL=llama3.2:1b
```

---

## 🖥️ Usar OpenCode en Easypanel

### Método 1: Terminal Web de Easypanel

1. Ve al servicio en Easypanel
2. Haz clic en **Terminal** o **Console**
3. Ejecuta:
   ```bash
   opencode
   ```

### Método 2: Cambiar el Comando de Inicio

En la configuración del servicio, cambia el comando a:
```bash
opencode
```

Reinicia el servicio y OpenCode estará corriendo.

### Método 3: Shell Interactivo

Para tener acceso a bash y ejecutar comandos manualmente:
```bash
# Cambiar comando a:
/bin/bash

# Luego en la terminal:
opencode --help
opencode auth login
```

---

## 📝 Comandos Útiles de OpenCode

Una vez dentro de OpenCode:

```bash
# Ver ayuda
opencode --help

# Configurar autenticación
opencode auth login

# Ejecutar con un archivo específico
opencode archivo.py

# Modo interactivo (chat con el proyecto)
opencode --interactive

# Ejecutar un comando específico
opencode "refactorizar la función de análisis técnico"
```

---

## 🔧 Estructura del Proyecto para OpenCode

OpenCode tendrá acceso a todo el código:

```
/app/
├── bot_con_ia.py          # Bot principal
├── config.py              # Configuración
├── core/                  # Módulos core
│   ├── experience_buffer.py
│   ├── feature_engineer.py
│   └── ...
├── strategies/            # Estrategias de trading
├── exnovaapi/              # API de Exnova
├── data/                   # Datos de operaciones
└── logs/                   # Logs
```

---

## ⚠️ Consideraciones Importantes

### 1. Persistencia de Cambios
- OpenCode puede modificar archivos dentro del contenedor
- Para que los cambios persistan entre reinicios, usa volúmenes montados
- En `docker-compose.opencode.yml` el volumen `.:/app` monta el código local

### 2. Git dentro del Contenedor
```bash
# Configurar git si vas a hacer commits
git config --global user.email "tu@email.com"
git config --global user.name "Tu Nombre"

# Ver estado
git status

# Hacer commit desde dentro del contenedor
git add .
git commit -m "Cambios hechos via OpenCode"
git push
```

### 3. Seguridad
- **NUNCA** subas archivos `.env` con credenciales
- Usa las variables de entorno de Easypanel
- El `GITHUB_TOKEN` solo si necesitas push automático

---

## 🔄 Alternar entre Bot y OpenCode

### Ejecutar el Bot:
```bash
# Cambiar comando del servicio a:
python bot_con_ia.py
```

### Ejecutar OpenCode:
```bash
# Cambiar comando del servicio a:
opencode
```

### Shell para ambos:
```bash
# Cambiar comando a:
/bin/bash -c "while true; do sleep 1000; done"

# Luego en terminal:
python bot_con_ia.py    # Para bot
opencode                # Para OpenCode
```

---

## 🐛 Solución de Problemas

### OpenCode no encuentra API key:
```bash
# Verificar variables exportadas
env | grep -i api

# Configurar manualmente
export ANTHROPIC_API_KEY=sk-...
opencode
```

### Cambios no persisten:
- Asegúrate de que el volumen esté correctamente montado
- En Easypanel, verifica que el volumen apunte a `/app`

### Permisos de Git:
```bash
# Si git pide credenciales
git config --global credential.helper store
# Luego haz un push manual para guardar credenciales
```

---

## 🎯 Casos de Uso Recomendados

1. **Refactorización**: "Refactoriza el sistema de riesgos en `core/risk_manager.py`"

2. **Agregar Features**: "Agrega un nuevo indicador técnico al analizador"

3. **Debugging**: "Encuentra y corrige el bug en la función de expiración"

4. **Documentación**: "Genera documentación para el módulo de estrategias"

5. **Tests**: "Crea tests unitarios para el orquestador"

---

## 📚 Recursos

- [Documentación OpenCode](https://dev.opencode.ai/docs/cli)
- [Repositorio GitHub](https://github.com/opencode-ai/opencode)
- [Instalación](https://opencode.ai/install)

---

**Nota**: Esta configuración permite que OpenCode modifique el código fuente directamente. Siempre haz backup o usa git antes de hacer cambios importantes.
