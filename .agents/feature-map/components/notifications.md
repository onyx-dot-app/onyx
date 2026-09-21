# Notifications

> The in-product messages Onyx shows its users: a bell popover feed, a bottom-left
> banner queue for the loud ones, release-note announcements, and an admin-authored
> site-wide banner. All four ride on one shared `Notification` table; nothing else in
> the codebase gets its own notification mechanism.

**Domain:** platform
**Edition:** CE, with one EE-only producer (license expiry warnings)
**Owns:**
`backend/onyx/db/notification.py`, `backend/onyx/server/features/notifications/`,
`backend/onyx/db/release_notes.py`, `backend/onyx/server/features/release_notes/`,
`backend/onyx/db/admin_banner.py`, `backend/onyx/server/features/admin_banner/api.py`,
`backend/onyx/db/connector_alerts.py`,
`web/src/lib/notifications/`, `web/src/lib/banner/`,
`web/src/sections/sidebar/NotificationsPopover.tsx`,
`web/src/sections/banners/BannerQueue.tsx`

---

## 1. What the user experiences

A bell icon in the sidebar opens a popover feed of notifications: new release
available, a shared assistant, a connector that broke, a license about to expire, a
site-wide announcement from an admin. Each row can be dismissed one at a time, or all
at once.

Anything loud enough (severity `WARNING` or `ERROR`) also appears as a floating card
in the bottom-left corner while it is active, one at a time, pageable if more than one
is live. Several notifications of the same type collapse into one aggregate card (for
example, "3 connectors need attention") instead of stacking.

An admin can author one site-wide banner (title, body, optional popup-on-first-visit)
from the EE admin theme settings page. Every user sees it as a normal notification;
editing or deleting it clears everyone's copy so it re-shows fresh.

---

## 2. Surfaces

