"""Unit tests for the shared Graph GET retry behavior.

Covers the empty/non-JSON 2xx body case: Microsoft Graph intermittently returns
a body-less response under load (gateway-shed throttling, backend list-view
timeouts on large libraries, mid-response connection drops). An empty body must
be retried like any other transient error, or indexing of a large library aborts
on a bare JSONDecodeError.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests
from requests import Response

from onyx.connectors.microsoft_utils import graph_client as graph_client_module
from onyx.connectors.microsoft_utils.graph_client import (
    GRAPH_API_MAX_RETRIES,
    graph_api_get_json,
)

PAGE_URL = "https://graph.microsoft.com/v1.0/drives/abc/root/children"


def _response(
    status: int = 200, body: Any = None, raw: bytes | None = None
) -> Response:
    """Build a fake requests.Response. body=None + raw=None => empty body."""
    resp = Response()
    resp.status_code = status
    if raw is not None:
        resp._content = raw
    elif body is not None:
        resp._content = json.dumps(body).encode()
    else:
        resp._content = b""  # empty 2xx body -> JSONDecodeError on .json()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never actually sleep between retries."""
    monkeypatch.setattr(graph_client_module.time, "sleep", lambda *_a, **_k: None)


def _token() -> str:
    return "fake-token"


def test_retries_empty_body_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty 2xx body is retried; the next good page is returned."""
    _no_sleep(monkeypatch)
    payload = {"value": [{"id": "1", "name": "f.docx"}]}
    responses = iter([_response(200, body=None), _response(200, body=payload)])
    monkeypatch.setattr(
        graph_client_module.requests, "get", lambda *_a, **_k: next(responses)
    )

    result = graph_api_get_json(_token, PAGE_URL, {"$top": "200"})

    assert result == payload


def test_raises_after_exhausting_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """A persistently empty body re-raises JSONDecodeError after all retries."""
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def _always_empty(*_a: Any, **_k: Any) -> Response:
        calls["n"] += 1
        return _response(200, body=None)

    monkeypatch.setattr(graph_client_module.requests, "get", _always_empty)

    with pytest.raises(requests.exceptions.JSONDecodeError):
        graph_api_get_json(_token, PAGE_URL)

    assert calls["n"] == GRAPH_API_MAX_RETRIES + 1


def test_retries_chunked_encoding_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mid-stream drop (ChunkedEncodingError) is retried, not fatal."""
    _no_sleep(monkeypatch)
    payload = {"value": []}
    state = {"n": 0}

    def _flaky(*_a: Any, **_k: Any) -> Response:
        state["n"] += 1
        if state["n"] == 1:
            raise requests.exceptions.ChunkedEncodingError("connection dropped")
        return _response(200, body=payload)

    monkeypatch.setattr(graph_client_module.requests, "get", _flaky)

    result = graph_api_get_json(_token, PAGE_URL)

    assert result == payload
    assert state["n"] == 2
