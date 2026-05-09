# Craft Search Tool — Design & Rationale

> Related: [search-requirements.md](search-requirements.md)

## Overview

This document defines the design for replacing Craft's legacy `files/` corpus sync with a first-party search tool. The high-level requirements live in `search-requirements.md`; this document records the approach we chose, why we chose it over alternatives, and the objectives and requirements for each subproject.

The implementation has four parts:

1. **Agent-First CLI Refactor** — Reposition onyx-cli as an agent experience (AX) tool.
2. **Search API** — A new backend endpoint exposing the full Onyx chat-mode search pipeline.
3. **CLI Search Command** — New onyx-cli command(s) wrapping the search API, plus a rationalized agent tool surface.
4. **Craft Integration** — Wire onyx-cli into the Craft sandbox, replacing file sync entirely.

The end state: a Craft agent calls onyx-cli inside its sandbox to search company knowledge, hitting the same search pipeline (query expansion, hybrid retrieval, LLM document selection, context expansion) that powers Onyx chat. The agent gets permissioned, fresh, citation-rich results scoped to the running user — no corpus dump, no drift, no separate retrieval story.

---

## Approaches Considered

We evaluated three delivery mechanisms for giving the Craft sandbox access to Onyx search: MCP, an independent skill script, and the CLI. Each was assessed against the core requirement from `search-requirements.md`: **behavioral parity with the chat flow's search tool**.

### A. Onyx MCP Server (rejected)

The Onyx MCP server is already configured to handle authentication and search requests. OpenCode can act as an MCP client, so in principle the sandbox could call the existing MCP search tool with no new backend work.

**Why rejected — not parity with chat-mode search:**

The MCP server uses the EE `send_search_query` endpoint, which provides parity with Onyx's **Search Mode**, not the **Chat Mode** search tool. The gap is significant:

- **No semantic query rephrase.** Chat-mode search runs `semantic_query_rephrase()` to produce a standalone reformulation of the query using conversation context. Search Mode skips this.
- **Different query expansion logic.** Chat-mode search runs parallel semantic + keyword expansion with distinct weighting (`LLM_SEMANTIC_QUERY_WEIGHT=1.3`, `LLM_KEYWORD_QUERY_WEIGHT=1.0`). Search Mode has its own, simpler expansion.
- **No LLM context expansion.** Chat-mode search classifies each selected document's relevance and expands context by including adjacent chunks (up to full-document retrieval). Search Mode returns chunks as-is.
- **No federated search.** Chat-mode search runs federated retrieval (Slack, etc.) in parallel with Vespa queries. Search Mode does not.
- **Different query weighting.** Chat-mode search uses weighted reciprocal rank fusion across multiple query groups with different hybrid alpha values. Search Mode uses simpler ranking.

The MCP path would have been the easiest to implement, but it delivers a materially worse search experience. The whole point of this project is that the Craft agent should get the same retrieval quality as a user in chat — "if chat search gets better, Craft search gets better for free." The MCP path doesn't achieve that.

### B. Independent Skill Script (viable but limited)

A standalone skill (a shell script calling `curl`) as described in the earlier `search-requirements.md` approach. Very lightweight: a `run.sh` that POSTs to a backend endpoint and prints results to stdout.

**Pros:**
- Minimal implementation surface. A shell script and a new endpoint.
- No dependency on the CLI codebase.

**Cons:**
- Craft-only. The skill script lives in the sandbox image and benefits no one else.
- No path to broader agent tooling. Other agents (Claude Code, Cursor, etc.) can't reuse the script.
- Requires a custom auth mechanism (sandbox token) rather than using the existing PAT system.
- Dead-end: if Craft needs more Onyx capabilities later (list connectors, create agents, manage personas), each requires a new bespoke script.

### C. Onyx CLI (chosen)

Bundle onyx-cli into the sandbox. Add a `search` command backed by a new general-purpose search API. Authenticate via PAT.

**Pros:**
- **Anything implemented for Craft immediately benefits all other agents.** Claude Code users, Cursor users, custom integrations — everyone gets the same search command.
- **Extensible.** If Craft later needs more Onyx capabilities (manage agents, configure connectors, "Onyx-management via Craft"), they're CLI commands, not bespoke scripts.
- **Uses existing auth.** PATs already work. No new token type.
- **The CLI already exists** and has infrastructure for non-interactive use (`ask` command, `--json` output, exit codes).

