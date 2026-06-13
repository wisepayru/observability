"""Smoke tests for the package's public surface.

These validate the test harness itself and the documented public API. The
behavioural tests live in test_handler / test_middleware / test_setup_logging /
test_context.
"""

import observability


def test_public_api_exports():
    expected = {
        "setup_logging",
        "TraceMiddleware",
        "run_context",
        "interaction_context",
        "get_trace_id",
        "get_span_id",
        "get_request_id",
        "build_outgoing_headers",
    }
    assert expected.issubset(set(observability.__all__))
    for name in expected:
        assert hasattr(observability, name), f"{name} not importable from observability"


def test_handler_importable():
    # Not re-exported at the top level; consumers import it from the submodule.
    from observability.handler import OpenSearchHandler

    assert issubclass(OpenSearchHandler, __import__("logging").Handler)
