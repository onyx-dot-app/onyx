"""Unit tests for the GateAddon mitmproxy addon.

Covers `_resolve_and_match` (fail-closed / fail-open / happy path),
`_write_response_for_decision`, `ParkedApprovals`,
`_persist_approval_row`, `_await_decision`, `drain_inflight`, and
`_terminalize_after_unhandled_error`. All external dependencies
(`_Resolver`, `ActionMatcher`, `CacheFactory`, `DBSessionFactory`) are
stubbed via small Protocol implementations.

The race arbiter (`_claim_expired_or_read_winner`) has unit tests
that would just restate the `try_record_decision` / `get_action_approval`
contract — see `external_dependency_unit/sandbox_proxy/
test_gate_claim_arbiter.py` for the version against a real
Postgres row.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID
from uuid import uuid4

import pytest
from mitmproxy import http
from redis.exceptions import RedisError

from onyx.db.enums import ApprovalDecision
from onyx.sandbox_proxy.action_matcher import ActionMatch
from onyx.sandbox_proxy.addons import gate as gate_mod
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.addons.gate import ParkedApprovals
from onyx.sandbox_proxy.addons.gate import PARSER_MAX_BODY_BYTES
from onyx.sandbox_proxy.identity import ResolvedSandbox
from onyx.sandbox_proxy.identity import SessionContext
from onyx.sandbox_proxy.snapshot_egress import SnapshotEgressPolicy

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


_SENTINEL = object()


class _StubResolver:
    """Implements the gate's `_Resolver` Protocol with canned returns."""

    def __init__(
        self,
        *,
        sandbox: Any = _SENTINEL,
        sandbox_exc: Exception | None = None,
        session: Any = _SENTINEL,
        session_exc: Exception | None = None,
        session_by_id: Any = _SENTINEL,
        session_by_id_exc: Exception | None = None,
    ) -> None:
        self._sandbox = sandbox
        self._sandbox_exc = sandbox_exc
        self._session = session
        self._session_exc = session_exc
        self._session_by_id = session_by_id
        self._session_by_id_exc = session_by_id_exc
        self.resolve_sandbox_calls = 0
        self.resolve_active_session_calls = 0
        self.resolve_session_by_id_calls: list[tuple[UUID, UUID, str]] = []

    def resolve_sandbox(
        self,
        src_ip: str,  # noqa: ARG002
    ) -> ResolvedSandbox | None:
        self.resolve_sandbox_calls += 1
        if self._sandbox_exc is not None:
            raise self._sandbox_exc
        return None if self._sandbox is _SENTINEL else self._sandbox  # type: ignore[no-any-return]

    def resolve_active_session(
        self,
        user_id: UUID,  # noqa: ARG002
        tenant_id: str,  # noqa: ARG002
    ) -> UUID | None:
        self.resolve_active_session_calls += 1
        if self._session_exc is not None:
            raise self._session_exc
        return None if self._session is _SENTINEL else self._session  # type: ignore[no-any-return]

    def resolve_session_by_id(
        self,
        session_id: UUID,
        user_id: UUID,
        tenant_id: str,
    ) -> UUID | None:
        self.resolve_session_by_id_calls.append((session_id, user_id, tenant_id))
        if self._session_by_id_exc is not None:
            raise self._session_by_id_exc
        return None if self._session_by_id is _SENTINEL else self._session_by_id  # type: ignore[no-any-return]


class _StubMatcher:
    """Implements `ActionMatcher` Protocol."""

    def __init__(
        self,
        *,
        result: ActionMatch | None = None,
        exc: Exception | None = None,
    ) -> None:
        self._result = result
        self._exc = exc
        self.calls = 0

    def match(
        self,
        request: http.Request,  # noqa: ARG002
    ) -> ActionMatch | None:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._result


def _noop_db_factory(tenant_id: str) -> Any:  # noqa: ARG001
    """A `DBSessionFactory` that should never be called by the tests
    that focus on `_resolve_and_match`."""

    @contextmanager
    def cm() -> Iterator[Any]:
        raise AssertionError("db factory unexpectedly used")
        yield  # pragma: no cover

    return cm()


def _noop_cache_factory(tenant_id: str) -> Any:  # noqa: ARG001
    raise AssertionError("cache factory unexpectedly used")


def _sandbox(
    *,
    user_id: UUID | None = None,
    tenant_id: str = "public",
) -> ResolvedSandbox:
    return ResolvedSandbox(
        sandbox_id=UUID("11111111-1111-1111-1111-111111111111"),
        user_id=user_id if user_id is not None else uuid4(),
        tenant_id=tenant_id,
        sandbox_name="sandbox-aaaa1111",
        sandbox_ip="10.0.0.1",
    )


def _ctx(
    *,
    tenant_id: str = "public",
    session_id: UUID | None = None,
    user_id: UUID | None = None,
) -> SessionContext:
    return SessionContext(
        session_id=session_id if session_id is not None else uuid4(),
        user_id=user_id if user_id is not None else uuid4(),
        sandbox_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=tenant_id,
        sandbox_name="sandbox-aaaa1111",
        sandbox_ip="10.0.0.1",
    )


