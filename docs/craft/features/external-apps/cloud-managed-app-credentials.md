# Cloud-Managed External-App Credentials

On Onyx Cloud, Onyx owns the OAuth client credentials for built-in external apps
(Gmail, Google Calendar, Slack, Linear). Each tenant is seeded with these apps
already configured, so a tenant admin never registers their own OAuth
application. An admin only **enables/disables** an app and sets its **action
policies**; users then run the normal per-user OAuth flow against Onyx's app.

Self-hosted is unchanged: admins create built-ins and supply their own
credentials, as before.

## Behavior

- **One built-in per type per tenant.** A tenant has at most one built-in app of
  each `app_type`, enforced by the built-in skill's unique slug. (`CUSTOM` apps
  may repeat.)
- **Seeded, disabled, on Cloud.** When a tenant is created, every Onyx-managed
  built-in is provisioned disabled with Onyx's credentials populated.
- **Admins toggle + set policies only.** On Cloud a tenant admin cannot create,
  edit credentials/config for, or delete a built-in app. Credentials and gateway
  config (`auth_template`, `upstream_url_patterns`) are never sent to the client.
- **Users authenticate normally.** Once an app is enabled, each user runs the
  existing OAuth flow and gets their own per-user token against Onyx's app.

## Onyx-managed providers

A built-in provider whose credentials Onyx owns subclasses `OnyxManagedExtApp`
(`onyx/external_apps/providers/base.py`). This interface is the single source of
truth for "is this app Onyx-managed":

- It declares `managed_org_credentials`, mapping each credential field to its
  value. Keys must match the provider's `required_org_credential_fields`
  (validated at class-definition time in `ExternalAppProvider.__init_subclass__`).
- `configured_managed_credentials()` returns those values when all are set, or
  `None` when none/only some are set (a partial set is logged and skipped).
- A built-in that admins configure themselves simply doesn't inherit
  `OnyxManagedExtApp`; it carries no Onyx-owned credentials and stays editable
  even on Cloud.

`get_onyx_managed_provider(app_type)` (`registry.py`) returns the provider if it
inherits `OnyxManagedExtApp`, else `None`; the API treats `… is not None`,
combined with `MULTI_TENANT`, as the Cloud-only lockdown check.

## Credential configuration

Operators supply credentials through per-field environment variables, defined as
constants in `onyx/configs/app_configs.py`:

```
EXT_APP_<APP_TYPE>_<FIELD>     e.g. EXT_APP_GMAIL_CLIENT_ID, EXT_APP_SLACK_CLIENT_SECRET
```

The `EXT_APP_` prefix and specific app type (e.g. `GMAIL`, not `GOOGLE`) keep
these distinct from the auth-flow `GOOGLE_OAUTH_*` variables. Each constant is
mapped to its field on the provider's `managed_org_credentials`. Stored values
are encrypted at rest (`organization_credentials`, an `EncryptedJson` column).

Leaving a provider's variables unset is valid: the app is still provisioned, just
without credentials until they are configured (it can't be meaningfully enabled
until then).

## Provisioning

`provision_built_in_external_apps(db_session)`
(`ee/onyx/server/tenants/provisioning.py`) runs from `setup_tenant`, alongside
`configure_default_api_keys`, when a tenant is created. It is gated by
`AUTO_PROVISION_DEFAULT_EXTERNAL_APPS` (default `false`; set `true` on cloud).
For each managed built-in it:

- creates the app disabled, with the operator's credentials (or empty if none
  are configured), or
- if the app already exists (e.g. a `setup_tenant` retry), refreshes its
  credentials in place and leaves enabled state and policies untouched.
  Credentials are overwritten only when configured for that type, so a re-run
  never wipes credentials the config no longer mentions.

Per-app failures are rolled back and logged so one bad app can't block the rest.

## Admin API

- `POST /admin/apps/built-in` — create/update a built-in app (self-hosted). On
  Cloud, managed built-ins are rejected here; use the PATCH endpoint.
- `PATCH /admin/apps/{id}` — toggle `enabled` and set `action_policies`, keyed
  solely by id. This is the only mutation path for Cloud-managed built-ins;
  it never touches credentials or gateway config.
- `DELETE /admin/apps/{id}` — rejected on Cloud for managed built-ins.
- `POST /admin/apps/custom` — `CUSTOM` apps, unaffected by the Cloud rules.

`_to_admin_response` blanks `organization_credentials`, `auth_template`, and
`upstream_url_patterns` for a managed app (and sets `is_onyx_managed=True`),
exposing only identity, enabled state, and policies. Self-hosted built-ins still
return masked (not blanked) credentials. After a mutation the helper flushes and
the endpoint commits once the sandbox push succeeds, so a push failure doesn't
leave the database ahead of the runtime.

The frontend (`web/src/app/craft/v1/apps/`) reads `is_onyx_managed` to hide the
credential form, the "add built-in" affordance, and the delete control for
managed apps, leaving only the enable toggle and policy editor.

## OAuth

User-facing endpoints (`GET /apps`, `POST /apps/{id}/credentials`) and the OAuth
start/callback are unchanged. Cloud uses a single Onyx-owned OAuth client with
one fixed callback (`{WEB_DOMAIN}/craft/v1/apps/oauth/callback`) shared across all
tenants; credential injection and token refresh read the seeded
`organization_credentials` with no change.

## Tests

`tests/external_dependency_unit/craft/test_managed_external_apps.py` covers
provisioning (seeding, idempotent re-run, credential refresh without wiping) and
the Cloud guards (create/update/delete blocked; PATCH toggles enablement;
response masking). `tests/unit/external_apps/test_managed_credentials.py` covers
credential resolution from the provider.
