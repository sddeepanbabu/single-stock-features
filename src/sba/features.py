"""Feature engine: derived columns, moving averages, rolling trend metrics and screen flags."""
from __future__ import annotations

import numpy as np
import pandas as pd

from sba.config import ScreenConfig
from sba.errors import FeatureError
from sba.logging_utils import logged
from sba.schema import PRICE_COLUMNS


@logged
def _add_rolling_features(df: pd.DataFrame, screen: ScreenConfig) -> pd.DataFrame:
    """Add rolling return, log-linear slope and R-squared, drawdown and monthly-consistency columns."""
    w, step = screen.window_days, screen.month_days
    n_steps = w // step
    xc = np.arange(w, dtype=float) - (w - 1) / 2
    sxx = float((xc ** 2).sum())

    def slope(y: np.ndarray) -> float:
        return float((xc * (y - y.mean())).sum() / sxx)

    def r_squared(y: np.ndarray) -> float:
        yc = y - y.mean()
        syy = float((yc ** 2).sum())
        if syy < 1e-12:
            return 0.0
        return float((xc * yc).sum() ** 2 / (sxx * syy))

    def max_drawdown(a: np.ndarray) -> float:
        return float((a / np.maximum.accumulate(a) - 1).min())

    close = df["close"]
    df["rolling_return"] = close / close.shift(w - 1) - 1
    df["rolling_slope"] = df["log_close"].rolling(w).apply(slope, raw=True)
    df["rolling_r2"] = df["log_close"].rolling(w).apply(r_squared, raw=True)
    df["trend_implied_return"] = np.exp(df["rolling_slope"] * (w - 1)) - 1
    df["rolling_max_drawdown"] = close.rolling(w).apply(max_drawdown, raw=True)
    ups = sum((close.shift(step * k) > close.shift(step * (k + 1))).astype(int) for k in range(n_steps))
    df["rolling_positive_months"] = ups.where(close.shift(step * n_steps).notna())
    return df


@logged
def _add_flags(df: pd.DataFrame, screen: ScreenConfig) -> pd.DataFrame:
    """Add liquidity, trend-health and the combined passes_screen flag (False while data is insufficient)."""
    fast, slow = df[f"sma_{screen.sma_fast}"], df[f"sma_{screen.sma_slow}"]
    df["median_traded_value"] = df["traded_value"].rolling(screen.liquidity_days).median()
    df["above_sma_fast"] = df["close"] > fast
    df["sma_fast_above_slow"] = fast > slow
    df["liquidity_ok"] = df["median_traded_value"] >= screen.min_median_traded_value
    df["passes_screen"] = (
        (df["rolling_return"] >= screen.min_return_pct / 100)
        & (df["rolling_r2"] >= screen.min_r2)
        & (df["rolling_positive_months"] >= screen.min_positive_months)
        & (df["rolling_max_drawdown"] >= -screen.max_drawdown_pct / 100)
        & df["above_sma_fast"] & df["sma_fast_above_slow"] & df["liquidity_ok"]
    )
    return df


@logged
def compute_features(prices: pd.DataFrame, screen: ScreenConfig) -> pd.DataFrame:
    """Return prices plus all derived columns and screen flags (one row per trading day)."""
    missing = [c for c in PRICE_COLUMNS if c not in prices.columns]
    if missing:
        raise FeatureError(f"Price data is missing columns: {missing}")
    df = prices.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    if df.empty:
        raise FeatureError("No usable price rows")
    if (df["close"] <= 0).any():
        raise FeatureError("Non-positive close prices cannot be log-transformed")
    df["daily_return"] = df["close"].pct_change(fill_method=None)
    df["log_close"] = np.log(df["close"])
    df["traded_value"] = df["close"] * df["volume"]
    for period in sorted({*screen.sma_periods, screen.sma_fast, screen.sma_slow}):
        df[f"sma_{period}"] = df["close"].rolling(period).mean()
    return _add_flags(_add_rolling_features(df, screen), screen)
