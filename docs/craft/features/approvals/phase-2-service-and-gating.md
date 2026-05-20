# Phase 2 — Approval Service & Gate Wiring (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 1.

## Goal

Two halves shipped together:

1. **Approval Service.** Backend module that records approvals, evaluates
   them (org-default policy in this phase; full policy management in
   Phase 4), and exposes a decision API. Owns the `BuildMessage` writes
   for both the request card and its resolution.
2. **Gate wiring.** The proxy stops being pass-through. On a gated
   action, the proxy calls the service in-process, blocks until the
   decision lands or the wait window elapses, and forwards or rejects.

At the end of Phase 2, gated external-app requests work end-to-end. Users
decide via the notification deep link (Phase 3 lands the inline chat
surface against the rows Phase 2 already writes).

## Module layout

Backend service + API:

```
backend/onyx/server/features/build/approvals/
├── api.py                 # FastAPI router (user-facing decision + audit)
├── service.py             # create / respond / await_decision / record_silent_decision
└── exceptions.py          # OnyxError subclasses if needed
```

DB:

```
backend/onyx/db/approval.py            # query module
backend/onyx/db/models.py              # ApprovalRequest ORM (additions)
backend/onyx/db/enums.py               # ApprovalStatus (additions)
backend/alembic/versions/XXXX_create_approval_request.py
```

Proxy (the proxy image bundles the backend module tree; no HTTP between
proxy and api-server, all in-process Python imports):

```
backend/onyx/sandbox_proxy/cache.py             # blocking-wakeup wrapper around CacheBackend
backend/onyx/sandbox_proxy/addons/gate.py       # the gating addon
backend/onyx/sandbox_proxy/parsers/             # per-provider body inspection → action kind
```

Constants / notifications / background:

```
backend/onyx/configs/constants.py                          # NotificationType.APPROVAL_REQUESTED
backend/onyx/background/celery/tasks/approvals/sweeper.py  # expire stale rows
```

Sandbox image (verify only):

```
backend/onyx/server/features/build/sandbox/...   # verify bash-tool timeout; update agent prompt
```

## Tasks

### T2.1 — Data model + migration

`ApprovalRequest` (in `db/models.py`) columns: `id (UUID, PK)`,
`session_id (FK build_session, indexed)`,
`requesting_user_id (FK user)`,
`kind (str)`, `summary (str)`, `payload (JSONB)`,
`status (ApprovalStatus, default PENDING)`,
`created_at (timezone-aware, server_default=func.now())`,
`decided_at (timezone-aware, nullable)`,
`decided_by (FK user, nullable)`.
Index: `(session_id, status)` for the pending-list query, and
`(status, created_at)` for the sweeper.

`ApprovalStatus` in `db/enums.py` follows the `ScheduledTaskRunStatus`
convention (UPPERCASE values):

```python
class ApprovalStatus(str, PyEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    def is_terminal(self) -> bool:
        return self != ApprovalStatus.PENDING
```

Manual Alembic migration; mirror `scheduled_task` migration patterns.

### T2.2 — DB query module

`backend/onyx/db/approval.py`, all writes `__no_commit` (mirroring
`scheduled_task.py` and `external_app.py`):

```python
def insert_approval__no_commit(db, *, session_id, requesting_user_id,
                               kind, summary, payload,
                               status=ApprovalStatus.PENDING,
                               decided_by=None) -> ApprovalRequest: ...

def get_approval(db, approval_id) -> ApprovalRequest | None: ...

def transition_to_terminal_if_pending__no_commit(
    db, *, approval_id, new_status, decided_by
) -> ApprovalRequest | None:
    """Conditional UPDATE ... WHERE status='PENDING' RETURNING *.
    Returns None if no row was updated (already terminal or missing)."""

def list_pending_approvals(db, session_id) -> list[ApprovalRequest]: ...

def list_approvals(db, session_id, *, status=None,
                   from_dt=None, to_dt=None) -> list[ApprovalRequest]: ...

def list_stale_pending_approvals(db, older_than) -> list[ApprovalRequest]: ...
```

### T2.3 — Service module

`backend/onyx/server/features/build/approvals/service.py`.

`create(db, *, session_id, tenant_id, requesting_user_id, kind, summary, payload) -> UUID`

`tenant_id` is carried through from `SessionContext.tenant_id` (Phase
1) so the cache key and any tenant-scoped audit query can use it
without re-deriving from the DB.

In one DB transaction:

