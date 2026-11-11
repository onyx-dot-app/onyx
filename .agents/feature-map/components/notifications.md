# Notifications

> The in-product messages Onyx shows a user: the bell feed, the banner queue
> for loud messages, release notes and the admin site-wide banner. Every
> producer writes one table through two idempotent insert helpers.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. License expiry warnings are EE and self-hosted only.

---

## User experience

- **A user** sees a feed of notifications: a new release, a shared agent,
  files ready, a Craft task that failed or waits for approval, an
  announcement. The user dismisses one or all of them. A dismissed
  notification stays dismissed after a reload.
- **A WARNING or ERROR notification** also stays in view until the user
  dismisses it. The user sees these one at a time. Notifications of one type
  group together. For connector alerts the user sees a count, and one dismiss
  clears them all. For other types, the user sees how many more wait.
- **An admin** sees connector alerts when a connector fails again and again or
  its credential becomes invalid. The alert clears when the connector is fixed.
  On self-hosted EE, an admin also sees license expiry warnings that grow louder
  as the date nears, and gets an email at each new stage.
- **An admin** writes one site-wide banner (title and body) on the EE theme
  page. Every user sees it with the other loud notifications. When the admin
  edits it, users who dismissed the old text see the new one.
- **An air-gapped deployment** (`ONYX_AIRGAPPED`) gets no release notes.

When a producer fails, the user sees nothing: the notification does not
appear, and the action that caused it still succeeds.

---

## Scope

This component holds the notification table and its insert, read and dismiss
helpers, the feed API with its read-time producers, release notes, the admin
banner, the connector alert helpers, the EE license expiry warnings, and the
web bell and banner queue.

Producers own the decision to notify. [[cc-pairs-and-creds]] and
[[indexing-pipeline]] raise and clear connector alerts. [[agents-personas]]
notifies on sharing. [[file-store-and-user-files]] notifies when files are
ready. [[craft-scheduled-tasks]] notifies on task failure.
[[craft-external-apps]] notifies on a pending approval (`APPROVAL_REQUESTED`,
from the egress proxy). [[billing]] owns the license state that the expiry
warning reads. The admin banner editor sits on the theme page
([[whitelabelling-and-theme]]).

---

## Architecture

```
producer ── create_notification / batch_create_notifications ── INSERT ... ON CONFLICT DO NOTHING
                                                                  (unique on user, type, additional_data)
GET /notifications ── page 0: lazy ensures ── feed (caller's own rows only)
   ├─ unfiltered: build-mode intro, permissions migration, release notes
   └─ SYSTEM_ANNOUNCEMENT and LICENSE_EXPIRY_WARNING (throttled on the banner poll)
web: bell (useNotifications) + banner queue (min_severity=warning, buildBannerQueue)
```

**Idempotent inserts.** A unique index on `(user_id, notif_type,
COALESCE(additional_data, '{}'))` decides what a duplicate is. Only the
migration
`backend/alembic/versions/8405ca81cc83_notifications_constraint.py` creates
it. `db/models.py:Notification` names it in a comment but does not declare it.
`db/notification.py:create_notification` reads first and then inserts with
`ON CONFLICT DO NOTHING`. `batch_create_notifications` inserts for many users
in one statement. A producer can call either one again and again with no
duplicate rows.

**Lazy producers.** Some rows appear on read, not from a job.
`server/features/notifications/api.py:get_notifications_api` runs the ensures
on page 0. An unfiltered request runs `_check_for_notifications_to_create`. The
banner queue polls with `min_severity` every minute per tab, so its ensures run
at most once per user per `ENSURE_THROTTLE_SECONDS` in each process.
`server/features/release_notes/utils.py:ensure_release_notes_fresh_and_notify`
fetches the changelog from GitHub at most once an hour, with an ETag and a lock
in the shared cache, and creates one row per active user per new version.

