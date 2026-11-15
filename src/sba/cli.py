"""Command-line interface. JSON report on stdout; JSON logs go to file and stderr."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from sba.config import load_settings, load_universe
from sba.errors import SBAError
from sba.logging_utils import configure_logging, log_event, logged, new_run_id
from sba.service import build_service

logger = logging.getLogger(__name__)


@logged
def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with the fetch, features and run commands."""
    parser = argparse.ArgumentParser(prog="sba", description="Stock Behaviour Analyzer")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("fetch", "download history and fundamentals"),
                       ("features", "compute features from stored history"),
                       ("run", "fetch then compute features")):
        cmd = sub.add_parser(name, help=text)
        cmd.add_argument("--universe", required=True, help="universe name or path to a .yaml file")
        cmd.add_argument("--symbol", help="restrict to one symbol of the universe")
        cmd.add_argument("--config", default="config/app.yaml", help="path to app.yaml")
    return parser


@logged
def _fail(run_id: str, exc: Exception, code: int) -> int:
    """Print a JSON error document to stderr and return the exit code."""
    print(json.dumps({"status": "error", "run_id": run_id,
                      "error_type": type(exc).__name__, "error": str(exc)}), file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    """Entry point. Exit codes: 0 ok, 1 some stocks failed, 2 config/domain error, 3 unexpected error."""
    args = build_parser().parse_args(argv)
    run_id = new_run_id()
    try:
        settings = load_settings(args.config)
        log_cfg = settings.app.log
        configure_logging(log_cfg.level, log_cfg.file, max_bytes=log_cfg.max_bytes,
                          backup_count=log_cfg.backup_count)
        log_event(logger, logging.INFO, "cli.main", "enter", command=args.command,
                  universe=args.universe, symbol=args.symbol)
        universe = load_universe(args.universe, settings.app.universe_dir)
        report = build_service(settings).run_universe(args.command, universe, args.symbol)
    except SBAError as exc:
        return _fail(run_id, exc, 2)
    except Exception as exc:
        log_event(logger, logging.ERROR, "cli.main", "error", error_type=type(exc).__name__, error=str(exc))
        return _fail(run_id, exc, 3)
    report["run_id"] = run_id
    report["status"] = "ok" if report["failed"] == 0 else "partial"
    log_event(logger, logging.INFO, "cli.main", "exit", status=report["status"],
              succeeded=report["succeeded"], failed=report["failed"])
    print(json.dumps(report, default=str))
    return 0 if report["failed"] == 0 else 1
