"""
Advanced Risk Manager - Sistema de Gestión de Riesgo Profesional
Implementa Kelly Criterion, Drawdown Protection, Position Sizing Dinámico
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import json


@dataclass
class RiskConfig:
    """Configuración de riesgo"""
    max_drawdown_daily: float = 0.15  # 15% drawdown máximo diario
    max_drawdown_weekly: float = 0.25  # 25% drawdown máximo semanal
    max_drawdown_monthly: float = 0.35  # 35% drawdown máximo mensual
    kelly_ceiling: float = 0.25  # Máximo 25% del balance por operación
    kelly_floor: float = 0.01  # Mínimo 1% del balance
    max_trades_per_hour: int = 8  # Máximo 8 operaciones por hora
    max_trades_per_day: int = 40  # Máximo 40 operaciones por día
    cooldown_after_loss_seconds: int = 300  # 5 minutos después de pérdida
    stop_after_consecutive_losses: int = 5  # Parar después de 5 pérdidas consecutivas
    min_confidence_threshold: float = 0.65  # Confianza mínima para operar
    volatility_adjustment: bool = True  # Ajustar posición según volatilidad


@dataclass
class TradingStats:
    """Estadísticas de trading para cálculo de Kelly"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    consecutive_losses: int = 0
    last_loss_time: Optional[datetime] = None


