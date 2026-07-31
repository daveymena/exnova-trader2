# Hallazgos medidos — Exnova Trading Bot

Todo lo de este documento está medido sobre datos propios, no citado de fuentes.
Cada afirmación es reproducible con los scripts indicados.

Fecha de la medición: 2026-07-31.

---

## 1. El sistema actual pierde de forma demostrable

```bash
python scripts/edge_stats.py
```

| Métrica | Valor |
|---|---|
| Trades | 500 |
| Winrate | 49.60% — IC95% [45.24%, 53.97%] |
| Payout medio real | 0.8383 |
| **Winrate de break-even** | **54.40%** |
| Esperanza por operación | **-0.088 × stake** |
| PnL acumulado | -176.19 |

El veredicto estadístico es `PERDEDOR REAL`: el intervalo de confianza completo
queda por debajo del break-even.

### Las features estaban muertas

| Feature | Diversidad | Problema |
|---|---|---|
| `rsi_at_touch` | 6 valores, moda `50` cubre **99.0%** | Constante: 0 información |
| `pattern` | moda `"demo"` cubre **50.6%** | Mitad del dataset es sintético |
| `zone_strength` | moda `1.0` cubre 53.0% | Mayormente un default |

Un sistema de aprendizaje entrenado sobre una constante no puede extraer nada.
Eso explica por qué 500 operaciones no mejoraron el resultado.

### Las reglas previas eran sobreajuste a ruido

`bot/engine/intelligent_engine.py:344` rechazaba patrones ajustados sobre
muestras de **n=1, n=6, n=7 y n=9**. Con intervalos de Wilson, *ninguno* de esos
grupos es distinguible del azar. Tampoco lo es ningún activo individual, ni
`pin_bar_bullish` (69.2%, n=26, IC95% [50.0%, 83.5%]).

### Potencia estadística necesaria

| Winrate a demostrar | Trades necesarios |
|---|---|
| 55% | 1.563 |
| 57% | 795 |
| 60% | 387 |
| 65% | 170 |

Con 107 activos distintos operados, ninguno llegó nunca a muestra suficiente.

---

## 2. Qué se puede operar realmente

```bash
python scripts/check_assets.py --real-only
```

**Exnova no ofrece ningún par de forex real como opción binaria.** EURUSD,
GBPUSD, USDJPY, AUDUSD y USDCAD no aparecen en las listas `turbo` ni `binary` de
la API. Solo existen en versión `-OTC` sintética.

Los 15 únicos activos de mercado real (payout 0.85–0.86):

- **turbo + binary**: `USSPX500:N`, `USNDAQ100:N`, `US30:N`, `US2000:N`, `JAPAN225:N`
- **solo binary**: `DXY`, `EXY`, `AXY`, `BXY`, `ETHUSD-op`

Frente a ~345 sintéticos OTC.

### Por qué antes siempre daba error

1. Los 13 tickers de `ASSETS_PTC_MORNING` (`SPX`, `DAX`, `EURUSD`…) **no existen**
   en la API. Corregido.
2. Una ventana horaria inventada de 08:00–12:00 bloqueaba el mercado real 20
   horas al día. Eliminada.
3. `get_all_open_time()` existía en la API pero **no se llamaba nunca**. Ahora sí,
   vía `bot/core/asset_discovery.py`.
4. Esa función además se cuelga (lanza 3 hilos; los de `digital` y
   `cfd/forex/crypto` no responden). Se lee `get_all_init_v2()` directamente.

---

## 3. Los feeds OTC son paseos aleatorios

```bash
python scripts/otc_pattern_lab.py
```

Medido sobre ~57.000 velas M1, 10 días:

| Activo | Tipo | P(sube) | Autocorr. lag1 | Runs test z | Vol. máx/mín |
|---|---|---|---|---|---|
| EURUSD-OTC | OTC | 0.5007 | -0.0028 | +0.74 | 1.53x |
| GBPUSD-OTC | OTC | 0.4897 | +0.0070 | -1.29 | 1.25x |
| USDJPY-OTC | OTC | 0.5024 | +0.0012 | +0.58 | 1.99x |
| XAUUSD-OTC | OTC | 0.5055 | -0.0020 | +0.37 | 1.90x |
| LTCUSD-OTC | OTC | 0.5023 | +0.0052 | +0.29 | 1.57x |
| USSPX500:N | REAL | 0.4886 | +0.0032 | +1.41 | **3.39x** |
| USNDAQ100:N | REAL | 0.4909 | -0.0016 | +1.31 | **3.28x** |
| US30:N | REAL | 0.4818 | -0.0055 | +2.05 | **4.77x** |
| US2000:N | REAL | 0.4905 | -0.0143 | +1.26 | **3.96x** |
| JAPAN225:N | REAL | 0.4860 | +0.0103 | -0.59 | **3.73x** |

