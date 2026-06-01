# Cloud-Managed External-App Credentials — Plan

> **Scope.** On Onyx Cloud, **Onyx owns the OAuth credentials** for built-in
> external apps. Every built-in app is **pre-provisioned (disabled) into each
> tenant** with Onyx's credentials already populated. A tenant admin's only
> actions are to **enable/disable** an app and **configure its action policies** —
> they cannot create built-in apps, cannot see or edit the credentials, and
> cannot delete the apps. Users then run the normal per-user OAuth flow against
> Onyx's app. Builds on the existing external-app subsystem
> ([action-policies.md](./action-policies.md),
> [oauth-token-refresh.md](./oauth-token-refresh.md)).

## Refined requirement

Today a tenant admin must register their own OAuth application with each
provider, obtain a `client_id` / `client_secret`, and paste them into the app's
`organization_credentials` before anyone can use a built-in app. On managed
cloud we want to remove that entirely and own the credentials ourselves:

1. **One built-in app per type.** A tenant may have at most **one** built-in
   external app of a given `app_type` (Gmail, Slack, Google Calendar, Linear).
   (`CUSTOM` apps are exempt — a tenant can have many.)
2. **Cloud pre-provisions all built-ins.** When a tenant is created, Onyx
   provisions **every** built-in app into that tenant, with Onyx's credentials
   already populated, **initially disabled**.
3. **Admins toggle + set policies only.** A tenant admin enables/disables a
   provisioned app and configures its action policies. That is the entire
   surface.
4. **Cloud admins cannot, for built-in apps:** create them (they already exist,
   and only one per type is allowed), update credentials (Onyx-owned), or delete
   them.
5. **Hide the rest.** The admin UI/API for a cloud built-in app exposes only its
   identity, enabled state, and policies — never the credentials or gateway
   config.
6. **Users authenticate normally.** Once enabled, each user runs the existing
   OAuth flow and gets their own per-user token against Onyx's OAuth app.
7. **Self-hosted is unchanged** except that the new one-per-type rule now
   applies there too; self-hosted admins still create built-ins and supply their
   own credentials.

## Design decision: cloud + built-in ⟹ Onyx-managed

