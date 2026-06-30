"""Unit tests for SharepointConnector._graph_api_get_json retry behavior.

Covers the empty/non-JSON 2xx body case: Microsoft Graph intermittently returns
a body-less response under load (gateway-shed throttling, backend list-view
timeouts on large libraries, mid-response connection drops). The bare
response.json() used to raise an unretried JSONDecodeError that aborted indexing
of large (>2K file) libraries; it must now be retried like any transient error.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import requests
from requests import Response

from onyx.connectors.sharepoint import connector as sp_connector
from onyx.connectors.sharepoint.connector import GRAPH_API_MAX_RETRIES
from onyx.connectors.sharepoint.connector import SharepointConnector

SITE_URL = "https://tenant.sharepoint.com/sites/Big"
PAGE_URL = "https://graph.microsoft.com/v1.0/drives/abc/root/children"


def _response(status: int = 200, body: Any = None, raw: bytes | None = None) -> Response:
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


def _connector(monkeypatch: pytest.MonkeyPatch) -> SharepointConnector:
    connector = SharepointConnector(sites=[SITE_URL])
    connector.graph_api_base = "https://graph.microsoft.com/v1.0"
    # Avoid real MSAL token acquisition.
    monkeypatch.setattr(connector, "_get_graph_access_token", lambda: "fake-token")
    # Never actually sleep between retries.
    monkeypatch.setattr(sp_connector.time, "sleep", lambda *_a, **_k: None)
    return connector


def test_retries_empty_body_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty 2xx body is retried; the next good page is returned."""
    connector = _connector(monkeypatch)
    payload = {"value": [{"id": "1", "name": "f.docx"}]}
    responses = iter([_response(200, body=None), _response(200, body=payload)])
    monkeypatch.setattr(sp_connector.requests, "get", lambda *_a, **_k: next(responses))

    result = connector._graph_api_get_json(PAGE_URL, {"$top": "200"})

    assert result == payload


def test_raises_after_exhausting_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """A persistently empty body re-raises JSONDecodeError after all retries."""
    connector = _connector(monkeypatch)
    calls = {"n": 0}

    def _always_empty(*_a: Any, **_k: Any) -> Response:
        calls["n"] += 1
        return _response(200, body=None)

    monkeypatch.setattr(sp_connector.requests, "get", _always_empty)

    with pytest.raises(requests.exceptions.JSONDecodeError):
        connector._graph_api_get_json(PAGE_URL)

    assert calls["n"] == GRAPH_API_MAX_RETRIES + 1


def test_retries_chunked_encoding_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mid-stream drop (ChunkedEncodingError) is retried, not fatal."""
    connector = _connector(monkeypatch)
    payload = {"value": []}
    state = {"n": 0}

    def _flaky(*_a: Any, **_k: Any) -> Response:
        state["n"] += 1
        if state["n"] == 1:
            raise requests.exceptions.ChunkedEncodingError("connection dropped")
        return _response(200, body=payload)

    monkeypatch.setattr(sp_connector.requests, "get", _flaky)

    result = connector._graph_api_get_json(PAGE_URL)

    assert result == payload
    assert state["n"] == 2
