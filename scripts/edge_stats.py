# -*- coding: utf-8 -*-
"""
Evaluador estadistico del historial de trades.

Responde una sola pregunta: de todo lo que el bot "aprendio", que sobrevive
a un intervalo de confianza y que es ruido.

Uso:
    python scripts/edge_stats.py [ruta_trade_history.json]
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

# Payout medio observado en los wins reales del historial.
# Con payout b, el winrate de break-even es 1 / (1 + b).
DEFAULT_PAYOUT = 0.838

# Etiquetas que no provienen de operativa real y contaminan el dataset.
SYNTHETIC_PATTERNS = {"demo"}


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson al 95%. Mas fiable que el normal con n pequeno."""
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def samples_needed(p_true: float, p_null: float, alpha: float = 0.05,
                   power: float = 0.80) -> int:
    """Trades necesarios para distinguir p_true de p_null con la potencia dada."""
    if abs(p_true - p_null) < 1e-9:
        return 10 ** 9
    z_a, z_b = 1.96, 0.84  # dos colas al 5%, potencia 80%
    pooled = (p_true + p_null) / 2
    num = z_a * math.sqrt(2 * pooled * (1 - pooled)) + z_b * math.sqrt(
        p_true * (1 - p_true) + p_null * (1 - p_null)
    )
    return math.ceil((num / (p_true - p_null)) ** 2)


def verdict(lo: float, hi: float, breakeven: float) -> str:
    """Solo hay conclusion cuando el intervalo entero cae de un lado."""
    if lo > breakeven:
        return "EDGE REAL"
    if hi < breakeven:
        return "PERDEDOR REAL"
    return "RUIDO (indistinguible)"


def group_stats(trades: list[dict], key: str) -> dict[str, tuple[int, int, float]]:
    out: dict[str, list] = defaultdict(lambda: [0, 0, 0.0])
    for t in trades:
        k = str(t.get(key, "?"))
        out[k][0] += 1
        out[k][1] += 1 if t.get("result") == "WIN" else 0
        out[k][2] += float(t.get("pnl", 0.0))
    return {k: (v[0], v[1], v[2]) for k, v in out.items()}


def report_group(title: str, stats: dict, breakeven: float, min_n: int = 1) -> None:
    print(f"\n{title}")
    print(f"  {'grupo':<24} {'n':>5} {'wr':>7} {'IC95%':>16} {'pnl':>9}  veredicto")
    print(f"  {'-' * 24} {'-' * 5} {'-' * 7} {'-' * 16} {'-' * 9}  {'-' * 22}")
    rows = sorted(stats.items(), key=lambda kv: -kv[1][0])
    for name, (n, w, pnl) in rows:
        if n < min_n:
            continue
        lo, hi = wilson_interval(w, n)
        print(
            f"  {name[:24]:<24} {n:>5} {100 * w / n:>6.1f}% "
            f"[{100 * lo:>5.1f}%,{100 * hi:>5.1f}%] {pnl:>9.2f}  {verdict(lo, hi, breakeven)}"
        )


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("bot/brain/trade_history.json")
    if not path.exists():
        print(f"No existe {path}")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    trades = data.get("trades", [])
    if not trades:
        print("Historial vacio")
        return 1

    # Payout implicito real, no el asumido.
    ratios = [
        t["pnl"] / t["amount"]
        for t in trades
        if t.get("result") == "WIN" and t.get("amount")
    ]
    payout = sum(ratios) / len(ratios) if ratios else DEFAULT_PAYOUT
    breakeven = 1 / (1 + payout)

    real = [t for t in trades if t.get("pattern") not in SYNTHETIC_PATTERNS]
    synthetic = len(trades) - len(real)

    n = len(trades)
    w = sum(1 for t in trades if t.get("result") == "WIN")
    lo, hi = wilson_interval(w, n)

    print("=" * 78)
    print("EVALUACION ESTADISTICA DEL HISTORIAL")
    print("=" * 78)
    print(f"Archivo            : {path}")
    print(f"Trades totales     : {n}   (sinteticos/'demo' descartables: {synthetic})")
    print(f"Winrate global     : {100 * w / n:.2f}%  IC95% [{100 * lo:.2f}%, {100 * hi:.2f}%]")
    print(f"Payout medio real  : {payout:.4f}")
    print(f"Break-even winrate : {100 * breakeven:.2f}%")
    print(f"PnL acumulado      : {sum(t.get('pnl', 0) for t in trades):.2f}")
    print(f"Esperanza por trade: {(w / n) * payout - (1 - w / n):.4f} x stake")
    print(f"VEREDICTO GLOBAL   : {verdict(lo, hi, breakeven)}")

    # Cuantos trades harian falta para demostrar un edge modesto.
    print("\nPOTENCIA ESTADISTICA (trades necesarios vs. moneda al aire del 50%):")
    for target in (0.55, 0.57, 0.60, 0.65):
        print(f"  demostrar winrate {100 * target:.0f}% -> {samples_needed(target, 0.50):>6,} trades")

    # Diversidad de features: una feature constante no puede ensenar nada.
    print("\nSALUD DE LAS FEATURES (una constante = 0 informacion para el aprendizaje):")
    for feat in ("rsi_at_touch", "zone_strength", "trend_aligned", "pattern", "asset"):
        vals = [t.get(feat) for t in trades]
        uniq = len(set(map(str, vals)))
        top = max(((str(v), vals.count(v)) for v in set(vals)), key=lambda kv: kv[1])
        pct = 100 * top[1] / n
        flag = "  <-- CONSTANTE, INUTILIZABLE" if pct > 80 else ""
        print(f"  {feat:<16} valores distintos={uniq:<4} moda='{top[0][:18]}' cubre {pct:.1f}%{flag}")

    report_group("POR PATRON DE VELA:", group_stats(trades, "pattern"), breakeven)
    report_group("POR DIRECCION:", group_stats(trades, "direction"), breakeven)
    report_group("POR ACTIVO (n>=8):", group_stats(trades, "asset"), breakeven, min_n=8)

    print("\nNOTA: 'EDGE REAL' exige que el intervalo completo supere el break-even.")
    print("Cualquier regla ajustada sobre un grupo marcado RUIDO es sobreajuste.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
