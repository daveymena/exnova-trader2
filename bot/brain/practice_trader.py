"""
PracticeTrader - Modo demo supervisado.
Opera virtualmente usando zonas ya validadas (>=3 analisis, WR>=55%, strength>=0.50).
No envia ordenes reales al broker. Trackea balance virtual separado.
"""
import json
import os
import time
import numpy as np
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

try:
    from .strategy_adjustments import get_active_adjustments
except ImportError:  # ejecucion directa fuera del paquete brain
    from strategy_adjustments import get_active_adjustments

VIRTUAL_BALANCE_INIT = 1000.0
AMOUNT_PER_TRADE = 10.0
BROKER_PAYOUT = 0.85  # 85% payout en win
# Minimo de analisis completados antes de confiar en el win rate de una zona.
# Con 3 muestras un 66-100% de acierto puede ser ruido puro.
MIN_ZONE_ANALYSES = 8


@dataclass
class VirtualTrade:
    asset: str
    direction: str
    entry_price: float
    amount: float
    entry_time: float
    expiration_sec: int
    zone_level: float
    zone_win_rate: float
    zone_strength: float
    zone_type: str
    resolved: bool = False
    result: str = "PENDING"
    exit_price: float = 0.0
    pnl: float = 0.0
    resolved_ts: float = 0.0


