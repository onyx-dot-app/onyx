# Vector DB Filter Semantics

How `IndexFilters` fields combine into the final query filter. Applies to both Vespa and OpenSearch.

## Filter categories

| Category | Fields | Join logic |
|---|---|---|
| **Visibility** | `hidden` | Always applied (unless `include_hidden`) |
| **Tenant** | `tenant_id` | AND (multi-tenant only) |
| **ACL** | `access_control_list` | OR within, AND with rest |
| **Narrowing** | `source_type`, `tags`, `time_cutoff` | Each OR within, AND with rest |
| **Knowledge scope** | `document_set`, `user_file_ids`, `attached_document_ids`, `hierarchy_node_ids` | OR within group, AND with rest |
| **Additive scope** | `project_id`, `persona_id` | OR'd into knowledge scope **only when** a knowledge scope filter already exists |

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

### No explicit knowledge attached

When `document_set`, `user_file_ids`, `attached_document_ids`, and `hierarchy_node_ids` are all empty/None:

- **No knowledge scope filter is applied.** The assistant can see everything (subject to ACL).
- `project_id` and `persona_id` are ignored — they never restrict on their own.

### One explicit knowledge type

```
-- Only document sets
AND (document_sets contains "Engineering" OR document_sets contains "Legal")

-- Only user files
AND (document_id = "uuid-1" OR document_id = "uuid-2")
```

### Multiple explicit knowledge types (OR'd)

```
-- Document sets + user files
AND (
    document_sets contains "Engineering"
    OR document_id = "uuid-1"
)
```

### Explicit knowledge + overflowing user files

When an explicit knowledge restriction is in effect **and** `project_id` or `persona_id` is set (user files overflowed the LLM context window), the additive scopes widen the filter:

```
-- Document sets + persona user files overflowed
AND (
    document_sets contains "Engineering"
    OR personas contains 42
)

-- User files + project files overflowed
AND (
    document_id = "uuid-1"
    OR user_project contains 7
)
```

### Only project_id or persona_id (no explicit knowledge)

No knowledge scope filter. The assistant searches everything.

```
-- Just ACL, no restriction
NOT hidden
AND (acl contains ...)
```

## Field reference

| Filter field | Vespa field | Vespa type | Purpose |
|---|---|---|---|
| `document_set` | `document_sets` | `weightedset<string>` | Connector doc sets attached to assistant |
| `user_file_ids` | `document_id` | `string` | User files uploaded to assistant |
| `attached_document_ids` | `document_id` | `string` | Documents explicitly attached (OpenSearch only) |
| `hierarchy_node_ids` | `ancestor_hierarchy_node_ids` | `array<int>` | Folder/space nodes (OpenSearch only) |
| `project_id` | `user_project` | `array<int>` | Project tag for overflowing user files |
| `persona_id` | `personas` | `array<int>` | Persona tag for overflowing user files |
| `access_control_list` | `access_control_list` | `weightedset<string>` | ACL entries for the requesting user |
| `source_type` | `source_type` | `string` | Connector source type (e.g. `web`, `jira`) |
| `tags` | `metadata_list` | `array<string>` | Document metadata tags |
| `time_cutoff` | `doc_updated_at` | `long` | Minimum document update timestamp |
| `tenant_id` | `tenant_id` | `string` | Tenant isolation (multi-tenant) |
