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
   decision write. Liveness is a SQL-only predicate
   (`decision IS NULL AND created_at >= now() - WAIT_TIMEOUT_S`); no
   separate Redis presence key.
2. **Gate wiring.** The proxy stops being pass-through. On a gated
   request, the gate addon writes the `action_approval` row, pushes
   an announce onto the session's announce list (so the api-server's
   chat-stream merger emits an `ApprovalRequestedPacket` on the open
   SSE), blocks on a per-approval wake channel until a decision lands
   or the wait window elapses, and then forwards or rejects.

At the end of Phase 2, gated external-app requests work end-to-end.
The Phase 3 chat surface fetches actionable rows via
`GET /api/build/approvals/sessions/{id}/live` and notifications
deep-link to the same session.

## Phase 1 context

- Identity is two-phase. `ResolvedSandbox` (pod IP → `sandbox_id, user_id, tenant_id, sandbox_name, sandbox_ip`) is returned by `IdentityResolver.resolve_sandbox(src_ip)` and is sufficient to authorize egress. `SessionContext` adds `session_id`, built by `resolved.with_session(session_id)` after `IdentityResolver.resolve_active_session(user_id, tenant_id)` returns the most-recently-active `BuildSession`. The session owner (`user_id` on the parent `build_session`) is the only authorized decider.
- Proxy `main()` already calls `SqlEngine.init_engine(pool_size=4, max_overflow=4)`. The gate addon reuses this engine via a per-tenant session factory.
- Identity resolution is owned by the gate addon itself: every flow
  starts with `self._identity.resolve_sandbox(src_ip)`. The gate does
  not read `flow.metadata` for session context. Session lookup is
  deferred until after the matcher confirms the request is gated, so
  non-gated egress (npm install, apt update, etc.) doesn't depend on
  having an active session.

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
    orphan is decided in SQL by comparing `created_at` against
    `WAIT_TIMEOUT_S` (see `sandbox_proxy/approval_cache.py`).
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

def try_record_decision(
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
    vs. genuine CONFLICT — see T2.4). This is the single race arbiter
    for the entire feature; both the API's `submit_decision` and the
    proxy's `_claim_expired_or_read_winner` call it."""

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
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[ActionApproval]:
    """User-scoped audit query. `decision=None` returns every row
    including `decision IS NULL` (orphan attempts)."""

def list_session_pending_action_approvals(
    db_session: Session, session_id: UUID, *,
    created_after: datetime | None = None,
) -> list[ActionApproval]:
    """Every row for the session with `decision IS NULL`. The live
    endpoint passes `created_after = now() - WAIT_TIMEOUT_S` so rows
    older than the wait window — i.e. rows whose parked proxy is
    gone — are excluded as orphans."""

