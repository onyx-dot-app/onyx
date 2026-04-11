"""Google Chat connector for Onyx.

Indexes messages from Google Chat spaces using the Google Chat API
(part of Google Workspace).
"""

import json
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any

from google.oauth2 import service_account  # type: ignore
from googleapiclient.discovery import build  # type: ignore

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.access.models import ExternalAccess
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_GOOGLE_CHAT_DOC_ID_PREFIX = "GOOGLE_CHAT_"
_SCOPES = ["https://www.googleapis.com/auth/chat.spaces.readonly",
           "https://www.googleapis.com/auth/chat.messages.readonly",
           "https://www.googleapis.com/auth/chat.memberships.readonly"]


def _build_chat_service(
    credentials_json: dict[str, Any],
    delegated_user_email: str | None = None,
) -> Any:
    """Build and return a Google Chat API service client."""
    creds = service_account.Credentials.from_service_account_info(
        credentials_json,
        scopes=_SCOPES,
    )
    if delegated_user_email:
        creds = creds.with_subject(delegated_user_email)
    return build("chat", "v1", credentials=creds, cache_discovery=False)


def _get_message_link(space_name: str, message_name: str) -> str:
    """Construct a deep link to a Google Chat message."""
    # space_name looks like "spaces/AAAA..."
    space_id = space_name.replace("spaces/", "")
    msg_id = message_name.replace(f"{space_name}/messages/", "")
    return f"https://chat.google.com/room/{space_id}/{msg_id}"