1. Insert the `ApprovalRequest` row (`status=PENDING`).
2. Look up the current `max(turn_index)` for the session's `BuildMessage`
   rows — the approval card lives in the agent's current turn — and
   insert a `BuildMessage` (`type=MessageType.ASSISTANT`, `turn_index=<that
   max>`, `message_metadata={"type": "approval_request", "approval_id":
   ..., "kind": ..., "summary": ..., "payload": ..., "status": "pending"}`).
3. Commit, then best-effort dispatch the `APPROVAL_REQUESTED`
   notification (failure must not roll back the row). Document the
   best-effort posture; Phase 3 adds a polling fallback for active
   sessions so a dropped notification doesn't strand the user.

`respond(db, *, approval_id, decision, user_id) -> None`

Race-safe single-shot terminal write:

```sql
UPDATE approval_request
SET status = :new_status, decided_at = now(), decided_by = :user
WHERE id = :id AND status = 'PENDING'
RETURNING session_id, kind;
```

Implemented via `approval.transition_to_terminal_if_pending__no_commit`
(T2.2): if it returns `None`, raise `OnyxError(CONFLICT)`. Otherwise,
in the same transaction, insert the resolution `BuildMessage`
(`MessageType.ASSISTANT`, `message_metadata={"type":
"approval_resolved", "approval_id": ..., "decision": ...,
"decided_by": ...}` at the current max `turn_index`). After commit,
`rpush` the wakeup signal with the decision string (one of
`"approve"` / `"reject"` — see T2.5 for the wire format).

`await_decision(db_factory, wakeup, approval_id, timeout_seconds) -> ApprovalStatus`

Block on `wakeup.wait`. Critically, **re-read the row on entry**
before calling wait — otherwise a decision that lands between
`service.create` returning and the addon entering `wait()` would be
silently missed. On wakeup, re-read the row and return its status.
On `None` (timeout), return whatever status is on the row at that
point (the sweeper or another caller may already have marked it
`EXPIRED`).

The gate addon (T2.8) calls `await_decision` rather than reaching
into the wakeup wrapper directly, so the race-safe entry-time re-read
isn't duplicated at every call site.

`record_silent_decision(db, *, session_id, requesting_user_id, kind,
summary, payload, decision)` — for Phase 4's policy evaluator. Inserts
an `ApprovalRequest` row with terminal status (`APPROVED` or `REJECTED`)
and the matching resolution `BuildMessage` in one transaction. No
notification, no wakeup. This keeps a single audit table backing one
query for every decision type (silent allow, deny, interactive,
expired).

All cache I/O via the existing `CacheBackend` interface
(`backend/onyx/cache/interface.py`).

### T2.4 — User-facing API

`backend/onyx/server/features/build/approvals/api.py`:

```python
router = APIRouter(
    prefix="/approvals",
    dependencies=[Depends(require_permission(Permission.BASIC_ACCESS))],
)

@router.get("/sessions/{session_id}/pending")
def list_pending(session_id, db, user) -> list[ApprovalView]: ...

@router.get("/sessions/{session_id}")
def list_session_approvals(
    session_id,
    status: ApprovalStatus | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    db, user,
) -> list[ApprovalView]:
    """Audit query — functional requirement #5 in the parent."""

@router.post("/{approval_id}/decision")
def submit_decision(approval_id, body: DecisionBody, user, db) -> None:
    # validate user owns the session, then service.respond(...)
    ...
```

Register on `backend/onyx/server/features/build/api/api.py`. No
`response_model`. Raise `OnyxError` only.

### T2.5 — Proxy: wakeup wrapper

`sandbox_proxy/cache.py` wraps the existing `CacheBackend`:

```python
class WakeupChannel:
    def __init__(self, cache_backend, ttl_seconds: int = 30):
        self._cache = cache_backend
        self._ttl = ttl_seconds

    async def wait(self, approval_id, timeout_seconds: int) -> str | None:
        key = f"approval:wake:{approval_id}"
        result = await asyncio.to_thread(
            self._cache.blpop, [key], timeout_seconds
        )
        if result is None:
            return None
        _key_bytes, value_bytes = result
        return value_bytes.decode()

    def signal(self, approval_id, decision: str) -> None:
        key = f"approval:wake:{approval_id}"
        self._cache.rpush(key, decision)
        self._cache.expire(key, self._ttl)
```

Both the proxy and `service.respond` use the same `CacheBackend`
implementation and same key naming.

### T2.6 — Sweeper task

mitmproxy's `CancelledError` on TCP close is not reliable enough to be
the sole expiration path. A Celery periodic task in
`backend/onyx/background/celery/tasks/approvals/sweeper.py` owns
expiration:

```sql
-- runs every ~30s
UPDATE approval_request
SET status = 'EXPIRED', decided_at = now()
WHERE status = 'PENDING' AND created_at < now() - interval '5 minutes'
RETURNING id, session_id;
```

