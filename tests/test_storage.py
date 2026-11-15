import pytest

from sba.config import ScreenConfig, StorageConfig
from sba.errors import ConfigError, StorageError
from sba.features import compute_features
from sba.storage import build_storage
from sba.storage.composite import CompositeStorage
from sba.storage.parquet_store import ParquetStorage
from sba.storage.sqlite_store import SQLiteStorage


@pytest.fixture(params=["sqlite", "parquet"])
def backend(request, tmp_path):
    return SQLiteStorage(tmp_path / "a.db") if request.param == "sqlite" else ParquetStorage(tmp_path / "pq")


def test_prices_round_trip_and_overwrite(backend, prices):
    assert backend.load_prices("NSE", "X").empty
    assert backend.save_prices("NSE", "X", prices) == 300
    loaded = backend.load_prices("NSE", "X")
    assert len(loaded) == 300 and loaded["close"].iloc[-1] == pytest.approx(prices["close"].iloc[-1])
    assert backend.save_prices("NSE", "X", prices.head(100)) == 100
    assert len(backend.load_prices("NSE", "X")) == 100


def test_prices_with_nan_values(backend, prices):
    p = prices.copy()
    p.loc[3, "volume"] = float("nan")
    backend.save_prices("US", "AAPL", p)
    assert backend.load_prices("US", "AAPL")["volume"].isna().sum() == 1


def test_features_round_trip(backend, prices):
    assert backend.load_features("NSE", "M&M").empty
    feats = compute_features(prices, ScreenConfig())
    assert backend.save_features("NSE", "M&M", feats) == 300
    loaded = backend.load_features("NSE", "M&M")
    assert len(loaded) == 300 and "rolling_r2" in loaded.columns
    assert backend.save_features("NSE", "M&M", feats.head(10)) == 10
    assert len(backend.load_features("NSE", "M&M")) == 10


def test_fundamentals_round_trip(backend):
    assert backend.load_fundamentals("NSE", "X") == {}
    backend.save_fundamentals("NSE", "X", {"data": {"pe_ratio": 20}})
    backend.save_fundamentals("NSE", "X", {"data": {"pe_ratio": 25}})
    assert backend.load_fundamentals("NSE", "X") == {"data": {"pe_ratio": 25}}


OPS = ["save_prices", "load_prices", "save_features", "load_features", "save_fundamentals", "load_fundamentals"]


def call(store, op, df):
    return {
        "save_prices": lambda: store.save_prices("NSE", "X", df),
        "load_prices": lambda: store.load_prices("NSE", "X"),
        "save_features": lambda: store.save_features("NSE", "X", df),
        "load_features": lambda: store.load_features("NSE", "X"),
        "save_fundamentals": lambda: store.save_fundamentals("NSE", "X", {"a": 1}),
        "load_fundamentals": lambda: store.load_fundamentals("NSE", "X"),
    }[op]()


@pytest.mark.parametrize("op", OPS)
def test_sqlite_errors_when_path_is_directory(tmp_path, prices, op):
    with pytest.raises(StorageError):
        call(SQLiteStorage(tmp_path), op, prices)


@pytest.mark.parametrize("op", ["save_prices", "save_features", "save_fundamentals"])
def test_parquet_write_errors_when_root_is_file(tmp_path, prices, op):
    root = tmp_path / "file"
    root.write_text("x")
    with pytest.raises(StorageError):
        call(ParquetStorage(root), op, prices)


@pytest.mark.parametrize("op,name", [("load_prices", "X_prices.parquet"),
                                     ("load_features", "X_features.parquet"),
                                     ("load_fundamentals", "X_fundamentals.json")])
def test_parquet_read_errors_on_corrupt_files(tmp_path, prices, op, name):
    folder = tmp_path / "pq" / "NSE"
    folder.mkdir(parents=True)
    (folder / name).write_text("garbage")
    with pytest.raises(StorageError):
        call(ParquetStorage(tmp_path / "pq"), op, prices)


def test_composite_mirrors_and_tolerates_secondary_failure(tmp_path, prices):
    bad_root = tmp_path / "file"
    bad_root.write_text("x")
    good = ParquetStorage(tmp_path / "pq")
    comp = CompositeStorage(SQLiteStorage(tmp_path / "a.db"), [good, ParquetStorage(bad_root)])
    assert comp.save_prices("NSE", "X", prices) == 300
    assert len(good.load_prices("NSE", "X")) == 300          # mirrored
    assert len(comp.load_prices("NSE", "X")) == 300           # read from primary
    feats = compute_features(prices, ScreenConfig())
    comp.save_features("NSE", "X", feats)
    assert len(comp.load_features("NSE", "X")) == 300
    comp.save_fundamentals("NSE", "X", {"a": 1})
    assert comp.load_fundamentals("NSE", "X") == {"a": 1}


def test_build_storage(tmp_path):
    cfg = StorageConfig(sqlite_path=str(tmp_path / "a.db"), parquet_dir=str(tmp_path / "pq"))
    assert isinstance(build_storage(cfg), CompositeStorage)
    assert isinstance(build_storage(cfg.model_copy(update={"secondary": []})), SQLiteStorage)
    assert isinstance(build_storage(cfg.model_copy(update={"primary": "parquet", "secondary": []})), ParquetStorage)
    with pytest.raises(ConfigError):
        build_storage(cfg.model_copy(update={"primary": "postgres"}))
