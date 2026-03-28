from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, List, cast
import time

import requests

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

_GRANOLA_BASE_URL = "https://public-api.granola.ai/v1"
_GRANOLA_ID_PREFIX = "GRANOLA_"
_GRANOLA_PAGE_SIZE = 30  # Max page size per Granola docs
_MIN_REQUEST_INTERVAL = 0.25  # seconds; stay under 5 req/sec sustained
_REQUEST_TIMEOUT_SECONDS = 30  # prevent workers from hanging on stalled upstream


def _parse_iso_datetime(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    # Granola returns RFC 3339 with Z suffix, e.g. 2026-01-27T15:30:00Z
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(dt_str).astimezone(timezone.utc)
    except Exception:
        logger.warning(f"Failed to parse Granola datetime: {dt_str}")
        return None


class GranolaConnector(PollConnector, LoadConnector):
    """Connector for Granola (AI meeting notes).

    Uses the public Granola REST API:
      - GET /notes to list notes with cursor-based pagination
      - GET /notes/{id}?include=transcript for full details and transcript
    """

    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        self.batch_size = batch_size
        self.api_key: str | None = None
        self._session = requests.Session()
        self._last_request_time: float = 0.0

    # ---------------------------------------------------------------------
    # Credentials
    # ---------------------------------------------------------------------
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        api_key = credentials.get("granola_api_key")

        if not isinstance(api_key, str):
            raise ConnectorMissingCredentialError(
                "The Granola API key must be a string"
            )

        self.api_key = api_key

        return None

    # ---------------------------------------------------------------------
    # HTTP helpers
    # ---------------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        if self.api_key is None:
            raise ConnectorMissingCredentialError("Granola")

        headers = kwargs.pop("headers", {})
        headers.setdefault("Authorization", f"Bearer {self.api_key}")
        headers.setdefault("Accept", "application/json")

        # Simple client-side rate limiting to stay within Granola's
        # documented 5 req/sec sustained, 25 burst.
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)

        url = f"{_GRANOLA_BASE_URL}{path}"
        response = self._session.request(
            method,
            url,
            headers=headers,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )
        self._last_request_time = time.monotonic()

        response.raise_for_status()
        return response

    def _iter_notes(
        self,
        created_after: str | None = None,
        created_before: str | None = None,
        updated_after: str | None = None,
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield pages of notes from Granola.

        Uses cursor-based pagination with page_size capped at 30.
        """

        params: dict[str, Any] = {"page_size": _GRANOLA_PAGE_SIZE}
        if created_after:
            params["created_after"] = created_after
        if created_before:
            params["created_before"] = created_before
        if updated_after:
            params["updated_after"] = updated_after

        cursor: str | None = None
        while True:
            if cursor:
                params["cursor"] = cursor

            resp = self._request("GET", "/notes", params=params)
            data = resp.json()

            notes = cast(List[dict[str, Any]], data.get("notes", []))
            if not notes:
                break

            yield notes

            has_more = data.get("hasMore")
            cursor = data.get("cursor")
            if not has_more or not cursor:
                break

    def _get_note_details(self, note_id: str) -> dict[str, Any]:
        resp = self._request(
            "GET",
            f"/notes/{note_id}",
            params={"include": "transcript"},
        )
        return resp.json()

    # ---------------------------------------------------------------------
    # Document construction
    # ---------------------------------------------------------------------
    def _create_document_from_note(
        self, note_summary: dict[str, Any], note: dict[str, Any]
    ) -> Document | None:
        note_id = note.get("id") or note_summary.get("id")
        if not isinstance(note_id, str):
            logger.warning("Skipping Granola note with missing id: %s", note_id)
            return None

        doc_id = f"{_GRANOLA_ID_PREFIX}{note_id}"

        title = note.get("title") or note_summary.get("title") or "Untitled meeting"

        created_at_str = cast(str | None, note.get("created_at"))
        created_at = _parse_iso_datetime(created_at_str) or datetime.now(timezone.utc)
        updated_at_str = cast(str | None, note.get("updated_at"))
        updated_at = _parse_iso_datetime(updated_at_str) or created_at

        year_month = created_at.strftime("%Y-%m")

        owner = cast(dict[str, Any] | None, note.get("owner")) or {}
        owner_email = owner.get("email")
        owner_name = owner.get("name")

        primary_owners: list[BasicExpertInfo] = []
        if owner_email or owner_name:
            primary_owners.append(
                BasicExpertInfo(
                    display_name=owner_name,
                    email=owner_email,
                )
            )

        attendees_infos: list[BasicExpertInfo] = []
        for attendee in cast(list[dict[str, Any]] | None, note.get("attendees")) or []:
            email = attendee.get("email")
            name = attendee.get("name")
            if not email and not name:
                continue
            if email and email == owner_email:
                continue
            attendees_infos.append(
                BasicExpertInfo(
                    display_name=name,
                    email=email,
                )
            )

        sections: list[TextSection | ImageSection] = []

        # First section: AI-generated summary
        summary_markdown = note.get("summary_markdown")
        summary_text = note.get("summary_text")
        if summary_markdown or summary_text:
            summary = cast(str, summary_markdown or summary_text)
            sections.append(
                TextSection(
                    link=None,
                    text=summary,
                )
            )

        # Transcript segments with (best-effort) speaker labels
        transcript = cast(list[dict[str, Any]] | None, note.get("transcript")) or []
        for segment in transcript:
            speaker = cast(dict[str, Any] | None, segment.get("speaker")) or {}
            speaker_name = speaker.get("name")
            speaker_email = speaker.get("email")
            speaker_source = speaker.get("source")

            if speaker_name and speaker_email:
                speaker_label = f"{speaker_name} ({speaker_email})"
            elif speaker_name:
                speaker_label = speaker_name
            elif speaker_email:
                speaker_label = speaker_email
            elif speaker_source:
                speaker_label = speaker_source
            else:
                speaker_label = "Unknown speaker"

            text = segment.get("text")
            if not text:
                continue

            sections.append(
                TextSection(
                    link=None,
                    text=f"{speaker_label}: {text}",
                )
            )

        folder_membership = cast(
            list[dict[str, Any]] | None, note.get("folder_membership")
        ) or []
        folder_names = [
            folder.get("name")
            for folder in folder_membership
            if isinstance(folder.get("name"), str)
        ]

        hierarchy = {
            "source_path": [year_month] + folder_names if folder_names else [year_month],
            "year_month": year_month,
            "meeting_title": title,
            "owner_email": owner_email,
        }

        calendar_event = cast(dict[str, Any] | None, note.get("calendar_event")) or {}

        metadata: dict[str, Any] = {
            "created_at": created_at_str,
            "updated_at": updated_at_str,
            "scheduled_start_time": calendar_event.get("scheduled_start_time"),
            "scheduled_end_time": calendar_event.get("scheduled_end_time"),
        }

        if not sections:
            # Skip documents with no indexable content (no summary or transcript)
            return None

        return Document(
            id=doc_id,
            sections=cast(List[TextSection | ImageSection], sections),
            source=DocumentSource.GRANOLA,
            semantic_identifier=title,
            doc_metadata={"hierarchy": hierarchy},
            metadata={
                k: str(v)
                for k, v in metadata.items()
                if v is not None
            },
            doc_updated_at=updated_at,
            primary_owners=primary_owners,
            secondary_owners=attendees_infos,
        )

    # ---------------------------------------------------------------------
    # Streaming interface required by connector runner
    # ---------------------------------------------------------------------
    def _generate_documents(
        self,
        created_after: str | None = None,
        created_before: str | None = None,
        updated_after: str | None = None,
    ) -> GenerateDocumentsOutput:
        doc_batch: List[Document | HierarchyNode] = []

        for notes_page in self._iter_notes(
            created_after=created_after,
            created_before=created_before,
            updated_after=updated_after,
        ):
            for note_summary in notes_page:
                note_id = note_summary.get("id")
                if not isinstance(note_id, str):
                    continue

                try:
                    note = self._get_note_details(note_id)
                except Exception as e:  # pragma: no cover - defensive logging
                    logger.error("Failed to fetch Granola note %s: %s", note_id, e)
                    continue

                doc = self._create_document_from_note(note_summary, note)
                if not doc:
                    continue

                doc_batch.append(doc)

                if len(doc_batch) >= self.batch_size:
                    yield doc_batch
                    doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Full sync: fetch all accessible notes."""

        return self._generate_documents()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Incremental sync based on creation and update time.

        We bound the window using created_after/created_before and also include
        notes whose updated_at falls within the same window via updated_after.
        """

        start_iso = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        end_iso = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        return self._generate_documents(
            created_after=start_iso,
            created_before=end_iso,
            updated_after=start_iso,
        )
