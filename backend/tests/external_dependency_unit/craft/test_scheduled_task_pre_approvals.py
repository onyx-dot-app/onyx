"""Scheduled-task pre-approvals (ext-dep): real SQL for the grant lookup,
the pre-decided insert, and the grant patch semantics.

The gate-side short-circuit behavior (skip park / fall through / DENY
ordering) is covered with stubs in ``tests/unit/sandbox_proxy/test_gate.py``;
this file pins the queries those stubs stand in for.
"""

from __future__ import annotations

from typing import Callable

import pytest
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import ApprovalDecidedVia
from onyx.db.enums import ApprovalDecision
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.models import BuildSession
from onyx.db.models import ExternalApp
from onyx.db.models import ScheduledTask
from onyx.db.models import ScheduledTaskPreApprovedApp
from onyx.db.models import User
from onyx.db.scheduled_task import create_scheduled_task
from onyx.db.scheduled_task import get_live_scheduled_run_grants
from onyx.db.scheduled_task import insert_run
from onyx.db.scheduled_task import mark_run_status
from onyx.db.scheduled_task import update_scheduled_task
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.db.action_approval import insert_action_approval
from onyx.server.features.build.scheduled_tasks import api as scheduled_tasks_api
from tests.external_dependency_unit.craft._test_helpers import default_action_entries
from tests.external_dependency_unit.craft._test_helpers import make_external_app
from tests.external_dependency_unit.craft._test_helpers import make_skill
from tests.external_dependency_unit.craft._test_helpers import make_user


def _make_app(db_session: Session) -> int:
    """Create a real ``ExternalApp`` and return its id. Grants now FK to
    ``external_app``, so tests can't use arbitrary ints."""
    app = make_external_app(db_session, skill=make_skill(db_session), auth_template={})
    return app.id


def _seed_task(
    db_session: Session,
    user: User,
    *,
    pre_approved_app_ids: list[int] | None = None,
    prompt: str = "Summarise yesterday's events",
) -> ScheduledTask:
    task = create_scheduled_task(
        db_session=db_session,
        user_id=user.id,
        name="nightly-report",
        prompt=prompt,
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        status=ScheduledTaskStatus.ACTIVE,
        pre_approved_app_ids=pre_approved_app_ids,
    )
    db_session.commit()
    db_session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# get_live_scheduled_run_grants
# ---------------------------------------------------------------------------


def test_grants_returned_for_running_run(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    user = make_user(db_session)
    bs = build_session_with_user(user=user)
    app_a, app_b = _make_app(db_session), _make_app(db_session)
    task = _seed_task(db_session, user, pre_approved_app_ids=[app_a, app_b])
    run = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
    )
    mark_run_status(
        db_session=db_session,
        run_id=run.id,
        status=ScheduledTaskRunStatus.RUNNING,
        session_id=bs.id,
    )
    db_session.commit()

    grants = get_live_scheduled_run_grants(db_session=db_session, session_id=bs.id)

    assert grants is not None
    run_id, app_ids = grants
    assert run_id == run.id
    assert app_ids == [app_a, app_b]


@pytest.mark.parametrize(
    "status",
    [
        ScheduledTaskRunStatus.SUCCEEDED,
        ScheduledTaskRunStatus.FAILED,
        ScheduledTaskRunStatus.AWAITING_APPROVAL,
    ],
)
def test_no_grants_for_non_running_run(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
    status: ScheduledTaskRunStatus,
) -> None:
    """A finished scheduled session (interactive follow-up turns) parks as
    usual — the RUNNING filter is the load-bearing scope guard."""
    user = make_user(db_session)
    bs = build_session_with_user(user=user)
    task = _seed_task(db_session, user, pre_approved_app_ids=[_make_app(db_session)])
    run = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
    )
    mark_run_status(
        db_session=db_session,
        run_id=run.id,
        status=status,
        session_id=bs.id,
    )
    db_session.commit()

    assert (
        get_live_scheduled_run_grants(db_session=db_session, session_id=bs.id) is None
    )


