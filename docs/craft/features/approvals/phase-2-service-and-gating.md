# Phase 2 — Approval Service & Gate Wiring (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 1.

## Goal

Two halves shipped together:

1. **Approval data layer + decision API.** Single `action_approval` table
  whose `decision` column is nullable (NULL = no decision recorded
   yet); a `db/action_approval.py` query module is the single source of SQL.
   The decision endpoint and the chat-render augmentation live in
   `api.py`. Redis holds an ephemeral liveness key owned by the
   proxy so the chat surface only renders an actionable card while
   the proxy is still asking.
2. **Gate wiring.** The proxy stops being pass-through. On a gated
   action, the proxy writes the `action_approval` row + the
   `approval_request` `BuildMessage` + the liveness key in one
   transaction, blocks on a wakeup channel until a decision lands
   or the wait window elapses, and forwards or rejects.

At the end of Phase 2, gated external-app requests work end-to-end. Users
decide via the notification deep link (Phase 3 lands the inline chat
surface against the rows + `is_live` field Phase 2 writes / returns).

## Phase 1 context

- `SessionContext` shape: `session_id, user_id, sandbox_id, tenant_id, sandbox_name, sandbox_ip`. Phase 2 reads `session_id` and `tenant_id`; `user_id` equals `build_session.user_id` (the session-owner identity).
- Proxy `main()` already calls `SqlEngine.init_engine(pool_size=4, max_overflow=4)`. The gate addon reuses this engine via the same session factory.

## Module layout

Backend API:

```
backend/onyx/server/features/build/approvals/
└── api.py                 # FastAPI router (user-facing decision + audit)
```

DB (matches the existing build-feature layout — sibling query modules
under `server/features/build/db/`; models and enums centralized):

```
backend/onyx/server/features/build/db/action_approval.py    # query module
backend/onyx/db/models.py                                   # ActionApproval ORM (additions)
backend/onyx/db/enums.py                                    # ApprovalDecision (additions)
backend/alembic/versions/XXXX_create_action_approval.py
```

Proxy (the proxy image bundles the backend module tree; no HTTP between
proxy and api-server, all in-process Python imports):

```
backend/onyx/sandbox_proxy/approval_cache.py    # procedural cache fns (liveness + wakeup)
backend/onyx/sandbox_proxy/action_matcher.py    # ActionMatcher Protocol + v0 Slack-only impl
backend/onyx/sandbox_proxy/addons/gate.py       # the gating addon
```

Constants / notifications / background:

```
backend/onyx/configs/constants.py                          # NotificationType.APPROVAL_REQUESTED
```

Sandbox image (verify only):

```
backend/onyx/server/features/build/sandbox/...   # verify bash-tool timeout; update agent prompt
```

## Tasks

### T2.1 — Data model + migration

`ActionApproval` ORM in `backend/onyx/db/models.py`. Each row is one
agent-initiated gated-action attempt and its eventual decision. The
session owner is the only authorized decider — derive identity via
the `session_id` FK rather than storing it on the row.

```python
class ActionApproval(Base):
    """One agent-initiated gated action and its decision.

    `decision IS NULL` = no decision recorded (in-flight, or orphaned
    by a hard proxy crash). Liveness vs orphan is distinguished by
    the `approval:live:{id}` Redis key (T2.5), not by the DB.
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
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    decision: Mapped[ApprovalDecision | None] = mapped_column(
        Enum(ApprovalDecision, native_enum=False, name="approvaldecision"),
        nullable=True,
    )
    decided_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
```



`ApprovalDecision` in `db/enums.py` (pending state is `decision IS NULL`
— no enum value):

```python
class ApprovalDecision(str, PyEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
```

Hand-written Alembic migration in
`backend/alembic/versions/XXXX_create_action_approval.py`. Follow the shape
of `28429dd43807_scheduled_tasks.py` — `op.create_table` plus
`op.drop_table` in `downgrade()`.

### T2.2 — DB query module

`backend/onyx/server/features/build/db/action_approval.py`. Writes
flush implicitly so callers can read auto-generated IDs back; the
caller still owns transaction commit. Same convention as
`build_session.py` and `sandbox.py`.

