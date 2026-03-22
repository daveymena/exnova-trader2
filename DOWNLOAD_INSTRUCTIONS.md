# 📥 DESCARGA E INSTALACIÓN DEL BOT

## 📦 Archivos Disponibles

Tienes dos opciones de descarga:

### Opción 1: Comprimido (Recomendado) ⚡
- **Archivo**: `exnova-trader-bot.tar.gz` (255 KB)
- **Ventaja**: Menor tamaño, más rápido de descargar
- **Sistema**: Linux/Mac

### Opción 2: Sin Comprimir
- **Archivo**: `exnova-trader-bot.tar` (1.5 MB)
- **Sistema**: Linux/Mac/Windows

---

## 🔐 Verificar Integridad (Opcional)

Después de descargar, puedes verificar que el archivo no fue modificado:

```bash
# En Linux/Mac:
sha256sum -c exnova-trader-bot.tar.gz.sha256

# En Windows (PowerShell):
(Get-FileHash exnova-trader-bot.tar.gz -Algorithm SHA256).Hash -eq (Get-Content exnova-trader-bot.tar.gz.sha256).Split()[0]
```

Expected hash:
```
ea7006d1fa746d12a135859e51472569765f14d5edbafebba32e8f3ca3a776b8
```

---

## 🚀 INSTALACIÓN RÁPIDA

### En Linux/Mac:

```bash
# 1. Extraer paquete
tar -xzf exnova-trader-bot.tar.gz
cd exnova-trader

# 2. Ejecutar instalador
bash INSTALL.sh

# 3. Configurar credenciales
nano .env

# 4. Ejecutar bot
python3 bot_practice_operativo.py
```

### En Windows:

```bash
# 1. Extraer paquete (usar 7-Zip, WinRAR o Windows Explorer)
# Click derecho > Extraer todo

# 2. Ejecutar instalador
INSTALL.bat

# 3. Configurar credenciales
notepad .env

# 4. Ejecutar bot
python bot_practice_operativo.py
```

---

## 📋 Qué Incluye el Paquete

```
exnova-trader/
├── bot_final.py                 ⭐ Bot principal (SIN RESTRICCIONES)
├── bot_practice_operativo.py    🚀 Ejecutor
├── .env.example                 📝 Plantilla de configuración
├── requirements.txt             📦 Dependencias Python
├── INSTALL.sh                   🐧 Instalador (Linux/Mac)
├── INSTALL.bat                  🪟 Instalador (Windows)
├── README_DOWNLOAD.md           📖 Guía rápida
├── exnovaapi/                   🔌 API de Exnova
├── data/                        📊 Carpeta para resultados
└── README.md                    📚 Documentación completa
```

---

## ⚙️ Configuración (Importante)

### 1. Editar .env

```bash
# Copiar plantilla
cp .env.example .env

# Editar con tu editor favorito (cambia tu_email y tu_password)
EXNOVA_EMAIL=tu_email@gmail.com
EXNOVA_PASSWORD=tu_password_12345

# Otras opciones (dejar como están si no sabes)
ACCOUNT_TYPE=PRACTICE
CAPITAL_PER_TRADE=1.0
EXPIRATION_TIME=60
```

### 2. Instalar Dependencias

```bash
# Opción 1: Automático (recomendado)
bash INSTALL.sh      # Linux/Mac
INSTALL.bat          # Windows

# Opción 2: Manual
pip install -r requirements.txt
```

---

## ✅ Verificar Instalación

```bash
# Verificar Python
python3 --version

# Verificar pip
pip --version

# Verificar que puede importar la API
python3 -c "from exnovaapi.api import ExnovaAPI; print('✅ OK')"
```

---

## 🎯 EJECUTAR EL BOT

### Opción 1 (Recomendada):
```bash
python3 bot_practice_operativo.py
```

### Opción 2 (Directa):
```bash
python3 bot_final.py
```

---

## 📊 Resultados

Durante la ejecución, se crean automáticamente:

```
data/operaciones_ejecutadas/
├── sesion_20260322_230526.log    ← Logs detallados
└── trades_20260322_230526.json   ← Datos de operaciones (JSON)
```

Cada operación incluye:
- Timestamp exacto
- Activo (EURUSD, GBPUSD, etc)
- Dirección (CALL/PUT)
- Resultado (WIN/LOSS)
- Ganancia/Pérdida

---

## 🛑 DETENER EL BOT

Presiona en la terminal: **`Ctrl + C`**

El bot mostrará:
- Total de operaciones ejecutadas
- Ganancias vs Pérdidas
- Win Rate (%)
- PnL Total

---

## 🔧 Requisitos del Sistema

- Python 3.7 o superior
- pip (gestor de paquetes)
- Conexión a internet
- Cuenta Exnova (cualquier cuenta, puede ser demo)
- ~300 MB de espacio en disco (después de instalar dependencias)

---

## ❓ Preguntas Frecuentes

**P: ¿Es seguro?**
R: Sí, usa PRACTICE mode (dinero simulado). Sin riesgo real.

**P: ¿Puedo cambiar el capital por operación?**
R: Sí, edita `CAPITAL_PER_TRADE=1.0` en `.env`

**P: ¿Cómo cambio a modo REAL?**
R: Cambia `ACCOUNT_TYPE=PRACTICE` a `ACCOUNT_TYPE=REAL` en `.env`
⚠️ Advertencia: Esto usará dinero REAL

**P: ¿Dónde veo mis resultados?**
R: En `data/operaciones_ejecutadas/` - archivos .log y .json

**P: ¿Puedo dejar el bot corriendo?**
R: Sí, puede correr 24/7 en PRACTICE mode

---

## 📞 SOPORTE

Si tienes problemas:

1. Verifica que el `.env` está bien configurado
2. Revisa los logs en `data/operaciones_ejecutadas/`
3. Verifica conexión a internet
4. Verifica que tienes Python 3.7+
5. Re-ejecuta: `pip install -r requirements.txt --upgrade`

---

## 🎉 ¡Listo!

Ya puedes descargar el paquete y empezar a operar.

**Próximos pasos:**
1. Descarga el paquete
2. Extrae el archivo
3. Ejecuta `INSTALL.sh` (o `INSTALL.bat` en Windows)
4. Edita `.env` con tus credenciales
5. Ejecuta `python3 bot_practice_operativo.py`
6. ¡Observe cómo el bot opera automáticamente!

---

**Bot EXNOVA Trading - V1.0.0**
**Última actualización: 2026-03-22**

