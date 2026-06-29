> Status: active · Task: group-manager-scoped-permissions · Source plan: 04-implementation-plan.md

# §8 Scoped Permissions (Group Manager) — PR Roadmap

Six PRs, dependency-ordered. **Safety invariant:** every enforcement PR lands its read-filter + write-side gate
+ endpoint `allow_scope` switch **together** — a manager can never reach an endpoint before its GATE 2 exists, so
there is no escalation window at any merge boundary. (Pre-GA branch: existing curators were already collapsed to
STANDARD by the `account_type` backfill, so no live capability is regressed while enforcement lands incrementally.)

## Overview

| PR | Title | Est. LOC | Depends on | Key deliverable |
|----|-------|----------|------------|-----------------|
| 1 | `feat(perms): add is_manager + is_group_manager columns and backfill` | ~220 | — | Schema + role-gated migration + cached-flag recompute |
| 2 | `feat(perms): scoped-manager authorization primitives` | ~330 | 1 | `scoped_permissions.py` (bundle, gates, scope helpers) + `require_permission(allow_scope)` — inert |
| 3 | `feat(perms): scope connectors & document sets to group managers` | ~520 | 2 | Two-gate enforcement end-to-end on cc_pairs + doc sets (walking skeleton) |
| 4 | `feat(perms): scope agents, feedback & token limits to group managers` | ~460 | 2 | Persona/feedback/token-limit enforcement + scoped-PAT tests |
| 5 | `feat(perms): group-manager assignment & membership scoping` | ~400 | 3,4 | make/revoke + assign endpoint (D3) + membership gates + `/me/permissions.is_manager` |
| 6 | `feat(perms): group-manager assignment UI & scoped nav` | ~370 | 5 | Group-detail Make/Revoke toggle + manager nav visibility + Playwright |

## Sequence

```
PR1 (schema+migration+recompute)
  └─▶ PR2 (auth primitives — inert)
        ├─▶ PR3 (connectors + doc sets enforcement)  ┐
        └─▶ PR4 (agents + feedback + token limits)   � both build on PR2 only; mergeable in either order
                                                      ▼
                                          PR5 (assignment + membership scoping)
                                                      ▼
                                          PR6 (frontend)
```

Walking skeleton = PR1→PR2→PR3: after PR3 the full two-gate model is provably working on the two
highest-value resource types, exercised by the escalation integration suite (managers seeded via fixture).

---

## PR 1 — Schema foundation: `is_manager` + cached flag + backfill
- **Goal:** add the only new state §8 needs and preserve the curator signal before it can be lost.
- **Scope (in):** `User__UserGroup.is_manager`; `User.is_group_manager` (cached route-gate flag); migration
  `4fa09af6ca14` (down_revision `c8e316473aaa`, role-gated backfill capturing CURATOR + GLOBAL_CURATOR, then
  `is_group_manager` backfill); extend `recompute_user_permissions__no_commit` to recompute the cached flag.
