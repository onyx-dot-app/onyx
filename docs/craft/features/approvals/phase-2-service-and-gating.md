# Phase 2 — Approval Service & Gate Wiring (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 1.

## Goal

Two halves shipped together:

1. **Approval data layer + decision API.** A single `action_approval`
   table whose `decision` column is nullable (`NULL` = pending /
   in-flight); `server/features/build/db/action_approval.py` is the
   single source of SQL. The user-facing API lives in
   `server/features/build/approvals/api.py` and exposes three
   endpoints: a live-rows feed (chat UI), an audit query, and a
   decision write. A short-TTL Redis "liveness" key, owned by the
   proxy while it waits, distinguishes a live request from an orphan
   row left by a hard proxy crash.
2. **Gate wiring.** The proxy stops being pass-through. On a gated
   request, the gate addon writes the `action_approval` row and
   publishes the liveness key in one DB transaction, blocks on a
   per-approval wake channel until a decision lands or the wait window
   elapses, and then forwards or rejects.

At the end of Phase 2, gated external-app requests work end-to-end.
The Phase 3 chat surface fetches actionable rows via
`GET /api/build/approvals/sessions/{id}/live` and notifications
deep-link to the same session.

## Phase 1 context

- `SessionContext` shape: `session_id, user_id, sandbox_id, tenant_id, sandbox_name, sandbox_ip`. Phase 2 reads `session_id`, `user_id`, and `tenant_id`. The session owner (`user_id` on the parent `build_session`) is the only authorized decider.
- Proxy `main()` already calls `SqlEngine.init_engine(pool_size=4, max_overflow=4)`. The gate addon reuses this engine via a per-tenant session factory.
- `PassthroughAddon` already attaches the resolved `SessionContext` to `flow.metadata[GateAddon.METADATA_KEY]`; the gate prefers that over re-resolving by IP.

## Module layout

Backend API:

```
backend/onyx/server/features/build/approvals/
└── api.py                 # FastAPI router (live + audit + decision)
```

DB (matches the existing build-feature layout — sibling query modules
under `server/features/build/db/`; models and enums centralized):

```
backend/onyx/server/features/build/db/action_approval.py    # query module
backend/onyx/db/models.py                                   # ActionApproval ORM
backend/onyx/db/enums.py                                    # ApprovalDecision
backend/alembic/versions/366c05b6f485_create_action_approval.py
```

Proxy (the proxy image bundles the backend module tree; no HTTP
between proxy and api-server, all in-process Python imports):

```
backend/onyx/sandbox_proxy/approval_cache.py    # procedural cache fns
backend/onyx/sandbox_proxy/action_matcher.py    # ActionMatcher Protocol + v0 Slack impl
backend/onyx/sandbox_proxy/addons/gate.py       # the gating addon
```

Constants / notifications:

```
backend/onyx/configs/constants.py               # NotificationType.APPROVAL_REQUESTED
```

## Tasks

### T2.1 — Data model + migration

`ActionApproval` ORM in `backend/onyx/db/models.py`. Each row is one
agent-initiated gated-action attempt and its terminal decision. The
session owner is the only authorized decider — identity is derived via
the `session_id` FK rather than denormalized onto the row.

```python
class ActionApproval(Base):
    """One agent-initiated gated action and its decision.

    `decision IS NULL` represents the pending / in-flight state (or an
    orphan attempt left behind by a hard proxy crash). Liveness vs.
    orphan is distinguished by the `approval:live:{id}` Redis key
    (see `sandbox_proxy/approval_cache.py`), not by the DB.
    """

    __tablename__ = "action_approval"

    approval_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4,
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("build_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(PGJSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    decision: Mapped[ApprovalDecision | None] = mapped_column(
        Enum(ApprovalDecision, native_enum=False, name="approvaldecision"),
        nullable=True,
    )
    decided_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
```

No secondary indexes. The primary-key lookup covers the decision API;
session-scoped audit queries are bounded by the per-session row count,
which is small.

`ApprovalDecision` in `db/enums.py` — pending state is `decision IS NULL`, no enum value reserved for it:

```python
class ApprovalDecision(str, PyEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
```

Hand-written Alembic migration at
`backend/alembic/versions/366c05b6f485_create_action_approval.py`.
`op.create_table` with the FK to `build_session(id)` (`ondelete="CASCADE"`)
plus `op.drop_table` in `downgrade()`.

### T2.2 — DB query module

`backend/onyx/server/features/build/db/action_approval.py`. Writes
flush implicitly so callers can read auto-generated IDs back; the
caller still owns transaction commit. Same convention as
`build_session.py` and `sandbox.py`. Cache (Redis) operations belong
in `sandbox_proxy/approval_cache.py`, not here.