```

The tenant-scoped audit query backing the admin page is added in
Phase 4.

### T2.3 — Call sites (overview)

`db/action_approval.py` queries and `sandbox_proxy/approval_cache.py`
functions have three call sites:

- **Gate addon — create flow.** Commits the `action_approval` row,
  then pushes onto the session's announce list and dispatches
  `APPROVAL_REQUESTED` (both best-effort; a missed announce/notification
  degrades to "card surfaces on the FE's next `/live` refetch"). Full
  code in T2.7.
- **API handler — decision flow.** Auth + ownership check via
  `get_action_approval_for_user` (NOT_FOUND on missing or non-owner),
  idempotency check, race-safe `try_record_decision`, best-effort
  `approval_cache.send_wake`. Full code in T2.4.
- **Chat-stream merger — announce path.** The streaming endpoint's
  generator wraps the ACP iterator in `_merge_acp_with_announces`,
  which spawns a daemon thread that `BLPOP`s the announce list (1s
  timeout) and yields `ApprovalRequestedPacket` frames inline on the
  open SSE. Details in the "SSE-piggyback announce" subsection below.

The policy-evaluator silent-decision path lives in Phase 4 and adds
its own `insert_silent_action_approval` helper alongside this module.

All cache access uses `approval_cache.py` functions. Callers obtain
a `CacheBackend` via `get_cache_backend(tenant_id=...)` at call time —
no FastAPI `Depends()` for cache (matches the codebase convention in
`onyx.chat.stop_signal_checker`). Tenant prefixing lives in the
factory; both keys (`approval:announce:{session_id}` and
`approval:wake:{approval_id}`) are tenant-scoped automatically.

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

    Actionable = `decision IS NULL` AND `created_at >= now() - WAIT_TIMEOUT_S`.
    Rows older than the wait window are treated as orphaned (the
    proxy parked on them is gone — either it crashed or its wait
    timed out without writing back) and excluded. The FE consumes
    this via SWR with key
    `SWR_KEYS.buildSessionLiveApprovals(sessionId)`."""

@router.get("/sessions/{session_id}")
def list_session_approvals(
    session_id: UUID,
    decision: ApprovalDecision | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
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
    current = action_approval.get_action_approval_for_user(
        db_session, approval_id, user.id,
    )
    if current is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")

    # Idempotent double-click: same decision recorded → 200 with row.
    if current.decision is not None:
        return _existing_decision_response(current, body.decision, approval_id)

    decided = action_approval.try_record_decision(
        db_session, approval_id=approval_id, decision=body.decision,
    )
    if decided is None:
        # Lost the race. Expire `current` first so SQLAlchemy's
        # identity map doesn't hand back the stale `decision=None`
        # instance on re-read.
        db_session.expire(current)
        winner = action_approval.get_action_approval(db_session, approval_id)
        if winner is None:
            # FK cascade deleted the row between the initial read and
            # the conditional UPDATE — surface as NOT_FOUND so the
            # client distinguishes the cases.
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")
        if winner.decision is None:
            # try_record_decision returned None only because a decision
            # is already recorded — guarded with an explicit None-check
            # (not `assert`) so `python -O` doesn't strip the invariant.
            raise OnyxError(
                OnyxErrorCode.INTERNAL_ERROR,
                "approval row reverted to pending unexpectedly",
            )
        return _existing_decision_response(winner, body.decision, approval_id)

    db_session.commit()

    try:
        cache = get_cache_backend(tenant_id=get_current_tenant_id())
        approval_cache.send_wake(approval_id, body.decision, cache)
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning(
            "approval.wake_failed approval_id=%s error=%s",
            approval_id, str(e),
        )

    return _to_view(decided, is_live=False)
```

`_to_view` serializes the row; `is_live` is computed in SQL terms
(undecided AND within the wait window):

```python
def _is_live(row: ActionApproval, cutoff: datetime) -> bool:
    return row.decision is None and row.created_at >= cutoff
```

The cutoff is `now() - WAIT_TIMEOUT_S` and is computed once per
request. No Redis hit per row — liveness is fully determined by the
two DB columns. This keeps the endpoint cheap to poll/refetch and
eliminates the cross-replica staleness window a presence key would
introduce.

Register the router on `backend/onyx/server/features/build/api.py`.
No `response_model`. Raise `OnyxError` only.

**Approvals are not BuildMessages.** The chat does not augment the
messages endpoint with `is_live`; instead it consumes
`GET /api/build/approvals/sessions/{id}/live` via SWR (key
`SWR_KEYS.buildSessionLiveApprovals(sessionId)`) and renders any
returned row as an inline card. There is no `is_live` field on
`MessageResponse`.

#### SSE-piggyback announce

The chat streaming endpoint's generator wraps the ACP iterator in
`BuildSessionManager._merge_acp_with_announces(acp_iter, session_id, tenant_id)`.
That static method spawns two daemon threads writing onto a shared
`queue.Queue`:

* one consumes the ACP iterator,
* one calls `approval_cache.pop_announcement(session_id, timeout_s=1, ...)`
  in a loop and, on each non-None return, pushes an
  `ApprovalRequestedPacket(approval_id=..., session_id=...)` onto the
  queue.

The generator drains the queue and yields. The streaming endpoint
recognises `ApprovalRequestedPacket` and emits it as an SSE frame
inline alongside ACP events. Worst-case announce-to-FE latency is the
1s BLPOP timeout.

