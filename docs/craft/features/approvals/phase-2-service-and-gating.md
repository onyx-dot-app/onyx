# Phase 2 — Approval Service & Gate Wiring (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 1.

## Goal

Two halves shipped together:

1. **Approval Service** — backend module that records approvals, evaluates
   them (org-default policy in this phase; full policy management in
   Phase 4), and exposes a decision API.
2. **Gate wiring** — proxy stops being pass-through. When a request matches
   a gated action, the proxy calls the service, blocks until the decision
   lands (or 180s timeout), and forwards / rejects accordingly.

At the end of Phase 2, gated external-app requests work end-to-end. Users
decide via the notification deep link (Phase 3 lands the inline chat
surface).

## Module layout

Backend:

```
backend/onyx/server/features/build/approvals/
├── api.py                 # FastAPI router; user-facing decision + audit
├── service.py             # create / respond / await_decision
└── exceptions.py          # OnyxError subclasses if needed
```

DB:

```
backend/onyx/db/approval.py            # query module
backend/onyx/db/models.py              # ApprovalRequest ORM (additions)
backend/onyx/db/enums.py               # ApprovalStatus (additions)
backend/alembic/versions/XXXX_create_approval_request.py
```

Proxy:

```
backend/onyx/sandbox_proxy/cache.py             # Redis BLPOP/RPUSH wrapper
backend/onyx/sandbox_proxy/addons/gate.py       # the gating addon
backend/onyx/sandbox_proxy/parsers/             # consume registry from External Apps
```

Constants / notifications:

```
backend/onyx/configs/constants.py      # NotificationType.APPROVAL_REQUESTED
```

Sandbox image:

```
backend/onyx/server/features/build/sandbox/kubernetes/docker/
  # verify + raise bash-tool default timeout
  # update agent system prompt
```

## Tasks

### T2.1 — Data model + migration

`ApprovalRequest` ORM in `db/models.py`:

```python
class ApprovalRequest(Base):
    __tablename__ = "approval_request"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("build_session.id"), index=True, nullable=False
    )
    requesting_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus), nullable=False,
        default=ApprovalStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    decided_at: Mapped[datetime | None]
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"))
```

`ApprovalStatus` in `db/enums.py`:

```python
class ApprovalStatus(str, PyEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"  # timed out without user action

    def is_terminal(self) -> bool:
        return self != ApprovalStatus.pending
```

Manual Alembic migration; mirror `scheduled_task` migration patterns.
Index on `(session_id, status)` for the pending-list query.

### T2.2 — DB query module

`backend/onyx/db/approval.py`:

```python
def insert_approval(db: Session, *, session_id, requesting_user_id,
                    kind, summary, payload) -> ApprovalRequest: ...

def get_approval(db: Session, approval_id: UUID) -> ApprovalRequest: ...

def mark_approval_status(db: Session, approval_id: UUID,
                         status: ApprovalStatus,
                         decided_by: UUID | None) -> None: ...

def list_pending_approvals(db: Session, session_id: UUID) -> list[ApprovalRequest]: ...
```

Follow `__no_commit` conventions used by `scheduled_task.py`.

### T2.3 — Service module

`backend/onyx/server/features/build/approvals/service.py`:

```python
def create(db: Session, *, session_id: UUID, kind: str, summary: str,
           payload: dict) -> UUID:
    """Persist the approval row, write a BuildMessage card (Phase 3
    consumer), dispatch notification. Returns approval_id."""

def respond(db: Session, *, approval_id: UUID,
            decision: Literal["approve", "reject"],
            user_id: UUID) -> None:
    """Mark the row terminal, write the resolution BuildMessage,
    rpush wakeup. Raises OnyxError(CONFLICT) if already decided.
    Raises OnyxError(NOT_FOUND) if missing."""

async def await_decision(approval_id: UUID,
                         timeout_seconds: int = 180) -> ApprovalStatus:
    """Block on Redis blpop. Returns terminal ApprovalStatus.
    On timeout: marks row expired and returns expired."""
```

Key details:
- `await_decision` re-reads the row on entry to handle the race where
  the decision lands before the blpop starts.
