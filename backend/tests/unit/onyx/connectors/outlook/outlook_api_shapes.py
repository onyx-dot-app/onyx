"""Builders for the Graph JSON, gateway models and errors the Outlook tests need.

Every builder returns a complete shape, so a test names only the field under
test and passes it as an override.
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import requests

from onyx.connectors.outlook.models import (
    OutlookAttachment,
    OutlookFolder,
    OutlookGraphError,
    OutlookMailbox,
    OutlookMessage,
    OutlookMessageChange,
    OutlookRecipient,
)

MAILBOX_ID = "user-1"
MAILBOX_ADDRESS = "alice@contoso.com"
INBOX_ID = "folder-inbox"
CONVERSATION_ID = "conv-1"
RECEIVED = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)

CREDENTIALS = {
    "outlook_client_id": "client-id",
    "outlook_directory_id": "tenant-id",
    "outlook_client_secret": "secret",
}


def graph_error(status: int, code: str = "ErrorAccessDenied") -> OutlookGraphError:
    return OutlookGraphError(status, code, "denied")


def http_error(status: int, code: str = "ErrorAccessDenied") -> requests.HTTPError:
    """The failure the shared Graph client raises for a non-2xx response."""
    response = MagicMock()
    response.status_code = status
    response.json.return_value = {"error": {"code": code, "message": "denied"}}
    response.text = "denied"
    return requests.HTTPError("boom", response=response)


def user_json(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "id": MAILBOX_ID,
        "mail": MAILBOX_ADDRESS,
        "userPrincipalName": MAILBOX_ADDRESS,
        "displayName": "Alice",
    }
    return fields | overrides


def folder_json(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "id": INBOX_ID,
        "displayName": "Inbox",
        "parentFolderId": "root",
        "childFolderCount": 0,
    }
    return fields | overrides


def recipient_json(address: str, name: str | None = None) -> dict[str, Any]:
    return {"emailAddress": {"address": address, "name": name}}


def message_json(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "id": "msg-1",
        "conversationId": CONVERSATION_ID,
        "parentFolderId": INBOX_ID,
        "subject": "Quarterly plan",
        "body": {"contentType": "text", "content": "Hello team"},
        "sender": recipient_json(MAILBOX_ADDRESS, "Alice"),
        "toRecipients": [recipient_json("bob@contoso.com", "Bob")],
        "ccRecipients": [],
        "receivedDateTime": "2026-09-01T10:00:00Z",
        "sentDateTime": "2026-09-01T09:59:00Z",
        "webLink": "https://outlook.office.com/mail/id/msg-1",
        "isDraft": False,
    }
    return fields | overrides


def change_json(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "id": "msg-1",
        "conversationId": CONVERSATION_ID,
        "receivedDateTime": "2026-09-01T10:00:00Z",
    }
    return fields | overrides


def removed_json(message_id: str = "msg-gone") -> dict[str, Any]:
    return {"id": message_id, "@removed": {"reason": "deleted"}}


def page_json(
    values: list[dict[str, Any]], next_link: str | None = None
) -> dict[str, Any]:
    page: dict[str, Any] = {"value": values}
    if next_link:
        page["@odata.nextLink"] = next_link
    return page


def mailbox(**overrides: Any) -> OutlookMailbox:
    fields: dict[str, Any] = {
        "id": MAILBOX_ID,
        "address": MAILBOX_ADDRESS,
        "display_name": "Alice",
    }
    return OutlookMailbox(**(fields | overrides))


def folder(**overrides: Any) -> OutlookFolder:
    fields: dict[str, Any] = {"id": INBOX_ID, "display_name": "Inbox"}
    return OutlookFolder(**(fields | overrides))


def message(**overrides: Any) -> OutlookMessage:
    fields: dict[str, Any] = {
        "id": "msg-1",
        "conversation_id": CONVERSATION_ID,
        "parent_folder_id": INBOX_ID,
        "subject": "Quarterly plan",
        "body_text": "Hello team",
        "sender": OutlookRecipient(address=MAILBOX_ADDRESS, name="Alice"),
        "to_recipients": [OutlookRecipient(address="bob@contoso.com", name="Bob")],
        "received_at": RECEIVED,
        "sent_at": RECEIVED,
        "web_link": "https://outlook.office.com/mail/id/msg-1",
    }
    return OutlookMessage(**(fields | overrides))


def change(**overrides: Any) -> OutlookMessageChange:
    fields: dict[str, Any] = {
        "id": "msg-1",
        "conversation_id": CONVERSATION_ID,
        "received_at": RECEIVED,
    }
    return OutlookMessageChange(**(fields | overrides))


def attachment_json(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "id": "att-1",
        "name": "report.pdf",
        "size": 2048,
        "isInline": False,
    }
    return fields | overrides


def attachment(**overrides: Any) -> OutlookAttachment:
    fields: dict[str, Any] = {
        "id": "att-1",
        "name": "report.pdf",
        "size": 2048,
        "is_file": True,
    }
    return OutlookAttachment(**(fields | overrides))
