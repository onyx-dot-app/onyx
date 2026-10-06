# Craft Admin

> The three admin-panel surfaces that govern Onyx Craft: who may use it, which
> external services a sandbox may reach, and what instructions and default
> model it runs with. This document does not cover sandboxes, snapshots,
> streaming, or the webapp proxy; it maps into `docs/craft/` for those.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** craft
**Edition:** CE, with a Cloud-only lockdown on built-in external-app credential editing (EE)
**Owns:**
`web/src/app/admin/craft/access/page.tsx`, `web/src/app/admin/craft/apps/page.tsx`,
`web/src/app/admin/craft/preferences/page.tsx`,
`web/src/views/admin/CraftPage/`, `web/src/views/admin/CraftPreferencesPage/`,
`web/src/views/admin/ExternalAppsPage/`,
`backend/onyx/server/features/build/api.py`, `build/utils.py`,
`backend/onyx/server/features/build/external_apps/api.py`,
`backend/onyx/db/external_app.py`, `backend/onyx/db/gated_app.py`,
`backend/onyx/db/user_preferences.py`, `backend/onyx/server/settings/api.py`

**Read first:** `docs/craft/craft-main-plan.md` for the overview of Craft as a
product, and `docs/craft/features/external-apps/` for the four documents this
page maps to code.

---

## 1. What the user experiences

An admin sees a "Craft" section in the admin sidebar with three pages: Access,
Apps, Preferences.

On **Access**, the admin sets a workspace-wide default (Craft on or off for
everyone) and can override that default for individual users, one at a time or
in bulk, in a searchable table.

On **Apps**, the admin sees every external service and MCP server the Craft
agent can reach: built-in apps (Slack, Gmail, Google Calendar, Google Drive, Linear,
HubSpot, Notion, GitHub), any custom app the admin has registered, and connected MCP
servers. For each, the admin can enable or disable it, edit its per-action
policy (auto-approve, ask, or deny each kind of action), and, for
self-hosted deployments, configure its credentials. On Onyx Cloud, built-in
apps already have Onyx-managed OAuth credentials; the admin can only toggle
them on and set policy.

On **Preferences**, the admin sets a workspace default model for Craft
sessions and a free-text "organization instructions" block that every Craft
agent sees, alongside a read-only preview of the base instructions template
those org instructions are appended to.

---

## 2. Surfaces

### Admin routes (`web/src/lib/admin-routes.ts`)

| Route | Component | Gate |
|---|---|---|
| `/admin/craft/access` | `CraftPage` (`web/src/views/admin/CraftPage/index.tsx`) | `Permission.FULL_ADMIN_PANEL_ACCESS`; hidden in the sidebar unless `FeatureFlags.craftAvailable` |
| `/admin/craft/apps` | `ExternalAppsPage` (`web/src/views/admin/ExternalAppsPage/index.tsx`) | same |
| `/admin/craft/preferences` | `CraftPreferencesPage` (`web/src/views/admin/CraftPreferencesPage/index.tsx`) | same |

All three carry `requiredTier: null` (`web/src/lib/admin-routes.ts:159-186`): visibility is not tied
to a billing tier, only to the `craftAvailable` feature flag and the admin
permission. See §5 for why the flag alone is not the real gate.

### HTTP endpoints

| Method | Path | Handler | Notes |
|---|---|---|---|
| PATCH | `/api/manage/admin/users/craft-enabled` | `set_user_craft_access` (`backend/onyx/server/manage/users.py:201`) | Sets or clears `User.craft_enabled` for one or more emails. `Permission.FULL_ADMIN_PANEL_ACCESS`. Emits `AuditAction.USER_CRAFT_ACCESS_CHANGE`. |
| PATCH | `/api/admin/settings` | `admin_patch_settings` (`backend/onyx/server/settings/api.py`) | Writes `craft_default_enabled` and `craft_instructions` as part of the general `Settings` blob. |
| GET | `/api/settings` | `fetch_settings` (`backend/onyx/server/settings/api.py`) | Returns the settings, including `craft_default_enabled` and `craft_instructions`. |
| GET | `/api/build/admin/base-instructions` | `get_base_instructions` (`backend/onyx/server/features/build/api.py:56`) | Returns the raw `AGENTS.template.md`, for the Preferences page's read-only preview. |
| GET/PATCH/POST/DELETE | `/api/build/admin/apps*` | `backend/onyx/server/features/build/external_apps/api.py` (`admin_router`) | Built-in create/patch (`/apps/built-in`, `/apps/{id}`), custom create (`/apps/custom`), list, catalog options, delete. Gated by `Permission.FULL_ADMIN_PANEL_ACCESS` only, **not** by `require_onyx_craft_enabled` (see §9). |
| POST/DELETE | `/api/admin/llm/default-craft` | `set_provider_as_default_craft` / `clear_default_craft` (`backend/onyx/server/manage/llm/api.py`, `Permission.MANAGE_LLMS`; see `[[llm-providers]]`) | The Craft default-model picker on the Preferences page. |

