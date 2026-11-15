"""Composite backend: writes to the primary, mirrors to secondaries, reads from the primary."""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from sba.logging_utils import log_event, logged
from sba.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class CompositeStorage(StorageBackend):
    """Primary backend plus best-effort mirrors (a mirror failure is logged, never fatal)."""

    @logged
    def __init__(self, primary: StorageBackend, secondaries: list[StorageBackend]) -> None:
        """Store the primary and secondary backends."""
        self._primary = primary
        self._secondaries = secondaries

    @logged
    def _mirror(self, method: str, *args: Any) -> None:
        """Call `method` on every secondary; log (warning) and continue on failure."""
        for secondary in self._secondaries:
            try:
                getattr(secondary, method)(*args)
            except Exception as exc:
                log_event(logger, logging.WARNING, "CompositeStorage._mirror", "mirror_failed",
                          backend=type(secondary).__name__, method=method, error=str(exc))

    @logged
    def save_prices(self, market: str, symbol: str, prices: pd.DataFrame) -> int:
        """Save to primary, then mirror."""
        rows = self._primary.save_prices(market, symbol, prices)
        self._mirror("save_prices", market, symbol, prices)
        return rows

    @logged
    def load_prices(self, market: str, symbol: str) -> pd.DataFrame:
        """Load from primary."""
        return self._primary.load_prices(market, symbol)

    @logged
    def save_features(self, market: str, symbol: str, features: pd.DataFrame) -> int:
        """Save to primary, then mirror."""
        rows = self._primary.save_features(market, symbol, features)
        self._mirror("save_features", market, symbol, features)
        return rows

    @logged
    def load_features(self, market: str, symbol: str) -> pd.DataFrame:
        """Load from primary."""
        return self._primary.load_features(market, symbol)

    @logged
    def save_fundamentals(self, market: str, symbol: str, payload: dict[str, Any]) -> None:
        """Save to primary, then mirror."""
        self._primary.save_fundamentals(market, symbol, payload)
        self._mirror("save_fundamentals", market, symbol, payload)

    @logged
    def load_fundamentals(self, market: str, symbol: str) -> dict[str, Any]:
        """Load from primary."""
        return self._primary.load_fundamentals(market, symbol)
