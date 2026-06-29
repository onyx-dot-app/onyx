> Status: active · Task: group-manager-scoped-permissions

# §8 Scoped Permissions (Group Manager) — Detailed Design

Granular spec for implementing §8 on `new-permission-system`. All paths relative to repo root.

---

## 1. Database design

### 1.1 New column: `user__user_group.is_manager`

Reuses the dead `is_curator` slot semantically (we **add** `is_manager` and later drop `is_curator`; we do
**not** rename in-place — the backfill needs both columns to coexist during the transition).

```python
# backend/onyx/db/models.py  — class User__UserGroup (currently lines 4356-4368)
is_manager: Mapped[bool] = mapped_column(
    Boolean, nullable=False, default=False, server_default=text("false")
)
```

| Attribute | Choice | Rationale |
|---|---|---|
| Name | `is_manager` | Distinct from the tombstone `is_curator`; "manager" matches the §8 vocabulary and the new single-resolver meaning. |
| Type | `Boolean` | A manager binding is binary per (user, group) edge. The *abilities* are code-defined, not stored — so no need for a richer type. |
| `nullable=False` | yes | Every membership row has a definite manager-or-not state; avoids tri-state ambiguity in the `WHERE is_manager` filter. |
| `default=False` / `server_default='false'` | yes | New memberships are non-managers; existing rows backfill to `false` before the targeted UPDATE sets the real managers. Server default lets the `ADD COLUMN` be non-blocking. |
| Placement | on the **edge** `user__user_group`, not on `user` or `permission_grant` | Scope is per-(user, group). `permission_grant` stays **global-only** (`group_id NOT NULL`, no `user_id`). A role binding is not a permission. |
| Index | **none new** — reuse `ix_user__user_group_user_id` (models.py:4359) | The live LIST lookup is `WHERE user_id = ? AND is_manager = true`; the existing `(user_id)` index serves it, and a manager has few memberships so the residual `is_manager` filter is cheap. A partial `(user_id) WHERE is_manager` is an optional later optimization, not needed at launch. |

### 1.1b Cached route-gate flag: `user.is_group_manager` (D1 — cache the boolean)

GATE-2 review chose **cache the boolean** so the route gate needs **zero queries**. Rather than reshape the
`effective_permissions` JSONB (`list[str]` — a sentinel would break `Permission(p)` validation in
`get_effective_permissions`), add a dedicated cached boolean on `User`, recomputed alongside the permission
cache. `effective_permissions` therefore stays **global-tokens-only**; the manager flag is a sibling field.

```python
# backend/onyx/db/models.py  — class User
is_group_manager: Mapped[bool] = mapped_column(
    Boolean, nullable=False, default=False, server_default=text("false")
)
```

| Attribute | Choice | Rationale |
|---|---|---|
| What it caches | "does this user manage **any** group?" (the boolean only) | The route gate (GATE 1) needs only reachability; it's loaded with the user at auth → no query. |
| What it does **not** cache | the managed-group **list** | The list stays live (`scoped_group_ids_subquery`) so filters + GATE 2 never go stale after a rename/move/delete. |
| Recompute trigger | `recompute_user_permissions__no_commit` (extend) **and** `make/revoke_group_manager` | Flag = `EXISTS(is_manager=true for user)`. Membership changes already recompute; manager flips must recompute the affected user too. |
| Staleness window | bounded to a single user, flipped in the same txn as the membership/manager change | Acceptable — the cost the live-list avoids was the *scope set* going stale, which this doesn't touch. |

### 1.2 Migration — additive only (ship with the feature)

`backend/alembic/versions/4fa09af6ca14_add_is_manager_to_user__user_group.py`
(revision `4fa09af6ca14`, **down_revision `c8e316473aaa`** — current head).
**Tenant schema** (`alembic/versions/`), NOT `alembic_tenants/`.

