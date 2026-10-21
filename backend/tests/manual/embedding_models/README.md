# Manual embedding model tests

Opt-in suites for the selectable embedding models. CI never collects
`backend/tests/manual`, and each suite skips unless its gate env var is `true`.
The suites read keys from plain env vars only. Do not put a gate in
`backend/.test.env`: pytest loads that file on every run.

| Suite | Gate env var | Needs |
|---|---|---|
| `test_self_hosted_embedding_models.py` | `ONYX_RUN_SELF_HOSTED_EMBEDDING_TESTS` | Internet for the first download (about 3.2 GB). About 8 GB of free RAM for Nemotron. No keys, no services. |
| `test_cloud_embedding_models_live.py` | `ONYX_RUN_CLOUD_EMBEDDING_TESTS` | Provider keys. No services. Costs less than 0.10 USD. |
| `test_embedding_model_switch_e2e.py` | `ONYX_EMBEDDING_E2E_ALLOW_MUTATION` | A disposable Onyx stack with EE search. **Changes the stack.** |

Key env vars. A cloud model without its key skips: `COHERE_API_KEY`,
`OPENAI_API_KEY`, `VOYAGE_API_KEY`, `VERTEX_CREDENTIALS` (the path to a Google
service-account JSON file). You can keep them in the gitignored
`.vscode/.env.embedding-tests`.

## Commands

Run each command from the repository root. Add `-k <model>` to run one model.

```bash
ONYX_RUN_SELF_HOSTED_EMBEDDING_TESTS=true \
  uv run pytest -v -rs backend/tests/manual/embedding_models/test_self_hosted_embedding_models.py

ONYX_RUN_CLOUD_EMBEDDING_TESTS=true uv run --env-file .vscode/.env.embedding-tests \
  pytest -v -rs backend/tests/manual/embedding_models/test_cloud_embedding_models_live.py

ONYX_EMBEDDING_E2E_ALLOW_MUTATION=true API_SERVER_PORT=18080 \
ONYX_E2E_ADMIN_EMAIL=<admin email> ONYX_E2E_ADMIN_PASSWORD=<admin password> \
ONYX_EMBEDDING_E2E_MODELS=ibm-granite/granite-embedding-97m-multilingual-r2,embed-v5.0-fast \
  uv run --env-file .vscode/.env.embedding-tests \
  pytest -v -s -rs backend/tests/manual/embedding_models/test_embedding_model_switch_e2e.py
```

## End to end

The e2e suite re-embeds every document on the stack once for each target. It
saves the provider keys on the stack. The last target stays live, and the
upgrade-only rule then blocks a return to a legacy model. Use a disposable
stack, or take a Postgres and OpenSearch snapshot first.

- `API_SERVER_HOST`, `API_SERVER_PORT`: the target api_server. The suite refuses
  port 8080 (the normal dev stack) unless `ONYX_EMBEDDING_E2E_ALLOW_PORT_8080=true`.
- `ONYX_E2E_ADMIN_EMAIL`, `ONYX_E2E_ADMIN_PASSWORD`: an existing admin. The suite
  never creates users or resets the database.
- `ONYX_EMBEDDING_E2E_MODELS`: optional. Comma-separated exact model names, run
  in this order. The default is every selectable model.
- `ONYX_EMBEDDING_E2E_TIMEOUT_SECONDS`: optional wait for each swap. The default
  is 3600.

Start the stack with `ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=true`: the search
check uses the EE search API. The suite never consents to connector deletion,
so the API refuses to re-index a stack with INVALID connectors. Fix or delete
them first. To check the same-model re-index of a legacy model, start with a
stack that uses a legacy model, for example nomic. Do not use `-n`: the tests
run in file order.
