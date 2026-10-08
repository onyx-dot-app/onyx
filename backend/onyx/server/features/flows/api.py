"""FastAPI routes for flow automations.

A thin layer over ``onyx.db.flow``: validate the payload, call one DB op
(which enforces ownership and raises ``OnyxError``), and optionally enqueue the
executor. No query lives here.

The webhook route is the one exception to the ownership pattern. It has no
session to check, so it authenticates with the trigger's own secret and is
deliberately parsimonious about what it says back — a wrong secret and an
unknown trigger return the same 404, so the endpoint cannot be used to find
out which flows exist.
"""

from __future__ import annotations

import json
import secrets
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.background.celery.tasks.flows.tasks import QUEUE_RESIDENCY_SECONDS
from onyx.background.celery.versioned_apps.client import app as celery_app
from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryQueues, OnyxCeleryTask
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import (
    FlowStatus,
    FlowTriggerKind,
    FlowTriggerSource,
    Permission,
)
from onyx.db.flow import (
    apply_human_decision,
    create_flow,
    ensure_webhook_signing_secret,
    get_flow,
    get_flow_version,
    get_run_for_user,
    get_trigger,
    insert_run,
    list_flows_for_user,
    list_runs_for_flow,
    publish_flow,
    replace_triggers,
    set_flow_status,
    soft_delete_flow,
    update_flow,
)
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.flows.models import (
    CreateFlowRequest,
    FlowDetail,
    FlowSummary,
    ReplaceTriggersRequest,
    RunDetail,
    RunSummary,
    SetStatusRequest,
    StartRunRequest,
    SubmitDecisionRequest,
    TriggerView,
    UpdateFlowRequest,
    WebhookAccepted,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/flows")

RUNS_DEFAULT_PAGE_SIZE = 50
RUNS_MAX_PAGE_SIZE = 200

# Header an inbound webhook must carry.
WEBHOOK_TOKEN_HEADER = "X-Onyx-Flow-Token"  # pragma: allowlist secret

# A webhook body larger than this is refused rather than persisted: the whole
# payload becomes `{{ trigger }}` and lands in the run row.
MAX_WEBHOOK_PAYLOAD_BYTES = 256 * 1024


# ---------------------------------------------------------------------------
# Flow CRUD
# ---------------------------------------------------------------------------


@router.post("")
def create_flow_route(
    request: CreateFlowRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> FlowDetail:
    flow = create_flow(
        db_session=db_session,
        user_id=user.id,
        name=request.name,
        description=request.description,
        draft_spec=request.spec,
    )
    db_session.commit()
    return FlowDetail.build(flow, published_spec=None)


@router.get("")
def list_flows_route(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[FlowSummary]:
    flows = list_flows_for_user(db_session=db_session, user_id=user.id)
    return [FlowSummary.from_model(flow) for flow in flows]


@router.get("/{flow_id}")
def get_flow_route(
    flow_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> FlowDetail:
    """The flow the editor renders.

    Mints the webhook signing secret if the flow has none, so a flow written
    before webhook nodes existed can show one the moment somebody opens it
    rather than only after its first run. Idempotent, so the write happens
    once and every later read is a plain read.
    """
    flow = get_flow(
        db_session=db_session, flow_id=flow_id, user_id=user.id, with_triggers=True
    )
    ensure_webhook_signing_secret(db_session=db_session, flow=flow)
    db_session.commit()
    return FlowDetail.build(
        flow, published_spec=_published_spec(db_session=db_session, flow=flow)
    )


@router.patch("/{flow_id}")
def update_flow_route(
    flow_id: UUID,
    request: UpdateFlowRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> FlowDetail:
    flow = get_flow(
        db_session=db_session, flow_id=flow_id, user_id=user.id, with_triggers=True
    )
    update_flow(
        db_session=db_session,
        flow=flow,
        name=request.name,
        description=request.description,
        draft_spec=request.spec,
    )
    db_session.commit()
    return FlowDetail.build(
        flow, published_spec=_published_spec(db_session=db_session, flow=flow)
    )


@router.delete("/{flow_id}")
def delete_flow_route(
    flow_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    flow = get_flow(
        db_session=db_session, flow_id=flow_id, user_id=user.id, with_triggers=True
    )
    soft_delete_flow(db_session=db_session, flow=flow)
    db_session.commit()


@router.post("/{flow_id}/publish")
def publish_flow_route(
    flow_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> FlowDetail:
    """Freeze the draft as a new version. Scheduled runs pick it up next fire."""
    flow = get_flow(
        db_session=db_session, flow_id=flow_id, user_id=user.id, with_triggers=True
    )
    publish_flow(db_session=db_session, flow=flow, user_id=user.id)
    db_session.commit()
    return FlowDetail.build(flow, published_spec=flow.draft_spec)


@router.post("/{flow_id}/status")
def set_status_route(
    flow_id: UUID,
    request: SetStatusRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> FlowDetail:
    flow = get_flow(
        db_session=db_session, flow_id=flow_id, user_id=user.id, with_triggers=True
    )
    set_flow_status(db_session=db_session, flow=flow, status=request.status)
    db_session.commit()
    return FlowDetail.build(
        flow, published_spec=_published_spec(db_session=db_session, flow=flow)
    )


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------


@router.put("/{flow_id}/triggers")
def replace_triggers_route(
    flow_id: UUID,
    request: ReplaceTriggersRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[TriggerView]:
    """Set the flow's triggers.

    A webhook secret is minted here and returned once — this is the only
    response that carries it.
    """
    flow = get_flow(
        db_session=db_session, flow_id=flow_id, user_id=user.id, with_triggers=True
    )
    created = replace_triggers(
        db_session=db_session,
        flow=flow,
        triggers=[definition.model_dump() for definition in request.triggers],
    )
    db_session.commit()
    return [TriggerView.from_model(trigger, reveal_secret=True) for trigger in created]


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.post("/{flow_id}/run")
def start_run_route(
    flow_id: UUID,
    request: StartRunRequest,
    test: bool = Query(
        default=False,
        description="Run the unsaved draft instead of the published version.",
    ),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> RunSummary:
    """Start a run now.

    A test run executes the draft and is kept out of the default run history,
    so trying something out does not litter the record the flow's owner reads
    to see whether the automation is healthy.
    """
    flow = get_flow(db_session=db_session, flow_id=flow_id, user_id=user.id)

    version_id: UUID | None = None
    if not test:
        if flow.published_version is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Publish the flow before running it, or run it as a test",
            )
        version_id = get_flow_version(
            db_session=db_session, flow_id=flow.id, version=flow.published_version
        ).id

    run = insert_run(
        db_session=db_session,
        flow_id=flow.id,
        flow_version_id=version_id,
        trigger_source=FlowTriggerSource.TEST if test else FlowTriggerSource.MANUAL,
        trigger_payload=request.payload,
    )
    db_session.commit()

    _enqueue(run_id=run.id)
    return RunSummary.from_model(run)


@router.get("/{flow_id}/runs")
def list_runs_route(
    flow_id: UUID,
    limit: int = Query(default=RUNS_DEFAULT_PAGE_SIZE, ge=1, le=RUNS_MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    include_tests: bool = Query(default=False),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> list[RunSummary]:
    flow = get_flow(db_session=db_session, flow_id=flow_id, user_id=user.id)
    runs = list_runs_for_flow(
        db_session=db_session,
        flow_id=flow.id,
        limit=limit,
        offset=offset,
        include_test_runs=include_tests,
    )
    return [RunSummary.from_model(run) for run in runs]


@router.get("/{flow_id}/runs/{run_id}")
def get_run_route(
    flow_id: UUID,
    run_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> RunDetail:
    run = get_run_for_user(
        db_session=db_session, run_id=run_id, flow_id=flow_id, user_id=user.id
    )
    return RunDetail.from_model(run)


@router.post("/{flow_id}/runs/{run_id}/decision")
def submit_decision_route(
    flow_id: UUID,
    run_id: UUID,
    request: SubmitDecisionRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> RunDetail:
    """Answer an approval step and let the run carry on.

    The flow's owner decides. A node's ``assignee`` says who ought to look at
    it, but turning that into an access rule would mean a run stuck forever
    behind somebody who left.
    """
    run = get_run_for_user(
        db_session=db_session, run_id=run_id, flow_id=flow_id, user_id=user.id
    )
    apply_human_decision(
        db_session=db_session,
        run=run,
        node_id=request.node_id,
        decision=request.decision,
        comment=request.comment,
        decided_by=user.email,
    )
    db_session.commit()

    _enqueue(run_id=run.id)
    return RunDetail.from_model(run)


# ---------------------------------------------------------------------------
# Inbound webhooks
# ---------------------------------------------------------------------------


@router.post("/webhooks/{trigger_id}")
async def webhook_route(
    trigger_id: UUID,
    request: Request,
    token: str | None = Header(default=None, alias=WEBHOOK_TOKEN_HEADER),
    db_session: Session = Depends(get_session),
) -> WebhookAccepted:
    """Start a run from an external system.

    Unauthenticated in the session sense: the trigger id plus its secret are
    the credential. Every rejection is the same 404 so the endpoint cannot be
    probed for which triggers exist.
    """
    payload = await _read_capped_payload(request)

    trigger = get_trigger(db_session=db_session, trigger_id=trigger_id)
    if not _webhook_is_valid(trigger, token):
        logger.warning("rejected flow webhook trigger_id=%s", trigger_id)
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Unknown webhook")

    assert trigger is not None  # narrowed by _webhook_is_valid
    flow = trigger.flow

    if flow.published_version is None:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "This flow has not been published")

    version = get_flow_version(
        db_session=db_session, flow_id=flow.id, version=flow.published_version
    )
    run = insert_run(
        db_session=db_session,
        flow_id=flow.id,
        flow_version_id=version.id,
        trigger_id=trigger.id,
        trigger_source=FlowTriggerSource.WEBHOOK,
        trigger_payload=payload,
    )
    db_session.commit()

    _enqueue(run_id=run.id)
    return WebhookAccepted(run_id=run.id)


async def _read_capped_payload(request: Request) -> dict[str, Any]:
    """Read the request body, refusing anything over the cap.

    Deliberately not a ``Body(...)`` dependency. FastAPI would parse the whole
    payload into memory before any check of ours could run, so the limit would
    only be enforced after the damage. Reading the stream here means an
    unauthenticated caller cannot make the server buffer an arbitrary body —
    or reach the database — by sending a large enough request.

    The body becomes ``{{ trigger }}`` and is persisted on the run row, so the
    cap is a real storage bound rather than a formality.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_bytes = int(declared)
        except ValueError:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT, "Content-Length is not a number"
            ) from None
        if declared_bytes > MAX_WEBHOOK_PAYLOAD_BYTES:
            raise _too_large(declared_bytes)

    # Content-Length is absent under chunked transfer encoding, so the stream
    # is capped as it arrives rather than trusted to match the header.
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > MAX_WEBHOOK_PAYLOAD_BYTES:
            raise _too_large(received)
        chunks.append(chunk)

    raw = b"".join(chunks)
    if not raw.strip():
        return {}

    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"Webhook payload is not valid JSON: {exc}"
        ) from None

    if not isinstance(parsed, dict):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Webhook payload must be a JSON object"
        )
    return parsed


def _too_large(size: int) -> OnyxError:
    return OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        f"Webhook payload is at least {size} bytes, over the "
        f"{MAX_WEBHOOK_PAYLOAD_BYTES} byte limit",
    )


def _webhook_is_valid(trigger: Any, token: str | None) -> bool:
    """Whether this delivery may start a run.

    Compared in constant time, and every failure looks the same from outside.
    """
    if trigger is None or trigger.kind != FlowTriggerKind.WEBHOOK:
        return False
    if not trigger.enabled or trigger.flow.deleted:
        return False
    if trigger.flow.status != FlowStatus.ACTIVE:
        return False
    if trigger.webhook_secret is None or token is None:
        return False
    expected = trigger.webhook_secret.get_value(apply_mask=False)
    return secrets.compare_digest(expected, token)


def _published_spec(*, db_session: Session, flow: Any) -> dict[str, Any] | None:
    if flow.published_version is None:
        return None
    version = get_flow_version(
        db_session=db_session, flow_id=flow.id, version=flow.published_version
    )
    return version.spec


def _enqueue(*, run_id: UUID) -> None:
    celery_app.send_task(
        OnyxCeleryTask.FLOWS_RUN,
        kwargs={"run_id": str(run_id), "tenant_id": get_current_tenant_id()},
        queue=OnyxCeleryQueues.SCHEDULED_TASKS,
        priority=OnyxCeleryPriority.MEDIUM,
        expires=QUEUE_RESIDENCY_SECONDS,
    )
