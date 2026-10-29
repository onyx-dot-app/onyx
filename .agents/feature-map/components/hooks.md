# Hooks

> Hook extensions: a customer HTTPS endpoint that Onyx calls and waits on at a
> fixed point in chat or indexing, to rewrite or reject a query, rewrite or drop
> a document, or receive each indexed document. The hook decides what enters the
> pipeline, so a failure must follow its fail strategy exactly.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** EE, self-hosted only. CE runs a no-op. Cloud refuses the admin API
and skips every hook.

---

## User experience

- **An admin** opens Admin > Hooks, picks a hook point, and enters an HTTPS
  URL, an optional API key, a timeout and a fail strategy. Onyx calls the
  endpoint before it saves the hook, and a new hook starts active. The page
  shows whether the
  endpoint is reachable and lists recent failures. The customer guide is
  `documentation/admins/advanced_configs/hook_extensions.mdx`.
- **A user** with a query-processing hook active sees nothing when the hook
  passes or rewrites the query. When the hook rejects the query, the chat shows
  the hook's rejection message. When the endpoint fails with the HARD strategy,
  the message fails with an error. With SOFT, the original query runs.
- **A connector owner** with a document-ingestion hook sees documents that the
  hook rewrote, and does not find documents that the hook dropped. A HARD
  failure fails the indexing batch.
- **An external system** behind a document-push hook receives each indexed
  document from a public connector, after the first full index. A HARD failure
  fails the indexing batch after its documents are in the index. Onyx does not
  retry them one by one, because their content hashes are saved and a retry
  skips them as unchanged (`indexing/indexing_pipeline.py:DocumentPushFailure`).

---

## Scope

This component owns the hook point registry and specs, the CE entry point and
the EE executor, the hook tables, the admin API and page, and the generic
client that posts JSON to an external endpoint.

It does not own the call sites. [[core-chat-loop]] calls the query-processing
hook. [[indexing-pipeline]] calls the ingestion and push hooks, and owns the
config-driven document push (`DOCUMENT_PUSH_ENDPOINT_URL`), which uses the same
HTTP client.

---

## Architecture

```
call site ── execute_hook ── fetch_versioned_implementation
                               ├─ CE: HookSkipped
                               └─ EE: _lookup_hook (none / inactive / cloud → HookSkipped)
                                        └─ post_json_to_endpoint
                                             ├─ success → validated response model
                                             ├─ fail + SOFT → HookSoftFailed (caller keeps default)
                                             └─ fail + HARD → OnyxError(HOOK_EXECUTION_FAILED)
```

**Hook points.** `db/enums.py:HookPoint` lists them. Each has a
`HookPointSpec` subclass in `hooks/points/` with payload and response models, a
default timeout and a default fail strategy. `hooks/registry.py:_REGISTRY` maps
each point to its spec. `validate_registry` runs at API server startup and
fails when a point has no spec.

**Execution.** `backend/ee/onyx/hooks/executor.py:_execute_hook_impl` reads the
hook with the caller's session and copies the fields it needs, so no session is
in use during the HTTP call. After the call it writes a `HookExecutionLog` row
on failure only, in its own session. It updates `is_reachable` in a second
session, and only when the outcome carries a reachability signal that differs
from the stored value. A concurrent deletion makes that update fail, and the
separate session keeps the failure log.

**Call sites.**
- Query processing runs before the user message is saved, only for a new
  non-blank message, and only when the session's incognito mode allows it
  (`IncognitoRecordMode.fires_hooks`). An empty `query` in the response rejects
  with `QUERY_REJECTED`
  (`chat/process_message.py:_resolve_query_processing_hook_result`).
- Document ingestion runs per document, in order, in
  `indexing/indexing_pipeline.py:_apply_document_ingestion_hook`. An empty
  `sections` drops the document. When the first document returns `HookSkipped`,
  the rest skip the lookup.
- Document push runs per indexed document in
  `indexing/indexing_pipeline.py:_maybe_push_documents`. It runs only for a
  `PUBLIC` connector, not during a from-beginning index, and not under
  `MULTI_TENANT`. When `DOCUMENT_PUSH_ENDPOINT_URL` is set, the config-driven
  push runs instead of the hook, in every edition.

---

## Contracts and traps

1. `hard-aborts-soft-falls-back` **HARD must abort, SOFT must fall back.** A
   HARD failure raises `OnyxError`, and the caller must let it stop the
   pipeline. A SOFT failure returns `HookSoftFailed`, and the caller must keep
   its default behaviour. Every call site must handle all three results: the
   response model, `HookSkipped` and `HookSoftFailed`. CE code checks them with
   `isinstance`, so keep the classes in `backend/onyx/hooks/executor.py`.
2. `one-hook-per-point` **At most one non-deleted hook per hook point.**
   `db/hook.py:create_hook__no_commit` returns `CONFLICT`, and a partial unique
   index on `hook_point` where `deleted` is false catches concurrent creates.
