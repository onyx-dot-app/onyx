"""Outlook source-operations gateway: every Graph mail call lives here.

Indexing and the capability checks compose these operations, and nothing else
under ``onyx/connectors/outlook`` talks to Graph. Transport, retry and token
acquisition come from the shared Microsoft package. Each operation returns the
plain models in ``models.py`` so a Graph schema change surfaces in one file.

Application permissions this gateway needs: ``Mail.Read`` for folders and
messages, ``User.Read.All`` to enumerate and resolve mailboxes.
"""

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import bs4
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.microsoft_utils.drive_items import parse_graph_datetime
from onyx.connectors.microsoft_utils.graph_auth import (
    MicrosoftAuthContext,
    acquire_graph_token,
    build_msal_app,
)
from onyx.connectors.microsoft_utils.graph_client import (
    GraphApiClient,
    graph_error_code,
)
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)
from onyx.connectors.outlook.models import (
    OutlookAuthError,
    OutlookDeltaPage,
    OutlookFolder,
    OutlookFolderPage,
    OutlookGraphError,
    OutlookMailbox,
    OutlookMailboxPage,
    OutlookMessage,
    OutlookMessageChange,
    OutlookRecipient,
    OutlookTokenInfo,
)
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

GRAPH_API_VERSION = "v1.0"

CREDENTIAL_CLIENT_ID = "outlook_client_id"
CREDENTIAL_DIRECTORY_ID = "outlook_directory_id"
CREDENTIAL_CLIENT_SECRET = "outlook_client_secret"
CREDENTIAL_FIELDS = (
    CREDENTIAL_CLIENT_ID,
    CREDENTIAL_DIRECTORY_ID,
    CREDENTIAL_CLIENT_SECRET,
)
# Raised as an OutlookAuthError code before MSAL is ever built, so a blank
# form field reads as a credential problem and not a KeyError.
MISSING_CREDENTIAL_CODE = "missing_credential"

CONFIG_AUTHORITY_HOST = "authority_host"
CONFIG_GRAPH_API_HOST = "graph_api_host"

# Graph caps $top at 999 for users and 1000 for messages.
USERS_PAGE_SIZE = 999
FOLDERS_PAGE_SIZE = 250
MESSAGES_PAGE_SIZE = 100

MAILBOX_SELECT = "id,mail,userPrincipalName,displayName"
FOLDER_SELECT = "id,displayName,parentFolderId,childFolderCount,totalItemCount"
# The delta walk only needs to know which conversations changed.
CHANGE_SELECT = "id,conversationId,receivedDateTime"
MESSAGE_SELECT = ",".join(
    (
        "id",
        "conversationId",
        "parentFolderId",
        "subject",
        "body",
        "sender",
        "toRecipients",
        "ccRecipients",
        "receivedDateTime",
        "sentDateTime",
        "webLink",
        "hasAttachments",
        "isDraft",
    )
)

# Graph renders bodies as HTML unless asked for text, and text spares a parse.
TEXT_BODY_PREFERENCE = 'outlook.body-content-type="text"'
SEARCH_FOLDER_TYPE = "#microsoft.graph.mailSearchFolder"


def _odata_quote(value: str) -> str:
    """Escape a value for an OData string literal. Only the quote is special."""
    return value.replace("'", "''")


def _to_graph_error(error: requests.HTTPError) -> OutlookGraphError:
    response = error.response
    if response is None:
        return OutlookGraphError(None, "<no response>", str(error))
    try:
        message = response.json().get("error", {}).get("message") or response.text
    except ValueError:
        message = response.text
    return OutlookGraphError(
        response.status_code, graph_error_code(response), str(message)[:500]
    )


def _recipient(raw: dict[str, Any] | None) -> OutlookRecipient | None:
    address = ((raw or {}).get("emailAddress") or {}).get("address")
    if not address:
        return None
    return OutlookRecipient(
        address=address, name=(raw or {}).get("emailAddress", {}).get("name")
    )


def _recipients(raw: list[dict[str, Any]] | None) -> list[OutlookRecipient]:
    return [r for r in (_recipient(item) for item in raw or []) if r is not None]


def _body_text(raw: dict[str, Any] | None) -> str:
    body = raw or {}
    content = body.get("content") or ""
    if body.get("contentType", "").lower() != "html":
        return content
    soup = bs4.BeautifulSoup(markup=content, features="html.parser")
    return " ".join(soup.stripped_strings)


def _parse_mailbox(raw: dict[str, Any]) -> OutlookMailbox | None:
    user_id = raw.get("id")
    address = raw.get("mail") or raw.get("userPrincipalName")
    if not user_id or not address:
        return None
    return OutlookMailbox(
        id=user_id, address=address, display_name=raw.get("displayName")
    )


def _parse_folder(raw: dict[str, Any]) -> OutlookFolder:
    return OutlookFolder(
        id=raw["id"],
        display_name=raw.get("displayName") or "",
        parent_folder_id=raw.get("parentFolderId"),
        child_folder_count=raw.get("childFolderCount") or 0,
        total_item_count=raw.get("totalItemCount") or 0,
        is_search_folder=raw.get("@odata.type") == SEARCH_FOLDER_TYPE,
    )


