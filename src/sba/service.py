"""Application service: orchestrates fetch and feature phases for stocks and universes."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Callable

from sba.config import Settings, Universe
from sba.errors import ConfigError, StorageError
from sba.exports import CsvExporter
from sba.features import compute_features
from sba.logging_utils import log_event, logged
from sba.providers import build_provider
from sba.providers.base import PriceProvider
from sba.storage import build_storage
from sba.storage.base import StorageBackend

logger = logging.getLogger(__name__)
PHASES = ("fetch", "features", "run")
_LATEST_FIELDS = ("close", "rolling_return", "rolling_r2", "rolling_max_drawdown",
                  "rolling_positive_months", "passes_screen")


def _py(value: Any) -> Any:
    """Convert numpy scalars to Python values and NaN to None."""
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


class AnalysisService:
    """Runs the fetch and feature phases; used by the CLI today and by agents/APIs later."""

    @logged
    def __init__(self, settings: Settings, storage: StorageBackend, exporter: CsvExporter,
                 provider_factory: Callable[[str], PriceProvider] | None = None) -> None:
        """Wire settings, storage, exporter and a (lazy, cached) provider factory."""
        self._settings = settings
        self._storage = storage
        self._exporter = exporter
        self._factory = provider_factory or (lambda name: build_provider(name, settings.sources))
        self._providers: dict[str, PriceProvider] = {}

    @logged
    def _provider_for(self, market_code: str) -> PriceProvider:
        """Return the cached provider for a market's configured source."""
        name = self._settings.source_name_for(market_code)
        if name not in self._providers:
            self._providers[name] = self._factory(name)
        return self._providers[name]

    @logged
    def _fetch_fundamentals(self, provider: PriceProvider, market_code: str, symbol: str) -> bool:
        """Fetch and store fundamentals; failures are logged and non-fatal. Returns success."""
        try:
            data = provider.fetch_fundamentals(symbol, self._settings.market(market_code))
        except Exception as exc:
            log_event(logger, logging.WARNING, "AnalysisService._fetch_fundamentals", "fundamentals_failed",
                      symbol=symbol, error=str(exc))
            return False
        self._storage.save_fundamentals(market_code, symbol, {
            "market": market_code, "symbol": symbol,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data": data})
        return True

    @logged
    def fetch(self, market_code: str, symbol: str) -> dict[str, Any]:
        """Download history (overwriting stored data) plus fundamentals for one stock."""
        market = self._settings.market(market_code)
        provider = self._provider_for(market_code)
        prices = provider.fetch_history(symbol, market)
        rows = self._storage.save_prices(market_code, symbol, prices)
        return {
            "symbol": symbol, "market": market_code, "rows": rows,
            "first_date": prices["date"].min().strftime("%Y-%m-%d"),
            "last_date": prices["date"].max().strftime("%Y-%m-%d"),
            "fundamentals_saved": self._fetch_fundamentals(provider, market_code, symbol),
        }

    @logged
    def compute(self, market_code: str, symbol: str) -> dict[str, Any]:
        """Compute features from stored prices, store them and export the full CSV."""
        prices = self._storage.load_prices(market_code, symbol)
        if prices.empty:
            raise StorageError(f"No stored prices for {market_code}:{symbol}; run 'fetch' first")
        features = compute_features(prices, self._settings.screen)
        rows = self._storage.save_features(market_code, symbol, features)
        path = self._exporter.export_features(market_code, symbol, features)
        last = features.iloc[-1]
        latest = {"date": last["date"].strftime("%Y-%m-%d"), **{f: _py(last[f]) for f in _LATEST_FIELDS}}
        return {"symbol": symbol, "market": market_code, "rows": rows,
                "export_path": str(path), "latest": latest}

    @logged
    def _run_phase(self, phase: str, market_code: str, symbol: str) -> dict[str, Any]:
        """Execute one phase for one stock."""
        if phase == "fetch":
            return self.fetch(market_code, symbol)
        if phase == "features":
            return self.compute(market_code, symbol)
        return {"fetch": self.fetch(market_code, symbol), "features": self.compute(market_code, symbol)}

    @logged
    def run_universe(self, phase: str, universe: Universe, only_symbol: str | None = None) -> dict[str, Any]:
        """Run a phase for every (or one) stock; a failing stock never stops the others."""
        if phase not in PHASES:
            raise ConfigError(f"Unknown phase '{phase}'. Available: {list(PHASES)}")
        stocks = [s for s in universe.stocks if only_symbol is None or s.symbol == only_symbol.strip().upper()]
        if not stocks:
            raise ConfigError(f"Symbol '{only_symbol}' not found in universe '{universe.name}'")
        results: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for stock in stocks:
            try:
                results.append(self._run_phase(phase, universe.market, stock.symbol))
            except Exception as exc:
                failures.append({"symbol": stock.symbol, "error_type": type(exc).__name__, "error": str(exc)})
        return {"universe": universe.name, "market": universe.market, "phase": phase,
                "total": len(stocks), "succeeded": len(results), "failed": len(failures),
                "results": results, "failures": failures}


@logged
def build_service(settings: Settings) -> AnalysisService:
    """Create the production service from loaded settings."""
    return AnalysisService(settings, build_storage(settings.app.storage), CsvExporter(settings.app.export_dir))
