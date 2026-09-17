# Vector DB Filter Semantics

How `IndexFilters` fields combine into the final query filter. Describes the active
**OpenSearch** backend. The deprecated **Vespa** backend differs in one respect:
`project_id_filter` there remains *additive* (see "project_id_filter" notes below).

## Filter categories

| Category | Fields | Join logic |
|---|---|---|
| **Visibility** | `hidden` | Always applied (unless `include_hidden`) |
| **Tenant** | `tenant_id` | AND (multi-tenant only) |
| **ACL** | `access_control_list` | OR within, AND with rest |
| **Narrowing** | `source_type`, `tags`, `created_at_range`, `updated_at_range` | Each OR within, AND with rest |
| **Knowledge scope** | `document_set`, `attached_document_ids`, `hierarchy_node_ids`, `persona_id_filter`, `project_id_filter` | OR within group, AND with rest |

## How filters combine

All categories are AND'd together. Within the knowledge scope category, individual filters are OR'd.

```
NOT hidden
AND tenant = T                          -- if multi-tenant
AND (acl contains A1 OR acl contains A2)
AND (source_type = S1 OR ...)           -- if set
AND (tag = T1 OR ...)                   -- if set
AND <knowledge scope>                   -- see below
AND <time windows>                      -- if set, see Time filtering
```

## Time filtering

Two ways to constrain time, both AND-ed into the query:

`created_at_range` / `updated_at_range` are inclusive `[start, end]` windows
(either bound may be open) on the document's creation / last-update time,
AND-ed together when both are set. Use them to express a query's
created-vs-updated intent. The persona `search_start_date` floor is folded into
`updated_at_range.start` in the search pipeline. The deprecated Vespa backend
enforces only `updated_at_range` (it has no `created_at` field, so
`created_at_range` widens rather than narrows there).

For wire compatibility, `BaseFilters` still accepts the deprecated
`time_cutoff` request field and folds it into `updated_at_range.start` at
validation; internal code never sees it.

### Why intent needs both fields

We store only a document's creation time and its **latest** update time — no edit
history. That shapes how intents map onto ranges:

| Intent | Ranges | Resulting predicate |
|---|---|---|
| **created in [S, E]** | `created_at_range=[S, E]` | `created_at >= S AND created_at <= E` |
| **updated / active in [S, E]** | `updated_at_range=[S, →]` **and** `created_at_range=[→, E]` | `last_updated >= S AND created_at <= E` (overlap) |
| **last-touched in [S, E]** (strict) | `updated_at_range=[S, E]` | `last_updated >= S AND last_updated <= E` |

The **updated/active** intent is an *overlap*, not a strict `last_updated` range:
the upper bound must go on `created_at`, because `last_updated` is only the latest
edit. A doc created 8mo ago, edited 5mo ago (unstored) then 2mo ago (the stored
latest) was updated inside a "4–7 months ago" window and must still match — a
strict `last_updated <= 4mo` would wrongly drop it, while the overlap keeps it
(its latest edit is `>= 7mo` and it existed by `4mo`).

### Undated documents

We prefer to over- than under-extend, so a missing timestamp does not remove a
document — with one exception to avoid flooding recent-window queries:

- **`created_at_range`**: undated docs are **always** kept (a doc with no
  `created_at` cannot be shown to fall outside the window).
- **`updated_at_range`**: undated docs are kept only for an **old, open-ended
  lower bound** (start older than `ASSUMED_DOCUMENT_AGE_DAYS`, no upper bound); a
  recent or bounded range excludes them.

## Knowledge scope rules

The knowledge scope filter controls **what knowledge an assistant can access**.

### Primary triggers

Each of these can start a knowledge scope on its own:

- **`persona_id_filter`** is a **primary** trigger. A persona with user files IS explicit
  knowledge, so `persona_id_filter` alone can start a knowledge scope. Note: this is
  NOT the raw ID of the persona being used — it is only set when the persona's
  user files overflowed the LLM context window.
- **`project_id_filter`** is a **primary** trigger. A chat inside a project is scoped to
  that project, so `project_id_filter` alone restricts the search to the project's files —
  project chats do not search team knowledge. (Deprecated Vespa backend: `project_id_filter`
  is still *additive* there and only widens an existing scope.)

### No explicit knowledge attached

When `document_set`, `attached_document_ids`, `hierarchy_node_ids`, `persona_id_filter`,
and `project_id_filter` are all empty/None:

- **No knowledge scope filter is applied.** The assistant can see everything (subject to ACL).

### One explicit knowledge type

```
-- Only document sets
AND (document_sets contains "Engineering" OR document_sets contains "Legal")

-- Only persona user files (overflowed context)
AND (personas contains 42)
```

### Multiple explicit knowledge types (OR'd)

```
-- Document sets + persona user files
AND (
    document_sets contains "Engineering"
    OR personas contains 42
)
```

### Explicit knowledge + overflowing project files

When an explicit knowledge restriction is in effect **and** `project_id_filter` is set (project files overflowed the LLM context window), `project_id_filter` widens the filter:

```
-- Document sets + project files overflowed
AND (
    document_sets contains "Engineering"
    OR user_project contains 7
)

-- Persona user files + project files (won't happen in practice;
-- custom personas ignore project files per the precedence rule)
AND (
    personas contains 42
    OR user_project contains 7
)
```

### Only project_id_filter (no other explicit knowledge)

The search is restricted to the project's files.

```
-- Restricted to project files
NOT hidden
AND (acl contains ...)
AND (user_project contains 7)
```

## Field reference

| Filter field | Vespa field | Vespa type | Purpose |
|---|---|---|---|
| `document_set` | `document_sets` | `weightedset<string>` | Connector doc sets attached to assistant |
| `attached_document_ids` | `document_id` | `string` | Documents explicitly attached (OpenSearch only) |
| `hierarchy_node_ids` | `ancestor_hierarchy_node_ids` | `array<int>` | Folder/space nodes (OpenSearch only) |
| `persona_id_filter` | `personas` | `array<int>` | Persona tag for overflowing user files (**primary** trigger) |
| `project_id_filter` | `user_project` | `array<int>` | Project tag for overflowing project files (**primary** trigger; restricts to project files — OpenSearch. Vespa keeps it additive, see notes) |
| `access_control_list` | `access_control_list` | `weightedset<string>` | ACL entries for the requesting user |
| `source_type` | `source_type` | `string` | Connector source type (e.g. `web`, `jira`) |
| `tags` | `metadata_list` | `array<string>` | Document metadata tags |
| `created_at_range` | `created_at` | `long` | Window on document creation time; see [Time filtering](#time-filtering) (OpenSearch only) |
| `updated_at_range` | `doc_updated_at` | `long` | Window on document update time; see [Time filtering](#time-filtering) |
| `tenant_id` | `tenant_id` | `string` | Tenant isolation (multi-tenant) |