**Cons:**
- Requires CLI refactoring work (Part 1) to make it properly agent-first.
- Requires a new backend search API (Part 2) — but this is needed regardless of delivery mechanism.
- Sandbox image grows by the size of the Go binary.
- Craft sandbox needs internal network URL (`ONYX_SERVER_URL` pointing at the Kube service, not the public nginx URL).

**Why this wins:**

The CLI is the only option where investment compounds. A skill script is throwaway. The MCP server doesn't have the right search pipeline. The CLI becomes the universal agent interface to Onyx — search, ask, discover, and (eventually) manage. Every Craft improvement lands for every agent.

### Decision: Results, Not Answers

The search API returns retrieved documents with citations — not an LLM-generated answer. This is deliberate:

- **If the search is for the user**, passing back an LLM-generated answer is "deep frying" — the agent will process the answer again to incorporate it into its own response. The user gets double-processed text for no reason.
- **If the search is for the agent**, returning results gives the agent more options. It can synthesize across multiple searches, decide which results matter, and cite sources directly. An LLM answer forecloses those options.
- **User-facing agents decide what to do with search results.** Fewer options if given a pre-digested answer.
- The existing `ask` command already provides the "give me an LLM answer" path. `search` is the complementary primitive: retrieval without generation.

### Consumer Note: Onyx MCP Server

The new search API (Part 2) should also become the backend for the Onyx MCP server's search tool. The MCP server currently calls the EE `send_search_query` endpoint (Search Mode parity). Once the chat-mode search API exists, the MCP server should switch to it — giving MCP consumers the same search quality upgrade. This is out of scope for this project but is a direct beneficiary.

---

## Dependencies Between Parts

```
Part 1 (CLI refactor)  ──────────────────────────────────────┐
                                                              │
Part 2 (Search API)  ─────────────────────────────────────────┤
                                                              ▼
Part 3 (CLI search command)  ──► depends on Part 1 + Part 2
                                                              │
                                                              ▼
Part 4 (Craft integration)   ──► depends on Part 1 + Part 2 + Part 3
```

Parts 1 and 2 are independent and can be developed in parallel. Part 3 requires both. Part 4 requires all three.

---

## Part 1: Agent-First CLI Refactor

### Objective

Reposition onyx-cli from a human-first TUI that has a non-interactive sidecar (`ask`) into an **agent experience (AX) tool** — a CLI designed first for agent consumption, with the TUI as an extension for human users.

This is not "add an agent mode." This is: onyx-cli is, by default, an agent's interface to Onyx knowledge and capabilities. The TUI and interactive configuration are gated behind a TTY. Agents without a TTY get the core tool surface — searching knowledge, getting answers, discovering what's available — with structured output, clean exit codes, and no prompts. If we want a richer human-facing CLI/TUI experience beyond what TTY-gating provides, that becomes an extension or a separate CLI. The agent path is the main path.

### Requirements

#### R1.1: Non-interactive by default without TTY

When stdin is not a TTY (the universal signal for "an agent or script is calling me"), the CLI must never:
- Launch the Bubble Tea TUI or any interactive UI
- Prompt for input (configuration, confirmation, or otherwise)
- Block waiting for user interaction
- Produce output that assumes a terminal (ANSI escape codes, cursor movement, spinners)

When stdin IS a TTY, current interactive behavior is preserved.

#### R1.2: Agent-optimized default output

Non-interactive mode output must be optimized for LLM consumption:
- Default output format is markdown (readable by agents, parseable, citation-friendly)
- `--json` flag switches to structured JSON (for programmatic consumers)
- `--quiet` flag suppresses progress/status output (already exists on `ask`)
- Progress and status information goes to stderr; results go to stdout (clean pipe separation)
- Non-TTY output is truncated to 4096 bytes with the full response saved to a temp file. This is intentional — coding agents have tool call output limits, and the temp file path lets the agent read more if needed. The `--max-output` flag provides an override.

#### R1.3: Configuration isolation

Agents must not be able to configure the CLI — they cannot set the Onyx URL, API key, or any other persistent setting. Configuration is a human operation:

