from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID
from uuid import uuid4

import pytest

from onyx.sandbox_proxy import identity as identity_mod
from onyx.sandbox_proxy.identity import IdentityResolver
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.identity import SandboxIdentity
from tests.unit.sandbox_proxy.conftest import StaticLookup


class _StubSession:
    """Stand-in for SQLAlchemy `Session`; returns canned scalar() results in order."""

    def __init__(self, scalar_results: list[Any]) -> None:
        self._results = list(scalar_results)
        self.scalar_calls = 0

    def scalar(self, _stmt: Any) -> Any:
        self.scalar_calls += 1
        return self._results.pop(0)


def _factory(stub: _StubSession) -> Any:
    @contextmanager
    def factory(tenant_id: str) -> Iterator[_StubSession]:
        factory.last_tenant_id = tenant_id  # ty: ignore[unresolved-attribute]
        yield stub

    factory.last_tenant_id = None  # ty: ignore[unresolved-attribute]
    return factory


def _identity(ip: str = "10.0.0.1") -> SandboxIdentity:
    return SandboxIdentity(
        sandbox_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id="public",
        sandbox_name="sandbox-aaaa1111",
        sandbox_ip=ip,
    )


# ---------------------------------------------------------------------------
# resolve_sandbox — pod IP → sandbox + user (no session lookup)
# ---------------------------------------------------------------------------


def test_resolve_sandbox_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox_user_id = uuid4()
    stub = _StubSession([sandbox_user_id])
    lookup = StaticLookup({"10.0.0.1": _identity()})
    factory = _factory(stub)

    monkeypatch.setattr(identity_mod, "get_session_with_tenant", factory)
    resolver = IdentityResolver(ip_lookup=lookup)
    sandbox = resolver.resolve_sandbox("10.0.0.1")

    assert sandbox is not None
    assert sandbox.user_id == sandbox_user_id
    assert sandbox.sandbox_id == UUID("11111111-1111-1111-1111-111111111111")
    # Tenant must be threaded into the DB factory for the per-tenant session.
    assert sandbox.tenant_id == "public"
    assert factory.last_tenant_id == "public"
    # Only the sandbox-user query runs here; session lookup is deferred to
    # resolve_session_by_id() so non-gated traffic avoids an extra round-trip.
    assert stub.scalar_calls == 1


def test_resolve_sandbox_unknown_ip_skips_db(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubSession([])
    lookup = StaticLookup({})
    factory = _factory(stub)

    monkeypatch.setattr(identity_mod, "get_session_with_tenant", factory)
    resolver = IdentityResolver(ip_lookup=lookup)

    assert resolver.resolve_sandbox("203.0.113.10") is None
    assert stub.scalar_calls == 0
    assert factory.last_tenant_id is None


def test_resolve_sandbox_missing_sandbox_row_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubSession([None])
    lookup = StaticLookup({"10.0.0.1": _identity()})
    factory = _factory(stub)

    monkeypatch.setattr(identity_mod, "get_session_with_tenant", factory)
    resolver = IdentityResolver(ip_lookup=lookup)

    assert resolver.resolve_sandbox("10.0.0.1") is None
    assert stub.scalar_calls == 1


# ---------------------------------------------------------------------------
# resolve_session_by_id — validate the in-band tag against its owner
# ---------------------------------------------------------------------------


def test_resolve_session_by_id_propagates_scalar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin both the verified (id returned) and unverified (None) cases so a
    change like wrapping the scalar in a default would fail here."""
    found_id = uuid4()
    stub = _StubSession([found_id, None])
    factory = _factory(stub)
    monkeypatch.setattr(identity_mod, "get_session_with_tenant", factory)
    resolver = IdentityResolver(ip_lookup=StaticLookup({}))

    assert resolver.resolve_session_by_id(found_id, uuid4(), "public") == found_id
    assert resolver.resolve_session_by_id(uuid4(), uuid4(), "public") is None
    assert factory.last_tenant_id == "public"
    assert stub.scalar_calls == 2


# ---------------------------------------------------------------------------
# `with_session` / `without_session` round-trip (the credential-injection seam
# unpacks the SessionContext back to a ResolvedSandbox on ASK→APPROVED).
# ---------------------------------------------------------------------------


def test_with_session_then_without_session_round_trips() -> None:
    """A regression that drops any field would silently break ASK→APPROVED
    credential injection, where resolvers key off `sandbox_id` and `user_id`."""
    sandbox = ResolvedSandbox(
        sandbox_id=uuid4(),
        user_id=uuid4(),
        tenant_id="tenant-xyz",
        sandbox_name="sandbox-1",
        sandbox_ip="10.0.0.99",
    )
    session_id = uuid4()

    assert sandbox.with_session(session_id).without_session() == sandbox
