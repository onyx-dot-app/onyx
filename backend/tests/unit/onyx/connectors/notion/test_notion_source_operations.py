import json
from typing import Any
from unittest import mock

import pytest
import requests

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    RateLimitTriedTooManyTimesError,
)
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.notion import source_operations
from onyx.connectors.notion.connector import NotionConnector
from onyx.connectors.notion.models import NotionSearchObjectType, NotionSearchResponse
from onyx.connectors.notion.source_operations import (
    NOTION_API_VERSION,
    NotionApiError,
    NotionSourceOperations,
)

_TOKEN = "secret-token"
_CREDENTIALS = {"notion_integration_token": _TOKEN}


def _gateway(credentials: dict[str, Any] | None = None) -> NotionSourceOperations:
    return NotionSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, "notion", credentials if credentials is not None else _CREDENTIALS
        )
    )


def _response(
    status: int,
    body: dict[str, Any] | None = None,
    *,
    text: str | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    content = text if text is not None else json.dumps(body or {})
    response._content = content.encode()
    response.headers.update(headers or {})
    return response


def _error_body(status: int, code: str) -> dict[str, Any]:
    return {"object": "error", "status": status, "code": code, "message": code}


def _search_body(results: list[dict[str, Any]], next_cursor: str | None) -> dict:
    return {
        "object": "list",
        "results": results,
        "next_cursor": next_cursor,
        "has_more": next_cursor is not None,
    }


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "unauthorized"),
        (403, "restricted_resource"),
        # Also the answer for a page that is not shared with the integration.
        (404, "object_not_found"),
        (400, "validation_error"),
        (500, "internal_server_error"),
    ],
)
def test_error_responses_leave_as_gateway_errors(status: int, code: str) -> None:
    gateway = _gateway()

    with mock.patch.object(
        source_operations.rl_requests,
        "get",
        return_value=_response(status, _error_body(status, code)),
    ):
        with pytest.raises(NotionApiError) as raised:
            gateway.get_page(page_id="p1")

    assert raised.value.status_code == status
    assert raised.value.code == code
    assert not raised.value.is_rate_limited


def test_an_error_without_a_json_body_keeps_its_status() -> None:
    gateway = _gateway()

    with mock.patch.object(
        source_operations.rl_requests,
        "get",
        return_value=_response(502, text="<html>Bad gateway</html>"),
    ):
        with pytest.raises(NotionApiError) as raised:
            gateway.get_bot_user()

    assert raised.value.status_code == 502
    assert raised.value.code is None
    assert "Bad gateway" in str(raised.value)


@pytest.mark.parametrize("text", ["", "<html>ok</html>", "[]"])
def test_a_success_without_a_json_object_leaves_as_a_gateway_error(text: str) -> None:
    gateway = _gateway()

    with mock.patch.object(
        source_operations.rl_requests, "get", return_value=_response(200, text=text)
    ):
        with pytest.raises(NotionApiError) as raised:
            gateway.get_page(page_id="p1")

    assert raised.value.status_code == 200


def test_a_fast_call_raises_a_rate_limit_at_once() -> None:
    """A fast call does not wait: the 429 and its Retry-After reach the
    caller after one request."""
    gateway = _gateway()

    with mock.patch.object(
        source_operations.requests,
        "request",
        return_value=_response(
            429, _error_body(429, "rate_limited"), headers={"Retry-After": "2"}
        ),
    ) as request:
        with pytest.raises(NotionApiError) as raised:
            gateway.get_bot_user(fast=True)

    request.assert_called_once()
    assert raised.value.is_rate_limited
    assert raised.value.code == "rate_limited"
    assert raised.value.retry_after_seconds == 2.0


def test_exhausted_rate_limit_waits_leave_as_a_rate_limit() -> None:
    gateway = _gateway()

    with mock.patch.object(
        source_operations.rl_requests,
        "post",
        side_effect=RateLimitTriedTooManyTimesError("Exceeded '30' retries"),
    ):
        with pytest.raises(NotionApiError) as raised:
            gateway.query_data_source(data_source_id="ds1")

    assert raised.value.is_rate_limited
    assert isinstance(raised.value.__cause__, RateLimitTriedTooManyTimesError)


def test_network_errors_leave_as_gateway_errors_without_a_status() -> None:
    gateway = _gateway()

    with mock.patch.object(
        source_operations.rl_requests,
        "get",
        side_effect=requests.ConnectionError("connection reset"),
    ):
        with pytest.raises(NotionApiError) as raised:
            gateway.get_database(database_id="db1")

    assert raised.value.status_code is None
    assert isinstance(raised.value.__cause__, requests.ConnectionError)


