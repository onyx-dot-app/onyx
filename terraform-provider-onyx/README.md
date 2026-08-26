# Terraform Provider for Onyx

Manages **Onyx application configuration** declaratively via the Onyx admin API: LLM
providers, the deployment default model, API keys, workspace settings, and embedding
providers.

> Not to be confused with `deployment/terraform/`, which provisions the *infrastructure*
> Onyx runs on (EKS, RDS, ...). This provider configures what runs *inside* an Onyx
> deployment.

## Resources & data sources

| Name | Manages | Import id |
|---|---|---|
| `onyx_api_key` | API keys (`/admin/api-key`) | numeric id |
| `onyx_llm_provider` | LLM providers + their model list (`/admin/llm/provider`) | numeric id |
| `onyx_llm_provider_default` | The deployment default (and vision) model — a singleton | `default` |
| `onyx_settings` | Workspace settings — a singleton, partially managed | `settings` |
| `onyx_embedding_provider` | Cloud embedding provider credentials | provider type (e.g. `openai`) |
| `onyx_credential` | Connector credentials (`/manage/credential`) | numeric id |
| `onyx_connector` | Connector definitions (`/manage/admin/connector`) | numeric id |
| `onyx_cc_pair` | Connector-credential pairs (`/manage/connector/.../credential/...`) | numeric id |
| `onyx_document_set` | Document sets (`/manage/admin/document-set`) | numeric id |
| `onyx_custom_tool` | Custom actions (`/admin/tool/custom`) | numeric id |
| `onyx_persona` | Agents / assistants (`/persona`) | numeric id |
| `onyx_mcp_server` | MCP servers Onyx connects to (`/admin/mcp`) | numeric id |
| `onyx_user_group` | User groups: roster, managers, permission grants (**EE only**) | numeric id |
| `data.onyx_llm_providers` | Read-only list of providers + defaults | — |
| `data.onyx_embedding_providers` | Read-only list of embedding providers | — |
| `data.onyx_settings` | Read-only current settings (incl. license `tier`) | — |
| `data.onyx_connectors` | Read-only list of connectors | — |

Generated per-resource docs live in [`docs/`](./docs/).

[`examples/bootstrap/`](./examples/bootstrap/) is a runnable day-one configuration: a chat
model, one indexed site, a document set built from it, and an agent that answers from it.

## Authentication

The provider needs an API key in the seeded **Admin** group (or an unrestricted PAT created
by an admin user). Create one in the Onyx admin panel (*API Keys*) or via the API — pass the
Admin group id, since a key with no group has no admin permissions:

```bash
curl -X POST https://your-onyx/api/admin/api-key \
  -H "Cookie: fastapiusersauth=<admin session>" \
  -H "Content-Type: application/json" \
  -d '{"name": "terraform", "group_ids": [<admin group id>]}'
```

[`examples/bootstrap/mint_api_key.sh`](./examples/bootstrap/mint_api_key.sh) does the whole
sequence — register, log in, resolve the Admin group, mint the key — for a scripted setup. It
requires `ONYX_ADMIN_EMAIL` and `ONYX_ADMIN_PASSWORD` rather than defaulting them: on a
deployment with no users it registers that account, and the first user to register becomes an
admin.

This first key is inherently chicken-and-egg: it must exist before Terraform can run, so
either leave it unmanaged, or `terraform import` it afterwards (its `api_key` attribute
stays null — the material is only ever returned at creation).

```hcl
provider "onyx" {
  endpoint = "https://your-onyx.example.com" # or ONYX_SERVER_URL
  api_key  = var.onyx_api_key                # or ONYX_API_KEY
  # api_prefix defaults to "/api" (the web proxy). Set to "" when pointing
  # directly at the backend (e.g. http://localhost:8080). Also: ONYX_API_PREFIX.
}
```

API keys work regardless of the deployment's human `AUTH_TYPE` (basic/OIDC/SAML/cloud),
and on Onyx Cloud the tenant is embedded in the key itself.

## Known limitations (by API design)

- **Secret drift is undetectable.** The API masks `api_key`/`custom_config` on read, so
  rotating them out-of-band (e.g. in the admin UI) is invisible to `terraform plan`. The
  configured value is authoritative and is re-asserted on the next apply.
- **`onyx_settings` and `onyx_llm_provider_default` don't really delete.** Onyx has no
  reset-settings API and no unset API for the text/vision defaults; destroy removes them
  from state with a warning and leaves the live values alone. The chat-naming default is
  the exception: it has an unset API and is cleared on destroy when managed.
