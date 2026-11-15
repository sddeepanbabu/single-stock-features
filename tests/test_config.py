import pytest

from sba.config import ScreenConfig, load_settings, load_universe, load_yaml
from sba.errors import ConfigError


def test_load_yaml_errors(tmp_path):
    with pytest.raises(ConfigError):
        load_yaml(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("a: [unclosed")
    with pytest.raises(ConfigError):
        load_yaml(bad)
    listy = tmp_path / "list.yaml"
    listy.write_text("- a\n- b\n")
    with pytest.raises(ConfigError):
        load_yaml(listy)


def test_load_settings_ok(config_dir):
    s = load_settings(config_dir)
    assert s.market("nse").suffix == ".NS"
    assert s.source_name_for("NSE") == "yf"
    assert s.screen.window_days == 105


def test_load_settings_invalid_screen(config_dir, tmp_path):
    (tmp_path / "screen.yaml").write_text("window_days: 5\n")
    with pytest.raises(ConfigError):
        load_settings(config_dir)


def test_load_settings_markets_not_mapping(config_dir, tmp_path):
    (tmp_path / "markets.yaml").write_text("markets: [a, b]\n")
    with pytest.raises(ConfigError):
        load_settings(config_dir)


def test_unknown_market_and_source(config_dir, tmp_path):
    s = load_settings(config_dir)
    with pytest.raises(ConfigError):
        s.market("XX")
    (tmp_path / "markets.yaml").write_text('markets:\n  NSE:\n    currency: INR\n    timezone: UTC\n    source: nope\n')
    with pytest.raises(ConfigError):
        load_settings(config_dir).source_name_for("NSE")


def test_load_universe_by_name_and_path(config_dir, tmp_path):
    s = load_settings(config_dir)
    u = load_universe("demo", s.app.universe_dir)
    assert u.market == "NSE" and [x.symbol for x in u.stocks] == ["CENTUM", "BAD"]
    assert load_universe(str(tmp_path / "universe" / "demo.yaml"), "unused").name == "demo"


def test_load_universe_empty_stocks_invalid(tmp_path):
    (tmp_path / "e.yaml").write_text("name: e\nmarket: NSE\nstocks: []\n")
    with pytest.raises(ConfigError):
        load_universe("e", tmp_path)


def test_screen_window_must_hold_a_month():
    with pytest.raises(ValueError):
        ScreenConfig(window_days=10, month_days=21)
