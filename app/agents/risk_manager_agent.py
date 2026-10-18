# -*- coding: utf-8 -*-
"""Gestor de riesgo determinista. Tiene el veto final sobre cada operacion.

TRES BUGS CORREGIDOS RESPECTO A LA VERSION ANTERIOR
---------------------------------------------------
1. SIZING ~100x SOBREDIMENSIONADO (punto 1 de la auditoria). El comentario
   decia "0.5 = 0.5% of equity" pero el codigo hacia
   `equity * (0.5 * confidence)`: con confianza 0.9 eso es el 45% DEL CAPITAL
   POR OPERACION. A payout 0.85 una racha de 3 perdidas -- perfectamente
   normal -- se llevaba el 74% de la cuenta. Ahora el porcentaje se divide
   entre 100 explicitamente y hay suelo y techo absolutos en unidades de dinero.

2. EN MODO PRACTICE NO HABIA NINGUN CONTROL. La version anterior hacia
   `50.0 if practice else config.risk_max_daily_loss_pct` para la perdida
   diaria, 100 operaciones/dia, 20 perdidas consecutivas y cooldown 0. Es
   decir: justo en el modo donde el sistema pasa semanas acumulando datos, los
   circuit breakers estaban desactivados. Un bot que se comporta distinto
   segun el modo no es medible: lo que aprende en practice no aplica a real.
   Ahora los limites son LOS MISMOS en todos los modos. Lo unico que cambia
   segun el modo es el GATE DE EDGE (cuanta evidencia se exige), nunca el
   riesgo.

3. EL CONTADOR DE PERDIDAS CONSECUTIVAS RECIBIA EL DATO INVERTIDO (punto 7).
   `record_trade_result()` hacia `if result.result < 0` sobre un TradeResult
   que el PaperBroker inicializaba en `-amount`, asi que contaba perdidas que
   aun no habian ocurrido; y con ExnovaBroker (que inicializaba en 0.0) el
   contador nunca crecia. Se sustituye por dos llamadas explicitas,
   `on_trade_opened()` y `on_trade_closed()`, y el contador solo se mueve con
   `ExecutionState` ya resuelto.

ANTI-MARTINGALA
---------------
No es solo que no se implemente: hay una comprobacion activa. `_check_no_martingale`
rechaza cualquier stake que supere al anterior justo despues de una perdida,
salvo que el crecimiento de equity lo justifique. La martingala es el patron de
ruina mas comun en binarias (aparece en la mayoria de los repos publicos del
dominio, p.ej. `VitalySvyatyuk/pocket_option_trading_bot` la tiene como
estrategia por defecto con stack [1,3,7,15,31,...]), y con payout < 1 no
funciona ni siquiera en teoria: a 0.85, tras 4 perdidas seguidas ni doblando
se recupera lo perdido.

SIZING
------
* PRODUCCION (edge probado): Kelly fraccionado sobre la COTA INFERIOR de
  Wilson, topado al porcentaje maximo por operacion. Usar la cota inferior y no
  el win rate puntual es deliberado: Kelly es muy sensible a sobreestimar `p`,
  y dimensionar sobre lo que se puede PROBAR en lugar de sobre la media
  muestral es lo que evita la ruina cuando el IC es ancho.
* EXPLORACION (sin edge probado): stake fijo pequeno. Se esta comprando
  informacion, no ganando dinero. Kelly daria 0 aqui (no hay edge demostrado),
  y stake 0 significaria no operar nunca y no acumular muestra jamas: la
  circularidad que bloqueaba el sistema.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from app.config import config, TradingMode
from app.data.schemas import (
    Direction, ExecutionState, MarketRegime, RiskDecision, SetupState, TradeResult,
)
from app.stats.core import breakeven_winrate, fractional_kelly

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Limites de riesgo. IDENTICOS en paper, practice y real."""
    max_daily_loss_pct: float = 3.0
    max_weekly_loss_pct: float = 8.0
    max_consecutive_losses: int = 4
    max_trades_per_day: int = 25
    max_trades_per_hour: int = 6
    max_open_positions: int = 1
    cooldown_after_loss_sec: int = 300
    cooldown_after_trade_sec: int = 45
    # Sizing.
    max_position_pct: float = 1.0        # 1.0 == 1% del equity. No 100%.
    exploration_position_pct: float = 0.5
    kelly_fraction: float = 0.25
    min_stake: float = 1.0
    max_stake: float = 200.0
    # Circuito de racha dentro del dia: tras N perdidas seguidas se para el
    # resto de la sesion, no solo un cooldown. Es la regla que evita que un mal
    # dia se convierta en una mala semana.
    halt_day_after_consecutive_losses: int = 6

    @classmethod
    def from_config(cls) -> "RiskLimits":
        """Toma los limites de `app.config` interpretando bien los porcentajes."""
        return cls(
            max_daily_loss_pct=config.risk_max_daily_loss_pct,
            max_weekly_loss_pct=config.risk_max_weekly_loss_pct,
            max_consecutive_losses=config.risk_max_consecutive_losses,
            max_trades_per_day=config.risk_max_trades_per_day,
            max_trades_per_hour=config.risk_max_trades_per_hour,
            max_open_positions=config.risk_max_open_positions,
            cooldown_after_loss_sec=config.risk_cooldown_after_loss_sec,
            cooldown_after_trade_sec=config.risk_cooldown_after_trade_sec,
            # `risk_max_position_pct` en config es 0.5 y el comentario decia
            # "0.5% of equity". Se interpreta como porcentaje, que es lo que
            # siempre se quiso decir.
            max_position_pct=config.risk_max_position_pct,
        )


