# Phase 4 — Policy Management (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 2 (Phase 3 not strictly required, but realistic for
admins to use this once approvals are visible in chat).

## Goal

Replace the hardcoded "every gated action requires approval" behavior
with a real policy layer:

- **Developers** declare gated actions in code (action_type, name, description,
  default policy) alongside the parsers that match them on the wire.
- **Admins** override per-action policy at the tenant level via a
  settings UI (`require_approval` / `deny` / `always_allow`), and can
  view a tenant-scoped audit log of recent approvals.

The schema is built so a per-user override layer can be added later
without a rewrite — v0 ships admin-only.

## Module layout

```
backend/onyx/sandbox_proxy/parsers/
├── slack.py                     # parser + GatedAction declarations
├── linear.py
├── gcal.py
└── ...                          # one module per provider; imported at proxy startup

backend/onyx/server/features/build/approvals/
├── policy.py                    # evaluator; imports parser modules to populate registry
└── admin_api.py                 # admin policy + audit endpoints

backend/onyx/server/features/build/db/
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
`BuiltinSkillRegistry` pattern (`backend/onyx/skills/registry.py`) —
parser modules call `gated_action_registry.register(...)` at module
top level; `policy.py` imports the parsers once at startup to trigger
the registrations.

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

def match(request) -> ActionMatch | None: ...
```

The proxy and admin API both consume the same registry singleton.

### T4.2 — Action-type taxonomy lock

Lock the action_type namespace convention: `<provider>.<verb_resource>` — e.g.
`slack.send_message`, `linear.create_issue`, `gcal.create_event`. All
new gated actions follow this convention. Document it at the top of
`sandbox_proxy/parsers/` (module docstring is sufficient; promote to an
ADR if it ever becomes contentious).

### T4.3 — DB: tenant policy storage

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

A future `user_action_policy` table with `(tenant_id, user_id, action_type)`
layers above this with no DDL changes here.

Manual Alembic migration; follow existing per-tenant settings patterns
(see `ee/onyx/server/enterprise_settings/`).

### T4.4 — Policy evaluator

```python
def evaluate(db: Session, *, tenant_id: str, action_type: str) -> PolicyDecision:
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

`tenant_id` comes from `SessionContext.tenant_id`, which Phase 1
already populates from the `onyx.app/tenant-id` sandbox label
(see [phase-1-proxy.md §T1.4](./phase-1-proxy.md#t14--identity-resolver)).
The evaluator does not re-derive it.

**Cache strategy (v0): no cache.** Each gated request runs one DB
lookup against `tenant_action_policy`. At v0 traffic this is
negligible, and it guarantees admin policy changes take effect on the
next gated request without invalidation plumbing. Revisit if profiling
shows the lookup is hot.

Consumed by the proxy's `GateAddon`, which calls
`db/action_approval.py` directly:

```python
match = self._registry.match(flow.request)
if match is None:
    return  # not gated

with self._db() as db:
    decision = policy.evaluate(db, tenant_id=ctx.tenant_id, action_type=match.action_type)

    if decision == PolicyDecision.always_allow:
        action_approval.insert_silent_action_approval(
            db,
            session_id=ctx.session_id,
            action_type=match.action_type,
            payload=payload,
            decision=ApprovalDecision.APPROVED,
        )
        db.commit()
        return  # forward
    if decision == PolicyDecision.deny:
        action_approval.insert_silent_action_approval(
            db,
            session_id=ctx.session_id,
            action_type=match.action_type,
            payload=payload,
            decision=ApprovalDecision.REJECTED,
        )
        db.commit()
        flow.response = http.Response.make(403, b'{"error":"policy_denied"}')
        return