- On timeout, write `expired` to the row and rpush so anyone else
  waiting (shouldn't happen in v0) gets notified.
- All cache I/O via the existing `CacheBackend` interface
  (`backend/onyx/cache/interface.py`).

### T2.4 — User-facing API

`backend/onyx/server/features/build/approvals/api.py`:

```python
router = APIRouter(prefix="/approvals", dependencies=[Depends(require_basic_access)])

@router.get("/sessions/{session_id}/pending")
def list_pending(session_id: UUID, db: Session) -> list[ApprovalView]: ...

@router.post("/{approval_id}/decision")
def submit_decision(approval_id: UUID, body: DecisionBody,
                    user: User, db: Session) -> None:
    # Validate: user must own the session this approval is on.
    # Call service.respond.
    ...
```

Register on the build aggregator (`backend/onyx/server/features/build/api/api.py`).

Conventions:
- No `response_model`.
- Raise `OnyxError` only.

### T2.5 — Proxy: Redis wakeup wrapper

`sandbox_proxy/cache.py`:

```python
class WakeupChannel:
    def __init__(self, cache_backend):
        self._cache = cache_backend

    async def wait(self, approval_id: UUID,
                   timeout_seconds: int) -> str | None:
        key = f"approval:wake:{approval_id}"
        return await asyncio.to_thread(
            self._cache.blpop, key, timeout=timeout_seconds
        )

    def signal(self, approval_id: UUID, decision: str):
        key = f"approval:wake:{approval_id}"
        self._cache.rpush(key, decision, expire_seconds=30)
```

Both the proxy and `service.respond()` use the same `CacheBackend`
implementation, same key naming.

### T2.6 — Gate addon

`sandbox_proxy/addons/gate.py`:

```python
class GateAddon:
    def __init__(self, identity, registry, db_factory, wakeup,
                 timeout_seconds: int = 180):
        ...

    async def request(self, flow):
        ctx = self._identity.resolve(flow.client_conn.peername[0])
        if ctx is None:
            flow.response = http.Response.make(
                403, b'{"error":"unidentified_sandbox"}',
                {"content-type": "application/json"},
            )
            return

        match = self._registry.match(flow.request)
        if match is None:
            return  # pass-through (Phase 1 LoggingAddon still logs)

        summary, payload = match.parse(flow.request)

        with self._db() as db:
            approval_id = service.create(
                db,
                session_id=ctx.session_id,
                kind=match.kind,
                summary=summary,
                payload=payload,
            )

        try:
            decision = await self._wakeup.wait(approval_id, self._timeout)
        except asyncio.CancelledError:
            # Sandbox closed first; mark the row terminal
            with self._db() as db:
                service.mark_terminal_if_pending(db, approval_id,
                                                 ApprovalStatus.expired)
            raise

        if decision == "approve":
            return  # forward to upstream
        elif decision == "reject":
            flow.response = http.Response.make(
                403, b'{"error":"user_rejected"}',
                {"content-type": "application/json"},
            )
        else:  # timed out → expired
            flow.response = http.Response.make(
                403, b'{"error":"not_authorized"}',
                {"content-type": "application/json"},
            )
```

### T2.7 — Action registry consumption

Consume `upstream_url_patterns` from External Apps (branch `dane/ea-craft-5`):

```python
# sandbox_proxy/parsers/registry.py
class ActionMatch:
    kind: str
    parse: Callable[[Request], tuple[str, dict]]

class Registry:
    def __init__(self, sources: list[ProviderActions]): ...
    def match(self, request) -> ActionMatch | None: ...
```

The `ProviderActions` interface comes from External Apps. If the merge
slips, ship a temporary minimal registry hardcoding Slack
`chat.postMessage` and migrate to the real registry on merge — flag this
dependency in standup.

### T2.8 — Notification type

`backend/onyx/configs/constants.py`:

```python
class NotificationType(str, PyEnum):
    ...
    APPROVAL_REQUESTED = "approval_requested"
```

In `service.create()`, dispatch via the existing notification machinery
(mirror `scheduled_tasks/executor.py:394-403`). Best-effort; do not block
the create on notification failure.

### T2.9 — Bash-tool default + agent prompt

- Find opencode's bash tool timeout default. Raise to ≥240s.
- Update the agent's system prompt to mention the approval window:

  > Network requests to gated external services (Slack, Linear, Google
  > Calendar) may take up to ~3 minutes to complete because they require
  > user approval. When using the bash tool for such calls, set a generous
  > explicit timeout (≥240s).

Where exactly the system prompt lives needs verification during the
phase. Likely opencode config files in
`backend/onyx/server/features/build/sandbox/kubernetes/docker/`.

## Testing

- **External-dependency-unit** (real Postgres + Redis):
  - `service.create` → `service.await_decision` blocks → `service.respond`
    unblocks with correct decision.
  - Reject path; expire path (small timeout for test).
  - Double-respond raises `OnyxError(CONFLICT)`.
  - Sandbox-disconnect-mid-wait: simulate cancellation; assert row is
    `expired`.
- **Integration** (full stack):
  - Stand up proxy + service + DB; trigger a gated request from a stand-in
    sandbox; "user" client POSTs decision; assert outcome end-to-end.
- **Smoke**: real Slack send through real proxy in staging, with manual
  approve / reject.

## Dependencies

- Phase 1 complete.
- External Apps' `upstream_url_patterns` registry (or fallback to
  temporary hardcoded matchers).
- Existing `CacheBackend` Redis backend in production.

## Open during phase

- HTTP status code on `rejected` — 403 is reasonable, but check the
  agent's tool-result handling for any preference.
- Body shape for the 403 — propose `{"error": "user_rejected" |
  "not_authorized"}` and lock before merge.
- Whether `service.create` should also write the BuildMessage row in the
  same transaction (Phase 3 needs it). Recommend yes; Phase 3 consumes
  it without re-writing.

## Definition of done

- All four service functions covered by tests.
- `POST /build/approvals/{id}/decision` works end-to-end.
- A gated request through the proxy: creates an approval row, blocks,
  unblocks on user POST, returns 403 on reject, returns `expired` after
  180s of inaction.
- Sandbox disconnect mid-wait correctly marks row `expired`.
- `APPROVAL_REQUESTED` notification fires and surfaces to the user.
- Bash-tool default verified / raised; system prompt updated.