`GET /api/manage/users` (`useAdminUsers` hook) returns each `UserRow` with
`craft_enabled: bool | None`, the per-user override the Access table renders.

### Environment / flags

| Variable | Where | Effect |
|---|---|---|
| `ENABLE_CRAFT` | `backend/onyx/server/features/build/configs.py:72` | Deployment-level Craft switch when no PostHog provider is configured. |
| `onyx-craft-enabled` (PostHog flag) | `build/utils.py:ONYX_CRAFT_ENABLED_FLAG` | Deployment-level switch when PostHog is configured; evaluated per user/tenant. |
| `AUTO_PROVISION_DEFAULT_EXTERNAL_APPS` | `backend/onyx/configs/app_configs.py:AUTO_PROVISION_DEFAULT_EXTERNAL_APPS` (default `false`) | Seeds Onyx-managed built-in apps (disabled) on tenant creation; `true` on Cloud. |

---

## 3. Data model

- `User.craft_enabled: bool | None` (`backend/onyx/db/models.py:351`): the
  per-user override. `None` means "follow the workspace default."
- `Settings.craft_default_enabled: bool` (default `True`) and
  `Settings.craft_instructions: str | None`
  (`backend/onyx/server/settings/models.py:96-104`): the workspace-wide Craft
  policy and org instructions, both stored on the general settings row (see
  the settings component for the storage mechanism; this document does not
  own that table).
- `ExternalApp`, `ExternalAppUserCredential`, `ExternalApp__Skill`
  (`backend/onyx/db/models.py`, read through `backend/onyx/db/external_app.py`):
  the configured app, each user's stored per-user credential, and the skill(s)
  an app is wired to.
- `GatedApp` (`backend/onyx/db/models.py`, read through `backend/onyx/db/gated_app.py`):
  the shared identity row for anything policy-gated, keyed by
  `(kind, target_id)` where `kind` is `GatedAppKind.EXTERNAL_APP` or
  `GatedAppKind.MCP_SERVER`. External apps and MCP servers share one gating
  mechanism through this row.
- `GatedActionPolicy`: sparse per-action overrides
  (`{gated_app_id, action_id, policy}`, `policy` one of
  `EndpointPolicy.ALWAYS | ASK | DENY`), written by
  `replace_action_policies__no_commit` (`backend/onyx/db/gated_app.py:80`).
  Unset actions resolve to the catalog's `default_policy`, not a stored row.
- `ExternalApp.default_policy`: the fallback for off-catalog built-in requests
  and the entire blanket policy for a custom app
  (`docs/craft/features/external-apps/action-policies.md`).
- `LLMModelFlow` row with `llm_model_flow_type = LLMModelFlowType.CRAFT`
  (`backend/onyx/db/llm.py`, `fetch_default_craft_model`): the Preferences
  page's default-model selection. See `[[llm-providers]]`.

---

## 4. How it works

### 4.1 Access: resolving whether a user can use Craft

```
require_onyx_craft_enabled                  server/features/build/api.py
  └─ is_craft_enabled_for_user              server/features/build/utils.py
       ├─ User.craft_enabled override        (per-user; short-circuits if False)
       ├─ Settings.craft_default_enabled      (workspace default, when override is None)
       └─ is_craft_available_for_deployment   (PostHog flag or ENABLE_CRAFT)
```

