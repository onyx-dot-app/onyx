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
| **Narrowing** | `source_type`, `tags`, `time_cutoff`, `time_cutoff_upper` | Each OR within, AND with rest |
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
AND time >= cutoff                      -- if set
```

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
| `time_cutoff` | `doc_updated_at` | `long` | Minimum document update timestamp |
| `time_cutoff_upper` | `doc_updated_at` | `long` | Maximum document update timestamp; usable alone or together with `time_cutoff` for a closed range; excludes undated docs in all cases |
| `tenant_id` | `tenant_id` | `string` | Tenant isolation (multi-tenant) |