```python
def insert_action_approval(
    db_session: Session, *,
    session_id: UUID, action_type: str, payload: dict[str, Any],
) -> ActionApproval:
    """Insert a new pending row. `decision IS NULL`; `approval_id` is
    auto-generated by the ORM (`default=uuid4`). Flushes so the caller
    can read `row.approval_id` back."""

def record_decision(
    db_session: Session, *,
    approval_id: UUID, decision: ApprovalDecision,
) -> ActionApproval | None:
    """Race-safe terminal write:
        UPDATE action_approval
           SET decision = :decision, decided_at = now()
         WHERE approval_id = :id AND decision IS NULL
        RETURNING *.
    Returns the row if the update fired, `None` if a decision was
    already recorded. Callers handle the `None` case (idempotent retry
    vs. genuine CONFLICT — see T2.4)."""

def get_action_approval(
    db_session: Session, approval_id: UUID,
) -> ActionApproval | None: ...

def get_action_approval_for_user(
    db_session: Session, approval_id: UUID, user_id: UUID,
) -> ActionApproval | None:
    """JOINs action_approval to build_session and filters by user_id.
    Returns None for both missing-row and wrong-owner — callers map
    to NOT_FOUND so existence isn't leaked."""

def list_session_action_approvals(
    db_session: Session, session_id: UUID, *,
    decision: ApprovalDecision | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
) -> list[ActionApproval]:
    """User-scoped audit query. `decision=None` returns every row
    including `decision IS NULL` (orphan attempts)."""

def list_session_pending_action_approvals(
    db_session: Session, session_id: UUID,
) -> list[ActionApproval]:
    """Every row for the session with `decision IS NULL`. The live
    endpoint filters this further by checking each row's Redis
    liveness key (orphan rows from a hard proxy crash are not
    actionable)."""

```

The tenant-scoped audit query backing the admin page is added in
Phase 4.

### T2.3 — Call sites (overview)

`db/action_approval.py` queries and `sandbox_proxy/approval_cache.py`
functions have three call sites:

- **Gate addon — create flow.** Writes the row and publishes the
  liveness key in one DB transaction (Redis failure rolls the DB
  back), then dispatches `APPROVAL_REQUESTED` best-effort. Full code
  in T2.7.
- **API handler — decision flow.** Auth + ownership check via
  `get_action_approval_for_user` (NOT_FOUND on missing or non-owner),
  idempotency check, race-safe `record_decision`, best-effort
  `approval_cache.finalize`. Full code in T2.4.

The policy-evaluator silent-decision path lives in Phase 4 and adds
its own `insert_silent_action_approval` helper alongside this module.

All cache access uses `approval_cache.py` functions. Callers obtain
a `CacheBackend` via `get_cache_backend(tenant_id=...)` at call time —
no FastAPI `Depends()` for cache (matches the codebase convention in
`onyx.chat.stop_signal_checker`).

### T2.4 — User-facing API

`backend/onyx/server/features/build/approvals/api.py`. Mounted under
the existing `/build` prefix, which already applies
`require_onyx_craft_enabled` + `Permission.BASIC_ACCESS`. The router
itself doesn't re-apply those.

Pydantic shapes:

```python
class DecisionBody(BaseModel):
    """Body of POST /approvals/{approval_id}/decision."""
    model_config = ConfigDict(extra="forbid")
    decision: Literal[ApprovalDecision.APPROVED, ApprovalDecision.REJECTED]
    # EXPIRED is server-only — set by the proxy on timeout, never
    # accepted from a client.

class ApprovalView(BaseModel):
    approval_id: UUID
    session_id: UUID
    action_type: str
    payload: dict[str, Any]
    created_at: datetime
    decision: ApprovalDecision | None
    decided_at: datetime | None
    is_live: bool

class ApprovalListResponse(BaseModel):
    items: list[ApprovalView]
```

Endpoints:

```python
router = APIRouter(prefix="/approvals")  # parent /build router already
                                          # applies require_onyx_craft_enabled
                                          # + BASIC_ACCESS.

@router.get("/sessions/{session_id}/live")
def list_live_approvals(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalListResponse:
    """Return the session's currently-actionable approvals.

    Actionable = DB row is undecided AND the Redis liveness key is
    present (i.e. some proxy is still parked on the wait). Orphan
    rows from a hard proxy crash are filtered out. The chat surface
    polls this endpoint to drive its inline approval card."""

@router.get("/sessions/{session_id}")
def list_session_approvals(
    session_id: UUID,
    decision: ApprovalDecision | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalListResponse:
    """Audit query for a session the caller owns. `decision=None`
    returns every row including `decision IS NULL` (orphans)."""

@router.post("/{approval_id}/decision")
def submit_decision(
    approval_id: UUID,
    body: DecisionBody,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalView:
    request_row = action_approval.get_action_approval_for_user(
        db_session, approval_id, user.id,
    )
    if request_row is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")

    # Idempotent double-click: same decision recorded → 200 with row.
    if request_row.decision is not None:
        if request_row.decision == body.decision:
            return _to_view(request_row, is_live=False)
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"decision already recorded ({request_row.decision.value})",
        )

    updated = action_approval.record_decision(
        db_session, approval_id=approval_id, decision=body.decision,
    )
    if updated is None:
        # Lost the race. Expire `request_row` first so SQLAlchemy's
        # identity map doesn't hand back the stale `decision=None`
        # instance on re-read.
        db_session.expire(request_row)
        fresh = action_approval.get_action_approval(db_session, approval_id)
        if fresh is None:
            # FK cascade deleted the row between the initial read and
            # the conditional UPDATE — surface as NOT_FOUND so the
            # client distinguishes the cases.
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")
        if fresh.decision == body.decision:
            return _to_view(fresh, is_live=False)
        # record_decision returned None only because a different
        # decision is already recorded — guarded with an explicit
        # None-check (not `assert`) so `python -O` doesn't strip the
        # invariant.
        if fresh.decision is None:
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "approval row reverted to pending unexpectedly",
            )
        logger.info(
            "approval.decision_conflict approval_id=%s lost_race=true "
            "existing_decision=%s requested_decision=%s",
            approval_id, fresh.decision.value, body.decision.value,
        )
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            f"decision already recorded ({fresh.decision.value})",
        )
    db_session.commit()

    try:
        cache = get_cache_backend(tenant_id=get_current_tenant_id())
        approval_cache.finalize(approval_id, body.decision, cache)
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning(
            "approval.cache_signal_failed approval_id=%s error=%s",
            approval_id, str(e),
        )

    return _to_view(updated, is_live=False)
```

