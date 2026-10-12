import json
import logging

from app.logging_config import JsonFormatter


def _record(message: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord(
        name="app.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=None,
    )


def test_log_output_is_json() -> None:
    line = JsonFormatter().format(_record("unknown weather code: %d", 1234))

    payload = json.loads(line)
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "app.test"
    assert payload["message"] == "unknown weather code: 1234"
    assert payload["time"].endswith("Z")


def test_log_output_is_single_line() -> None:
    line = JsonFormatter().format(_record("first\nsecond"))

    assert "\n" not in line
    assert json.loads(line)["message"] == "first\nsecond"
