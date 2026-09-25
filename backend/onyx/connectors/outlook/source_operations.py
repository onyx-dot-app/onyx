"""Outlook source-operations gateway: every Graph mail and calendar call lives here.

Indexing and the capability checks compose these operations, and nothing else
under ``onyx/connectors/outlook`` talks to Graph. Transport, retry and token
acquisition come from the shared Microsoft package. Each operation returns the
plain models in ``models.py`` so a Graph schema change surfaces in one file.

Application permissions this gateway needs: ``Mail.Read`` for folders and
messages, ``Calendars.Read`` for the calendar view, ``User.Read.All`` to
enumerate and resolve mailboxes.
"""

from datetime import datetime, timezone
from typing import Any

import bs4
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.microsoft_utils.drive_items import (
    download_graph_url_with_cap,
    parse_graph_datetime,
)
from onyx.connectors.microsoft_utils.entra import (
    ENTRA_PAGE_SIZE,
    EntraClient,
    EntraUser,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient
from onyx.connectors.microsoft_utils.graph_env import (
    DEFAULT_AUTHORITY_HOST,
    DEFAULT_GRAPH_API_HOST,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    MicrosoftGraphError as OutlookGraphError,
)
from onyx.connectors.microsoft_utils.graph_errors import (
    microsoft_error_from_exception,
)
from onyx.connectors.microsoft_utils.graph_gateway import (
    MicrosoftGraphAuthConfig,
    MicrosoftGraphGateway,
    build_graph_user_url,
)
from onyx.connectors.outlook.models import (
    OutlookAttachment,
    OutlookDeltaPage,
    OutlookEvent,
    OutlookEventPage,
    OutlookFolder,
    OutlookFolderPage,
    OutlookMailbox,
    OutlookMailboxPage,
    OutlookMessage,
    OutlookMessageChange,
    OutlookMessagePage,
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
CREDENTIAL_PRIVATE_KEY = "outlook_private_key"
CREDENTIAL_CERTIFICATE_PASSWORD = "outlook_certificate_password"
# Missing means client secret, the shared package's default.
CREDENTIAL_AUTH_METHOD = "authentication_method"

CONFIG_AUTHORITY_HOST = "authority_host"
CONFIG_GRAPH_API_HOST = "graph_api_host"

# Message pages stay small because each row carries a full body.
FOLDERS_PAGE_SIZE = 250
MESSAGES_PAGE_SIZE = 100
# The calendar view delta takes no $select, so every row carries a full body.
EVENTS_PAGE_SIZE = 50

MAILBOX_SELECT = "id,mail,userPrincipalName,displayName"
FOLDER_SELECT = "id,displayName,parentFolderId,childFolderCount,isHidden"
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
        "isDraft",
        "hasAttachments",
    )
)
# Attachment records without contentBytes, which the listing would otherwise
# inline for every file attachment.
ATTACHMENT_SELECT = "id,name,size,isInline"
FILE_ATTACHMENT_TYPE = "#microsoft.graph.fileAttachment"

# Graph renders bodies as HTML unless asked for text, and text spares a parse.
TEXT_BODY_PREFERENCE = 'outlook.body-content-type="text"'
# Graph defaults event times to UTC. Pinned so the naive dateTime never
# needs a Windows zone table.
UTC_TIMEZONE_PREFERENCE = 'outlook.timezone="UTC"'
EVENT_PREFERENCES = f"{TEXT_BODY_PREFERENCE}, {UTC_TIMEZONE_PREFERENCE}"
SEARCH_FOLDER_TYPE = "#microsoft.graph.mailSearchFolder"

# Graph only orders by a property that leads the filter, so conversation reads
# carry this always-true bound to be allowed ``$orderby=receivedDateTime desc``.
EPOCH_TIMESTAMP = "1970-01-01T00:00:00Z"

# Graph may answer a collection request with an empty page and a next link.
# Lookups that want a single item follow at most this many of them.
EMPTY_PAGE_FOLLOW_LIMIT = 20


