"""FastAPI router for scheduled tasks.

Thin HTTP layer over ``onyx.db.scheduled_task``. Every handler:

1. Validates request payload via Pydantic.
2. Calls a DB op (which enforces ownership + raises ``OnyxError``).
3. Optionally enqueues the executor task on the ``scheduled_tasks`` queue.

The router is mounted twice: at ``/scheduled-tasks`` for the chat app, and
under ``/build`` (``backend/onyx/server/features/build/api.py``) behind the
Craft gate for the Craft pages.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StringConstraints,
    model_validator,
)
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.background.celery.versioned_apps.client import app as celery_app
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import (
    Permission,
    ScheduledTaskRunStatus,
    ScheduledTaskStatus,
    ScheduledTaskTriggerSource,
)
from onyx.db.integration_policy import list_task_integration_links
from onyx.db.models import ScheduledTask, ScheduledTaskRun, User
from onyx.db.scheduled_task import (
    create_scheduled_task,
    get_run_of_chat_session,
    get_scheduled_task,
    has_in_flight_run_for_task,
    insert_run,
    latest_runs_for_tasks,
    list_runs_for_task,
    list_scheduled_tasks_for_user,
    mark_runs_viewed,
    soft_delete_scheduled_task,
    unread_run_counts_for_user,
    update_scheduled_task,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.craft import list_task_integration_views
from onyx.integrations.policy import parse_action_settings
from onyx.scheduled_tasks.enqueue import send_scheduled_run
from onyx.server.features.build.models import TaskIntegrationView
from onyx.server.features.build.scheduled_tasks.schedule import (
    EDITOR_PAYLOAD_MODELS,
    EditorMode,
    EditorPayload,
    compile_to_cron,
    human_readable,
    next_n_fires,
)
from onyx.tools.models import IntegrationLinkConfiguration
from onyx.utils.datetime import datetime_to_utc
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Number of future fires returned by the detail endpoint for UI preview.
NEXT_RUNS_PREVIEW_COUNT = 3

# Default and max page sizes for the runs listing endpoint.
RUNS_DEFAULT_PAGE_SIZE = 50
RUNS_MAX_PAGE_SIZE = 100

# Max run IDs accepted by one bulk mark-viewed request.
RUNS_VIEWED_MAX_ENTRIES = 1000


router = APIRouter(prefix="/scheduled-tasks")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class _Forbid(BaseModel):
    """Base model that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid")


TaskName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
TASK_PROMPT_MAX_CHARS = 20_000
TaskPrompt = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=TASK_PROMPT_MAX_CHARS
    ),
]
# A task saved before the limit can keep its longer prompt; see ``patch_task``.
EditedTaskPrompt = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1)
]


def _dispatch_editor_payload(data: Any) -> Any:
    """``model_validator(mode="before")`` helper.

    Routes a raw ``editor_payload`` dict to the typed payload model that
    pairs with ``editor_mode``. After this runs, ``editor_payload`` is a
    fully validated ``IntervalPayload`` / ``DailyWeeklyPayload`` /
    ``AdvancedPayload`` instance — never a raw dict. Mismatched shapes
    surface as Pydantic ``ValidationError`` → 422 at the FastAPI layer.
    """
    if not isinstance(data, dict):
        return data
    mode = data.get("editor_mode")
    raw = data.get("editor_payload")
    if not isinstance(raw, dict):
        # ``editor_mode`` validation (Literal) catches invalid modes; ``None``
        # / non-dict payloads fall through to the field-level required check.
        return data
    model_cls = EDITOR_PAYLOAD_MODELS.get(mode) if isinstance(mode, str) else None
    if model_cls is None:
        # Let the ``editor_mode`` Literal validator produce the canonical
        # error message; leave the raw payload in place.
        return data
    data["editor_payload"] = model_cls.model_validate(raw)
    return data


class ScheduledTaskCreate(_Forbid):
    """Request body for ``POST /scheduled-tasks``."""

    name: TaskName
    prompt: TaskPrompt
    editor_mode: EditorMode
    editor_payload: EditorPayload
    status: ScheduledTaskStatus = ScheduledTaskStatus.ACTIVE
    run_immediately: bool = False
    integrations: list[IntegrationLinkConfiguration] | None = None

    _dispatch = model_validator(mode="before")(_dispatch_editor_payload)


