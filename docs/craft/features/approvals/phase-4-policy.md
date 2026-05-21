# Phase 4 — Policy Management (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on the Phase 2 data layer (`action_approval` table, gate
addon, decision API) and is realistic to use once Phase 3 surfaces
approvals in chat.

## Goal

Replace the implicit "every gated action requires approval" behavior
with a real policy layer:

- **Developers** declare gated actions in code (action_type, name,
  description, default policy) alongside the parser that matches them
  on the wire.
- **Admins** override per-action policy at the tenant level via a
  settings UI (`require_approval` / `deny` / `always_allow`), and can
  view a tenant-scoped audit log of recent approvals.

The schema accepts a future per-user override layer with no DDL
changes — v0 ships admin-only.

## Module layout

```
backend/onyx/sandbox_proxy/parsers/
├── slack.py                     # parser + GatedAction declarations
├── linear.py
├── gcal.py
└── ...                          # one module per provider; imported at proxy startup

backend/onyx/sandbox_proxy/
└── action_matcher.py            # registry-backed ActionMatcher impl + Protocol

backend/onyx/server/features/build/approvals/
├── api.py                       # (Phase 2) decision + live + per-session audit
└── policy_api.py                # admin policy CRUD + tenant audit endpoints

backend/onyx/server/features/build/db/
├── action_approval.py           # (Phase 2) + insert_silent_action_approval +
│                                # list_tenant_action_approvals
└── approval_policy.py           # queries for TenantActionPolicy

backend/onyx/db/
├── models.py                    # TenantActionPolicy (additions)
└── enums.py                     # PolicyDecision (additions)

backend/alembic/versions/YYYY_create_tenant_action_policy.py

web/src/app/admin/approvals/
├── ApprovalSettingsPage.tsx
├── ActionPolicyRow.tsx
└── ApprovalAuditPage.tsx
```

## Tasks

### T4.1 — Parser-owned action declarations

Each parser both matches requests on the wire and declares the
`GatedAction`s it produces. Registration is explicit, matching the
`BuiltinSkillRegistry` pattern (`backend/onyx/skills/registry.py`):
parser modules call `gated_action_registry.register(...)` at module
top level, and `policy.py` imports the parser modules once at startup
to trigger the registrations.

```python
# backend/onyx/sandbox_proxy/parsers/slack.py

@dataclass(frozen=True)
class GatedAction:
    action_type: str             # "slack.send_message"
    name: str                    # "Send Slack message"
    description: str             # "Posts a message to a Slack channel"
    default_policy: PolicyDecision = PolicyDecision.require_approval

SEND_MESSAGE = GatedAction(
    action_type="slack.send_message",
    name="Send Slack message",
    description="Posts a message to a Slack channel.",
)
gated_action_registry.register(SEND_MESSAGE)

def match(request: http.Request) -> ActionMatch | None: ...
```

The proxy and the admin API consume the same registry singleton.

### T4.2 — Action-type taxonomy lock

Lock the action_type namespace convention: `<provider>.<verb_resource>`
— e.g. `slack.send_message`, `linear.create_issue`,
`gcal.create_event`. Document it at the top of
`sandbox_proxy/parsers/` (module docstring is sufficient; promote to
an ADR if it ever becomes contentious).

### T4.3 — Registry-backed `ActionMatcher`

`ActionMatcher` is a `Protocol` consumed by `GateAddon`
(`backend/onyx/sandbox_proxy/action_matcher.py`):

```python
class ActionMatcher(Protocol):
    def match(self, request: http.Request) -> ActionMatch | None: ...
```

`GateAddon.__init__` takes `action_matcher: ActionMatcher` as a
constructor arg, so swapping the implementation needs no other gate
changes. Phase 4 ships a registry-backed implementation that walks
the parser modules' `match` functions, returning the first
`ActionMatch` or `None`:

```python
class RegistryActionMatcher:
    def __init__(self, parsers: Sequence[ParserModule]) -> None:
        self._parsers = parsers

    def match(self, request: http.Request) -> ActionMatch | None:
        for parser in self._parsers:
            hit = parser.match(request)
            if hit is not None:
                return hit
        return None
```