- **Out of scope:** any reader of the new columns (they're inert this PR); dropping `is_curator`/`role`.
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `backend/onyx/db/models.py` | modified | 2 boolean columns (`User__UserGroup`, `User`) |
  | `backend/alembic/versions/4fa09af6ca14_*.py` | new | add columns + role-gated backfill |
  | `backend/onyx/db/permissions.py` | modified | recompute sets `is_group_manager` |
  | `backend/tests/external_dependency_unit/.../test_is_manager_backfill.py` | new | backfill correctness |
- **Est. size:** ~220 LOC
- **Depends on:** —
- **Feature-flag state:** N/A — additive, columns unread until PR3+.
- **Tests on merge:** external-dependency unit — CURATOR(+is_curator)→manager; zero-`is_curator` GLOBAL_CURATOR
  captured on all memberships; `is_group_manager` mirrors; fresh-install all-false.
- **Drift checkpoint:** confirm `c8e316473aaa` is still head; confirm the pre-GA assumption (curators already
  collapsed to STANDARD) still holds so migrated `is_manager` bits are dormant, not a silent re-grant. If §6.1.1
  snapshot caveat matters operationally, decide whether the zero-managed-group report ships now or later.

## PR 2 — Authorization primitives (inert core)
- **Goal:** land the reusable scope logic and the route-gate extension with no behavior change.
- **Scope (in):** new `backend/onyx/auth/scoped_permissions.py` — `SCOPED_MANAGER_PERMISSIONS`,
  `scoped_group_ids_subquery`, `get_scoped_groups`, `has_permission_or_scope` (reads cached flag),
  `within_managed_scope_clause`, `assert_group_set_within_scope`; extend `require_permission(allow_scope=False)`.
- **Out of scope:** wiring any endpoint/filter to them (PR3+).
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `backend/onyx/auth/scoped_permissions.py` | new | bundle + scope helpers + both gates |
  | `backend/onyx/auth/permissions.py` | modified | `require_permission(..., allow_scope)` |
  | `backend/tests/external_dependency_unit/.../test_scoped_permissions.py` | new | gate logic + clause SQL |
- **Est. size:** ~330 LOC
- **Depends on:** PR 1
- **Feature-flag state:** N/A — nothing calls these yet.
- **Tests on merge:** unit/external-dependency unit — `assert_group_set_within_scope` invariants (⊆ managed,
  non-empty, private, fail-closed, admin/global bypass); `within_managed_scope_clause` selects the right rows.
- **Drift checkpoint:** confirm the §8.1 bundle membership (esp. `manage:actions`, `manage:user_groups`) is still
  the agreed manager ability set; confirm `require_permission`'s token-cap branch is unchanged since `03`.

## PR 3 — Enforce scope on connectors & document sets (walking skeleton)
- **Goal:** prove the full two-gate model end-to-end on the two highest-value resources.
- **Scope (in):** rewrite editable filters in `connector_credential_pair.py` and `document_set.py` (the latter
  built from today's `sa_false()`) onto `within_managed_scope_clause`; insert `assert_group_set_within_scope` in
  cc_pair create/update + doc-set create/update DB fns (re-reading current groups in-txn); switch those endpoints
  to `require_permission(<token>, allow_scope=True)`; resolve `get_scoped_groups` once per request on bulk paths.
- **Out of scope:** agents/feedback/token-limit (PR4); membership/assignment (PR5); UI (PR6).
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `backend/onyx/db/connector_credential_pair.py` | modified | filter re-key + create/update gate |
  | `backend/onyx/db/document_set.py` | modified | filter rebuild + create/update gate |
  | `backend/onyx/server/documents/{connector,cc_pair}.py` | modified | `allow_scope=True` deps |
  | `backend/onyx/server/features/document_set/api.py` | modified | `allow_scope=True` deps |
  | `backend/tests/integration/.../test_group_manager_resources.py` | new | escalation suite (these two) |
- **Est. size:** ~520 LOC
- **Depends on:** PR 2
- **Feature-flag state:** N/A — safe by the lands-together invariant; managers seeded via fixture for tests.
- **Tests on merge:** integration — capture-by-reassign rejected; PUBLIC/SYNC rejected; fail-closed empty scope;
  bulk per-item; happy paths (create/edit/attach/detach within managed groups) succeed.
- **Drift checkpoint:** confirm the cc_pair update path that sets groups/access (file may differ from `03`'s
  guess `server/documents/cc_pair.py`) — locate the actual group/access setter before coding. Confirm doc sets
  still use `is_public` (not an `access_type`) for the private check.

## PR 4 — Enforce scope on agents, feedback & token limits
- **Goal:** extend the proven model to the remaining manager-scoped resources; verify PAT composition.
- **Scope (in):** persona filter + gate (`db/persona.py`, `ee/onyx/db/persona.py:update_persona_access`,
  `is_public`+`add:agents` ownership preserved); feedback editable filter re-key (`db/feedback.py`); managed-scope
  enforcement in EE `token_limit.py` group write path; `credentials.py` left unchanged (documented no-op);
  scoped-PAT tests.
- **Out of scope:** membership/assignment (PR5); UI (PR6).
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `backend/onyx/db/persona.py` | modified | filter + gate |
  | `backend/ee/onyx/db/persona.py` | modified | `update_persona_access` gate |
  | `backend/onyx/db/feedback.py` | modified | editable filter re-key |
  | `backend/ee/onyx/db/token_limit.py` | modified | managed-scope on group token-limit writes |
  | `backend/onyx/server/.../persona api` | modified | `allow_scope=True` deps |
  | `backend/tests/integration/.../test_group_manager_agents.py` | new | agent escalation + PAT narrowing |
- **Est. size:** ~460 LOC
- **Depends on:** PR 2 (independent of PR 3)
- **Feature-flag state:** N/A — lands-together invariant.
- **Tests on merge:** integration — agent create/share scoped; manager can't widen a PAT's group reach; `add:agents`
  ownership tier still keyed on `Persona.user_id`; credentials remain owner-only for a manager.
- **Drift checkpoint:** confirm actions-via-agents assumption (no direct tool→group table) still holds; confirm
  the persona create/update endpoint path + that `manage:agents` is the right scoped token.

## PR 5 — Manager assignment & group-membership scoping (backend complete)
- **Goal:** let admins/in-group managers create managers, and scope membership edits; expose the flag to clients.
- **Scope (in):** `make_group_manager`/`revoke_group_manager` (`ee/onyx/db/user_group.py`) + recompute trigger;
  gates in `update_user_group`/`add_users_to_user_group` (`group_id ∈ managed`); `allow_scope=True` on group
  update/add-users endpoints; **new** `PUT …/user-group/{group_id}/manager` gated `admin ∨ group_id ∈ managed`
  (D3); group **create** + `set_group_permissions` left admin-only (D2); add `is_manager` (+`managed_group_ids`)
  to `GET /users/me/permissions`.
- **Out of scope:** frontend (PR6).
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `backend/ee/onyx/db/user_group.py` | modified | make/revoke + membership gates |
  | `backend/ee/onyx/server/user_group/api.py` | modified | allow_scope deps + manager-assign endpoint |
  | `backend/onyx/server/.../permissions api` | modified | `/me/permissions` adds `is_manager` |
  | `backend/tests/integration/.../test_group_manager_membership.py` | new | assign authz + membership scope |
- **Est. size:** ~400 LOC
- **Depends on:** PR 3, PR 4
- **Feature-flag state:** N/A — this is the backend "on switch" for creating new managers.
- **Tests on merge:** integration — cross-group member add rejected; `set_group_permissions` rejected for
  managers; assign endpoint allows admin + manager-of-that-group, rejects others; non-member target → 400.
- **Drift checkpoint:** re-confirm D2 (admins-only create) and D3 (admin-or-manager assign) still hold; confirm
  the `/me/permissions` response shape the frontend (PR6) will consume.

## PR 6 — Frontend: assignment UI & scoped nav
- **Goal:** make the capability usable and visible to humans.
- **Scope (in):** `usePermissions`/`hasPermission` consume `is_manager` for nav visibility; group-detail
  per-member "Make/Revoke Manager" toggle calling the PR5 endpoint; Playwright happy-path.
- **Out of scope:** any backend change (all landed PR1–5).
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `web/src/lib/.../usePermissions.ts` | modified | `is_manager` flag |
  | `web/src/.../hasPermission.ts` | modified | manager nav visibility |
  | `web/src/app/ee/admin/groups/[groupId]/...` | modified | Make/Revoke Manager toggle |
  | `web/tests/e2e/.../group-manager.spec.ts` | new | assign → scoped pages visible |
- **Est. size:** ~370 LOC
- **Depends on:** PR 5
- **Feature-flag state:** N/A — final wiring; feature fully live after merge.
- **Tests on merge:** Playwright — admin assigns a manager on the group page; that user sees the scoped admin
  pages and only their group's resources; non-managed pages/resources hidden.
- **Drift checkpoint:** confirm the group-detail page location under `web/src/app/ee/admin/groups/[groupId]/` and
  whether an old "Make Curator" affordance still exists to replace rather than add beside.
