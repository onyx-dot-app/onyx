# Craft Admin

> The admin controls for Onyx Craft: who may use it, which apps and MCP servers
> a sandbox may act through with which action policies, and the organization
> instructions and default model that each session starts with.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE. On multi-tenant Cloud, Onyx-managed built-in apps are locked to enable/disable and policy edits.

---

## User experience

An admin with full admin-panel access manages Craft access, plugins, and
preferences such as organization instructions and the Craft default model.

**Access.** The admin sets a workspace default (Craft on or off for everyone;
on until an admin changes it) and overrides it for single users or in bulk. A
user whose effective access is off cannot open Craft. Every route on the Craft
user router returns 403, not only a hidden link. The shared-webapp preview does
not check Craft access, and a static preview checks the owner's access, not
the viewer's ([[#preview-routes-skip-access-gate]]). When the admin turns access off for the owner of a scheduled
task, the next fire records a skipped run instead of running
([[craft-scheduled-tasks]]).

**Plugins.** The admin sees built-in apps, custom apps and MCP servers on one
Plugins page. For each one the admin can turn it on or off for Craft, set
credentials, attach skills, and set a policy per action: Auto-approve
(`ALWAYS`), Ask (`ASK`) or Disabled (`DENY`). A switch decides whether users
may override the workspace policy with their own choices. When the agent later
tries a Disabled action, the call fails with a policy error. When it tries an
Ask action, the user gets an approval card in the session. On Onyx Cloud, the
admin cannot see or edit credentials or URL patterns of Onyx-managed built-ins,
and cannot create or delete them. The admin can only enable them and set
policy.

**Preferences.** The admin writes organization instructions and picks a Craft
default model. Instructions appear in each new session's `AGENTS.md` under an
"Organization instructions" heading. A read-only preview shows the base
template the text is added to. With no Craft default model, sessions use the
workspace chat default, and the page shows that model as inherited.

In this document "workspace" always means the tenant-wide scope (workspace
default, workspace policy). The sandbox directory of a session is the "session
workspace" ([[craft-sandboxes]]).

---

## Scope

This component owns:
- the access decision for each user and its enforcement on every Craft user
  route;
- the Craft admin router and its routes: external-app configuration, the
  read-only workspace policy views, and the base-instructions preview;
- the Craft admin pages (Access, Preferences) and the external-app admin
  editor.

Neighbours own the rest:
- [[craft-external-apps]]: what a policy means at request time, the precedence
  of workspace, personal and task choices, the action catalogs, and OAuth.
