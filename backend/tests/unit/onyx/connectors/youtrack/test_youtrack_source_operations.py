"""The YouTrack gateway's HTTP layer: overlapping pages that never repeat an
item, the error each status maps to, refused redirects, and Retry-After waits
bounded by the shared helper."""

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.youtrack import source_operations
from onyx.connectors.youtrack.source_operations import (
    YouTrackRequestError,
    YouTrackSourceOperations,
)

_BASE_URL = "https://example.youtrack.cloud"


def _response(
    status: int, body: Any = None, headers: dict[str, str] | None = None
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    response._content = b"" if body is None else json.dumps(body).encode()
    return response


@pytest.fixture
def gateway() -> Iterator[YouTrackSourceOperations]:
    with patch.object(source_operations, "validate_base_url"):
        yield YouTrackSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.YOUTRACK.value, {"youtrack_token": "perm:test"}
            ),
            connector_specific_config={"base_url": _BASE_URL},
        )


def test_pages_overlap_and_never_repeat_an_item(
    gateway: YouTrackSourceOperations,
) -> None:
    """With 10 per page the second request starts at 9, so an item deleted in
    between still leaves the next live item on the second page."""
    listing = [{"id": f"3-{n}"} for n in range(15)]
    del listing[3]  # deleted after the first page was read
    first_page = [{"id": f"3-{n}"} for n in range(10)]
    pages: list[list[dict[str, str]]] = [first_page, listing[9:19]]
    get = MagicMock(side_effect=[_response(200, page) for page in pages])

    with patch.object(requests.Session, "get", get):
        walked = [
            item["id"]
            for page in gateway._pages("/issues", {"fields": "id"}, 10)
            for item in page
        ]

    assert walked == [f"3-{n}" for n in range(15)]
    assert [call.kwargs["params"]["$skip"] for call in get.call_args_list] == [0, 9]


@pytest.mark.parametrize(
    "response, error",
    [
        (_response(401), CredentialInvalidError),
        (_response(403, {"error_description": "no"}), InsufficientPermissionsError),
        (
            _response(302, headers={"Location": "https://elsewhere.example/api"}),
            ConnectorValidationError,
        ),
        (_response(500, {"error": "boom"}), YouTrackRequestError),
    ],
    ids=["401", "403", "redirect", "500"],
)
def test_each_status_maps_to_its_error(
    gateway: YouTrackSourceOperations,
    response: requests.Response,
    error: type[Exception],
) -> None:
    with patch.object(requests.Session, "get", MagicMock(return_value=response)):
        with pytest.raises(error):
            gateway.get_me()


def test_redirects_are_never_followed(gateway: YouTrackSourceOperations) -> None:
    get = MagicMock(return_value=_response(200, {"id": "1-1"}))
    with patch.object(requests.Session, "get", get):
        gateway.get_me()
    assert get.call_args.kwargs["allow_redirects"] is False


def test_retry_after_goes_through_the_shared_bound() -> None:
    upstream = MagicMock()
    upstream.headers = {"Retry-After": "900"}
    with patch.object(
        source_operations, "bound_server_wait", return_value=60.0
    ) as bound:
        wait = source_operations._RETRY.get_retry_after(upstream)

    assert wait == 60.0
    bound.assert_called_once_with(900.0, "youtrack")


def test_a_listing_past_its_size_cap_raises(
    gateway: YouTrackSourceOperations,
) -> None:
    page = [{"id": f"0-{n}", "shortName": f"P{n}", "name": "p"} for n in range(500)]
    get = MagicMock(
        side_effect=[
            _response(200, [{**item, "id": f"{n}-{item['id']}"} for item in page])
            for n in range(10)
        ]
    )
    with (
        patch.object(source_operations, "_MAX_LISTED_ITEMS", 1000),
        patch.object(requests.Session, "get", get),
        pytest.raises(RuntimeError, match="more than 1000"),
    ):
        gateway.list_projects()
