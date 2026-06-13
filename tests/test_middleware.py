"""Tests for TraceMiddleware, driven through Starlette's in-process TestClient.

Covers: trace/span ids made available to the handler and echoed on the
response, W3C traceparent continuation from upstream, upstream X-Request-Id
capture, and the `closes #4` feature -- inbound request headers logged with
secrets redacted.
"""

import logging
import re

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from observability import (
    TraceMiddleware,
    get_request_id,
    get_span_id,
    get_trace_id,
    setup_logging,
)

_TRACEPARENT_RE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$")


@pytest.fixture(autouse=True)
def _provider():
    # setup_logging() installs a real SDK TracerProvider so spans record valid
    # (non-zero) trace/span ids. Without it the API returns no-op spans.
    setup_logging()
    yield


async def _endpoint(request):
    return JSONResponse(
        {
            "trace_id": get_trace_id(),
            "span_id": get_span_id(),
            "request_id": get_request_id(),
        }
    )


@pytest.fixture
def client():
    app = Starlette(
        routes=[Route("/", _endpoint)],
        middleware=[Middleware(TraceMiddleware)],
    )
    return TestClient(app)


def test_response_carries_traceparent_header(client):
    resp = client.get("/")
    assert _TRACEPARENT_RE.match(resp.headers["traceparent"])


def test_trace_and_span_ids_available_in_handler(client):
    resp = client.get("/")
    body = resp.json()
    assert re.fullmatch(r"[0-9a-f]{32}", body["trace_id"])
    assert re.fullmatch(r"[0-9a-f]{16}", body["span_id"])
    # the ids the handler saw are the ones echoed on the response
    assert body["trace_id"] in resp.headers["traceparent"]
    assert body["span_id"] in resp.headers["traceparent"]


def test_upstream_traceparent_is_continued(client):
    incoming_trace = "0af7651916cd43dd8448eb211c80319c"
    incoming_span = "b7ad6b7169203331"
    resp = client.get(
        "/",
        headers={"traceparent": f"00-{incoming_trace}-{incoming_span}-01"},
    )
    body = resp.json()
    # same trace, fresh child span
    assert body["trace_id"] == incoming_trace
    assert body["span_id"] != incoming_span


def test_upstream_request_id_captured(client):
    resp = client.get("/", headers={"X-Request-Id": "upstream-req-123"})
    assert resp.json()["request_id"] == "upstream-req-123"


def test_request_logged_once_with_http_block(client, caplog):
    with caplog.at_level(logging.INFO, logger="observability.middleware"):
        client.get("/orders")

    records = [r for r in caplog.records if r.getMessage() == "Received HTTP request"]
    assert len(records) == 1
    http = records[0].http
    assert http["method"] == "GET"
    assert http["path"] == "/orders"


def test_sensitive_request_headers_are_redacted(client, caplog):
    with caplog.at_level(logging.INFO, logger="observability.middleware"):
        client.get(
            "/",
            headers={
                "Authorization": "Bearer supersecret",
                "X-Api-Key": "key-123",
                "Cookie": "session=abc",
                "User-Agent": "pytest-ua",
            },
        )

    record = next(r for r in caplog.records if r.getMessage() == "Received HTTP request")
    headers = record.http["request_headers"]
    assert headers["authorization"] == "***REDACTED***"
    assert headers["x-api-key"] == "***REDACTED***"
    assert headers["cookie"] == "***REDACTED***"
    # non-sensitive headers pass through untouched
    assert headers["user-agent"] == "pytest-ua"


def test_client_ip_prefers_x_real_ip(client, caplog):
    with caplog.at_level(logging.INFO, logger="observability.middleware"):
        client.get("/", headers={"X-Real-IP": "176.65.139.233"})

    record = next(r for r in caplog.records if r.getMessage() == "Received HTTP request")
    assert record.http["client_ip"] == "176.65.139.233"
