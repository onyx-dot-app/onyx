from collections.abc import Iterator
from collections.abc import Sequence
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
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.db.enums import HierarchyNodeType
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
    published: bool | None = None
    unlock_at: str | None = None
    lock_at: str | None = None
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
            published=payload.get("published"),
            unlock_at=payload.get("unlock_at"),
            lock_at=payload.get("lock_at"),
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
    published: bool | None = None
    unlock_at: str | None = None
    lock_at: str | None = None
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
            published=payload.get("published"),
            unlock_at=payload.get("unlock_at"),
            lock_at=payload.get("lock_at"),
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
    delayed_post_at: str | None = None
    course_id: int

    @classmethod
    def from_api(cls, payload: dict[str, Any], course_id: int) -> "CanvasAnnouncement":
        return cls(
            id=payload["id"],
            title=payload["title"],
            message=payload.get("message"),
            html_url=payload["html_url"],
            posted_at=payload.get("posted_at"),
            delayed_post_at=payload.get("delayed_post_at"),
            course_id=course_id,
        )


class CanvasFile(BaseModel):
    id: int
    display_name: str
    filename: str
    url: str  # direct download URL
    content_type: str | None = None
    size: int | None = None
    hidden: bool | None = None
    locked: bool | None = None
    unlock_at: str | None = None
    lock_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    course_id: int

    @classmethod
    def from_api(cls, payload: dict[str, Any], course_id: int) -> "CanvasFile":
        return cls(
            id=payload["id"],
            display_name=payload.get("display_name", payload.get("filename", "")),
            filename=payload.get("filename", ""),
            url=payload.get("url", ""),
            content_type=payload.get("content-type") or payload.get("mime_class"),
            size=payload.get("size"),
            hidden=payload.get("hidden"),
            locked=payload.get("locked"),
            unlock_at=payload.get("unlock_at"),
            lock_at=payload.get("lock_at"),
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
            course_id=course_id,
        )


class CanvasModule(BaseModel):
    id: int
    name: str
    position: int | None = None
    published: bool | None = None
    unlock_at: str | None = None
    workflow_state: str | None = None
    course_id: int

    @classmethod
    def from_api(cls, payload: dict[str, Any], course_id: int) -> "CanvasModule":
        return cls(
            id=payload["id"],
            name=payload.get("name", ""),
            position=payload.get("position"),
            published=payload.get("published"),
            unlock_at=payload.get("unlock_at"),
            workflow_state=payload.get("workflow_state"),
            course_id=course_id,
        )


class CanvasModuleItem(BaseModel):
    id: int
    title: str
    item_type: str  # "Page", "Assignment", "File", "ExternalUrl", etc.
    content_id: int | None = None  # numeric id of the linked content
    html_url: str | None = None
    external_url: str | None = None
    published: bool | None = None
    module_id: int
    course_id: int

    @classmethod
    def from_api(
        cls, payload: dict[str, Any], module_id: int, course_id: int
    ) -> "CanvasModuleItem":
        return cls(
            id=payload["id"],
            title=payload.get("title", ""),
            item_type=payload.get("type", ""),
            content_id=payload.get("content_id"),
            html_url=payload.get("html_url"),
            external_url=payload.get("external_url"),
            published=payload.get("published"),
            module_id=module_id,
            course_id=course_id,
        )


class CanvasQuiz(BaseModel):
    id: int
    title: str
    description: str | None = None
    html_url: str
    quiz_type: str | None = None
    question_count: int | None = None
    published: bool | None = None
    unlock_at: str | None = None
    lock_at: str | None = None
    course_id: int
    created_at: str | None = None
    updated_at: str | None = None  # Canvas quizzes don't always have updated_at

    @classmethod
    def from_api(cls, payload: dict[str, Any], course_id: int) -> "CanvasQuiz":
        return cls(
            id=payload["id"],
            title=payload.get("title", ""),
            description=payload.get("description"),
            html_url=payload.get("html_url", ""),
            quiz_type=payload.get("quiz_type"),
            question_count=payload.get("question_count"),
            published=payload.get("published"),
            unlock_at=payload.get("unlock_at"),
            lock_at=payload.get("lock_at"),
            course_id=course_id,
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
        )


class CanvasDiscussion(BaseModel):
    id: int
    title: str
    message: str | None = None
    html_url: str
    posted_at: str | None = None
    course_id: int
    published: bool | None = None
    delayed_post_at: str | None = None
    lock_at: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any], course_id: int) -> "CanvasDiscussion":
        return cls(
            id=payload["id"],
            title=payload.get("title", ""),
            message=payload.get("message"),
            html_url=payload.get("html_url", ""),
            posted_at=payload.get("posted_at"),
            course_id=course_id,
            published=payload.get("published"),
            delayed_post_at=payload.get("delayed_post_at"),
            lock_at=payload.get("lock_at"),
        )


_RELEASED_WORKFLOW_STATES: set[str] = {"active", "available"}


def _optional_bool_field(canvas_object: BaseModel, field_name: str) -> bool | None:
    value = getattr(canvas_object, field_name, None)
    return value if isinstance(value, bool) else None


def _optional_str_field(canvas_object: BaseModel, field_name: str) -> str | None:
    value = getattr(canvas_object, field_name, None)
    return value if isinstance(value, str) else None