```python
def insert_action_approval(
    db_session: Session, *,
    session_id: UUID, action_type: str, payload: dict,
) -> ActionApproval:
    """Row starts with decision IS NULL. approval_id is auto-generated
    by SQLAlchemy (`default=uuid4`); the function flushes so the
    caller can read `row.approval_id`."""

def insert_action_approval_request_build_message(
    db_session: Session, *,
    session_id: UUID, approval_id: UUID,
    action_type: str, payload: dict,
) -> BuildMessage:
    """Inserts a BuildMessage with type=ASSISTANT and
    message_metadata={'type': 'approval_request', 'approval_id': ...,
    'action_type': ..., 'payload': ...} at max(turn_index) for the
    session.

    Concurrency: takes SELECT ... FOR UPDATE on the parent
    build_session row before computing max(turn_index), serialising
    against the agent stream writer. Without this lock two writers
    can read the same max and collide on turn order. The lock is
    held only for the duration of this single transaction."""

def record_decision(
    db_session: Session, *,
    approval_id: UUID, decision: ApprovalDecision,
) -> ActionApproval | None:
    """UPDATE action_approval
       SET decision = :decision, decided_at = now()
       WHERE approval_id = :id AND decision IS NULL
       RETURNING *.
       Returns the row if updated, None if a decision was already
       recorded. Callers handle the None case (idempotent retry vs
       genuine CONFLICT — see T2.4)."""

def insert_silent_action_approval(
    db_session: Session, *,
    session_id: UUID, action_type: str, payload: dict,
    decision: ApprovalDecision,
) -> ActionApproval:
    """INSERT with decision + decided_at pre-populated. Asserts
    decision in (APPROVED, REJECTED) — EXPIRED is time-driven and
    never silent. No liveness key, no wakeup, no chat card."""

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

def list_tenant_action_approvals(
    db_session: Session, tenant_id: str, *,
    decision: ApprovalDecision | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 100,
    cursor: UUID | None = None,
) -> list[ActionApproval]:
    """Tenant-scoped audit query — Phase 4 admin audit page. JOINs
    action_approval to build_session and filters by tenant.
    Cursor-paginated."""

```

### T2.3 — Call sites (overview)

`db/action_approval.py` queries and `sandbox_proxy/approval_cache.py`
functions are invoked directly by three call sites:

- **Gate addon — create flow.** Writes the row + `BuildMessage` +
  liveness key in one DB transaction (Redis failure rolls the DB
  back), then dispatches `APPROVAL_REQUESTED` best-effort. Full
  code in T2.7.
- **API handler — decision flow.** Auth + ownership check via
  `get_action_approval_for_user` (NOT_FOUND on missing or
  non-owner), idempotent retry, conditional `WHERE decision IS NULL`
  UPDATE, best-effort `release_liveness` + `signal_decision`. Full
  code in T2.4.
- **Policy evaluator (Phase 4) — silent decision.**
  `insert_silent_action_approval(APPROVED | REJECTED)` only — no
  liveness key, no wakeup, no chat card. EXPIRED is server-only.

All cache access uses `approval_cache.py` functions. Callers
obtain the `CacheBackend` via `get_cache_backend(tenant_id=...)` at
call time — no FastAPI `Depends()` for cache (matches the codebase
convention in `onyx.chat.stop_signal_checker`).

### T2.4 — User-facing API

`backend/onyx/server/features/build/approvals/api.py`. Pydantic
request / response shapes:

```python
class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal[ApprovalDecision.APPROVED, ApprovalDecision.REJECTED]
    # Server rejects EXPIRED here — that's a server-only terminal state.

class ApprovalView(BaseModel):
    approval_id: UUID
    session_id: UUID
    action_type: str
    payload: dict
    created_at: datetime
    decision: ApprovalDecision | None
    decided_at: datetime | None
    is_live: bool

class ApprovalListResponse(BaseModel):
    items: list[ApprovalView]
    next_cursor: UUID | None
```

Router:

