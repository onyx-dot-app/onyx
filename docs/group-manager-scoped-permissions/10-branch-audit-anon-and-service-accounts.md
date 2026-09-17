# §10 Branch Audit — Anonymous Access, Groupless Service Accounts, and a Live Admin Escalation

Audit of `new-permission-system` vs `origin/main` (merge-base `6376385614`), requested to (1) understand
the branch, (2) chase a reported anonymous-access regression, and (3) define groupless-service-account
behavior. Method: route/actor matrix built from the live FastAPI dependency graph on both branches (507
routes each), live probes against a running deployment, plus a 4-hunter / adversarial-verify pass (60
agents, 32 findings survived verification, 16 refuted, 2 unverified on a session-limit cutoff).

**Headline: no anonymous-access regression was found.** The audit instead surfaced a **live,
reproduced CRITICAL privilege escalation** unrelated to anonymous access — see §3.

> **Status (2026-08-17, updated):** The CRITICAL finding (§3.3) is **fixed** — `0ad792f85e`
> (`_assert_no_privilege_amplification`), committed by a parallel session that read this doc while it was
> still being written. Independently re-verified against the current worktree by calling
> `add_users_to_user_group` directly (bypassing the HTTP layer): raises `OnyxError(INSUFFICIENT_PERMISSIONS)`
> and leaves the attacker's `effective_permissions` unchanged. The original live HTTP repro in §3.3 succeeded
> only because it ran against a stale `api_server` process (started before the fix commit, no `--reload`) —
> **restart the api_server before re-testing any of these findings against a live server.**
>
> Also fixed by the same parallel session: **`690129858c`** (connector-write surface for scoped managers —
> ingestion/run-once/targeted-reindex regained `allow_scope`; `get_llm_for_persona` aligned to `MANAGE_LLMS`;
> agent-editor tool visibility) and **`28063d2784`** (dead `UserRole`/curator residue removed, including
> `CURATORS_CANNOT_VIEW_OR_EDIT_NON_OWNED_ASSISTANTS` — resolved by deletion rather than restoration, since
> the migration to token-based auth left it unreachable either way).
>
> Additionally fixed **in this session**: `GET /admin/index-attempt/{id}/stage-metrics` was missing
> `allow_scope=True` at GATE 1 despite its own GATE 2 already scoping correctly
> (`backend/onyx/server/documents/cc_pair.py`) — a scoped manager who could read the sibling
> `index-attempts` list was wrongly 403'd here. Fixed + covered by two new integration tests in
> `test_group_manager_resources.py` (`test_manager_reads_stage_metrics_of_managed_cc_pair`,
> `test_manager_cannot_read_stage_metrics_of_unmanaged_cc_pair`). **Left unstaged, not committed** — the
> integration test needs a restarted `api_server` to actually run (see above); verified independently via
> direct route-dependency inspection instead.
>
> Two findings below are **reclassified**, not fixed, after cross-checking the locked design decisions in
> [00-index.md](00-index.md): "group manager can no longer delete a shared cc-pair/doc-set" matches **D6**
> ("managers may do everything except delete") — not a bug. "`DELETE /admin/credential/{id}` moved to
> `MANAGE_CONNECTORS` with no ownership scoping" is GLOBAL-only (no `allow_scope`, so no scoped-manager
> leak) and looks like the same accepted broadening as `MANAGE_SERVICE_ACCOUNT_API_KEYS` (doc 08 finding
> #1, "admin-equivalent, accepted, won't fix") — flagged as an open question for the owner, not fixed.
>
> Remaining open items needing an owner decision before a backend fix makes sense: EE non-admins losing
> `add:agents` (no migration ever grants it — granting it broadly is a capability decision, not a pure bug
> fix), Community Edition having no path to promote/demote an admin, and whether `GET /manage/users`'s
> org-wide visibility should be narrowed for a `MANAGE_LLMS`-only delegate (it also serves as the
> group-member-picker for `MANAGE_USER_GROUPS` delegates, which have a real need to search the whole
> directory — narrowing it is a design call, not a mechanical fix).

---

## 1. What the branch changes

Main already had the permission-token core (`require_permission`, `IMPLIED_PERMISSIONS`,
`User.effective_permissions`). This branch adds the **scoped group manager** layer and removes `UserRole`
entirely:

- `User__UserGroup.is_manager` (per-membership edge) + cached `User.is_group_manager`
  (`backend/onyx/db/models.py`), written by `recompute_user_permissions__no_commit`
  (`backend/onyx/db/permissions.py:52-150`).
- `has_permission(user, perm) -> GLOBAL | SCOPED | NONE` (`backend/onyx/auth/permissions.py:296-310`).
  Two-gate model: GATE 1 (`allow_scope=True` on `require_permission`) lets a SCOPED manager *reach* a
  route; GATE 2 (`assert_within_scope` / `assert_manages_group` / a managed-scope read clause) must
  confine them, or every resource leaks. `backend/onyx/auth/scoped_permissions.py` is the primitive layer.
- Read-side capability projection: `permissions{}` maps stamped on DTOs
  (`backend/onyx/auth/permission_projection.py`), affordance-only, never an authz input.
- `UserRole` is now a nullable tombstone (`backend/onyx/db/models.py:333`, migration
  `c8e316473aaa_make_user_role_nullable.py`) and is read nowhere in `backend/onyx` or `backend/ee`.
  `GET /get-user-role` and `PATCH /manage/set-user-role` are deleted (both 404 live).
- Only two migrations: `is_manager`/`is_group_manager` (with a CURATOR/GLOBAL_CURATOR → `is_manager`
  backfill) and the role-nullable migration. **No migration touches `permission_grant` rows.**

| Old (`UserRole`) | New equivalent |
|---|---|
| `ADMIN` | `FULL_ADMIN_PANEL_ACCESS` via the seeded Admin group (`admin` grant) |
| `BASIC` | `BASIC_ACCESS` via the seeded Basic group |
| `GLOBAL_CURATOR` / `CURATOR` | `is_manager` edge on a `User__UserGroup` row → `is_group_manager` |
| `LIMITED` (service account, no group) | `SERVICE_ACCOUNT` + empty `effective_permissions` → `account_derived_permissions` gives `write:chat` only |
| `SLACK_USER` / `EXT_PERM_USER` | unchanged: `AccountType.BOT` / `AccountType.EXT_PERM_USER`, no group system |

---

## 2. Anonymous user access — no regression confirmed

Built the actor×route matrix from the live dependency graph on **both** `main` and HEAD. The
anonymous-capable route set is **identical** — same 13 routes on both branches:

```
GET  /chat/get-chat-session/{session_id}      POST /chat/create-chat-session
POST /chat/send-chat-message                  POST /chat/create-chat-message-feedback
DELETE /chat/remove-chat-message-feedback     GET  /chat/available-context-tokens/{id}
GET  /chat/chat-session/{id}/resume-stream    GET  /manage/connector-status
GET  /persona                                 GET  /agents
GET  /settings                                GET  /llm/provider
GET  /llm/persona/{persona_id}/providers
```

Live-verified end to end: flipped `anonymous_user_enabled` on, sent an anonymous chat message, got a real
streamed model response, confirmed the write-surface routes still 401 (`/chat/file`, `/tool`,
`/chat/get-user-chat-sessions`), flipped the setting back off. No route gained or lost `allow_anonymous`
between branches; `/chat/file` has required an authenticated user since `f3ff4b57bd` on main, long before
this branch.

Three real anonymous-adjacent findings did survive verification — all low/info, none change what an
anonymous visitor can read or write:

- **LOW — Anonymous visitors are stamped `edit: true` / `share: true` on every public listed agent.**
  `backend/onyx/db/persona.py:116-121`'s anonymous carve-out sits *above* the `get_editable` split at
  `:130`, so it returns the same `is_public AND is_listed` clause for both edit and view queries.
  `stamp_persona_permissions` (`persona.py:539-588`) then marks every such agent editable/shareable in
  the `GET /persona` and `GET /agents` responses, and `AgentCard.tsx:103,115` renders Edit/Share buttons
  for signed-out visitors — including on built-in agents, which main's `checkUserCanEditAgent` explicitly
  excluded. **Live-reproduced**: with anonymity on, `GET /api/persona` returned
  `"permissions":{"edit":true,"share":true,...}` on the default public agent. No write lands — the
  single-agent GET and the share PATCH both reject anonymous — so this is a UI dead-end, not a data leak.
  Fix: move the anonymous return inside the `get_editable` branch in `_add_user_filters`.
- **LOW — `GET /me` for the anonymous user under-reports its own permissions.**
  `fetch_anonymous_user_info` (`backend/onyx/auth/anonymous_user.py:50-61`) builds `UserInfo` without
  passing `effective_permissions`/`admin_capabilities`, so the anonymous `/me` response reports `[]` for
  both while the in-process `User` object actually resolves `["basic"]` → the full BASIC bundle. Nothing
  client-side gates on those fields for anonymous today, so this is currently cosmetic — but it is a
  latent trap for the next feature that checks `permissions.includes(...)` before rendering a chat
  affordance. Fix: pass `effective_permissions=["basic", ...]` (or the resolved set) into the `UserInfo`
  constructor.
- **INFO — `document_set._add_user_filters` and `ee/onyx/db/token_limit.py`'s anonymous carve-outs were
  deleted without replacement**, and now fail closed (empty result) for anonymous on the editable path.
  Currently unreachable (no anonymous-facing route calls the editable path), recorded for completeness.

---

## 3. Groupless service account — definitive behavior, plus a live escalation found nearby

### 3.1 The requested spec

Creation with `group_ids: []` succeeds. `account_derived_permissions()`
(`backend/onyx/db/permissions.py:40-49`) is the single mechanism that keeps a groupless service account
usable at all — it hands it `write:chat` (which implies `read:chat`) purely because it's a
`SERVICE_ACCOUNT` with zero group memberships. `is_limited_user` (`backend/onyx/db/users.py:44-60`) is
**not** triggered, so the key authenticates normally.

Live-probed against a running deployment:

| Route class | Result |
|---|---|
| `GET /me`, `POST /chat/create-chat-session`, `GET /chat/get-user-chat-sessions` | **200** |
| `/settings`, `/tool`, `/manage/document-set`, `/manage/users`, `/onyx-api/ingestion`, `POST /user/pats` | **403** `INSUFFICIENT_PERMISSIONS` |

This mirrors main's `role=LIMITED` service account (`role_derived_permissions` keyed on `UserRole.LIMITED`
→ now keyed on "service account in no group") — same chat-only capability, same shape, different
mechanism. **Not a regression** for the groupless case itself.

