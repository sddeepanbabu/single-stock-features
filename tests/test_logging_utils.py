import io
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sba.logging_utils import (JsonFormatter, configure_logging, get_run_id, log_event, logged,
                               new_run_id, summarize)


def test_summarize_scalars_and_containers():
    assert summarize(None) is None and summarize(True) is True
    assert summarize(np.int64(3)) == 3 and summarize(1.5) == 1.5
    assert summarize(float("nan")) is None and summarize(float("inf")) is None
    assert summarize("x" * 300).endswith("...") and len(summarize("x" * 300)) == 203
    assert summarize(Path("/tmp/a")) == "/tmp/a"
    assert summarize(pd.DataFrame({"a": [1, 2]})) == {"type": "DataFrame", "rows": 2, "cols": 1}
    assert summarize([1, 2, 3]) == {"type": "list", "len": 3}
    assert summarize(object()) == {"type": "object"}
    assert len(summarize({i: i for i in range(30)})) == 20


def test_summarize_masks_secrets():
    assert summarize({"api_token": "abc", "ok": 1}) == {"api_token": "***", "ok": 1}
    assert summarize("abc", key="password") == "***"


def test_logged_success_logs_enter_and_exit(caplog):
    @logged
    def add(a, b, api_key="x"):
        return a + b

    with caplog.at_level(logging.INFO):
        assert add(1, 2, api_key="secret") == 3
    enter, exit_ = caplog.records[0].sba, caplog.records[1].sba
    assert enter["event"] == "enter" and enter["inputs"] == {"a": 1, "b": 2, "api_key": "***"}
    assert exit_["event"] == "exit" and exit_["output"] == 3 and exit_["duration_ms"] >= 0


def test_logged_error_is_logged_and_reraised(caplog):
    @logged
    def boom():
        raise ValueError("bad")

    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        boom()
    err = caplog.records[-1].sba
    assert err["event"] == "error" and err["error_type"] == "ValueError" and err["error"] == "bad"


def test_logged_handles_unbindable_args(caplog):
    @logged
    def f(a):
        return a

    with caplog.at_level(logging.INFO), pytest.raises(TypeError):
        f(1, 2)
    assert caplog.records[0].sba["inputs"] == {"unbound": True}


def test_logged_skips_self(caplog):
    class A:
        @logged
        def m(self, x):
            return x

    with caplog.at_level(logging.INFO):
        A().m(5)
    assert caplog.records[0].sba["inputs"] == {"x": 5}


def test_json_formatter_valid_json_with_and_without_extra():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    lg = logging.getLogger("sba.fmt_test")
    lg.addHandler(handler)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    rid = new_run_id()
    log_event(lg, logging.INFO, "f", "enter", inputs={"a": 1})
    lg.info("plain")
    first, second = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert first["function"] == "f" and first["event"] == "enter" and first["run_id"] == rid == get_run_id()
    assert first["schema"] == "1" and second["message"] == "plain" and "function" not in second


def test_configure_logging_file_and_replacement(tmp_path):
    log_file = tmp_path / "logs" / "x.log"
    lg = configure_logging("DEBUG", log_file, to_stderr=False)
    log_event(lg, logging.INFO, "f", "enter")
    for handler in lg.handlers:
        handler.flush()
    assert json.loads(log_file.read_text().splitlines()[-1])["function"] == "f"
    lg = configure_logging("INFO", None, to_stderr=True)
    assert len(lg.handlers) == 1