`ApprovalRequestedPacket` carries only `approval_id` and `session_id`
(see `server/features/build/packets.py`); the FE refetches the row
via the `/live` endpoint to render the card. Keeping the packet small
means Postgres stays the single source of truth for card contents and
the FE never has to reconcile two shapes.

**FE invalidation.** The `useBuildStreaming` hook recognises the
`approval_requested` packet and calls
`globalMutate(SWR_KEYS.buildSessionLiveApprovals(sessionId))`. Any
component that subscribes to that SWR key gets a push invalidation
for free; the Phase 3 card component just needs
`useSWR(SWR_KEYS.buildSessionLiveApprovals(sessionId), fetcher)`.

A missed announce (cache transient error, FE not yet streaming) is
correct but delayed: the FE refetches `/live` on reconnect / remount,
so the card surfaces on the next natural refresh. Realtime is
best-effort, correctness is not.

### T2.5 — Approval cache module

`backend/onyx/sandbox_proxy/approval_cache.py` is a module of
procedural functions over `CacheBackend`, following the
`onyx.chat.stop_signal_checker` / `chat_processing_checker` pattern.
No wrapper classes — callers obtain a `CacheBackend` via
`get_cache_backend(tenant_id=...)` (`onyx.cache.factory`) and pass it
in. The factory handles tenant prefixing, so both keys are
automatically scoped per tenant.

Two single-purpose Redis lists back the rendezvous:

* `approval:announce:{session_id}` — the proxy `RPUSH`es an
  `approval_id` onto this list right after committing the row. The
  api-server's chat-stream merger (`_merge_acp_with_announces` in
  `BuildSessionManager`) `BLPOP`s it and emits an
  `ApprovalRequestedPacket` on the open SSE so the FE renders the
  card immediately.
* `approval:wake:{approval_id}` — the api-server `RPUSH`es a decision
  onto this list when a write lands. The parked proxy's `BLPOP`
  unblocks so it can write the response back to the sandbox without
  waiting out `WAIT_TIMEOUT_S`.

The conditional `WHERE decision IS NULL` UPDATE in
`db/action_approval.try_record_decision` is the only race arbiter;
cache operations are best-effort notifications. A missed announce
falls back to the FE's next `/live` refetch; a missed wake falls back
to the proxy's wait timeout. Neither loses correctness.

There is **no heartbeat and no presence key.** "Is this row still
actionable?" is answered by SQL alone:
`decision IS NULL AND created_at >= now() - INTERVAL '<WAIT_TIMEOUT_S>'`.
`WAIT_TIMEOUT_S = 180` lives in `approval_cache.py` and is the single
coordination constant — the same value bounds the proxy's park time
in `_await_decision` AND the orphan cutoff in `/live`. A hard proxy
crash leaves the row pending in Postgres; it falls out of `/live`
automatically once `WAIT_TIMEOUT_S` elapses.

```python
# Outer bound on how long the proxy will park on a single approval.
# Also serves as the "is this row still actionable" window the
# /live endpoint applies.
WAIT_TIMEOUT_S = 180

# A never-consumed announce / wake auto-evicts. The values only need
# to outlive the gap between RPUSH and the consumer's BLPOP.
ANNOUNCE_TTL_S = 60
WAKE_TTL_S = 30


# Proxy side ----------------------------------------------------------

def announce_approval(
    approval_id: UUID, session_id: UUID, cache: CacheBackend
) -> None:
    """RPUSH onto approval:announce:{session_id} + EXPIRE. Best-effort.

    A missed push degrades to 'card surfaces only on the FE's next
    /live refetch' — correctness preserved, realtime not."""


async def wait_for_wake(
    approval_id: UUID, timeout_s: int, cache: CacheBackend
) -> ApprovalDecision | None:
    """BLPOP wrapped via asyncio.to_thread so the proxy event loop
    doesn't block. Returns the decoded decision or None on timeout /
    unparseable payload (caller re-reads the row)."""


# API side ------------------------------------------------------------

def send_wake(
    approval_id: UUID, decision: ApprovalDecision, cache: CacheBackend
) -> None:
    """RPUSH + EXPIRE so a never-consumed wake auto-evicts. Best-effort."""


# Chat-stream merger side --------------------------------------------

def pop_announcement(
    session_id: UUID, timeout_s: int, cache: CacheBackend
) -> UUID | None:
    """Synchronous BLPOP of one announce_id, or None on timeout.
    Intended to run in a producer thread feeding the chat-stream
    merge queue."""
```

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

