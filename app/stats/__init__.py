# -*- coding: utf-8 -*-
"""Nucleo estadistico de `app/`.

Existe porque el gate de edge se rompia con NameError (`wilson_lower_bound` no
estaba definida en ningun sitio) y porque, cuando no se rompia, miraba el win
rate puntual en lugar de su cota inferior. Ver `app/stats/core.py`.
"""
from app.stats.core import (
    Z_95_ONE_SIDED,
    Z_95_TWO_SIDED,
    Z_99_TWO_SIDED,
    benjamini_hochberg,
    binary_sharpe,
    binomial_pvalue_lower,
    binomial_pvalue_upper,
    bonferroni,
    breakeven_winrate,
    expectancy_per_unit,
    fractional_kelly,
    geometric_checkpoints,
    kelly_fraction,
    longest_streak,
    looks_alpha,
    max_drawdown_pct,
    mean_confidence_interval,
    profit_factor,
    summarize_binomial,
    wilson_interval,
    wilson_lower_bound,
    wilson_upper_bound,
    z_from_alpha,
)

__all__ = [
    "Z_95_ONE_SIDED",
    "Z_95_TWO_SIDED",
    "Z_99_TWO_SIDED",
    "benjamini_hochberg",
    "binary_sharpe",
    "binomial_pvalue_lower",
    "binomial_pvalue_upper",
    "bonferroni",
    "breakeven_winrate",
    "expectancy_per_unit",
    "fractional_kelly",
    "geometric_checkpoints",
    "kelly_fraction",
    "longest_streak",
    "looks_alpha",
    "max_drawdown_pct",
    "mean_confidence_interval",
    "profit_factor",
    "summarize_binomial",
    "wilson_interval",
    "wilson_lower_bound",
    "wilson_upper_bound",
    "z_from_alpha",
]
