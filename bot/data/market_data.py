import pandas as pd
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import Config
except Exception:
    class Config:
        pass

try:
    from exnovaapi.stable_api import Exnova
except ImportError:
    Exnova = None

try:
    from iqoptionapi.stable_api import IQ_Option
except ImportError:
    IQ_Option = None


class MarketDataHandler:
    def __init__(self, broker_name="exnova", account_type="PRACTICE"):
        self.broker_name = broker_name.lower()
        self.account_type = account_type
        self.api = None
        self.connected = False

    def connect(self, email, password, max_retries=3):
        last_error = None
        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                print(f"  Reintento {attempt}/{max_retries}...")
                import time
                time.sleep(3)
            print(f"  Conectando a {self.broker_name.upper()} ({self.account_type})...")
            try:
                if self.broker_name == "exnova":
                    if Exnova is None:
                        print("  ERROR: librería exnovaapi no instalada.")
                        continue
                    self.api = Exnova(email, password, active_account_type=self.account_type)
                    check, reason = self.api.connect()
                    if check and self.api.check_connect():
                        try:
                            import threading
                            def update_actives():
                                try:
                                    self.api.update_ACTIVES_OPCODE()
                                except:
                                    pass
                            thread = threading.Thread(target=update_actives, daemon=True)
                            thread.start()
                            thread.join(timeout=5)
                            if thread.is_alive():
                                print("  [WARN] Timeout actualizando activos (continuando de todos modos)")
                        except Exception as e:
                            print(f"  [WARN] Error actualizando activos: {e}")
                        self.connected = True
                        print(f"  [OK] Conectado a EXNOVA ({self.account_type})")
                        return True
                    else:
                        print(f"  [FAIL] Razón: {reason}")
                        self.connected = False
                elif self.broker_name == "iq":
                    if IQ_Option is None:
                        print("  ERROR: librería iqoptionapi no instalada.")
                        continue
                    self.api = IQ_Option(email, password)
                    check, reason = self.api.connect()
                    if check:
                        self.api.change_balance(self.account_type)
                        self.connected = True
                        return True
                    else:
                        self.connected = False
                else:
                    print(f"  Broker desconocido: {self.broker_name}")
                    return False
            except Exception as e:
                err_msg = str(e)
                if "'ConnectionError' object has no attribute 'text'" in err_msg:
                    print(f"  [WARN] Error de conexión conocido (intento {attempt}/{max_retries})")
                else:
                    print(f"  Excepción en connect: {e}")
                self.connected = False
                last_error = e
        
        print(f"  [FAIL] No se pudo conectar tras {max_retries} intentos")
        return False

    def get_candles(self, asset, timeframe, num_candles, end_time=None):
        if not self.connected or not self.api:
            return pd.DataFrame()
        
        # Convertir timeframe string a segundos si es necesario
        interval_seconds = timeframe
        if isinstance(timeframe, str):
            tf_map = {
                "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
                "1h": 3600, "2h": 7200, "4h": 14400,
                "1d": 86400, "1w": 604800,
            }
            interval_seconds = tf_map.get(timeframe, 60)
        
        try:
            if end_time is None:
                end_time = time.time()
            try:
                candles = self.api.get_candles(asset, interval_seconds, num_candles, end_time)
            except TypeError:
                candles = self.api.get_candles(asset, interval_seconds, num_candles)
        except Exception:
            return pd.DataFrame()
        
        if not candles:
            return pd.DataFrame()
        if isinstance(candles, dict):
            return pd.DataFrame()
        
        df = pd.DataFrame(candles)
        if df.empty:
            return df
        
        rename_map = {'max': 'high', 'min': 'low', 'open': 'open',
                      'close': 'close', 'volume': 'volume', 'from': 'timestamp'}
        df.rename(columns=rename_map, inplace=True)
        
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            df.set_index('timestamp', inplace=True)
        
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col not in df.columns:
                df[col] = 0.0
        
        df = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric, errors='coerce')
        return df

    def get_balance(self):
        if self.connected and self.api:
            try:
                return self.api.get_balance()
            except Exception:
                return 0.0
        return 0.0

    def get_current_price(self, asset):
        if not self.connected or not self.api:
            return 0.0
        try:
            candles = self.api.get_candles(asset, 60, 1, time.time())
            if candles and isinstance(candles, list) and len(candles) > 0:
                c = candles[-1]
                if isinstance(c, dict) and 'close' in c:
                    return float(c['close'])
        except Exception:
            pass
        return 0.0

    def buy(self, asset, amount, action, duration):
        if not self.connected or not self.api:
            return False, "No conectado"
        success, result = self._execute_buy_logic(asset, amount, action, duration)
        if success:
            return True, result
        # Fallback OTC/Normal
        alt = asset.replace("-OTC", "") if asset.endswith("-OTC") else asset + "-OTC"
        success2, result2 = self._execute_buy_logic(alt, amount, action, duration)
        if success2:
            return True, result2
        return False, f"Falló en {asset} y {alt}"

    def _execute_buy_logic(self, asset, amount, action, duration):
        try:
            if duration in [1, 5, 15]:
                try:
                    self.api.subscribe_strike_list(asset, duration)
                    payout = self.api.get_digital_to_payout(asset, duration)
                    if payout and payout > 0:
                        check, order_id = self.api.buy_digital_spot(asset, amount, action, duration)
                        if check:
                            return True, order_id
                except Exception:
                    pass
            check, order_id = self.api.buy(amount, asset, action, duration)
            if check:
                return True, order_id
            return False, f"Rechazado: {order_id}"
        except Exception as e:
            return False, str(e)

    def is_really_connected(self):
        if not self.connected or not self.api:
            return False
        try:
            if self.broker_name == "exnova":
                return self.api.check_connect()
            else:
                return self.api.get_balance() is not None
        except Exception:
            return False

    def reconnect(self, email, password):
        self.connected = False
        time.sleep(2)
        return self.connect(email, password)

    def get_open_assets(self, min_profit=75):
        if not self.connected:
            return []
        try:
            profits = self.api.get_all_profit()
            if not profits:
                return []
            open_assets = []
            for asset_name, data in profits.items():
                profit = 0
                if isinstance(data, dict):
                    profit = data.get('turbo', data.get('binary', 0))
                else:
                    profit = data
                if profit >= (min_profit / 100.0):
                    open_assets.append({
                        'name': asset_name,
                        'profit': profit * 100,
                    })
            return sorted(open_assets, key=lambda x: x['profit'], reverse=True)
        except Exception:
            return []

    def disconnect(self):
        if self.api:
            try:
                if hasattr(self.api, 'close'):
                    self.api.close()
            except Exception:
                pass
        self.connected = False
        self.api = None