- [[mcp-and-custom-tools]]: the MCP server admin routes. They write the same
  policy tables ([[#two-gates-one-policy-table]]).
- [[plugins]]: the Plugins page shell, which hosts the external-app editor,
  and the MCP and OpenAPI editors.
- [[chat-preferences]]: the workspace `Settings` store, which holds the Craft
  default and the organization instructions. The admin writes them through
  `PATCH /admin/settings`, like any other workspace setting.
- [[llm-providers]]: the `CRAFT` model flow behind the default-model picker.
- [[craft-sandboxes]]: renders the instructions into the session instructions file.

---

## Architecture

The product name is "Craft". Most backend code says "build"
(`backend/onyx/server/features/build/`, the `/build` prefix). Search for both.

```
Access decision (per request)
  require_onyx_craft_enabled                       server/features/build/api.py
    -> is_craft_enabled_for_user                   server/features/build/utils.py
         ANONYMOUS account        -> no
         User.craft_enabled False -> no
         User.craft_enabled None  -> Settings.craft_default_enabled must be true
         User.craft_enabled True  -> skips the workspace default
         then is_craft_available_for_deployment:
           PostHog flag "onyx-craft-enabled" (or ENABLE_CRAFT without PostHog)
           AND tier_at_least(current tier, LLM_GATEWAY_MIN_TIER)
```

`backend/onyx/server/settings/api.py:fetch_settings` evaluates the same functions and
returns `onyx_craft_available`, `onyx_craft_enabled` and
`onyx_craft_requires_upgrade`. The admin sidebar shows the Craft section when
`onyx_craft_available` is true (`web/src/lib/admin-routes.ts`). When the flag
is on but the tier is too low, `server/features/build/utils.py:is_craft_locked_by_tier`
makes the web app show an upgrade page instead of Craft. The tier rule exists
because every Craft turn calls the tier-gated LLM gateway.

**Access writes.** `server/manage/users.py:set_user_craft_access` sets or
clears `User.craft_enabled` and writes an audit event. The Access table sends
`null` when a toggle matches the workspace default, so the user follows later
default changes (`web/src/views/admin/CraftPage/AccessCell.tsx`).

**Policy writes.** Every workspace policy write goes through
`db/action_policy.py:replace_workspace_action_policies`, keyed by a `GatedApp`
row for `(kind, target_id)`:

```
External app (FULL_ADMIN_PANEL_ACCESS)        MCP server (MANAGE_ACTIONS, scoped allowed)
  PATCH /build/admin/apps/{id}                  PATCH /admin/mcp/server/{id}
    update_external_app                           update_mcp_server_simple
    -> _write_policies__no_commit               POST setup flows
    -> replace_workspace_action_policies          _publish_mcp_setup
  commit, then push_skills_for_users            -> replace_workspace_action_policies
  (SKILL.md lists DENY actions as unavailable)  commit, then _hot_reload_craft_sessions
                                                (restamps mcp_config_hash only)
```

`replace_workspace_action_policies` validates action ids against the catalog
and stores only the entries that differ from the catalog default
(`external_apps/providers/registry.py:normalize_action_policies`). A submitted
map replaces the old rows. It does not merge.

**Instructions.** A sandbox manager reads `Settings.craft_instructions` with
`load_settings()` when it builds a session's `AGENTS.md`
(`backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py:KubernetesSandboxManager._load_agent_instructions`
and the Docker equivalent).
`backend/onyx/server/features/build/sandbox/util/agent_instructions.py:build_organization_instructions_section`
renders it. Empty or whitespace text renders nothing. A change reaches new
session workspaces and regenerated session configs without an image rebuild.
`fetch_settings` hides the text from anonymous callers only.

**Default model.** `server/manage/llm/api.py:set_provider_as_default_craft`
(`MANAGE_LLMS`) sets the `CRAFT` pointer.
`backend/onyx/server/features/build/session/manager.py:SessionManager.build_llm_configs` tries the Craft default,
then the chat default.

---

## Contracts and traps

1. `admin-router-no-craft-gate` **`/build/admin` must not use
   `require_onyx_craft_enabled`.** An admin who configures Craft may not have
   Craft for themselves. The comment on `server/features/build/api.py:admin_router`
   states this. A new admin route goes on `admin_router`; a new user route
   goes on `router`.
2. `frontend-flag-not-gate` **The frontend flag is not the gate.**
   `onyx_craft_available` only decides what the sidebar shows. The backend
   dependency (`server/features/build/api.py:require_onyx_craft_enabled`)
   decides access on every request. A test that checks only the UI
   proves nothing about access.
3. `true-override-beats-default` **A `True` override beats a workspace default
   of `False`.** Only the deployment check can still deny that user. Code that
   reads `craft_default_enabled` alone gives the wrong answer for overridden
   users (`server/features/build/utils.py:is_craft_enabled_for_user`).
4. `two-gates-one-policy-table` **Two permission gates write the same policy
   tables.** External-app policies need `FULL_ADMIN_PANEL_ACCESS`. MCP policies
   need `MANAGE_ACTIONS`, and a group-scoped action manager may write them for
   its servers. `web/src/lib/plugins/hooks.ts:useInstalledPlugins` must not
   fetch the external-app admin list (organization credentials) for a user
   without full admin access.
5. `save-paths-refresh-differently` **The save paths refresh sandboxes
   differently.** The external-app PATCH commits, then calls
   `skills/push.py:push_skills_for_users` so the skill file lists DENY actions as
   unavailable (`skills/rendering.py:build_action_availability_section`).
   Built-in create and app delete push before commit, so a push failure rolls
   the write back. Custom create pushes nothing. The MCP routes only restamp
   `mcp_config_hash`; tool policies need no push because the proxy reads them
   live. A new write route must pick one of these on purpose.
6. `unset-action-is-catalog-default` **An unset action is not "no policy".**
   It resolves to the catalog `default_policy` at read time, and an override
   equal to the default is not stored. Every MCP tool has the default `ASK`
   (`db/action_policy.py:_catalog_defaults`). A change to a catalog default changes
   behaviour for every app that kept the default, with no migration and no
   row change.
7. `app-type-immutable` **`app_type` cannot change on update.** The PATCH
   request has no `app_type` field, and `db/external_app.py:update_external_app`
   raises on a mismatch, because the type decides the skill and provider.
   Delete and recreate instead.
8. `managed-builtins-locked-multi-tenant` **Onyx-managed built-ins are locked
   only when `MULTI_TENANT`.** `backend/onyx/server/features/build/external_apps/api.py:_to_admin_response` blanks
   credentials, auth template and URL patterns. The create and delete routes
   refuse them. The PATCH route silently ignores those three fields and
   applies the rest (`enabled`, name, policies, the user-management switch and
   skill associations). Self-hosted built-ins of the same type
   stay editable. A new admin field for apps needs the same `managed` check.
9. `masked-credentials-round-trip` **Masked credentials round-trip.** The
   admin response masks organization credentials. The write path restores
   masked values that come back unchanged
   (`db/external_app.py:resolve_masked_credentials`). A per-account provider
   (Zendesk) then derives its URL patterns from the restored credentials. Do
   not compare a masked value with the stored value.
10. `preferences-picker-no-fallback` **`fallbackToDefault={false}` and
    `persistSelection={false}` on the Preferences model picker are
    deliberate.** They stop the admin's own remembered model choice from
    appearing as the workspace default, and stop the workspace pick from
    becoming the admin's personal choice
    (`web/src/views/admin/CraftPreferencesPage/index.tsx`, props defined in
    `web/src/app/craft/components/ModelPickerButton.tsx`).
11. `gated-app-identity-by-id` **A `GatedApp` row is identified by
    `(kind, target id)`, never by name.** Self-hosted instances can share an
    `app_type`, and two MCP servers can share a display name. A policy lookup
    by name collides silently (`db/models.py:GatedApp`).
12. `preview-routes-skip-access-gate` **The preview routes are outside the
    access gate.** `server/features/build/webapp_proxy.py:public_build_router`
    and `server/features/build/static_preview.py:public_router` sit under
    `/build` but do not use `require_onyx_craft_enabled`. The webapp proxy
    checks session sharing instead
    ([[craft-webapp-proxy#public-router-checks-access]]), so a user whose Craft
    access is off can still open a webapp that another user shares.
    `server/features/build/static_preview.py:read_static_preview` checks the preview token, then
    refuses with 404 when the token's owner is inactive or has lost
    `BASIC_ACCESS` or Craft access. It does not check the viewer. Do not
    assume that a path under `/build` implies the Craft gate.

---

## Known issues

- `backend/onyx/configs/app_configs.py:AUTO_PROVISION_DEFAULT_EXTERNAL_APPS` and
  `external_apps/providers/base.py:OnyxManagedExtApp.configured_managed_credentials`
  have no callers in this repository. On multi-tenant the admin API refuses to
  create a managed built-in. The code that seeds managed app rows on Cloud is
  not in this tree, so how Cloud tenants get them is unverified.
- `web/src/app/admin/craft/apps/page.tsx` only redirects old app links to the
  Plugins page. It is a false lead for app admin work.

---

## Dependencies

- [[craft-external-apps]]: enforces the policies, owns precedence, catalogs
  and OAuth.
- [[mcp-and-custom-tools]]: MCP server routes and data that share the policy
  tables.
- [[craft-sandboxes]]: renders organization instructions into `AGENTS.md`.
- [[skills]]: `push_skills_for_users` and skill association rules.
- [[llm-providers]]: the `CRAFT` model flow.
- [[editions-and-gating]]: `tier_at_least` and the PostHog flag provider.
- [[authorization]]: `require_permission` and the group-scoped action manager.
- [[auth-and-identity]]: the anonymous account type.

---

## Recipes

- `admin-endpoint` **A Craft admin endpoint.** Copy `GET /build/admin/base-instructions` in
  `server/features/build/api.py`. List the admin routes with
  `git grep -n '@admin_router\.' backend/onyx/server/features/build/`. Put the
  route on `admin_router` or a router included there. Do not add
  `require_onyx_craft_enabled` ([[#admin-router-no-craft-gate]]).
- `workspace-setting` **A workspace setting for Craft.** Copy `craft_instructions`. List the Craft
  settings with `git grep -n craft_ backend/onyx/server/settings/models.py`.
  Read the value with `load_settings()` at the point of use. If a sandbox
  needs it, read it where `AGENTS.md` or the opencode config is built, not at
  image build time.
- `external-app-admin-field` **A new admin field for an external app.** Copy `users_can_manage_policies`
  on the create and PATCH requests in `server/features/build/external_apps/api.py`.
  Add the `managed` check ([[#managed-builtins-locked-multi-tenant]]) and pick
  a refresh path ([[#save-paths-refresh-differently]]).
- `investigate-craft-off` **Investigate "Craft is off for me".** Read `GET /api/settings` as that user
  through the frontend: `onyx_craft_available` false means the flag or the
  tier, `onyx_craft_requires_upgrade` true means the tier. Then read
  `User.craft_enabled` for the user and `craft_default_enabled` in the
  workspace settings, and apply the table in Architecture.
- `setup-access-override` **Set up an override for a test.** Set one user's override opposite to the
  workspace default, flip the default, and confirm that user keeps the
  override.

---

## Verification

- Access and the feature gate: `backend/tests/external_dependency_unit/craft/`
  and `backend/tests/unit/onyx/server/features/craft/`.
- External-app admin and the Cloud lockdown:
  `backend/tests/external_dependency_unit/craft/`.
- Policy storage: `backend/tests/external_dependency_unit/permissions/` and
  `backend/tests/integration/tests/external_apps/`.
- Default model: `backend/tests/external_dependency_unit/llm/`.
- By hand: save organization instructions, start a new session, and confirm
  the section in the session's `AGENTS.md`.
