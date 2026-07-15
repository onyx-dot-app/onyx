> Status: active · Task: group-manager-scoped-permissions

# §8 Scoped Permissions (Group Manager) — Implementation Plan

> **Primitives per [03 §2](03-detailed-design.md) (single-classifier model).** `has_permission` returns
> `PermissionAuthority` (one classifier; the separate `has_permission_or_scope` removed) and lives in `permissions.py` with
> the bundle; `has_global_permission` is the GLOBAL-only bool helper. GATE 1 = `require_permission(...,
> allow_scope=True)` (threshold); GATE 2 = `assert_within_scope` / `assert_global`. Names below updated to match.

## Issues to Address

The base group-permission system (§1–7) grants tokens to a whole group — every member gets them everywhere.
There is **no way to delegate admin-like control over a single group** without granting it globally. §8 adds the
**Group Manager**: a user with `manage:*` powers confined to the group(s) they manage, and nothing else. The
change must deliver that delegation **without re-introducing the old dual-path fragility** and **without opening
privilege-escalation paths** (capturing out-of-scope resources, publishing org-wide, or self-granting tokens).
Outcome: an EE admin (or an existing manager) can make a user a manager of a group; that user can create/edit/
share/attach the group's connectors, document sets, agents, actions, and manage its membership — strictly
PRIVATE and strictly within their managed groups — enforced authoritatively at the database write.

## Important Notes

- **§8 is greenfield on §1–7; PR0+PR1 now built.** Base system complete (`01-research.md`). PR1 shipped the
  schema migration as `c71a18ea7d07` (down_revision `c8e316473aaa`, now head) — the earlier placeholder
  `4fa09af6ca14` was never used. Scoped artifacts (PR2+) remain absent.
- **Two-gate model is non-negotiable.** Route gate (`has_permission`, cached flag) only grants
  *reachability*; the **authorization of record** is `assert_within_scope`, run **inside the DB write**,
  re-reading the resource's **current** groups (`02/03`). The route gate must never authorize.
- **D1 (cache the boolean):** new cached `user.is_group_manager` (sibling to `effective_permissions`, which stays
  global-only), recomputed via `recompute_user_permissions__no_commit` (`db/permissions.py:43`) on membership
  change and on manager flip. Managed-group **list** stays live (`scoped_group_ids_subquery`).
- **D2:** admins only create top-level groups. **D3:** admin or manager-of-that-group assigns managers.
- **Reuse, don't rebuild:** extend `require_permission` (`auth/permissions.py:257`) with `allow_scope`; reuse the
  existing `(user_id)` index; PAT token-cap (`permissions.py:278`, `db/pat.py`) already intersects permissions —
  no PAT schema change.
- **Migration ordering trap:** `is_manager` backfill is role-gated (captures GLOBAL_CURATOR, which has no
  `is_curator` rows) and **must run before any later release drops `role`/`is_curator`**.
- **`document_set` editable filter is `sa_false()`** today (`db/document_set.py:47`) — the manager branch is a
  full build, not a tweak. `credentials` stays owner-scoped (deliberate no-op).
- **Escalation points that gate only on global `manage:*` today:** group membership writes
  (`ee/user_group.py:462/504`), connector create (`connector_credential_pair.py:496`), persona group-share
  (`ee/persona.py:68`). These are where GATE 2 must be inserted.
- **Conventions (CLAUDE.md):** raise `OnyxError`, strict typing, no `response_model`, DB ops only under
  `*/db/`, EE code under `ee/`.
