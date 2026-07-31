"""Main orchestrator for the Exnova Trading Bot.

Runs the scanning loop, processes signals, manages risk, and records results.
"""
import time
import random
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.config import config, TradingMode
from app.data.repository import repository
from app.data.schemas import (
    Candle, Direction, MarketRegime, TradeDecision,
    TradeResult, ExecutionState, RiskDecision, Timeframe, TradingMode as SchemaMode,
    AccountSnapshot
)
from app.agents.signal_agent import SignalAgent
from app.agents.risk_manager_agent import RiskManagerAgent
from app.agents.ai_auditor_agent import AIAuditorAgent
from app.services.paper_broker import PaperBroker
from app.services.exnova_broker import ExnovaBroker


logger = logging.getLogger(__name__)


class TradingBot:
    def __init__(self):
        config.validate()
        repository.migrate()

        self.mode = config.mode
        self.signal_agent = SignalAgent()
        self.risk_manager = RiskManagerAgent()
        self.broker = PaperBroker()

        if self.mode in (TradingMode.PRACTICE, TradingMode.REAL):
            broker = ExnovaBroker(
                email=config.exnova_email,
                password=config.exnova_password,
                account_type="PRACTICE" if self.mode == TradingMode.PRACTICE else "REAL",
            )
            if broker.connect():
                self.broker = broker
                logger.info("Connected to Exnova broker")
            else:
                logger.warning("Exnova connection failed, falling back to PaperBroker")
        else:
            self.broker = PaperBroker()

        self.ai_auditor = AIAuditorAgent(
            enabled=True,
        )

        self.running = False
        self.last_scan_time: Optional[datetime] = None
        self.daily_reset_time: Optional[datetime] = None
        self.current_asset_index = 0

        # Available assets to scan
        self.assets = self._load_assets()

    def _load_assets(self) -> list[str]:
        if hasattr(self.broker, 'get_open_assets'):
            try:
                assets_info = self.broker.get_open_assets(min_profit=75)
                if assets_info:
                    all_assets = [a['name'] for a in assets_info]
                    print(f"[BOT] {len(all_assets)} activos disponibles en broker")
                    # Prioritize liquid forex pairs first, then everything else
                    priority = ["EURUSD-OTC", "GBPUSD-OTC", "AUDUSD-OTC", "USDJPY-OTC",
                                "EURJPY-OTC", "GBPJPY-OTC", "EURGBP-OTC", "NZDSGD-OTC",
                                "AUDCAD-OTC", "AUDJPY-OTC", "CHFJPY-OTC", "EURNZD-OTC",
                                "GBPAUD-OTC", "NZDCAD-OTC", "XAUUSD-OTC", "BTC-OTC"]
                    ordered = [a for a in priority if a in all_assets]
                    rest = [a for a in all_assets if a not in ordered]
                    return ordered + rest
            except Exception:
                pass
        return ["EURUSD-OTC", "GBPUSD-OTC", "AUDUSD-OTC", "USDJPY-OTC",
                "EURJPY-OTC", "GBPJPY-OTC", "XAUUSD-OTC", "BTC-OTC"]

    def start(self):
        self.running = True
        logger.info(f"Bot started in {self.mode.value.upper()} mode")

        if self.mode == TradingMode.PAPER:
            logger.info("Paper mode: no real trades will be executed")
        elif self.mode == TradingMode.PRACTICE:
            logger.info("Practice mode: demo trades via broker")
        elif self.mode == TradingMode.REAL:
            logger.warning("REAL MONEY TRADING ACTIVE")

        self._scan_loop()

    def stop(self):
        self.running = False
        if hasattr(self.broker, 'disconnect'):
            self.broker.disconnect()
        logger.info("Bot stopped")

    def _scan_loop(self):
        cycle = 0
        total_signals = 0
        total_trades = 0
        win_count = 0
        loss_count = 0
        signals_by_strategy = {}
        cooldown_until = 0.0
        max_concurrent = 1

        while self.running:
            try:
                now = time.time()
                self._check_daily_reset()

                # Resolve expired trades
                resolved = self._resolve_expired_trades()
                for r in resolved:
                    if r.result > 0:
                        win_count += 1
                    else:
                        loss_count += 1
                    print(f"[RESULTADO] {r.asset} {r.direction.value} {'GANADA' if r.result > 0 else 'PERDIDA'} ${abs(r.result):.2f} ({win_count}G/{loss_count}P)")

                # Cooldown entre trades
                if len(self.broker.open_trades) >= max_concurrent:
                    time.sleep(5)
                    cycle += 1
                    if cycle % 10 == 0:
                        print(f"[BOT] Esperando fin de trade... {len(self.broker.open_trades)} abiertos")
                    continue

                if now < cooldown_until:
                    time.sleep(1)
                    continue

                result = self._scan_and_trade()
                if result:
                    total_signals += 1
                    strat = result["signal"].get("strategy_name", result["signal"].get("strategy", "?"))
                    signals_by_strategy[strat] = signals_by_strategy.get(strat, 0) + 1
                    exec_result = self._process_decision(result)
                    if exec_result and exec_result.get("traded", False):
                        total_trades += 1
                        cooldown_until = now + 30  # 30s cooldown tras trade

                cycle += 1
                if cycle % 10 == 0:
                    strat_summary = " | ".join(f"{k}={v}" for k, v in sorted(signals_by_strategy.items()))
                    wr = f"{(win_count/(win_count+loss_count)*100):.0f}%" if (win_count+loss_count) > 0 else "-"
                    print(f"[BOT] {cycle} ciclos | senales: {total_signals} | trades: {total_trades} | {win_count}G/{loss_count}P ({wr}) | activo: {self.assets[self.current_asset_index % len(self.assets)]}")
                    if strat_summary:
                        print(f"[BOT]   estrategias: {strat_summary}")
            except Exception as e:
                logger.error(f"Scan error: {e}", exc_info=True)
                repository.log_error("main", str(e))
            time.sleep(1)

    def _resolve_expired_trades(self) -> list[TradeResult]:
        now = datetime.utcnow()
        resolved = []
        still_open = []
        for trade in self.broker.open_trades:
            expiry_time = trade.timestamp + timedelta(seconds=trade.expiry)
            if now < expiry_time:
                still_open.append(trade)
                continue
            # Trade expired - resolve it
            if trade.execution_state in (ExecutionState.SENT, ExecutionState.PENDING):
                won = random.random() < 0.55  # 55% win rate simulation
                payout = trade.payout or 0.85
                if won:
                    profit = trade.stake * payout
                    self.broker.balance += trade.stake + profit
                    trade.result = profit
                    trade.execution_state = ExecutionState.WON
                else:
                    trade.execution_state = ExecutionState.LOST
                trade.payout = payout
                repository.save_trade_result(trade)
            resolved.append(trade)
        self.broker.open_trades = still_open
        return resolved

    def _scan_and_trade(self) -> Optional[dict]:
        self.last_scan_time = datetime.utcnow()

        # Get candles from broker (or mock as fallback)
        asset = self.assets[self.current_asset_index % len(self.assets)]
        self.current_asset_index += 1

        if hasattr(self.broker, 'get_candles_as_schema') and self.broker.connected:
            candles_m15 = self.broker.get_candles_as_schema(asset, Timeframe.M15, 100)
            candles_m5 = self.broker.get_candles_as_schema(asset, Timeframe.M5, 100)
            candles_m1 = self.broker.get_candles_as_schema(asset, Timeframe.M1, 50)
            if not candles_m15 or not candles_m5:
                candles_m15 = self._get_mock_candles(100)
                candles_m5 = self._get_mock_candles(100)
                candles_m1 = self._get_mock_candles(50)
        else:
            candles_m15 = self._get_mock_candles(100)
            candles_m5 = self._get_mock_candles(100)
            candles_m1 = self._get_mock_candles(50)

        result = self.signal_agent.scan(
            candles_m15, candles_m5, candles_m1,
            asset=asset,
            account_equity=self.broker.get_equity(),
        )

        if result["signal"]["direction"] == Direction.NO_TRADE:
            return None

        return result

    def _process_decision(self, scan_result: dict):
        signal = scan_result["signal"]
        timing = scan_result["entry_timing"]
        edge = scan_result["edge_validation"]
        risk = scan_result["risk_approval"]
        asset = scan_result["asset"]
        direction = signal["direction"]

        decision = TradeDecision(
            timestamp=datetime.utcnow(),
            asset=asset,
            direction=direction,
            strategy=signal.get("strategy_name", signal["strategy"]),
            confidence=signal.get("confidence", 0),
            opportunity_score=signal.get("opportunity_score", 0),
            market_regime=signal.get("market_regime"),
            entry_timing=timing.get("timing"),
            expiry=scan_result["expiry"]["selected_expiry"],
            payout=0.85,
            risk_decision=RiskDecision.REJECTED,
            edge_approved=edge.get("approved", False),
            edge_details=edge,
        )

        if not timing.get("enter_now", False):
            decision.risk_decision = RiskDecision.REJECTED
            decision.risk_reason = f"Timing: {timing.get('rationale', 'unknown')}"
            repository.save_decision(decision)
            return

        if not edge.get("approved", False):
            decision.risk_decision = RiskDecision.REJECTED
            decision.risk_reason = f"Edge: {'; '.join(edge.get('reasons', []))}"
            repository.save_decision(decision)
            return

        if risk.get("decision") != RiskDecision.APPROVED:
            decision.risk_decision = risk.get("decision", RiskDecision.REJECTED)
            decision.risk_reason = f"Risk: {'; '.join(risk.get('reasons', []))}"
            repository.save_decision(decision)
            return

        # All checks passed: execute
        decision.risk_decision = RiskDecision.APPROVED
        repository.save_decision(decision)

        stake = risk.get("stake", 10.0)
        trade = self._execute_trade(
            asset, direction, stake,
            scan_result["expiry"]["selected_expiry"],
            signal.get("strategy_name", signal["strategy"]),
            signal.get("market_regime"),
            signal.get("confidence", 0),
        )

        if trade:
            self.risk_manager.record_trade_result(trade)
            return {"traded": True}

        return {"traded": False}

    def _execute_trade(self, asset: str, direction: Direction, amount: float,
                       expiry_sec: int, strategy: str,
                       market_regime, confidence: float) -> Optional[TradeResult]:
        print(f"[TRADE] Ejecutando {asset} {direction.value} ${amount} {expiry_sec}s [{strategy}]")
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(self.broker.buy, asset, direction, amount, expiry_sec,
                            strategy, market_regime, confidence)
            try:
                trade = fut.result(timeout=15)
            except concurrent.futures.TimeoutError:
                print(f"[TRADE] TIMEOUT en {asset} - broker colgado, saltando")
                return None
        if trade:
            print(f"[TRADE] OK {asset} {direction.value} ${amount} -> order_id={getattr(trade, 'features', {}).get('order_id','?')}")
            logger.info(f"Trade: {asset} {direction.value} ${amount}")
        return trade

    def _check_daily_reset(self):
        now = datetime.utcnow()
        if self.daily_reset_time is None or now.date() > self.daily_reset_time.date():
            self.risk_manager.reset_daily(self.broker.get_equity())
            self.daily_reset_time = now
            mode_map = {
                TradingMode.PAPER: SchemaMode.PAPER,
                TradingMode.PRACTICE: SchemaMode.PRACTICE,
                TradingMode.REAL: SchemaMode.REAL,
            }
            snap = AccountSnapshot(
                timestamp=now,
                mode=mode_map.get(self.mode, SchemaMode.PAPER),
                equity=self.broker.get_equity(),
                balance=self.broker.get_balance(),
                daily_pnl=0,
                daily_drawdown=0,
                open_positions=len(self.broker.open_trades),
                total_trades_today=0,
            )
            repository.save_account_snapshot(snap)

    @staticmethod
    def _get_mock_candles(count: int) -> list[Candle]:
        import random
        from datetime import timedelta

        now = datetime.utcnow()
        candles = []
        price = 1.0500
        for i in range(count):
            t = now - timedelta(minutes=i)
            change = random.gauss(0, 0.001)
            open_p = price
            close_p = price + change
            high_p = max(open_p, close_p) + abs(random.gauss(0, 0.0005))
            low_p = min(open_p, close_p) - abs(random.gauss(0, 0.0005))
            candles.append(Candle(
                asset="MOCK",
                timeframe=Timeframe.M1,
                open_time=t,
                open=round(open_p, 5),
                high=round(high_p, 5),
                low=round(low_p, 5),
                close=round(close_p, 5),
                source="mock",
            ))
            price = close_p
        return candles


def main():
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    bot = TradingBot()
    try:
        bot.start()
    except KeyboardInterrupt:
        bot.stop()
        logger.info("Bot terminated by user")


if __name__ == "__main__":
    main()
