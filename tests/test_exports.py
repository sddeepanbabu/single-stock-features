import pandas as pd
import pytest

from sba.config import ScreenConfig
from sba.errors import StorageError
from sba.exports import CsvExporter
from sba.features import compute_features


def test_export_writes_full_csv(tmp_path, prices):
    feats = compute_features(prices, ScreenConfig())
    path = CsvExporter(tmp_path / "ex").export_features("NSE", "CENTUM", feats)
    assert path.name == "CENTUM_full.csv"
    back = pd.read_csv(path)
    assert len(back) == 300 and {"close", "rolling_r2", "passes_screen"} <= set(back.columns)
    assert back["date"].iloc[0] == "2023-01-02"


def test_export_error(tmp_path, prices):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(StorageError):
        CsvExporter(blocker).export_features("NSE", "X", compute_features(prices, ScreenConfig()))
