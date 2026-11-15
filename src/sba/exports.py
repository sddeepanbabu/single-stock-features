"""CSV export of the full per-stock dataset (raw + derived columns) for human inspection."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from sba.errors import StorageError
from sba.logging_utils import logged
from sba.storage.base import safe_name


class CsvExporter:
    """Writes <export_dir>/<MARKET>/<SYMBOL>_full.csv, overwriting on every run."""

    @logged
    def __init__(self, export_dir: str | Path) -> None:
        """Remember the export directory."""
        self._dir = Path(export_dir)

    @logged
    def export_features(self, market: str, symbol: str, features: pd.DataFrame) -> Path:
        """Write the features frame to CSV and return the file path."""
        path = self._dir / safe_name(market) / f"{safe_name(symbol)}_full.csv"
        out = features.copy()
        out["date"] = out["date"].dt.strftime("%Y-%m-%d")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            out.to_csv(path, index=False)
        except OSError as exc:
            raise StorageError(f"CSV export failed for {path}: {exc}") from exc
        return path
