# Bootstrap example

A day-one Onyx configuration. It creates a chat model, indexes one public
documentation site, groups the result into a document set, and adds an agent
that answers from it.

Everything here works on Community Edition. The `onyx_user_group` resource is
the one exception and stays off unless you set
`enable_enterprise_features = true`.

## Get an API key

The provider authenticates with an Onyx API key. A key's access comes from the
groups it belongs to, so the key must be in the `Admin` group.

Create one in the admin panel under **Settings -> Service Accounts**, or run:

```bash
ONYX_SERVER_URL=http://localhost:8080 \
ONYX_ADMIN_EMAIL=admin@example.com \
ONYX_ADMIN_PASSWORD='...' \
./mint_api_key.sh
```

The script logs in as that account and mints a key in the `Admin` group. It
needs `curl` and `jq`, and listing groups needs the same Enterprise Edition
route the admin panel uses.

The credentials are required rather than defaulted, deliberately. On a
deployment with no users the script registers the account, and the first user
to register becomes an admin — so a default password here would quietly create
a known-password administrator on any reachable deployment.

## Apply

```bash
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars

terraform init
terraform plan
terraform apply
```

Credentials can also come from the environment, which keeps them out of
`terraform.tfvars`:

```bash
export ONYX_SERVER_URL=http://localhost:8080
export ONYX_API_KEY="$(ONYX_ADMIN_EMAIL=admin@example.com \
  ONYX_ADMIN_PASSWORD='...' ./mint_api_key.sh)"
export TF_VAR_openai_api_key="sk-..."
```

## What it creates

| Resource | Purpose |
| --- | --- |
| `onyx_settings.workspace` | Workspace name |
| `onyx_llm_provider.openai` | The chat model provider |
| `onyx_llm_provider_default.this` | Picks the deployment-wide default model |
| `onyx_credential.web` | An empty credential, which is what the web connector takes |
| `onyx_connector.docs` | Says what to index and how often |
| `onyx_cc_pair.docs` | Joins connector to credential and indexes |
| `onyx_document_set.docs` | Groups the indexed pair for search |
| `onyx_persona.docs` | The agent that answers from the set |
| `onyx_user_group.platform` | Enterprise Edition only, off by default |

Indexing starts after apply and runs in the background, so the agent answers
from the site only once the first index run finishes. Watch progress in the
admin panel under **Connectors**.

## Clean up

```bash
terraform destroy
```

Destroying the pair also removes the documents it indexed, which Onyx does in
the background. `onyx_settings` is the exception: destroying it stops managing
the settings but does not reset them.
