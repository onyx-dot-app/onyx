> Status: active · Task: group-manager-scoped-permissions

# §8 Scoped Permissions (Group Manager) — Research

> **Historical research.** Final primitive names/shapes differ — see [03 §2](03-detailed-design.md):
> `has_permission` returns `PermissionAuthority` (the one classifier; the proposed `has_permission_or_scope`
> was folded into it), and the write gate is `assert_within_scope` / `assert_global` (not
> `assert_group_set_within_scope`). The names below reflect the original investigation, not the shipped API.

## Requirement

Implement **§8 of the Group-Based Permissions System V2** solution design — the **Group Manager**
(scoped-permissions) layer — on the `new-permission-system` branch. A Group Manager is a user given
admin-like control over a **single group's** resources and members, and nothing outside it.

Source of truth: wiki `Engineering Projects/Group-Based Permissions System V2/solution-design.md` §8.

## Clarifications

| Question | Answer |
|---|---|
| How should this run treat §8's design? | **Adopt the wiki §8 model as-is** (chosen approach is locked — no approach generation). The 2026-06-23 46-agent adversarial review already settled the design; §8 was rewritten to the FINAL model on 2026-06-24. |
| Scope | All of §8 (§8.1–§8.5): the `is_manager` flag + migration, the scoped-permission bundle, live scope resolution, two-gate enforcement, filter re-keying, PAT intersection, and the Group-Manager assignment UI. |

## Current status & reuse (from codebase scan — `OnyxFolder/onyx`, branch `new-permission-system`)

### §8 is entirely greenfield — every artifact ABSENT

| §8 artifact | Status | Evidence |
|---|---|---|
| `is_manager` column on `User__UserGroup` | ABSENT at research time → **BUILT (PR1)** | now on `User__UserGroup`; `User.is_group_manager` cached flag added too |
| Alembic migration (`is_manager` add/backfill) | ABSENT at research time → **BUILT (PR1) as `c71a18ea7d07`** | down_revision `c8e316473aaa`, now head; placeholder `4fa09af6ca14` never used |
| `SCOPED_MANAGER_PERMISSIONS` bundle | ABSENT | no match in backend |
| `get_scoped_groups()` resolver | ABSENT | no match |
| `assert_group_set_within_scope` / `can_act_on_resource` write-side gate | ABSENT | no match |
| `make_group_manager` / `revoke_group_manager` | ABSENT | no match |
| `has_permission_or_scope` route-gate variant | ABSENT | only plain `has_permission` — `backend/onyx/auth/permissions.py:252` |
| `is_manager` boolean inside `effective_permissions` | ABSENT | `effective_permissions` is `Mapped[list[str]]` tokens only — `models.py:375` |
| Group-Manager assignment UI (web) | ABSENT | no manager UI under `web/src/app/(ee/)admin/groups*` |
| PAT scope-intersection w/ manager scope | ABSENT | `backend/onyx/db/pat.py` scopes are flat permission tokens |

> **⚠ Status (updated):** at research time §8 was entirely unbuilt and the wiki's *"Implemented as revision
> `4fa09af6ca14`"* was wrong. Since then **PR0+PR1 shipped** (migration `c71a18ea7d07`); scoped enforcement
> (PR2+) is still not-yet-built.

### Base system (§1–7) — FULLY BUILT (the foundation §8 extends)

