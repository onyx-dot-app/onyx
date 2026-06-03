"""Flow persistence against a real database.

Unit tests cover the spec model and the engine. What they cannot cover is
anything whose correctness *is* the database: the dispatcher's `FOR UPDATE
SKIP LOCKED` claim, the unique key that makes a redelivered run safe, and the
cascades that keep run history from outliving its flow.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    FlowNodeKind,
    FlowNodeRunStatus,
    FlowRunStatus,
    FlowStatus,
    FlowTriggerKind,
    FlowTriggerSource,
)
from onyx.db.flow import (
    advance_next_run_at,
    apply_human_decision,
    claim_due_triggers,
    create_flow,
    ensure_webhook_signing_secret,
    finish_node_run,
    get_flow,
    get_run,
    has_in_flight_run,
    insert_run,
    publish_flow,
    purge_old_runs,
    replace_triggers,
    set_flow_status,
    soft_delete_flow,
    start_node_run,
)
from onyx.db.models import Flow, FlowNodeRun, FlowRun, FlowVersion, User
from onyx.error_handling.exceptions import OnyxError
from onyx.flows.runner import run_flow_logic
from tests.external_dependency_unit.conftest import create_test_user


def simple_spec(value: str = "1") -> dict[str, Any]:
    return {
        "spec_version": 1,
        "start": "step",
        "nodes": [
            {
                "id": "step",
                "name": "step",
                "kind": "TRANSFORM",
                "next": [],
                "for_each": None,
                "on_error": "stop",
                "retry": {"max_attempts": 1, "backoff_seconds": 1},
                "fields": {"value": value},
            }
        ],
    }


def _run_count(db_session: Session, flow_id: UUID) -> int:
    """Runs belonging to one flow. `purge_old_runs` sweeps every flow, and
    this database is shared across the file, so a global tally would depend on
    what the other tests left behind."""
    rows = db_session.execute(
        select(FlowRun).where(FlowRun.flow_id == flow_id)
    ).scalars()
    return len(list(rows))


@pytest.fixture
def owner(db_session: Session) -> User:
    return create_test_user(db_session, "flow_owner")


def make_flow(db_session: Session, owner: User, name: str = "test flow") -> Flow:
    flow = create_flow(
        db_session=db_session,
        user_id=owner.id,
        name=name,
        draft_spec=simple_spec(),
    )
    db_session.commit()
    return flow


# ---------------------------------------------------------------------------
# Publishing and status
# ---------------------------------------------------------------------------


def test_publish_numbers_versions_from_one(db_session: Session, owner: User) -> None:
    flow = make_flow(db_session, owner)

    first = publish_flow(db_session=db_session, flow=flow, user_id=owner.id)
    db_session.commit()
    assert first.version == 1
    assert flow.published_version == 1

    flow.draft_spec = simple_spec("2")
    second = publish_flow(db_session=db_session, flow=flow, user_id=owner.id)
    db_session.commit()

    assert second.version == 2
    assert flow.published_version == 2
    # Each version keeps the spec it froze, which is what lets a run pin one.
    assert first.spec["nodes"][0]["fields"]["value"] == "1"
    assert second.spec["nodes"][0]["fields"]["value"] == "2"


def test_activating_without_a_published_version_is_refused(
    db_session: Session, owner: User
) -> None:
    flow = make_flow(db_session, owner)

    with pytest.raises(OnyxError, match="Publish the flow before activating it"):
        set_flow_status(db_session=db_session, flow=flow, status=FlowStatus.ACTIVE)


def test_status_drives_the_dispatcher_field(db_session: Session, owner: User) -> None:
    flow = make_flow(db_session, owner)
    replace_triggers(
        db_session=db_session,
        flow=flow,
        triggers=[{"kind": "SCHEDULE", "config": {"cron": "*/5 * * * *"}}],
    )
    publish_flow(db_session=db_session, flow=flow, user_id=owner.id)
    db_session.commit()

    # Paused flows are invisible to the dispatcher, whatever their cron says.
    assert flow.triggers[0].next_run_at is None

    set_flow_status(db_session=db_session, flow=flow, status=FlowStatus.ACTIVE)
    db_session.commit()
    assert flow.triggers[0].next_run_at is not None

    set_flow_status(db_session=db_session, flow=flow, status=FlowStatus.PAUSED)
    db_session.commit()
    assert flow.triggers[0].next_run_at is None


def test_soft_delete_stops_the_dispatcher_and_hides_the_flow(
    db_session: Session, owner: User
) -> None:
    flow = make_flow(db_session, owner)
    replace_triggers(
        db_session=db_session,
        flow=flow,
        triggers=[{"kind": "SCHEDULE", "config": {"cron": "*/5 * * * *"}}],
    )
    publish_flow(db_session=db_session, flow=flow, user_id=owner.id)
    set_flow_status(db_session=db_session, flow=flow, status=FlowStatus.ACTIVE)
    db_session.commit()
    assert flow.triggers[0].next_run_at is not None

    soft_delete_flow(db_session=db_session, flow=flow)
    db_session.commit()

    # Clearing next_run_at is what actually stops it; the flag alone would
    # leave an already-claimed trigger firing.
    assert flow.triggers[0].next_run_at is None
    with pytest.raises(OnyxError, match="Flow not found"):
        get_flow(db_session=db_session, flow_id=flow.id, user_id=owner.id)


def test_a_flow_is_only_visible_to_its_owner(db_session: Session, owner: User) -> None:
    flow = make_flow(db_session, owner)
    stranger = create_test_user(db_session, "flow_stranger")

    with pytest.raises(OnyxError, match="Flow not found"):
        get_flow(db_session=db_session, flow_id=flow.id, user_id=stranger.id)


# ---------------------------------------------------------------------------
# The dispatcher's claim
# ---------------------------------------------------------------------------


def test_due_schedule_triggers_are_claimed(db_session: Session, owner: User) -> None:
    flow = make_flow(db_session, owner)
    replace_triggers(
        db_session=db_session,
        flow=flow,
        triggers=[{"kind": "SCHEDULE", "config": {"cron": "* * * * *"}}],
    )
    publish_flow(db_session=db_session, flow=flow, user_id=owner.id)
    set_flow_status(db_session=db_session, flow=flow, status=FlowStatus.ACTIVE)
    db_session.commit()

    later = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    claimed = claim_due_triggers(db_session=db_session, now=later, batch_size=50)

    assert flow.triggers[0].id in {trigger.id for trigger in claimed}


def test_a_webhook_trigger_is_never_claimed(db_session: Session, owner: User) -> None:
    """Only schedules are the dispatcher's business."""
    flow = make_flow(db_session, owner)
    replace_triggers(
        db_session=db_session, flow=flow, triggers=[{"kind": "WEBHOOK", "config": {}}]
    )
    publish_flow(db_session=db_session, flow=flow, user_id=owner.id)
    set_flow_status(db_session=db_session, flow=flow, status=FlowStatus.ACTIVE)
    db_session.commit()

    assert flow.triggers[0].kind == FlowTriggerKind.WEBHOOK
    assert flow.triggers[0].next_run_at is None

    later = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    claimed = claim_due_triggers(db_session=db_session, now=later, batch_size=50)
    assert flow.triggers[0].id not in {trigger.id for trigger in claimed}


