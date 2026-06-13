"""Tests for setup_logging: env-driven handler selection and the JSON formatter
field set. The expected document shape is pinned against a real record captured
from the live `wisepay-ym-api` OpenSearch index.
"""

import io
import json
import logging

import pytest

from observability import setup_logging
from observability._vars import _request_id_var, _span_id_var, _trace_id_var
from observability.handler import OpenSearchHandler

# Fields present on every record in the live wisepay-ym-api index (captured
# 2026-06-13). trace_id/span_id are conditional on an active trace context.
_CAPTURED_BASE_FIELDS = {
    "message",
    "@timestamp",
    "log_sequence",
    "service",
    "env",
    "level",
    "logger",
    "tie_breaker_id",
}


def _emit_and_capture(logger_name="demo", level=logging.INFO, msg="hello", **log_kwargs):
    """Run setup_logging in console mode, emit one record, return it parsed."""
    buf = io.StringIO()
    root = logging.getLogger()
    assert root.handlers, "setup_logging() must run before _emit_and_capture()"
    root.handlers[0].stream = buf
    logging.getLogger(logger_name).log(level, msg, **log_kwargs)
    last_line = buf.getvalue().strip().splitlines()[-1]
    return json.loads(last_line)


# ---------------------------------------------------------------------------
# Handler selection
# ---------------------------------------------------------------------------


def test_console_handler_when_opensearch_unconfigured():
    setup_logging()
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert not isinstance(handler, OpenSearchHandler)


def test_opensearch_handler_when_host_and_password_set(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_HOST", "http://opensearch.local:9200")
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "secret")
    monkeypatch.setenv("OPENSEARCH_USER", "logger")
    monkeypatch.setenv("OPENSEARCH_INDEX", "wisepay-ym-api")
    monkeypatch.setenv("LOG_FLUSH_INTERVAL", "3600")  # keep the bg thread quiet

    setup_logging()

    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, OpenSearchHandler)
    assert handler._index == "wisepay-ym-api"
    assert handler._auth == ("logger", "secret")
    assert handler._host == "http://opensearch.local:9200"


def test_host_without_password_uses_console(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_HOST", "http://opensearch.local:9200")
    # no OPENSEARCH_PASSWORD
    setup_logging()
    handler = logging.getLogger().handlers[0]
    assert not isinstance(handler, OpenSearchHandler)


def test_single_handler_replaces_previous(monkeypatch):
    setup_logging()
    setup_logging()
    assert len(logging.getLogger().handlers) == 1


# ---------------------------------------------------------------------------
# Log level
# ---------------------------------------------------------------------------


def test_log_level_respected(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    setup_logging()
    assert logging.getLogger().level == logging.WARNING


def test_invalid_log_level_falls_back_to_debug(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "NOPE")
    setup_logging()
    assert logging.getLogger().level == logging.DEBUG


def test_noisy_loggers_quieted():
    setup_logging()
    for name in ("httpcore", "httpx", "urllib3", "hpack", "requests"):
        assert logging.getLogger(name).level == logging.WARNING


# ---------------------------------------------------------------------------
# JSON formatter field set (pinned to the captured shape)
# ---------------------------------------------------------------------------


def test_record_contains_all_captured_base_fields(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "wisepay-ym-api")
    monkeypatch.setenv("APP_ENV", "production")
    setup_logging()

    doc = _emit_and_capture(logger_name="observability.middleware", msg="Received HTTP request")

    assert _CAPTURED_BASE_FIELDS.issubset(doc)
    assert doc["service"] == "wisepay-ym-api"
    assert doc["env"] == "production"
    assert doc["level"] == "INFO"
    assert doc["logger"] == "observability.middleware"
    assert doc["message"] == "Received HTTP request"
    assert doc["@timestamp"].endswith("Z")
    assert isinstance(doc["log_sequence"], int)


def test_all_field_names_are_snake_case():
    setup_logging()
    doc = _emit_and_capture()
    for key in doc:
        # @timestamp is the one intentional non-snake key (ECS convention).
        if key == "@timestamp":
            continue
        assert key == key.lower(), key
        assert " " not in key


def test_trace_and_span_injected_when_in_context():
    _trace_id_var.set("52054e263603410ea52c5b7393ed1eb1")
    _span_id_var.set("f9361e8a943d0a8a")
    setup_logging()

    doc = _emit_and_capture()

    assert doc["trace_id"] == "52054e263603410ea52c5b7393ed1eb1"
    assert doc["span_id"] == "f9361e8a943d0a8a"


def test_trace_and_span_absent_without_context():
    setup_logging()
    doc = _emit_and_capture()
    assert "trace_id" not in doc
    assert "span_id" not in doc


def test_exception_serialized_to_string():
    setup_logging()
    try:
        raise ValueError("boom")
    except ValueError:
        doc = _emit_and_capture(level=logging.ERROR, msg="failed", exc_info=True)

    assert isinstance(doc["exception"], str)
    assert "Traceback" in doc["exception"]
    assert "ValueError: boom" in doc["exception"]
    # The raw exc_info tuple must not leak into the document.
    assert "exc_info" not in doc


def test_app_extra_fields_pass_through():
    # Fields the application attaches via `extra=` (correlation_id, order_id,
    # ...) must survive into the document untouched -- the OpenSearch mapping
    # maps them and the dashboards depend on them. The formatter does NOT
    # synthesize correlation_id itself; it only passes through app-set fields.
    setup_logging()
    doc = _emit_and_capture(
        msg="order status changed",
        extra={"correlation_id": "c65e0d66-f4a1-45f4-beb0-4804c6a62de3", "order_id": 57962476928},
    )
    assert doc["correlation_id"] == "c65e0d66-f4a1-45f4-beb0-4804c6a62de3"
    assert doc["order_id"] == 57962476928


@pytest.mark.xfail(
    strict=True,
    reason="#9: upstream X-Request-Id is captured but never injected into log records",
)
def test_upstream_request_id_injected_when_in_context():
    _request_id_var.set("upstream-req-123")
    setup_logging()
    doc = _emit_and_capture()
    # The OpenSearch mapping's canonical correlation field is `correlation_id`;
    # accept either name so this flips to passing whichever the fix adopts.
    injected = doc.get("correlation_id") or doc.get("request_id")
    assert injected == "upstream-req-123"