| Building block | Path |
|---|---|
| `AccountType` enum (STANDARD/BOT/EXT_PERM_USER/SERVICE_ACCOUNT/ANONYMOUS) | `backend/onyx/db/enums.py:7-28` |
| `account_type` column on `User` | `backend/onyx/db/models.py:324-329` |
| `Permission` enum (token set) | `backend/onyx/db/enums.py:490-549` |
| `PermissionGrant` model (`(group_id, permission)` unique) | `backend/onyx/db/models.py:4371-4391` |
| `require_permission(...)` FastAPI dep | `backend/onyx/auth/permissions.py:257-289` |
| `has_permission(...)` (non-FastAPI) | `backend/onyx/auth/permissions.py:252` |
| `resolve_effective_permissions()` + `IMPLIED_PERMISSIONS` | `backend/onyx/auth/permissions.py:214-231`, `:32-71` |
| `get_effective_permissions()` (reads `User.effective_permissions`) | `backend/onyx/auth/permissions.py:234-249` |
| 6× `_add_user_filters` (token-based, **no** `role`/`is_curator`) | `connector_credential_pair.py:50`, `persona.py:77`, `document_set.py:41`, `credentials.py:41`, `feedback.py:46`, EE `token_limit.py` |
| `User__UserGroup` membership model (where `is_manager` lands) | `backend/onyx/db/models.py:~4361` |
| PAT model | `backend/onyx/db/pat.py` |

### Residual tombstones (kept by design; §8 reuses / must not break)

- `role` column + `UserRole` enum — `models.py:320-323` (nullable, "Legacy tombstone").
- `is_curator` column on `User__UserGroup` — `models.py:4361` (to be **repurposed** as `is_manager`).
- 3 surviving `user.role == UserRole.ADMIN` readers: `persona_sharing.py:53`, `build_session.py:638`,
  `search/api.py:104`. These block dropping `role`; **out of scope** for §8 (deferred cleanup release).

**Reuse posture:** §8 adds one column, one code-defined permission bundle, a handful of resolver/gate helpers,
and re-keys ~4 editable filters (connector, document_set, persona, skill — credentials + feedback unchanged;
see [03 §11.7](03-detailed-design.md)) from "membership" to "managed groups." It does **not** add tables, does
**not** touch `permission_grant` (stays global-only), and does **not** add a second auth round-trip.

## Industry best practices (backing for the locked design)

The chosen model maps to established scoped-RBAC patterns (validated in the prior adversarial review):

- **Role binding, not a permission row** — Group Manager = a binding of a *role* to a (user, group) edge, like
  Kubernetes `RoleBinding` (namespace-scoped) vs `ClusterRoleBinding` (global). A role ≠ an atomic permission
  (NIST RBAC, k8s, Google Zanzibar all keep permissions atomic and bind roles separately). → §8 keeps the
  manager bundle out of `permission_grant`.
- **Permission boundaries narrow, never widen** — AWS IAM permission boundaries / SCPs cap effective access; a
  scoped principal can only intersect. → §8.5 PAT intersection: a scoped token can only narrow, never widen.
- **Resolve scope live; don't materialize it** — Azure scoped RBAC and Zanzibar resolve the scope set at check
  time from the relationship graph rather than caching a denormalized list, avoiding stale-after-move bugs. →
  §8.1 caches only an `is_manager` boolean; the managed-group **list** is resolved live per request.
- **Authorization of record at the write, not the route** — defense-in-depth / "don't trust the client's
  object list": the mutating layer must re-read the resource's current owners and re-check, because the route
  filter only hides things from the UI. → §8.2 per-resource gate runs inside the DB write.

## Chosen approach — the locked wiki §8 model

**One-line:** a Group Manager is a single boolean `is_manager` on the membership row; their abilities are a
code-defined bundle applied **only** to the groups they manage; scope is resolved **live**; and every manager
action passes **two gates** — a coarse route gate (cached) and a per-resource write-side gate (authoritative).

### The five pillars

1. **Who** — `is_manager` boolean on `user__user_group` (repurposes the dead `is_curator` column). No new
   table, no new row. Semantically a role binding on the membership edge.
2. **What** — `SCOPED_MANAGER_PERMISSIONS = {manage:connectors, manage:document_sets, manage:agents,
   add:agents, manage:user_groups}`, expanded live at resolve time, applied only to managed groups.
   **Never** merged into `effective_permissions.global`. (Per the 2026-06-29 review — D4 — `manage:actions`
   **stays in the bundle** so GATE 1 admits managers; scope is resolved at GATE 2 via the agents that
   reference the action. Skills are added as a 7th scoped resource under a new dedicated `manage:skills`
   token (D5). See [03 §11](03-detailed-design.md).)
