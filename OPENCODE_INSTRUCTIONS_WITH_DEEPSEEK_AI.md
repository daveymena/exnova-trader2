# 🎯 INSTRUCCIONES PARA OPENCODE - SUPERVISIÓN INTELIGENTE CON IA

**Nota importante:** Esto es para OPENCODE (tu orquestador de trading), NO confundir con Claude Code (que es lo que yo soy - solo ayudo a escribir código).

---

## 🎬 FLUJO CON OPENCODE + IA (DeepSeek Flash)

```
┌──────────────────────────────────────────────────────┐
│ TÚ (Usuario)                                         │
│ ├─ Haces git push main                              │
│ └─ OpenCode lo detecta automáticamente              │
└──────────────┬───────────────────────────────────────┘
               ↓
┌──────────────────────────────────────────────────────┐
│ GITHUB (Repositorio)                                 │
│ ├─ Almacena código                                  │
│ ├─ Almacena estrategias                             │
│ └─ Almacena DeepSeek Optimizer (IA)                │
└──────────────┬───────────────────────────────────────┘
               ↓
┌──────────────────────────────────────────────────────┐
│ OPENCODE (Orquestador Inteligente)                   │
│ ├─ 1. Descarga código desde Git                    │
│ ├─ 2. Inicializa Bot                               │
│ ├─ 3. Inicializa IA DeepSeek Optimizer             │
│ ├─ 4. SUPERVISA: Monitorea en tiempo real           │
│ └─ 5. INTELIGENTE: Usa IA para decisiones          │
└──────────────┬───────────────────────────────────────┘
               ↓
    ╔═══════════════════════════════════════╗
    ║ BOT EJECUTANDO + IA ANALIZANDO        ║
    ║                                       ║
    ║ Trade 1 → Resultado → IA ANALIZA     ║
    ║ Trade 2 → Resultado → IA MEJORA      ║
    ║ Trade 3 → Resultado → IA OPTIMIZA    ║
    ║ ...                                   ║
    ║                                       ║
    ║ 24/7 Mejora automática + Supervisión ║
    ╚═══════════════════════════════════════╝
```

---

## 🚀 INSTRUCCIONES PASO A PASO PARA OPENCODE

### PASO 1: CONFIGURACIÓN INICIAL

```yaml
# opencode-config.yaml

trading_system:
  name: "PCR Trading Bot with DeepSeek AI"
  version: "1.0.0"
  
git_integration:
  repository: "https://github.com/menadanyer/Exnova-Trading-Bot"
  branch: "main"
  auto_sync: true
  check_interval: 300  # Cada 5 minutos

deployment:
  command: "python run_pcr_live.py"
  working_directory: "/bot"
  environment_vars:
    STRATEGY: "pcr_simple"
    DEEPSEEK_API_KEY: "${DEEPSEEK_API_KEY}"  # Secret
    EXNOVA_EMAIL: "${EXNOVA_EMAIL}"          # Secret
    EXNOVA_PASSWORD: "${EXNOVA_PASSWORD}"    # Secret

monitoring:
  enabled: true
  dashboard_port: 8080
  check_interval: 10
  alert_on_wr_below: 54.4
  alert_on_consecutive_losses: 5

ai_optimization:
  enabled: true
  provider: "deepseek"
  model: "deepseek-chat"
  analysis_frequency: "every_10_trades"
  deep_analysis_frequency: "every_50_trades"
  optimization_frequency: "every_100_trades"
```

---

### PASO 2: INICIAR OPENCODE

```bash
# Comando para iniciar OpenCode

opencode start --config opencode-config.yaml --mode supervised

# Output esperado:
# ✅ Configuration loaded
# ✅ Git repository synchronized
# ✅ Bot initialized
# ✅ DeepSeek AI connected
# ✅ Monitoring active
# 🟢 System ready for autonomous trading
```

---

### PASO 3: SUPERVISIÓN AUTOMÁTICA DE OPENCODE

OpenCode, una vez iniciado, **automáticamente**:

#### A) MONITOREA EL BOT
```python
# OpenCode ejecuta continuamente:

while bot_running:
    status = get_bot_status()
    
    # Verificar cada 10 segundos
    if status.cpu > 80%:
        alert("CPU alta")
    
    if status.memory > 1GB:
        alert("Memoria alta")
    
    if not status.connected_to_exnova:
        restart_bot()
    
    sleep(10)
```