### HTTP endpoints

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/notifications` | `get_notifications_api` (`notifications/api.py`) | Paginated feed for the caller. `notif_type` and `min_severity` filters. Page 0 with no filters also runs the lazy-materialization checks (`_check_for_notifications_to_create`). |
| GET | `/notifications/summary` | `get_notifications_summary_api` | Badge counts only. |
| POST | `/notifications/{id}/dismiss` | `dismiss_notification_endpoint` | Per-notification, per-user. |
| POST | `/notifications/dismiss-all` | `dismiss_all_notifications_endpoint` | Dismisses all of the caller's own undismissed rows. |
| GET | `/admin/banner` | `get_admin_banner_config` (`admin_banner/api.py`) | `FULL_ADMIN_PANEL_ACCESS` required. Reads the KV-stored banner, not the `Notification` table. |
| PUT | `/admin/banner` | `upsert_admin_banner` | Writes the KV banner, then deletes every `SYSTEM_ANNOUNCEMENT` row so it re-materializes for everyone on next read. |
| DELETE | `/admin/banner` | `delete_admin_banner` | Clears the KV banner and the `SYSTEM_ANNOUNCEMENT` rows. |

Release notes have no dedicated endpoint. `ensure_release_notes_fresh_and_notify`
(`release_notes/utils.py`) runs only from inside `get_notifications_api`.

### Frontend

- `web/src/sections/sidebar/NotificationsPopover.tsx`: the bell feed, backed by
  `useNotifications` (`web/src/hooks/useNotifications.ts`, `useSWRInfinite`).
- `web/src/sections/banners/BannerQueue.tsx`: the floating card, backed by
  `useBannerQueue` (`web/src/lib/banner/hooks.ts`), which fetches one
  severity-filtered page (`min_severity=warning`) and collapses same-type rows via
  `buildBannerQueue` (`web/src/lib/banner/queue.ts`).
- `web/src/app/ee/admin/theme/page.tsx`: the admin banner editor. It calls
  `/api/admin/banner` directly and is reachable only from the EE admin section, even
  though the backend router itself is registered unconditionally in
  `onyx/main.py:588`.

### Env / config

None. Release-note fetch cadence is Redis-cached
(`release_notes/constants.py:AUTO_REFRESH_THRESHOLD_SECONDS`, 1 hour), not env-driven.

---

## 3. Data model

One table, `Notification` (`onyx/db/models.py:Notification`), shared by every
producer:

| Column | Meaning |
|---|---|
| `notif_type` | `NotificationType` enum (`configs/constants.py:NotificationType`), the discriminator for kind and rendering. |
| `severity` | `NotificationSeverity`: `INFO` (bell only), `WARNING`/`ERROR` (also banner-worthy). Default `INFO`. |
| `user_id` | Nullable FK to `User`. `NULL` means the row is a global/unscoped notification (see §9). |
| `additional_data` | JSONB. This is the dedup key, not just payload. |
| `dismissed`, `first_shown`, `last_shown` | Per-row state. No separate read/unread flag; `dismissed` is the only durability state. |

**Dedup is enforced by a unique index** on `(user_id, notif_type,
COALESCE(additional_data, '{}'))` (migration `8405ca81cc83`, referenced in
`onyx/db/models.py:Notification.__table_args__` comment). `create_notification` and
`batch_create_notifications` (`onyx/db/notification.py`) both insert with
`ON CONFLICT DO NOTHING` against this index, so a producer calling with the same
`(user, type, additional_data)` twice is a no-op, not a duplicate row. A helper,
`_notification_additional_data_key`, normalizes SQL NULL and JSON null to `{}` so the
index and Python-side comparisons agree.

**`connector_alerts.py` has no table of its own.** It is a thin producer over the
shared `Notification` table: `notify_admins_of_connector_alert` calls
`batch_create_notifications` with `notif_type` set by the caller
(`CONNECTOR_REPEATED_ERRORS` or `CONNECTOR_INVALID`) and a dedup key built by
`connector_alert_additional_data(cc_pair_id)` (`{"cc_pair_id": ..., "link": ...}`).
`clear_connector_alerts__no_commit` deletes by that same key via
`delete_notifications_by_additional_data`. Confirmed: `connector_alerts.py` imports
nothing from a dedicated model or table; it is entirely a `Notification` producer.

### `NotificationType` values and their producers

| Kind | Producer |
|---|---|
| `REINDEX` | `server/settings/api.py` |
| `PERSONA_SHARED` | `db/persona.py` |
| `TRIAL_ENDS_TWO_DAYS` | `server/settings/api.py`; global (`user_id=None`), delivered via the settings payload, not the per-user feed (§9) |
| `RELEASE_NOTES` | `db/release_notes.py:create_release_notifications_for_versions` |
| `ASSISTANT_FILES_READY` | `indexing/adapters/user_file_indexing_adapter.py` |
| `FEATURE_ANNOUNCEMENT` | `server/features/build/utils.py:ensure_build_mode_intro_notification`, `notifications/utils.py:ensure_permissions_migration_notification` |
| `SYSTEM_ANNOUNCEMENT` | `notifications/utils.py:ensure_system_announcement_notification`, sourced from the admin banner KV value |
| `CONNECTOR_REPEATED_ERRORS`, `CONNECTOR_INVALID` | `background/celery/tasks/docprocessing/tasks.py`, `background/indexing/run_docfetching.py`, `db/credentials.py`, `db/connector_credential_pair.py` (via `connector_alerts.py`) |
| `LICENSE_EXPIRY_WARNING` | `ee/onyx/utils/license_notifications.py` (EE only) |
| `SCHEDULED_TASK_FAILED`, `SCHEDULED_TASK_AWAITING_APPROVAL`, `SCHEDULED_TASK_PRE_APPROVED_ACTION`, `APPROVAL_REQUESTED` | `server/features/build/scheduled_tasks/executor.py`, `sandbox_proxy/addons/gate.py` (Craft/build-mode) |

---

## 4. How it works

### Creation

Every producer goes through `create_notification` (single row, idempotent-read
semantics) or `batch_create_notifications` (many users, one insert). Both live in
`onyx/db/notification.py` and both rely on the unique index for idempotency rather
than a pre-check-then-insert race.

Two producers materialize lazily on read rather than from a background job:
- `ensure_system_announcement_notification` (`notifications/utils.py`): reads the
  admin's KV-stored banner (`admin_banner.py:get_admin_banner`) and creates a
  `SYSTEM_ANNOUNCEMENT` row for the requesting user if one is set.
- `ensure_release_notes_fresh_and_notify` (`release_notes/utils.py`): fetches
  `changelog.mdx` from GitHub (ETag-cached in Redis, refreshed at most hourly), parses
  entries newer than the running version, and calls
  `create_release_notifications_for_versions` to batch-create one row per eligible
  active user per version.

Both run from `get_notifications_api` (`notifications/api.py:_check_for_notifications_to_create`
and the per-banner-type ensure loop), throttled per-user for 5 minutes
(`ENSURE_THROTTLE_SECONDS`, a `TTLCache`) when the request is the banner queue's
severity-only poll, so a background job is not required for these to appear.

License expiry is the one EE-only, genuinely background producer:
`check_license_expiry_notifications_task` (`ee/onyx/background/celery/tasks/license_notifications/tasks.py`)
runs on a schedule, computes an `ExpiryWarningStage` from the stored license, and calls
`notify_admins_for_stage` (`ee/onyx/utils/license_notifications.py`), which
batch-creates the notification and sends an email to newly-notified admins. A
same-request fallback, `ensure_license_expiry_notification_for_user`, materializes the
requesting admin's row on read (no email) so the banner does not wait for the daily
task; it no-ops under `MULTI_TENANT`.

### Delivery

The frontend polls two endpoints: the mixed feed (`GET /notifications`, paginated,
newest-undismissed-first) for the bell, and a severity-filtered fetch
(`min_severity=warning`) for the banner queue. `buildBannerQueue`
(`web/src/lib/banner/queue.ts`) groups same-type rows into one slot, most urgent
first, so the banner never shows two notifications of the same kind at once.

### Dismissal

Per user, per row: `POST /notifications/{id}/dismiss` sets `dismissed=True`
(`db/notification.py:dismiss_notification`) after `get_notification_by_id` checks the
caller owns the row (or holds `FULL_ADMIN_PANEL_ACCESS` for a global row).
`dismiss-all` dismisses every undismissed row for the caller
(`dismiss_user_notifications`). There is no global "dismiss for everyone."

The one exception is `TRIAL_ENDS_TWO_DAYS`, a global (`user_id=None`) row: a
non-admin cannot dismiss it server-side without hiding it for the whole tenant, so
the frontend dismisses it client-side only, via a browser cookie
(`web/src/lib/banner/hooks.ts:DISMISSED_NOTIFICATION_COOKIE_PREFIX`).

---

## 5. Contracts and invariants

1. **A dedup key (`notif_type` + `additional_data`) must stay stable once shipped.**
   `ensure_permissions_migration_notification` comments this explicitly: changing the
   `"feature"` string in `additional_data` breaks the unique-index dedup and
   re-notifies every user. The same applies to `connector_alert_additional_data`'s
   `cc_pair_id` key and the release notes `version` key.
2. **Dismissal is per user unless the row itself is global (`user_id is NULL`).** A
   new producer must decide up front whether its notification is per-user or global;
   there is no per-notification override of dismissal scope.
3. **A new producer must pick a `NotificationType` that matches its actual
   semantics**, not reuse an existing one for convenience. `severity` and
   `additional_data.link` conventions differ by consumer (`BannerQueue`'s
   `bannerTypeConfig`, `NotificationsPopover`'s icon map), so reusing a kind with
   different data shapes breaks that kind's existing renderer.
4. **`severity` is set only on the first insert of a dedup group.** A later call with
   the same key that conflicts on insert keeps the original severity
   (`batch_create_notifications` docstring). An escalation (for example, a louder
   license stage) needs its own `additional_data` (the license flow varies `stage`).
5. **Clearing a type-wide set of rows (`delete_notifications_by_type`,
   `delete_notifications_by_additional_data`) is the re-show mechanism.** The admin
   banner's edit path relies on `delete_notifications_by_type(SYSTEM_ANNOUNCEMENT)` to
   force re-materialization; skipping it means an edited banner never reaches users
   who already dismissed the old one.
6. **`connector_alerts.py`'s `notify_admins_of_connector_alert` never raises; it rolls
   back and logs on failure**, so a notification failure cannot poison the connector
   update transaction that called it.

---

## 6. Relationships

**Depends on**
- [[auth-and-identity]]: `require_permission(Permission.BASIC_ACCESS)` gates the user
  endpoints; `FULL_ADMIN_PANEL_ACCESS` gates the admin banner and cross-user
  notification reads (`get_notification_by_id`'s admin-can-read-global-rows branch).
- [[multi-tenancy]]: `Notification` lives in the per-tenant schema like other tables;
  the admin banner's KV value is scoped through the same per-tenant KV store
  (`onyx/key_value_store/factory.py`), confirmed by the test fixture
  `tenant_context` in `test_admin_banner_notification.py`.
- [[editions-and-gating]]: license-expiry notifications are EE-only
  (`ee/onyx/utils/license_notifications.py`) and no-op under `MULTI_TENANT`.
- [[background-jobs]]: `check_license_expiry_notifications_task` is a scheduled Celery
  task; every other producer runs inline on a request or another background job
  (indexing, docprocessing).
- [[cc-pairs-and-credentials]]: `connector_alerts.py` is called from
  `db/connector_credential_pair.py`, `db/credentials.py`, and the indexing/docprocessing
  background tasks whenever a connector repeatedly errors or its credentials go
  invalid.
- [[chat-frontend]]: the sidebar bell and the banner queue mount alongside the chat
  shell (`web/src/layouts/chromes/AppChrome.tsx`).

**Depended on by**
- Nothing outside this component reads `Notification` rows back for its own logic;
  every consumer is a display surface.

---

## 7. Blast radius

| If your change... | Also check |
|---|---|
| adds a `NotificationType` | the frontend `NotificationType` enum mirror (`web/src/lib/notifications/interfaces.ts`) must add the same value, plus an icon mapping and, if banner-worthy, a `bannerTypeConfig` entry in `BannerQueue.tsx` |
| changes an existing kind's `additional_data` shape | every reader of that shape: `BannerQueue.tsx`'s `link`/aggregate lookups, and any other producer that reuses the same kind |
| changes the dedup key for an existing kind | every existing undismissed row of that kind stops matching new inserts, so already-dismissed users get re-notified; this is the mechanism the admin banner edit path uses deliberately, so make sure a change elsewhere is intentional, not accidental |
| changes dismissal semantics (adds a global dismiss, or changes per-user scoping) | `get_notification_by_id`'s ownership check, and the `TRIAL_ENDS_TWO_DAYS` cookie-based path, which assumes non-admin users cannot dismiss global rows server-side |
| touches `create_notification` / `batch_create_notifications` | the unique index migration `8405ca81cc83` and every producer's assumption that a duplicate call is a no-op, not an error |
| touches the admin banner KV schema (`AdminBanner` model) | `web/src/app/ee/admin/theme/page.tsx` and `ensure_system_announcement_notification`'s mapping of banner fields to notification title/description |

---

## 8. How to verify a change

### Tests

```bash
cd backend && uv run pytest tests/external_dependency_unit/db/test_notification.py
cd backend && uv run pytest tests/external_dependency_unit/db/test_admin_banner_notification.py
cd backend && uv run pytest tests/external_dependency_unit/ee/onyx/utils/test_license_notifications.py
cd backend && uv run pytest tests/external_dependency_unit/ee/onyx/background/celery/test_license_notifications_task.py
cd backend && uv run pytest tests/unit/ee/onyx/background/celery/tasks/license_notifications
```

No release-notes-specific test file exists as of this writing; the parsing and
GitHub-fetch logic in `release_notes/utils.py` is unverified by an automated test. No
playwright coverage was found for the bell popover or banner queue.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open `http://localhost:3000`, sign in as `admin_user@example.com` /
   `TestPassword123!`.
