"""Storage interface. An empty DataFrame / dict means 'nothing stored yet'."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


def safe_name(value: str) -> str:
    """Make a symbol/market safe for file and table names (non-alphanumerics become '_')."""
    return re.sub(r"[^A-Za-z0-9_]+", "_", value)


class StorageBackend(ABC):
    """Abstract persistence for raw prices, computed features and fundamentals."""

    @abstractmethod
    def save_prices(self, market: str, symbol: str, prices: pd.DataFrame) -> int:
        """Replace all stored prices for the stock; return rows written."""

    @abstractmethod
    def load_prices(self, market: str, symbol: str) -> pd.DataFrame:
        """Return stored prices ordered by date (empty frame if none)."""

    @abstractmethod
    def save_features(self, market: str, symbol: str, features: pd.DataFrame) -> int:
        """Replace stored features for the stock; return rows written."""

    @abstractmethod
    def load_features(self, market: str, symbol: str) -> pd.DataFrame:
        """Return stored features (empty frame if none)."""

    @abstractmethod
    def save_fundamentals(self, market: str, symbol: str, payload: dict[str, Any]) -> None:
        """Replace the stored fundamentals snapshot."""

    @abstractmethod
    def load_fundamentals(self, market: str, symbol: str) -> dict[str, Any]:
        """Return the stored fundamentals snapshot ({} if none)."""
