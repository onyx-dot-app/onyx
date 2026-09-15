"""The Outlook gateway builds the right Graph requests and returns plain data.

The Graph client is replaced below the gateway, so these tests exercise the
real query construction, pagination and error mapping without a network.
"""

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from msal.exceptions import MsalServiceError

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.outlook.models import (
    INVALID_AUTHORITY_CODE,
    MISSING_CREDENTIAL_CODE,
    OutlookAuthError,
    OutlookGraphError,
)
from onyx.connectors.outlook.source_operations import (
    CHANGE_SELECT,
    EMPTY_PAGE_FOLLOW_LIMIT,
    EPOCH_TIMESTAMP,
    MESSAGE_SELECT,
    MESSAGES_PAGE_SIZE,
    TEXT_BODY_PREFERENCE,
    OutlookSourceOperations,
)
from tests.unit.onyx.connectors.outlook.outlook_api_shapes import (
    CONVERSATION_ID,
    CREDENTIALS,
    INBOX_ID,
    MAILBOX_ADDRESS,
    MAILBOX_ID,
    change_json,
    folder_json,
    http_error,
    message_json,
    page_json,
    removed_json,
    user_json,
)

MODULE = "onyx.connectors.outlook.source_operations"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _gateway(
    credentials: dict[str, Any] | None = None,
) -> tuple[OutlookSourceOperations, MagicMock]:
    """A gateway whose Graph client is a mock, so ``_get`` runs for real."""
    gateway = OutlookSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None, "outlook", CREDENTIALS if credentials is None else credentials
        )
    )
    client = MagicMock()
    gateway._graph_client = client
    return gateway, client


def test_list_mailbox_users_builds_the_users_query() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json(
        [
            user_json(),
            user_json(id="user-2", mail=None, userPrincipalName="svc@contoso.com"),
        ]
    )

    result = gateway.list_mailbox_users(page_size=2)

    url, params = client.get_json.call_args.args[:2]
    assert url == f"{GRAPH_BASE}/users"
    assert params["$filter"] == "accountEnabled eq true"
    assert params["$top"] == "2"
    # An enabled user without a mail address has no mailbox to probe.
    assert [m.address for m in result.mailboxes] == [MAILBOX_ADDRESS]
    assert result.next_link is None


def test_list_mailbox_users_follows_next_link_without_resending_params() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json([])

    gateway.list_mailbox_users(next_link="https://graph/next")

    assert client.get_json.call_args.args[:2] == ("https://graph/next", None)


def test_resolve_mailbox_falls_back_to_the_primary_smtp_address() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = [
        http_error(404, "Request_ResourceNotFound"),
        page_json([user_json()]),
    ]

    result = gateway.resolve_mailbox(address="alias@contoso.com")

    assert result is not None and result.id == MAILBOX_ID
    fallback_params = client.get_json.call_args_list[1].args[1]
    assert fallback_params["$filter"] == "mail eq 'alias@contoso.com'"


def test_resolve_mailbox_returns_none_when_nothing_matches() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = [
        http_error(404, "Request_ResourceNotFound"),
        page_json([]),
    ]

    assert gateway.resolve_mailbox(address="ghost@contoso.com") is None


def test_resolve_mailbox_quotes_the_address_in_the_path() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = user_json()

    gateway.resolve_mailbox(address="o'brien@contoso.com")

    assert (
        client.get_json.call_args.args[0] == f"{GRAPH_BASE}/users/o%27brien@contoso.com"
    )


def test_graph_failures_surface_status_and_code() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = http_error(403, "ErrorAccessDenied")

    with pytest.raises(OutlookGraphError) as exc_info:
        gateway.probe_mailbox(mailbox_id=MAILBOX_ID)

    assert exc_info.value.status == 403
    assert exc_info.value.code == "ErrorAccessDenied"


def test_graph_failure_without_a_json_body_keeps_the_text() -> None:
    gateway, client = _gateway()
    response = MagicMock()
    response.status_code = 502
    response.json.side_effect = ValueError("not json")
    response.text = "<html>Bad gateway</html>"
    client.get_json.side_effect = requests.HTTPError("boom", response=response)

    with pytest.raises(OutlookGraphError) as exc_info:
        gateway.probe_mailbox(mailbox_id=MAILBOX_ID)

    assert exc_info.value.status == 502
    assert exc_info.value.code == "<no code>"
    assert "Bad gateway" in str(exc_info.value)


