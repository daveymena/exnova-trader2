# -*- coding: utf-8 -*-
"""
Control de concurrencia de posiciones.

Regla principal pedida: **una sola operacion abierta por activo**. Hasta que no
se conoce el resultado no se vuelve a entrar en esa divisa.

No es una restriccion cosmetica. Apilar dos entradas sobre la misma senal
duplica el riesgo sin duplicar la informacion: los dos resultados estan
correlacionados, asi que el dataset gana dos filas pero menos de dos
observaciones independientes. Eso corrompe cualquier medicion posterior de
winrate, que es justo lo que se quiere evitar.

Aplica ademas los limites de seguridad que ya estaban dispersos por el codigo,
pero en un unico sitio donde se pueden auditar.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class GuardConfig:
    max_concurrent_total: int = 3        # posiciones abiertas a la vez, en total
    min_seconds_between_trades: int = 60  # respiro global entre entradas
    min_seconds_same_asset: int = 300     # respiro extra sobre el mismo activo
    max_consecutive_losses: int = 4
    cooldown_after_losses: int = 900      # 15 min de pausa tras la racha
    max_trades_per_hour: int = 12
    max_trades_per_day: int = 60
    daily_loss_limit: float | None = None  # en unidades de cuenta


@dataclass
class GuardState:
    open_by_asset: dict[str, float] = field(default_factory=dict)
    last_trade_at: float = 0.0
    last_by_asset: dict[str, float] = field(default_factory=dict)
    consecutive_losses: int = 0
    cooldown_until: float = 0.0
    recent_trades: list[float] = field(default_factory=list)
    daily_pnl: float = 0.0
    daily_anchor: float = 0.0


class PositionGuard:
    """Decide si se puede abrir una operacion, y explica por que no."""

    def __init__(self, config: GuardConfig | None = None):
        self.cfg = config or GuardConfig()
        self.state = GuardState(daily_anchor=time.time())
        self._lock = threading.Lock()

    # -- consulta ---------------------------------------------------------

    def can_trade(self, asset: str, now: float | None = None) -> tuple[bool, str]:
        """Devuelve (permitido, motivo). El motivo se registra para auditarlo."""
        now = now or time.time()
        with self._lock:
            self._roll_day(now)
            cfg, st = self.cfg, self.state

            # La regla principal: nada de dos posiciones en la misma divisa.
            if asset in st.open_by_asset:
                waiting = int(now - st.open_by_asset[asset])
                return False, f"ya hay una operacion abierta en {asset} ({waiting}s)"

            if len(st.open_by_asset) >= cfg.max_concurrent_total:
                return False, (f"limite de posiciones simultaneas "
                               f"({len(st.open_by_asset)}/{cfg.max_concurrent_total})")

            if now < st.cooldown_until:
                return False, f"en pausa {int(st.cooldown_until - now)}s tras racha de perdidas"

            elapsed = now - st.last_trade_at
            if st.last_trade_at and elapsed < cfg.min_seconds_between_trades:
                return False, (f"espera global: faltan "
                               f"{int(cfg.min_seconds_between_trades - elapsed)}s")

            last_same = st.last_by_asset.get(asset, 0.0)
            if last_same:
                gap = now - last_same
                if gap < cfg.min_seconds_same_asset:
                    return False, (f"espera sobre {asset}: faltan "
                                   f"{int(cfg.min_seconds_same_asset - gap)}s")

            hour_ago = now - 3600
            in_hour = sum(1 for t in st.recent_trades if t > hour_ago)
            if in_hour >= cfg.max_trades_per_hour:
                return False, f"limite horario alcanzado ({in_hour}/{cfg.max_trades_per_hour})"

            if len(st.recent_trades) >= cfg.max_trades_per_day:
                return False, (f"limite diario alcanzado "
                               f"({len(st.recent_trades)}/{cfg.max_trades_per_day})")

            if cfg.daily_loss_limit is not None and st.daily_pnl <= -abs(cfg.daily_loss_limit):
                return False, f"limite de perdida diaria alcanzado ({st.daily_pnl:.2f})"

            return True, "ok"

    # -- transiciones -----------------------------------------------------

    def register_open(self, asset: str, now: float | None = None) -> None:
        now = now or time.time()
        with self._lock:
            self.state.open_by_asset[asset] = now
            self.state.last_trade_at = now
            self.state.last_by_asset[asset] = now
            self.state.recent_trades.append(now)

    def register_close(self, asset: str, result: str, pnl: float,
                       now: float | None = None) -> None:
        now = now or time.time()
        with self._lock:
            self.state.open_by_asset.pop(asset, None)
            self.state.daily_pnl += float(pnl)

            if result == "LOSS":
                self.state.consecutive_losses += 1
                if self.state.consecutive_losses >= self.cfg.max_consecutive_losses:
                    self.state.cooldown_until = now + self.cfg.cooldown_after_losses
                    self.state.consecutive_losses = 0
            elif result == "WIN":
                self.state.consecutive_losses = 0

    # -- interno ----------------------------------------------------------

    def _roll_day(self, now: float) -> None:
        if now - self.state.daily_anchor >= 86400:
            self.state.daily_anchor = now
            self.state.daily_pnl = 0.0
            self.state.recent_trades = [t for t in self.state.recent_trades
                                        if t > now - 3600]

    def snapshot(self) -> dict:
        with self._lock:
            now = time.time()
            return {
                "abiertas": list(self.state.open_by_asset),
                "perdidas_consecutivas": self.state.consecutive_losses,
                "en_pausa": now < self.state.cooldown_until,
                "trades_ultima_hora": sum(1 for t in self.state.recent_trades
                                          if t > now - 3600),
                "trades_hoy": len(self.state.recent_trades),
                "pnl_dia": round(self.state.daily_pnl, 2),
            }


_guard: PositionGuard | None = None


def get_guard(config: GuardConfig | None = None) -> PositionGuard:
    global _guard
    if _guard is None:
        _guard = PositionGuard(config)
    return _guard
