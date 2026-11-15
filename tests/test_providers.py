import sys
import types

import pandas as pd
import pytest

from sba.config import MarketConfig, SourceConfig, SourcesConfig
from sba.errors import ConfigError, DataFetchError
from sba.providers import build_provider
from sba.providers.yfinance_provider import YFinanceProvider, normalize_history
from sba.schema import PRICE_COLUMNS

NSE = MarketConfig(suffix=".NS", currency="INR", timezone="Asia/Kolkata")
US = MarketConfig(suffix="", currency="USD", timezone="America/New_York")


def raw_frame(adj=True):
    idx = pd.DatetimeIndex(["2024-01-03", "2024-01-02", "2024-01-02"], tz="Asia/Kolkata", name="Date")
    df = pd.DataFrame({"Open": [1, 2, 3.0], "High": [1, 2, 3.0], "Low": [1, 2, 3.0],
                       "Close": [10, 20, 30.0], "Volume": [5, 6, 7.0], "Dividends": 0.0}, index=idx)
    if adj:
        df["Adj Close"] = [9, 19, 29.0]
    return df


def test_normalize_history_basic():
    df = normalize_history(raw_frame())
    assert list(df.columns) == PRICE_COLUMNS and len(df) == 2
    assert df["date"].dt.tz is None and df["date"].is_monotonic_increasing
    assert df.loc[0, "close"] == 30.0  # duplicate date keeps last


def test_normalize_history_without_adj_close():
    df = normalize_history(raw_frame(adj=False))
    assert (df["adj_close"] == df["close"]).all()


@pytest.mark.parametrize("raw", [None, pd.DataFrame()])
def test_normalize_history_empty(raw):
    with pytest.raises(DataFetchError):
        normalize_history(raw)


def test_normalize_history_missing_columns_and_nan_close():
    with pytest.raises(DataFetchError):
        normalize_history(raw_frame().drop(columns=["Volume"]))
    nan = raw_frame()
    nan["Close"] = float("nan")
    with pytest.raises(DataFetchError):
        normalize_history(nan)


def install_fake_yf(monkeypatch, history_fn, info):
    calls = []

    class FakeTicker:
        def __init__(self, ticker):
            self.ticker = ticker
            self.info = info

        def history(self, **kwargs):
            calls.append((self.ticker, kwargs))
            return history_fn(len(calls))

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=FakeTicker))
    return calls


def test_ticker_suffix():
    p = YFinanceProvider(SourceConfig(adapter="yfinance"))
    assert p.ticker_for("CENTUM", NSE) == "CENTUM.NS" and p.ticker_for("AAPL", US) == "AAPL"


def test_fetch_history_success_and_config_passthrough(monkeypatch):
    calls = install_fake_yf(monkeypatch, lambda n: raw_frame(), {})
    df = YFinanceProvider(SourceConfig(adapter="yfinance", period="5y")).fetch_history("CENTUM", NSE)
    assert len(df) == 2 and calls[0][0] == "CENTUM.NS" and calls[0][1]["period"] == "5y"


def test_fetch_history_retries_then_succeeds(monkeypatch):
    def history(n):
        if n == 1:
            raise RuntimeError("temporary")
        return raw_frame()

    install_fake_yf(monkeypatch, history, {})
    sleeps = []
    p = YFinanceProvider(SourceConfig(adapter="yfinance", retries=3, backoff_seconds=2), sleeper=sleeps.append)
    assert len(p.fetch_history("X", US)) == 2 and sleeps == [2]


def test_fetch_history_exhausts_retries(monkeypatch):
    install_fake_yf(monkeypatch, lambda n: pd.DataFrame(), {})
    sleeps = []
    p = YFinanceProvider(SourceConfig(adapter="yfinance", retries=3, backoff_seconds=1), sleeper=sleeps.append)
    with pytest.raises(DataFetchError):
        p.fetch_history("X", US)
    assert sleeps == [1, 2]


def test_fetch_fundamentals(monkeypatch):
    install_fake_yf(monkeypatch, lambda n: raw_frame(), {"marketCap": 123, "trailingPE": 20.5, "sector": "Tech"})
    f = YFinanceProvider(SourceConfig(adapter="yfinance")).fetch_fundamentals("X", US)
    assert f["market_cap"] == 123 and f["pe_ratio"] == 20.5 and f["roe"] is None


def test_fetch_fundamentals_none_info(monkeypatch):
    install_fake_yf(monkeypatch, lambda n: raw_frame(), None)
    assert YFinanceProvider(SourceConfig(adapter="yfinance")).fetch_fundamentals("X", US)["sector"] is None


def test_build_provider():
    sources = SourcesConfig(default_source="y", sources={"y": SourceConfig(adapter="yfinance"), "z": SourceConfig(adapter="nope")})
    assert isinstance(build_provider("y", sources), YFinanceProvider)
    with pytest.raises(ConfigError):
        build_provider("missing", sources)
    with pytest.raises(ConfigError):
        build_provider("z", sources)
