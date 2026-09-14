"""The Outlook gateway builds the right Graph requests and returns plain data.

The Graph client is replaced below the gateway, so these tests exercise the
real query construction, pagination and error mapping without a network.
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.outlook.models import OutlookAuthError, OutlookGraphError
from onyx.connectors.outlook.source_operations import (
    CHANGE_SELECT,
    MISSING_CREDENTIAL_CODE,
    TEXT_BODY_PREFERENCE,
    OutlookSourceOperations,
)
from tests.unit.onyx.connectors.outlook.outlook_api_shapes import (
    CONVERSATION_ID,
    INBOX_ID,
    MAILBOX_ADDRESS,
    MAILBOX_ID,
    change_json,
    folder_json,
    message_json,
    page_json,
    removed_json,
    user_json,
)

MODULE = "onyx.connectors.outlook.source_operations"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

CREDENTIALS = {
    "outlook_client_id": "client-id",
    "outlook_directory_id": "tenant-id",
    "outlook_client_secret": "secret",
}


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


def _http_error(status: int, code: str = "ErrorAccessDenied") -> requests.HTTPError:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = {"error": {"code": code, "message": "denied"}}
    response.text = "denied"
    return requests.HTTPError("boom", response=response)


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
    assert [m.address for m in result.mailboxes] == [MAILBOX_ADDRESS, "svc@contoso.com"]
    assert result.next_link is None


def test_list_mailbox_users_follows_next_link_without_resending_params() -> None:
    gateway, client = _gateway()
    client.get_json.return_value = page_json([])

    gateway.list_mailbox_users(next_link="https://graph/next")

    assert client.get_json.call_args.args[:2] == ("https://graph/next", None)


def test_resolve_mailbox_falls_back_to_the_primary_smtp_address() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = [
        _http_error(404, "Request_ResourceNotFound"),
        page_json([user_json()]),
    ]

    result = gateway.resolve_mailbox(address="alias@contoso.com")

    assert result is not None and result.id == MAILBOX_ID
    fallback_params = client.get_json.call_args_list[1].args[1]
    assert fallback_params["$filter"] == "mail eq 'alias@contoso.com'"


def test_resolve_mailbox_returns_none_when_nothing_matches() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = [
        _http_error(404, "Request_ResourceNotFound"),
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
    client.get_json.side_effect = _http_error(403, "ErrorAccessDenied")

    with pytest.raises(OutlookGraphError) as exc_info:
        gateway.probe_mailbox(mailbox_id=MAILBOX_ID)

    assert exc_info.value.status == 403
    assert exc_info.value.code == "ErrorAccessDenied"


def test_well_known_folder_lookup_treats_404_as_absent() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = _http_error(404, "ErrorItemNotFound")

    assert gateway.get_well_known_folder(mailbox_id=MAILBOX_ID, name="archive") is None


def test_well_known_folder_lookup_reraises_other_statuses() -> None:
    gateway, client = _gateway()
    client.get_json.side_effect = _http_error(403)

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

    assert client.get_json.call_args.args[0].endswith(
        f"/mailFolders/{INBOX_ID}/childFolders"
    )
    assert [f.is_search_folder for f in result.folders] == [False, True]


def test_delta_page_sends_filter_and_page_size_only_on_the_first_request() -> None:
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
        mailbox_id=MAILBOX_ID, folder_id=INBOX_ID, next_link=result.next_link
    )
    assert client.get_json.call_args.args[:2] == (result.next_link, None)


def test_conversation_messages_page_until_the_limit_and_read_text_bodies() -> None:
    gateway, client = _gateway()
    html = message_json(
        id="msg-2",
        body={"contentType": "html", "content": "<p>Hi <b>Bob</b></p>"},
    )
    client.get_json.side_effect = [
        page_json([message_json(), html], next_link="https://graph/messages?page=2"),
        page_json([message_json(id="msg-3"), message_json(id="msg-4")]),
    ]

    result = gateway.list_conversation_messages(
        mailbox_id=MAILBOX_ID, conversation_id="conv'1", limit=3
    )

    first_url, first_params, first_headers = client.get_json.call_args_list[0].args
    assert first_url == f"{GRAPH_BASE}/users/{MAILBOX_ID}/messages"
    assert first_params["$filter"] == "conversationId eq 'conv''1'"
    assert first_headers == {"Prefer": TEXT_BODY_PREFERENCE}
    assert client.get_json.call_args_list[1].args[1] is None
    assert [m.id for m in result] == ["msg-1", "msg-2", "msg-3"]
    assert result[1].body_text == "Hi Bob"
    assert result[0].sender is not None and result[0].sender.address == MAILBOX_ADDRESS


def test_missing_credential_field_fails_before_msal_is_built() -> None:
    gateway, _ = _gateway({**CREDENTIALS, "outlook_client_secret": ""})

    with (
        patch(f"{MODULE}.build_msal_app") as build,
        pytest.raises(OutlookAuthError) as exc_info,
    ):
        gateway.check_token()

    assert exc_info.value.code == MISSING_CREDENTIAL_CODE
    build.assert_not_called()


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