#### B) RECOLECTA DATOS
```python
# OpenCode recolecta automáticamente:

every_second:
    ├─ ¿Bot sigue ejecutándose?
    └─ Registrar timestamp

every_trade:
    ├─ Resultado: WIN/LOSS
    ├─ WR actual
    ├─ PnL acumulado
    └─ Parámetros usados

every_10_trades:
    ├─ Llamar IA DeepSeek: "Analiza estos 10 trades"
    ├─ Recolectar recomendaciones
    └─ Guardar en logs

every_50_trades:
    ├─ Llamar IA DeepSeek: "Detecta patrones profundos"
    ├─ Análisis de causa raíz
    └─ Recomendaciones estratégicas

every_100_trades:
    ├─ Llamar IA DeepSeek: "Optimiza parámetros"
    ├─ Genera plan de optimización
    └─ Aplica cambios automáticamente
```

#### C) EXPONE DASHBOARD
```bash
# OpenCode automáticamente expone:

http://localhost:8080/pcr/
├─ Live metrics (WR, PnL, trades)
├─ Bot health
├─ IA recommendations
├─ Performance history
└─ Alert log

API Endpoints (OpenCode automáticamente):
├─ GET /api/metrics          → Métricas actuales
├─ GET /api/ai-analysis      → Análisis de IA
├─ GET /api/recommendations  → Recomendaciones
├─ GET /api/alerts           → Alertas activas
└─ POST /api/action?action=X → Ejecutar acciones
```

---

## 🤖 CÓMO LA IA SUPERVISA INTELIGENTEMENTE

### Supervisión Nivel 1: Análisis de Cada Trade

```
Bot ejecuta Trade
     ↓
OpenCode detecta resultado
     ↓
Si es importante → Llama IA DeepSeek
     ↓
IA analiza:
  ├─ ¿Por qué ganó/perdió?
  ├─ ¿Qué patrones ve?
  ├─ ¿Qué parámetro ajustar?
  └─ ¿Cómo mejorar próximo?
     ↓
OpenCode recibe recomendaciones
     ↓
Registro automático en logs
     ↓
Dashboard actualiza
```

### Supervisión Nivel 2: Detección de Problemas

```
Cada 50 trades:
  OpenCode → IA: "¿Qué está pasando?"
     ↓
IA ANALIZA PROFUNDAMENTE:
  ├─ Patrones no obvios
  ├─ Problemas sistémicos
  ├─ Causas raíz
  └─ Soluciones inteligentes
     ↓
Si Problema Crítico:
  ├─ OpenCode → ALERTA inmediata
  ├─ Dashboard → Rojo
  ├─ Email → Notificación
  └─ Opción: Auto-pause si severidad = CRÍTICA
```

### Supervisión Nivel 3: Optimización Continua

```
Cada 100 trades:
  OpenCode → IA: "Optimiza el sistema"
     ↓
IA GENERA:
  ├─ Nuevos parámetros propuestos
  ├─ Plan de cambios
  ├─ Impacto esperado
  └─ Plan A/B testing
     ↓
OpenCode APLICA:
  ├─ Crea versión B con nuevos parámetros
  ├─ Prueba ambas versiones
  ├─ Compara WR después de 50 trades
  ├─ Elige la mejor
  └─ Descarta la peor
     ↓
Próximo ciclo: Sistema más optimizado
```

---

## 📋 INSTRUCCIONES ESPECÍFICAS PARA OPENCODE

### Instrucción 1: Iniciar con IA

```bash
opencode execute --script launch_bot_with_ai.py

# launch_bot_with_ai.py contendrá:

import subprocess
import os
from bot.ai_agents.deepseek_optimizer import DeepSeekOptimizer

# 1. Verificar credenciales de IA
if not os.getenv('DEEPSEEK_API_KEY'):
    print("ERROR: DEEPSEEK_API_KEY no configurada")
    exit(1)

# 2. Inicializar IA
ai = DeepSeekOptimizer()
print("✅ IA DeepSeek conectada")

# 3. Iniciar Bot
process = subprocess.Popen(['python', 'run_pcr_live.py'])
print("✅ Bot iniciado")

# 4. Monitorear continuamente
while True:
    # ... código de monitoreo
    # ... llamadas a IA cada N trades
    # ... actualización de dashboard
```

### Instrucción 2: Supervisión en Tiempo Real

```bash
# OpenCode debe ejecutar CONTINUAMENTE:

while bot_running:
    # Cada 10 segundos
    metrics = get_bot_metrics()
    
    # Cada trade
    if new_trade:
        trade_data = get_latest_trade()
        if trade_data['importance'] > threshold:
            # Llamar IA para análisis
            ai_analysis = ai.analyze_trade(trade_data)
            store_in_logs(ai_analysis)
            update_dashboard(ai_analysis)
    
    # Cada 50 trades
    if trades_count % 50 == 0:
        trades_batch = get_last_50_trades()
        deep_analysis = ai.detect_patterns_across_trades(trades_batch)
        check_alerts(deep_analysis)
        
    # Cada 100 trades
    if trades_count % 100 == 0:
        optimization = ai.optimize_parameters_with_ai(
            current_params,
            performance_data
        )
        apply_optimizations(optimization)
        report_improvements()
```

