
import copy
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from typing import Literal
from typing import TypeAlias

from pydantic import BaseModel
from retry import retry
from typing_extensions import override

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.canvas.access import get_course_permissions
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
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
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.error_handling.exceptions import OnyxError
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _html_to_text(html: str | None) -> str:
    """Strip HTML tags and return plain text."""
    if not html:
        return ""
    return parse_html_page_basic(html)


class CanvasCourse(BaseModel):
    id: int
    name: str
    course_code: str
    created_at: str
    workflow_state: str


class CanvasPage(BaseModel):
    page_id: int
    url: str
    title: str
    body: str | None = None
    created_at: str
    updated_at: str
    course_id: int

    @property
    def id(self) -> int:
        return self.page_id

    @classmethod
    def from_api(
        cls, payload: dict[str, Any], course_id: int
    ) -> "CanvasPage":
        return cls(
            page_id=payload["page_id"],
            url=payload["url"],
            title=payload["title"],
            body=payload.get("body"),
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            course_id=course_id,
        )


class CanvasAssignment(BaseModel):
    id: int
    name: str
    description: str | None = None
    html_url: str
    course_id: int
    created_at: str
    updated_at: str
    due_at: str | None = None

    @classmethod
    def from_api(
        cls, payload: dict[str, Any], course_id: int
    ) -> "CanvasAssignment":
        return cls(
            id=payload["id"],
            name=payload["name"],
            description=payload.get("description"),
            html_url=payload["html_url"],
            course_id=course_id,
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
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
    def from_api(
        cls, payload: dict[str, Any], course_id: int
    ) -> "CanvasAnnouncement":
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
        self.canvas_base_url = canvas_base_url.rstrip("/")
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
        next_url: str | None = None
        first_request = True
        while True:
            if first_request:
                response, next_url = self.canvas_client.get(
                    "courses",
                    params={
                        "per_page": "100",
                        "enrollment_state": "active",
                    },
                )
                first_request = False
            else:
                response, next_url = self.canvas_client.get(
                    "", full_url=next_url
                )

            if not response:
                break
            courses.extend(
                CanvasCourse(
                    id=course["id"],
                    name=course["name"],
                    course_code=course["course_code"],
                    created_at=course["created_at"],
                    workflow_state=course["workflow_state"],
                )
                for course in response
            )
            if not next_url:
                break

        return courses

    @retry(tries=3, delay=1, backoff=2)
    def _list_pages(self, course_id: int) -> list[CanvasPage]:
        """Fetch all pages for a given course."""
        logger.debug(f"Fetching pages for course {course_id}")

        pages: list[CanvasPage] = []
        next_url: str | None = None
        first_request = True
        while True:
            if first_request:
                response, next_url = self.canvas_client.get(
                    f"courses/{course_id}/pages",
                    params={
                        "per_page": "100",
                        "include[]": "body",
                    },
                )
                first_request = False
            else:
                response, next_url = self.canvas_client.get(
                    "", full_url=next_url
                )

            if not response:
                break
            pages.extend(
                CanvasPage.from_api(p, course_id=course_id)
                for p in response
            )
            if not next_url:
                break

        return pages

    @retry(tries=3, delay=1, backoff=2)
    def _list_assignments(self, course_id: int) -> list[CanvasAssignment]:
        """Fetch all assignments for a given course."""
        logger.debug(f"Fetching assignments for course {course_id}")

        assignments: list[CanvasAssignment] = []
        next_url: str | None = None
        first_request = True
        while True:
            if first_request:
                response, next_url = self.canvas_client.get(
                    f"courses/{course_id}/assignments",
                    params={"per_page": "100"},
                )
                first_request = False
            else:
                response, next_url = self.canvas_client.get(
                    "", full_url=next_url
                )

            if not response:
                break
            assignments.extend(
                CanvasAssignment.from_api(
                    assignment, course_id=course_id
                )
                for assignment in response
            )
            if not next_url:
                break

        return assignments

    @retry(tries=3, delay=1, backoff=2)
    def _list_announcements(self, course_id: int) -> list[CanvasAnnouncement]:
        """Fetch all announcements for a given course."""
        logger.debug(f"Fetching announcements for course {course_id}")

        announcements: list[CanvasAnnouncement] = []
        next_url: str | None = None
        first_request = True
        while True:
            if first_request:
                response, next_url = self.canvas_client.get(
                    "announcements",
                    params={
                        "per_page": "100",
                        "context_codes[]": f"course_{course_id}",
                    },
                )
                first_request = False
            else:
                response, next_url = self.canvas_client.get(
                    "", full_url=next_url
                )

            if not response:
                break
            announcements.extend(
                CanvasAnnouncement.from_api(a, course_id=course_id)
                for a in response
            )
            if not next_url:
                break

        return announcements

    def _convert_page_to_document(self, page: CanvasPage) -> Document:
        """Convert a Canvas page to a Document."""

        link = f"{self.canvas_base_url}/courses/{page.course_id}/pages/{page.url}"

        text_parts = [page.title, link]
        body_text = _html_to_text(page.body)
        if body_text:
            text_parts.append(body_text)

        sections = [TextSection(link=link, text="\n\n".join(text_parts))]

        return Document(
            id=f"canvas-page-{page.course_id}-{page.page_id}",
            sections=cast(list[TextSection | ImageSection], sections),
            source=DocumentSource.CANVAS,
            semantic_identifier=page.title or f"Page {page.page_id}",
            doc_updated_at=datetime.fromisoformat(page.updated_at).astimezone(
                timezone.utc
            ),
            metadata={"course_id": str(page.course_id)},
        )

    def _convert_assignment_to_document(
        self, assignment: CanvasAssignment
    ) -> Document:
        """Convert a Canvas assignment to a Document."""

        text_parts = [assignment.name, assignment.html_url]
        desc_text = _html_to_text(assignment.description)
        if desc_text:
            text_parts.append(desc_text)
        if assignment.due_at:
            text_parts.append(f"Due: {assignment.due_at}")

        sections = [
            TextSection(link=assignment.html_url, text="\n\n".join(text_parts))
        ]

        return Document(
            id=f"canvas-assignment-{assignment.course_id}-{assignment.id}",
            sections=cast(list[TextSection | ImageSection], sections),
            source=DocumentSource.CANVAS,
            semantic_identifier=assignment.name or f"Assignment {assignment.id}",
            doc_updated_at=datetime.fromisoformat(
                assignment.updated_at
            ).astimezone(timezone.utc),
            metadata={"course_id": str(assignment.course_id)},
        )

    def _convert_announcement_to_document(
        self, announcement: CanvasAnnouncement
    ) -> Document:
        """Convert a Canvas announcement to a Document."""

        text_parts = [announcement.title, announcement.html_url]
        msg_text = _html_to_text(announcement.message)
        if msg_text:
            text_parts.append(msg_text)

        sections = [
            TextSection(
                link=announcement.html_url, text="\n\n".join(text_parts)
            )
        ]

        doc_updated_at = None
        if announcement.posted_at:
            doc_updated_at = datetime.fromisoformat(
                announcement.posted_at
            ).astimezone(timezone.utc)

        return Document(
            id=f"canvas-announcement-{announcement.course_id}-{announcement.id}",
            sections=cast(list[TextSection | ImageSection], sections),
            source=DocumentSource.CANVAS,
            semantic_identifier=announcement.title
            or f"Announcement {announcement.id}",
            doc_updated_at=doc_updated_at,
            metadata={"course_id": str(announcement.course_id)},
        )

    def load_credentials(
        self, credentials: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Load and validate Canvas credentials."""
        self._canvas_client = CanvasApiClient(
            bearer_token=credentials["canvas_access_token"],
            canvas_base_url=self.canvas_base_url,
        )

        try:
            self._canvas_client.get("courses", params={"per_page": "1"})
        except OnyxError as e:
            if e.status_code == 401:
                raise CredentialExpiredError(
                    "Canvas API token is invalid or expired (HTTP 401)."
                )
            raise

        return None

    def validate_connector_settings(self) -> None:
        """Validate Canvas connector settings by testing API access."""
        try:
            self.canvas_client.get("courses", params={"per_page": "1"})
            logger.info("Canvas connector settings validated successfully")
        except OnyxError as e:
            if e.status_code == 401:
                raise CredentialExpiredError(
                    "Canvas credential appears to be invalid or expired (HTTP 401)."
                )
            elif e.status_code == 429:
                raise ConnectorValidationError(
                    "Validation failed due to Canvas rate-limits being exceeded (HTTP 429). "
                    "Please try again later."
                )
            else:
                raise UnexpectedValidationError(
                    f"Unexpected Canvas HTTP error (status={e.status_code}): {e}"
                )
        except Exception as exc:
            raise UnexpectedValidationError(
                f"Unexpected error during Canvas settings validation: {exc}"
            )