```python
router = APIRouter(prefix="/approvals")  # parent /build router already
                                          # applies require_onyx_craft_enabled
                                          # + BASIC_ACCESS.

@router.get("/sessions/{session_id}")
def list_session_approvals_endpoint(
    session_id: UUID,
    decision: ApprovalDecision | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalListResponse:
    """Audit query for a session the caller owns. `decision=None`
    returns every row including `decision IS NULL` (orphan attempts)."""

@router.post("/{approval_id}/decision")
def submit_decision(
    approval_id: UUID,
    body: DecisionBody,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ApprovalView:
    tenant_id = get_current_tenant_id()
    cache = get_cache_backend(tenant_id=tenant_id)

    request = action_approval.get_action_approval_for_user(db_session, approval_id, user.id)
    if request is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "approval request not found")

    # Idempotent double-click: same decision recorded → 200 with row.
    if request.decision is not None:
        if request.decision == body.decision:
            return _to_view(request, is_live=False)
        raise OnyxError(OnyxErrorCode.CONFLICT, "decision already recorded")

    updated = action_approval.record_decision(
        db_session, approval_id=approval_id, decision=body.decision,
    )
    if updated is None:
        # Lost the race; re-read and apply the same idempotency rule.
        fresh = action_approval.get_action_approval(db_session, approval_id)
        if fresh and fresh.decision == body.decision:
            return _to_view(fresh, is_live=False)
        raise OnyxError(OnyxErrorCode.CONFLICT, "decision already recorded")
    db_session.commit()

    logger.info(
        "approval.decision_recorded",
        extra={"approval_id": str(approval_id), "decision": body.decision.value,
               "user_id": str(user.id), "session_id": str(request.session_id)},
    )

    try:
        approval_cache.release_liveness(approval_id, cache)
        approval_cache.signal_decision(approval_id, body.decision.value, cache)
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning(
            "approval.cache_signal_failed",
            extra={"approval_id": str(approval_id), "error": str(e)},
        )

    return _to_view(updated, is_live=False)
```

Register the router on `backend/onyx/server/features/build/api/api.py`.
No `response_model`. Raise `OnyxError` only — always with the
`OnyxErrorCode.*` prefix.

**Cross-router addition** — augment each `approval_request`
`BuildMessage` in `GET /api/build/sessions/{id}/messages` with
`is_live: bool`:

```python
is_live = (
    approval_row.decision is None
    and approval_cache.liveness_exists(approval_row.approval_id, cache)
)
```

Cached server-side ~5s per `approval_id` to bound Redis read load on
chat reloads. The Phase 3 frontend renders the actionable card iff
`is_live=true`. Note the lag composition: client polls every 10s
(Phase 3) + server cache 5s + liveness TTL 60s on hard proxy crash =
worst-case ~75s for a card to disappear after a proxy dies. Decision
recorded by a live API path is reflected within polling cadence (≤15s).

### T2.5 — Approval cache module

`backend/onyx/sandbox_proxy/approval_cache.py` is a module of
procedural functions over `CacheBackend`, following the
`onyx.chat.stop_signal_checker` / `chat_processing_checker` pattern.
No wrapper classes — callers obtain a `CacheBackend` via
`get_cache_backend(tenant_id=...)` (`onyx.cache.factory`) and pass it
to each function.

The conditional `WHERE decision IS NULL` UPDATE in `db/action_approval.py`
is the race-safe arbiter; cache operations are best-effort
notifications.

