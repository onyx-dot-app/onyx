# Manual embedding model tests

These suites check the embedding models that admins can select. They are opt-in.
CI never collects `backend/tests/manual`, and every test in it skips unless you
set its gate env vars to `true`.

| Suite | File | Gate env vars | Needs | Changes a deployment |
|---|---|---|---|---|
| Self-hosted real weights | `test_self_hosted_embedding_models.py` | `ONYX_RUN_SELF_HOSTED_EMBEDDING_TESTS` | Internet for the first download. No keys. No running services. | No |
| Cloud live | `test_cloud_embedding_models_live.py` | `ONYX_RUN_CLOUD_EMBEDDING_TESTS` | Provider keys in env vars. No running services. | No |
| End to end | `e2e/test_embedding_model_switch_e2e.py` | `ONYX_EMBEDDING_E2E` and `ONYX_EMBEDDING_E2E_ALLOW_MUTATION` | A running Onyx stack with EE search. Keys for cloud targets. | **Yes** |

## Safety rules

- The suites read keys from plain env vars only. They never read AWS Secrets
  Manager, `tests/utils/pytest_secrets`, or `.vscode/.env`.
- Do not put the gate env vars in `backend/.test.env`. pytest loads that file
  (pytest-dotenv), so a gate there turns a suite on for every run.
