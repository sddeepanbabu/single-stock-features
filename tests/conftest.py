"""Shared fixtures: synthetic prices, settings, fake provider, config files."""
import logging

import numpy as np
import pandas as pd
import pytest

from sba.config import (AppConfig, LoggingConfig, MarketConfig, ScreenConfig, Settings,
                        SourceConfig, SourcesConfig, StorageConfig)
from sba.errors import DataFetchError
from sba.providers.base import PriceProvider


@pytest.fixture(autouse=True)
def _reset_sba_logger():
    """Remove handlers installed by configure_logging between tests."""
    yield
    logger = logging.getLogger("sba")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)


@pytest.fixture
def prices():
    """300 business days of a perfectly smooth uptrend (+~640% overall, +100% per 105 days)."""
    n = 300
    close = 100 * np.exp(np.linspace(0, 2.0, n))
    return pd.DataFrame({
        "date": pd.bdate_range("2023-01-02", periods=n), "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close, "adj_close": close, "volume": np.full(n, 1_000_000.0)})


@pytest.fixture
def settings(tmp_path):
    """Settings pointing every path into tmp_path."""
    app = AppConfig(
        storage=StorageConfig(primary="sqlite", secondary=["parquet"],
                              sqlite_path=str(tmp_path / "sba.db"), parquet_dir=str(tmp_path / "pq")),
        export_dir=str(tmp_path / "exports"), log=LoggingConfig(file=str(tmp_path / "logs" / "sba.log")))
    sources = SourcesConfig(default_source="yf", sources={"yf": SourceConfig(adapter="yfinance", retries=2, backoff_seconds=0)})
    markets = {"NSE": MarketConfig(suffix=".NS", currency="INR", timezone="Asia/Kolkata"),
               "US": MarketConfig(suffix="", currency="USD", timezone="America/New_York", source="yf")}
    return Settings(app=app, sources=sources, markets=markets, screen=ScreenConfig())


class FakeProvider(PriceProvider):
    """In-memory provider; symbols in `bad` raise DataFetchError."""

    def __init__(self, prices, fundamentals=None, fail_fundamentals=False, bad=()):
        self.prices = prices
        self.fundamentals = fundamentals if fundamentals is not None else {"sector": "Electronics", "pe_ratio": 20}
        self.fail_fundamentals = fail_fundamentals
        self.bad = set(bad)

    def fetch_history(self, symbol, market):
        if symbol in self.bad:
            raise DataFetchError(f"no data for {symbol}")
        return self.prices.copy()

    def fetch_fundamentals(self, symbol, market):
        if self.fail_fundamentals:
            raise DataFetchError("fundamentals down")
        return self.fundamentals


@pytest.fixture
def fake_provider(prices):
    """Default fake provider."""
    return FakeProvider(prices)


@pytest.fixture
def config_dir(tmp_path):
    """Write a complete config set under tmp_path and return the app.yaml path."""
    (tmp_path / "sources.yaml").write_text("default_source: yf\nsources:\n  yf:\n    adapter: yfinance\n    retries: 1\n")
    (tmp_path / "markets.yaml").write_text('markets:\n  NSE:\n    suffix: ".NS"\n    currency: INR\n    timezone: Asia/Kolkata\n')
    (tmp_path / "screen.yaml").write_text("window_days: 105\nmin_return_pct: 50\n")
    (tmp_path / "universe").mkdir()
    (tmp_path / "universe" / "demo.yaml").write_text("name: demo\nmarket: NSE\nstocks:\n  - symbol: centum\n  - symbol: bad\n")
    app = tmp_path / "app.yaml"
    app.write_text(
        f"sources_file: {tmp_path / 'sources.yaml'}\nmarkets_file: {tmp_path / 'markets.yaml'}\n"
        f"screen_file: {tmp_path / 'screen.yaml'}\nuniverse_dir: {tmp_path / 'universe'}\n"
        f"export_dir: {tmp_path / 'exports'}\nstorage:\n  primary: sqlite\n  secondary: [parquet]\n"
        f"  sqlite_path: {tmp_path / 'sba.db'}\n  parquet_dir: {tmp_path / 'pq'}\n"
        f"log:\n  level: INFO\n  file: {tmp_path / 'logs' / 'sba.log'}\n")
    return app
