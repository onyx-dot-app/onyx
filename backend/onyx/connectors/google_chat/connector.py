"""Indexes the named spaces of a Google Workspace organization.

A service account with domain-wide delegation lists every named space and its
members through the primary admin's Chat admin privilege, then reads each
space's messages as one of its members. The messages of one space on one UTC
day make one document, with each thread's replies under the thread's first
message of that day.
"""

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta, timezone
from itertools import islice
from typing import Any

from google.auth.exceptions import RefreshError
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.errors import HttpError

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.google_chat.models import ChatSpace, ChatUser
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.google_utils import (
    execute_paginated_retrieval,
    execute_single_retrieval,
    is_access_denied,
)
from onyx.connectors.google_utils.resources import (
    AdminService,
    GoogleChatService,
    GoogleService,
    get_google_service,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
    GOOGLE_SCOPES,
    MISSING_SCOPES_ERROR_STR,
    GoogleCredentialKind,
    google_credential_kind,
)
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.db.enums import HierarchyNodeType
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PAGE_SIZE = 1000
# spaces.search returns only named spaces (spaceType SPACE) with admin access.
_SPACE_QUERY = 'customer = "customers/my_customer" AND spaceType = "SPACE"'
_SPACE_SEARCH_FIELDS = "nextPageToken,results(space(name,displayName,spaceUri))"
_MEMBER_FIELDS = "nextPageToken,memberships(state,member(name))"
# Admin access lists human members only, and requires this filter.
_HUMAN_MEMBER_FILTER = 'member.type = "HUMAN"'
_MESSAGE_FIELDS = (
    "nextPageToken,messages(name,createTime,lastUpdateTime,text,threadReply,"
    "thread(name),sender(name,displayName,type),attachment(contentName))"
)
# The slim pass skips the messages the main pass skips, so it reads their text.
_SLIM_MESSAGE_FIELDS = "nextPageToken,messages(createTime,text,attachment(contentName))"
_USER_FIELDS = "primaryEmail,name(fullName),suspended"
# Members tried as the reader of a space before the space counts as unreadable.
_MAX_READER_CANDIDATES = 5
# Bounds the memory one day of a busy space holds.
_MAX_MESSAGES_PER_DOCUMENT = 10_000
_REPLY_INDENT = "    "


class SpaceUnreadableError(Exception):
    """Google refused every member tried as the reader of a space."""


class GoogleChatCheckpoint(ConnectorCheckpoint):
    # Spaces still to index, listed on the first run. Each run indexes one.
    spaces: list[ChatSpace] | None = None


def _utc(timestamp: SecondsSinceUnixEpoch) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _created_at(message: dict[str, Any]) -> datetime:
    return _parse_time(message["createTime"])


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def document_id(space: ChatSpace, day: date) -> str:
    return f"google_chat:{space.name}:{day.isoformat()}"


def _message_filter(start: datetime | None, end: datetime | None) -> str | None:
    # The filter compares createTime with > and < only.
    clauses: list[str] = []
    if start is not None:
        clauses.append(f'createTime > "{_rfc3339(start - timedelta(seconds=1))}"')
    if end is not None:
        clauses.append(f'createTime < "{_rfc3339(end)}"')
    return " AND ".join(clauses) or None


def _message_text(message: dict[str, Any]) -> str:
    parts: list[str] = []
    if text := (message.get("text") or "").strip():
        parts.append(text)
    parts.extend(
        f"[Attachment: {name}]"
        for attachment in message.get("attachment") or []
        if (name := attachment.get("contentName"))
    )
    return " ".join(parts)


def _refresh_error_reason(error: RefreshError) -> str:
    # google-auth puts Google's message first and the raw response second.
    if error.args and isinstance(error.args[0], str):
        return error.args[0]
    return str(error)


