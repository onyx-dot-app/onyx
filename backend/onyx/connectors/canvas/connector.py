from datetime import datetime
from datetime import timezone
from enum import StrEnum
from typing import Any
from typing import cast
from typing import NoReturn

from pydantic import BaseModel
from retry import retry
from typing_extensions import override

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.canvas.access import get_course_permissions
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _handle_canvas_api_error(e: OnyxError) -> NoReturn:
    """Map Canvas API errors to connector framework exceptions."""
    if e.status_code == 401:
        raise CredentialExpiredError(
            "Canvas API token is invalid or expired (HTTP 401)."
        )
    elif e.status_code == 403:
        raise InsufficientPermissionsError(
            "Canvas API token does not have sufficient permissions (HTTP 403)."
        )
    elif e.status_code >= 500:
        raise UnexpectedValidationError(
            f"Unexpected Canvas HTTP error (status={e.status_code}): {e}"
        )
    else:
        raise ConnectorValidationError(
            f"Canvas API error (status={e.status_code}): {e}"
        )


class CanvasStage(StrEnum):
    PAGES = "pages"
    ASSIGNMENTS = "assignments"
    ANNOUNCEMENTS = "announcements"


_STAGE_CONFIG: dict[CanvasStage, dict[str, Any]] = {
    CanvasStage.PAGES: {
        "endpoint": "courses/{course_id}/pages",
        "params": {
            "per_page": "100",
            "include[]": "body",
            "published": "true",
            "sort": "updated_at",
            "order": "desc",
        },
    },
    CanvasStage.ASSIGNMENTS: {
        "endpoint": "courses/{course_id}/assignments",
        "params": {"per_page": "100", "published": "true"},
    },
    CanvasStage.ANNOUNCEMENTS: {
        "endpoint": "announcements",
        "params": {
            "per_page": "100",
            "context_codes[]": "course_{course_id}",
            "active_only": "true",
        },
    },
}


