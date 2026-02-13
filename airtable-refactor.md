# Airtable Connector Refactor: "Index Everything" Mode

## Issues to Address

The current Airtable connector requires users to manually specify a single `base_id` and `table_name_or_id`. This means:
1. Users must create a **separate connector instance** for every table they want to index.
2. If the user has many bases/tables, setup is tedious and error-prone.
3. There is no way to automatically discover and index all accessible data.

**Goal:** Add an "Index Everything" mode that automatically discovers all bases → lists all tables in each base → indexes all records from every table. This should be an **additional option** alongside the existing single-base/table mode.

## Important Notes

### Airtable API

- **List Bases:** `GET /v0/meta/bases` — returns all bases the token can access, paginated (up to 1,000 per page, opaque `offset` token).
- **Get Base Schema:** `GET /v0/meta/bases/{baseId}/tables` — returns all tables + field schemas for a base (not paginated, returns everything at once).
- **List Records:** `GET /v0/{baseId}/{tableIdOrName}` — returns records paginated (100 per page max, opaque `offset` token).
- **Rate Limits:** 5 requests/second/base, 50 requests/second/token. On 429, wait 30 seconds.
- **Auth:** Personal Access Token (PAT) with `schema.bases:read` + `data.records:read` scopes.

### pyairtable Library

The existing `pyairtable` library already supports all needed operations:
- `api.bases()` → lists all bases
- `api.base(base_id).tables()` → lists all tables in a base
- `table.all()` → fetches all records (handles pagination internally)
- `table.schema()` → gets table schema with field definitions

This means we do **not** need raw HTTP calls — the library handles pagination and rate limiting internally.

### Current Connector Architecture

- Current connector is a `LoadConnector` (full state load, no incremental updates).
- Airtable has no "modified since" filter, so full loads are appropriate.
- The connector uses `pyairtable.Api` for all API calls.
- Document IDs follow the pattern `airtable__{record_id}`.
- Records are processed in parallel batches of 8 using `ThreadPoolExecutor`.
- The connector currently takes `base_id` and `table_name_or_id` as **required** constructor params.

### Connector Interface Choice

**Decision: Keep `LoadConnector` interface.** Rationale:
- Airtable doesn't support "modified since" filtering, so `PollConnector` adds no value.
- `CheckpointedConnector` is overkill here — the pyairtable library handles pagination internally, and the dataset sizes for a single Airtable account are bounded (max 50k records/base on most plans). The overhead of implementing checkpoint models, serialization, and stage tracking is not justified.
- The existing `LoadConnector` pattern works well. If checkpointing becomes needed later (e.g., for very large enterprise Airtable accounts), it can be added as a follow-up.

### Frontend Configuration System

- Connector configs are declarative in `web/src/lib/connectors/connectors.tsx`.
- Supports `tab` field type for conditional field groups (e.g., "Index Everything" vs "Specific Table").
- The `visibleCondition` on fields allows showing/hiding fields based on other selections.
- Airtable is registered as a `load_state` connector type.

## Implementation Strategy

### Phase 1: Backend — Connector Changes

**File:** `backend/onyx/connectors/airtable/airtable_connector.py`

#### 1.1 Add `index_all` Constructor Parameter

Add a new boolean parameter `index_all` (default `False`) to `__init__`. When `True`, the connector ignores `base_id` and `table_name_or_id` and instead discovers all bases and tables automatically.

```python
def __init__(
    self,
    base_id: str = "",           # Make optional (empty string when index_all=True)
    table_name_or_id: str = "",  # Make optional (empty string when index_all=True)
    index_all: bool = False,     # NEW: index everything mode
    treat_all_non_attachment_fields_as_metadata: bool = False,
    view_id: str | None = None,
    share_id: str | None = None,
    batch_size: int = INDEX_BATCH_SIZE,
) -> None:
```

#### 1.2 Add `_load_all_bases_and_tables()` Method

New private method that:
1. Calls `self.airtable_client.bases()` to list all accessible bases.
2. For each base, calls `self.airtable_client.base(base_id).tables()` to list all tables.
3. Returns a list of `(base_id, base_name, table)` tuples for iteration.

#### 1.3 Refactor `load_from_state()` to Support Both Modes

Modify `load_from_state()`:
- **If `index_all` is `True`:** call `_load_all_bases_and_tables()`, then iterate over each table, fetching all records and yielding document batches. Must override `self.base_id` per-table for URL generation.
- **If `index_all` is `False`:** behave exactly as today (single base + table).

Extract the per-table indexing logic into a helper method `_index_table(base_id, table)` that both code paths share:
```python
def _index_table(
    self,
    base_id: str,
    table: pyairtable.Table,
) -> GenerateDocumentsOutput:
    """Index all records from a single table. Yields batches of Documents."""
```

#### 1.4 Add Rate Limiting Between Bases/Tables

When iterating over multiple bases and tables, add a small delay (~0.25s) between API calls to stay well within the 5 req/s/base limit. The `pyairtable` library handles pagination rate limiting for `table.all()`, but the meta API calls (listing bases/tables) should be throttled.

#### 1.5 Add `validate_connector_settings()` Override

Validate based on mode:
- **`index_all=True`:** Call `self.airtable_client.bases()` and verify at least one base is accessible.
- **`index_all=False`:** Verify the specific `base_id` and `table_name_or_id` are accessible (try to fetch schema).

Raise `ConnectorValidationError` with helpful messages if validation fails.

#### 1.6 Enhance Document IDs for Multi-Base Uniqueness