ACTION_TYPE_SLACK_POST_MESSAGE = "slack.post_message"


@dataclass(frozen=True)
class ActionMatch:
    action_type: str   # e.g. "slack.post_message"
    payload: dict[str, Any]


class ActionMatcher(Protocol):
    """Single-method seam used by the gate addon. Return None for
    non-gated traffic; do not raise for 'this isn't my action type'."""
    def match(self, request: http.Request) -> ActionMatch | None: ...
```

The gate depends only on `ActionMatcher`. Phase 2 wires up the
single-file v0 implementation `SlackPostMessageMatcher`. It hardcodes
detection of Slack `chat.postMessage` and emits
`action_type=ACTION_TYPE_SLACK_POST_MESSAGE` (wire string
`"slack.post_message"`) — small enough to delete and replace when a
broader registry lands. Phase 4's parser registry plugs in by
providing its own `ActionMatcher`; no other code in Phase 2 needs to
change.

`SlackPostMessageMatcher` specifics:

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
map (e.g. `"slack.post_message"` → `"Craft is trying to send a
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
PARSER_MAX_BODY_BYTES = 1_048_576

DBSessionFactory = Callable[[str], AbstractContextManager[Session]]
CacheFactory = Callable[[str], CacheBackend]


class GateAddon:
    def __init__(
        self,
        identity: _Resolver,
        action_matcher: ActionMatcher,
        db_session_factory: DBSessionFactory,
        cache_factory: CacheFactory,
        proxy_instance_id: str,
    ) -> None:
        ...
        # approval_id -> tenant_id for every approval the proxy is
        # currently parked on. The SIGTERM drain reads this to route
        # the conditional UPDATE to the right schema. Mutated only
        # from the event loop (mitmproxy hooks + drain), so no lock.
        # Invariant: _persist_approval_row is the only writer,
        # _await_decision's finally is the only remover.
        self._parked_approvals: dict[UUID, str] = {}
        # Each running request() coroutine registers itself here so
        # the drain can asyncio.wait on real completion instead of
        # sleeping. Self-cleaning via add_done_callback.
        self._inflight_tasks: set[asyncio.Task[None]] = set()

    async def request(self, flow: http.HTTPFlow) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._inflight_tasks.add(task)
            task.add_done_callback(self._inflight_tasks.discard)

        gate_target = self._resolve_and_match(flow)
        if gate_target is None:
            return
        ctx, match = gate_target

        # mitmproxy's default on addon exceptions is to forward the
        # original request, which would silently bypass the gate. Wrap
        # row creation + the wait so any unhandled error becomes a
        # fail-closed 403 and terminalizes the committed row.
        approval_id: UUID | None = None
        try:
            approval_id = self._persist_approval_row(ctx, match)
            decision = await self._await_decision(approval_id, ctx, match)
            self._write_response_for_decision(flow, decision)
        except Exception:
            logger.exception(
                "gate.unhandled_error session_id=%s tenant_id=%s "
                "approval_id=%s action_type=%s",
                ctx.session_id, ctx.tenant_id, approval_id, match.action_type,
            )
            flow.response = _http_403(_CODE_INTERNAL_ERROR)
            if approval_id is not None:
                self._terminalize_after_unhandled_error(approval_id, ctx.tenant_id)
