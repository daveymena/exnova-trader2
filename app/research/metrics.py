"""Statistical metrics used to decide whether a strategy has real edge."""
from math import sqrt


def break_even_win_rate(payout: float) -> float:
    """Minimum win rate for a binary payout before fees and slippage."""
    if payout <= 0:
        raise ValueError("payout must be positive")
    return 1.0 / (1.0 + payout)


def wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    """Conservative lower confidence bound for a binomial win rate.

    The bound is intentionally used instead of the observed rate when
    validating a live edge, so a small lucky sample cannot authorize trading.
    """
    if total < 0 or wins < 0 or wins > total:
        raise ValueError("wins and total must describe a valid sample")
    if total == 0:
        return 0.0

    observed = wins / total
    denominator = 1 + z * z / total
    center = observed + z * z / (2 * total)
    spread = z * sqrt(
        (observed * (1 - observed) / total) + (z * z / (4 * total * total))
    )
    return (center - spread) / denominator