```python
from onyx.cache.interface import CacheBackend

# Liveness key TTL must be a multiple of the heartbeat interval —
# 60 / 15 = 4× safety against a missed refresh tick. Wake TTL just
# needs to outlive a brief network blip between the API's RPUSH and
# the proxy's BLPOP.
LIVENESS_TTL_S = 60
HEARTBEAT_INTERVAL_S = 15
WAKE_TTL_S = 30


def _live_key(approval_id: UUID) -> str:
    return f"approval:live:{approval_id}"


def _wake_key(approval_id: UUID) -> str:
    return f"approval:wake:{approval_id}"


def publish_liveness(
    approval_id: UUID, proxy_instance_id: str, cache: CacheBackend
) -> None:
    """Idempotent — used for both initial acquire and periodic refresh.
    Redis SET overwrites by default; no NX needed."""
    cache.set(_live_key(approval_id), proxy_instance_id, ex=LIVENESS_TTL_S)


def release_liveness(approval_id: UUID, cache: CacheBackend) -> None:
    cache.delete(_live_key(approval_id))


def liveness_exists(approval_id: UUID, cache: CacheBackend) -> bool:
    return cache.exists(_live_key(approval_id))


async def wait_for_decision(
    approval_id: UUID, timeout_s: int, cache: CacheBackend
) -> str | None:
    """BLPOP wrapped via asyncio.to_thread so the proxy event loop
    doesn't block. Returns the decision string or None on timeout."""
    result = await asyncio.to_thread(
        cache.blpop, [_wake_key(approval_id)], timeout_s
    )
    if result is None:
        return None
    _key_bytes, value_bytes = result
    return value_bytes.decode()


def signal_decision(
    approval_id: UUID, decision: str, cache: CacheBackend
) -> None:
    """Best-effort wakeup. RPUSH + EXPIRE so a never-consumed key
    auto-evicts."""
    cache.rpush(_wake_key(approval_id), decision)
    cache.expire(_wake_key(approval_id), WAKE_TTL_S)
```

The gate addon refreshes the liveness key every `HEARTBEAT_INTERVAL_S`
via an asyncio task spawned alongside the BLPOP wait.

### T2.6 — Action-type matching

The gate addon needs one capability from this layer: given an
intercepted HTTPS request, return `(action_type, payload)` if the
request is gated, or `None` if it isn't. Everything else —
URL-to-app matching, per-provider parser modules, registries — is
owned by the External Apps workstream (`dane/ea-craft-5`) and its
final shape is not yet locked.

Phase 2 ships only the seam:

```python
# sandbox_proxy/action_matcher.py

@dataclass(frozen=True)
class ActionMatch:
    action_type: str   # e.g. "slack.send_message"
    payload: dict

class ActionMatcher(Protocol):
    def match(self, request) -> ActionMatch | None: ...
```

The gate addon depends only on `ActionMatcher`. Phase 2 wires up a
single-file v0 implementation that hardcodes Slack `chat.postMessage`
detection — small enough to delete and replace when the External
Apps work lands. Phase 4's parser registry plugs in by providing its
own `ActionMatcher` implementation; no other code in Phase 2 needs
to change.

The chat client maps `action_type` to a display label via a static
map (e.g. `"slack.send_message"` → `"Craft is trying to send a
message in Slack"`).

**Default open** on any ambiguity from the matcher:

- `matcher.match(...) is None` → request is not gated; forward
  unchanged.
- `matcher.match(...)` raises → log `gate.matcher_error` with the
  exception detail, then forward unchanged. The matcher is a
  heuristic over arbitrary HTTPS bodies; treating crashes as a
  security boundary breaks legitimate traffic when the matcher has
  a bug. The real security boundary is Phase 1's iptables egress
  lockdown, which already constrains the sandbox to talk only to
  the proxy. We're choosing "don't gate what we can't classify"
  over "block what we can't classify."

Body-size cap stays fail-closed (T2.7 enforces
`PARSER_MAX_BODY_BYTES`, 1 MiB): an oversize body
likely indicates either a real DoS attempt against the matcher or
exfiltration that wouldn't show up in summary/payload anyway.

### T2.7 — Gate addon

`request(flow)` is decomposed into helpers so the policy evaluator
(Phase 4) and other future hooks have a clean extension point — and
so the SIGTERM / cancel / timeout cleanup paths are share-able. Each
helper is independently testable.

