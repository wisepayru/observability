from contextlib import contextmanager
from typing import Tuple

from opentelemetry import trace

from ._vars import (
    _trace_id_var,
    _span_id_var,
    get_trace_id,
    get_span_id,
    build_outgoing_headers,
)

__all__ = [
    "run_context",
    "interaction_context",
    "get_trace_id",
    "get_span_id",
    "build_outgoing_headers",
]


@contextmanager
def run_context(name: str = "run"):
    """
    Context manager for one-shot script runs (cron jobs, parsers, etc.).
    Creates a fresh OTEL span and stores trace_id/span_id in contextvars
    so they appear in every log record for the duration of the run.

    Usage:
        with run_context("bankffinkz"):
            fetch_and_store_rates()
    """
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(name) as span:
        span_ctx = span.get_span_context()
        trace_id = format(span_ctx.trace_id, "032x")
        span_id = format(span_ctx.span_id, "016x")
        _trace_id_var.set(trace_id)
        _span_id_var.set(span_id)
        yield trace_id, span_id


# Alias used in tg-bot
interaction_context = run_context
