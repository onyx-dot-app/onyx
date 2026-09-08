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
| `onyx_agent` | Agents / assistants (`/persona`) | numeric id |
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

## Keeping secrets out of state

Every secret this provider takes has two forms. The plain attribute is stored in Terraform
state, where anyone who can read the state file can read the secret. The `_wo` twin is a
[write-only argument](https://developer.hashicorp.com/terraform/language/resources/ephemeral#write-only-arguments):
Terraform strips the value from the plan and the state, so it lives only in your
configuration and never reaches a state file. Prefer the twin.

| Resource | Stored | Write-only |
| --- | --- | --- |
| `onyx_llm_provider` | `api_key`, `custom_config` | `api_key_wo`, `custom_config_wo` |
| `onyx_embedding_provider` | `api_key` | `api_key_wo` |
| `onyx_credential` | `credential_json` | `credential_json_wo` |
| `onyx_mcp_server` | `api_token`, `admin_credentials` | `api_token_wo`, `admin_credentials_wo` |
| `onyx_custom_tool` | `custom_headers` | `custom_headers_wo` |

Set one or the other, never both. `onyx_credential` needs exactly one of the two, because
the payload is mandatory.

Three secrets have no twin, and cannot get one:

- **`onyx_api_key.api_key`** is the key Onyx mints, not one you supply. Terraform can only
  hand back a generated value through state. Treat the state file as holding it.
- **`onyx_mcp_server.auth_template_headers`** is computed — Onyx writes the template itself
  for a shared token — and Terraform does not allow an argument to be both computed and
  write-only. Its placeholder values are filled from `admin_credentials_wo`.
- **The provider's own `api_key`** is provider configuration, which Terraform does not
  write to state at all. Supply it from `ONYX_API_KEY` rather than in a `.tf` file.

```hcl
resource "onyx_llm_provider" "openai" {
  name          = "openai"
  provider_type = "openai"

  api_key_wo         = var.openai_api_key
  api_key_wo_version = 1

  model_configurations = [{ name = "gpt-5-mini" }]
}
```

Write-only arguments need Terraform 1.11 or later. An older CLI rejects a configuration
that sets one.

### Rotating a write-only secret

A value Terraform never stores is a value it cannot diff, so changing `api_key_wo` on its
own plans nothing at all. Each twin has a `_wo_version` counter for this: raise it, and the
diff that produces makes the next apply send the current secret.

Do not derive the counter from the secret (`md5(var.token)` and friends). Unlike the
secret, the counter is kept in state.

The counter only decides when an apply is *triggered*. Onyx replaces all fields on update,
so the provider sends the secret on every apply it runs, whatever moved the plan.

### Two things to know

**`onyx_custom_tool` stops refreshing its headers.** Onyx returns action headers in full
rather than masked, so `custom_headers` is normally refreshed and out-of-band edits show up
in `terraform plan`. It cannot do that for `custom_headers_wo` without writing the secret
into state, so it does not: a header changed in the admin UI goes unreported until the next
apply overwrites it. This is the one place where the write-only form gives up something.

**Importing takes one extra apply.** Import reads what the server has, so a secret Onyx
returns unmasked lands in the stored attribute. The first apply against a configuration
that uses the twin clears it from state and moves the resource onto the write-only path.

## Known limitations (by API design)

These follow from how the Onyx API behaves, so each is something to design around rather than
a bug to wait on.

**Fixed upstream** marks a limitation the backend has already changed. The fix is not in a
released Onyx yet, so the provider keeps its workaround and the limitation still applies.

### Secrets

- **Secret drift is undetectable.** The API masks secrets on read, so rotating one in the
  admin UI is invisible to `terraform plan`. The configured value is authoritative and is
  re-asserted on the next apply.

### Settings and deployment defaults

- **`onyx_settings` and `onyx_llm_provider_default` do not really delete.** Onyx has no
  reset-settings API and no unset API for the text and vision defaults, so destroy drops them
  from state and leaves the live values alone. The chat-naming default does have an unset API
  and is cleared.

### LLM and embedding providers

- **`onyx_embedding_provider` updates replace all fields.** Keep `api_key` (or `api_key_wo`)
  in the configuration or an update clears the stored key. The active embedding provider
  cannot be deleted.
- **`model_configurations` is the list of record.** Omitted models are removed server-side,
  and removing the current deployment default fails — repoint `onyx_llm_provider_default`
  first, which references order correctly.
- **The model list read is the API's display view.** It hides obsolete and dated-duplicate
  models, so no write can preserve rows it does not return. The admin UI has the same
  behaviour. *Fixed upstream:* the upsert takes `keep_existing_models`.

### Credentials and connectors

- **`onyx_credential` payloads are never read back.** The API always masks the payload, so it
  is never refreshed or diffed. `admin_public`, `curator_public` and `groups` have no update
  endpoint and force replacement.
- **A private credential can look deleted.** Onyx hides a credential with
  `admin_public = false` from every admin but its creator, which is indistinguishable from
  deletion, so Terraform would drop it and recreate it. Keep the default `admin_public = true`
  for managed credentials, or apply with the key that created them.
- **`onyx_connector` does not own its access control.** Onyx applies access when a credential
  is associated, so `access_type` and `groups` live on the connector-credential pair. The
  connector endpoints still require `access_type` in the body and ignore it, so the provider
  sends a fixed value rather than offering a knob that does nothing. Set access on
  `onyx_cc_pair`.
- **An unset `prune_freq` becomes 7 days** on a connector's first update, and the provider
  then keeps that as the value of record.

### Agents and actions

- **Deleting an agent leaves a tombstone.** The row is marked deleted, so the name stays
  taken and a later create under it revives the same agent. Destroy-then-apply returns the
  original id, not a new one.
- **A deleted agent answers 400, not 404**, so "gone" cannot be read off the status. The
  provider confirms against the agent listing rather than matching error text.
  *Fixed upstream:* the route answers a typed `PERSONA_NOT_FOUND`.
- **`onyx_agent` does not own every field.** Attached folders and documents are cleared by an
  omitted list and reject an explicit null, so the provider reads them and writes them back —
  leaving a one-round-trip window where an attachment added in between is reverted.
  *Fixed upstream:* both fields are nullable. Separately, `search_start_date` is written but
  never read back, and avatars are not managed.
- **`display_priority` is create-only on the upsert.** Onyx ignores it on later writes, so a
  change costs a second call to the display-priority endpoint. That endpoint can only set a
  number, so the attribute is computed: removing it keeps the last value.
- **Two built-in actions are hidden from the API.** `OktaProfileTool` and `MemoryTool` are
  left out of the agent snapshot, so an agent holding one reports fewer `tool_ids` than were
  written and never settles. Use custom actions and the other built-ins.
- **Deleting a custom action detaches it from every agent using it**, including agents
  Terraform does not manage, with no error or warning.

### User groups (Enterprise Edition)

- **`onyx_user_group` is Enterprise Edition only.** The routes do not exist on Community
  Edition, where every call answers 404.
- **`onyx_user_group` does not manage what a group can see.** Connectors, document sets,
  agents, LLM providers, MCP servers and credentials each carry their own `groups` and own
  that link. The group exposes `cc_pair_ids`, `document_set_ids` and `agent_ids` read-only, so
  the two sides never fight over one edge.
- **Removing a member can overwrite a concurrent connector share.** Onyx's update endpoint
  replaces connector links along with members, and there is no removal-only route, so the
  provider reads the links and writes them back. The window is one round-trip and only opens
  for a removal; adding members uses an endpoint that preserves the links server-side.
- **A group's computed links lag one apply.** Terraform creates the group before the
  `onyx_cc_pair` referencing it, so `cc_pair_ids` fills in on the next refresh.
- **Onyx refuses membership, rename and delete while a group is syncing**, and a new group
  starts out syncing, so the provider waits before each. Managers, incognito and permissions
  are not gated.
- **A syncing group answers 404, not a conflict**, on the membership and delete routes, which
  map every error to not-found. So a 404 does not prove the group is gone, and destroy
  confirms against the listing before reporting success. *Fixed upstream:* the gate raises a
  distinct `RESOURCE_SYNCING` conflict.
- **Permissions use Onyx's wire tokens**, such as `manage:connectors`, not the enum names.
  Only toggleable permissions can be set; `basic`, `admin`, `craft_sandbox`, `manage:skills`
  and the implied read tokens are managed by Onyx.
- **A seeded default group (`Admin`, `Basic`) holds members and nothing else.** Managing its
  roster works; rename, delete, permission and incognito changes are refused.
- **Onyx refuses a removal that would strand someone** in no group at all, since a person with
  no group has no permissions. Destroying a group is checked the same way, so a destroy can
  fail on a member whose only group it is. Self-removal by a manager, privilege amplification
  and the survival of admin access are guarded too.

### MCP servers

- **Only servers needing no interactive sign-in are managed.** `NONE` and `API_TOKEN` work;
  `OAUTH` and `PT_OAUTH` need a browser round-trip and are refused at plan time.
- **Which tools a server exposes is not managed.** Onyx learns them by calling the server and
  rejects a tool selection or Craft policy naming one it has never seen, so a server Terraform
  just created has none to name.
- **An omitted `description` is cleared, not kept**, because Onyx reads a missing one as
  "leave alone" and the provider therefore always sends the field. The same rule applies to
  `groups` and `users`: removing either from the configuration clears it on the server,
  including entries added from the admin panel. `available_in_craft` lives on another
  endpoint, so setting it costs a second call.
- **A server added from the admin panel but never configured imports with empty strings.**
  `auth_type` and `transport` are unset there, so the first plan after import moves them to
  the schema defaults. It settles in one apply.
- **`auth_template_headers` is never refreshed.** A header value may be a literal rather than
  a `{placeholder}`, and Onyx masks those, so refreshing would store the mask and never
  settle. Onyx's own template is read back only when the configuration states none. Admin-panel
  edits are invisible to `terraform plan`, like any other secret.
- **The header template is never reset.** Onyx keeps the stored template whenever a write
  omits one, so moving a server from `PER_USER` to a shared token leaves the per-user headers
  in place. Recreate the server to start over.
- **`auth_performer = "PER_USER"` credentials belong to the identity that applied them.** Onyx
  stores `admin_credentials` against the applying user, so a Terraform-managed per-user server
  holds the API key's own credentials, not an administrator's, and masks them only partially.
- **A server URL cannot point at the Onyx host.** The SSRF guard refuses `localhost` and
  link-local addresses at every protection level, not just the strictest.

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

## Publishing

The public Terraform Registry only serves a provider from a repository named after it, so
releases go out through a mirror, `onyx-dot-app/terraform-provider-onyx`. The mirror holds
no source of its own. It is written from this directory and never edited directly.

Two workflows split the work, one in each repository:

1. `ods release tf-provider` pushes a `tf-provider/vX.Y.Z` tag on the monorepo.
2. `.github/workflows/release-terraform-provider.yml` commits this directory's tree onto
   the mirror's history and tags it `vX.Y.Z`. (`git subtree split` would walk all ~10,000
   monorepo commits to find the handful that touch this directory, which takes longer than
   the rest of the release put together.)