```python
WAIT_TIMEOUT_S = 180
PARSER_MAX_BODY_BYTES = 1_048_576


class GateAddon:
    def __init__(self, identity, action_matcher: ActionMatcher,
                 db_factory, cache, proxy_instance_id: str):
        ...
        # _proxy_inflight is touched only from the event loop
        # (SIGTERM via loop.add_signal_handler), so a plain set is safe.
        self._proxy_inflight: set[UUID] = set()

    async def request(self, flow):
        ctx, match = self._match_action(flow)
        if ctx is None or match is None:
            return  # short-circuited (unidentified / non-gated / matcher miss)

        approval_id = self._create_request(ctx, match)
        decision = await self._await_decision(approval_id, ctx)
        self._apply_decision_to_flow(flow, decision)

    # --- helpers -----------------------------------------------------

    def _match_action(self, flow):
        """Identity + body-size + matcher dispatch. Returns
        (ctx, match) or sets flow.response and returns (None, None).
        A matcher crash falls open per T2.6."""
        ctx = self._identity.resolve(flow.client_conn.peername[0])
        if ctx is None:
            flow.response = _http_403("unidentified_sandbox")
            return None, None
        if len(flow.request.raw_content or b"") > PARSER_MAX_BODY_BYTES:
            flow.response = _http_403("body_too_large")
            return None, None
        try:
            match = self._action_matcher.match(flow.request)
        except Exception as e:
            # Default open — see T2.6.
            logger.exception("gate.matcher_error", extra={"error": str(e)})
            return ctx, None
        return ctx, match

    def _create_request(self, ctx, match) -> UUID:
        """Writes the row + BuildMessage + liveness key inside one DB
        transaction. Returns the auto-generated approval_id."""
        with self._db() as db:
            row = action_approval.insert_action_approval(
                db,
                session_id=ctx.session_id,
                action_type=match.action_type,
                payload=match.payload,
            )
            action_approval.insert_action_approval_request_build_message(
                db,
                session_id=ctx.session_id,
                approval_id=row.approval_id,
                action_type=match.action_type,
                payload=match.payload,
            )
            # Publish liveness inside the txn — Redis failure rolls
            # back the DB writes too.
            approval_cache.publish_liveness(
                row.approval_id, self._proxy_instance_id, self._cache,
            )
            db.commit()

        approval_id = row.approval_id
        logger.info("gate.row_committed",
                    extra={"approval_id": str(approval_id),
                           "session_id": str(ctx.session_id),
                           "tenant_id": ctx.tenant_id,
                           "sandbox_id": str(ctx.sandbox_id),
                           "proxy_instance_id": self._proxy_instance_id,
                           "action_type": match.action_type})
        try:
            self._notify_approval_requested(approval_id, ctx, match)
        except Exception as e:
            logger.warning("approval.notify_failed",
                           extra={"approval_id": str(approval_id), "error": str(e)})
        return approval_id

    async def _await_decision(self, approval_id: UUID, ctx) -> ApprovalDecision:
        """Heartbeat + BLPOP + timeout/cancel cleanup. Returns the
        recorded ApprovalDecision (APPROVED / REJECTED / EXPIRED)."""
        self._proxy_inflight.add(approval_id)
        heartbeat = asyncio.create_task(self._heartbeat_loop(approval_id))
        try:
            decision_str = await approval_cache.wait_for_decision(
                approval_id, WAIT_TIMEOUT_S, self._cache,
            )
            if decision_str is not None:
                logger.info("gate.wake_received",
                            extra={"approval_id": str(approval_id),
                                   "decision": decision_str})
                return ApprovalDecision(decision_str)
            # Timeout — race-safe via the conditional UPDATE.
            return self._claim_expired_or_read(approval_id)
        except asyncio.CancelledError:
            # Sandbox-side socket closed. Same cleanup as timeout.
            self._claim_expired_or_read(approval_id)
            raise
        finally:
            heartbeat.cancel()
            try:
                await heartbeat  # let cancellation settle before release
            except (asyncio.CancelledError, Exception):
                pass
            try:
                approval_cache.release_liveness(approval_id, self._cache)
            except CACHE_TRANSIENT_ERRORS:
                pass
            self._proxy_inflight.discard(approval_id)

    def _claim_expired_or_read(self, approval_id: UUID) -> ApprovalDecision:
        """Try the conditional UPDATE to claim EXPIRED. If we lose
        (someone already decided), re-read the row and return the
        winner's decision so the addon forwards/rejects correctly."""
        with self._db() as db:
            row = action_approval.record_decision(
                db, approval_id=approval_id, decision=ApprovalDecision.EXPIRED,
            )
            if row is None:
                row = action_approval.get_action_approval(db, approval_id)
            db.commit()
        return row.decision

    async def _heartbeat_loop(self, approval_id: UUID):
        try:
            while True:
                await asyncio.sleep(approval_cache.HEARTBEAT_INTERVAL_S)
                approval_cache.publish_liveness(
                    approval_id, self._proxy_instance_id, self._cache,
                )
        except asyncio.CancelledError:
            return

    def _apply_decision_to_flow(self, flow, decision: ApprovalDecision):
        if decision == ApprovalDecision.APPROVED:
            return  # forward upstream
        code = "user_rejected" if decision == ApprovalDecision.REJECTED else "not_authorized"
        flow.response = _http_403(code)
```

