# Onyx API

> The HTTP surface that external software programs against: the ordinary routes
> that carry the `public` tag, their reference-docs pipeline, and the router that
> pushes documents into the index without a connector.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE for the tag, the ingestion router and the OpenAPI scripts. Several
EE routers also carry the tag.

---

## User experience

- **An API caller** (a script, CI job or another backend) sends a personal access
  token or an API key as a Bearer token. It calls the same `/api/...` routes that
  the web app calls, with the same request and response shapes. The token's
  permissions and scopes apply as they do for any route ([[authorization]]).
  Creating API keys needs the Business tier.
- **The caller reads the API reference** at docs.onyx.app. It lists only the
  routes tagged `public`, with Bearer auth and no internal parameters.
- **A caller that pushes documents** posts them to `/onyx-api/ingestion`. They
  become searchable with no connector, credential or crawl. A second push of the
  same `document_id` updates the document, and the response says whether it
  existed before.
- **A caller sees these failures:** 401 or 403 for a missing token or permission;
  402 for a route above the deployment's tier ([[editions-and-gating]]); 501 from
  the ingestion writes when the vector database is turned off; 429 from an LLM
  route over a token budget, and on cloud from the chat and search routes when
  the weekly API-call cap is used up ([[rate-and-usage-limits]]).
- **An operator** can serve `/openapi.json`, `/docs` and `/redoc` from a
  deployment by setting `ENABLE_PUBLIC_DOCS=true`. They are off by default.

---

## Scope

This component owns:
- the `public` tag convention (`PUBLIC_API_TAGS`) and what it promises callers;
- the ingestion API, which writes and deletes documents with no connector;
- the scripts that build the OpenAPI spec for the customer reference.

It does not own the tagged routes. Each belongs to the component that owns its
router. To list them, run `git grep -n "PUBLIC_API_TAGS" backend`.

Its neighbours own:
- [[auth-and-identity]]: API keys and PATs as identities.
- [[authorization]]: token scopes, GATE 1 and GATE 2, and the startup auth check.
- [[rate-and-usage-limits]]: the cloud API-call cap.
- [[indexing-pipeline]]: `run_indexing_pipeline`, which the ingestion router
  calls.
- [[mcp-server]] and [[llm-gateway]]: separate integration surfaces that do not
  use the tag.
- The customer docs: the reference pages themselves, written to the rules of the
  documentation agents file.

---

## Architecture

**The reference pipeline.**

```
documentation/scripts/generate.sh
  -> backend/scripts/onyx_openapi_schema.py --tagged-for-docs
                                         imports onyx.main:app, which loads the EE app
       default output: tags stripped, for client generation
       tagged output: every route, tags kept
  -> backend/scripts/transform_openapi_for_docs.py
                                         keeps operations tagged "public",
                                         Bearer auth only, drops tenant_id
                                         and db_session, prunes schemas
  -> documentation/developers/api_reference/openapi.json  generated, not committed
```

Each reference page in `documentation/developers/api_reference/` names its
operation as `METHOD /path`. The `docs-check` workflow
(`.github/workflows/docs-check.yml`) regenerates the spec and runs Mintlify
validation on every PR that touches `backend/onyx/server/` or
`backend/ee/onyx/server/`.

`backend/onyx/main.py:use_route_function_names_as_operation_ids` sets each
operation id to the handler's function name.

**The ingestion write.**
`backend/onyx/server/onyx_api/ingestion.py:upsert_ingestion_doc` runs in the
request:

```
reject file_id, TabularSection, and image ids the caller does not own
mark from_ingestion_api = True; set doc_updated_at to the request time when it is missing
target pair = cc_pair_id or DEFAULT_CC_PAIR_ID (1, the public default pair)
GATE 2 at EDIT on the target pair
GATE 2 at EDIT on every pair that already serves this document_id
reject an id that belongs to a user file
run_indexing_pipeline(ignore_time_skip=True) on the primary index, then the secondary if one is building
-> IngestionResult(already_existed = new_docs == 0)
```

`delete_ingestion_doc` refuses a document that a connector wrote, checks every
owning pair, records port-orphan candidates, and then deletes from the index and
Postgres.

---

## Contracts and traps

1. `two-meanings-of-public` **"Public" means two unrelated things.**
   `backend/onyx/configs/constants.py:PUBLIC_API_TAGS` marks a route as
   documented for integrators. The route still
   needs authentication. `backend/onyx/server/auth_check.py:PUBLIC_ENDPOINT_SPECS`
   marks a route that needs no authentication.
   `backend/onyx/server/auth_check.py:check_router_auth` never reads
   the tag. A route with no auth dependency fails the startup check unless
   `PUBLIC_ENDPOINT_SPECS` lists it, tagged or not. Some routes, such as `/health`
   and `/me`, are in both lists.
