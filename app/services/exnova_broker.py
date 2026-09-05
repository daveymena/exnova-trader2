"""Exnova broker connector for the new architecture."""
import os
import sys
import time
import threading
from typing import Optional
from datetime import datetime, timedelta

import pandas as pd

from app.data.schemas import (
    Candle, Direction, Timeframe, TradeResult, ExecutionState, ResolutionSource
)
from app.services.paper_broker import PaperBroker

# Try multiple paths for exnovaapi
_EXNOVA_PATHS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                 "Nueva carpeta (2)", "bot-reversiones-iq-new"),
    os.path.join(os.path.expanduser("~"), "Videos", "Nueva carpeta (2)", "bot-reversiones-iq-new"),
]
for _p in _EXNOVA_PATHS:
    if os.path.isdir(_p):
        sys.path.insert(0, _p)

try:
    from exnovaapi.stable_api import Exnova as ExnovaAPI
except ImportError:
    ExnovaAPI = None


class ExnovaBroker(PaperBroker):
    def __init__(self, email: str, password: str, account_type: str = "PRACTICE"):
        super().__init__()
        self.email = email
        self.password = password
        self.account_type = account_type
        self.api = None
        self.connected = False

    def connect(self, max_retries: int = 3) -> bool:
        if ExnovaAPI is None:
            print("[EXNOVA] exnovaapi no instalado. Usar: pip install exnovaapi")
            return False

        for attempt in range(1, max_retries + 1):
            try:
                print(f"[EXNOVA] Conectando ({attempt}/{max_retries})...")
                self.api = ExnovaAPI(self.email, self.password,
                                     active_account_type=self.account_type)
                check, reason = self.api.connect()
                if check and self.api.check_connect():
                    self.api.change_balance(self.account_type)
                    # Refresh assets in background
                    t = threading.Thread(
                        target=lambda: self.api.update_ACTIVES_OPCODE(),
                        daemon=True
                    )
                    t.start()
                    t.join(timeout=5)
                    self.connected = True
                    balance = self.api.get_balance()
                    print(f"[EXNOVA] Conectado ({self.account_type}) Balance: ${balance}")
                    return True
                print(f"[EXNOVA] Error: {reason}")
            except Exception as e:
                print(f"[EXNOVA] Fallo intento {attempt}: {e}")
                time.sleep(3)
        return False

    def get_candles(self, asset: str, timeframe: int, count: int = 100) -> pd.DataFrame:
        if not self.connected or not self.api:
            return pd.DataFrame()
        try:
            end = time.time()
            candles = self.api.get_candles(asset, timeframe, count, end)
            if not candles or isinstance(candles, dict):
                return pd.DataFrame()
            df = pd.DataFrame(candles)
            rename = {'max': 'high', 'min': 'low', 'open': 'open',
                      'close': 'close', 'from': 'timestamp'}
            df.rename(columns=rename, inplace=True)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                df.set_index('timestamp', inplace=True)
            for c in ['open', 'high', 'low', 'close']:
                if c not in df.columns:
                    df[c] = 0.0
            return df[['open', 'high', 'low', 'close']].apply(pd.to_numeric, errors='coerce')
        except Exception:
            return pd.DataFrame()

    def get_balance(self) -> float:
        if self.connected and self.api:
            try:
                return self.api.get_balance()
            except Exception:
                return self.balance
        return self.balance

    def buy(self, asset, direction: Direction, amount: float,
            expiry_sec: int, strategy: str, market_regime, confidence: float):
        if not self.connected or not self.api:
            return super().buy(asset, direction, amount, expiry_sec,
                               strategy, market_regime, confidence)

        action = direction.value.upper()
        try:
            if expiry_sec in [1, 5, 15]:
                try:
                    self.api.subscribe_strike_list(asset, expiry_sec)
                    payout = self.api.get_digital_to_payout(asset, expiry_sec)
                    if payout and payout > 0:
                        check, order_id = self.api.buy_digital_spot(
                            asset, amount, action, expiry_sec
                        )
                        if check:
                            return self._register_sent(
                                asset, direction, strategy, expiry_sec,
                                payout, amount, market_regime, confidence,
                                order_id,
                            )
                except Exception:
                    pass

            check, order_id = self.api.buy(amount, asset, action, expiry_sec)
            if check:
                return self._register_sent(
                    asset, direction, strategy, expiry_sec,
                    0.85, amount, market_regime, confidence, order_id,
                )
            print(f"[EXNOVA] Buy rejected: {order_id}")
        except Exception as e:
            print(f"[EXNOVA] Buy error: {e}")

        # Fallback to paper
        return super().buy(asset, direction, amount, expiry_sec,
                           strategy, market_regime, confidence)

    def _register_sent(self, asset, direction: Direction, strategy: str,
                       expiry_sec: int, payout: float, amount: float,
                       market_regime, confidence: float,
                       order_id) -> TradeResult:
        """Registra la orden enviada junto a su evidencia de entrada.

        Antes los dos `return TradeResult(...)` de buy() no pasaban por
        open_trades, asi que ninguna orden real llegaba nunca al resolvedor:
        se enviaban y se olvidaban. Las unicas filas que acababan en
        trade_results venian del PaperBroker de respaldo.
        """
        now = datetime.utcnow()
        trade = TradeResult(
            timestamp=now,
            asset=asset, direction=direction,
            strategy=strategy, expiry=expiry_sec,
            payout=payout, stake=amount,
            result=0.0,
            execution_state=ExecutionState.SENT,
            market_regime=market_regime,
            confidence=confidence,
            features={"order_id": order_id, "broker": "exnova"},
            entry_price=self.get_last_close(asset),
            entry_time=now,
            expiry_time=now + timedelta(seconds=expiry_sec),
            broker_order_id=str(order_id),
            resolution_source=ResolutionSource.UNRESOLVED,
        )
        self.open_trades.append(trade)
        return trade

    def get_last_close(self, asset: str) -> Optional[float]:
        """Ultimo cierre observado (M1), o None si no hay feed."""
        if not self.connected or not self.api:
            return None
        try:
            df = self.get_candles(asset, 60, 2)
            if df.empty or "close" not in df.columns:
                return None
            price = float(df["close"].iloc[-1])
            return price if price > 0 else None
        except Exception:
            return None

    def resolve_order(self, order_id) -> Optional[float]:
        """PnL real reportado por el broker para una orden.

        None significa "todavia no se sabe", nunca "cero": quien llama debe
        reintentar, jamas asumir un resultado.
        """
        if not self.connected or not self.api or order_id is None:
            return None
        try:
            data = self.api.check_win_v4(order_id)
        except Exception as e:
            print(f"[EXNOVA] check_win error: {e}")
            return None
        if isinstance(data, tuple):
            profit = data[1] if len(data) > 1 else None
            return float(profit) if profit is not None else None
        if isinstance(data, (int, float)):
            return float(data)
        return None

    def get_open_assets(self, min_profit: float = 75) -> list:
        if not self.connected or not self.api:
            return []
        try:
            profits = self.api.get_all_profit()
            if not profits:
                return []
            assets = []
            for name, data in profits.items():
                profit = data.get('turbo', data.get('binary', 0)) if isinstance(data, dict) else data
                if profit >= (min_profit / 100.0):
                    assets.append({'name': name, 'profit': profit * 100})
            return sorted(assets, key=lambda x: x['profit'], reverse=True)
        except Exception:
            return []

    def is_connected(self) -> bool:
        if not self.connected or not self.api:
            return False
        try:
            return self.api.check_connect()
        except Exception:
            return False

    def disconnect(self):
        if self.api:
            try:
                if hasattr(self.api, 'close'):
                    self.api.close()
            except Exception:
                pass
        self.connected = False
        self.api = None

    def get_candles_as_schema(self, asset: str, timeframe: Timeframe,
                               count: int = 100) -> list[Candle]:
        tf_sec = timeframe.value
        df = self.get_candles(asset, tf_sec, count)
        if df.empty:
            return []

        candles = []
        for idx, row in df.iterrows():
            candles.append(Candle(
                asset=asset,
                timeframe=timeframe,
                open_time=idx.to_pydatetime() if hasattr(idx, 'to_pydatetime') else idx,
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                source="exnova",
            ))
        return candles
