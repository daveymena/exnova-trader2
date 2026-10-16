#!/usr/bin/env python3
"""Investigacion: mide el edge de cada estrategia y del bot de consenso.

El objetivo es honesto: generar datos sinteticos reproducibles, ejecutar cada
estrategia por separado y el `ConsensusWinningStrategy` sobre exactamente la
misma serie, y comparar win rate, expectancy, profit factor, drawdown y
racha perdedora contra el punto de equilibrio que impone el payout.

Nada de lo que imprime este script alimenta al bot: solo mide.

Uso:
    python scripts/research_consensus_edge.py
    python scripts/research_consensus_edge.py --seeds 5 --candles 3000
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.schemas import Candle, Direction, Timeframe  # noqa: E402
from app.strategies.sr_bounce import SRBounceStrategy  # noqa: E402
from app.strategies.trend_continuation import TrendContinuationStrategy  # noqa: E402
from app.strategies.breakout_retest import BreakoutRetestStrategy  # noqa: E402
from app.strategies.mean_reversion import MeanReversionStrategy  # noqa: E402
from app.strategies.breakout_direct import BreakoutDirectStrategy  # noqa: E402
from app.strategies.consensus_winning import ConsensusWinningStrategy  # noqa: E402

PAYOUT = 0.85
BREAK_EVEN = 1.0 / (1.0 + PAYOUT)   # 0.5405
STAKE = 10.0


@dataclass
class Scenario:
    name: str
    drift: float
    vol: float
    mean_revert: float = 0.0
    anchor: float = 0.0


SCENARIOS = [
    Scenario("tendencia_alcista", drift=0.0008, vol=0.0009),
    Scenario("tendencia_bajista", drift=-0.0008, vol=0.0009),
    Scenario("lateral_rango", drift=0.0, vol=0.0009, mean_revert=0.05, anchor=1.1000),
    Scenario("alta_volatilidad", drift=0.0002, vol=0.0035),
    Scenario("baja_volatilidad", drift=0.0, vol=0.00025, mean_revert=0.08, anchor=1.1000),
    Scenario("choppy_sin_direccion", drift=0.0, vol=0.0012),
]


def generate_series(n: int, scenario: Scenario, seed: int) -> list[Candle]:
    """Serie OHLC M1 reproducible (GBM + opcional anclaje al centro)."""
    rng = random.Random(seed)
    start = datetime(2026, 1, 1, 8, 0, 0)
    price = 1.1000
    candles: list[Candle] = []
    for i in range(n):
        shock = rng.gauss(scenario.drift, scenario.vol)
        if scenario.mean_revert:
            shock += scenario.mean_revert * (scenario.anchor - price) / scenario.anchor
        open_p = price
        close_p = open_p * (1 + shock)
        wick_up = abs(rng.gauss(0, scenario.vol * 0.35))
        wick_dn = abs(rng.gauss(0, scenario.vol * 0.35))
        high_p = max(open_p, close_p) * (1 + wick_up)
        low_p = min(open_p, close_p) * (1 - wick_dn)
        candles.append(Candle(
            asset="EURUSD", timeframe=Timeframe.M1,
            open_time=start + timedelta(minutes=i),
            open=round(open_p, 5), high=round(high_p, 5),
            low=round(low_p, 5), close=round(close_p, 5),
            volume=rng.randint(800, 4000),
        ))
        price = close_p
    return candles


def resample(candles: list[Candle], tf: Timeframe, minutes: int) -> list[Candle]:
    """Agrupa velas M1 en M5/M15 (maximo/minimo reales, no medias)."""
    out: list[Candle] = []
    for base in range(0, len(candles) - minutes + 1, minutes):
        chunk = candles[base:base + minutes]
        out.append(Candle(
            asset="EURUSD", timeframe=tf,
            open_time=chunk[0].open_time,
            open=chunk[0].open,
            high=max(c.high for c in chunk),
            low=min(c.low for c in chunk),
            close=chunk[-1].close,
            volume=sum(c.volume or 0 for c in chunk),
        ))
    return out


@dataclass
class Stats:
    label: str
    trades: int = 0
    wins: int = 0
    pnl: float = 0.0
    peak: float = 0.0
    max_dd: float = 0.0
    max_loss_streak: int = 0
    streak: int = 0
    returns: list = field(default_factory=list)

    def record(self, won: bool, pnl: float):
        self.trades += 1
        self.wins += 1 if won else 0
        self.pnl += pnl
        self.returns.append(pnl)
        self.peak = max(self.peak, self.pnl)
        self.max_dd = max(self.max_dd, self.peak - self.pnl)
        if won:
            self.streak = 0
        else:
            self.streak += 1
            self.max_loss_streak = max(self.max_loss_streak, self.streak)

    def as_dict(self) -> dict:
        wr = self.wins / self.trades if self.trades else 0.0
        expectancy = (wr * PAYOUT - (1 - wr)) if self.trades else 0.0
        gross_win = sum(r for r in self.returns if r > 0)
        gross_loss = abs(sum(r for r in self.returns if r < 0))
        pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
        sharpe = 0.0
        if len(self.returns) > 1 and statistics.pstdev(self.returns) > 0:
            sharpe = statistics.mean(self.returns) / statistics.pstdev(self.returns) * math.sqrt(252)
        return {
            "strategy": self.label,
            "trades": self.trades,
            "wins": self.wins,
            "win_rate": round(wr, 4),
            "pnl": round(self.pnl, 2),
            "expectancy_per_trade": round(expectancy, 4),
            "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
            "max_drawdown": round(self.max_dd, 2),
            "max_loss_streak": self.max_loss_streak,
            "sharpe": round(sharpe, 3),
            "beats_break_even": wr > BREAK_EVEN if self.trades else False,
        }


# Ventana maxima de contexto. Sin tope, cada evaluate recalcula ADX y el
# percentil de ATR sobre el prefijo completo: el backtest entero pasaba a
# O(n^2) y tardaba mas de 10 minutos por escenario. Es el mismo criterio que
# usa bot/backtest/strategies_book.py con su LOOKBACK.
LOOKBACK_M1 = 400
LOOKBACK_M5 = 120
LOOKBACK_M15 = 60


def backtest_one(strategy, m15, m5, m1, label: str, min_bars: int = 60) -> Stats:
    """Recorre la serie y resuelve cada trade contra la vela de expiracion."""
    st = Stats(label)
    cooldown = 0
    for i in range(min_bars, len(m1)):
        if cooldown > 0:
            cooldown -= 1
            continue
        # El contexto de cada timeframe incluye la vela en curso: la ultima
        # vela del contexto tiene que ser "ahora", que es lo que esperan las
        # estrategias (miran m1_sorted[-1]). Excluirla desplazaba la senal una
        # vela y media el resultado contra la vela equivocada.
        idx15 = i // 15 + 1
        idx5 = i // 5 + 1
        ctx15 = m15[max(0, idx15 - LOOKBACK_M15): idx15]
        ctx5 = m5[max(0, idx5 - LOOKBACK_M5): idx5]
        ctx1 = m1[max(0, i + 1 - LOOKBACK_M1): i + 1]
        try:
            sig = strategy.evaluate(ctx15, ctx5, ctx1, "EURUSD")
        except Exception:
            continue
        direction = sig.get("direction", Direction.NO_TRADE)
        if direction == Direction.NO_TRADE:
            continue
        expiry = int(sig.get("expiry") or 180)
        bars = max(1, round(expiry / 60))
        j = i + bars
        if j >= len(m1):
            continue
        entry = m1[i].close
        exit_p = m1[j].close
        if exit_p == entry:
            continue
        won = exit_p > entry if direction == Direction.CALL else exit_p < entry
        st.record(won, STAKE * PAYOUT if won else -STAKE)
        cooldown = bars - 1  # nunca solapamos operaciones
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--candles", type=int, default=2000)
    ap.add_argument("--seed-offset", type=int, default=0)
    args = ap.parse_args()

    strategies = {
        "sr_bounce": SRBounceStrategy(),
        "trend_continuation": TrendContinuationStrategy(),
        "breakout_retest": BreakoutRetestStrategy(),
        "mean_reversion": MeanReversionStrategy(),
        "breakout_direct": BreakoutDirectStrategy(),
        "CONSENSO_WINNING": ConsensusWinningStrategy(),
    }

    print("=" * 96)
    print("INVESTIGACION DE EDGE - ESTRATEGIAS VS BOT DE CONSENSO")
    print("=" * 96)
    print(f"payout={PAYOUT}  break-even={BREAK_EVEN:.4f}  stake=${STAKE}  "
          f"candles={args.candles}  seeds={args.seeds}")
    print("Resolucion: cierre de la vela de expiracion (sin look-ahead, sin suposiciones).")

    aggregate: dict[str, list[dict]] = {k: [] for k in strategies}
    all_rows: list[dict] = []

    for sc in SCENARIOS:
        print(f"\n### {sc.name}  (drift={sc.drift} vol={sc.vol})")
        for seed in range(1 + args.seed_offset, args.seeds + 1 + args.seed_offset):
            m1 = generate_series(args.candles, sc, seed)
            m5 = resample(m1, Timeframe.M5, 5)
            m15 = resample(m1, Timeframe.M15, 15)
            for name, strat in strategies.items():
                st = backtest_one(strat, m15, m5, m1, name)
                row = st.as_dict()
                row["scenario"] = sc.name
                row["seed"] = seed
                all_rows.append(row)
                aggregate[name].append(row)

    print("\n" + "=" * 96)
    print("RESULTADO AGREGADO POR ESTRATEGIA (todas las semillas y escenarios)")
    print("=" * 96)
    header = (f"{'estrategia':<20}{'trades':>8}{'WR%':>8}{'exp/trade':>11}"
              f"{'PF':>8}{'PnL':>11}{'maxDD':>9}{'rachaP':>8}{'sharpe':>8}  ok?")
    print(header)
    print("-" * len(header))

    summary = {}
    for name, rows in aggregate.items():
        trades = sum(r["trades"] for r in rows)
        wins = sum(r["wins"] for r in rows)
        pnl = sum(r["pnl"] for r in rows)
        wr = wins / trades if trades else 0.0
        exp = (wr * PAYOUT - (1 - wr)) if trades else 0.0
        gw = sum(STAKE * PAYOUT for r in rows for _ in range(r["wins"]))
        gl = sum(STAKE for r in rows for _ in range(r["trades"] - r["wins"]))
        pf = (gw / gl) if gl > 0 else float("inf")
        maxdd = max((r["max_drawdown"] for r in rows), default=0.0)
        streak = max((r["max_loss_streak"] for r in rows), default=0)
        sharpe = statistics.mean([r["sharpe"] for r in rows]) if rows else 0.0
        ok = "SI" if wr > BREAK_EVEN and pnl > 0 else "no"
        pfs = f"{pf:8.2f}" if pf != float("inf") else f"{'inf':>8}"
        print(f"{name:<20}{trades:>8}{wr*100:>7.1f}%{exp:>11.4f}{pfs}"
              f"{pnl:>11.2f}{maxdd:>9.1f}{streak:>8}{sharpe:>8.2f}  {ok}")
        summary[name] = {
            "trades": trades, "wins": wins, "win_rate": round(wr, 4),
            "expectancy_per_trade": round(exp, 4),
            "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
            "pnl": round(pnl, 2), "max_drawdown": round(maxdd, 2),
            "max_loss_streak": streak, "mean_sharpe": round(sharpe, 3),
            "beats_break_even": bool(wr > BREAK_EVEN and pnl > 0),
        }

    cons = summary["CONSENSO_WINNING"]
    base = max((v for k, v in summary.items() if k != "CONSENSO_WINNING"),
               key=lambda v: v["win_rate"])
    base_name = max((k for k in summary if k != "CONSENSO_WINNING"),
                    key=lambda k: summary[k]["win_rate"])

    print("\n" + "=" * 96)
    print("CONCLUSION")
    print("=" * 96)
    print(f"Mejor estrategia individual : {base_name} "
          f"WR={base['win_rate']*100:.1f}%  exp={base['expectancy_per_trade']:+.4f}")
    print(f"Bot de consenso             : CONSENSO_WINNING "
          f"WR={cons['win_rate']*100:.1f}%  exp={cons['expectancy_per_trade']:+.4f}")
    delta = cons["expectancy_per_trade"] - base["expectancy_per_trade"]
    print(f"Mejora de expectancy        : {delta:+.4f} por trade")
    print(f"Operaciones del consenso    : {cons['trades']} "
          f"(calidad sobre cantidad: {base['trades'] - cons['trades']:+d} vs la mejor individual)")
    if cons["beats_break_even"]:
        print("VEREDICTO: el consenso supera el break-even agregado y es candidato a forward testing.")
    else:
        print("VEREDICTO: el consenso NO supera el break-even agregado; hay que seguir investigando.")

    out = {
        "generated_at": datetime.utcnow().isoformat(),
        "config": {"payout": PAYOUT, "break_even": round(BREAK_EVEN, 4),
                   "stake": STAKE, "candles": args.candles, "seeds": args.seeds},
        "scenarios": [s.name for s in SCENARIOS],
        "summary": summary,
        "detail": all_rows,
    }
    dest = Path("reports/consensus_edge_research.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2))
    print(f"\nReporte guardado en {dest}")


if __name__ == "__main__":
    main()
