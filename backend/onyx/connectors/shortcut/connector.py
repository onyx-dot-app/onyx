from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import (
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    TextSection,
)
from onyx.connectors.shortcut.client import ShortcutClient
from onyx.connectors.shortcut.models import ShortcutEpic, ShortcutStory
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _epic_to_document(epic: ShortcutEpic) -> Document:
    text_parts = [f"Shortcut Epic #{epic.id}: {epic.name}"]
    if epic.state:
        text_parts.append(f"State: {epic.state}")
    if epic.description:
        text_parts.append(f"\nDescription:\n{epic.description}")

    created_at_dt = None
    if epic.created_at:
        try:
            created_at_dt = time_str_to_utc(epic.created_at)
        except Exception:
            pass

    updated_at_dt = None
    if epic.updated_at:
        try:
            updated_at_dt = time_str_to_utc(epic.updated_at)
        except Exception:
            pass

    metadata: dict[str, Any] = {
        "epic_id": str(epic.id),
    }
    if epic.state:
        metadata["state"] = epic.state
    if epic.app_url:
        metadata["url"] = epic.app_url

    return Document(
        id=f"shortcut_epic_{epic.id}",
        source=DocumentSource.SHORTCUT,
        semantic_identifier=epic.name,
        title=epic.name,
        metadata=metadata,
        doc_updated_at=updated_at_dt,
        doc_created_at=created_at_dt,
        sections=[TextSection(text="\n".join(text_parts))],
    )


def _story_to_document(story: ShortcutStory) -> Document:
    header_parts = [f"Shortcut Story #{story.id}: {story.name}"]
    if story.story_type:
        header_parts.append(f"Type: {story.story_type}")
    if story.completed:
        header_parts.append("Status: Completed")
    if story.labels:
        header_parts.append(f"Labels: {', '.join(story.labels)}")
    if story.description:
        header_parts.append(f"\nDescription:\n{story.description}")

    sections: list[TextSection] = [TextSection(text="\n".join(header_parts))]

    if story.tasks:
        tasks_lines = ["Tasks:"]
        for task in story.tasks:
            status_str = "[x]" if task.complete else "[ ]"
            tasks_lines.append(f"- {status_str} {task.description}")
        sections.append(TextSection(text="\n".join(tasks_lines)))

    if story.comments:
        comments_lines = ["Comments:"]
        for comment in story.comments:
            comments_lines.append(f"- {comment.text}")
        sections.append(TextSection(text="\n".join(comments_lines)))

    created_at_dt = None
    if story.created_at:
        try:
            created_at_dt = time_str_to_utc(story.created_at)
        except Exception:
            pass

    updated_at_dt = None
    if story.updated_at:
        try:
            updated_at_dt = time_str_to_utc(story.updated_at)
        except Exception:
            pass

    metadata: dict[str, Any] = {
        "story_id": str(story.id),
        "story_type": story.story_type,
        "completed": str(story.completed),
    }
    if story.epic_id:
        metadata["epic_id"] = str(story.epic_id)
    if story.project_id:
        metadata["project_id"] = str(story.project_id)
    if story.labels:
        metadata["labels"] = story.labels
    if story.app_url:
        metadata["url"] = story.app_url

    return Document(
        id=f"shortcut_story_{story.id}",
        source=DocumentSource.SHORTCUT,
        semantic_identifier=story.name,
        title=story.name,
        metadata=metadata,
        doc_updated_at=updated_at_dt,
        doc_created_at=created_at_dt,
        sections=sections,
    )


class ShortcutConnector(LoadConnector, PollConnector, CredentialsConnector):
    def __init__(
        self,
        project_ids: list[int] | None = None,
        epic_ids: list[int] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.project_ids = project_ids
        self.epic_ids = epic_ids
        self.batch_size = batch_size
        self.client: ShortcutClient | None = None
        self._credentials_provider: CredentialsProviderInterface | None = None

    def _get_client(self) -> ShortcutClient:
        if self._credentials_provider:
            credentials = self._credentials_provider.get_credentials()
            self.load_credentials(credentials)
        if not self.client:
            raise ConnectorMissingCredentialError("Shortcut credentials not loaded.")
        return self.client

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        token = credentials.get("shortcut_api_token") or credentials.get("api_token")
        if not token:
            raise ConnectorMissingCredentialError("Shortcut API token is required.")
        self.client = ShortcutClient(api_token=str(token))
        return None

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._credentials_provider = credentials_provider
        credentials = credentials_provider.get_credentials()
        self.load_credentials(credentials)

    def validate_connector_settings(self) -> None:
        client = self._get_client()
        client.validate_credentials()

    def load_from_state(self) -> GenerateDocumentsOutput:
        client = self._get_client()
        batch: list[Document] = []

        # 1. Epics
        epics = client.get_epics()
        for epic in epics:
            if self.epic_ids and epic.id not in self.epic_ids:
                continue
            doc = _epic_to_document(epic)
            batch.append(doc)
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        # 2. Stories
        for story in client.paginate_stories(
            project_ids=self.project_ids,
            epic_ids=self.epic_ids,
            batch_size=self.batch_size,
        ):
            doc = _story_to_document(story)
            batch.append(doc)
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
        client = self._get_client()
        batch: list[Document] = []

        # 1. Epics
        epics = client.get_epics()
        for epic in epics:
            if self.epic_ids and epic.id not in self.epic_ids:
                continue
            ts = None
            if epic.updated_at:
                try:
                    ts = time_str_to_utc(epic.updated_at).timestamp()
                except Exception:
                    pass
            elif epic.created_at:
                try:
                    ts = time_str_to_utc(epic.created_at).timestamp()
                except Exception:
                    pass

            if ts is not None and not (start <= ts <= end):
                continue

            doc = _epic_to_document(epic)
            batch.append(doc)
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        # 2. Stories
        for story in client.paginate_stories(
            project_ids=self.project_ids,
            epic_ids=self.epic_ids,
            batch_size=self.batch_size,
        ):
            ts = None
            if story.updated_at:
                try:
                    ts = time_str_to_utc(story.updated_at).timestamp()
                except Exception:
                    pass
            elif story.created_at:
                try:
                    ts = time_str_to_utc(story.created_at).timestamp()
                except Exception:
                    pass

            if ts is not None and not (start <= ts <= end):
                continue

            doc = _story_to_document(story)
            batch.append(doc)
            if len(batch) >= self.batch_size:
                yield batch
                batch = []

        if batch:
            yield batch