**Ratio de volatilidad medio: OTC 1.65x vs REAL 3.83x.**

El perfil horario es la prueba visual. Los índices reales despiertan a las
13–15h UTC (apertura de Nueva York): 1.75 → 1.96 → 1.52 veces la media. Los OTC
marcan 0.97, 0.99, 0.97 — planos las 24 horas. Ningún mercado con participantes
humanos se comporta así.

### El OTC tampoco deriva del mercado real

Hipótesis probada y descartada: si `EURUSD-OTC` siguiera a `EURUSD` real con
retardo, sería explotable. Correlación de retornos **-0.0956** a lag 0, sin
retardo aprovechable en k=±5, y diferencia media de precio de **81 pips**. Son
feeds independientes.

### 138 reglas mecánicas probadas sobre OTC

Reversión tras rachas, momentum, RSI, Bollinger, agotamiento por ATR, EMAs —
con Bonferroni y validación fuera de muestra. **Ninguna** supera el break-even.
La señal condicional más fuerte de todo el dataset es P(revierte)=52.81% tras 5
velas alcistas, por debajo del 53.76% necesario.

---

## 4. El playbook investigado, backtesteado

```bash
python scripts/backtest_playbook.py --payout 0.86 --expiries 1,3,5
```

Ocho estrategias implementadas con los parámetros literales de las fuentes
(opciones-binarias.mx y el material de SlideShare), evaluadas en 48
combinaciones (8 × 3 expiraciones × 2 mercados):

| Estrategia | Mejor resultado fuera de muestra |
|---|---|
| MACD 12/26/9 + SMA200 | 54.6% en REAL 5min (n=586) — pero 46.2% dentro de muestra |
| Pullback tendencia | 53.2% en REAL 5min (n=1950) |
| Alligator + Fractal | 53.1% en REAL 5min (n=879) |
| Triple EMA 15/30/60 | 52.0% en REAL 3min (n=152) |
| Bollinger + RSI | 51.6% en REAL 3min (n=337) |
| SAR + Estocástico | 51.6% en SINTÉTICO (n=758) |
| Soporte/Resistencia + Stoch | 51.1% en SINTÉTICO (n=1384) |
| MA Crossover 5/20 | 50.9% en REAL 3min (n=884) |

**Ninguna alcanza el break-even con su intervalo de confianza.**

La mejor (MACD+SMA200, 54.6%) da **46.2% dentro de muestra y 54.6% fuera**. Esa
inversión completa es la firma del ruido, no de un edge: un sistema con ventaja
real funciona en ambos tramos.

---

## Herramientas construidas

| Script | Para qué |
|---|---|
| `scripts/edge_stats.py` | Evalúa el historial con intervalos de Wilson |
| `scripts/check_assets.py` | Pregunta al bróker qué está abierto y con qué payout |
| `scripts/fetch_history.py` | Descarga y persiste velas históricas |
| `scripts/otc_pattern_lab.py` | Busca patrones con corrección por multiplicidad |
| `scripts/backtest_playbook.py` | Backtestea el playbook, sintético vs real |
| `bot/backtest/` | Motor de replay sin look-ahead + indicadores + estrategias |
| `bot/core/asset_discovery.py` | Descubrimiento de activos desde el bróker |

El motor de backtest está validado contra un control: sobre datos aleatorios
reporta correctamente `PERDEDOR REAL` in-sample y se niega a concluir nada con
muestras pequeñas.

---

## Qué queda pendiente

- Auditoría del sesgo CALL (354 vs 146) y del bucle de aprendizaje: los agentes
  murieron por límite de sesión.
- Probar un método discrecional concreto, si se dispone de sus reglas exactas.
- Nivel tick: todo lo medido aquí es sobre velas M1.