def test_oauth_error_bodies_keep_their_bare_code_and_description() -> None:
    """The token endpoint puts a string in "error", unlike Graph's nested object."""
    gateway, client = _gateway()
    response = MagicMock()
    response.status_code = 503
    response.json.return_value = {
        "error": "temporarily_unavailable",
        "error_description": "AADSTS90033: retry later",
    }
    response.text = "irrelevant"
    client.get_json.side_effect = requests.HTTPError("boom", response=response)

    with pytest.raises(OutlookGraphError) as exc_info:
        gateway.probe_mailbox(mailbox_id=MAILBOX_ID)

    assert exc_info.value.status == 503
    assert exc_info.value.code == "temporarily_unavailable"
    assert "AADSTS90033" in str(exc_info.value)


def test_transport_failure_after_retries_is_a_graph_error_without_status() -> None:
    """The shared client re-raises a transport error once its retries are
    spent, and the connector must see it as a gateway failure like any other."""
    gateway, client = _gateway()
    client.get_json.side_effect = requests.Timeout("read timed out")

    with pytest.raises(OutlookGraphError) as exc_info:
        gateway.fetch_conversation_messages_page(
            mailbox_id=MAILBOX_ID, conversation_id=CONVERSATION_ID
        )

    assert exc_info.value.status is None
    assert exc_info.value.code == "Timeout"


def test_unreadable_body_after_retries_is_a_graph_error_without_status() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = ValueError("Expecting value: line 1 column 1")

    with pytest.raises(OutlookGraphError) as exc_info:
        gateway.probe_mailbox(mailbox_id=MAILBOX_ID)

    assert exc_info.value.status is None
    assert exc_info.value.code == "ValueError"


def test_principal_names_starting_with_a_dollar_use_the_key_literal_form() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = user_json()

    gateway.resolve_mailbox(address="$svc@contoso.com")

    assert (
        client.get_json.call_args.args[0] == f"{GRAPH_BASE}/users('$svc@contoso.com')"
    )


def test_well_known_folder_lookup_treats_404_as_absent() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = http_error(404, "ErrorItemNotFound")

    assert gateway.get_well_known_folder(mailbox_id=MAILBOX_ID, name="archive") is None


def test_well_known_folder_lookup_reraises_other_statuses() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = http_error(403)

    with pytest.raises(OutlookGraphError):
        gateway.get_well_known_folder(mailbox_id=MAILBOX_ID, name="junkemail")


def test_child_folder_listing_marks_search_folders() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json(
        [
            folder_json(),
            folder_json(
                id="search-1",
                displayName="Weekly digests",
                **{"@odata.type": "#microsoft.graph.mailSearchFolder"},
            ),
        ]
    )

    result = gateway.list_child_folders(
        mailbox_id=MAILBOX_ID, parent_folder_id=INBOX_ID
    )

    url, params = client.get_json.call_args.args[:2]
    assert url.endswith(f"/mailFolders/{INBOX_ID}/childFolders")
    assert params["includeHiddenFolders"] == "true"
    assert [f.is_search_folder for f in result.folders] == [False, True]


def test_folder_listing_marks_hidden_folders() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json(
        [folder_json(), folder_json(id="hidden-1", isHidden=True)]
    )

    result = gateway.list_child_folders(mailbox_id=MAILBOX_ID)

    assert client.get_json.call_args.args[0].endswith("/mailFolders")
    assert [f.is_hidden for f in result.folders] == [False, True]


def test_delta_page_sends_query_params_once_and_the_page_size_header_always() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json(
        [change_json(), removed_json()], next_link="https://graph/delta?$skiptoken=1"
    )

    result = gateway.fetch_folder_delta_page(
        mailbox_id=MAILBOX_ID,
        folder_id=INBOX_ID,
        received_after=datetime(2026, 9, 1, tzinfo=timezone.utc),
        page_size=5,
    )

    url, params, headers = client.get_json.call_args.args
    assert url.endswith(f"/mailFolders/{INBOX_ID}/messages/delta")
    assert params == {
        "changeType": "created",
        "$select": CHANGE_SELECT,
        "$filter": "receivedDateTime ge 2026-09-01T00:00:00Z",
    }
    assert headers == {"Prefer": "odata.maxpagesize=5"}
    assert [c.removed for c in result.changes] == [False, True]
    assert result.changes[0].conversation_id == CONVERSATION_ID
    assert result.next_link == "https://graph/delta?$skiptoken=1"

    gateway.fetch_folder_delta_page(
        mailbox_id=MAILBOX_ID,
        folder_id=INBOX_ID,
        page_size=5,
        next_link=result.next_link,
    )
    assert client.get_json.call_args.args == (
        result.next_link,
        None,
        {"Prefer": "odata.maxpagesize=5"},
    )


def test_delta_page_without_a_window_sends_no_filter() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json([])

    gateway.fetch_folder_delta_page(mailbox_id=MAILBOX_ID, folder_id=INBOX_ID)

    assert "$filter" not in client.get_json.call_args.args[1]


