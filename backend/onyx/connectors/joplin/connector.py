from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any

import requests
from retry import retry

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import (
    rl_requests,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

_JOPLIN_API_TIMEOUT = 30
_JOPLIN_PAGE_LIMIT = 100


class JoplinConnector(LoadConnector, PollConnector):
    """
    Connector for Joplin note-taking application.

    Supports:
    - Initial bulk loading of all notes via load_from_state()
    - Incremental sync via poll_source() using Joplin's Events API
    - Folder hierarchy and tag metadata preservation
    """

    def __init__(
        self,
        base_url: str = "http://localhost:41184",
        include_folders: list[str] | None = None,
        include_tags: list[str] | None = None,
        exclude_folders: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.base_url = base_url.rstrip("/")

        # Helper to process comma-separated strings into lists
        def normalize_filter_list(filter_input: list[str] | None) -> list[str]:
            if not filter_input:
                return []

            result = []
            for item in filter_input:
                # If item contains commas, split it
                if isinstance(item, str) and "," in item:
                    result.extend([s.strip() for s in item.split(",") if s.strip()])
                elif isinstance(item, str) and item.strip():
                    result.append(item.strip())

            return result

        self.include_folders = normalize_filter_list(include_folders)
        self.include_tags = normalize_filter_list(include_tags)
        self.exclude_folders = normalize_filter_list(exclude_folders)
        self.exclude_tags = normalize_filter_list(exclude_tags)
        self.batch_size = batch_size

        # Debug logging
        logger.info("Joplin Connector initialized with filters:")
        logger.info(f"  include_folders: {self.include_folders}")
        logger.info(f"  include_tags: {self.include_tags}")
        logger.info(f"  exclude_folders: {self.exclude_folders}")
        logger.info(f"  exclude_tags: {self.exclude_tags}")
        self.api_token: str | None = None
        self.headers: dict[str, str] = {}
        self._folder_cache: dict[str, dict[str, Any]] = {}

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.api_token = credentials.get("joplin_api_token")
        if not self.api_token:
            raise ConnectorValidationError("Missing joplin_api_token in credentials")

        self.headers = {
            "Content-Type": "application/json",
        }
        return None

    def _add_token_to_params(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Add API token to request parameters."""
        if params is None:
            params = {}
        params["token"] = self.api_token
        return params

    def validate_connector_settings(self) -> None:
        if not self.api_token:
            raise ConnectorValidationError("API token not loaded")

        try:
            response = rl_requests.get(
                f"{self.base_url}/notes",
                headers=self.headers,
                params=self._add_token_to_params({"limit": 1}),
                timeout=_JOPLIN_API_TIMEOUT,
            )

            if response.status_code == 401 or response.status_code == 403:
                raise CredentialExpiredError("Invalid or expired Joplin API token")

            response.raise_for_status()

        except requests.exceptions.ConnectionError:
            raise ConnectorValidationError(
                f"Unable to connect to Joplin API at {self.base_url}. "
                "Ensure Joplin is running and Web Clipper service is enabled."
            )
        except requests.exceptions.Timeout:
            raise ConnectorValidationError(f"Connection to Joplin API at {self.base_url} timed out")
        except requests.exceptions.RequestException as e:
            raise ConnectorValidationError(f"Error connecting to Joplin API: {str(e)}")

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_note(self, note_id: str) -> dict[str, Any] | None:
        logger.debug(f"Fetching note with ID '{note_id}'")

        fields = [
            "id",
            "title",
            "body",
            "parent_id",
            "created_time",
            "updated_time",
            "is_todo",
            "source_url",
            "user_created_time",
            "user_updated_time",
        ]

        response = rl_requests.get(
            f"{self.base_url}/notes/{note_id}",
            headers=self.headers,
            params=self._add_token_to_params({"fields": ",".join(fields)}),
            timeout=_JOPLIN_API_TIMEOUT,
        )

        if response.status_code == 404:
            logger.warning(f"Note {note_id} not found (may have been deleted)")
            return None

        response.raise_for_status()
        return response.json()

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_folder(self, folder_id: str) -> dict[str, Any] | None:
        if folder_id in self._folder_cache:
            return self._folder_cache[folder_id]

        logger.debug(f"Fetching folder with ID '{folder_id}'")

        response = rl_requests.get(
            f"{self.base_url}/folders/{folder_id}",
            headers=self.headers,
            params=self._add_token_to_params({"fields": "id,title,parent_id"}),
            timeout=_JOPLIN_API_TIMEOUT,
        )

        if response.status_code == 404:
            logger.warning(f"Folder {folder_id} not found")
            return None

        response.raise_for_status()
        folder = response.json()
        self._folder_cache[folder_id] = folder
        return folder

    def _build_folder_path(self, folder_id: str) -> str:
        path_parts: list[str] = []
        current_id: str | None = folder_id
        seen_ids: set[str] = set()

        while current_id:
            if current_id in seen_ids:
                logger.warning(f"Circular folder reference detected at {current_id}")
                break

            seen_ids.add(current_id)
            folder = self._fetch_folder(current_id)

            if not folder:
                break

            title = folder.get("title", "Unknown")
            if isinstance(title, str):
                path_parts.insert(0, title)

            current_id = folder.get("parent_id")

        return " > ".join(path_parts) if path_parts else "Root"

    def _should_filter_note(self, folder_path: str, tags: list[str]) -> bool:
        """
        Check if note should be filtered based on include/exclude rules.
        Returns True if note should be skipped, False if it should be indexed.
        """
        # Check exclude filters first (they take precedence)
        if self.exclude_folders:
            if folder_path in self.exclude_folders:
                logger.debug(f"Note excluded - folder '{folder_path}' in exclude list")
                return True

        if self.exclude_tags:
            if any(tag in self.exclude_tags for tag in tags):
                logger.debug("Note excluded - has excluded tag")
                return True

        # Then check include filters (if specified)
        if self.include_folders:
            if folder_path not in self.include_folders:
                logger.debug(f"Note filtered - folder '{folder_path}' not in include list")
                return True

        if self.include_tags:
            if not any(tag in self.include_tags for tag in tags):
                logger.debug("Note filtered - no matching tags")
                return True

        return False

    @retry(tries=3, delay=1, backoff=2)
    def _fetch_note_tags(self, note_id: str) -> list[str]:
        logger.debug(f"Fetching tags for note '{note_id}'")

        response = rl_requests.get(
            f"{self.base_url}/notes/{note_id}/tags",
            headers=self.headers,
            params=self._add_token_to_params(),
            timeout=_JOPLIN_API_TIMEOUT,
        )

        if response.status_code == 404:
            return []

        response.raise_for_status()
        tags_data = response.json()

        if isinstance(tags_data, dict) and "items" in tags_data:
            return [tag.get("title", "") for tag in tags_data["items"] if tag.get("title")]

        return []

    def _ms_to_seconds(self, timestamp_ms: int | None) -> float | None:
        if timestamp_ms is None:
            return None
        return timestamp_ms / 1000.0

    def _convert_to_document(self, note: dict[str, Any], folder_path: str, tags: list[str]) -> Document:
        note_id = note["id"]
        title = note.get("title", "Untitled")
        body = note.get("body", "")

        updated_time_ms = note.get("updated_time") or note.get("user_updated_time")
        updated_time = self._ms_to_seconds(updated_time_ms)

        created_time_ms = note.get("created_time") or note.get("user_created_time")
        self._ms_to_seconds(created_time_ms)

        metadata: dict[str, str | list[str]] = {
            "folder_path": folder_path,
        }

        if tags:
            metadata["tags"] = tags

        if note.get("is_todo"):
            metadata["is_todo"] = "true"

        if note.get("source_url"):
            metadata["source_url"] = note["source_url"]

        sections: list[TextSection | ImageSection] = [
            TextSection(
                link=f"joplin://x-callback-url/openNote?id={note_id}",
                text=body,
            )
        ]

        return Document(
            id=note_id,
            sections=sections,
            source=DocumentSource.JOPLIN,
            semantic_identifier=title,
            doc_updated_at=datetime.fromtimestamp(updated_time, tz=timezone.utc) if updated_time else None,
            metadata=metadata,
        )

    def _paginate_notes(
        self,
        page: int = 1,
        order_by: str = "updated_time",
        order_dir: str = "ASC",
    ) -> Generator[dict[str, Any], None, None]:
        has_more = True
        current_page = page

        fields = [
            "id",
            "title",
            "body",
            "parent_id",
            "created_time",
            "updated_time",
            "is_todo",
            "source_url",
            "user_created_time",
            "user_updated_time",
        ]

        while has_more:
            logger.info(f"Fetching notes page {current_page}")

            response = rl_requests.get(
                f"{self.base_url}/notes",
                headers=self.headers,
                params=self._add_token_to_params(
                    {
                        "page": current_page,
                        "limit": _JOPLIN_PAGE_LIMIT,
                        "fields": ",".join(fields),
                        "order_by": order_by,
                        "order_dir": order_dir,
                    }
                ),
                timeout=_JOPLIN_API_TIMEOUT,
            )

            response.raise_for_status()
            data = response.json()

            items = data.get("items", [])
            has_more = data.get("has_more", False)

            for note in items:
                yield note

            current_page += 1

    def load_from_state(self) -> GenerateDocumentsOutput:
        logger.info("Starting Joplin connector bulk load")

        doc_batch: list[Document] = []

        for note in self._paginate_notes():
            try:
                folder_path = "Root"
                parent_id = note.get("parent_id")

                if parent_id:
                    folder_path = self._build_folder_path(parent_id)

                tags = self._fetch_note_tags(note["id"])

                # Use centralized filtering logic
                if self._should_filter_note(folder_path, tags):
                    continue

                document = self._convert_to_document(note, folder_path, tags)
                doc_batch.append(document)

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

            except Exception as e:
                logger.error(f"Error processing note {note.get('id', 'unknown')}: {e}")
                continue

        if doc_batch:
            yield doc_batch

        logger.info("Completed Joplin connector bulk load")

    @retry(tries=3, delay=1, backoff=2)
    def _get_events(self, cursor: str | None = None) -> dict[str, Any]:
        logger.debug(f"Fetching events with cursor: {cursor}")

        params = {}
        if cursor:
            params["cursor"] = cursor

        response = rl_requests.get(
            f"{self.base_url}/events",
            headers=self.headers,
            params=self._add_token_to_params(params),
            timeout=_JOPLIN_API_TIMEOUT,
        )

        response.raise_for_status()
        return response.json()

    def poll_source(self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch) -> GenerateDocumentsOutput:
        logger.info(f"Starting Joplin incremental sync from {start} to {end}")

        # If start time is close to epoch (first sync), use load_from_state instead
        # Events API may not return historical events going back to 1970
        YEAR_1990_TIMESTAMP = 631152000  # Jan 1, 1990
        if start < YEAR_1990_TIMESTAMP:
            logger.info("Start time is before 1990, using full load instead of incremental sync")
            yield from self.load_from_state()
            return

        start_ms = int(start * 1000)
        end_ms = int(end * 1000)

        doc_batch: list[Document] = []
        cursor: str | None = None

        while True:
            try:
                events_data = self._get_events(cursor)
                items = events_data.get("items", [])
                cursor = events_data.get("cursor")

                if not items:
                    break

                for event in items:
                    event_time = event.get("created_time", 0)

                    if event_time < start_ms:
                        continue

                    if event_time > end_ms:
                        continue

                    item_type = event.get("item_type")
                    if item_type != 1:
                        continue

                    event_type = event.get("type")
                    note_id = event.get("item_id")

                    if not note_id:
                        continue

                    if event_type == 3:
                        logger.info(f"Note {note_id} was deleted")
                        continue

                    try:
                        note = self._fetch_note(note_id)

                        if not note:
                            continue

                        folder_path = "Root"
                        parent_id = note.get("parent_id")

                        if parent_id:
                            folder_path = self._build_folder_path(parent_id)

                        tags = self._fetch_note_tags(note_id)

                        # Use centralized filtering logic
                        if self._should_filter_note(folder_path, tags):
                            continue

                        document = self._convert_to_document(note, folder_path, tags)
                        doc_batch.append(document)

                        if len(doc_batch) >= self.batch_size:
                            yield doc_batch
                            doc_batch = []

                    except Exception as e:
                        logger.error(f"Error processing note {note_id}: {e}")
                        continue

                if not events_data.get("has_more", False):
                    break

            except Exception as e:
                logger.error(f"Error fetching events: {e}")
                break

        if doc_batch:
            yield doc_batch

        logger.info("Completed Joplin incremental sync")
