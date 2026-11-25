# Tech debt register

Temporary shapes and planned removals in the code. Each entry says what it is,
why it exists, where it lives, what ends it, the owner and the date it was
added. A change that leaves a temporary shape or a planned removal adds an
entry here. The PR that pays it off deletes the entry. Component documents
link here from **Known issues** and do not restate the entry.

---

## Dual write of OpenAPI apps to `tool`

- **What:** Each create and spec change of an OpenAPI app writes the
  `api_app` row and also the parsed document to the `tool` row. The
  integration keeps both `tool_id` and `api_app_id`.
- **Why:** The readers move from `tool` to `api_app` in a later release. One
  release of dual write keeps a rolling deploy and a rollback working.
- **Where:** `backend/onyx/db/integration.py:write_openapi_document__no_commit`;
  `ck_integration_single_kind_row` on `backend/onyx/db/models.py:Integration`
  takes `coalesce(tool_id, api_app_id)`.
- **Ends when:** The release after the readers move to `api_app` ships. Then
  stop the writes to `tool`, drop `integration.tool_id` for API apps and the
  OpenAPI columns of `tool`, and change the check constraint to name
  `api_app_id`.
- **Owner:** rohoswagger. **Added:** 2026-11-24.

## Rolling-deploy gap of `api_app`

- **What:** During a rolling deploy the old release writes OpenAPI apps to
  `tool` only. The `api_app` row of such an app can be missing or stale until
  the next admin save of its spec.
- **Why:** Accepted for the deploy window. The next spec save adds or
  corrects the row ([[mcp-and-custom-tools]]).
- **Where:** `backend/onyx/db/integration.py:write_openapi_document__no_commit`.
- **Ends when:** The dual write above ends.
- **Owner:** rohoswagger. **Added:** 2026-11-24.