- The `configure` command is gated behind interactive mode (requires TTY). Without a TTY, it fails with a clear error.
- Inside Craft sandboxes, the CLI is configured entirely via environment variables (`ONYX_SERVER_URL`, `ONYX_API_KEY`). No config file is created, read, or needed.
- The `validate-config` command remains available in non-interactive mode (read-only, useful for health checks).
- Outside of Craft (e.g., a developer using onyx-cli with Claude Code), the config file works as it does today.

#### R1.4: Clean command surface for agents

Agents can see all CLI commands, but human-only commands are gated behind the TUI (no TTY = not usable):

- **Agent-usable commands** (available without TTY): commands for searching knowledge, getting LLM answers, listing agents/personas, and validating configuration. The exact command names and whether search and answer are one command or two is an implementation decision (see Part 3).
- **Human-only commands** (require TTY): the TUI, interactive configuration, SSH server, session browser.
- **Setup commands** (one-time, not for agents): skill installation for agent harnesses.
- Invoking a human-only command without a TTY produces a clear error, not a hang or crash.

#### R1.5: Exit codes are the error contract

Agents use both exit codes and error messages. Exit codes tell the agent (and scripts) that something failed; the stderr error message tells the agent *what* failed and *what to do about it*. Both matter:

- The existing exit code set (`NotConfigured=1`, `BadRequest=2`, `AuthFailure=3`, `Unreachable=4`) must be extended to cover the full surface of failures an agent might encounter (rate limited, search-specific errors, etc.).
- Every non-zero exit must print a clear, actionable error message to stderr — not just an error code or generic "request failed." The message should help an agent understand the problem and either fix it or ask the user for help (e.g., `"authentication failed: PAT expired, ask the user to generate a new one"`).

#### R1.6: Version and capability discovery

The CLI should support a machine-readable health check so that agents (or Craft session setup) can verify:
- CLI version
- Backend version and reachability
- Available authentication (is a PAT configured? does it have valid permissions?)

This supports Part 4's need to validate the CLI is properly configured at session start.

#### R1.7: SKILL.md and README updates

The CLI's `install-skill` command installs a `SKILL.md` for agent harnesses (Claude Code, etc.). This SKILL.md and the CLI's README must be updated to reflect the new agent-first positioning: search as a primary command, the rationalized command surface, structured output options, and the fact that the CLI is designed for agent use.

### Key Challenges

- **Breaking change for existing CLI users**: This refactor will break existing onyx-cli workflows. Developers who use it interactively today will see different default behavior. Backwards compatibility is not a design constraint — we are not preserving the old UX — but be aware this is a breaking change and documentation/changelog should call it out.
- **Output format**: Agents consume the default plain-text stdout. The existing `--json` flag (NDJSON stream events) is left unchanged — it serves programmatic consumers, not agents.

---

## Part 2: Search API

### Objective

Create a new backend API endpoint that exposes Onyx's full hybrid search pipeline — the same pipeline that powers the chat flow's `SearchTool` — as a standalone, authenticated endpoint. It returns ranked, permissioned search results without generating an LLM answer.

The API must invoke `SearchTool.run()` exactly as the chat flow does: query expansion, multi-query hybrid retrieval, weighted RRF fusion, LLM document selection, and context expansion. This is behavioral parity — the same search quality a user gets in chat, available programmatically.

This API is general-purpose. Its consumers include onyx-cli (Part 3), the Craft sandbox (Part 4), and — in the future — the Onyx MCP server (replacing its current Search Mode backend).

### Requirements

#### R2.1: Exact search pipeline parity

The endpoint must instantiate `SearchTool` and call `.run()` — the same code path `tool_constructor.py` uses for chat. This means:
- LLM-powered query expansion (semantic rephrase + keyword expansion)
- Multi-query hybrid retrieval against Vespa
- Weighted reciprocal rank fusion across query results
- LLM-powered document selection (top-N relevance filtering)
- LLM-powered context expansion (adjacent chunk inclusion)
- Federated source retrieval (Slack, etc.) where configured

The endpoint is NOT a simplified "just search Vespa" shortcut. It is the full intelligent retrieval pipeline. The LLM calls inside the pipeline use the deployment's default LLM (or an optionally specified one).

#### R2.2: Interface design — layered configuration

The interface is the hardest part of this subproject. It must be a complete, usable primitive for agents while still allowing high configuration for power users and integrations.