def test_conversation_page_orders_newest_first_and_reads_text_bodies() -> None:
    gateway, client = _gateway()
    html = message_json(
        id="msg-2",
        body={"contentType": "html", "content": "<p>Hi <b>Bob</b></p>"},
    )
    client.get_json.return_value = page_json(
        [message_json(), html], next_link="https://graph/messages?page=2"
    )

    result = gateway.fetch_conversation_messages_page(
        mailbox_id=MAILBOX_ID, conversation_id="conv'1", page_size=3
    )

    url, params, headers = client.get_json.call_args.args
    assert url == f"{GRAPH_BASE}/users/{MAILBOX_ID}/messages"
    assert params["$filter"] == (
        f"receivedDateTime ge {EPOCH_TIMESTAMP} and conversationId eq 'conv''1'"
    )
    assert params["$orderby"] == "receivedDateTime desc"
    assert params["$top"] == "3"
    assert headers == {"Prefer": TEXT_BODY_PREFERENCE}
    assert [m.id for m in result.messages] == ["msg-1", "msg-2"]
    assert result.messages[1].body_text == "Hi Bob"
    assert result.messages[0].sender is not None
    assert result.messages[0].sender.address == MAILBOX_ADDRESS
    assert result.next_link == "https://graph/messages?page=2"


def test_conversation_next_page_keeps_the_body_preference_and_drops_params() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json([message_json(id="msg-3")])

    result = gateway.fetch_conversation_messages_page(
        mailbox_id=MAILBOX_ID,
        conversation_id=CONVERSATION_ID,
        next_link="https://graph/messages?page=2",
    )

    assert client.get_json.call_args.args == (
        "https://graph/messages?page=2",
        None,
        {"Prefer": TEXT_BODY_PREFERENCE},
    )
    assert [m.id for m in result.messages] == ["msg-3"]
    assert result.next_link is None


def test_read_any_message_selects_the_indexed_fields_as_text() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json([message_json()])

    result = gateway.read_any_message(mailbox_id=MAILBOX_ID)

    url, params, headers = client.get_json.call_args.args
    assert url == f"{GRAPH_BASE}/users/{MAILBOX_ID}/messages"
    assert params == {"$select": MESSAGE_SELECT, "$top": "1"}
    assert headers == {"Prefer": TEXT_BODY_PREFERENCE}
    assert result is not None and result.body_text == "Hello team"


def test_read_any_message_is_none_for_an_empty_mailbox() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json([])

    assert gateway.read_any_message(mailbox_id=MAILBOX_ID) is None


def test_read_any_message_follows_an_empty_page_with_a_next_link() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = [
        page_json([], next_link="https://graph/messages?page=2"),
        page_json([message_json()]),
    ]

    result = gateway.read_any_message(mailbox_id=MAILBOX_ID)

    assert result is not None and result.id == "msg-1"
    assert client.get_json.call_args_list[1].args == (
        "https://graph/messages?page=2",
        None,
        {"Prefer": TEXT_BODY_PREFERENCE},
    )


def test_endless_empty_pages_are_a_failure_not_an_empty_mailbox() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json(
        [], next_link="https://graph/messages?again"
    )

    with pytest.raises(OutlookGraphError) as exc_info:
        gateway.read_any_message(mailbox_id=MAILBOX_ID)

    assert exc_info.value.status is None
    assert exc_info.value.code == "EmptyPages"
    assert client.get_json.call_count == EMPTY_PAGE_FOLLOW_LIMIT


def test_an_empty_collection_that_ends_on_the_last_budgeted_page_is_empty() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = [
        page_json([], next_link="https://graph/messages?again")
        for _ in range(EMPTY_PAGE_FOLLOW_LIMIT - 1)
    ] + [page_json([])]

    assert gateway.read_any_message(mailbox_id=MAILBOX_ID) is None
    assert client.get_json.call_count == EMPTY_PAGE_FOLLOW_LIMIT


def test_resolve_mailbox_fallback_follows_an_empty_page_with_a_next_link() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = [
        http_error(404, "Request_ResourceNotFound"),
        page_json([], next_link="https://graph/users?page=2"),
        page_json([user_json()]),
    ]

    result = gateway.resolve_mailbox(address="alias@contoso.com")

    assert result is not None and result.id == MAILBOX_ID
    assert client.get_json.call_count == 3


def test_conversation_page_size_defaults_to_the_message_page_size() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json([])

    gateway.fetch_conversation_messages_page(
        mailbox_id=MAILBOX_ID, conversation_id=CONVERSATION_ID
    )

    assert client.get_json.call_args.args[1]["$top"] == str(MESSAGES_PAGE_SIZE)


def test_missing_credential_field_fails_before_msal_is_built() -> None:
    gateway, _ = _gateway({**CREDENTIALS, "outlook_client_secret": ""})

    with (
        patch(f"{MODULE}.build_msal_app") as build,
        pytest.raises(OutlookAuthError) as exc_info,
    ):
        gateway.check_token()

    assert exc_info.value.code == MISSING_CREDENTIAL_CODE
    build.assert_not_called()


