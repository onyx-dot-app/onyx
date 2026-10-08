"""A throttled download is retried with Retry-After like any other Graph
call, so one 429 on a file or an image does not fail the indexing attempt."""

from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.connectors.microsoft_utils import drive_items
from onyx.connectors.microsoft_utils.drive_items import (
    stream_response_to_buffer_with_cap,
)


def _response(status: int, body: bytes = b"", retry_after: str | None = None) -> Any:
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.headers = {"Content-Length": str(len(body))}
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    response.iter_content.return_value = [body]
    response.raise_for_status.side_effect = (
        requests.HTTPError(str(status), response=response) if status >= 400 else None
    )
    response.text = ""
    return nullcontext(response)


def test_a_throttled_download_waits_retry_after_and_succeeds() -> None:
    answers = iter([_response(429, retry_after="7"), _response(200, b"file bytes")])

    with patch.object(drive_items.time, "sleep") as sleep:
        content = stream_response_to_buffer_with_cap(
            lambda: next(answers), cap=1_000, description="f"
        )

    assert content == b"file bytes"
    assert sleep.call_count == 1
    assert sleep.call_args.args[0] == pytest.approx(7, abs=1)


def test_a_download_throttled_past_the_retries_raises() -> None:
    answers = iter([_response(429, retry_after="1") for _ in range(4)])

    with patch.object(drive_items.time, "sleep"), pytest.raises(requests.HTTPError):
        stream_response_to_buffer_with_cap(
            lambda: next(answers), cap=1_000, description="f", max_retries=3
        )
