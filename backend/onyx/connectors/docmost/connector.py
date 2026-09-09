"""DocMost connector for Onyx.

Implements LoadConnector, PollConnector, and SlimConnector.

Architecture note (Open Elements disjoint-cascade pattern):
    Each connector instance authenticates as a single DocMost service user whose
    space membership defines exactly what it can see. Combined with an optional
    ``space_filter`` allow-list, one Onyx connector instance maps to one cluster
    (extern / employee / it / gl). Visibility cascades via the connector being
    set Private + mapped to an Onyx user group; NO per-document permission sync
    is performed here (tracked as a v2 follow-up).

Field names below were verified against a live DocMost instance
(docmost.playground.open-elements.cloud, DocMost v0.25.x): the SPACE_* and
PAGE_* record fields all match, and /pages/recent returns page metadata WITHOUT
the `content` body — so full content is fetched per-page via /pages/info. Space
scoping is done client-side by spaceId; /pages/recent needs no scoping arg.
"""

from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.docmost.client import DocmostAuthError
from onyx.connectors.docmost.client import DocmostClient
from onyx.connectors.docmost.client import DocmostClientError
from onyx.connectors.docmost.prosemirror import prosemirror_to_text
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

logger = setup_logger()

# --- DocMost record field names (verified against a live instance) ----------
SPACE_ID_FIELD = "id"
SPACE_SLUG_FIELD = "slug"
SPACE_NAME_FIELD = "name"

PAGE_ID_FIELD = "id"
PAGE_TITLE_FIELD = "title"
PAGE_CONTENT_FIELD = "content"
PAGE_SLUG_FIELD = "slugId"
PAGE_UPDATED_FIELD = "updatedAt"
PAGE_SPACE_ID_FIELD = "spaceId"
# ----------------------------------------------------------------------------

# Endpoint paths (all POST per DocMost API).
_SPACES_LIST = "spaces"
_PAGES_RECENT = "pages/recent"
_PAGE_INFO = "pages/info"


class DocmostConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        space_filter: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        # Allow-list of space slugs; empty/None means "all spaces the service user sees".
        self.space_filter = {s.strip() for s in (space_filter or []) if s.strip()}
        self.batch_size = batch_size

        self._client: DocmostClient | None = None
        self._web_base_url: str | None = None

    # -- credential wiring ---------------------------------------------------

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        base_url = credentials.get("docmost_base_url")
        api_token = credentials.get("docmost_api_token")
        if not base_url or not api_token:
            raise ConnectorMissingCredentialError("DocMost")

        self._web_base_url = base_url.rstrip("/")
        if self._web_base_url.endswith("/api"):
            self._web_base_url = self._web_base_url[: -len("/api")]

        self._client = DocmostClient(base_url=base_url, api_token=api_token)
        return None

    @property
    def client(self) -> DocmostClient:
        if self._client is None:
            raise ConnectorMissingCredentialError("DocMost")
        return self._client

    def validate_connector_settings(self) -> None:
        """Confirm the token works and that any configured space filters resolve."""
        try:
            # /spaces is the smallest list call; limit 1 just probes auth.
            next(iter(self.client.paginate(_SPACES_LIST, limit=1)), None)
        except DocmostAuthError as e:
            raise CredentialExpiredError(str(e))
        except DocmostClientError as e:
            raise ConnectorValidationError(str(e))

        # Validate that space_filter slugs actually resolve to visible spaces.
        if self.space_filter:
            resolved = self._allowed_space_ids()
            if resolved is not None and not resolved:
                raise ConnectorValidationError(
                    f"None of the configured space_filter slugs "
                    f"({', '.join(sorted(self.space_filter))}) match any "
                    f"spaces visible to the service user. Check that the "
                    f"slugs are correct and the user has access."
                )

    # -- interface: LoadConnector -------------------------------------------

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Full backfill: every space the service user sees (respecting the
        allow-list), then every page in each space."""
        yield from self._fetch_documents(start=None, end=None)

    # -- interface: PollConnector -------------------------------------------

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Incremental: pages updated within [start, end].

        Uses /pages/recent (recency-ordered) and stops paginating once we cross
        below ``start``. Pages are still filtered to the allow-listed spaces.
        """
        yield from self._fetch_documents(start=start, end=end)

    # -- interface: SlimConnector -------------------------------------------

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: Any | None = None,
    ) -> GenerateSlimDocumentOutput:
        """ID-only pass used by the pruning job.

        Intentionally enumerates ALL documents (ignoring start/end) because
        pruning needs the full set of IDs to detect deletions.
        """
        slim_batch: list[SlimDocument] = []
        for page in self._iter_pages(start=None, end=None, fetch_content=False):
            page_id = page.get(PAGE_ID_FIELD)
            if not page_id:
                continue
            slim_batch.append(SlimDocument(id=self._doc_id(page_id)))
            if len(slim_batch) >= self.batch_size:
                yield slim_batch
                slim_batch = []
        if slim_batch:
            yield slim_batch

    # -- internals -----------------------------------------------------------

    def _fetch_documents(
        self,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
    ) -> Iterator[list[Document]]:
        batch: list[Document] = []
        for page in self._iter_pages(start=start, end=end):
            doc = self._page_to_document(page)
            if doc is None:
                continue
            batch.append(doc)
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def _allowed_space_ids(self) -> set[str] | None:
        """Resolve the allow-list of space slugs to a set of space IDs.

        Returns None when no filter is configured (meaning: index everything
        the service user can see)."""
        if not self.space_filter:
            return None
        allowed: set[str] = set()
        visible_slugs: set[str] = set()
        for space in self.client.paginate(_SPACES_LIST):
            slug = space.get(SPACE_SLUG_FIELD)
            if slug:
                visible_slugs.add(slug)
            if slug in self.space_filter:
                space_id = space.get(SPACE_ID_FIELD)
                if space_id:
                    allowed.add(space_id)

        unresolved = self.space_filter - visible_slugs
        if unresolved:
            logger.warning(
                f"DocMost space_filter contains slugs not visible to the "
                f"service user: {sorted(unresolved)}. These will be ignored."
            )
        return allowed

    def _iter_pages(
        self,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        fetch_content: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """Yield raw page records, filtered by space allow-list and time window.

        Pages are pulled via /pages/recent (recency-ordered). For a poll we stop
        once updatedAt drops below ``start``. For a full load we read to the end.

        When ``fetch_content`` is False, skips the per-page /pages/info call
        (used by slim-doc retrieval where only IDs are needed).
        """
        allowed_ids = self._allowed_space_ids()

        for page in self.client.paginate(_PAGES_RECENT):
            # Apply space filter first so that pages from non-allowed spaces
            # don't trigger the early-break on the time window boundary.
            if allowed_ids is not None:
                if page.get(PAGE_SPACE_ID_FIELD) not in allowed_ids:
                    continue

            updated_at = self._parse_updated(page.get(PAGE_UPDATED_FIELD))

            # Recency-ordered: once we're older than the window start, we're done.
            if start is not None and updated_at is not None:
                if updated_at.timestamp() < start:
                    break
            if end is not None and updated_at is not None:
                if updated_at.timestamp() > end:
                    continue

            # /pages/recent may return a summary; fetch full content if missing.
            if fetch_content and not page.get(PAGE_CONTENT_FIELD):
                page = self._fetch_page_full(page) or page

            yield page

    def _fetch_page_full(self, page: dict[str, Any]) -> dict[str, Any] | None:
        page_id = page.get(PAGE_ID_FIELD)
        if not page_id:
            return None
        try:
            return self.client.post(_PAGE_INFO, {"pageId": page_id})
        except DocmostClientError as e:
            logger.warning(f"Could not fetch full DocMost page {page_id}: {e}")
            return None

    def _page_to_document(self, page: dict[str, Any]) -> Document | None:
        page_id = page.get(PAGE_ID_FIELD)
        if not page_id:
            return None

        title = page.get(PAGE_TITLE_FIELD) or "Untitled"
        text = prosemirror_to_text(page.get(PAGE_CONTENT_FIELD))
        # Index even title-only pages; an empty body is still a real page.
        full_text = f"{title}\n\n{text}".strip() if text else title

        updated_at = self._parse_updated(page.get(PAGE_UPDATED_FIELD))

        metadata: dict[str, str | list[str]] = {}
        if page.get(PAGE_SPACE_ID_FIELD):
            metadata["space_id"] = str(page[PAGE_SPACE_ID_FIELD])
        if page.get("creatorId"):
            metadata["author"] = str(page["creatorId"])

        return Document(
            id=self._doc_id(page_id),
            sections=[TextSection(link=self._page_url(page), text=full_text)],
            source=DocumentSource.DOCMOST,
            semantic_identifier=title,
            metadata=metadata,
            doc_updated_at=updated_at,
        )

    def _page_url(self, page: dict[str, Any]) -> str:
        slug = page.get(PAGE_SLUG_FIELD) or page.get(PAGE_ID_FIELD)
        return f"{self._web_base_url}/p/{slug}"

    @staticmethod
    def _doc_id(page_id: str) -> str:
        return f"docmost:page:{page_id}"

    @staticmethod
    def _parse_updated(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
