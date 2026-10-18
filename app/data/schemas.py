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


class DataSource(enum.Enum):
    """De dónde vienen los PRECIOS contra los que se resolvió la operación.

    `ResolutionSource` dice CÓMO se decidió el resultado; `DataSource` dice si
    el precio que se usó era real. Las dos hacen falta, y este es el campo que
    faltaba.

    Sin él, un PaperBroker alimentado por el simulador de microestructura
    produce filas con `resolution_source='candle'` — técnicamente "evidencia"
    — cuyo precio es ruido sintético. El EdgeValidator aprendería edge de una
    serie inventada y lo consolidaría. Es el bug #2 de la auditoría
    (`random.random() < 0.55`) con una capa más de maquillaje: ya no se tira
    una moneda, pero se tira una moneda con forma de vela.

    Regla: evidencia estadística = resolución real SOBRE precio real.
        resolution_source IN ('broker','candle') AND data_source IN ('broker','csv')
    """
    BROKER = "broker"          # vela/precio devuelto por el broker en vivo
    CSV = "csv"                # histórico real cargado desde CSV (replay)
    SIMULATOR = "simulator"    # microestructura sintética: NUNCA es evidencia
    UNKNOWN = "unknown"

    @property
    def is_evidence(self) -> bool:
        """True solo si el precio subyacente es real (broker o histórico CSV)."""
        return self in (DataSource.BROKER, DataSource.CSV)


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
    # Proveniencia dura de la vela. `source` es una etiqueta libre legible por
    # humanos ("exnova", "csv", "mock"); `data_source` es el enum que decide si
    # lo que se derive de esta vela puede contar como evidencia estadistica.
    data_source: "DataSource" = DataSource.UNKNOWN

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
    data_source: DataSource = DataSource.UNKNOWN

    @property
    def is_evidence(self) -> bool:
        """True solo si el resultado proviene de un precio REAL observado.

        Dos condiciones independientes y ambas necesarias:
          1. resuelto contra algo observado (broker reporto PnL, o se comparo
             entry_price contra el close de la vela de expiracion);
          2. ese precio observado era real (broker en vivo o historico CSV),
             no microestructura sintetica.

        La version anterior solo comprobaba la 1. Con un PaperBroker alimentado
        por el simulador, toda operacion cumplia la 1 y ninguna era medible de
        verdad: el EdgeValidator habria aprendido edge de ruido con forma de vela.
        """
        return (
            self.resolution_source in (ResolutionSource.BROKER, ResolutionSource.CANDLE)
            and self.execution_state in (ExecutionState.WON, ExecutionState.LOST)
            and self.data_source.is_evidence
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


# ===========================================================================
# Ciclo de vida de un setup (motor de auto-evaluacion)
# ===========================================================================
#
# Un "setup" es la unidad que se mide y se opera: la combinacion
# (activo, estrategia, direccion, regime, expiracion). No es la estrategia:
# `sr_bounce` puede ser GANADOR en EURUSD-OTC/M15-tendencia/300s y PERDEDOR en
# BTC-OTC/range/60s. Promover o retirar estrategias enteras es la granularidad
# equivocada, y es la que hace que un motor de mejora continua tire el edge de
# un contexto bueno junto al ruido de uno malo.

class SetupState(enum.Enum):
    """Estado operativo de un setup.

    EXPLORACION  setup nuevo o degradado. Se opera, pero a tamano MINIMO: el
                 objetivo es comprar informacion, no ganar dinero.
    PRODUCCION   veredicto GANADOR vigente. Tamano normal.
    RETIRADO     no se opera. Permanente salvo `reopen()` explicito y topado.
    """
    EXPLORACION = "exploracion"
    PRODUCCION = "produccion"
    RETIRADO = "retirado"


class SetupVerdict(enum.Enum):
    """Veredicto estadistico sobre un setup.

    INSUFICIENTE  no hay muestra para concluir nada. NO es "neutro": es
                  "todavia no lo sabemos", y se opera en EXPLORACION.
    RUIDO         hay muestra y el IC cruza el break-even. No se puede afirmar
                  ni edge ni ausencia de edge.
    GANADOR       el IC ENTERO queda por encima del break-even.
    PERDEDOR      el IC ENTERO queda por debajo del break-even.
    """
    INSUFICIENTE = "insuficiente"
    RUIDO = "ruido"
    GANADOR = "ganador"
    PERDEDOR = "perdedor"


@dataclass(frozen=True)
class SetupKey:
    """Identidad de un setup. Inmutable y hashable para usarla de clave."""
    asset: str
    strategy: str
    direction: Direction
    market_regime: MarketRegime
    expiry: int

    @property
    def slug(self) -> str:
        return f"{self.asset}|{self.strategy}|{self.direction.value}|{self.market_regime.value}|{self.expiry}"

    @classmethod
    def from_slug(cls, slug: str) -> "SetupKey":
        asset, strategy, direction, regime, expiry = slug.split("|")
        return cls(asset, strategy, Direction(direction), MarketRegime(regime), int(expiry))


@dataclass
class SetupRecord:
    """Estado persistido de un setup: muestra, veredicto y tamano autorizado."""
    key: SetupKey
    state: SetupState = SetupState.EXPLORACION
    n: int = 0
    # Observaciones con DINERO puesto, frente a `n` que incluye las sombras.
    # Una sombra mide calidad de senal; un trade mide PnL realizado, con riesgo
    # de ejecucion y payout reales. Los dos hacen falta y no son la misma cosa.
    n_traded: int = 0
    wins: int = 0
    win_rate: Optional[float] = None
    win_rate_lower: Optional[float] = None
    win_rate_upper: Optional[float] = None
    avg_payout: float = 0.85
    break_even: Optional[float] = None
    expectancy: Optional[float] = None
    expectancy_lower: Optional[float] = None
    verdict: SetupVerdict = SetupVerdict.INSUFICIENTE
    looks: int = 0                 # cuantas veces se ha re-evaluado (penaliza alpha)
    next_checkpoint: int = 0       # n en el que se vuelve a decidir
    reopened: int = 0              # reaperturas consumidas (hay tope)
    variants: int = 0              # variantes de parametros probadas en esta familia
    updated_at: Optional[datetime] = None
    stake_multiplier: float = 1.0  # 1.0 en PRODUCCION, reducido en EXPLORACION


@dataclass
class ImprovementProposal:
    """Un cambio propuesto por el agente de IA (o por el motor estadistico).

    El LLM PROPONE. Nunca aplica. La aplicacion la decide
    `app/services/improvement_engine.py` contra el gate estadistico y el
    walk-forward. Ese separation es el freno que faltaba en
    `mcp_server_trading.trading_apply_change` (punto 9 de la auditoria): alli
    la unica validacion antes de escribir `data/ai_overrides.json` era un
    filtro de texto trivialmente evadible.
    """
    id: str
    origin: str                    # "llm" | "statistics" | "human"
    target: str                    # "strategy:<nombre>" | "risk" | "expiry" ...
    action: str                    # "tune_param" | "enable" | "disable" | "new_variant"
    payload: dict = field(default_factory=dict)
    rationale: str = ""
    evidence: dict = field(default_factory=dict)
    status: str = "proposed"       # proposed|validated|applied|rejected|rolled_back
    created_at: Optional[datetime] = None
    decided_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    # Medida antes/despues. Sin esto no hay "mejora continua", solo cambio.
    baseline_metric: Optional[float] = None
    candidate_metric: Optional[float] = None
    improvement: Optional[float] = None


@dataclass
class BacktestRun:
    """Una ejecucion de backtest, persistida para poder comparar versiones."""
    id: str
    created_at: datetime
    label: str = ""
    data_source: DataSource = DataSource.UNKNOWN
    asset: str = ""
    strategy: str = ""
    candles_used: int = 0
    params: dict = field(default_factory=dict)
    # Muestra in-sample (donde se eligieron los parametros) y out-of-sample
    # (donde se juzgan). Reportar solo el conjunto donde se ajusto es la forma
    # estandar de autoenganarse; ver `bozidar-quant/quant-strategy-backtester`,
    # que documento un resultado negativo en lugar de esconderlo detras de una
    # curva de equity cherry-picked.
    in_sample: dict = field(default_factory=dict)
    out_of_sample: dict = field(default_factory=dict)
    walk_forward: dict = field(default_factory=dict)
    verdict: str = ""
    honest_note: str = ""