We do **not** add a separate `managed_external_app` table or a
`creation_source` column. In cloud, **every built-in app is Onyx-managed by
definition** (admins can't create their own), so the discriminator is simply:

```
is_managed(app) := MULTI_TENANT  and  app.app_type != ExternalAppType.CUSTOM
```

- Credentials live in the existing `external_app.organization_credentials`
  column (seeded server-side at provisioning; see below). No new storage.
- The one-per-type rule (req. 1) guarantees a built-in `app_type` uniquely
  identifies its row within a tenant, so the cloud restrictions can key off
  `app_type` alone.
- `MULTI_TENANT` (`backend/shared_configs/configs.py:167`) /
  `AuthType.CLOUD` (`backend/onyx/configs/constants.py:314`) gates all cloud-only
  enforcement; self-hosted code paths are untouched apart from the uniqueness
  constraint.

This is the "seed the external_apps table directly" approach, with the
managed-vs-user ambiguity resolved by environment + app type rather than by an
extra column or table.

## Issues to Address

- **No uniqueness on built-in `app_type`.** The model explicitly allows
  duplicates today (`backend/onyx/db/models.py:5850-5854` comment: "NOT
  unique"). Requirement 1 reverses that for non-`CUSTOM` types.
- **No cloud provisioning of built-ins.** `provision_tenant`
  (`backend/ee/onyx/server/tenants/provisioning.py:177`) seeds default LLM
  providers (`configure_default_api_keys`, `:324`) but nothing seeds external
  apps. We need to provision every built-in (disabled, with Onyx creds) here.
- **Admin write paths are unrestricted.** All of these allow a tenant admin to
  do things cloud must forbid for built-ins
  (`backend/onyx/server/features/build/api/external_apps_api.py`):
  - create — `POST /admin/apps` create branch (`:110`, `request.id is None`);
  - edit credentials/config — same endpoint's update branch (`:135`);
  - delete — `DELETE /admin/apps/{external_app_id}` (`:392`);
  - the "available built-ins to add" lists feed a create UI that must be hidden
    in cloud — `GET /admin/apps/built-in/options` (`:376`).
- **Credentials are exposed (masked) to the admin.** `_to_admin_response`
  (`:56`) returns masked `organization_credentials` and the full gateway config.
  For cloud built-ins it must expose **only** identity + enabled + policies.

## Important Notes (from research)

- **Provider registry is the source of "all built-ins."** `_PROVIDER_CLASSES` /
  `fetch_available_built_in_apps()`
  (`backend/onyx/external_apps/providers/registry.py:17,155`) enumerate every
  built-in and carry each provider's `auth_template`, `upstream_url_patterns`,
  `required_org_credential_fields`, and default action policies — everything the
  provisioning seed needs except the secret values.
- **Per-tenant seeding from operator config is the established pattern.**
  `configure_default_api_keys` (`provisioning.py:324`) and
  `seed_exa_provider_from_env.py` both read operator secrets from env/config,
  encrypt with the existing crypto, and write per tenant. We reuse that posture
  for the external-app credentials.
- **`create_external_app`** (`backend/onyx/db/external_app.py`) already builds
  the skill + app + default policies; the provisioning seed calls it with
  `enabled=False`.
- **Single-instance built-ins only.** The current built-ins (Slack, Google
  Calendar, Gmail, Linear) are all single-instance, so one-per-type is safe. A
  future multi-instance built-in (e.g. self-hosted GitLab/Jira) would not fit
  this rule and would have to be modeled as `CUSTOM` or revisited — call this
  out so the reversed uniqueness decision is intentional.
- **Encryption** is unchanged: `organization_credentials` is already
  `EncryptedJson` / `SensitiveValue`.

## Implementation strategy

### 1. One-per-type uniqueness (all deployments) — already enforced

**No migration needed.** A built-in app is created through
`create_built_in_skill_row__no_commit` (`onyx/db/skill.py:268`), whose slug is
the provider's stable built-in id, guarded by the existing `uq_skill_slug`
unique constraint. Each built-in `app_type` maps to exactly one skill id
(`EXTERNAL_APP_BUILT_IN_SKILL_IDS`), so a second built-in of the same type
already fails with `OnyxError(DUPLICATE_RESOURCE)` per tenant. A separate
partial unique index on `external_app(app_type)` would be redundant and only add
migration risk, so it was intentionally **not** added. (`CUSTOM` apps repeat
freely — they don't go through the built-in slug path.) The "single-instance
built-ins only" note above records why reversing the old multi-instance comment
is safe for the current providers.

### 2. Cloud provisioning of built-ins (`provision_tenant`)

- Add an idempotent `provision_built_in_external_apps(db_session)` beside
  `configure_default_api_keys` in `ee/onyx/server/tenants/provisioning.py` — the
  cloud analogue that seeds per-tenant rows from deployment config. It
  orchestrates by calling DB-layer helpers in `onyx/db/external_app.py` (so the
  actual queries stay under `onyx/db`). For each provider in the registry,
  **upsert** one `external_app` row keyed on `app_type`:
  - config (`auth_template`, `upstream_url_patterns`, default policies) from the
    provider descriptor;
  - `organization_credentials` from operator config
    (`MANAGED_EXTERNAL_APP_CREDENTIALS` env JSON keyed by `app_type`, parsed in
    `onyx/external_apps/managed_credentials.py`), encrypted at rest;
  - `enabled=False`.
  Idempotent upsert means it's safe to re-run (it doubles as the
  backfill/rotation primitive); per-app failures are logged and skipped.
- Called from `setup_tenant` (same file), alongside `configure_default_api_keys`.
  New tenants get every built-in, disabled, with Onyx creds populated.
- **Backfill + rotation (manual ops script).** Run the same reconcile across
  existing tenants via a re-runnable `backend/scripts` management script that
  loops over `get_all_tenant_ids()`. This is the rollout-backfill, the
  rotation mechanism, and the way newly-added built-in providers reach
  already-provisioned tenants. **Decided:** rotation is a manual script we run;
  no automated beat task and no rotation-overlap handling in scope (re-running
  the script updates creds in place).
- **Decided — provision even without creds.** A built-in with no operator creds
  configured is **still provisioned** (disabled). It simply can't be
  meaningfully enabled/used until creds are seeded, and self-heals on the next
  reconcile once creds exist. We always provision the full set of built-ins.

### 3. Cloud write-path lockdown (built-in apps)

Add a single guard `assert_built_in_mutable(app_type)` (raises in cloud for
non-`CUSTOM` types) and apply it in `external_apps_api.py`:

- **Create** — `POST /admin/apps`, create branch: in cloud, reject any built-in
  create with `OnyxError(INVALID_INPUT, "Built-in apps are provided by Onyx and
  cannot be created.")`. (The uniqueness index is a second line of defense.)
- **Update** — `POST /admin/apps` update branch: in cloud, for a built-in,
  accept **only** `enabled` and `action_policies`; reject (or ignore) any change
  to `organization_credentials`, `auth_template`, `upstream_url_patterns`,
  `name`, `description`. The clean contract: a cloud built-in update may toggle
  enablement and set policies — nothing else.
- **Delete** — `DELETE /admin/apps/{external_app_id}` (`:392`): in cloud, reject
  for built-in apps.
- `CUSTOM` apps (`POST /admin/apps/custom`, `:184`) are unaffected by these
  rules in cloud — they remain user-owned, create/edit/delete as today.

### 4. Hide credentials + config (read path)

- `_to_admin_response` (`:56`): for a managed (cloud built-in) app, return
  `organization_credentials={}` and blank/omit the gateway config
  (`auth_template`, `upstream_url_patterns`), exposing only `id`, `name`,
  `description`, `app_type`, `enabled`, and `actions` (policies). The secret and
  config never leave the server.
- `GET /admin/apps/built-in/options` + `/{app_type}` (`:376`, `:384`): in cloud
  these power "add a built-in" — return empty (or have the UI not call them) so
  no create affordance is offered.
- **Frontend** (`web/src/app/craft/...`): for cloud built-ins, render only the
  enable toggle + policy editor; hide the credential form, the "add built-in"
  entry point, and the delete control.

### 5. User-facing + OAuth paths (unchanged)

- `GET /apps`, `POST /apps/{id}/credentials`
  (`external_apps_api.py:445,421`) and the OAuth start/callback
  (`external_apps_oauth_api.py:83,130`) are unchanged. Once an admin enables a
  provisioned app, users OAuth in exactly as today; the existing credential
  injection / token-refresh seams read the seeded `organization_credentials`
  with no change.

## Tests

Prefer **external dependency unit tests** for the constraint, the provisioning
reconcile, and the cloud guards (they need DB + encryption and benefit from
toggling the cloud flag); one **integration** test for the admin happy path.

- **External dependency unit:**
  - Uniqueness: a second built-in of the same `app_type` is rejected; two
    `CUSTOM` apps are allowed.
  - `reconcile_built_in_external_apps`: provisions every registry built-in as
    `enabled=False` with creds from operator config; is idempotent (second run
    no-ops); populates encrypted creds.
  - Cloud guards (with the cloud flag on): create/delete/credential-edit of a
    built-in are rejected; enable-toggle and policy update succeed; `CUSTOM`
    apps are unaffected.
  - Read masking: `_to_admin_response` for a cloud built-in returns no
    credential or gateway-config material, only identity + enabled + policies.
- **Integration:**
  - In a cloud-configured run, a provisioned built-in starts disabled; the admin
    enables it and sets policies successfully; attempts to create a duplicate
    built-in, edit its credentials, or delete it are all rejected; the admin
    response exposes only policies + enabled state.
- **Out of scope here:** the full OAuth round-trip (existing tests cover it) and
  self-hosted create flows (unchanged apart from the uniqueness check, which the
  unit test covers).

## Resolved decisions

- **Provision built-ins even without creds.** We always provision the full set
  of built-in apps per tenant (disabled). One lacking operator creds is present
  but un-enableable until creds are seeded.
- **Rotation = manual ops script.** Credential rotation/backfill is a
  re-runnable management script over `get_all_tenant_ids()` that we run by hand;
  it upserts creds in place. No automated reconcile task and no rotation-overlap
  handling in scope.
- **Single OAuth client, one redirect URI.** Cloud uses **no per-tenant
  subdomains** — all tenants share one app domain — so a single Onyx-owned OAuth
  client with the one fixed callback `{WEB_DOMAIN}/craft/v1/apps/oauth/callback`
  covers every tenant. No canonical-host relay or per-tenant redirect handling
  needed.

## Implemented in

- **Operator config** — `onyx/external_apps/managed_credentials.py`
  (`MANAGED_EXTERNAL_APP_CREDENTIALS` env JSON → `{app_type: {field: value}}`,
  case-insensitive keys, malformed entries skipped).
- **Provisioning/reconcile** — `provision_built_in_external_apps` in
  `ee/onyx/server/tenants/provisioning.py` (the cloud analogue of, and beside,
  `configure_default_api_keys`; idempotent — creates disabled, refreshes creds
  in place, never wipes), called from `setup_tenant` in the same file.
- **DB helpers** — `onyx/db/external_app.py`: `get_external_app_by_app_type`,
  `set_external_app_organization_credentials`,
  `set_external_app_enablement_and_policies`.
- **Cloud guards + masking** — `onyx/server/features/build/api/external_apps_api.py`
  (`_is_onyx_managed`; create/credential-edit/delete blocked; admin response
  blanks creds + config) and `is_onyx_managed` on `ExternalAppAdminResponse`
  (`api/models.py`).
- **Backfill/rotation script** — `scripts/reconcile_managed_external_apps.py`.
- **Frontend** — `web/src/app/craft/v1/apps/{registry.ts,admin/page.tsx,admin/ConfigureProviderModal.tsx}`
  (hide add/delete/credential controls for managed built-ins; policies-only edit).
- **Tests** — `tests/external_dependency_unit/craft/test_managed_external_apps.py`.
