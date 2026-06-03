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
    claim_due_triggers,
    create_flow,
    finish_node_run,
    get_flow,
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