def _flow(
    *,
    peername: tuple[str, int] | None = ("10.0.0.1", 12345),
    raw_content: bytes | None = b"{}",
    host: str = "slack.com",
    port: int = 443,
    method: str = "POST",
    path_components: tuple[str, ...] = (),
    conn_id: str = "conn-default",
    proxy_auth: str | None = None,
) -> http.HTTPFlow:
    flow = MagicMock(spec=http.HTTPFlow)
    flow.client_conn = MagicMock()
    flow.client_conn.peername = peername
    flow.client_conn.id = conn_id
    flow.request = MagicMock()
    flow.request.host = host
    flow.request.port = port
    flow.request.method = method
    flow.request.path_components = path_components
    flow.request.raw_content = raw_content
    flow.request.stream = False
    # Real dict so header lookups behave like mitmproxy's str|None `.get`,
    # instead of a MagicMock that returns truthy magic objects.
    flow.request.headers = (
        {"Proxy-Authorization": proxy_auth} if proxy_auth is not None else {}
    )
    flow.response = None
    # Real dict, not a MagicMock: `request` reads the snapshot-stream
    # flag off this, and a MagicMock `.get(...)` would be truthy.
    flow.metadata = {}
    return flow


def _build(
    *,
    resolver: _StubResolver,
    matcher: _StubMatcher,
    db_factory: Any = _noop_db_factory,
    cache_factory: Any = _noop_cache_factory,
) -> GateAddon:
    return GateAddon(
        identity=resolver,
        action_matcher=matcher,  # type: ignore[arg-type]
        db_session_factory=db_factory,
        cache_factory=cache_factory,
        proxy_instance_id="proxy-test",
    )


def _assert_403(flow: http.HTTPFlow, expected_code: str) -> None:
    assert flow.response is not None
    assert flow.response.status_code == 403
    content = flow.response.content
    assert content is not None
    body = json.loads(content)
    assert body == {"error": expected_code}


_MATCH = ActionMatch(action_type="slack.post_message", payload={"text": "hi"})


# ---------------------------------------------------------------------------
# _resolve_and_match — fail-closed
# ---------------------------------------------------------------------------


def test_resolve_and_match_no_source_ip_fails_closed() -> None:
    resolver = _StubResolver()
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(resolver=resolver, matcher=matcher)
    flow = _flow(peername=None)

    result = addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, gate_mod._CODE_UNIDENTIFIED_SANDBOX)
    # Short-circuit: resolver / matcher must not have been called.
    assert resolver.resolve_sandbox_calls == 0
    assert matcher.calls == 0


@pytest.mark.parametrize(
    "resolver_kwargs",
    [
        {"sandbox": None},
        {"sandbox_exc": RuntimeError("db down")},
    ],
    ids=["returns_none", "raises"],
)
def test_resolve_and_match_sandbox_resolution_fails_closed(
    resolver_kwargs: dict[str, Any],
) -> None:
    """Both an absent pod and a DB blip during identity resolution must
    fail closed with `unidentified_sandbox`. A leaked exception would
    crash the test; absence of a crash + returning normally is the proof
    that the failure was caught."""
    resolver = _StubResolver(**resolver_kwargs)
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(resolver=resolver, matcher=matcher)
    flow = _flow()

    result = addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, gate_mod._CODE_UNIDENTIFIED_SANDBOX)
    assert matcher.calls == 0


# Hardcode the byte count from the spec rather than re-deriving it from
# the constant under test. A separate completeness check
# (`test_parser_max_body_bytes_constant_matches_spec`) pins the constant.
_OVERSIZE_BODY = b"\x00" * 1_048_577


@pytest.mark.parametrize(
    "raw_content",
    [None, _OVERSIZE_BODY],
    ids=["streamed", "oversize"],
)
def test_resolve_and_match_body_too_large_fails_closed(
    raw_content: bytes | None,
) -> None:
    """`raw_content is None` (streamed) and bodies above the parser
    threshold both fail closed with `body_too_large` per the docstring."""
    resolver = _StubResolver(sandbox=_sandbox())
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(resolver=resolver, matcher=matcher)
    flow = _flow(raw_content=raw_content)

    result = addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, gate_mod._CODE_BODY_TOO_LARGE)
    assert matcher.calls == 0


def test_parser_max_body_bytes_constant_matches_spec() -> None:
    """Completeness check: pin the parser body cap to the documented
    1 MiB. Bumping the constant requires updating this test, which
    forces a deliberate decision rather than silent drift."""
    assert PARSER_MAX_BODY_BYTES == 1_048_576


@pytest.mark.parametrize(
    "resolver_kwargs",
    [
        {"session": None},
        {"session_exc": RuntimeError("db down")},
    ],
    ids=["lookup_returns_none", "lookup_raises"],
)
def test_resolve_and_match_active_session_failure_fails_closed(
    resolver_kwargs: dict[str, Any],
) -> None:
    """Gated request from an identified pod, but no active session to
    route the approval card to (either no row, or a DB blip during the
    lookup) — fail closed with `no_active_session`."""
    resolver = _StubResolver(sandbox=_sandbox(), **resolver_kwargs)
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(resolver=resolver, matcher=matcher)
    flow = _flow()

    result = addon._resolve_and_match(flow)

    assert result is None
    _assert_403(flow, gate_mod._CODE_NO_ACTIVE_SESSION)
    assert resolver.resolve_active_session_calls == 1


# ---------------------------------------------------------------------------
# _resolve_and_match — fail-open
# ---------------------------------------------------------------------------