- **`onyx_embedding_provider` updates replace all fields.** Keep `api_key` in
  configuration — an update applied without it clears the stored key (the API has no
  keep-stored-key flag). The currently-active embedding provider also cannot be deleted.
- **`model_configurations` is the list of record.** Models omitted from it are removed
  server-side, and removing the model currently set as deployment default fails — repoint
  `onyx_llm_provider_default` first (references order this correctly).
- **`onyx_credential` payloads are write-only.** The API always returns `credential_json`
  masked, so it is never refreshed or diffed. `admin_public`, `curator_public` and `groups`
  have no update endpoint and force replacement instead.
- **`onyx_connector` does not own its access control.** `access_type` and `groups` are
  validated on write but stored on the cc-pair, so Terraform cannot refresh them. Onyx also
  rewrites an unset `prune_freq` to 7 days on the first update, which the provider then
  keeps as the value of record.
- **`onyx_connector` does not set access control.** Onyx applies it when a credential is
  associated, so it belongs to the connector-credential pair. The connector endpoints still
  require an `access_type` in the request body but ignore it, so the provider sends a fixed
  value rather than offering a knob that would do nothing.
- **A private credential can look deleted.** The API hides a credential with
  `admin_public = false` from admins other than its creator, and that is indistinguishable
  from a deleted one, so Terraform would drop it from state and recreate it. Keep
  `admin_public = true` (the default) for credentials Terraform manages, or run Terraform
  with the key that created them.
- **Deleting an agent leaves a tombstone.** Onyx marks the row deleted instead of removing
  it, so the name stays taken. A later create under that name revives the tombstone, which
  is why destroy-then-apply returns the same agent id rather than a new one.
- **A deleted agent answers 400, not 404.** The lookup raises a plain `ValueError`, which
  Onyx renders as a bad request, so "gone" cannot be read off the status. The provider
  confirms against the agent listing instead of matching on the message text. Making that
  endpoint return 404 is a worthwhile backend fix.
- **`onyx_persona` does not own every field on an agent.** Attached folders and documents
  are cleared by an omitted list, and sending null is rejected (422), so the provider reads
  them and sends them back unchanged. That leaves a narrow window in which an attachment
  added between the read and the write is reverted; making the two fields nullable
  server-side would close it. Also,
  `search_start_date` is sent but never read back, because Onyx returns it as a parsed
  timestamp that would not match a plain date. Avatar images are not managed at all.
- **`display_priority` is create-only on the upsert.** Onyx reads it when an agent is
  created and ignores it on every later write, so the provider applies a change through
  the display-priority endpoint as a second call. That endpoint only sets a number, so the
  attribute is computed: removing it from the configuration leaves the last value rather
  than reporting a difference that never settles.
- **Two built-in actions are hidden from the API.** `OktaProfileTool` and `MemoryTool` are
  left out of the agent snapshot, so an agent holding one reports fewer `tool_ids` than
  were written and the difference never settles. Attach custom actions and the ordinary
  built-ins instead.
- **Deleting a custom action detaches it from every agent that uses it**, including agents
  Terraform does not manage, without an error or a warning.
- **`onyx_user_group` is Enterprise Edition only.** The routes live in the EE application
  and do not exist on Community Edition, where every call answers 404. Its acceptance tests
  skip when `ee_features_enabled` is false.
- **`onyx_user_group` does not manage what a group can see.** Connectors, document sets,
  agents, LLM providers, MCP servers and credentials each carry their own `groups`
  attribute and own that link. The group exposes `cc_pair_ids`, `document_set_ids` and
  `persona_ids` read-only, so the two sides never fight over the same edge.
- **A roster change must not disturb those links, and how it avoids that depends on the
  change.** Onyx's update endpoint replaces connector links along with members. A roster
  that only gains members therefore goes through the add-users endpoint instead, which
  takes members alone and lets Onyx preserve the links itself, inside the transaction that
  holds the membership lock. A roster that loses one has no such endpoint: the provider
  reads the connector ids and sends them back, so a connector share made between that read
  and the write is overwritten by the older list. The window is one round-trip and only
  opens for a removal. Sending an empty list instead — the obvious-looking alternative —
  would unshare every connector from the group with nothing in the plan saying so.
- **A group's computed links lag by one apply.** Terraform creates a group before the
  `onyx_cc_pair` that references it, so `cc_pair_ids` is still empty in the state written
  by that first apply and fills in on the next refresh.
- **Onyx refuses membership, rename and delete while a group is syncing**, and a newly
  created group starts out syncing, so the provider waits before each of those. Managers,
  incognito and permissions are not gated. **The user group tests therefore need Celery
  beat as well as the workers** — the sync that clears the gate is beat-scheduled every 20
  seconds, so without beat every one of those writes waits until it times out.
