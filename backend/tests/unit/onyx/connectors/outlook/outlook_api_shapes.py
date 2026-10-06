"""Builders for the Graph JSON, gateway models and errors the Outlook tests need.

Every builder returns a complete shape, so a test names only the field under
test and passes it as an override.
"""

import base64
import hashlib
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import requests

from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OutlookGraphError,
)
from onyx.connectors.outlook.models import (
    OutlookAttachment,
    OutlookEvent,
    OutlookFolder,
    OutlookMailbox,
    OutlookMessage,
    OutlookMessageChange,
    OutlookRecipient,
)
from onyx.connectors.outlook.threads import thread_document_id, thread_key

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
        "conversationIndex": conversation_index(CONVERSATION_ID),
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
        "internet_message_id": f"<{overrides.get('id', 'msg-1')}@contoso.com>",
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


def conversation_index(conversation_id: str) -> str:
    """A conversation index whose thread root is unique to the conversation id."""
    return base64.b64encode(
        hashlib.sha256(conversation_id.encode()).digest()[:22]
    ).decode()


def thread_doc_id(conversation_id: str) -> str:
    """The thread document id a change made with ``change()`` leads to."""
    key = thread_key(conversation_index(conversation_id))
    assert key is not None
    return thread_document_id(key)


def change(**overrides: Any) -> OutlookMessageChange:
    fields: dict[str, Any] = {
        "id": "msg-1",
        "internet_message_id": f"<{overrides.get('id', 'msg-1')}@contoso.com>",
        "conversation_id": CONVERSATION_ID,
        "parent_folder_id": INBOX_ID,
        "received_at": RECEIVED,
    }
    conversation_id = overrides.get("conversation_id", CONVERSATION_ID)
    if conversation_id is not None:
        fields["conversation_index"] = conversation_index(conversation_id)
    return OutlookMessageChange(**(fields | overrides))


def event_json(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "id": "evt-1",
        "subject": "Quarterly review",
        "body": {"contentType": "text", "content": "Agenda: numbers"},
        "start": {"dateTime": "2026-09-02T14:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-09-02T15:00:00.0000000", "timeZone": "UTC"},
        "originalStartTimeZone": "UTC",
        "isAllDay": False,
        "isCancelled": False,
        "sensitivity": "normal",
        "type": "singleInstance",
        "seriesMasterId": None,
        "organizer": recipient_json(MAILBOX_ADDRESS, "Alice"),
        "attendees": [
            {"type": "required", **recipient_json("bob@contoso.com", "Bob")},
            {"type": "optional", **recipient_json(MAILBOX_ADDRESS, "Alice")},
        ],
        "location": {"displayName": "Room 4"},
        "webLink": "https://outlook.office365.com/calendar/item/evt-1",
        "createdDateTime": "2026-08-20T09:00:00Z",
        "lastModifiedDateTime": "2026-09-01T09:00:00Z",
    }
    return fields | overrides


def event(**overrides: Any) -> OutlookEvent:
    fields: dict[str, Any] = {
        "id": "evt-1",
        "subject": "Quarterly review",
        "body_text": "Agenda: numbers",
        "start_at": datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc),
        "end_at": datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc),
        "organizer": OutlookRecipient(address=MAILBOX_ADDRESS, name="Alice"),
        "attendees": [
            OutlookRecipient(address="bob@contoso.com", name="Bob"),
            OutlookRecipient(address=MAILBOX_ADDRESS, name="Alice"),
        ],
        "location": "Room 4",
        "web_link": "https://outlook.office365.com/calendar/item/evt-1",
        "created_at": datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
        "last_modified_at": RECEIVED,
    }
    return OutlookEvent(**(fields | overrides))


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


def memory_file_store() -> MagicMock:
    """A file store kept in a dict, with the records the thread table lists."""
    files: dict[str, bytes] = {}
    store = MagicMock()

    def save_file(*, content: BytesIO, file_id: str, **_: object) -> None:
        files[file_id] = content.read()

    def read_file(file_id: str, mode: str = "b") -> BytesIO:  # noqa: ARG001
        return BytesIO(files[file_id])

    def list_files_by_prefix(prefix: str) -> list[MagicMock]:
        return [
            MagicMock(file_id=f, created_at=datetime.now(timezone.utc))
            for f in files
            if f.startswith(prefix)
        ]

    def delete_file(file_id: str, error_on_missing: bool = True) -> None:  # noqa: ARG001
        files.pop(file_id, None)

    store.save_file.side_effect = save_file
    store.read_file.side_effect = read_file
    store.list_files_by_prefix.side_effect = list_files_by_prefix
    store.delete_file.side_effect = delete_file
    store.files = files
    return store