```python
def upgrade() -> None:
    op.add_column(
        "user__user_group",
        sa.Column("is_manager", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "user",
        sa.Column("is_group_manager", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Backfill is_manager — NOT a rename. is_curator alone misses GLOBAL_CURATOR (no per-group rows).
    op.execute("""
        UPDATE user__user_group ug SET is_manager = true
        FROM "user" u
        WHERE ug.user_id = u.id AND u.role = 'CURATOR' AND ug.is_curator = true
    """)
    op.execute("""
        UPDATE user__user_group ug SET is_manager = true
        FROM "user" u
        WHERE ug.user_id = u.id AND u.role = 'GLOBAL_CURATOR'
    """)
    # Backfill the cached flag from the rows just set.
    op.execute("""
        UPDATE "user" u SET is_group_manager = true
        WHERE EXISTS (
            SELECT 1 FROM user__user_group ug
            WHERE ug.user_id = u.id AND ug.is_manager = true
        )
    """)

def downgrade() -> None:
    op.drop_column("user", "is_group_manager")
    op.drop_column("user__user_group", "is_manager")
```

- **Ordering invariant:** must run **before** any later migration drops `role` / `is_curator`. Captured in
  `01-research.md` (disappearing-tombstone trap).
- **Fresh installs / new tenants:** backfill UPDATEs match nothing; `is_manager` starts all-false. ✓
- **Migration report (operational, not a migration step):** a one-off script flags any CURATOR/GLOBAL_CURATOR
  whose backfill mapped to **zero** managed groups (snapshot caveat — GLOBAL_CURATOR was dynamic). Out of the
  migration transaction; can be a logged query or admin CSV.

### 1.3 Deferred (NOT in this feature)

Dropping `is_curator`, `role`, `UserRole`; migrating the 3 `user.role==UserRole.ADMIN` readers. Separate cleanup
release — keeps a code rollback possible while §8 is unproven.

---

## 2. Code design — new authorization primitives

New module: **`backend/onyx/auth/scoped_permissions.py`** (keeps DB-querying scope logic out of the pure
`permissions.py`; imports `User`, `Permission`, `User__UserGroup`).

### 2.1 The manager ability bundle

```python
SCOPED_MANAGER_PERMISSIONS: frozenset[Permission] = frozenset({
    Permission.MANAGE_CONNECTORS,
    Permission.MANAGE_DOCUMENT_SETS,
    Permission.MANAGE_AGENTS,
    Permission.ADD_AGENTS,
    Permission.MANAGE_USER_GROUPS,   # membership + resource sharing of the managed group only
    Permission.MANAGE_ACTIONS,       # tools/MCP, scoped via the managed group's agents
})
```
Code-defined, never written to `permission_grant`. Expanded live; never merged into
`effective_permissions` (which stays global-only).

### 2.2 Live scope resolution (two forms)

```python
def scoped_group_ids_subquery(user: User) -> Select:
    """Composable subquery of the user's managed group ids — embed in _add_user_filters
    so the scope predicate stays in SQL (no extra round-trip)."""
    return select(User__UserGroup.user_group_id).where(
        User__UserGroup.user_id == user.id,
        User__UserGroup.is_manager.is_(True),
    )

def get_scoped_groups(user: User, db_session: Session,
                      permission: Permission | None = None) -> set[int]:
    """Imperative form for the write-side gate. Empty if permission given but not scopable."""
    if permission is not None and permission not in SCOPED_MANAGER_PERMISSIONS:
        return set()
    return set(db_session.scalars(scoped_group_ids_subquery(user)).all())
```

### 2.3 GATE 1 — route gate

```python
def has_permission_or_scope(user: User, permission: Permission) -> bool:
    if has_permission(user, permission):          # global token or admin override
        return True
    # D1: cached flag → zero query. scopable + manages something ⇒ reachable.
    return permission in SCOPED_MANAGER_PERMISSIONS and user.is_group_manager
```

FastAPI wiring — **extend the existing `require_permission`** with `allow_scope: bool = False` rather than add a
second factory. Because GATE 1 now reads the cached `user.is_group_manager`, **no DB session dependency is
needed** at the route:

```python
# permissions.py — require_permission(required, *, allow_anonymous=False, allow_scope=False)
# when allow_scope: pass-condition becomes
#   has_permission_or_scope(user, required) AND permitted_by_token
# token cap (request.state.token_scopes) is unchanged and still applies.
```
Endpoints a manager must reach (resource + group writes/lists) switch to
`require_permission(<token>, allow_scope=True)`. `set_group_permissions` stays
`require_permission(FULL_ADMIN_PANEL_ACCESS)` — **no** `allow_scope`.

