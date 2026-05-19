"""Unit tests for streaming-download retry behavior in the SharePoint connector.

SharePoint and the Microsoft Graph API occasionally drop the TCP connection
mid-body (surfaces as ``ChunkedEncodingError: IncompleteRead``). The download
helpers must transparently retry these transport-level failures with a fresh
HTTP request so that an isolated network blip does not turn into a permanent
per-document failure (which then trips the indexing failure threshold).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests

from onyx.connectors.sharepoint import connector as sp_connector
from onyx.connectors.sharepoint.connector import _download_via_graph_api
from onyx.connectors.sharepoint.connector import _download_with_cap
from onyx.connectors.sharepoint.connector import SizeCapExceeded

CAP = 10 * 1024 * 1024  # 10 MiB cap; well above the byte payloads used in tests


def _make_response(
    chunks: list[bytes] | None = None,
    raise_during_iter: Exception | None = None,
    headers: dict[str, str] | None = None,
    status: int = 200,
) -> MagicMock:
    """Build a MagicMock that quacks like a streaming requests.Response.

    - ``chunks``: bytes the response will yield from ``iter_content``.
    - ``raise_during_iter``: if set, ``iter_content`` will yield nothing and
      raise this exception (simulates a mid-body connection drop).
    - ``headers``: response headers (e.g. for Content-Length checks).
    - ``status``: HTTP status code; non-2xx triggers ``raise_for_status``.
    """
    resp = MagicMock(spec=requests.Response)
    resp.headers = headers or {}
    resp.status_code = status
    resp.text = ""

    def _raise_for_status() -> None:
        if status >= 400:
            raise requests.HTTPError(f"{status} error", response=resp)

    resp.raise_for_status.side_effect = _raise_for_status

    def _iter_content(_chunk_size: int) -> Any:
        if raise_during_iter is not None:
            # Match real `requests` behavior: yield what we've buffered so far,
            # then raise on the next read. For the failure case we yield
            # nothing before raising, which is the simplest reproduction.
            raise raise_during_iter
        for c in chunks or []:
            yield c

    resp.iter_content.side_effect = _iter_content
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


@patch("onyx.connectors.sharepoint.connector.time")
@patch("onyx.connectors.sharepoint.connector.requests.get")
def test_download_with_cap_retries_on_chunked_encoding_error(
    mock_get: MagicMock, mock_time: MagicMock
) -> None:
    """A single mid-stream ChunkedEncodingError should be retried and succeed."""
    failing_resp = _make_response(
        raise_during_iter=requests.exceptions.ChunkedEncodingError(
            "Connection broken: IncompleteRead(20480 bytes read, 476750 more expected)"
        )
    )
    succeeding_resp = _make_response(chunks=[b"hello", b"world"])

    mock_get.side_effect = [failing_resp, succeeding_resp]

    result = _download_with_cap("https://example/download", timeout=60, cap=CAP)

    assert result == b"helloworld"
    # Two HTTP requests means a fresh socket on retry, not a reused stale one.
    assert mock_get.call_count == 2
    mock_time.sleep.assert_called_once()


@patch("onyx.connectors.sharepoint.connector.time")
@patch("onyx.connectors.sharepoint.connector.requests.get")
def test_download_via_graph_api_retries_on_chunked_encoding_error(
    mock_get: MagicMock, mock_time: MagicMock
) -> None:
    """The Graph API helper retries the same way as the downloadUrl path."""
    failing_resp = _make_response(
        raise_during_iter=requests.exceptions.ChunkedEncodingError(
            "Connection broken: IncompleteRead"
        )
    )
    succeeding_resp = _make_response(chunks=[b"docbytes"])
    mock_get.side_effect = [failing_resp, succeeding_resp]

    result = _download_via_graph_api(
        access_token="tok",
        drive_id="drive-1",
        item_id="item-1",
        bytes_allowed=CAP,
        graph_api_base="https://graph.microsoft.com/v1.0",
    )

    assert result == b"docbytes"
    assert mock_get.call_count == 2
    mock_time.sleep.assert_called_once()


@patch("onyx.connectors.sharepoint.connector.time")
@patch("onyx.connectors.sharepoint.connector.requests.get")
def test_download_with_cap_reraises_after_max_retries(
    mock_get: MagicMock, mock_time: MagicMock
) -> None:
    """Persistent transport errors should re-raise after retries are exhausted."""
    mock_get.side_effect = [
        _make_response(
            raise_during_iter=requests.exceptions.ChunkedEncodingError("boom")
        )
        for _ in range(sp_connector.STREAM_DOWNLOAD_MAX_RETRIES + 1)
    ]

    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        _download_with_cap("https://example/download", timeout=60, cap=CAP)

    assert mock_get.call_count == sp_connector.STREAM_DOWNLOAD_MAX_RETRIES + 1
    # Sleep is invoked between attempts only, not after the final failure.
    assert mock_time.sleep.call_count == sp_connector.STREAM_DOWNLOAD_MAX_RETRIES


@patch("onyx.connectors.sharepoint.connector.time")
@patch("onyx.connectors.sharepoint.connector.requests.get")
def test_size_cap_exceeded_is_not_retried_pre_download(
    mock_get: MagicMock, mock_time: MagicMock
) -> None:
    """A Content-Length over the cap raises immediately without retrying."""
    mock_get.return_value = _make_response(
        chunks=[],
        headers={"Content-Length": str(CAP + 1)},
    )

    with pytest.raises(SizeCapExceeded):
        _download_with_cap("https://example/download", timeout=60, cap=CAP)

    assert mock_get.call_count == 1
    mock_time.sleep.assert_not_called()


@patch("onyx.connectors.sharepoint.connector.time")
@patch("onyx.connectors.sharepoint.connector.requests.get")
def test_size_cap_exceeded_is_not_retried_during_download(
    mock_get: MagicMock, mock_time: MagicMock
) -> None:
    """If the streamed body exceeds the cap, we abort once -- no retry."""
    mock_get.return_value = _make_response(chunks=[b"x" * (CAP + 1)])

    with pytest.raises(SizeCapExceeded):
        _download_with_cap("https://example/download", timeout=60, cap=CAP)

    assert mock_get.call_count == 1
    mock_time.sleep.assert_not_called()


@patch("onyx.connectors.sharepoint.connector.time")
@patch("onyx.connectors.sharepoint.connector.requests.get")
def test_http_error_from_raise_for_status_is_not_retried(
    mock_get: MagicMock, mock_time: MagicMock
) -> None:
    """HTTPError (4xx/5xx) is intentionally outside the transport-retry scope."""
    mock_get.return_value = _make_response(status=404)

    with pytest.raises(requests.HTTPError):
        _download_with_cap("https://example/download", timeout=60, cap=CAP)

    assert mock_get.call_count == 1
    mock_time.sleep.assert_not_called()


@patch("onyx.connectors.sharepoint.connector.time")
@patch("onyx.connectors.sharepoint.connector.requests.get")
def test_connection_error_before_iter_content_is_retried(
    mock_get: MagicMock, mock_time: MagicMock
) -> None:
    """ConnectionError raised before streaming starts is also retried."""
    mock_get.side_effect = [
        requests.exceptions.ConnectionError("connection refused"),
        _make_response(chunks=[b"ok"]),
    ]

    result = _download_with_cap("https://example/download", timeout=60, cap=CAP)

    assert result == b"ok"
    assert mock_get.call_count == 2
    mock_time.sleep.assert_called_once()
