from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID
from uuid import uuid4

from onyx.sandbox_proxy.identity import IdentityResolver
from onyx.sandbox_proxy.identity import SandboxIdentity
from onyx.sandbox_proxy.identity import SandboxIPLookup


class _StaticLookup(SandboxIPLookup):
    def __init__(self, cache: dict[str, SandboxIdentity]) -> None:
        self._cache = cache

    def lookup(self, src_ip: str) -> SandboxIdentity | None:
        return self._cache.get(src_ip)

    def wait_for_initial_sync(
        self,
        timeout_seconds: float,  # noqa: ARG002
    ) -> bool:
        return True

    def is_synced(self) -> bool:
        return True

    def stop(self) -> None:
        return None


class _StubSession:
    """Stand-in for SQLAlchemy `Session`; returns canned scalar()
    results in queue order."""

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


def test_happy_path_resolves_session_context() -> None:
    sandbox_user_id = uuid4()
    active_session_id = uuid4()
    stub = _StubSession([sandbox_user_id, active_session_id])
    lookup = _StaticLookup({"10.0.0.1": _identity()})
    factory = _factory(stub)

    resolver = IdentityResolver(ip_lookup=lookup, db_session_factory=factory)
    ctx = resolver.resolve("10.0.0.1")

    assert ctx is not None
    assert ctx.session_id == active_session_id
    assert ctx.user_id == sandbox_user_id
    assert ctx.sandbox_id == UUID("11111111-1111-1111-1111-111111111111")
    assert ctx.tenant_id == "public"
    assert ctx.sandbox_name == "sandbox-aaaa1111"
    assert ctx.sandbox_ip == "10.0.0.1"
    assert factory.last_tenant_id == "public"
    assert stub.scalar_calls == 2


def test_unknown_ip_returns_none_without_db_calls() -> None:
    stub = _StubSession([])
    lookup = _StaticLookup({})
    factory = _factory(stub)

    resolver = IdentityResolver(ip_lookup=lookup, db_session_factory=factory)

    assert resolver.resolve("203.0.113.10") is None
    assert stub.scalar_calls == 0
    assert factory.last_tenant_id is None


def test_missing_sandbox_row_returns_none() -> None:
    stub = _StubSession([None])
    lookup = _StaticLookup({"10.0.0.1": _identity()})
    factory = _factory(stub)

    resolver = IdentityResolver(ip_lookup=lookup, db_session_factory=factory)

    assert resolver.resolve("10.0.0.1") is None
    # Short-circuit: only the sandbox-user lookup fires.
    assert stub.scalar_calls == 1


def test_no_active_session_returns_none() -> None:
    sandbox_user_id = uuid4()
    stub = _StubSession([sandbox_user_id, None])
    lookup = _StaticLookup({"10.0.0.1": _identity()})
    factory = _factory(stub)

    resolver = IdentityResolver(ip_lookup=lookup, db_session_factory=factory)

    assert resolver.resolve("10.0.0.1") is None
    assert stub.scalar_calls == 2


def test_tenant_id_threaded_to_db_factory() -> None:
    identity = SandboxIdentity(
        sandbox_id=UUID("22222222-2222-2222-2222-222222222222"),
        tenant_id="tenant_acme",
        sandbox_name="sandbox-xxxx2222",
        sandbox_ip="10.0.0.2",
    )
    stub = _StubSession([uuid4(), uuid4()])
    lookup = _StaticLookup({"10.0.0.2": identity})
    factory = _factory(stub)

    resolver = IdentityResolver(ip_lookup=lookup, db_session_factory=factory)
    ctx = resolver.resolve("10.0.0.2")

    assert ctx is not None
    assert ctx.tenant_id == "tenant_acme"
    assert factory.last_tenant_id == "tenant_acme"
