# Federated Search

> Searching a source live, at query time, instead of indexing it. No connector run,
> no chunks in the index. Results are fetched from the source's own API during a
> search call and merged into the same ranked set as indexed documents.

**Domain:** search
**Edition:** CE
**Owns:**
`backend/onyx/federated_connectors/` (`interfaces.py`, `registry.py`, `factory.py`,
`models.py`, `federated_retrieval.py`, `oauth_utils.py`, `slack/federated_connector.py`,
`slack/models.py`), `backend/onyx/context/search/federated/slack_search.py`,
`slack_search_utils.py`, `models.py`, `backend/onyx/db/federated.py`,
`backend/onyx/server/federated/api.py`, `models.py`,
`web/src/app/admin/federated/[id]/`, `web/src/components/admin/federated/`

**Does not own:** the parallel-lane fan-out, rank fusion, or LLM selection that
merges federated results with indexed ones ([[internal-search]] owns
`SearchTool.run` and `search_pipeline`), or how a source's permissions are synced
into Onyx ahead of time ([[access-control]] and [[permission-sync]] own the
indexed-side ACL, which this component deliberately bypasses).

---

## 1. What the user experiences

For most connected sources, the user gets results from documents Onyx already
crawled and indexed. Slack is different: Onyx does not index Slack messages at
all. When the user asks a question, if they have connected their own Slack
account (or the Slack bot's tenant-wide token is usable), Onyx searches Slack
live, over the Slack API, and folds the results into the same document cards and
numbered citations as everything else. The user cannot tell, from the answer,
which documents came from the index and which came from a live Slack call.

If the user has never connected Slack, or their token has expired, the search
simply runs without a Slack lane. Nothing errors and nothing tells the user
Slack was skipped, unless a source-scoped filter note mentions Slack explicitly.

An admin connects Slack for the whole workspace once (app credentials), after
which each individual user separately authorizes their own Slack account (or
the tenant's Slack bot, if one is already installed with a usable token, covers
everyone without per-user connection).

---

## 2. Surfaces

### HTTP endpoints (router prefix `/federated`, `server/federated/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/federated` | `create_federated_connector` | Admin only (`MANAGE_CONNECTORS`). Creates the workspace-level connector row (app credentials + entity config). |
| GET | `/federated` | `get_federated_connectors` | `BASIC_ACCESS`. Status table: every configured connector, by source. |
| GET | `/federated/{id}` | `get_federated_connector_detail` | Connector detail for the admin edit form. |
| PUT | `/federated/{id}` | `update_federated_connector_endpoint` | Admin only. Updates credentials or entity config. |
| DELETE | `/federated/{id}` | `delete_federated_connector_endpoint` | Admin only. |
| GET | `/federated/{id}/entities`, `/federated/sources/{source}/configuration/schema` | `get_entities`, `get_configuration_schema_by_source` | Entity/config field specs for the setup form. |
| GET | `/federated/{id}/credentials/schema`, `/federated/sources/{source}/credentials/schema` | | Credential field specs. |
| POST | `/federated/sources/{source}/credentials/validate` | `validate_credentials` | Admin only; instantiates the connector to check credentials. |
| GET | `/federated/{id}/authorize` | `get_authorize_url` | **Any authenticated user** (`BASIC_ACCESS`). Returns the per-user OAuth URL. |
| POST | `/federated/callback` | `handle_oauth_callback_generic` | Any authenticated user. State-verified OAuth callback; stores the per-user token. Returns only `source`, `expires_at`, `token_type`, `scope`, never a token. |
| GET | `/federated/oauth-status` | `get_user_oauth_status` | Any authenticated user. Per-connector: does *this* user have a token, and if not, an authorize URL. Polled by `AccountPopover.tsx` in the account menu. |
| DELETE | `/federated/{id}/oauth-token` | `disconnect_oauth_token` | Any authenticated user. Disconnects their own token. |

Per-user Slack connection is reached from the account popover
(`web/src/sections/sidebar/AccountPopover.tsx`), not from an admin page. The
workspace-level connector (app credentials, entity config, document-set link) is
configured from `web/src/app/admin/federated/[id]/page.tsx`, reached only by
cross-link, not a sidebar entry: `web/src/app/admin/add-connector/page.tsx` routes
there after creating a federated connector,
`web/src/app/admin/documents/sets/page.tsx` links to it from a document set's
linked federated connector, and `CCPairIndexingStatusTable.tsx` links to it
alongside regular cc-pairs. `web/src/lib/admin-routes.ts` lists `/admin/federated`
only inside `VECTOR_DB_REQUIRED_ROUTE_PREFIXES` (line 541,
`web/src/lib/admin-routes.ts`), not as a registered `ADMIN_ROUTES` entry: there is
no admin sidebar item and no `/admin/federated` index page, only the `[id]`
detail page reached by the links above.

### The registry (no HTTP surface, called in-process)

`get_federated_retrieval_functions` (`backend/onyx/federated_connectors/federated_retrieval.py:get_federated_retrieval_functions`)
is the generic entry point any retrieval code calls to get zero or more live
search functions for the current request.

---

## 3. Data model

`backend/onyx/db/models.py`:

- `FederatedConnector` (`FederatedConnector`): one row per workspace-level
  connector. `source` (`FederatedConnectorSource`), `credentials`
  (`EncryptedJson`, app-level OAuth client id/secret), `config`
  (`JSONB`, connector-level entity filters, for example Slack channel scope).
- `FederatedConnectorOAuthToken`: one row per `(federated_connector_id, user_id)`.
  `token` (`EncryptedString`), `expires_at`. **No `refresh_token` column exists.**
  The Slack callback (`onyx/federated_connectors/slack/federated_connector.py:callback`)
  receives a `refresh_token` from Slack and puts it on `OAuthResult.refresh_token`,
  but `update_federated_connector_oauth_token` (`onyx/db/federated.py:update_federated_connector_oauth_token`)
  only accepts and stores `token` and `expires_at`. The refresh token is discarded.
- `FederatedConnector__DocumentSet`: many-to-many join, with a per-mapping
  `entities` JSON column that is a **legacy, unused field** for Slack; Slack now
  reads entity config from `FederatedConnector.config` (the connector-level
  column), not from this junction table (`federated_retrieval.py:get_federated_retrieval_functions`,
  the comment "Use connector-level config (no junction table entities)").

This component owns none of the document-set or cc-pair tables it reads;
[[cc-pairs-and-credentials]] and the document-set tables in [[access-control]]
own those.

---

## 4. How it works

### 4.1 Two mechanisms, one always empty in practice today

```
                          ┌─────────────────────────────────────────┐
                          │        get_federated_retrieval_functions │
                          │        federated_connectors/             │
                          │        federated_retrieval.py             │
                          └───────────────┬───────────────────────────┘
                                          │
        called from TWO sites:           │
                                          │
 (A) SearchTool.run(), search_tool.py:838 │  (B) search_chunks, search_runner.py:111
     always slack_context=None            │      only when NOT pre-fetched by (A)
     prefetches once per run(), passes    │      (only the EE Search UI path,
     result into every non-Slack lane     │      ee/onyx/search/process_search_query.py,
     via prefetched_federated_retrieval_  │      calls search_pipeline with no
     infos (search_tool.py:587)           │      prefetched_federated_retrieval_infos)
                                          │      also always slack_context=None
                                          ▼
                   Inside get_federated_retrieval_functions:
                   - slack_context branch: UNREACHABLE. No call site in the
                     repo ever passes slack_context (grep confirms it).
                   - user_id branch: explicitly SKIPS any oauth_token whose
                     source == FEDERATED_SLACK ("Slack is handled separately
                     inside SearchTool", federated_retrieval.py).
                   - FederatedConnectorSource has exactly one member
                     (FEDERATED_SLACK, configs/constants.py:318), and it is
                     always skipped here.
                   => get_federated_retrieval_functions returns [] on every
                      call site that exists in the codebase today.

                          ┌─────────────────────────────────────────┐
                          │   SearchTool._run_slack_search            │
                          │   search_tool.py:493, added as its own    │
                          │   parallel lane at search_tool.py:1108    │
                          │   (slack_lane_ran gate)                   │
                          └───────────────┬───────────────────────────┘
                                          │
                       Only path that ever actually returns Slack results.
                       Token pre-fetched once in run() by
                       _prefetch_slack_data (search_tool.py:355), before the
                       parallel lanes start.
```

**This answers the central question.** The two mechanisms cannot both fetch
Slack in one search, but not because of a deliberate cross-check gate between
them: it is because `get_federated_retrieval_functions` hard-codes a skip for
`FEDERATED_SLACK` in its non-bot branch (`federated_retrieval.py:
"Skipping Slack federated connector in user OAuth path - handled by SearchTool"`),
and its bot-context branch (the one place it *would* return a Slack retrieval
function) is dead code: no call site anywhere in `backend/` passes
`slack_context`, verified by `grep -rn "get_federated_retrieval_functions(" backend/onyx`
showing only the two call sites above, neither with that argument. So today, for
the only source that exists, the registry path always contributes `[]` and
`_run_slack_search` is the sole Slack lane. This is closer to "no gate needed
because one branch is unreachable" than "a gate that actively prevents
duplication". If a future change starts passing `slack_context` into (A) or (B),
or a second federated source is added whose oauth token is not explicitly
skipped, the two mechanisms would both fire with no cross-check between them,
and [[internal-search]]'s `combine_retrieval_results`
(`context/search/retrieval/search_runner.py:combine_retrieval_results`) would
only absorb a true double-fetch if both fetches assign the **same**
`(document_id, chunk_id)` to the same message; Slack's `document_id` is derived
per-message inside `slack_search.py`, not from a stable index-side ID, so two
independently-run Slack fetches are not guaranteed to collide on
`(document_id, chunk_id)` and would more likely appear as duplicate-content
sections rather than be deduplicated. See §9.

### 4.2 Per-user token resolution

`SearchTool._prefetch_slack_data` (`search_tool.py:355`) runs once inside the
single DB session opened at the top of `run()`, before any parallel lane starts:

1. **Bot context** (`self.slack_context` set, i.e. `SearchTool` was constructed
   for a Slack bot turn): requires the persona's document sets to include one
   linked to a `FEDERATED_SLACK` connector (§4.3). If found, picks a Slack bot
   row (`db/slack_bot.py:fetch_slack_bots`) that is `enabled`, preferring one
   with a `user_token` over one with only a `bot_token`. `access_token =
   user_token or bot_token`.
2. **Web user** (no bot token found, `self.user` set): looks up
   `list_federated_connector_oauth_tokens(db_session, self.user.id)`
   (`db/federated.py:list_federated_connector_oauth_tokens`) and takes the
   Slack row's `token`.
3. If neither yields a token, returns `(None, None, {})`. `_prefetch_slack_data`
   swallows every exception in each branch and logs a warning; it never raises.

The result feeds `slack_lane_ran = bool(slack_access_token and
override_kwargs.original_query)` (`search_tool.py:1108`), the sole gate on
whether `_run_slack_search` is added to the parallel lane list.

### 4.3 The document-set gate

Both the bot-context path (`_prefetch_slack_data`) and the registry's bot-context
branch (`federated_retrieval.py:get_federated_retrieval_functions`, unreachable
today per §4.1) apply the same rule: **Slack federated search requires a
`FEDERATED_SLACK` connector to be linked to one of the current persona's document
sets, via `FederatedConnector__DocumentSet`.**

`get_federated_connector_document_set_mappings_by_document_set_names`
(`db/federated.py:get_federated_connector_document_set_mappings_by_document_set_names`)
looks up that join by document-set name. If `self.persona_search_info.document_set_names`
is empty, or none of the mappings resolve to a `FEDERATED_SLACK` connector,
Slack federated search is skipped outright (`search_tool.py:375-403`), before any
token is even fetched. **A persona or chat session with no document sets, or with
document sets not linked to the Slack connector, never gets Slack results, even
if the bot token exists.** This gate applies only to the bot-context branch; the
web-user branch (§4.2 step 2) has no document-set check at all, it fires
whenever the user has a Slack OAuth token, regardless of which document sets are
in scope for that search.

### 4.4 Merging into the ranked set

`_run_slack_search` (`search_tool.py:493`) builds a `ChunkIndexRequest` with
`IndexFilters(access_control_list=None)` (see §5) and calls `slack_retrieval`
(`context/search/federated/slack_search.py:slack_retrieval`), which:

1. Builds Slack search queries with entity filtering (channel include/exclude,
   `search_all_channels`, `include_dm`, `include_group_dm`,
   `include_private_channels`, `default_search_days`) from the connector's
   `config` (`federated_connectors/slack/federated_connector.py:entities_schema`).
2. Calls the Slack API (`query_slack`, `slack_search.py:535`), fetches thread
   context, and scores messages.
3. Converts matched messages into `IndexingDocument`/`TextSection`
   (`connectors/models.py`), the **same shape connector indexing uses**.
4. Runs them through `Chunker` (`indexing/chunker.py`) and
   `DefaultIndexingEmbedder` (`indexing/embedder.py`), the same chunker used by
   the indexing pipeline, so Slack messages are chunked identically to indexed
   documents even though nothing is written to the index.
5. Builds `InferenceChunk` objects (`slack_search.py:1331`) with
   `source_type=DocumentSource.SLACK`, a synthetic per-message `document_id`, and
   `is_federated=True`.

Because the result is a plain `list[InferenceChunk]`, it merges into
`weighted_reciprocal_rank_fusion` and `merge_individual_chunks` exactly like any
indexed lane (see [[internal-search]] §4.4), gets the same LLM-selection and
context-expansion treatment, and receives a citation number the same way. See
[[citations]] for how `convert_inference_sections_to_llm_string` assigns that
number; nothing about it is federated-specific.

Non-Slack federated results (from `get_federated_retrieval_functions`, when a
future source makes it non-empty) merge the same way, but arrive through
`search_chunks`'s `run_functions_tuples_in_parallel` call
(`context/search/retrieval/search_runner.py:search_chunks`) rather than as a
`SearchTool`-level lane; both eventually feed the same
`combine_retrieval_results` / `weighted_reciprocal_rank_fusion` stage.

---

## 5. Contracts and invariants

1. **A federated result must never exceed what the user's own token can see.**
   Verified for Slack: `_run_slack_search` builds `IndexFilters(access_control_list=None)`
   (`search_tool.py:518`), and access is enforced entirely by what the Slack API
   returns for the given `access_token`, which is scoped by Slack's own OAuth
   consent (the `SCOPES` list in `federated_connector.py`, all `*.read`/`*.history`
   scopes, none admin-level). **I cannot independently verify, from this
   codebase, that Slack's API genuinely restricts results to channels the token
   owner can see** since that guarantee lives inside Slack's API, not Onyx code.
   Onyx trusts the token's scope entirely; it applies no additional filtering.
2. **A missing or expired token must degrade to no results, not an error that
   kills the turn.** `_prefetch_slack_data` and `_run_slack_search` both wrap
   their bodies in `try/except`, logging and returning empty/`None` rather than
   raising (`search_tool.py:355`, `search_tool.py:537`). There is no explicit
   `expires_at` check before use; an expired token is discovered only when the
   Slack API call itself fails, which the `except` in `_run_slack_search`
   catches.
3. **Federated results must merge into the same ranked set without breaking
   citation numbering.** Slack chunks flow through the identical
   `InferenceChunk` → `weighted_reciprocal_rank_fusion` → `merge_individual_chunks`
   → citation-numbering path as indexed chunks (§4.4). Do not special-case Slack
   chunks downstream of `_run_slack_search`; anything that does breaks this
   invariant.
4. **The document-set gate for the bot-context Slack path must hold.**
   `_prefetch_slack_data` must return `(None, None, {})` whenever the persona's
   document sets are empty or unlinked to a `FEDERATED_SLACK` connector
   (`search_tool.py:373-403`). A change that fetches a Slack token before this
   check would let Slack federated search fire outside its intended scope.
5. **The web-user OAuth path has no document-set gate**, unlike the bot-context
   path. Do not assume symmetry between the two branches of
   `_prefetch_slack_data`; a change to one does not automatically apply to the
   other.
6. **`get_federated_retrieval_functions`'s skip of `FEDERATED_SLACK` in the
   user-OAuth branch must stay in sync with `SearchTool`'s Slack handling.** If
   `SearchTool` ever stops being the sole Slack caller, or the registry starts
   being called with `slack_context` set, re-verify this document's §4.1
   analysis: it currently holds only because of the specific call-site
   arguments observed in the code, not because of an explicit mutual-exclusion
   check between the two mechanisms.
7. **Refresh tokens are captured but never persisted or used.** Do not assume a
   background job refreshes federated tokens; there is none. An expired token
   requires the user to reauthorize through `/federated/{id}/authorize`.
   Only a Slack app with token rotation turned on (off by default) sends a
   refresh token and 12-hour expiry, so only those apps hit this.
8. **The OAuth callback never returns a token to the browser.** The provider's
   access and refresh tokens are stored encrypted and stay server side;
   `OAuthCallbackResult` has no token fields, and the web callback page reads
   only `source`. Do not add a token field to the response model.

---

## 6. Relationships

**Depends on**
- [[document-index]]: not used for Slack results at all; this is the point of
  the component. Indexed sources still go through `document_index.hybrid_retrieval`/
  `keyword_retrieval` in the same search call.
- [[connectors]] / [[cc-pairs-and-credentials]]: `FederatedConnectorSource`
  (`configs/constants.py:318`) and `to_non_federated_source()` map a federated
  source to the `DocumentSource` enum connectors also use, so scope filters
  (`source_type`) apply uniformly across indexed and federated sources.
- [[auth-and-identity]]: per-user OAuth tokens are keyed to `User.id`; the
  callback endpoint verifies the authenticated user matches the OAuth session
  (`server/federated/api.py:handle_oauth_callback_generic`).
- [[slack-bot]]: supplies `SlackContext` and the tenant Slack bot row
  (`db/slack_bot.py:fetch_slack_bots`) that the bot-context branch of
  `_prefetch_slack_data` reads.
- [[citations]]: the merged Slack chunks are cited the same way as indexed
  chunks; see §4.4.

**Depended on by**
- [[internal-search]]: `SearchTool.run` is the only caller that actually
  produces Slack federated results; `search_chunks` calls the generic registry
  as a secondary, currently-inert path. See [[internal-search]] §4.3 and §5.8,
  which this document's §4.1 corrects/extends: internal-search.md correctly
  states the Slack lane carries no ACL and is handled inside `SearchTool` rather
  than through the registry, but it does not state that the registry path is
  empty in practice for every call site that exists today; that fact belongs
  here.
- The onyx-cli/programmatic `/search` endpoint and the EE Search UI backend
  (`ee/onyx/search/process_search_query.py`) reuse `search_pipeline`, so they
  reach `get_federated_retrieval_functions` through call site (B) in §4.1, but
  never reach `_run_slack_search` (that lane lives only inside `SearchTool`),
  so **neither of those surfaces ever returns Slack federated results.**

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a new federated source (a second `FederatedConnectorSource` member) | implement every abstract method in `interfaces.py:FederatedConnector`; add it to `FEDERATED_CONNECTOR_CLASS_MAP` (`registry.py`); decide whether it needs a `SearchTool`-level dedicated lane like Slack or can rely purely on the registry path; if the latter, this is the first source that actually exercises `get_federated_retrieval_functions`'s user-OAuth branch in production, re-verify §4.1's dead-code claims still hold for the new source |
| changes the lane assembly in `search_tool.py` (`run`, `_run_slack_search`, `_prefetch_slack_data`) | re-walk §4.1's call-site argument analysis; a change that starts passing `slack_context` into `get_federated_retrieval_functions`, or stops the explicit `FEDERATED_SLACK` skip, opens the double-fetch path this document currently rules out |
| changes token handling (`oauth_utils.py`, `db/federated.py`, `_prefetch_slack_data`) | the "no results on missing/expired token" contract (§5.2); the document-set gate (§5.4); whether refresh tokens are still silently discarded (§5.7) |
| changes the document-set gate (`get_federated_connector_document_set_mappings_by_document_set_names`, `_prefetch_slack_data`'s document_set_names check) | both branches independently reimplement a version of this gate (bot-context in `search_tool.py`, bot-context in `federated_retrieval.py`); keep them in sync or delete the duplication |
| changes `slack_search.py`'s chunk construction | [[citations]], since the citation pipeline assumes uniform `InferenceChunk` shape; also the entity-filter schema in `federated_connector.py:entities_schema`, which the admin form and this pipeline must agree on |
| changes `FederatedConnectorOAuthToken` or adds a `refresh_token` column | a migration, plus wiring an actual refresh call somewhere; none exists today |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/integration -k federated
cd backend && uv run pytest tests/unit -k "federated or slack_search"
```

`backend/tests/external_dependency_unit` has no dedicated federated-connector
suite as of this writing; check for one before assuming the above two commands
are exhaustive. See `backend/AGENTS.md` for authoritative commands and required
env (a real Slack app's `client_id`/`client_secret` is a `TestSecret` resolved
per `backend/tests/utils/aws_secrets.py`, needed for any test that exercises the
OAuth exchange for real).

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Sign in as `admin_user@example.com` / `TestPassword123!` at `http://localhost:3000`.
3. As admin, add a Slack federated connector: `/admin/add-connector` → select
   Slack (federated), enter a Slack app's client id/secret. Confirm it redirects
   to `/admin/federated/{id}`.
4. Link the connector to a document set the test persona uses
   (`/admin/documents/sets`), since document-set linkage gates whether the bot
   path (and, if extended, non-bot paths reusing that check) will ever fire.
5. As a regular user, open the account popover and connect Slack (this hits
   `/federated/{id}/authorize` then `/federated/callback`). Confirm
   `/federated/oauth-status` now reports `has_oauth_token=true` for that user.
6. Ask a chat question whose answer lives only in Slack messages, with a
   persona scoped to the linked document set. Confirm a citation resolves to a
   Slack message link, not an indexed document.
7. Disconnect the Slack OAuth token (`DELETE /federated/{id}/oauth-token`) and
   repeat step 6. Confirm the turn completes normally with no Slack citations
   and no error surfaced to the user.

Drive the browser with `claude-in-chrome` against the user's real Chrome rather
than launching Playwright ad hoc.

### What "working" looks like

- A Slack federated citation opens the real Slack message/thread.
- Disconnecting Slack degrades to "no Slack results", never a turn-ending error.
- A persona whose document sets are not linked to the Slack connector never
  produces Slack citations, even for a user who has connected Slack personally.

---

## 9. Footguns

- **The framework is generic; the product is Slack-only.** `FederatedConnectorSource`
  (`configs/constants.py:318`) has exactly one member. Every abstraction in
  `federated_connectors/` (`interfaces.py`, `registry.py`, `factory.py`) is built
  for N sources, but only Slack has ever been implemented. Reading the registry
  code in isolation overstates how general the actual behavior is.
- **The registry path returns `[]` for every call site that exists today.**
  `get_federated_retrieval_functions`'s only branch that can return a non-empty
  list for Slack (the `slack_context` bot branch) is never reached by any caller
  in the repo; its other branch explicitly skips Slack. So despite looking like
  "the" federated retrieval mechanism, it currently contributes nothing to any
  search. `_run_slack_search` inside `SearchTool` is the entire Slack federated
  search feature today. See §4.1.
- **Two call sites of the same function do not mean two independent fetches.**
  `search_tool.py:838` prefetches once and threads the (always-empty, for
  Slack) result through every lane; `search_runner.py:111` only calls the
  registry itself when nothing was prefetched, which happens only outside
  `SearchTool` (the EE Search UI path). Reading only "there are two call sites"
  without checking `prefetched_federated_retrieval_infos` leads to a wrong
  conclusion about duplication.
- **Refresh tokens are silently dropped.** The Slack OAuth callback extracts a
  `refresh_token` from Slack's response and puts it on `OAuthResult`, but the DB
  layer never stores it and nothing ever calls a refresh endpoint. A user's
  Slack connection lapses permanently at `expires_at` and must be manually
  reconnected; there is no silent renewal to break.
- **The bot-context and web-user branches of `_prefetch_slack_data` are not
  symmetric.** Only the bot-context branch checks the document-set link before
  fetching a token; the web-user branch does not. A reviewer assuming both
  branches enforce the same gate will miss that a personally-connected user's
  Slack results are scoped only by their token, not by the persona's document
  sets, for that branch.
- **The entities junction table (`FederatedConnector__DocumentSet.entities`) is
  effectively dead for Slack.** Entity config (channel filters, DM inclusion) is
  read from `FederatedConnector.config`, the connector-level column, not the
  per-mapping column, despite the schema still having both.
