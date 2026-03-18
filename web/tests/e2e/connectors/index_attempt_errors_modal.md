# Index Attempt Errors Modal - Comprehensive Test Plan

## Application Overview

The Index Attempt Errors Modal is an admin-facing feature found on the connector detail page at
`/admin/connector/[ccPairId]`. It surfaces document-level indexing failures for a given
Connector-Credential Pair (CC Pair) and allows an admin to review them and trigger a full re-index
to attempt resolution.

### Feature Summary

- **Entry point**: A yellow `Alert` banner on the connector detail page that reads "Some documents
  failed to index" with a "View details." bold link. The banner appears only when
  `indexAttemptErrors.total_items > 0`.
- **Data fetching**: The parent page (`page.tsx`) fetches errors via `usePaginatedFetch` with
  `itemsPerPage: 10, pagesPerBatch: 1`, polling every 5 seconds. Only the first 10 errors are
  loaded into the modal. The modal receives these as `errors.items` and performs client-side
  pagination over them.
- **Modal title**: "Indexing Errors" with an `SvgAlertTriangle` icon.
- **Table columns**: Time, Document ID (optionally hyperlinked), Error Message (scrollable cell at
  60px height), Status (badge).
- **Pagination**: Client-side within the modal. Page size is computed dynamically from the
  container height via a `ResizeObserver` (minimum 3 rows per page). A `PageSelector` renders only
  when `totalPages > 1`.
- **Resolve All button**: In the modal footer. Rendered only when `hasUnresolvedErrors === true`
  and `isResolvingErrors === false`. Clicking it: closes the modal, sets
  `showIsResolvingKickoffLoader` to true, and awaits `triggerReIndex(fromBeginning = true)`.
- **Spinner**: The full-screen `Spinner` is shown when `showIsResolvingKickoffLoader &&
  !isResolvingErrors`. Once the backend index attempt transitions to `in_progress` / `not_started`
  with `from_beginning = true`, `isResolvingErrors` becomes true and the spinner is hidden
  regardless of `showIsResolvingKickoffLoader`.
- **Resolving state**: While a full re-index initiated from the modal is running (latest index
  attempt is `in_progress` or `not_started`, `from_beginning = true`, and none of the currently
  loaded errors belong to that attempt), the banner switches to an animated "Resolving failures"
  pulse and the modal header description changes.
- **Access control**: The `/api/manage/admin/cc-pair/{id}/errors` endpoint requires
  `current_curator_or_admin_user`.

---

## Important Implementation Details (Affecting Test Design)

1. **10-error fetch limit**: The parent page only fetches up to 10 errors per poll cycle
   (`itemsPerPage: 10`). The modal's client-side pagination operates on these 10 items, not on the
   full database count. Testing large error counts via the UI requires either adjusting this limit
   or using direct API calls.

2. **Double-spinner invocation**: The `onResolveAll` handler in `page.tsx` sets
   `showIsResolvingKickoffLoader(true)` before calling `triggerReIndex`, which itself also sets it
   to `true`. The spinner correctly disappears when `triggerReIndex` resolves (via `finally`). This
   is benign but worth noting for timing-sensitive tests.

3. **isResolvingErrors logic**: `isResolvingErrors` is derived from `indexAttemptErrors.items`
   (the 10-item fetch) and `latestIndexAttempt`. If any of the currently loaded errors have the
   same `index_attempt_id` as the latest in-progress attempt, `isResolvingErrors` is `false` even
   though a re-index is running.

4. **PageSelector "unclickable" style**: The "‹" and "›" buttons use a `div` with
   `unclickable` prop that adds `text-text-200` class and removes `cursor-pointer`. They are not
   `<button disabled>` elements — they remain clickable in the DOM but navigation is guarded by
   `Math.max`/`Math.min` clamps.

5. **Alert uses dark: modifiers**: The banner component uses `dark:` Tailwind classes, which
   contradicts the project's `colors.css` theming convention. This is an existing code issue and
   not a test failure.

---

## Assumptions

- All test scenarios begin from a fresh, clean state unless explicitly stated otherwise.
- The test user is logged in as an admin (`a@example.com` / `a`).
- A file connector is created via `OnyxApiClient.createFileConnector()` before each scenario that
  needs one, and cleaned up in `afterEach` via `apiClient.deleteCCPair(testCcPairId)`.