For each expired row, insert an `approval_resolved` `BuildMessage`
(`decision: "expired"`). All in one task call, batched per row. Schedule
via the existing beat schedule pattern; supply `expires=` on enqueue.

This is the safety net for the sandbox-disconnect path: even if the
proxy coroutine vanishes silently, the row reaches a terminal state.

**Hard proxy crash (OOM, kill) consequence.** If the proxy process
itself dies, the gate addon's `CancelledError` handler never runs and
the sandbox-side TCP socket drops with RST. The row sits `PENDING`
until the sweeper picks it up at the 5-minute threshold. During that
window, a user can still POST a decision — `respond()` succeeds and
writes the resolution `BuildMessage`, but there's no addon listening,
the sandbox's HTTP call already failed, and the upstream API was
never hit. The audit row will say "approved" or "rejected" for a
request that never went through. Phase 1's two-replica deploy makes
this rare (in-flight flows on the surviving replica continue); the
sweeper window bounds the worst-case staleness.

### T2.7 — Action-kind matching

Two layers:

1. **App-level (External Apps).** `_find_enabled_app_for_url(url)` from
   `dane/ea-craft-5` tells us "this URL belongs to Slack." Sole source
   of truth for URL → app.
2. **Action-kind (this project).** Per-provider modules in
   `sandbox_proxy/parsers/` inspect the request body of URLs already
   matched to a provider and emit an action kind plus a summary +
   payload for the card. The action-kind registry is owned here, not in
   External Apps.

```python
# sandbox_proxy/parsers/base.py
class ActionMatch:
    kind: str          # e.g. "slack.send_message"
    summary: str
    payload: dict

class Parser(Protocol):
    def match(self, request) -> ActionMatch | None: ...

# sandbox_proxy/parsers/slack.py
class SlackParser:
    def match(self, request) -> ActionMatch | None:
        # request body inspection: chat.postMessage → slack.send_message
        ...
```

The gate addon composes: External Apps app lookup, then dispatch to the
matching parser, then `service.create`.

**Interface contract for the External Apps dependency.** If
`dane/ea-craft-5` is unmerged at implementation time, define the
`AppMatcher` Protocol that the proxy expects and ship a temporary
implementation that hardcodes Slack `chat.postMessage`. Both
implementations conform to the same Protocol so the swap is
mechanical:

```python
class App(Protocol):
    app_type: str   # e.g. "slack", keys into parsers dict

class AppMatcher(Protocol):
    def find(self, url: str) -> App | None: ...
```

### T2.8 — Gate addon

```python
class GateAddon:
    def __init__(self, identity, app_matcher, parsers, db_factory,
                 wakeup, timeout_seconds: int = 180):
        ...

    async def request(self, flow):
        ctx = self._identity.resolve(flow.client_conn.peername[0])
        if ctx is None:
            flow.response = http.Response.make(
                403, b'{"error":"unidentified_sandbox"}',
                {"content-type": "application/json"},
            )
            return

        app = self._app_matcher.find(flow.request.url)
        if app is None:
            return
        parser = self._parsers.get(app.app_type)
        if parser is None:
            return
        match = parser.match(flow.request)
        if match is None:
            return

        with self._db() as db:
            approval_id = service.create(
                db,
                session_id=ctx.session_id,
                tenant_id=ctx.tenant_id,
                requesting_user_id=ctx.user_id,
                kind=match.kind,
                summary=match.summary,
                payload=match.payload,
            )

        try:
            status = await service.await_decision(
                self._db, self._wakeup, approval_id, self._timeout,
            )
        except asyncio.CancelledError:
            # Best-effort terminal mark; sweeper is the real safety net.
            with self._db() as db:
                approval.transition_to_terminal_if_pending__no_commit(
                    db, approval_id=approval_id,
                    new_status=ApprovalStatus.EXPIRED, decided_by=None,
                )
                db.commit()
            raise

        if status == ApprovalStatus.APPROVED:
            return
        if status == ApprovalStatus.REJECTED:
            flow.response = http.Response.make(
                403, b'{"error":"user_rejected"}',
                {"content-type": "application/json"},
            )
            return
        # PENDING (timed out before sweeper updated) or EXPIRED.
        flow.response = http.Response.make(
            403, b'{"error":"not_authorized"}',
            {"content-type": "application/json"},
        )
```

SDK-bypass detection (logging mitmproxy TLS handshake failures as a
canary for agents trying to bypass our CA) belongs in Phase 1's
pass-through addon, not in the gate addon — it's a proxy-core concern
that wants to fire even before gating is enabled.

### T2.9 — Notification type