### 2.4 GATE 2 — per-resource write-side gate (authorization of record)

```python
def assert_group_set_within_scope(
    user: User,
    db_session: Session,
    *,
    permission: Permission,                 # the manage:* token this write needs
    current_group_ids: Collection[int],     # re-read from DB, in this txn
    requested_group_ids: Collection[int],   # client-supplied target groups
    is_private: bool,                        # access_type==PRIVATE / not is_public
) -> None:
    # Global authority (admin or holds the token globally) → base-system rules already govern.
    if has_permission(user, permission):
        return
    managed = get_scoped_groups(user, db_session, permission)
    final = set(current_group_ids) | set(requested_group_ids)
    if not managed or not final or not final.issubset(managed) or not is_private:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Group managers can only act on private resources within the groups they manage.",
        )
```

Invariants enforced: `final ⊆ managed` (no group outside scope, closes capture-by-reassign),
`final` non-empty (resource stays in ≥1 group — covers detach), `is_private` (PRIVATE-only),
**fail-closed** (empty `managed` ⇒ reject, never "no filter").

### 2.5 Manager assignment helpers (EE)

```python
# backend/ee/onyx/db/user_group.py
def make_group_manager(db_session: Session, user_id: UUID, group_id: int) -> None:
    """Flip is_manager=true on the (user, group) row. Row must exist (a manager is a member).
    Idempotent. Used by the migration backfill helper and the assignment UI."""
def revoke_group_manager(db_session: Session, user_id: UUID, group_id: int) -> None:
    """Flip is_manager=false. Idempotent."""
```

### 2.6 Cached-flag recompute (D1 plumbing)

`backend/onyx/db/permissions.py:43` `recompute_user_permissions__no_commit` — **extend** to also set
`user.is_group_manager = EXISTS(is_manager=true for that user)` in the same write. This already fires on
membership add/remove (`update_user_group:570`). Additionally, `make_group_manager` / `revoke_group_manager`
must call `recompute_user_permissions__no_commit(user_id)` for the affected user so a pure manager flip (no
membership change) refreshes the cached flag. `effective_permissions` content is unchanged (global tokens only).

---

## 3. Filter rewrites — the 6 `_add_user_filters`

Each `get_editable=True` branch gains a scoped-manager case using `scoped_group_ids_subquery(user)`. The
read-side predicate mirrors GATE 2: a resource is editable-by-manager iff **every** group it belongs to is
managed, it belongs to **≥1** group, and it is **private**.

Reusable clause (new helper in `scoped_permissions.py`):

```python
def within_managed_scope_clause(
    resource_id_col, junction_model, junction_resource_col, junction_group_col,
    is_public_col, managed_subq: Select,
) -> ColumnElement[bool]:
    """resource is fully inside managed groups, in ≥1 group, and private."""
    # NOT EXISTS(group not in managed)  AND  EXISTS(group in managed)  AND  is_public = false
```

| File | Today (`get_editable`) | Change |
|---|---|---|
| `backend/onyx/db/document_set.py:41` | returns `sa_false()` (only global MANAGE edits) | add manager branch: editable = `within_managed_scope_clause(...)` over `DocumentSet__UserGroup`. **Biggest build** — currently fully short-circuited. |
| `backend/onyx/db/connector_credential_pair.py:50` | builds membership/manage join (no short-circuit) | re-key the editable branch onto `scoped_group_ids_subquery` + `within_managed_scope_clause` over `UserGroup__ConnectorCredentialPair`; require PRIVATE. |
| `backend/onyx/db/persona.py:77` | owner + EDITOR group shares | add manager branch over `Persona__UserGroup`; `add:agents` ownership tier unchanged. |
| `backend/onyx/db/feedback.py:46` | join through cc_pair groups | re-key onto managed groups (mirror connector). |
| `backend/onyx/db/credentials.py:41` | owner-keyed (`Credential.user_id==user.id`), no `get_editable` | **NO CHANGE** — credentials stay owner-scoped by design; a manager never inherits others' credentials. Document the deliberate no-op. |
| `backend/ee/onyx/db/token_limit.py` | no `_add_user_filters`; direct group query | enforce managed-scope in the group-token-limit **write/endpoint** path (manager may set limits only on managed groups). Minor. |

