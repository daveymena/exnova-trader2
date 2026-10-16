#!/usr/bin/env python3
"""Auditoria de estrategias: mide el edge real de cada una, por direccion.

No opina: mide. Para cada estrategia cuenta cuantas veces acierta cuando dice
CALL y cuantas cuando dice PUT, sobre la misma serie sintetica y resolviendo
siempre contra la vela de expiracion. Una estrategia cuyo lado PUT acierte
menos que el break-even esta perdiendo dinero de forma sistematica y hay que
arreglarla o quitarla.

Uso:
    BOT_DISABLE_PERSISTENCE=1 python scripts/research_strategy_audit.py
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.schemas import Candle, Direction, Timeframe  # noqa: E402
from app.strategies.sr_bounce import SRBounceStrategy  # noqa: E402
from app.strategies.trend_continuation import TrendContinuationStrategy  # noqa: E402
from app.strategies.breakout_retest import BreakoutRetestStrategy  # noqa: E402
from app.strategies.mean_reversion import MeanReversionStrategy  # noqa: E402
from app.strategies.breakout_direct import BreakoutDirectStrategy  # noqa: E402
from app.agents.market_regime_agent import MarketRegimeAgent  # noqa: E402

PAYOUT = 0.85
BREAK_EVEN = 1.0 / (1.0 + PAYOUT)

LOOKBACK_M1, LOOKBACK_M5, LOOKBACK_M15 = 400, 120, 60


def generate_series(n, drift, vol, mean_revert=0.0, anchor=1.1, seed=1):
    rng = random.Random(seed)
    start = datetime(2026, 1, 1, 8, 0, 0)
    price = 1.1000
    out = []
    for i in range(n):
        shock = rng.gauss(drift, vol)
        if mean_revert:
            shock += mean_revert * (anchor - price) / anchor
        o = price
        c = o * (1 + shock)
        high_p = max(o, c) * (1 + abs(rng.gauss(0, vol * 0.35)))
        low_p = min(o, c) * (1 - abs(rng.gauss(0, vol * 0.35)))
        out.append(Candle(asset="EURUSD", timeframe=Timeframe.M1,
                          open_time=start + timedelta(minutes=i),
                          open=round(o, 5), high=round(high_p, 5),
                          low=round(low_p, 5), close=round(c, 5),
                          volume=rng.randint(800, 4000)))
        price = c
    return out


def resample(candles, tf, minutes):
    out = []
    for base in range(0, len(candles) - minutes + 1, minutes):
        chunk = candles[base:base + minutes]
        out.append(Candle(asset="EURUSD", timeframe=tf, open_time=chunk[0].open_time,
                          open=chunk[0].open, high=max(c.high for c in chunk),
                          low=min(c.low for c in chunk), close=chunk[-1].close,
                          volume=sum(c.volume or 0 for c in chunk)))
    return out


SCENARIOS = [
    ("tendencia_alcista", 0.0008, 0.0009, 0.0),
    ("tendencia_bajista", -0.0008, 0.0009, 0.0),
    ("lateral_rango", 0.0, 0.0009, 0.05),
    ("alta_volatilidad", 0.0002, 0.0035, 0.0),
    ("baja_volatilidad", 0.0, 0.00025, 0.08),
    ("choppy", 0.0, 0.0012, 0.0),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--candles", type=int, default=1500)
    ap.add_argument("--seed-offset", type=int, default=0)
    args = ap.parse_args()

    strategies = {
        "sr_bounce": SRBounceStrategy(),
        "trend_continuation": TrendContinuationStrategy(),
        "breakout_retest": BreakoutRetestStrategy(),
        "mean_reversion": MeanReversionStrategy(),
        "breakout_direct": BreakoutDirectStrategy(),
    }
    regime_agent = MarketRegimeAgent()

    # (strategy, direction, regime) -> [wins, total]
    tally = defaultdict(lambda: [0, 0])
    scenario_tally = defaultdict(lambda: [0, 0])

    for name, drift, vol, mr in SCENARIOS:
        for seed in range(1 + args.seed_offset, args.seeds + 1 + args.seed_offset):
            m1 = generate_series(args.candles, drift, vol, mr, seed=seed)
            m5 = resample(m1, Timeframe.M5, 5)
            m15 = resample(m1, Timeframe.M15, 15)
            for i in range(80, len(m1)):
                idx15, idx5 = i // 15 + 1, i // 5 + 1
                c15 = m15[max(0, idx15 - LOOKBACK_M15): idx15]
                c5 = m5[max(0, idx5 - LOOKBACK_M5): idx5]
                c1 = m1[max(0, i + 1 - LOOKBACK_M1): i + 1]
                regime = regime_agent.classify(c15, "EURUSD").regime.value
                for sname, strat in strategies.items():
                    try:
                        sig = strat.evaluate(c15, c5, c1, "EURUSD")
                    except Exception:
                        continue
                    d = sig.get("direction", Direction.NO_TRADE)
                    if d == Direction.NO_TRADE:
                        continue
                    bars = max(1, round((sig.get("expiry") or 180) / 60))
                    j = i + bars
                    if j >= len(m1):
                        continue
                    entry, exit_p = m1[i].close, m1[j].close
                    if exit_p == entry:
                        continue
                    won = exit_p > entry if d == Direction.CALL else exit_p < entry
                    key = (sname, d.value, regime)
                    tally[key][1] += 1
                    tally[key][0] += 1 if won else 0
                    skey = (sname, d.value, name)
                    scenario_tally[skey][1] += 1
                    scenario_tally[skey][0] += 1 if won else 0

    print("=" * 92)
    print(f"AUDITORIA POR ESTRATEGIA / DIRECCION / REGIMEN  (break-even = {BREAK_EVEN:.4f})")
    print("=" * 92)
    print(f"{'estrategia':<20}{'dir':<6}{'regimen':<18}{'trades':>8}{'WR%':>8}  veredicto")
    print("-" * 92)
    report = {}
    for (sname, d, regime), (wins, total) in sorted(tally.items()):
        wr = wins / total if total else 0.0
        if total < 20:
            verdict = "poca muestra"
        elif wr < BREAK_EVEN - 0.02:
            verdict = "PIERDE DINERO"
        elif wr < BREAK_EVEN + 0.02:
            verdict = "marginal"
        else:
            verdict = "tiene edge"
        print(f"{sname:<20}{d:<6}{regime:<18}{total:>8}{wr*100:>7.1f}%  {verdict}")
        report[f"{sname}|{d}|{regime}"] = {"trades": total, "wins": wins,
                                           "win_rate": round(wr, 4)}

    print("\n" + "=" * 92)
    print("POR ESCENARIO")
    print("=" * 92)
    print(f"{'estrategia':<20}{'dir':<6}{'escenario':<22}{'trades':>8}{'WR%':>8}  veredicto")
    print("-" * 92)
    for (sname, d, sc), (wins, total) in sorted(scenario_tally.items()):
        wr = wins / total if total else 0.0
        verdict = ("PIERDE DINERO" if wr < BREAK_EVEN - 0.02 and total >= 20
                   else "marginal" if total >= 20 else "poca muestra")
        print(f"{sname:<20}{d:<6}{sc:<22}{total:>8}{wr*100:>7.1f}%  {verdict}")
        report[f"{sname}|{d}|sc:{sc}"] = {"trades": total, "wins": wins,
                                          "win_rate": round(wr, 4)}

    out = {"generated_at": datetime.utcnow().isoformat(),
           "break_even": round(BREAK_EVEN, 4), "results": report}
    dest = Path("reports/strategy_audit.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2))
    print(f"\nReporte guardado en {dest}")


if __name__ == "__main__":
    main()