`_to_view` serializes the row; `is_live` is set per-row using
`approval_cache.is_alive`:

```python
def _is_live(row: ActionApproval, cache: CacheBackend) -> bool:
    if row.decision is not None:
        return False
    try:
        return approval_cache.is_alive(row.approval_id, cache)
    except CACHE_TRANSIENT_ERRORS:
        return False
```

A row is live if no decision is recorded AND the Redis liveness key
still exists. Redis EXISTS is sub-ms, hit directly per row per request —
no in-process memo. The realistic worst-case load on this endpoint is
small (one user, one session, polling) and the cache would add eviction,
cross-replica staleness, and an invalidation site for no real win.

Register the router on `backend/onyx/server/features/build/api/api.py`.
No `response_model`. Raise `OnyxError` only.

**Approvals are not BuildMessages.** The chat does not augment the
messages endpoint with `is_live`; instead it polls
`GET /api/build/approvals/sessions/{id}/live` and renders any returned
row as an inline card. There is no `is_live` field on `MessageResponse`.

### T2.5 — Approval cache module

`backend/onyx/sandbox_proxy/approval_cache.py` is a module of
procedural functions over `CacheBackend`, following the
`onyx.chat.stop_signal_checker` / `chat_processing_checker` pattern.
No wrapper classes — callers obtain a `CacheBackend` via
`get_cache_backend(tenant_id=...)` (`onyx.cache.factory`) and pass it
in.

Two Redis keys back the rendezvous:

* `approval:live:{id}` — short-TTL presence flag the proxy owns while
  parked. The chat shows an actionable card iff this key exists AND
  the DB row is undecided. A hard proxy crash lets the key lapse
  within `LIVENESS_TTL_S` and the card disappears on its own.
* `approval:wake:{id}` — one-shot BLPOP list the api-server pushes
  onto when a decision is recorded so the proxy's wait unblocks
  immediately rather than timing out 180s later.

The conditional `WHERE decision IS NULL` UPDATE in
`db/action_approval.py` is the race-safe arbiter; cache operations
are best-effort notifications.

```python
# Heartbeat cadence × 4 gives two missed refreshes worth of slack
# (network blip, GC pause).
HEARTBEAT_INTERVAL_S = 15
LIVENESS_TTL_S = HEARTBEAT_INTERVAL_S * 4   # 60s
WAKE_TTL_S = 30


# Proxy side -------------------------------------------------------

def set_alive(
    approval_id: UUID, proxy_instance_id: str, cache: CacheBackend
) -> None:
    """Initial publish + each heartbeat tick. Idempotent (plain SET)."""
    cache.set(_live_key(approval_id), proxy_instance_id, ex=LIVENESS_TTL_S)


def clear_alive(approval_id: UUID, cache: CacheBackend) -> None:
    cache.delete(_live_key(approval_id))


async def wait_for_wake(
    approval_id: UUID, timeout_s: int, cache: CacheBackend
) -> ApprovalDecision | None:
    """BLPOP wrapped via asyncio.to_thread so the proxy event loop
    doesn't block. Returns the decoded decision or None on timeout /
    unparseable payload (caller re-reads the row)."""


# API side ---------------------------------------------------------

def is_alive(approval_id: UUID, cache: CacheBackend) -> bool:
    return cache.exists(_live_key(approval_id))


def send_wake(
    approval_id: UUID, decision: ApprovalDecision, cache: CacheBackend
) -> None:
    """RPUSH + EXPIRE so a never-consumed wake auto-evicts."""


def finalize(
    approval_id: UUID, decision: ApprovalDecision, cache: CacheBackend
) -> None:
    """End-of-life: clear_alive + send_wake. Clear first so a racing
    is_alive sees the terminal state immediately."""
```

