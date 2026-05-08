# Onyx Search Tool for Craft

> Related: [search-design.md](search-design.md)

## Objective

Replace the legacy `files/` corpus sync with a first-party HTTP search tool that the Craft sandbox can call. The tool must mirror the regular Onyx app's search behavior — same hybrid pipeline, same permission model, same citation shape — but run inside the sandbox boundary and produce results that are safe to feed to the agent. This is the foundation that lets us delete the per-session corpus dump (which never scaled, never matched permissions, and was a constant source of drift between Onyx data and what the agent could see).

## Issues to Address

1. **No permissioned retrieval.** Today the sandbox reads JSON files written to `/workspace/files/` via S3 init container. The contents reflect whichever connector files were dumped at session creation — not the running user's ACL.
2. **No corpus freshness.** Files are a snapshot. New data ingested after the sandbox starts is invisible to the agent.
3. **Corpus dump is huge and slow.** Every session pays the cost of materializing connector JSON, even when the agent only needs three documents.
4. **The agent has the wrong primitive.** It's told to `find` and `grep` company knowledge as flat files, which forces full-document reads, blows context windows, and makes citation back to the source ad-hoc.
5. **Two retrieval stories.** Onyx chat uses the real hybrid search pipeline (Vespa, ACLs, reranking, federated). Craft uses a directory listing. Anything we improve in one doesn't help the other.

V1 collapses these into one retrieval path: the Craft sandbox calls `company_search`, which executes the same `search_pipeline(...)` the chat tool uses, scoped to the calling session's user.

## Important Notes

- **Single retrieval implementation.** Do not fork the search pipeline. Call `backend/onyx/context/search/pipeline.py:269 search_pipeline(...)` directly. Anything we add (caching, formatters) wraps it; nothing reimplements it.
- **The sandbox never receives raw user credentials.** It gets a session-scoped Craft token, generated at session creation, passed in via env var. The backend resolves token → `BuildSession` → `User` → tenant, then runs search as that user.
- **Tenant context must be set on the request handler before calling search.** The pipeline reads `get_current_tenant_id()` to pin Vespa filters; if we forget to set it, queries either fail or leak across tenants.
- **No persona.** Craft search runs without a persona today — pass `PersonaSearchInfo(document_set_names=[], ...)` (empty). Persona-scoped Craft search is a later enhancement (Skills system already plans to give skills "search profiles").
- **No streaming.** The sandbox calls a synchronous JSON endpoint. Streaming partial results into OpenCode would mean reimplementing the SSE plumbing the chat tool uses; not worth it for V1.
- **Behavioral parity with the regular Onyx search tool is the bar.** Same hybrid retrieval, same ACL path, same query expansion, same LLM-driven document selection and context expansion. The endpoint instantiates `SearchTool` and calls `.run()` exactly like the chat path does — we are not reimplementing or simplifying the retrieval logic. If chat search gets better, Craft search gets better for free.
- **The LLM used inside `SearchTool` (for query expansion / doc selection) is the session's configured LLM.** `BuildSession` already stores `llm_provider_type` and `llm_model_name`; resolve these to a live `LLM` instance the same way the messages API does today, and pass it into `SearchTool`. This keeps the cost path predictable (the user already chose this model for the session) and avoids a separate "search LLM" config.
- **Federated sources (Slack, etc.) work automatically** because `SearchTool.run()` already builds the prefetched federated retrieval info inline. We pay the same per-request setup cost the chat path pays, which is fine.
- **OpenCode tool surface.** OpenCode does not have a native "HTTP tool" primitive. We expose the search tool as a **skill** (a small CLI script bundled into `.opencode/skills/company-search/`) that the agent invokes by name. The script is just `curl` with the session token. This keeps the OpenCode integration small and lets the future Skills system own distribution.
- **Skill name is `company_search`.** Reads naturally to the agent ("search the company's knowledge") and stays neutral about the underlying retrieval system. The brand "Onyx" lives in env var names (`ONYX_BUILD_SESSION_TOKEN`, `ONYX_BACKEND_URL`) where it's identifying the product boundary, not in user-facing tool names.
- **Available sources are described to the agent at session setup.** The skill's `SKILL.md` is templated like `AGENTS.md` — at sandbox setup the backend queries the user's accessible connectors and renders the list (e.g. "Google Drive — internal docs, Slack — #eng / #sales / ..., Linear — eng tickets") into the skill doc. The list is fixed for the duration of the session; we don't refresh it mid-session.
- **Return format is a single markdown blob to stdout.** The skill prints the formatted text the LLM sees and exits. We do not write a parallel JSON file to disk in V1 — the agent reads markdown, not JSON, and there is no other consumer in the sandbox today. Stable IDs (`document_id`, `chunk_ind`) are inlined into the markdown so they're still recoverable if a future tool needs them. The endpoint itself returns both `llm_facing_text` and the structured `results`/`citation_mapping` (matching the chat tool's `rich_response`/`llm_facing_response` split) — the structured part is for server-side audit and any future non-skill consumer.
- **Backwards compatibility is not a goal.** Existing Craft sessions, sandboxes, and `files/` content can be deleted as part of this change. See the main plan: V1 has no migration story.

