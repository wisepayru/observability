"""Tests for the script/worker context helpers (run_context /
interaction_context) and build_outgoing_headers trace propagation.
"""

import re

from observability import (
    build_outgoing_headers,
    get_span_id,
    get_trace_id,
    interaction_context,
    run_context,
    setup_logging,
)


def _setup_provider():
    # Real TracerProvider so run_context produces valid (non-zero) ids.
    setup_logging()


def test_run_context_sets_trace_and_span():
    _setup_provider()
    with run_context("nightly-job") as (trace_id, span_id):
        assert re.fullmatch(r"[0-9a-f]{32}", trace_id)
        assert re.fullmatch(r"[0-9a-f]{16}", span_id)
        assert get_trace_id() == trace_id
        assert get_span_id() == span_id


def test_interaction_context_is_run_context_alias():
    assert interaction_context is run_context


def test_build_outgoing_headers_within_context():
    _setup_provider()
    with run_context("job") as (trace_id, span_id):
        headers = build_outgoing_headers()
    assert headers["X-Request-Id"] == trace_id
    assert headers["traceparent"] == f"00-{trace_id}-{span_id}-01"


def test_build_outgoing_headers_empty_outside_context():
    # conftest resets the contextvars, so nothing is set here.
    assert build_outgoing_headers() == {}


def test_sequential_runs_get_distinct_traces():
    _setup_provider()
    with run_context("first") as (first_trace, _):
        pass
    with run_context("second") as (second_trace, _):
        pass
    assert first_trace != second_trace