def test_unparseable_discovery_body_is_a_graph_error_not_a_bad_directory() -> None:
    """MSAL wraps the decode error of a discovery body in a ValueError, which
    is a broken proxy or outage rather than a wrong directory id."""
    gateway, _ = _gateway()

    def wrapped_decode_error(**kwargs: Any) -> None:
        del kwargs
        try:
            json.loads("<html>")
        except json.JSONDecodeError as e:
            raise ValueError("Unable to get authority configuration") from e

    with (
        patch(f"{MODULE}.build_msal_app", side_effect=wrapped_decode_error),
        pytest.raises(OutlookGraphError) as exc_info,
    ):
        gateway.check_token()

    assert exc_info.value.status is None
    assert exc_info.value.code == "ValueError"


@pytest.mark.parametrize(
    "failure, status",
    [
        (
            ValueError(
                "OIDC Discovery failed on https://login/x. HTTP status: 429, Error: slow"
            ),
            429,
        ),
        (
            MsalServiceError("HTTP Error: 503", error="", error_description=""),
            503,
        ),
    ],
)
def test_discovery_service_trouble_keeps_its_status(
    failure: Exception, status: int
) -> None:
    gateway, _ = _gateway()

    with (
        patch(f"{MODULE}.build_msal_app", side_effect=failure),
        pytest.raises(OutlookGraphError) as exc_info,
    ):
        gateway.check_token()

    assert exc_info.value.status == status


def test_throttled_discovery_wrapped_by_msal_keeps_its_status() -> None:
    """MSAL raises its own ValueError from the discovery one, so the status
    sits in the chained exception rather than the outer message."""
    gateway, _ = _gateway()

    def wrapped_throttle(**kwargs: Any) -> None:
        del kwargs
        try:
            raise ValueError(
                "OIDC Discovery failed on https://login/x. HTTP status: 429, Error: slow"
            )
        except ValueError as e:
            raise ValueError("Unable to get authority configuration for x") from e

    with (
        patch(f"{MODULE}.build_msal_app", side_effect=wrapped_throttle),
        pytest.raises(OutlookGraphError) as exc_info,
    ):
        gateway.check_token()

    assert exc_info.value.status == 429


def test_token_endpoint_5xx_keeps_its_status() -> None:
    gateway, _ = _gateway()

    with (
        patch(f"{MODULE}.build_msal_app"),
        patch(
            f"{MODULE}.acquire_graph_token",
            side_effect=MsalServiceError(
                "HTTP Error: 502", error="", error_description=""
            ),
        ),
        pytest.raises(OutlookGraphError) as exc_info,
    ):
        gateway.check_token()

    assert exc_info.value.status == 502
    assert exc_info.value.code == "MsalServiceError"


def test_unknown_directory_is_an_auth_error_with_a_stable_code() -> None:
    gateway, _ = _gateway()

    with (
        patch(
            f"{MODULE}.build_msal_app",
            side_effect=ValueError("Unable to get authority configuration"),
        ),
        pytest.raises(OutlookAuthError) as exc_info,
    ):
        gateway.check_token()

    assert exc_info.value.code == INVALID_AUTHORITY_CODE


@pytest.mark.parametrize(
    "failure, code",
    [
        (requests.ConnectionError("login unreachable"), "ConnectionError"),
        (ValueError("Expecting value: line 1 column 1"), "ValueError"),
    ],
)
def test_token_endpoint_failures_are_graph_errors_without_status(
    failure: Exception, code: str
) -> None:
    gateway, _ = _gateway()

    with (
        patch(f"{MODULE}.build_msal_app"),
        patch(f"{MODULE}.acquire_graph_token", side_effect=failure),
        pytest.raises(OutlookGraphError) as exc_info,
    ):
        gateway.check_token()

    assert exc_info.value.status is None
    assert exc_info.value.code == code


def test_check_token_maps_msal_refusal() -> None:
    gateway, _ = _gateway()

    with (
        patch(f"{MODULE}.build_msal_app"),
        patch(
            f"{MODULE}.acquire_graph_token",
            return_value={"error": "invalid_client", "error_description": "bad secret"},
        ),
        pytest.raises(OutlookAuthError) as exc_info,
    ):
        gateway.check_token()

    assert exc_info.value.code == "invalid_client"


def test_check_token_reports_expiry() -> None:
    gateway, _ = _gateway()

    with (
        patch(f"{MODULE}.build_msal_app"),
        patch(
            f"{MODULE}.acquire_graph_token",
            return_value={"access_token": "tok", "expires_in": "3599"},
        ),
    ):
        info = gateway.check_token()

    assert info.expires_in == 3599