class PracticeTrader:
    def __init__(
        self,
        zone_learner,
        persist_path: str = "brain/practice_trades.json",
        trade_amount: float = AMOUNT_PER_TRADE,
        max_concurrent: int = 3,
        cooldown_global: float = 60.0,
    ):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.persist_path = os.path.join(base_dir, "..", persist_path)
        self.zone_learner = zone_learner
        self.trade_amount = trade_amount
        self.max_concurrent = max_concurrent
        self.cooldown_global = cooldown_global
        self.virtual_balance = VIRTUAL_BALANCE_INIT
        self.virtual_trades: List[VirtualTrade] = []
        self._last_trade_ts: Dict[str, float] = {}
        self._last_trade_global_ts: float = 0.0
        self._adj_cache = {"ts": 0.0, "data": None}
        self._load()
        self._resolve_stale()

    def _adjustments(self) -> Dict:
        """Ajustes del improvement_loop (min_confidence, expiry_by_asset),
        cacheados 60s para no leer disco en cada intento de escaneo."""
        now = time.time()
        if self._adj_cache["data"] is None or now - self._adj_cache["ts"] > 60:
            try:
                self._adj_cache["data"] = get_active_adjustments()
            except Exception:
                self._adj_cache["data"] = {"min_confidence": None, "expiry_by_asset": {}}
            self._adj_cache["ts"] = now
        return self._adj_cache["data"]

    def _calc_atr(self, df_m1, period=14):
        """Calcula ATR (Average True Range) desde velas M1."""
        if df_m1 is None or len(df_m1) < period + 1:
            return None
        highs = df_m1["high"].values.astype(float)
        lows = df_m1["low"].values.astype(float)
        closes = df_m1["close"].values.astype(float)
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1])
            )
        )
        return float(np.mean(tr[-period:]))

    def _liquidity_sweep_against(self, df_m1, level: float, direction: str) -> bool:
        """Detecta si una de las ultimas velas barrio el nivel en sentido
        CONTRARIO a `direction` (mecha atraviesa el nivel, cierre de vuelta
        del otro lado con fuerza) - señal clasica de toma de liquidez /
        stop hunt seguida de reversion. Si se detecta, la entrada propuesta
        va contra el rebote que se esta formando y no se debe tomar.
        """
        if df_m1 is None or len(df_m1) < 2:
            return False
        for c in (df_m1.iloc[-1], df_m1.iloc[-2]):
            body = abs(c["close"] - c["open"])
            if direction == "PUT":
                # Barrida alcista: mecha bajo el nivel, cierre alcista sobre
                # el nivel -> reversion al alza, contradice un PUT.
                lower_wick = min(c["close"], c["open"]) - c["low"]
                if (c["low"] < level and c["close"] > level
                        and c["close"] > c["open"] and lower_wick > body * 1.2):
                    return True
            else:
                # Barrida bajista: mecha sobre el nivel, cierre bajista bajo
                # el nivel -> reversion a la baja, contradice un CALL.
                upper_wick = c["high"] - max(c["close"], c["open"])
                if (c["high"] > level and c["close"] < level
                        and c["close"] < c["open"] and upper_wick > body * 1.2):
                    return True
        return False

    def _expiration_from_atr(self, atr, current_price, zone_strength):
        """Determina expiracion optima segun ATR (volatilidad) y fuerza de zona."""
        if atr is None or atr == 0 or current_price == 0:
            if zone_strength >= 0.75:
                return 60
            elif zone_strength >= 0.60:
                return 120
            return 300
        atr_pct = atr / abs(current_price)
        if atr_pct >= 0.002:
            base = 60
        elif atr_pct >= 0.001:
            base = 120
        elif atr_pct >= 0.0005:
            base = 180
        else:
            base = 240
        if zone_strength >= 0.75:
            return max(60, int(base * 0.7))
        elif zone_strength >= 0.60:
            return max(60, int(base * 0.85))
        return max(60, int(base))

    def scan_and_trade(
        self, asset: str, current_price: float, df_m1=None
    ) -> Optional[VirtualTrade]:
        """Escanea zonas listas y si el precio esta en zona, ejecuta trade virtual."""
        zones = self.zone_learner.zones.get(asset, [])
        if not zones:
            return None

        now = time.time()

        # Auto-resolver pendientes muy viejos (stales)
        self._resolve_stale()

        # Limitar concurrentes global
        activos_activos = len(
            [t for t in self.virtual_trades if not t.resolved]
        )
        if activos_activos >= self.max_concurrent:
            return None

        # Cooldown global entre practice trades
        if now - self._last_trade_global_ts < self.cooldown_global:
            return None

        # Limitar frecuencia por asset (1 trade cada 90s)
        last_ts = self._last_trade_ts.get(asset, 0.0)
        if now - last_ts < 90:
            return None

        best = None
        best_dist = float("inf")

        # El improvement_loop puede endurecer el umbral de confianza segun lo
        # que aprenda de lotes reales (ej. 0.55 -> 0.85 tras una mala racha).
        # Usamos win_rate de zona como proxy de confianza: nunca baja de 0.55.
        adj = self._adjustments()
        adj_min_conf = adj.get("min_confidence")
        min_wr = max(0.55, adj_min_conf) if isinstance(adj_min_conf, (int, float)) else 0.55
        expiry_overrides = adj.get("expiry_by_asset") or {}

        for zone in zones:
            # Muestra minima para confiar en el win rate de una zona: con solo
            # 3 analisis, un 66-100% de acierto puede ser pura casualidad y el
            # bot queda "enganchado" operando una zona que ya no tiene edge.
            if zone.completed_analyses < MIN_ZONE_ANALYSES:
                continue
            if zone.analysis_win_rate < min_wr:
                continue
            if zone.strength < 0.50:
                continue
            # Filtrar WR extremos (contaminados por bugs anteriores)
            if zone.analysis_win_rate >= 0.99 or zone.analysis_win_rate <= 0.01:
                continue

            direction = "CALL" if zone.zone_type == "support" else "PUT"
            dist = abs(current_price - zone.level) / max(abs(zone.level), 0.0001)

            overshoot_buf = max(0.0, zone.avg_overshoot_adv / 10000.0) if hasattr(zone, 'avg_overshoot_adv') else 0.0
            max_dist = min(0.002 + overshoot_buf * 5.0, 0.010)

            # Cambio de rol soporte/resistencia: si hay una zona del tipo
            # OPUESTO al mismo nivel de precio con un toque mas reciente,
            # el mercado probablemente rompio esta zona y ahora actua al
            # reves. No operar la zona vieja hasta que ella misma acumule
            # touques mas recientes que la nueva.
            opposite_type = "resistance" if zone.zone_type == "support" else "support"
            role_flipped = any(
                other.zone_type == opposite_type
                and abs(other.level - zone.level) / max(abs(zone.level), 0.0001) <= max_dist
                and other.last_touch_ts > zone.last_touch_ts
                for other in zones
            )
            if role_flipped:
                continue

            if dist <= max_dist and dist < best_dist:
                # Confirmar rechazo en M1 antes de entrar
                if df_m1 is not None and len(df_m1) >= 2:
                    last = df_m1.iloc[-1]
                    if direction == "CALL":
                        # Debe mostrar vela alcista cerrando sobre soporte
                        if not (last["close"] > last["open"] and last["close"] > zone.level):
                            continue
                    else:
                        # Debe mostrar vela bajista cerrando bajo resistencia
                        if not (last["close"] < last["open"] and last["close"] < zone.level):
                            continue

                # Toma de liquidez contra la direccion propuesta: el precio
                # ya esta revirtiendo hacia el otro lado, no entrar de vuelta.
                if self._liquidity_sweep_against(df_m1, zone.level, direction):
                    continue

                # Verificar no duplicado reciente en esta zona
                dup = False
                for t in self.virtual_trades:
                    if t.resolved:
                        continue
                    if t.asset != asset:
                        continue
                    if t.direction != direction:
                        continue
                    if abs(t.zone_level - zone.level) / max(abs(zone.level), 0.0001) <= 0.003:
                        dup = True
                        break
                if dup:
                    continue

                best = (zone, direction, dist)
                best_dist = dist

        if best is None:
            return None

        zone, direction, dist = best

        # Determinar expiracion segun ATR (volatilidad real) y fuerza de zona,
        # salvo que el improvement_loop haya fijado un minimo para este activo
        # (ej. tras detectar que expiraciones cortas se comportan como ruleta).
        if asset in expiry_overrides:
            try:
                expiration = max(60, int(expiry_overrides[asset]) * 60)
            except (TypeError, ValueError):
                atr = self._calc_atr(df_m1)
                expiration = self._expiration_from_atr(atr, current_price, zone.strength)
        else:
            atr = self._calc_atr(df_m1)
            expiration = self._expiration_from_atr(atr, current_price, zone.strength)

        trade = VirtualTrade(
            asset=asset,
            direction=direction,
            entry_price=current_price,
            amount=self.trade_amount,
            entry_time=now,
            expiration_sec=expiration,
            zone_level=zone.level,
            zone_win_rate=round(zone.analysis_win_rate, 2),
            zone_strength=round(zone.strength, 2),
            zone_type=zone.zone_type,
        )
        self.virtual_trades.append(trade)
        self._last_trade_ts[asset] = now
        self._last_trade_global_ts = now
        self._save()
        return trade

    def resolve_pending(self, asset: str, current_price: float) -> int:
        """Resuelve trades virtuales expirados usando precio real del mercado."""
        now = time.time()
        resueltos = 0
        for t in self.virtual_trades:
            if t.resolved:
                continue
            if t.asset != asset:
                continue
            if now - t.entry_time < t.expiration_sec:
                continue

            t.exit_price = current_price
            if t.direction == "CALL":
                won = current_price > t.entry_price
            else:
                won = current_price < t.entry_price

            t.result = "WIN" if won else "LOSS"
            t.pnl = round(t.amount * BROKER_PAYOUT if won else -t.amount, 2)
            t.resolved = True
            t.resolved_ts = now
            self.virtual_balance += t.pnl
            self.zone_learner.record_trade_result(
                asset=t.asset, direction=t.direction,
                entry=t.entry_price, exit=t.exit_price,
                result=t.result, level=t.zone_level,
            )
            resueltos += 1

        if resueltos:
            self._save()
        return resueltos

    def resolve_all_pending(self, df_by_asset: Dict[str, float]) -> int:
        """Resuelve trades virtuales de todos los activos."""
        total = 0
        for asset, price in df_by_asset.items():
            total += self.resolve_pending(asset, price)
        return total

    def get_stats(self) -> Dict:
        total = len(self.virtual_trades)
        wins = sum(1 for t in self.virtual_trades if t.result == "WIN")
        losses = sum(1 for t in self.virtual_trades if t.result == "LOSS")
        pending = sum(1 for t in self.virtual_trades if not t.resolved)
        wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0.0
        return {
            "balance": round(self.virtual_balance, 2),
            "trades": total,
            "wins": wins,
            "losses": losses,
            "pending": pending,
            "win_rate": round(wr, 1),
            "pnl": round(self.virtual_balance - VIRTUAL_BALANCE_INIT, 2),
            "initial_balance": VIRTUAL_BALANCE_INIT,
        }

    def get_recent_trades(self, n: int = 10) -> List[Dict]:
        return [
            asdict(t) for t in self.virtual_trades[-n:]
        ]

    def _resolve_stale(self):
        """Resuelve trades pendientes que llevan mas de 10min vencidos."""
        now = time.time()
        cambios = False
        for t in self.virtual_trades:
            if t.resolved:
                continue
            if now - t.entry_time > t.expiration_sec + 600:
                t.resolved = True
                t.result = "EXPIRED"
                t.pnl = -t.amount
                t.resolved_ts = now
                self.virtual_balance += t.pnl
                cambios = True
        if cambios:
            self._save()

    def _load(self):
        if os.path.exists(self.persist_path):
            try:
                with open(self.persist_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.virtual_balance = data.get("balance", VIRTUAL_BALANCE_INIT)
                self.virtual_trades = [
                    VirtualTrade(**t) for t in data.get("trades", [])
                ]
            except Exception:
                self.virtual_balance = VIRTUAL_BALANCE_INIT
                self.virtual_trades = []

    def _save(self):
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
        data = {
            "balance": self.virtual_balance,
            "trades": [asdict(t) for t in self.virtual_trades[-1000:]],
        }
        with open(self.persist_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