- **A syncing group answers HTTP 404**, not a conflict, on the membership routes *and on
  delete*, because those handlers map every `ValueError` to not-found. The rename route gets
  this right. So a 404 from any of them does not mean the group is gone — the destroy
  confirms each one against the listing before reporting success, since trusting it would
  drop a live group out of state and leave the next apply failing on the name it still holds.
- **`onyx_user_group` permissions use Onyx's wire tokens**, for example `manage:connectors`,
  not the enum names. Only toggleable permissions can be set; `basic`, `admin`,
  `craft_sandbox`, `manage:skills` and the implied read tokens are managed by Onyx and are
  neither read back nor writable.
- **A seeded default group (`Admin`, `Basic`) holds members and nothing else.** Importing
  one and managing its roster works, but a rename, a delete, or a permission or incognito
  change is refused with a conflict.
- **Onyx refuses a membership removal that would strand someone**, leaving them in no group
  at all — a person with no group has no permissions. Destroying a group is checked the same
  way, because it drops the whole roster, so a `terraform destroy` can fail on a member whose
  only group this is. It also guards self-removal by a manager, privilege amplification, and
  the survival of admin access.
- **`onyx_mcp_server` manages only servers that need no interactive sign-in.** `NONE` and
  `API_TOKEN` are supported; `OAUTH` and `PT_OAUTH` need a browser round-trip and are
  refused while the plan is built, with a diagnostic naming the admin panel.
- **Which tools an MCP server exposes is not managed.** Onyx only learns them by calling
  the server, and it rejects both a tool selection and a Craft approval policy naming a
  tool it has never seen. Neither attribute is exposed rather than exposing one that
  silently does nothing on a server Terraform just created.
- **An MCP server's `description` left out of the configuration is cleared, not kept.** Onyx
  reads a missing description as "leave it alone", so the provider always sends the field and
  an unstated one goes out empty — the same rule as `groups` and `users` below. The upsert
  cannot carry `available_in_craft`, which lives on a different endpoint, so setting it costs
  a second call.
- **An MCP server added from the admin panel but never configured imports with empty strings.**
  That flow leaves `auth_type` and `transport` unset, and Terraform has no value to show for
  them, so the first plan after such an import moves them to the schema defaults. It settles
  in one apply.
- **A configured `auth_template_headers` is never refreshed from Onyx.** A header value may be
  a literal rather than a `{placeholder}`, and Onyx masks those on the way out, so refreshing
  would store the mask and leave a difference that never settles. Onyx's own template is read
  back only when the configuration states none. Editing the headers in the admin panel is
  therefore invisible to `terraform plan`, like any other secret.
- **`auth_performer = "PER_USER"` credentials belong to the identity that applied them.**
  Onyx stores `admin_credentials` against the applying user rather than the server, so a
  Terraform-managed per-user server holds the API key's own credentials, not an
  administrator's. It also masks them partially rather than fully, unlike a shared token.
- **An MCP server's header template is never reset.** Onyx keeps the stored template
  whenever a write omits one, so switching a server from `PER_USER` to a shared token
  leaves the per-user headers in place rather than restoring the default `Authorization`
  header. Recreate the server to start over.
- **`groups` and `users` on an MCP server are owned by the configuration.** Onyx reads a
  missing list as "leave it alone", so the provider sends an empty one instead. Removing
  either from the configuration clears it on the server, including entries added from the
  admin panel.
- **An MCP server URL cannot point at the Onyx host.** The SSRF guard refuses `localhost`
  and link-local addresses by name at every protection level, not only the strictest.
- **The model list read is the API's display view.** It hides obsolete models and dated
  duplicates, so writes (including the auto-mode pass-through, which is also not atomic
  with its read) cannot preserve rows the API hides. The admin UI round-trips the same
  filtered view; a keep-models flag on the upsert API is the planned structural fix.

## Development

