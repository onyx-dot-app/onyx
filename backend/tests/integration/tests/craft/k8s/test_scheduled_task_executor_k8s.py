"""Scheduled-task executor wake-failure contract in the Craft k8s lane."""

from __future__ import annotations

import datetime
from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from onyx.db.enums import AccountType
from onyx.db.enums import SandboxStatus
from onyx.db.enums import ScheduledTaskErrorClass
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.models import Sandbox
from onyx.db.models import ScheduledTask
from onyx.db.models import ScheduledTaskRun
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.scheduled_tasks.executor import run_scheduled_task_logic

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)


@pytest.fixture
def scheduled_task_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[User, None, None]:
    helper = PasswordHelper()
    user = User(
        id=uuid4(),
        email=f"craft_k8s_sched_{uuid4().hex[:8]}@example.com",
        hashed_password=helper.hash(helper.generate()),
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=UserRole.EXT_PERM_USER,
        account_type=AccountType.EXT_PERM_USER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    try:
        yield user
    finally:
        db_session.rollback()
        row = db_session.get(User, user.id)
        if row is not None:
            db_session.delete(row)
            db_session.commit()


def _seed_task_and_queued_run(db_session: Session, user: User) -> ScheduledTaskRun:
    task = ScheduledTask(
        user_id=user.id,
        name="nightly-report",
        prompt="Summarise yesterday's events",
        cron_expression="0 9 * * *",
        editor_mode="advanced",
        status=ScheduledTaskStatus.ACTIVE,
        next_run_at=datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(days=1),
    )
    db_session.add(task)
    db_session.flush()
    run = ScheduledTaskRun(
        task_id=task.id,
        status=ScheduledTaskRunStatus.QUEUED,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
        started_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def test_run_fails_when_wake_fails(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    scheduled_task_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Seed PROVISIONING + 0s wait window so the wake deterministically raises,
    # which must mark the run FAILED / sandbox_wake_failed.
    monkeypatch.setattr(
        "onyx.server.features.build.scheduled_tasks.executor.PROVISIONING_WAIT_SECONDS",
        0,
    )

    user = scheduled_task_user
    sandbox = Sandbox(id=uuid4(), user_id=user.id, status=SandboxStatus.PROVISIONING)
    db_session.add(sandbox)
    db_session.commit()

    run = _seed_task_and_queued_run(db_session, user)

    run_scheduled_task_logic(run.id)

    db_session.expire_all()
    refreshed = db_session.get(ScheduledTaskRun, run.id)
    assert refreshed is not None
    assert refreshed.status == ScheduledTaskRunStatus.FAILED
    assert refreshed.error_class == ScheduledTaskErrorClass.SANDBOX_WAKE_FAILED.value