**Sandbox-facing 403 enum.** The proxy's 403 body is a separate
protocol from `OnyxError`. Lock the enum:
`unidentified_sandbox | body_too_large | user_rejected | not_authorized | policy_denied` (Phase 4 adds the last). Matcher exceptions do not produce 403s — they fail open per T2.6.

**SIGTERM drain.** On SIGTERM the proxy flips the readiness probe
and iterates `self._proxy_inflight`. For each `approval_id`:

1. Run the same `_claim_expired_or_read` path. If we **won** the
   claim, the row is now EXPIRED — log `gate.drain_expired` and
   move on; the in-flight flow will see the 403.
2. If we **lost** the claim (API already wrote APPROVED / REJECTED),
   read back the row and **forward / reject the upstream call
   inline before exiting** (log `gate.drain_forwarded`). Dropping
   the connection without forwarding an already-APPROVED upstream
   call would mean the audit log says APPROVED for an action that
   never happened.

Use the same `_apply_decision_to_flow` helper so the drain path
matches the normal path.

SDK-bypass detection (logging mitmproxy TLS handshake failures as a
canary for agents trying to bypass our CA) belongs in Phase 1's
pass-through addon, not in the gate addon.

**Hard proxy crash (kill -9, OOM).** The refresh loop dies with the
process; the liveness key in Redis lapses within `LIVENESS_TTL_S`
(60s); `is_live` flips false for any chat client polling that
approval. The DB row sits with `decision IS NULL` and is visible
in the admin audit view via a `decision IS NULL` filter.

### T2.8 — Notification type

Add `APPROVAL_REQUESTED` to `NotificationType` in
`backend/onyx/configs/constants.py`. Dispatch from the gate addon's
`_notify_approval_requested` helper mirrors
`scheduled_tasks/executor.py:394-403`. Notification body:
`{approval_id, session_id, action_type}` — enough for the popover
to render a one-line preview and deep-link to the session. The full
payload lives on the `BuildMessage`, fetched when the chat loads.

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

**Structured logging is not deferred.** Every state transition in the
gate addon and the API handler must emit one log line. Lines use the
existing `setup_logger()` pattern from
`scheduled_tasks/executor.py`. Each line carries the same `extra`
fields where applicable: `approval_id, session_id, tenant_id, sandbox_id, proxy_instance_id, action_type`.

Required log lines:

- Gate addon: `gate.match`, `gate.row_committed`, `gate.wake_received`,
`gate.wake_timeout`, `gate.expired_on_timeout`, `gate.drain_expired`,
`gate.drain_forwarded`, `gate.matcher_error`.
- API handler: `approval.decision_recorded`,
`approval.decision_conflict`, `approval.cache_signal_failed`,
`approval.notify_failed`.

**PII rule.** Never log `payload` — it contains user content (Slack
message bodies, etc.). Log `action_type` only. The notification body
likewise carries only `action_type` and ID fields; popovers render a
label from `action_type` client-side.

**One-query lifecycle.** Documented in the runbook:

```
grep "approval_id=<UUID>" backend/log/sandbox_proxy_debug.log backend/log/api_server_debug.log | sort
```

