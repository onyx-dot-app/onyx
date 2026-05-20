# Phase 4 — Policy Management (implementation)

Reference: [approvals-plan.md](./approvals-plan.md) for architecture.
Depends on Phase 2 (Phase 3 not strictly required, but realistic for
admins to use this once approvals are visible in chat).

## Goal

Replace the hardcoded "every gated action requires approval" behavior
with a real policy layer:

- **Developers** register gated actions in code (kind, name, description,
  default policy).
- **Admins** override per-action policy at the org level via a settings UI
  (`require_approval` / `deny` / `always_allow`).
- The Approval Service consults the policy before deciding what to do
  with an incoming gated request.

The schema is built so a per-user override layer can be added later
without a rewrite — v0 ships admin-only.

## Module layout

```
backend/onyx/server/features/build/approvals/
├── policy.py                    # action registry + policy evaluator
├── admin_api.py                 # admin endpoints (separate router)
└── service.py                   # consumes policy.evaluate(...)

backend/onyx/db/
├── approval_policy.py           # DB queries
├── models.py                    # OrgActionPolicy (additions)
└── enums.py                     # PolicyDecision (additions)

backend/alembic/versions/YYYY_create_org_action_policy.py

web/src/app/admin/approvals/
├── ApprovalSettingsPage.tsx
└── ActionPolicyRow.tsx
```

## Tasks

### T4.1 — Action registry

A registry developers populate with their action declarations:

```python
# backend/onyx/server/features/build/approvals/policy.py

@dataclass(frozen=True)
class GatedAction:
    kind: str                    # "slack.send_message"
    name: str                    # "Send Slack message"
    description: str             # "Posts a message to a Slack channel"
    default_policy: PolicyDecision = PolicyDecision.require_approval

class ActionRegistry:
    def __init__(self):
        self._actions: dict[str, GatedAction] = {}

    def register(self, action: GatedAction) -> None: ...
    def all(self) -> list[GatedAction]: ...
    def get(self, kind: str) -> GatedAction | None: ...

REGISTRY = ActionRegistry()

# Action declarations live alongside their consumers; e.g. in
# external_apps for Slack/Linear/GCal kinds.
```

Discovery: registrations happen at import time. The proxy and admin API
import the relevant modules to populate `REGISTRY` before serving.

### T4.2 — DB: org policy storage

`PolicyDecision` enum in `db/enums.py`:

```python
class PolicyDecision(str, PyEnum):
    require_approval = "require_approval"
    deny = "deny"
    always_allow = "always_allow"
```

`OrgActionPolicy` ORM in `db/models.py`:

```python
class OrgActionPolicy(Base):
    __tablename__ = "org_action_policy"
    # composite unique on (org_id, kind); use a composite PK or
    # surrogate id with unique constraint — either is fine
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organization.id"))
    kind: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[PolicyDecision] = mapped_column(
        Enum(PolicyDecision), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_by: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"))

    __table_args__ = (UniqueConstraint("org_id", "kind"),)
```

Designed for extension: a future `user_action_policy` table with
`(org_id, user_id, kind)` slots cleanly above this without changes here.

Alembic migration follows existing patterns.

### T4.3 — Policy evaluator

```python
def evaluate(db: Session, *, org_id: UUID, kind: str) -> PolicyDecision:
    """Resolve effective policy for an action in an org.

    Order:
      1. OrgActionPolicy row for (org_id, kind)
      2. GatedAction.default_policy in the registry
    """
    row = approval_policy.get(db, org_id, kind)
    if row:
        return row.decision
    action = REGISTRY.get(kind)
    if action is None:
        # Unknown kind — fail closed.
        return PolicyDecision.deny
    return action.default_policy
```

Consumed by the proxy's `GateAddon` and by `service.create()`:

```python
# In the gate addon (Phase 2 currently always creates an approval)
match = self._registry.match(flow.request)
if match is None:
    return  # not gated

with self._db() as db:
    decision = policy.evaluate(
        db, org_id=ctx.org_id, kind=match.kind,
    )

if decision == PolicyDecision.always_allow:
    # log + audit row, but don't ask user
    audit.record_silent_allow(db, ctx.session_id, match.kind, summary, payload)
    return  # forward
if decision == PolicyDecision.deny:
    audit.record_denial(db, ctx.session_id, match.kind, summary, payload)
    flow.response = http.Response.make(403, b'{"error":"policy_denied"}')
    return
# require_approval → existing Phase 2 flow
...
```

### T4.4 — Audit

Per the requirements, every approval is recorded — including silent
allows and denials. Two options:

