from typing import Optional

from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ._vars import (
    _trace_id_var,
    _span_id_var,
    _request_id_var,
    get_trace_id,
    get_span_id,
    get_request_id,
    build_outgoing_headers,
)

__all__ = [
    "TraceMiddleware",
    "get_trace_id",
    "get_span_id",
    "get_request_id",
    "build_outgoing_headers",
]


class TraceMiddleware(BaseHTTPMiddleware):
    """
    FastAPI/Starlette middleware that:
      - Extracts a W3C traceparent from the incoming request (propagated by
        upstream callers), or starts a fresh OTEL span if none is present.
      - Extracts X-Request-Id set by upstream callers and stores it in a
        contextvar for cross-service log correlation.
      - Stores trace_id and span_id in contextvars so they are automatically
        included in every log record for the duration of the request.
      - Injects a traceparent response header so callers can correlate.
    """

    _propagator = TraceContextTextMapPropagator()

    async def dispatch(self, request: Request, call_next) -> Response:
        tracer = trace.get_tracer(__name__)
        ctx = self._propagator.extract(dict(request.headers))

        upstream_request_id = request.headers.get("X-Request-Id")
        _request_id_var.set(upstream_request_id)

        with tracer.start_as_current_span(
            f"{request.method} {request.url.path}", context=ctx
        ) as span:
            span_ctx = span.get_span_context()
            trace_id = format(span_ctx.trace_id, "032x")
            span_id = format(span_ctx.span_id, "016x")

            _trace_id_var.set(trace_id)
            _span_id_var.set(span_id)

            response = await call_next(request)
            response.headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
            return response