def test_resolve_and_match_matcher_returns_none_fails_open() -> None:
    """Non-gated traffic: matcher returns None → mitmproxy forwards."""
    resolver = _StubResolver(sandbox=_sandbox())
    matcher = _StubMatcher(result=None)
    addon = _build(resolver=resolver, matcher=matcher)
    flow = _flow()

    result = addon._resolve_and_match(flow)

    assert result is None
    assert flow.response is None  # mitmproxy will forward.
    # Session lookup must NOT happen for non-gated traffic.
    assert resolver.resolve_active_session_calls == 0


def test_resolve_and_match_matcher_raises_fails_open() -> None:
    resolver = _StubResolver(sandbox=_sandbox())
    matcher = _StubMatcher(exc=RuntimeError("matcher boom"))
    addon = _build(resolver=resolver, matcher=matcher)
    flow = _flow()

    result = addon._resolve_and_match(flow)

    assert result is None
    assert flow.response is None
    assert resolver.resolve_active_session_calls == 0


# ---------------------------------------------------------------------------
# _resolve_and_match — happy path
# ---------------------------------------------------------------------------


def test_resolve_and_match_happy_path_promotes_session() -> None:
    user_id = uuid4()
    session_id = uuid4()
    sandbox = _sandbox(user_id=user_id)
    resolver = _StubResolver(sandbox=sandbox, session=session_id)
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(resolver=resolver, matcher=matcher)
    flow = _flow()

    result = addon._resolve_and_match(flow)

    assert result is not None
    ctx, match = result
    assert match is _MATCH
    assert ctx.session_id == session_id
    assert ctx.user_id == user_id
    assert ctx.tenant_id == sandbox.tenant_id
    assert ctx.sandbox_id == sandbox.sandbox_id
    assert flow.response is None


# ---------------------------------------------------------------------------
# In-band session tag — Proxy-Authorization parsing
# ---------------------------------------------------------------------------


def _basic_auth(username: str, password: str = "") -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


_TAG_UUID = "44444444-4444-4444-4444-444444444444"


@pytest.mark.parametrize(
    "header, expected",
    [
        (_basic_auth(_TAG_UUID), _TAG_UUID),  # id-only tag (empty password)
        (_basic_auth(_TAG_UUID, "secret"), _TAG_UUID),  # password ignored
        (
            f"Basic {base64.b64encode(_TAG_UUID.encode()).decode()}",
            _TAG_UUID,
        ),  # no colon
        (None, None),
        ("", None),
        ("Bearer abc", None),  # not basic
        ("Basic !!!notbase64!!!", None),  # undecodable
        ("Basic", None),  # missing token
    ],
)
def test_parse_proxy_auth_username(header: str | None, expected: str | None) -> None:
    assert gate_mod._parse_proxy_auth_username(header) == expected


def test_http_connect_caches_tag_and_client_disconnected_evicts() -> None:
    addon = _build(resolver=_StubResolver(), matcher=_StubMatcher())
    flow = _flow(conn_id="conn-xyz", proxy_auth=_basic_auth(_TAG_UUID))

    addon.http_connect(flow)
    assert addon._conn_session_tags == {"conn-xyz": _TAG_UUID}

    addon.client_disconnected(flow.client_conn)
    assert addon._conn_session_tags == {}


def test_http_connect_ignores_missing_or_garbled_header() -> None:
    addon = _build(resolver=_StubResolver(), matcher=_StubMatcher())
    addon.http_connect(_flow(conn_id="c1"))  # no Proxy-Authorization
    addon.http_connect(_flow(conn_id="c2", proxy_auth="Bearer nope"))
    assert addon._conn_session_tags == {}


# ---------------------------------------------------------------------------
# _resolve_and_match — exact in-band session resolution
# ---------------------------------------------------------------------------


def test_resolve_and_match_exact_tag_on_http_request() -> None:
    """Plain-HTTP request carries Proxy-Authorization directly; a verified
    tag routes to that exact session and skips the heuristic."""
    user_id = uuid4()
    tagged_id = UUID(_TAG_UUID)
    sandbox = _sandbox(user_id=user_id)
    resolver = _StubResolver(sandbox=sandbox, session_by_id=tagged_id)
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    flow = _flow(proxy_auth=_basic_auth(_TAG_UUID))

    result = addon._resolve_and_match(flow)

    assert result is not None
    ctx, _match = result
    assert ctx.session_id == tagged_id
    assert resolver.resolve_session_by_id_calls == [
        (tagged_id, user_id, sandbox.tenant_id)
    ]
    # Exact match wins — the heuristic must NOT run.
    assert resolver.resolve_active_session_calls == 0


def test_resolve_and_match_exact_tag_on_https_connect() -> None:
    """HTTPS: the tag rode on the CONNECT (captured via http_connect),
    not the MITM'd request. It's read back off the connection."""
    user_id = uuid4()
    tagged_id = UUID(_TAG_UUID)
    sandbox = _sandbox(user_id=user_id)
    resolver = _StubResolver(sandbox=sandbox, session_by_id=tagged_id)
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))

    connect_flow = _flow(conn_id="conn-1", proxy_auth=_basic_auth(_TAG_UUID))
    addon.http_connect(connect_flow)
    # The decrypted request has NO Proxy-Authorization header of its own.
    request_flow = _flow(conn_id="conn-1")

    result = addon._resolve_and_match(request_flow)

    assert result is not None
    ctx, _match = result
    assert ctx.session_id == tagged_id
    assert resolver.resolve_active_session_calls == 0