def test_requests_carry_the_token_and_the_api_version() -> None:
    gateway = _gateway()

    with mock.patch.object(
        source_operations.rl_requests, "get", return_value=_response(200, {})
    ) as get:
        gateway.get_block_children(block_id="b1", start_cursor="c1")

    assert get.call_args.args[0] == "https://api.notion.com/v1/blocks/b1/children"
    headers = get.call_args.kwargs["headers"]
    assert headers["Authorization"] == f"Bearer {_TOKEN}"
    assert headers["Notion-Version"] == NOTION_API_VERSION
    assert get.call_args.kwargs["params"] == {"start_cursor": "c1"}


def test_a_credential_without_a_token_is_missing() -> None:
    gateway = _gateway({})

    with pytest.raises(ConnectorMissingCredentialError):
        gateway.get_bot_user()


def test_iter_search_follows_the_cursor_and_sends_the_sort() -> None:
    gateway = _gateway()
    pages = [
        _response(200, _search_body([{"id": "p1"}], "cursor-2")),
        _response(200, _search_body([{"id": "p2"}], None)),
    ]

    with mock.patch.object(
        source_operations.rl_requests, "post", side_effect=pages
    ) as post:
        results = list(
            gateway.iter_search(
                object_type=NotionSearchObjectType.PAGE, sort_by_last_edited=True
            )
        )

    assert [page.results[0]["id"] for page in results] == ["p1", "p2"]
    first_query, second_query = (call.kwargs["json"] for call in post.call_args_list)
    assert first_query["filter"] == {"property": "object", "value": "page"}
    assert first_query["sort"]["timestamp"] == "last_edited_time"
    assert "start_cursor" not in first_query
    assert second_query["start_cursor"] == "cursor-2"


def test_generator_operations_translate_errors_raised_while_iterating() -> None:
    """The second page fails after the caller has read the first: the error
    leaves the iteration as a gateway error."""
    gateway = _gateway()
    pages = [
        _response(200, _search_body([{"id": "p1"}], "cursor-2")),
        _response(404, _error_body(404, "object_not_found")),
    ]

    with mock.patch.object(
        source_operations.requests, "request", side_effect=pages
    ) as request:
        listing = gateway.iter_search(
            object_type=NotionSearchObjectType.DATA_SOURCE, fast=True
        )
        # Nothing is fetched until the caller iterates.
        request.assert_not_called()
        first: NotionSearchResponse = next(listing)
        with pytest.raises(NotionApiError) as raised:
            next(listing)

    assert first.results == [{"id": "p1"}]
    assert raised.value.status_code == 404


def test_connector_requires_credentials_for_the_gateway() -> None:
    connector = NotionConnector()

    with pytest.raises(ConnectorMissingCredentialError):
        connector.validate_connector_settings()


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (401, "unauthorized", CredentialExpiredError),
        (403, "restricted_resource", InsufficientPermissionsError),
        # A rate limit is transient: it must not pause a valid connector.
        (429, "rate_limited", UnexpectedValidationError),
    ],
)
def test_connector_settings_validation_maps_the_status(
    status: int, code: str, expected: type[Exception]
) -> None:
    connector = NotionConnector(root_page_id="root")
    connector.load_credentials(dict(_CREDENTIALS))

    with mock.patch.object(
        source_operations.rl_requests,
        "get",
        return_value=_response(status, _error_body(status, code)),
    ):
        with pytest.raises(expected):
            connector.validate_connector_settings()


def test_connector_skips_a_block_that_is_not_shared() -> None:
    connector = NotionConnector()
    connector.load_credentials(dict(_CREDENTIALS))

    with mock.patch.object(
        source_operations.rl_requests,
        "get",
        return_value=_response(404, _error_body(404, "object_not_found")),
    ):
        assert connector._fetch_child_blocks("b1") is None


def test_connector_does_not_skip_blocks_on_a_network_error() -> None:
    connector = NotionConnector()
    connector.load_credentials(dict(_CREDENTIALS))

    with (
        mock.patch.object(
            source_operations.rl_requests,
            "get",
            side_effect=requests.ConnectionError("connection reset"),
        ),
        mock.patch("time.sleep"),
    ):
        with pytest.raises(NotionApiError):
            connector._fetch_child_blocks("b1")


def test_connector_does_not_skip_blocks_on_a_bad_success_body() -> None:
    """A 200 with a body that is not JSON is retried and then raises; it is
    not read as a block that is not shared."""
    connector = NotionConnector()
    connector.load_credentials(dict(_CREDENTIALS))

    with (
        mock.patch.object(
            source_operations.rl_requests,
            "get",
            return_value=_response(200, text="<html>ok</html>"),
        ) as get,
        mock.patch("time.sleep"),
    ):
        with pytest.raises(NotionApiError):
            connector._fetch_child_blocks("b1")

    assert get.call_count == 3