def _odata_quote(value: str) -> str:
    """Escape a value for an OData string literal. Only the quote is special."""
    return value.replace("'", "''")


def _recipient(raw: dict[str, Any] | None) -> OutlookRecipient | None:
    email = (raw or {}).get("emailAddress") or {}
    address = email.get("address")
    if not address:
        return None
    return OutlookRecipient(address=address, name=email.get("name"))


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


def _mailbox_from_entra(user: EntraUser) -> OutlookMailbox | None:
    address = user.mail or user.user_principal_name
    if not address:
        return None
    return OutlookMailbox(
        id=user.id,
        address=address,
        display_name=user.display_name,
    )


def _parse_folder(raw: dict[str, Any]) -> OutlookFolder:
    return OutlookFolder(
        id=raw["id"],
        display_name=raw.get("displayName") or "",
        parent_folder_id=raw.get("parentFolderId"),
        child_folder_count=raw.get("childFolderCount") or 0,
        is_search_folder=raw.get("@odata.type") == SEARCH_FOLDER_TYPE,
        is_hidden=bool(raw.get("isHidden")),
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
        is_draft=bool(raw.get("isDraft")),
        has_attachments=bool(raw.get("hasAttachments")),
    )


_RECURRENCE_UNITS = {
    "daily": "day",
    "weekly": "week",
    "absoluteMonthly": "month",
    "relativeMonthly": "month",
    "absoluteYearly": "year",
    "relativeYearly": "year",
}
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _recurrence_summary(raw: dict[str, Any] | None) -> str | None:
    """The pattern and range of a series in words, so a search for the weekly
    standup or the first-Monday review finds the series document."""
    if not raw:
        return None
    pattern = raw.get("pattern") or {}
    range_ = raw.get("range") or {}
    kind = pattern.get("type") or ""
    interval = pattern.get("interval") or 1
    unit = _RECURRENCE_UNITS.get(kind, "time")
    parts = [f"every {unit}" if interval == 1 else f"every {interval} {unit}s"]
    days = ", ".join(pattern.get("daysOfWeek") or [])
    # Relative patterns pick a weekday by its place in the month ("the last
    # friday"), absolute ones a day number.
    if days and kind.startswith("relative"):
        parts.append(f"on the {pattern.get('index') or 'first'} {days}")
    elif days:
        parts.append(f"on {days}")
    if kind.startswith("absolute") and pattern.get("dayOfMonth"):
        parts.append(f"on day {pattern['dayOfMonth']}")
    month = pattern.get("month") or 0
    if kind.endswith("Yearly") and 1 <= month <= len(_MONTH_NAMES):
        parts.append(f"of {_MONTH_NAMES[month - 1]}")
    if range_.get("startDate"):
        parts.append(f"from {range_['startDate']}")
    if range_.get("type") == "endDate" and range_.get("endDate"):
        parts.append(f"until {range_['endDate']}")
    elif range_.get("type") == "numbered" and range_.get("numberOfOccurrences"):
        parts.append(f"for {range_['numberOfOccurrences']} occurrences")
    return " ".join(parts)


def _parse_event(raw: dict[str, Any]) -> OutlookEvent:
    # Event times arrive as a naive clock in the zone every request asks for,
    # UTC, and the shared parser reads a naive value as UTC.
    return OutlookEvent(
        id=raw["id"],
        subject=raw.get("subject"),
        body_text=_body_text(raw.get("body")),
        body_present="body" in raw,
        start_at=parse_graph_datetime((raw.get("start") or {}).get("dateTime")),
        end_at=parse_graph_datetime((raw.get("end") or {}).get("dateTime")),
        time_zone=raw.get("originalStartTimeZone") or None,
        is_all_day=bool(raw.get("isAllDay")),
        is_cancelled=bool(raw.get("isCancelled")),
        sensitivity=raw.get("sensitivity") or "normal",
        event_type=raw.get("type") or "singleInstance",
        series_master_id=raw.get("seriesMasterId"),
        organizer=_recipient(raw.get("organizer")),
        attendees=_recipients(raw.get("attendees")),
        location=(raw.get("location") or {}).get("displayName") or None,
        web_link=raw.get("webLink"),
        created_at=parse_graph_datetime(raw.get("createdDateTime")),
        last_modified_at=parse_graph_datetime(raw.get("lastModifiedDateTime")),
        recurrence=_recurrence_summary(raw.get("recurrence")),
    )