- The e2e suite changes the embedding model of the target stack. Read
  [E2E warning](#e2e-warning) before you run it.

## Env vars

| Env var | Suite | Meaning |
|---|---|---|
| `ONYX_RUN_SELF_HOSTED_EMBEDDING_TESTS` | self-hosted | `true` runs the suite. |
| `ONYX_EMBEDDING_TEST_MODEL_SERVER_URL` | self-hosted | Optional. For example `http://localhost:9000`. Sends each request to a running model server through `EmbeddingModel`. If unset, the suite calls `model_server.encoders.process_embed_request` in-process. |
| `ONYX_EMBEDDING_TEST_DEVICE` | self-hosted | `cpu` (default) or `auto`. `cpu` hides CUDA and MPS from torch, so the model server takes its CPU path (fp32). The golden scores are fp32 values. `auto` lets torch pick the device (bf16 on GPU or MPS). |
| `ONYX_RUN_CLOUD_EMBEDDING_TESTS` | cloud | `true` runs the suite. |
| `COHERE_API_KEY` | cloud, e2e | Cohere key. Runs `embed-v5.0-pro` and `embed-v5.0-fast`. |
| `OPENAI_API_KEY` | cloud, e2e | OpenAI key. Runs `text-embedding-3-large` and `text-embedding-3-small`. |
| `VERTEX_CREDENTIALS` | cloud, e2e | Google service-account JSON: the raw JSON, or a path to the file. Runs `gemini-embedding-2`. |
| `VERTEX_LOCATION` | cloud, e2e | Optional. Written into the service-account JSON as `location`. `gemini-embedding-2` needs `global`, `us` or `eu`. If unset, Onyx uses `GOOGLE_CLOUD_LOCATION`, then `global`. |
| `ONYX_EMBEDDING_E2E` | e2e | `true` is the first gate. |
| `ONYX_EMBEDDING_E2E_ALLOW_MUTATION` | e2e | `true` is the second gate. It confirms that you accept the changes to the target stack. |
| `API_SERVER_HOST`, `API_SERVER_PORT` | e2e | **Required. No default.** The api_server of the disposable target stack. The shared Manager helpers read these. `API_SERVER_PROTOCOL` is optional (default `http`). If you also set `API_SERVER_URL`, it must be the same URL. |
| `ONYX_EMBEDDING_E2E_ALLOW_PORT_8080` | e2e | Optional. Port 8080 is the port of the normal dev stack, so the suite refuses it. Set `true` only if the stack on port 8080 is disposable. |
| `ONYX_E2E_ADMIN_EMAIL`, `ONYX_E2E_ADMIN_PASSWORD` | e2e | **Required. No default.** An existing admin on the target stack. The suite never creates users. |
| `ONYX_EMBEDDING_E2E_ALLOW_CONNECTOR_DELETION` | e2e | Optional. `true` lets each re-index consent to deleting the connectors in INVALID status. Without it, the suite stops before any change if such connectors exist. See [E2E warning](#e2e-warning). |
| `ONYX_EMBEDDING_E2E_MODELS` | e2e | Optional. Comma-separated exact model names, run in this order. The last model stays live. Default: all 8 selectable models in registry order. Cloud models without a key skip. A model that you name here fails if its key is missing. |
| `ONYX_EMBEDDING_E2E_TIMEOUT_SECONDS` | e2e | Optional. The wait for each port and swap. Defaults: 900 for cloud models, 1800 for self-hosted models, 3600 for Nemotron. |
| `ONYX_EMBEDDING_E2E_KEEP_FAILED_REINDEX` | e2e | Optional. `true` keeps a failed or timed-out re-index running for debugging. By default the suite cancels it. |

To keep keys in a file, use the gitignored `.vscode/.env.embedding-tests`:

```
COHERE_API_KEY=...
OPENAI_API_KEY=...
VERTEX_CREDENTIALS=/absolute/path/to/service-account.json
VERTEX_LOCATION=global
```

## Commands

Run every command from the repository root.

### Prove that the suites import and skip

```bash
uv run pytest backend/tests/manual --collect-only -q
uv run pytest backend/tests/manual -q -rs
```

The second command must report `78 skipped` (the count changes when models are
added). Each skip reason names the gate env vars.

### Self-hosted real weights

```bash
ONYX_RUN_SELF_HOSTED_EMBEDDING_TESTS=true \
  uv run pytest -v -rs backend/tests/manual/embedding_models/test_self_hosted_embedding_models.py
```

- One model only: add `-k granite`, `-k voyage` or `-k nemotron`.
- Against a running model server: add
  `ONYX_EMBEDDING_TEST_MODEL_SERVER_URL=http://localhost:9000`. The checks that
  need the loaded model object skip in this mode.

The suite checks each of the 3 selectable self-hosted models:

- Vector dimension from the registry, finite values and unit norm.
- The server applies the query and passage prefixes.
- QUERY and PASSAGE vectors differ for voyage-4-nano and Nemotron. They are identical for granite.
- Bidirectional attention: a change to the last token changes the output of the first token.
- No default prompt on top of the Onyx prefix.
- A padded batch gives the same vectors as single inputs.
- Text past the 512-token context window does not change the vector.
- Golden "Red Planet" cosine scores (fp32, tolerance 0.01).
- The API server tokenizer is the model's own tokenizer, not the nomic fallback.

It also checks that the legacy `nomic-ai/nomic-embed-text-v1` still loads with
768 dimensions. It also checks that a custom `voyageai/voyage-4-nano` with 1024
dimensions (added with "Add Custom Model" before the registry) still gets the
1024-dim vectors of the old load.

### Cloud live

```bash
ONYX_RUN_CLOUD_EMBEDDING_TESTS=true \
  uv run --env-file .vscode/.env.embedding-tests \
  pytest -v -rs backend/tests/manual/embedding_models/test_cloud_embedding_models_live.py
```

Each call goes through `EmbeddingModel.encode`, the path that indexing and
query embedding use. The suite checks the 5 selectable cloud models:

- Vector count and dimension (from the registry), finite values and non-zero norm, for QUERY and PASSAGE.
- A batch above the provider limit keeps its order: 130 texts for Cohere and OpenAI, 12 for Vertex.
- Semantic ranking: each query finds its passage first.
- QUERY and PASSAGE vectors differ for Cohere and Gemini.
- `reduced_dimension` for OpenAI and `gemini-embedding-2`, at 1/4 and 1/2 of the full dimension.

### End to end

Read [E2E warning](#e2e-warning) first.

Run the suite against a disposable stack, for example a separate Docker
Compose project with its own volumes, and its api_server on port 18080. Do not
point it at your normal dev stack (port 8080).

```bash
ONYX_EMBEDDING_E2E=true ONYX_EMBEDDING_E2E_ALLOW_MUTATION=true \
API_SERVER_HOST=127.0.0.1 API_SERVER_PORT=18080 \
ONYX_E2E_ADMIN_EMAIL=<admin email> ONYX_E2E_ADMIN_PASSWORD=<admin password> \
ONYX_EMBEDDING_E2E_MODELS=ibm-granite/granite-embedding-97m-multilingual-r2,embed-v5.0-fast \
  uv run --env-file .vscode/.env.embedding-tests \
  pytest -v -s -rs backend/tests/manual/embedding_models/e2e
```

Remove `ONYX_EMBEDDING_E2E_MODELS` to run all 8 selectable models. Do not use
`-n`: the tests must run in file order.

The suite does these steps:

1. It logs in as an existing admin. It never resets the database. If the stack
   has connectors in INVALID status, it stops here, unless
   `ONYX_EMBEDDING_E2E_ALLOW_CONNECTOR_DELETION=true`.
2. It sends each LEGACY registry model as a new target. The API must refuse each one with a 4xx. If the API accepts one, the suite cancels that re-index and fails.
3. It starts a re-index to the current (PRESENT) model. The API must accept it. Then the suite cancels it.
4. It creates an API key and a connector, and it seeds 5 documents. The document ids contain a unique marker.
5. For each target model, the suite does these steps:
   1. It connects the cloud provider with the key from the env var.
   2. It starts a REINDEX to the target model.
   3. It waits for the port and the swap.
   4. It checks the current settings and the index name.
   5. It runs a pure vector search (`hybrid_alpha=1.0`) for a paraphrase of each seeded document. Each document must be in the top 3.
6. At the end it deletes the API key and the connector. The deletion task then removes the seeded documents.

The search check uses the EE endpoint `/api/search/send-search-message`. Start
the target stack with `ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=true`.

## E2E warning

The e2e suite changes the target deployment:

- It re-embeds **every** document on the stack once for each target model, not
  only the seeded documents.
- It overwrites the stored key of each cloud provider that it connects.
- The last target model stays the live model. The upgrade-only rule then blocks
  a return to a legacy model (for example nomic) through the API.
- Each re-index consents to deleting every connector in INVALID status (except
  the default Ingestion connector). The API does not start a re-index without
  this consent. After the swap, the clean-up of the old index deletes these
  connectors and their documents. The suite gives this consent only with
  `ONYX_EMBEDDING_E2E_ALLOW_CONNECTOR_DELETION=true`. Fix or delete INVALID
  connectors before the run.

Do not run it against a deployment that people use. Use a disposable stack,
for example a separate Docker Compose project with its own volumes and ports.
Or take a Postgres and OpenSearch snapshot before the run, so that you can
restore it.

## Runtime and cost

| Suite | Runtime | Cost |
|---|---|---|
| Self-hosted | The first run downloads about 3.7 GB (granite 195 MB, voyage-4-nano 693 MB, Nemotron 2.28 GB, nomic about 550 MB). After that, about 5 to 15 minutes on a laptop CPU. Nemotron needs about 8 GB of free RAM on CPU (fp32). | None |
| Cloud | About 2 to 5 minutes with all keys. | Less than 0.10 USD. |
| E2E | Each switch waits for a full re-embed of the stack. A cloud model or granite takes minutes on a small stack. Nemotron on CPU embeds about 2 passages per second, so use a GPU or a small stack. | Cloud cost scales with the number of documents on the stack, for each cloud target. |

## Troubleshooting

- **All tests skip.** Check the skip reason (`-rs`). It names the gate env vars that are not `true`.
- **A cloud case skips.** Its key env var is not set.
- **Golden scores fail with `ONYX_EMBEDDING_TEST_DEVICE=auto`.** bf16 on GPU or MPS can drift. Run again with the default `cpu`.
- **E2E fails with "no default target" or "port 8080".** Set `API_SERVER_HOST` and `API_SERVER_PORT` to a disposable stack.
- **E2E fails with "connectors ... are INVALID".** Fix or delete those connectors, or set `ONYX_EMBEDDING_E2E_ALLOW_CONNECTOR_DELETION=true` to let the suite delete them.
- **E2E fails with "already in progress".** Another re-index runs on the stack. Let it finish, or cancel it on the admin Index Settings page.
- **E2E search returns 404.** The stack runs without EE. Set `ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=true`.
- **E2E times out on Nemotron.** Increase `ONYX_EMBEDDING_E2E_TIMEOUT_SECONDS`, or run the model server on a GPU.
