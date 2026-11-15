import numpy as np
import pytest

from sba.config import ScreenConfig
from sba.errors import FeatureError
from sba.features import compute_features


def test_smooth_uptrend_passes(prices):
    f = compute_features(prices, ScreenConfig())
    last = f.iloc[-1]
    assert last["rolling_r2"] > 0.999 and last["rolling_positive_months"] == 5
    assert last["rolling_return"] > 0.9 and last["rolling_max_drawdown"] > -0.001
    assert last["trend_implied_return"] == pytest.approx(last["rolling_return"], rel=1e-3)
    assert bool(last["passes_screen"]) is True
    assert bool(f.iloc[10]["passes_screen"]) is False and np.isnan(f.iloc[10]["rolling_r2"])
    for col in ("sma_20", "sma_50", "sma_100", "sma_200", "log_close", "traded_value", "daily_return"):
        assert col in f.columns


def test_flat_series_fails(prices):
    flat = prices.copy()
    flat[["open", "high", "low", "close", "adj_close"]] = 100.0
    f = compute_features(flat, ScreenConfig())
    assert f.iloc[-1]["rolling_r2"] == 0.0 and bool(f.iloc[-1]["passes_screen"]) is False


def test_downtrend_fails(prices):
    down = prices.copy()
    down["close"] = down["close"].iloc[::-1].to_numpy()
    assert bool(compute_features(down, ScreenConfig()).iloc[-1]["passes_screen"]) is False


def test_short_history_has_nan_rolling_and_no_pass(prices):
    f = compute_features(prices.head(50), ScreenConfig())
    assert f["rolling_r2"].isna().all() and not f["passes_screen"].any()


def test_sma_union_adds_fast_and_slow(prices):
    f = compute_features(prices, ScreenConfig(sma_periods=[20]))
    assert {"sma_20", "sma_50", "sma_100"} <= set(f.columns)


def test_nan_close_rows_dropped(prices):
    p = prices.copy()
    p.loc[0, "close"] = np.nan
    assert len(compute_features(p, ScreenConfig())) == 299


def test_invalid_inputs(prices):
    with pytest.raises(FeatureError):
        compute_features(prices.drop(columns=["volume"]), ScreenConfig())
    bad = prices.copy()
    bad.loc[5, "close"] = 0
    with pytest.raises(FeatureError):
        compute_features(bad, ScreenConfig())
    empty = prices.copy()
    empty["close"] = np.nan
    with pytest.raises(FeatureError):
        compute_features(empty, ScreenConfig())