- Indexing errors are seeded directly via `psql` or a dedicated test API endpoint because they are
  produced by the background indexing pipeline in production.
- The connector detail page polls CC Pair data and errors every 5 seconds; tests that check
  dynamic state must account for this polling interval (allow up to 10 seconds).

---

## Test Scenarios

### 1. Alert Banner Visibility

#### 1.1 No Errors - Banner Is Hidden

**Seed:** Create a file connector with zero `IndexAttemptError` records.

**Steps:**
1. Navigate to `/admin/connector/{ccPairId}`.
2. Wait for the page to finish loading (`networkidle`).
3. Observe the area between the connector header and the "Indexing" section title.

**Expected Results:**
- The yellow alert banner ("Some documents failed to index") is not present in the DOM.
- The "Indexing" section and its status card are visible.

---

#### 1.2 One or More Unresolved Errors - Banner Appears

**Seed:** Create a file connector, then insert at least one `IndexAttemptError` row with
`is_resolved = false` for that CC Pair.

**Steps:**
1. Navigate to `/admin/connector/{ccPairId}`.
2. Wait for the page to finish loading.
3. Observe the area above the "Indexing" section title.

**Expected Results:**
- The yellow alert banner is visible.
- The banner heading reads "Some documents failed to index".
- The banner body contains the text "We ran into some issues while processing some documents."
- The text "View details." is rendered as a bold, clickable element within the banner body.

---

#### 1.3 All Errors Resolved - Banner Disappears Automatically

**Seed:** Create a file connector with one `IndexAttemptError` where `is_resolved = false`.

**Steps:**
1. Navigate to `/admin/connector/{ccPairId}` and confirm the banner is visible.
2. Using `psql` or a direct DB update, set `is_resolved = true` on that error record.
3. Wait up to 10 seconds for the 5-second polling cycle to refresh the errors fetch.
4. Observe the banner area.

**Expected Results:**
- The yellow alert banner disappears without a manual page reload.
- No navigation or error occurs.

---

#### 1.4 Banner Absent for Invalid Connector With No Errors

**Seed:** Create a file connector with zero errors. Manually put it into `INVALID` status via the
DB.

**Steps:**
1. Navigate to `/admin/connector/{ccPairId}`.
2. Observe both the "Invalid Connector State" callout and the banner area.

**Expected Results:**
- The "Invalid Connector State" warning callout is visible.
- The yellow "Some documents failed to index" banner is absent.
- The two alerts do not overlap.

---

### 2. Opening and Closing the Modal

#### 2.1 Open Modal via "View Details" Link

**Seed:** Create a file connector with one unresolved `IndexAttemptError`.

**Steps:**
1. Navigate to `/admin/connector/{ccPairId}`.
2. Wait for the yellow alert banner to appear.
3. Click the bold "View details." text within the banner.

**Expected Results:**
- A modal dialog appears with the title "Indexing Errors" and an alert-triangle icon.
- The modal header has no description text (description is only shown in the resolving state).
- The modal body shows the paragraph starting with "Below are the errors encountered during
  indexing."
- A second paragraph reads "Click the button below to kick off a full re-index..."
- The table is visible with four column headers: Time, Document ID, Error Message, Status.
- The one seeded error is displayed as a row.
- The modal footer contains a "Resolve All" button.

---

#### 2.2 Close Modal via the X Button

**Seed:** One unresolved `IndexAttemptError`.

**Steps:**
1. Open the Indexing Errors modal (scenario 2.1).
2. Click the close (X) button in the modal header.

**Expected Results:**
- The modal closes and is no longer visible.
- The connector detail page remains with the yellow alert banner still present.
- No navigation occurs.

---

#### 2.3 Close Modal via Escape Key

**Seed:** One unresolved `IndexAttemptError`.

**Steps:**
1. Open the Indexing Errors modal.
2. Press the Escape key.

**Expected Results:**
- The modal closes.
- The connector detail page remains intact with the banner still displayed.

---

#### 2.4 Close Modal via Backdrop Click

**Seed:** One unresolved `IndexAttemptError`.

**Steps:**
1. Open the Indexing Errors modal.
2. Click outside the modal content area on the dimmed backdrop.

**Expected Results:**
- The modal closes.
- The connector detail page remains intact.

---

#### 2.5 Modal Cannot Be Opened When Errors Are Resolving

**Seed:** Simulate `isResolvingErrors = true` by ensuring the latest index attempt has
`status = in_progress`, `from_beginning = true`, and no currently loaded errors share its
`index_attempt_id`.