def test_two_dispatchers_cannot_claim_the_same_trigger(
    db_session: Session, owner: User
) -> None:
    """The heart of the dispatcher: SKIP LOCKED means a concurrent tick sees
    no rows rather than firing the same schedule twice."""
    flow = make_flow(db_session, owner, name="contended flow")
    replace_triggers(
        db_session=db_session,
        flow=flow,
        triggers=[{"kind": "SCHEDULE", "config": {"cron": "* * * * *"}}],
    )
    publish_flow(db_session=db_session, flow=flow, user_id=owner.id)
    set_flow_status(db_session=db_session, flow=flow, status=FlowStatus.ACTIVE)
    db_session.commit()

    trigger_id = flow.triggers[0].id
    later = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    started = __import__("threading").Barrier(2)

    def claim_and_advance() -> list[UUID]:
        with get_session_with_current_tenant() as session:
            # Line both threads up on the claim so the locks genuinely race.
            started.wait(timeout=10)
            claimed = claim_due_triggers(db_session=session, now=later, batch_size=50)
            ids = [trigger.id for trigger in claimed]
            for trigger in claimed:
                insert_run(
                    db_session=session,
                    flow_id=trigger.flow_id,
                    trigger_id=trigger.id,
                    trigger_source=FlowTriggerSource.SCHEDULE,
                )
                advance_next_run_at(db_session=session, trigger=trigger, now=later)
            session.commit()
            return ids

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(claim_and_advance) for _ in range(2)]
        claimed_ids = [found for future in results for found in future.result()]

    assert claimed_ids.count(trigger_id) == 1, (
        "the same schedule was claimed twice, so it would have fired twice"
    )

    runs = db_session.execute(
        select(FlowRun).where(FlowRun.trigger_id == trigger_id)
    ).scalars()
    assert len(list(runs)) == 1


