"""Provider interface: every data source adapter returns the same normalised schema."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from sba.config import MarketConfig
from sba.logging_utils import logged


class PriceProvider(ABC):
    """Abstract data provider returning normalised history and a fundamentals snapshot."""

    @logged
    def ticker_for(self, symbol: str, market: MarketConfig) -> str:
        """Build the provider ticker from a symbol and the market's suffix (e.g. CENTUM.NS)."""
        return f"{symbol}{market.suffix}"

    @abstractmethod
    def fetch_history(self, symbol: str, market: MarketConfig) -> pd.DataFrame:
        """Return daily OHLCV with columns date, open, high, low, close, adj_close, volume."""

    @abstractmethod
    def fetch_fundamentals(self, symbol: str, market: MarketConfig) -> dict[str, Any]:
        """Return a flat dict of the current fundamentals snapshot (missing values are None)."""