**Constants** (module-level, not env-var-tunable). All in the module
that owns the behavior — no `configs/app_configs.py` indirection.
Promote to env vars if a real ops-tuning need ever surfaces.

| Constant                       | Value     | Lives in                |
| ------------------------------ | --------- | ----------------------- |
| `WAIT_TIMEOUT_S`               | 180       | `addons/gate.py`        |
| `PARSER_MAX_BODY_BYTES`        | 1_048_576 | `addons/gate.py`        |
| `IS_LIVE_CACHE_TTL_S`          | 5         | `approvals/api.py`      |
| `LIVENESS_TTL_S`               | 60        | `approval_cache.py`     |
| `HEARTBEAT_INTERVAL_S`         | 15        | `approval_cache.py`     |
| `WAKE_TTL_S`                   | 30        | `approval_cache.py`     |

The `approval_cache.py` trio is a coupled set (TTL = 4× heartbeat).


**Metrics deferred.** Leave no-op or commented hooks where counters /
histograms will land. Likely candidates:

- Counters: `approvals_created`, `approved`, `rejected`, `expired`,
`silent_allowed`, `denied`, `matcher_error`.
- Histograms: `approval_decision_latency_seconds`,
`blpop_wait_seconds`.

## Testing

For test-tier conventions see CLAUDE.md. TTL constants are
monkey-patched to <1s in tests where wall-clock waits would otherwise
poison CI.

External-dependency-unit (real Postgres + Redis):

- **Create flow.** Gate addon's `_create_request` writes the
`approval` row + `approval_request` `BuildMessage` in one
transaction; liveness key exists in Redis afterwards.
- **Decision APPROVED / REJECTED.** Decision API writes the row,
retracts the liveness key, and delivers the wakeup to a waiting
`wait_for_decision`.
- **Idempotent double-click.** Two sequential POSTs with the same
decision: both 200, identical `ApprovalView`. Two POSTs with
conflicting decisions: first 200, second `CONFLICT`.
- **Concurrent decisions.** Two threaded TestClient POSTs against
the same approval_id with the same decision: both 200; different
decisions: one 200, one CONFLICT. Verifies the `WHERE decision IS NULL` arbiter via the HTTP path.
- **NOT_FOUND.** POST to a random UUID → 404. POST as a non-owner
→ 404 (existence not leaked).
- **Matcher exception defaults open.** Patch the matcher to raise;
  assert the request is forwarded unchanged, no DB / liveness side
  effects, and `gate.matcher_error` is logged.
- **Body size cap.** Send a request body > `PARSER_MAX_BODY_BYTES`;
assert 403 `body_too_large` without invoking the parser.
- **Liveness TTL alone writes nothing.** Patch `LIVENESS_TTL_S` to
0.5s; let it lapse; assert the row stays `decision IS NULL`.
- **Heartbeat refreshes.** Patch `HEARTBEAT_INTERVAL_S` to 0.1s,
wait 0.5s, assert ≥3 `publish_liveness` calls observed.
- **SIGTERM drain — claim path.** Drive `_create_request`, populate
`_proxy_inflight`, invoke the drain coroutine directly (not a
real SIGTERM in tests); assert each row reaches `EXPIRED` and
`gate.drain_expired` was logged.
- **SIGTERM drain — read-back-and-forward path.** Drive
`_create_request`, commit `APPROVED` via the API while the addon
is still in `_proxy_inflight`, invoke the drain coroutine; assert
the row stays `APPROVED` and `_apply_decision_to_flow` ran with
APPROVED.
- **CancelledError path.** Cancel the addon task mid-wait; assert
the row is `EXPIRED` (or stays whatever the API wrote) and the
liveness key is released.
- **`is_live` flip.** Messages endpoint returns `is_live=true`
  while the Redis key exists; let it expire (patched TTL) and the
  same endpoint returns `is_live=false`.
- **`is_live` decision-wins.** Row has `decision != NULL` and key
  still in Redis → endpoint returns `is_live=false`.
- **`is_live` 5s cache staleness.** Patch cache TTL to ~0.5s,
  delete the key, assert stale `true` returned within window then
  `false` after.