class GoogleChatConnector(
    CheckpointedConnector[GoogleChatCheckpoint],
    SlimConnector,
):
    slim_listing_honors_indexing_start = True

    def __init__(self, spaces: list[str] | None = None) -> None:
        self.spaces: list[str] = spaces or []
        self._creds: ServiceAccountCredentials | None = None
        self._primary_admin_email: str | None = None
        self._admin_chat: GoogleChatService | None = None
        self._directory: AdminService | None = None
        # Directory users by Chat user resource name (users/{id}); None when
        # the directory does not hold the user.
        self._users: dict[str, ChatUser | None] = {}

    @property
    def creds(self) -> ServiceAccountCredentials:
        if self._creds is None:
            raise ConnectorMissingCredentialError("Google Chat")
        return self._creds

    @property
    def primary_admin_email(self) -> str:
        if self._primary_admin_email is None:
            raise ConnectorMissingCredentialError("Google Chat")
        return self._primary_admin_email

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        if google_credential_kind(credentials) != GoogleCredentialKind.SERVICE_ACCOUNT:
            raise CredentialInvalidError(
                "Google Chat needs a service account key with domain-wide delegation."
            )
        try:
            creds, _ = get_google_creds(credentials, DocumentSource.GOOGLE_CHAT)
        except RefreshError as e:
            raise CredentialInvalidError(
                f"Google rejected the service account key: {_refresh_error_reason(e)}"
            ) from e
        if not isinstance(creds, ServiceAccountCredentials):
            raise CredentialInvalidError(
                "Google Chat needs a service account key with domain-wide delegation."
            )
        self._creds = creds
        self._primary_admin_email = credentials[DB_CREDENTIALS_PRIMARY_ADMIN_KEY]
        return None

    def _admin_chat_service(self) -> GoogleChatService:
        if self._admin_chat is None:
            self._admin_chat = get_google_service(
                GoogleService.CHAT, self.creds, self.primary_admin_email
            )
        return self._admin_chat

    def _directory_service(self) -> AdminService:
        if self._directory is None:
            self._directory = get_google_service(
                GoogleService.ADMIN, self.creds, self.primary_admin_email
            )
        return self._directory

    def _in_scope(self, space: ChatSpace) -> bool:
        if not self.spaces:
            return True
        wanted: set[str] = {
            entry.lower().removeprefix("spaces/") for entry in self.spaces
        }
        return bool(wanted & {space.space_id.lower(), space.display_name.lower()})

    def _list_spaces(self, active_after: datetime | None) -> list[ChatSpace]:
        query: str = _SPACE_QUERY
        if active_after is not None:
            query += f' AND lastActiveTime > "{_rfc3339(active_after)}"'
        spaces: list[ChatSpace] = []
        for result in execute_paginated_retrieval(
            retrieval_function=self._admin_chat_service().spaces().search,  # ty: ignore[unresolved-attribute]
            list_key="results",
            fields=_SPACE_SEARCH_FIELDS,
            query=query,
            useAdminAccess=True,
            pageSize=_PAGE_SIZE,
        ):
            space: ChatSpace = ChatSpace.from_api(result["space"])
            if self._in_scope(space):
                spaces.append(space)
        return spaces

    def _user(self, user_name: str) -> ChatUser | None:
        """The directory user behind a Chat user resource name (users/{id})."""
        if user_name not in self._users:
            # Only a missing user is skipped: a refused directory read would
            # leave every space without a reader, which a prune reads as every
            # document deleted.
            try:
                found: dict[str, Any] = next(
                    execute_single_retrieval(
                        retrieval_function=self._directory_service().users().get,  # ty: ignore[unresolved-attribute]
                        userKey=user_name.removeprefix("users/"),
                        fields=_USER_FIELDS,
                    )
                )
            except HttpError as e:
                if e.resp.status != 404:
                    raise
                found = {}
            self._users[user_name] = (
                ChatUser.from_directory(found) if found.get("primaryEmail") else None
            )
        return self._users[user_name]

    def _reader_candidates(self, space: ChatSpace) -> Iterator[str]:
        """Emails of the space's joined members who are active directory users."""
        for membership in execute_paginated_retrieval(
            retrieval_function=self._admin_chat_service().spaces().members().list,  # ty: ignore[unresolved-attribute]
            list_key="memberships",
            fields=_MEMBER_FIELDS,
            parent=space.name,
            filter=_HUMAN_MEMBER_FILTER,
            useAdminAccess=True,
            pageSize=_PAGE_SIZE,
        ):
            if membership.get("state") != "JOINED":
                continue
            user_name: str = (membership.get("member") or {}).get("name", "")
            user: ChatUser | None = self._user(user_name) if user_name else None
            if user is not None and not user.suspended:
                yield user.email

    def _messages(
        self,
        space: ChatSpace,
        start: datetime | None,
        end: datetime | None,
        fields: str,
    ) -> Iterator[dict[str, Any]]:
        """The space's messages created in the window, oldest first, read as
        the first member Google lets read them. Yields nothing for a space
        without an active member, and raises SpaceUnreadableError when Google
        refuses every member tried."""
        refused: list[str] = []
        for reader in islice(self._reader_candidates(space), _MAX_READER_CANDIDATES):
            chat: GoogleChatService = get_google_service(
                GoogleService.CHAT, self.creds, reader
            )
            pages: Iterator[dict[str, Any]] = execute_paginated_retrieval(
                retrieval_function=chat.spaces().messages().list,  # ty: ignore[unresolved-attribute]
                list_key="messages",
                fields=fields,
                parent=space.name,
                pageSize=_PAGE_SIZE,
                # The client drops a None parameter.
                filter=_message_filter(start, end),
            )
            try:
                first: dict[str, Any] | None = next(pages, None)
            except HttpError as e:
                if not is_access_denied(e):
                    raise
                logger.warning(
                    "Google Chat refused %s as the reader of %s: %s",
                    reader,
                    space.name,
                    e,
                )
                refused.append(reader)
                continue
            if first is not None:
                yield first
                yield from pages
            return
        if refused:
            raise SpaceUnreadableError(
                f"Google Chat refused every member tried as the reader of "
                f"{space.display_name} ({space.name}): {', '.join(refused)}"
            )
        logger.info("Skipping %s: it has no active member to read it as", space.name)

    def _sender(self, message: dict[str, Any]) -> BasicExpertInfo:
        """Google returns a sender's display name only while they share the
        space with the reader, so former members are named from the directory."""
        sender: dict[str, Any] = message.get("sender") or {}
        user: ChatUser | None = None
        if sender.get("type") == "HUMAN" and sender.get("name"):
            user = self._user(sender["name"])
        if user is None:
            return BasicExpertInfo(display_name=sender.get("displayName"))
        return BasicExpertInfo(
            display_name=sender.get("displayName") or user.full_name,
            email=user.email,
        )

    def _to_document(
        self, space: ChatSpace, day: date, messages: list[dict[str, Any]]
    ) -> Document:
        threads: dict[str, list[dict[str, Any]]] = {}
        for message in messages:
            thread_name: str = (message.get("thread") or {}).get("name") or message[
                "name"
            ]
            threads.setdefault(thread_name, []).append(message)

        owners: dict[str, BasicExpertInfo] = {}
        thread_blocks: list[str] = []
        for thread_messages in threads.values():
            lines: list[str] = []
            for message in thread_messages:
                sender: BasicExpertInfo = self._sender(message)
                if sender.display_name or sender.email:
                    owners.setdefault(sender.get_semantic_name(), sender)
                indent: str = _REPLY_INDENT if message.get("threadReply") else ""
                lines.append(
                    f"{indent}{sender.get_semantic_name()}: {_message_text(message)}"
                )
            thread_blocks.append("\n".join(lines))

        updated_at: datetime = max(
            _parse_time(message.get("lastUpdateTime") or message["createTime"])
            for message in messages
        )
        semantic_identifier: str = f"{space.display_name} - {day.isoformat()}"
        return Document(
            id=document_id(space, day),
            source=DocumentSource.GOOGLE_CHAT,
            semantic_identifier=semantic_identifier,
            title=semantic_identifier,
            sections=[TextSection(link=space.uri, text="\n\n".join(thread_blocks))],
            metadata={"space": space.display_name},
            doc_created_at=_created_at(messages[0]),
            doc_updated_at=updated_at,
            primary_owners=list(owners.values()),
            parent_hierarchy_raw_node_id=space.name,
        )

    def _space_documents(
        self, space: ChatSpace, start: datetime | None, end: datetime
    ) -> Iterator[Document]:
        """One document per day with a message created in the window. A day
        always holds all of its messages up to `end`, so the window opens at
        the start of the day `start` falls on."""
        window_start: datetime | None = _day_start(start.date()) if start else None
        day: date | None = None
        day_messages: list[dict[str, Any]] = []
        day_touched: bool = False
        for message in self._messages(space, window_start, end, _MESSAGE_FIELDS):
            created_at: datetime = _created_at(message)
            if window_start is not None and created_at < window_start:
                continue
            if created_at.date() != day:
                if day is not None and day_messages and day_touched:
                    yield self._to_document(space, day, day_messages)
                day, day_messages, day_touched = created_at.date(), [], False
            if not _message_text(message):
                continue
            day_touched = day_touched or start is None or created_at >= start
            if len(day_messages) < _MAX_MESSAGES_PER_DOCUMENT:
                day_messages.append(message)
                if len(day_messages) == _MAX_MESSAGES_PER_DOCUMENT:
                    logger.warning(
                        "%s reached %d messages on %s; later messages of that "
                        "day are not indexed",
                        space.name,
                        _MAX_MESSAGES_PER_DOCUMENT,
                        day,
                    )
        if day is not None and day_messages and day_touched:
            yield self._to_document(space, day, day_messages)

    @staticmethod
    def _space_node(space: ChatSpace) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=space.name,
            raw_parent_id=None,
            display_name=space.display_name,
            link=space.uri,
            node_type=HierarchyNodeType.SPACE,
        )

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GoogleChatCheckpoint,
    ) -> CheckpointOutput[GoogleChatCheckpoint]:
        checkpoint = checkpoint.model_copy(deep=True)
        # A first run starts at the epoch, which needs no time filter.
        window_start: datetime | None = _utc(start) if start > 0 else None
        if checkpoint.spaces is None:
            checkpoint.spaces = self._list_spaces(active_after=window_start)
        if checkpoint.spaces:
            space: ChatSpace = checkpoint.spaces.pop(0)
            yield self._space_node(space)
            try:
                yield from self._space_documents(space, window_start, _utc(end))
            except SpaceUnreadableError as e:
                yield ConnectorFailure(
                    failed_entity=EntityFailure(
                        entity_id=space.name,
                        missed_time_range=(window_start or _utc(0), _utc(end)),
                    ),
                    failure_message=str(e),
                    exception=e,
                )
        checkpoint.has_more = bool(checkpoint.spaces)
        return checkpoint

    def build_dummy_checkpoint(self) -> GoogleChatCheckpoint:
        return GoogleChatCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> GoogleChatCheckpoint:
        return GoogleChatCheckpoint.model_validate_json(checkpoint_json)

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        window_start: datetime | None = _utc(start) if start else None
        window_end: datetime | None = _utc(end) if end else None
        for space in self._list_spaces(active_after=window_start):
            # A partial listing would read as deleted documents, so stopping
            # and an unreadable space both raise.
            if callback is not None and callback.should_stop():
                raise RuntimeError("Google Chat slim retrieval: stop signal detected")
            days: set[date] = {
                _created_at(message).date()
                for message in self._messages(
                    space, window_start, window_end, _SLIM_MESSAGE_FIELDS
                )
                if (window_start is None or _created_at(message) >= window_start)
                and _message_text(message)
            }
            yield [self._space_node(space)] + [
                SlimDocument(
                    id=document_id(space, day), parent_hierarchy_raw_node_id=space.name
                )
                for day in sorted(days)
            ]

    def validate_connector_settings(self) -> None:
        try:
            spaces: list[ChatSpace] = self._list_spaces(active_after=None)
            self._directory_service().users().get(  # ty: ignore[unresolved-attribute]
                userKey=self.primary_admin_email, fields=_USER_FIELDS
            ).execute()
        except RefreshError as e:
            if MISSING_SCOPES_ERROR_STR in str(e) or "unauthorized_client" in str(e):
                raise InsufficientPermissionsError(
                    "The service account is not authorized for the Google Chat "
                    "scopes. In the Google Admin console, grant domain-wide "
                    f"delegation for: {', '.join(GOOGLE_SCOPES[DocumentSource.GOOGLE_CHAT])}"
                ) from e
            raise CredentialInvalidError(
                "Google rejected the service account credentials: "
                f"{_refresh_error_reason(e)}"
            ) from e
        except HttpError as e:
            if e.resp.status == 401:
                raise CredentialInvalidError(
                    "Google rejected the service account credentials."
                ) from e
            if e.resp.status == 403:
                raise InsufficientPermissionsError(
                    f"{self.primary_admin_email} cannot list Google Chat spaces. "
                    "The primary admin must be a Google Workspace administrator "
                    "with the Chat and spaces conversations privilege."
                ) from e
            raise
        if self.spaces and not spaces:
            raise ConnectorValidationError(
                f"No Google Chat spaces match {', '.join(self.spaces)}. Use each "
                "space's exact name or its id from the space URL."
            )
