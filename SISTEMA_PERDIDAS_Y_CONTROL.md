# 🧠 Sistema de Control de Operaciones y Manejo de Pérdidas

## 📋 Resumen de Cambios

El sistema ha sido actualizado para:
1. **Prevenir operaciones simultáneas** (múltiples trades al mismo tiempo)
2. **Aprender de las pérdidas** y ajustar estrategia automáticamente
3. **Refinar entradas** basándose en historial de éxito/fracaso

---

## 🚨 Control de Operaciones Simultáneas

### El Problema
El bot anterior podía iniciar múltiples operaciones simultáneamente si:
- Se reiniciaba mientras había operaciones abiertas
- El ciclo de búsqueda era más rápido que la expiración
- Había lag en la verificación de estado

### La Solución: File-Based Lock

```python
# Archivo: ai_learning.py

class TradingLearner:
    def is_operation_in_progress(self):
        """
        Verifica si hay una operación activa mediante un archivo lock.
        Si el lock tiene >15 minutos, se considera "stale" y se libera.
        """
        if self.lock_file.exists():
            lock_time = obtener_tiempo_del_lock()
            if time.time() - lock_time > 900:  # 15 minutos
                self._release_lock()  # Auto-limpieza
                return False
            return True  # Hay operación activa
        return False  # No hay operación
```

### Flujo de Control

```
┌─────────────────────────────────────────┐
│  Ciclo Principal del Bot                │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  ¿Hay operación en curso?               │
│  (verificar archivo lock)               │
└──────────────┬──────────────────────────┘
               │
       ┌───────┴───────┐
       │               │
      SÍ              NO
       │               │
       ▼               ▼
┌──────────┐   ┌──────────────────┐
│ Esperar  │   │ Buscar oportunidad│
│ 10s      │   └────────┬─────────┘
│ y repetir│            │
└──────────┘            ▼
               ┌──────────────────┐
               │ Validar entrada  │
               └────────┬─────────┘
                        │
                        ▼
               ┌──────────────────┐
               │ Crear LOCK       │◄── Registra operación
               │ antes de comprar │    como "en progreso"
               └────────┬─────────┘
                        │
                        ▼
               ┌──────────────────┐
               │ Ejecutar compra  │
               └────────┬─────────┘
                        │
                        ▼
               ┌──────────────────┐
               │ Esperar cierre   │
               │ (no buscar más)  │
               └────────┬─────────┘
                        │
                        ▼
               ┌──────────────────┐
               │ Liberar LOCK     │◄── Operación terminada
               │ y analizar       │    Analizar resultado
               └──────────────────┘
```

---

## 📉 Manejo de Pérdidas (Sistema de Aprendizaje)

### 1. Cooldown Post-Pérdida

```python
# Después de cada pérdida:
def analyze_operation(self, operation_data):
    if result == 'LOSS':
        # 1. Incrementar contador de pérdidas
        self.consecutive_losses += 1

        # 2. Activar cooldown de 5 minutos
        self.cooldown_until = time.time() + 300  # 300s = 5min

        # 3. Registrar patrón que falló
        pattern_key = f"{asset}_{direction}_RSI{int(rsi/5)*5}"
        self.loss_patterns[pattern_key]['failures'] += 1
```

### 2. Límite de Pérdidas Consecutivas

```python
def should_enter_trade(self, context):
    # 🛑 Bloquear si hay 3+ pérdidas seguidas
    if self.consecutive_losses >= 3:
        return False, "Límite de 3 pérdidas consecutivas"
```

### 3. Detección de Patrones Problemáticos

El sistema agrupa operaciones por:
- **Activo** (EURUSD, GBPUSD, etc.)
- **Dirección** (CALL/PUT)
- **RSI** (agrupado en rangos de 5: 30-35, 35-40, etc.)

```python
# Ejemplo de patrón registrado:
{
  "EURUSD_CALL_RSI35": {
    "failures": 3,
    "last_failure": "2026-04-12T15:30:00"
  },
  "GBPUSD_PUT_RSI60": {
    "failures": 2,
    "last_failure": "2026-04-12T14:45:00"
  }
}
```

Si un patrón falla 3+ veces, se **rechaza automáticamente**.

### 4. Umbral de Confianza Adaptativo