- **Orphan visibility.** After a hard "crash" (cancel the heartbeat
  without going through drain), the row remains queryable via
  `list_session_action_approvals(decision=None)` with `decision IS NULL`.
- **Lost wakeup recovery.** Patch `signal_decision` to no-op; the
proxy's `wait_for_decision` times out, reads the row, and
forwards / rejects per the recorded decision.
- **Cache signal failure swallowed.** Patch `release_liveness` and
`signal_decision` to raise `CACHE_TRANSIENT_ERRORS`; assert the
API still returns 200 and the DB row is updated. Assert
`approval.cache_signal_failed` warning logged.
- **Notification dispatch failure swallowed.** Patch
`_notify_approval_requested` to raise; assert the row is still
committed and `approval.notify_failed` warning is logged.
- **Silent decision.** `insert_silent_action_approval(APPROVED)`
writes one row with no liveness key and no `BuildMessage`.
`insert_silent_action_approval(EXPIRED)` raises (asserted).
- **`max(turn_index)` race.** With a fresh session, spawn two
  threads that simultaneously call (a) the agent stream's message
  insert and (b) `insert_action_approval_request_build_message`;
  assert no `turn_index` collision and message order is
  deterministic. Verifies the `SELECT FOR UPDATE` serialisation.
- **PII not in logs.** Run a create flow with sentinel content in
  `payload`; assert no log line contains it.

Integration (full stack):

- Trigger a gated request from a stand-in sandbox through the real
proxy + Redis + DB; POST a decision via the API; assert the
upstream outcome and that the chat card disappears within polling
cadence (≤15s).
- **Cron-driven session** (functional requirement #2 in the parent):
a scheduled task prompts an existing session, that session
triggers a gated request, the same approval flow runs; verify the
`APPROVAL_REQUESTED` notification fires and the audit query
returns the row.

Smoke (runbook item, not automated): real Slack send through real
proxy in staging with manual approve / reject.

## Dependencies

- Phase 1 complete.
- External Apps' app-level matcher (`_find_enabled_app_for_url`) from
`dane/ea-craft-5`, or the temporary Protocol-conformant fallback.
- **Redis-backed `CacheBackend`.** Required, not optional. The proxy
and API use the existing surface only: `set` / `delete` / `exists` /
`rpush` / `blpop` / `expire`. Local dev runs Redis already.

## Open during phase

- Whether `is_live` polling should move to SSE / WebSocket push in
Phase 3 to avoid the polling lag. Phase 2 ships polling.

## Definition of done

- Schema is the single `action_approval` table with nullable
  `decision`; `ApprovalDecision` enum is APPROVED / REJECTED /
  EXPIRED (pending is `decision IS NULL`).
- Liveness lifecycle works: published on row insert and refreshed
  every 15s while waiting (TTL 60s); released on decision / timeout
  / cancel / SIGTERM drain.
- `POST /approvals/{id}/decision` race-safe via the conditional
  `WHERE decision IS NULL` UPDATE; double-clicks idempotent;
  conflicting decisions return CONFLICT; non-owner returns 404.
- Card disappears within polling cadence (≤15s) of a recorded
  decision; the agent's next message is the only post-decision
  artifact in the chat.
- `GET /api/build/sessions/{id}/messages` returns `is_live` per
  approval card; flips false when key expires or decision lands.
- Audit table holds every decision class (silent allow / deny,
  interactive approve / reject, expired, orphan). Both
  `list_session_action_approvals` and
  `list_tenant_action_approvals` work.
- `max(turn_index)` race covered by `SELECT FOR UPDATE` on the
  parent `build_session`; verified by a concurrent-write test.
- SIGTERM drain: rows the proxy owns reach EXPIRED; rows the API
  already decided are forwarded / rejected inline before exit.
- Oversized bodies reject with 403; matcher exceptions default
  open (T2.6).
- Structured logs at every state transition; no PII (`payload`)
  in any log line.
- `APPROVAL_REQUESTED` notification dispatch verified end-to-end;
  body is `{approval_id, session_id, action_type}` — no PII.
- Cron-driven session integration test green.
- Bash-tool default verified / raised per T2.9.