**Simple case (agents, most calls):** Just a query string. Everything else uses sensible defaults.
```
POST /api/search { "query": "what's the sales process for enterprise?" }
```

**Filtered case (power users, targeted searches):** Query plus source and time filters.
```
POST /api/search { "query": "...", "sources": ["slack", "google_drive"], "time_cutoff_days": 30 }
```

**Advanced case (integrations, automation):** Full control over search behavior.
```
POST /api/search {
  "query": "...",
  "sources": ["slack"],
  "document_sets": ["engineering-docs"],
  "tags": [...],
  "time_cutoff_days": 90,
  "persona_id": 5,
  "num_results": 20,
  "skip_query_expansion": false,
  "skip_document_selection": false,
  "max_context_chunks": 15
}
```

The design principle: every parameter beyond `query` is optional with a good default. The defaults should produce the same quality results as a chat search with no user-selected filters. Advanced parameters expose the knobs that exist internally without inventing new ones.

**Knob exposure:** The search pipeline has many configurable parameters — retrieval balance, result counts, query expansion behavior, recency weighting, source/document-set filters, persona scoping, message history for context, and more. Agents are good at iterating: they run a search, read results, reason about what's wrong, and adjust on the next call. The implementation plan for this part should audit all per-query knobs in the search pipeline, determine which are meaningful to expose, and design how they map to API parameters. The goal is that an agent can progressively refine searches without needing a settings echo — it infers what to change from the results.

Key interface decisions that need resolution:
- **Persona scoping**: Should `persona_id` be a parameter? Personas define document set filters, search start dates, and attached documents. Exposing this gives the API access to admin-configured "search profiles" without re-specifying all their settings. But it also couples the search API to persona configuration.
- **LLM selection**: The search pipeline uses an LLM for query expansion and document selection. What LLM does the API use? Options: the deployment's default, a request-specified model, or a dedicated "search LLM" configuration. The simplest is the deployment's default.
- **Query expansion control**: `skip_query_expansion` and `skip_document_selection` let callers trade quality for speed/cost. These are internal SearchTool knobs that exist today. Should they be exposed?
- **Message history**: The chat flow passes message history to the query expander for context, which significantly improves query expansion (e.g., resolving pronouns, understanding follow-up questions). The search API should accept an optional `message_history` parameter so callers with conversation context can pass it in. Without it, the query must be self-contained — which is fine for most agent use. This may be more work than we want for V1 since it requires defining a message format in the API contract and threading it through to the query expander; if so, defer it, but it's worth considering because it's the main quality gap between chat search and standalone search.

#### R2.3: Response format — structured + LLM-facing

The response includes both structured data (for programmatic consumers) and an LLM-facing text blob (for agents):

```json
{
  "results": [
    {
      "citation_id": 1,
      "document_id": "google_drive__abc123",
      "chunk_ind": 4,
      "title": "Enterprise Sales Playbook",
      "blurb": "...",
      "content": "...",
      "link": "https://docs.google.com/...",
      "source_type": "google_drive",
      "score": 0.78,
      "updated_at": "2026-03-12T00:00:00Z"
    }
  ],
  "llm_facing_text": "[1] Enterprise Sales Playbook (Google Drive, 2026-03-12)\n...",
  "citation_mapping": { "1": "google_drive__abc123" },
  "query_expansion": {
    "semantic_queries": ["..."],
    "keyword_queries": ["..."]
  }
}
```

- `results`: The full ranked result set with all metadata. Derived from `SearchDocsResponse.search_docs` / `displayed_docs`.
- `llm_facing_text`: The same citation-rich markdown string that `SearchTool` produces as its `llm_facing_response`. Ready to paste into an LLM context window.
- `citation_mapping`: Maps citation numbers to document IDs, matching the chat tool's behavior.
- `query_expansion`: What queries the LLM expanded the original into. Useful for debugging and transparency.

#### R2.4: Authentication — PAT-based

The endpoint authenticates via the existing PAT system (`Authorization: Bearer onyx_pat_...`). The PAT resolves to a user; the search runs with that user's permissions (ACLs, tenant). This is the same auth mechanism onyx-cli already uses for all other endpoints. The Craft sandbox gets a session-scoped PAT (Part 4) that is just a regular PAT minted and revoked by the session lifecycle.

No new auth mechanism is needed.

#### R2.5: Permissioning and tenant isolation