def test_resolve_and_match_unverified_tag_falls_back_to_heuristic() -> None:
    """Tag present but it doesn't resolve to one of this user's sessions
    (stale / foreign / tampered) — fall back to the heuristic, not a 403."""
    heuristic_id = uuid4()
    sandbox = _sandbox()
    resolver = _StubResolver(sandbox=sandbox, session_by_id=None, session=heuristic_id)
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    flow = _flow(proxy_auth=_basic_auth(_TAG_UUID))

    result = addon._resolve_and_match(flow)

    assert result is not None
    ctx, _match = result
    assert ctx.session_id == heuristic_id
    assert len(resolver.resolve_session_by_id_calls) == 1
    assert resolver.resolve_active_session_calls == 1


def test_resolve_and_match_malformed_tag_skips_lookup_and_falls_back() -> None:
    """A non-UUID username never hits the DB; goes straight to heuristic."""
    heuristic_id = uuid4()
    resolver = _StubResolver(sandbox=_sandbox(), session=heuristic_id)
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    flow = _flow(proxy_auth=_basic_auth("not-a-uuid"))

    result = addon._resolve_and_match(flow)

    assert result is not None
    ctx, _match = result
    assert ctx.session_id == heuristic_id
    assert resolver.resolve_session_by_id_calls == []
    assert resolver.resolve_active_session_calls == 1


# ---------------------------------------------------------------------------
# requestheaders — tenant-scoped snapshot egress streaming (option B)
# ---------------------------------------------------------------------------


_SNAPSHOT_BUCKET = "onyx-sandbox-snapshots"


def _snapshot_policy() -> SnapshotEgressPolicy:
    # Path-style (MinIO-shaped) endpoint; keeps the tenant-prefix check
    # as the load-bearing control.
    return SnapshotEgressPolicy(
        bucket=_SNAPSHOT_BUCKET, endpoint_host="release-minio", endpoint_port=9000
    )


def _snapshot_flow(
    *, tenant_segment: str, host: str = "release-minio"
) -> http.HTTPFlow:
    # Multipart UploadPart shape: query (?partNumber=...) is excluded
    # from path_components. Body is oversize so a missed opt-in would
    # otherwise fail closed on the cap.
    return _flow(
        host=host,
        port=9000,
        method="PUT",
        path_components=(
            _SNAPSHOT_BUCKET,
            tenant_segment,
            "snapshots",
            "sess-1",
            "snap-1.tar.gz",
        ),
        raw_content=_OVERSIZE_BODY,
    )


@pytest.mark.asyncio
async def test_requestheaders_streams_tenant_snapshot_upload() -> None:
    sandbox = _sandbox(tenant_id="tenant_acme")
    resolver = _StubResolver(sandbox=sandbox)
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    addon._snapshot_policy = _snapshot_policy()
    flow = _snapshot_flow(tenant_segment="tenant_acme")

    await addon.requestheaders(flow)

    assert flow.request.stream is True
    assert flow.metadata[gate_mod._SNAPSHOT_STREAM_FLAG] is True


@pytest.mark.asyncio
async def test_requestheaders_ignores_non_s3_host() -> None:
    """Cheap host pre-check must short-circuit before any DB resolve."""
    resolver = _StubResolver(sandbox=_sandbox())
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    addon._snapshot_policy = _snapshot_policy()
    flow = _flow(host="slack.com")

    await addon.requestheaders(flow)

    assert flow.request.stream is False
    assert gate_mod._SNAPSHOT_STREAM_FLAG not in flow.metadata
    assert resolver.resolve_sandbox_calls == 0


@pytest.mark.asyncio
async def test_requestheaders_rejects_cross_tenant_prefix() -> None:
    """Pod resolves to tenant_acme but the key targets tenant_evil's
    prefix on the shared MinIO — must NOT stream, so `request` then
    fail-closes on the body cap."""
    resolver = _StubResolver(sandbox=_sandbox(tenant_id="tenant_acme"))
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=None))
    addon._snapshot_policy = _snapshot_policy()
    flow = _snapshot_flow(tenant_segment="tenant_evil")

    await addon.requestheaders(flow)
    assert flow.request.stream is False
    assert gate_mod._SNAPSHOT_STREAM_FLAG not in flow.metadata

    # The unmarked oversize flow now hits the fail-closed cap.
    result = addon._resolve_and_match(flow)
    assert result is None
    _assert_403(flow, gate_mod._CODE_BODY_TOO_LARGE)


@pytest.mark.asyncio
async def test_request_forwards_flagged_snapshot_flow() -> None:
    """A flow flagged in requestheaders forwards from `request` without
    touching the matcher, the cap, or the session lookup."""
    resolver = _StubResolver(sandbox=_sandbox())
    matcher = _StubMatcher(result=_MATCH)
    addon = _build(resolver=resolver, matcher=matcher)
    flow = _snapshot_flow(tenant_segment="tenant_acme")
    flow.metadata[gate_mod._SNAPSHOT_STREAM_FLAG] = True

    await addon.request(flow)

    assert flow.response is None  # forwarded
    assert matcher.calls == 0
    assert resolver.resolve_sandbox_calls == 0