class ScheduledTaskPatch(_Forbid):
    """Request body for ``PATCH /scheduled-tasks/{id}``.

    All fields are optional; ``editor_mode`` and ``editor_payload`` must be
    supplied together (enforced below).
    """

    name: TaskName | None = None
    prompt: EditedTaskPrompt | None = None
    editor_mode: EditorMode | None = None
    editor_payload: EditorPayload | None = None
    status: ScheduledTaskStatus | None = None
    integrations: list[IntegrationLinkConfiguration] | None = None

    _dispatch = model_validator(mode="before")(_dispatch_editor_payload)

    @model_validator(mode="after")
    def _editor_pair_consistency(self) -> ScheduledTaskPatch:
        if (self.editor_mode is None) != (self.editor_payload is None):
            raise ValueError("editor_mode and editor_payload must be supplied together")
        return self


class RunSummary(BaseModel):
    """Shape used both as ``last_run`` on the list payload and as a row in
    the paginated runs listing.
    """

    id: str
    status: ScheduledTaskRunStatus
    trigger_source: ScheduledTaskTriggerSource
    started_at: datetime
    finished_at: datetime | None
    chat_session_id: str | None
    summary: str | None
    skip_reason: str | None
    error_class: str | None
    error_detail: str | None
    revision: int
    viewed_revision: int | None

    @classmethod
    def from_model(cls, run: ScheduledTaskRun) -> "RunSummary":
        return cls(
            id=str(run.id),
            status=run.status,
            trigger_source=run.trigger_source,
            started_at=run.started_at,
            finished_at=run.finished_at,
            chat_session_id=(
                str(run.chat_session_id) if run.chat_session_id is not None else None
            ),
            summary=run.summary,
            skip_reason=run.skip_reason,
            error_class=run.error_class,
            error_detail=run.error_detail,
            revision=run.version,
            viewed_revision=run.viewed_revision,
        )


class ScheduledRunContextResponse(BaseModel):
    """The run of a scheduled-run session, for the banner above its chat."""

    run_id: str
    task_id: str
    task_name: str
    status: ScheduledTaskRunStatus
    started_at: datetime
    finished_at: datetime | None
    revision: int
    viewed_revision: int | None

    @classmethod
    def from_run(cls, run: ScheduledTaskRun) -> "ScheduledRunContextResponse":
        return cls(
            run_id=str(run.id),
            task_id=str(run.task_id),
            task_name=run.task.name,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            revision=run.version,
            viewed_revision=run.viewed_revision,
        )


class _ScheduledTaskBase(BaseModel):
    id: str
    name: str
    human_readable_schedule: str
    cron_expression: str
    editor_mode: str
    status: ScheduledTaskStatus
    next_run_at: datetime | None
    last_run: RunSummary | None
    created_at: datetime
    updated_at: datetime


class ScheduledTaskListItem(_ScheduledTaskBase):
    """Row in ``GET /scheduled-tasks``."""

    unviewed_run_count: int


class ScheduledTaskDetail(_ScheduledTaskBase):
    """Response for ``GET /scheduled-tasks/{id}`` and the mutating endpoints
    that return the full task.
    """

    prompt: str
    next_runs: list[datetime]
    integrations: list[IntegrationLinkConfiguration]


class ScheduledTaskListResponse(BaseModel):
    items: list[ScheduledTaskListItem]


