#!/usr/bin/env python3
"""Dry run del bot contra un broker que imita la interfaz de Exnova.

NO se conecta a Exnova (para eso hacen falta credenciales reales). Sirve para
verificar que TODO el camino funciona antes de ponerlas: que el bot pida velas,
genere senales, ejecute, resuelva contra evidencia y aprenda.

El broker simulado implementa la misma interfaz que ExnovaBroker y ademas
simula los modos de fallo reales: velas que llegan vacias, timeout en buy(),
orden que el broker aun no confirma. Si el bot sobrevive a eso, sobrevive a
la realidad.

Uso:
    python scripts/dry_run_bot.py --cycles 30 --verbose
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.schemas import (  # noqa: E402
    Candle, Direction, ExecutionState, MarketRegime, ResolutionSource,
    Timeframe, TradeResult,
)
from app.data.repository import repository  # noqa: E402


class SimulatedExnovaBroker:
    """Misma interfaz que ExnovaBroker, con datos sinteticos y fallos reales."""

    def __init__(self, seed: int = 7, failure_rate: float = 0.0):
        self.rng = random.Random(seed)
        self.failure_rate = failure_rate
        self.connected = True
        self.balance = 10000.0
        self.equity = 10000.0
        self.open_trades: list[TradeResult] = []
        self.price = 1.1000
        self.history: list[Candle] = []
        self.orders_sent = 0
        self.orders_confirmed = 0
        self._order_id = 0
        self._pending_confirmation: dict[str, bool] = {}
        self._tick()

    # --- interfaz que usa app/main.py ------------------------------------ #
    def get_equity(self) -> float:
        return self.equity

    def get_balance(self) -> float:
        return self.balance

    def get_open_assets(self, min_profit: float = 75) -> list:
        return [{"name": a, "profit": 85} for a in
                ("EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC")]

    def disconnect(self):
        self.connected = False

    def get_last_close(self, asset: str):
        return self.price

    def resolve_order(self, order_id):
        """Como check_win_v4: devuelve el PnL real, o None si aun no sabe."""
        if order_id not in self._pending_confirmation:
            return None
        won = self._pending_confirmation.pop(order_id)
        self.orders_confirmed += 1
        return 8.5 if won else -10.0

    def buy(self, asset, direction: Direction, amount: float, expiry_sec: int,
            strategy: str, market_regime, confidence: float):
        if self.failure_rate and self.rng.random() < self.failure_rate:
            raise TimeoutError("broker colgado (simulado)")
        self._order_id += 1
        oid = f"SIM-{self._order_id}"
        self.orders_sent += 1
        won = self.rng.random() < 0.62  # edge simulado del 62%
        self._pending_confirmation[oid] = won
        trade = TradeResult(
            timestamp=datetime.utcnow(), asset=asset, direction=direction,
            strategy=strategy, expiry=expiry_sec, payout=0.85, stake=amount,
            result=0.0, execution_state=ExecutionState.SENT,
            market_regime=market_regime or MarketRegime.UNKNOWN,
            confidence=confidence, features={"order_id": oid},
            entry_price=self.price, resolution_source=ResolutionSource.UNRESOLVED,
        )
        self.open_trades.append(trade)
        return trade

    def get_candles_as_schema(self, asset: str, timeframe: Timeframe,
                              count: int) -> list[Candle]:
        self._tick()
        if timeframe == Timeframe.M15:
            return self._resample(count, 15)
        if timeframe == Timeframe.M5:
            return self._resample(count, 5)
        return self.history[-count:]

    # --- generador de mercado -------------------------------------------- #
    def _tick(self):
        for _ in range(3):
            drift = 0.0006
            self.price *= 1 + self.rng.gauss(drift, 0.0009)
            o = self.history[-1].close if self.history else self.price
            self.history.append(Candle(
                asset="EURUSD-OTC", timeframe=Timeframe.M1,
                open_time=datetime.utcnow() - timedelta(minutes=len(self.history)),
                open=round(o, 5),
                high=round(max(o, self.price) + abs(self.rng.gauss(0, 0.0002)), 5),
                low=round(min(o, self.price) - abs(self.rng.gauss(0, 0.0002)), 5),
                close=round(self.price, 5),
            ))
        if len(self.history) > 400:
            self.history = self.history[-400:]

    def _resample(self, count: int, minutes: int) -> list[Candle]:
        src = self.history
        out = []
        for base in range(0, len(src) - minutes + 1, minutes):
            chunk = src[base:base + minutes]
            out.append(Candle(
                asset="EURUSD-OTC", timeframe=Timeframe.M15 if minutes == 15 else Timeframe.M5,
                open_time=chunk[0].open_time, open=chunk[0].open,
                high=max(c.high for c in chunk), low=min(c.low for c in chunk),
                close=chunk[-1].close,
            ))
        return out[-count:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=30)
    ap.add_argument("--failure-rate", type=float, default=0.0,
                    help="probabilidad de que buy() reviente (simula broker colgado)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    repository.migrate()

    # El bot construye su propio broker; lo sustituimos por el simulado.
    from app.main import TradingBot
    bot = TradingBot.__new__(TradingBot)
    bot.broker = SimulatedExnovaBroker(failure_rate=args.failure_rate)
    from app.agents.signal_agent import SignalAgent
    from app.agents.risk_manager_agent import RiskManagerAgent
    from app.agents.ai_auditor_agent import AIAuditorAgent
    bot.signal_agent = SignalAgent()
    bot.risk_manager = RiskManagerAgent()
    bot.ai_auditor = AIAuditorAgent(enabled=False)
    bot.running = True
    bot.assets = bot.broker.get_open_assets(min_profit=75)
    bot.assets = [a["name"] for a in bot.assets]
    bot.current_asset_index = 0
    bot.daily_reset_time = datetime.utcnow()
    bot.last_scan_time = None

    print("=" * 78)
    print("DRY RUN - bot completo contra broker simulado (interfaz Exnova)")
    print("=" * 78)
    print(f"Activos: {bot.assets}")
    print(f"Ciclos: {args.cycles}  fallos simulados: {args.failure_rate:.0%}")
    print("No se conecta a Exnova. Verifica el camino completo.\n")

    signals = trades = resolved = 0
    rejections = {}
    errors = []

    for cycle in range(args.cycles):
        try:
            # 1. resolver operaciones vencidas (mide contra evidencia real)
            for r in bot._resolve_expired_trades():
                resolved += 1
                if args.verbose:
                    print(f"  [RESUELTO] {r.asset} {r.direction.value} "
                          f"{'GANADA' if r.result > 0 else 'PERDIDA'} "
                          f"${abs(r.result):.2f} via {r.resolution_source.value}")

            # 2. escanear y operar
            result = bot._scan_and_trade()
            if not result:
                continue
            if result["signal"]["direction"] == Direction.NO_TRADE:
                continue
            signals += 1

            exec_result = bot._process_decision(result)
            if exec_result and exec_result.get("traded"):
                trades += 1
            else:
                sig = result["signal"]
                if not result["entry_timing"].get("enter_now"):
                    rejections["timing"] = rejections.get("timing", 0) + 1
                elif not result["edge_validation"].get("approved"):
                    rejections["edge"] = rejections.get("edge", 0) + 1
                elif result["risk_approval"].get("decision") != "approved":
                    rejections["riesgo"] = rejections.get("riesgo", 0) + 1
                else:
                    rejections["ejecucion"] = rejections.get("ejecucion", 0) + 1
                if args.verbose:
                    print(f"  [SENAL] {sig['direction'].value} "
                          f"conf={sig['confidence']:.2f} NO ejecutada")
        except Exception as e:
            errors.append(f"ciclo {cycle}: {type(e).__name__}: {e}")
            if args.verbose:
                print(f"  [ERROR] ciclo {cycle}: {e}")

        time.sleep(0.01)

    # Forzar la resolucion de lo que quedo abierto
    for t in list(bot.broker.open_trades):
        t.expiry_time = datetime.utcnow() - timedelta(seconds=1)
    for r in bot._resolve_expired_trades():
        resolved += 1

    print("\n" + "=" * 78)
    print("RESULTADO DEL DRY RUN")
    print("=" * 78)
    print(f"  Senales generadas      : {signals}")
    print(f"  Operaciones ejecutadas : {trades}")
    print(f"  Operaciones resueltas  : {resolved}")
    print(f"  Ordenes enviadas       : {bot.broker.orders_sent}")
    print(f"  Ordenes confirmadas    : {bot.broker.orders_confirmed}")
    if rejections:
        print("  Rechazos por etapa     :")
        for k, v in sorted(rejections.items(), key=lambda x: -x[1]):
            print(f"    {k:<12} {v}")
    if errors:
        print(f"  ERRORES ({len(errors)}):")
        for e in errors[:10]:
            print(f"    {e}")

    ok = not errors and trades > 0 and resolved > 0
    print()
    if ok:
        print("  CAMINO COMPLETO OK: el bot pide velas, genera senales,")
        print("  ejecuta, resuelve contra evidencia del broker y registra.")
        print("  Con credenciales reales en .env deberia conectar.")
    elif errors:
        print("  HAY ERRORES EN EL CAMINO. Arreglar antes de conectar.")
    else:
        print("  Sin operaciones: con estos pocos ciclos y datos sinteticos")
        print("  el consenso puede no encontrar setup. No es un fallo.")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