@pytest.mark.asyncio
async def test_requestheaders_noop_without_policy() -> None:
    resolver = _StubResolver(sandbox=_sandbox())
    addon = _build(resolver=resolver, matcher=_StubMatcher(result=_MATCH))
    flow = _snapshot_flow(tenant_segment="tenant_acme")

    await addon.requestheaders(flow)

    assert flow.request.stream is False
    assert gate_mod._SNAPSHOT_STREAM_FLAG not in flow.metadata
    assert resolver.resolve_sandbox_calls == 0


# ---------------------------------------------------------------------------
# _write_response_for_decision
# ---------------------------------------------------------------------------


def test_write_response_approved_does_not_set_response() -> None:
    addon = _build(resolver=_StubResolver(), matcher=_StubMatcher())
    flow = _flow()

    addon._write_response_for_decision(flow, ApprovalDecision.APPROVED)

    assert flow.response is None


def test_write_response_rejected_sets_user_rejected_403() -> None:
    addon = _build(resolver=_StubResolver(), matcher=_StubMatcher())
    flow = _flow()

    addon._write_response_for_decision(flow, ApprovalDecision.REJECTED)

    _assert_403(flow, gate_mod._CODE_USER_REJECTED)


def test_write_response_expired_sets_not_authorized_403() -> None:
    addon = _build(resolver=_StubResolver(), matcher=_StubMatcher())
    flow = _flow()

    addon._write_response_for_decision(flow, ApprovalDecision.EXPIRED)

    _assert_403(flow, gate_mod._CODE_NOT_AUTHORIZED)


# ---------------------------------------------------------------------------
# ParkedApprovals
# ---------------------------------------------------------------------------


def test_parked_approvals_snapshot_is_independent_of_source() -> None:
    """The drain reads `snapshot()` and must be able to iterate while
    the event loop is mutating `_by_tenant` (add/remove). Pin the
    `dict[set].copy()` semantic so a refactor to e.g. a shallow tuple
    fails here."""
    parked = ParkedApprovals()
    id_a = uuid4()
    id_b = uuid4()
    id_c = uuid4()
    parked.add("tenant-1", id_a)
    parked.add("tenant-1", id_b)
    parked.add("tenant-2", id_c)

    snap_before = parked.snapshot()

    # Mutate the source after taking the snapshot.
    new_id = uuid4()
    parked.add("tenant-1", new_id)
    parked.remove("tenant-2", id_c)

    # Snapshot must reflect the state at the time it was taken.
    snap_dict_before = dict(snap_before)
    assert snap_dict_before["tenant-1"] == {id_a, id_b}
    assert snap_dict_before["tenant-2"] == {id_c}

    snap_after = dict(parked.snapshot())
    assert snap_after["tenant-1"] == {id_a, id_b, new_id}
    # tenant-2 went empty so the entry was cleaned up entirely (see
    # next test for the invariant).
    assert "tenant-2" not in snap_after


def test_parked_approvals_remove_last_cleans_tenant_entry() -> None:
    """Internal invariant: an empty per-tenant set is deleted so the
    top-level snapshot doesn't grow unbounded over the proxy's lifetime."""
    parked = ParkedApprovals()
    approval_id = uuid4()
    parked.add("tenant-1", approval_id)
    assert dict(parked.snapshot()) == {"tenant-1": {approval_id}}

    parked.remove("tenant-1", approval_id)

    assert parked.snapshot() == []

    # Removing again is a no-op (must not raise / re-create the entry).
    parked.remove("tenant-1", approval_id)
    assert parked.snapshot() == []


# ---------------------------------------------------------------------------
# _persist_approval_row
# ---------------------------------------------------------------------------


class _RecorderSession:
    """Captures the ordered sequence of operations applied to a DB
    session so a test can pin "commit happened before announce"."""

    def __init__(self, ops: list[str]) -> None:
        self._ops = ops

    def add(self, obj: Any) -> None:  # noqa: ARG002
        self._ops.append("add")

    def flush(self) -> None:
        self._ops.append("flush")

    def commit(self) -> None:
        self._ops.append("commit")

    # `db_session.query(...).filter_by(...).filter(...).first()` for the
    # idempotency check inside `create_notification`. Returning None
    # forces the "create a new row" path.
    def query(self, *_args: Any, **_kwargs: Any) -> "_RecorderSession":
        return self

    def filter_by(self, *_args: Any, **_kwargs: Any) -> "_RecorderSession":
        return self

    def filter(self, *_args: Any, **_kwargs: Any) -> "_RecorderSession":
        return self

    def first(self) -> None:
        return None


def _recorder_db_factory(ops: list[str]) -> Any:
    @contextmanager
    def factory(tenant_id: str) -> Iterator[_RecorderSession]:  # noqa: ARG001
        yield _RecorderSession(ops)

    return factory


class _RecorderCache:
    """Stub `CacheBackend` that records announce/wake calls.

    `announce_approval` calls `cache.rpush` + `cache.expire`; that's
    all the gate touches.
    """

    def __init__(self, ops: list[str], rpush_raises: Exception | None = None) -> None:
        self._ops = ops
        self._rpush_raises = rpush_raises
        self.rpush_calls: list[tuple[str, Any]] = []
        self.expire_calls: list[tuple[str, int]] = []

    def rpush(self, key: str, value: Any) -> None:
        if self._rpush_raises is not None:
            raise self._rpush_raises
        self._ops.append(f"rpush:{key}")
        self.rpush_calls.append((key, value))

    def expire(self, key: str, ttl: int) -> None:
        self._ops.append(f"expire:{key}")
        self.expire_calls.append((key, ttl))


