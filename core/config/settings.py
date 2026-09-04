"""
Centralized configuration for OptionSentinel.

Every threshold, limit, and mode switch in the system is read from here.
No module outside this file should hardcode a risk limit, scoring weight,
or execution-mode default. This is what makes the system auditable and
lets judges (and us) reason about behavior without reading every file.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AlpacaEnv(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class ExecutionMode(str, Enum):
    """
    The mode ladder is the single source of truth for which BrokerAdapter
    gets used (see integrations/broker_factory.py::get_broker_adapter).
    Nothing else in the codebase should decide real-vs-mock adapter
    selection — that was the Day-1 bug (apps/api/main.py picked the real
    adapter based on "are credentials present" instead of this mode).
    """
    DRY_RUN = "DRY_RUN"
    # Nothing touches Alpaca. MockBrokerAdapter only. Full pipeline runs,
    # logs, journals. This is the default and the safe fallback.

    PAPER_SIMULATION = "PAPER_SIMULATION"
    # Still MockBrokerAdapter (or a future dedicated simulation adapter) —
    # no live network calls. Distinguished from DRY_RUN only by intent/UI
    # labeling: "we are simulating as if paper-trading."

    PAPER_MANUAL_APPROVAL = "PAPER_MANUAL_APPROVAL"
    # Real AlpacaBrokerAdapter (paper endpoint). Pipeline builds and risk-
    # checks real trades against real market data, but STOPS before
    # submit_order and waits for explicit operator approval.

    PAPER_AUTONOMOUS = "PAPER_AUTONOMOUS"
    # Real AlpacaBrokerAdapter (paper endpoint). Approved trades are
    # submitted automatically. Requires explicit operator opt-in — never
    # the default.

    LIVE = "LIVE"
    # Hard-blocked in this build, unconditionally, regardless of any other
    # flag. See integrations/broker_factory.py and
    # integrations/alpaca/adapter.py::LiveTradingDisabledError.


class DeployStage(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    COMPETITION = "competition"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True
    )

    # ── Environment / safety ────────────────────────────────
    alpaca_env: AlpacaEnv = Field(default=AlpacaEnv.PAPER, alias="ALPACA_ENV")
    alpaca_live_trading_confirmed: bool = Field(default=False, alias="ALPACA_LIVE_TRADING_CONFIRMED")
    deploy_stage: DeployStage = Field(default=DeployStage.DEV, alias="DEPLOY_STAGE")
    execution_mode: ExecutionMode = Field(default=ExecutionMode.DRY_RUN, alias="EXECUTION_MODE")

    # ── Alpaca credentials ───────────────────────────────────
    alpaca_api_key: str = Field(
        default="", validation_alias=AliasChoices("APCA_API_KEY_ID", "ALPACA_API_KEY")
    )
    alpaca_secret_key: str = Field(
        default="", validation_alias=AliasChoices("APCA_API_SECRET_KEY", "ALPACA_SECRET_KEY")
    )
    alpaca_paper_base_url: str = Field(
        default="https://paper-api.alpaca.markets", alias="ALPACA_PAPER_BASE_URL"
    )
    alpaca_data_base_url: str = Field(default="https://data.alpaca.markets", alias="ALPACA_DATA_BASE_URL")

    # ── Database ──────────────────────────────────────────────
    database_url: str = Field(default="sqlite:///./data/optionsentinel_dev.db", alias="DATABASE_URL")

    # ── Risk limits ───────────────────────────────────────────
    max_portfolio_risk_pct: float = Field(default=0.06, alias="MAX_PORTFOLIO_RISK_PCT")
    max_trade_risk_pct: float = Field(default=0.015, alias="MAX_TRADE_RISK_PCT")
    max_daily_loss_pct: float = Field(default=0.03, alias="MAX_DAILY_LOSS_PCT")
    max_drawdown_pct: float = Field(default=0.10, alias="MAX_DRAWDOWN_PCT")
    max_open_positions: int = Field(default=8, alias="MAX_OPEN_POSITIONS")
    max_position_concentration_pct: float = Field(default=0.20, alias="MAX_POSITION_CONCENTRATION_PCT")
    max_bid_ask_spread_pct: float = Field(default=0.12, alias="MAX_BID_ASK_SPREAD_PCT")
    min_open_interest: int = Field(default=50, alias="MIN_OPEN_INTEREST")
    min_option_volume: int = Field(default=10, alias="MIN_OPTION_VOLUME")
    stale_quote_seconds: int = Field(default=60, alias="STALE_QUOTE_SECONDS")

    # ── Trade scoring ─────────────────────────────────────────
    score_no_trade_max: int = Field(default=60, alias="SCORE_NO_TRADE_MAX")
    score_small_size_max: int = Field(default=70, alias="SCORE_SMALL_SIZE_MAX")
    score_normal_size_max: int = Field(default=85, alias="SCORE_NORMAL_SIZE_MAX")

    scoring_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "market_regime": 0.25,
            "options_signal": 0.20,
            "volatility_edge": 0.15,
            "momentum": 0.15,
            "liquidity": 0.10,
            "risk_reward": 0.10,
            "news_catalyst": 0.05,
        }
    )

    # ── Logging ───────────────────────────────────────────────
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")

    # ── Universe ──────────────────────────────────────────────
    watchlist: str = Field(default="SPY,QQQ,AAPL,MSFT,NVDA", alias="WATCHLIST")

    @field_validator("scoring_weights")
    @classmethod
    def weights_sum_to_one(cls, v: dict[str, float]) -> dict[str, float]:
        total = round(sum(v.values()), 6)
        if total != 1.0:
            raise ValueError(f"scoring_weights must sum to 1.0, got {total}")
        return v

    @property
    def watchlist_symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.watchlist.split(",") if s.strip()]

    @property
    def is_live_trading_permitted(self) -> bool:
        """
        Hard safety gate. Live trading requires BOTH the env flag and an
        explicit confirmation flag. Day 1 of this build does not implement
        live execution at all — this only prevents silent misconfiguration.
        """
        return self.alpaca_env == AlpacaEnv.LIVE and self.alpaca_live_trading_confirmed


@lru_cache
def get_settings() -> Settings:
    return Settings()
