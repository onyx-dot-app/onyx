# Tech debt register

Temporary shapes and planned removals in the code. Each entry says what it is,
why it exists, where it lives, what ends it, the owner and the date it was
added. A change that leaves a temporary shape or a planned removal adds an
entry here. The PR that pays it off deletes the entry. Component documents
link here from **Known issues** and do not restate the entry.

---

## Linear and Notion presets hidden from the catalog

- **What:** The add catalog does not show a preset when a suggested MCP server
  covers the same service. The Linear and Notion presets, their providers,
  built-in skills and existing integrations stay and keep working.
- **Why:** On a self-hosted deployment a preset needs an OAuth app of the
  admin's own. The hosted MCP server needs none, so the catalog shows one tile
  for the service.
- **Where:** `web/src/lib/plugins/catalog.ts:hasSuggestedMcpServer`,
  `web/src/sections/integrations/AddIntegrationModal.tsx`.
- **Ends when:** A decision removes the Linear and Notion presets (providers,
  built-in skills, tests and rows) or brings them back to the catalog.
- **Owner:** rohoswagger. **Added:** 2026-11-24.

## Dual write of OpenAPI apps to `tool`

- **What:** Each create and spec change of an OpenAPI app writes the
  `api_app` row and also the parsed document to the `tool` row. The
  integration keeps both `tool_id` and `api_app_id`.
- **Why:** The previous release reads the spec from `tool`. The readers move to
  `api_app` one release after this table, so every app has its `api_app` row
  before they do.
  Writing `tool` for one more release keeps a version rollback working: the
  old release still finds every app that was created or changed.
- **Where:** `backend/onyx/db/integration.py:write_openapi_document__no_commit`;
  `ck_integration_single_kind_row` on `backend/onyx/db/models.py:Integration`
  takes `coalesce(tool_id, api_app_id)`;
  `backend/onyx/integrations/service.py:_shapes` reads an integration with
  `api_app_id` and no `tool_id` as GraphQL.
- **Ends when:** The release after the readers move to `api_app` ships. Then
  stop the writes to `tool`, drop `integration.tool_id` for API apps and the
  OpenAPI columns of `tool`, change the check constraint to name
  `api_app_id`, and make `_shapes` read `api_app.api_type`.
- **Owner:** rohoswagger. **Added:** 2026-11-24.

## URL-pattern apps

- **What:** An old URL-pattern app (a CUSTOM `external_app`) keeps
  its URL patterns: an admin can change its name and sign-in, or delete it.
  Create refuses the shape, and chat offers no tool for it.
- **Why:** Existing rows must keep loading until their admins delete them.
  Revision `933a21d46472` turns an app with one `https://host/path/*`
  pattern into a REST app; no base URL covers the other apps.
- **Where:** `backend/onyx/integrations/craft.py`,
  `backend/onyx/integrations/chat_tools.py`,
  `backend/onyx/integrations/kinds/api.py`,
  `backend/onyx/integrations/models.py:ApiShape`.
- **Ends when:** No URL-pattern app remains. Then remove their runtime
  handling in these files and `ApiShape.URL_PATTERN`.
- **Owner:** rohoswagger. **Added:** 2026-11-24.

## Playground trial-start periods use the calendar week

- **What:** `tenant_trial_start` returns nothing, so playground limits that
  count from the trial start (LLM cost per 7 days, chunks for the whole trial)
  use the calendar week instead. Both reset every Monday.
- **Why:** The trial start comes from the control plane through a per-tenant
  cache, which the next PR of the ENG-4479 stack adds.
- **Where:** `backend/onyx/server/usage_limits.py:tenant_trial_start`, used by
  `period_for`.
- **Ends when:** `tenant_trial_start` reads the cached `trial_start`. That PR
  also adds a per-tenant warning when the trial start is missing.
- **Owner:** Subash-Mohan. **Added:** 2026-11-27.

## The old `tenant_usage` table is kept for one release

- **What:** `tenant_usage` and its model `TenantUsage` stay, but the current
  code does not read or write them. `tenant_usage_counter` replaced them.
- **Why:** Migration `db8e1bfe4729` copies the usage into the new table. During
  the rolling deploy, old pods still read and write `tenant_usage`. If it is
  gone, they fail every request that checks a usage limit, such as chat on
  Onyx's keys, API key calls and indexing batches. Rolling back is not
  supported.
- **Where:** `backend/onyx/db/models.py:TenantUsage`.
- **Ends when:** The release after the one that adds `tenant_usage_counter`
  drops the table and the model.
- **Owner:** Subash-Mohan. **Added:** 2026-11-27.
