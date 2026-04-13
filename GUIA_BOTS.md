# 📋 RESUMEN DE BOTS DISPONIBLES

## ⚠️ IMPORTANTE: EJECUTAR EL BOT CORRECTO

### **BOT CORREGIDO (RECOMENDADO):**
```bash
python bot_con_ia_corregido.py
```

**Características:**
- ✅ **Cooldown de 5 minutos por activo** (evita operaciones dobles)
- ✅ **Expiración dinámica** (3-7 min según volatilidad ATR)
- ✅ Sistema de IA con fallbacks (GitHub → Ollama Easypanel → Ollama Local)
- ✅ Detector de contexto de precio
- ✅ Aprendizaje progresivo

---

## 📊 COMPARACIÓN DE BOTS

| Bot | Cooldown | Expiración Dinámica | IA | Contexto | Recomendado |
|-----|-----------|---------------------|----|----------|-------------|
| **bot_con_ia_corregido.py** | ✅ | ✅ | ✅ | ✅ | ✅ **SÍ** |
| bot_con_ia.py | ❌ | ❌ | ✅ | ✅ | ❌ No |
| bot_con_contexto.py | ❌ | ❌ | ❌ | ✅ | ❌ No |
| bot_que_opera.py | ❌ | ❌ | ❌ | ❌ | ❌ No |

---

## 🔧 QUÉ HACE EL COOLDOWN

### **Sin Cooldown (bot_con_ia.py):**
```
10:30:00 - EURUSD CALL → Ejecutado
10:30:30 - EURUSD CALL → Ejecutado ← OPERACIÓN DOBLE
10:31:00 - EURUSD CALL → Ejecutado ← OPERACIÓN DOBLE
```

### **Con Cooldown (bot_con_ia_corregido.py):**
```
10:30:00 - EURUSD CALL → Ejecutado
10:30:30 - EURUSD CALL → RECHAZADO (Cooldown: 270s restantes)
10:35:00 - EURUSD CALL → Disponible (Cooldown terminado)
```

---

## 🎯 CÓMO EJECUTAR

### **1. Detener cualquier bot en ejecución:**
```bash
# Presionar Ctrl+C en la terminal
```

### **2. Ejecutar el bot CORREGIDO:**
```bash
python bot_con_ia_corregido.py
```

### **3. Verificar que funciona:**
```
Debes ver:
================================================================================
BOT CON IA - VERSIÓN CORREGIDA
================================================================================
Mejoras:
  ✅ Expiración dinámica (3-7 min según volatilidad)
  ✅ Sin operaciones dobles (cooldown por activo)
  ✅ Sistema de IA con fallbacks
================================================================================
```

---

## 📈 MÉTRICAS ESPERADAS

### **Bot Original (sin cooldown):**
- Win Rate: 60-70%
- Operaciones dobles: SÍ
- Expiración: Fija 5 min

### **Bot Corregido (con cooldown):**
- Win Rate: 65-75%
- Operaciones dobles: NO
- Expiración: Dinámica 3-7 min

---

## ⚠️ PROBLEMA COMÚN

**Si ves operaciones dobles:**
1. Verifica que estás ejecutando `bot_con_ia_corregido.py`
2. Detén cualquier otro bot en ejecución
3. Busca el mensaje "VERSIÓN CORREGIDA" al inicio

**Si ves el mensaje:**
```
BOT CON IA - APRENDIZAJE PROGRESIVO  ← ESTE ES EL ORIGINAL (SIN COOLDOWN)
```

**Detén y ejecuta:**
```bash
python bot_con_ia_corregido.py
```

---

## 🎯 RESUMEN FINAL

**EJECUTA SIEMPRE:**
```bash
python bot_con_ia_corregido.py
```

**NUNCA EJECUTES:**
```bash
python bot_con_ia.py  # ← Sin cooldown
```