- **Regression-review additions (2026-06-29) — see [03 §11](03-detailed-design.md) for the full checklist:**
  - **PREREQUISITE (boot bug, §11.0):** `current_curator_or_admin_user` is gone but still imported by
    `skill/api.py:16` + `targeted_reindex.py:22` → the API server won't boot. Fix first (Step 0).
  - **D4 actions (§11.1):** keep `MANAGE_ACTIONS` **in the bundle** (GATE 1 reach); switch the tool/MCP admin
    endpoints to `allow_scope=True`; GATE 2 scopes via the agents that reference the action
    (`Tool → Persona__Tool → Persona__UserGroup` ⊆ managed), replacing the owner-or-admin per-resource check.
  - **D5 skills (§11.2):** add a **dedicated `MANAGE_SKILLS` permission** (groups UI + bundle; no migration).
    Skills do NOT mirror personas — add a NEW scoped admin-list path (don't touch the runtime visibility
    filter), GATE 2 on `replace_skill_grants` (the `/grants` seam), re-point `skill/api.py` by verb to
    `MANAGE_SKILLS, allow_scope=True` (DELETE stays admin-only).
  - **D7 agent→group = `MANAGE_AGENTS`-controlled (§11.5):** group-share is the standard GATE 2 keyed on
    `MANAGE_AGENTS` (admin/global bypass; scoped managers ⊆ managed; `ADD_AGENTS`-only can't group-share).
    Today's route is `ADD_AGENTS` + editable-fetch, so PR4 adds the `MANAGE_AGENTS` requirement on the
    group-share write (a small intended tightening).
  - **D6 delete (§11.3):** managers do everything *except delete* — all DELETE endpoints stay admin-only.
  - **Persona GATE 2 (§11.5):** `update_persona_access` lacks the actor `User`+`permission`; thread the
    acting user into it from all 3 callers (create / share / `/agents`) and gate the shared chokepoint.
  - **cc_pair re-attach (§11.6):** `update_user_group` rewrites group↔cc_pair from client `cc_pair_ids` —
    run GATE 2 per added cc_pair (else a manager attaches out-of-scope connectors).
  - **Corrections (§11.7):** feedback `db/feedback.py` = **no change** (admin-only; not in bundle);
    `recompute_user_permissions__no_commit` takes `(user_ids, db_session)` and must be extended to set
    `is_group_manager`.
  - **Confirmed SAFE (§11.8):** PAT cap, chat runtime, and document/Vespa ACL are untouched — keep them so.

## Implementation Strategy

**Step 0 — Prerequisite boot fix (independent of §8).** Re-point `skill/api.py` (`:16` + deps at
`:173/186/223/259/297/322`) and `targeted_reindex.py:22` off the deleted `current_curator_or_admin_user`
onto `require_permission(...)`. Until this lands, `import onyx.main` raises `ImportError` and nothing runs.
Lands as its own small commit ahead of (or at the head of) PR1.

**Step 1 — Schema + cached flag + migration.** Add `User__UserGroup.is_manager` and `User.is_group_manager`
(`db/models.py`). Author migration `c71a18ea7d07` (down_revision `c8e316473aaa`, `alembic/versions/`) adding both
columns, role-gated `is_manager` backfill (CURATOR + GLOBAL_CURATOR), and `is_group_manager` backfill from the
result. Extend `recompute_user_permissions__no_commit` (`db/permissions.py:43`) to recompute `is_group_manager`.

**Step 2 — Auth primitives.** New `auth/scoped_permissions.py`: `SCOPED_MANAGER_PERMISSIONS`,
`scoped_group_ids_subquery`, `get_scoped_groups`, `has_permission` (reads cached flag),
`within_managed_scope_clause`, `assert_within_scope`. Extend `require_permission` with
`allow_scope: bool` (`auth/permissions.py`). Unit-coverable, no endpoints wired yet.

**Step 3 — Manager assignment.** `make_group_manager` / `revoke_group_manager` (`ee/onyx/db/user_group.py`) with
a recompute trigger for the affected user. New EE endpoint `PUT …/user-group/{group_id}/manager`
(`ee/onyx/server/user_group/api.py`) gated `admin ∨ group_id ∈ managed` (D3); reject non-member targets.

**Step 4 — Write-side gates (the security core).** Insert `assert_within_scope` into each scoped write
fn, re-reading current groups in-txn: connector create/update (`db/connector_credential_pair.py:496` +
cc_pair update), document set create/update (`db/document_set.py:220/296`), persona
(`db/persona.py:325`→`ee/persona.py:68`), group update/add-users (`ee/user_group.py:504/462`). Switch those
endpoints to `require_permission(<token>, allow_scope=True)`. Leave **group create** and **set_group_permissions**
on the plain global dependency (D2 + admin-only grants). Ensure bulk endpoints check **every** item.

**Step 5 — Listing/edit filters.** Re-key the editable branch of the 4 filters onto `within_managed_scope_clause`:
`document_set.py` (build from `sa_false()`), `connector_credential_pair.py`, `persona.py`, and **`skill.py`**
(`_add_user_visibility_filter`, the new 7th resource — D5). Enforce managed-scope in the EE `token_limit.py` group
write path. `credentials.py` **and `feedback.py`** unchanged (documented no-ops — feedback is admin-only,
`FULL_ADMIN_PANEL_ACCESS`, and not in the bundle; §11.7). Every branch fails closed on an empty managed set.

**Step 6 — API + frontend.** Add `is_manager` (and optionally `managed_group_ids`) to `GET /users/me/permissions`.
Frontend: `usePermissions` / `hasPermission` consume the flag for nav visibility; group-detail page gets a
per-member "Make/Revoke Manager" toggle (`web/src/app/ee/admin/groups/[groupId]/`) calling the Step-3 endpoint.

**Step 7 — PAT composition verification.** No schema change; add tests proving a scoped PAT narrows permissions
and can never widen group reach (live `is_manager` bounds groups regardless of token).

## Tests

Primary type = **integration** (per CLAUDE.md: real deployment, hardest to fake; this is a security boundary).
Use `UserGroupManager` / resource managers in `tests/integration/common_utils`; prefer fixtures.

> **Find the existing home before writing a new test file.** The new permission system already has
> strong coverage — don't reflexively `git add` a fresh test file. First locate the suite that already
> exercises the behavior, read it, confirm it's sound, and **extend it** when the new assertion belongs to
> a flow it already drives. Only create a new file when no existing suite covers the behavior. Known homes:
> - recompute / `effective_permissions` → `tests/integration/tests/usergroup/test_group_membership_updates_user_permissions.py`
> - grant / revoke (bulk) + implied-expansion → `tests/integration/tests/usergroup/test_group_permission_toggle.py`
> - registration / default-group propagation + fixtures → `tests/integration/tests/permissions/` (`test_auth_permission_propagation.py`, `conftest.py`)
> - read-time permission expansion (pure logic) → `tests/unit/onyx/auth/test_permissions.py`
>
> Worked example (PR1): `is_group_manager` is the *second* column `recompute_user_permissions__no_commit`
> writes, so its coverage was folded into the existing recompute test above — **not** a standalone file. An
> earlier standalone `test_is_manager_recompute.py` was deleted because it duplicated that home, flipped the
> flag on an incidental default-group membership, and re-ran the migration's copied SQL as a self-referential
> oracle. The migration-backfill case is the one genuinely new home (own file under
> `tests/integration/tests/migrations/`, running the real alembic migration — never a copied-SQL oracle).

- **Escalation suite (integration)** — for a manager of group X: (a) capture-by-reassign rejected
  (`PUT resource{groups:[X]}` on a resource currently in Y → 403); (b) PUBLIC/SYNC create+edit rejected;
  (c) cross-group membership add rejected (add to Y); (d) **fail-closed** — a user with `is_manager` on zero
  groups gets empty editable lists, not everything; (e) `set_group_permissions` rejected for a manager;
  (f) bulk edit rejects the batch if any item is out of scope; (g) happy paths (create/edit/attach/detach/member
  add within X) succeed.
- **PAT (integration)** — a manager's PAT scoped to `manage:connectors` edits only X's connectors and cannot
  reach Y; a PAT cannot widen group reach.
- **Migration backfill (DEFERRED by owner; revisit before GA) — integration, real alembic** — a new test under
  `tests/integration/tests/migrations/` that seeds CURATOR(+is_curator) and a zero-`is_curator` GLOBAL_CURATOR,
  runs the actual migration (down→up), and asserts `is_manager` (GLOBAL_CURATOR captured on all memberships) +
  `is_group_manager` mirror; fresh-install leaves all false. NOT a copied-SQL oracle.
- **Filter SQL (external-dependency unit)** — `within_managed_scope_clause` returns exactly the resources whose
  every group ⊆ managed and ≥1 group and private (the `document_set` rebuild especially).
- **Manager toggle UI (playwright, 1 test)** — admin assigns a manager via the group page; that user then sees
  the scoped admin pages and only their group's resources.

---

## Plan Challenge Results

### 1. Extendability & Scalability: PASS (one refinement)
Adding a new manageable resource = add token to `SCOPED_MANAGER_PERMISSIONS` + re-key its filter + insert the
gate in its write fn; the `within_managed_scope_clause` helper is reused, no hardcoded limits. **Refinement
(folded in):** in bulk endpoints, resolve `get_scoped_groups(user)` **once per request** and pass the set to the
per-item gate — avoids N indexed reads on batch edits. The route-gate cost is O(1) (cached `is_group_manager`).

### 2. Fragility: CONCERN → hardened
The model's load-bearing assumption is *every* scoped write path calls `assert_within_scope`; a future
write path that forgets it is an escalation. Hardenings added to the plan:
- **Minimize insertion sites** — route resource→group attaches through the existing single junction writers
  (e.g. `_relate_groups_to_cc_pair__no_commit`) so the gate has few, obvious homes, not scattered call sites.
- **Defense-in-depth test** — the escalation integration suite asserts each scoped endpoint rejects out-of-scope
  input, so a missing gate fails CI.
- **Cache-staleness is security-safe by construction** — the cached `is_group_manager` is only a *reachability*
  hint for GATE 1 (can only reject earlier). The authorization of record (GATE 2) resolves the managed-group
  **list live**, so a stale `true` still hits a live `managed={} → 403` (fail-closed); a stale `false` is an
  availability bug, never an escalation. Recompute must fire on every `is_manager` flip (already specified).

### 3. Industry Standard: VERIFIED
Searched scoped-RBAC / delegated-admin best practices (2025), k8s RoleBinding delegation, and Zanzibar
live-vs-materialized. Findings confirm the design: scoped (not global) roles with a **User→Role→Scope** model are
the recommended pattern; access control should be **centralized at the data/policy layer**, not the gateway
(Oso/OpenFGA/Cedar). k8s binds a *role* to a *namespace* (our bundle→group) and **prevents privilege escalation
by only allowing you to bind a role you already hold at that scope** — exactly what D3 in-group delegation does
(a manager grants the same bundle it holds, within a group it manages). The two-gate + write-side enforcement is
industry-standard.

### 4. Fact Check: PASS (and D1 strengthened)
- *k8s RoleBinding namespace-scoping + escalation-prevention bind rule* — **verified**.
- *Zanzibar resolves live to avoid the "new-enemy problem" (Alice removes Bob, adds docs, Bob must not see them)*
  — **verified**, and it nuances D1 favorably: Zanzibar serves ~99% of checks from **bounded-stale** local
  replicas and only forces freshness for critical ops (zookies). So **caching the `is_manager` boolean (D1) is
  consistent with industry practice** *because* the security-critical decision (GATE 2) stays live — the original
  "must resolve everything live" framing was stricter than the standard requires.
- *AWS IAM permission boundaries / Azure scoped RBAC (narrow-only)* — widely documented; carried from the prior
  46-agent review (not re-searched this round). Confidence high.

### 5. Maintainability: PASS
Two gates, one code bundle, one cached flag — graspable in <15 min. Extends existing seams (`require_permission`,
`_add_user_filters`, the recompute hooks) rather than inventing a parallel system. Watch item: the
`within_managed_scope_clause` SQL and the `document_set` rebuild (from `sa_false()`) need clear docstrings so the
"every group ⊆ managed ∧ ≥1 ∧ private" predicate stays consistent across the four filters.

### 6. Patch vs. Fix: PROPER FIX
Root cause (no scoped delegation) is solved with a first-class model; no error suppression, no timeouts, no
workarounds. Reusing the `is_curator` column is a deliberate, documented single-resolver decision (not a
tombstone hack) — the old dual-path *meaning* is gone. **No patch/fix decision needed from the user.**

**Verdict: plan passes all six checks. No blocking concerns; the fragility hardenings are folded into Steps 4–5
and the test plan.**
