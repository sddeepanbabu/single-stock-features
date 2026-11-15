"""Provider registry: maps adapter names in config to provider classes."""
from __future__ import annotations

from sba.config import SourcesConfig
from sba.errors import ConfigError
from sba.logging_utils import logged
from sba.providers.base import PriceProvider
from sba.providers.yfinance_provider import YFinanceProvider

ADAPTERS: dict[str, type] = {"yfinance": YFinanceProvider}


@logged
def build_provider(source_name: str, sources: SourcesConfig) -> PriceProvider:
    """Instantiate the provider configured under `source_name`."""
    config = sources.sources.get(source_name)
    if config is None:
        raise ConfigError(f"Source '{source_name}' is not defined")
    adapter = ADAPTERS.get(config.adapter)
    if adapter is None:
        raise ConfigError(f"Unknown adapter '{config.adapter}'. Available: {sorted(ADAPTERS)}")
    return adapter(config)