The search must run as the authenticated user with full ACL enforcement:
- `build_access_filters_for_user()` determines what documents the user can see
- `CURRENT_TENANT_ID` is set from the user's tenant before any search operations
- Cross-tenant document leakage is a security boundary — this must be tested explicitly

#### R2.6: Rate limiting (deferred from V1)

The core chat flow does not have per-request rate limiting on search — only token-budget rate limiting across chat sessions. Agents iterating through multiple searches to refine results is expected behavior, not abuse. For V1, the PAT already scopes access to a single user, and Craft sessions are sandboxed. Rate limiting can be added later if usage patterns warrant it.

#### R2.7: Endpoint placement

The search endpoint lives under `/api/search` (not `/api/build/...` or `/api/chat/...`). It is a general-purpose Onyx API, not a Craft-specific or chat-specific endpoint. Any authenticated client — onyx-cli, MCP server, integrations, Craft sandbox — can call it.

### Key Challenges

- **Interface design**: Balancing simplicity for the common case with configurability for advanced use. Too few parameters and power users can't express what they need. Too many and agents send garbage.
- **LLM cost**: Every search request triggers LLM calls (query expansion + document selection + context expansion). This is the right tradeoff for quality, but the cost should be visible. Rate limiting is deferred from V1 (see R2.6).
- **SearchTool coupling**: `SearchTool` was built for the chat flow. It requires an `Emitter` (for streaming search progress to the chat UI), message history, user memory context, etc. The API must construct a SearchTool with sensible substitutes for chat-specific dependencies.
- **No conversation context**: Chat search benefits from message history for query expansion context. The API has no conversation. Query expansion still works — it just operates on the query alone, which is how most search APIs work.

---

## Part 3: CLI Search Command & Agent Tool Surface

### Objective

Wrap the Part 2 search API in a CLI command (or commands) and rationalize the full CLI into a final set of tools and options for agents. The result is a CLI that an AI agent can use as its primary interface to Onyx — searching knowledge, getting answers, and discovering what's available.

### Requirements

#### R3.1: CLI access to the search API

The CLI must expose the Part 2 search API's full capabilities through command-line flags. At minimum:
- A query string (the only required input)
- Source type filtering
- Time cutoff filtering
- Result count limiting
- Persona scoping
- Structured JSON output as an alternative to the default
- Controls for skipping LLM query expansion / document selection (trade quality for speed/cost)

#### R3.2: Command design — open question

Whether search-results and LLM-generated-answers are exposed as two separate commands or a single command with a mode flag is an implementation decision. Key considerations:

- **Two commands** (e.g., `search` for results, `ask` for answers): clearer semantics, different backends (search API vs chat endpoint), different output shapes and cost profiles. `ask` already exists.
- **One command with a flag** (e.g., `search --answer`): simpler agent surface (one tool to learn, one SKILL.md entry), shared flags like `--source`/`--days` apply to both modes. But the command silently switches between very different code paths.

The implementation plan for this part should make and justify this decision.

#### R3.3: Default output is LLM-facing markdown

When not in JSON mode, the command prints the `llm_facing_text` from the API response to stdout. This is citation-rich markdown that an agent can directly consume and cite from. Progress/status goes to stderr.

In JSON mode, the command prints the full structured API response.

#### R3.4: Rationalized command set for agents

The CLI should have a clear, final set of agent-usable commands. All agent-usable commands must share:
- Structured JSON output option
- Clean exit codes for every failure mode
- No interactive prompts
- Stderr for progress, stdout for results
- `--help` that describes the command in a way an LLM can read

Existing commands should be reviewed for consistency with the new search command(s) — flag naming, output format, error format, and truncation behavior should be uniform across the agent-usable surface.

#### R3.5: Persona/agent discovery

Agents need a way to list available personas with enough information to choose one for a scoped search (ID, name, description, attached document sets, search start date). This may be a standalone command or a flag on another command — the implementation plan should decide.

### Key Challenges

- **Command structure**: The search/ask split is a UX decision that affects how agents discover and use the CLI. The implementation plan must justify the chosen structure.
- **Flag design**: Flags must map cleanly to the API's parameters while being intuitive on the command line.
- **Output format stability**: Agents will parse this output. The markdown format must be stable. The JSON format must be a documented, versioned contract.
- **Consistency across commands**: All agent-usable commands should feel like they're from the same tool.

