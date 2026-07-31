"""Normalized data schemas and enums."""
import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class DataQuality(enum.Enum):
    NORMAL = "normal"
    STALE = "stale"
    DUPLICATE = "duplicate"
    MISSING = "missing"
    SUSPECT = "suspect"


class MarketRegime(enum.Enum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    RANGE = "range"
    HIGH_VOLATILITY = "high_volatility"
    LOW_LIQUIDITY = "low_liquidity"
    NEWS_RISK = "news_risk"
    UNKNOWN = "unknown"


class Timeframe(enum.Enum):
    M1 = 60
    M5 = 300
    M15 = 900
    M30 = 1800
    H1 = 3600


class Direction(enum.Enum):
    CALL = "call"
    PUT = "put"
    NO_TRADE = "no_trade"


class EntryTiming(enum.Enum):
    ENTER_NOW = "enter_now"
    WAIT_CONFIRMATION = "wait_confirmation"
    WAIT_RETEST = "wait_retest"
    TOO_LATE = "too_late"
    NO_TRADE = "no_trade"


class RiskDecision(enum.Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    HALTED = "halted"


class ExecutionState(enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    WON = "won"
    LOST = "lost"
    UNKNOWN = "unknown"
    REJECTED = "rejected"


class TradingMode(enum.Enum):
    PAPER = "paper"
    PRACTICE = "practice"
    REAL = "real"


class ResolutionSource(enum.Enum):
    """Cómo se determinó el resultado de una operación.

    Solo BROKER y CANDLE son evidencia válida para medir edge.
    SIMULATED existe únicamente para tests y jamás debe alimentar
    el EdgeValidator ni el entrenamiento de modelos.
    """
    BROKER = "broker"        # el broker reportó el PnL de la orden
    CANDLE = "candle"        # comparación entry_price vs close de la vela de expiración
    SIMULATED = "simulated"  # sintético: NO es evidencia
    UNRESOLVED = "unresolved"


@dataclass
class Candle:
    asset: str
    timeframe: Timeframe
    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    source: str = "unknown"
    quality: DataQuality = DataQuality.NORMAL

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body_pct(self) -> float:
        if self.range == 0:
            return 0.0
        return self.body / self.range


@dataclass
class MarketRegimeSnapshot:
    timestamp: datetime
    asset: str
    regime: MarketRegime
    adx: float
    atr_percentile: float
    ema_slope: float
    price_distance_ema: float
    features: dict = field(default_factory=dict)


@dataclass
class MultiTimeframeSnapshot:
    timestamp: datetime
    asset: str
    m15_regime: MarketRegime
    m5_regime: MarketRegime
    m1_regime: MarketRegime
    alignment: str  # agree, partial, conflict
    m15_trend: str
    m5_trend: str
    m1_trend: str


@dataclass
class Signal:
    timestamp: datetime
    asset: str
    strategy: str
    direction: Direction
    confidence: float
    market_regime: MarketRegime
    entry_timing: EntryTiming
    expiry: int
    payout: float
    rationale: str
    invalidation: str
    features: dict = field(default_factory=dict)
    opportunity_score: float = 0.0


@dataclass
class TradeDecision:
    timestamp: datetime
    asset: str
    direction: Direction
    strategy: str
    confidence: float
    opportunity_score: float
    market_regime: MarketRegime
    entry_timing: EntryTiming
    expiry: int
    payout: float
    risk_decision: RiskDecision
    risk_reason: Optional[str] = None
    edge_approved: bool = False
    edge_details: Optional[dict] = None
    ai_audit: Optional[str] = None
    execution_state: ExecutionState = ExecutionState.PENDING


@dataclass
class TradeResult:
    timestamp: datetime
    asset: str
    direction: Direction
    strategy: str
    expiry: int
    payout: float
    stake: float
    result: float  # positive = win, negative = loss
    execution_state: ExecutionState
    market_regime: MarketRegime
    confidence: float = 0.0
    entry_timing: EntryTiming = EntryTiming.NO_TRADE
    features: dict = field(default_factory=dict)
    error: Optional[str] = None
    # --- Evidencia de resolución (sin esto el resultado no es medible) ---
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    entry_time: Optional[datetime] = None
    expiry_time: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    broker_order_id: Optional[str] = None
    resolution_source: ResolutionSource = ResolutionSource.UNRESOLVED

    @property
    def is_evidence(self) -> bool:
        """True solo si el resultado proviene de un precio real observado."""
        return (
            self.resolution_source in (ResolutionSource.BROKER, ResolutionSource.CANDLE)
            and self.execution_state in (ExecutionState.WON, ExecutionState.LOST)
        )


@dataclass
class BacktestResult:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    expectancy: float = 0.0
    net_return: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    longest_losing_streak: int = 0
    regime_breakdown: dict = field(default_factory=dict)
    strategy_breakdown: dict = field(default_factory=dict)
    equity_curve: list = field(default_factory=list)


@dataclass
class AccountSnapshot:
    timestamp: datetime
    mode: TradingMode
    equity: float
    balance: float
    daily_pnl: float
    daily_drawdown: float
    open_positions: int
    total_trades_today: int