def test_persist_approval_row_commits_announces_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin three load-bearing properties of the commit path:

    1. The row is inserted + committed before the announce fires
       (FE must never get an approval_id that doesn't yet exist in PG).
    2. The announce is RPUSHed onto `approval:announce:{session_id}`
       (the chat-stream merger reads from this exact key).
    3. The approval_id is registered with the parked-approvals drain
       (otherwise SIGTERM would orphan the row).

    A notification is also dispatched, but that's best-effort —
    pinned by the "no exception thrown" assertion only.
    """
    ops: list[str] = []
    approval_id = UUID("22222222-2222-2222-2222-222222222222")

    # `insert_action_approval` is the only thing about the DB call we
    # actually care about; stub it to return a row with a fixed id so
    # the rest of the assertions can pin the side effects.
    inserted_payload: dict[str, Any] = {}

    def _fake_insert(
        db: Any,  # noqa: ARG001
        **kwargs: Any,
    ) -> Any:
        inserted_payload.update(kwargs)
        ops.append("insert")
        return MagicMock(approval_id=approval_id)

    monkeypatch.setattr(
        gate_mod.action_approval, "insert_action_approval", _fake_insert
    )
    # Notification go through the regular `create_notification` code
    # path, which calls `query(...).filter_by(...).filter(...).first()`
    # — handled by `_RecorderSession` above.

    cache = _RecorderCache(ops)
    addon = _build(
        resolver=_StubResolver(),
        matcher=_StubMatcher(),
        db_factory=_recorder_db_factory(ops),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )

    ctx = _ctx(tenant_id="tenant-1")
    returned = addon._persist_approval_row(ctx, _MATCH)

    assert returned == approval_id
    assert inserted_payload == {
        "session_id": ctx.session_id,
        "action_type": _MATCH.action_type,
        "payload": _MATCH.payload,
    }

    # Ordering: insert -> commit -> rpush. A commit-after-announce
    # would let the FE read the row before it's persisted.
    insert_at = ops.index("insert")
    commit_at = ops.index("commit")
    rpush_at = next(i for i, op in enumerate(ops) if op.startswith("rpush:"))
    assert insert_at < commit_at < rpush_at, ops

    # Announce key is the session-specific list the merger BLPOPs on.
    assert cache.rpush_calls == [
        (f"approval:announce:{ctx.session_id}", str(approval_id))
    ]
    # Parked set picked up the new id so the SIGTERM drain can claim
    # it if the proxy dies before the wait completes.
    assert dict(addon._parked.snapshot()) == {"tenant-1": {approval_id}}


def test_persist_approval_row_announce_failure_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Redis blip on the announce path must not roll back the row.

    The row is already in Postgres; the FE picks up the card on the
    next `/live` refetch. Failing the request would convert a transient
    cache hiccup into a sandbox-visible 500.

    Crucially, the three best-effort sub-steps (commit, announce,
    notify) run independently — a failed announce must NOT skip the
    notification dispatch. Pin that by asserting `_notify_approval_requested`
    still fires after the rpush blows up.
    """
    approval_id = UUID("33333333-3333-3333-3333-333333333333")
    ops: list[str] = []

    def _fake_insert(
        db: Any,  # noqa: ARG001
        **kwargs: Any,  # noqa: ARG001
    ) -> Any:
        ops.append("insert")
        return MagicMock(approval_id=approval_id)

    monkeypatch.setattr(
        gate_mod.action_approval, "insert_action_approval", _fake_insert
    )

    cache = _RecorderCache(ops, rpush_raises=RedisError("connection refused"))
    addon = _build(
        resolver=_StubResolver(),
        matcher=_StubMatcher(),
        db_factory=_recorder_db_factory(ops),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )

    notify_calls: list[tuple[UUID, SessionContext, ActionMatch]] = []

    def _fake_notify(
        _self: Any, aid: UUID, ctx_arg: SessionContext, match_arg: ActionMatch
    ) -> None:
        notify_calls.append((aid, ctx_arg, match_arg))

    monkeypatch.setattr(GateAddon, "_notify_approval_requested", _fake_notify)

    ctx = _ctx(tenant_id="tenant-1")
    # Must NOT propagate the RedisError.
    returned = addon._persist_approval_row(ctx, _MATCH)
    assert returned == approval_id
    # And the row is still registered for the drain.
    assert dict(addon._parked.snapshot()) == {"tenant-1": {approval_id}}

    # The "best-effort" contract is per sub-step: a failed announce
    # must NOT short-circuit the notification dispatch.
    assert notify_calls == [(approval_id, ctx, _MATCH)]
    # And insert+commit ran before the failed announce, so the row is
    # durable in PG even though the cache push blew up.
    assert ops.index("insert") < ops.index("commit")
    # No rpush op was appended because the recorder appends only on
    # success — the raise short-circuits the record.
    assert not any(op.startswith("rpush:") for op in ops)


# ---------------------------------------------------------------------------
# _await_decision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_await_decision_wake_received_returns_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wake arrived before timeout → return the wake's decision. The
    parked entry is cleared either way (finally block)."""
    approval_id = uuid4()
    ctx = _ctx(tenant_id="tenant-1")

    async def _fake_wait_for_wake(
        _approval_id: UUID, _timeout: int, _cache: Any
    ) -> ApprovalDecision | None:
        return ApprovalDecision.APPROVED

    monkeypatch.setattr(gate_mod.approval_cache, "wait_for_wake", _fake_wait_for_wake)

    cache = _RecorderCache([])
    addon = _build(
        resolver=_StubResolver(),
        matcher=_StubMatcher(),
        db_factory=_recorder_db_factory([]),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )
    addon._parked.add(ctx.tenant_id, approval_id)

    decision = await addon._await_decision(approval_id, ctx, _MATCH)

    assert decision == ApprovalDecision.APPROVED
    # `finally` removed the parked entry; the empty per-tenant set is
    # cleaned up entirely.
    assert addon._parked.snapshot() == []


@pytest.mark.asyncio
async def test_await_decision_timeout_claims_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wait returns None → claim EXPIRED via the race arbiter."""
    approval_id = uuid4()
    ctx = _ctx(tenant_id="tenant-1")

    async def _fake_wait_for_wake(
        _approval_id: UUID, _timeout: int, _cache: Any
    ) -> ApprovalDecision | None:
        return None

    monkeypatch.setattr(gate_mod.approval_cache, "wait_for_wake", _fake_wait_for_wake)

    cache = _RecorderCache([])
    addon = _build(
        resolver=_StubResolver(),
        matcher=_StubMatcher(),
        db_factory=_recorder_db_factory([]),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )
    addon._parked.add(ctx.tenant_id, approval_id)

    claim_calls: list[tuple[UUID, str]] = []

    def _fake_claim(aid: UUID, tid: str) -> ApprovalDecision:
        claim_calls.append((aid, tid))
        return ApprovalDecision.EXPIRED

    monkeypatch.setattr(addon, "_claim_expired_or_read_winner", _fake_claim)

    decision = await addon._await_decision(approval_id, ctx, _MATCH)

    assert decision == ApprovalDecision.EXPIRED
    assert claim_calls == [(approval_id, ctx.tenant_id)]
    assert addon._parked.snapshot() == []


@pytest.mark.asyncio
async def test_await_decision_cancelled_claims_expired_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sandbox-side socket closed mid-wait. We must (1) claim EXPIRED
    so the audit row is terminal and (2) re-raise so mitmproxy releases
    the flow. The parked-set entry is removed by the `finally`."""
    approval_id = uuid4()
    ctx = _ctx(tenant_id="tenant-1")

    async def _fake_wait_for_wake(
        _approval_id: UUID, _timeout: int, _cache: Any
    ) -> ApprovalDecision | None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(gate_mod.approval_cache, "wait_for_wake", _fake_wait_for_wake)

    cache = _RecorderCache([])
    addon = _build(
        resolver=_StubResolver(),
        matcher=_StubMatcher(),
        db_factory=_recorder_db_factory([]),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )
    addon._parked.add(ctx.tenant_id, approval_id)

    claim_calls: list[tuple[UUID, str]] = []

    def _fake_claim(aid: UUID, tid: str) -> ApprovalDecision:
        claim_calls.append((aid, tid))
        return ApprovalDecision.EXPIRED

    monkeypatch.setattr(addon, "_claim_expired_or_read_winner", _fake_claim)

    with pytest.raises(asyncio.CancelledError):
        await addon._await_decision(approval_id, ctx, _MATCH)

    assert claim_calls == [(approval_id, ctx.tenant_id)]
    assert addon._parked.snapshot() == []


# ---------------------------------------------------------------------------
# drain_inflight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_inflight_walks_parked_per_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drain must:

    1. Walk per-tenant so each tenant's cache backend is fetched once
       (not once per parked approval).
    2. Wake every parked approval (so the BLPOP in `_await_decision`
       returns immediately rather than waiting out `WAIT_TIMEOUT_S`).
    3. Never cross-contaminate tenants — `send_wake` on tenant-1's
       cache must use tenant-1's approval ids only.
    4. Leave `_parked` unchanged — removal is owned by
       `_await_decision.finally`. Drain just sends wakes; if the drain
       starts removing entries we'd risk double-frees and miss wakes
       for tasks that haven't yet returned from their BLPOP.
    """
    cache_t1 = _RecorderCache([])
    cache_t2 = _RecorderCache([])
    per_tenant_caches: dict[str, _RecorderCache] = {
        "tenant-1": cache_t1,
        "tenant-2": cache_t2,
    }

    addon = _build(
        resolver=_StubResolver(),
        matcher=_StubMatcher(),
        db_factory=_recorder_db_factory([]),
        cache_factory=lambda tenant_id: per_tenant_caches[tenant_id],
    )

    t1_a = uuid4()
    t1_b = uuid4()
    t2_a = uuid4()
    addon._parked.add("tenant-1", t1_a)
    addon._parked.add("tenant-1", t1_b)
    addon._parked.add("tenant-2", t2_a)

    parked_before = dict(addon._parked.snapshot())

    monkeypatch.setattr(
        addon,
        "_claim_expired_or_read_winner",
        lambda _aid, _tid: ApprovalDecision.EXPIRED,
    )

    send_wake_calls: list[tuple[UUID, ApprovalDecision, _RecorderCache]] = []

    def _fake_send_wake(aid: UUID, decision: ApprovalDecision, cache: Any) -> None:
        send_wake_calls.append((aid, decision, cache))

    monkeypatch.setattr(gate_mod.approval_cache, "send_wake", _fake_send_wake)

    await addon.drain_inflight()

    # Every parked approval got a wake.
    waked_ids = {aid for aid, _decision, _cache in send_wake_calls}
    assert waked_ids == {t1_a, t1_b, t2_a}

    # No cross-tenant contamination: each id was waked on its own
    # tenant's cache backend.
    for aid, _decision, cache in send_wake_calls:
        if aid in (t1_a, t1_b):
            assert cache is cache_t1, "tenant-1 approval waked on wrong cache"
        else:
            assert cache is cache_t2, "tenant-2 approval waked on wrong cache"

    # Invariant: drain does NOT remove from `_parked`. A refactor that
    # eagerly removes here would break the contract with
    # `_await_decision.finally` and cause double-removes.
    assert dict(addon._parked.snapshot()) == parked_before


@pytest.mark.asyncio
async def test_drain_inflight_completes_when_inflight_set_empty() -> None:
    """No parked approvals + no inflight tasks → drain returns
    immediately. This is the happy SIGTERM path (proxy shut down with
    nothing in flight)."""
    cache_factory_calls: list[str] = []

    def _tracking_cache_factory(tenant_id: str) -> _RecorderCache:
        cache_factory_calls.append(tenant_id)
        return _RecorderCache([])

    addon = _build(
        resolver=_StubResolver(),
        matcher=_StubMatcher(),
        db_factory=_recorder_db_factory([]),
        cache_factory=_tracking_cache_factory,
    )

    assert addon._parked.snapshot() == []
    assert addon._inflight_tasks == set()

    # Bound by a low timeout so a regression that introduces an
    # unbounded wait would fail fast.
    await asyncio.wait_for(addon.drain_inflight(), timeout=1.0)

    # Postconditions: nothing changed, and the cache factory was never
    # consulted because there were no parked approvals to walk.
    assert addon._parked.snapshot() == []
    assert addon._inflight_tasks == set()
    assert cache_factory_calls == []


# ---------------------------------------------------------------------------
# _terminalize_after_unhandled_error
# ---------------------------------------------------------------------------


def test_terminalize_happy_path_writes_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cleanup after an unhandled exception: claim a terminal decision
    (so the audit row isn't left pending) and forward it via send_wake
    (so any parked BLPOP returns immediately).

    Note: the wake carries whatever decision the arbiter returned —
    APPROVED here, not unconditionally EXPIRED. The arbiter reads the
    winner if the API beat us to the record."""
    approval_id = uuid4()
    cache = _RecorderCache([])
    addon = _build(
        resolver=_StubResolver(),
        matcher=_StubMatcher(),
        db_factory=_recorder_db_factory([]),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )

    monkeypatch.setattr(
        addon,
        "_claim_expired_or_read_winner",
        lambda _aid, _tid: ApprovalDecision.APPROVED,
    )

    wake_calls: list[tuple[UUID, ApprovalDecision]] = []

    def _fake_send_wake(aid: UUID, decision: ApprovalDecision, _cache: Any) -> None:
        wake_calls.append((aid, decision))

    monkeypatch.setattr(gate_mod.approval_cache, "send_wake", _fake_send_wake)

    addon._terminalize_after_unhandled_error(approval_id, "tenant-1")

    assert wake_calls == [(approval_id, ApprovalDecision.APPROVED)]


def test_terminalize_db_failure_skips_wake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If claiming the terminal decision raises, there's nothing to
    forward — send_wake must NOT be called (a wake without a known
    decision would be a bug). The exception is swallowed; the caller's
    original exception is what matters."""
    approval_id = uuid4()
    cache = _RecorderCache([])
    addon = _build(
        resolver=_StubResolver(),
        matcher=_StubMatcher(),
        db_factory=_recorder_db_factory([]),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )

    def _claim_raises(aid: UUID, tid: str) -> ApprovalDecision:  # noqa: ARG001
        raise RuntimeError("db blip")

    monkeypatch.setattr(addon, "_claim_expired_or_read_winner", _claim_raises)

    wake_count = 0

    def _fake_send_wake(_aid: UUID, _decision: ApprovalDecision, _cache: Any) -> None:
        nonlocal wake_count
        wake_count += 1

    monkeypatch.setattr(gate_mod.approval_cache, "send_wake", _fake_send_wake)

    # Should not raise.
    addon._terminalize_after_unhandled_error(approval_id, "tenant-1")

    assert wake_count == 0


def test_terminalize_wake_failure_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claim succeeds but send_wake raises — no exception propagates.
    The parked BLPOP will time out on its own and re-read the row from
    Postgres; the audit row is already terminal."""
    approval_id = uuid4()
    cache = _RecorderCache([])
    addon = _build(
        resolver=_StubResolver(),
        matcher=_StubMatcher(),
        db_factory=_recorder_db_factory([]),
        cache_factory=lambda tenant_id: cache,  # noqa: ARG005
    )

    monkeypatch.setattr(
        addon,
        "_claim_expired_or_read_winner",
        lambda _aid, _tid: ApprovalDecision.EXPIRED,
    )

    def _wake_raises(_aid: UUID, _decision: ApprovalDecision, _cache: Any) -> None:
        raise RedisError("wake failed")

    monkeypatch.setattr(gate_mod.approval_cache, "send_wake", _wake_raises)

    # Should not raise.
    addon._terminalize_after_unhandled_error(approval_id, "tenant-1")