Wiring at proxy startup constructs this with the imported parser
modules and passes it into `GateAddon(...)`.

### T4.4 — DB: tenant policy storage

`PolicyDecision` enum in `db/enums.py`:

```python
class PolicyDecision(str, PyEnum):
    require_approval = "require_approval"
    deny = "deny"
    always_allow = "always_allow"
```

`TenantActionPolicy` ORM in `db/models.py`:

```python
class TenantActionPolicy(Base):
    __tablename__ = "tenant_action_policy"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[PolicyDecision] = mapped_column(
        Enum(PolicyDecision), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"))

    __table_args__ = (UniqueConstraint("tenant_id", "action_type"),)
```

A future `user_action_policy` table with
`(tenant_id, user_id, action_type)` layers above this with no DDL
changes here.

Manual Alembic migration; follow existing per-tenant settings patterns
(see `ee/onyx/server/enterprise_settings/`).

Queries live in
`backend/onyx/server/features/build/db/approval_policy.py`
(`get`, `upsert`, `delete`, `list_for_tenant`), mirroring
`action_approval.py`'s convention: each function flushes so the
caller can read back, but commits are owned by the API handler.

### T4.5 — Policy evaluator

```python
def evaluate(
    db: Session, *, tenant_id: str, action_type: str
) -> PolicyDecision:
    """Resolve effective policy for an action in a tenant.

    Order:
      1. TenantActionPolicy row for (tenant_id, action_type)
      2. GatedAction.default_policy from the parser-owned registry
      3. If action_type is not registered: deny (fail closed)
    """
    row = approval_policy.get(db, tenant_id, action_type)
    if row:
        return row.decision
    action = REGISTRY.get(action_type)
    if action is None:
        return PolicyDecision.deny
    return action.default_policy
```

`tenant_id` comes from `SessionContext.tenant_id`, populated by the
Phase 1 identity resolver from the `onyx.app/tenant-id` sandbox
label.

**Cache strategy (v0): no cache.** Each gated request runs one DB
lookup against `tenant_action_policy`. At v0 traffic this is
negligible, and it guarantees admin policy changes take effect on the
next gated request without invalidation plumbing. Revisit if
profiling shows the lookup is hot.

### T4.6 — Silent-decision audit write

Silent `always_allow` / `deny` decisions need an audit row but no
liveness key, no wake channel, and no `BuildMessage` — the row is
the entire artifact. Add a single helper to
`backend/onyx/server/features/build/db/action_approval.py`:

```python
def insert_silent_action_approval(
    db_session: Session,
    *,
    session_id: UUID,
    action_type: str,
    payload: dict[str, Any],
    decision: ApprovalDecision,
) -> ActionApproval:
    """Insert a pre-decided action_approval row.

    Used by the policy evaluator's silent paths. Accepts only
    APPROVED / REJECTED; EXPIRED is reserved for the proxy's timeout
    path and asserted out.
    """
    assert decision in (ApprovalDecision.APPROVED, ApprovalDecision.REJECTED)
    row = ActionApproval(
        session_id=session_id,
        action_type=action_type,
        payload=payload,
        decision=decision,
        decided_at=datetime.now(timezone.utc),
    )
    db_session.add(row)
    db_session.flush()
    return row
```

Same table, same audit query — no separate audit storage. Silent
rows show up next to interactive decisions when filtered by
`decision`.

### T4.7 — Gate addon: policy hook

The gate addon already decomposes its `request` hook into helpers:

```
_match_action  →  _create_request  →  _await_decision  →  _apply_decision_to_flow
```

Phase 4 inserts the policy evaluator between `_match_action`
(which returns `(ctx, match)`) and `_create_request`. The shape of
the `request` hook becomes:

```python
async def request(self, flow: http.HTTPFlow) -> None:
    match_result = self._match_action(flow)
    if match_result is None:
        return
    ctx, match = match_result

    with self._db_session_factory(ctx.tenant_id) as db:
        decision = policy.evaluate(
            db, tenant_id=ctx.tenant_id, action_type=match.action_type
        )

        if decision == PolicyDecision.always_allow:
            action_approval.insert_silent_action_approval(
                db,
                session_id=ctx.session_id,
                action_type=match.action_type,
                payload=match.payload,
                decision=ApprovalDecision.APPROVED,
            )
            db.commit()
            self._apply_decision_to_flow(flow, ApprovalDecision.APPROVED)
            return

        if decision == PolicyDecision.deny:
            action_approval.insert_silent_action_approval(
                db,
                session_id=ctx.session_id,
                action_type=match.action_type,
                payload=match.payload,
                decision=ApprovalDecision.REJECTED,
            )
            db.commit()
            self._apply_decision_to_flow(
                flow, ApprovalDecision.REJECTED, code=_CODE_POLICY_DENIED
            )
            return

    # require_approval: interactive path
    approval_id = self._create_request(ctx, match)
    decision = await self._await_decision(approval_id, ctx, match)
    self._apply_decision_to_flow(flow, decision)
```

`_apply_decision_to_flow` gains an optional `code` arg so the silent
deny path can emit the `policy_denied` 403 (see T4.8), while the
existing user-rejected path keeps emitting `user_rejected`. APPROVED
silent rows flow through the same forwarding branch as user-approved.

### T4.8 — Sandbox-facing 403 code: `policy_denied`

The sandbox-side 403 code enum is locked at:

```
unidentified_sandbox | body_too_large | user_rejected
| not_authorized | policy_denied
```

Phase 4 is the first user of `policy_denied`. It's distinct from
`user_rejected` (a human said no) and `not_authorized` (the
timeout/expired path) so the sandbox-side caller can distinguish
"admin policy blocks this action" from "user declined this request"
in error messages.

### T4.9 — Admin policy API

`backend/onyx/server/features/build/approvals/policy_api.py`,
mounted on the same `/approvals` router prefix as `api.py`:

```python
router = APIRouter(
    prefix="/approvals/admin",
    dependencies=[Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS))],
)

@router.get("/actions")
def list_actions(
    db: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> list[ActionPolicyView]:
    """Return every registered GatedAction plus its current effective
    policy for the caller's tenant."""

@router.put("/actions/{action_type}/policy")
def set_policy(
    action_type: str,
    body: PolicyBody,
    db: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
    user: User = Depends(current_user),
) -> None:
    """Upsert TenantActionPolicy row; raise OnyxError(NOT_FOUND) if
    action_type is not registered."""

@router.delete("/actions/{action_type}/policy")
def reset_policy(
    action_type: str,
    db: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> None:
    """Delete the tenant-specific row; revert to the action's default."""
```

`tenant_id` and `db` come from FastAPI dependencies, matching the
enterprise-settings router. Raise `OnyxError(NOT_FOUND, ...)` for
unknown action_types. No `response_model`.

### T4.10 — Admin audit API + tenant query

The user-facing API already exposes per-session audit lookup
(`/approvals/sessions/{id}`). Phase 4 adds the tenant-scoped variant
that an admin uses to browse all approvals across the org. Add the
query to `action_approval.py`:

```python
def list_tenant_action_approvals(
    db_session: Session,
    tenant_id: str,
    *,
    decision: ApprovalDecision | Literal["null"] | None = None,
    action_type: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 100,
    cursor: UUID | None = None,
) -> list[ActionApproval]:
    """Tenant-scoped audit, JOINed against build_session for
    user_id projection and tenant scoping."""
```

Endpoint, on the same admin router:

```python
@router.get("/audit")
def list_audit(
    decision: ApprovalDecision | Literal["null"] | None = None,
    action_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    cursor: UUID | None = None,
    db: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> AuditPage:
    """Tenant-scoped, filterable list of rows from the single
    `action_approval` table."""
```

The session owner is both the requester and the decider for every
approval, so identity isn't denormalized onto the row; the JOIN to
`build_session` projects `build_session.user_id` as the "requesting
user" column for display.

The `decision` filter accepts the three `ApprovalDecision` enum
values (`APPROVED` / `REJECTED` / `EXPIRED`) or the sentinel `null`
to select rows where `decision IS NULL` — orphan / pending attempts
that never reached a terminal state. The default admin UI splits
these into a "decisions" view (`decision IS NOT NULL`) and a
"pending / orphan" view (`decision IS NULL`); the API exposes both
via this single filter parameter.