**Fail-closed rule for every rewrite:** if `scoped_group_ids_subquery` yields no rows, the manager branch must
resolve to empty, never to an unfiltered statement.

---

## 4. Write-path gate insertions (where GATE 2 is called)

Each DB-write fn loads the resource's **current** groups in-txn, then calls
`assert_group_set_within_scope(...)` before mutating. Endpoints switch to `allow_scope=True`.

| Resource / action | DB fn (insert gate here) | Endpoint → new dep |
|---|---|---|
| Connector create | `add_credential_to_connector` (`connector_credential_pair.py:496`, groups via `_relate_groups_to_cc_pair__no_commit:480`) | `connector.py:1603` POST → `require_permission(MANAGE_CONNECTORS, allow_scope=True)` |
| Connector update (groups/access) | cc_pair update path (`server/documents/cc_pair.py` group/access setter) | same dep |
| Document set create | `insert_document_set` (`document_set.py:220`) | `document_set/api.py:33` POST → `MANAGE_DOCUMENT_SETS, allow_scope=True` |
| Document set update | `update_document_set` (`document_set.py:296`) | `document_set/api.py:59` PATCH → same |
| Persona create/update | `create_update_persona` (`persona.py:325`) → `update_persona_access` (`ee/persona.py:68`, `group_ids`+is_public) | persona create/update endpoint → `MANAGE_AGENTS, allow_scope=True` |
| Group create | `insert_user_group` (`ee/user_group.py:413`) | `user_group/api.py:144` POST → **UNCHANGED** `MANAGE_USER_GROUPS` (no `allow_scope`). **D2: admins only create top-level groups** — no self-grant path. |
| Group update / members | `update_user_group` (`ee/user_group.py:504`), `add_users_to_user_group` (`:462`) | `user_group/api.py:194` PATCH, `:215` add-users → `MANAGE_USER_GROUPS, allow_scope=True`; gate: `group_id ∈ managed` |
| Group **permissions** | `set_group_permission(s)__no_commit` (`ee/user_group.py:705/748`) | `user_group/api.py:115` PUT → **UNCHANGED** `FULL_ADMIN_PANEL_ACCESS` (managers cannot grant tokens) |

For group membership/update, GATE 2 degenerates to "is the *target group* in `managed`?" (the resource *is* the
group). For resource writes it is the full `current ∪ requested ⊆ managed` + private check.

**Bulk/list endpoints:** any endpoint accepting multiple resource ids must run GATE 2 **per item**, not on the
first/aggregate (e.g. batch cc_pair group edits).

> **D2 (decided): managers cannot create top-level groups.** Only admins create groups; managers manage the
> groups assigned to them. Group *create* keeps the plain global `MANAGE_USER_GROUPS` dependency (no
> `allow_scope`); `allow_scope=True` applies only to group *update / members*. No manager-creates-manager
> self-grant path to reason about.

---

## 5. PAT composition (§8.5) — minimal change

PAT scopes already cap permissions (`request.state.token_scopes` → `require_permission`, `permissions.py:278`;
model `db/pat.py`). A manager's **group** scope is never encoded in the token — it always comes from live
`is_manager`. Therefore:
- Permissions: effective = (manager bundle ∩ token_scopes) — the existing token cap already does the
  intersection; no change needed.
- Groups: GATE 2 runs regardless of PAT and bounds to live managed groups — a token cannot widen it.

**No PAT schema change.** Add only tests proving a scoped PAT cannot widen group reach.

---

## 6. API surface changes

- **`GET /users/me/permissions`** (`permissions.py` API) — add `is_manager: bool` (true if the user manages any
  group) so the frontend can reveal manager-relevant nav. Optionally `managed_group_ids: list[int]`. Keeps the
  endpoint the single "what can I do?" source.
- **New EE endpoint** — `PUT /manage/admin/user-group/{group_id}/manager` `{user_id, is_manager}` →
  `make_group_manager`/`revoke_group_manager`. Dep: `require_permission(MANAGE_USER_GROUPS, allow_scope=True)`.
  **D3 (decided): admin or manager-of-that-group may assign** — GATE 2 on this endpoint = admin **or**
  `group_id ∈ get_scoped_groups(actor)`. A manager can thus delegate management within their own group;
  assignment of a manager outside the actor's managed groups is rejected. The target `user_id` must already be a
  member of `group_id` (a manager is always a member) — else 400.