`is_craft_enabled_for_user` (`build/utils.py:156`) is the single source of
truth: `AccountType.ANONYMOUS` users never get Craft (it is identity-bound: a
per-user sandbox, library, and scheduled tasks), then the per-user override
wins if set to `False`, then the workspace default gates `None`, and finally
the deployment-level flag must also be true. All three settings-page toggles
(the per-user switch, the workspace default switch, and the deployment flag)
feed this one function; nothing else in the codebase re-implements the
decision.

The admin Access page never calls this function directly. It reads
`Settings.craft_default_enabled` and each `User.craft_enabled` through
`GET /api/manage/users`, and writes through
`PATCH /api/manage/admin/users/craft-enabled`
(`web/src/views/admin/CraftPage/svc.ts:setUsersCraftAccess`). A toggle that
matches the workspace default clears the override (sends `null`) rather than
storing a redundant explicit value
(`web/src/views/admin/CraftPage/AccessCell.tsx`).

### 4.2 Apps: what an admin configures and how it is enforced

An admin action on `/admin/craft/apps` is one of: enable/disable an app,
edit its `auth_template` and `organization_credentials` (self-hosted only),
edit its per-action policy, or associate/detach a skill. All of these route
through `backend/onyx/db/external_app.py` (`update_external_app`,
`_write_policies__no_commit`) and, for policy, into the shared `gated_app`
tables in §3.

Enforcement is a separate runtime, the sandbox egress proxy, which reads what
the admin configured:

```
outbound HTTPS request from a Craft sandbox
  └─ resolve_app_for_url                 sandbox_proxy/request_evaluator.py
       (matches request.url against enabled apps' upstream_url_patterns)
  └─ recognize_actions / apply_credential_gate
       external_apps/matching/engine.py
       (classifies the request into one or more catalog action_ids,
        each carrying its resolved EndpointPolicy)
  └─ gate addon                           sandbox_proxy/addons/gate.py
       DENY   -> http_403(POLICY_DENIED)
       ALWAYS -> inject credentials, forward
       ASK    -> hold for the approval flow (see [[background-jobs]] for the
                 scheduled/async surface; approvals are out of this doc's scope)
```

Credential injection (`sandbox_proxy/credential_injection.py`) is a separate
concern from policy: a resolver only injects a secret for an app the user has
connected. A request that matches no connected app's `upstream_url_patterns`
is not gated by this pipeline at all (`matched_actions is None` in
`request_evaluator.py`); see §5 for what governs that traffic instead.

### 4.3 Preferences: what an admin sets

Two independent settings, both read by the sandbox at session-start:

**Organization instructions.** The admin's free-text `craft_instructions`
(max 4000 characters client-side, `web/src/views/admin/CraftPreferencesPage/index.tsx:MAX_INSTRUCTIONS_LENGTH`)
is saved onto `Settings.craft_instructions` via the same
`updateAdminSettings` call every other settings page uses. At session-start,
`kubernetes_sandbox_manager.py:453` calls
`generate_agent_instructions(organization_instructions=load_settings().craft_instructions, ...)`,
which (`agent_instructions.py:build_organization_instructions_section`) renders
it as:

```
## Organization instructions

Your organization's admins set these workspace-wide instructions. Follow them
in every session; the Hard rules above still win on any conflict.

<the admin's text>
```

and splices that section into the sandbox's generated `AGENTS.md`. This
confirms the earlier finding: `craft_instructions` **is** what becomes the
"## Organization instructions" section. An empty or whitespace-only value
renders nothing (no empty heading).

**Default model.** The picker calls `setDefaultCraftModel` /
`deleteDefaultCraftModel` (`web/src/lib/languageModels/svc.ts`), which hit
`POST` / `DELETE /api/admin/llm/default-craft`. That endpoint writes the
`LLMModelFlow` row for `LLMModelFlowType.CRAFT`
(`backend/onyx/db/llm.py:update_default_craft_provider`).
Per `[[llm-providers]]`, `CRAFT` is a **pointer flow, not a capability check**:
nothing populates this row automatically, and Craft falls back to the
workspace chat default (`defaultText` in the page) when no explicit Craft
default is configured. The page resolves and shows this fallback itself
(`inheritedSelection` in `CraftPreferencesPage/index.tsx`) so a per-admin
`localStorage` model pick can never leak into what the page reports as the
workspace value. A hidden/deprecated model that was previously set as default
still resolves, so an admin can see and clear it even after it is hidden.