3. As admin, PUT a banner: `curl -X PUT http://localhost:3000/api/admin/banner -H
   "Content-Type: application/json" -d '{"title":"test","content":"hello"}'` (with the
   session cookie attached). Reload the app; the bell badge should increment and a
   banner card should appear bottom-left.
4. Dismiss it from either surface. Refresh; it should not reappear.
5. Re-PUT the same banner content. It should reappear (the edit path deletes and
   re-materializes `SYSTEM_ANNOUNCEMENT` rows).
6. Delete the banner (`DELETE /api/admin/banner`); it should disappear for good.

### What "working" looks like

- Duplicate calls to a producer (same user, type, `additional_data`) never create a
  second row.
- Dismissing a notification removes it from the bell and banner without a reload, and
  it stays dismissed after a reload.
- Editing the admin banner re-shows it to users who already dismissed the old text.

---

## 9. Footguns

- **`Notification` is a shared substrate, not a single feature.** Six-plus unrelated
  producers (connector health, release notes, license expiry, persona sharing, build
  mode scheduled tasks, admin announcements) all write the same table through the
  same two insert helpers. A schema or dedup change here has a wide, easy-to-miss
  blast radius across producers that never call each other.
- **`user_id IS NULL` means global, not "unassigned."** `TRIAL_ENDS_TWO_DAYS` is the
  one kind that uses this today, and it is delivered outside the normal per-user feed
  (through the settings payload) specifically because a global row cannot be
  dismissed per-user server-side. The frontend fakes per-user dismissal with a cookie
  instead.
