# Onyx Component Index

The sitemap. Every product surface in Onyx, grouped by domain.

`✅` document written · `🚧` planned, not yet written

Onyx is two products sharing one platform:

- **Chat + Search.** Ask a question, the system retrieves from your connected
  company data and answers with citations.
- **Craft.** An agentic coding product that runs a coding agent in a sandbox.

Both sit on shared platform services: auth, tenancy, LLM access, background jobs.

```
                         ┌──────────────── Users ────────────────┐
                         │                                       │
                    Chat + Search                             Craft
                         │                                       │
   ┌─────────────────────┴───────────────────┐                   │
   │                                         │                   │
core loop                                 ingestion              │
(turn → tools → answer)          (connectors → index)            │
   │                                         │                   │
   └──────────────┬──────────────────────────┴───────────────────┘
                  │
              platform
   (auth · tenancy · LLM · jobs · observability)
```

---

## Domain: Core loop

The chat turn. A user sends a message; the system assembles context, runs an LLM
loop with tools, streams packets back, and saves the turn.

| | Component | What it covers |
|---|---|---|
| ✅ | [core-chat-loop](components/core-chat-loop.md) | `process_message` → `run_llm_loop` → `run_llm_step`. The turn engine. |
| ✅ | [context-assembly](components/context-assembly.md) | System prompt, custom agent prompt, project files, user files, reminders, token budget, compression. |
| ✅ | [streaming-protocol](components/streaming-protocol.md) | Packet types, `Placement`/`turn_index`, the emitter, the wire format the frontend consumes. |
| ✅ | [tools-framework](components/tools-framework.md) | The `Tool` interface, tool construction per turn, the tool runner, built-in tool catalogue. |
| ✅ | [citations](components/citations.md) | How the LLM cites a document number and how that becomes a link. |
| ✅ | [chat-persistence](components/chat-persistence.md) | Sessions, the message tree, branching and edits, tool call storage, feedback. |
| ✅ | [llm-providers](components/llm-providers.md) | Provider config, model selection, model flows, LiteLLM routing, streaming interface. |
| ✅ | [chat-frontend](components/chat-frontend.md) | The chat UI: routes, stores, packet rendering, message actions. |

## Domain: Search and retrieval

Turning a query into ranked, access-filtered context.

| | Component | What it covers |
|---|---|---|
| ✅ | [internal-search](components/internal-search.md) | The search tool and the retrieval pipeline: preprocessing, hybrid retrieval, reranking, section merging, pruning. |
| ✅ | [document-index](components/document-index.md) | The OpenSearch-backed index: schema, chunks, embeddings, search settings, index swap. |
| ✅ | [access-control](components/access-control.md) | Document ACLs, user groups, document sets, external permission sync, curator scoping. |
| ✅ | [web-search](components/web-search.md) | External web search and page fetch as a tool. |
| 🚧 | [federated-search](components/federated-search.md) | Query-time search against a source you have not indexed. |
| ✅ | [search-receipts](components/search-receipts.md) | The retrieval-quality evidence trail. |

## Domain: Ingestion

Getting company data into the index and keeping it fresh and correctly permissioned.

| | Component | What it covers |
|---|---|---|
| ✅ | [connectors](components/connectors.md) | The connector interface and the ~69 source integrations. |
| ✅ | [cc-pairs-and-credentials](components/cc-pairs-and-credentials.md) | Connector/credential pairing, encrypted credential storage, connector admin. |
| ✅ | [indexing-pipeline](components/indexing-pipeline.md) | Document → chunk → embed → write. Index attempts, heartbeats, coordination. |
| ✅ | [permission-sync](components/permission-sync.md) | Pulling source-side permissions into Onyx ACLs. |
| ✅ | [file-store-and-user-files](components/file-store-and-user-files.md) | Blob storage, user uploads, projects as file collections. |

## Domain: Configuration surfaces

What an admin or user configures to change how chat behaves.

| | Component | What it covers |
|---|---|---|
| ✅ | [agents-personas](components/agents-personas.md) | Agents (DB name: `Persona`): prompt, tools, document sets, sharing, pinning. |
| 🚧 | [projects](components/projects.md) | A durable file + instruction scope across sessions. |
| 🚧 | [skills](components/skills.md) | Reusable instruction bundles, user and admin scoped. |
| ✅ | [mcp-and-custom-tools](components/mcp-and-custom-tools.md) | MCP servers and OpenAPI-defined custom actions. |
| ✅ | [chat-preferences](components/chat-preferences.md) | Input prompts, reminders, default assistant, per-user settings. |
| ✅ | [standard-answers](components/standard-answers.md) | Canned answers matched before the LLM runs, used by the bots. |

## Domain: Platform

Cross-cutting services every feature depends on.