The gate addon refreshes the liveness key every
`HEARTBEAT_INTERVAL_S` via an asyncio task spawned alongside the
BLPOP wait.

### T2.6 — Action-type matching

The gate addon needs one capability from this layer: given an
intercepted HTTPS request, return `(action_type, payload)` if the
request is gated, or `None` if it isn't. Everything else —
URL-to-app matching, per-provider parser modules, registries — is
owned by the External Apps workstream and its final shape is not yet
locked.

Phase 2 ships only the seam:

```python
# sandbox_proxy/action_matcher.py

@dataclass(frozen=True)
class ActionMatch:
    action_type: str   # e.g. "slack.send_message"
    payload: dict[str, Any]


class ActionMatcher(Protocol):
    """Single-method seam used by the gate addon. Return None for
    non-gated traffic; do not raise for 'this isn't my action type'."""
    def match(self, request: http.Request) -> ActionMatch | None: ...
```

The gate depends only on `ActionMatcher`. Phase 2 wires up the
single-file v0 implementation `SlackSendMessageMatcher`. It hardcodes
detection of Slack `chat.postMessage` — small enough to delete and
replace when a broader registry lands. Phase 4's parser registry
plugs in by providing its own `ActionMatcher`; no other code in
Phase 2 needs to change.

`SlackSendMessageMatcher` specifics:

- **Host suffix-safe.** `host.lower().rstrip(".")` then accept
  either exact `slack.com` or any `*.slack.com`. `slack.com.` and
  `api.slack.com` are caught; `evil-slack.com` is rejected.
- **Method.** POST only (case-insensitive on `request.method`).
- **Path.** case-insensitive prefix `/api/chat.postmessage`.
- **Body encodings.** Both `application/json` and
  `application/x-www-form-urlencoded` decoded — Slack's Web API
  accepts both for this method. `parse_qs` lists are collapsed to
  scalars where the value list has length 1 so the payload shape
  matches the JSON form.
- **Body-shape policy.** Once the URL + method + path match, gate the
  known endpoint; an unparseable body is Slack's problem to reject,
  not a reason to bypass the gate. `_decode_body` returning `None`
  becomes `payload={}` and the matcher still emits an `ActionMatch`.

Other Slack Web API methods (`chat.postEphemeral`, `files.upload`,
etc.) are out of scope for v0 — broader gating awaits the parser
registry.

The chat client maps `action_type` to a display label via a static
map (e.g. `"slack.send_message"` → `"Craft is trying to send a
message in Slack"`).

**Default open** on matcher ambiguity:

- `matcher.match(...) is None` → not gated; forward unchanged.
- `matcher.match(...)` raises → log `gate.matcher_error`; forward
  unchanged. The matcher is a heuristic over arbitrary HTTPS bodies;
  treating crashes as a security boundary breaks legitimate traffic
  when the matcher has a bug. The real security boundary is Phase
  1's iptables egress lockdown.

Body-size cap stays fail-closed (T2.7 enforces
`PARSER_MAX_BODY_BYTES`, 1 MiB): an oversize body either signals a
DoS attempt against the matcher or carries exfil that wouldn't show
up in summary anyway.

### T2.7 — Gate addon

`request(flow)` is decomposed into helpers so the policy evaluator
(Phase 4) and the SIGTERM drain share the same arbiter / cleanup
paths. Each helper is independently testable.

```python
WAIT_TIMEOUT_S = 180
PARSER_MAX_BODY_BYTES = 1_048_576

DBSessionFactory = Callable[[str], AbstractContextManager[Session]]
CacheFactory = Callable[[str], CacheBackend]


class GateAddon:
    METADATA_KEY = "onyx_session_context"  # mirrors PassthroughAddon

    def __init__(
        self,
        identity: _Resolver,
        action_matcher: ActionMatcher,
        db_session_factory: DBSessionFactory,
        cache_factory: CacheFactory,
        proxy_instance_id: str,
    ) -> None:
        ...
        # Approvals the proxy is currently parked on, mapped to their
        # tenant_id so the SIGTERM drain routes the conditional UPDATE
        # back to the right schema. Touched only from the event loop
        # (mitmproxy hooks + drain via loop.add_signal_handler).
        self._inflight_tenant_by_approval: dict[UUID, str] = {}

    async def request(self, flow: http.HTTPFlow) -> None:
        match_result = self._match_action(flow)
        if match_result is None:
            return  # short-circuited
        ctx, match = match_result

        # mitmproxy's default on addon exceptions is to forward the
        # original request, which would silently bypass the gate. Wrap
        # row creation + the wait so any unhandled error becomes a
        # fail-closed 403 and terminalizes the committed row.
        approval_id: UUID | None = None
        try:
            approval_id = self._create_request(ctx, match)
            decision = await self._await_decision(approval_id, ctx, match)
            self._apply_decision_to_flow(flow, decision)
        except Exception:
            logger.exception(
                "gate.unhandled_error session_id=%s tenant_id=%s "
                "approval_id=%s action_type=%s",
                ctx.session_id, ctx.tenant_id, approval_id, match.action_type,
            )
            flow.response = _http_403(_CODE_INTERNAL_ERROR)
            if approval_id is not None:
                self._safe_terminalize(approval_id, ctx.tenant_id)
        finally:
            # Belt-and-braces: _await_decision's own finally is the
            # canonical pop path, but if it raised before entering its
            # try block this guards the drain dict against leaks.
            if approval_id is not None:
                self._inflight_tenant_by_approval.pop(approval_id, None)
```

