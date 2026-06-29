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

`backend/alembic/versions/c71a18ea7d07_add_is_manager_and_is_group_manager.py`
(revision `c71a18ea7d07`, **down_revision `c8e316473aaa`**).
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
    Permission.MANAGE_SKILLS,        # NEW dedicated token (D5) — also grantable globally in the groups UI
    Permission.MANAGE_ACTIONS,       # tools/MCP — in the bundle for GATE 1 reach; scoped via agents at GATE 2 (D4)
})
```
Code-defined, never written to `permission_grant`. Expanded live; never merged into
`effective_permissions` (which stays global-only).

> **`MANAGE_ACTIONS` is in the bundle (D4), scoped via agents.** It must be — GATE 1
> (`has_permission_or_scope`) would 403 a scoped manager on every action endpoint otherwise. "Agent-mediated"
> describes GATE 2's scope resolution, not bundle membership: the route gate lets the manager *reach* the
> tool/MCP endpoints; GATE 2 derives an action's groups from the agents that reference it
> (`Tool → Persona__Tool → Persona__UserGroup`) and requires them ⊆ managed. See §11.1.

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
must call `recompute_user_permissions__no_commit([user_id], db_session)` for the affected user so a pure
manager flip (no membership change) refreshes the cached flag. `effective_permissions` content is unchanged (global tokens only).

---

## 3. Filter rewrites — the `_add_user_filters` set

> **Superseded by §11.4/§11.7** (regression review): the real set is **4 re-keyed filters** (connector,
> document_set, persona, **skill**) + the `token_limit` write-path. Credentials AND **feedback** are
> unchanged (no feedback permission in the bundle). The table below still applies row-by-row except the
> feedback row, which is now NO CHANGE.

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
| `backend/onyx/db/feedback.py:46` | admin-only (`FULL_ADMIN_PANEL_ACCESS`) | **NO CHANGE** — not in the bundle; admin-only. (§11.7 — the old "mirror connector" label was wrong.) |
| `backend/onyx/db/credentials.py:41` | owner-keyed (`Credential.user_id==user.id`), no `get_editable` | **NO CHANGE** — credentials stay owner-scoped by design; a manager never inherits others' credentials. Document the deliberate no-op. |
| `backend/ee/onyx/db/token_limit.py` | no `_add_user_filters`; direct group query | enforce managed-scope in the group-token-limit **write/endpoint** path (manager may set limits only on managed groups). Minor. |

**Fail-closed rule for every rewrite:** if `scoped_group_ids_subquery` yields no rows, the manager branch must
resolve to empty, never to an unfiltered statement.

---

## 4. Write-path gate insertions (where GATE 2 is called)

> **Superseded by §11.4** (regression review): the table below under-enumerates the manager-reachable
> writes. §11.4 is the complete list (cc_pair status/name/property/prune, persona `/share`, group rename,
> `/agents` attach, skills) with the **delete = admin-only (D6)** rule and the persona-gate fix (§11.5)
> and cc_pair-reattach fix (§11.6). Use §11.4 as the source of truth.

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
- The resource list pages (connectors / doc-sets / agents / skills) call backend list endpoints whose
  filters now return the manager-scoped set — no client-side scoping logic needed (and must not be relied on
  for security). **Exception: the GROUP list is NOT auto-scoped** — `fetch_user_groups` returns all groups
  and needs a manager-scoped variant (§11.9) before the Groups page / assign-toggle UI work for managers.

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
    db/models.py                       ← MOD: User__UserGroup.is_manager + User.is_group_manager
    db/permissions.py                  ← MOD: recompute_user_permissions__no_commit sets is_group_manager (§11.7)
    db/document_set.py                 ← MOD: _add_user_filters editable manager branch (was sa_false)
    db/connector_credential_pair.py    ← MOD: filter + add_credential_to_connector gate
    db/persona.py                      ← MOD: filter + update_persona_access gate (MIT twin, §11.5)
    db/skill.py                        ← MOD: scoped admin-list path + replace_skill_grants GATE 2 (§11.2)
    db/feedback.py                     ← (no change — admin-only, not in bundle; §11.7)
    db/credentials.py                  ← (no change — documented no-op)
    server/features/skill/api.py       ← MOD: re-point off curator dep; allow_scope by verb (§11.2)
    server/features/tool/api.py        ← MOD: allow_scope=True; agent-mediated GATE 2 replaces owner-or-admin (§11.1)
    server/features/mcp/api.py         ← MOD: allow_scope=True; agent-mediated GATE 2 replaces owner-or-admin (§11.1)
    db/tools.py                        ← MOD: agent-mediated action scope (Tool→Persona__Tool→groups, §11.1)
    server/.../{document_set,connector,cc_pair,persona}/api.py  ← MOD: allow_scope=True deps
    server/.../permissions api         ← MOD: /users/me/permissions adds is_manager
  ee/onyx/
    db/user_group.py                   ← MOD: make/revoke_group_manager + gates in update/add_users
    db/persona.py                      ← MOD: update_persona_access gate
    db/token_limit.py                  ← MOD: managed-scope enforcement on group token-limit writes
    server/user_group/api.py           ← MOD: allow_scope deps + NEW manager-assign endpoint
  alembic/versions/
    c71a18ea7d07_add_is_manager_and_is_group_manager.py  ← NEW migration (down_revision c8e316473aaa)
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

---

## 11. Regression-review resolutions — full case coverage (verified 2026-06-29)

A 5-dimension adversarial review against `new-permission-system` (PAT · admin-retrieval · chat ·
junction-only · completeness, 18 agents) confirmed the core design is sound — PAT cap preserved, chat
runtime untouched, purely junction-based, and the feared backfill data-loss does **not** occur — but found
that §1–10 under-specify several manager-reachable paths. **This section is the authoritative coverage
checklist; implement every row.** New decisions locked with the owner: **D4 actions = `manage:actions` in the
bundle, scoped via agents at GATE 2** · **D5 skills = in scope (7th resource)** · **D6 managers may do
everything EXCEPT delete**.

### 11.0 PREREQUISITE — independent boot bug (fix before/with PR1)
`current_curator_or_admin_user` was removed from `onyx/auth/users.py` by §1–7 but is still imported by
`server/features/skill/api.py:16` and `server/documents/targeted_reindex.py:22` → `import onyx.main` raises
`ImportError` and **the API server cannot boot on this branch** (verified at runtime). Re-point both off the
dead dep: skills → see §11.2; `targeted_reindex.py:80/163` → `require_permission(MANAGE_CONNECTORS)` (matches
its connector/indexing peers). This is a merge-integration break, not a §8 feature change, but it blocks
everything. Add an `import onyx.main` smoke test to CI so a deleted auth dep fails fast.

### 11.1 Actions (D4 — `MANAGE_ACTIONS` in the bundle; scoped via agents at GATE 2)
- **`MANAGE_ACTIONS` stays in `SCOPED_MANAGER_PERMISSIONS`** (§2.1). Bundle membership is what GATE 1
  (`has_permission_or_scope`) checks — drop it and a scoped manager 403s at the route on every action endpoint.
  "Agent-mediated" is GATE 2's scope resolution, not a reason to omit the token.
- **Reaching the endpoints (GATE 1):** switch the standalone tool/MCP admin endpoints (`tool/api.py`
  POST/PUT/DELETE, `mcp/api.py`) to `require_permission(MANAGE_ACTIONS, allow_scope=True)` so managers can reach
  them. (Delete stays admin-only per D6.)
- **Scope check (GATE 2):** actions have no direct group; derive an action's groups from the agents that
  reference it — `Tool → Persona__Tool → Persona__UserGroup` — and require them ⊆ managed (+ PRIVATE). This
  **replaces** the current owner-or-admin per-resource check (`_get_editable_custom_tool` /
  `_ensure_mcp_server_owner_or_admin`); keep owner/admin as a bypass.
- **Edge cases:** a tool used by agents spanning a group the manager doesn't manage → reject; a tool referenced
  by **no** agent → no group context → owner/admin only.
- Attaching existing catalog tools to an agent still flows through the persona path (`tool_ids` on
  `create_update_persona`, gated by `MANAGE_AGENTS` + the persona GATE 2) — unchanged.

### 11.2 Skills (D5 — in scope, 7th scoped resource) — REVISED per the GO/NO-GO review
Skills (`Skill__UserGroup` `models.py:4460`; `db/skill.py`) are group-shareable but **do NOT mirror personas
structurally** — the original "re-key the editable filter like personas" instruction was wrong. Five
corrections (verified 2026-06-29):
- **Dedicated `MANAGE_SKILLS` permission (owner decision — replaces the "reuse MANAGE_AGENTS" idea).** Add
  `Permission.MANAGE_SKILLS = "manage:skills"` to the enum + the permission **registry** (so it shows in the
  **groups permission UI** and is grantable to a group globally, like the other manage tokens) and to
  `SCOPED_MANAGER_PERMISSIONS` (so managers get it scoped). **No DB migration needed** —
  `permission_grant.permission` is `Enum(native_enum=False)` (stored as a string), so a new enum value is a
  pure code change. Admins get it automatically via the `FULL_ADMIN_PANEL_ACCESS` override. Don't put it in
  `NON_TOGGLEABLE_PERMISSIONS`. This removes the over/under-grant of reusing `MANAGE_AGENTS`.
- **Do NOT touch `_add_user_visibility_filter` (`skill.py:85`).** It has no editable/viewing split AND it feeds
  the agent RUNTIME — `list_skills_for_sandbox_injection` (`skill.py:250`) → `skills/push.py` → build-session
  sandbox hydration (`session/manager.py:386`, `session/api.py:438`). OR-ing a manager branch into it would
  widen which skills get injected into a manager's agent context at runtime — the exact leak the design
  deliberately closes (admins get NO bypass here on purpose, `skill.py:91-94`). **The manager predicate must
  NEVER enter this filter or any function reaching `push.py`/`session/*`.**
- **Read side = a NEW scoped ADMIN-LIST path.** `list_skills_for_admin` (`skill.py:260`) is `select(Skill)`
  with no filter — a re-pointed manager would see every skill in the tenant. Add a manager-scoped variant
  (`within_managed_scope_clause` over `Skill__UserGroup`, PRIVATE-only, fail-closed) used only when the caller
  is a non-admin scoped manager; leave the runtime/visibility filter byte-identical.
- **Write side = GATE 2 on the GRANTS seam, not create/update.** `create_skill__no_commit` takes no group_ids
  and `patch_skill` only toggles is_public/enabled; the only group↔skill writer is `replace_skill_grants`
  (`skill.py:430`, reached via PUT `/admin/skills/custom/{id}/grants`, body `GrantsReplace.group_ids`). Put
  GATE 2 there (current grants via `get_group_ids_for_skill` ∪ requested ⊆ managed, `is_private = not
  skill.is_public`, re-read in-txn). Also gate the `is_public` toggle in `patch_custom_skill` so a manager
  can't publish a private skill out of scope.
- **Endpoint re-point BY VERB.** list/get/create/update/share → `require_permission(MANAGE_SKILLS,
  allow_scope=True)`; **skill DELETE (`skill/api.py:320`, dep at `:322`) stays admin-only (D6) — exclude it
  from the re-point.** `Skill.is_public` + `Skill__UserGroup` exist, so GATE 2 is expressible. (PR0 parks the
  re-point on `FULL_ADMIN_PANEL_ACCESS` to unbreak boot; PR4 adds `MANAGE_SKILLS` + `allow_scope` + the GATE 2
  and admin-list together, then narrows the deps.)

### 11.3 Manager power = everything EXCEPT delete (D6)
Managers may create / edit / attach / detach / pause / rename / share within managed groups (PRIVATE-only,
GATE 2). **DELETE is admin-only for every resource.** These stay on the plain global dep (no `allow_scope`):
connector/cc_pair delete (`administrative.py:141`), document-set delete (`document_set/api.py:93`), persona
delete, skill delete; plus group create (D2) + group delete + `set_group_permissions` (admin-only).

### 11.4 Complete write-path enumeration (supersedes/extends the §4 table — gate EVERY row)
All `allow_scope=True` + GATE 2 EXCEPT where marked admin-only (D6/D2):

| Endpoint(s) | DB fn (GATE 2 site) | Treatment |
|---|---|---|
| cc_pair status `cc_pair.py:427` · name `:512` · property `:542` · prune `:604` | re-keyed editable read-filter authorizes (no group/access change) | allow_scope=True |
| associate-credential `cc_pair.py:716` · connector create mock-cred `connector.py:1568` · bare create `:1538` | `add_credential_to_connector` (`:496`) | allow_scope=True on **all**; the `connector.py:1603` anchor was imprecise (it's the mock-cred path) |
| ee `sync_cc_pair_groups` `cc_pair.py:130` | group-attach | allow_scope=True; GATE 2 per cc_pair |
| connector/cc_pair **DELETE** `administrative.py:141` | — | **admin-only (D6)** |
| doc-set create `document_set/api.py:36` · patch `:62` | `insert/update_document_set` (`:220/:296`) | allow_scope=True |
| doc-set **DELETE** `:93` | — | **admin-only (D6)** |
| persona create `persona/api.py:310` · update `:181` · **share `:443`** | `update_persona_access` (§11.5) | allow_scope=True; **GATE 2 keyed on `MANAGE_AGENTS` (D7)** — admin/global bypass; scoped managers ⊆ managed; ADD_AGENTS-only can't group-share |
| skill create/update `skill/api.py:186/...` | skill write fn (§11.2) | allow_scope=True; GATE 2 on `replace_skill_grants` |
| tool/MCP create/update `tool/api.py` · `mcp/api.py` | GATE 2 via agents (`Tool → Persona__Tool → Persona__UserGroup` ⊆ managed); replaces owner-or-admin check (§11.1) | allow_scope=True; **DELETE admin-only (D6)** |
| group update/members `user_group/api.py:194/215` · **rename `:164`** | `update_user_group` / `add_users_to_user_group` | allow_scope=True; GATE 2 = group ∈ managed; **cc_pair_ids per §11.6** |
| group `/agents` persona attach `user_group/api.py:256` | `update_persona_access` | allow_scope=True; **manager-scope GATE 2 = target group ∈ managed** (the roster surface) |
| group create `:144` · delete · permissions `:115` | — | **admin-only (D2)** |

### 11.5 Persona group-share = MANAGE_AGENTS-controlled (D7, owner decision 2026-06-29) + gate plumbing
**D7 — who may attach an agent to a group:** self member-share (sharing your own agent to a group) is
controlled by **`MANAGE_AGENTS`** — not `ADD_AGENTS`, not bare membership. So the group-share write is the
**standard GATE 2 keyed on `MANAGE_AGENTS`**, no special carve-out (the earlier membership framing is dropped):
- `has_permission(user, MANAGE_AGENTS)` (admin or a **global** `MANAGE_AGENTS` holder) → bypass; keeps today's
  self-share to their groups.
- else a **scoped manager** → allow only if target groups ⊆ `get_scoped_groups(user, MANAGE_AGENTS)` (managed),
  private. Managers hold `MANAGE_AGENTS` via the bundle.
- else (`ADD_AGENTS`-only) → reject the group-share. Such a user can still create/edit a private, **no-group**
  personal agent — they just can't attach it to a group.

> **Current-code nuance to enforce (PR4):** today the persona create/`/share` route gates on `ADD_AGENTS`
> (`persona/api.py:310/340/447`) and the share write authorizes via the **editable fetch** (owner/EDITOR/admin,
> `update_persona_shared:434`), **not** `MANAGE_AGENTS` — so group-share isn't `MANAGE_AGENTS`-gated yet. PR4
> adds the `MANAGE_AGENTS` requirement on the group-share write via GATE 2 (`permission=MANAGE_AGENTS`). The
> route stays `ADD_AGENTS` (so users can still make personal agents) + `allow_scope=True` so scoped managers
> reach it. This is a small, intended tightening of who can put an agent into a group.

Plumbing (review-F2/F4/BR-3): thread the acting `user: User` into `update_persona_access` from all callers
(`create_update_persona` `persona.py:384`, `update_persona_shared` `persona.py:472`, `update_group_agents`
`user_group/api.py:269/281`); apply to BOTH `onyx/db/persona.py:273` (MIT) and `ee/onyx/db/persona.py:68` (EE);
re-read current groups + `is_public` in-txn (don't trust caller flags). `is_public` stays owner/admin-gated
(unchanged — `update_persona_shared`'s `is_owner_or_admin`). The group `/agents` roster surface uses the same
manager-scope GATE 2 (target group ∈ managed) — §11.4.

### 11.6 Group-update cc_pair re-attach is an escalation vector (closes review-F4)
`update_user_group` (`ee/user_group.py:551-562`) rewrites the group↔cc_pair junction from a client
`cc_pair_ids` list, bypassing the gated `add_credential_to_connector`. "group ∈ managed" does **not**
validate those cc_pairs → a manager could attach a public/out-of-scope connector to their group.
**Resolution:** when a scoped manager edits a managed group, run GATE 2 **per added cc_pair** (each within
managed scope + PRIVATE); reject otherwise. Admins unaffected (global bypass).

### 11.7 Filter & recompute corrections
- **Feedback `db/feedback.py:46` → NO CHANGE.** No feedback permission exists in the bundle and its editable
  gate is `FULL_ADMIN_PANEL_ACCESS` (admin-only). Leave it like `credentials.py`; the §3 "mirror connector"
  label was wrong. Real re-keyed filters are **4** (connector, document_set, persona, **skill**) + the
  `token_limit` write-path; credentials + feedback unchanged. ("6 filters" was a miscount.)
- **`recompute_user_permissions__no_commit` (`db/permissions.py:43`) signature is `(user_ids, db_session)`** —
  the §2.6 one-arg call is wrong. Extend the fn to also set `user.is_group_manager = EXISTS(is_manager)` in
  the same txn; `make/revoke_group_manager` call it as `([user_id], db_session)`.

### 11.8 Confirmed SAFE — no action (the three core worries)
- **PAT:** token cap (`permissions.py:278`) preserved verbatim; `allow_scope` only swaps the user-side
  conjunct and only on opt-in routes; GATE 2 never reads the token → a scoped PAT can only narrow, never
  widen group reach. Default `allow_scope=False` path is byte-identical to today. Implementation invariants:
  keep `dependency._is_require_permission = True` unconditional (`permissions.py:288`); keep the default
  path calling `has_permission` directly.
- **Chat:** answer hot path reads `chat_session.persona` (ORM, `process_message.py:635`); all runtime reads
  use `get_editable=False`; GATE 2 never on the send path; `get_acl_for_user` untouched. Invariant: keep all
  filter edits inside the `if get_editable:` block as correlated subqueries — do not perturb the shared joins
  above the split.
- **Junction-only:** scope is purely `User__UserGroup.is_manager` + resource↔group junctions;
  `permission_grant` stays global-only; Vespa ACL untouched. Backfill is safe — no upgrade migration nulls
  `role`, and `native_enum=False` stores `'CURATOR'`/`'GLOBAL_CURATOR'` literally. Ship the
  zero-managed-group migration report for the GLOBAL_CURATOR snapshot caveat.

### 11.9 Group LIST must be scoped (closes the group-list gap)
`fetch_user_groups` (`ee/user_group.py:188`) returns ALL groups with no user/`is_manager` filter, and
`list_user_groups` (`user_group/api.py:46`) is the list the Groups admin page AND the §6 manager-assign
toggle UI depend on. So the §7 claim "list pages already return the manager-scoped set" is **false for
groups** — `MANAGE_USER_GROUPS` is in the bundle but the group list is not one of the re-keyed filters.
Resolution: add a manager-scoped group-list variant filtered by `User__UserGroup.is_manager` (NOT membership),
switch `list_user_groups` (and the single-group/member-list reads the toggle UI needs) to `allow_scope=True`
returning only managed groups for a scoped manager; admins keep the full list. Without this a scoped manager
either 403s on the Groups page (feature unusable) or sees every org group (leak). Correct the §7 wording.

### 11.10 Doc-consistency reconciliations (mechanical)
- **§8 file tree + PR4 file table:** flip `db/feedback.py` to no-op; ADD `db/skill.py` (filter + grants GATE 2)
  and `server/features/skill/api.py` (re-point); ADD `User.is_group_manager` to the models.py line and
  `db/permissions.py` (recompute) — these are the artifacts implementers slice from.
- **§11.0 tokens:** `targeted_reindex.py:80/163` → `require_permission(MANAGE_CONNECTORS)` (matches connector
  peers; independent of the skills token). Skills token per §11.2.
- **D6 delete invariant:** deletes stay admin-only **only** because their route gate keeps `allow_scope=False`
  — the re-keyed editable filter would otherwise authorize a manager. Never add `allow_scope=True` to a DELETE
  route; add an escalation test asserting each DELETE 403s a scoped-only manager. (Persona delete is already
  owner/owner-group gated via `get_persona_by_id`, not `_add_user_filters`, so PR4 doesn't open it.)
- Stale prose to fix: "6 filters" → 4 re-keyed + skill (`00:14`, `01:52/64`, `02` ASCII); `§2.6` call →
  `([user_id], db_session)`; `§3` feedback row → NO CHANGE.
