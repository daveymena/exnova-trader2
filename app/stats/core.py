# -*- coding: utf-8 -*-
"""Primitivas estadisticas del nucleo. Sin dependencias externas (solo `math`).

POR QUE EXISTE ESTE MODULO
---------------------------
`app/data/repository.py` llamaba a `wilson_lower_bound()` -- funcion que no
existia en ningun archivo de `app/`. En cuanto habia evidencia repetida de una
combinacion asset/strategy/direction/regime/expiry, `get_historical_edge()`
reventaba con NameError. Es decir: el sistema se rompia exactamente cuando
empezaba a tener datos que medir. Ese era el punto 3 de
`app/NOT_PRODUCTION_READY.md`.

Pero el bug no era solo la funcion faltante. Era el criterio. Con payout 0.85 el
break-even esta en 1/1.85 = 54.05%. Un setup con 6 aciertos de 9 (66.7%) parece
tener edge y es ruido puro: su IC95% de Wilson va de ~35% a ~88%. Promover
reglas sobre esas muestras es el mecanismo exacto que hundio las 500
operaciones historicas de este proyecto.

Por eso aqui no hay solo intervalos: hay tambien correccion por comparaciones
multiples y por miradas repetidas. Probar 40 variantes de parametros y
quedarse con la mejor produce un "ganador" aparente aunque las 40 sean monedas
al aire; y mirar el mismo setup despues de cada operacion es testear la misma
hipotesis cientos de veces.

LINEAGE
-------
El estandar se toma de `bot/core/self_evaluator.py`, que es lo mejor que tenia
el repositorio y que `app/` nunca llego a usar. Las funciones se portan aqui
para que `app/` sea autonomo (es el nucleo unico a partir de ahora) y para que
el bot no arrastre scipy.

REGLA DE ORO DEL PROYECTO
-------------------------
Si un valor no se puede calcular se devuelve `None`, NUNCA un default
plausible. `wilson_interval(0, 0)` devuelve `(None, None)` y no `(0.0, 1.0)`:
un intervalo (0,1) invita a compararlo con el break-even y a "concluir" algo.
Sin datos no hay conclusion.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

__all__ = [
    "z_from_alpha",
    "wilson_interval",
    "wilson_lower_bound",
    "wilson_upper_bound",
    "binomial_pvalue_upper",
    "binomial_pvalue_lower",
    "benjamini_hochberg",
    "bonferroni",
    "breakeven_winrate",
    "expectancy_per_unit",
    "profit_factor",
    "kelly_fraction",
    "fractional_kelly",
    "max_drawdown_pct",
    "longest_streak",
    "binary_sharpe",
    "geometric_checkpoints",
    "looks_alpha",
    "mean_confidence_interval",
    "summarize_binomial",
]

Z_95_ONE_SIDED = 1.6448536269514722
Z_95_TWO_SIDED = 1.959963984540054
Z_99_TWO_SIDED = 2.5758293035489004


# ===========================================================================
# Cuantil normal (sin scipy: esto corre dentro del runtime del bot)
# ===========================================================================

_Z_CACHE: dict[float, float] = {}


def z_from_alpha(alpha: float) -> float:
    """Cuantil normal 1-alpha (una cola). alpha=0.05 -> 1.6449, 0.025 -> 1.9600.

    Aproximacion de Acklam mas un refinamiento de Halley: error < 1e-12.
    """
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha fuera de rango (0,1): {alpha}")
    cached = _Z_CACHE.get(alpha)
    if cached is not None:
        return cached

    p = 1.0 - alpha
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1.0 - 0.02425

    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= phigh:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)

    # Refinamiento de Halley sobre el error residual.
    e = 0.5 * math.erfc(-x / math.sqrt(2.0)) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    x = x - u / (1.0 + 0.5 * u * x)

    _Z_CACHE[alpha] = x
    return x


# ===========================================================================
# Intervalos de Wilson sobre proporcion de aciertos
# ===========================================================================

def wilson_interval(wins: int, n: int,
                    z: float = Z_95_TWO_SIDED) -> tuple[Optional[float], Optional[float]]:
    """Intervalo de Wilson para la proporcion de aciertos. `(None, None)` si n<=0.

    Wilson y no Wald (p +- z*sqrt(p(1-p)/n)) porque Wald se degrada gravemente
    con p cerca de 0 o 1 y con n pequeno -- justo el regimen de un setup que
    empieza a acumular operaciones.
    """
    if n <= 0:
        return (None, None)
    if wins < 0 or wins > n:
        raise ValueError(f"wins={wins} fuera de rango para n={n}")
    p = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def wilson_lower_bound(wins: int, n: int, z: float = Z_95_TWO_SIDED) -> Optional[float]:
    """Cota INFERIOR de Wilson. Es la unica cifra que el gate de edge debe mirar.

    Devuelve None cuando n<=0: "sin muestra" no es "0% de edge", es
    "no lo sabemos". Quien confunde las dos cosas acaba operando un setup
    del que no tiene ninguna informacion.
    """
    lo, _ = wilson_interval(wins, n, z)
    return lo


def wilson_upper_bound(wins: int, n: int, z: float = Z_95_TWO_SIDED) -> Optional[float]:
    """Cota SUPERIOR de Wilson. Sirve para declarar PERDEDOR: si incluso el
    escenario optimista queda por debajo del break-even, el setup esta muerto."""
    _, hi = wilson_interval(wins, n, z)
    return hi


# ===========================================================================
# Test binomial exacto
# ===========================================================================

def _log_binom_pmf(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return (math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
            + k * math.log(p) + (n - k) * math.log(1.0 - p))


def binomial_pvalue_upper(wins: int, n: int, p0: float) -> Optional[float]:
    """P(X >= wins) bajo H0: p = p0. Binomial exacta, sin aproximacion normal.

    None si n<=0. Es la pregunta "podria esta racha de aciertos ser suerte?"
    contra la hipotesis nula de que solo acertamos el break-even.
    """
    if n <= 0:
        return None
    if not (0.0 <= p0 <= 1.0):
        raise ValueError(f"p0 fuera de [0,1]: {p0}")
    total = 0.0
    for k in range(wins, n + 1):
        total += math.exp(_log_binom_pmf(k, n, p0))
    return min(1.0, total)


def binomial_pvalue_lower(wins: int, n: int, p0: float) -> Optional[float]:
    """P(X <= wins) bajo H0: p = p0. Para detectar setups estructuralmente malos."""
    if n <= 0:
        return None
    if not (0.0 <= p0 <= 1.0):
        raise ValueError(f"p0 fuera de [0,1]: {p0}")
    total = 0.0
    for k in range(0, wins + 1):
        total += math.exp(_log_binom_pmf(k, n, p0))
    return min(1.0, total)


# ===========================================================================
# Correccion por comparaciones multiples
# ===========================================================================

def benjamini_hochberg(pvalues: Sequence[Optional[float]],
                       alpha: float = 0.05) -> list[dict]:
    """Benjamini-Hochberg (control de FDR) sobre una familia de p-valores.

    Devuelve una lista de dicts con `index`, `p`, `q` (p ajustado) y
    `rejected`. Los `None` se conservan en su posicion y nunca se rechazan:
    un setup sin muestra no puede declararse ganador.

    POR QUE: un motor de mejora continua prueba decenas de variantes de
    parametros a la vez. Con alpha=0.05 y 40 pruebas independientes, esperar
    2 falsos positivos "significativos" es aritmetica, no suerte. Sin esta
    correccion el motor de auto-mejora ASCIENDE ruido y lo consolida.
    """
    results: list[dict] = [
        {"index": i, "p": p, "q": None, "rejected": False}
        for i, p in enumerate(pvalues)
    ]
    valid = [(i, p) for i, p in enumerate(pvalues) if p is not None]
    if not valid:
        return results

    m = len(valid)
    ordered = sorted(valid, key=lambda t: t[1])

    # p ajustado (q-value) recorriendo de mayor a menor y acumulando el minimo.
    prev_q = 1.0
    for rank in range(m, 0, -1):
        idx, p = ordered[rank - 1]
        q = min(prev_q, p * m / rank)
        q = min(1.0, q)
        results[idx]["q"] = q
        prev_q = q

    # Umbral BH: el mayor k tal que p_(k) <= k/m * alpha. Todo lo anterior pasa.
    threshold_rank = 0
    for rank in range(1, m + 1):
        _, p = ordered[rank - 1]
        if p <= (rank / m) * alpha:
            threshold_rank = rank
    if threshold_rank:
        for rank in range(1, threshold_rank + 1):
            idx, _ = ordered[rank - 1]
            results[idx]["rejected"] = True
    return results


def bonferroni(pvalues: Sequence[Optional[float]],
               alpha: float = 0.05) -> list[dict]:
    """Bonferroni (control de FWER). Mas conservador que BH.

    Se usa para lo caro de equivocarse: ASCENDER un setup a tamano completo.
    BH se usa para lo barato: retirar un setup (solo se deja de operar).
    """
    valid = [p for p in pvalues if p is not None]
    m = len(valid) if valid else 1
    out: list[dict] = []
    for i, p in enumerate(pvalues):
        if p is None:
            out.append({"index": i, "p": None, "adjusted": None, "rejected": False})
        else:
            adj = min(1.0, p * m)
            out.append({"index": i, "p": p, "adjusted": adj, "rejected": adj <= alpha})
    return out


def looks_alpha(n_looks: int, base_alpha: float = 0.05) -> float:
    """Alpha penalizado por numero de miradas repetidas sobre el mismo setup.

    Mirar el win rate despues de cada operacion es ejecutar el mismo test
    binario N veces; el falso positivo acumulado crece con N. Bonferroni sobre
    miradas es tosco pero honesto, y lo importante es que el umbral se VUELVA
    mas exigente cuanto mas se insista.
    """
    if n_looks < 1:
        raise ValueError("n_looks debe ser >= 1")
    return base_alpha / n_looks


def geometric_checkpoints(min_n: int, factor: int = 2,
                          max_n: int = 100_000) -> list[int]:
    """Puntos geometricos (200, 400, 800...) en los que SI se decide.

    Entre checkpoint y checkpoint el veredicto se congela. Es lo que convierte
    "mirar despues de cada trade" (cientos de tests) en "mirar 5 veces".
    """
    if min_n < 1:
        raise ValueError("min_n debe ser >= 1")
    out: list[int] = []
    n = min_n
    while n <= max_n:
        out.append(n)
        n *= factor
    return out


# ===========================================================================
# Matematica dura de las opciones binarias
# ===========================================================================

def breakeven_winrate(payout: float) -> Optional[float]:
    """Win rate minimo para no perder dinero: 1 / (1 + payout).

    payout 0.85 -> 0.5405. payout 0.80 -> 0.5556. payout 0.70 -> 0.5882.

    Este es EL numero del negocio. Un broker que paga 85% y cobra 100% te
    obliga a acertar mas de la mitad de las veces solo para quedar a cero:
    a 50% de aciertos pierdes 7.5 centavos por cada dolar apostado, por
    estructura y no por mala suerte. Ninguna "mejora" del sistema tiene
    sentido si no se mide contra esta linea.
    """
    if payout is None or payout <= 0:
        return None
    return 1.0 / (1.0 + payout)


def expectancy_per_unit(winrate: Optional[float], payout: float) -> Optional[float]:
    """Expectancy por unidad apostada: wr*payout - (1-wr).

    None si winrate es None (sin muestra no hay expectancy, no hay 0.0).
    """
    if winrate is None or payout is None:
        return None
    return winrate * payout - (1.0 - winrate)


def profit_factor(wins: int, losses: int, payout: float) -> Optional[float]:
    """Beneficio bruto / perdida bruta. `inf` si no hay perdedoras, None si n=0."""
    if wins + losses <= 0:
        return None
    if losses == 0:
        return math.inf if wins > 0 else None
    return (wins * payout) / losses


def kelly_fraction(winrate: float, payout: float) -> Optional[float]:
    """Kelly para payoff binario: (p*(b+1) - 1) / b, con b = payout.

    Devuelve None o 0.0 cuando no hay edge: Kelly negativo significa "no
    apostar", nunca "apostar al otro lado".
    """
    if payout is None or payout <= 0 or winrate is None:
        return None
    f = (winrate * (payout + 1.0) - 1.0) / payout
    return f if f > 0 else 0.0


def fractional_kelly(winrate: float, payout: float, fraction: float = 0.25,
                     cap: float = 0.02) -> float:
    """Kelly fraccionado y topado. El sizing real del sistema.

    Kelly pleno maximiza el crecimiento esperado pero asume que conoces `p`
    exactamente, y no lo conocemos: lo estimamos con un IC que puede ser de
    10 puntos de ancho. Kelly pleno sobre una p sobreestimada arruina. Por eso
    (a) se fracciona y (b) se topa por config al porcentaje maximo por
    operacion. Ambos limites se aplican: el resultado es el minimo.
    """
    full = kelly_fraction(winrate, payout)
    if not full:
        return 0.0
    return min(full * fraction, cap)


# ===========================================================================
# Metricas de serie temporal / racha
# ===========================================================================

def max_drawdown_pct(equity_curve: Sequence[float]) -> float:
    """Maximo drawdown en %. 0.0 si la curva esta vacia o nunca bajo del pico."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak * 100.0
            if dd > worst:
                worst = dd
    return worst