class AdvancedRiskManager:
    """
    Gestor de Riesgo Avanzado con Kelly Criterion

    Reemplaza el sistema de monto fijo ($1.00) con:
    - Kelly Criterion dinámico basado en winrate histórico
    - Ajuste por volatilidad (ATR)
    - Protección de drawdown en múltiples timeframe
    - Ajuste por rachas (ganadoras/perdedoras)
    - Cooldown inteligente después de pérdidas
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self.stats = TradingStats()
        self.initial_balance = 0.0
        self.current_balance = 0.0
        self.peak_balance = 0.0
        self.trades_today: List[Dict] = []
        self.trades_this_hour: List[Dict] = []
        self.daily_pnl: Dict[str, float] = {}  # YYYY-MM-DD -> PnL
        self.weekly_pnl: Dict[int, float] = {}  # ISO week -> PnL
        self.monthly_pnl: Dict[str, float] = {}  # YYYY-MM -> PnL

        # Estado actual
        self.is_stopped = False  # Detenido por drawdown
        self.stop_reason: Optional[str] = None
        self.last_trade_time: Optional[datetime] = None
        self.last_trade_was_loss = False
        self._setup_winrate: Optional[float] = None  # Win rate del setup actual

    def initialize(self, balance: float):
        """Inicializar con balance inicial"""
        self.initial_balance = balance
        self.current_balance = balance
        self.peak_balance = balance
        print(f"[OK] Risk Manager inicializado con balance: ${balance:.2f}")

    def set_setup_winrate(self, winrate: Optional[float]):
        """Establecer el win rate del setup actual (del self_evaluator)"""
        self._setup_winrate = winrate

    def update_balance(self, new_balance: float, trade_result: Optional[Dict] = None):
        """
        Actualizar balance después de una operación

        Args:
            new_balance: Nuevo balance después de la operación
            trade_result: Dict con resultado de la operación
        """
        pnl = new_balance - self.current_balance
        was_profitable = pnl > 0

        # Actualizar balances
        self.current_balance = new_balance
        if new_balance > self.peak_balance:
            self.peak_balance = new_balance

        # Actualizar estadísticas
        self.stats.total_trades += 1

        if was_profitable:
            self.stats.winning_trades += 1
            self.stats.total_profit += pnl
            self.stats.consecutive_losses = 0
        else:
            self.stats.losing_trades += 1
            self.stats.total_loss += abs(pnl)
            self.stats.consecutive_losses += 1
            self.stats.last_loss_time = datetime.now()

        # Calcular métricas derivadas
        if self.stats.winning_trades > 0:
            self.stats.avg_win = self.stats.total_profit / self.stats.winning_trades
        if self.stats.losing_trades > 0:
            self.stats.avg_loss = self.stats.total_loss / self.stats.losing_trades
        if self.stats.total_trades > 0:
            self.stats.win_rate = self.stats.winning_trades / self.stats.total_trades
        if self.stats.total_loss > 0:
            self.stats.profit_factor = self.stats.total_profit / self.stats.total_loss

        # Registrar trade
        trade_record = {
            'time': datetime.now(),
            'pnl': pnl,
            'profitable': was_profitable,
            **(trade_result or {})
        }
        self.trades_today.append(trade_record)
        self.trades_this_hour.append(trade_record)

        # Actualizar PnL por periodo
        self._update_period_pnl(pnl)

        # Verificar drawdowns
        self._check_drawdowns()

        # Actualizar estado
        self.last_trade_time = datetime.now()
        self.last_trade_was_loss = not was_profitable

    def _update_period_pnl(self, pnl: float):
        """Actualizar PnL acumulado por periodo"""
        now = datetime.now()
        today_key = now.strftime('%Y-%m-%d')
        week_key = now.isocalendar()[1]
        month_key = now.strftime('%Y-%m')

        self.daily_pnl[today_key] = self.daily_pnl.get(today_key, 0.0) + pnl
        self.weekly_pnl[week_key] = self.weekly_pnl.get(week_key, 0.0) + pnl
        self.monthly_pnl[month_key] = self.monthly_pnl.get(month_key, 0.0) + pnl

    def _check_drawdowns(self):
        """Verificar si se alcanzaron límites de drawdown"""
        if self.peak_balance <= 0:
            return

        current_dd = (self.peak_balance - self.current_balance) / self.peak_balance

        # Verificar drawdown diario
        today_key = datetime.now().strftime('%Y-%m-%d')
        daily_dd = abs(min(0, self.daily_pnl.get(today_key, 0.0))) / self.initial_balance

        # Verificar drawdown semanal
        week_key = datetime.now().isocalendar()[1]
        weekly_dd = abs(min(0, self.weekly_pnl.get(week_key, 0.0))) / self.initial_balance

        # Verificar drawdown mensual
        month_key = datetime.now().strftime('%Y-%m')
        monthly_dd = abs(min(0, self.monthly_pnl.get(month_key, 0.0))) / self.initial_balance

        if daily_dd >= self.config.max_drawdown_daily:
            self.is_stopped = True
            self.stop_reason = f"Drawdown diario alcanzado: {daily_dd*100:.2f}%"
            print(f"[STOP] TRADING DETENIDO: {self.stop_reason}")
        elif weekly_dd >= self.config.max_drawdown_weekly:
            self.is_stopped = True
            self.stop_reason = f"Drawdown semanal alcanzado: {weekly_dd*100:.2f}%"
            print(f"[STOP] TRADING DETENIDO: {self.stop_reason}")
        elif monthly_dd >= self.config.max_drawdown_monthly:
            self.is_stopped = True
            self.stop_reason = f"Drawdown mensual alcanzado: {monthly_dd*100:.2f}%"
            print(f"[STOP] TRADING DETENIDO: {self.stop_reason}")
        elif self.stats.consecutive_losses >= self.config.stop_after_consecutive_losses:
            self.is_stopped = True
            self.stop_reason = f"{self.config.stop_after_consecutive_losses} pérdidas consecutivas"
            print(f"[STOP] TRADING DETENIDO: {self.stop_reason}")
        else:
            # Verificar si podemos reanudar (nuevo día/semana/mes)
            self.is_stopped = False
            self.stop_reason = None

    def calculate_kelly(self) -> float:
        """
        Calcular fracción de Kelly óptima

        Fórmula: Kelly % = W - [(1-W) / R]
        Donde:
            W = Win rate
            R = Profit factor (avg_win / avg_loss)

        Retorna fracción entre 0 y config.kelly_ceiling
        """
        if self.stats.total_trades < 10:
            # Muy pocos trades para estadísticas confiables, usar conservador
            return self.config.kelly_floor

        win_rate = self.stats.win_rate
        if self.stats.avg_loss == 0:
            return self.config.kelly_floor

        profit_ratio = self.stats.avg_win / self.stats.avg_loss

        # Kelly formula
        kelly = win_rate - ((1 - win_rate) / profit_ratio)

        # Aplicar límites
        kelly = max(self.config.kelly_floor, min(self.config.kelly_ceiling, kelly))

        # "Quarter Kelly" para reducir volatilidad (ULTRA conservador)
        kelly = kelly * 0.25

        # Reducir aún más después de pérdidas consecutivas
        if self.stats.consecutive_losses >= 2:
            kelly = kelly * 0.5  # 50% reduction después de 2 pérdidas
        elif self.stats.consecutive_losses >= 1:
            kelly = kelly * 0.75  # 25% reduction después de 1 pérdida

        return kelly

    def calculate_position_size(
        self,
        confidence: float = 0.5,
        atr: Optional[float] = None,
        asset_volatility: float = 1.0
    ) -> float:
        """
        Calcular tamaño de posición usando Kelly Criterion + ajustes

        Args:
            confidence: Nivel de confianza de la señal (0-1)
            atr: Average True Range actual para ajuste por volatilidad
            asset_volatility: Factor de volatilidad del activo (1.0 = normal)

        Returns:
            Tamaño de posición en dólares
        """
        if self.is_stopped:
            print(f"[WARN] No se puede calcular posicion: {self.stop_reason}")
            return 0.0

        # Verificar cooldown después de pérdida
        if self.last_trade_was_loss and self.last_trade_time:
            time_since_loss = (datetime.now() - self.last_trade_time).total_seconds()
            if time_since_loss < self.config.cooldown_after_loss_seconds:
                remaining = self.config.cooldown_after_loss_seconds - time_since_loss
                print(f"[WAIT] Cooldown activo: esperar {remaining:.0f}s mas")
                return 0.0

        # Verificar límites de operaciones
        if not self._can_trade_more():
            print("[WARN] Limite de operaciones alcanzado por hoy/esta hora")
            return 0.0

        # Verificar confianza mínima
        if confidence < self.config.min_confidence_threshold:
            print(f"[WARN] Confianza {confidence*100:.1f}% < minimo {self.config.min_confidence_threshold*100:.1f}%")
            return 0.0

        # Kelly base
        kelly_fraction = self.calculate_kelly()

        # ─── AJUSTE DINÁMICO POR CONFIANZA (Tiers) ──────────────────────
        # En vez de lineal, usar escalera: confianza alta = tamaño desproporcionalmente mayor
        if confidence >= 0.85:
            confidence_adjustment = 1.2  # Boost +20% para setups excelentes
        elif confidence >= 0.75:
            confidence_adjustment = 1.0  # Base completa
        elif confidence >= 0.65:
            confidence_adjustment = 0.8  # Reducir 20%
        elif confidence >= 0.55:
            confidence_adjustment = 0.6  # Reducir 40%
        else:
            confidence_adjustment = 0.4  # Reducir 60% — exploración mínima

        # ─── BONUS POR WIN RATE COMPROBADO ──────────────────────────────
        # Si el setup tiene >60 trades y WR >55%, dar bonus de tamaño
        win_rate_bonus = 1.0
        if hasattr(self, '_setup_winrate') and self._setup_winrate is not None:
            wr = self._setup_winrate
            if wr >= 0.65:
                win_rate_bonus = 1.15  # +15% para setups ganadores
            elif wr >= 0.58:
                win_rate_bonus = 1.05  # +5% para setups prometedores
            elif wr < 0.45:
                win_rate_bonus = 0.7   # -30% para setups perdedores

        # ─── MODO RECUPERACIÓN INTELIGENTE ──────────────────────────────
        # Después de pérdidas, recuperar gradualmente en vez de volver full
        recovery_adjustment = 1.0
        if self.stats.consecutive_losses >= 2:
            # Empezar recuperación: escalar 50% → 70% → 90% → 100%
            recovery_adjustment = min(1.0, 0.5 + (self.stats.consecutive_losses - 2) * 0.1)

        # Ajuste por volatilidad (menor posición = mayor volatilidad)
        volatility_adjustment = 1.0
        if self.config.volatility_adjustment and atr and atr > 0:
            normalized_atr = atr / (self.current_balance * 0.01)
            if normalized_atr > 1:
                volatility_adjustment = 1.0 / normalized_atr

        # Ajuste por racha actual (orden importa: >=5 primero)
        streak_adjustment = 1.0
        if self.stats.consecutive_losses >= 5:
            streak_adjustment = 0.5
        elif self.stats.consecutive_losses >= 3:
            streak_adjustment = 0.7

        # Bonus por racha ganadora (momentum positivo)
        if self.stats.consecutive_wins >= 3:
            streak_adjustment = min(1.2, streak_adjustment + 0.1)

        # Calcular posición final
        base_position = self.current_balance * kelly_fraction
        final_position = (
            base_position *
            confidence_adjustment *
            win_rate_bonus *
            recovery_adjustment *
            volatility_adjustment *
            streak_adjustment *
            asset_volatility
        )

        # Límites absolutos
        min_position = self.current_balance * 0.01  # Mínimo 1%
        max_position = self.current_balance * self.config.kelly_ceiling

        final_position = max(min_position, min(max_position, final_position))

        return round(final_position, 2)

    def _can_trade_more(self) -> bool:
        """Verificar si podemos operar más (límites por hora/día)"""
        now = datetime.now()

        # Limpiar trades viejos (más de 1 hora)
        hour_ago = now - timedelta(hours=1)
        self.trades_this_hour = [
            t for t in self.trades_this_hour
            if t['time'] > hour_ago
        ]

        # Verificar límite por hora
        if len(self.trades_this_hour) >= self.config.max_trades_per_hour:
            return False

        # Verificar límite por día
        today_key = now.strftime('%Y-%m-%d')
        trades_today = len([t for t in self.trades_today if t['time'].strftime('%Y-%m-%d') == today_key])
        if trades_today >= self.config.max_trades_per_day:
            return False

        return True

    def get_status_report(self) -> Dict:
        """Obtener reporte completo del estado de riesgo"""
        drawdown = (self.peak_balance - self.current_balance) / self.peak_balance if self.peak_balance > 0 else 0

        return {
            'balance': self.current_balance,
            'peak_balance': self.peak_balance,
            'initial_balance': self.initial_balance,
            'total_pnl': self.current_balance - self.initial_balance,
            'drawdown': drawdown,
            'is_stopped': self.is_stopped,
            'stop_reason': self.stop_reason,
            'stats': {
                'total_trades': self.stats.total_trades,
                'win_rate': self.stats.win_rate * 100,
                'profit_factor': self.stats.profit_factor,
                'consecutive_losses': self.stats.consecutive_losses,
                'avg_win': self.stats.avg_win,
                'avg_loss': self.stats.avg_loss,
            },
            'kelly_fraction': self.calculate_kelly(),
            'trades_today': len([t for t in self.trades_today if t['time'].strftime('%Y-%m-%d') == datetime.now().strftime('%Y-%m-%d')]),
            'trades_this_hour': len(self.trades_this_hour),
        }

    def reset_daily_counters(self):
        """Resetear contadores diarios (llamar al inicio de cada día)"""
        self.trades_today = []
        self.is_stopped = False
        self.stop_reason = None

    def export_stats(self) -> str:
        """Exportar estadísticas a JSON"""
        return json.dumps({
            'stats': {
                'total_trades': self.stats.total_trades,
                'winning_trades': self.stats.winning_trades,
                'losing_trades': self.stats.losing_trades,
                'win_rate': self.stats.win_rate,
                'profit_factor': self.stats.profit_factor,
                'avg_win': self.stats.avg_win,
                'avg_loss': self.stats.avg_loss,
                'total_profit': self.stats.total_profit,
                'total_loss': self.stats.total_loss,
            },
            'balance_info': {
                'current': self.current_balance,
                'peak': self.peak_balance,
                'initial': self.initial_balance,
            },
            'kelly_fraction': self.calculate_kelly(),
        }, indent=2)


# Singleton para uso global
_risk_manager_instance: Optional[AdvancedRiskManager] = None


def get_risk_manager() -> AdvancedRiskManager:
    """Obtener instancia singleton del Risk Manager"""
    global _risk_manager_instance
    if _risk_manager_instance is None:
        _risk_manager_instance = AdvancedRiskManager()
    return _risk_manager_instance


def initialize_risk_manager(balance: float, config: Optional[RiskConfig] = None) -> AdvancedRiskManager:
    """Inicializar el Risk Manager con balance inicial"""
    global _risk_manager_instance
    _risk_manager_instance = AdvancedRiskManager(config)
    _risk_manager_instance.initialize(balance)
    return _risk_manager_instance