3. That tag starts `publish.yml` in the mirror. It lives here, at
   `.github/workflows/publish.yml`, and travels with the directory it publishes — GitHub
   only reads workflows from a repository's root, so it is inert in the monorepo.
4. goreleaser builds every platform archive, signs the checksum file with the release GPG
   key, and publishes a GitHub release. The registry ingests it from there.

goreleaser runs in the mirror rather than the monorepo because it takes the version from
whatever tag the checkout has. Here it would find tags like `nightly-latest-...` and stamp
them into every artifact name.

### Cutting a release

Add the version's section to [`CHANGELOG.md`](./CHANGELOG.md) first. Publish reads it and
uses it as the GitHub release body, which is what a user sees before upgrading. A version
with no section fails the release rather than publishing empty notes.

```console
$ ods release tf-provider              # bumps the patch version
$ ods release tf-provider --bump minor
$ ods release tf-provider --version 1.0.0
$ ods release tf-provider --dry-run    # computes the version, tags nothing
```

> [!IMPORTANT]
> `ods release` tags **`HEAD`**, not `main`, and does not check which branch you are on.
> Run `git rev-parse HEAD` and `git rev-parse origin/main` and compare them first. Tagging
> from a stale branch publishes that branch's provider under the new version.

To rehearse, run **Publish** by hand from the mirror's Actions tab. It defaults to a dry
run, which builds every archive and publishes none of them.