`_match_action` resolves identity, enforces the body-size cap, and
dispatches to the matcher. **Fail-closed paths** set `flow.response`
to a 403 and return `None`:

- No source IP on `flow.client_conn.peername` → `unidentified_sandbox`.
- `flow.metadata[METADATA_KEY]` empty AND `identity.resolve()` raises
  → `unidentified_sandbox`. Identity is a precondition for gating; a
  DB blip cannot grant ungated egress.
- `identity.resolve()` returns `None` → `unidentified_sandbox`.
- `flow.request.raw_content is None` → `body_too_large`. Defensive
  against a future addon enabling `stream=True`; we don't enable
  streaming today.
- `len(raw_content) > PARSER_MAX_BODY_BYTES` → `body_too_large`.

**Fail-open path:** `matcher.match(...)` raises → log
`gate.matcher_error`, return `(None)` without setting
`flow.response`. The request is forwarded unchanged. This is the
only fail-open path in the addon.

If a `PassthroughAddon`-resolved `SessionContext` is already on
`flow.metadata`, `_match_action` uses it directly — saves a DB hit
per request.

`_create_request` writes the row, then publishes the liveness key:

```python
def _create_request(self, ctx: SessionContext, match: ActionMatch) -> UUID:
    with self._db_session_factory(ctx.tenant_id) as db:
        row = action_approval.insert_action_approval(
            db,
            session_id=ctx.session_id,
            action_type=match.action_type,
            payload=match.payload,
        )
        approval_id = row.approval_id  # capture before commit detaches row
        db.commit()

    # Register here (not in _await_decision) so a SIGTERM firing
    # between commit and the caller's await still finds the row in
    # the drain dict.
    self._inflight_tenant_by_approval[approval_id] = ctx.tenant_id

    try:
        approval_cache.set_alive(
            approval_id,
            self._proxy_instance_id,
            self._cache_factory(ctx.tenant_id),
        )
    except CACHE_TRANSIENT_ERRORS as e:
        # Without liveness the chat won't surface the card, so the
        # user can't act on it. Terminalize EXPIRED inline and re-raise
        # — request()'s outer handler then emits 403 internal_error.
        logger.warning(
            "gate.initial_set_alive_failed approval_id=%s error=%s",
            approval_id, str(e),
        )
        self._safe_terminalize(approval_id, ctx.tenant_id)
        raise

    # Best-effort APPROVAL_REQUESTED notification — failures swallowed
    # and logged as approval.notify_failed.
    try:
        self._notify_approval_requested(approval_id, ctx, match)
    except Exception as e:
        logger.warning("approval.notify_failed approval_id=%s error=%s",
                       approval_id, str(e))
    return approval_id
```

Commit-first ordering: the DB write commits before liveness is
published, so a `set_alive` failure terminalizes the committed row
inline (via `_safe_terminalize`) rather than leaving an orphan pending
row. Re-raising lets `request()`'s outer handler emit the 403
`internal_error` to the sandbox.

`_await_decision` runs the heartbeat + BLPOP, terminalises the row on
timeout / cancellation, and always releases the in-flight tracking
entry. The in-flight entry was set in `_create_request`; this method
only owns its removal.

```python
async def _await_decision(
    self, approval_id: UUID, ctx: SessionContext, match: ActionMatch,
) -> ApprovalDecision:
    cache = self._cache_factory(ctx.tenant_id)
    heartbeat = asyncio.create_task(self._heartbeat_loop(approval_id, cache))
    try:
        decision = await approval_cache.wait_for_wake(
            approval_id, WAIT_TIMEOUT_S, cache,
        )
        if decision is not None:
            return decision
        # Timeout — race-safe via the conditional UPDATE.
        return self._terminalize_as_expired(approval_id, ctx.tenant_id)
    except asyncio.CancelledError:
        # Sandbox-side socket closed mid-wait. Same cleanup as timeout.
        self._terminalize_as_expired(approval_id, ctx.tenant_id)
        raise
    finally:
        heartbeat.cancel()
        try:
            await heartbeat  # let cancellation settle
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(
                "gate.heartbeat_unexpected_error approval_id=%s", approval_id,
            )
        try:
            approval_cache.clear_alive(approval_id, cache)
        except CACHE_TRANSIENT_ERRORS:
            pass
        self._inflight_tenant_by_approval.pop(approval_id, None)
```

