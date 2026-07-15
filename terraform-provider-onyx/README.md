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
| `data.onyx_llm_providers` | Read-only list of providers + defaults | — |
| `data.onyx_embedding_providers` | Read-only list of embedding providers | — |
| `data.onyx_settings` | Read-only current settings (incl. license `tier`) | — |

Generated per-resource docs live in [`docs/`](./docs/).

## Authentication

The provider needs an **admin-role API key** (or an unrestricted PAT created by an admin
user). Create one in the Onyx admin panel (*API Keys*) or via the API:

```bash
curl -X POST https://your-onyx/api/admin/api-key \
  -H "Cookie: fastapiusersauth=<admin session>" \
  -H "Content-Type: application/json" \
  -d '{"name": "terraform", "role": "admin"}'
```

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
  reset-settings or unset-default API; destroy removes them from state with a warning and
  leaves the live values alone.
- **`onyx_embedding_provider` updates replace all fields.** Keep `api_key` in
  configuration — an update applied without it clears the stored key (the API has no
  keep-stored-key flag). The currently-active embedding provider also cannot be deleted.
- **`model_configurations` is the list of record.** Models omitted from it are removed
  server-side, and removing the model currently set as deployment default fails — repoint
  `onyx_llm_provider_default` first (references order this correctly).

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

Without `TF_ACC` these tests skip, so plain `go test ./...` (and the repo's Go CI) stays
green with no Onyx running.

### Docs

`docs/` is generated — edit schema `MarkdownDescription`s and `examples/`, then:

```bash
go generate .   # runs tfplugindocs; needs terraform on PATH
```

## Publishing (future)

The public Terraform Registry requires a standalone GitHub repo named exactly
`terraform-provider-onyx` with GPG-signed goreleaser artifacts. Until a release mirror is
set up, install via `dev_overrides` (above) or a private registry/filesystem mirror.