**The admin banner** lives in the key-value store (`db/admin_banner.py`).
`server/features/notifications/utils.py:ensure_system_announcement_notification`
copies it into a per-user `SYSTEM_ANNOUNCEMENT` row with WARNING severity. The
admin PUT and DELETE call `delete_notifications_by_type(SYSTEM_ANNOUNCEMENT)`,
so the next read creates fresh rows and a dismissed banner shows again. The
theme page saves through `/api/admin/banner` and then calls
`invalidateNotificationCaches`, so the banner queue and the bell fetch again.

**License expiry (EE).** The scheduled task in
`backend/ee/onyx/background/celery/tasks/license_notifications/` computes a
stage and calls `ee/onyx/utils/license_notifications.py:notify_admins_for_stage`,
which creates the rows and emails newly notified admins. The read path calls
`ensure_license_expiry_notification_for_user` through
`fetch_ee_implementation_or_noop`, with no email. It does nothing under
`MULTI_TENANT`.

**Global rows.** A row with `user_id` null is global. The feed returns only the
rows of the caller. `backend/onyx/server/settings/api.py:get_settings_notifications`
returns the global `TRIAL_ENDS_TWO_DAYS` row in the settings payload, and the
banner queue adds it to its list.

---

## Contracts and traps

1. `additional-data-is-dedup-key` **`additional_data` is the dedup key, not
   only a payload.** Once a producer ships, its key must not change. A changed
   key does not match the old rows, so every user gets the notification again,
   even users who dismissed it. `ensure_permissions_migration_notification`
   warns about its `feature` value. The same holds for the connector alert key
   (`db/connector_alerts.py:connector_alert_additional_data`, which includes the
   admin `link`) and the release notes key
   (`db/release_notes.py:create_release_notifications_for_versions`), which
   holds the `version` and the full docs `link` with its UTM parameters. A
   change to either link format notifies every user again.
2. `severity-first-insert-only` **`severity` is set only on the first insert
   of a dedup group.** A later call to `db/notification.py:create_notification`
   with the same key keeps the old severity.
   An escalation needs its own key, as the license flow does by putting
   `stage` in `additional_data`.
3. `dismissed-never-returns` **A dismissed row never comes back by itself.**
   The dedup index returns the dismissed row. To show something again, delete
   the rows (`db/notification.py:delete_notifications_by_type` or
   `db/notification.py:delete_notifications_by_additional_data`) or use a new key. The admin
   banner edit and the connector alert clear depend on this.
4. `connector-alert-rollback`
   **`db/connector_alerts.py:notify_admins_of_connector_alert` rolls back the
   session of the caller on failure.** It never raises, so a failed alert
   cannot break the connector update. Because it calls `rollback`, the caller
   must have no uncommitted work on the session when it calls it.
5. `global-rows-not-per-user` **Global rows cannot be dismissed per user on the
   server.** Dismissing a global row hides it for the whole tenant. The banner
   queue records the dismissal of a global type in a cookie
   (`web/src/lib/banner/hooks.ts:DISMISSED_NOTIFICATION_COOKIE_PREFIX`).
   `db/notification.py:get_notification_by_id` lets only a full admin touch a
   global row. The unique index does not deduplicate global rows, because
   Postgres treats each null `user_id` as distinct. Only the read before the
   insert in `create_notification` stops a duplicate, so two concurrent
   inserts can both succeed. A new producer must choose per-user or global
   before it ships.
6. `web-enum-mirrored` **The web enum mirrors `NotificationType` by hand.** A
   new type needs a value in `web/src/lib/notifications/interfaces.ts`, an
   icon, and a `bannerTypeConfig` entry in
   `web/src/sections/banners/BannerQueue.tsx` if it needs its own link or
   aggregate text. Severity alone decides whether it shows as a banner.
7. `type-implies-data-shape` **Reusing a type means reusing its data shape.**
   `web/src/sections/banners/BannerQueue.tsx` reads `additional_data.link` and
   the aggregate text by type. A producer that writes a different shape under
   an existing type breaks the card of that type.
8. `read-ensure-no-refresh` **A read-path ensure must not refresh
   `last_shown`.** The ensures in `server/features/notifications/utils.py` and
   the build-mode intro pass `refresh_existing=False` to `create_notification`,
   so repeated GETs return the same response. A new ensure must do the same.

---

## Known issues