The current document ID format `airtable__{record_id}` is already globally unique (Airtable record IDs are globally unique across all bases), so no change is needed here.

#### 1.7 Enhance Semantic Identifiers

When in `index_all` mode, include the base name in the semantic identifier for clarity:
- Current: `{table_name}: {primary_field_value}`
- Index-all mode: `{base_name} > {table_name}: {primary_field_value}`

### Phase 2: Frontend — Configuration UI Changes

**File:** `web/src/lib/connectors/connectors.tsx`

#### 2.1 Add Tab-Based Mode Selection

Replace the current flat field list with a `tab` field type that lets users choose between:

**Tab 1: "Index Everything"**
- No additional fields needed (base_id and table_name_or_id will be sent as empty strings).
- Checkbox for `treat_all_non_attachment_fields_as_metadata`.

**Tab 2: "Specific Table"**
- Same fields as today: `base_id`, `table_name_or_id`.
- Checkbox for `treat_all_non_attachment_fields_as_metadata`.
- Advanced: `view_id`, `share_id`.

The tab field will set `index_all` to `True` or `False` based on the selected tab.

Implementation pattern (following the existing `highspot` connector as a reference):
```typescript
airtable: {
  description: "Configure Airtable connector",
  values: [
    {
      type: "tab",
      name: "airtable_scope",
      label: "What should we index from Airtable?",
      optional: true,
      tabs: [
        {
          value: "everything",
          label: "Everything",
          fields: [
            {
              type: "checkbox",
              label: "Index all bases and tables",
              name: "index_all",
              description: "Automatically discovers and indexes all bases and tables accessible by your API token.",
              optional: false,
              hidden: true,
              default: true,
            },
          ],
        },
        {
          value: "specific",
          label: "Specific Table",
          fields: [
            {
              type: "text",
              query: "Enter the base ID:",
              label: "Base ID",
              name: "base_id",
              optional: false,
              description: "The ID of the Airtable base to index (starts with 'app').",
            },
            {
              type: "text",
              query: "Enter the table name or ID:",
              label: "Table Name or Table ID",
              name: "table_name_or_id",
              optional: false,
            },
          ],
        },
      ],
    },
    {
      type: "checkbox",
      label: "Treat all fields except attachments as metadata",
      name: "treat_all_non_attachment_fields_as_metadata",
      description: "Choose this if the primary content to index are attachments and all other columns are metadata for these attachments.",
      optional: false,
    },
  ],
  advanced_values: [
    // view_id and share_id only apply to specific table mode
    {
      type: "text",
      label: "View ID",
      name: "view_id",
      optional: true,
      description: "If you need to link to a specific View, put that ID here e.g. viwVUEJjWPd8XYjh8.",
      visibleCondition: (values: any) => !values.index_all,
    },
    {
      type: "text",
      label: "Share ID",
      name: "share_id",
      optional: true,
      description: "If you need to link to a specific Share, put that ID here e.g. shrkfjEzDmLaDtK83.",
      visibleCondition: (values: any) => !values.index_all,
    },
  ],
  overrideDefaultFreq: 60 * 60 * 24,
},
```

### Phase 3: Logging and Error Handling

#### 3.1 Structured Logging

Add informative logging at each stage of the "index all" flow:
- Log the number of bases discovered.
- Log each base name + number of tables.
- Log each table name + number of records.
- Log any tables that fail to index (continue with next table, don't abort entirely).

#### 3.2 Graceful Error Handling Per Table

If a single table fails to index (e.g., permission error, transient API error), log the error and continue indexing other tables. This prevents one problematic table from blocking the entire sync.

### Phase 4: Testing

#### 4.1 Unit Tests

**File:** `backend/tests/unit/connectors/airtable/test_airtable_connector.py` (new)

Test with mocked `pyairtable` API:
- Test `index_all=True`: mock `api.bases()` and `base.tables()` to return multiple bases/tables, verify all records from all tables are yielded.
- Test `index_all=False`: verify existing single-table behavior is unchanged.
- Test that `index_all=True` with an empty account (no bases) yields nothing gracefully.
- Test that a failure in one table doesn't prevent other tables from being indexed.
- Test semantic identifier format includes base name in `index_all` mode.
- Test `validate_connector_settings()` for both modes.

#### 4.2 Manual Testing

Using the provided test token (`patiFRjtZTbaR0fdl...`), verify against real Airtable data:
- The token has access to 2 bases: "Bug Tracking System" (4 tables) and "Employee Bio Database" (4 tables).
- Verify all 8 tables are discovered and indexed.
- Verify document content and metadata are correct.
- Verify the frontend tab UI works correctly in both modes.

## File Changes Summary

| File | Change |
|------|--------|
| `backend/onyx/connectors/airtable/airtable_connector.py` | Add `index_all` param, add `_load_all_bases_and_tables()`, refactor `load_from_state()`, add `_index_table()`, add `validate_connector_settings()`, enhance semantic IDs |
| `web/src/lib/connectors/connectors.tsx` | Restructure airtable config to use tab-based mode selection with "Everything" and "Specific Table" tabs |
| `backend/tests/unit/connectors/airtable/test_airtable_connector.py` | New unit tests for index_all mode |

## Backward Compatibility

- Existing connectors with `base_id` and `table_name_or_id` set will continue to work as-is since `index_all` defaults to `False`.
- No database migration needed — `index_all` is just another field in `connector_specific_config` JSON.
- The registry entry in `registry.py` does not need to change — same class, same module path.
