"""The Egnyte gateway's HTTP layer: overlapping folder pages that never repeat
a child, per-second rate limits waited out, the daily quota failing at once,
and the error each status maps to."""

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
    response._content = b"" if body is None else json.dumps(body).encode()
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


def test_folder_pages_overlap_and_never_repeat_a_child() -> None:
    """With 10 per page the second request starts at 9, so a file deleted in
    between still leaves the next live file on the second page."""
    listing = [_file(f"f{n:02d}.txt") for n in range(15)]
    first_page = listing[:10]
    del listing[3]  # deleted after the first page was read
    get = MagicMock(
        side_effect=[
            _response(200, {"files": first_page}),
            _response(200, {"files": listing[9:19]}),
        ]
    )

    with patch.object(requests.Session, "get", get):
        walked = [
            file.name
            for page in _gateway().iterate_folder_pages(
                folder_path="/Shared/Docs", page_size=10
            )
            for file in page.files
        ]

    assert walked == [f"f{n:02d}.txt" for n in range(15)]
    assert [call.kwargs["params"]["offset"] for call in get.call_args_list] == [0, 9]


def test_per_second_rate_limit_is_waited_out(no_sleep: MagicMock) -> None:
    get = MagicMock(
        side_effect=[
            _response(429, headers={"Retry-After": "1"}),
            _response(200, {"files": [_file("a.txt")]}),
        ]
    )

    with patch.object(requests.Session, "get", get):
        pages = list(_gateway().iterate_folder_pages(folder_path="/Shared/Docs"))

    assert [file.name for file in pages[0].files] == ["a.txt"]
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