def test_advancing_moves_the_trigger_into_the_future(
    db_session: Session, owner: User
) -> None:
    flow = make_flow(db_session, owner)
    replace_triggers(
        db_session=db_session,
        flow=flow,
        triggers=[{"kind": "SCHEDULE", "config": {"cron": "*/5 * * * *"}}],
    )
    publish_flow(db_session=db_session, flow=flow, user_id=owner.id)
    set_flow_status(db_session=db_session, flow=flow, status=FlowStatus.ACTIVE)
    db_session.commit()

    now = datetime.now(tz=timezone.utc)
    trigger = flow.triggers[0]
    advance_next_run_at(db_session=db_session, trigger=trigger, now=now)
    db_session.commit()

    assert trigger.next_run_at is not None
    assert trigger.next_run_at > now


# ---------------------------------------------------------------------------
# Runs and the resume path
# ---------------------------------------------------------------------------


def test_in_flight_runs_are_detected(db_session: Session, owner: User) -> None:
    flow = make_flow(db_session, owner)
    db_session.commit()
    assert has_in_flight_run(db_session=db_session, flow_id=flow.id) is False

    run = insert_run(
        db_session=db_session,
        flow_id=flow.id,
        trigger_source=FlowTriggerSource.MANUAL,
    )
    db_session.commit()
    assert has_in_flight_run(db_session=db_session, flow_id=flow.id) is True

    run.status = FlowRunStatus.SUCCEEDED
    db_session.commit()
    assert has_in_flight_run(db_session=db_session, flow_id=flow.id) is False


def test_a_finished_node_is_returned_rather_than_duplicated(
    db_session: Session, owner: User
) -> None:
    """The resume path. A redelivered run must find the completed row and
    reuse its output instead of repeating the side effect."""
    flow = make_flow(db_session, owner)
    run = insert_run(
        db_session=db_session,
        flow_id=flow.id,
        trigger_source=FlowTriggerSource.MANUAL,
    )
    db_session.commit()

    node_run, existed = start_node_run(
        db_session=db_session,
        run_id=run.id,
        node_id="step",
        kind=FlowNodeKind.TRANSFORM,
        item_index=0,
        node_input=None,
    )
    assert existed is False
    finish_node_run(
        db_session=db_session,
        node_run=node_run,
        status=FlowNodeRunStatus.SUCCEEDED,
        output={"value": "already done"},
    )
    db_session.commit()

    again, existed_now = start_node_run(
        db_session=db_session,
        run_id=run.id,
        node_id="step",
        kind=FlowNodeKind.TRANSFORM,
        item_index=0,
        node_input=None,
    )
    db_session.commit()

    assert existed_now is True
    assert again.id == node_run.id
    assert again.status == FlowNodeRunStatus.SUCCEEDED
    assert again.output == {"value": {"value": "already done"}}

    rows = db_session.execute(
        select(FlowNodeRun).where(FlowNodeRun.run_id == run.id)
    ).scalars()
    assert len(list(rows)) == 1