### T4.11 — Admin UI: policy page

Mounts under `web/src/app/admin/approvals/`. Add an `APPROVALS`
entry to `web/src/lib/admin-routes.ts` and a matching `add()` call
in `web/src/sections/sidebar/AdminSidebar.tsx` (likely under
"Permissions" pending UX call). Permission gate matches the API:
`FULL_ADMIN_PANEL_ACCESS`.

Behavioral contract for `ApprovalSettingsPage`:

- Fetches `GET /approvals/admin/actions` on mount.
- Renders a table: action name, description, current policy,
  "default vs override" indicator.
- Each row has a policy dropdown
  (`require_approval` / `deny` / `always_allow`); changing it
  issues `PUT /approvals/admin/actions/{action_type}/policy` and
  optimistically updates local state.
- Each row has a "Reset to default" link, shown only when an
  override exists; clicking it issues
  `DELETE /approvals/admin/actions/{action_type}/policy`.
- All mutations refetch on success; errors surface as a toast and
  roll back the optimistic update.

### T4.12 — Admin UI: audit page

`ApprovalAuditPage.tsx`:

- Fetches `GET /approvals/admin/audit` with filter state.
- Filters: decision (multi-select of `APPROVED` / `REJECTED` /
  `EXPIRED` plus a "Pending / Orphan" sentinel that maps to
  `decision IS NULL`), action_type (multi-select populated from
  the action list), date range.
- Table columns: created_at, action_type (rendered as
  `GatedAction.name`), requesting user (derived from
  `build_session.user_id`), decision (rendered as "Pending" when
  `NULL`), decided_at.
- Cursor-paginated; "Load more" appends.
- Row click opens a detail panel showing the full payload JSON.

## Testing

- **Unit** — `policy.evaluate` across the matrix: tenant row present
  / absent × registered / unknown action_type × all three decisions.
- **External-dependency-unit** — admin policy API CRUD against real
  DB (upsert, reset, unknown-action_type 404, permission check).
- **Integration** — configure `always_allow` via admin API, trigger
  through the proxy, assert no user prompt and that an
  `ActionApproval` row with `decision=APPROVED` and a `decided_at`
  exists; repeat for `deny` (assert 403 with `policy_denied` code +
  `decision=REJECTED` row); repeat for `require_approval` and assert
  the interactive Phase 2 flow runs (row inserted as pending,
  decision API call resolves it).
- **Integration** — admin audit API: seed rows with a mix of
  `APPROVED` / `REJECTED` / `EXPIRED` / `NULL` decisions across
  multiple tenants, exercise each filter (including the
  `decision IS NULL` sentinel) and assert tenant scoping +
  correct subset.

## Dependencies

- Phase 2 `action_approval` table, `insert_action_approval`,
  `record_decision`, decision API, and gate addon shipped.
- `SessionContext.tenant_id` populated by Phase 1.
- Parser registration ships before any External Apps registry update
  that introduces a new provider. If an action_type hits the proxy
  without a matching `GatedAction`, the evaluator returns `deny`
  (fail-closed) — release runbook item: "land parser metadata first,
  then enable the upstream pattern."

## Open during phase

- Whether the admin pages need design review before shipping; if so,
  loop in design at the start of the phase.
- Exact filter UX on the audit page (chips vs. dropdowns) —
  coordinate with whoever owns admin UI conventions.

## Definition of done

- Admin can list every registered gated action and the current
  policy for their tenant.
- Admin can change a policy and the **next** gated request reflects
  it with no proxy restart (verifies the no-cache strategy).
- `always_allow` skips the user prompt, forwards the upstream
  request, and records an `action_approval` row with
  `decision=APPROVED`.
- `deny` returns a 403 with the `policy_denied` code, blocks the
  upstream request, and records an `action_approval` row with
  `decision=REJECTED`.
- `require_approval` runs the Phase 2 interactive flow unchanged.
- Admin audit UI returns the correct rows for each filter
  combination, scoped to the caller's tenant.
- Schema accepts a future per-user override layer with no DDL
  changes to existing tables.