---

> **Note (2026-05-08):** Everything below this line is from the first iteration of the search tool design. It is kept for documentation purposes only. The current design — including the chosen approach (onyx-cli), rationale, and implementation plan — lives in [`search-design.md`](search-design.md).

---

## Approaches Considered

### A. HTTP tool wired directly into OpenCode (rejected)
Add `company_search` as a first-class OpenCode tool by patching the OpenCode binary or its tool registry. Tightest UX (the agent gets a typed tool call rather than a shell command).

**Why rejected:** OpenCode is upstream code we explicitly want to keep replaceable (see craft-main-plan.md notes — "Use OpenCode for V1. Leave a clean runtime boundary so a homebuilt agent runner can replace it later"). Forking the binary or maintaining a patch set blocks that. OpenCode's skill system is the documented extension point and gives us the same UX with no fork.

### B. MCP server inside the sandbox (rejected)
Spin up a small MCP server in the sandbox that exposes `company_search` and let OpenCode discover it.

**Why rejected:** Main plan explicitly defers MCP support. Adds a process to babysit, an authentication layer, and a discovery handshake — all to wrap one call. Skill is simpler.

### C. Mount Vespa results as files in `files/results/` per query (rejected)
Keep the file-based primitive; backend writes search results to a directory the agent watches.

**Why rejected:** Latency is bad (round-trip via filesystem watcher), makes the agent's request shape implicit, doesn't compose with concurrent searches. And we'd still need an HTTP path to *trigger* the search, so we'd be building both.

### D. Skill that calls a new authenticated HTTP endpoint (winner)
Bundle a `company-search` skill into the sandbox image. Skill is a thin script that POSTs to `/api/build/sandbox/search` with the session token and prints LLM-facing markdown to stdout. Stateless — no files written to disk.

