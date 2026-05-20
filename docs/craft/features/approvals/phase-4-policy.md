# Phase 4 — Policy Management (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 2 (Phase 3 not strictly required, but realistic for
admins to use this once approvals are visible in chat).

## Goal

Replace the hardcoded "every gated action requires approval" behavior
with a real policy layer:

- **Developers** declare gated actions in code (kind, name, description,
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
├── admin_api.py                 # admin policy + audit endpoints
└── service.py                   # consumes policy.evaluate(...) and record_silent_decision

backend/onyx/db/
├── approval_policy.py           # queries for TenantActionPolicy
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

The registry of gated actions is the set of parser modules in
`sandbox_proxy/parsers/`. Each parser both matches requests on the wire
and declares the `GatedAction`s it produces:

```python
# backend/onyx/sandbox_proxy/parsers/slack.py

@dataclass(frozen=True)
class GatedAction:
    kind: str                    # "slack.send_message"
    name: str                    # "Send Slack message"
    description: str             # "Posts a message to a Slack channel"
    default_policy: PolicyDecision = PolicyDecision.require_approval

SEND_MESSAGE = GatedAction(
    kind="slack.send_message",
    name="Send Slack message",
    description="Posts a message to a Slack channel.",
)

ACTIONS: list[GatedAction] = [SEND_MESSAGE, ...]

def match(request) -> ActionMatch | None: ...
```

Discovery: `policy.py` imports the parser modules at startup, building
the in-memory `{kind: GatedAction}` map from each module's `ACTIONS`
list. The proxy and admin API both consume the same map.

### T4.2 — Action-kind taxonomy lock

Lock the kind namespace convention: `<provider>.<verb_resource>` — e.g.
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
    kind: Mapped[str] = mapped_column(String, nullable=False)
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

    __table_args__ = (UniqueConstraint("tenant_id", "kind"),)
```

A future `user_action_policy` table with `(tenant_id, user_id, kind)`
layers above this with no DDL changes here.

Manual Alembic migration; follow existing per-tenant settings patterns
(see `ee/onyx/server/enterprise_settings/`).

### T4.4 — Policy evaluator

```python
def evaluate(db: Session, *, tenant_id: str, kind: str) -> PolicyDecision:
    """Resolve effective policy for an action in a tenant.

    Order:
      1. TenantActionPolicy row for (tenant_id, kind)
      2. GatedAction.default_policy from the parser-owned registry
      3. If kind is not registered: deny (fail closed)
    """
    row = approval_policy.get(db, tenant_id, kind)
    if row:
        return row.decision
    action = REGISTRY.get(kind)
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

Consumed by the proxy's `GateAddon` and by `service.create()`:

```python
match = self._registry.match(flow.request)
if match is None:
    return  # not gated

with self._db() as db:
    decision = policy.evaluate(db, tenant_id=ctx.tenant_id, kind=match.kind)

if decision == PolicyDecision.always_allow:
    service.record_silent_decision(
        db, ctx, match.kind, summary, payload, ApprovalStatus.approved,
    )
    return  # forward
if decision == PolicyDecision.deny:
    service.record_silent_decision(
        db, ctx, match.kind, summary, payload, ApprovalStatus.rejected,
    )
    flow.response = http.Response.make(403, b'{"error":"policy_denied"}')
    return
# require_approval → existing Phase 2 flow
```

### T4.5 — Audit row synthesis

Audit rows for `always_allow` and `deny` decisions are synthesized by
Phase 2's `service.record_silent_decision(...)`, which the policy
evaluator calls. Same `ApprovalRequest` table, same audit query — no
new audit storage in Phase 4.

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

@router.put("/actions/{kind}/policy")
def set_policy(
    kind: str,
    body: PolicyBody,
    db: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
    user: User = Depends(current_user),
) -> None:
    """Upsert TenantActionPolicy row; raise OnyxError(NOT_FOUND) if
    kind is not registered."""

@router.delete("/actions/{kind}/policy")
def reset_policy(
    kind: str,
    db: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> None:
    """Delete the tenant-specific row; revert to the action's default."""
```

`tenant_id` and `db` come from FastAPI dependencies — same pattern as
the enterprise-settings router. Raise `OnyxError(NOT_FOUND, ...)` for
unknown kinds. No `response_model`.

### T4.7 — Admin audit API

```python
@router.get("/audit")
def list_audit(
    db: Session,
    tenant_id: str,
    status: ApprovalStatus | None = None,
    kind: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    cursor: UUID | None = None,
) -> AuditPage:
    """Tenant-scoped, filterable list of ApprovalRequest rows. Backed by
    the Phase 2 audit query."""
```

The handler is a thin wrapper over Phase 2's audit query, scoped to the
caller's tenant.

### T4.8 — Admin UI: policy page

Mounts under `web/src/app/admin/approvals/` (sibling to the other
admin pages listed under `web/src/app/admin/`). Added to the admin nav
under a new "Approvals" entry. Permission gate matches the API:
`FULL_ADMIN_PANEL_ACCESS`.

Behavioral contract for `ApprovalSettingsPage`:

- Fetches `GET /admin/approvals/actions` on mount.
- Renders a table: action name, description, current policy, "default
  vs override" indicator.
- Each row has a policy dropdown
  (`require_approval` / `deny` / `always_allow`); changing it issues
  `PUT /admin/approvals/actions/{kind}/policy` and optimistically
  updates local state.
- Each row has a "Reset to default" link, shown only when an override
  exists; clicking it issues `DELETE /admin/approvals/actions/{kind}/policy`.
- All mutations refetch on success; errors surface as a toast and roll
  back the optimistic update.

### T4.9 — Admin UI: audit page

`ApprovalAuditPage.tsx`:

- Fetches `GET /admin/approvals/audit` with filter state.
- Filters: status (multi-select), kind (multi-select populated from the
  action list), date range.
- Table columns: created_at, kind, requesting user, status, decided_at,
  decided_by, summary.
- Cursor-paginated; "Load more" appends.
- Row click opens a detail panel showing the full payload JSON.

## Testing

- **Unit** — `policy.evaluate` across the matrix: tenant row present /
  absent × registered / unknown kind × all three decisions.
- **External-dependency-unit** — admin policy API CRUD against real DB
  (upsert, reset, unknown-kind 404, permission check).
- **Integration** — configure `always_allow` via admin API, trigger
  through the proxy, assert no user prompt and an approved audit row
  exists; repeat for `deny` (assert 403 + rejected row); repeat for
  `require_approval` and assert Phase 2 behavior is preserved.
- **Integration** — admin audit API: seed mixed-status rows, exercise
  each filter and assert the right subset comes back.

## Dependencies

- Phase 2 complete (`service.create`, `service.record_silent_decision`,
  and Phase 2's audit query exist).
- `SessionContext.tenant_id` populated by Phase 1.
- Parser registration ships before any External Apps registry update
  that introduces a new provider. If a kind hits the proxy without a
  matching `GatedAction`, the evaluator returns `deny` (fail-closed),
  which is the right safety posture but a poor UX — document this as a
  release runbook item: "land parser metadata first, then enable the
  upstream pattern."

## Open during phase

- Where the admin nav entry mounts (verify against the existing
  `web/src/app/admin/layout.tsx` nav structure).
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
  `service.record_silent_decision`.
- `deny` returns 403 without a prompt and records an audit row via
  `service.record_silent_decision`.
- `require_approval` (default) preserves the Phase 2 behavior.
- Admin audit UI returns the correct rows for each filter combination.
- Schema accepts a future per-user override layer with no DDL changes
  to existing tables.