class RunListResponse(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None


class UnviewedTaskCountResponse(BaseModel):
    count: int


class RunsViewedRequest(_Forbid):
    revisions: dict[UUID, PositiveInt] = Field(max_length=RUNS_VIEWED_MAX_ENTRIES)


class RunNowResponse(BaseModel):
    run_id: str
    status: ScheduledTaskRunStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_fields(
    task: ScheduledTask, last_run: ScheduledTaskRun | None
) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "name": task.name,
        "human_readable_schedule": human_readable(task.cron_expression),
        "cron_expression": task.cron_expression,
        "editor_mode": task.editor_mode,
        "status": task.status,
        "next_run_at": task.next_run_at,
        "last_run": RunSummary.from_model(last_run) if last_run is not None else None,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _detail(db_session: Session, task: ScheduledTask) -> ScheduledTaskDetail:
    next_runs: list[datetime] = []
    if task.status == ScheduledTaskStatus.ACTIVE:
        next_runs = next_n_fires(
            task.cron_expression,
            datetime.now(tz=timezone.utc),
            NEXT_RUNS_PREVIEW_COUNT,
        )
    return ScheduledTaskDetail(
        **_base_fields(task, latest_runs_for_tasks(db_session, [task.id]).get(task.id)),
        prompt=task.prompt,
        next_runs=next_runs,
        integrations=[
            IntegrationLinkConfiguration(
                integration_id=link.integration_id,
                action_settings=parse_action_settings(link.action_settings),
            )
            for link in list_task_integration_links(db_session, task.id)
        ],
    )


def _encode_cursor(run: ScheduledTaskRun) -> str:
    raw = f"{run.started_at.isoformat()}|{run.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    """``None`` and the empty string both mean "first page"."""
    if not cursor:
        return None
    try:
        started_at, run_id = (
            base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        )
        return datetime_to_utc(datetime.fromisoformat(started_at)), UUID(run_id)
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Invalid cursor") from e


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
def list_scheduled_tasks(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ScheduledTaskListResponse:
    """List the caller's scheduled tasks, newest first."""
    tasks = list_scheduled_tasks_for_user(db_session=db_session, user_id=user.id)
    unviewed = unread_run_counts_for_user(db_session=db_session, user_id=user.id)
    last_runs = latest_runs_for_tasks(db_session, [task.id for task in tasks])
    items = [
        ScheduledTaskListItem(
            **_base_fields(task, last_runs.get(task.id)),
            unviewed_run_count=unviewed.get(task.id, 0),
        )
        for task in tasks
    ]
    return ScheduledTaskListResponse(items=items)


@router.get("/unviewed-count")
def get_unviewed_task_count(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> UnviewedTaskCountResponse:
    """Number of the caller's tasks with run results they have not opened."""
    unviewed = unread_run_counts_for_user(db_session=db_session, user_id=user.id)
    return UnviewedTaskCountResponse(count=len(unviewed))


# Declared before ``/{task_id}`` so the literal path wins.
@router.get("/action-policies")
def list_new_task_action_policies(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[TaskIntegrationView]:
    """The catalog a new task starts from."""
    return list_task_integration_views(db_session, user, None)


@router.get("/chat-sessions/{chat_session_id}/run")
def get_chat_session_run(
    chat_session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ScheduledRunContextResponse | None:
    """The run of a chat, for its banner. None: the chat is not a run. The
    chat view asks on every open, so a normal chat is not an error."""
    run = get_run_of_chat_session(db_session, chat_session_id, user.id)
    return ScheduledRunContextResponse.from_run(run) if run is not None else None


@router.post("")
def create_task(
    request: ScheduledTaskCreate,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ScheduledTaskDetail:
    """Create a new scheduled task.

    Pipeline:
      1. Compile ``editor_mode`` + ``editor_payload`` to a canonical cron.
      2. Insert via ``create_scheduled_task`` (which computes ``next_run_at``
         when the task is created ACTIVE).
      3. If ``run_immediately`` is set, insert a ``manual_run_now`` run row
         and enqueue the executor. Does NOT touch ``next_run_at``.
    """
    cron_expression = compile_to_cron(request.editor_payload)

    task = create_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        name=request.name,
        prompt=request.prompt,
        cron_expression=cron_expression,
        editor_mode=request.editor_mode,
        status=request.status,
        integrations=request.integrations,
    )

    if request.run_immediately:
        run = insert_run(
            db_session=db_session,
            task_id=task.id,
            trigger_source=ScheduledTaskTriggerSource.MANUAL_RUN_NOW,
            status=ScheduledTaskRunStatus.QUEUED,
        )
        db_session.commit()
        # Enqueue only after the row is durably persisted so the worker
        # cannot race ahead of its own input.
        send_scheduled_run(celery_app, run.id, get_current_tenant_id())
    else:
        db_session.commit()

    db_session.refresh(task)
    return _detail(db_session, task)


@router.get("/{task_id}")
def get_task(
    task_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ScheduledTaskDetail:
    """Fetch one task + the next 3 fire times for the UI preview."""
    task = get_scheduled_task(db_session=db_session, task_id=task_id, user_id=user.id)
    return _detail(db_session, task)


@router.patch("/{task_id}")
def patch_task(
    task_id: UUID,
    request: ScheduledTaskPatch,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ScheduledTaskDetail:
    """Apply a partial update.

    If ``editor_mode`` + ``editor_payload`` are provided, the cron is
    recompiled before being handed to ``update_scheduled_task``. The DB op
    handles ``next_run_at`` recomputation (schedule change, pause/resume) on
    its own.
    """
    if (
        request.prompt is not None
        and len(request.prompt) > TASK_PROMPT_MAX_CHARS
        and request.prompt
        != get_scheduled_task(
            db_session=db_session, task_id=task_id, user_id=user.id
        ).prompt.strip()
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"The prompt can have at most {TASK_PROMPT_MAX_CHARS} characters",
        )
    cron_expression: str | None = None
    if request.editor_payload is not None:
        # ``_editor_pair_consistency`` already guaranteed editor_mode is set
        # whenever editor_payload is — no runtime check needed here.
        cron_expression = compile_to_cron(request.editor_payload)

    task = update_scheduled_task(
        db_session=db_session,
        task_id=task_id,
        user_id=user.id,
        name=request.name,
        prompt=request.prompt,
        cron_expression=cron_expression,
        editor_mode=request.editor_mode,
        status=request.status,
        integrations=request.integrations,
    )
    db_session.commit()
    db_session.refresh(task)
    return _detail(db_session, task)


@router.delete("/{task_id}")
def delete_task(
    task_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> Response:
    """Soft-delete a task. Deleting an already-deleted task is a no-op; a
    task that is missing or owned by another user is a 404."""
    soft_delete_scheduled_task(db_session=db_session, task_id=task_id, user_id=user.id)
    db_session.commit()
    return Response(status_code=204)


@router.post("/{task_id}/run-now")
def run_now(
    task_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> RunNowResponse:
    """Fire a one-off ``manual_run_now`` execution.

    Allowed on PAUSED tasks. A 409 while a run is QUEUED or RUNNING. Does NOT mutate ``next_run_at`` — that's
    the dispatcher's job for recurring fires.
    """
    # The task row lock serializes run-now calls, so only one run starts.
    task = get_scheduled_task(
        db_session=db_session, task_id=task_id, user_id=user.id, lock=True
    )
    if has_in_flight_run_for_task(db_session=db_session, task_id=task.id):
        raise OnyxError(
            OnyxErrorCode.CONFLICT, "A run of this task is already in progress"
        )
    run = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.MANUAL_RUN_NOW,
        status=ScheduledTaskRunStatus.QUEUED,
    )
    db_session.commit()
    send_scheduled_run(celery_app, run.id, get_current_tenant_id())
    return RunNowResponse(run_id=str(run.id), status=run.status)


@router.get("/{task_id}/runs")
def list_task_runs(
    task_id: UUID,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=RUNS_DEFAULT_PAGE_SIZE, ge=1, le=RUNS_MAX_PAGE_SIZE),
    unviewed: bool = Query(default=False),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> RunListResponse:
    """Paginated run history for a task, newest first.

    ``cursor`` is the opaque ``next_cursor`` of the previous page. ``next_cursor`` is ``None`` when the last page is
    reached. ``unviewed`` keeps only runs with results the owner has not
    opened.

    Raises ``OnyxError(NOT_FOUND)`` when the task is missing, soft-deleted,
    or owned by another user (ownership check happens inside the DB op).
    """
    runs = list_runs_for_task(
        db_session=db_session,
        task_id=task_id,
        user_id=user.id,
        cursor=_decode_cursor(cursor),
        limit=limit,
        unviewed_only=unviewed,
    )
    # A full page may be the last one; the client stops at an empty page.
    return RunListResponse(
        items=[RunSummary.from_model(run) for run in runs],
        next_cursor=_encode_cursor(runs[-1]) if len(runs) == limit else None,
    )


@router.patch("/{task_id}/runs/viewed")
def view_task_runs(
    task_id: UUID,
    body: RunsViewedRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> RunListResponse:
    try:
        runs = mark_runs_viewed(
            db_session=db_session,
            task_id=task_id,
            user_id=user.id,
            revisions=body.revisions,
        )
    except ValueError as error:
        raise OnyxError(OnyxErrorCode.CONFLICT, str(error)) from error
    response = RunListResponse(
        items=[RunSummary.from_model(run) for run in runs], next_cursor=None
    )
    db_session.commit()
    return response


@router.get("/{task_id}/action-policies")
def list_task_action_policies(
    task_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[TaskIntegrationView]:
    """The integrations the task can use, each marked when the task uses it, with
    the setting and the effective policy of each action."""
    get_scheduled_task(db_session=db_session, task_id=task_id, user_id=user.id)
    return list_task_integration_views(db_session, user, task_id)