`_terminalize_as_expired(approval_id, tenant_id)` is the single
race-safe claim helper: tries the conditional UPDATE, and on loss
re-reads the row to return the winner's decision. Used by the
wait-timeout path, the `CancelledError` path, and the SIGTERM drain
path (each passes the appropriate `tenant_id` — `ctx.tenant_id` for
the live paths, the snapshotted tenant from the in-flight dict for
the drain). If the row was deleted via FK cascade (parent
`build_session` dropped mid-flight), it returns `EXPIRED` and logs
`gate.row_missing_on_claim`.

`_safe_terminalize(approval_id, tenant_id)` wraps
`_terminalize_as_expired` + `approval_cache.finalize` with swallowed
errors (logged as `gate.safe_terminalize_db_failed` /
`gate.safe_terminalize_cache_failed`). Used by `request()`'s outer
exception handler and by `_create_request`'s initial-set_alive failure
path so cleanup never masks the original error.

`_heartbeat_loop` sleeps `HEARTBEAT_INTERVAL_S` then calls
`approval_cache.set_alive`. Transient cache failures are logged
(`gate.heartbeat_failed`) and the next tick retries. If the proxy
process dies, the key naturally lapses within `LIVENESS_TTL_S`.

`_apply_decision_to_flow`:

```python
def _apply_decision_to_flow(self, flow, decision: ApprovalDecision) -> None:
    if decision == ApprovalDecision.APPROVED:
        return  # forward upstream
    code = (
        _CODE_USER_REJECTED
        if decision == ApprovalDecision.REJECTED
        else _CODE_NOT_AUTHORIZED
    )
    flow.response = _http_403(code)
```

**Sandbox-facing 403 enum.** The proxy's 403 body is a separate
protocol from `OnyxError`. Locked enum:
`unidentified_sandbox | body_too_large | user_rejected | not_authorized | internal_error`.
`policy_denied` is reserved for Phase 4. The body is
`json.dumps({"error": code})` with `content-type: application/json`.
Matcher exceptions do not produce 403s — they fail open per T2.6.

**SIGTERM drain (`drain_inflight`).** On SIGTERM the proxy flips the
readiness probe and iterates a snapshot of
`_inflight_tenant_by_approval`. For each `(approval_id, tenant_id)`:

1. Call `_terminalize_as_expired(approval_id, tenant_id)` — the same
   single claim helper the live paths use, with the tenant_id
   snapshotted at registration time (the `SessionContext` is no
   longer in scope).
2. If we **win** the claim → row is now EXPIRED; log
   `gate.drain_expired`.
3. If we **lose** the claim → re-read returns the API-written
   decision; log `gate.drain_forwarded`.
4. Either way, `approval_cache.finalize(...)` (clear_alive + send_wake
   in one call) so the parked `_await_decision` coroutine's BLPOP
   unblocks immediately. The shared `_apply_decision_to_flow` then
   forwards or rejects inline.

Dropping the connection without forwarding an already-APPROVED
upstream call would mean the audit log says APPROVED for an action
that never happened, so the drain explicitly wakes parked coroutines
rather than just exiting.

The signal handler in `sandbox_proxy/server.py` schedules the drain
on the event loop with a single outer timeout
(`_DRAIN_TIMEOUT_SECONDS = 10s`). `drain_inflight` does the work in
two phases: it writes terminal decisions + wakes parked coroutines,
then `asyncio.wait`s on the `self._inflight_tasks` set so it actually
blocks until every `request()` task has serialized its response
(including any upstream forward on APPROVED) before mitmproxy tears
connections down. The K8s `terminationGracePeriodSeconds` sizes to
`_DRAIN_TIMEOUT_SECONDS + margin`, i.e. ≥ 20s.

**Hard proxy crash (kill -9, OOM).** The refresh loop dies with the
process; the liveness key in Redis lapses within `LIVENESS_TTL_S`
(60s); `/approvals/sessions/{id}/live` stops returning the row.
The DB row sits with `decision IS NULL` and is visible to the admin
audit view via a `decision IS NULL` filter.

### T2.8 — Notification type

Add `APPROVAL_REQUESTED = "approval_requested"` to `NotificationType`
in `backend/onyx/configs/constants.py`. Dispatch from the gate addon's
`_notify_approval_requested` helper calls `create_notification` with:

- `notif_type=NotificationType.APPROVAL_REQUESTED`
- `user_id=ctx.user_id` (the session owner)
- `title="Craft is awaiting approval"`
- `additional_data={"approval_id": ..., "session_id": ..., "action_type": ...}`

No `payload` in the notification body — the popover renders a label
from `action_type` client-side and deep-links to the session; the
full payload lives on the `action_approval` row and is fetched when
the chat loads.

`require_permission` lives in `onyx.auth.permissions`; `Permission`
lives in `onyx.db.enums`.

### T2.9 — Bash-tool timeout (verify-and-document)

The `backend/onyx/server/features/build/sandbox/opencode/` directory
ships empty in this repo: opencode is consumed as a binary/image we
don't control. If our deployment owns opencode config, raise the bash
tool default timeout to ≥240s and update the agent system prompt to
mention the approval window. If opencode is an external binary,
document the limitation and rely on the agent-prompt nudge alone (the
agent can still set explicit per-call timeouts on `curl`-style
requests).

