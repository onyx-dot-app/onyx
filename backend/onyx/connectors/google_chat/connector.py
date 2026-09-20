import json
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

from google.auth.exceptions import GoogleAuthError
from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
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


def _parse_timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
                link=f"https://chat.google.com/room/{space_name.removeprefix('spaces/')}",
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
        space_names: list[str] | None = None,
        start_date: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.space_names = {
            name.strip().casefold() for name in space_names or [] if name.strip()
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
                raw_service_account = json.loads(raw_service_account)
            except json.JSONDecodeError as error:
                raise CredentialInvalidError(
                    "Google Chat service account key must be valid JSON."
                ) from error

        if not isinstance(raw_service_account, dict):
            raise CredentialInvalidError(
                "Google Chat service account key must be a JSON object."
            )

        self._service_account_info = raw_service_account
        return None

    def _chat_service(self) -> Resource:
        if self._service_account_info is None:
            raise ConnectorMissingCredentialError("Google Chat")
        try:
            credentials = service_account.Credentials.from_service_account_info(
                self._service_account_info,
                scopes=_GOOGLE_CHAT_SCOPES,
            )
            return build("chat", "v1", credentials=credentials, cache_discovery=False)
        except (ValueError, TypeError) as error:
            raise CredentialInvalidError(
                f"Invalid Google Chat service account key: {error}"
            ) from error

    def validate_connector_settings(self) -> None:
        try:
            chat_service = self._chat_service()
            space = next(self._selected_spaces(chat_service), None)
            if space is None:
                raise ConnectorValidationError(
                    "No accessible Google Chat spaces matched the connector settings. "
                    "Add the Chat app to a space or update the space filter."
                )

            space_name = space.get("name")
            if not isinstance(space_name, str) or not space_name:
                raise ConnectorValidationError(
                    "Google Chat returned a space without a resource name."
                )

            chat_service.spaces().messages().list(  # ty: ignore[unresolved-attribute]
                parent=space_name,
                pageSize=1,
                pageToken=None,
                filter=None,
                orderBy="ASC",
            ).execute()
        except HttpError as error:
            status_code = error.resp.status if error.resp else None
            if status_code == 401:
                raise CredentialInvalidError(
                    "Google Chat rejected the service account credentials."
                ) from error
            if status_code == 403:
                raise InsufficientPermissionsError(
                    "The Google Chat app cannot read messages. Confirm that a "
                    "Workspace administrator approved the Chat app message-read scope."
                ) from error
            raise ConnectorValidationError(
                f"Unable to validate Google Chat access (status={status_code}): {error}"
            ) from error
        except GoogleAuthError as error:
            raise CredentialInvalidError(
                f"Google Chat rejected the service account credentials: {error}"
            ) from error

    def _selected_spaces(self, chat_service: Resource) -> Iterator[dict[str, Any]]:
        page_token: str | None = None
        while True:
            response = (
                chat_service.spaces()  # ty: ignore[unresolved-attribute]
                .list(pageSize=_GOOGLE_CHAT_PAGE_SIZE, pageToken=page_token)
                .execute()
            )
            for space in response.get("spaces", []):
                resource_name = str(space.get("name") or "").casefold()
                display_name = str(space.get("displayName") or "").casefold()
                if self.space_names and self.space_names.isdisjoint(
                    (resource_name, display_name)
                ):
                    continue
                yield space

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def _messages(
        self,
        chat_service: Resource,
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
                chat_service.spaces()  # ty: ignore[unresolved-attribute]
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
