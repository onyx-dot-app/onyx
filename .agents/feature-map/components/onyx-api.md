# Onyx API

> Onyx's public HTTP surface: the contract external software programs against.
> It is not one router. It is a cross-cutting `public` tag applied to selected
> endpoints across roughly twenty routers, plus one dedicated router for
> pushing documents into Onyx without a connector.

**Domain:** onyx-api
**Edition:** CE for the tag mechanism, the ingestion router, and OpenAPI
generation. EE adds one tagged router ([[access-control]]'s user-group API).
**Owns:**
`backend/onyx/server/onyx_api/` (`ingestion.py`, `models.py`),
`backend/onyx/configs/constants.py` (`PUBLIC_API_TAGS`),
`backend/onyx/server/auth_check.py` (`PUBLIC_ENDPOINT_SPECS`,
`check_router_auth`), `backend/onyx/main.py` (app construction,
`ENABLE_PUBLIC_DOCS`), `backend/scripts/onyx_openapi_schema.py`,
`backend/scripts/transform_openapi_for_docs.py`,
`backend/scripts/api_inference_sample.py`.

**Does not own:** the ~106 individual endpoints that carry the `public` tag.
Each belongs to its own component (chat endpoints to [[core-chat-loop]],
connector/cc-pair endpoints to [[cc-pairs-and-credentials]], persona endpoints
to [[agents-personas]], and so on). This document owns the tag, the
ingestion router, and the docs pipeline; it does not restate what each tagged
endpoint does. Authentication mechanics (API keys, PATs, scopes,
`check_router_auth`'s auth-dependency requirement) belong to
[[auth-and-identity]]; this document only states how the public API uses them.

---

## 1. What the user experiences

A person integrating with Onyx from outside the web app (a script, a CI job,
a third-party backend) authenticates with an API key or a personal access
token and calls the same HTTP endpoints the Onyx frontend calls: create a
chat session, send a message, list personas, manage connectors, and so on.
There is no separate "external API" with its own paths or response shapes.
The `public` tag marks which of these endpoints are meant to be depended on
by integrators, and, when `ENABLE_PUBLIC_DOCS` is turned on, which ones show
up in the generated OpenAPI schema and interactive docs.

One part of the surface has no UI equivalent at all: the ingestion API
(`GET /onyx-api/connector-docs/{cc_pair_id}`, `GET /onyx-api/ingestion`,
`POST /onyx-api/ingestion`, `DELETE /onyx-api/ingestion/{document_id}`). It
lets a script push a document into Onyx's index directly, without configuring
a connector, credential, or crawl. This is the API's one genuinely
API-native feature.

---

## 2. Surfaces

### The `public` tag

`PUBLIC_API_TAGS: list[str | Enum] = ["public"]`
(`backend/onyx/configs/constants.py:29`). Passed as `tags=PUBLIC_API_TAGS` on
an `APIRouter` (marks every route in the router) or on an individual
`@router.get/post/...` decorator (marks just that route).

`grep -rn "PUBLIC_API_TAGS" backend/onyx backend/ee | grep "tags="` returns
106 matches across these files:

| Router file | What it exposes |
|---|---|
| `onyx/server/onyx_api/ingestion.py` | The ingestion API (below), tagged at the router level. |
| `onyx/server/query_and_chat/chat_backend.py` | Chat session and message endpoints; see [[core-chat-loop]]. |
| `onyx/server/features/persona/api.py` | Persona/agent CRUD and listing; see [[agents-personas]]. |
| `onyx/server/features/projects/api.py` | Projects, project files; see [[chat-persistence]]/[[core-chat-loop]]. |
| `onyx/server/documents/connector.py` | Connector CRUD, indexing status, run-once; see [[cc-pairs-and-credentials]]. |
| `onyx/server/documents/cc_pair.py` | CC-pair status, pruning, errors, index attempts; see [[cc-pairs-and-credentials]]. |
| `onyx/server/documents/credential.py` | Credential management (router-level tag); see [[cc-pairs-and-credentials]]. |
| `onyx/server/features/tool/api.py` | Custom tool CRUD, OpenAPI-based tool import; see [[tools-framework]]. |
| `onyx/server/features/search/api.py` | The one-shot search endpoint, gated by `require_vector_db`; see [[internal-search]]. |
| `onyx/server/features/web_search/api.py` | Web search router (router-level tag). |
| `onyx/server/features/usage/api.py` | Usage and cost-override endpoints (three routers, all tagged); see [[rate-and-usage-limits]]. |
| `onyx/server/features/mcp/client_metadata.py` | MCP OAuth client-metadata discovery endpoint; see [[mcp-server]]. |
| `onyx/server/features/build/interactive_turns/api.py`, `.../build/session/messages.py` | Craft/build session turn and message endpoints. |
| `onyx/server/manage/users.py` | User management: list, invite, activate/deactivate, `/me`; see [[auth-and-identity]]. |
| `onyx/server/manage/administrative.py` | Admin deletion-attempt endpoint. |
| `onyx/server/manage/get_state.py` | Health, readiness, version, auth-type endpoints. |
| `onyx/server/auth/captcha_api.py` | Pre-OAuth captcha verification (router-level tag). |
| `ee/onyx/server/user_group/api.py` | EE user-group management (router-level tag); see [[access-control]]. |
| `ee/onyx/server/query_and_chat/search_backend.py` | EE search-flow classification and search history. |
| `ee/onyx/server/query_history/api.py` | Query-history export endpoints. |
| `ee/onyx/server/analytics/api.py` | Analytics router (router-level tag). |
| `ee/onyx/server/token_rate_limits/api.py` | Token rate-limit admin router (router-level tag); see [[rate-and-usage-limits]]. |

This list is exhaustive; re-run the grep above before
trusting a specific count, since new endpoints can add or drop the tag.

### The ingestion router (`onyx-api/ingestion.py`, prefix `/onyx-api`)

| Method | Path | Handler | Auth | Notes |
|---|---|---|---|---|
| GET | `/onyx-api/connector-docs/{cc_pair_id}` | `get_docs_by_connector_credential_pair` | `require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)` | Lists the documents attached to one cc-pair. GATE 2: `verify_user_has_access_to_cc_pair`. |
| GET | `/onyx-api/ingestion` | `get_ingestion_docs` | `require_permission(Permission.MANAGE_CONNECTORS)` | Lists every document ever pushed through this API, org-wide; no `allow_scope`, so no group scope can narrow it (comment at `ingestion.py:89`). |
| POST | `/onyx-api/ingestion` | `upsert_ingestion_doc` | `require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)` + `Depends(require_vector_db)` | The write path; see §4.2. |
| DELETE | `/onyx-api/ingestion/{document_id}` | `delete_ingestion_doc` | `require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)` + `Depends(require_vector_db)` | Only deletes documents with `from_ingestion_api=True`; refuses to delete a connector-synced document. |

`require_vector_db` (`onyx/server/utils_vector_db.py:require_vector_db`)
raises `501` when `DISABLE_VECTOR_DB` is set, since ingestion writes and
deletes require a working index; the read endpoints do not carry this
dependency.

### Environment configuration

| Variable | File | Default | Effect |
|---|---|---|---|
| `ENABLE_PUBLIC_DOCS` | `onyx/configs/app_configs.py:383` | off (`os.environ.get("ENABLE_PUBLIC_DOCS", "").lower() == "true"`) | When true, registers `/openapi.json`, `/docs`, `/redoc` on the FastAPI app (`onyx/main.py:527-529`). When false, those paths are never registered (404), not merely hidden. |
| `DISABLE_VECTOR_DB` | `onyx/configs/app_configs.py` | off | Gates `require_vector_db`; makes ingestion writes/deletes return 501. |

---

## 3. Data model

The ingestion router writes to tables it does not own:

- `Document.from_ingestion_api` (`onyx/db/models.py`): set true by
  `upsert_ingestion_doc` (`ingestion.py:137`); `delete_ingestion_doc` refuses
  to act on a document where this is false. `get_ingestion_documents`
  (`onyx/db/document.py:1432`) filters on it directly.
- `Document.content_hash`: written by
  `update_docs_content_hash__no_commit` (`onyx/indexing/indexing_pipeline.py`)
  after a successful vector-DB write, and is the mechanism that lets a
  re-push of unchanged content skip re-embedding.
- Connector-credential-pair ownership rows, via
  `get_cc_pair_ids_for_document` / `verify_user_can_edit_all_cc_pairs`
  (`onyx/db/connector_credential_pair.py`): a document can be served by more
  than one cc-pair, so both the create and delete paths check every owning
  pair, not just the one named in the request. See
  [[cc-pairs-and-credentials]].

No table belongs to this component itself; there is no "public API request
log" or "API version" table. That absence is itself a fact worth carrying
into §5 and §9.

---

## 4. How it works

### 4.1 Assembling and documenting the surface

```
FastAPI app construction                          onyx/main.py:get_application
  ├─ openapi_url/docs_url/redoc_url = None unless ENABLE_PUBLIC_DOCS
  ├─ include_router_with_global_prefix_prepended(application, <every router>)
  │    (each router's own routes carry whatever tags they declared,
  │     PUBLIC_API_TAGS among them)
  └─ check_router_auth(application)                onyx/server/auth_check.py
       walks every registered route; requires a real auth dependency
       unless (path, methods) is in PUBLIC_ENDPOINT_SPECS

Offline schema generation                          scripts/onyx_openapi_schema.py
  └─ get_openapi(routes=app.routes) → full schema, every route, every tag
       ├─ strip_tags_from_schema  → client-generation schema (tags removed
       │    so codegen tools put everything in one DefaultApi)
       └─ (optional) tagged schema written verbatim for the docs pipeline

Docs-site filtering                                scripts/transform_openapi_for_docs.py
  └─ keeps only operations whose "tags" include PUBLIC_TAG = "public"
       ├─ rewrites auth to Bearer-token only
       ├─ drops INTERNAL_PARAMETERS = {"tenant_id", "db_session"}
       └─ prunes schemas down to only what the kept operations reference
```

`check_router_auth` never looks at `PUBLIC_API_TAGS`. It only looks for a
real FastAPI auth dependency (`current_user`, `require_permission(...)`,
etc.) or an entry in `PUBLIC_ENDPOINT_SPECS`. Tagging a route `public` has no
effect on whether the route requires authentication; see §5.1 for why these
are unrelated mechanisms.

`transform_openapi_for_docs.py` is the only code that reads the `public` tag
for a behavioral purpose: it decides what appears in the externally hosted
docs site. `strip_tags_from_schema` (in `onyx_openapi_schema.py`) discards
tags entirely for the client-generation output, so that pipeline does not
distinguish public from non-public at all.

### 4.2 Ingestion write path

```
POST /onyx-api/ingestion                          onyx_api/ingestion.py:upsert_ingestion_doc
  ├─ reject file_id / TabularSection payloads (ingestion API cannot
  │    reference file-store content)
  ├─ reject image_file_id references the caller doesn't own
  │    (get_owned_file_ids)
  ├─ document.from_ingestion_api = True
  ├─ resolve target_cc_pair_id (doc_info.cc_pair_id or DEFAULT_CC_PAIR_ID = 1,
  │    onyx/configs/constants.py:72, the seeded default pair)
  ├─ GATE 2: verify_user_has_access_to_cc_pair(target_cc_pair_id, ...)
  │    (the default pair is public, so a scoped manager cannot ingest into it
  │    without broader access, per the comment at ingestion.py:155)
  ├─ GATE 2 again: verify_user_can_edit_all_cc_pairs(existing_cc_pair_ids, ...)
  │    for every pair that ALREADY serves this document_id, before the
  │    upsert rewrites the shared row and replaces its chunks
  ├─ reject if document_id collides with an existing user-file id
  │    (get_user_file_by_id)
  └─ run_indexing_pipeline(document_batch=[document], ignore_time_skip=True, ...)
       (primary index, and again for a secondary index if one is building)
       → IngestionResult(document_id, already_existed = new_docs == 0)
```

`run_indexing_pipeline` is the same function every connector uses; see
[[indexing-pipeline]]. The ingestion router's only special behavior is
`from_ingestion_api=True`, `ignore_time_skip=True` (bypass the normal
poll-interval skip), and the ownership checks above. It does not go through
`document_push.py` (`onyx/indexing/document_push.py`): that module is the
*outbound* sink, firing an optional webhook after any document (from any
source, including ingestion) is indexed. It is unrelated to how a document
gets in.

### 4.3 Ingestion delete path

```
DELETE /onyx-api/ingestion/{document_id}          ingestion.py:delete_ingestion_doc
  ├─ 404 if the document doesn't exist
  ├─ reject if from_ingestion_api is False (cannot delete a connector doc
  │    through this endpoint)
  ├─ GATE 2: verify_user_can_edit_all_cc_pairs over every owning pair
  ├─ record_port_orphan_candidates_for_document (commits) before the index
  │    delete, so a racing index-port doesn't resurrect the doc
  ├─ delete from every document index (primary + secondary if present)
  └─ delete_documents_complete (Postgres row)
       on failure: rollback, then clean up only the port-orphan rows this
       call inserted, and re-raise
```

### 4.4 Authentication on this surface

The ingestion router and every other `public`-tagged endpoint authenticate
exactly like any other Onyx endpoint: a session cookie, or a Bearer API key
/ PAT resolved through `optional_user` (`auth/users.py:_resolve_optional_user`,
see [[auth-and-identity]] §4.7). There is no separate credential type for
"the public API." A scoped PAT's `scopes` still cap `require_permission`'s
decision the same way; the ingestion endpoints require
`Permission.MANAGE_CONNECTORS`, so a PAT scoped to something narrower (for
example `use:llm_gateway`) cannot reach them. An unscoped PAT or API key
grants whatever the underlying user's (or service account's)
`effective_permissions` allow, capped by nothing beyond that, per
[[auth-and-identity]] §4.8's `permitted_by_token` check.

---

## 5. Contracts and invariants

1. **Tagging an endpoint `public` is a compatibility commitment, not a
   grouping label.** It is what `transform_openapi_for_docs.py` uses to
   decide what ships in the externally hosted docs. Changing a tagged
   endpoint's path, method, request shape, or response shape breaks whatever
   integrators read those docs and built against. Removing the tag from an
   endpoint that already shipped in the docs is a breaking change to the
   documented surface even if the endpoint itself keeps working.
2. **The two senses of "public" are different concepts and must not be
   conflated.** `PUBLIC_API_TAGS` (`onyx/configs/constants.py:29`) marks an
   endpoint as *documented and supported for integrators*; it is still fully
   authenticated. `PUBLIC_ENDPOINT_SPECS`
   (`onyx/server/auth_check.py:PUBLIC_ENDPOINT_SPECS`) marks an endpoint as
   *reachable with no auth dependency at all*. The two lists barely overlap:
   `/health`, `/version`, `/versions`, `/auth/type`, and `/me` are marked
   with the `public` tag in their routers (`onyx/server/manage/get_state.py`,
   `onyx/server/manage/users.py:1081`) and separately listed in
   `PUBLIC_ENDPOINT_SPECS` because they are also meant to be callable before
   login. Every other `public`-tagged endpoint (ingestion, chat, personas,
   connectors, ...) requires a real session or token; being in
   `PUBLIC_API_TAGS` says nothing about whether a request needs
   authentication. Reading "public" in one list as implying anything about
   the other is a security-relevant misreading.
3. **Ingestion is idempotent on `document_id`, verified.**
   `upsert_ingestion_doc` always calls `Document.from_base` and
   `run_indexing_pipeline`, which performs a Postgres upsert keyed on
   document id (`onyx/db/document.py:upsert_documents`) and only re-embeds
   and re-writes vector-DB chunks when `content_hash` changed
   (`indexing_pipeline.py`'s hash-skip logic). `IngestionResult.already_existed`
   is `new_docs == 0` from the pipeline result, so a caller can tell a
   create from a re-push. Re-pushing the same `document_id` never creates a
   second document row; it updates the existing one (or is a near no-op if
   the content is unchanged).
4. **A `public`-tagged endpoint still enforces the same permissions and ACLs
   as any other endpoint.** The tag changes nothing about `require_permission`,
   scope capping, or GATE 2 ownership checks. Every ingestion route above
   still runs the full auth chain from [[auth-and-identity]] §4.8.
5. **`check_router_auth` is not aware of `PUBLIC_API_TAGS` and never will be
   by construction.** It walks FastAPI's dependency graph, not route tags. A
   PR that assumes tagging a new endpoint `public` satisfies the startup auth
   check is wrong; the endpoint still needs its own `current_user` /
   `require_permission(...)` dependency, or an explicit
   `PUBLIC_ENDPOINT_SPECS` entry if it is genuinely meant to be unauthenticated.
6. **`require_vector_db` gates the ingestion write routes, not the read
   routes.** `POST /onyx-api/ingestion` and `DELETE /onyx-api/ingestion/{id}`
   depend on it; `GET /onyx-api/ingestion` and
   `GET /onyx-api/connector-docs/{id}` do not, since listing existing
   documents does not require a live vector DB.

---

## 6. Relationships

**Depends on**
- [[auth-and-identity]]: every endpoint on this surface, tagged or not,
  authenticates through the same API key / PAT / session resolution and the
  same `require_permission` scope-capping.
- [[indexing-pipeline]]: `run_indexing_pipeline` is the write path for both
  ingestion-API documents and connector-synced documents.
- [[cc-pairs-and-credentials]]: the ingestion router attaches documents to a
  cc-pair (`DEFAULT_CC_PAIR_ID` or a caller-specified one) and enforces the
  same ownership checks that gate connector management.
- [[rate-and-usage-limits]]: usage endpoints (`usage/api.py`) that carry the
  `public` tag report on the same usage this component gates for.

**Depended on by**
- Anyone integrating with Onyx from outside the web app: scripts, CI, other
  services. `scripts/api_inference_sample.py` is a minimal worked example
  (create a chat session, send a message, read the streamed answer) using an
  API key as a Bearer token, and is not itself part of the shipped surface.
- [[core-chat-loop]]: chat's endpoints are the single largest contributor of
  tagged surface; a change there is a change to the public API even though
  core-chat-loop owns the behavior.
- [[llm-gateway]] and [[mcp-server]]: separate integration surfaces
  (a PAT-scoped gateway, and an MCP-protocol server) that sit alongside this
  HTTP surface rather than inside it; neither carries the `public` tag itself,
  since neither is a FastAPI route tagged this way. Treat them as sibling
  integration points, not part of this document's owned surface.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds the `public` tag to an endpoint | it now appears in the docs site if `ENABLE_PUBLIC_DOCS` is on and `transform_openapi_for_docs.py` runs; confirm the request/response models are stable enough to commit to, and that `db_session`/`tenant_id` params (auto-stripped) are the only internal parameters it has |
| changes a tagged endpoint's request or response shape | this is a breaking change for integrators by definition (§5.1); check `transform_openapi_for_docs.py`'s schema-reference walk still resolves, and update `scripts/api_inference_sample.py` if it uses that endpoint |
| changes `PUBLIC_API_TAGS` itself (not just which routes use it) | every one of the ~106 tagged routes and both OpenAPI scripts, since the string literal `"public"` is hardcoded again in `transform_openapi_for_docs.py:PUBLIC_TAG` rather than imported |
| changes the ingestion router (`ingestion.py`) | [[indexing-pipeline]] (payload shape into `run_indexing_pipeline`), [[cc-pairs-and-credentials]] (the GATE 2 ownership checks), and the idempotency contract in §5.3 |
| changes `ENABLE_PUBLIC_DOCS` default or behavior | whether `/openapi.json`/`/docs`/`/redoc` exist at all (`onyx/main.py:527-529`); confirm `PUBLIC_ENDPOINT_SPECS`'s entries for those three paths still match reality, since they assume the routes may or may not be registered |
| adds a new non-human credential type or changes scope capping | this surface's effective reachability; see [[auth-and-identity]] §7 for the fuller list of what else that touches |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/integration -k ingestion
cd backend && uv run pytest tests/integration -k onyx_api
```

Search `backend/tests/integration/tests/` for a directory named after the
router you changed (for example `tests/integration/tests/pat`,
`tests/integration/tests/api_key`) if the change is about auth rather than a
specific endpoint's behavior; see `backend/AGENTS.md` for the authoritative
command list and required secrets/env. This search did not locate a
dedicated `tests/integration/tests/ingestion` directory in this checkout;
treat the presence of ingestion-specific integration coverage as unverified
and confirm directly before relying on it.

### Regenerating the OpenAPI schema

```bash
cd backend && uv run python scripts/onyx_openapi_schema.py <output.json>
# with a docs-tagged copy alongside the stripped client-gen schema:
cd backend && uv run python scripts/onyx_openapi_schema.py <output.json> <tagged_output.json>
cd backend && uv run python scripts/transform_openapi_for_docs.py -i <tagged_output.json> -o <docs_output.json>
```

### Manual reproduction (ingestion)

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Create a PAT or API key with `Permission.MANAGE_CONNECTORS` (through the
   frontend, per [[auth-and-identity]] §8).
3. `curl -X POST http://localhost:3000/api/onyx-api/ingestion -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"document": {...}}'`
   (always go through the frontend proxy at `:3000`, not `:8080` directly,
   per the root `CLAUDE.md`).
4. Confirm the response's `already_existed` is `false` on first push.
5. Re-push the identical payload; confirm `already_existed` is `true` and no
   second document row was created (`GET /onyx-api/ingestion` still lists one
   entry for that `document_id`).
6. `DELETE /onyx-api/ingestion/{document_id}`; confirm the document is gone
   from both Postgres and the document index, and that a repeat delete 404s.

### What "working" looks like

- A re-pushed `document_id` never duplicates a row or a chunk.
- An ingestion write against a cc-pair the caller cannot manage returns
  `INSUFFICIENT_PERMISSIONS`, not a silent success against the wrong pair.
- With `ENABLE_PUBLIC_DOCS` unset, `/openapi.json`, `/docs`, and `/redoc` all
  404.
- The docs-transformed schema contains only operations tagged `public`, with
  `tenant_id`/`db_session` parameters stripped from all of them.

---

## 9. Footguns

- **"Public" means two different things and the code gives no warning when
  you mix them up.** `PUBLIC_API_TAGS` (documented surface, still
  authenticated) and `PUBLIC_ENDPOINT_SPECS` (no authentication required) are
  unrelated lists that happen to share the English word. An endpoint can be
  in neither, either, or both. Grepping for "public" and assuming every hit
  means "no auth" is the specific mistake this document exists to prevent.
- **There is no API versioning.** No version prefix (no `/v1/`), no
  deprecation header, no changelog file, and no mechanism in
  `transform_openapi_for_docs.py` or `onyx_openapi_schema.py` that tracks
  what changed between two schema snapshots. `app.version` is the whole
  application's release version, not an API contract version. If you are
  integrating against this API, the only stability guarantee is "endpoints
  tagged `public` are not casually changed"; there is nothing to pin a
  request to beyond a Git commit or Docker image tag. Treat any breaking
  change to a tagged endpoint as requiring the same care as a database
  migration, since there is no version negotiation to fall back on.
- **`DEFAULT_CC_PAIR_ID = 1` is a real, ambient default.** An ingestion
  request with no `cc_pair_id` lands in the seeded default pair, which is
  public by default; the GATE 2 check exists specifically because a scoped
  group manager should not be able to write there just because it is
  unscoped-looking.
- **The stripped (client-generation) schema and the tagged (docs) schema are
  different artifacts from the same generator run.** `onyx_openapi_schema.py`
  produces the full untagged-in-name-only schema by default; you must pass
  `tagged_for_docs` explicitly to also get the version
  `transform_openapi_for_docs.py` expects as input. Running the docs
  transform against the stripped schema silently keeps nothing, since it
  filters on the `tags` field that stripping just removed.
- **`document_push.py` is not the ingestion write path.** Despite the name
  suggesting an inbound push, `onyx/indexing/document_push.py` is an
  *outbound* fire-and-forget webhook fired after any document (ingested or
  connector-synced) is indexed. Do not confuse it with the ingestion
  router's `POST /onyx-api/ingestion`, which is the actual inbound path; they
  share no code beyond both eventually flowing through
  `run_indexing_pipeline`.