```

`_resolve_and_match` is the entry funnel: identity → body-size cap →
matcher → (only on gated requests) active-session lookup. Identity
resolution is owned in-line by the gate — every flow calls
`self._identity.resolve_sandbox(src_ip)` directly. There is no
`flow.metadata` fast path.

Phase ordering matters: the **active session is checked last**, only
after the matcher has confirmed the request is gated. Non-gated
traffic (npm install, apt update, pip, anything outside the matcher
registry) is authorized purely by pod identity, so startup-time and
inter-session egress flow even when the user has no ACTIVE session.

**Fail-closed paths** set `flow.response` to a 403 and return `None`:

- No source IP on `flow.client_conn.peername` → `unidentified_sandbox`.
- `identity.resolve_sandbox()` raises → log `gate.identity_error`,
  `unidentified_sandbox`. A DB blip cannot grant ungated egress.
- `identity.resolve_sandbox()` returns `None` → `unidentified_sandbox`.
- `flow.request.raw_content is None` → `body_too_large`. Defensive
  against a future addon enabling `stream=True`; we don't enable
  streaming today.
- `len(raw_content) > PARSER_MAX_BODY_BYTES` → `body_too_large`.
- Gated request, but `identity.resolve_active_session()` returns
  `None` (or raises) → log `gate.no_active_session` /
  `gate.session_lookup_error`, `no_active_session`. We can't mint
  an approval without a session to route the card to.

**Fail-open paths** return `None` without touching `flow.response`
(mitmproxy then forwards the request unchanged):

- `matcher.match(...)` raises → log `gate.matcher_error`.
- `matcher.match(...)` returns `None` — request isn't gated. Pod
  identity has already been confirmed; no session lookup runs.

`_persist_approval_row` commits the row, registers it for the drain,
and pushes onto the session's announce list:

```python
def _persist_approval_row(self, ctx: SessionContext, match: ActionMatch) -> UUID:
    with self._db_session_factory(ctx.tenant_id) as db:
        row = action_approval.insert_action_approval(
            db,
            session_id=ctx.session_id,
            action_type=match.action_type,
            payload=match.payload,
        )
        approval_id = row.approval_id  # capture before commit detaches
        db.commit()

    # Register here (not in _await_decision) so a SIGTERM firing
    # between commit and the caller's await still finds the row.
    self._parked_approvals[approval_id] = ctx.tenant_id

    try:
        approval_cache.announce_approval(
            approval_id,
            ctx.session_id,
            self._cache_factory(ctx.tenant_id),
        )
    except CACHE_TRANSIENT_ERRORS as e:
        # Best-effort: a missed announce degrades to "FE surfaces the
        # card on the next /live refetch (reconnect / remount)". The
        # row is already in Postgres, so we don't fail the request.
        logger.warning(
            "gate.announce_failed approval_id=%s error=%s",
            approval_id, str(e),
        )

    # Best-effort APPROVAL_REQUESTED notification.
    try:
        self._notify_approval_requested(approval_id, ctx, match)
    except Exception as e:
        logger.warning("approval.notify_failed approval_id=%s error=%s",
                       approval_id, str(e))
    return approval_id
```

Commit-first ordering: the DB row is the source of truth, the
announce is a hint. A failed announce never blocks the request from
being gated — the FE's next `/live` refetch will pick the row up.

`_await_decision` parks on the wake channel and claims EXPIRED on
timeout / cancel. The parked-approvals entry was set in
`_persist_approval_row`; this method only owns its removal.

```python
async def _await_decision(
    self, approval_id: UUID, ctx: SessionContext, match: ActionMatch,
) -> ApprovalDecision:
    cache = self._cache_factory(ctx.tenant_id)
    try:
        decision = await approval_cache.wait_for_wake(
            approval_id, approval_cache.WAIT_TIMEOUT_S, cache,
        )
        if decision is not None:
            return decision
        # Timeout — race-safe via the conditional UPDATE.
        return self._claim_expired_or_read_winner(approval_id, ctx.tenant_id)
    except asyncio.CancelledError:
        # Sandbox-side socket closed mid-wait. Claim EXPIRED so the
        # audit row is terminal, then re-raise so mitmproxy releases
        # the flow.
        self._claim_expired_or_read_winner(approval_id, ctx.tenant_id)
        raise
    finally:
        self._parked_approvals.pop(approval_id, None)
