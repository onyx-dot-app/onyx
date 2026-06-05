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
from onyx.connectors.sharepoint.connector import _redact_url_for_logging
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


def test_backoff_seconds_uses_equal_jitter() -> None:
    """Exponential backoff falls in [base/2, base] (equal jitter).

    Base sequence: 5, 10, 20, 30 (capped). Each draw must respect the bounds
    so retries spread out without violating the floor or the cap.
    """
    expected_bases = [5, 10, 20, 30, 30]
    for attempt, base in enumerate(expected_bases):
        samples = [
            sp_connector._backoff_seconds(attempt, retry_after=None) for _ in range(50)
        ]
        for s in samples:
            assert base / 2 <= s <= base, (
                f"attempt={attempt} base={base} produced out-of-range sleep {s}"
            )
        # Sanity: with 50 samples we should see at least two distinct values
        # (otherwise jitter isn't actually being applied).
        assert len(set(samples)) > 1, (
            f"attempt={attempt} produced no jitter spread: {samples[:5]}..."
        )


def test_backoff_seconds_respects_retry_after_header_verbatim() -> None:
    """Server-provided Retry-After is an instruction; jitter must not be applied."""
    for raw in ("0", "1", "12", "120"):
        # Repeat to make sure we don't accidentally jitter on this path.
        for _ in range(10):
            assert sp_connector._backoff_seconds(0, retry_after=raw) == float(raw)


def test_backoff_seconds_honors_http_date_retry_after() -> None:
    """An already-elapsed HTTP-date Retry-After is honored verbatim (0s wait)."""
    assert (
        sp_connector._backoff_seconds(0, retry_after="Wed, 21 Oct 2015 07:28:00 GMT")
        == 0
    )


def test_backoff_seconds_falls_back_when_retry_after_unparseable() -> None:
    """Genuinely unparseable Retry-After values fall through to jittered backoff."""
    base = 5  # attempt=0
    for _ in range(20):
        s = sp_connector._backoff_seconds(0, retry_after="not-a-date")
        assert base / 2 <= s <= base


# Sentinel value used in tests below to simulate a leaked credential parameter.
# `@microsoft.graph.downloadUrl` query strings carry a JWT in `tempauth=`. We
# use a clearly-fake marker (no real JWT prefix) so this test file is friendly
# to credential scanners.
_FAKE_TEMPAUTH = "TEST-FAKE-TEMPAUTH-DO-NOT-LOG"


def test_redact_url_strips_query_string_with_tempauth() -> None:
    """tempauth and other query parameters must never survive into the description."""
    raw = (
        "https://tenant.sharepoint.com/sites/Foo/_layouts/15/download.aspx"
        f"?UniqueId=abc&Translate=false&tempauth={_FAKE_TEMPAUTH}&ApiVersion=2.1"
    )
    safe = _redact_url_for_logging(raw)
    assert "tempauth" not in safe
    assert _FAKE_TEMPAUTH not in safe
    assert "?" not in safe
    assert safe.startswith("https://tenant.sharepoint.com/sites/Foo/")


def test_redact_url_truncates_overly_long_paths() -> None:
    """Even after stripping the query, a runaway path is bounded for log size."""
    raw = "https://tenant.sharepoint.com/" + "a" * 500
    safe = _redact_url_for_logging(raw, max_len=80)
    assert len(safe) <= 80 + len("...")
    assert safe.endswith("...")


@patch("onyx.connectors.sharepoint.connector.time")
@patch("onyx.connectors.sharepoint.connector.logger")
@patch("onyx.connectors.sharepoint.connector.requests.get")
def test_download_with_cap_does_not_log_tempauth_token(
    mock_get: MagicMock,
    mock_logger: MagicMock,
    mock_time: MagicMock,  # noqa: ARG001
) -> None:
    """A failing download must never write the preauthenticated URL to the logger.

    Without redaction the description string would carry the full downloadUrl
    (including ``tempauth=...``) into every retry/exhaustion log line, which is
    a credential leak into log aggregators.
    """
    raw_url = (
        "https://tenant.sharepoint.com/sites/Foo/_layouts/15/download.aspx"
        f"?UniqueId=abc&tempauth={_FAKE_TEMPAUTH}&ApiVersion=2.1"
    )
    mock_get.side_effect = [
        _make_response(
            raise_during_iter=requests.exceptions.ChunkedEncodingError("boom")
        )
        for _ in range(sp_connector.STREAM_DOWNLOAD_MAX_RETRIES + 1)
    ]

    with pytest.raises(requests.exceptions.ChunkedEncodingError):
        _download_with_cap(raw_url, timeout=60, cap=CAP)

    # Flatten every positional/keyword arg from every logger call into one blob
    # and assert no credential material made it through.
    all_log_args: list[Any] = []
    for call in mock_logger.warning.call_args_list + mock_logger.error.call_args_list:
        all_log_args.extend(call.args)
        all_log_args.extend(call.kwargs.values())
    blob = " ".join(str(a) for a in all_log_args)
    assert _FAKE_TEMPAUTH not in blob
    assert "tempauth" not in blob