**Steps:**
1. Navigate to `/admin/connector/{ccPairId}`.
2. Observe the yellow banner in the resolving state.
3. Confirm there is no "View details." link in the banner.

**Expected Results:**
- The banner body shows only the animated "Resolving failures" text (no "View details." link).
- There is no interactive element in the banner to open the modal.

---

### 3. Table Content and Rendering

#### 3.1 Single Error Row - All Fields Present

**Seed:** Insert one `IndexAttemptError` with:
- `document_id = "doc-123"`
- `document_link = "https://example.com/doc-123"`
- `failure_message = "Timeout while fetching document content"`
- `is_resolved = false`
- `time_created = <known timestamp>`

**Steps:**
1. Open the Indexing Errors modal.
2. Inspect the single data row in the table.

**Expected Results:**
- The "Time" cell displays a human-readable, localized version of `time_created`.
- The "Document ID" cell renders "doc-123" as an `<a>` element pointing to
  `https://example.com/doc-123` with `target="_blank"` and `rel="noopener noreferrer"`.
- The "Error Message" cell shows "Timeout while fetching document content" in a 60px-height
  scrollable div.
- The "Status" cell shows a badge with text "Unresolved" styled with red background.

---

#### 3.2 Error Without a Document Link - Plain Text ID

**Seed:** Insert one `IndexAttemptError` with `document_id = "doc-no-link"` and
`document_link = null`.

**Steps:**
1. Open the Indexing Errors modal.
2. Inspect the Document ID cell.

**Expected Results:**
- The Document ID cell displays "doc-no-link" as plain text with no `<a>` element or underline.

---

#### 3.3 Error With Entity ID Instead of Document ID

**Seed:** Insert one `IndexAttemptError` with `document_id = null`, `entity_id = "entity-abc"`,
and `document_link = null`.

**Steps:**
1. Open the Indexing Errors modal.
2. Inspect the Document ID cell.

**Expected Results:**
- The Document ID cell displays "entity-abc" as plain text (fallback to `entity_id` when
  `document_id` is null and no link exists).

---

#### 3.4 Error With Document Link But No Document ID - Uses Entity ID in Link

**Seed:** Insert one `IndexAttemptError` with `document_id = null`,
`entity_id = "entity-link-test"`, and `document_link = "https://example.com/entity"`.

**Steps:**
1. Open the Indexing Errors modal.
2. Inspect the Document ID cell.

**Expected Results:**
- The Document ID cell renders "entity-link-test" as a hyperlink pointing to
  `https://example.com/entity`.
- The link text is `entity_id` because `document_id` is null (code:
  `error.document_id || error.entity_id || "Unknown"`).

---

#### 3.5 Error With Neither Document ID Nor Entity ID

**Seed:** Insert one `IndexAttemptError` with `document_id = null` and `entity_id = null`.

**Steps:**
1. Open the Indexing Errors modal.
2. Inspect the Document ID cell.

**Expected Results:**
- The Document ID cell displays the text "Unknown".

---

#### 3.6 Long Error Message Is Scrollable

**Seed:** Insert one `IndexAttemptError` with a `failure_message` of at least 500 characters.

**Steps:**
1. Open the Indexing Errors modal.
2. Locate the Error Message cell for that row.
3. Attempt to scroll within the cell.

**Expected Results:**
- The Error Message cell's inner `div` is capped at 60px height with `overflow-y-auto`.
- The cell content is scrollable, allowing the full message to be read.
- The table row height does not expand beyond 60px.

---

#### 3.7 Error Message With Special HTML Characters Is Escaped

**Seed:** Insert one `IndexAttemptError` with
`failure_message = "<script>alert('xss')</script>"`.

**Steps:**
1. Open the Indexing Errors modal.
2. Inspect the Error Message cell.

**Expected Results:**
- The text is rendered as a literal string, not interpreted as HTML.
- No JavaScript alert dialog appears.
- The exact text `<script>alert('xss')</script>` is visible as escaped content.

---

#### 3.8 Single-Character Error Message Does Not Break Layout

**Seed:** Insert one `IndexAttemptError` with `failure_message = "X"`.

**Steps:**
1. Open the Indexing Errors modal.
2. Inspect the Error Message cell and table row height.

**Expected Results:**
- The cell renders "X" without layout breakage.
- The row height remains at 60px.

---