1. Use the existing `ApprovalRequest` table; create a row with
   `status=approved` or `status=rejected` immediately (no user prompt)
   for silent-allow / deny. Simple, audit query is unified.
2. Separate `approval_audit` table.

Recommend option 1 — fewer tables, single audit query, the row's
existence + status tells you the decision and what triggered it.

### T4.5 — Admin API

`backend/onyx/server/features/build/approvals/admin_api.py`:

```python
router = APIRouter(
    prefix="/admin/approvals",
    dependencies=[Depends(require_admin_role)],
)

@router.get("/actions")
def list_actions(db: Session, org: Organization) -> list[ActionPolicyView]:
    """Return every registered GatedAction plus its current effective
    policy for the caller's org."""
    return [
        ActionPolicyView(
            kind=a.kind,
            name=a.name,
            description=a.description,
            default_policy=a.default_policy,
            org_policy=approval_policy.get(db, org.id, a.kind),
        )
        for a in REGISTRY.all()
    ]

@router.put("/actions/{kind}/policy")
def set_policy(kind: str, body: PolicyBody, db: Session,
               org: Organization, user: User) -> None:
    if REGISTRY.get(kind) is None:
        raise OnyxError(NOT_FOUND, f"unknown action kind: {kind}")
    approval_policy.upsert(
        db, org_id=org.id, kind=kind, decision=body.decision,
        updated_by=user.id,
    )

@router.delete("/actions/{kind}/policy")
def reset_policy(kind: str, db: Session, org: Organization) -> None:
    """Delete the org-specific row; revert to the action's default."""
    approval_policy.delete(db, org_id=org.id, kind=kind)
```

Use the existing admin-auth dependency pattern (look at the
enterprise-settings router for the canonical example).

### T4.6 — Admin UI

`web/src/app/admin/approvals/ApprovalSettingsPage.tsx`:

- Fetches `GET /admin/approvals/actions`.
- Renders a table: action name, description, current policy dropdown.
- Dropdown change → `PUT /admin/approvals/actions/{kind}/policy`.
- "Revert to default" link → `DELETE /admin/approvals/actions/{kind}/policy`.
- Indicate which actions are using their default vs. an org override
  (small label).

Sketch:

```tsx
export function ApprovalSettingsPage() {
  const { data: actions } = useFetch<ActionPolicyView[]>("/admin/approvals/actions");
  return (
    <SettingsLayout title="Approvals">
      <Table>
        <thead>...</thead>
        <tbody>
          {actions?.map(a => (
            <ActionPolicyRow key={a.kind} action={a} onChange={refetch} />
          ))}
        </tbody>
      </Table>
    </SettingsLayout>
  );
}
```

Each row is a small component with the policy dropdown + reset button.

## Future-extension hooks

For the per-user override layer (out of scope for v0 but the schema
should be ready):

- A future `user_action_policy(org_id, user_id, kind, decision)` table.
- `policy.evaluate` gains a `user_id` parameter and an additional lookup
  ahead of the org-level one.
- Admin UI gains a "users may override" toggle per action, gated by the
  "always_allow" admin permission.

None of that lands in Phase 4. The signal that we're ready for it is
just that `policy.evaluate` is a single function and the schema doesn't
fight the addition.

## Testing

- **Unit**: `policy.evaluate` for each combination (org row present /
  absent, registered / unknown action, all three decisions).
- **External-dependency-unit**: admin API CRUD against real DB.
- **Integration**: configure an action as `always_allow` via admin API,
  trigger the action through the proxy, assert no user prompt and that
  the audit row is `approved`.
- **Integration**: configure as `deny`, trigger, assert 403 returned and
  audit row is `rejected`.

## Dependencies

- Phase 2 complete (`service.create` and the gate addon exist).
- Existing org / admin-role plumbing in the auth layer.

## Open during phase

- Naming: `OrgActionPolicy` vs. `OrgApprovalPolicy` — pick one and
  commit.
- Where exactly admin routes mount in the API tree (admin namespace
  exists; confirm prefix).
- Default policy for unregistered kinds: `deny` (fail closed) is the
  recommendation; confirm.

## Definition of done

- Admins can list every gated action and current org policy.
- Admins can change a policy and the next gated request reflects it
  immediately (no proxy restart).
- `always_allow` skips the user prompt but still records the audit row.
- `deny` returns 403 without prompting and records the audit row.
- `require_approval` (default) preserves the Phase 2 behavior.
- Schema accepts a future per-user override layer without DDL changes
  to existing tables.
