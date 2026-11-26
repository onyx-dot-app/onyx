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
- **Why:** The previous release reads the spec from `tool`. The readers move to
  `api_app` in the next PR of this stack, in the same release as this table.
  Writing `tool` for one more release keeps a version rollback working: the
  old release still finds every app that was created or changed.
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
- **Why:** Accepted for the deploy window. It matters from the PR that moves
  the readers to `api_app`; until then nothing reads the row. The next spec
  save adds or corrects the row ([[mcp-and-custom-tools]]).
- **Where:** `backend/onyx/db/integration.py:write_openapi_document__no_commit`.
- **Ends when:** The dual write above ends.
- **Owner:** rohoswagger. **Added:** 2026-11-24.

## Usage-limit counters accept only `CALENDAR_WEEK`

- **What:** A counter allowance on any window other than `CALENDAR_WEEK` is
  refused at import and again before each check.
- **Why:** An allowance declares its window, but the `tenant_usage` counter
  does not read it yet: the check and the increment always use the current
  calendar-week row. Another window would be counted in the wrong row with no
  error.
- **Where:** `backend/onyx/server/usage_limits.py:_counter_window_supported`,
  called by `_require_supported_windows` and `_measure_and_check`.
- **Ends when:** The next PR of the ENG-4479 stack passes the allowance's
  `window_start` to `check_usage_limit` and `increment_usage`. Then the guard
  checks only that the counter supports the window's anchor.
- **Owner:** Subash-Mohan. **Added:** 2026-11-25.