#### 3.9 Resolved Errors Are Filtered Out of Modal by Default

**Seed:** Insert one `IndexAttemptError` with `is_resolved = true` and no unresolved errors.

**Steps:**
1. Make a direct API call: `GET /api/manage/admin/cc-pair/{ccPairId}/errors` (without
   `include_resolved`).
2. Make a second call: `GET /api/manage/admin/cc-pair/{ccPairId}/errors?include_resolved=true`.
3. Navigate to `/admin/connector/{ccPairId}`.

**Expected Results:**
- The first API call returns zero items (`total_items = 0`).
- The second API call returns the resolved error with `is_resolved: true`.
- The yellow alert banner is absent from the connector page.
- The modal cannot be opened through normal UI (no "View details." link).

---

### 4. Pagination

#### 4.1 Single Page - No Pagination Controls

**Seed:** Insert 3 unresolved errors (the minimum page size).

**Steps:**
1. Open the Indexing Errors modal.
2. Observe whether a `PageSelector` is rendered below the table.

**Expected Results:**
- No `PageSelector` is rendered (`totalPages === 1`).
- All 3 errors are visible simultaneously in the table.

---

#### 4.2 Multiple Pages - Pagination Controls Appear

**Seed:** Insert 10 unresolved errors (matches the parent's `itemsPerPage: 10` fetch limit).
The modal's dynamic page size is typically larger than 3 but can be forced small by using a
narrow viewport.

**Steps:**
1. Set the browser viewport to a height that results in a page size smaller than 10 (e.g., a
   height where the modal table container fits only 3 rows).
2. Open the Indexing Errors modal.
3. Observe the area below the table.

**Expected Results:**
- A `PageSelector` is rendered with "‹" and "›" navigation controls.
- The current page indicator (page 1) is visually highlighted (active styling).
- Only the rows for page 1 are shown in the table body.

---

#### 4.3 Navigate to Next Page

**Seed:** Insert 10 unresolved errors and use a viewport that yields page size < 10.

**Steps:**
1. Open the Indexing Errors modal and confirm `PageSelector` is visible on page 1.
2. Note the Document IDs visible on page 1.
3. Click the "›" (next page) button.

**Expected Results:**
- The table updates to show errors for page 2.
- The Document IDs on page 2 differ from those on page 1.
- The page 2 indicator becomes highlighted.
- The "‹" (previous page) button becomes clickable (no longer has `unclickable` styling).

---

#### 4.4 Navigate Back to Previous Page

**Seed:** Same as 4.3.

**Steps:**
1. Open the modal and navigate to page 2 (scenario 4.3).
2. Click the "‹" (previous page) button.

**Expected Results:**
- The table returns to showing page 1 errors.
- The page 1 indicator is highlighted.
- The "‹" button gains `unclickable` styling (lighter text, no pointer cursor).

---

#### 4.5 Previous Button Does Not Navigate Below Page 1

**Seed:** Insert enough errors to produce at least 2 pages.

**Steps:**
1. Open the Indexing Errors modal. Confirm the current page is 1.
2. Observe the "‹" button styling.
3. Click the "‹" button.

**Expected Results:**
- The "‹" button has `text-text-200` styling (from `PageLink unclickable` prop) and no
  `cursor-pointer`.
- Note: The button is a `div`, not a `<button disabled>`. It remains clickable in the DOM, but the
  handler clamps navigation to `Math.max(currentPage - 1, 1)`, so clicking it on page 1 has no
  effect on the displayed rows.
- The current page remains page 1.

---

#### 4.6 Next Button Does Not Navigate Beyond Last Page

**Seed:** Insert exactly enough errors to produce 2 pages. Navigate to page 2.

**Steps:**
1. Open the modal and navigate to the last page.
2. Observe the "›" button styling.
3. Click the "›" button.

**Expected Results:**
- The "›" button has `unclickable` styling on the last page.
- Clicking it does not navigate beyond the last page (clamped by `Math.min`).

---

#### 4.7 Page Resets to 1 When Error Count Changes

**Seed:** Insert 10 errors. Use a small viewport so multiple pages exist. Navigate to page 2.

**Steps:**
1. Open the modal and navigate to page 2.
2. While the modal is open, delete all error rows from the DB.
3. Wait up to 10 seconds for the polling cycle to reload errors.

**Expected Results:**
- The modal's error table shows the empty-state message.
- The `currentPage` state resets to 1 (triggered by the `useEffect` watching
  `errors.items.length` and `errors.total_items`).
- The `PageSelector` disappears if only one (empty) page remains.

---

#### 4.8 API-Level Pagination: page_size Parameter Maximum

**Seed:** Insert 101 errors for the CC Pair.

**Steps:**
1. Make `GET /api/manage/admin/cc-pair/{ccPairId}/errors?page_size=100` as an authenticated admin.
2. Make `GET /api/manage/admin/cc-pair/{ccPairId}/errors?page_size=101`.

**Expected Results:**
- The `page_size=100` request returns 100 items and `total_items = 101`.
- The `page_size=101` request returns a 422 Unprocessable Entity error (backend enforces
  `le=100`).

---

### 5. Resolve All Functionality

#### 5.1 Resolve All Button Triggers Full Re-Index and Shows Spinner

**Seed:** Create a file connector in ACTIVE status (not paused, not indexing, not invalid) with at
least one unresolved `IndexAttemptError`.

**Steps:**
1. Open the Indexing Errors modal.
2. Confirm the "Resolve All" button is visible in the modal footer.
3. Click "Resolve All".

**Expected Results:**
- The modal closes immediately.
- A full-screen `Spinner` component appears while the re-index request is in flight
  (`showIsResolvingKickoffLoader = true` and `isResolvingErrors = false`).
- A success toast notification appears: "Complete re-indexing started successfully".
- The `Spinner` disappears after `triggerIndexing` resolves.
- The connector detail page is still visible.
- The yellow alert banner remains visible (errors are not immediately marked resolved; they resolve
  as the re-index runs).

---

#### 5.2 Spinner Disappears Once Re-Index Is Picked Up

**Seed:** Same as 5.1. The re-index task must be picked up by a running Celery worker.

**Steps:**
1. Click "Resolve All" (scenario 5.1).
2. Wait for the Celery worker to start the index attempt (it will transition to `not_started` /
   `in_progress` with `from_beginning = true`).
3. Observe the spinner and the banner.

**Expected Results:**
- Once `isResolvingErrors` becomes `true` (the latest attempt is in-progress, from-beginning, and
  none of the currently loaded errors belong to it), the spinner condition
  `showIsResolvingKickoffLoader && !isResolvingErrors` becomes false, hiding the spinner.
- The banner transitions to the "Resolving failures" pulse state.

---

#### 5.3 Resolve All Button Is Hidden When All Loaded Errors Are Resolved

**Note:** Since `usePaginatedFetch` fetches only unresolved errors by default (no
`include_resolved` param on the errors endpoint), zero unresolved errors means the banner is
absent and the modal cannot be opened via the normal UI. This scenario therefore validates the
banner-suppression mechanism:

**Steps:**
1. Ensure the CC Pair has zero unresolved `IndexAttemptError` records.
2. Navigate to `/admin/connector/{ccPairId}`.
3. Confirm the yellow alert banner is not present.

**Expected Results:**
- The yellow banner is absent.
- The modal cannot be opened via the banner (no "View details." link).
- The "Resolve All" button is therefore unreachable via the normal UI.

---

#### 5.4 Resolve All Button Is Hidden While Re-Index Is In Progress

**Seed:** Trigger a full re-index (scenario 5.1) and re-open the modal while it is running.

**Steps:**
1. Trigger "Resolve All" (scenario 5.1).
2. Immediately click "View details." in the banner to re-open the modal.
3. Observe the modal while the re-index is `in_progress`.

**Expected Results:**
- The modal header description reads: "Currently attempting to resolve all errors by performing a
  full re-index. This may take some time to complete."
- The two explanatory body paragraphs ("Below are the errors..." and "Click the button below...") are
  not visible.
- The "Resolve All" button is not present in the footer.
- The error rows are still displayed in the table.

---

#### 5.5 Resolve All Fails Gracefully When Connector Is Paused

**Seed:** Create a file connector that is in PAUSED status with unresolved errors.

**Steps:**
1. Open the Indexing Errors modal.
2. Confirm the "Resolve All" button is visible (it renders based on `hasUnresolvedErrors`, not on
   connector status).
3. Click "Resolve All".

**Expected Results:**
- The modal closes and the spinner appears briefly.
- An error toast appears (because `triggerIndexing` returns an error message for paused
  connectors).
- The spinner disappears after the failed request.
- The banner is still visible with the "View details." link.

---

### 6. Banner Resolving State

#### 6.1 Banner Shows "Resolving Failures" While Re-Index Is In Progress

**Seed:** Trigger a full re-index from the modal.

**Steps:**
1. Trigger "Resolve All".
2. Return to the connector detail page without re-opening the modal.
3. Observe the yellow alert banner body.

**Expected Results:**
- The banner body no longer shows "We ran into some issues..." or the "View details." link.
- Instead, the banner body shows a pulsing "Resolving failures" span
  (`animate-pulse` CSS class).
- The banner heading still reads "Some documents failed to index".
- The banner remains visible until the re-index completes and errors are resolved.

---

#### 6.2 Banner Reverts to "View Details" if Resolving Attempt Gains New Errors

**Seed:** A re-index is in progress (`isResolvingErrors = true`). Force a new
`IndexAttemptError` with `index_attempt_id` matching the running attempt.

**Steps:**
1. Observe the banner in "Resolving failures" state.
2. Insert a new `IndexAttemptError` with `index_attempt_id = <running attempt id>` into the DB.
3. Wait for the 5-second polling cycle.
4. Observe the banner.

**Expected Results:**
- `isResolvingErrors` transitions back to `false` (the loaded errors now include one belonging to
  the latest attempt).
- The banner reverts to showing "We ran into some issues..." with the "View details." link.

---

### 7. Empty State

#### 7.1 Empty Table When No Items on Current Page

**Seed:** Construct a state where the `errors.items` array is empty (zero errors loaded for the
CC Pair — this requires that `indexAttemptErrors.total_items > 0` to keep the banner visible, but
a data race occurs where errors are deleted while the modal is open).

**Steps:**
1. Open the modal with some errors visible.
2. Delete all error rows from the DB while the modal is open.
3. Wait for the 5-second polling cycle.
4. Observe the table body.

**Expected Results:**
- The table body shows a single row spanning all four columns with the text "No errors found on
  this page" (centered, grayed-out `text-gray-500` style).
- The `PageSelector` may disappear (if `totalPages` drops to 1).

---

### 8. Access Control

#### 8.1 Non-Admin User Cannot Access the Errors API Endpoint

**Seed:** Ensure a basic (non-admin, non-curator) user account exists.

**Steps:**
1. Log in as the basic user.
2. Make a `GET /api/manage/admin/cc-pair/{ccPairId}/errors` request.

**Expected Results:**
- The API returns a 401 or 403 HTTP status code.
- The basic user cannot access the connector detail admin page via the UI.

---

#### 8.2 Curator User Can Access the Errors Endpoint and Open Modal

**Seed:** Ensure a curator user account exists and is assigned to the CC Pair's access group.

**Steps:**
1. Log in as the curator user.
2. Navigate to `/admin/connector/{ccPairId}` for a connector the curator can edit.
3. If unresolved errors exist, click "View details." to open the modal.

**Expected Results:**
- The modal opens successfully.
- The errors table is populated.
- The "Resolve All" button is visible (if unresolved errors exist and no re-index is running).

---

### 9. Data Freshness and Auto-Refresh

#### 9.1 New Error Appears Without Page Reload

**Seed:** Create a file connector with zero errors. Keep the connector detail page open.

**Steps:**
1. Navigate to `/admin/connector/{ccPairId}` and confirm no yellow banner.
2. Insert a new `IndexAttemptError` with `is_resolved = false` via the DB.
3. Wait up to 10 seconds (two 5-second polling cycles).
4. Observe the page.

**Expected Results:**
- The yellow alert banner appears automatically without a manual page refresh.
- No full page reload occurs.

---

#### 9.2 Errors List Refreshes While Modal Is Open

**Seed:** Create a file connector with 2 unresolved errors.

**Steps:**
1. Open the Indexing Errors modal.
2. Confirm 2 rows are visible.
3. Insert a third `IndexAttemptError` via the DB.
4. Wait up to 10 seconds for the polling cycle.
5. Observe the modal table.

**Expected Results:**
- The third error row appears in the table without closing and reopening the modal.
- If the total errors now exceed the current page size, the `PageSelector` appears if it was not
  already present.

---

### 10. Page-Level Integration

#### 10.1 Connector Detail Page Continues to Function With Modal Open

**Seed:** Create a file connector with unresolved errors.

**Steps:**
1. Navigate to `/admin/connector/{ccPairId}`.
2. Open the Indexing Errors modal.
3. With the modal open, attempt to scroll the page behind the modal.
4. Close the modal.
5. Verify the page remains functional: the Indexing section status card is visible, and the
   "Manage" dropdown button is present.

**Expected Results:**
- The modal renders over page content with a dimmed backdrop.
- Scrolling behind the modal does not cause layout issues.
- After closing the modal, all page elements are interactive and properly displayed.
- No state corruption occurs.

---

#### 10.2 Other Manage Dropdown Actions Are Unaffected

**Seed:** Create a file connector with unresolved errors.

**Steps:**
1. Navigate to `/admin/connector/{ccPairId}`.
2. Open the Indexing Errors modal and close it without clicking "Resolve All".
3. Open the "Manage" dropdown.
4. Confirm the "Re-Index", "Pause", and "Delete" items are visible and have the correct enabled
   state.

**Expected Results:**
- The Manage dropdown functions normally after interacting with the errors modal.
- No state from the modal (e.g., lingering `showIsResolvingKickoffLoader`) affects the dropdown.

---

### 11. Boundary Conditions

#### 11.1 Minimum Page Size of 3 Rows

**Seed:** Insert enough errors to exceed page size.

**Steps:**
1. Set the browser viewport to a very small height (e.g., 300px total).
2. Open the Indexing Errors modal.
3. Observe the number of rows rendered per page.

**Expected Results:**
- The page size does not drop below 3 rows (enforced by `Math.max(3, ...)` in the `ResizeObserver`
  callback).
- At least 3 rows are displayed per page regardless of available container height.

---

#### 11.2 Exactly the API Page Limit (10 Items) Displayed

**Seed:** Insert exactly 10 unresolved errors for the CC Pair.

**Steps:**
1. Open the Indexing Errors modal with a sufficiently large viewport.
2. Observe that all 10 errors are visible (assuming the dynamic page size is >= 10).

**Expected Results:**
- All 10 errors are accessible in the modal.
- No pagination is needed if the computed page size is >= 10.
- Note: If 11+ errors exist in the DB, only the first 10 (from `usePaginatedFetch`) are surfaced
  in the modal. The 11th error would require a separate API call or a larger `itemsPerPage` config
  to verify.

---

#### 11.3 Modal Opens Only When indexAttemptErrors Is Non-Null

**Steps:**
1. Observe the condition in `page.tsx`: `{showIndexAttemptErrors && indexAttemptErrors && ...}`.
2. During the initial page load (before the first poll completes), `indexAttemptErrors` is `null`.

**Expected Results:**
- Clicking "View details." while `indexAttemptErrors` is still null has no effect
  (`setShowIndexAttemptErrors(true)` is called but the modal renders only when both
  `showIndexAttemptErrors` and `indexAttemptErrors` are truthy).
- Once the first poll completes and errors are available, the modal renders normally.

---

## Test File Location

These tests should be implemented as Playwright E2E specs at:

```
web/tests/e2e/connectors/index_attempt_errors_modal.spec.ts
```

### Recommended OnyxApiClient Additions

The following methods should be added to `web/tests/e2e/utils/onyxApiClient.ts` to support
seeding and cleanup:

- `createIndexAttemptError(ccPairId, options)` - inserts an error record via `psql` or a dedicated
  test endpoint; options include `documentId`, `documentLink`, `entityId`, `failureMessage`,
  `isResolved`, `indexAttemptId`.
- `resolveAllIndexAttemptErrors(ccPairId)` - marks all errors for a CC Pair as resolved.
- `getIndexAttemptErrors(ccPairId, includeResolved?)` - calls the errors API and returns the
  parsed response.

### Cleanup Strategy

Each test must clean up its CC Pair in an `afterEach` hook:

```typescript
test.afterEach(async ({ page }) => {
  const apiClient = new OnyxApiClient(page.request);
  if (testCcPairId !== null) {
    await apiClient.deleteCCPair(testCcPairId);
    testCcPairId = null;
  }
});
```

Cascade deletes on the CC Pair will remove associated `IndexAttemptError` rows automatically.

### Polling Guidance

For scenarios that require waiting for auto-refresh to propagate state changes, use
`expect.poll()` with a 10-second timeout to avoid flaky tests:

```typescript
await expect.poll(
  async () => page.locator('[data-testid="error-banner"]').isVisible(),
  { timeout: 10000 }
).toBe(true);
```