How a failed release is recovered depends on whether the mirror push got through. Check
whether the mirror already carries the tag.

**It does not** — the monorepo's *Release Terraform Provider* failed. Re-drive it from that
repo's Actions tab, or with the command below. Do not delete and re-push the `tf-provider`
tag: the mirror step commits the tree at the ref you dispatch from, so dispatching from `main`
also picks up any fix merged since the tag was cut.

```console
$ gh workflow run release-terraform-provider.yml --ref main -f version=0.3.0
```

**It does** — the mirror push succeeded and the mirror's *Publish* failed (goreleaser,
signing, the registry). Re-run that workflow from the **mirror's** Actions tab. Dispatching
the monorepo workflow again will not work: it pushes `main` and the tag atomically, so a tag
the mirror already holds rejects the whole push and nothing moves.

### One-time setup

All of it is done, and releases have been automated since `v0.2.0`. This records what
exists, for whoever has to rebuild or rotate it:

- [x] The public repo `onyx-dot-app/terraform-provider-onyx` exists.
- [x] The mirror carries its own `LICENSE`.
- [x] The release GPG key exists and its public half is registered under the
      `onyx-dot-app` namespace.
- [x] The mirror holds `TF_PROVIDER_GPG_PRIVATE_KEY` and `TF_PROVIDER_GPG_PASSPHRASE`,
      which is where the signing happens. The monorepo never holds the key.
- [x] The mirror is linked on registry.terraform.io as the `onyx-dot-app` organisation.
- [x] The `release-terraform-provider` environment holds the mirror credential: variable
      `TF_PROVIDER_RELEASE_APP_CLIENT_ID` — the App's **Client ID** (`Iv23li...`), *not*
      the numeric App ID — and secret `TF_PROVIDER_RELEASE_APP_PRIVATE_KEY`, the whole
      generated `.pem` including its `BEGIN`/`END` lines.

Two properties of that App are load-bearing, and each one failed a release once:

- It needs **contents: write** *and* **workflows: write**. The mirrored tree contains
  `.github/workflows/publish.yml`, and GitHub refuses a push from an App that changes a
  workflow file without the second one. It only bites on a release that edits that file,
  so the first releases did not need it.
- It must be a **bypass actor on the mirror's `Read-only mirror` rulesets**, for both the
  branch and the tag rule. Without that the push is refused with `GH013` and nothing
  reaches the mirror.

## Licence

MIT, the same terms the Onyx monorepo applies to content outside its `ee` directories.
The provider contains no Enterprise-licensed code. `LICENSE` holds the plain MIT text
with nothing added, so licence scanners and GitHub detect it as MIT rather than
reporting `NOASSERTION`.
