# 🚀 DESPLIEGUE EN EASYPANEL - GUÍA RÁPIDA

## ✅ Estado del Código en Git

Todo está subido y listo para desplegar:
- ✅ OpenCode integrado
- ✅ Sistema de control de operaciones robusto
- ✅ Manejo de pérdidas con aprendizaje
- ✅ Solo Ollama configurado (sin otras IAs)

---

## 📦 Archivos Principales Subidos

| Archivo | Propósito |
|---------|-----------|
| `Dockerfile.opencode` | Docker con Python + Node.js + OpenCode |
| `docker-compose.opencode.yml` | Configuración completa para Easypanel |
| `entrypoint.sh` | Script de entrada flexible |
| `bot_con_ia_v2.py` | Bot con control de operaciones robusto |
| `ai_learning.py` | Sistema de IA y aprendizaje |
| `operation_lock.py` | Lock atómico para prevenir operaciones dobles |

---

## 🚀 PASOS PARA DESPLEGAR EN EASYPANEL

### 1. Crear Servicio
```
En Easypanel:
1. Click "Create Service"
2. Seleccionar "Docker Compose"
3. Elegir tu repositorio GitHub
4. Branch: main
5. Docker Compose File: docker-compose.opencode.yml
```

### 2. Configurar Variables de Entorno

```bash
# OBLIGATORIAS - Credenciales Exnova
EXNOVA_EMAIL=tu_email@gmail.com
EXNOVA_PASSWORD=tu_password
ACCOUNT_TYPE=PRACTICE

# IA - Solo Ollama
OLLAMA_BASE_URL=https://biblia-ollama.ginee6.easypanel.host
OLLAMA_MODEL=llama3.2:1b
```

### 3. Deploy
```
Click "Deploy" y esperar a que construya la imagen
```

---

## 🖥️ USAR EL SERVICIO

### Opción A: Ejecutar el Bot (Versión Segura)
```bash
# En la terminal de Easypanel:
/entrypoint.sh bot
```

### Opción B: Ejecutar Bot V2 (Más Seguro)
```bash
# Usa el sistema de lock robusto:
python bot_con_ia_v2.py
```

### Opción C: Usar OpenCode
```bash
# Para editar código con IA:
/entrypoint.sh opencode
```

### Opción D: Shell Interactivo
```bash
# Para ejecutar comandos manualmente:
/entrypoint.sh shell
```

---

## 🆘 COMANDOS DE EMERGENCIA

### Detener Todo:
```bash
python emergency_stop.py
```

### Liberar Locks Manualmente:
```bash
rm -f data/locks/operation.lock
rm -f /tmp/bot.lock
```

### Ver Estado del Lock:
```python
python -c "from operation_lock import get_lock; print(get_lock().is_locked())"
```

---

## 📋 COMPORTAMIENTO DEL BOT V2

### Control de Operaciones:
- ✅ **Una operación a la vez** (imposible operar doble)
- ✅ **Lock atómico** con verificación de proceso vivo
- ✅ **Limpieza automática** de locks huérfanos

### Manejo de Pérdidas:
- 🕐 **Cooldown**: 5 minutos de pausa tras cada pérdida
- 🛑 **Límite**: Máximo 3 pérdidas consecutivas
- 🧠 **Aprendizaje**: Evita patrones que fallaron 3+ veces
- 📊 **Umbral adaptativo**: Ajusta confianza según resultados

---

## 📊 Qué Verás en los Logs

```
🚀 TRADING BOT V2 - CONTROL ROBUSTO
====================================
✅ Lock atómico activado

[1] Inicializando sistema de IA...
   Operaciones registradas: 0
   Umbral actual: 70.0%
   Pérdidas consecutivas: 0/3
   Cooldown activo: No
   Operación en curso: No

[CICLO #1] - 16:30:45
A) Escaneando mercado...
   ⏳ Sin oportunidad clara, esperando 30s...
```

Si hay operación activa:
```
⛔ LOCK ACTIVO: Operación en curso
   Esperando 10 segundos...
```

---

## ⚠️ NOTAS IMPORTANTES

1. **Restart Policy**: `restart: "no"` - No reinicia automáticamente
2. **Lock**: Previene operaciones simultáneas automáticamente
3. **Persistencia**: Los datos se guardan en volúmenes montados
4. **OpenCode**: Disponible en `/app` para editar código

---

## 🔧 Solución de Problemas

### Si hay operaciones dobles:
```bash
# 1. Detener todo
python emergency_stop.py

# 2. Limpiar locks
rm -f data/locks/* /tmp/bot*

# 3. Reiniciar con V2
python bot_con_ia_v2.py
```

### Si el bot no inicia:
Verifica variables de entorno:
```bash
echo $EXNOVA_EMAIL
echo $ACCOUNT_TYPE
```

---

## ✅ CHECKLIST PRE-DEPLOY

- [ ] Variables de entorno configuradas en Easypanel
- [ ] Repositorio conectado a Easypanel
- [ ] Archivo seleccionado: `docker-compose.opencode.yml`
- [ ] Cuenta de Exnova tiene saldo (PRACTICE)

---

**Listo para deploy! 🚀**
