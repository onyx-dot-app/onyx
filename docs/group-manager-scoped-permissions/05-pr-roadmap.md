> Status: active · Task: group-manager-scoped-permissions · Source plan: 04-implementation-plan.md

# §8 Scoped Permissions (Group Manager) — PR Roadmap

Six PRs, dependency-ordered. **Safety invariant:** every enforcement PR lands its read-filter + write-side gate
+ endpoint `allow_scope` switch **together** — a manager can never reach an endpoint before its GATE 2 exists, so
there is no escalation window at any merge boundary. (Pre-GA branch: existing curators were already collapsed to
STANDARD by the `account_type` backfill, so no live capability is regressed while enforcement lands incrementally.)

> **Revised by the 2026-06-29 regression review** — see [03 §11](03-detailed-design.md) for the full case
> checklist. Net changes to this roadmap: a new **PR0** (boot-fix prerequisite); **PR4** swaps feedback →
> **skills** and drops actions (D4/D5); **delete stays admin-only** across all PRs (D6); PR3/PR5 enumerate
> the previously-missed write endpoints (cc_pair status/name/property/prune, persona `/share`, group rename,
> `/agents`) and the persona-gate signature fix (§11.5) + cc_pair-reattach fix (§11.6).

## Overview

| PR | Title | Est. LOC | Depends on | Key deliverable |
|----|-------|----------|------------|-----------------|
| 0 | `fix(perms): re-point skill/targeted-reindex off removed curator dep` | ~30 | — | **Unblocks boot** — `import onyx.main` currently fails (§11.0); independent of §8 |
| 1 | `feat(perms): add is_manager + is_group_manager columns and backfill` | ~220 | 0 | Schema + role-gated migration + cached-flag recompute |
| 2 | `feat(perms): scoped-manager authorization primitives` | ~330 | 1 | `scoped_permissions.py` (bundle w/o actions, gates, scope helpers) + `require_permission(allow_scope)` — inert |
| 3 | `feat(perms): scope connectors & document sets to group managers` | ~560 | 2 | Two-gate enforcement on cc_pairs + doc sets incl. status/name/property/prune (delete admin-only) |
| 4 | `feat(perms): scope agents, skills & token limits to group managers` | ~520 | 2 | Persona (+ `/share`, `/agents`, gate-signature fix §11.5) + **skills** + token-limit enforcement + scoped-PAT tests |
| 5 | `feat(perms): group-manager assignment & membership scoping` | ~430 | 3,4 | make/revoke + assign endpoint (D3) + membership gates + cc_pair-reattach gate (§11.6) + group rename + `/me/permissions.is_manager` |
| 6 | `feat(perms): group-manager assignment UI & scoped nav` | ~370 | 5 | Group-detail Make/Revoke toggle + manager nav visibility + Playwright |

## Sequence

```
PR0 (boot-fix: curator dep) ─▶ PR1 (schema+migration+recompute)
  └─▶ PR2 (auth primitives — inert)
        ├─▶ PR3 (connectors + doc sets enforcement)  ┐
        └─▶ PR4 (agents + skills + token limits)     ┘ both build on PR2 only; mergeable in either order
                                                      ▼
                                          PR5 (assignment + membership scoping)
                                                      ▼
                                          PR6 (frontend)
```

Walking skeleton = PR1→PR2→PR3: after PR3 the full two-gate model is provably working on the two
highest-value resource types, exercised by the escalation integration suite (managers seeded via fixture).

---

## PR 0 — Boot-fix prerequisite: re-point off the removed curator dep
- **Goal:** restore a bootable app — independent of §8, but blocks every later PR.
- **Scope (in):** `current_curator_or_admin_user` was deleted from `onyx/auth/users.py` by §1–7 but is still
  imported by `server/features/skill/api.py:16` (deps `:173/186/223/259/297/322`) and
  `server/documents/targeted_reindex.py:22`, so `import onyx.main` raises `ImportError`. Re-point both onto the
  correct `require_permission(...)` dep: `targeted_reindex.py:80/163` → `MANAGE_CONNECTORS` (its connector
  peers); skills → `FULL_ADMIN_PANEL_ACCESS` in PR0 (safe, unbreaks boot), narrowed to the new
  `MANAGE_SKILLS, allow_scope=True` when the skill GATE 2 lands in PR4 (§11.2). DELETE endpoints excluded
  (stay admin-only).