- **Two scheduled-task types have no producer.**
  `SCHEDULED_TASK_AWAITING_APPROVAL` and `SCHEDULED_TASK_PRE_APPROVED_ACTION`
  are defined in `configs/constants.py:NotificationType` but never created.
- **`TRIAL_ENDS_TWO_DAYS` and `REINDEX` have no producer in this
  repository.** `backend/onyx/server/settings/api.py:get_settings_notifications` reads the
  global trial row and an admin's `REINDEX` rows, but no backend code creates
  either.
- **The admin banner API is not gated to EE.** `admin_banner_router` mounts in
  `backend/onyx/main.py` for every edition, and `/admin/banner` has no entry in
  `backend/ee/onyx/configs/license_enforcement_config.py:PATH_PREFIX_MIN_TIER`.
  Only the editor page is under the EE admin tree, so a CE admin can set a
  banner through the API.
- **`show_as_popup` is stored but never delivered.** The `SYSTEM_ANNOUNCEMENT`
  row has `additional_data` `{}`, so the web cannot tell whether to show a
  first-visit popup (TODO in `web/src/lib/banner/hooks.ts`).
- **Release-note rows are created only when a fetch returns new content.**
  `ensure_release_notes_fresh_and_notify` creates rows after a 200 response.
  A 304 or a fresh cache creates none. A user who becomes active later gets no
  row for versions already fetched. On cloud the fetch state is shared across
  tenants, so only the tenant whose request did the fetch gets rows. Confirm
  the intent before you rely on release notes reaching every user.
- **The ensure throttle is per process.** With several API server replicas,
  the ensures of a user can run more often. Each ensure is idempotent, so this
  costs only queries.

---

## Dependencies

- [[authorization]]: `BASIC_ACCESS` for the feed, and `FULL_ADMIN_PANEL_ACCESS` for the banner and global rows.
- [[editions-and-gating]]: `fetch_ee_implementation_or_noop` selects the EE license ensure.
- [[multi-tenancy]]: rows and the banner value are per tenant, and the release-notes ETag, fetch time and lock are in the shared cache.
- [[billing]]: the license state that drives the expiry stages.
- [[background-jobs]]: the scheduled task that sends the license expiry warnings and emails.

---

## Recipes

- `add-notification-type` **Add a notification type.** Add the value to
  `configs/constants.py:NotificationType` and to the web enum
  ([[#web-enum-mirrored]]). Pick a stable `additional_data` key
  ([[#additional-data-is-dedup-key]]), a severity, and per-user or global
  scope ([[#global-rows-not-per-user]]). Call `create_notification` for one
  user or `batch_create_notifications` for many. For a producer that runs in a
  job, copy `db/connector_alerts.py:notify_admins_of_connector_alert`. To show
  it on read instead, copy
  `server/features/notifications/utils.py:ensure_permissions_migration_notification`
  and call it from `_check_for_notifications_to_create`
  ([[#read-ensure-no-refresh]]). List the producers with
  `git grep -nE "create_notification\(|batch_create_notifications\(" backend`.
- `show-admin-banner` **Show the admin banner by hand.** As an admin, PUT `/api/admin/banner`
  through the frontend and reload. Dismiss the card, reload, and confirm it
  stays hidden. PUT new text and confirm it shows again.
- `investigate-notification` **Investigate a notification that does not show,
  or shows again.** Query
  the `notification` table for the user and type, and compare
  `additional_data` with the key the producer writes. A missing row with a
  dismissed match means [[#dismissed-never-returns]]. A second row means the key
  changed ([[#additional-data-is-dedup-key]]) or the row is global
  ([[#global-rows-not-per-user]]). A banner that stays at INFO means
  [[#severity-first-insert-only]].

---

## Verification

- Backend: `backend/tests/external_dependency_unit/db/` (the notification and
  admin banner tests) and
  `backend/tests/unit/onyx/server/features/release_notes/`.
- License expiry: `backend/tests/external_dependency_unit/ee/onyx/` and
  `backend/tests/unit/ee/onyx/background/celery/tasks/license_notifications/`.
- Banner queue grouping: `web/src/lib/banner/`.
