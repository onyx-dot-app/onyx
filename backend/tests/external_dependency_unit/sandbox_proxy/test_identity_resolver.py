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

from onyx.db.enums import BuildSessionStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.sandbox_proxy.identity import IdentityResolver
from onyx.sandbox_proxy.identity import SandboxIdentity
from shared_configs.contextvars import POSTGRES_DEFAULT_SCHEMA
from tests.external_dependency_unit.conftest import create_test_user
from tests.unit.sandbox_proxy.conftest import StaticLookup


def _resolver_with(identity: SandboxIdentity | None) -> IdentityResolver:
    return IdentityResolver(ip_lookup=StaticLookup.single(identity))


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


# ---------------------------------------------------------------------------
# resolve_sandbox — pod IP → user/tenant (no session lookup)
# ---------------------------------------------------------------------------


def test_resolve_sandbox_returns_owner_for_known_pod(
    seeded_sandbox: tuple[UUID, UUID, UUID],
) -> None:
    sandbox_id, user_id, _ = seeded_sandbox
    sandbox = _resolver_with(_identity_for(sandbox_id)).resolve_sandbox("10.0.0.1")

    assert sandbox is not None
    assert sandbox.sandbox_id == sandbox_id
    assert sandbox.user_id == user_id
    assert sandbox.tenant_id == POSTGRES_DEFAULT_SCHEMA


def test_resolve_sandbox_returns_none_when_sandbox_row_missing() -> None:
    sandbox = _resolver_with(_identity_for(uuid4())).resolve_sandbox("10.0.0.1")
    assert sandbox is None


def test_resolve_sandbox_succeeds_without_any_active_session(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Pod identity must resolve even when every session is IDLE.

    Regression for the "npm install gets 403 with no ACTIVE session" bug:
    non-gated egress depends on identity being independent of session liveness.
    """
    user = create_test_user(db_session, "identity_no_session")
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

    resolved = _resolver_with(_identity_for(sandbox.id)).resolve_sandbox("10.0.0.1")
    assert resolved is not None
    assert resolved.user_id == user.id


# ---------------------------------------------------------------------------
# resolve_session_by_id — exact in-band tag, validated against the owner
# ---------------------------------------------------------------------------


def test_resolve_session_by_id_returns_id_for_owning_user(
    seeded_sandbox: tuple[UUID, UUID, UUID],
) -> None:
    _, user_id, active_session_id = seeded_sandbox
    resolver = _resolver_with(None)
    found = resolver.resolve_session_by_id(
        active_session_id, user_id, POSTGRES_DEFAULT_SCHEMA
    )
    assert found == active_session_id


def test_resolve_session_by_id_rejects_other_users_session(
    db_session: Session,
    seeded_sandbox: tuple[UUID, UUID, UUID],
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Cross-user guard: a tag naming another user's session must NOT resolve;
    the user_id from the unforgeable source IP wins."""
    _, _owner_id, victim_session_id = seeded_sandbox
    attacker = create_test_user(db_session, "tag_attacker")
    db_session.commit()

    resolver = _resolver_with(None)
    found = resolver.resolve_session_by_id(
        victim_session_id, attacker.id, POSTGRES_DEFAULT_SCHEMA
    )
    assert found is None


def test_resolve_session_by_id_returns_none_for_unknown_session(
    seeded_sandbox: tuple[UUID, UUID, UUID],
) -> None:
    _, user_id, _ = seeded_sandbox
    resolver = _resolver_with(None)
    found = resolver.resolve_session_by_id(uuid4(), user_id, POSTGRES_DEFAULT_SCHEMA)
    assert found is None