def test_fanned_out_items_get_a_row_each(db_session: Session, owner: User) -> None:
    flow = make_flow(db_session, owner)
    run = insert_run(
        db_session=db_session,
        flow_id=flow.id,
        trigger_source=FlowTriggerSource.MANUAL,
    )
    db_session.commit()

    for index in range(3):
        start_node_run(
            db_session=db_session,
            run_id=run.id,
            node_id="step",
            kind=FlowNodeKind.TRANSFORM,
            item_index=index,
            node_input={"index": index},
        )
    db_session.commit()

    rows = list(
        db_session.execute(
            select(FlowNodeRun).where(FlowNodeRun.run_id == run.id)
        ).scalars()
    )
    assert sorted(row.item_index for row in rows) == [0, 1, 2]


# ---------------------------------------------------------------------------
# Retention and cascades
# ---------------------------------------------------------------------------


def test_purge_honours_both_the_age_and_the_keep_limit(
    db_session: Session, owner: User
) -> None:
    flow = make_flow(db_session, owner)
    db_session.commit()

    old = datetime.now(tz=timezone.utc) - timedelta(days=40)
    for _ in range(5):
        run = insert_run(
            db_session=db_session,
            flow_id=flow.id,
            trigger_source=FlowTriggerSource.SCHEDULE,
            status=FlowRunStatus.SUCCEEDED,
        )
        run.started_at = old
    db_session.commit()

    # Old, but inside the keep window, so nothing of this flow's goes.
    purge_old_runs(
        db_session=db_session, older_than=timedelta(days=30), keep_per_flow=10
    )
    db_session.commit()
    assert _run_count(db_session, flow.id) == 5

    # Beyond both bounds now, so the surplus goes and the newest stay.
    purge_old_runs(
        db_session=db_session, older_than=timedelta(days=30), keep_per_flow=2
    )
    db_session.commit()
    assert _run_count(db_session, flow.id) == 2


def test_recent_runs_survive_the_purge(db_session: Session, owner: User) -> None:
    flow = make_flow(db_session, owner)
    for _ in range(4):
        insert_run(
            db_session=db_session,
            flow_id=flow.id,
            trigger_source=FlowTriggerSource.SCHEDULE,
            status=FlowRunStatus.SUCCEEDED,
        )
    db_session.commit()

    purge_old_runs(
        db_session=db_session, older_than=timedelta(days=30), keep_per_flow=1
    )
    db_session.commit()

    assert _run_count(db_session, flow.id) == 4, (
        "a busy flow's recent history must survive the keep limit"
    )


def test_deleting_a_flow_takes_its_history_with_it(
    db_session: Session, owner: User
) -> None:
    flow = make_flow(db_session, owner)
    replace_triggers(
        db_session=db_session,
        flow=flow,
        triggers=[{"kind": "SCHEDULE", "config": {"cron": "*/5 * * * *"}}],
    )
    publish_flow(db_session=db_session, flow=flow, user_id=owner.id)
    run = insert_run(
        db_session=db_session,
        flow_id=flow.id,
        trigger_source=FlowTriggerSource.MANUAL,
    )
    start_node_run(
        db_session=db_session,
        run_id=run.id,
        node_id="step",
        kind=FlowNodeKind.TRANSFORM,
        item_index=0,
        node_input=None,
    )
    db_session.commit()
    flow_id, run_id = flow.id, run.id

    db_session.delete(flow)
    db_session.commit()

    for model, column in (
        (FlowVersion, FlowVersion.flow_id),
        (FlowRun, FlowRun.flow_id),
    ):
        left = db_session.execute(select(model).where(column == flow_id)).scalars()
        assert list(left) == [], f"{model.__name__} outlived its flow"

    node_rows = db_session.execute(
        select(FlowNodeRun).where(FlowNodeRun.run_id == run_id)
    ).scalars()
    assert list(node_rows) == []


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