Add `APPROVAL_REQUESTED` to `NotificationType` in
`backend/onyx/configs/constants.py`. Dispatch from `service.create`
mirrors `scheduled_tasks/executor.py:394-403`. Notification body:
`{approval_id, session_id, kind, summary}` — enough for the popover
to render a one-line preview and deep-link to the session. The full
payload lives on the `BuildMessage`, fetched when the chat loads.

`require_permission` lives in `onyx.auth.permissions`; `Permission`
lives in `onyx.db.enums`.

### T2.10 — Bash-tool timeout (verify-and-document)

The `backend/onyx/server/features/build/sandbox/opencode/` directory
ships empty in this repo: opencode is consumed as a binary/image we
don't control. If our deployment owns opencode config, raise the bash
tool default timeout to ≥240s and update the agent system prompt to
mention the approval window. If opencode is an external binary,
document the limitation and rely on the agent-prompt nudge alone (the
agent can still set explicit per-call timeouts on `curl`-style
requests).

### T2.11 — Observability (deferred)

Metrics are deferred for the initial dev-only implementation, matching
Phase 1. The hooks (where counters/histograms would be incremented in
the service and the addon) should be left as comments or no-op calls so
the wiring is in place when we want to add a real metrics surface.
Likely candidates when we get there: `approvals_created` / `approved`
/ `rejected` / `expired` / `silent_allowed` / `denied` counters,
`approval_decision_latency_seconds` histogram, and a `blpop_wait`
histogram on the proxy side.

## Testing

- **External-dependency-unit** (real Postgres + Redis):
  - `create` → `await_decision` blocks → `respond` unblocks with correct
    decision, and both `BuildMessage` rows land in the same transactions.
  - Reject path.
  - Sweeper expires stale `PENDING` rows and writes the resolved
    `BuildMessage`.
  - Concurrent `respond` calls: exactly one succeeds, the other gets
    `OnyxError(CONFLICT)`. Verifies the race-safe conditional UPDATE.
  - `record_silent_decision` writes both rows in one transaction.
  - Sandbox-disconnect-mid-wait: simulate `CancelledError` and assert
    the row reaches `EXPIRED` (via the addon path or the sweeper).
- **Integration** (full stack):
  - Stand up proxy + service + DB; trigger a gated request from a
    stand-in sandbox; "user" client POSTs decision; assert outcome
    end-to-end.
  - **Cron-driven session test** (functional requirement #2 in the
    parent): a scheduled task prompts an existing session, that session
    triggers a gated request, the same approval flow runs. Verify the
    `APPROVAL_REQUESTED` notification surfaces and the audit query
    returns the row.
- **Smoke**: real Slack send through real proxy in staging, with manual
  approve / reject.

## Dependencies

- Phase 1 complete.
- External Apps' app-level matcher (`_find_enabled_app_for_url`) from
  `dane/ea-craft-5`, or the temporary Protocol-conformant fallback.
- **`CacheBackend` with BLPOP.** Redis is the production backend. The
  Postgres `CacheBackend.blpop` (`backend/onyx/cache/postgres_backend.py:257`)
  is a polling fallback with `_BLPOP_POLL_INTERVAL` latency — it works
  but adds per-poll DB load. Acceptable for local dev / single-tenant
  testing; Redis required for any non-trivial deployment.

## Open during phase

- HTTP status code on `rejected` — 403 is reasonable, but check the
  agent's tool-result handling for any preference.
- Body shape for the 403 — propose `{"error": "user_rejected" |
  "not_authorized"}` and lock before merge.

## Definition of done

- All four service functions (`create`, `respond`, `await_decision`,
  `record_silent_decision`) covered by tests.
- `POST /build/approvals/{id}/decision` and the audit `GET` work
  end-to-end.
- A gated request through the proxy: creates an approval row + the
  request `BuildMessage`, blocks, unblocks on user POST, writes the
  resolved `BuildMessage`, returns 403 on reject, returns
  `not_authorized` after the wait window.
- Concurrent POSTs to the decision endpoint resolve race-safely: one
  wins, the other gets CONFLICT.
- The audit table holds every decision type — silent allow, deny,
  interactive approve/reject, expired — and the audit query returns
  them.
- Sweeper task verified: a `PENDING` row past the threshold reaches
  `EXPIRED` and produces the resolved `BuildMessage`.
- `APPROVAL_REQUESTED` notification dispatch verified end-to-end.
- Cron-driven session integration test green.
- Metrics hooks present (no-op or commented) so a real metrics surface
  can be added without code-shape changes later.
- Bash-tool default verified / raised; system prompt updated (or
  limitation documented, per T2.10).