def _parse_canvas_datetime(datetime_str: str) -> datetime:
    return datetime.fromisoformat(datetime_str.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _passes_canvas_published_state(canvas_object: BaseModel) -> bool:
    published = _optional_bool_field(canvas_object, "published")
    if published is False:
        return False

    workflow_state = _optional_str_field(canvas_object, "workflow_state")
    if workflow_state is not None and workflow_state not in _RELEASED_WORKFLOW_STATES:
        return False

    return True


def _is_released(
    canvas_object: BaseModel,
    release_check_time: datetime,
    parent_module: CanvasModule | None = None,
    respect_release_dates: bool = True,
) -> bool:
    if not _passes_canvas_published_state(canvas_object):
        return False
    if parent_module is not None and not _is_released(
        parent_module,
        release_check_time,
        respect_release_dates=respect_release_dates,
    ):
        return False
    if not respect_release_dates:
        return True

    if _optional_bool_field(canvas_object, "hidden") is True:
        return False
    if _optional_bool_field(canvas_object, "locked") is True:
        return False

    unlock_at = _optional_str_field(canvas_object, "unlock_at")
    delayed_post_at = _optional_str_field(canvas_object, "delayed_post_at")
    release_at = unlock_at or delayed_post_at
    if release_at and _parse_canvas_datetime(release_at) > release_check_time:
        return False

    lock_at = _optional_str_field(canvas_object, "lock_at")
    if lock_at and _parse_canvas_datetime(lock_at) <= release_check_time:
        return False

    return True


def _parse_respect_release_dates(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off"}
    return bool(value)


CanvasStage: TypeAlias = Literal[
    "pages",
    "assignments",
    "announcements",
    "files",
    "modules",
    "quizzes",
    "discussions",
    "syllabus",
]


# Maps a Canvas module item `type` value to the doc_type prefix used in
# document IDs and folder IDs. Items whose type isn't in this map (SubHeader,
# ExternalUrl, ExternalTool, ...) are ignored when building the membership map.
_MODULE_ITEM_TYPE_TO_DOC_TYPE: dict[str, str] = {
    "Page": "page",
    "Assignment": "assignment",
    "File": "file",
    "Quiz": "quiz",
    "Discussion": "discussion",
}


_DOC_TYPE_DISPLAY_NAMES: dict[str, str] = {
    "page": "Pages",
    "assignment": "Assignments",
    "announcement": "Announcements",
    "file": "Files",
    "quiz": "Quizzes",
    "discussion": "Discussions",
    "syllabus": "Syllabus",
}


def _normalize_canvas_course_ids(
    course_ids: Sequence[int | str] | None,
) -> list[int] | None:
    if course_ids is None:
        return None

    normalized_course_ids: list[int] = []
    seen_course_ids: set[int] = set()
    for raw_course_id in course_ids:
        try:
            course_id = int(str(raw_course_id).strip())
        except ValueError as e:
            raise ValueError("Canvas course_ids must contain numeric course IDs") from e

        if course_id <= 0:
            raise ValueError("Canvas course_ids must contain positive course IDs")
        if course_id in seen_course_ids:
            continue

        seen_course_ids.add(course_id)
        normalized_course_ids.append(course_id)

    return normalized_course_ids


def _course_type_folder_id(course_id: int, doc_type: str) -> str:
    return f"canvas-type-course-{course_id}-{doc_type}"


def _module_type_folder_id(course_id: int, module_id: int, doc_type: str) -> str:
    return f"canvas-type-module-{course_id}-{module_id}-{doc_type}"


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
        course_ids: Sequence[int | str] | None = None,
        lti_context_id: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.canvas_base_url = canvas_base_url.rstrip("/").removesuffix("/api/v1")
        self.course_ids = _normalize_canvas_course_ids(course_ids)
        self.lti_context_id = lti_context_id
        self.batch_size = batch_size
        self._canvas_client: CanvasApiClient | None = None
        self._respect_release_dates = True
        self._release_check_time: datetime | None = None
        self._course_permissions_cache: dict[int, ExternalAccess | None] = {}
        # Maps course_id -> {(doc_type, content_id): module_id}.
        # Populated lazily on first use per course; persists for the lifetime
        # of the connector instance.
        self._module_membership_cache: dict[int, dict[tuple[str, int], int]] = {}
        self._unreleased_module_content_cache: dict[int, set[tuple[str, int]]] = {}
        # Cache CanvasCourse objects so hierarchy emission has the proper
        # display name without an extra round trip per call.
        self._courses_by_id: dict[int, CanvasCourse] = {}
        # Tracks which course-level type folder raw_node_ids have been
        # emitted in this connector instance's lifetime. Re-emission across
        # connector instances is fine — hierarchy upserts are idempotent.
        self._emitted_course_folders: set[str] = set()
        # Tracks course_ids whose starter hierarchy (course + modules +
        # module-level type folders) has already been emitted in this
        # connector instance.
        self._emitted_starter_hierarchy: set[int] = set()

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

    def _get_release_check_time(self) -> datetime:
        if self._release_check_time is None:
            self._release_check_time = datetime.now(timezone.utc)
        return self._release_check_time

    def _canvas_object_is_released(
        self,
        canvas_object: BaseModel,
        parent_module: CanvasModule | None = None,
    ) -> bool:
        return _is_released(
            canvas_object,
            release_check_time=self._get_release_check_time(),
            parent_module=parent_module,
            respect_release_dates=self._respect_release_dates,
        )

    def _content_is_released_for_module_membership(
        self, course_id: int, doc_type: str, content_id: int
    ) -> bool:
        membership = self._get_module_membership_map(course_id)
        if (doc_type, content_id) in membership:
            return True
        return (doc_type, content_id) not in self._unreleased_module_content_cache.get(
            course_id, set()
        )

    def _build_module_membership_map(
        self, course_id: int
    ) -> dict[tuple[str, int], int]:
        """Map (doc_type, content_id) -> module_id.

        When an item belongs to multiple modules, the first module by
        position wins (Canvas returns items in position order within a
        module; we sort modules by position).
        """
        mapping: dict[tuple[str, int], int] = {}
        content_in_unreleased_modules: set[tuple[str, int]] = set()
        try:
            modules = self._list_all_modules(course_id)
        except Exception as e:
            logger.warning(f"Failed to list modules for course {course_id}: {e}")
            self._unreleased_module_content_cache[course_id] = set()
            return mapping

        modules_sorted = sorted(
            modules, key=lambda m: (m.position is None, m.position or 0)
        )

        for module in modules_sorted:
            module_is_released = self._canvas_object_is_released(module)
            try:
                items = self._list_all_module_items(course_id, module.id)
            except Exception as e:
                logger.warning(
                    f"Failed to list items for module {module.id} "
                    f"in course {course_id}: {e}"
                )
                continue
            for item in items:
                doc_type = _MODULE_ITEM_TYPE_TO_DOC_TYPE.get(item.item_type)
                if doc_type is None or item.content_id is None:
                    continue
                key = (doc_type, item.content_id)
                if not module_is_released:
                    content_in_unreleased_modules.add(key)
                    continue
                if not self._canvas_object_is_released(item, parent_module=module):
                    content_in_unreleased_modules.add(key)
                    continue
                if key not in mapping:
                    mapping[key] = module.id
        self._unreleased_module_content_cache[course_id] = (
            content_in_unreleased_modules - set(mapping)
        )
        return mapping

    def _get_module_membership_map(self, course_id: int) -> dict[tuple[str, int], int]:
        """Cached accessor for the per-course module membership map."""
        if course_id not in self._module_membership_cache:
            self._module_membership_cache[course_id] = (
                self._build_module_membership_map(course_id)
            )
        return self._module_membership_cache[course_id]

    def _resolve_doc_parent(
        self, course_id: int, doc_type: str, content_id: int
    ) -> str:
        """Return the hierarchy node ID a doc of (doc_type, content_id) hangs from.

        If the item is a member of any module, returns the module-scoped type
        folder under that module. Otherwise returns the course-scoped type
        folder under the course.
        """
        membership = self._get_module_membership_map(course_id)
        module_id = membership.get((doc_type, content_id))
        if module_id is not None:
            return _module_type_folder_id(course_id, module_id, doc_type)
        return _course_type_folder_id(course_id, doc_type)

    def _make_course_node(
        self, course: CanvasCourse, permissions: ExternalAccess | None
    ) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=f"canvas-course-{course.id}",
            raw_parent_id=None,
            display_name=course.name or f"Course {course.id}",
            link=f"{self.canvas_base_url}/courses/{course.id}",
            node_type=HierarchyNodeType.COURSE,
            external_access=permissions,
        )

    def _make_module_node(
        self,
        course_id: int,
        module: CanvasModule,
        permissions: ExternalAccess | None,
    ) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=f"canvas-module-{course_id}-{module.id}",
            raw_parent_id=f"canvas-course-{course_id}",
            display_name=module.name,
            link=(
                f"{self.canvas_base_url}/courses/{course_id}"
                f"/modules#module_{module.id}"
            ),
            node_type=HierarchyNodeType.MODULE,
            external_access=permissions,
        )

    def _make_module_type_folder_node(
        self,
        course_id: int,
        module_id: int,
        doc_type: str,
        permissions: ExternalAccess | None,
    ) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=_module_type_folder_id(course_id, module_id, doc_type),
            raw_parent_id=f"canvas-module-{course_id}-{module_id}",
            display_name=_DOC_TYPE_DISPLAY_NAMES[doc_type],
            link=(
                f"{self.canvas_base_url}/courses/{course_id}"
                f"/modules#module_{module_id}"
            ),
            node_type=HierarchyNodeType.FOLDER,
            external_access=permissions,
        )

    def _make_course_type_folder_node(
        self,
        course_id: int,
        doc_type: str,
        permissions: ExternalAccess | None,
    ) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=_course_type_folder_id(course_id, doc_type),
            raw_parent_id=f"canvas-course-{course_id}",
            display_name=_DOC_TYPE_DISPLAY_NAMES[doc_type],
            link=f"{self.canvas_base_url}/courses/{course_id}",
            node_type=HierarchyNodeType.FOLDER,
            external_access=permissions,
        )

    def _iter_course_starter_hierarchy(
        self, course_id: int, permissions: ExternalAccess | None
    ) -> Iterator[HierarchyNode]:
        """Yield the hierarchy nodes that can be emitted purely from
        knowledge of the course's modules and items, in parent-before-child
        order:

            Course
            └── Module
                └── module-level Type folder (one per type with items)

        Course-level type folders are NOT emitted here — they are emitted
        lazily by the caller the first time a doc with a course-level type
        folder parent is yielded. This keeps the hierarchy free of empty
        folders.
        """
        course = self._get_course(course_id)
        if course is None:
            # Fall back to a synthetic course with just the ID so the rest
            # of the hierarchy still resolves.
            course = CanvasCourse(id=course_id)
        yield self._make_course_node(course, permissions)

        # Build the membership map (also lists modules + items). After this
        # call, _module_membership_cache[course_id] is populated.
        try:
            modules = self._list_modules(course_id)
        except Exception as e:
            logger.warning(f"Failed to list modules for course {course_id}: {e}")
            return

        modules_sorted = sorted(
            modules, key=lambda m: (m.position is None, m.position or 0)
        )
        membership = self._get_module_membership_map(course_id)
        # Invert membership: module_id -> set of doc_types that route to it.
        module_to_doc_types: dict[int, set[str]] = {}
        for (doc_type, _content_id), module_id in membership.items():
            module_to_doc_types.setdefault(module_id, set()).add(doc_type)

        for module in modules_sorted:
            yield self._make_module_node(course_id, module, permissions)
            for doc_type in sorted(module_to_doc_types.get(module.id, set())):
                yield self._make_module_type_folder_node(
                    course_id, module.id, doc_type, permissions
                )

    def _maybe_emit_course_type_folder(
        self,
        parent_raw_node_id: str | None,
        course_id: int,
        permissions: ExternalAccess | None,
    ) -> HierarchyNode | None:
        """Return a course-level type-folder HierarchyNode if `parent_raw_node_id`
        names one and we haven't yet emitted it; otherwise None.

        Used right before yielding a document so the folder lands in the
        runner before its child doc.
        """
        if parent_raw_node_id is None:
            return None
        prefix = f"canvas-type-course-{course_id}-"
        if not parent_raw_node_id.startswith(prefix):
            return None
        if parent_raw_node_id in self._emitted_course_folders:
            return None
        doc_type = parent_raw_node_id[len(prefix) :]
        if doc_type not in _DOC_TYPE_DISPLAY_NAMES:
            return None
        self._emitted_course_folders.add(parent_raw_node_id)
        return self._make_course_type_folder_node(course_id, doc_type, permissions)

    @retry(tries=3, delay=1, backoff=2)
    def _list_courses(self) -> list[CanvasCourse]:
        """Fetch all courses accessible to the authenticated user."""
        logger.debug("Fetching Canvas courses")

        courses: list[CanvasCourse] = []
        for page in self.canvas_client.paginate(
            "courses", params={"per_page": "100", "state[]": "available"}
        ):
            courses.extend(CanvasCourse.from_api(c) for c in page)
        for c in courses:
            self._courses_by_id[c.id] = c
        return courses

    def _get_course(self, course_id: int) -> CanvasCourse | None:
        """Fetch a single course by ID, with per-instance caching.

        Used by the hierarchy emission path so we always have the proper
        display name even when the connector instance was created mid-run
        (e.g., resumed from a checkpoint after course_ids was already
        materialized).
        """
        if course_id in self._courses_by_id:
            return self._courses_by_id[course_id]
        try:
            data, _ = self.canvas_client.get(f"courses/{course_id}")
        except Exception as e:
            logger.warning(f"Failed to fetch course {course_id}: {e}")
            return None
        if not isinstance(data, dict):
            return None
        course = CanvasCourse.from_api(data)
        self._courses_by_id[course_id] = course
        return course

    @retry(tries=3, delay=1, backoff=2)
    def _list_pages(self, course_id: int) -> list[CanvasPage]:
        """Fetch all pages for a given course."""
        logger.debug(f"Fetching pages for course {course_id}")

        pages: list[CanvasPage] = []
        for page in self.canvas_client.paginate(
            f"courses/{course_id}/pages",
            params={"per_page": "100", "include[]": "body", "published": "true"},
        ):
            for p in page:
                canvas_page = CanvasPage.from_api(p, course_id=course_id)
                if self._canvas_object_is_released(canvas_page):
                    pages.append(canvas_page)
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
            for a in page:
                assignment = CanvasAssignment.from_api(a, course_id=course_id)
                if self._canvas_object_is_released(assignment):
                    assignments.append(assignment)
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
            for a in page:
                announcement = CanvasAnnouncement.from_api(a, course_id=course_id)
                if self._canvas_object_is_released(announcement):
                    announcements.append(announcement)
        return announcements

    @retry(tries=3, delay=1, backoff=2)
    def _list_files(self, course_id: int) -> list[CanvasFile]:
        """Fetch all files for a given course."""
        logger.debug(f"Fetching files for course {course_id}")

        files: list[CanvasFile] = []
        for page in self.canvas_client.paginate(
            f"courses/{course_id}/files",
            params={"per_page": "100"},
        ):
            for f in page:
                file = CanvasFile.from_api(f, course_id=course_id)
                if self._canvas_object_is_released(file):
                    files.append(file)
        return files

    @retry(tries=3, delay=1, backoff=2)
    def _list_all_modules(self, course_id: int) -> list[CanvasModule]:
        """Fetch all modules for a given course."""
        logger.debug(f"Fetching modules for course {course_id}")

        modules: list[CanvasModule] = []
        for page in self.canvas_client.paginate(
            f"courses/{course_id}/modules",
            params={"per_page": "100"},
        ):
            modules.extend(CanvasModule.from_api(m, course_id=course_id) for m in page)
        return modules

    @retry(tries=3, delay=1, backoff=2)
    def _list_modules(self, course_id: int) -> list[CanvasModule]:
        """Fetch all released modules for a given course."""
        return [
            module
            for module in self._list_all_modules(course_id)
            if self._canvas_object_is_released(module)
        ]

    @retry(tries=3, delay=1, backoff=2)
    def _list_all_module_items(
        self, course_id: int, module_id: int
    ) -> list[CanvasModuleItem]:
        """Fetch all items for a given module."""
        logger.debug(
            f"Fetching module items for module {module_id} in course {course_id}"
        )

        items: list[CanvasModuleItem] = []
        for page in self.canvas_client.paginate(
            f"courses/{course_id}/modules/{module_id}/items",
            params={"per_page": "100"},
        ):
            for item_payload in page:
                item = CanvasModuleItem.from_api(
                    item_payload, module_id=module_id, course_id=course_id
                )
                items.append(item)
        return items

    @retry(tries=3, delay=1, backoff=2)
    def _list_module_items(
        self, course_id: int, module_id: int
    ) -> list[CanvasModuleItem]:
        """Fetch all released items for a given module."""
        return [
            item
            for item in self._list_all_module_items(course_id, module_id)
            if self._canvas_object_is_released(item)
        ]

    @retry(tries=3, delay=1, backoff=2)
    def _list_quizzes(self, course_id: int) -> list[CanvasQuiz]:
        """Fetch all published quizzes for a given course."""
        logger.debug(f"Fetching quizzes for course {course_id}")

        quizzes: list[CanvasQuiz] = []
        for page in self.canvas_client.paginate(
            f"courses/{course_id}/quizzes",
            params={"per_page": "100"},
        ):
            for q in page:
                quiz = CanvasQuiz.from_api(q, course_id=course_id)
                if not self._canvas_object_is_released(quiz):
                    continue
                quizzes.append(quiz)
        return quizzes

    @retry(tries=3, delay=1, backoff=2)
    def _list_discussions(self, course_id: int) -> list[CanvasDiscussion]:
        """Fetch all published discussion topics for a given course."""
        logger.debug(f"Fetching discussions for course {course_id}")

        discussions: list[CanvasDiscussion] = []
        for page in self.canvas_client.paginate(
            f"courses/{course_id}/discussion_topics",
            params={"per_page": "100"},
        ):
            for d in page:
                disc = CanvasDiscussion.from_api(d, course_id=course_id)
                if not self._canvas_object_is_released(disc):
                    continue
                # Skip announcement-type discussions (already fetched separately)
                if d.get("is_announcement"):
                    continue
                discussions.append(disc)
        return discussions

    @retry(tries=3, delay=1, backoff=2)
    def _get_syllabus(self, course_id: int) -> str | None:
        """Fetch the syllabus body for a course. Returns None if empty."""
        logger.debug(f"Fetching syllabus for course {course_id}")

        data, _ = self.canvas_client.get(
            f"courses/{course_id}",
            params={"include[]": "syllabus_body"},
        )
        if isinstance(data, dict):
            return data.get("syllabus_body")
        return None

    def _build_document(
        self,
        doc_id: str,
        link: str,
        text: str,
        semantic_identifier: str,
        doc_updated_at: datetime | None,
        course_id: int,
        doc_type: str,
        parent_hierarchy_raw_node_id: str,
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
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
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
            parent_hierarchy_raw_node_id=self._resolve_doc_parent(
                page.course_id, "page", page.page_id
            ),
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
            parent_hierarchy_raw_node_id=self._resolve_doc_parent(
                assignment.course_id, "assignment", assignment.id
            ),
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
            parent_hierarchy_raw_node_id=_course_type_folder_id(
                announcement.course_id, "announcement"
            ),
        )
        return document

    def _convert_file_to_document(self, file: CanvasFile) -> Document:
        """Convert a Canvas file to a Document.

        The file URL points to the direct download. The indexing pipeline
        handles extraction of text from PDFs, DOCX, PPTX, etc.
        """
        link = f"{self.canvas_base_url}/courses/{file.course_id}/files/{file.id}"

        text_parts = [file.display_name]
        if file.content_type:
            text_parts.append(f"File type: {file.content_type}")

        doc_updated_at = (
            datetime.fromisoformat(file.updated_at.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
            if file.updated_at
            else None
        )

        return self._build_document(
            doc_id=f"canvas-file-{file.course_id}-{file.id}",
            link=link,
            text="\n\n".join(text_parts),
            semantic_identifier=file.display_name or f"File {file.id}",
            doc_updated_at=doc_updated_at,
            course_id=file.course_id,
            doc_type="file",
            parent_hierarchy_raw_node_id=self._resolve_doc_parent(
                file.course_id, "file", file.id
            ),
        )

    def _convert_quiz_to_document(self, quiz: CanvasQuiz) -> Document:
        """Convert a Canvas quiz to a Document."""
        text_parts = [quiz.title]
        desc_text = parse_html_page_basic(quiz.description) if quiz.description else ""
        if desc_text:
            text_parts.append(desc_text)
        if quiz.quiz_type:
            text_parts.append(f"Quiz type: {quiz.quiz_type}")
        if quiz.question_count is not None:
            text_parts.append(f"Questions: {quiz.question_count}")

        doc_updated_at = (
            datetime.fromisoformat(quiz.updated_at.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
            if quiz.updated_at
            else None
        )

        return self._build_document(
            doc_id=f"canvas-quiz-{quiz.course_id}-{quiz.id}",
            link=quiz.html_url,
            text="\n\n".join(text_parts),
            semantic_identifier=quiz.title or f"Quiz {quiz.id}",
            doc_updated_at=doc_updated_at,
            course_id=quiz.course_id,
            doc_type="quiz",
            parent_hierarchy_raw_node_id=self._resolve_doc_parent(
                quiz.course_id, "quiz", quiz.id
            ),
        )

    def _convert_discussion_to_document(self, discussion: CanvasDiscussion) -> Document:
        """Convert a Canvas discussion topic to a Document."""
        text_parts = [discussion.title]
        msg_text = (
            parse_html_page_basic(discussion.message) if discussion.message else ""
        )
        if msg_text:
            text_parts.append(msg_text)

        doc_updated_at = (
            datetime.fromisoformat(
                discussion.posted_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            if discussion.posted_at
            else None
        )

        return self._build_document(
            doc_id=f"canvas-discussion-{discussion.course_id}-{discussion.id}",
            link=discussion.html_url,
            text="\n\n".join(text_parts),
            semantic_identifier=discussion.title or f"Discussion {discussion.id}",
            doc_updated_at=doc_updated_at,
            course_id=discussion.course_id,
            doc_type="discussion",
            parent_hierarchy_raw_node_id=self._resolve_doc_parent(
                discussion.course_id, "discussion", discussion.id
            ),
        )

    def _convert_syllabus_to_document(
        self, course_id: int, syllabus_body: str
    ) -> Document:
        """Convert a course syllabus to a Document."""
        text = parse_html_page_basic(syllabus_body)
        link = f"{self.canvas_base_url}/courses/{course_id}/assignments/syllabus"

        return self._build_document(
            doc_id=f"canvas-syllabus-{course_id}",
            link=link,
            text=f"Syllabus\n\n{text}" if text else "Syllabus",
            semantic_identifier="Syllabus",
            doc_updated_at=None,
            course_id=course_id,
            doc_type="syllabus",
            parent_hierarchy_raw_node_id=_course_type_folder_id(course_id, "syllabus"),
        )

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load and validate Canvas credentials."""
        access_token = credentials.get("canvas_access_token")
        if not access_token:
            raise ConnectorMissingCredentialError("Canvas")
        self._respect_release_dates = _parse_respect_release_dates(
            credentials.get("respect_release_dates", True)
        )

        try:
            client = CanvasApiClient(
                bearer_token=access_token,
                canvas_base_url=self.canvas_base_url,
            )
            if self.course_ids is None or len(self.course_ids) == 0:
                client.get("courses", params={"per_page": "1"})
            else:
                for course_id in self.course_ids:
                    course_payload, _ = client.get(f"courses/{course_id}")
                    if isinstance(course_payload, dict):
                        self._courses_by_id[course_id] = CanvasCourse.from_api(
                            course_payload
                        )
        except ValueError as e:
            raise ConnectorValidationError(f"Invalid Canvas base URL: {e}")
        except OnyxError as e:
            _handle_canvas_api_error(e)

        self._canvas_client = client
        return None

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: CanvasConnectorCheckpoint,
        include_permissions: bool = False,
    ) -> CheckpointOutput[CanvasConnectorCheckpoint]:
        """Shared implementation for load_from_checkpoint and load_from_checkpoint_with_perm_sync."""
        if not checkpoint.course_ids:
            self._release_check_time = datetime.now(timezone.utc)
        else:
            self._get_release_check_time()

        new_checkpoint = checkpoint.model_copy(deep=True)

        # First call: materialize the list of course IDs
        if not new_checkpoint.course_ids:
            if self.course_ids is not None:
                new_checkpoint.course_ids = list(self.course_ids)
                new_checkpoint.current_course_index = 0
                new_checkpoint.stage = "pages"
                logger.info(
                    "Found %d configured Canvas courses to process",
                    len(new_checkpoint.course_ids),
                )
                new_checkpoint.has_more = len(new_checkpoint.course_ids) > 0
                return new_checkpoint

            try:
                courses = self._list_courses()
            except Exception as e:
                logger.warning(f"Failed to list Canvas courses: {e}")
                new_checkpoint.has_more = True
                return new_checkpoint
            new_checkpoint.course_ids = [c.id for c in courses]
            new_checkpoint.current_course_index = 0
            new_checkpoint.stage = "pages"
            logger.info(f"Found {len(courses)} Canvas courses to process")
            new_checkpoint.has_more = len(new_checkpoint.course_ids) > 0
            if not new_checkpoint.has_more:
                self._release_check_time = None
            return new_checkpoint

        # All courses done
        if new_checkpoint.current_course_index >= len(new_checkpoint.course_ids):
            new_checkpoint.has_more = False
            self._release_check_time = None
            return new_checkpoint

        course_id = new_checkpoint.course_ids[new_checkpoint.current_course_index]
        stage = new_checkpoint.stage

        _VALID_STAGES: set[str] = {
            "pages",
            "assignments",
            "announcements",
            "files",
            "modules",
            "quizzes",
            "discussions",
            "syllabus",
        }
        if stage not in _VALID_STAGES:
            raise ValueError(f"Invalid checkpoint stage: {stage!r}")

        # Hierarchy nodes attached to this course's perms only when we are
        # running the perm-sync flavor of this method.
        hierarchy_perms = (
            self._get_course_permissions(course_id) if include_permissions else None
        )

        # Emit starter hierarchy once per course per connector-instance.
        # This ensures regular indexing populates the Course/Module/folder
        # nodes — without this, PUBLIC connectors (which never run
        # retrieve_all_slim_docs_perm_sync) would have no hierarchy at all
        # and every doc would fall back to the SOURCE root.
        if course_id not in self._emitted_starter_hierarchy:
            for node in self._iter_course_starter_hierarchy(course_id, hierarchy_perms):
                yield node
            self._emitted_starter_hierarchy.add(course_id)

        def _in_time_window(timestamp_str: str) -> bool:
            ts = (
                datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                .astimezone(timezone.utc)
                .timestamp()
            )
            return start < ts <= end

        def _maybe_attach_permissions(document: Document) -> Document:
            if include_permissions:
                document.external_access = self._get_course_permissions(course_id)
            return document

        def _emit_doc(
            document: Document,
        ) -> Iterator[Document | HierarchyNode]:
            """Yield a doc — preceded by its course-level type folder
            HierarchyNode if we haven't emitted that folder yet."""
            folder = self._maybe_emit_course_type_folder(
                document.parent_hierarchy_raw_node_id, course_id, hierarchy_perms
            )
            if folder is not None:
                yield folder
            yield _maybe_attach_permissions(document)

        # Fetch one page of API results for the current stage.
        # If next_url is set, we're resuming mid-pagination.
        # --- Syllabus is a special stage (single fetch, not paginated) ---
        if stage == "syllabus":
            try:
                syllabus_body = self._get_syllabus(course_id)
            except Exception as e:
                logger.warning(f"Failed to fetch syllabus for course {course_id}: {e}")
                # Syllabus is last stage — advance to next course
                new_checkpoint.advance_course()
                new_checkpoint.has_more = new_checkpoint.current_course_index < len(
                    new_checkpoint.course_ids
                )
                if not new_checkpoint.has_more:
                    self._release_check_time = None
                return new_checkpoint

            if syllabus_body:
                try:
                    doc = self._convert_syllabus_to_document(course_id, syllabus_body)
                    yield from _emit_doc(doc)
                except Exception as e:
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=f"canvas-syllabus-{course_id}",
                            document_link=(
                                f"{self.canvas_base_url}/courses/{course_id}"
                                "/assignments/syllabus"
                            ),
                        ),
                        failure_message=f"Failed to process syllabus: {e}",
                        exception=e,
                    )

            new_checkpoint.advance_course()
            new_checkpoint.has_more = new_checkpoint.current_course_index < len(
                new_checkpoint.course_ids
            )
            if not new_checkpoint.has_more:
                self._release_check_time = None
            return new_checkpoint

        # --- Modules stage: fetch modules + items (not paginated via stage_config) ---
        if stage == "modules":
            try:
                modules = self._list_modules(course_id)
            except Exception as e:
                logger.warning(f"Failed to fetch modules for course {course_id}: {e}")
                new_checkpoint.next_url = None
                new_checkpoint.stage = "quizzes"
                new_checkpoint.has_more = True
                return new_checkpoint

            for module in modules:
                try:
                    items = self._list_module_items(course_id, module.id)
                except Exception as e:
                    logger.warning(
                        f"Failed to fetch items for module {module.id} "
                        f"in course {course_id}: {e}"
                    )
                    continue
                for mi in items:
                    # Module items are structural references; we index
                    # the actual content (pages, assignments, files) in
                    # their own stages. Skip SubHeader items entirely.
                    pass

            # Modules stage complete — advance
            new_checkpoint.next_url = None
            new_checkpoint.stage = "quizzes"
            new_checkpoint.has_more = True
            return new_checkpoint

        # --- Standard paginated stages ---
        stage_config: dict[str, dict[str, Any]] = {
            "pages": {
                "endpoint": f"courses/{course_id}/pages",
                "params": {"per_page": "100", "include[]": "body", "published": "true"},
            },
            "assignments": {
                "endpoint": f"courses/{course_id}/assignments",
                "params": {"per_page": "100", "published": "true"},
            },
            "announcements": {
                "endpoint": "announcements",
                "params": {
                    "per_page": "100",
                    "context_codes[]": f"course_{course_id}",
                    "active_only": "true",
                },
            },
            "files": {
                "endpoint": f"courses/{course_id}/files",
                "params": {"per_page": "100"},
            },
            "quizzes": {
                "endpoint": f"courses/{course_id}/quizzes",
                "params": {"per_page": "100"},
            },
            "discussions": {
                "endpoint": f"courses/{course_id}/discussion_topics",
                "params": {"per_page": "100"},
            },
        }
        config = stage_config[stage]

        try:
            if new_checkpoint.next_url:
                response, result_next_url = self.canvas_client.get(
                    full_url=new_checkpoint.next_url
                )
            else:
                response, result_next_url = self.canvas_client.get(
                    config["endpoint"], params=config["params"]
                )
        except OnyxError as oe:
            # Re-raise security errors from _parse_next_link (host/scheme
            # mismatch on pagination URLs) — these must not be silenced.
            # Security errors have no HTTP status code override (they are
            # raised locally, not from an API response).
            is_api_error = oe._status_code_override is not None
            if not is_api_error:
                raise
            logger.warning(f"Failed to fetch {stage} for course {course_id}: {oe}")
            new_checkpoint.has_more = True
            return new_checkpoint
        except Exception as e:
            logger.warning(f"Failed to fetch {stage} for course {course_id}: {e}")
            new_checkpoint.has_more = True
            return new_checkpoint

        # Process fetched items
        for item in response or []:
            try:
                if stage == "pages":
                    page = CanvasPage.from_api(item, course_id=course_id)
                    if not self._canvas_object_is_released(page):
                        continue
                    if not self._content_is_released_for_module_membership(
                        course_id, "page", page.page_id
                    ):
                        continue
                    if not page.updated_at or not _in_time_window(page.updated_at):
                        continue
                    doc = self._convert_page_to_document(page)
                    yield from _emit_doc(doc)

                elif stage == "assignments":
                    assignment = CanvasAssignment.from_api(item, course_id=course_id)
                    if not self._canvas_object_is_released(assignment):
                        continue
                    if not self._content_is_released_for_module_membership(
                        course_id, "assignment", assignment.id
                    ):
                        continue
                    if not assignment.updated_at or not _in_time_window(
                        assignment.updated_at
                    ):
                        continue
                    doc = self._convert_assignment_to_document(assignment)
                    yield from _emit_doc(doc)

                elif stage == "announcements":
                    announcement = CanvasAnnouncement.from_api(
                        item, course_id=course_id
                    )
                    if not self._canvas_object_is_released(announcement):
                        continue
                    if not announcement.posted_at:
                        logger.debug(
                            f"Skipping announcement {announcement.id} in "
                            f"course {course_id}: no posted_at"
                        )
                        continue
                    if not _in_time_window(announcement.posted_at):
                        continue
                    doc = self._convert_announcement_to_document(announcement)
                    yield from _emit_doc(doc)

                elif stage == "files":
                    file = CanvasFile.from_api(item, course_id=course_id)
                    if not self._canvas_object_is_released(file):
                        continue
                    if not self._content_is_released_for_module_membership(
                        course_id, "file", file.id
                    ):
                        continue
                    if not file.updated_at or not _in_time_window(file.updated_at):
                        continue
                    doc = self._convert_file_to_document(file)
                    yield from _emit_doc(doc)

                elif stage == "quizzes":
                    quiz = CanvasQuiz.from_api(item, course_id=course_id)
                    if not self._canvas_object_is_released(quiz):
                        continue
                    if not self._content_is_released_for_module_membership(
                        course_id, "quiz", quiz.id
                    ):
                        continue
                    if not quiz.updated_at or not _in_time_window(quiz.updated_at):
                        continue
                    doc = self._convert_quiz_to_document(quiz)
                    yield from _emit_doc(doc)

                elif stage == "discussions":
                    disc = CanvasDiscussion.from_api(item, course_id=course_id)
                    if not self._canvas_object_is_released(disc):
                        continue
                    if not self._content_is_released_for_module_membership(
                        course_id, "discussion", disc.id
                    ):
                        continue
                    if item.get("is_announcement"):
                        continue
                    if not disc.posted_at:
                        continue
                    if not _in_time_window(disc.posted_at):
                        continue
                    doc = self._convert_discussion_to_document(disc)
                    yield from _emit_doc(doc)

            except Exception as e:
                item_id = item.get("id") or item.get("page_id", "unknown")
                if stage == "pages":
                    doc_link = (
                        f"{self.canvas_base_url}/courses/{course_id}"
                        f"/pages/{item.get('url', '')}"
                    )
                else:
                    doc_link = item.get("html_url", "")
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=f"canvas-{stage.removesuffix('s')}-{course_id}-{item_id}",
                        document_link=doc_link,
                    ),
                    failure_message=f"Failed to process {stage.removesuffix('s')}: {e}",
                    exception=e,
                )

        # If there are more pages, save the cursor and return
        if result_next_url:
            new_checkpoint.next_url = result_next_url
        else:
            # Stage complete — advance to next stage
            new_checkpoint.next_url = None
            next_stages: dict[str, CanvasStage | None] = {
                "pages": "assignments",
                "assignments": "announcements",
                "announcements": "files",
                "files": "modules",
                # modules handled specially above; quizzes comes after
                "quizzes": "discussions",
                "discussions": "syllabus",
                # syllabus handled specially above
            }
            next_stage = next_stages[stage]
            if next_stage:
                new_checkpoint.stage = next_stage
            else:
                new_checkpoint.advance_course()

        new_checkpoint.has_more = new_checkpoint.current_course_index < len(
            new_checkpoint.course_ids
        )
        if not new_checkpoint.has_more:
            self._release_check_time = None
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

    def _flush_batch(
        self,
        _batch: list[SlimDocument | HierarchyNode],
        callback: IndexingHeartbeatInterface | None,
    ) -> list[SlimDocument | HierarchyNode]:
        """Yield the batch if non-empty and check for stop signal."""
        if callback and callback.should_stop():
            raise RuntimeError("canvas_perm_sync: Stop signal detected")
        return []

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Return slim documents with permission info for all courses.

        Hierarchy emitted per course:

            canvas-course-{course_id}
            ├── canvas-type-course-{course_id}-{doc_type}      (FOLDER)
            │   └── slim docs not in any module
            └── canvas-module-{course_id}-{module_id}          (MODULE)
                └── canvas-type-module-{course_id}-{module_id}-{doc_type}  (FOLDER)
                    └── slim docs that belong to this module

        A type folder is only emitted if at least one slim doc actually hangs
        from it.
        """
        self._release_check_time = datetime.now(timezone.utc)
        batch: list[SlimDocument | HierarchyNode] = []
        courses = (
            [
                self._get_course(course_id)
                or CanvasCourse(id=course_id, name=f"Course {course_id}")
                for course_id in self.course_ids
            ]
            if self.course_ids is not None
            else self._list_courses()
        )

        def _maybe_flush() -> Iterator[list[SlimDocument | HierarchyNode]]:
            nonlocal batch
            if len(batch) >= self.batch_size:
                yield batch
                batch = self._flush_batch(batch, callback)

        for course in courses:
            course_id = course.id
            permissions = self._get_course_permissions(course_id)

            # 1. Course + modules + module-level type folders. The starter
            # helper emits everything we know up front from the membership
            # map.
            for node in self._iter_course_starter_hierarchy(course_id, permissions):
                batch.append(node)
                yield from _maybe_flush()
            self._emitted_starter_hierarchy.add(course_id)
            membership = self._get_module_membership_map(course_id)

            def _emit_slim(
                doc_type: str, doc_id: str, content_id: int | None
            ) -> Iterator[list[SlimDocument | HierarchyNode]]:
                if content_id is not None and (doc_type, content_id) in membership:
                    module_id = membership[(doc_type, content_id)]
                    parent = _module_type_folder_id(course_id, module_id, doc_type)
                else:
                    parent = _course_type_folder_id(course_id, doc_type)
                folder = self._maybe_emit_course_type_folder(
                    parent, course_id, permissions
                )
                if folder is not None:
                    batch.append(folder)
                    yield from _maybe_flush()
                batch.append(
                    SlimDocument(
                        id=doc_id,
                        external_access=permissions,
                        parent_hierarchy_raw_node_id=parent,
                    )
                )
                yield from _maybe_flush()

            # 2. Slim docs. Each doc auto-emits its course-level type
            # folder lazily (before itself) so empty folders are never
            # created. Pages/assignments/etc have no try/except: a
            # mid-fetch failure must abort the whole sync rather than risk
            # generic_doc_sync mass-revoking permissions.
            for page in self._list_pages(course_id):
                if not self._content_is_released_for_module_membership(
                    course_id, "page", page.page_id
                ):
                    continue
                yield from _emit_slim(
                    "page", f"canvas-page-{course_id}-{page.page_id}", page.page_id
                )
            for assignment in self._list_assignments(course_id):
                if not self._content_is_released_for_module_membership(
                    course_id, "assignment", assignment.id
                ):
                    continue
                yield from _emit_slim(
                    "assignment",
                    f"canvas-assignment-{course_id}-{assignment.id}",
                    assignment.id,
                )
            for announcement in self._list_announcements(course_id):
                yield from _emit_slim(
                    "announcement",
                    f"canvas-announcement-{course_id}-{announcement.id}",
                    None,
                )
            for file in self._list_files(course_id):
                if not self._content_is_released_for_module_membership(
                    course_id, "file", file.id
                ):
                    continue
                yield from _emit_slim(
                    "file", f"canvas-file-{course_id}-{file.id}", file.id
                )
            for quiz in self._list_quizzes(course_id):
                if not self._content_is_released_for_module_membership(
                    course_id, "quiz", quiz.id
                ):
                    continue
                yield from _emit_slim(
                    "quiz", f"canvas-quiz-{course_id}-{quiz.id}", quiz.id
                )
            for disc in self._list_discussions(course_id):
                if not self._content_is_released_for_module_membership(
                    course_id, "discussion", disc.id
                ):
                    continue
                yield from _emit_slim(
                    "discussion",
                    f"canvas-discussion-{course_id}-{disc.id}",
                    disc.id,
                )

            try:
                syllabus_body = self._get_syllabus(course_id)
            except Exception as e:
                logger.warning(f"Failed to fetch syllabus for course {course_id}: {e}")
                syllabus_body = None
            if syllabus_body:
                yield from _emit_slim("syllabus", f"canvas-syllabus-{course_id}", None)

            if callback:
                callback.progress("canvas_perm_sync", 1)

        if batch:
            yield batch
            batch = []
        self._release_check_time = None