def gated_spec() -> dict[str, Any]:
    """A branch, then an approval, with a step on each side of both.

    The untaken branch sits *before* the approval on purpose. A resumed run
    walks the whole graph again and reaches it a second time, so this is what
    proves the skip write survives the replay rather than tripping the unique
    key on (run, node, item).
    """
    return {
        "start": "check",
        "nodes": [
            {
                "id": "check",
                "kind": "CONDITION",
                "left": "{{ trigger.tag }}",
                "operator": "is_not_empty",
                "on_true": ["prepare"],
                "on_false": ["untaken"],
            },
            {
                "id": "prepare",
                "kind": "TRANSFORM",
                "fields": {"tag": "{{ trigger.tag }}"},
                "next": ["gate"],
            },
            {"id": "untaken", "kind": "TRANSFORM", "fields": {"value": "nope"}},
            {
                "id": "gate",
                "kind": "HUMAN",
                "question": "Ship {{ trigger.tag }}?",
                "on_approve": ["ship"],
            },
            {"id": "ship", "kind": "TRANSFORM", "fields": {"value": "shipped"}},
        ],
    }


def gated_run(db_session: Session, owner: User, name: str) -> FlowRun:
    flow = create_flow(
        db_session=db_session, user_id=owner.id, name=name, draft_spec=gated_spec()
    )
    run = insert_run(
        db_session=db_session,
        flow_id=flow.id,
        trigger_source=FlowTriggerSource.TEST,
        trigger_payload={"tag": "v4"},
    )
    db_session.commit()
    return run


def node_rows(db_session: Session, run_id: UUID, node_id: str) -> list[FlowNodeRun]:
    rows = db_session.execute(
        select(FlowNodeRun).where(
            FlowNodeRun.run_id == run_id, FlowNodeRun.node_id == node_id
        )
    ).scalars()
    return list(rows)


def test_a_run_parks_on_an_approval_and_resumes_when_it_is_answered(
    db_session: Session, owner: User
) -> None:
    """The whole approval cycle against real rows.

    Nothing is held between the two halves: the first call ends, and the
    second reconstructs everything it needs from what the first wrote.
    """
    run_id = gated_run(db_session, owner, "gated flow").id

    run_flow_logic(run_id)
    db_session.expire_all()

    run = get_run(db_session=db_session, run_id=run_id)
    assert run is not None
    assert run.status == FlowRunStatus.AWAITING_DECISION
    assert run.finished_at is None, "a parked run has not finished"

    gate = node_rows(db_session, run_id, "gate")[0]
    assert gate.status == FlowNodeRunStatus.RUNNING
    assert gate.input == {"question": "Ship v4?", "assignee": None}
    assert node_rows(db_session, run_id, "ship") == [], "ran past the approval"
    assert node_rows(db_session, run_id, "untaken")[0].status == (
        FlowNodeRunStatus.SKIPPED
    )

    prepare_finished_at = node_rows(db_session, run_id, "prepare")[0].finished_at

    apply_human_decision(
        db_session=db_session,
        run=run,
        node_id="gate",
        decision="approve",
        comment="numbers look right",
        decided_by="ada@example.test",
    )
    db_session.commit()
    assert run.status == FlowRunStatus.QUEUED

    run_flow_logic(run_id)
    db_session.expire_all()

    run = get_run(db_session=db_session, run_id=run_id)
    assert run is not None
    assert run.status == FlowRunStatus.SUCCEEDED
    # Output is boxed under "value" on the row so the column keeps one shape.
    shipped = node_rows(db_session, run_id, "ship")[0].output
    assert shipped is not None and shipped["value"] == {"value": "shipped"}
    assert node_rows(db_session, run_id, "gate")[0].output["value"]["decided_by"] == (
        "ada@example.test"
    )

    # The replayed nodes were reused, not re-executed.
    assert node_rows(db_session, run_id, "prepare")[0].finished_at == (
        prepare_finished_at
    )
    assert len(node_rows(db_session, run_id, "untaken")) == 1, (
        "the untaken branch was recorded twice by the replay"
    )