### T2.10 — Observability + constants

**Structured logging.** Every state transition in the gate addon and
the API handler emits one log line via the existing `setup_logger()`
pattern. Common keys: `approval_id, session_id, tenant_id, sandbox_id, proxy_instance_id, action_type`.

Required log lines:

- Gate addon: `gate.match`, `gate.row_committed`, `gate.wake_received`,
  `gate.wake_timeout`, `gate.expired_on_timeout`, `gate.drain_expired`,
  `gate.drain_forwarded`, `gate.drain_error`, `gate.matcher_error`,
  `gate.identity_error`, `gate.heartbeat_failed`,
  `gate.heartbeat_unexpected_error`, `gate.unhandled_error`,
  `gate.initial_set_alive_failed`, `gate.safe_terminalize_db_failed`,
  `gate.safe_terminalize_cache_failed`, `gate.row_missing_on_claim`.
- API handler: `approval.decision_recorded`,
  `approval.decision_conflict`, `approval.cache_signal_failed`,
  `approval.notify_failed`.

**PII rule.** Never log `payload` — it contains user content (Slack
message bodies, etc.). Log `action_type` only. The notification body
likewise carries only `action_type` and ID fields.

**One-query lifecycle.** Documented in the runbook:

```
grep "approval_id=<UUID>" backend/log/sandbox_proxy_debug.log backend/log/api_server_debug.log | sort
```

**Constants** (module-level, not env-var-tunable). All in the module
that owns the behavior — no `configs/app_configs.py` indirection.
Promote to env vars if a real ops-tuning need surfaces.

| Constant                       | Value     | Lives in                |
| ------------------------------ | --------- | ----------------------- |
| `WAIT_TIMEOUT_S`               | 180       | `addons/gate.py`        |
| `PARSER_MAX_BODY_BYTES`        | 1_048_576 | `addons/gate.py`        |
| `HEARTBEAT_INTERVAL_S`         | 15        | `approval_cache.py`     |
| `LIVENESS_TTL_S`               | 60        | `approval_cache.py`     |
| `WAKE_TTL_S`                   | 30        | `approval_cache.py`     |

The `approval_cache.py` trio is a coupled set
(`LIVENESS_TTL_S = HEARTBEAT_INTERVAL_S * 4`).

**Metrics deferred.** Leave no-op hooks where counters / histograms
will land. Likely candidates:

- Counters: `approvals_created`, `approved`, `rejected`, `expired`,
  `silent_allowed`, `denied`, `matcher_error`.
- Histograms: `approval_decision_latency_seconds`,
  `blpop_wait_seconds`.

## Testing

For test-tier conventions see CLAUDE.md. TTL constants are
monkey-patched to <1s in tests where wall-clock waits would otherwise
poison CI.

External-dependency-unit (real Postgres + Redis):

- **Create flow.** `GateAddon._create_request` writes the row in one
  transaction; liveness key exists in Redis afterwards.
- **Decision APPROVED / REJECTED.** `POST /approvals/{id}/decision`
  writes the row, clears the liveness flag, and delivers the wake to
  a parked `wait_for_wake`.
- **Idempotent double-click.** Two sequential POSTs with the same
  decision: both 200, identical `ApprovalView`. Two with conflicting
  decisions: first 200, second `CONFLICT`.
- **Concurrent decisions.** Two threaded TestClient POSTs against
  the same approval_id with the same decision: both 200; different
  decisions: one 200, one CONFLICT. Verifies the
  `WHERE decision IS NULL` arbiter via the HTTP path.
- **NOT_FOUND.** POST to a random UUID → 404. POST as a non-owner →
  404 (existence not leaked).
- **Matcher exception defaults open.** Patch `ActionMatcher.match`
  to raise; assert the request is forwarded unchanged, no DB /
  liveness side effects, and `gate.matcher_error` is logged.
- **Body size cap.** Send a request body > `PARSER_MAX_BODY_BYTES`;
  assert 403 `body_too_large` without invoking the matcher.
- **Unidentified sandbox.** Drive a flow whose source IP doesn't
  resolve; assert 403 `unidentified_sandbox` and no DB row.
- **`raw_content is None`.** Force the flow's `raw_content` to None;
  assert 403 `body_too_large`.
- **Slack host suffix matrix.** Hosts `slack.com`, `slack.com.`,
  `api.slack.com` match; `evil-slack.com` does not. Verified against
  `SlackSendMessageMatcher.match` directly.
- **Slack body encodings.** `application/json` and
  `application/x-www-form-urlencoded` bodies both classify to the
  `slack.send_message` action_type; form-encoded scalar values are
  collapsed.
- **Liveness TTL alone writes nothing.** Patch `LIVENESS_TTL_S` to
  0.5s; let it lapse; assert the row stays `decision IS NULL`.
