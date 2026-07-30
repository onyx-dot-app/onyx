from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, Protocol, cast

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import CredentialInvalidError
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    TextSection,
)

_GOOGLE_CHAT_SCOPES = (
    "https://www.googleapis.com/auth/chat.bot",
    "https://www.googleapis.com/auth/chat.app.messages.readonly",
)
_GOOGLE_CHAT_DOC_ID_PREFIX = "GOOGLE_CHAT_"
_GOOGLE_CHAT_PAGE_SIZE = 1000
_SNIPPET_LENGTH = 80


class _ExecutableRequest(Protocol):
    def execute(self) -> dict[str, Any]: ...


class _GoogleChatMessagesResource(Protocol):
    def list(
        self,
        *,
        parent: str,
        pageSize: int,
        pageToken: str | None,
        filter: str | None,
        orderBy: str,
    ) -> _ExecutableRequest: ...


class _GoogleChatSpacesResource(Protocol):
    def list(
        self,
        *,
        pageSize: int,
        pageToken: str | None = None,
    ) -> _ExecutableRequest: ...

    def messages(self) -> _GoogleChatMessagesResource: ...


class _GoogleChatService(Protocol):
    def spaces(self) -> _GoogleChatSpacesResource: ...


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _message_link(space_name: str) -> str:
    space_id = space_name.removeprefix("spaces/")
    return f"https://chat.google.com/room/{space_id}"


def _message_to_document(message: dict[str, Any], space: dict[str, Any]) -> Document:
    message_name = str(message["name"])
    space_name = str(space["name"])
    space_display_name = str(space.get("displayName") or space_name)
    sender = message.get("sender") or {}
    sender_name = str(sender.get("displayName") or "Google Chat user")
    text = str(message.get("text") or message.get("formattedText") or "").strip()
    snippet = text[:_SNIPPET_LENGTH].rstrip()
    if len(text) > _SNIPPET_LENGTH:
        snippet += "..."

    metadata: dict[str, str | list[str]] = {
        "Space": space_display_name,
        "Sender": sender_name,
    }
    thread_name = str((message.get("thread") or {}).get("name") or "")
    if thread_name:
        metadata["Thread"] = thread_name

    return Document(
        id=f"{_GOOGLE_CHAT_DOC_ID_PREFIX}{message_name}",
        source=DocumentSource.GOOGLE_CHAT,
        semantic_identifier=f"{sender_name} in {space_display_name}: {snippet}",
        title=space_display_name,
        sections=[
            TextSection(
                text=text,
                link=_message_link(space_name),
            )
        ],
        metadata=metadata,
        doc_created_at=_parse_timestamp(message.get("createTime")),
        doc_updated_at=_parse_timestamp(
            message.get("lastUpdateTime") or message.get("createTime")
        ),
        primary_owners=[BasicExpertInfo(display_name=sender_name)],
    )


class GoogleChatConnector(PollConnector, LoadConnector):
    def __init__(
        self,
        space_names: list[str] = [],
        start_date: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.space_names = {
            name.strip().casefold() for name in space_names if name.strip()
        }
        self.start_date = (
            datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if start_date
            else None
        )
        self.batch_size = batch_size
        self._service_account_info: dict[str, Any] | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raw_service_account = credentials.get("google_chat_service_account_secret")
        if isinstance(raw_service_account, str):
            try:
                service_account_info = json.loads(raw_service_account)
            except json.JSONDecodeError as error:
                raise CredentialInvalidError(
                    "Google Chat service account key must be valid JSON."
                ) from error
        elif isinstance(raw_service_account, dict):
            service_account_info = raw_service_account
        else:
            raise CredentialInvalidError(
                "Google Chat service account key must be a JSON object."
            )

        self._service_account_info = service_account_info
        return None

    def _chat_service(self) -> _GoogleChatService:
        if self._service_account_info is None:
            raise ConnectorMissingCredentialError("Google Chat")
        try:
            credentials = service_account.Credentials.from_service_account_info(
                self._service_account_info,
                scopes=_GOOGLE_CHAT_SCOPES,
            )
            return cast(
                _GoogleChatService,
                build(
                    "chat",
                    "v1",
                    credentials=credentials,
                    cache_discovery=False,
                ),
            )
        except (ValueError, TypeError) as error:
            raise CredentialInvalidError(
                f"Invalid Google Chat service account key: {error}"
            ) from error

    def validate_connector_settings(self) -> None:
        try:
            self._chat_service().spaces().list(pageSize=1).execute()
        except HttpError as error:
            raise CredentialInvalidError(
                f"Unable to access Google Chat spaces: {error}"
            ) from error

    def _selected_spaces(
        self, chat_service: _GoogleChatService
    ) -> Iterator[dict[str, Any]]:
        page_token: str | None = None
        while True:
            response = (
                chat_service.spaces()
                .list(pageSize=_GOOGLE_CHAT_PAGE_SIZE, pageToken=page_token)
                .execute()
            )
            for space in response.get("spaces", []):
                resource_name = str(space.get("name") or "").casefold()
                display_name = str(space.get("displayName") or "").casefold()
                if self.space_names and not {
                    resource_name,
                    display_name,
                }.intersection(self.space_names):
                    continue
                yield space

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def _messages(
        self,
        chat_service: _GoogleChatService,
        space: dict[str, Any],
        start: datetime | None,
        end: datetime | None,
    ) -> Iterator[dict[str, Any]]:
        filters: list[str] = []
        if start:
            filters.append(f'createTime > "{_format_timestamp(start)}"')
        if end:
            filters.append(f'createTime < "{_format_timestamp(end)}"')

        page_token: str | None = None
        while True:
            response = (
                chat_service.spaces()
                .messages()
                .list(
                    parent=space["name"],
                    pageSize=_GOOGLE_CHAT_PAGE_SIZE,
                    pageToken=page_token,
                    filter=" AND ".join(filters) or None,
                    orderBy="ASC",
                )
                .execute()
            )
            for message in response.get("messages", []):
                if message.get("text") or message.get("formattedText"):
                    yield message

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def _generate_documents(
        self,
        start: datetime | None,
        end: datetime | None,
    ) -> GenerateDocumentsOutput:
        effective_start = (
            max(start, self.start_date)
            if start is not None and self.start_date is not None
            else start or self.start_date
        )
        chat_service = self._chat_service()
        batch: list[Document | HierarchyNode] = []

        for space in self._selected_spaces(chat_service):
            for message in self._messages(
                chat_service,
                space,
                effective_start,
                end,
            ):
                batch.append(_message_to_document(message, space))
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []

        if batch:
            yield batch

    def poll_source(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> GenerateDocumentsOutput:
        return self._generate_documents(
            datetime.fromtimestamp(start, tz=timezone.utc),
            datetime.fromtimestamp(end, tz=timezone.utc),
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._generate_documents(None, None)
