"""Typed configuration models and loaders (app, sources, markets, screen, universe)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from sba.errors import ConfigError
from sba.logging_utils import logged


class SourceConfig(BaseModel):
    """Settings for one data source adapter (provider, period, retries)."""

    adapter: str
    period: str = "5y"
    interval: str = "1d"
    auto_adjust: bool = False
    retries: int = Field(3, ge=1)
    backoff_seconds: float = Field(2.0, ge=0)


class SourcesConfig(BaseModel):
    """All configured data sources and which one is the default."""

    default_source: str
    sources: dict[str, SourceConfig]


class MarketConfig(BaseModel):
    """Per-market settings: symbol suffix, currency, timezone and optional source override."""

    suffix: str = ""
    currency: str
    timezone: str
    source: str | None = None


class ScreenConfig(BaseModel):
    """Thresholds and windows used to compute features and the passes_screen flag."""

    window_days: int = Field(105, ge=10)
    month_days: int = Field(21, ge=1)
    sma_periods: list[int] = [20, 50, 100, 200]
    sma_fast: int = 50
    sma_slow: int = 100
    liquidity_days: int = 63
    min_return_pct: float = 50
    min_r2: float = 0.85
    min_positive_months: int = 4
    max_drawdown_pct: float = 20
    min_median_traded_value: float = 10_000_000

    @model_validator(mode="after")
    def _check_window(self) -> "ScreenConfig":
        """Ensure the window can hold at least one monthly step."""
        if self.window_days < self.month_days:
            raise ValueError("window_days must be >= month_days")
        return self


class StorageConfig(BaseModel):
    """Storage backends: one primary (read/write) and optional mirrored secondaries."""

    primary: str = "sqlite"
    secondary: list[str] = ["parquet"]
    sqlite_path: str = "data/sba.db"
    parquet_dir: str = "data/parquet"


class LoggingConfig(BaseModel):
    """Logging level, file path and rotation."""

    level: str = "INFO"
    file: str = "logs/sba.log"
    max_bytes: int = 5_000_000
    backup_count: int = 5


class AppConfig(BaseModel):
    """Top-level application configuration (paths to the other config files and storage)."""

    profile: str = "local"
    storage: StorageConfig = StorageConfig()
    log: LoggingConfig = LoggingConfig()
    export_dir: str = "data/exports"
    sources_file: str = "config/sources.yaml"
    markets_file: str = "config/markets.yaml"
    screen_file: str = "config/screen.yaml"
    universe_dir: str = "config/universe"


class StockEntry(BaseModel):
    """One stock in a universe file."""

    symbol: str
    name: str | None = None
    tags: dict[str, Any] = {}

    @field_validator("symbol")
    @classmethod
    def _normalise_symbol(cls, value: str) -> str:
        """Upper-case and trim the symbol."""
        return value.strip().upper()


class Universe(BaseModel):
    """A named list of stocks belonging to one market."""

    name: str
    market: str
    stocks: list[StockEntry] = Field(min_length=1)


@dataclass(frozen=True)
class Settings:
    """Fully loaded configuration bundle passed to the service layer."""

    app: AppConfig
    sources: SourcesConfig
    markets: dict[str, MarketConfig]
    screen: ScreenConfig

    @logged
    def market(self, code: str) -> MarketConfig:
        """Return the market config for a code such as 'NSE' or 'US'."""
        try:
            return self.markets[code.upper()]
        except KeyError as exc:
            raise ConfigError(f"Unknown market '{code}'. Configured: {sorted(self.markets)}") from exc

    @logged
    def source_name_for(self, code: str) -> str:
        """Return the data source name for a market (market override or default source)."""
        name = self.market(code).source or self.sources.default_source
        if name not in self.sources.sources:
            raise ConfigError(f"Source '{name}' is not defined in sources config")
        return name


@logged
def load_yaml(path: str | Path) -> dict[str, Any]:
    """Read a YAML file that must contain a mapping."""
    file = Path(path)
    if not file.is_file():
        raise ConfigError(f"Config file not found: {file}")
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {file}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{file} must contain a YAML mapping")
    return data


@logged
def _validate(model: type[BaseModel], data: dict[str, Any], label: str) -> Any:
    """Validate raw data against a pydantic model, converting failures to ConfigError."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid {label} config: {exc}") from exc


@logged
def load_settings(app_path: str | Path) -> Settings:
    """Load app.yaml and the sources, markets and screen files it references."""
    app = _validate(AppConfig, load_yaml(app_path), "app")
    sources = _validate(SourcesConfig, load_yaml(app.sources_file), "sources")
    raw_markets = load_yaml(app.markets_file).get("markets")
    if not isinstance(raw_markets, dict):
        raise ConfigError("markets file must contain a 'markets' mapping")
    markets = {code.upper(): _validate(MarketConfig, cfg, f"market {code}") for code, cfg in raw_markets.items()}
    screen = _validate(ScreenConfig, load_yaml(app.screen_file), "screen")
    return Settings(app=app, sources=sources, markets=markets, screen=screen)


@logged
def load_universe(ref: str, universe_dir: str | Path) -> Universe:
    """Load a universe by name (looked up in universe_dir) or by explicit .yaml path."""
    candidate = Path(ref)
    if candidate.suffix in (".yaml", ".yml") and candidate.is_file():
        path = candidate
    else:
        path = Path(universe_dir) / f"{ref}.yaml"
    return _validate(Universe, load_yaml(path), "universe")
