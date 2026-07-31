import os
import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class TradingMode(enum.Enum):
    PAPER = "paper"
    PRACTICE = "practice"
    REAL = "real"


class LogFormat(enum.Enum):
    JSON = "json"
    TEXT = "text"


@dataclass
class Config:
    mode: TradingMode = TradingMode.PAPER
    real_trading_enabled: bool = False

    broker_name: str = "iqoption"
    iq_option_email: str = ""
    iq_option_password: str = ""
    exnova_email: str = ""
    exnova_password: str = ""

    opencode_zen_api_key: str = ""
    opencode_zen_base_url: str = "https://opencode.ai/zen/v1"
    github_token: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    risk_max_daily_loss_pct: float = 2.0
    risk_max_weekly_loss_pct: float = 5.0
    risk_max_consecutive_losses: int = 3
    risk_max_trades_per_day: int = 15
    risk_max_trades_per_hour: int = 6
    risk_max_position_pct: float = 0.5
    risk_max_open_positions: int = 3
    risk_cooldown_after_loss_sec: int = 300
    risk_cooldown_after_trade_sec: int = 60

    backtest_default_amount: float = 10000.0
    backtest_min_sample_size: int = 100
    backtest_min_payout: float = 0.80
    backtest_safety_margin: float = 0.03

    strategy_min_confidence: float = 0.65
    strategy_min_zone_strength: float = 0.40

    database_path: str = "data/trading_bot.db"
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON

    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)

    def __post_init__(self):
        mode_str = os.getenv("TRADING_MODE") or os.getenv("ACCOUNT_TYPE", "paper").lower()
        self.mode = TradingMode(mode_str)
        self.real_trading_enabled = os.getenv("REAL_TRADING_ENABLED", "false").lower() == "true"

        self.broker_name = os.getenv("BROKER_NAME", "exnova")
        self.iq_option_email = os.getenv("IQ_OPTION_EMAIL", "")
        self.exnova_email = os.getenv("EXNOVA_EMAIL", "")
        self.exnova_password = os.getenv("EXNOVA_PASSWORD", "")

        self.opencode_zen_api_key = os.getenv("OPENCODE_ZEN_API_KEY", "")

        self.risk_max_daily_loss_pct = float(os.getenv("RISK_MAX_DAILY_LOSS_PCT", "2.0"))
        self.risk_max_consecutive_losses = int(os.getenv("RISK_MAX_CONSECUTIVE_LOSSES", "3"))
        self.risk_max_trades_per_day = int(os.getenv("RISK_MAX_TRADES_PER_DAY", "15"))
        self.risk_max_position_pct = float(os.getenv("RISK_MAX_POSITION_PCT", "0.5"))
        self.risk_max_open_positions = int(os.getenv("RISK_MAX_OPEN_POSITIONS", "3"))

        self.backtest_min_sample_size = int(os.getenv("BACKTEST_MIN_SAMPLE_SIZE", "100"))
        self.backtest_min_payout = float(os.getenv("BACKTEST_MIN_PAYOUT", "0.80"))
        self.backtest_safety_margin = float(os.getenv("BACKTEST_SAFETY_MARGIN", "0.03"))

        self.strategy_min_confidence = float(os.getenv("STRATEGY_MIN_CONFIDENCE", "0.65"))

        self.database_path = os.getenv("DATABASE_PATH", str(self.base_dir / "data" / "trading_bot.db"))
        self.log_level = os.getenv("LOG_LEVEL", "INFO")

        log_fmt = os.getenv("LOG_FORMAT", "json").lower()
        self.log_format = LogFormat.JSON if log_fmt == "json" else LogFormat.TEXT

    def validate(self):
        if self.mode == TradingMode.REAL and not self.real_trading_enabled:
            raise RuntimeError(
                "REAL mode requires REAL_TRADING_ENABLED=true in .env"
            )
        if self.mode in (TradingMode.PRACTICE, TradingMode.REAL):
            if not self.iq_option_email and not self.exnova_email:
                raise RuntimeError(
                    "PRACTICE or REAL mode requires broker credentials in .env"
                )
        return True


config = Config()