```python
# Después de WIN:
if result == 'WIN':
    self.consecutive_losses = 0
    self.current_threshold = min(85, self.current_threshold + 1)
    # Más selectivo (requiere mejor señal)

# Después de LOSS:
if result == 'LOSS':
    self.consecutive_losses += 1
    self.current_threshold = max(60, self.current_threshold - 2)
    # Más conservador (baja el umbral de aceptación)
```

| Resultado | Ajuste de Umbral | Consecuencia |
|-----------|------------------|--------------|
| WIN | +1% | Más selectivo |
| LOSS | -2% | Más conservador |

---

## 🔄 Refinamiento de Entradas

### Análisis de Activo

```python
def _get_asset_stats(self, asset):
    """Calcula estadísticas por activo"""
    asset_ops = [op for op in self.operations if op['asset'] == asset]
    wins = len([op for op in asset_ops if op['result'] == 'WIN'])

    return {
        'total': len(asset_ops),
        'wins': wins,
        'losses': len(asset_ops) - wins
    }

# Uso:
if asset_stats['total'] >= 5:
    win_rate = asset_stats['wins'] / asset_stats['total']
    if win_rate < 0.4:  # Menos de 40%
        return False, "Win rate del activo muy bajo"
```

### Sugerencias Automáticas

Cada 10 operaciones, el sistema genera sugerencias:

```python
def get_improvement_suggestions(self):
    if win_rate < 0.5:
        return [
            "Win rate bajo - Aumentar confirmación",
            "Reducir tamaño de posición",
            "Esperar mejor timing"
        ]
    elif win_rate > 0.65:
        return [
            "Buen win rate - Considerar aumentar capital",
            "Buscar más oportunidades similares"
        ]
```

---

## 📊 Archivos Generados

El sistema crea estos archivos en `data/ai_learning/`:

| Archivo | Contenido |
|---------|-----------|
| `operation_history.json` | Historial completo de operaciones |
| `loss_patterns.json` | Patrones que han fallado |
| `config.json` | Configuración adaptativa (umbral actual) |
| `operation.lock` | Lock de operación en curso (temporal) |

---

## 🎯 Ejemplo de Flujo Completo

### Escenario 1: Pérdida Seguida de Cooldown

```
1. Bot ejecuta EURUSD CALL → LOSS
2. Sistema registra:
   - consecutive_losses = 1
   - cooldown_until = ahora + 300s
   - pattern "EURUSD_CALL_RSI40" failures += 1

3. Próximo ciclo:
   IA dice: "RECHAZADO: En cooldown (280s restantes)"
   Bot espera 5 minutos sin operar

4. Después del cooldown:
   Bot vuelve a operar con umbral más bajo
```

### Escenario 2: Pérdidas Consecutivas

```
1. Operación 1: GBPUSD PUT → LOSS
   consecutive_losses = 1

2. Operación 2: EURUSD CALL → LOSS
   consecutive_losses = 2

3. Operación 3: Intenta USDJPY CALL
   IA dice: "RECHAZADO: Límite de 3 pérdidas consecutivas"
   Bot NO opera hasta próximo reinicio o win manual
```

### Escenario 3: Patrón Problemático

```
1. EURUSD CALL con RSI 42 → LOSS (fallo #1)
2. EURUSD CALL con RSI 44 → LOSS (fallo #2)
3. EURUSD CALL con RSI 41 → LOSS (fallo #3)

4. Próximo intento: EURUSD CALL con RSI 43
   IA detecta: "EURUSD_CALL_RSI40" tiene 3 fallos
   IA dice: "RECHAZADO: Patrón ha fallado 3 veces"
```

---

## ✅ Ventajas del Sistema

1. **No más operaciones simultáneas**: Lock file garantiza una sola operación
2. **Protección tras pérdidas**: Cooldown automático + límite de 3
3. **Aprendizaje real**: Evita patrones que han fallado
4. **Adaptabilidad**: Umbral se ajusta según resultados
5. **Persistencia**: Datos guardados entre sesiones

---

## ⚠️ Consideraciones

- El lock file se libera automáticamente al terminar la operación
- Si el bot se cierra abruptamente, el lock puede quedar "huérfano" (se limpia solo después de 15 min)
- El cooldown es global (aplica a todos los activos), no por activo individual
- Los patrones se agrupan por rangos de RSI de 5 puntos (para evitar overfitting)