**Why this wins:**
- Reuses the existing skill machinery (already materialized into `.opencode/skills` at session setup, already documented in `AGENTS.md` via `{{AVAILABLE_SKILLS_SECTION}}`).
- No OpenCode fork. Swappable to a homebuilt runner later — the skill is just `curl`.
- One new endpoint, no new server. Token auth is cheap and tracked on the existing `BuildSession` row.
- Symmetric with the future Skills System project (project #3 in the main plan): `company-search` is the first built-in skill, seeded by the same path that will seed presentation/document/dashboard skills.

## Key Design Decisions

1. **Skill, not tool, not MCP.** The agent calls `company_search "query"` as a skill. Implementation is `curl` to a backend endpoint. No upstream OpenCode changes.
2. **Session-scoped bearer token, generated at session creation.** Stored on `BuildSession.sandbox_token` (random 32 bytes, base64url). Injected into the sandbox via `ONYX_BUILD_SESSION_TOKEN` env var. Rotated on session restart. Never logged, never written to artifacts.
3. **Endpoint lives under the existing `/api/build` router**, but in a new sub-router with a custom auth dependency that validates the session token instead of the user cookie. The user cookie auth path is preserved for the rest of `/api/build`.
4. **Instantiate `SearchTool` and call `.run()` — don't reach into `search_pipeline` directly.** `SearchTool` is what gives us query expansion, LLM doc selection, and context expansion in addition to retrieval. Reaching one layer below would require us to reimplement those passes, which is exactly the divergence we're trying to avoid. The endpoint constructs `SearchTool` with the session's user, an empty `PersonaSearchInfo`, the session's LLM, and the document index — same shape `tool_constructor.py` uses for chat — then calls `.run(queries=[query])` and returns its `rich_response` and `llm_facing_response`.
5. **Query expansion and LLM doc selection happen automatically in the endpoint, exactly like chat.** This is behavioral parity with the regular Onyx search tool — the agent gets the same quality of retrieval that a user gets in chat. Yes, this means an LLM pass per `company_search` call (the session's configured LLM, not a separate one). That's the right tradeoff: search quality is what makes the agent useful, and we'd rather pay the LLM cost once at the search step than have the agent fan out into 5 lower-quality searches to compensate.
6. **Citation IDs are inlined into the markdown, not written to a side file.** Each citation footer in the rendered markdown carries the stable `document_id` (and `chunk_ind` where useful), so the agent — or any future `company_fetch_document` skill — can recover them by reading stdout. No `outputs/.company-search/` directory, no JSON written to disk; the skill is stateless.
7. **Rate limit per session.** Reuse the existing `backend/onyx/server/features/build/api/rate_limit.py` pattern, scoped per `build_session_id` not per user. Default to 60 searches per session per hour; tune on data.
8. **Failures are skill-script exit codes.** Skill prints a one-line error to stderr and exits non-zero on auth failure / quota / backend error. Agent treats this as a tool failure and can retry or pivot. No cascading 500s into the chat stream.
9. **Skill replaces — does not supplement — `find`/`grep` over `files/`.** The corpus directory is removed entirely (see "Files to Remove" below). `AGENTS.template.md` is rewritten so the only documented path to company knowledge is `company_search`. User-uploaded session files (under `attachments/`) stay accessible via normal file reads — those are explicit session input, not the corpus.
10. **Available sources are rendered into `SKILL.md` per session, not hard-coded.** Backend queries the user's accessible connector_credential_pairs at session setup (same path the existing `/api/build/connectors` endpoint uses) and writes a templated source list into the materialized SKILL.md. The list is rebuilt at the start of every new session and not refreshed mid-session — connectors added or removed during a session aren't reflected until the user starts a new one.

## Architecture

```
┌─────────────────── Sandbox (k8s pod / docker container) ───────────────────┐
│                                                                            │
│  OpenCode agent                                                            │
│    │                                                                       │
│    │ runs skill: company_search "what's in flight on auth?"                │
│    ▼                                                                       │
│  .opencode/skills/company-search/run.sh                                    │
│    │                                                                       │
│    │ curl -H "Authorization: Bearer $ONYX_BUILD_SESSION_TOKEN"             │
│    │      $ONYX_BACKEND_URL/api/build/sandbox/search                       │
│    │      -d '{"query":"...","limit":10}'                                  │
│    │                                                                       │
│    │ prints LLM-facing markdown (with inlined doc IDs) to stdout           │
└─ ─ ┼─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘
     │
     ▼
┌─────────────────────── Onyx backend (api_server) ──────────────────────────┐
│                                                                            │
│  POST /api/build/sandbox/search                                            │
│    │                                                                       │
│    ├─ require_sandbox_session_token() dependency                           │
│    │     1. Look up BuildSession by sandbox_token (constant-time compare)  │
│    │     2. Set CURRENT_TENANT_ID from session.user.tenant                 │
│    │     3. Return (BuildSession, User)                                    │
│    │                                                                       │
│    ├─ rate_limit_check(session_id)                                         │
│    │                                                                       │
│    ├─ resolve session LLM from BuildSession.llm_provider_type/model_name   │
│    │                                                                       │
│    ├─ SearchTool(                                                          │
│    │     user=session.user,                                                │
│    │     persona_search_info=PersonaSearchInfo(empty),                     │
│    │     llm=session_llm,                                                  │
│    │     document_index=get_default_document_index(),                      │
│    │     ...                                                               │
│    │  ).run(queries=[query], override_kwargs=...)                          │
│    │     │                                                                 │
│    │     └─ internally: query expansion, hybrid retrieval, LLM doc         │
│    │        selection, context expansion — same as chat                    │
│    │                                                                       │
│    ├─ return rich_response (SearchDocs + citation_mapping) +               │
│    │   llm_facing_response (markdown w/ citations)                         │
│    │                                                                       │
│    └─ audit log: {session_id, user_id, query, n_results, latency}          │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

## Relevant Files / Onyx Subsystems

**Search tool (instantiate and call directly — this is the integration point):**
- `backend/onyx/tools/tool_implementations/search/search_tool.py` — `SearchTool`; `.run(queries=...)` returns `ToolResponse(rich_response=SearchDocsResponse, llm_facing_response=str)`. This is what we wrap.
- `backend/onyx/chat/tool_handling/tool_constructor.py` — reference call site for how chat instantiates `SearchTool` (PersonaSearchInfo, llm, document_index, user_selected_filters, etc.). Mirror its construction shape, drop persona-specific bits.
- `backend/onyx/context/search/pipeline.py:269` — `search_pipeline()`; called transitively by `SearchTool`. We do **not** call it directly.
- `backend/onyx/context/search/models.py:343` — `SearchDocsResponse`, `SearchDoc` (response shape we serialize).
- `backend/onyx/context/search/preprocessing/access_filters.py:8` — `build_access_filters_for_user()` (called transitively).
- `backend/onyx/access/access.py:111` — user ACL resolution (called transitively).
- `backend/onyx/document_index/factory.py` — `get_default_document_index()`.
- `backend/onyx/llm/factory.py` — to construct an `LLM` instance from the session's `llm_provider_type` / `llm_model_name`. Look at how `messages_api.py` resolves the per-session LLM today and reuse the same path.

**Craft / Build module (modify):**
- `backend/onyx/server/features/build/api/api.py` — add a sub-router for sandbox-callable endpoints
- `backend/onyx/server/features/build/api/sandbox_search.py` — **new**: the endpoint
- `backend/onyx/server/features/build/api/sandbox_auth.py` — **new**: token-based auth dependency
- `backend/onyx/server/features/build/db/build_session.py` — extend session creation to mint a token
- `backend/onyx/server/features/build/sandbox/base.py:455` — remove `files/` S3 sync logic (`sync_files_from_s3`)
- `backend/onyx/server/features/build/sandbox/util/opencode_config.py:151` — drop the `/workspace/files` allow rules; keep `/workspace/demo_data` only if demo path is still in use (tracked separately, but out of scope here is to only delete what becomes dead code)
- `backend/onyx/server/features/build/sandbox/util/agent_instructions.py:345` — delete `build_knowledge_sources_section` and the `{{KNOWLEDGE_SOURCES_SECTION}}` placeholder substitution
- `backend/onyx/server/features/build/AGENTS.template.md` — rewrite the "Knowledge Sources" / "Information Retrieval" sections to point at the `company_search` skill
- `backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/company-search/` — **new** skill bundle: `SKILL.md.template` + `run.sh`
- `backend/onyx/server/features/build/sandbox/util/agent_instructions.py` — add `render_company_search_skill_md(user, db_session)` that materializes the per-session SKILL.md from the user's connector list (same source as `get_connector_credential_pairs_for_user` used in `api/api.py:91`)
- `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile` — copy the new skill into the image; remove file-sync init container references that only existed for the corpus

**Database:**
- `backend/onyx/db/models.py:4958` — `BuildSession`: add `sandbox_token` column
- `backend/alembic/versions/<new>.py` — migration

**Tenancy:**
- `backend/onyx/db/engine/sql_engine.py` (and `shared_configs/contextvars.py`) — `CURRENT_TENANT_ID` setting must be done by the auth dependency before opening the DB session used by `search_pipeline`.

## Data Model Changes

Add one column to `BuildSession`:

```python
# backend/onyx/db/models.py — BuildSession
sandbox_token: Mapped[str] = mapped_column(
    String, nullable=False, unique=True, index=True
)
```

- Generated as `secrets.token_urlsafe(32)` at session creation. **NOT NULL** — every session has a token, full stop. A null token would be a silent bug where a session was created without going through the proper path; the schema should reject that.
- Indexed and unique so token lookup is one query.
- Compared in constant time (`hmac.compare_digest`) in the auth dependency.
- Logged only as a fingerprint (first 6 chars + length) if at all.

The migration backfills a fresh token for every existing `build_session` row (one UPDATE generating `secrets.token_urlsafe(32)` per row), then sets the column to `NOT NULL`. Legacy rows keep their session/message/artifact history. Backfilled tokens won't help any already-running sandbox — those sandboxes don't have the token in their env — but legacy sandboxes get restarted on the deploy that ships this change anyway, and most legacy sessions are inactive. Preserving history is cheap; deleting it has no upside.

No new tables. Audit/observability for searches is project #8's job — for V1 we emit a structured log line per request and let it land in the existing audit log path.

## API Spec

**`POST /api/build/sandbox/search`**

Auth: `Authorization: Bearer <sandbox_token>` (no user cookie). Token resolves to a `BuildSession`; tenant is set from the session's user.

Request:
```json
{
  "query": "what is the sales process for enterprise deals?",
  "limit": 10,
  "source_filters": ["google_drive", "slack"],
  "time_cutoff_days": 90
}
```

Fields:
- `query` (string, required, ≤ 1024 chars).
- `limit` (int, optional, default 10, max 25). Mirrors `MAX_CHUNKS_FOR_RELEVANCE`.
- `source_filters` (list[str], optional). Maps to `DocumentSource` enum; unknown values rejected.
- `time_cutoff_days` (int, optional). Translated to `time_cutoff` on `IndexFilters`.

Response (200):
```json
{
  "results": [
    {
      "citation_id": 1,
      "document_id": "google_drive__abc123",
      "chunk_ind": 4,
      "title": "Enterprise Sales Playbook",
      "blurb": "...",
      "link": "https://docs.google.com/...",
      "source_type": "google_drive",
      "score": 0.78,
      "updated_at": "2026-03-12T00:00:00Z"
    }
  ],
  "llm_facing_text": "[1] Enterprise Sales Playbook (Google Drive, 2026-03-12)\n...",
  "citation_mapping": {"1": "google_drive__abc123"}
}
```

Errors (raise `OnyxError`, never `HTTPException`):
- `UNAUTHENTICATED` — missing/invalid bearer token.
- `RATE_LIMITED` — session over per-hour cap.
- `INVALID_REQUEST` — bad query, unknown source, oversized limit.
- `BAD_GATEWAY` — Vespa/document-index failure (with `status_code_override`).

The endpoint is **not** added to the existing `router = APIRouter(prefix="/build", dependencies=[Depends(require_onyx_craft_enabled)])` because the cookie-based dependency would reject the sandbox. Mount as a sibling router:

```python
sandbox_router = APIRouter(
    prefix="/build/sandbox",
    dependencies=[Depends(require_sandbox_session_token)],
)
```

## Skill Bundle

`backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/company-search/`

The bundle ships with `SKILL.md.template` (not `SKILL.md`). At session setup the backend renders the template into the materialized `.opencode/skills/company-search/SKILL.md`, substituting `{{AVAILABLE_SOURCES_SECTION}}` with the user's actual connector list. This is the same templating pattern that `AGENTS.template.md` already uses (`render_template_placeholders` in `agent_instructions.py`).

**`SKILL.md.template`** (read by the agent after rendering):
```
# company_search

Search the company's knowledge — restricted to what the current user has permission to see.

## Sources available in this session

{{AVAILABLE_SOURCES_SECTION}}

If a source you'd expect isn't listed, it isn't connected for this user — don't assume it.

## Usage

  company_search "<query>" [--limit N] [--source slack,google_drive]

## Output

Stdout is markdown with numbered citations like `[1]`, `[2]`, each followed by the title,
source, last-updated date, link, and stable document id. Cite results by their citation
number when you reference them in your response to the user.

Filter by source with `--source slack` or `--source slack,linear`. Source names match the
identifiers shown in the list above.
```

The static "documents, emails, Slack, tickets, meeting transcripts" phrasing that was in earlier drafts is gone on purpose. That phrasing both lies (the agent has whatever sources the user has connected — which may be none of those) and primes the agent to assume connectors exist that don't. The rendered `{{AVAILABLE_SOURCES_SECTION}}` is the single source of truth for what the agent should believe is reachable.

**Rendered `{{AVAILABLE_SOURCES_SECTION}}`** — example for a user with three connectors:
```
- google_drive — Internal docs, meeting notes, draft specs
- slack — Channels: #eng, #sales, #incidents, #product (+ DMs the user is in)
- linear — Engineering tickets across teams: backend, frontend, infra
- (user_uploads) — Files the user has attached to this session, under `attachments/`
```

The renderer source-of-truth is `get_connector_credential_pairs_for_user(user, db_session)` (already used by `backend/onyx/server/features/build/api/api.py:91 GET /api/build/connectors`). For each accessible CC pair, render `<source_id> — <one-line description>`. For sources with meaningful sub-scopes (Slack channels, Linear teams) include up to ~5 examples plus an ellipsis; this is hint-level data, not a complete inventory.

**`run.sh`** (~20 lines): `curl -fsS -H "Authorization: Bearer $ONYX_BUILD_SESSION_TOKEN" "$ONYX_BACKEND_URL/api/build/sandbox/search" -d "$(jq -n --arg q "$1" '{query:$q, limit:10}')"`, then `jq -r .llm_facing_text` to stdout. Non-zero exit + one-line stderr message on auth/quota/backend errors. No files written.

The skill is materialized into `.opencode/skills/company-search/` by the existing setup path (same way `pptx`, `image-generation`, `bio-builder` are today). It shows up automatically in `{{AVAILABLE_SKILLS_SECTION}}`.

## How the source list stays current

The list is rebuilt from scratch at the start of every new session, and only at the start of every new session. No mid-session refresh, no companion endpoint, no change-detection flag — the rendered `SKILL.md` is a snapshot and stays a snapshot until the user starts a new session.

The renderer never holds its own private map of connector facts (the trap the old `CONNECTOR_INFO` dict fell into). It composes from data Onyx already maintains:

- **Source ID + display name** — `DocumentSource` enum, same resolver `/api/build/connectors` already uses.
- **One-line "what's in it" description** — new `craft_description` field on the `DocumentSource` enum metadata. Connector authors fill it in as part of the normal landing checklist. A unit test asserts every `DocumentSource` member has a non-empty `craft_description` (or is on an explicit "intentionally undescribed" allow-set), so adding a connector without a one-liner fails CI — same forcing function we use today for display names. If one slips through, the renderer falls back to the display name alone, never a crash.
- **Sub-scope examples** (Slack channels, Linear teams) — pulled from the CC pair config / indexed group metadata that the connector subsystem already populates for the chat search path.

Richer admin-customizable per-source descriptions ("our 'sales' Slack workspace is for AE comms") are out of scope here — they belong in the control-plane work (project #7).

## AGENTS Template Changes

Rewrite `AGENTS.template.md`:

- Delete the entire "Knowledge Sources" section and the `{{KNOWLEDGE_SOURCES_SECTION}}` placeholder. The list of available sources now lives in the `company_search` skill's rendered SKILL.md, not in AGENTS.md.
- Replace the "Step 1: Information Retrieval" guidance to point at `company_search`. New text (sketched):
  > **Search** company knowledge using the `company_search` skill. This is your only path to company context — there is no `files/` directory. Run `company_search "<query>"` and read the returned markdown; cite results by their citation number when you reference them. The skill's SKILL.md lists which sources are available for this session. Iterate (run additional searches) until you have enough context.
- Keep the "Behavior Guidelines" / "Outputs" sections unchanged.
- Drop the "Files are JSON with: title, source, metadata, sections..." note — it's wrong now.
- `attachments/` (user-uploaded session files) remains documented and is still read with normal file ops.

## Files to Remove

As part of this work, delete:

- The `/workspace/files/` symlink wiring in `SandboxManager.setup_session_workspace()` and any S3 sync helpers (`sync_files_from_s3` in `sandbox/base.py:455`).
- `build_knowledge_sources_section` and `{{KNOWLEDGE_SOURCES_SECTION}}` substitution in `agent_instructions.py`.
- `CONNECTOR_INFO` dict (only used by the section builder).
- `external_directory` rules in `opencode_config.py` that whitelist `/workspace/files`.
- `AGENTS.template-chris.md`.
- The Kubernetes init container responsible for syncing the corpus from S3 into the pod (in `sandbox/kubernetes/kubernetes_sandbox_manager.py`).
- Any Celery task that enqueues files-sync work — at minimum verify there's no orphan task in `sandbox/tasks/tasks.py` after removing the call sites.

If `demo_data` mode survives this change without breaking, that's fine — it's covered separately by the control-plane work — but if removing the legacy `files/` plumbing also removes the only path that demo data currently uses, demo data goes too (main plan: "Remove the legacy files/ corpus directory and demo-data path as part of search/control-plane work").

## Tests

Lightweight is fine — search is changing fast and the heavy lifting is verified by Onyx's existing chat-search tests. Keep the new surface narrow.

**External dependency unit (one file, the bulk of the value):**
`backend/tests/external_dependency_unit/build/test_sandbox_search.py`
- Indexes a couple of test docs against the real Vespa, creates a `BuildSession` with a token, calls `POST /api/build/sandbox/search` directly via FastAPI test client, asserts:
  - Results come back, blurbs are non-empty, citation IDs are sequential.
  - Token mismatch → `UNAUTHENTICATED`.
  - Cross-tenant doc indexed under another user is **not** returned (this is the load-bearing assertion — it proves the ACL path actually engaged).
  - `source_filters=["slack"]` excludes a Google Drive doc.
  - Rendered SKILL.md for a session with two CC pairs lists exactly those two sources (covers the per-session source-list rendering).

**Unit (one file, only for the auth dependency):**
`backend/tests/unit/onyx/server/features/build/test_sandbox_auth.py`
- `require_sandbox_session_token` returns the right session given a valid token; raises `UNAUTHENTICATED` for missing/wrong/expired token; sets `CURRENT_TENANT_ID` on the contextvar.
- Asserts every `DocumentSource` member has a non-empty `craft_description` or is on the allow-set.

**Manual smoke (do this before merging):**
- Run a real Craft session locally, watch the agent call `company_search`, confirm it cites results from the live Onyx index, confirm `find files/` returns nothing (corpus path is gone).
- Run the same query through regular Onyx chat search and through `company_search` for the same user — top results should overlap heavily. Big divergence is a signal we're constructing `SearchTool` differently from chat and need to fix it, not a signal that the test is wrong.
- Confirm a search by user A in tenant 1 cannot see docs ingested by user B in tenant 2 (manual check is fine; the unit test covers the regression).

That's it. No load test, no fuzzer — those are appropriate when the contract stabilizes. For now: prove permissioning works, prove the skill round-trips, ship.