def _convert_message_to_document(
    message: dict[str, Any],
    space_name: str,
    space_display_name: str,
    external_access: ExternalAccess | None = None,
) -> Document | None:
    """Convert a single Google Chat message dict to a Document."""
    text = message.get("text", "")
    if not text or not text.strip():
        return None

    sender = message.get("sender", {}).get("displayName", "Unknown")
    msg_name = message.get("name", "")
    created_time_str = message.get("createTime", "")

    doc_updated_at = None
    if created_time_str:
        try:
            doc_updated_at = datetime.fromisoformat(
                created_time_str.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            logger.error(f"Failed to parse createTime for message: {created_time_str}")

    snippet = text[:50].rstrip() + "..." if len(text) > 50 else text
    semantic_identifier = f"{sender} in {space_display_name}: {snippet}"

    link = _get_message_link(space_name, msg_name)

    metadata: dict[str, str | list[str]] = {
        "Space": space_display_name,
        "Sender": sender,
    }

    thread_name = message.get("thread", {}).get("name", "")
    if thread_name:
        metadata["Thread"] = thread_name

    return Document(
        id=f"{_GOOGLE_CHAT_DOC_ID_PREFIX}{msg_name}",
        source=DocumentSource.GOOGLE_CHAT,
        semantic_identifier=semantic_identifier,
        doc_updated_at=doc_updated_at,
        title="",
        sections=[TextSection(text=text, link=link)],
        metadata=metadata,
        external_access=external_access,
    )


def _fetch_spaces(
    service: Any,
    space_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fetch all spaces, optionally filtering by space name."""
    spaces: list[dict[str, Any]] = []
    page_token = None

    while True:
        response = (
            service.spaces()
            .list(pageSize=100, pageToken=page_token)
            .execute()
        )
        for space in response.get("spaces", []):
            if space_names:
                if space.get("displayName") in space_names or space.get("name") in space_names:
                    spaces.append(space)
            else:
                spaces.append(space)

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    logger.info(f"Found {len(spaces)} Google Chat spaces")
    return spaces


def _fetch_messages_from_space(
    service: Any,
    space_name: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Generator[dict[str, Any], None, None]:
    """Fetch messages from a single space with optional time filter."""
    page_token = None
    filter_str = ""

    # Build the time-based filter
    if start and end:
        filter_str = (
            f'createTime > "{start.strftime("%Y-%m-%dT%H:%M:%SZ")}" AND '
            f'createTime < "{end.strftime("%Y-%m-%dT%H:%M:%SZ")}"'
        )
    elif start:
        filter_str = f'createTime > "{start.strftime("%Y-%m-%dT%H:%M:%SZ")}"'
    elif end:
        filter_str = f'createTime < "{end.strftime("%Y-%m-%dT%H:%M:%SZ")}"'

    while True:
        request_kwargs: dict[str, Any] = {
            "parent": space_name,
            "pageSize": 100,
        }
        if page_token:
            request_kwargs["pageToken"] = page_token
        if filter_str:
            request_kwargs["filter"] = filter_str

        response = service.spaces().messages().list(**request_kwargs).execute()

        for message in response.get("messages", []):
            yield message

        page_token = response.get("nextPageToken")
        if not page_token:
            break


def _fetch_space_members(
    service: Any,
    space_name: str,
) -> set[str]:
    """Fetch all member emails from a Google Chat space."""
    members: set[str] = set()
    page_token = None

    try:
        while True:
            response = (
                service.spaces()
                .members()
                .list(parent=space_name, pageSize=1000, pageToken=page_token)
                .execute()
            )
            for membership in response.get("memberships", []):
                member = membership.get("member", {})
                if member.get("type") == "HUMAN":
                    email = member.get("email")
                    if email:
                        members.add(email)

            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except Exception as e:
        logger.error(f"Failed to fetch memberships for space {space_name}: {e}")

    return members


class GoogleChatConnector(PollConnector, LoadConnector, SlimConnectorWithPermSync):
    """Connector that indexes messages from Google Chat spaces."""

    def __init__(
        self,
        space_names: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ):
        self.space_names = space_names or []
        self.batch_size = batch_size
        self._credentials_json: dict[str, Any] | None = None
        self._delegated_user_email: str | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # The credential can be passed either as a JSON string or a dict
        creds = credentials.get("google_chat_service_account_key")
        if isinstance(creds, str):
            self._credentials_json = json.loads(creds)
        elif isinstance(creds, dict):
            self._credentials_json = creds
        else:
            raise ConnectorMissingCredentialError("google_chat_service_account_key")

        self._delegated_user_email = credentials.get("google_chat_delegated_user_email")
        return None

    def _get_service(self) -> Any:
        if self._credentials_json is None:
            raise ConnectorMissingCredentialError("Google Chat")
        return _build_chat_service(
            self._credentials_json,
            self._delegated_user_email,
        )

    def _fetch_documents(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        include_permissions: bool = False,
    ) -> GenerateDocumentsOutput:
        service = self._get_service()
        spaces = _fetch_spaces(
            service,
            self.space_names if self.space_names else None,
        )

        doc_batch: list[Document] = []

        for space in spaces:
            space_name = space["name"]
            space_display_name = space.get("displayName", space_name)

            logger.info(
                f"Fetching messages from space: {space_display_name} ({space_name})"
            )

            external_access = None
            if include_permissions:
                members = _fetch_space_members(service, space_name)
                external_access = ExternalAccess(
                    external_user_emails=members,
                    external_user_group_ids=set(),
                    is_public=False,
                )

            for message in _fetch_messages_from_space(
                service, space_name, start, end
            ):
                doc = _convert_message_to_document(
                    message, space_name, space_display_name, external_access
                )
                if doc:
                    doc_batch.append(doc)
                    if len(doc_batch) >= self.batch_size:
                        yield doc_batch
                        doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_documents(include_permissions=True)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        return self._fetch_documents(
            start=datetime.fromtimestamp(start, tz=timezone.utc),
            end=datetime.fromtimestamp(end, tz=timezone.utc),
            include_permissions=True,
        )

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Return 'slim' docs (IDs only) for indexing."""
        service = self._get_service()
        spaces = _fetch_spaces(
            service,
            self.space_names if self.space_names else None,
        )

        slim_doc_batch: list[SlimDocument] = []

        for space in spaces:
            space_name = space["name"]

            for message in _fetch_messages_from_space(
                service,
                space_name,
                start=datetime.fromtimestamp(start, tz=timezone.utc) if start else None,
                end=datetime.fromtimestamp(end, tz=timezone.utc) if end else None,
            ):
                msg_name = message.get("name", "")
                if msg_name:
                    slim_doc_batch.append(
                        SlimDocument(
                            id=f"{_GOOGLE_CHAT_DOC_ID_PREFIX}{msg_name}",
                        )
                    )

                    if len(slim_doc_batch) >= self.batch_size:
                        yield slim_doc_batch
                        slim_doc_batch = []

            if callback and callback.should_stop():
                raise RuntimeError("retrieve_all_slim_docs: Stop signal detected")

        if slim_doc_batch:
            yield slim_doc_batch

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Return 'slim' docs (IDs + permissions) for synchronization."""
        service = self._get_service()
        spaces = _fetch_spaces(
            service,
            self.space_names if self.space_names else None,
        )

        slim_doc_batch: list[SlimDocument] = []

        for space in spaces:
            space_name = space["name"]
            members = _fetch_space_members(service, space_name)
            external_access = ExternalAccess(
                external_user_emails=members,
                external_user_group_ids=set(),
                is_public=False,
            )

            for message in _fetch_messages_from_space(
                service,
                space_name,
                start=datetime.fromtimestamp(start, tz=timezone.utc) if start else None,
                end=datetime.fromtimestamp(end, tz=timezone.utc) if end else None,
            ):
                msg_name = message.get("name", "")
                if msg_name:
                    slim_doc_batch.append(
                        SlimDocument(
                            id=f"{_GOOGLE_CHAT_DOC_ID_PREFIX}{msg_name}",
                            external_access=external_access,
                        )
                    )

                    if len(slim_doc_batch) >= self.batch_size:
                        yield slim_doc_batch
                        slim_doc_batch = []

            if callback and callback.should_stop():
                raise RuntimeError("retrieve_all_slim_docs_perm_sync: Stop signal detected")

        if slim_doc_batch:
            yield slim_doc_batch