```

`_claim_expired_or_read_winner(approval_id, tenant_id)` is the single
race-safe claim helper: tries `try_record_decision(..., EXPIRED)`,
and on loss re-reads the row to return the winner's decision. Used
by the wait-timeout path, the `CancelledError` path, and the SIGTERM
drain (each passes the appropriate `tenant_id` — `ctx.tenant_id` for
the live paths, the snapshotted tenant from `_parked_approvals` for
the drain). If the row was deleted via FK cascade (parent
`build_session` dropped mid-flight), it returns `EXPIRED` and logs
`gate.row_missing_on_claim`.

`_terminalize_after_unhandled_error(approval_id, tenant_id)` is used
by `request()`'s outer exception handler. It calls
`_claim_expired_or_read_winner` (swallowing exceptions as
`gate.terminalize_db_failed`) and then `send_wake` (swallowing as
`gate.terminalize_wake_failed`), so cleanup never masks the original
exception.

`_write_response_for_decision`:

```python
def _write_response_for_decision(
    self, flow: http.HTTPFlow, decision: ApprovalDecision,
) -> None:
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
`unidentified_sandbox | no_active_session | body_too_large | user_rejected | not_authorized | internal_error`.
`policy_denied` is reserved for Phase 4. The body is
`json.dumps({"error": code, "message": prose})` with
`content-type: application/json` — `error` is the stable code, `message` is
human-readable prose the sandbox agent acts on.
Matcher exceptions do not produce 403s — they fail open per T2.6.

**SIGTERM drain (`drain_inflight`).** Two phases, each best-effort:

1. **Wake parked approvals.** For each `(approval_id, tenant_id)` in
   a snapshot of `_parked_approvals`:
   - `_claim_expired_or_read_winner(approval_id, tenant_id)` — same
     single claim helper the live paths use, with the tenant_id
     snapshotted at registration time (the `SessionContext` is no
     longer in scope).
   - `approval_cache.send_wake(approval_id, decision, ...)` so the
     parked `_await_decision` coroutine's BLPOP returns immediately
     instead of waiting out `WAIT_TIMEOUT_S`.
   - On a winning claim → log `gate.drain_expired`. On a lost claim
     (the API wrote APPROVED / REJECTED first) → log
     `gate.drain_forwarded`.