def _parse_change(raw: dict[str, Any]) -> OutlookMessageChange:
    received = raw.get("receivedDateTime")
    return OutlookMessageChange(
        id=raw["id"],
        removed="@removed" in raw,
        conversation_id=raw.get("conversationId"),
        received_at=parse_graph_datetime(received) if received else None,
    )


def _parse_message(raw: dict[str, Any]) -> OutlookMessage:
    received = raw.get("receivedDateTime")
    sent = raw.get("sentDateTime")
    return OutlookMessage(
        id=raw["id"],
        conversation_id=raw.get("conversationId"),
        parent_folder_id=raw.get("parentFolderId"),
        subject=raw.get("subject"),
        body_text=_body_text(raw.get("body")),
        sender=_recipient(raw.get("sender")),
        to_recipients=_recipients(raw.get("toRecipients")),
        cc_recipients=_recipients(raw.get("ccRecipients")),
        received_at=parse_graph_datetime(received) if received else None,
        sent_at=parse_graph_datetime(sent) if sent else None,
        web_link=raw.get("webLink"),
        has_attachments=bool(raw.get("hasAttachments")),
        is_draft=bool(raw.get("isDraft")),
    )


def _graph_timestamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OutlookSourceOperations(SourceOperations):
    source = DocumentSource.OUTLOOK
    # msal reaches this directory only through the shared package, and requests
    # is fenced so the connector cannot bypass the gateway with a raw call.
    sdk_modules = ("msal", "requests")

    # Built lazily on first use so the credential is decrypted at the first
    # remote call, not at construction.
    _auth_context: MicrosoftAuthContext | None = None
    _graph_client: GraphApiClient | None = None

    def _config_value(self, key: str, default: str) -> str:
        config = self.connector_specific_config or {}
        value = config.get(key)
        return (value or default).rstrip("/")

    def _graph_host(self) -> str:
        return self._config_value(CONFIG_GRAPH_API_HOST, DEFAULT_GRAPH_API_HOST)

    def _graph_base(self) -> str:
        return f"{self._graph_host()}/{GRAPH_API_VERSION}"

    def _auth(self) -> MicrosoftAuthContext:
        if self._auth_context is None:
            credentials = self.credentials_provider.get_credentials()
            missing = [
                field
                for field in CREDENTIAL_FIELDS
                if not str(credentials.get(field) or "").strip()
            ]
            if missing:
                raise OutlookAuthError(
                    MISSING_CREDENTIAL_CODE, "missing " + ", ".join(missing)
                )
            self._auth_context = build_msal_app(
                client_id=credentials[CREDENTIAL_CLIENT_ID],
                directory_id=credentials[CREDENTIAL_DIRECTORY_ID],
                authority_host=self._config_value(
                    CONFIG_AUTHORITY_HOST, DEFAULT_AUTHORITY_HOST
                ),
                client_secret=credentials[CREDENTIAL_CLIENT_SECRET],
            )
        return self._auth_context

    def _token_response(self) -> dict[str, Any]:
        response = acquire_graph_token(self._auth().app, self._graph_host())
        if "access_token" not in response:
            raise OutlookAuthError(
                str(response.get("error") or "unknown_error"),
                str(response.get("error_description") or ""),
            )
        return response

    def _access_token(self) -> str:
        return str(self._token_response()["access_token"])

    def _client(self) -> GraphApiClient:
        if self._graph_client is None:
            self._graph_client = GraphApiClient(self._access_token, self._graph_base())
        return self._graph_client

    def _get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._client().get_json(url, params, headers)
        except requests.HTTPError as e:
            raise _to_graph_error(e) from e

    def _user_url(self, mailbox_id: str) -> str:
        return f"{self._graph_base()}/users/{quote(mailbox_id, safe='@')}"

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def check_token(self) -> OutlookTokenInfo:
        """Acquire an app-only token: proves client id, directory id and secret agree."""
        response = self._token_response()
        expires_in = response.get("expires_in")
        return OutlookTokenInfo(
            expires_in=int(expires_in) if expires_in is not None else None
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_mailbox_users(
        self, *, page_size: int = USERS_PAGE_SIZE, next_link: str | None = None
    ) -> OutlookMailboxPage:
        """One page of enabled users, the candidates in every-mailbox mode.

        Needs ``User.Read.All``. Whether a user actually has a mailbox is only
        known once :meth:`probe_mailbox` is called for it.
        """
        params = None
        url = next_link
        if url is None:
            url = f"{self._graph_base()}/users"
            params = {
                "$filter": "accountEnabled eq true",
                "$select": MAILBOX_SELECT,
                "$top": str(page_size),
            }
        data = self._get(url, params)
        mailboxes = [
            mailbox
            for mailbox in (_parse_mailbox(raw) for raw in data.get("value", []))
            if mailbox is not None
        ]
        return OutlookMailboxPage(
            mailboxes=mailboxes, next_link=data.get("@odata.nextLink")
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def resolve_mailbox(self, *, address: str) -> OutlookMailbox | None:
        """Find the user behind an address: by UPN or object id, then by primary SMTP."""
        params = {"$select": MAILBOX_SELECT}
        try:
            return _parse_mailbox(self._get(self._user_url(address), params))
        except OutlookGraphError as e:
            if e.status != 404:
                raise
        params["$filter"] = f"mail eq '{_odata_quote(address)}'"
        users = self._get(f"{self._graph_base()}/users", params).get("value", [])
        return _parse_mailbox(users[0]) if users else None

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def probe_mailbox(self, *, mailbox_id: str) -> OutlookFolder:
        """Read the Inbox record.

        The cheapest call that proves the mailbox exists, is licensed and sits
        inside the app's Exchange scope. 403 means out of scope, 404 means no
        mailbox behind the user.
        """
        return _parse_folder(
            self._get(
                f"{self._user_url(mailbox_id)}/mailFolders/inbox",
                {"$select": FOLDER_SELECT},
            )
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_well_known_folder(
        self, *, mailbox_id: str, name: str
    ) -> OutlookFolder | None:
        """Resolve a well-known folder name such as ``junkemail`` to its folder.

        Display names are localized per mailbox, so exclusions resolve through
        these names. None when the mailbox has no such folder.
        """
        try:
            return _parse_folder(
                self._get(
                    f"{self._user_url(mailbox_id)}/mailFolders/{name}",
                    {"$select": FOLDER_SELECT},
                )
            )
        except OutlookGraphError as e:
            if e.status == 404:
                return None
            raise

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_child_folders(
        self,
        *,
        mailbox_id: str,
        parent_folder_id: str | None = None,
        page_size: int = FOLDERS_PAGE_SIZE,
        next_link: str | None = None,
    ) -> OutlookFolderPage:
        """One page of folders directly under a folder, or under the root when None."""
        params = None
        url = next_link
        if url is None:
            if parent_folder_id is None:
                url = f"{self._user_url(mailbox_id)}/mailFolders"
            else:
                url = f"{self._user_url(mailbox_id)}/mailFolders/{parent_folder_id}/childFolders"
            params = {"$select": FOLDER_SELECT, "$top": str(page_size)}
        data = self._get(url, params)
        return OutlookFolderPage(
            folders=[_parse_folder(raw) for raw in data.get("value", [])],
            next_link=data.get("@odata.nextLink"),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def fetch_folder_delta_page(
        self,
        *,
        mailbox_id: str,
        folder_id: str,
        received_after: datetime | None = None,
        page_size: int = MESSAGES_PAGE_SIZE,
        next_link: str | None = None,
    ) -> OutlookDeltaPage:
        """One page of messages created in a folder, newest ``received_after``.

        Graph encodes the query into its state tokens, so the filter and page
        size are sent only on the first request and ``next_link`` carries them
        afterwards. Delta still reports removals and read-state changes
        whatever ``changeType`` says, so callers must ignore those entries.
        """
        params = None
        url = next_link
        if url is None:
            url = f"{self._user_url(mailbox_id)}/mailFolders/{folder_id}/messages/delta"
            params = {"changeType": "created", "$select": CHANGE_SELECT}
            if received_after is not None:
                params["$filter"] = (
                    f"receivedDateTime ge {_graph_timestamp(received_after)}"
                )
        data = self._get(url, params, {"Prefer": f"odata.maxpagesize={page_size}"})
        return OutlookDeltaPage(
            changes=[_parse_change(raw) for raw in data.get("value", [])],
            next_link=data.get("@odata.nextLink"),
            delta_link=data.get("@odata.deltaLink"),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "Needs a conversation id from a live delta page. The mail-read "
            "check proves the same Mail.Read grant on the same mailbox."
        ),
    )
    def list_conversation_messages(
        self, *, mailbox_id: str, conversation_id: str, limit: int = 500
    ) -> list[OutlookMessage]:
        """Up to ``limit`` messages of one conversation in one mailbox, bodies as text.

        Graph rejects ordering by a property that is not in the filter, so
        messages come back unordered and callers sort them.
        """
        params: dict[str, str] | None = {
            "$filter": f"conversationId eq '{_odata_quote(conversation_id)}'",
            "$select": MESSAGE_SELECT,
            "$top": str(min(limit, MESSAGES_PAGE_SIZE)),
        }
        headers = {"Prefer": TEXT_BODY_PREFERENCE}
        url: str | None = f"{self._user_url(mailbox_id)}/messages"
        messages: list[OutlookMessage] = []
        while url is not None and len(messages) < limit:
            data = self._get(url, params, headers)
            params = None
            messages.extend(_parse_message(raw) for raw in data.get("value", []))
            url = data.get("@odata.nextLink")
        return messages[:limit]
