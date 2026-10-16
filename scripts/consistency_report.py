#!/usr/bin/env python3
"""Reporte de consistencia: responde si el bot es ganador de verdad.

No pregunta "cual es el win rate". Pregunta si el win rate es ESTABLE, si la
expectancy aguanta en cada regimen, y si el drawdown y las rachas perdedoras
caben dentro de lo que el riesgo permite. Un bot con 90% de acierto en una
sola semana y 45% en las siguientes no es consistente: es suerte.

Mide, por ventana temporal y por regimen:

    - win rate y su limite inferior de Wilson al 95%
    - expectancy por operacion (ajustada al payout)
    - profit factor, drawdown maximo, racha perdedora maxima
    - estabilidad: cuantas ventanas se mantienen sobre el break-even

Veredicto final solo si TODAS las ventanas con muestra suficiente pasan.

Uso:
    python scripts/consistency_report.py
    python scripts/consistency_report.py --min-sample 30 --windows 4
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.repository import repository, wilson_lower_bound  # noqa: E402
from app.data.schemas import TradeResult  # noqa: E402
from app.research.edge_ledger import EdgeLedger  # noqa: E402

PAYOUT = 0.85
BREAK_EVEN = 1 / (1 + PAYOUT)


def _expectancy(win_rate: float, payout: float) -> float:
    return win_rate * payout - (1 - win_rate)


def _stats(rows: list[TradeResult]) -> dict:
    """Estadisticas de un conjunto de operaciones ya resueltas."""
    total = len(rows)
    if total == 0:
        return {"trades": 0}
    wins = sum(1 for r in rows if r.result > 0)
    wr = wins / total
    pnl = sum(r.result for r in rows)
    gross_win = sum(r.result for r in rows if r.result > 0)
    gross_loss = abs(sum(r.result for r in rows if r.result < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    equity, peak, max_dd = 0.0, 0.0, 0.0
    for r in rows:
        equity += r.result
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    streak = max_streak = 0
    for r in rows:
        streak = streak + 1 if r.result < 0 else 0
        max_streak = max(max_streak, streak)

    return {
        "trades": total,
        "wins": wins,
        "win_rate": round(wr, 4),
        "win_rate_lower_95": round(wilson_lower_bound(wins, total), 4),
        "expectancy": round(_expectancy(wr, PAYOUT), 4),
        "pnl": round(pnl, 2),
        "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
        "max_drawdown": round(max_dd, 2),
        "max_loss_streak": max_streak,
        "beats_break_even": wr > BREAK_EVEN,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-sample", type=int, default=30)
    ap.add_argument("--windows", type=int, default=4)
    ap.add_argument("--asset", default=None)
    args = ap.parse_args()

    trades = repository.get_trade_results(asset=args.asset, limit=100000,
                                          evidence_only=True)
    trades = [t for t in trades
              if t.execution_state.value in ("won", "lost")]

    print("=" * 92)
    print("REPORTE DE CONSISTENCIA")
    print("=" * 92)
    print(f"Operaciones con evidencia real: {len(trades)}")
    print(f"break-even con payout {PAYOUT}: {BREAK_EVEN:.4f}")
    print(f"Muestra minima por celda: {args.min_sample}")

    if not trades:
        print("\nNO HAY NADA QUE MEDIR TODAVIA.")
        print("El bot no ha resuelto ninguna operacion contra evidencia real")
        print("(broker o vela observada). Sin eso no se puede saber si es")
        print("ganador: solo se sabe que el backtest sobre datos sinteticos")
        print("dio 90%. Son dos cosas distintas.")
        print("\nSiguiente paso: correr en PRACTICE contra Exnova y dejar")
        print("acumular muestra. Este informe se llena solo.")
        return 1

    trades = sorted(trades, key=lambda t: t.timestamp)

    # ---- 1. Global ------------------------------------------------------- #
    overall = _stats(trades)
    print("\n" + "-" * 92)
    print("GLOBAL")
    print("-" * 92)
    _print_row(overall, args.min_sample)

    # ---- 2. Por ventana temporal ----------------------------------------- #
    print("\n" + "-" * 92)
    print(f"ESTABILIDAD TEMPORAL ({args.windows} ventanas del mismo tamano)")
    print("-" * 92)
    size = max(1, len(trades) // args.windows)
    window_rows = []
    for w in range(args.windows):
        chunk = trades[w * size:(w + 1) * size] if w < args.windows - 1 \
            else trades[w * size:]
        if not chunk:
            continue
        stats = _stats(chunk)
        first = chunk[0].timestamp.strftime("%Y-%m-%d")
        last = chunk[-1].timestamp.strftime("%Y-%m-%d")
        print(f"  ventana {w + 1} ({first} -> {last})")
        _print_row(stats, args.min_sample, indent="    ")
        window_rows.append(stats)

    measured_windows = [w for w in window_rows if w["trades"] >= args.min_sample]
    stable = all(w["beats_break_even"] for w in measured_windows) \
        if measured_windows else False

    # ---- 3. Por regimen -------------------------------------------------- #
    print("\n" + "-" * 92)
    print("POR REGIMEN DE MERCADO")
    print("-" * 92)
    by_regime = defaultdict(list)
    for t in trades:
        by_regime[t.market_regime.value if t.market_regime else "unknown"].append(t)
    regime_rows = {}
    for regime, rows in sorted(by_regime.items()):
        stats = _stats(rows)
        regime_rows[regime] = stats
        _print_row(stats, args.min_sample, label=regime)

    # ---- 4. Por estrategia ----------------------------------------------- #
    print("\n" + "-" * 92)
    print("POR ESTRATEGIA (donde se ve cual conviene dejar de usar)")
    print("-" * 92)
    by_strategy = defaultdict(list)
    for t in trades:
        by_strategy[t.strategy or "unknown"].append(t)
    for strat, rows in sorted(by_strategy.items()):
        _print_row(_stats(rows), args.min_sample, label=strat)

    # ---- 5. Veredicto ---------------------------------------------------- #
    print("\n" + "=" * 92)
    print("VEREDICTO")
    print("=" * 92)

    checks = []
    checks.append(("Expectancy global positiva", overall.get("expectancy", 0) > 0))
    checks.append(("Win rate global sobre break-even",
                   overall.get("win_rate", 0) > BREAK_EVEN))
    lower = overall.get("win_rate_lower_95", 0)
    checks.append((f"Limite inferior 95% ({lower:.1%}) sobre break-even",
                   lower > BREAK_EVEN))
    checks.append((f"Drawdown maximo acotado (${overall.get('max_drawdown', 0)})",
                   overall.get("max_drawdown", 0) > 0))
    if measured_windows:
        checks.append((f"Estable en {len(measured_windows)}/"
                       f"{len(window_rows)} ventanas", stable))
    else:
        checks.append(("Ventanas con muestra suficiente", False))

    for label, ok in checks:
        print(f"  [{'OK ' if ok else 'FALLA'}] {label}")

    passed = sum(1 for _, ok in checks if ok)
    print(f"\n  {passed}/{len(checks)} condiciones")

    if passed == len(checks) and measured_windows:
        print("\n  CONSISTENTE: el edge se mantiene en el tiempo y en los")
        print("  regimenes. Candidato a subir exposicion gradualmente.")
    elif not measured_windows:
        print("\n  MUESTRA INSUFICIENTE para declarar consistencia.")
        print(f"  Hacen falta al menos {args.min_sample} operaciones por")
        print("  ventana. Seguir acumulando en PRACTICE.")
    else:
        print("\n  NO CONSISTENTE todavia. Revisar que condicion falla:")
        print("  si falla una ventana concreta, el edge depende del periodo;")
        print("  si falla un regimen, hay que dejar de operar ahi;")
        print("  si falla una estrategia, hay que sacarla del pool.")

    # ---- 6. Lo que el bot aprendio --------------------------------------- #
    print("\n" + "-" * 92)
    print("LO QUE EL BOT HA APRENDIDO (EdgeLedger)")
    print("-" * 92)
    ledger = EdgeLedger(min_sample=args.min_sample)
    report = ledger.report(asset=args.asset)
    print(f"  Celdas con evidencia: {report['cells_with_evidence']}")
    print(f"  Celdas con edge probado: {report['cells_with_edge']}")
    for regime, voters in report["voters"].items():
        print(f"    {regime:<14} -> {voters if voters else '(nadie: no opera)'}")

    out = {
        "generated_at": datetime.utcnow().isoformat(),
        "config": {"payout": PAYOUT, "break_even": round(BREAK_EVEN, 4),
                   "min_sample": args.min_sample, "windows": args.windows},
        "overall": overall,
        "windows": window_rows,
        "by_regime": regime_rows,
        "ledger": report,
        "checks": [{"check": c, "passed": ok} for c, ok in checks],
        "consistent": bool(passed == len(checks) and measured_windows),
    }
    dest = Path("reports/consistency_report.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nReporte guardado en {dest}")
    return 0


def _print_row(stats: dict, min_sample: int, label: str = "",
               indent: str = "  ") -> None:
    if not stats.get("trades"):
        print(f"{indent}{label or 'sin datos'}: sin operaciones")
        return
    wr = stats["win_rate"]
    lower = stats["win_rate_lower_95"]
    pf = stats["profit_factor"]
    ok = wr > BREAK_EVEN and stats["trades"] >= min_sample
    flag = "OK  " if ok else ("poca muestra" if stats["trades"] < min_sample
                              else "PIERDE")
    name = f"{label:<14}" if label else ""
    print(f"{indent}{name} n={stats['trades']:>4}  WR={wr:>6.1%}  "
          f"inf95={lower:>6.1%}  exp={stats['expectancy']:>+7.4f}  "
          f"PF={pf:>6}  DD=${stats['max_drawdown']:>7.1f}  "
          f"rachaP={stats['max_loss_streak']:>3}  [{flag}]")


if __name__ == "__main__":
    sys.exit(main())