### Instrucción 3: Alertas Inteligentes

```python
# OpenCode debe generar alertas INTELIGENTES:

alerts = {
    'WR_BELOW_THRESHOLD': {
        'condition': lambda m: m['wr'] < 54.4,
        'severity': 'HIGH',
        'action': 'Log + Dashboard + Email',
        'ai_required': True  # Llamar IA para diagnóstico
    },
    'CONSECUTIVE_LOSSES': {
        'condition': lambda m: m['consecutive_losses'] >= 5,
        'severity': 'CRITICAL',
        'action': 'Log + Email + Optional pause',
        'ai_required': True  # IA debe diagnosticar
    },
    'VOLATILITY_EXTREME': {
        'condition': lambda m: m['volatility'] > 0.02,
        'severity': 'MEDIUM',
        'action': 'Log + Dashboard',
        'ai_required': False  # Ya sabemos qué hacer
    },
    'UNUSUAL_PATTERN': {
        'condition': lambda m: ai_detects_pattern(m),
        'severity': 'MEDIUM',
        'action': 'Log + Dashboard + IA analysis',
        'ai_required': True  # IA detectó, IA analiza
    }
}

for alert_type, config in alerts.items():
    if config['condition'](metrics):
        if config['ai_required']:
            # Llamar IA para análisis
            ai_insight = ai.diagnose_failure(recent_trades)
            send_alert(alert_type, config['severity'], ai_insight)
        else:
            send_alert(alert_type, config['severity'])
```

### Instrucción 4: Dashboard Supervisado

```
El Dashboard que OpenCode expone debe mostrar:

┌─────────────────────────────────────────┐
│ 📊 DASHBOARD INTELIGENTE                │
├─────────────────────────────────────────┤
│ MÉTRICAS EN VIVO:                       │
│ ├─ WR: 65.2% ✅                         │
│ ├─ PnL: +$312.50                        │
│ ├─ Trades: 183                          │
│ └─ Últimas 50: 68% WR                   │
│                                         │
│ 🤖 IA INSIGHTS:                         │
│ ├─ Última análisis: Hace 10 min         │
│ ├─ Recomendación: Aumentar confid 65→70│
│ ├─ Patrón detectado: Hora 11-12 es ok  │
│ └─ Sistema: Optimizando (v2.3)          │
│                                         │
│ 🚨 ALERTAS ACTIVAS: 0                  │
│                                         │
│ ⚙️ PARÁMETROS ACTUALES:                │
│ ├─ confidence_threshold: 70 (mejor +2%)│
│ ├─ min_touches: 3 (robusto)            │
│ ├─ volatility_max: 0.015 (seguro)      │
│ └─ strict_mode: True (optimizando)     │
│                                         │
│ 📈 HISTÓRICO:                          │
│ └─ Mejora en 100 trades: 52% → 68% ✅ │
└─────────────────────────────────────────┘
```

---

## 🎯 RESUMEN: QUÉ HACE OPENCODE CON IA

```
OPENCODE CON IA (DeepSeek Flash):

1️⃣ DESCARGA código desde Git
   └─ Incluye DeepSeek Optimizer

2️⃣ INICIA Bot
   └─ Bot empieza a tradear

3️⃣ MONITOREA con IA
   ├─ Cada trade → IA analiza
   ├─ Cada 50 → IA detecta patrones
   └─ Cada 100 → IA optimiza

4️⃣ SUPERVISA INTELIGENTEMENTE
   ├─ IA identifica problemas
   ├─ IA sugiere soluciones
   ├─ OpenCode ejecuta sugerencias
   └─ Sistema mejora continuamente

5️⃣ EXPONE DASHBOARD
   ├─ Métricas en vivo
   ├─ Análisis de IA
   ├─ Alertas inteligentes
   └─ Plan de optimización

RESULTADO:
✅ Trading 24/7 automático
✅ Supervisión inteligente con IA
✅ Mejora continua sin intervención
✅ Sistema evoluciona solo
```

---

## 📝 NOTA IMPORTANTE

```
🎯 NO CONFUNDIR:

❌ Claude Code (yo) = Ayudo a escribir código
✅ OpenCode (tuyo) = Ejecuta y supervisa

❌ Claude Code no ejecuta trades
✅ OpenCode ejecuta, Bot opera, IA mejora

ARQUITECTURA FINAL:
├─ Git: Almacena código
├─ OpenCode: Orquesta y supervisa
├─ Bot: Ejecuta trades
└─ DeepSeek AI: Analiza y mejora (inteligentemente)
```

---

**STATUS:** 🟢 OpenCode configurado para supervisión inteligente con IA DeepSeek