### 3.2 Sharp edges around it (verified)

- **MEDIUM — A rename-only `PATCH /admin/api-key/{id}` silently strips every group.**
  `APIKeyArgs.group_ids` defaults to `[]` (`backend/onyx/server/api_key/models.py`); `update_api_key`
  (`backend/onyx/db/api_key.py:172-205`) always calls `set_user_groups__no_commit` with whatever
  `group_ids` the client sent. A client that omits the field to do a pure name-change (main's contract,
  where `role` had no bearing on a rename) now demotes the key from admin/basic to chat-only. The web UI
  always resends current groups, so only direct API callers hit this — but the blast radius is worse than
  main's analogous footgun (main defaulted to `BASIC`, not chat-only). **Live-reproduced**: posting
  `{"name":"x","role":"admin"}` (the old-client shape) against the new endpoint silently created a
  chat-only key — the unknown `role` field is dropped by pydantic with no error.
- **MEDIUM — Community Edition can only ever create chat-only service accounts.** `ApiKeyFormModal`'s
  group picker is fed by `useGroups(true)`, which is hard-empty in CE (no group-permission UI exists
  there). Every CE-created key is therefore permanently groupless → chat-only. On main, CE defaulted new
  keys to the `BASIC` role, which included `read:search`, `generate:image`, `use:llm_gateway`. This is a
  genuine CE regression, not an artifact of the groupless case being intentionally narrow.