3. **Cached vs live** — `User.effective_permissions` carries global tokens **plus an `is_manager` boolean**
   (so the route gate needs no extra query). The managed-group **list** is read live by
   `get_scoped_groups(user)` (one indexed read on `user_id WHERE is_manager=true`) — never cached, so never
   stale.
4. **Two-gate enforcement:**
   - **Route gate** `has_permission_or_scope` — coarse, cached; lets a manager *reach* the endpoint. Can only
     reject; never authorizes.
   - **Per-resource gate** `assert_group_set_within_scope` — the authorization of record; runs **inside the
     write**, re-reads the resource's current groups in-transaction, allows only if the resource ends up in
     **≥1 managed group, none outside, and PRIVATE**.
5. **What a manager can/can't do** — create/edit/attach/detach resources fully inside managed groups; add/remove
   members of managed groups. **Cannot** edit a group's permissions, act on out-of-scope resources, or make
   anything PUBLIC/SYNC. Admins bypass all of it.

### Carried-in must-fixes / confirmed risks (from the 46-agent review — design inputs, not open questions)

These are already folded into the locked design; the implementation must honor each:

1. **Write-side gate is mandatory & centralized.** Put `assert_group_set_within_scope` inside *every*
   group-mutating DB fn (`add_users`, `update_group`/agents, resource group-attach). Route gate is only a
   pre-filter. `set_group_permissions` stays **admin-only** (a manager cannot grant tokens).
2. **PUBLIC/SYNC is an orthogonal axis** — scoped managers are **PRIVATE-only**; reject any create/edit that
   sets or keeps `access_type` PUBLIC or SYNC.
3. **Filters key on managed groups, not membership** — `get_scoped_groups`, not "all of the user's groups."
   Filters are heterogeneous (e.g. document_set editable filter is `sa_false()` today and must be built).
4. **Fail closed on empty scope** — empty managed-group set ⇒ no access, never "no filter"; guard against
   `IN ()` / dropped `WHERE` matching everything.
5. **Don't trust "they can't see it"** — a direct API call by resource ID bypasses the listing filter; the
   write must load the resource's **current** groups, not just the client-supplied new set (capture-by-reassign
   attack, e.g. `PUT /connector/<Finance id> {groups:[Engineering]}`).
6. **Bulk/list endpoints check every item**, not the first or the aggregate.
7. **Live resolution kills the staleness class** — no pre-expansion / materialization of scoped perms; resolve
   at check time (deletes pre-expansion staleness + `@validates` divergence + write-time fan-out).

### Migration (the disappearing-tombstone trap — §6.1.1 / §6.1.2)

- Backfill `is_manager` is **not a rename** — `is_curator` alone misses GLOBAL_CURATOR (they have no
  per-group `is_curator` rows). Compute it:
  - `is_manager=true` where `is_curator=true` **AND** `user.role='CURATOR'`;
  - `is_manager=true` on **every** membership where `user.role='GLOBAL_CURATOR'`.
- Must run **before** `role` is dropped, or GLOBAL_CURATOR is lost permanently (the `account_type` backfill
  already collapsed CURATOR/GLOBAL_CURATOR→STANDARD, so `role`+`is_curator` are the only surviving signal).
- Migration goes in `backend/alembic/versions/` (tenant schema), **not** `alembic_tenants/`.
- Ship **additive only** with the feature (add column + backfill + reuse existing `ix_user__user_group_user_id`);
  **defer** dropping `is_curator`/`role` to a later cleanup release (rollback-safe; not GA).
- Emit a per-user migration report flagging any CURATOR/GLOBAL_CURATOR mapping to **zero** managed groups
  (snapshot caveat — GLOBAL_CURATOR was dynamic; migrated set does not auto-extend to groups joined later).

## Chosen approach

**Locked: the wiki §8 settled model above** (user selected "Adopt wiki §8 as-is"). No competing approaches
generated — the design was already settled by the 2026-06-23 adversarial review. Proceed to high-level design.