def longest_streak(outcomes: Sequence[bool]) -> tuple[int, int]:
    """(racha de True mas larga, racha de False mas larga).

    CORRECCION: `backtester.py` reportaba `longest_losing_streak =
    consecutive_losses`, que es la racha VIGENTE al final del backtest, no la
    mas larga. Un backtest que termina en racha ganadora reportaba 0 perdidas
    seguidas aunque hubiera tenido 12 en el medio. La racha maxima es lo que
    dimensiona el riesgo de ruina; la vigente no dice nada.
    """
    best_true = best_false = 0
    cur_true = cur_false = 0
    for value in outcomes:
        if value:
            cur_true += 1
            cur_false = 0
            best_true = max(best_true, cur_true)
        else:
            cur_false += 1
            cur_true = 0
            best_false = max(best_false, cur_false)
    return best_true, best_false


def binary_sharpe(results: Sequence[float]) -> Optional[float]:
    """Ratio expectancy/desviacion sobre el PnL por operacion.

    No es un Sharpe anualizado (no tiene sentido sin frecuencia fijada): es la
    consistencia del payoff. Un 0.05 con desviacion 0.9 es mucho mas fiable
    que un 0.09 con desviacion 1.4, y el win rate solo no lo distingue.
    """
    values = [r for r in results if r is not None]
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return None
    return mean / sd


