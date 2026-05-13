"""FastAPI router for Craft Scheduled Tasks.

Thin HTTP layer over ``onyx.db.scheduled_task``. Every handler:

1. Validates request payload via Pydantic.
2. Calls a DB op (which enforces ownership + raises ``OnyxError``).
3. Optionally enqueues the executor task on the ``scheduled_tasks`` queue.

The router is mounted under the existing ``/build`` prefix (see
``backend/onyx/server/features/build/api/api.py``), which provides the
``require_onyx_craft_enabled`` gate.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from fastapi import Response
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.background.celery.versioned_apps.client import app as celery_app
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.models import ScheduledTask
from onyx.db.models import ScheduledTaskRun
from onyx.db.models import User
from onyx.db.scheduled_task import create_scheduled_task
from onyx.db.scheduled_task import get_scheduled_task
from onyx.db.scheduled_task import insert_run
from onyx.db.scheduled_task import list_runs_for_task
from onyx.db.scheduled_task import list_scheduled_tasks_for_user
from onyx.db.scheduled_task import soft_delete_scheduled_task
from onyx.db.scheduled_task import update_scheduled_task
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.scheduled_tasks.schedule import compile_to_cron
from onyx.server.features.build.scheduled_tasks.schedule import EDITOR_PAYLOAD_MODELS
from onyx.server.features.build.scheduled_tasks.schedule import EditorMode
from onyx.server.features.build.scheduled_tasks.schedule import EditorPayload
from onyx.server.features.build.scheduled_tasks.schedule import human_readable
from onyx.server.features.build.scheduled_tasks.schedule import next_n_fires
from onyx.server.features.build.scheduled_tasks.schedule import validate_timezone
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Number of seconds before a queued executor task is dropped. Mirrors
# ``check-for-pruning`` and ``check-for-indexing`` — 15 minutes is plenty for
# the worker to pick up the task; anything still queued past that is dead.
EXECUTOR_TASK_EXPIRES_SECONDS = 900

# Number of future fires returned by the detail endpoint for UI preview.
NEXT_RUNS_PREVIEW_COUNT = 3

# Default and max page sizes for the runs listing endpoint.
RUNS_DEFAULT_PAGE_SIZE = 50
RUNS_MAX_PAGE_SIZE = 100


router = APIRouter(prefix="/scheduled-tasks")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class _Forbid(BaseModel):
    """Base model that rejects unknown fields. Matches the convention in
    ``backend/onyx/server/features/build/api/models.py`` for newer endpoints.
    """

    model_config = ConfigDict(extra="forbid")


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

    name: str = Field(..., min_length=1, max_length=200)
    prompt: str = Field(..., min_length=1)
    editor_mode: EditorMode
    editor_payload: EditorPayload
    timezone: str
    status: ScheduledTaskStatus = ScheduledTaskStatus.ACTIVE
    run_immediately: bool = False

    _dispatch = model_validator(mode="before")(_dispatch_editor_payload)


class ScheduledTaskPatch(_Forbid):
    """Request body for ``PATCH /scheduled-tasks/{id}``.

    All fields are optional; ``editor_mode`` and ``editor_payload`` must be
    supplied together (enforced below).
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, min_length=1)
    editor_mode: EditorMode | None = None
    editor_payload: EditorPayload | None = None
    timezone: str | None = None
    status: ScheduledTaskStatus | None = None

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
    session_id: str | None
    summary: str | None
    skip_reason: str | None
    error_class: str | None

    @classmethod
    def from_model(cls, run: ScheduledTaskRun) -> "RunSummary":
        return cls(
            id=str(run.id),
            status=run.status,
            trigger_source=run.trigger_source,
            started_at=run.started_at,
            finished_at=run.finished_at,
            session_id=str(run.session_id) if run.session_id is not None else None,
            summary=run.summary,
            skip_reason=run.skip_reason,
            error_class=run.error_class,
        )