### Where to go next

This document stops at the admin surface. For the parts it deliberately does
not cover:

- **Sandboxes** (isolation, egress lockdown mechanics, network policy):
  `docs/craft/sandbox/image-and-spinup.md`,
  `docs/craft/sandbox/sandbox-podtemplate.md`,
  `docs/craft/infra/sandbox-worker-network-policy.md`.
- **Snapshots** (session persistence across restarts):
  `docs/craft/infra/snapshot-retention.md`.
- **Streaming** (turn execution and event delivery):
  `docs/craft/sandbox/sandbox-exec-sidecar.md`,
  `docs/craft/ui/packet-rendering-overhaul.md`.
- **The webapp proxy** (previewing a sandbox's running app):
  `docs/craft/lazy-webapp-provisioning.md`.
- **Scheduled tasks** (the `/build/admin` surface does not cover these; they
  are user-configured, not admin-configured):
  `backend/onyx/server/features/build/scheduled_tasks/`.
- **Approvals** (the `ASK` hold/prompt UX referenced in §4.2):
  `backend/onyx/server/features/build/approvals/api.py`,
  `docs/craft/features/external-apps/action-policies.md`.
- **OAuth token refresh** for connected apps:
  `docs/craft/features/external-apps/oauth-token-refresh.md`.

---

## 5. Contracts and invariants

1. **Craft access gating is enforced server side, on every `/build` request,
   not only by hiding the sidebar link.** `require_onyx_craft_enabled`
   (`build/api.py:require_onyx_craft_enabled`) is a router-level FastAPI
   dependency on the user-facing `/build` router. The separate `/build/admin`
   router does not use it (item 5). The frontend's `craftAvailable` flag only controls whether
   the nav item and page render; it grants nothing by itself.
2. **A disabled app gets no credential injection.**
   `ExternalAppResolver` renders headers through
   `external_apps/credentials.py:resolve_injection_headers`. That function
   returns `{}` when the app is missing or not `enabled`. Otherwise it merges the
   organization credentials with the user's `ExternalAppUserCredential`, if any.
   An org-credentialed app needs no per-user row. Disabling an app does not
   delete stored user credentials.
3. **A connected app's `DENY`-policied action is blocked before any upstream
   connection for that action, not just hidden from the agent's tool list.**
   The gate addon (`sandbox_proxy/addons/gate.py`) returns `http_403` before
   forwarding; it does not rely on the agent choosing not to attempt the call.
4. **General internet egress from a sandbox is not the same guarantee as
   "admin-approved."** Requests that match no connected app's
   `upstream_url_patterns` are not evaluated by the action-policy gate at all
   (`matched_actions is None`); the proxy forwards them unchanged. The
   sandbox's iptables lockdown (`firewall-init.sh`) drops all outbound traffic
   except to the proxy. Public-host access (needed for `npm`, `pip`, etc.)
   therefore goes through the proxy. **The admin-configured app policy governs
   only requests attributed to a connected app or MCP server; it is not a
   general internet allowlist.** State this precisely when reasoning about
   "can a sandbox reach an unapproved service": it can reach arbitrary public
   hosts, but it cannot authenticate as an org-connected app it wasn't granted,
   and a connected app's `DENY`-policied actions are blocked.
5. **`/build/admin/*` endpoints are gated by `FULL_ADMIN_PANEL_ACCESS` alone,
   deliberately not `require_onyx_craft_enabled`.** An admin configuring Craft
   for the org may not have Craft enabled for themselves
   (`build/api.py:46-47`, comment on `admin_router`).
6. **`craft_instructions` reaching the agent is deterministic, not
   best-effort.** It is read fresh from `load_settings()` at session-start
   (not cached in the sandbox image) and always occupies the same template
   position (`agent_instructions.py`), so a change takes effect on the next
   new session without a rebuild.
7. **A `GatedApp` row's identity is `(kind, target_id)`, never a name.**
   Self-hosted GitLab/Jira instances can share an `app_type`, and two MCP
   servers can share a display name; anything that looks up policy or grants
   by name instead of `(kind, id)` will silently collide.

---

## 6. Relationships

**Depends on**
- [[access-control]]: `Permission.FULL_ADMIN_PANEL_ACCESS` gates every admin
  endpoint in this document except the Craft default-model endpoints, which
  use `Permission.MANAGE_LLMS` (see `[[llm-providers]]`).
  `Permission.BASIC_ACCESS` gates the underlying `/build` user-facing router.
- [[auth-and-identity]]: `AccountType.ANONYMOUS` is excluded from Craft
  entirely; per-user OAuth credentials for external apps depend on the acting
  user's identity.
- [[editions-and-gating]]: `is_craft_available_for_deployment` reads a
  PostHog feature flag (or `ENABLE_CRAFT`), a deployment-level switch distinct
  from any billing-tier check; `requiredTier: null` on all three routes
  confirms Craft admin visibility is not tier-gated at the nav level.
- [[llm-providers]]: the Preferences default-model picker is the `CRAFT`
  `LLMModelFlowType`; see `llm-providers.md` §9 for why it is a pointer, not a
  capability check.
- [[agents-personas]]: Craft instructions are analogous to (but a separate
  mechanism from) a persona's custom agent prompt; both ultimately shape what
  the agent sees, through different templates.
- [[code-execution]]: the sandbox this document configures access and policy
  for is where Craft's code actually runs.
- [[multi-tenancy]]: `Settings`, `User.craft_enabled`, and every `ExternalApp`
  row are tenant-scoped; the PostHog flag check is evaluated per tenant.
- [[background-jobs]]: Craft scheduled tasks and the `ASK` approval hold both
  run through async/background infrastructure this document does not own.

**Depended on by**
- Every Craft sandbox session: reads `is_craft_enabled_for_user`,
  `craft_instructions`, the default-model row, and the egress ruleset this
  document's pages configure.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| changes the access gate (`is_craft_enabled_for_user`, the PostHog flag, or `ENABLE_CRAFT`) | every user-facing `/build` route (they all sit behind `require_onyx_craft_enabled`; `/build/admin` routes do not); the Access page's `enabledCount` math (`CraftPage/index.tsx`); anonymous-user exclusion |
| adds an external app (built-in or custom) | the egress ruleset the proxy reads (`sandbox_proxy/request_evaluator.py`); the app's `default_policy` seed (`DENY` for built-in, admin-chosen for custom); its `upstream_url_patterns` regex correctness (a bad regex is silently skipped, not rejected); the skill it may be associated with, see [[mcp-and-custom-tools]] |
| changes the egress policy (an action's `ALWAYS/ASK/DENY`, or `default_policy`) | `sandbox_proxy/addons/gate.py`'s three branches; the credential-injection path for `ALWAYS` (a token refresh failure there still blocks); the `external-app-skill-action-availability` doc, since `DENY`d actions are meant to be fenced out of the pushed `SKILL.md` |
| changes admin instructions (`craft_instructions` or the base template) | `agent_instructions.py:generate_agent_instructions` and both sandbox managers (`docker_sandbox_manager.py`, `kubernetes_sandbox_manager.py`) that call it; the Preferences page's base-instructions preview (`GET /build/admin/base-instructions`) must still reflect the template a change touches |
| changes the Craft default model | `[[llm-providers]]`'s blast radius for `LLMModelFlowType.CRAFT`; the fallback-to-chat-default resolution in `CraftPreferencesPage` |
| changes `GatedApp` / `GatedActionPolicy` shape | both consumers: the admin API (`external_apps/api.py`) and the live proxy (`sandbox_proxy/request_evaluator.py`, `addons/gate.py`); MCP servers share this table, so an external-app-only migration will silently break MCP gating |

---

## 8. How to verify a change

### Tests

```bash
# Access gating
cd backend && uv run pytest tests/external_dependency_unit/craft/test_craft_access_admin.py
cd backend && uv run pytest tests/unit/onyx/server/features/craft/test_feature_gate.py

# External apps: admin CRUD, policy, credentials, Cloud-managed lockdown
cd backend && uv run pytest tests/external_dependency_unit/craft/test_custom_external_app_create.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_external_app_admin_update.py
cd backend && uv run pytest tests/external_dependency_unit/craft/test_managed_external_apps.py
cd backend && uv run pytest tests/integration/tests/external_apps/test_external_app_action_policies.py
cd backend && uv run pytest tests/integration/tests/external_apps/test_external_apps.py
cd backend && uv run pytest tests/unit/external_apps/matching/test_engine.py

# Sandbox network posture (the actual egress lockdown behind §5.4)
cd backend && uv run pytest tests/integration/tests/craft/docker_e2e/test_sandbox_network_posture_docker.py

# Craft default model
cd backend && uv run pytest tests/external_dependency_unit/llm/test_llm_provider_default_craft_model.py

# Frontend end-to-end
cd web && bun run playwright tests/e2e/craft/craft_onboarding.spec.ts
```

`web/tests/e2e/craft/` currently covers onboarding, not the three admin pages
directly; a new admin-page Playwright spec would be the first of its kind
there.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Sign in as `admin_user@example.com` / `TestPassword123!` at
   `http://localhost:3000`, and go to `/admin/craft/access`.
3. Flip the workspace default off, confirm the modal, and verify a
   non-overridden user's effective toggle follows it. Set one user's override
   opposite to the default and confirm it sticks independently.
4. Go to `/admin/craft/apps`. Enable a built-in app, set one action to
   `DENY`, and confirm on `/admin/craft/preferences` (or in a live Craft
   session) that the agent's attempt at that action is blocked, not silently
   ignored.
5. Go to `/admin/craft/preferences`. Set organization instructions, save, and
   start a new Craft session; confirm the "## Organization instructions"
   section appears in the sandbox's `AGENTS.md` with the saved text verbatim.
6. Set and then clear a Craft default model; confirm the picker shows the
   "inherited" tag and the workspace chat default once cleared.

### What "working" looks like

- A user with `craft_enabled=False` (override or inherited from a `False`
  workspace default) gets a `403 INSUFFICIENT_PERMISSIONS` from every
  `/build` endpoint, not just a hidden UI.
- A `DENY`-policied action is blocked at the proxy (`POLICY_DENIED` in the
  sandbox-facing 403), never reaches the upstream host.
- Saved `craft_instructions` appear in every new session's `AGENTS.md`
  exactly once, in the same template position.

---

## 9. Footguns

- **Craft/Build naming split.** The product is "Craft" everywhere in the UI
  and docs; the backend router, its directory, and most Python identifiers say
  "Build" (`backend/onyx/server/features/build/`, `/build` prefix,
  `docker_sandbox_manager` comments, `BUILD_MODE_FEATURE_ID`). Do not expect
  `grep -r craft backend/` to find the router; search for `build` too. See
  `GLOSSARY.md`.
- **The Apps page governs MCP servers too**, not only external apps.
  `ExternalAppsPage` renders both external apps and MCP servers as one
  normalized "governed integration" list (`ConfiguredIntegration` in
  `interfaces.ts`) sharing the same `GatedApp` policy mechanism. A change
  scoped to "external apps only" easily misses the MCP tab.
- **`craftAvailable` in settings is not the enforcement gate.** The frontend
  flag only decides what renders; the actual gate is
  `is_craft_enabled_for_user`, evaluated per request on the backend. Testing
  only the frontend flag gives false confidence.
- **An unset action is not "no policy."** It resolves to the catalog's
  `default_state` at read time (`get_action_policies` only returns explicit
  overrides). A new catalog action changes behavior for every existing app
  with no backfill and no visible DB row change.
- **General internet reachability from a sandbox is intentional, not a
  leak.** Do not treat "the sandbox can reach `example.com`" as a policy
  violation; only requests attributed to a connected app or MCP server are
  policy-gated. See §5.4.
- **Onyx Cloud built-in apps hide their own credential form.** `is_onyx_managed`
  blanks `organization_credentials`, `auth_template`, and
  `upstream_url_patterns` in the admin response; an admin on Cloud can only
  toggle enablement and edit policy for these, by design
  (`docs/craft/features/external-apps/cloud-managed-app-credentials.md`).
- **`app_type` is immutable on update.** `update_external_app` raises rather
  than allowing a cross-edit between built-in and custom; deleting and
  recreating is the only path to change it.
- **The Preferences page's `fallbackToDefault={false}` on the model picker is
  deliberate.** It exists so an admin's own remembered `localStorage` model
  pick cannot leak into what the page reports as the workspace default; do
  not "simplify" this away.
