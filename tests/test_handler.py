"""Tests for OpenSearchHandler: bulk NDJSON framing, auth, and the stderr
fallback paths that guarantee no log is ever lost when OpenSearch misbehaves.

The handler's HTTP client is mocked throughout; nothing hits the network. The
background flush thread is neutralised by a very large flush_interval so each
test drives _flush() deterministically.
"""

import json
import logging
import queue

import httpx
import pytest

from observability.handler import OpenSearchHandler


@pytest.fixture
def make_handler():
    """Factory for OpenSearchHandlers that are cleanly torn down.

    flush_interval is huge so the background daemon thread never fires during a
    test; tests call handler._flush() explicitly.
    """
    created = []

    def _make(**overrides):
        kwargs = {
            "host": "http://opensearch.local:9200",
            "index": "wisepay-ym-api",
            "user": "admin",
            "password": "secret",
            "flush_interval": 3600,
        }
        kwargs.update(overrides)
        handler = OpenSearchHandler(**kwargs)
        created.append(handler)
        return handler

    yield _make

    for handler in created:
        handler._stopped.set()
        # Drain any leftover records so handler.close() (and logging's atexit
        # shutdown) don't try to ship them over a closed/mock client.
        try:
            while True:
                handler._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            handler.close()  # also deregisters it from logging._handlerList
        except Exception:
            pass


def _make_record(msg="hello"):
    return logging.LogRecord("demo", logging.INFO, __file__, 1, msg, None, None)


def _mock_ok_post(mocker, handler, body=None):
    response = mocker.MagicMock(status_code=200)
    response.json.return_value = body if body is not None else {"errors": False}
    handler._client = mocker.MagicMock()
    handler._client.post.return_value = response
    return handler._client


# ---------------------------------------------------------------------------
# Bulk framing
# ---------------------------------------------------------------------------


def test_flush_posts_bulk_ndjson(mocker, make_handler):
    handler = make_handler(index="wisepay-ym-api")
    client = _mock_ok_post(mocker, handler)

    handler._queue.put_nowait('{"message":"a"}')
    handler._queue.put_nowait('{"message":"b"}')
    handler._flush()

    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert args[0] == "http://opensearch.local:9200/_bulk"
    assert kwargs["auth"] == ("admin", "secret")
    assert kwargs["headers"]["Content-Type"] == "application/x-ndjson"

    lines = kwargs["content"].decode().strip().split("\n")
    # action / source / action / source
    assert len(lines) == 4
    assert json.loads(lines[0]) == {"index": {"_index": "wisepay-ym-api"}}
    assert lines[1] == '{"message":"a"}'
    assert json.loads(lines[2]) == {"index": {"_index": "wisepay-ym-api"}}
    assert lines[3] == '{"message":"b"}'


def test_host_trailing_slash_stripped(mocker, make_handler):
    handler = make_handler(host="http://opensearch.local:9200/")
    client = _mock_ok_post(mocker, handler)

    handler._queue.put_nowait('{"message":"a"}')
    handler._flush()

    assert client.post.call_args.args[0] == "http://opensearch.local:9200/_bulk"


def test_emit_formats_then_flush_ships_it(mocker, make_handler):
    handler = make_handler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    client = _mock_ok_post(mocker, handler)

    handler.emit(_make_record("formatted-line"))
    handler._flush()

    lines = client.post.call_args.kwargs["content"].decode().strip().split("\n")
    assert lines[1] == "formatted-line"


def test_empty_queue_does_not_post(mocker, make_handler):
    handler = make_handler()
    client = _mock_ok_post(mocker, handler)
    handler._flush()
    client.post.assert_not_called()


def test_flush_respects_batch_size(mocker, make_handler):
    handler = make_handler(batch_size=2)
    client = _mock_ok_post(mocker, handler)
    for i in range(5):
        handler._queue.put_nowait(json.dumps({"i": i}))

    handler._flush()  # one flush ships at most batch_size records

    lines = client.post.call_args.kwargs["content"].decode().strip().split("\n")
    assert len(lines) == 4  # 2 records -> 2 action + 2 source lines
    assert handler._queue.qsize() == 3


# ---------------------------------------------------------------------------
# Fallback paths (no log lost)
# ---------------------------------------------------------------------------


def test_transport_error_falls_back_to_stderr(mocker, make_handler, capsys):
    handler = make_handler()
    handler._client = mocker.MagicMock()
    handler._client.post.side_effect = httpx.ConnectError("unreachable")

    handler._queue.put_nowait('{"message":"keepme"}')
    handler._flush()

    err = capsys.readouterr().err
    assert "transport error" in err
    assert "ConnectError" in err
    assert '{"message":"keepme"}' in err  # the record itself survives to stderr


def test_queue_full_falls_back_to_stderr(make_handler, capsys):
    handler = make_handler(max_queue_size=1)
    handler._queue.put_nowait("occupied")  # fill the single slot

    handler.emit(_make_record("overflow-record"))

    assert "overflow-record" in capsys.readouterr().err


def test_http_error_status_logged_to_stderr(mocker, make_handler, capsys):
    handler = make_handler()
    handler._client = mocker.MagicMock()
    handler._client.post.return_value = mocker.MagicMock(status_code=503, text="unavailable")

    handler._queue.put_nowait('{"message":"a"}')
    handler._flush()

    err = capsys.readouterr().err
    assert "HTTP 503" in err
    assert "unavailable" in err


def test_partial_document_failures_logged(mocker, make_handler, capsys):
    handler = make_handler()
    _mock_ok_post(
        mocker,
        handler,
        body={
            "errors": True,
            "items": [
                {"index": {"status": 201}},
                {
                    "index": {
                        "status": 400,
                        "error": {"type": "mapper_parsing_exception", "reason": "bad field"},
                    }
                },
            ],
        },
    )

    handler._queue.put_nowait('{"message":"a"}')
    handler._queue.put_nowait('{"message":"b"}')
    handler._flush()

    err = capsys.readouterr().err
    assert "rejected" in err
    assert "mapper_parsing_exception" in err


def test_successful_flush_is_silent(mocker, make_handler, capsys):
    handler = make_handler()
    _mock_ok_post(mocker, handler, body={"errors": False})
    handler._queue.put_nowait('{"message":"a"}')
    handler._flush()
    assert capsys.readouterr().err == ""