# require_approval → existing Phase 2 flow
```

### T4.5 — Audit row synthesis

Audit rows for `always_allow` and `deny` decisions are synthesized
by `action_approval.insert_silent_action_approval`, which the policy
evaluator calls directly from the gate addon (see T4.4). Same
`approval` table, same audit query — no new audit storage in Phase 4.
Silent decisions INSERT a row with `decision` pre-populated
(`APPROVED` or `REJECTED`); no liveness key, no wakeup.

### T4.6 — Admin policy API

`backend/onyx/server/features/build/approvals/admin_api.py`:

```python
router = APIRouter(
    prefix="/admin/approvals",
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

`tenant_id` and `db` come from FastAPI dependencies — same pattern as
the enterprise-settings router. Raise `OnyxError(NOT_FOUND, ...)` for
unknown action_types. No `response_model`.

### T4.7 — Admin audit API

By invariant, the session owner is both the requester and the decider
for every approval; the audit schema relies on this and stores neither
identity directly.

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
    """Tenant-scoped, filterable list of rows from the single `approval`
    table. Backed by the Phase 2 audit query."""
```

The handler is a thin wrapper over Phase 2's audit query, scoped to the
caller's tenant. It reads from the single `approval` table and
optionally JOINs to `build_session` to project `build_session.user_id`
as the "requesting user" column.

The `decision` filter accepts the three `ApprovalDecision` enum values
(`APPROVED` / `REJECTED` / `EXPIRED`) **or** the sentinel `null` to
select rows where `decision IS NULL` — i.e. orphan / pending attempts
that never had a decision recorded. The default admin UI splits these
into a "decisions" view (`decision IS NOT NULL`) and a "pending /
orphan" view (`decision IS NULL`), but that's a UX concern; the API
exposes both via this single filter parameter.

### T4.8 — Admin UI: policy page

Mounts under `web/src/app/admin/approvals/`. Add an `APPROVALS` entry
to `web/src/lib/admin-routes.ts` and a matching `add()` call in
`web/src/sections/sidebar/AdminSidebar.tsx` (likely under the
"Permissions" section pending UX call). Permission gate matches the
API: `FULL_ADMIN_PANEL_ACCESS`.

Behavioral contract for `ApprovalSettingsPage`:

- Fetches `GET /admin/approvals/actions` on mount.
- Renders a table: action name, description, current policy, "default
  vs override" indicator.
- Each row has a policy dropdown
  (`require_approval` / `deny` / `always_allow`); changing it issues
  `PUT /admin/approvals/actions/{action_type}/policy` and optimistically
  updates local state.
- Each row has a "Reset to default" link, shown only when an override
  exists; clicking it issues `DELETE /admin/approvals/actions/{action_type}/policy`.
- All mutations refetch on success; errors surface as a toast and roll
  back the optimistic update.

### T4.9 — Admin UI: audit page

`ApprovalAuditPage.tsx`:

- Fetches `GET /admin/approvals/audit` with filter state.
- Filters: decision (multi-select of `APPROVED` / `REJECTED` /
  `EXPIRED` plus a "Pending / Orphan" sentinel that maps to
  `decision IS NULL`), action_type (multi-select populated from
  the action list), date range.
- Table columns: created_at, action_type (rendered as the
  GatedAction.name), requesting user (derived from
  `build_session.user_id`), decision (rendered as "Pending" when
  `NULL`), decided_at.
- Cursor-paginated; "Load more" appends.
- Row click opens a detail panel showing the full payload JSON.

## Testing

- **Unit** — `policy.evaluate` across the matrix: tenant row present /
  absent × registered / unknown action_type × all three decisions.
- **External-dependency-unit** — admin policy API CRUD against real DB
  (upsert, reset, unknown-action_type 404, permission check).
- **Integration** — configure `always_allow` via admin API, trigger
  through the proxy, assert no user prompt and an approved audit row
  exists; repeat for `deny` (assert 403 + rejected row); repeat for
  `require_approval` and assert Phase 2 behavior is preserved.
- **Integration** — admin audit API: seed rows with a mix of
  `APPROVED` / `REJECTED` / `EXPIRED` / `NULL` decisions, exercise each
  filter (including the `decision IS NULL` sentinel) and assert the
  right subset comes back.

## Dependencies

- Phase 2 complete (`action_approval.insert_action_approval`,
  `action_approval.record_decision`,
  `action_approval.insert_silent_action_approval`, and the audit
  queries exist in `db/action_approval.py`).
- `SessionContext.tenant_id` populated by Phase 1.
- Parser registration ships before any External Apps registry update
  that introduces a new provider. If an action_type hits the proxy without a
  matching `GatedAction`, the evaluator returns `deny` (fail-closed),
  which is the right safety posture but a poor UX — document this as a
  release runbook item: "land parser metadata first, then enable the
  upstream pattern."

## Open during phase

- Whether the admin pages need design review before shipping; if so,
  loop in design at the start of the phase.
- Exact filter UX on the audit page (chips vs. dropdowns) — coordinate
  with whoever owns admin UI conventions.

## Definition of done

- Admin can list every registered gated action and the current policy
  for their tenant.
- Admin can change a policy and the **next** gated request reflects it
  with no proxy restart (verifies the no-cache strategy).
- `always_allow` skips the user prompt and records an audit row via
  `action_approval.insert_silent_action_approval`.
- `deny` returns 403 without a prompt and records an audit row via
  `action_approval.insert_silent_action_approval`.
- `require_approval` (default) preserves the Phase 2 behavior.
- Admin audit UI returns the correct rows for each filter combination.
- Schema accepts a future per-user override layer with no DDL changes
  to existing tables.