- **Heartbeat refreshes.** Patch `HEARTBEAT_INTERVAL_S` to 0.1s,
  wait 0.5s, assert ≥3 `set_alive` calls observed.
- **SIGTERM drain — claim path.** Drive `_create_request`, populate
  `_inflight_tenant_by_approval`, invoke `drain_inflight` directly;
  assert each row reaches `EXPIRED`, `gate.drain_expired` logged,
  and a wake was pushed.
- **SIGTERM drain — read-back-and-forward path.** Drive
  `_create_request`, commit `APPROVED` via the API while the addon
  is still in `_inflight_tenant_by_approval`, invoke
  `drain_inflight`; assert the row stays `APPROVED` and the wake
  carries APPROVED.
- **CancelledError path.** Cancel the addon task mid-wait; assert
  the row is `EXPIRED` (or stays whatever the API wrote) and the
  liveness key is released.
- **Live endpoint vs Redis flip.** `GET /approvals/sessions/{id}/live`
  returns the row while the Redis key exists; let it expire (patched
  TTL) and the endpoint returns an empty list.
- **Decision excludes from live feed.** Row has `decision != NULL`
  and key still in Redis → `/live` returns empty.
- **Orphan visibility.** After a hard "crash" (cancel the heartbeat
  without going through drain), the row remains queryable via
  `list_session_action_approvals(decision=None)` with
  `decision IS NULL`.
- **Lost wake recovery.** Patch `send_wake` to no-op; the proxy's
  `wait_for_wake` times out, reads the row, and forwards / rejects
  per the recorded decision.
- **Cache signal failure swallowed.** Patch `clear_alive` and
  `send_wake` to raise `CACHE_TRANSIENT_ERRORS`; assert the API
  still returns 200 and the DB row is updated. Assert
  `approval.cache_signal_failed` warning logged.
- **Notification dispatch failure swallowed.** Patch
  `_notify_approval_requested` to raise; assert the row is still
  committed and `approval.notify_failed` warning is logged.
- **PII not in logs.** Run a create flow with sentinel content in
  `payload`; assert no log line contains it.

Integration (full stack):

- Trigger a gated request from a stand-in sandbox through the real
  proxy + Redis + DB; POST a decision via the API; assert the
  upstream outcome and that `/approvals/sessions/{id}/live` drops the
  row within polling cadence.
- **Cron-driven session.** A scheduled task prompts an existing
  session, that session triggers a gated request, the same approval
  flow runs; verify the `APPROVAL_REQUESTED` notification fires and
  the audit query returns the row.

Smoke (runbook item, not automated): real Slack send through real
proxy in staging with manual approve / reject.

## Dependencies

- Phase 1 complete.
- A working `ActionMatcher` implementation. v0 ships
  `SlackSendMessageMatcher`; Phase 4's parser registry replaces it.
- **Redis-backed `CacheBackend`.** Required, not optional. The proxy
  and API use the existing surface only: `set` / `delete` / `exists` /
  `rpush` / `blpop` / `expire`. Local dev runs Redis already.

## Open during phase

- Whether the chat's `/live` polling should move to SSE / WebSocket
  push in Phase 3 to avoid the polling lag. Phase 2 ships polling.

## Definition of done

- Schema is the single `action_approval` table with nullable
  `decision`; `ApprovalDecision` enum is APPROVED / REJECTED /
  EXPIRED (pending is `decision IS NULL`); FK cascade from
  `build_session`.
- Liveness lifecycle works: `set_alive` on row insert and refreshed
  every 15s while waiting (TTL 60s); `clear_alive` on decision /
  timeout / cancel / SIGTERM drain.
- `POST /approvals/{id}/decision` race-safe via the conditional
  `WHERE decision IS NULL` UPDATE; double-clicks idempotent;
  conflicting decisions return CONFLICT; non-owner returns 404.
- `GET /approvals/sessions/{id}/live` returns only undecided rows
  whose Redis liveness key is present; orphan rows from a proxy
  crash drop out within `LIVENESS_TTL_S`.
- `GET /approvals/sessions/{id}` returns the full audit history,
  filterable by `decision`, `from_dt`, `to_dt`.
- Audit table holds every decision class (interactive approve /
  reject, expired, orphan). `list_session_action_approvals` returns
  the session-scoped history.
- SIGTERM drain: rows the proxy owns reach EXPIRED; rows the API
  already decided are forwarded / rejected inline before exit; the
  parked `_await_decision` coroutine is woken either way.
- Oversized bodies, unidentified sandboxes, and `raw_content is None`
  reject with 403; matcher exceptions default open.
- `SlackSendMessageMatcher` matches `slack.com` / `*.slack.com`,
  rejects `evil-slack.com`, requires POST + case-insensitive
  `/api/chat.postmessage`, and decodes both JSON and form bodies.
- Structured logs at every state transition; no PII (`payload`) in
  any log line.
- `APPROVAL_REQUESTED` notification dispatch verified end-to-end;
  body is `{approval_id, session_id, action_type}` — no PII.
- Cron-driven session integration test green.
- Bash-tool default verified / raised per T2.9.