class ScheduledTaskListItem(BaseModel):
    """Row in ``GET /scheduled-tasks``."""

    id: str
    name: str
    human_readable_schedule: str
    cron_expression: str
    timezone: str
    editor_mode: str
    status: ScheduledTaskStatus
    next_run_at: datetime | None
    last_run: RunSummary | None
    created_at: datetime
    updated_at: datetime


class ScheduledTaskDetail(BaseModel):
    """Response for ``GET /scheduled-tasks/{id}`` and the mutating endpoints
    that return the full task.
    """

    id: str
    name: str
    prompt: str
    human_readable_schedule: str
    cron_expression: str
    timezone: str
    editor_mode: str
    status: ScheduledTaskStatus
    next_run_at: datetime | None
    next_runs: list[datetime]
    last_run: RunSummary | None
    created_at: datetime
    updated_at: datetime


class ScheduledTaskListResponse(BaseModel):
    items: list[ScheduledTaskListItem]


class RunListResponse(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None


class RunNowResponse(BaseModel):
    run_id: str
    status: ScheduledTaskRunStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _latest_run(
    db_session: Session,
    task: ScheduledTask,
    user_id: UUID,
) -> ScheduledTaskRun | None:
    """Fetch the most recent run for the task, or ``None`` if none exist.

    Trades a per-task query (N+1 in the list endpoint) for code simplicity;
    V1 per-user task counts are small and the index covers the lookup.
    """
    runs = list_runs_for_task(
        db_session=db_session,
        task_id=task.id,
        user_id=user_id,
        cursor=None,
        limit=1,
    )
    return runs[0] if runs else None


def _list_item(
    db_session: Session,
    task: ScheduledTask,
    user_id: UUID,
) -> ScheduledTaskListItem:
    last_run = _latest_run(db_session, task, user_id)
    return ScheduledTaskListItem(
        id=str(task.id),
        name=task.name,
        human_readable_schedule=human_readable(task.cron_expression, task.timezone),
        cron_expression=task.cron_expression,
        timezone=task.timezone,
        editor_mode=task.editor_mode,
        status=task.status,
        next_run_at=task.next_run_at,
        last_run=RunSummary.from_model(last_run) if last_run is not None else None,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _detail(
    db_session: Session,
    task: ScheduledTask,
    user_id: UUID,
) -> ScheduledTaskDetail:
    last_run = _latest_run(db_session, task, user_id)
    next_runs: list[datetime] = []
    if task.status == ScheduledTaskStatus.ACTIVE:
        next_runs = next_n_fires(
            task.cron_expression,
            task.timezone,
            datetime.now(tz=timezone.utc),
            NEXT_RUNS_PREVIEW_COUNT,
        )
    return ScheduledTaskDetail(
        id=str(task.id),
        name=task.name,
        prompt=task.prompt,
        human_readable_schedule=human_readable(task.cron_expression, task.timezone),
        cron_expression=task.cron_expression,
        timezone=task.timezone,
        editor_mode=task.editor_mode,
        status=task.status,
        next_run_at=task.next_run_at,
        next_runs=next_runs,
        last_run=RunSummary.from_model(last_run) if last_run is not None else None,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _enqueue_executor(run_id: UUID) -> None:
    """Enqueue the headless executor for a run.

    The executor task definition lives in the background-workers package
    (a sibling agent owns that). We only need its name + queue + an
    ``expires=`` (per CLAUDE.md).

    Passes ``tenant_id`` so ``TenantAwareTask`` sets the per-task
    contextvar on the executor — without it, the run would execute
    against the default schema.
    """
    tenant_id = get_current_tenant_id()
    celery_app.send_task(
        OnyxCeleryTask.SCHEDULED_TASKS_RUN,
        kwargs={"run_id": str(run_id), "tenant_id": tenant_id},
        queue=OnyxCeleryQueues.SCHEDULED_TASKS,
        priority=OnyxCeleryPriority.MEDIUM,
        expires=EXECUTOR_TASK_EXPIRES_SECONDS,
    )


def _parse_cursor(cursor: str | None) -> datetime | None:
    """Parse the ``cursor`` query param (ISO-8601) into a UTC datetime.

    ``None`` and the empty string both mean "first page".
    """
    if cursor is None or cursor == "":
        return None
    try:
        parsed = datetime.fromisoformat(cursor)
    except ValueError as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Invalid cursor (expected ISO-8601 datetime): {cursor!r}",
        ) from e
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


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
    items = [_list_item(db_session, task, user.id) for task in tasks]
    return ScheduledTaskListResponse(items=items)


@router.post("")
def create_task(
    request: ScheduledTaskCreate,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ScheduledTaskDetail:
    """Create a new scheduled task.

    Pipeline:
      1. Validate the timezone.
      2. Compile ``editor_mode`` + ``editor_payload`` to a canonical cron.
      3. Insert via ``create_scheduled_task`` (which computes ``next_run_at``
         when the task is created ACTIVE).
      4. If ``run_immediately`` is set, insert a ``manual_run_now`` run row
         and enqueue the executor. Does NOT touch ``next_run_at``.
    """
    validate_timezone(request.timezone)
    cron_expression = compile_to_cron(request.editor_payload)

    task = create_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        name=request.name,
        prompt=request.prompt,
        cron_expression=cron_expression,
        timezone_name=request.timezone,
        editor_mode=request.editor_mode,
        status=request.status,
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
        _enqueue_executor(run.id)
    else:
        db_session.commit()

    db_session.refresh(task)
    return _detail(db_session, task, user.id)


@router.get("/{task_id}")
def get_task(
    task_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ScheduledTaskDetail:
    """Fetch one task + the next 3 fire times for the UI preview."""
    task = get_scheduled_task(db_session=db_session, task_id=task_id, user_id=user.id)
    return _detail(db_session, task, user.id)


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
    handles ``next_run_at`` recomputation (schedule/timezone change,
    pause/resume) on its own.
    """
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
        timezone_name=request.timezone,
        editor_mode=request.editor_mode,
        status=request.status,
    )
    db_session.commit()
    db_session.refresh(task)
    return _detail(db_session, task, user.id)


@router.delete("/{task_id}")
def delete_task(
    task_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> Response:
    """Soft-delete a task. Idempotent — calling on a missing or already-
    deleted task is a no-op (matches ``soft_delete_scheduled_task``).
    """
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

    Allowed on PAUSED tasks. Does NOT mutate ``next_run_at`` — that's
    the dispatcher's job for recurring fires.
    """
    task = get_scheduled_task(db_session=db_session, task_id=task_id, user_id=user.id)
    run = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.MANUAL_RUN_NOW,
        status=ScheduledTaskRunStatus.QUEUED,
    )
    db_session.commit()
    _enqueue_executor(run.id)
    return RunNowResponse(run_id=str(run.id), status=run.status)


@router.get("/{task_id}/runs")
def list_task_runs(
    task_id: UUID,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=RUNS_DEFAULT_PAGE_SIZE, ge=1, le=RUNS_MAX_PAGE_SIZE),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> RunListResponse:
    """Paginated run history for a task, newest first.

    ``cursor`` is the ``started_at`` (ISO-8601) of the last row returned by
    the previous page. ``next_cursor`` is ``None`` when the last page is
    reached.

    Raises ``OnyxError(NOT_FOUND)`` when the task is missing, soft-deleted,
    or owned by another user (ownership check happens inside the DB op).
    """
    cursor_dt = _parse_cursor(cursor)
    runs = list_runs_for_task(
        db_session=db_session,
        task_id=task_id,
        user_id=user.id,
        cursor=cursor_dt,
        limit=limit,
    )
    next_cursor: str | None = None
    if len(runs) == limit:
        # Use the last row's started_at as the cursor for the next page.
        # If the next page turns out empty, the client just stops paging.
        next_cursor = runs[-1].started_at.isoformat()
    return RunListResponse(
        items=[RunSummary.from_model(run) for run in runs],
        next_cursor=next_cursor,
    )
