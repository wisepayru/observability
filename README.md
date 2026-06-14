# wisepay-observability

Shared structured-logging + tracing library for wisepay services. It ships JSON
log records to OpenSearch (with a console fallback), and propagates W3C trace
context across services so logs can be correlated by `trace_id`.

Consumed by `ym-api`, `iris`, `currency-exchange-rates-api`, `tg-bot`,
`currency-exchange-rates-parsers` and `banking`.

## Install

Pinned by tag (this is the supported install path — every release also attaches
a built wheel + sdist):

```
wisepay-observability @ git+https://github.com/wisepayru/observability.git@1.1.1
```

Requires Python >= 3.14.

## Quickstart

### HTTP service (FastAPI / Starlette)

```python
from fastapi import FastAPI
from observability import setup_logging, TraceMiddleware

setup_logging()                  # configure root logging from the environment
app = FastAPI()
app.add_middleware(TraceMiddleware)
```

`TraceMiddleware` starts (or continues, from an inbound `traceparent`) a trace
per request, stores `trace_id`/`span_id` in context so every log record carries
them, logs one record per request with **sanitized** headers (secrets like
`authorization` / `cookie` / `x-api-key` redacted), and sets a `traceparent`
response header.

### Outgoing calls — propagate the trace

```python
import httpx
from observability import build_outgoing_headers

async with httpx.AsyncClient() as client:
    await client.get(url, headers=build_outgoing_headers())
```

### Scripts / workers / bots

```python
from observability import setup_logging, run_context

setup_logging()
with run_context("nightly-rates"):
    fetch_and_store_rates()      # every log inside carries the run's trace_id
```

`interaction_context` is an alias of `run_context` (used by `tg-bot`).

## Configuration

`setup_logging()` reads everything from the environment:

| Variable | Default | Purpose |
|---|---|---|
| `OPENSEARCH_HOST` | _(unset)_ | OpenSearch node URL. **If unset (or no password), logs go to the console** instead of OpenSearch. |
| `OPENSEARCH_PASSWORD` | _(unset)_ | Basic-auth password; required (with host) to enable the OpenSearch handler. |
| `OPENSEARCH_USER` | `admin` | Basic-auth username. |
| `OPENSEARCH_INDEX` | `wisepay-logs` | Target index. Services set this per app, e.g. `wisepay-ym-api`. |
| `SERVICE_NAME` | `wisepay-service` | Emitted as `service` on every record. |
| `APP_ENV` | `production` | Emitted as `env`. |
| `LOG_LEVEL` | `DEBUG` | Root log level. |
| `LOG_BATCH_SIZE` | `50` | Records per bulk flush. |
| `LOG_FLUSH_INTERVAL` | `1.0` | Seconds between flushes. |
| `LOG_MAX_QUEUE_SIZE` | `10000` | In-memory queue cap (overflow falls back to stderr). |

Business logs ship to OpenSearch **or** the console, not both. App code can
attach arbitrary fields via `extra=` (e.g. `correlation_id`, `order_id`) and
they pass through to the document untouched.

## Development

```bash
python3.14 -m venv .venv
.venv/bin/pip install -e . -r requirements-test.txt
.venv/bin/ruff check .
.venv/bin/pytest
```

See [`tests/README.md`](tests/README.md) for the test layout and
[`docs/release.md`](docs/release.md) for the versioning + release flow.
