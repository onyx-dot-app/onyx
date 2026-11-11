"""The Egnyte gateway's HTTP layer: overlapping folder pages that never repeat
a child, per-second rate limits waited out, the daily quota failing at once,
and the error each status maps to."""

import io
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.egnyte import source_operations
from onyx.connectors.egnyte.source_operations import (
    EgnyteApiError,
    EgnyteQuotaExhaustedError,
    EgnyteSourceOperations,
)
from onyx.connectors.exceptions import (
    CredentialInvalidError,
    InsufficientPermissionsError,
)


def _response(
    status: int, body: Any = None, headers: dict[str, str] | None = None
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    # Served from raw, so both .json() and iter_content can read it.
    response.raw = io.BytesIO(b"" if body is None else content)
    return response


def _file(name: str) -> dict[str, str]:
    return {
        "name": name,
        "path": f"/Shared/Docs/{name}",
        "group_id": f"group-{name}",
        "entry_id": f"entry-{name}",
        "last_modified": "Tue, 10 Nov 2026 18:00:00 GMT",
    }


def _gateway(domain: str = "acme") -> EgnyteSourceOperations:
    return EgnyteSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None,
            DocumentSource.EGNYTE.value,
            {"domain": domain, "access_token": "test-token"},
        )
    )


@pytest.fixture(autouse=True)
def no_sleep() -> Iterator[MagicMock]:
    with patch.object(source_operations.time, "sleep") as sleep:
        yield sleep


def test_folder_page_reads_the_folder_and_its_children() -> None:
    body = {
        "name": "Docs",
        "path": "/Shared/Docs",
        "folder_id": "f1",
        "parent_id": "f0",
        "folders": [{"name": "Sub", "path": "/Shared/Docs/Sub", "folder_id": "f2"}],
        "files": [_file("a.txt")],
    }
    get = MagicMock(return_value=_response(200, body))

    with patch.object(requests.Session, "get", get):
        page = _gateway().list_folder_page(
            folder_path="/Shared/Docs", offset=180, page_size=200
        )

    assert (page.folder.folder_id, page.folder.parent_id) == ("f1", "f0")
    assert [f.path for f in page.folders] == ["/Shared/Docs/Sub"]
    assert [f.group_id for f in page.files] == ["group-a.txt"]
    assert get.call_args.args[0] == "https://acme.egnyte.com/pubapi/v1/fs/Shared/Docs"
    params = get.call_args.kwargs["params"]
    assert (params["offset"], params["count"], params["sort_by"]) == (180, 200, "name")


def test_per_second_rate_limit_is_waited_out(no_sleep: MagicMock) -> None:
    get = MagicMock(
        side_effect=[
            _response(429, headers={"Retry-After": "1"}),
            _response(200, b"text"),
        ]
    )

    with patch.object(requests.Session, "get", get):
        content = _gateway().download_file(file_path="/Shared/Docs/a.txt")

    assert content.getvalue() == b"text"
    no_sleep.assert_any_call(1.0)


def test_used_up_daily_quota_fails_without_waiting(no_sleep: MagicMock) -> None:
    quota_headers = {
        "Retry-After": "40000",
        "X-Accesstoken-Quota-Allotted": "1000",
        "X-Accesstoken-Quota-Current": "1000",
    }
    get = MagicMock(return_value=_response(429, headers=quota_headers))

    with patch.object(requests.Session, "get", get):
        with pytest.raises(EgnyteQuotaExhaustedError):
            _gateway().download_file(file_path="/Shared/Docs/a.txt")

    assert get.call_count == 1
    assert all(call.args[0] < 40000 for call in no_sleep.call_args_list)


@pytest.mark.parametrize(
    "response, error",
    [
        (_response(401), CredentialInvalidError),
        (_response(403, {"errorMessage": "no"}), InsufficientPermissionsError),
        (_response(404, {"errorMessage": "gone"}), EgnyteApiError),
        (_response(500, {"errorMessage": "boom"}), EgnyteApiError),
    ],
    ids=["401", "403", "404", "500"],
)
def test_each_status_maps_to_its_error(
    response: requests.Response, error: type[Exception]
) -> None:
    with patch.object(requests.Session, "get", MagicMock(return_value=response)):
        with pytest.raises(error):
            _gateway().download_file(file_path="/Shared/Docs/a.txt")


def test_domain_that_is_not_one_label_is_refused() -> None:
    get = MagicMock()

    with patch.object(requests.Session, "get", get):
        with pytest.raises(CredentialInvalidError):
            _gateway("evil.example.com/x").download_file(file_path="/a.txt")

    get.assert_not_called()


def test_download_reads_only_the_start_when_bounded() -> None:
    response = _response(200, b"x" * 10_000)
    with patch.object(requests.Session, "get", MagicMock(return_value=response)):
        content = _gateway().download_file(file_path="/Shared/big.txt", max_bytes=100)

    assert content.getvalue() == b"x" * 100


def test_bounded_user_listing_makes_one_small_call() -> None:
    user = {
        "userName": "ana",
        "email": "ana@acme.com",
        "userType": "standard",
        "active": True,
    }
    get = MagicMock(
        return_value=_response(200, {"totalResults": 500, "resources": [user]})
    )

    with patch.object(requests.Session, "get", get):
        users = _gateway().list_users(limit=1)

    assert [u.user_name for u in users] == ["ana"]
    assert get.call_count == 1
    assert get.call_args.kwargs["params"]["count"] == 1