2. `tagged-route-is-contract` **A tagged route is a published contract, and there
   is no versioning.** No `/v1` prefix, no deprecation header, and nothing to pin
   a request to beyond the release. Every breaking change reaches callers with
   the next release. Change a tagged route's path, method, parameters or response
   fields only in an additive way. Removing the tag drops the route from the
   reference, and its page in `documentation/` then names an operation that the
   spec does not have.
3. `tag-controls-docs` **The tag also controls customer docs.** A newly tagged
   route needs a page in `documentation/developers/api_reference/`, with the
   permission note that the other pages carry. Request and response models must
   be stable before you tag them.
4. `operation-id-is-handler-name` **Operation ids are handler names.** Renaming a
   tagged route's handler changes its id in the schema and in any generated
   client.
5. `transform-needs-tagged-output` **Run the docs transform on the tagged
   output.** The default output of `backend/scripts/onyx_openapi_schema.py` has no
   tags, so the transform keeps nothing.
   `backend/scripts/transform_openapi_for_docs.py:PUBLIC_TAG` repeats the string
   `"public"` instead of importing `PUBLIC_API_TAGS`. Change both together.
6. `spec-from-ee-app` **The spec comes from the EE app.** Tagged EE routes appear
   in the reference. A Community deployment refuses the paid ones at runtime.
7. `ingestion-idempotent` **Ingestion is idempotent on `document_id`.** The
   pipeline upserts the row. When the caller omits `doc_updated_at`, the router
   sets it to the request time, so every such push re-embeds. The pipeline skips
   a push only when `doc_updated_at` did not advance and the content hash is
   unchanged (`backend/onyx/indexing/indexing_pipeline.py:get_docs_to_update`).
   Keep `already_existed`, because callers use it to tell a create from an
   update.
8. `from-ingestion-api-last-writer` **`from_ingestion_api` records the last
   writer.** `backend/onyx/db/document.py:upsert_documents` overwrites it on
   conflict. A connector that indexes the same id sets it back to false, and the
   ingestion delete then refuses the document.
9. `ingestion-gates-before-pipeline` **Both ingestion gates must run before the
   pipeline.** The pipeline replaces the shared document row and its chunks, and
   adds the target pair as an owner. A check after it is too late. A user file
   has no document row or pair, so the user-file id check stops an overwrite of
   its chunks.
10. `only-writes-need-vector-db` **Only the ingestion writes need the vector
    database.** `backend/onyx/server/utils_vector_db.py:require_vector_db` guards `POST` and `DELETE`. The `GET` routes
    work without it.
11. `document-push-not-ingestion` **`backend/onyx/indexing/document_push.py` is
    not ingestion.** It is an outbound sink that fires after any document is
    indexed. Do not change it to change how documents come in.

---

## Known issues

- **The ingestion list is org-wide.** `GET /onyx-api/ingestion` uses
  `require_permission` without `allow_scope`, on purpose, because no group scope
  can bound the list. Only a manager with global `MANAGE_CONNECTORS` can call it.
  A scoped manager cannot list even its own pushed documents.

---

## Dependencies

- [[auth-and-identity]]: resolution of the Bearer token to a user.
- [[authorization]]: scopes and the GATE 1 and GATE 2 checks on every route.
- [[indexing-pipeline]]: the write path for pushed documents.
- [[cc-pairs-and-creds]]: the pair that a pushed document joins, and its
  ownership checks.
- [[editions-and-gating]]: the tier gate on paid tagged routes.

---

## Recipes

- `add-public-route` **Add a public route.** Copy
  `backend/onyx/server/features/search/api.py:search`: `tags=PUBLIC_API_TAGS` on
  the route, a real auth dependency, and the usage checks of
  [[rate-and-usage-limits#every-entry-point-checks]] when it drives LLM work. List the
  current set with `git grep -n "PUBLIC_API_TAGS" backend`. Then add a reference
  page by copying a page in `documentation/developers/api_reference/search/`.
- `check-generated-reference` **Check the generated reference.** Run `documentation/scripts/generate.sh`
  from the repo root. Search the generated OpenAPI spec in the API reference
  directory for the operation. A
  route that is missing has no `public` tag, or the transform ran on the stripped
  output ([[#transform-needs-tagged-output]]).
- `push-test-document` **Push a test document.** Through `http://localhost:3000/api`, post to
  `/onyx-api/ingestion` with a PAT that has `MANAGE_CONNECTORS`.
  `already_existed` is false. Push it again: it is true, and
  `GET /onyx-api/ingestion` lists one entry. Delete it, and a second delete
  returns 404.
- `call-api-from-script` **Call the API from a script.** Copy `backend/scripts/api_inference_sample.py`,
  a minimal client that creates a chat session and streams an answer.

---

## Verification

- Integration tests: `backend/tests/integration/tests/ingestion/`.
- The `docs-check` workflow regenerates the spec and validates the reference
  pages.
