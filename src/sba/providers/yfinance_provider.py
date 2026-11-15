"""yfinance adapter (free, no login). The library is imported lazily."""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

import pandas as pd

from sba.config import MarketConfig, SourceConfig
from sba.errors import DataFetchError
from sba.logging_utils import log_event, logged
from sba.providers.base import PriceProvider
from sba.schema import PRICE_COLUMNS

logger = logging.getLogger(__name__)

_RENAME = {"Open": "open", "High": "high", "Low": "low", "Close": "close",
           "Adj Close": "adj_close", "Volume": "volume"}
FUNDAMENTAL_FIELDS = {
    "name": "longName", "sector": "sector", "industry": "industry",
    "market_cap": "marketCap", "pe_ratio": "trailingPE", "pb_ratio": "priceToBook",
    "roe": "returnOnEquity", "debt_to_equity": "debtToEquity",
    "revenue_growth": "revenueGrowth", "earnings_growth": "earningsGrowth",
    "insider_holding": "heldPercentInsiders",
}


@logged
def normalize_history(raw: pd.DataFrame) -> pd.DataFrame:
    """Convert a yfinance history frame to the normalised schema (naive dates, sorted, de-duplicated)."""
    if raw is None or raw.empty:
        raise DataFetchError("Provider returned no rows")
    df = raw.rename(columns=_RENAME)
    missing = [c for c in ("open", "high", "low", "close", "volume") if c not in df.columns]
    if missing:
        raise DataFetchError(f"Provider response missing columns: {missing}")
    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"]
    index = pd.DatetimeIndex(pd.to_datetime(df.index))
    if index.tz is not None:
        index = index.tz_localize(None)
    df = df.assign(date=index.normalize())[PRICE_COLUMNS].dropna(subset=["close"])
    df = df.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)
    if df.empty:
        raise DataFetchError("Provider returned only rows without a close price")
    return df


class YFinanceProvider(PriceProvider):
    """Fetches history and fundamentals through yfinance with retry and linear backoff."""

    @logged
    def __init__(self, config: SourceConfig, sleeper: Callable[[float], None] = time.sleep) -> None:
        """Store source settings and the sleep function (injectable for tests)."""
        self._cfg = config
        self._sleep = sleeper

    @logged
    def _download(self, ticker: str) -> pd.DataFrame:
        """Call yfinance for raw history."""
        import yfinance as yf

        return yf.Ticker(ticker).history(
            period=self._cfg.period, interval=self._cfg.interval, auto_adjust=self._cfg.auto_adjust
        )

    @logged
    def _info(self, ticker: str) -> dict[str, Any] | None:
        """Call yfinance for the fundamentals info dict."""
        import yfinance as yf

        return yf.Ticker(ticker).info

    @logged
    def fetch_history(self, symbol: str, market: MarketConfig) -> pd.DataFrame:
        """Download and normalise history, retrying on any failure before raising DataFetchError."""
        ticker = self.ticker_for(symbol, market)
        last_error: Exception | None = None
        for attempt in range(1, self._cfg.retries + 1):
            try:
                return normalize_history(self._download(ticker))
            except Exception as exc:  # provider errors are heterogeneous
                last_error = exc
                log_event(logger, logging.WARNING, "YFinanceProvider.fetch_history", "retry",
                          attempt=attempt, ticker=ticker, error=str(exc))
                if attempt < self._cfg.retries:
                    self._sleep(self._cfg.backoff_seconds * attempt)
        raise DataFetchError(f"Failed to fetch {ticker} after {self._cfg.retries} attempts: {last_error}") from last_error

    @logged
    def fetch_fundamentals(self, symbol: str, market: MarketConfig) -> dict[str, Any]:
        """Return the current fundamentals snapshot mapped to SBA field names."""
        info = self._info(self.ticker_for(symbol, market)) or {}
        return {field: info.get(source) for field, source in FUNDAMENTAL_FIELDS.items()}