---

## 7. Frontend

- `web/src/lib/.../usePermissions` (and `hasPermission`) — consume the new `is_manager` flag; treat a manager as
  holding the scoped `manage:*` tokens **for nav/visibility only** (real enforcement is backend GATE 2).
- Sidebar (`Connectors`/`Document Sets`/`Groups`) shows for managers.
- **Group detail page** — per-member "Make Manager" / "Revoke Manager" toggle (mirrors the old "Make Curator"
  affordance), calling the new endpoint. Files under `web/src/app/ee/admin/groups/[groupId]/`.
- The list pages already call backend list endpoints whose filters now return the manager-scoped set — no
  client-side scoping logic needed (and must not be relied on for security).

---

## 8. New files & file tree

```
backend/
  onyx/
    auth/
      scoped_permissions.py            ← NEW: SCOPED_MANAGER_PERMISSIONS, scoped_group_ids_subquery,
                                              get_scoped_groups, has_permission_or_scope,
                                              assert_group_set_within_scope, within_managed_scope_clause
    auth/permissions.py                ← MOD: require_permission(..., allow_scope=False)
    db/models.py                       ← MOD: User__UserGroup.is_manager
    db/document_set.py                 ← MOD: _add_user_filters editable manager branch (was sa_false)
    db/connector_credential_pair.py    ← MOD: filter + add_credential_to_connector gate
    db/persona.py                      ← MOD: filter + create_update_persona gate
    db/feedback.py                     ← MOD: filter
    db/credentials.py                  ← (no change — documented no-op)
    server/.../{document_set,connector,cc_pair,persona}/api.py  ← MOD: allow_scope=True deps
    server/.../permissions api         ← MOD: /users/me/permissions adds is_manager
  ee/onyx/
    db/user_group.py                   ← MOD: make/revoke_group_manager + gates in update/add_users
    db/persona.py                      ← MOD: update_persona_access gate
    db/token_limit.py                  ← MOD: managed-scope enforcement on group token-limit writes
    server/user_group/api.py           ← MOD: allow_scope deps + NEW manager-assign endpoint
  alembic/versions/
    4fa09af6ca14_add_is_manager_to_user__user_group.py   ← NEW migration
web/
  src/app/ee/admin/groups/[groupId]/   ← MOD: manager toggle UI
  src/lib/.../usePermissions(.ts)      ← MOD: is_manager flag
  src/.../hasPermission(.ts)           ← MOD: manager nav visibility
```

---

## 9. Pre-implementation notes (must honor)

1. **GATE 2 is the authorization of record.** Route gate (`allow_scope`) only widens *reachability*; never let
   it authorize. Every scoped write path must call `assert_group_set_within_scope`.
2. **Re-read current groups in-txn.** Never trust the client's group list alone (capture-by-reassign).
3. **PRIVATE-only.** Reject any manager create/edit that sets/keeps PUBLIC or SYNC.
4. **Fail closed.** Empty managed set ⇒ no access; guard every filter against an unfiltered fallback.
5. **`set_group_permissions` stays admin-only.** Managers manage membership + resource sharing, never the
   group's token grants.
6. **Bulk endpoints check every item.**
7. **Keep the bundle out of `effective_permissions.global`.** Never persist scoped tokens; resolve live.
8. **Migration before drops.** Backfill `is_manager` before any later release drops `role`/`is_curator`.
9. **Credentials unchanged.** Owner-scoped; deliberately no manager inheritance.
10. **Tracing / OnyxError / typing conventions** per CLAUDE.md (raise `OnyxError`, strict typing, no
    `response_model`).

## 10. Decisions resolved at GATE 2

- **D1 → cache the boolean.** New cached `user.is_group_manager` (sibling to `effective_permissions`, not inside
  it), recomputed on membership change and on manager flip; route gate reads it with zero queries. The managed
  **list** stays live. (§1.1b, §2.3, §2.6.)
- **D2 → admins only create groups.** Group create keeps global `MANAGE_USER_GROUPS`; `allow_scope` only on
  group update/members. (§4 table, note.)
- **D3 → admin or manager-of-that-group assigns managers.** Manager-assign endpoint gates on
  `admin ∨ group_id ∈ managed`. (§6.)