Requires Go (see `go.mod`) and the [Terraform CLI](https://developer.hashicorp.com/terraform/install).

```bash
go build ./...        # build
go test ./...         # unit tests (no Onyx needed)
```

### Running it against a local build

Point Terraform at your locally-built binary with a `dev_overrides` block in
`~/.terraformrc`:

```hcl
provider_installation {
  dev_overrides {
    "onyx-dot-app/onyx" = "/path/to/onyx/terraform-provider-onyx"
  }
  direct {}
}
```

Then `go build` here and run `terraform plan/apply` (skip `terraform init`) in any config
using the provider.

### Acceptance tests

Acceptance tests run real CRUD cycles against a live Onyx deployment (they create and
destroy providers/keys and briefly modify workspace settings — use a dev deployment):

```bash
TF_ACC=1 ONYX_TF_ACC_SERVER_URL=http://localhost:8080 go test ./internal/provider/ -v
```

- `ONYX_TF_ACC_API_PREFIX` defaults to `""` (direct backend). Set `/api` when targeting
  the web server.
- Auth: set `ONYX_TF_ACC_API_KEY` to an existing admin key, or let the harness bootstrap
  one by logging in as `ONYX_TF_ACC_ADMIN_EMAIL`/`ONYX_TF_ACC_ADMIN_PASSWORD` (defaults:
  `admin_user@example.com` / `TestPassword123!`; on a fresh deployment the first
  registered user becomes admin automatically).

Without `TF_ACC` these tests skip, so plain `go test ./...` stays green with no Onyx
running. That is also what `pr-golang-tests.yml` runs, so the acceptance suite does not
run there.

`pr-terraform-provider-tests.yml` is the lane that does run it. It stands up api_server
and background from docker compose, so the workers and beat below come with it, and runs
the suite twice: once letting the harness bootstrap its own key, and once against a key
minted first by `examples/bootstrap/mint_api_key.sh`. On pull requests it only triggers
for provider and compose changes; the nightly run is what catches a backend change that
breaks the provider.

To test against an API server that does not touch your dev database, give it a database of
its own. This reuses the running Postgres, Redis, OpenSearch and MinIO containers (the
container name follows your compose project, so adjust it if yours differs):

```bash
docker exec onyx-relational_db-1 psql -U postgres -c "CREATE DATABASE onyx_tf_acc;"
cd backend && POSTGRES_DB=onyx_tf_acc uv run alembic upgrade head
POSTGRES_DB=onyx_tf_acc AUTH_TYPE=basic LICENSE_ENFORCEMENT_ENABLED=false \
  ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=true \
  USER_AUTH_SECRET="$(openssl rand -hex 32)" \
  uv run uvicorn onyx.main:app --port 8081
```

Each variable earns its place. `AUTH_TYPE=basic` gives the harness a login to bootstrap
its key with. License enforcement must be off or API key creation answers 402. The
enterprise features flag registers the user-group routes, which the harness reads to find
the Admin group its key needs.

The `onyx_cc_pair`, `onyx_document_set` and `onyx_user_group` tests also need Celery,
because those objects are synced and deleted in the background. Without a worker the rows
never go away and the destroy step waits until it times out. They need the same
environment as the API server, plus `PYTHONPATH` pointing at `backend/` so beat can load
the Enterprise schedule:

```bash
source /path/to/the/same/env   # the variables above
export PYTHONPATH=/path/to/onyx/backend
celery -A onyx.background.celery.versioned_apps.beat beat --loglevel=INFO &
celery -A onyx.background.celery.versioned_apps.primary worker \
  --pool=threads --concurrency=4 --loglevel=INFO --hostname=tfacc-primary@%n -Q celery &
celery -A onyx.background.celery.versioned_apps.light worker \
  --pool=threads --concurrency=8 --loglevel=INFO --hostname=tfacc-light@%n \
  -Q vespa_metadata_sync,connector_deletion,doc_permissions_upsert,checkpoint_cleanup,index_attempt_cleanup,opensearch_migration &
```

The primary worker picks up the deletion checks the API server dispatches; the light
worker runs the deletions and the document set sync themselves.

**Beat is required for the user group tests specifically.** Onyx refuses to change or
delete a group while it is syncing, a new group starts out syncing, and only the
beat-scheduled `check-for-vespa-sync` (every 20 seconds) clears that state. The workers
alone never run it, so without beat every group rename, membership change and destroy
waits until it times out.

The pair tests use the `mock_connector` source on purpose. Creating a pair runs the
connector's real `validate_connector_settings`, which reaches the source system; Onyx
short-circuits that check for `mock_connector` and `ingestion_api`, so the tests cover the
whole lifecycle without any live source or credentials.

### Docs

`docs/` is generated — edit schema `MarkdownDescription`s and `examples/`, then:

```bash
go generate .   # runs tfplugindocs; needs terraform on PATH
```

## Publishing (future)

The public Terraform Registry requires a standalone GitHub repo named exactly
`terraform-provider-onyx` with GPG-signed goreleaser artifacts. Until a release mirror is
set up, install via `dev_overrides` (above) or a private registry/filesystem mirror.
