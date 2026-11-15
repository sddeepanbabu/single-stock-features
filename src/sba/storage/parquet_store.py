"""Parquet/JSON file backend: <root>/<MARKET>/<SYMBOL>_{prices,features}.parquet and _fundamentals.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from sba.errors import StorageError
from sba.logging_utils import logged
from sba.schema import PRICE_COLUMNS
from sba.storage.base import StorageBackend, safe_name

_ERRORS = (OSError, ValueError)


class ParquetStorage(StorageBackend):
    """Stores each stock's data as separate Parquet files plus a fundamentals JSON file."""

    @logged
    def __init__(self, root: str | Path) -> None:
        """Remember the root directory (created lazily)."""
        self._root = Path(root)

    @logged
    def _path(self, market: str, symbol: str, kind: str, ext: str = "parquet") -> Path:
        """Return the file path for a stock and data kind."""
        return self._root / safe_name(market) / f"{safe_name(symbol)}_{kind}.{ext}"

    @logged
    def _write_frame(self, path: Path, df: pd.DataFrame) -> int:
        """Write a DataFrame to Parquet, creating folders; return rows written."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path, index=False)
        except _ERRORS as exc:
            raise StorageError(f"Parquet write failed for {path}: {exc}") from exc
        return len(df)

    @logged
    def _read_frame(self, path: Path) -> pd.DataFrame | None:
        """Read a Parquet file, or None if it does not exist."""
        if not path.is_file():
            return None
        try:
            return pd.read_parquet(path)
        except _ERRORS as exc:
            raise StorageError(f"Parquet read failed for {path}: {exc}") from exc

    @logged
    def save_prices(self, market: str, symbol: str, prices: pd.DataFrame) -> int:
        """Overwrite the stock's prices file."""
        return self._write_frame(self._path(market, symbol, "prices"), prices)

    @logged
    def load_prices(self, market: str, symbol: str) -> pd.DataFrame:
        """Read the stock's prices file (empty frame if missing)."""
        df = self._read_frame(self._path(market, symbol, "prices"))
        return pd.DataFrame(columns=PRICE_COLUMNS) if df is None else df

    @logged
    def save_features(self, market: str, symbol: str, features: pd.DataFrame) -> int:
        """Overwrite the stock's features file."""
        return self._write_frame(self._path(market, symbol, "features"), features)

    @logged
    def load_features(self, market: str, symbol: str) -> pd.DataFrame:
        """Read the stock's features file (empty frame if missing)."""
        df = self._read_frame(self._path(market, symbol, "features"))
        return pd.DataFrame() if df is None else df

    @logged
    def save_fundamentals(self, market: str, symbol: str, payload: dict[str, Any]) -> None:
        """Overwrite the stock's fundamentals JSON file."""
        path = self._path(market, symbol, "fundamentals", "json")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
        except _ERRORS as exc:
            raise StorageError(f"Fundamentals write failed for {path}: {exc}") from exc

    @logged
    def load_fundamentals(self, market: str, symbol: str) -> dict[str, Any]:
        """Read the fundamentals JSON file ({} if missing)."""
        path = self._path(market, symbol, "fundamentals", "json")
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except _ERRORS as exc:
            raise StorageError(f"Fundamentals read failed for {path}: {exc}") from exc
