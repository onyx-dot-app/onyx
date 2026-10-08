# Onyx Glossary

Onyx overloads several words. The product name and the database name often differ,
and two words sometimes mean the same thing in different layers. Read this before
you trust your intuition about an identifier.

There are **two `SearchDoc` classes** and they are not the same thing. There is a
`Tool` abstract class and a `Tool` database table, and one row can back three very
different kinds of tool. `Persona` in the database is what the product calls an
Agent. These are the traps.

---

## The renames

| Product word | Code identifier | Note |
|---|---|---|
| Agent | `Persona` (`backend/onyx/db/models.py:Persona`) | The product renamed Persona to Agent. The database, the API paths (`/persona`), and most of the backend still say Persona. `web/src/app/admin/agents/` is the admin UI for it. |
| Onyx | Danswer | The product was renamed. Old identifiers and some comments still say Danswer. |
| Craft | Build | The Craft product's backend router is `backend/onyx/server/features/build/` and its API paths are under `/build`. |
| Action | `Tool` | The admin UI calls custom tools "Actions" (`web/src/app/admin/openapi-actions/`, `mcp-actions/`). The code calls them Tools. |

## The collisions

**`SearchDoc`** exists twice.
- `backend/onyx/context/search/models.py:SearchDoc` is the in-flight Pydantic model a
  search returns.
- `backend/onyx/db/models.py:SearchDoc` is the table row that persists a document a
  turn surfaced, linked to the `ToolCall` that found it.

**`Tool`** exists three ways.
- `backend/onyx/tools/interface.py:Tool` is the abstract class every tool implements.
- The `Tool` table is one row per configured tool. Which of three kinds it is depends
  on which column is set: `in_code_tool_id` (a built-in), `openapi_schema` (a custom
  OpenAPI action), or `mcp_server_id` (an MCP tool).
- `backend/onyx/coding_agent/` and `backend/onyx/deep_research/` define SDK agents.
  Their control tools use `AgentTool` definitions without DB tool rows.
  Shared execution lives in `backend/onyx/agents/tool_execution.py:ToolBatch`.
  See [[tools-framework]].


**"Turn"** means two different things.
- Backend: one user message plus everything the assistant does before it finishes.
- Frontend: `Placement.turn_index` is a **rendering block**. One LLM inference that
  produces reasoning and a tool call is one backend step but two frontend turns.
  See [[streaming-protocol]].

**"Search"** covers four distinct mechanisms.
- `internal_search`: the tool over your indexed company data. See [[internal-search]].
- `web_search`: a separate tool hitting an external provider. See [[web-search]].
- Federated search: query-time search against a source that was never indexed. Slack
  is a lane inside `internal_search`. Slack is the only registered federated source
  today. Future sources can plug into `search_chunks`. See [[federated-search]].
- Chat search: `GET /chat/search` searches the user's own conversation history.

**"Agent"** means three things depending on context: a `Persona`, an autonomous
sub-loop (the deep research agent, the coding agent), or the AI assistant generally.

## The retrieval vocabulary

| Term | Meaning |
|---|---|
| Document | One item from a source: a page, a ticket, a message thread. |
| Chunk | A slice of a document, sized for embedding. The unit the index stores. |
| Section (`InferenceSection`) | Adjacent chunks from one document, rejoined. `merge_individual_chunks` joins chunks whose `chunk_id` differs by 1. This is the unit the LLM reads. |
| Lane | One parallel retrieval path inside a single search tool call. One per expanded query, plus an optional Slack lane. Lanes are combined by weighted RRF. |
| Expansion | Two unrelated meanings. **Query expansion** rewrites one query into several. **Section expansion** pulls chunks surrounding an already-selected section. |
| Selection | The LLM stage that picks which retrieved sections are worth expanding. It is what Onyx has instead of a reranking model. |

## Ingestion vocabulary

| Term | Meaning |
|---|---|
| Connector | The code that pulls documents from one source type. |
| Credential | The stored, encrypted secret for one account on a source. |
| cc-pair (`ConnectorCredentialPair`) | A connector plus a credential. **This is the real unit of ingestion**, not the connector. Indexing, permissions, and deletion all operate on the pair. |
| Index attempt | One run of indexing for a cc-pair. |
| Document set | An admin-defined group of cc-pairs and/or federated connectors, used to scope an agent or a search. |
| User file | A file a user uploaded, as opposed to a connector-sourced document. |
| Project | A durable collection of user files plus instructions that persists across sessions. |

## Index vocabulary

| Term | Meaning |
|---|---|
| Search settings (`SearchSettings`) | The row that defines the embedding model and index configuration. |
| PRESENT / FUTURE | `IndexModelStatus`. PRESENT is the live index. FUTURE is a second index being built during an embedding-model swap. |
| Secondary index | The FUTURE index. During a swap the system writes to both. |
| `hybrid_alpha` | A caller-level keyword-versus-semantic hint. It is partly a no-op inside the OpenSearch backend. Do not assume it controls scoring. See [[document-index]]. |

## Access vocabulary

| Term | Meaning |
|---|---|
| ACL | The access control list stored on each indexed document, compiled into every search query as a filter. |
| External permissions | Permissions pulled from the source system, as opposed to Onyx-native groups. See [[permission-sync]]. |
| Curator | A user-group-scoped admin role. |
| CE / EE | Community Edition (MIT, `backend/onyx/`) and Enterprise Edition (`backend/ee/onyx/`, mirroring the CE layout). EE code is reached from CE through `fetch_versioned_implementation` and `fetch_ee_implementation_or_noop`. |

## Chat internals

| Term | Meaning |
|---|---|
| Step / cycle | One LLM inference with a given context and tool set. A turn contains up to `MAX_LLM_CYCLES` of them. |
| Emitter | The object a deep call uses to push a packet without returning it up the stack. It stamps `model_index`. |
| State container | The per-model accumulator that streaming code fills and persistence reads at the end of a turn to build the saved rows. Deep-research tool code also reads its prior tool calls. |
| Reminder | A trailing user message carrying one or two critical instructions. It is last because models attend hardest to final tokens. |
| Custom agent prompt | The persona's instructions, injected as a user message that moves to sit above the newest user message each turn. |
| Fence | A cache key acting as a flag. The stop fence means the user pressed stop. The processing fence means a turn is live. |
| Incognito | A session mode where content is not persisted to the chat tables. |

## Three representations of a message

Mixing these is the most common mistake in the chat code.

1. `ChatMessage`: the database row. Convert it early, never pass it deep.
2. `ChatMessageSimple`: the canonical in-code model. Extend this one.
3. `ChatCompletionMessage`: the LLM-facing form. Deliberately minimal.