| | Component | What it covers |
|---|---|---|
| ✅ | [auth-and-identity](components/auth-and-identity.md) | OAuth, SAML, SSO discovery, SCIM, API keys, PATs, service accounts, roles. |
| ✅ | [multi-tenancy](components/multi-tenancy.md) | Tenant isolation, shards, schema-per-tenant. |
| ✅ | [background-jobs](components/background-jobs.md) | Celery apps, queues, beat schedules, locking, the task conventions. |
| ✅ | [editions-and-gating](components/editions-and-gating.md) | CE vs EE, feature flags, licensing, gated apps. |
| ✅ | [observability](components/observability.md) | Metrics, tracing, audit logging, LLM usage and cost. |
| ✅ | [rate-and-usage-limits](components/rate-and-usage-limits.md) | Token rate limits, usage limits, invite limits. |
| ✅ | [notifications](components/notifications.md) | In-app notifications, release notes, admin banners. |
| ✅ | [billing](components/billing.md) | Plans, checkout, license activation, seat and usage billing. |
| ✅ | [whitelabelling-and-theme](components/whitelabelling-and-theme.md) | Enterprise settings: branding, custom theme, application name. |

## Domain: Integrations and clients

Ways to reach Onyx that are not the web chat UI.

| | Component | What it covers |
|---|---|---|
| ✅ | [slack-bot](components/slack-bot.md) | Slack app, channel config, the bot turn runner. |
| ✅ | [discord-bot](components/discord-bot.md) | Discord equivalent. |
| 🚧 | [onyx-api](components/onyx-api.md) | The public HTTP API. |
| 🚧 | [mcp-server](components/mcp-server.md) | Onyx exposed as an MCP server. |
| 🚧 | [llm-gateway](components/llm-gateway.md) | OpenAI-compatible gateway with cost tracking. |
| 🚧 | [mobile-app](components/mobile-app.md) | React Native + Expo client. |
| 🚧 | [desktop-widget-extensions](components/desktop-widget-extensions.md) | Tauri desktop shell, embeddable widget, browser extensions. |
| ✅ | [voice](components/voice.md) | Voice input and output. |
| ✅ | [image-generation](components/image-generation.md) | The image generation tool and its admin config. |
| ✅ | [code-execution](components/code-execution.md) | Code interpreter, bash, and python tools. |

## Domain: Craft

The agentic coding product. It has its own deep documentation under `docs/craft/`;
these components are the map into it.

| | Component | What it covers |
|---|---|---|
| ✅ | [craft-admin](components/craft-admin.md) | The three Craft admin pages: access, apps, preferences. Map into `docs/craft/`. |
| ✅ | [craft-sessions](components/craft-sessions.md) | Craft session lifecycle, turns, history. |
| ✅ | [craft-sandboxes](components/craft-sandboxes.md) | Kubernetes sandbox provisioning, snapshot and restore. |
| ✅ | [craft-streaming](components/craft-streaming.md) | The opencode-serve client and event stream. |
| ✅ | [craft-webapp-proxy](components/craft-webapp-proxy.md) | Previewing the app a sandbox is running. |
| ✅ | [craft-external-apps](components/craft-external-apps.md) | Egress proxy, action policies, credential injection. |
| ✅ | [craft-scheduled-tasks](components/craft-scheduled-tasks.md) | Recurring agent runs. |

---

## Retired features

These have code in the tree but are not part of the product. Do not build on them,
and do not treat their code as a live surface when reviewing a diff.

| Feature | State |
|---|---|
| Knowledge graph | Removed from the product. `backend/onyx/kg/`, `db/entities.py`, `db/entity_type.py`, `db/relationships.py`, `db/kg_config.py` and `tools/tool_implementations/knowledge_graph/` still exist. `KnowledgeGraphTool` is in `BUILT_IN_TOOL_MAP`, but its branch in `tool_constructor.py:_construct_tools_impl` is commented out with "disabling for now because it's broken in the refactor", and the if/elif chain has no trailing `else`, so a persona referencing it silently gets no tool. See [[tools-framework]] §9. |

## Admin panel coverage

`web/src/lib/admin-routes.ts` is the authoritative list of admin routes. Every one
of its 40 entries maps to a written component, across 22 components.

To re-check after changing the admin panel, list the routes and confirm each still
has an owner here:

```bash
grep -oE 'path: "/admin[^"]*"' web/src/lib/admin-routes.ts | sort -u
```

Two traps when auditing this yourself:

- Some `/admin/*` paths are served from a second tree, `web/src/app/ee/admin/`, via a
  rewrite in `web/src/proxy.ts:EE_ROUTES`. Listing `web/src/app/admin/` alone misses
  theme, standard-answer, export-logs, performance, and groups.
- A directory under `ee/admin/` that is **not** in `EE_ROUTES` is unreachable.
  `ee/admin/billing/` is dead code; the live page is `web/src/app/admin/billing/`.

## Coverage gaps

Anything not listed above is unmapped. If you touch unmapped code, say so in the
PR rather than assuming it is low risk, and add the component here.