- **The admin banner has two storage locations that must stay in sync by hand.** The
  authored content lives in the KV store (`admin_banner.py`); its user-facing
  materialization is a `Notification` row created on read. There is no direct display
  endpoint for the banner itself, so a bug in `ensure_system_announcement_notification`
  can make `GET /admin/banner` (admin view) and what users actually see diverge.
- **The admin banner's backend router is not EE-gated, only its editor UI is.**
  `admin_banner_router` is registered unconditionally in `onyx/main.py:588`; only the
  frontend page that calls it (`web/src/app/ee/admin/theme/page.tsx`) lives under the
  EE admin section. A CE deployment with API access could still set it.
- **A row's `severity` is fixed at first insert for its dedup group.** A producer that
  wants to escalate urgency without spamming a new row must vary `additional_data`
  (the license flow's `stage` field), or the escalation silently never shows.
- **`show_as_popup` on the admin banner is stored but not delivered anywhere.** A
  `TODO` in `web/src/lib/banner/hooks.ts` notes that `additional_data` on the
  synthesized `SYSTEM_ANNOUNCEMENT` notification is always `{}`, so the frontend has
  no way today to know it should also show a first-visit popup.

---

Cross-links: [[auth-and-identity]], [[multi-tenancy]], [[editions-and-gating]],
[[background-jobs]], [[cc-pairs-and-credentials]], [[chat-frontend]]