@dataclass
class RiskState:
    """Estado mutable del dia/semana. Se reinicia con `reset_daily`."""
    trades_today: list = field(default_factory=list)
    consecutive_losses: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    day_start_equity: Optional[float] = None
    week_start_equity: Optional[float] = None
    day_key: Optional[str] = None
    week_key: Optional[str] = None
    last_trade_time: Optional[datetime] = None
    last_loss_time: Optional[datetime] = None
    open_positions: int = 0
    kill_switch: bool = False
    day_halted: bool = False
    day_halt_reason: str = ""
    last_stake: float = 0.0
    rejected_stake: int = 0
    rejected_limits: int = 0
    rejected_martingale: int = 0


class RiskManagerAgent:
    """Veto final determinista. No consulta IA ni depende de nada externo."""

    def __init__(self, limits: Optional[RiskLimits] = None,
                 now_fn=None):
        self.limits = limits or RiskLimits.from_config()
        self.s = RiskState()
        # `now_fn` inyectable para que los tests no dependan del reloj de pared.
        self._now = now_fn or datetime.utcnow

    # ── aprobacion ────────────────────────────────────────────────────────

    def approve(self, asset: str, direction: Direction, strategy: str,
                market_regime: MarketRegime, confidence: float,
                account_equity: float,
                payout: float = 0.85,
                edge: Optional[dict] = None,
                setup_state: SetupState = SetupState.EXPLORACION,
                stake_multiplier: float = 1.0,
                now: Optional[datetime] = None) -> dict:
        """Decide si se opera y con cuanto. Nunca lanza: devuelve un dict."""
        now = now or self._now()
        edge = edge or {}

        if self.s.kill_switch:
            return self._reject(RiskDecision.HALTED, "kill switch activo")
        if self.s.day_halted:
            return self._reject(RiskDecision.HALTED,
                                f"sesion parada: {self.s.day_halt_reason}")

        self._ensure_baselines(account_equity, now)

        # ── limites de perdida ────────────────────────────────────────────
        daily_dd = self._drawdown_pct(self.s.day_start_equity, account_equity)
        if daily_dd > self.limits.max_daily_loss_pct:
            self._halt_day(f"perdida diaria {daily_dd:.2f}% > {self.limits.max_daily_loss_pct}%")
            return self._reject(RiskDecision.HALTED, self.s.day_halt_reason)

        weekly_dd = self._drawdown_pct(self.s.week_start_equity, account_equity)
        if weekly_dd > self.limits.max_weekly_loss_pct:
            return self._reject(RiskDecision.HALTED,
                                f"perdida semanal {weekly_dd:.2f}% > {self.limits.max_weekly_loss_pct}%")

        # ── limites de actividad ──────────────────────────────────────────
        self._prune(now)
        if len(self.s.trades_today) >= self.limits.max_trades_per_day:
            self.s.rejected_limits += 1
            return self._reject(RiskDecision.REJECTED,
                                f"maximo de operaciones/dia ({self.limits.max_trades_per_day})")
        hourly = sum(1 for t in self.s.trades_today
                     if (now - t).total_seconds() < 3600)
        if hourly >= self.limits.max_trades_per_hour:
            self.s.rejected_limits += 1
            return self._reject(RiskDecision.REJECTED,
                                f"maximo de operaciones/hora ({self.limits.max_trades_per_hour})")

        # ── racha de perdidas ─────────────────────────────────────────────
        if self.s.consecutive_losses >= self.limits.halt_day_after_consecutive_losses:
            self._halt_day(f"{self.s.consecutive_losses} perdidas consecutivas")
            return self._reject(RiskDecision.HALTED, self.s.day_halt_reason)
        if self.s.consecutive_losses >= self.limits.max_consecutive_losses:
            self.s.rejected_limits += 1
            return self._reject(
                RiskDecision.REJECTED,
                f"{self.s.consecutive_losses} perdidas consecutivas "
                f"(limite {self.limits.max_consecutive_losses})")

        # ── posiciones abiertas y cooldowns ───────────────────────────────
        if self.s.open_positions >= self.limits.max_open_positions:
            self.s.rejected_limits += 1
            return self._reject(RiskDecision.REJECTED,
                                f"{self.s.open_positions} posiciones abiertas "
                                f"(maximo {self.limits.max_open_positions})")
        if self.s.last_loss_time and self.limits.cooldown_after_loss_sec:
            elapsed = (now - self.s.last_loss_time).total_seconds()
            if elapsed < self.limits.cooldown_after_loss_sec:
                self.s.rejected_limits += 1
                return self._reject(
                    RiskDecision.REJECTED,
                    f"cooldown post-perdida: faltan "
                    f"{self.limits.cooldown_after_loss_sec - elapsed:.0f}s")
        if self.s.last_trade_time and self.limits.cooldown_after_trade_sec:
            elapsed = (now - self.s.last_trade_time).total_seconds()
            if elapsed < self.limits.cooldown_after_trade_sec:
                self.s.rejected_limits += 1
                return self._reject(
                    RiskDecision.REJECTED,
                    f"cooldown entre operaciones: faltan "
                    f"{self.limits.cooldown_after_trade_sec - elapsed:.0f}s")

        # ── payout inviable ───────────────────────────────────────────────
        be = breakeven_winrate(payout)
        if be is None or be >= 0.75:
            # break-even >= 75% significa payout <= 0.33: matematicamente no
            # hay estrategia que lo sostenga. No es una cuestion de riesgo, es
            # que el instrumento no es operable.
            self.s.rejected_limits += 1
            return self._reject(RiskDecision.REJECTED,
                                f"payout {payout:.2f} inviable (break-even {be:.1%})")

        # ── sizing ────────────────────────────────────────────────────────
        stake, sizing_basis = self._size(account_equity, payout, edge, setup_state)
        stake = round(stake * max(0.0, min(1.0, stake_multiplier)), 2)

        if stake < self.limits.min_stake:
            self.s.rejected_limits += 1
            return self._reject(
                RiskDecision.REJECTED,
                f"stake {stake:.2f} por debajo del minimo {self.limits.min_stake:.2f} "
                f"({sizing_basis})")
        if stake > self.limits.max_stake:
            # Se recorta AL TECHO, no se rechaza: el techo existe para proteger,
            # y recortar hacia abajo nunca aumenta el riesgo.
            stake = self.limits.max_stake
            sizing_basis += f" (recortado al techo {self.limits.max_stake:.2f})"
        if stake > account_equity:
            self.s.rejected_limits += 1
            return self._reject(RiskDecision.REJECTED,
                                f"stake {stake:.2f} > equity {account_equity:.2f}")

        # ── invariante anti-martingala ────────────────────────────────────
        ok, why = self._check_no_martingale(stake, account_equity)
        if not ok:
            self.s.rejected_martingale += 1
            return self._reject(RiskDecision.REJECTED, f"anti-martingala: {why}")

        return {
            "decision": RiskDecision.APPROVED,
            "reasons": [],
            "stake": stake,
            "position_size_pct": round(stake / account_equity * 100, 4) if account_equity else 0.0,
            "max_loss": round(stake, 2),
            "max_gain": round(stake * payout, 2),
            "daily_drawdown": round(daily_dd, 2),
            "weekly_drawdown": round(weekly_dd, 2),
            "consecutive_losses": self.s.consecutive_losses,
            "trades_today": len(self.s.trades_today),
            "sizing_basis": sizing_basis,
            "break_even_wr": round(be, 4),
            "setup_state": setup_state.value,
        }

    def _size(self, equity: float, payout: float, edge: dict,
              setup_state: SetupState) -> tuple[float, str]:
        """Tamano de la operacion. Nunca martingala, nunca procentajes crudos."""
        if equity <= 0:
            return 0.0, "equity no positivo"

        if setup_state != SetupState.PRODUCCION:
            # EXPLORACION: stake fijo pequeno. Se compra informacion.
            pct = self.limits.exploration_position_pct / 100.0
            return equity * pct, f"exploracion {self.limits.exploration_position_pct}% del equity"

        # PRODUCCION: Kelly fraccionado sobre la COTA INFERIOR de Wilson.
        wr_lower = edge.get("win_rate_lower")
        if wr_lower is None:
            # Sin cota inferior no hay Kelly. Se cae al sizing de exploracion
            # antes que a dimensionar sobre el win rate puntual.
            pct = self.limits.exploration_position_pct / 100.0
            return equity * pct, "produccion sin IC: sizing conservador"

        cap = self.limits.max_position_pct / 100.0
        f = fractional_kelly(wr_lower, payout, self.limits.kelly_fraction, cap)
        if f <= 0:
            return 0.0, "Kelly no positivo con la cota inferior de Wilson"
        return equity * f, (
            f"Kelly fraccionado ({self.limits.kelly_fraction}) sobre WR_lower="
            f"{wr_lower:.4f}, payout={payout:.2f}, tope {self.limits.max_position_pct}%"
        )

    def _check_no_martingale(self, stake: float, equity: float) -> tuple[bool, str]:
        """Invariante: no subir el stake despues de perder.

        Se permite subirlo SOLO si el equity crecio lo suficiente como para que
        el nuevo stake represente el mismo porcentaje o menos. Es decir: se
        puede escalar con la cuenta, nunca con las perdidas.
        """
        prev = self.s.last_stake
        if prev <= 0 or stake <= prev:
            return True, ""
        if self.s.consecutive_losses > 0:
            return False, (f"stake sube {prev:.2f} -> {stake:.2f} con "
                           f"{self.s.consecutive_losses} perdidas consecutivas")
        prev_pct = prev / self.s.day_start_equity if self.s.day_start_equity else 0
        new_pct = stake / equity if equity else 0
        if prev_pct and new_pct > prev_pct * 1.0001:
            return False, (f"stake sube {prev:.2f} -> {stake:.2f} y ademas gana "
                           f"peso relativo ({prev_pct:.4%} -> {new_pct:.4%})")
        return True, ""

    # ── ciclo de vida de las operaciones ──────────────────────────────────

    def on_trade_opened(self, trade: TradeResult):
        """Se llama al ABRIR. No toca el contador de perdidas: aun no hay resultado."""
        now = trade.entry_time or self._now()
        self.s.trades_today.append(now)
        self.s.last_trade_time = now
        self.s.last_stake = float(trade.stake or 0.0)
        self.s.open_positions += 1

    def on_trade_closed(self, trade: TradeResult):
        """Se llama al CERRAR, con el resultado YA resuelto por evidencia.

        Solo WON y LOST mueven el contador. UNKNOWN y los reembolsos por empate
        NO: no son ni victoria ni derrota, y contabilizarlos sesgaria el
        contador de rachas en cualquier direccion.
        """
        self.s.open_positions = max(0, self.s.open_positions - 1)
        if trade.execution_state == ExecutionState.WON:
            self.s.wins += 1
            self.s.consecutive_losses = 0
        elif trade.execution_state == ExecutionState.LOST:
            self.s.losses += 1
            self.s.consecutive_losses += 1
            self.s.last_loss_time = trade.resolved_at or self._now()
            if self.s.consecutive_losses >= self.limits.halt_day_after_consecutive_losses:
                self._halt_day(f"{self.s.consecutive_losses} perdidas consecutivas")
        else:
            self.s.ties += 1

    def set_open_positions(self, count: int):
        self.s.open_positions = max(0, int(count))

    # ── controles globales ────────────────────────────────────────────────

    def kill(self, reason: str = "manual"):
        self.s.kill_switch = True
        logger.warning("KILL SWITCH activado: %s", reason)

    def resume(self):
        self.s.kill_switch = False
        self.s.day_halted = False
        self.s.day_halt_reason = ""
        logger.info("gestor de riesgo reanudado")

    def _halt_day(self, reason: str):
        self.s.day_halted = True
        self.s.day_halt_reason = reason
        logger.warning("SESION PARADA: %s", reason)

    def reset_daily(self, equity: float, now: Optional[datetime] = None):
        now = now or self._now()
        day_key = now.date().isoformat()
        week_key = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
        if self.s.day_key != day_key:
            self.s.day_key = day_key
            self.s.day_start_equity = equity
            self.s.trades_today.clear()
            self.s.consecutive_losses = 0
            # El halt de sesion se levanta con el dia: fue un corte de emergencia
            # para LA sesion, no una retirada permanente (de eso se encarga el
            # SetupEvaluator, con evidencia).
            self.s.day_halted = False
            self.s.day_halt_reason = ""
        if self.s.week_key != week_key:
            self.s.week_key = week_key
            self.s.week_start_equity = equity

    def state(self) -> dict:
        """Foto del estado, para el dashboard y los informes."""
        return {
            "limits": {
                "max_daily_loss_pct": self.limits.max_daily_loss_pct,
                "max_weekly_loss_pct": self.limits.max_weekly_loss_pct,
                "max_consecutive_losses": self.limits.max_consecutive_losses,
                "halt_day_after_consecutive_losses": self.limits.halt_day_after_consecutive_losses,
                "max_trades_per_day": self.limits.max_trades_per_day,
                "max_trades_per_hour": self.limits.max_trades_per_hour,
                "max_open_positions": self.limits.max_open_positions,
                "max_position_pct": self.limits.max_position_pct,
                "exploration_position_pct": self.limits.exploration_position_pct,
                "min_stake": self.limits.min_stake,
                "max_stake": self.limits.max_stake,
                "cooldown_after_loss_sec": self.limits.cooldown_after_loss_sec,
                "cooldown_after_trade_sec": self.limits.cooldown_after_trade_sec,
            },
            "kill_switch": self.s.kill_switch,
            "day_halted": self.s.day_halted,
            "day_halt_reason": self.s.day_halt_reason,
            "trades_today": len(self.s.trades_today),
            "consecutive_losses": self.s.consecutive_losses,
            "wins": self.s.wins, "losses": self.s.losses, "ties": self.s.ties,
            "open_positions": self.s.open_positions,
            "day_start_equity": self.s.day_start_equity,
            "week_start_equity": self.s.week_start_equity,
            "last_stake": self.s.last_stake,
            "rejected_stake": self.s.rejected_stake,
            "rejected_limits": self.s.rejected_limits,
            "rejected_martingale": self.s.rejected_martingale,
        }

    # ── compatibilidad con el API viejo ───────────────────────────────────

    def record_trade_result(self, result: TradeResult):
        """DEPRECADO pero conservado para no romper `app/main.py` heredado.

        La version anterior mezclaba apertura y cierre en una sola llamada y
        por eso el contador de perdidas recibia el dato invertido. Ahora hace
        las dos cosas en orden, que es lo unico correcto si solo hay una
        llamada disponible.
        """
        if result.execution_state in (ExecutionState.SENT, ExecutionState.PENDING):
            self.on_trade_opened(result)
        else:
            self.on_trade_closed(result)

    # ── internos ──────────────────────────────────────────────────────────

    def _ensure_baselines(self, equity: float, now: datetime):
        if self.s.day_start_equity is None:
            self.s.day_start_equity = equity
            self.s.day_key = now.date().isoformat()
        if self.s.week_start_equity is None:
            self.s.week_start_equity = equity
            iso = now.isocalendar()
            self.s.week_key = f"{iso[0]}-W{iso[1]:02d}"

    def _prune(self, now: datetime):
        self.s.trades_today = [t for t in self.s.trades_today
                               if (now - t).total_seconds() < 86_400]

    @staticmethod
    def _drawdown_pct(baseline: Optional[float], current: float) -> float:
        if not baseline or baseline <= 0:
            return 0.0
        return max(0.0, (baseline - current) / baseline * 100.0)

    def _reject(self, decision: RiskDecision, reason: str) -> dict:
        return {
            "decision": decision,
            "reasons": [reason],
            "stake": 0.0,
            "position_size_pct": 0.0,
            "max_loss": 0.0,
            "max_gain": 0.0,
            "daily_drawdown": 0.0,
            "weekly_drawdown": 0.0,
            "consecutive_losses": self.s.consecutive_losses,
            "trades_today": len(self.s.trades_today),
            "sizing_basis": "rechazado",
            "break_even_wr": None,
            "setup_state": "",
        }