def mean_confidence_interval(values: Sequence[float],
                             z: float = Z_95_TWO_SIDED
                             ) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """(media, limite inferior, limite superior). None si n<2."""
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n < 2:
        return (vals[0] if n == 1 else None), None, None
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    margin = z * math.sqrt(var / n)
    return mean, mean - margin, mean + margin


def summarize_binomial(wins: int, n: int, payout: float,
                       z: float = Z_95_TWO_SIDED) -> dict:
    """Resumen completo de un bucket. Es lo que consume el gate de edge.

    Todo en un solo sitio para que ningun consumidor pueda elegir mirar solo
    el win rate puntual y olvidarse del intervalo -- que es exactamente lo que
    hacia `EdgeValidatorAgent.validate()` (punto 4 de la auditoria).
    """
    be = breakeven_winrate(payout)
    if n <= 0:
        return {
            "n": 0, "wins": 0, "losses": 0,
            "win_rate": None, "win_rate_lower": None, "win_rate_upper": None,
            "payout": payout, "break_even": be,
            "expectancy": None, "expectancy_lower": None,
            "profit_factor": None, "pvalue_vs_breakeven": None,
            "edge_proven": False, "no_edge_proven": False,
        }
    losses = n - wins
    wr = wins / n
    lo, hi = wilson_interval(wins, n, z)
    exp = expectancy_per_unit(wr, payout)
    exp_lo = expectancy_per_unit(lo, payout) if lo is not None else None
    return {
        "n": n,
        "wins": wins,
        "losses": losses,
        "win_rate": wr,
        "win_rate_lower": lo,
        "win_rate_upper": hi,
        "payout": payout,
        "break_even": be,
        "expectancy": exp,
        "expectancy_lower": exp_lo,
        "profit_factor": profit_factor(wins, losses, payout),
        # H0: el setup acierta exactamente lo justo para no perder.
        "pvalue_vs_breakeven": binomial_pvalue_upper(wins, n, be) if be else None,
        # GANADOR solo si hasta el pesimismo del IC supera el break-even.
        "edge_proven": bool(be is not None and lo is not None and lo > be),
        # PERDEDOR solo si hasta el optimismo del IC queda por debajo.
        "no_edge_proven": bool(be is not None and hi is not None and hi < be),
    }