- **Out of scope:** any manager scoping (that's PR1+).
- **Est. size:** ~30 LOC.
- **Depends on:** —
- **Tests on merge:** `python -c "import onyx.main"` succeeds; skill admin + targeted-reindex endpoints import.
- **Drift checkpoint:** confirm whether §1–7 already intends a specific replacement dep for these endpoints
  (align with how the other ex-curator endpoints were migrated) before picking the token.

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
- **Drift checkpoint:** confirm the bundle is the 6-token set — `manage:actions` OUT (D4 — agent-mediated),
  new `manage:skills` IN (D5); confirm `require_permission`'s token-cap branch is
  unchanged since `03`.

## PR 3 — Enforce scope on connectors & document sets (walking skeleton)
- **Goal:** prove the full two-gate model end-to-end on the two highest-value resources.
- **Scope (in):** rewrite editable filters in `connector_credential_pair.py` and `document_set.py` (the latter
  built from today's `sa_false()`) onto `within_managed_scope_clause`; insert `assert_group_set_within_scope` in
  cc_pair create/update + doc-set create/update DB fns (re-reading current groups in-txn); switch the **full set**
  of manager-reachable endpoints (§11.4) to `require_permission(<token>, allow_scope=True)` — connector create
  (mock-cred `connector.py:1568` **and** bare `:1538`), associate-credential `cc_pair.py:716`, cc_pair status
  `:427`/name `:512`/property `:542`/prune `:604`, ee `sync_cc_pair_groups`, doc-set create/patch — **but leave
  connector/cc_pair and doc-set DELETE on the global admin dep (D6)**; resolve `get_scoped_groups` once per
  request on bulk paths.
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

## PR 4 — Enforce scope on agents, skills & token limits
- **Goal:** extend the proven model to the remaining manager-scoped resources; verify PAT composition.
- **Scope (in):** persona filter + thread the acting `user: User` into `update_persona_access` (both MIT+EE
  twins); persona group-share is **`MANAGE_AGENTS`-gated via GATE 2 (D7, §11.5)** — admin/global bypass,
  scoped managers ⊆ managed, `ADD_AGENTS`-only can't group-share (today's route is `ADD_AGENTS` + editable
  fetch, so PR4 adds the `MANAGE_AGENTS` check on the group-share write); `is_public` stays owner/admin-gated. **Skills (D5):** new dedicated **`MANAGE_SKILLS`** permission (enum + registry/groups UI +
  bundle; no migration), a NEW scoped admin-list path (do NOT touch the runtime visibility filter), GATE 2 on
  `replace_skill_grants`, re-point `skill/api.py` by verb to `MANAGE_SKILLS, allow_scope=True` (§11.2);
  managed-scope enforcement in EE `token_limit.py` group write path; `credentials.py` **and `feedback.py`** left
  unchanged (documented no-ops); **persona/skill delete stays admin-only (D6)**; scoped-PAT tests. **Actions:
  nothing to build** — agent-mediated
  (D4), `MANAGE_ACTIONS` not in the bundle, tool/MCP catalog stays owner/admin.
- **Out of scope:** membership/assignment (PR5); UI (PR6).
- **Files:**
  | File | New/Modified | This PR's slice |
  |------|--------------|-----------------|
  | `backend/onyx/db/persona.py` | modified | filter + `update_persona_access` MIT twin gate + owner carve-out (§11.5) |
  | `backend/ee/onyx/db/persona.py` | modified | `update_persona_access` EE gate (lockstep signature) |
  | `backend/onyx/db/skill.py` | modified | scoped admin-list path + `replace_skill_grants` GATE 2 + is_public toggle gate (§11.2) |
  | `backend/onyx/server/features/skill/api.py` | modified | re-point off curator dep; `allow_scope=True` by verb (DELETE stays admin-only) |
  | `backend/ee/onyx/db/token_limit.py` | modified | managed-scope on group token-limit writes |
  | `backend/onyx/server/.../persona api` | modified | `ADD_AGENTS, allow_scope=True` deps |
  | `backend/tests/integration/.../test_group_manager_agents.py` | new | agent + skill escalation + ADD_AGENTS-owner no-regression + PAT narrowing |
  | `backend/onyx/db/feedback.py` | unchanged | NO CHANGE — admin-only, not in bundle (§11.7) |
- **Est. size:** ~460 LOC
- **Depends on:** PR 2 (independent of PR 3)
- **Feature-flag state:** N/A — lands-together invariant.
- **Tests on merge:** integration — agent create/share scoped; manager can't widen a PAT's group reach; `add:agents`
  ownership tier still keyed on `Persona.user_id`; credentials remain owner-only for a manager.
- **Drift checkpoint:** confirm actions-via-agents assumption (no direct tool→group table) still holds; confirm
  the persona create/update endpoint path + that `manage:agents` is the right scoped token.

## PR 5 — Manager assignment & group-membership scoping (backend complete)
- **Goal:** let admins/in-group managers create managers, and scope membership edits; expose the flag to clients.
- **Scope (in):** `make_group_manager`/`revoke_group_manager` (`ee/onyx/db/user_group.py`) + recompute trigger
  (extend `recompute_user_permissions__no_commit(user_ids, db_session)` to set `is_group_manager` — §11.7);
  gates in `update_user_group`/`add_users_to_user_group` (`group_id ∈ managed`) **plus a per-cc_pair GATE 2 on
  `update_user_group`'s `cc_pair_ids` re-attach (§11.6 — else a manager attaches out-of-scope connectors)**;
  `allow_scope=True` on group update/add-users **and rename (`:164`)** endpoints; **scoped group-LIST**
  (`fetch_user_groups` manager variant filtered by `is_manager`, `list_user_groups`+detail/member reads to
  `allow_scope=True` returning only managed groups — §11.9, or the Groups page/assign-UI breaks); **new**
  `PUT …/user-group/{group_id}/manager` gated `admin ∨ group_id ∈ managed` (D3); group **create**, **delete**,
  and `set_group_permissions` left admin-only (D2/D6); add `is_manager` (+`managed_group_ids`) to
  `GET /users/me/permissions`.
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