- **LOW — `is_limited_user`'s `SERVICE_ACCOUNT` branch is now dead code.** Every group (including any
  admin-created one) auto-grants `BASIC_ACCESS` on creation (`ee/onyx/db/user_group.py:509`,
  `ee/onyx/db/scim.py:998`), and `basic` is non-toggleable — so a service account with ≥1 group can never
  have empty `effective_permissions`. The `not user.effective_permissions` check only ever fires for the
  zero-group case, which is already handled by `account_derived_permissions`. Docstring says "no group
  membership" as the trigger; code says "and permissions ended up empty," which given the auto-grant is
  the same thing today but is fragile to a future group ever *not* granting `basic`.
- **LOW/design — a service account in any group can never be scoped below the full Basic bundle**
  (`read:search`, `read:chat`, `write:chat`, `generate:image`, `use:llm_gateway`) — there's no
  intermediate tier between "groupless → chat-only" and "any group → full basic". Worth a product
  decision, not a bug.
- **LOW — `set_user_groups__no_commit` deletes and re-inserts `User__UserGroup` rows wholesale**
  (`backend/onyx/db/users.py:796-798`), which strips any `is_manager` edge. A service account made a
  group manager loses that status silently the next time its key is edited (rename, group change) via
  `update_api_key`. SCIM's group-sync path already diffs instead of delete-all for this reason
  (`ee/onyx/db/scim.py`); `set_user_groups__no_commit` should do the same.

