"""SQLite backend (stdlib sqlite3). Creates the database and schema automatically."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from sba.errors import StorageError
from sba.logging_utils import logged
from sba.schema import PRICE_COLUMNS
from sba.storage.base import StorageBackend, safe_name

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
  market TEXT NOT NULL, symbol TEXT NOT NULL, date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, adj_close REAL, volume REAL,
  PRIMARY KEY (market, symbol, date));
CREATE TABLE IF NOT EXISTS fundamentals (
  market TEXT NOT NULL, symbol TEXT NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY (market, symbol));
"""
_ERRORS = (sqlite3.Error, pd.errors.DatabaseError, ValueError)


def _num(value: Any) -> float | None:
    """Convert NaN/None to None and everything else to float."""
    return None if pd.isna(value) else float(value)


class SQLiteStorage(StorageBackend):
    """Stores prices and fundamentals in SQLite; features go to one table per stock."""

    @logged
    def __init__(self, path: str | Path) -> None:
        """Remember the database file path (created lazily)."""
        self._path = Path(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, ensure the schema exists, and always close it."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path)
        try:
            conn.executescript(SCHEMA)
            yield conn
        finally:
            conn.close()

    @logged
    def save_prices(self, market: str, symbol: str, prices: pd.DataFrame) -> int:
        """Atomically delete then insert all price rows for the stock (overwrite semantics)."""
        rows = [
            (market, symbol, r.date.strftime("%Y-%m-%d"), _num(r.open), _num(r.high), _num(r.low),
             _num(r.close), _num(r.adj_close), _num(r.volume))
            for r in prices.itertuples(index=False)
        ]
        try:
            with self._connect() as conn, conn:
                conn.execute("DELETE FROM prices WHERE market=? AND symbol=?", (market, symbol))
                conn.executemany("INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?)", rows)
        except _ERRORS as exc:
            raise StorageError(f"SQLite save_prices failed for {market}:{symbol}: {exc}") from exc
        return len(rows)

    @logged
    def load_prices(self, market: str, symbol: str) -> pd.DataFrame:
        """Read stored prices ordered by date."""
        sql = ("SELECT date, open, high, low, close, adj_close, volume FROM prices "
               "WHERE market=? AND symbol=? ORDER BY date")
        try:
            with self._connect() as conn:
                df = pd.read_sql_query(sql, conn, params=(market, symbol))
        except _ERRORS as exc:
            raise StorageError(f"SQLite load_prices failed for {market}:{symbol}: {exc}") from exc
        df["date"] = pd.to_datetime(df["date"])
        return df[PRICE_COLUMNS]

    @logged
    def save_features(self, market: str, symbol: str, features: pd.DataFrame) -> int:
        """Replace the per-stock features table."""
        table = f"features_{safe_name(market)}_{safe_name(symbol)}".lower()
        out = features.copy()
        out["date"] = out["date"].dt.strftime("%Y-%m-%d")
        try:
            with self._connect() as conn:
                out.to_sql(table, conn, if_exists="replace", index=False)
        except _ERRORS as exc:
            raise StorageError(f"SQLite save_features failed for {market}:{symbol}: {exc}") from exc
        return len(out)

    @logged
    def load_features(self, market: str, symbol: str) -> pd.DataFrame:
        """Read the per-stock features table (empty frame if it does not exist)."""
        table = f"features_{safe_name(market)}_{safe_name(symbol)}".lower()
        try:
            with self._connect() as conn:
                found = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                if not found:
                    return pd.DataFrame()
                df = pd.read_sql_query(f'SELECT * FROM "{table}" ORDER BY date', conn)
        except _ERRORS as exc:
            raise StorageError(f"SQLite load_features failed for {market}:{symbol}: {exc}") from exc
        df["date"] = pd.to_datetime(df["date"])
        return df

    @logged
    def save_fundamentals(self, market: str, symbol: str, payload: dict[str, Any]) -> None:
        """Upsert the fundamentals snapshot as JSON."""
        try:
            with self._connect() as conn, conn:
                conn.execute("INSERT OR REPLACE INTO fundamentals VALUES (?,?,?)",
                             (market, symbol, json.dumps(payload, default=str)))
        except _ERRORS as exc:
            raise StorageError(f"SQLite save_fundamentals failed for {market}:{symbol}: {exc}") from exc

    @logged
    def load_fundamentals(self, market: str, symbol: str) -> dict[str, Any]:
        """Return the stored fundamentals snapshot or {}."""
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT payload FROM fundamentals WHERE market=? AND symbol=?",
                                   (market, symbol)).fetchone()
        except _ERRORS as exc:
            raise StorageError(f"SQLite load_fundamentals failed for {market}:{symbol}: {exc}") from exc
        return json.loads(row[0]) if row else {}
