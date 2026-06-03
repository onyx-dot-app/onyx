"""Database operations for flow automations.

Same shape as ``onyx/db/scheduled_task.py``: ``db_session`` first, every query
in this module, ownership enforced here rather than in the router.

``claim_due_triggers`` is the only function that takes row locks. Its caller
must advance ``next_run_at`` and insert the run row inside the same
transaction that claimed the trigger — releasing the locks first lets a
concurrent beat tick claim the same rows and fire twice.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session, selectinload

from onyx.db.enums import (
    FlowErrorClass,
    FlowNodeKind,
    FlowNodeRunStatus,
    FlowRunStatus,
    FlowStatus,
    FlowTriggerKind,
    FlowTriggerSource,
)
from onyx.db.models import Flow, FlowNodeRun, FlowRun, FlowTrigger, FlowVersion
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.flows.models import SpecError, parse_spec
from onyx.server.features.build.scheduled_tasks.schedule import compute_next_run_at
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Long enough that guessing one is hopeless, short enough to paste into
# whatever is going to POST to it.
WEBHOOK_SECRET_BYTES = 32


# ---------------------------------------------------------------------------
# Flow CRUD
# ---------------------------------------------------------------------------


def create_flow(
    *,
    db_session: Session,
    user_id: UUID,
    name: str,
    draft_spec: dict[str, Any],
    description: str | None = None,
) -> Flow:
    """Insert a paused flow holding a validated draft.

    New flows start PAUSED on purpose: saving something should never be the
    same gesture as putting it into production.
    """
    _validate_spec(draft_spec)

    flow = Flow(
        user_id=user_id,
        name=name,
        description=description,
        draft_spec=draft_spec,
        status=FlowStatus.PAUSED,
    )
    db_session.add(flow)
    db_session.flush()
    return flow


def get_flow(
    *, db_session: Session, flow_id: UUID, user_id: UUID, with_triggers: bool = False
) -> Flow:
    """Fetch a flow the user owns.

    Raises:
        OnyxError(NOT_FOUND): if it is missing, deleted, or somebody else's.
    """
    stmt = select(Flow).where(
        Flow.id == flow_id,
        Flow.user_id == user_id,
        Flow.deleted.is_(False),
    )
    if with_triggers:
        stmt = stmt.options(selectinload(Flow.triggers))

    flow = db_session.execute(stmt).scalar_one_or_none()
    if flow is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Flow not found")
    return flow


def list_flows_for_user(*, db_session: Session, user_id: UUID) -> list[Flow]:
    stmt = (
        select(Flow)
        .options(selectinload(Flow.triggers))
        .where(Flow.user_id == user_id, Flow.deleted.is_(False))
        .order_by(desc(Flow.created_at))
    )
    return list(db_session.execute(stmt).scalars())


def update_flow(
    *,
    db_session: Session,
    flow: Flow,
    name: str | None = None,
    description: str | None = None,
    draft_spec: dict[str, Any] | None = None,
) -> Flow:
    """Apply a partial edit. Only the fields passed are touched."""
    if draft_spec is not None:
        _validate_spec(draft_spec)
        flow.draft_spec = draft_spec
    if name is not None:
        flow.name = name
    if description is not None:
        flow.description = description
    db_session.flush()
    return flow


def soft_delete_flow(*, db_session: Session, flow: Flow) -> None:
    """Retire a flow but keep its run history readable.

    Also clears every ``next_run_at`` so the dispatcher stops looking at it,
    which is what actually stops the flow — the ``deleted`` flag alone would
    leave a claimed trigger mid-tick still firing.
    """
    flow.deleted = True
    flow.status = FlowStatus.PAUSED
    for trigger in flow.triggers:
        trigger.next_run_at = None
    db_session.flush()


def publish_flow(*, db_session: Session, flow: Flow, user_id: UUID) -> FlowVersion:
    """Freeze the current draft as the next version.

    Runs pin a version, so publishing is what makes an edit take effect for
    anything other than a test run.
    """
    spec = _validate_spec(flow.draft_spec)

    next_version = (
        db_session.execute(
            select(func.coalesce(func.max(FlowVersion.version), 0)).where(
                FlowVersion.flow_id == flow.id
            )
        ).scalar_one()
        + 1
    )

    version = FlowVersion(
        flow_id=flow.id,
        version=next_version,
        spec=flow.draft_spec,
        created_by_id=user_id,
    )
    db_session.add(version)
    flow.published_version = next_version
    db_session.flush()

    logger.info(
        "published flow flow_id=%s version=%d nodes=%d",
        flow.id,
        next_version,
        len(spec.nodes),
    )
    return version


def get_flow_version(
    *, db_session: Session, flow_id: UUID, version: int
) -> FlowVersion:
    stmt = select(FlowVersion).where(
        FlowVersion.flow_id == flow_id, FlowVersion.version == version
    )
    found = db_session.execute(stmt).scalar_one_or_none()
    if found is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Flow version not found")
    return found


def set_flow_status(
    *,
    db_session: Session,
    flow: Flow,
    status: FlowStatus,
    now: datetime | None = None,
) -> Flow:
    """Activate or pause a flow, keeping trigger schedules consistent.

    Activating requires a published version: an ACTIVE flow whose cron fires
    into nothing would just accumulate failed runs.
    """
    now = now or datetime.now(tz=timezone.utc)

    if status == FlowStatus.ACTIVE and flow.published_version is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Publish the flow before activating it",
        )

    flow.status = status
    for trigger in flow.triggers:
        trigger.next_run_at = _next_run_for(trigger, flow_status=status, now=now)
    db_session.flush()
    return flow


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------


def replace_triggers(
    *,
    db_session: Session,
    flow: Flow,
    triggers: list[dict[str, Any]],
    now: datetime | None = None,
) -> list[FlowTrigger]:
    """Set the flow's triggers to exactly this list.

    Webhook secrets are re-minted on replace. That is a deliberate cost: it
    keeps this function simple and means a rotated secret is one edit away.

    Works through ``flow.triggers`` rather than adding rows to the session
    directly. Sessions here are built with ``expire_on_commit=False``, so a
    collection this function bypassed would stay stale for the rest of the
    request — and ``set_flow_status`` walks that collection to decide what the
    dispatcher sees. Going through the relationship keeps the two in step.
    """
    now = now or datetime.now(tz=timezone.utc)

    # delete-orphan on the relationship turns this into the DELETEs.
    flow.triggers.clear()
    db_session.flush()

    created: list[FlowTrigger] = []
    for definition in triggers:
        kind = FlowTriggerKind(definition["kind"])
        config = definition.get("config") or {}

        if kind == FlowTriggerKind.SCHEDULE:
            cron = config.get("cron")
            if not cron:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "A schedule trigger needs a cron expression",
                )
            try:
                compute_next_run_at(cron, now)
            except ValueError as exc:
                raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(exc)) from exc

        trigger = FlowTrigger(
            kind=kind,
            config=config,
            enabled=definition.get("enabled", True),
        )
        if kind == FlowTriggerKind.WEBHOOK:
            # EncryptedString coerces str -> SensitiveValue at the ORM level.
            trigger.webhook_secret = secrets.token_urlsafe(  # ty: ignore[invalid-assignment]
                WEBHOOK_SECRET_BYTES
            )

        trigger.next_run_at = _next_run_for(trigger, flow_status=flow.status, now=now)
        flow.triggers.append(trigger)
        created.append(trigger)

    db_session.flush()
    return created


def get_trigger(*, db_session: Session, trigger_id: UUID) -> FlowTrigger | None:
    """Look a trigger up without an ownership check.

    Used by the webhook route, which authenticates with the trigger's own
    secret rather than a session — there is no user to check against.
    """
    stmt = (
        select(FlowTrigger)
        .options(selectinload(FlowTrigger.flow))
        .where(FlowTrigger.id == trigger_id)
    )
    return db_session.execute(stmt).scalar_one_or_none()


def claim_due_triggers(
    *, db_session: Session, now: datetime, batch_size: int
) -> list[FlowTrigger]:
    """Claim up to ``batch_size`` schedule triggers that are due.

    The caller must, in this same transaction: insert the run rows, call
    ``advance_next_run_at`` for each trigger, and commit.
    """
    if batch_size <= 0:
        return []

    stmt = (
        select(FlowTrigger)
        .join(Flow, Flow.id == FlowTrigger.flow_id)
        .options(selectinload(FlowTrigger.flow))
        .where(
            FlowTrigger.kind == FlowTriggerKind.SCHEDULE,
            FlowTrigger.enabled.is_(True),
            FlowTrigger.next_run_at.is_not(None),
            FlowTrigger.next_run_at <= now,
            Flow.status == FlowStatus.ACTIVE,
            Flow.deleted.is_(False),
        )
        .order_by(FlowTrigger.next_run_at)
        .limit(batch_size)
        .with_for_update(skip_locked=True, of=FlowTrigger)
    )
    return list(db_session.execute(stmt).scalars())


def advance_next_run_at(
    *, db_session: Session, trigger: FlowTrigger, now: datetime
) -> datetime | None:
    """Move a fired trigger on to its next occurrence."""
    trigger.next_run_at = _next_run_for(
        trigger, flow_status=trigger.flow.status, now=now
    )
    db_session.flush()
    return trigger.next_run_at


def _next_run_for(
    trigger: FlowTrigger, *, flow_status: FlowStatus, now: datetime
) -> datetime | None:
    """When the dispatcher should next look at this trigger.

    NULL for anything that is not a live schedule, which is what keeps the
    dispatcher's index small and its query one comparison wide.
    """
    if trigger.kind != FlowTriggerKind.SCHEDULE:
        return None
    if not trigger.enabled or flow_status != FlowStatus.ACTIVE:
        return None

    cron = (trigger.config or {}).get("cron")
    if not cron:
        return None
    try:
        return compute_next_run_at(cron, now)
    except ValueError:
        logger.exception(
            "flow trigger has an invalid cron, leaving it dormant trigger_id=%s",
            trigger.id,
        )
        return None


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def insert_run(
    *,
    db_session: Session,
    flow_id: UUID,
    trigger_source: FlowTriggerSource,
    flow_version_id: UUID | None = None,
    trigger_id: UUID | None = None,
    trigger_payload: dict[str, Any] | None = None,
    status: FlowRunStatus = FlowRunStatus.QUEUED,
    skip_reason: str | None = None,
) -> FlowRun:
    run = FlowRun(
        flow_id=flow_id,
        flow_version_id=flow_version_id,
        trigger_id=trigger_id,
        trigger_source=trigger_source,
        trigger_payload=trigger_payload,
        status=status,
        skip_reason=skip_reason,
        finished_at=(datetime.now(tz=timezone.utc) if status.is_terminal() else None),
    )
    db_session.add(run)
    db_session.flush()
    return run


def get_run(*, db_session: Session, run_id: UUID) -> FlowRun | None:
    return db_session.execute(
        select(FlowRun).where(FlowRun.id == run_id)
    ).scalar_one_or_none()


def get_run_for_user(
    *, db_session: Session, run_id: UUID, flow_id: UUID, user_id: UUID
) -> FlowRun:
    stmt = (
        select(FlowRun)
        .join(Flow, Flow.id == FlowRun.flow_id)
        .options(selectinload(FlowRun.node_runs))
        .where(
            FlowRun.id == run_id,
            FlowRun.flow_id == flow_id,
            Flow.user_id == user_id,
        )
    )
    run = db_session.execute(stmt).scalar_one_or_none()
    if run is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Flow run not found")
    return run


def list_runs_for_flow(
    *,
    db_session: Session,
    flow_id: UUID,
    limit: int,
    offset: int = 0,
    include_test_runs: bool = False,
) -> list[FlowRun]:
    stmt: Select[Any] = select(FlowRun).where(FlowRun.flow_id == flow_id)
    if not include_test_runs:
        stmt = stmt.where(FlowRun.trigger_source != FlowTriggerSource.TEST)
    stmt = stmt.order_by(desc(FlowRun.started_at)).limit(limit).offset(offset)
    return list(db_session.execute(stmt).scalars())


def has_in_flight_run(*, db_session: Session, flow_id: UUID) -> bool:
    """Whether a previous run is still going.

    A schedule that fires faster than the flow completes should queue up
    behind itself rather than run two copies over the same data. A run parked
    on an approval counts: it is unfinished work over the same data, and
    firing past it would put a second question in front of the same person.
    """
    stmt = (
        select(FlowRun.id)
        .where(
            FlowRun.flow_id == flow_id,
            FlowRun.status.in_(
                [
                    FlowRunStatus.QUEUED,
                    FlowRunStatus.RUNNING,
                    FlowRunStatus.AWAITING_DECISION,
                ]
            ),
        )
        .limit(1)
    )
    return db_session.execute(stmt).first() is not None


def mark_run_status(
    *,
    db_session: Session,
    run: FlowRun,
    status: FlowRunStatus,
    error_class: FlowErrorClass | None = None,
    error_detail: str | None = None,
) -> FlowRun:
    run.status = status
    if error_class is not None:
        run.error_class = error_class.value
    if error_detail is not None:
        # Enough to diagnose without turning the run table into a log store.
        run.error_detail = error_detail[:4000]
    if status.is_terminal():
        run.finished_at = datetime.now(tz=timezone.utc)
    db_session.flush()
    return run


def find_stuck_runs(
    *,
    db_session: Session,
    queued_before: datetime,
    running_before: datetime,
) -> list[FlowRun]:
    """Runs whose worker died without writing a terminal status."""
    stmt = select(FlowRun).where(
        (
            (FlowRun.status == FlowRunStatus.QUEUED)
            & (FlowRun.started_at < queued_before)
        )
        | (
            (FlowRun.status == FlowRunStatus.RUNNING)
            & (FlowRun.started_at < running_before)
        )
    )
    return list(db_session.execute(stmt).scalars())


# ---------------------------------------------------------------------------
# Node runs
# ---------------------------------------------------------------------------


def get_node_run(
    *, db_session: Session, run_id: UUID, node_id: str, item_index: int
) -> FlowNodeRun | None:
    stmt = select(FlowNodeRun).where(
        FlowNodeRun.run_id == run_id,
        FlowNodeRun.node_id == node_id,
        FlowNodeRun.item_index == item_index,
    )
    return db_session.execute(stmt).scalar_one_or_none()


def start_node_run(
    *,
    db_session: Session,
    run_id: UUID,
    node_id: str,
    kind: FlowNodeKind,
    item_index: int,
    node_input: dict[str, Any] | None,
) -> tuple[FlowNodeRun, bool]:
    """Get or create the row for one node execution.

    Returns the row and whether it already existed. An existing SUCCEEDED row
    is the resume signal: this run already did that work, possibly with a side
    effect, so the engine reuses its output rather than repeating it.
    """
    existing = get_node_run(
        db_session=db_session, run_id=run_id, node_id=node_id, item_index=item_index
    )
    if existing is not None:
        return existing, True

    node_run = FlowNodeRun(
        run_id=run_id,
        node_id=node_id,
        kind=kind,
        item_index=item_index,
        status=FlowNodeRunStatus.RUNNING,
        input=node_input,
    )
    db_session.add(node_run)
    db_session.flush()
    return node_run, False


def finish_node_run(
    *,
    db_session: Session,
    node_run: FlowNodeRun,
    status: FlowNodeRunStatus,
    output: Any = None,
    attempt: int = 1,
    error_class: FlowErrorClass | None = None,
    error_detail: str | None = None,
) -> FlowNodeRun:
    node_run.status = status
    node_run.attempt = attempt
    # JSONB holds an object; anything else is boxed so the column stays one
    # shape and the inspector has one thing to render.
    node_run.output = None if output is None else {"value": output}
    if error_class is not None:
        node_run.error_class = error_class.value
    if error_detail is not None:
        node_run.error_detail = error_detail[:4000]
    node_run.finished_at = datetime.now(tz=timezone.utc)
    db_session.flush()
    return node_run


def record_skipped_node(
    *, db_session: Session, run_id: UUID, node_id: str, kind: FlowNodeKind
) -> FlowNodeRun:
    """Note a node on a branch the run did not take.

    Idempotent, because a run resumed after an approval walks the whole graph
    again and reaches the same untaken branches a second time. The unique key
    on (run, node, item) would otherwise turn a perfectly ordinary resume into
    an integrity error.
    """
    existing = get_node_run(
        db_session=db_session, run_id=run_id, node_id=node_id, item_index=0
    )
    if existing is not None:
        return existing

    node_run = FlowNodeRun(
        run_id=run_id,
        node_id=node_id,
        kind=kind,
        item_index=0,
        status=FlowNodeRunStatus.SKIPPED,
        finished_at=datetime.now(tz=timezone.utc),
    )
    db_session.add(node_run)
    db_session.flush()
    return node_run


def record_node_waiting(
    *,
    db_session: Session,
    run_id: UUID,
    node_id: str,
    item_index: int,
    detail: dict[str, Any],
) -> FlowNodeRun | None:
    """Record what an open node is waiting on, without closing it.

    The detail is merged into the row's ``input``, which the run view already
    shows beside the step — so the rendered question reaches the reviewer
    without a column of its own.
    """
    node_run = get_node_run(
        db_session=db_session, run_id=run_id, node_id=node_id, item_index=item_index
    )
    if node_run is None:
        return None

    # Reassigned rather than mutated: JSONB is not tracked in place.
    node_run.input = {**(node_run.input or {}), **detail}
    db_session.flush()
    return node_run


def apply_human_decision(
    *,
    db_session: Session,
    run: FlowRun,
    node_id: str,
    decision: str,
    comment: str | None,
    decided_by: str | None,
) -> FlowNodeRun:
    """Answer an approval and put the run back in the queue.

    The decision is written onto the node's own row, which is what the engine
    reads when it replays the run. Nothing else carries it, so there is no
    second copy to disagree with.
    """
    if run.status != FlowRunStatus.AWAITING_DECISION:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This run is not waiting for a decision",
        )

    node_run = get_node_run(
        db_session=db_session, run_id=run.id, node_id=node_id, item_index=0
    )
    if node_run is None or node_run.kind != FlowNodeKind.HUMAN:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "No approval step by that name")
    if node_run.status != FlowNodeRunStatus.RUNNING:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "This approval has already been answered"
        )

    finish_node_run(
        db_session=db_session,
        node_run=node_run,
        status=FlowNodeRunStatus.SUCCEEDED,
        output={
            "decision": decision,
            "comment": comment,
            "decided_by": decided_by,
            "decided_at": datetime.now(tz=timezone.utc).isoformat(),
        },
    )

    run.status = FlowRunStatus.QUEUED
    # A resumed run is a fresh attempt: leaving the last failure on the row
    # would have the run list reporting an error that no longer applies.
    run.error_class = None
    run.error_detail = None
    run.finished_at = None
    db_session.flush()

    logger.info(
        "flow approval answered run_id=%s node=%s decision=%s",
        run.id,
        node_id,
        decision,
    )
    return node_run


def purge_old_runs(
    *, db_session: Session, older_than: timedelta, keep_per_flow: int
) -> int:
    """Drop run history past both the age and per-flow keep limits.

    Both bounds apply: a busy flow keeps its most recent runs however old the
    cutoff, and a quiet one does not hoard a year of green ticks.
    """
    cutoff = datetime.now(tz=timezone.utc) - older_than
    ranked = select(
        FlowRun.id.label("id"),
        func.row_number()
        .over(partition_by=FlowRun.flow_id, order_by=desc(FlowRun.started_at))
        .label("position"),
        FlowRun.started_at.label("started_at"),
    ).subquery()
    doomed = select(ranked.c.id).where(
        ranked.c.position > keep_per_flow, ranked.c.started_at < cutoff
    )

    runs = list(
        db_session.execute(select(FlowRun).where(FlowRun.id.in_(doomed))).scalars()
    )
    for run in runs:
        db_session.delete(run)
    db_session.flush()
    return len(runs)


def _validate_spec(raw: dict[str, Any]) -> Any:
    try:
        return parse_spec(raw)
    except SpecError as exc:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(exc)) from exc