---

## Part 4: Craft Integration

### Objective

Wire onyx-cli into the Craft sandbox as the primary search tool, replacing the legacy `files/` corpus sync entirely. This requires: minting session-scoped PATs, bundling the CLI binary, creating a CLI skill, populating it with the user's available sources, and tearing down the file sync infrastructure.

### Requirements

#### R4.1: Session-scoped PAT lifecycle

Each Craft session gets a dedicated PAT that exists only for the session's lifetime. This follows the existing pattern of internal service authentication — the Discord bot service already hits the API server directly with a "service account" API key and tenant context is handled there. Craft PATs work the same way: provisioned per session, scoped to the session's user.

- **Provisioning**: At session creation, mint a new PAT scoped to the session's user. The PAT name should identify it as session-bound (e.g., `craft-session-{session_id}`). The PAT's permissions are the same as the user's — no elevation, no restriction beyond what the user already has. (PAT scopes will be addressed later by the Permissions system, not this project.)
- **Injection**: For this version, the PAT value (the raw token, not the hash) is injected directly into the sandbox environment as `ONYX_API_KEY`. The CLI reads this env var for authentication. The backend URL is injected as `ONYX_SERVER_URL`, pointing at the internal Kube service address (not the public nginx URL, which is irrelevant inside the cluster). Long-term, the raw PAT will not be exposed to the sandbox at all — the egress interception proxy (Craft V1 project #4) will inject credentials server-side on outbound requests, so the sandbox never sees secrets. This direct env var injection is the interim approach until that proxy layer is in place.
- **Deprovisioning**: When the session ends (user closes it, idle timeout, explicit cleanup), the PAT is revoked. Revoked PATs immediately stop working — any in-flight search requests fail with an auth error.
- **Expiration**: Session PATs should have a time-based expiration as a safety net (e.g., 24 hours), independent of session lifecycle. If the session cleanup path fails, the PAT still expires.
- **Audit**: Session PATs are distinguishable from user-created PATs in the PAT list. Users should see them (transparency) but they should be clearly labeled as session-managed and not manually editable.

#### R4.2: CLI binary bundling

The onyx-cli binary must be available inside the sandbox:

- The binary is included in the sandbox Docker image. This is a build-time dependency, not a runtime download.
- The binary version is pinned to the Onyx release. There is no version mismatch between the CLI and the backend it talks to.
- The binary is on `$PATH` inside the sandbox so the agent can invoke it as `onyx-cli` without a full path.
- The binary works without a config file — it reads `ONYX_API_KEY` and `ONYX_SERVER_URL` from the environment (per Part 1's agent-first design). No `configure` step is needed or possible.

#### R4.3: CLI skill creation

The search tool is exposed to the agent as a skill (following the existing skills system described in `docs/craft/features/skills.md`). The skill consists of:

- **`SKILL.md.template`**: A template that describes how to use onyx-cli search, rendered at session setup with the user's available sources. This is a built-in skill registered with the `BuiltinSkillRegistry`.
- **Skill name**: `company-search` (consistent with `search-requirements.md` — reads naturally, brand-neutral).
- **Rendered `SKILL.md`**: At session setup, the backend queries the user's accessible connectors and renders a per-session SKILL.md that tells the agent:
  - What the search tool is and what it does
  - What sources are available (specific to this user's permissions)
  - Usage examples with the CLI flags
  - Output format description
  - What to do when a source they expect isn't listed

The skill does NOT include a shell script wrapper. The agent calls onyx-cli directly — the CLI is the tool, not a wrapper around curl.

#### R4.4: Available sources injection

The skill's source list is populated from the user's actual connector access:

- Source data comes from `get_connector_credential_pairs_for_user()` (the same function the existing `/api/build/connectors` endpoint uses).
- For each accessible source, render: source identifier (matching the `--source` flag values), display name, and a one-line description of what's in it.
- For sources with meaningful sub-scopes (Slack channels, Linear teams), include a few examples.
- The list is a snapshot at session creation — not refreshed mid-session. Connector changes take effect on the next session.
- If the user has no connected sources, the skill still renders but the source list says so explicitly. The agent should not hallucinate sources.

#### R4.5: Decommission file sync

Remove the legacy `files/` corpus sync infrastructure (the search tool replaces it):

- **Remove the `files/` directory from sandbox workspace setup.** No more symlink to persistent document storage or demo data.
- **Remove `PersistentDocumentWriter`** and any Celery tasks that sync documents to persistent storage for sandbox consumption. (Verify no other consumer depends on this path first.)
- **Remove `build_knowledge_sources_section`** and the `{{KNOWLEDGE_SOURCES_SECTION}}` placeholder from `AGENTS.template.md`. The knowledge sources section is replaced by the `company-search` skill's SKILL.md.
- **Remove `CONNECTOR_INFO` dict** that was only used by the knowledge sources section builder.
- **Remove `/workspace/files` allowlist rules** from `opencode_config.py`.
- **Remove the Kubernetes init container** that synced corpus from S3 into the pod (if one exists).
- **Update `AGENTS.template.md`** to point the agent at the `company-search` skill as the only path to company knowledge. Remove references to `files/`, `find`, `grep` over company data, JSON document format, etc.
- **Preserve `attachments/`** — user-uploaded session files are still read via normal file operations and are not part of this removal.

#### R4.6: Validation at session start

Before the agent begins working, verify the search tool is functional:

- After injecting the PAT and bundling the CLI, run `onyx-cli validate-config` inside the sandbox as a health check.
- If validation fails (PAT invalid, backend unreachable, search endpoint not available), the session should surface a clear error rather than letting the agent discover the tool is broken mid-task.
- This uses the capability discovery from Part 1 (R1.6).

#### R4.7: Demo data path

If removing the `files/` infrastructure also removes the only path that demo data uses, demo data goes too. The main plan explicitly permits this: "Remove the legacy files/ corpus directory and demo-data path as part of search/control-plane work." If demo data has an independent path that survives, leave it alone.

### Key Challenges

- **PAT lifecycle reliability**: The PAT must be revoked when the session ends. If the cleanup path fails (crash, timeout, orphaned sandbox), the time-based expiration is the safety net. But there should also be a periodic sweep that revokes PATs for sessions that no longer exist.
- **Internal network URL**: The sandbox must reach the Onyx backend via the internal Kube service URL, not the public nginx URL. `ONYX_SERVER_URL` must be set to an address reachable from inside the sandbox. This is a Craft-specific networking concern that the CLI itself doesn't care about.
- **Source list quality**: The one-line descriptions of what's in each source are critical for agent search quality. If the agent doesn't know that "google_drive" contains "engineering specs and product docs," it can't formulate good queries. This data may not exist today and may need to be added to connector metadata or crafted per source type.
- **Transition from file sync**: Existing Craft sessions (if any are active during deploy) will lose access to `files/`. Backwards compatibility is not a constraint — breaking active sessions is acceptable. Be aware this will happen and consider whether the deploy sequence matters (deploy search tool before removing file sync, or accept a brief gap).

---

## Cross-Cutting Concerns

### Testing Strategy

Each part owns its own tests (detailed in part-specific implementation plans), but the end-to-end story spans all four:

- **Unit tests**: Part 1 (TTY detection, output formatting), Part 2 (auth dependency, filter validation)
- **External dependency unit tests**: Part 2 (search endpoint against real Vespa + Postgres — the bulk of the value), Part 4 (PAT lifecycle, SKILL.md rendering)
- **Integration tests**: Part 4 (provision a Craft session, verify the agent can call `onyx-cli search` and get results, verify cross-tenant isolation)
- **Manual smoke**: Run a real Craft session, watch the agent use `onyx-cli search`, compare results to chat search for the same query

### Security Boundaries

- The sandbox never receives long-lived user credentials. The session PAT is short-lived, scoped, and auto-revoked.
- The CLI config file is not created inside the sandbox. Configuration is env-var-only.
- The search API enforces the same ACL path as chat search. Cross-tenant leakage is tested.
- PATs are stored hashed in the database. The raw token exists only in the sandbox environment and the minting response.
- PAT scopes are out of scope for this project; they will be addressed by the Permissions system. Session PATs currently have the same permissions as the user.

### Repo Conventions

All parts follow the conventions in CLAUDE.md:
- `OnyxError` (not `HTTPException`) for all API errors
- Typed FastAPI returns (no `response_model=`)
- DB operations under `backend/onyx/db/`
- Celery tasks with `@shared_task` and `expires=`
- Strict typing in both Python and TypeScript
