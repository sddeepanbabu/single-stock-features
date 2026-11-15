from pathlib import Path

import pytest
from conftest import FakeProvider

from sba.config import StockEntry, Universe
from sba.errors import ConfigError, StorageError
from sba.exports import CsvExporter
from sba.service import AnalysisService, build_service
from sba.storage import build_storage


@pytest.fixture
def storage(settings):
    return build_storage(settings.app.storage)


@pytest.fixture
def service(settings, storage, fake_provider):
    return AnalysisService(settings, storage, CsvExporter(settings.app.export_dir),
                           provider_factory=lambda name: fake_provider)


def test_fetch_stores_prices_and_fundamentals_and_overwrites(service, storage):
    result = service.fetch("NSE", "CENTUM")
    assert result["rows"] == 300 and result["fundamentals_saved"] is True
    assert result["first_date"] == "2023-01-02"
    assert storage.load_fundamentals("NSE", "CENTUM")["data"]["sector"] == "Electronics"
    service.fetch("NSE", "CENTUM")
    assert len(storage.load_prices("NSE", "CENTUM")) == 300


def test_fetch_survives_fundamentals_failure(settings, storage, prices):
    svc = AnalysisService(settings, storage, CsvExporter(settings.app.export_dir),
                          provider_factory=lambda n: FakeProvider(prices, fail_fundamentals=True))
    assert svc.fetch("NSE", "X")["fundamentals_saved"] is False


def test_compute_requires_fetch(service):
    with pytest.raises(StorageError):
        service.compute("NSE", "CENTUM")


def test_compute_after_fetch(service, storage):
    service.fetch("NSE", "CENTUM")
    result = service.compute("NSE", "CENTUM")
    assert result["latest"]["passes_screen"] is True and Path(result["export_path"]).is_file()
    assert "rolling_r2" in storage.load_features("NSE", "CENTUM").columns


def test_unknown_market(service):
    with pytest.raises(ConfigError):
        service.fetch("XX", "A")


def test_provider_is_cached(settings, storage, fake_provider):
    created = []

    def factory(name):
        created.append(name)
        return fake_provider

    svc = AnalysisService(settings, storage, CsvExporter(settings.app.export_dir), provider_factory=factory)
    svc.fetch("NSE", "A")
    svc.fetch("US", "B")
    assert created == ["yf"]


def test_run_universe_collects_failures(settings, storage, prices):
    svc = AnalysisService(settings, storage, CsvExporter(settings.app.export_dir),
                          provider_factory=lambda n: FakeProvider(prices, bad={"BAD"}))
    uni = Universe(name="u", market="NSE", stocks=[StockEntry(symbol="centum"), StockEntry(symbol="bad")])
    report = svc.run_universe("run", uni)
    assert (report["total"], report["succeeded"], report["failed"]) == (2, 1, 1)
    assert report["failures"][0]["symbol"] == "BAD" and report["failures"][0]["error_type"] == "DataFetchError"
    assert set(report["results"][0]) == {"fetch", "features"}


def test_run_universe_phases_and_filters(service):
    uni = Universe(name="u", market="US", stocks=[StockEntry(symbol="AAPL"), StockEntry(symbol="MSFT")])
    assert service.run_universe("fetch", uni, "aapl")["total"] == 1
    assert service.run_universe("features", uni, "AAPL")["succeeded"] == 1
    with pytest.raises(ConfigError):
        service.run_universe("nope", uni)
    with pytest.raises(ConfigError):
        service.run_universe("fetch", uni, "TSLA")


def test_build_service(settings):
    assert isinstance(build_service(settings), AnalysisService)