2. **Wait for tasks.** `asyncio.wait` on every task in
   `self._inflight_tasks` (excluding the drain coroutine itself, in
   case it's ever scheduled as one). The wakes from phase 1 let each
   parked `request()` task return promptly; the wait ensures every
   coroutine fully serialises its response (including any upstream
   forward on APPROVED) before mitmproxy tears connections down.

Dropping the connection without forwarding an already-APPROVED
upstream call would mean the audit log says APPROVED for an action
that never happened, so the drain explicitly wakes parked coroutines
rather than just exiting.

The signal handler in `sandbox_proxy/server.py` schedules the drain
on the event loop with a single outer timeout
(`_DRAIN_TIMEOUT_S = 10.0`). The K8s
`terminationGracePeriodSeconds` sizes to `_DRAIN_TIMEOUT_S + margin`,
i.e. ≥ 20s.

**Hard proxy crash (kill -9, OOM).** The `request()` coroutine dies
with the process. The DB row sits with `decision IS NULL`; the
`/live` endpoint's `created_at >= now() - WAIT_TIMEOUT_S` cutoff
filters it out as soon as the wait window elapses (180s), so the
chat card disappears on its own. The row remains visible to the
admin audit view via a `decision IS NULL` filter.

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
  `gate.drain_forwarded`, `gate.drain_error`, `gate.drain_awaiting_tasks`,
  `gate.matcher_error`, `gate.identity_error`, `gate.unhandled_error`,
  `gate.announce_failed`, `gate.terminalize_db_failed`,
  `gate.terminalize_wake_failed`, `gate.row_missing_on_claim`.
- API handler: `approval.decision_recorded`,
  `approval.decision_conflict`, `approval.wake_failed`,
  `approval.notify_failed`.
- Chat-stream merger: `approval.announce_poll_failed`.

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

| Constant                | Value     | Lives in            |
| ----------------------- | --------- | ------------------- |
| `WAIT_TIMEOUT_S`        | 180       | `approval_cache.py` |
| `ANNOUNCE_TTL_S`        | 60        | `approval_cache.py` |
| `WAKE_TTL_S`            | 30        | `approval_cache.py` |
| `PARSER_MAX_BODY_BYTES` | 1_048_576 | `addons/gate.py`    |
| `_DRAIN_TIMEOUT_S`      | 10.0      | `server.py`         |

`WAIT_TIMEOUT_S` is the single coordination constant: the proxy
parks for at most this long, and `/live` excludes rows older than
this. The TTLs on the announce/wake lists only need to outlive the
gap between RPUSH and the consumer's BLPOP.

**Metrics deferred.** Leave no-op hooks where counters / histograms
will land. Likely candidates:

- Counters: `approvals_created`, `approved`, `rejected`, `expired`,
  `silent_allowed`, `denied`, `matcher_error`.
- Histograms: `approval_decision_latency_seconds`,
  `blpop_wait_seconds`.

## Testing

For test-tier conventions see CLAUDE.md. `WAIT_TIMEOUT_S` is
monkey-patched to <1s in tests where wall-clock waits would otherwise
poison CI.

External-dependency-unit (real Postgres + Redis):

- **Create flow.** `GateAddon._persist_approval_row` writes the row
  in one transaction; an announce_id appears on
  `approval:announce:{session_id}` afterwards.
- **Decision APPROVED / REJECTED.** `POST /approvals/{id}/decision`
  writes the row and delivers the wake to a parked
  `wait_for_wake`.
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
  to raise; assert the request is forwarded unchanged, no DB or
  announce side effects, and `gate.matcher_error` is logged.
- **Body size cap.** Send a request body > `PARSER_MAX_BODY_BYTES`;
  assert 403 `body_too_large` without invoking the matcher.
- **Unidentified sandbox.** Drive a flow whose source IP doesn't
  resolve; assert 403 `unidentified_sandbox` and no DB row.
- **`raw_content is None`.** Force the flow's `raw_content` to None;
  assert 403 `body_too_large`.
- **Slack host suffix matrix.** Hosts `slack.com`, `slack.com.`,
  `api.slack.com` match; `evil-slack.com` does not. Verified against
  `SlackPostMessageMatcher.match` directly.
- **Slack body encodings.** `application/json` and
  `application/x-www-form-urlencoded` bodies both classify to the
  `slack.post_message` action_type; form-encoded scalar values are
  collapsed.
- **SIGTERM drain — claim path.** Drive `_persist_approval_row`,
  populate `_parked_approvals`, invoke `drain_inflight` directly;
  assert each row reaches `EXPIRED`, `gate.drain_expired` logged,
  and a wake was pushed onto `approval:wake:{id}`.
- **SIGTERM drain — read-back-and-forward path.** Drive
  `_persist_approval_row`, commit `APPROVED` via the API while the
  addon is still in `_parked_approvals`, invoke `drain_inflight`;
  assert the row stays `APPROVED`, `gate.drain_forwarded` logged,
  and the wake carries APPROVED.
- **SIGTERM drain — waits for tasks.** Hold a fake `request()` task
  blocked, invoke `drain_inflight`; assert it does not return until
  the task completes (verifies the `asyncio.wait` phase).
- **CancelledError path.** Cancel the addon task mid-wait; assert
  the row is `EXPIRED` (or stays whatever the API wrote) and the
  parked-approvals entry is removed.
- **Live endpoint cutoff.** `GET /approvals/sessions/{id}/live`
  returns the row while `now() - created_at < WAIT_TIMEOUT_S`. Patch
  `WAIT_TIMEOUT_S` to ~0; the endpoint returns an empty list (orphan
  cutoff).
- **Decision excludes from live feed.** Row has `decision != NULL`;
  `/live` returns empty regardless of `created_at`.
- **Announce-then-stream.** Start a chat SSE stream, then commit a
  row via `_persist_approval_row` and `announce_approval`; assert
  the stream emits an `ApprovalRequestedPacket` carrying the
  approval_id within ~1s (the announce BLPOP cadence).
- **Orphan visibility.** After a hard "crash" (kill the addon task
  without invoking drain), the row remains queryable via
  `list_session_action_approvals(decision=None)` and falls out of
  `/live` once `WAIT_TIMEOUT_S` elapses.
- **Lost wake recovery.** Patch `send_wake` to no-op; the proxy's
  `wait_for_wake` times out, the gate claims EXPIRED, and the row
  reflects either EXPIRED or the API-written decision per the race.
- **Cache signal failure swallowed.** Patch `send_wake` to raise
  `CACHE_TRANSIENT_ERRORS`; assert the API still returns 200 and the
  DB row is updated. Assert `approval.wake_failed` warning logged.
- **Announce failure swallowed.** Patch `announce_approval` to raise
  `CACHE_TRANSIENT_ERRORS`; assert the row is still committed, the
  gate proceeds to park on the wake channel, and `gate.announce_failed`
  warning is logged.
- **Notification dispatch failure swallowed.** Patch
  `_notify_approval_requested` to raise; assert the row is still
  committed and `approval.notify_failed` warning is logged.
- **PII not in logs.** Run a create flow with sentinel content in
  `payload`; assert no log line contains it.

Integration (full stack):

- Trigger a gated request from a stand-in sandbox through the real
  proxy + Redis + DB; POST a decision via the API; assert the
  upstream outcome and that `/approvals/sessions/{id}/live` drops the
  row immediately after the decision lands (no longer matches the
  `decision IS NULL` filter).
- **Cron-driven session.** A scheduled task prompts an existing
  session, that session triggers a gated request, the same approval
  flow runs; verify the `APPROVAL_REQUESTED` notification fires and
  the audit query returns the row.

Smoke (runbook item, not automated): real Slack send through real
proxy in staging with manual approve / reject.

## Dependencies

- Phase 1 complete.
- A working `ActionMatcher` implementation. v0 ships
  `SlackPostMessageMatcher`; Phase 4's parser registry replaces it.
- **Redis-backed `CacheBackend`.** Required, not optional. The proxy
  and API use the existing surface only: `rpush` / `blpop` / `expire`.
  Local dev runs Redis already.

## Definition of done

- Schema is the single `action_approval` table with nullable
  `decision`; `ApprovalDecision` enum is APPROVED / REJECTED /
  EXPIRED (pending is `decision IS NULL`); FK cascade from
  `build_session`.
- Liveness is SQL-only: a row is actionable iff `decision IS NULL`
  AND `created_at >= now() - WAIT_TIMEOUT_S`. No presence key, no
  heartbeat.
- `POST /approvals/{id}/decision` race-safe via the conditional
  `WHERE decision IS NULL` UPDATE in `try_record_decision`;
  double-clicks idempotent; conflicting decisions return CONFLICT;
  non-owner returns 404.
- `GET /approvals/sessions/{id}/live` returns only undecided rows
  within the wait window; orphan rows from a proxy crash drop out
  within `WAIT_TIMEOUT_S`.
- `GET /approvals/sessions/{id}` returns the full audit history,
  filterable by `decision`, `since`, `until`.
- Audit table holds every decision class (interactive approve /
  reject, expired, orphan). `list_session_action_approvals` returns
  the session-scoped history.
- Announce path delivers `ApprovalRequestedPacket` on the open chat
  SSE within ~1s of `_persist_approval_row` returning; the FE
  invalidates `SWR_KEYS.buildSessionLiveApprovals(sessionId)` on
  receipt.
- SIGTERM drain: rows the proxy owns reach EXPIRED; rows the API
  already decided are forwarded / rejected inline before exit; the
  parked `_await_decision` coroutine is woken either way; the drain
  blocks on every `request()` task until it serialises its response.
- Oversized bodies, unidentified sandboxes, and `raw_content is None`
  reject with 403; matcher exceptions default open.
- `SlackPostMessageMatcher` matches `slack.com` / `*.slack.com`,
  rejects `evil-slack.com`, requires POST + case-insensitive
  `/api/chat.postmessage`, decodes both JSON and form bodies, and
  emits `slack.post_message` as the action_type.
- Structured logs at every state transition; no PII (`payload`) in
  any log line.
- `APPROVAL_REQUESTED` notification dispatch verified end-to-end;
  body is `{approval_id, session_id, action_type}` — no PII.
- Cron-driven session integration test green.
- Bash-tool default verified / raised per T2.9.