### 3.3 CRITICAL — unrelated to either question, found and live-confirmed during the sweep

**A user holding only the delegatable `MANAGE_USER_GROUPS` permission (not full admin) can add themself
to the seeded Admin group and become a full admin.**

`assert_manages_group` → `manages_group` (`backend/onyx/auth/scoped_permissions.py:108-127`)
short-circuits `True` for **any** GLOBAL `MANAGE_USER_GROUPS` holder against **any** `group_id`, including
the seeded Admin default group — no `is_default` guard, no `FULL_ADMIN_PANEL_ACCESS` requirement. This is
the GATE 2 for `POST /admin/user-group/{id}/add-users` (`backend/ee/onyx/server/user_group/api.py:304-323`
→ `add_users_to_user_group`, `backend/ee/onyx/db/user_group.py:561-604`) and for
`PATCH /admin/user-group/{id}` (`api.py:280-301` → `update_user_group`, `user_group.py:696`). Sibling
routes (`rename`, `delete`) *do* carry an explicit `is_default` check (`api.py:236,334`) — this one
doesn't.

**Live-reproduced** on the running deployment: created a non-admin user holding only
`["basic", "manage:user_groups"]`, POSTed `add-users` against the seeded Admin group (id 1) with their own
user id, got **HTTP 200**, confirmed the `user__user_group` row, and their `/me` came back with the full
27-token admin permission set. A user who is only a SCOPED manager (a manager edge, no global token)
correctly got 403 on the identical call — the hole is exclusively in the GLOBAL branch.

