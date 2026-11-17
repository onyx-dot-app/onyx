"""The Drive gateway counts each request it sends, by outcome."""

from collections.abc import Callable
from typing import Any
from unittest import mock

import httplib2
import pytest
import requests
from googleapiclient.errors import HttpError

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.google_drive import source_operations
from onyx.connectors.google_drive.source_operations import (
    DriveCorpus,
    GoogleDriveSourceOperations,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_DICT_TOKEN_KEY,
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.server.metrics.source_api_metrics import (
    SOURCE_API_REQUESTS,
    RequestOutcome,
)

_RATE_LIMIT_BODY = (
    b'{"error": {"errors": [{"reason": "rateLimitExceeded"}], '
    b'"message": "Rate Limit Exceeded"}}'
)


def _http_error(status: int, body: bytes = b"{}") -> HttpError:
    return HttpError(httplib2.Response({"status": status}), body)


def _gateway() -> GoogleDriveSourceOperations:
    return GoogleDriveSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None,
            "google_drive",
            {
                DB_CREDENTIALS_DICT_TOKEN_KEY: "{}",
                DB_CREDENTIALS_PRIMARY_ADMIN_KEY: "admin@co.com",
            },
        )
    )


def _counts(api: str) -> dict[RequestOutcome, float]:
    return {
        outcome: SOURCE_API_REQUESTS.labels(
            source="google_drive", api=api, outcome=outcome.value
        )._value.get()
        for outcome in RequestOutcome
    }


def _added(api: str, run: Callable[[], Any]) -> dict[RequestOutcome, float]:
    """The requests that ``run`` counted, by outcome, without the zeros."""
    before = _counts(api)
    run()
    after = _counts(api)
    return {
        outcome: after[outcome] - before[outcome]
        for outcome in RequestOutcome
        if after[outcome] != before[outcome]
    }


def test_each_list_page_counts_as_one_request() -> None:
    gateway = _gateway()
    drive = mock.MagicMock()
    drive.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "1"}], "nextPageToken": "t"},
        {"files": [{"id": "2"}]},
    ]

    def run() -> None:
        with mock.patch.object(
            GoogleDriveSourceOperations, "_drive", return_value=drive
        ):
            list(
                gateway.list_files(
                    variant=DriveCorpus.USER,
                    user_email="a@co.com",
                    fields="nextPageToken, files(id)",
                )
            )

    assert _added("drive", run) == {RequestOutcome.OK: 2}


def test_a_denied_read_counts_as_denied() -> None:
    gateway = _gateway()
    drive = mock.MagicMock()
    drive.files.return_value.get.return_value.execute.side_effect = _http_error(404)

    def run() -> None:
        with mock.patch.object(
            GoogleDriveSourceOperations, "_drive", return_value=drive
        ):
            assert (
                gateway.get_file(user_email="a@co.com", file_id="f", fields="id")
                is None
            )

    assert _added("drive", run) == {RequestOutcome.DENIED: 1}


def test_each_try_of_a_retried_docs_fetch_counts() -> None:
    gateway = _gateway()
    responses: list[mock.MagicMock] = []
    for status in (429, 503, 200):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        if status == 200:
            response.iter_content.return_value = [b'{"title": "t"}']
        else:
            error_response = requests.Response()
            error_response.status_code = status
            error_response._content = b"{}"
            response.raise_for_status.side_effect = requests.HTTPError(
                response=error_response
            )
        responses.append(response)
    session = mock.Mock()
    session.get.side_effect = [requests.ConnectionError("reset"), *responses]

    def run() -> None:
        with (
            mock.patch.object(
                GoogleDriveSourceOperations, "_docs_session", return_value=session
            ),
            mock.patch("time.sleep"),
        ):
            assert gateway.fetch_google_doc(
                user_email="a@co.com", doc_id="d", max_response_bytes=1000
            ) == {"title": "t"}

    assert _added("docs", run) == {
        RequestOutcome.NETWORK_ERROR: 1,
        RequestOutcome.RATE_LIMITED: 1,
        RequestOutcome.SERVER_ERROR: 1,
        RequestOutcome.OK: 1,
    }


class _FakeBatch:
    """Answers the first request of the batch and refuses the others for
    their rate."""

    def __init__(self, callback: Callable[[str, Any, Exception | None], None]):
        self._callback = callback
        self._keys: list[str] = []

    def add(self, _request: Any, request_id: str) -> None:
        self._keys.append(request_id)

    def execute(self) -> None:
        for index, key in enumerate(self._keys):
            if index == 0:
                self._callback(key, {"id": key}, None)
            else:
                self._callback(key, None, _http_error(403, _RATE_LIMIT_BODY))


def test_each_request_of_a_batch_counts_by_its_own_answer() -> None:
    gateway = _gateway()
    drive = mock.MagicMock()
    drive.new_batch_http_request.side_effect = lambda callback: _FakeBatch(callback)

    def run() -> None:
        with mock.patch.object(
            GoogleDriveSourceOperations, "_drive", return_value=drive
        ):
            gateway.batch_get_files(
                user_email="a@co.com",
                file_ids_by_key={"k1": "f1", "k2": "f2", "k3": "f3"},
                fields="id",
            )

    assert _added("drive", run) == {
        RequestOutcome.OK: 1,
        RequestOutcome.RATE_LIMITED: 2,
    }


def test_directory_requests_count_as_admin() -> None:
    gateway = _gateway()
    directory = mock.MagicMock()
    directory.groups.return_value.list.return_value.execute.return_value = {
        "groups": [{"email": "g@co.com"}]
    }

    def run() -> None:
        with (
            mock.patch.object(
                GoogleDriveSourceOperations, "_directory", return_value=directory
            ),
            mock.patch.object(
                GoogleDriveSourceOperations, "_domain", return_value="co.com"
            ),
        ):
            assert list(gateway.list_groups()) == ["g@co.com"]

    assert _added("admin", run) == {RequestOutcome.OK: 1}


@pytest.mark.parametrize(
    ("status", "body", "outcome"),
    [
        (200, b"data", RequestOutcome.OK),
        (429, b"{}", RequestOutcome.RATE_LIMITED),
        (403, _RATE_LIMIT_BODY, RequestOutcome.RATE_LIMITED),
        (403, b"{}", RequestOutcome.DENIED),
        (500, b"", RequestOutcome.SERVER_ERROR),
    ],
)
def test_a_media_download_counts_each_http_request(
    status: int, body: bytes, outcome: RequestOutcome
) -> None:
    """googleapiclient retries a media download itself, so the gateway counts
    each HTTP request that the download sends."""
    http = mock.Mock()
    http.request.return_value = (httplib2.Response({"status": status}), body)
    counting = source_operations._CountingHttp(http, "drive")

    assert _added("drive", lambda: counting.request("https://x")) == {outcome: 1}


def test_a_media_download_with_no_answer_counts_as_a_network_error() -> None:
    http = mock.Mock()
    http.request.side_effect = ConnectionResetError("reset")
    counting = source_operations._CountingHttp(http, "drive")

    def run() -> None:
        with pytest.raises(ConnectionResetError):
            counting.request("https://x")

    assert _added("drive", run) == {RequestOutcome.NETWORK_ERROR: 1}
