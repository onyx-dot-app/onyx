from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from typing import Literal
from typing import NoReturn
from typing import TypeAlias

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
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
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
    elif e.status_code == 429:
        raise ConnectorValidationError(
            "Canvas rate-limit exceeded (HTTP 429). Please try again later."
        )
    elif e.status_code >= 500:
        raise UnexpectedValidationError(
            f"Unexpected Canvas HTTP error (status={e.status_code}): {e}"
        )
    else:
        raise ConnectorValidationError(
            f"Canvas API error (status={e.status_code}): {e}"
        )

def _handle_canvas_api_error(e: OnyxError) -> None:
    """Map Canvas API errors to connector framework exceptions."""
    if e.status_code == 401:
        raise CredentialExpiredError(
            "Canvas API token is invalid or expired (HTTP 401)."
        )
    elif e.status_code == 403:
        raise InsufficientPermissionsError(
            "Canvas API token does not have sufficient permissions (HTTP 403)."
        )
    elif e.status_code == 429:
        raise ConnectorValidationError(
            "Canvas rate-limit exceeded (HTTP 429). Please try again later."
        )
    else:
        raise ConnectorValidationError(
            f"Canvas API error (status={e.status_code}): {e}"
        )


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


CanvasStage: TypeAlias = Literal["pages", "assignments", "announcements"]


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
    stage: CanvasStage = "pages"
    next_url: str | None = None

    def advance_course(self) -> None:
        """Move to the next course and reset within-course state."""
        self.current_course_index += 1
        self.stage = "pages"
        self.next_url = None


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
        logger.debug(f"Fetching pages for course {course_id}")

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
        logger.debug(f"Fetching assignments for course {course_id}")

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
        logger.debug(f"Fetching announcements for course {course_id}")

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

        doc_updated_at = (
            datetime.fromisoformat(page.updated_at.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
            if page.updated_at
            else None
        )

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
            due_dt = datetime.fromisoformat(
                assignment.due_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            text_parts.append(f"Due: {due_dt.strftime('%B %d, %Y %H:%M UTC')}")

        doc_updated_at = (
            datetime.fromisoformat(
                assignment.updated_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            if assignment.updated_at
            else None
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
            datetime.fromisoformat(
                announcement.posted_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            if announcement.posted_at
            else None
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
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: CanvasConnectorCheckpoint,
    ) -> CheckpointOutput[CanvasConnectorCheckpoint]:
        # TODO(benwu408): implemented in PR3 (checkpoint)
        raise NotImplementedError

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: CanvasConnectorCheckpoint,
    ) -> CheckpointOutput[CanvasConnectorCheckpoint]:
        # TODO(benwu408): implemented in PR3 (checkpoint)
        raise NotImplementedError

    @override
    def build_dummy_checkpoint(self) -> CanvasConnectorCheckpoint:
        # TODO(benwu408): implemented in PR3 (checkpoint)
        raise NotImplementedError

    @override
    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> CanvasConnectorCheckpoint:
        # TODO(benwu408): implemented in PR3 (checkpoint)
        raise NotImplementedError

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        # TODO(benwu408): implemented in PR4 (perm sync)
        raise NotImplementedError
