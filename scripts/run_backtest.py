# -*- coding: utf-8 -*-
"""
Ejecuta el playbook completo de estrategias contra todo el historico
descargado y compara mercado sintetico (OTC) frente a mercado real.

Uso:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --payout 0.85 --only triple_ema_15_30_60
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.backtest.replay import BacktestConfig, ReplayEngine   # noqa: E402
from bot.backtest.strategies_book import all_strategies         # noqa: E402

HISTORY_DIR = ROOT / "bot" / "data" / "history"


def is_synthetic(name: str) -> bool:
    return "-OTC" in name.upper()


def load() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if not HISTORY_DIR.exists():
        return out
    for p in sorted(HISTORY_DIR.glob("*_60.*")):
        if p.suffix not in (".parquet", ".csv"):
            continue
        asset = p.stem[:-3]
        try:
            df = (pd.read_parquet(p) if p.suffix == ".parquet"
                  else pd.read_csv(p, index_col=0, parse_dates=True))
        except Exception as e:
            print(f"  aviso: no se pudo leer {p.name}: {e}")
            continue
        if len(df) >= 1000:
            out[asset] = df.sort_index()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Backtest del playbook de estrategias")
    ap.add_argument("--payout", type=float, default=0.86)
    ap.add_argument("--only", default=None, help="Ejecutar solo una estrategia por nombre")
    ap.add_argument("--max-trades", type=int, default=None)
    args = ap.parse_args()

    data = load()
    if not data:
        print(f"No hay historico en {HISTORY_DIR}. Descarga primero con fetch_history.py")
        return 1

    synth = {k: v for k, v in data.items() if is_synthetic(k)}
    real = {k: v for k, v in data.items() if not is_synthetic(k)}

    cfg = BacktestConfig(payout=args.payout, warmup_bars=250,
                         min_bars_between_trades=3, max_trades=args.max_trades)
    engine = ReplayEngine(cfg)

    print("=" * 94)
    print("BACKTEST DEL PLAYBOOK DE ESTRATEGIAS INVESTIGADAS")
    print("=" * 94)
    print(f"Payout {args.payout:.3f}  ->  break-even {100 * cfg.breakeven_winrate:.2f}%")
    print(f"Sinteticos OTC : {len(synth)} activos -> {', '.join(sorted(synth)) or '-'}")
    print(f"Mercado real   : {len(real)} activos -> {', '.join(sorted(real)) or '-'}")
    print("\nSolo cuenta el resultado FUERA DE MUESTRA (ultimo 30% del historico).\n")

    strategies = [s for s in all_strategies()
                  if args.only is None or s.name == args.only]
    if not strategies:
        print(f"No existe la estrategia '{args.only}'")
        return 1

    header = (f"{'estrategia':<28}{'mercado':<12}{'n_oos':>7}{'wr_in':>8}"
              f"{'wr_oos':>8}{'pnl':>9}{'dd':>8}  veredicto")
    print(header)
    print("-" * 94)

    summary = []
    for strat in strategies:
        for label, group in (("SINTETICO", synth), ("REAL", real)):
            if not group:
                continue
            result = engine.run_many(strat, group.items())
            ins = result.stats("in_sample")
            oos = result.stats("out_of_sample")
            if oos["n"] == 0:
                print(f"{strat.name[:26]:<28}{label:<12}{'sin operaciones':>40}")
                continue
            print(f"{strat.name[:26]:<28}{label:<12}{oos['n']:>7}"
                  f"{100 * ins['winrate']:>7.1f}%{100 * oos['winrate']:>7.1f}%"
                  f"{oos['pnl']:>9.1f}{oos['max_drawdown']:>8.1f}  {oos['verdict']}")
            summary.append((strat.name, label, oos))

    print("-" * 94)
    winners = [s for s in summary if s[2]["verdict"] == "EDGE REAL"]
    print()
    if winners:
        print(f"ESTRATEGIAS CON EDGE DEMOSTRADO ({len(winners)}):")
        for name, market, st in winners:
            print(f"  {name} en {market}: {100 * st['winrate']:.1f}% "
                  f"IC95%[{100 * st['ci_low']:.1f}%, {100 * st['ci_high']:.1f}%] n={st['n']}")
    else:
        print("NINGUNA estrategia demuestra edge fuera de muestra en ningun mercado.")
        if summary:
            best = max(summary, key=lambda s: s[2]["winrate"])
            print(f"La mejor fue {best[0]} en {best[1]}: {100 * best[2]['winrate']:.1f}% "
                  f"(n={best[2]['n']}), IC95% baja hasta {100 * best[2]['ci_low']:.1f}% "
                  f"< {100 * cfg.breakeven_winrate:.1f}% necesario.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
