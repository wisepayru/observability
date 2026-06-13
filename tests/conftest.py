"""Shared pytest fixtures for the observability test suite.

This package configures itself entirely from environment variables (read at
``setup_logging`` call time) and mutates the process-global root logger. The
fixtures here keep every test hermetic:

  * ``_isolate_env``  - removes any OPENSEARCH_*/LOG_*/SERVICE_NAME/APP_ENV vars
    leaking in from the developer's shell, so a test only sees what it sets.
  * ``_reset_logging`` - snapshots the root logger's handlers/level before each
    test and restores them afterwards, so ``setup_logging`` calls don't bleed
    across tests (and queued OpenSearch handlers get closed).
"""

import logging

import pytest

# Env vars this package reads. Cleared before each test so the host environment
# never influences a result.
_OBSERVABILITY_ENV_VARS = (
    "OPENSEARCH_HOST",
    "OPENSEARCH_USER",
    "OPENSEARCH_PASSWORD",
    "OPENSEARCH_INDEX",
    "SERVICE_NAME",
    "APP_ENV",
    "LOG_LEVEL",
    "LOG_BATCH_SIZE",
    "LOG_FLUSH_INTERVAL",
    "LOG_MAX_QUEUE_SIZE",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    for var in _OBSERVABILITY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _reset_logging():
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        yield
    finally:
        for handler in root.handlers[:]:
            if handler not in saved_handlers:
                # Close handlers the test installed (flushes/joins the
                # OpenSearchHandler background thread, closes its httpx client).
                try:
                    handler.close()
                except Exception:
                    pass
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
