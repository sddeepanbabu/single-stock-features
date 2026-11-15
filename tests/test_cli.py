import json

import pytest
from conftest import FakeProvider

from sba import cli
from sba.exports import CsvExporter
from sba.service import AnalysisService
from sba.storage import build_storage


def patch_service(monkeypatch, provider):
    def fake_build(settings):
        return AnalysisService(settings, build_storage(settings.app.storage),
                               CsvExporter(settings.app.export_dir), provider_factory=lambda n: provider)
    monkeypatch.setattr(cli, "build_service", fake_build)


def test_parser_requires_command():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def test_main_ok_single_symbol(config_dir, prices, monkeypatch, capsys):
    patch_service(monkeypatch, FakeProvider(prices))
    code = cli.main(["run", "--universe", "demo", "--symbol", "centum", "--config", str(config_dir)])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["status"] == "ok" and report["succeeded"] == 1 and report["run_id"]


def test_main_partial_failure(config_dir, prices, monkeypatch, capsys):
    patch_service(monkeypatch, FakeProvider(prices, bad={"BAD"}))
    code = cli.main(["fetch", "--universe", "demo", "--config", str(config_dir)])
    assert code == 1 and json.loads(capsys.readouterr().out)["status"] == "partial"


def test_main_config_error(tmp_path, capsys):
    code = cli.main(["run", "--universe", "demo", "--config", str(tmp_path / "missing.yaml")])
    assert code == 2 and "ConfigError" in capsys.readouterr().err


def test_main_unknown_symbol_is_domain_error(config_dir, prices, monkeypatch, capsys):
    patch_service(monkeypatch, FakeProvider(prices))
    assert cli.main(["run", "--universe", "demo", "--symbol", "ZZZ", "--config", str(config_dir)]) == 2


def test_main_unexpected_error(config_dir, monkeypatch, capsys):
    def boom(settings):
        raise RuntimeError("kaput")
    monkeypatch.setattr(cli, "build_service", boom)
    code = cli.main(["run", "--universe", "demo", "--config", str(config_dir)])
    assert code == 3 and "kaput" in capsys.readouterr().err
