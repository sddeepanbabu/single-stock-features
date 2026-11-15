"""Storage factory: builds the configured primary (+ mirrors) backend."""
from __future__ import annotations

from sba.config import StorageConfig
from sba.errors import ConfigError
from sba.logging_utils import logged
from sba.storage.base import StorageBackend
from sba.storage.composite import CompositeStorage
from sba.storage.parquet_store import ParquetStorage
from sba.storage.sqlite_store import SQLiteStorage


@logged
def build_storage(config: StorageConfig) -> StorageBackend:
    """Create the primary backend and, if configured, wrap it with secondary mirrors."""
    makers = {
        "sqlite": lambda: SQLiteStorage(config.sqlite_path),
        "parquet": lambda: ParquetStorage(config.parquet_dir),
    }

    def make(name: str) -> StorageBackend:
        maker = makers.get(name)
        if maker is None:
            raise ConfigError(f"Unsupported storage backend '{name}'. Available: {sorted(makers)}")
        return maker()

    primary = make(config.primary)
    secondaries = [make(name) for name in config.secondary]
    return CompositeStorage(primary, secondaries) if secondaries else primary
