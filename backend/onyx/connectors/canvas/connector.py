from typing import Literal

from pydantic import BaseModel

from onyx.connectors.models import ConnectorCheckpoint
from onyx.utils.logger import setup_logger

logger = setup_logger()


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


class CanvasAssignment(BaseModel):
    id: int
    name: str
    description: str | None = None
    html_url: str
    course_id: int
    created_at: str
    updated_at: str
    due_at: str | None = None


class CanvasAnnouncement(BaseModel):
    id: int
    title: str
    message: str | None = None
    html_url: str
    posted_at: str | None = None
    course_id: int


CanvasStage = Literal["pages", "assignments", "announcements"]


class CanvasConnectorCheckpoint(ConnectorCheckpoint):
    """Checkpoint state for resumable Canvas indexing.

    Fields:
        course_ids: Materialized list of course IDs to process.
        current_course_index: Index into course_ids for current course.
        stage: Which item type we're processing for the current course.
        next_url: Pagination cursor within the current stage. None means
            start from the first page; a URL means resume from that page.
    """

    course_ids: list[int] = []
    current_course_index: int = 0
    stage: CanvasStage = "pages"
    next_url: str | None = None
