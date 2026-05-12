"""Fixtures for scheduled-tasks background-worker tests.

The shared `tenant_context` / `db_session` / `test_user` fixtures live in
the craft test conftest already; we don't redefine them here. This module
adds the scheduled-task-specific helpers: a running sandbox + factory
helpers for tasks and runs.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from uuid import uuid4

import pytest
from fastapi_users.password import PasswordHelper
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import AccountType
from onyx.db.enums import SandboxStatus
from onyx.db.enums import ScheduledTaskStatus
from onyx.db.models import Sandbox
from onyx.db.models import ScheduledTask
from onyx.db.models import User
from onyx.db.models import UserRole
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID

# ---------------------------------------------------------------------------
# Re-exported core fixtures — duplicated from `craft/conftest.py` so this
# package can be invoked on its own without importing from a sibling.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    with get_session_with_current_tenant() as session:
        yield session


@pytest.fixture(scope="function")
def tenant_context() -> Generator[None, None, None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="function")
def test_user(db_session: Session, tenant_context: None) -> User:  # noqa: ARG001
    """Create a test user owned by this test."""
    unique_email = f"sched_test_{uuid4().hex[:8]}@example.com"
    password_helper = PasswordHelper()
    password = password_helper.generate()
    hashed_password = password_helper.hash(password)

    user = User(
        id=uuid4(),
        email=unique_email,
        hashed_password=hashed_password,
        is_active=True,
        is_superuser=False,
        is_verified=True,
        role=UserRole.EXT_PERM_USER,
        account_type=AccountType.EXT_PERM_USER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def running_sandbox(
    db_session: Session,
    test_user: User,
    tenant_context: None,  # noqa: ARG001
) -> Sandbox:
    """A RUNNING Sandbox for the test user (executor requires this)."""
    sandbox = Sandbox(
        id=uuid4(),
        user_id=test_user.id,
        status=SandboxStatus.RUNNING,
    )
    db_session.add(sandbox)
    db_session.commit()
    db_session.refresh(sandbox)
    return sandbox


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def make_task(
    db_session: Session,
    test_user: User,
    tenant_context: None,  # noqa: ARG001
) -> Callable[..., ScheduledTask]:
    """Factory that inserts a ScheduledTask row with sane defaults.

    Keyword args override the defaults. The task is committed before
    returning so callers can mutate / refetch as needed.
    """

    def _factory(
        *,
        name: str = "Test Task",
        prompt: str = "do the thing",
        cron_expression: str = "*/5 * * * *",
        timezone_name: str = "UTC",
        editor_mode: str = "interval",
        status: ScheduledTaskStatus = ScheduledTaskStatus.ACTIVE,
        next_run_at: datetime | None = None,
        deleted: bool = False,
        user: User | None = None,
    ) -> ScheduledTask:
        owner = user or test_user
        task = ScheduledTask(
            id=uuid4(),
            user_id=owner.id,
            name=name,
            prompt=prompt,
            cron_expression=cron_expression,
            timezone=timezone_name,
            editor_mode=editor_mode,
            status=status,
            # Default: due 1 second ago so claim_due_scheduled_tasks picks it up.
            next_run_at=(
                next_run_at
                if next_run_at is not None
                else datetime.now(tz=timezone.utc).replace(microsecond=0)
            ),
            deleted=deleted,
        )
        db_session.add(task)
        db_session.commit()
        db_session.refresh(task)
        return task

    return _factory