def _parse_attachment(raw: dict[str, Any]) -> OutlookAttachment:
    return OutlookAttachment(
        id=raw["id"],
        name=raw.get("name") or "",
        size=raw.get("size") or 0,
        is_inline=bool(raw.get("isInline")),
        is_file=raw.get("@odata.type") == FILE_ATTACHMENT_TYPE,
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
    _graph_gateway: MicrosoftGraphGateway | None = None

    def _config_value(self, key: str, default: str) -> str:
        config = self.connector_specific_config or {}
        value = config.get(key)
        return (value or default).rstrip("/")

    def _graph_host(self) -> str:
        return self._config_value(CONFIG_GRAPH_API_HOST, DEFAULT_GRAPH_API_HOST)

    def _graph_base(self) -> str:
        return self._gateway().graph_api_base

    def _gateway(self) -> MicrosoftGraphGateway:
        if self._graph_gateway is not None:
            return self._graph_gateway
        credentials = self.credentials_provider.get_credentials()
        self._graph_gateway = MicrosoftGraphGateway(
            auth_config=MicrosoftGraphAuthConfig(
                client_id=credentials.get(CREDENTIAL_CLIENT_ID),
                directory_id=credentials.get(CREDENTIAL_DIRECTORY_ID),
                authority_host=self._config_value(
                    CONFIG_AUTHORITY_HOST, DEFAULT_AUTHORITY_HOST
                ),
                auth_method=credentials.get(CREDENTIAL_AUTH_METHOD),
                client_secret=credentials.get(CREDENTIAL_CLIENT_SECRET),
                private_key_b64=credentials.get(CREDENTIAL_PRIVATE_KEY),
                certificate_password=credentials.get(CREDENTIAL_CERTIFICATE_PASSWORD),
            ),
            graph_api_host=self._graph_host(),
            graph_api_version=GRAPH_API_VERSION,
        )
        return self._graph_gateway

    def _token_response(self) -> dict[str, Any]:
        return self._gateway().token_response()

    def _access_token(self) -> str:
        return self._gateway().access_token()

    def _client(self) -> GraphApiClient:
        return self._gateway().client

    def _get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._gateway().get_json(url, params, headers)

    def _entra(self) -> EntraClient:
        return EntraClient(self._gateway().get_json, self._graph_base())

    def _first_item(
        self,
        url: str,
        params: dict[str, str] | None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """The first entry of a collection, following empty continuation pages.

        None means the collection is empty. Running out of budget with pages
        left is a failure, never absence.
        """
        next_url = url
        for _ in range(EMPTY_PAGE_FOLLOW_LIMIT):
            data = self._get(next_url, params, headers)
            params = None
            items = data.get("value", [])
            if items:
                return items[0]
            next_url = data.get("@odata.nextLink")
            if next_url is None:
                return None
        raise OutlookGraphError(
            None,
            "EmptyPages",
            f"{EMPTY_PAGE_FOLLOW_LIMIT} empty pages with more to follow: {url}",
        )

    def _user_url(self, mailbox_id: str) -> str:
        return build_graph_user_url(self._graph_base(), mailbox_id)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def check_token(self) -> OutlookTokenInfo:
        """Acquire an app-only token: proves client id, directory id and credential agree."""
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
        self, *, page_size: int = ENTRA_PAGE_SIZE, next_link: str | None = None
    ) -> OutlookMailboxPage:
        """One page of enabled users with a mail address, the candidates in
        every-mailbox mode.

        Needs ``User.Read.All``. Whether a user actually has a mailbox is only
        known once :meth:`probe_mailbox` is called for it.
        """
        page = self._entra().list_users_page(
            next_link=next_link,
            page_size=page_size,
            enabled_only=True,
        )
        mailboxes = [
            mailbox
            for user in page.users
            if user.mail
            if (mailbox := _mailbox_from_entra(user)) is not None
        ]
        return OutlookMailboxPage(
            mailboxes=mailboxes,
            next_link=page.next_link,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "Runs only for a configured address. The configured-mailboxes check "
            "and the mail-read check call it for every listed address, but the "
            "coverage spy carries no connector config, so neither reaches it."
        ),
    )
    def resolve_mailbox(self, *, address: str) -> OutlookMailbox | None:
        """Find the user behind an address: by UPN or object id, then by primary SMTP."""
        params = {"$select": MAILBOX_SELECT}
        try:
            return _mailbox_from_entra(self._entra().get_user(address))
        except OutlookGraphError as e:
            if e.status != 404:
                raise
        params["$filter"] = f"mail eq '{_odata_quote(address)}'"
        user = self._first_item(f"{self._graph_base()}/users", params)
        return _parse_mailbox(user) if user else None

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def probe_mailbox(self, *, mailbox_id: str) -> OutlookFolder:
        """Read the Inbox record.

        The cheapest call that proves the mailbox exists, is licensed and sits
        inside the app's Exchange scope. 403 means out of scope, 404 no mailbox
        behind the user, 423 a locked or archived mailbox.
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
        """One page of folders directly under a folder, or under the root when None.

        Hidden folders are asked for too, since Graph omits them by default and
        an excluded subtree's hidden descendants must be known to be excluded.
        """
        params = None
        url = next_link
        if url is None:
            if parent_folder_id is None:
                url = f"{self._user_url(mailbox_id)}/mailFolders"
            else:
                url = f"{self._user_url(mailbox_id)}/mailFolders/{parent_folder_id}/childFolders"
            params = {
                "$select": FOLDER_SELECT,
                "$top": str(page_size),
                "includeHiddenFolders": "true",
            }
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
        """One page of messages created in a folder at or after ``received_after``.

        Graph encodes query parameters into its state tokens, so ``changeType``,
        ``$select`` and ``$filter`` go on the first request only and
        ``next_link`` carries them afterwards. The page-size header is not a
        query parameter, so it goes with every request. Delta still reports
        removals and read-state changes whatever ``changeType`` says, so
        callers must filter those entries.
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
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "The calendar check reads one page of it, but only when the "
            "connector config turns calendars on, which the coverage harness's "
            "empty config never does."
        ),
    )
    def fetch_calendar_delta_page(
        self,
        *,
        mailbox_id: str,
        window_start: datetime,
        window_end: datetime,
        page_size: int = EVENTS_PAGE_SIZE,
        next_link: str | None = None,
    ) -> OutlookEventPage:
        """One page of the events in the window, recurring series expanded into
        their occurrences. The window rides in the state tokens, so it goes on
        the first request only. Removed rows are dropped: pruning owns deletions,
        and Graph also files events outside the window under @removed."""
        params = None
        url = next_link
        if url is None:
            url = f"{self._user_url(mailbox_id)}/calendarView/delta"
            params = {
                "startDateTime": _graph_timestamp(window_start),
                "endDateTime": _graph_timestamp(window_end),
            }
        data = self._get(
            url,
            params,
            {"Prefer": f"odata.maxpagesize={page_size}, {EVENT_PREFERENCES}"},
        )
        return OutlookEventPage(
            events=[
                _parse_event(raw)
                for raw in data.get("value", [])
                if "@removed" not in raw
            ],
            next_link=data.get("@odata.nextLink"),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "Needs a series master id, which only a recurring event provides. "
            "The calendar check reads the same calendar under the same grant."
        ),
    )
    def get_event(self, *, mailbox_id: str, event_id: str) -> OutlookEvent:
        """One event by id, read for the master of a recurring series."""
        return _parse_event(
            self._get(
                f"{self._user_url(mailbox_id)}/events/{event_id}",
                None,
                {"Prefer": EVENT_PREFERENCES},
            )
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_message_attachments(
        self, *, mailbox_id: str, message_id: str, limit: int
    ) -> list[OutlookAttachment]:
        """The first ``limit`` attachment records of one message, without bytes.

        One page only, so a message carrying thousands of attachments costs
        one call whatever the caller does with the records.
        """
        url = f"{self._user_url(mailbox_id)}/messages/{message_id}/attachments"
        data = self._get(url, {"$select": ATTACHMENT_SELECT, "$top": str(limit)})
        return [_parse_attachment(raw) for raw in data.get("value", [])[:limit]]

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "Listing a message's attachments needs the same Mail.Read grant, "
            "and the mail-read check does that for its sample message."
        ),
    )
    def download_attachment(
        self, *, mailbox_id: str, message_id: str, attachment_id: str, cap: int
    ) -> bytes:
        """The bytes of a file attachment, streamed with a cap.

        Raises ``SizeCapExceeded`` past ``cap`` so a huge attachment never sits
        in memory whole.
        """
        url = (
            f"{self._user_url(mailbox_id)}/messages/{message_id}"
            f"/attachments/{attachment_id}/$value"
        )
        try:
            return download_graph_url_with_cap(
                access_token=self._access_token(),
                url=url,
                cap=cap,
                description=f"outlook attachment {attachment_id}",
            )
        except requests.RequestException as e:
            raise microsoft_error_from_exception(e) from e

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "The calendar check reads one event body with it, but only when the "
            "connector config turns calendars on, which the coverage harness's "
            "empty config never does."
        ),
    )
    def read_any_event(self, *, mailbox_id: str) -> OutlookEvent | None:
        """One event from the mailbox's calendar with its body, or None when
        the calendar holds none.

        Calendars.ReadBasic.All lists events but withholds bodies, so this is
        the call that tells it apart from Calendars.Read.
        """
        raw = self._first_item(
            f"{self._user_url(mailbox_id)}/events",
            {"$select": "id,subject,body", "$top": "1"},
            {"Prefer": EVENT_PREFERENCES},
        )
        return _parse_event(raw) if raw else None

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def read_any_message(self, *, mailbox_id: str) -> OutlookMessage | None:
        """One message from anywhere in the mailbox with the fields indexing
        reads, or None when the mailbox holds none.

        Mail.ReadBasic.All answers every folder and delta call and refuses only
        bodies, so this is the call that tells the two grants apart.
        """
        raw = self._first_item(
            f"{self._user_url(mailbox_id)}/messages",
            {"$select": MESSAGE_SELECT, "$top": "1"},
            {"Prefer": TEXT_BODY_PREFERENCE},
        )
        return _parse_message(raw) if raw else None

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "Needs a conversation id, which only the delta walk produces. The "
            "mail-read check proves body access with read_any_message, the same "
            "fields and body preference on the mailbox-wide route."
        ),
    )
    def fetch_conversation_messages_page(
        self,
        *,
        mailbox_id: str,
        conversation_id: str,
        page_size: int = MESSAGES_PAGE_SIZE,
        next_link: str | None = None,
    ) -> OutlookMessagePage:
        """One page of a conversation's messages in one mailbox, newest first,
        bodies as text.

        Ordering needs the ordered property to lead the filter, hence the
        always-true ``receivedDateTime`` bound ahead of the conversation id.
        The body preference is a header, so it goes with every request.
        """
        params = None
        url = next_link
        if url is None:
            url = f"{self._user_url(mailbox_id)}/messages"
            params = {
                "$filter": (
                    f"receivedDateTime ge {EPOCH_TIMESTAMP} and "
                    f"conversationId eq '{_odata_quote(conversation_id)}'"
                ),
                "$orderby": "receivedDateTime desc",
                "$select": MESSAGE_SELECT,
                "$top": str(page_size),
            }
        data = self._get(url, params, {"Prefer": TEXT_BODY_PREFERENCE})
        return OutlookMessagePage(
            messages=[_parse_message(raw) for raw in data.get("value", [])],
            next_link=data.get("@odata.nextLink"),
        )
