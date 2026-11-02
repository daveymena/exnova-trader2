# Bot IQ Option con Gemma (dinero real)

Bot que intenta replicar las entradas manuales del usuario (64 operaciones, 64,5 % de acierto)
en IQ Option. Gemma (`gemma4:31b` en Ollama Cloud) lee la gráfica antes de cada operación.

## Cómo entra
1. 13 s antes del cierre de la vela de 15 s, Gemma recibe una imagen con dos paneles
   (panorámica de 1 min ~200 min y 30 min de velas de 15 s) y 14 ejemplos del usuario más
   las últimas 4 operaciones repasadas del bot. Solo puede vetar por mala ubicación.
2. Al cierre (+1 s) el código comprueba la vela cerrada y las reglas de `lugar_ok`:
   lado de la EMA20, toque de EMA20, vela de confirmación a favor, `pos30 <= 0.60`,
   `avance <= 0.45`, `pos_lado <= 0.85`, lado de la EMA50 de 1 min, `pos_3h <= 0.80`,
   máximo 6 cruces de EMA20 en 10 min.
3. Compra la de mayor confianza: una por análisis, una por activo, una abierta a la vez.

## Protección
- Mercado inestable (`vr > 1.8` o salto `> 6`): salta el activo; si la mitad lo está, pausa 5 min.
- Madrugada (00:00–06:00 Colombia) sin operar, salvo `--con-madrugada`.
- 3 pérdidas seguidas: pausa de 30 min.
- Topes: `--stop-perdida`, `--stop-ganancia`, `--max-ops`, `--parar-al-perder`.
  Al llegar a un tope escribe `bot/data/REAL_FINALIZADO` y el vigía no lo relanza.
- Parada manual: crear `bot/data/PARAR_REAL`.

## Procesos
| Script | Qué hace |
|---|---|
| `scripts/gemma_live.py` | Bot (práctica o `--real --confirmo-real`, máximo $2) |
| `scripts/ciclo_mejora.py` | Cada 5 min mide cada análisis con 6 puntos de entrada y vencimientos de 1 a 5 min (`reports/ciclo_mejora.txt`). Solo cambia el vencimiento si una combinación pasa Wilson+Bonferroni con 100 casos y el usuario no lo fijó |
| `scripts/repaso_real.py` | Margen de cada operación real moviendo la entrada ±60 s (`reports/repaso_real.txt`) |
| `scripts/medir_gemma.py --bucle` | Si lo que Gemma aprueba gana más que lo que rechaza (`reports/valor_gemma.txt`) |
| `scripts/vigia_bots.ps1` | Tarea programada `BotsIQ_Vigia` cada 5 min: relanza lo caído |

`bot/data/gemma_config.json` fija el vencimiento (2 min, decidido por el usuario) sin reiniciar.

## Lo medido (resumen)
- Ninguna regla mecánica sola supera el 54 % necesario en el historial de IQ (375 combinaciones, ~49–51 %).
- El usuario sí muestra habilidad: 40/62 frente a 50,2 % al azar (p = 0,016).
- Madrugada 47,3 %, noche 53,2 %, volatilidad extrema 46,4 %.
- Gemma aprueba vs rechaza: todavía sin diferencia clara.
- Primera tanda real: 18 operaciones, 11 ganadas, +$4,58. Muestra pequeña: aún no prueba ventaja.

Los scripts `medir_*`, `lab_*`, `buscar_borde`, `pruebas_finales`, `replica_*` y `examen_*`
son las mediciones que llevaron a estas reglas; sus resultados están en `reports/`.
