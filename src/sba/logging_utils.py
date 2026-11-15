"""Structured JSON logging and the @logged decorator applied to every SBA method.

Log line schema (version 1): schema, ts, level, run_id, logger, message, plus for
method events: function, event (enter|exit|error), inputs, output, duration_ms,
error_type, error. Logging infrastructure itself (this module) is not decorated to
avoid recursion.
"""
from __future__ import annotations

import contextvars
import functools
import inspect
import json
import logging
import math
import numbers
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, TypeVar

import pandas as pd

LOG_SCHEMA_VERSION = "1"
_SECRET_PATTERN = re.compile(r"(key|token|secret|password|auth)", re.IGNORECASE)
_MAX_STR = 200
_MAX_KEYS = 20
_run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("sba_run_id", default="-")
F = TypeVar("F", bound=Callable[..., Any])


def new_run_id() -> str:
    """Create, store and return a short unique run id attached to every log line."""
    run_id = uuid.uuid4().hex[:12]
    _run_id_var.set(run_id)
    return run_id


def get_run_id() -> str:
    """Return the current run id ('-' when none has been set)."""
    return _run_id_var.get()


def summarize(value: Any, key: str | None = None) -> Any:
    """Return a small JSON-safe description of a value; masks secrets and omits bulk data."""
    if key is not None and _SECRET_PATTERN.search(str(key)):
        return "***"
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, str):
        return value if len(value) <= _MAX_STR else value[:_MAX_STR] + "..."
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.DataFrame):
        return {"type": "DataFrame", "rows": int(value.shape[0]), "cols": int(value.shape[1])}
    if isinstance(value, dict):
        return {str(k): summarize(v, k) for k, v in list(value.items())[:_MAX_KEYS]}
    if isinstance(value, (list, tuple, set)):
        return {"type": type(value).__name__, "len": len(value)}
    return {"type": type(value).__name__}


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects following the SBA log schema."""

    def format(self, record: logging.LogRecord) -> str:
        """Render one record as JSON, merging the structured 'sba' extra fields if present."""
        payload: dict[str, Any] = {
            "schema": LOG_SCHEMA_VERSION,
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "run_id": get_run_id(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "sba", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload, default=str, ensure_ascii=False)


def log_event(logger: logging.Logger, level: int, function: str, event: str, **fields: Any) -> None:
    """Emit one structured event (function, event name and arbitrary extra fields)."""
    logger.log(level, f"{function} {event}", extra={"sba": {"function": function, "event": event, **fields}})


def configure_logging(
    level: str = "INFO",
    log_file: str | Path | None = None,
    to_stderr: bool = True,
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure the 'sba' logger with JSON handlers (rotating file and/or stderr)."""
    logger = logging.getLogger("sba")
    logger.setLevel(level.upper())
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    formatter = JsonFormatter()
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    if to_stderr:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger


def _bind_inputs(sig: inspect.Signature, args: tuple, kwargs: dict) -> dict[str, Any]:
    """Map call arguments to parameter names and summarise them (self/cls skipped)."""
    try:
        bound = sig.bind_partial(*args, **kwargs)
    except TypeError:
        return {"unbound": True}
    return {n: summarize(v, n) for n, v in bound.arguments.items() if n not in ("self", "cls")}


def logged(func: F) -> F:
    """Decorator: log enter/exit with summarised inputs/outputs and duration; log and re-raise errors."""
    logger = logging.getLogger(func.__module__)
    signature = inspect.signature(func)
    name = func.__qualname__

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        log_event(logger, logging.INFO, name, "enter", inputs=_bind_inputs(signature, args, kwargs))
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            log_event(
                logger, logging.ERROR, name, "error",
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                error_type=type(exc).__name__, error=str(exc),
            )
            raise
        log_event(
            logger, logging.INFO, name, "exit",
            duration_ms=round((time.perf_counter() - start) * 1000, 2), output=summarize(result),
        )
        return result

    return wrapper  # type: ignore[return-value]