def test_no_grants_for_interactive_session(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """Sessions with no run row (interactive origin) never match."""
    user = make_user(db_session)
    bs = build_session_with_user(user=user)

    assert (
        get_live_scheduled_run_grants(db_session=db_session, session_id=bs.id) is None
    )


# ---------------------------------------------------------------------------
# insert_action_approval — pre-decided rows
# ---------------------------------------------------------------------------


def test_insert_pre_decided_row(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    user = make_user(db_session)
    bs = build_session_with_user(user=user)

    row = insert_action_approval(
        db_session,
        session_id=bs.id,
        actions=default_action_entries(),
        app_name="Slack",
        payload={"text": "hi"},
        decision=ApprovalDecision.APPROVED,
        decided_via=ApprovalDecidedVia.PRE_APPROVAL,
    )
    db_session.commit()
    db_session.refresh(row)

    assert row.decision == ApprovalDecision.APPROVED
    assert row.decided_via == ApprovalDecidedVia.PRE_APPROVAL
    assert row.decided_at is not None
    assert row.decided_at.tzinfo is not None


def test_insert_default_row_stays_pending(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    user = make_user(db_session)
    bs = build_session_with_user(user=user)

    row = insert_action_approval(
        db_session,
        session_id=bs.id,
        actions=default_action_entries(),
        app_name="Slack",
        payload={},
    )
    db_session.commit()
    db_session.refresh(row)

    assert row.decision is None
    assert row.decided_at is None
    assert row.decided_via is None
    assert row.external_app_id is None


# ---------------------------------------------------------------------------
# update_scheduled_task — grant patch semantics
# ---------------------------------------------------------------------------


def test_prompt_change_preserves_grants(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Grants are explicit state surfaced as checkboxes in the editor: a
    prompt edit that omits ``pre_approved_app_ids`` leaves them untouched."""
    user = make_user(db_session)
    app = _make_app(db_session)
    task = _seed_task(db_session, user, pre_approved_app_ids=[app], prompt="orig")

    updated = update_scheduled_task(
        db_session=db_session,
        task_id=task.id,
        user_id=user.id,
        prompt="a rewritten prompt",
    )
    db_session.commit()

    assert updated.pre_approved_app_ids == [app]


def test_supplied_grants_replace_existing(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Supplying ``pre_approved_app_ids`` replaces the set wholesale —
    dropping omitted apps and adding new ones."""
    user = make_user(db_session)
    app_a, app_b = _make_app(db_session), _make_app(db_session)
    task = _seed_task(db_session, user, pre_approved_app_ids=[app_a])

    updated = update_scheduled_task(
        db_session=db_session,
        task_id=task.id,
        user_id=user.id,
        pre_approved_app_ids=[app_b],
    )
    db_session.commit()

    assert updated.pre_approved_app_ids == [app_b]


def test_resubmitting_existing_grant_is_idempotent(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Re-submitting an already-granted app must not orphan+reinsert the same
    (task, app) unique key in one flush (which Postgres rejects). The editor
    re-sends current grants on every save, so this is the common path."""
    user = make_user(db_session)
    app_a, app_b = _make_app(db_session), _make_app(db_session)
    task = _seed_task(db_session, user, pre_approved_app_ids=[app_a])

    updated = update_scheduled_task(
        db_session=db_session,
        task_id=task.id,
        user_id=user.id,
        pre_approved_app_ids=[app_a, app_b],  # app_a already granted
    )
    db_session.commit()

    assert set(updated.pre_approved_app_ids) == {app_a, app_b}


def test_create_persists_grants(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = make_user(db_session)
    app_a, app_b = _make_app(db_session), _make_app(db_session)
    assert app_a < app_b  # ids autoincrement, so the higher id is created last
    # Insertion order is preserved (not sorted): pass the higher id first.
    task = _seed_task(db_session, user, pre_approved_app_ids=[app_b, app_a])
    assert task.pre_approved_app_ids == [app_b, app_a]

    bare = _seed_task(db_session, user)
    assert bare.pre_approved_app_ids == []


# ---------------------------------------------------------------------------
# FK referential actions (deliberate, documented ondelete choices)
# ---------------------------------------------------------------------------


def test_deleting_app_drops_grants(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """``external_app_id`` is ``ON DELETE CASCADE``: removing an app drops its
    grant rows — a grant on a removed app is meaningless."""
    user = make_user(db_session)
    app_id = _make_app(db_session)
    task = _seed_task(db_session, user, pre_approved_app_ids=[app_id])
    assert task.pre_approved_app_ids == [app_id]

    db_session.execute(delete(ExternalApp).where(ExternalApp.id == app_id))
    db_session.commit()

    remaining = (
        db_session.execute(
            select(ScheduledTaskPreApprovedApp).where(
                ScheduledTaskPreApprovedApp.scheduled_task_id == task.id
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


def test_deleting_app_nulls_action_approval_fk(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    build_session_with_user: Callable[..., BuildSession],
) -> None:
    """``action_approval.external_app_id`` is ``ON DELETE SET NULL``: an audit
    row survives app deletion with the FK cleared, not cascaded away."""
    user = make_user(db_session)
    bs = build_session_with_user(user=user)
    app_id = _make_app(db_session)
    row = insert_action_approval(
        db_session,
        session_id=bs.id,
        actions=default_action_entries(),
        app_name="Slack",
        payload={},
        external_app_id=app_id,
        decision=ApprovalDecision.APPROVED,
        decided_via=ApprovalDecidedVia.PRE_APPROVAL,
    )
    db_session.commit()
    assert row.external_app_id == app_id

    db_session.execute(delete(ExternalApp).where(ExternalApp.id == app_id))
    db_session.commit()
    db_session.refresh(row)

    assert row.external_app_id is None


# ---------------------------------------------------------------------------
# API validation helper
# ---------------------------------------------------------------------------


def test_validated_app_ids_rejects_unknown_and_dedupes(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dedupe is order-preserving; any id outside the tenant's apps raises
    INVALID_INPUT. Apps are stubbed — only the validation logic is under
    test, not ``get_external_apps``'s SQL."""

    class _App:
        def __init__(self, app_id: int) -> None:
            self.id = app_id

    monkeypatch.setattr(
        scheduled_tasks_api,
        "get_external_apps",
        lambda _db: [_App(7), _App(9)],
    )

    assert scheduled_tasks_api._validated_app_ids(db_session, []) == []
    assert scheduled_tasks_api._validated_app_ids(db_session, [9, 7, 9]) == [9, 7]

    with pytest.raises(OnyxError) as exc_info:
        scheduled_tasks_api._validated_app_ids(db_session, [7, 123])
    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