The prior review (`08-security-review-must-fix.md`, finding #4) fixed the equivalent hole for *scoped*
managers by excluding default groups from `scoped_group_ids_subquery`
(`backend/onyx/db/scoped_permissions.py:20-34`). That fix never touches `manages_group`'s GLOBAL
short-circuit, so a GLOBAL `manage:user_groups` delegate — someone an admin intended to hand only "Manage
Groups," per the registry description "Add and update user groups" — bypasses it completely.

**Fix direction:** add the same `is_default` guard `manages_group` uses on its SCOPED path to its GLOBAL
path too, or require `FULL_ADMIN_PANEL_ACCESS` (not just `MANAGE_USER_GROUPS`) for any membership/manager
edit that touches a default group.

---

## 4. Other confirmed findings, ranked

**HIGH**

- **EE: every non-admin loses agent creation and deletion of their own agents.** `POST /persona` /
  `DELETE /persona/{id}` moved `basic` → `add:agents` (`backend/onyx/server/features/persona/api.py`), but
  no migration ever grants `add:agents` — the only two migrations that write `permission_grant` seed
  `admin`/`basic` only (`977e834c1427_seed_default_groups.py:22-25`,
  `b4b7e1028dfd_grant_basic_to_existing_groups.py:47`). `CE_UNGATED_PERMISSIONS` covers Community Edition
  (`backend/onyx/auth/permissions.py:105-109`), but EE has no equivalent — every existing EE deployment's
  non-admins lose agent creation on upgrade until an admin manually grants "Create Agents" per group.
- **Community Edition: no remaining mechanism to promote or demote an admin.** `PATCH /manage/set-user-role`
  is deleted; the only replacement (adding a user to the Admin group via
  `POST /manage/admin/user-group/{id}/add-users`) is registered only by `ee/onyx/main.py` — absent in CE
  builds. The lone CE admin is permanently whoever registered first.
- **`MANAGE_LLMS` now implies `READ_USERS`, and `GET /manage/users` has `allow_scope=True` with no GATE 2**
  (`backend/onyx/server/manage/users.py:357-371` — the handler calls `get_all_users()` unfiltered and
  discards the user as `_`). An "LLM manager" delegate — a much narrower grant than "manage groups" —
  gets the entire org user directory plus the pending-invite list as a side effect. Same missing-GATE-2
  route was independently flagged by two hunters.

**MEDIUM** (6 more survived, spanning: CE service-account chat-only default (§3.2); the rename-strips-groups
footgun (§3.2); the org-directory leak above stated twice; group managers 403'd on the whole
connector-write surface — file upload, PATCH, DELETE, run-once, OAuth callbacks — despite holding
`MANAGE_CONNECTORS` in scope; credential group-sharing being write-only for a manager (can create, can't
view); `CURATORS_CANNOT_VIEW_OR_EDIT_NON_OWNED_ASSISTANTS` becoming silently inert since it still checks
the deleted `UserRole`; a `stage-metrics` route with a working GATE 2 but missing `allow_scope` at GATE 1
(reachable-but-403 for a manager who should pass); a manager losing the ability to delete a cc-pair or
doc-set shared into their own managed group; `DELETE /admin/credential/{id}` moved from full-admin to
`MANAGE_CONNECTORS` with no per-credential ownership scoping).

**LOW / INFO** (13 more survived): affordance-only anonymous-agent stamping and `/me` under-report (§2);
migration silently demoting `GLOBAL_CURATOR`/`CURATOR` users whose group membership doesn't map cleanly;
an agent owner losing analytics on their own agent (route needs `READ_AGENT_ANALYTICS` with no
`allow_scope`); a connector detail page rendering admin-only buttons to a manager; agent-create UI gating
on the wrong permission set; the four `/onyx-api/ingestion` routes losing curator-level access entirely;
managers losing the ability to create PUBLIC (not just private) resources that CURATOR/GLOBAL_CURATOR
could; a `get_llm_for_persona` call site checking `FULL_ADMIN_PANEL_ACCESS` where every sibling checks
`MANAGE_LLMS`; confirmation that leaving `request.state.token_scopes` unset for API-key auth is
intentional (not a bug).

**16 findings were raised and refuted** on review — mostly claims where a caller-side guard, a different
dependency, or a DB constraint already covered the scenario. Full detail (including refutation reasoning)
is in the audit transcript, not reproduced here to keep this doc load-bearing rather than a changelog.

**2 findings could not be verified** — the verify pass hit a session token limit before reaching them:
"deleted test coverage: no replacement pins the manager's connector-creation flow" and "ordinary users
lose the `/admin/credential` update paths that were `BASIC_ACCESS` on main." Both were raised at
medium/low severity by the hunt pass; re-run if a definitive answer is needed.

---

## 5. Open questions for the author

- Is the CE-only capability loss (agent creation via `add:agents`, PAT creation via
  `create:user_api_keys`, admin promotion, service-account scope) intended tightening, or an oversight of
  `CE_UNGATED_PERMISSIONS` not covering the full new permission surface?
- Should `manages_group`'s GLOBAL branch require `FULL_ADMIN_PANEL_ACCESS` for default-group edits, matching
  the `is_default` guard already present on rename/delete? (§3.3 — recommend fixing before any release
  that delegates `MANAGE_USER_GROUPS` to a non-admin.)
- Is CE's forced chat-only service-account tier (§3.2) acceptable, or should CE keep a "full basic" option
  the way main's `role=BASIC` default gave it?

---

*Method: route/actor matrix diffed against main via the live FastAPI dependency graph (507 routes, both
branches); live probes against a running deployment (anonymous chat send/receive, groupless
service-account creation and route sweep, the Admin-group escalation); 5 mapping agents → 4 adversarial
hunters (50 raw findings) → per-finding adversarial verification (32 survived, 16 refuted, 2 unverified on
a session cutoff). The Admin-group escalation (§3.3) was independently re-derived and confirmed by hand
against the code after the automated pass, not taken on the sub-agent's word alone.*