def test_rejecting_an_approval_with_no_reject_branch_fails_the_run(
    db_session: Session, owner: User
) -> None:
    run_id = gated_run(db_session, owner, "rejected flow").id
    run_flow_logic(run_id)
    db_session.expire_all()

    run = get_run(db_session=db_session, run_id=run_id)
    assert run is not None
    apply_human_decision(
        db_session=db_session,
        run=run,
        node_id="gate",
        decision="reject",
        comment="wrong build",
        decided_by="ada@example.test",
    )
    db_session.commit()

    run_flow_logic(run_id)
    db_session.expire_all()

    run = get_run(db_session=db_session, run_id=run_id)
    assert run is not None
    assert run.status == FlowRunStatus.FAILED
    assert run.error_class == "decision_rejected"
    assert run.error_detail == "[gate] rejected: wrong build"
    assert node_rows(db_session, run_id, "ship") == []


def test_an_approval_cannot_be_answered_twice(db_session: Session, owner: User) -> None:
    run_id = gated_run(db_session, owner, "double answer flow").id
    run_flow_logic(run_id)
    db_session.expire_all()

    run = get_run(db_session=db_session, run_id=run_id)
    assert run is not None
    answer = {
        "node_id": "gate",
        "decision": "approve",
        "comment": None,
        "decided_by": "ada@example.test",
    }
    apply_human_decision(db_session=db_session, run=run, **answer)
    db_session.commit()

    with pytest.raises(OnyxError, match="not waiting for a decision"):
        apply_human_decision(db_session=db_session, run=run, **answer)


def test_a_parked_run_still_counts_as_in_flight(
    db_session: Session, owner: User
) -> None:
    """A schedule must queue behind an approval, not ask the same person twice."""
    run = gated_run(db_session, owner, "in flight flow")
    run_flow_logic(run.id)
    db_session.expire_all()

    assert has_in_flight_run(db_session=db_session, flow_id=run.flow_id) is True


# ---------------------------------------------------------------------------
# Webhook signing secret
# ---------------------------------------------------------------------------


def test_a_new_flow_gets_a_signing_secret_that_survives_the_column(
    db_session: Session, owner: User
) -> None:
    """Minted on create, and the same value comes back out.

    The column is an EncryptedString, so the value makes a round trip through
    the type decorator rather than being stored as given. Whether that round
    trip actually encrypts depends on the deployment's key, which is the
    type's own business — what matters here is that a receiver's configured
    secret still matches what the flow will sign with.
    """
    flow = make_flow(db_session, owner, name="signed flow")

    assert flow.webhook_signing_secret is not None
    secret = flow.webhook_signing_secret.get_value(apply_mask=False)
    assert len(secret) > 20, "too short to be worth signing with"

    db_session.expire_all()
    reloaded = get_flow(db_session=db_session, flow_id=flow.id, user_id=owner.id)
    assert reloaded.webhook_signing_secret is not None
    assert reloaded.webhook_signing_secret.get_value(apply_mask=False) == secret


def test_minting_a_signing_secret_is_idempotent(
    db_session: Session, owner: User
) -> None:
    flow = make_flow(db_session, owner, name="stable secret flow")
    first = ensure_webhook_signing_secret(db_session=db_session, flow=flow)

    second = ensure_webhook_signing_secret(db_session=db_session, flow=flow)

    assert second == first, "a receiver's configured secret must not move"


def test_a_flow_without_a_secret_gets_one_on_demand(
    db_session: Session, owner: User
) -> None:
    """Flows written before webhook nodes existed have NULL here."""
    flow = make_flow(db_session, owner, name="legacy flow")
    flow.webhook_signing_secret = None
    db_session.commit()

    minted = ensure_webhook_signing_secret(db_session=db_session, flow=flow)
    db_session.commit()

    assert minted
    assert flow.webhook_signing_secret is not None
    assert flow.webhook_signing_secret.get_value(apply_mask=False) == minted
