# Tests

Unit tests for `wisepay-observability`. No external services and no database
are required — the OpenSearch transport is mocked and the middleware is driven
through Starlette's in-process `TestClient`.

## Running

```bash
python3.14 -m venv .venv
.venv/bin/pip install -e . -r requirements-test.txt
.venv/bin/ruff check .
.venv/bin/pytest
```

CI additionally enforces a coverage floor with `pytest --cov-fail-under=<N>`;
locally `pytest` reports coverage without failing on it.

## Layout

- `conftest.py` — env isolation + root-logger snapshot/restore so
  `setup_logging` calls don't bleed across tests.
- `test_package.py` — public-API smoke tests.
- `test_handler.py` — `OpenSearchHandler`: bulk NDJSON shape, stderr fallback,
  batch/queue behaviour.
- `test_middleware.py` — `TraceMiddleware`: trace/span ids on each request,
  sanitized request-header logging, traceparent response header.
- `test_setup_logging.py` — env-driven handler selection + JSON formatter fields.
- `test_context.py` — `run_context` / `build_outgoing_headers` / contextvar
  isolation.
