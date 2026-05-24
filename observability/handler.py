import json
import logging
import queue
import sys
import threading
import time
from typing import Optional

import httpx


class OpenSearchHandler(logging.Handler):
    """
    Async-safe logging handler that ships log records to OpenSearch via the
    bulk API. Records are queued in memory and flushed by a background daemon
    thread, keeping the hot path (emit) non-blocking.

    Falls back to stderr if OpenSearch is unreachable so no logs are lost.
    """

    def __init__(
        self,
        host: str,
        index: str,
        user: str,
        password: str,
        batch_size: int = 50,
        flush_interval: float = 1.0,
        max_queue_size: int = 10_000,
    ):
        super().__init__()
        self._host = host.rstrip("/")
        self._index = index
        self._auth = (user, password)
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._queue: queue.Queue[str] = queue.Queue(maxsize=max_queue_size)
        self._client = httpx.Client(timeout=httpx.Timeout(5.0))
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._flush_loop, daemon=True, name="opensearch-log-flusher")
        self._thread.start()

    # ------------------------------------------------------------------
    # logging.Handler interface
    # ------------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._queue.put_nowait(self.format(record))
        except queue.Full:
            # Queue full — write directly to stderr rather than drop silently
            print(self.format(record), file=sys.stderr)

    def close(self) -> None:
        self._stopped.set()
        self._flush()
        self._client.close()
        super().close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _flush_loop(self) -> None:
        while not self._stopped.is_set():
            time.sleep(self._flush_interval)
            self._flush()

    def _flush(self) -> None:
        records: list[str] = []
        try:
            while len(records) < self._batch_size:
                records.append(self._queue.get_nowait())
        except queue.Empty:
            pass

        if not records:
            return

        bulk_body = ""
        for record_str in records:
            bulk_body += json.dumps({"index": {"_index": self._index}}) + "\n"
            bulk_body += record_str + "\n"

        try:
            self._client.post(
                f"{self._host}/_bulk",
                content=bulk_body.encode(),
                headers={"Content-Type": "application/x-ndjson"},
                auth=self._auth,
            )
        except Exception:
            # OpenSearch unreachable — write to stderr so nothing is lost
            for record_str in records:
                print(record_str, file=sys.stderr)
