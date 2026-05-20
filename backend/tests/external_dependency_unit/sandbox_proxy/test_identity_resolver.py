"""External-dependency-unit tests for `IdentityResolver`.

Unit tests stub `Session.scalar`; this file exercises the real ORM
queries against Postgres so a schema-level regression (column rename,
enum drift, ordering change) actually fails the test.
"""

import datetime as dt
from collections.abc import Generator
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import BuildSessionStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.sandbox_proxy.identity import IdentityResolver
from onyx.sandbox_proxy.identity import SandboxIdentity
from onyx.sandbox_proxy.identity import SandboxIPLookup
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import create_test_user


class _StaticLookup(SandboxIPLookup):
    def __init__(self, identity: SandboxIdentity | None) -> None:
        self._identity = identity

    def start(self) -> None:
        return None

    def lookup(self, src_ip: str) -> SandboxIdentity | None:  # noqa: ARG002
        return self._identity

    def wait_for_initial_sync(
        self,
        timeout_seconds: float,  # noqa: ARG002
    ) -> bool:
        return True

    def is_synced(self) -> bool:
        return True

    def stop(self) -> None:
        return None


def _resolver_with(identity: SandboxIdentity | None) -> IdentityResolver:
    return IdentityResolver(
        ip_lookup=_StaticLookup(identity),
        db_session_factory=lambda tenant_id: get_session_with_tenant(
            tenant_id=tenant_id
        ),
    )


@pytest.fixture
def seeded_sandbox(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[UUID, UUID, UUID], None, None]:
    """Sandbox owned by a fresh user with one ACTIVE BuildSession.

    Yields (sandbox_id, user_id, active_session_id).
    """
    user = create_test_user(db_session, "identity_resolver")

    sandbox = Sandbox(id=uuid4(), user_id=user.id)
    db_session.add(sandbox)

    active_session = BuildSession(
        id=uuid4(),
        user_id=user.id,
        status=BuildSessionStatus.ACTIVE,
        last_activity_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(active_session)
    db_session.commit()

    yield sandbox.id, user.id, active_session.id


def _identity_for(sandbox_id: UUID) -> SandboxIdentity:
    return SandboxIdentity(
        sandbox_id=sandbox_id,
        tenant_id=POSTGRES_DEFAULT_SCHEMA,
        sandbox_name="sandbox-xxxx",
        sandbox_ip="10.0.0.1",
    )


def test_resolves_active_session(
    seeded_sandbox: tuple[UUID, UUID, UUID],
) -> None:
    sandbox_id, user_id, active_session_id = seeded_sandbox
    ctx = _resolver_with(_identity_for(sandbox_id)).resolve("10.0.0.1")

    assert ctx is not None
    assert ctx.session_id == active_session_id
    assert ctx.user_id == user_id
    assert ctx.sandbox_id == sandbox_id


def test_returns_none_when_sandbox_missing() -> None:
    ctx = _resolver_with(_identity_for(uuid4())).resolve("10.0.0.1")
    assert ctx is None


def test_returns_none_when_no_active_session(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "no_active")
    sandbox = Sandbox(id=uuid4(), user_id=user.id)
    db_session.add(sandbox)
    idle = BuildSession(
        id=uuid4(),
        user_id=user.id,
        status=BuildSessionStatus.IDLE,
        last_activity_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(idle)
    db_session.commit()

    ctx = _resolver_with(_identity_for(sandbox.id)).resolve("10.0.0.1")
    assert ctx is None


def test_picks_most_recent_active_session(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "two_active")
    sandbox = Sandbox(id=uuid4(), user_id=user.id)
    db_session.add(sandbox)

    now = dt.datetime.now(dt.timezone.utc)
    older = BuildSession(
        id=uuid4(),
        user_id=user.id,
        status=BuildSessionStatus.ACTIVE,
        last_activity_at=now - dt.timedelta(minutes=10),
    )
    newer = BuildSession(
        id=uuid4(),
        user_id=user.id,
        status=BuildSessionStatus.ACTIVE,
        last_activity_at=now,
    )
    db_session.add(older)
    db_session.add(newer)
    db_session.commit()

    ctx = _resolver_with(_identity_for(sandbox.id)).resolve("10.0.0.1")
    assert ctx is not None
    assert ctx.session_id == newer.id
