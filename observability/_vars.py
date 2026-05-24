"""
Shared context variables for trace propagation.

Both middleware.py (FastAPI) and context.py (scripts/bots) write to these
same vars, so config.py can read them without knowing which transport is
in use.
"""

import contextvars
from typing import Dict, Optional

_trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "trace_id", default=None
)
_span_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "span_id", default=None
)
# Set by TraceMiddleware from the incoming X-Request-Id header (upstream caller).
_request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)


def get_trace_id() -> Optional[str]:
    return _trace_id_var.get()


def get_span_id() -> Optional[str]:
    return _span_id_var.get()


def get_request_id() -> Optional[str]:
    return _request_id_var.get()


def build_outgoing_headers() -> Dict[str, str]:
    """
    Return W3C traceparent and X-Request-Id headers to inject on outgoing
    HTTP calls so downstream services can correlate their logs with ours.
    Returns an empty dict when called outside a trace context.
    """
    trace_id = get_trace_id()
    span_id = get_span_id()
    headers: Dict[str, str] = {}
    if trace_id:
        headers["X-Request-Id"] = trace_id
    if trace_id and span_id:
        headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
    return headers