3. `validate-url-at-config` **Validate the URL at configuration time.**
   `ee/onyx/server/features/hooks/api.py:_check_ssrf_safety` always requires
   HTTPS and follows the admin SSRF protection level.
   `utils/external_endpoint.py:post_json_to_endpoint` does not validate again
   and only refuses redirects. A new place that stores an endpoint must call
   `utils/url.py:validate_outbound_http_url`.
4. `query-hook-full-history-only` **The query-processing hook sends the raw
   query and the user's email out.** That is why it runs only for a
   full-history chat (`db/enums.py:IncognitoRecordMode.fires_hooks`). Keep this check if you add a hook point
   that sends user content.
5. `gateway-bypasses-hooks` **Hooks do not see LLM gateway traffic.** Requests
   to `/gateway/*` never run the query-processing hook
   (`hooks/points/query_processing.py`). A customer cannot use a hook to inspect
   content that an external tool sends to a model through [[llm-gateway]].
6. `per-document-sequential` **Each document waits on the endpoint in
   sequence.** Ingestion and push call the endpoint once per document with no
   concurrency (`indexing/indexing_pipeline.py:_apply_document_ingestion_hook`,
   `_maybe_push_documents`). A slow endpoint slows indexing by its latency times the batch
   size, up to the timeout.
7. `off-on-cloud-two-layers` **Hooks are off on cloud at two layers.**
   `onyx/hooks/api_dependencies.py:require_hook_enabled` refuses the admin API,
   and `ee/onyx/hooks/executor.py:_lookup_hook` returns `HookSkipped`. A new
   hook path must keep both.
8. `downgrade-deletes-hooks` **The Community downgrade deletes every hook.**
   `ee/onyx/db/community_downgrade.py:disable_paid_features__no_commit` marks
   each hook deleted and inactive ([[billing]]).

---

## Decisions

- **Only failures are logged.** A success writes no row, so a busy hook point
  adds no database write per call.
- **Saving and activating validate the endpoint.** `create_hook` and
  `activate_hook` send an empty POST first and refuse on a network error, a
  timeout, or a 401 or 403. Any other HTTP status passes, so an endpoint that
  cannot be reached never becomes active. `update_hook` checks again when the
  URL, key or timeout changes, and refuses a failing edit for an active hook.
  To edit an active hook whose endpoint is down, deactivate it, edit it, then
  activate it.

---

## Known issues

- **No check at delivery time against DNS rebinding.** A hostname that was
  public at validation can later resolve to a private address. The
  `_check_ssrf_safety` docstring states this.
- **`DocumentIngestionSpec` names a "Document Ingestion Light" path that has no
  code.** The docstring is stale.

---

## Dependencies

- [[editions-and-gating]]: `fetch_versioned_implementation` picks the CE no-op
  or the EE executor.
- [[multi-tenancy]]: `MULTI_TENANT` turns hooks off.
- [[authorization]]: the admin API needs `FULL_ADMIN_PANEL_ACCESS`.

---

## Recipes

- `new-hook-point` **A hook point.** Copy `hooks/points/query_processing.py`. List the current
  points in `db/enums.py:HookPoint` and `_REGISTRY`. Add the value to
  `HookPoint`, write a `HookPointSpec` subclass with payload and response
  models, and register it in `_REGISTRY`. Call `execute_hook` at the call site
  and handle all three results ([[#hard-aborts-soft-falls-back]]). Add the point
  to `web/src/ee/views/admin/HooksPage/hookPoints.ts` and its catalog strings,
  and document it in `hook_extensions.mdx`.
- `local-test-hook` **Set up a hook for a local test.** Run an EE build with `MULTI_TENANT` off.
  The endpoint must use HTTPS with a certificate that verifies, at every SSRF
  level, so a plain local HTTP server does not work; use an HTTPS tunnel. An
  endpoint on a private address also needs an SSRF protection level that allows
  private networks ([[#validate-url-at-config]]); a loopback address needs
  `SSRFProtectionLevel.DISABLED`. Start the endpoint before you create the
  hook, because creation calls it.
- `investigate-hook-not-run` **Investigate "the hook does not run".** Check the edition (CE is a no-op),
  `MULTI_TENANT`, and that the hook is active with an endpoint URL. For query
  processing, check that the message is new and not blank and that the session
  is full-history ([[#query-hook-full-history-only]]). For document push, check
  the connector access type, `from_beginning` and `DOCUMENT_PUSH_ENDPOINT_URL`.
  Failed calls are in `GET /admin/hooks/{hook_id}/execution-logs`; successes
  leave no row.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/hooks/`,
  `backend/tests/unit/ee/onyx/hooks/` and
  `backend/tests/unit/ee/onyx/server/features/hooks/`. The call sites have tests
  in `backend/tests/unit/onyx/indexing/` and `backend/tests/unit/onyx/chat/`.
- By hand on a self-hosted EE build: point a query-processing hook at an
  endpoint that returns `{"query": null}`. A chat message must fail with the
  rejection text. Stop the endpoint: HARD blocks the message, SOFT lets it run.