def _parse_canvas_dt(timestamp_str: str) -> datetime:
    """Parse a Canvas ISO-8601 timestamp (e.g. '2025-06-15T12:00:00Z')
    into a timezone-aware UTC datetime.

    Canvas returns timestamps with a trailing 'Z' instead of '+00:00',
    so we normalise before parsing.
    """
    return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _unix_to_canvas_time(epoch: float) -> str:
    """Convert a Unix timestamp to Canvas ISO-8601 format (e.g. '2025-06-15T12:00:00Z')."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _in_time_window(timestamp_str: str, start: float, end: float) -> bool:
    """Check whether a Canvas ISO-8601 timestamp falls within (start, end]."""
    return start < _parse_canvas_dt(timestamp_str).timestamp() <= end


class CanvasCourse(BaseModel):
    id: int
    name: str | None = None
    course_code: str | None = None
    created_at: str | None = None
    workflow_state: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "CanvasCourse":
        return cls(
            id=payload["id"],
            name=payload.get("name"),
            course_code=payload.get("course_code"),
            created_at=payload.get("created_at"),
            workflow_state=payload.get("workflow_state"),
        )


class CanvasPage(BaseModel):
    page_id: int
    url: str
    title: str
    body: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    course_id: int

    @classmethod
    def from_api(cls, payload: dict[str, Any], course_id: int) -> "CanvasPage":
        return cls(
            page_id=payload["page_id"],
            url=payload["url"],
            title=payload["title"],
            body=payload.get("body"),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            course_id=course_id,
        )


class CanvasAssignment(BaseModel):
    id: int
    name: str
    description: str | None = None
    html_url: str
    course_id: int
    created_at: str | None = None
    updated_at: str | None = None
    due_at: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any], course_id: int) -> "CanvasAssignment":
        return cls(
            id=payload["id"],
            name=payload["name"],
            description=payload.get("description"),
            html_url=payload["html_url"],
            course_id=course_id,
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            due_at=payload.get("due_at"),
        )


class CanvasAnnouncement(BaseModel):
    id: int
    title: str
    message: str | None = None
    html_url: str
    posted_at: str | None = None
    course_id: int

    @classmethod
    def from_api(cls, payload: dict[str, Any], course_id: int) -> "CanvasAnnouncement":
        return cls(
            id=payload["id"],
            title=payload["title"],
            message=payload.get("message"),
            html_url=payload["html_url"],
            posted_at=payload.get("posted_at"),
            course_id=course_id,
        )


class CanvasConnectorCheckpoint(ConnectorCheckpoint):
    """Checkpoint state for resumable Canvas indexing.

    Fields:
        course_ids: Materialized list of course IDs to process.
        current_course_index: Index into course_ids for current course.
        stage: Which item type we're processing for the current course.
        next_url: Pagination cursor within the current stage. None means
            start from the first page; a URL means resume from that page.

    Invariant:
        If current_course_index is incremented, stage must be reset to
        "pages" and next_url must be reset to None.
    """

    course_ids: list[int] = []
    current_course_index: int = 0
    stage: CanvasStage = CanvasStage.PAGES
    next_url: str | None = None

    def advance_course(self) -> None:
        """Move to the next course and reset within-course state."""
        self.current_course_index += 1
        self.stage = CanvasStage.PAGES
        self.next_url = None

    def advance_stage(self) -> None:
        """Advance past the current stage.

        Moves to the next stage within the same course, or to the next
        course if the current stage is the last one. Resets next_url so
        the next call starts fresh on the new stage.
        """
        self.next_url = None
        stages: list[CanvasStage] = list(CanvasStage)
        next_idx = stages.index(self.stage) + 1
        if next_idx < len(stages):
            self.stage = stages[next_idx]
        else:
            self.advance_course()


class CanvasConnector(
    CheckpointedConnectorWithPermSync[CanvasConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
    def __init__(
        self,
        canvas_base_url: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.canvas_base_url = canvas_base_url.rstrip("/").removesuffix("/api/v1")
        self.batch_size = batch_size
        self._canvas_client: CanvasApiClient | None = None
        self._course_permissions_cache: dict[int, ExternalAccess | None] = {}

    @property
    def canvas_client(self) -> CanvasApiClient:
        if self._canvas_client is None:
            raise ConnectorMissingCredentialError("Canvas")
        return self._canvas_client

    def _get_course_permissions(self, course_id: int) -> ExternalAccess | None:
        """Get course permissions with caching."""
        if course_id not in self._course_permissions_cache:
            self._course_permissions_cache[course_id] = get_course_permissions(
                canvas_client=self.canvas_client,
                course_id=course_id,
            )
        return self._course_permissions_cache[course_id]

    @retry(tries=3, delay=1, backoff=2)
    def _list_courses(self) -> list[CanvasCourse]:
        """Fetch all courses accessible to the authenticated user."""
        logger.debug("Fetching Canvas courses")

        courses: list[CanvasCourse] = []
        for page in self.canvas_client.paginate(
            "courses", params={"per_page": "100", "state[]": "available"}
        ):
            courses.extend(CanvasCourse.from_api(c) for c in page)
        return courses

    @retry(tries=3, delay=1, backoff=2)
    def _list_pages(self, course_id: int) -> list[CanvasPage]:
        """Fetch all pages for a given course."""
        logger.debug("Fetching pages for course %s", course_id)

        pages: list[CanvasPage] = []
        for page in self.canvas_client.paginate(
            f"courses/{course_id}/pages",
            params={"per_page": "100", "include[]": "body", "published": "true"},
        ):
            pages.extend(CanvasPage.from_api(p, course_id=course_id) for p in page)
        return pages

    @retry(tries=3, delay=1, backoff=2)
    def _list_assignments(self, course_id: int) -> list[CanvasAssignment]:
        """Fetch all assignments for a given course."""
        logger.debug("Fetching assignments for course %s", course_id)

        assignments: list[CanvasAssignment] = []
        for page in self.canvas_client.paginate(
            f"courses/{course_id}/assignments",
            params={"per_page": "100", "published": "true"},
        ):
            assignments.extend(
                CanvasAssignment.from_api(a, course_id=course_id) for a in page
            )
        return assignments

    @retry(tries=3, delay=1, backoff=2)
    def _list_announcements(self, course_id: int) -> list[CanvasAnnouncement]:
        """Fetch all announcements for a given course."""
        logger.debug("Fetching announcements for course %s", course_id)

        announcements: list[CanvasAnnouncement] = []
        for page in self.canvas_client.paginate(
            "announcements",
            params={
                "per_page": "100",
                "context_codes[]": f"course_{course_id}",
                "active_only": "true",
            },
        ):
            announcements.extend(
                CanvasAnnouncement.from_api(a, course_id=course_id) for a in page
            )
        return announcements

    def _build_document(
        self,
        doc_id: str,
        link: str,
        text: str,
        semantic_identifier: str,
        doc_updated_at: datetime | None,
        course_id: int,
        doc_type: str,
    ) -> Document:
        """Build a Document with standard Canvas fields."""
        return Document(
            id=doc_id,
            sections=cast(
                list[TextSection | ImageSection],
                [TextSection(link=link, text=text)],
            ),
            source=DocumentSource.CANVAS,
            semantic_identifier=semantic_identifier,
            doc_updated_at=doc_updated_at,
            metadata={"course_id": str(course_id), "type": doc_type},
        )

    def _convert_page_to_document(self, page: CanvasPage) -> Document:
        """Convert a Canvas page to a Document."""
        link = f"{self.canvas_base_url}/courses/{page.course_id}/pages/{page.url}"

        text_parts = [page.title]
        body_text = parse_html_page_basic(page.body) if page.body else ""
        if body_text:
            text_parts.append(body_text)

        doc_updated_at = _parse_canvas_dt(page.updated_at) if page.updated_at else None

        document = self._build_document(
            doc_id=f"canvas-page-{page.course_id}-{page.page_id}",
            link=link,
            text="\n\n".join(text_parts),
            semantic_identifier=page.title or f"Page {page.page_id}",
            doc_updated_at=doc_updated_at,
            course_id=page.course_id,
            doc_type="page",
        )
        return document

    def _convert_assignment_to_document(self, assignment: CanvasAssignment) -> Document:
        """Convert a Canvas assignment to a Document."""
        text_parts = [assignment.name]
        desc_text = (
            parse_html_page_basic(assignment.description)
            if assignment.description
            else ""
        )
        if desc_text:
            text_parts.append(desc_text)
        if assignment.due_at:
            due_dt = _parse_canvas_dt(assignment.due_at)
            text_parts.append(f"Due: {due_dt.strftime('%B %d, %Y %H:%M UTC')}")

        doc_updated_at = (
            _parse_canvas_dt(assignment.updated_at) if assignment.updated_at else None
        )

        document = self._build_document(
            doc_id=f"canvas-assignment-{assignment.course_id}-{assignment.id}",
            link=assignment.html_url,
            text="\n\n".join(text_parts),
            semantic_identifier=assignment.name or f"Assignment {assignment.id}",
            doc_updated_at=doc_updated_at,
            course_id=assignment.course_id,
            doc_type="assignment",
        )
        return document

    def _convert_announcement_to_document(
        self, announcement: CanvasAnnouncement
    ) -> Document:
        """Convert a Canvas announcement to a Document."""
        text_parts = [announcement.title]
        msg_text = (
            parse_html_page_basic(announcement.message) if announcement.message else ""
        )
        if msg_text:
            text_parts.append(msg_text)

        doc_updated_at = (
            _parse_canvas_dt(announcement.posted_at) if announcement.posted_at else None
        )

        document = self._build_document(
            doc_id=f"canvas-announcement-{announcement.course_id}-{announcement.id}",
            link=announcement.html_url,
            text="\n\n".join(text_parts),
            semantic_identifier=announcement.title or f"Announcement {announcement.id}",
            doc_updated_at=doc_updated_at,
            course_id=announcement.course_id,
            doc_type="announcement",
        )
        return document

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load and validate Canvas credentials."""
        access_token = credentials.get("canvas_access_token")
        if not access_token:
            raise ConnectorMissingCredentialError("Canvas")

        try:
            client = CanvasApiClient(
                bearer_token=access_token,
                canvas_base_url=self.canvas_base_url,
            )
            client.get("courses", params={"per_page": "1"})
        except ValueError as e:
            raise ConnectorValidationError(f"Invalid Canvas base URL: {e}")
        except OnyxError as e:
            _handle_canvas_api_error(e)

        self._canvas_client = client
        return None

    def _fetch_stage_page(
        self,
        next_url: str | None,
        endpoint: str,
        params: dict[str, Any],
    ) -> tuple[list[Any], str | None]:
        """Fetch one page of API results for the current stage.

        Returns (items, next_url).  All error handling is done by the
        caller (_load_from_checkpoint).
        """
        if next_url:
            # Resuming mid-pagination: the next_url from Canvas's
            # Link header already contains endpoint + query params.
            response, result_next_url = self.canvas_client.get(full_url=next_url)
        else:
            # First request for this stage: build from endpoint + params.
            response, result_next_url = self.canvas_client.get(
                endpoint=endpoint, params=params
            )
        return response or [], result_next_url

    def _process_items(
        self,
        response: list[Any],
        stage: CanvasStage,
        course_id: int,
        start: float,
        end: float,
        include_permissions: bool,
    ) -> tuple[list[Document | ConnectorFailure], bool]:
        """Process a page of API results into documents.

        Returns (docs, early_exit). early_exit is True when pages
        (sorted desc by updated_at) hit an item older than start,
        signaling that pagination should stop.
        """
        results: list[Document | ConnectorFailure] = []
        early_exit = False

        for item in response:
            try:
                if stage == CanvasStage.PAGES:
                    page = CanvasPage.from_api(item, course_id=course_id)
                    if not page.updated_at:
                        continue
                    # Pages are sorted by updated_at desc — once we see
                    # an item at or before `start`, all remaining items
                    # on this and subsequent pages are older too.
                    if not _in_time_window(page.updated_at, start, end):
                        if _parse_canvas_dt(page.updated_at).timestamp() <= start:
                            early_exit = True
                            break
                        # ts > end: page is newer than our window, skip it
                        continue
                    doc = self._convert_page_to_document(page)
                    results.append(
                        self._maybe_attach_permissions(
                            doc, course_id, include_permissions
                        )
                    )

                elif stage == CanvasStage.ASSIGNMENTS:
                    assignment = CanvasAssignment.from_api(item, course_id=course_id)
                    if not assignment.updated_at or not _in_time_window(
                        assignment.updated_at, start, end
                    ):
                        continue
                    doc = self._convert_assignment_to_document(assignment)
                    results.append(
                        self._maybe_attach_permissions(
                            doc, course_id, include_permissions
                        )
                    )

                elif stage == CanvasStage.ANNOUNCEMENTS:
                    announcement = CanvasAnnouncement.from_api(
                        item, course_id=course_id
                    )
                    if not announcement.posted_at:
                        logger.debug(
                            "Skipping announcement %s in course %s: no posted_at",
                            announcement.id,
                            course_id,
                        )
                        continue
                    if not _in_time_window(announcement.posted_at, start, end):
                        continue
                    doc = self._convert_announcement_to_document(announcement)
                    results.append(
                        self._maybe_attach_permissions(
                            doc, course_id, include_permissions
                        )
                    )

            except Exception as e:
                item_id = item.get("id") or item.get("page_id", "unknown")
                if stage == CanvasStage.PAGES:
                    doc_link = (
                        f"{self.canvas_base_url}/courses/{course_id}"
                        f"/pages/{item.get('url', '')}"
                    )
                else:
                    doc_link = item.get("html_url", "")
                results.append(
                    ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=f"canvas-{stage.removesuffix('s')}-{course_id}-{item_id}",
                            document_link=doc_link,
                        ),
                        failure_message=f"Failed to process {stage.removesuffix('s')}: {e}",
                        exception=e,
                    )
                )

        return results, early_exit

    def _maybe_attach_permissions(
        self,
        document: Document,
        course_id: int,
        include_permissions: bool,
    ) -> Document:
        if include_permissions:
            document.external_access = self._get_course_permissions(course_id)
        return document

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: CanvasConnectorCheckpoint,
        include_permissions: bool = False,
    ) -> CheckpointOutput[CanvasConnectorCheckpoint]:
        """Shared implementation for load_from_checkpoint and load_from_checkpoint_with_perm_sync."""
        new_checkpoint = checkpoint.model_copy(deep=True)

        # First call: materialize the list of course IDs.
        # On failure, let the exception propagate so the framework fails the
        # attempt cleanly. Swallowing errors here would leave the checkpoint
        # state unchanged and cause an infinite retry loop.
        if not new_checkpoint.course_ids:
            try:
                courses = self._list_courses()
            except OnyxError as e:
                if e.status_code in (401, 403):
                    _handle_canvas_api_error(e)  # NoReturn — always raises
                raise
            new_checkpoint.course_ids = [c.id for c in courses]
            logger.info("Found %s Canvas courses to process", len(courses))
            new_checkpoint.has_more = len(new_checkpoint.course_ids) > 0
            return new_checkpoint

        # All courses done.
        if new_checkpoint.current_course_index >= len(new_checkpoint.course_ids):
            new_checkpoint.has_more = False
            return new_checkpoint

        course_id = new_checkpoint.course_ids[new_checkpoint.current_course_index]
        try:
            stage = CanvasStage(new_checkpoint.stage)
        except ValueError as e:
            raise ValueError(
                f"Invalid checkpoint stage: {new_checkpoint.stage!r}. "
                f"Valid stages: {[s.value for s in CanvasStage]}"
            ) from e

        # Build endpoint + params from the static template.
        config = _STAGE_CONFIG[stage]
        endpoint = config["endpoint"].format(course_id=course_id)
        params = {k: v.format(course_id=course_id) for k, v in config["params"].items()}
        # Only the announcements API supports server-side date filtering
        # (start_date/end_date). Pages support server-side sorting
        # (sort=updated_at desc) enabling early exit, but not date
        # filtering. Assignments support neither. Both are filtered
        # client-side via _in_time_window after fetching.
        if stage == CanvasStage.ANNOUNCEMENTS:
            params["start_date"] = _unix_to_canvas_time(start)
            params["end_date"] = _unix_to_canvas_time(end)

        try:
            response, result_next_url = self._fetch_stage_page(
                next_url=new_checkpoint.next_url,
                endpoint=endpoint,
                params=params,
            )
        except OnyxError as oe:
            # Security errors from _parse_next_link (host/scheme
            # mismatch on pagination URLs) have no status code override
            # and must not be silenced.
            is_api_error = oe._status_code_override is not None
            if not is_api_error:
                raise
            if oe.status_code in (401, 403):
                _handle_canvas_api_error(oe)  # NoReturn — always raises

            # 404 means the course itself is gone or inaccessible. The
            # other stages on this course will hit the same 404, so skip
            # the whole course rather than burning API calls on each stage.
            if oe.status_code == 404:
                logger.warning(
                    "Canvas course %s not found while fetching %s (HTTP 404). Skipping course.",
                    course_id,
                    stage,
                )
                yield ConnectorFailure(
                    failed_entity=EntityFailure(
                        entity_id=f"canvas-course-{course_id}",
                    ),
                    failure_message=(f"Canvas course {course_id} not found: {oe}"),
                    exception=oe,
                )
                new_checkpoint.advance_course()
            else:
                logger.warning(
                    "Failed to fetch %s for course %s: %s. Skipping remainder of this stage.",
                    stage,
                    course_id,
                    oe,
                )
                yield ConnectorFailure(
                    failed_entity=EntityFailure(
                        entity_id=f"canvas-{stage}-{course_id}",
                    ),
                    failure_message=(
                        f"Failed to fetch {stage} for course {course_id}: {oe}"
                    ),
                    exception=oe,
                )
                new_checkpoint.advance_stage()
            new_checkpoint.has_more = new_checkpoint.current_course_index < len(
                new_checkpoint.course_ids
            )
            return new_checkpoint
        except Exception as e:
            # Unknown error — skip the stage and try to continue.
            logger.warning(
                "Failed to fetch %s for course %s: %s. Skipping remainder of this stage.",
                stage,
                course_id,
                e,
            )
            yield ConnectorFailure(
                failed_entity=EntityFailure(
                    entity_id=f"canvas-{stage}-{course_id}",
                ),
                failure_message=(
                    f"Failed to fetch {stage} for course {course_id}: {e}"
                ),
                exception=e,
            )
            new_checkpoint.advance_stage()
            new_checkpoint.has_more = new_checkpoint.current_course_index < len(
                new_checkpoint.course_ids
            )
            return new_checkpoint

        # Process fetched items
        results, early_exit = self._process_items(
            response, stage, course_id, start, end, include_permissions
        )
        for result in results:
            yield result

        # If we hit an item older than our window (pages sorted desc),
        # skip remaining pagination and advance to the next stage.
        if early_exit:
            result_next_url = None

        # If there are more pages, save the cursor and return
        if result_next_url:
            new_checkpoint.next_url = result_next_url
        else:
            # Stage complete — advance to next stage (or next course if last).
            new_checkpoint.advance_stage()

        new_checkpoint.has_more = new_checkpoint.current_course_index < len(
            new_checkpoint.course_ids
        )
        return new_checkpoint

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: CanvasConnectorCheckpoint,
    ) -> CheckpointOutput[CanvasConnectorCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=False
        )

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: CanvasConnectorCheckpoint,
    ) -> CheckpointOutput[CanvasConnectorCheckpoint]:
        """Load documents from checkpoint with permission information included."""
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=True
        )

    @override
    def build_dummy_checkpoint(self) -> CanvasConnectorCheckpoint:
        return CanvasConnectorCheckpoint(has_more=True)

    @override
    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> CanvasConnectorCheckpoint:
        return CanvasConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def validate_connector_settings(self) -> None:
        """Validate Canvas connector settings by testing API access."""
        try:
            self.canvas_client.get("courses", params={"per_page": "1"})
            logger.info("Canvas connector settings validated successfully")
        except OnyxError as e:
            _handle_canvas_api_error(e)
        except ConnectorMissingCredentialError:
            raise
        except Exception as exc:
            raise UnexpectedValidationError(
                f"Unexpected error during Canvas settings validation: {exc}"
            )

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        # TODO(benwu408): implemented in PR4 (perm sync)
        raise NotImplementedError
