# CC-Pairs and Credentials

> The connector config, the credential that holds the secret for one source
> account, and the connector-credential pair (cc-pair) that joins them and is
> the unit that indexing, access, scheduling and deletion act on.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. EE adds data-access and manage-access groups, the perm-synced access types, and real secret encryption.

---

## User experience

- **An admin adds a connector.** The admin picks a source, fills in its config,
  and authenticates: pastes a secret, uploads a key file, or goes through an
  OAuth redirect. The admin picks who can see the documents (public, private,
  or a perm-synced type) and saves. The pair starts `SCHEDULED`, and the status
  page shows it move through `INITIAL_INDEXING` to `ACTIVE`, with its runs and
  errors.
- **An admin manages a pair.** The admin can pause and resume it, rename it,
  change its refresh, prune and check schedules, start a prune, cancel an index
  attempt, resolve failed runs, and delete it. A pause stops new work and keeps
  what is indexed. A delete removes the documents that only this pair indexed,
  in the background, and keeps documents that another pair also indexes.
- **A user reuses a credential.** A user a credential is shared with can pair
  it. A source with account-bound settings, such as a site URL, accepts a
  shared credential only with the settings of a pair that already uses it.
- **When it fails,** the admin sees the error at once: a refused credential, a
  duplicate pairing (`CONFLICT`), a source that does not support permission
  sync, or a failed connector validation. A failed creation leaves no connector
  behind. Errors after creation show on the status page as failed runs and as a
  repeated-error alert.

---

## Scope

This component owns:
- the connector, credential and cc-pair records, their lifecycle routes
  (create, pair, pause, rename, schedule, delete trigger) and the status page;
- credential storage: the encrypted column types, `SensitiveValue`, masking in
  responses, and the rule for using another user's credential;
- the per-pair run feed and run resolution on the connector and status pages;
- the connector OAuth authorization flow.

Its neighbours own:
- [[connectors]]: what a connector does once it runs, credential bindings, and
  the connector edit flow, which changes the config and the access type of an
  existing pair.
- [[connector-capability-checks]]: the checks on a credential and config, the
  report rows, and the indexing hold on a first attempt.
- [[indexing-pipeline]]: index attempts, scheduling (`should_index`) and
  targeted reindex.
- [[background-jobs]]: the deletion and pruning task flows.
- [[access-control]]: the cc-pair access levels and roles, data-access groups,
  and the document ACL built from the pair's access type.
- [[permission-sync]]: what a perm-synced access type means, and the rules a
  pairing must meet to choose one.
- [[editions-and-gating]]: the CE and EE split that decides whether secrets are
  encrypted.

---

## Architecture

```
Connector (config, schedules)  1 ──< ConnectorCredentialPair >── 1  Credential (secret)
                                      │ status, access_type, name, watermarks
                                      ├─< document_by_connector_credential_pair  (keyed by connector_id, credential_id)
                                      ├─< document set, user group, data-access rows  (keyed by cc_pair.id)
                                      └─< IndexAttempt, permission sync attempts   [[indexing-pipeline]], [[permission-sync]]
```

**Create.** Three routes create a pair.
`backend/onyx/server/documents/connector.py:create_connector_with_credential`
creates the connector and pairs it in one call, and promotes a draft credential
from the form. `backend/onyx/server/documents/cc_pair.py:associate_credential_to_connector`
pairs an existing connector and credential; it also needs edit access on every
pair the connector already has.
`backend/onyx/server/documents/connector.py:create_connector_with_mock_credential`
serves sources with no secret: it creates an empty credential, refuses
`SYNC_RESTRICTED`, and with `paused=true` creates the pair `PAUSED` and starts
no indexing. All three run the same steps in this order: a scope check on the
manage groups (`authorize_pairing`; the mock route calls `assert_within_scope`
itself), `connectors/pairing_access.py:validate_pairing_access` (access-type
rules, [[permission-sync]]), `connectors/factory.py:validate_ccpair_for_user`
(the credential use rule, then the pairing checks of
[[connector-capability-checks]]), then `add_credential_to_connector`. Each then
sends `CHECK_FOR_INDEXING` at once so the first attempt does not wait for the
beat. Craft's user library calls `add_credential_to_connector` directly for its
own private pair ([[craft-sessions]]).

**Pause and resume.** `backend/onyx/server/documents/cc_pair.py:update_cc_pair_status`
takes the pair's row lock (`lock_connector_credential_pair_row`) and holds it
until the status commit. Attempt creation takes the same lock, so a pause either
sees and cancels a new attempt, or the creation sees `PAUSED`. The cancellations
commit with the `PAUSED` status: a cancel committed earlier frees the pair's sync
lock while the beat still sees the pair `ACTIVE`. The route revokes the Celery
tasks after the commit. [[#pause-stops-background-work]] lists what a pause
must stop.

**Delete.** The UI delete calls `POST /manage/admin/deletion-attempt`
(`server/manage/administrative.py:create_deletion_attempt_for_connector_id`).
It takes the row lock, cancels attempts, sets `DELETING`, and sends
`CHECK_FOR_CONNECTOR_DELETION`. The deletion task flow is in
[[background-jobs]]. For a File connector, the route deletes the uploaded files
from the file store at once.

**Credential reads.** `EncryptedJson` and `EncryptedString`
(`db/models.py:EncryptedJson`) wrap every read in
`utils/sensitive.py:SensitiveValue`. It raises on `str()`, iteration and
indexing, so each caller must call `get_value(apply_mask=...)`. API responses
build the secret through
`backend/onyx/server/documents/models.py:CredentialSnapshot.from_credential_db_model`,
which masks when the caller passes `mask_credential_prefix`.

**Run feed.** `db/cc_pair_runs.py:get_cc_pair_run_page` unions index attempts,
doc permission syncs, group syncs, prunes and check runs into one page, newest
first. A failed run is superseded when a newer run of the same kind on the same
history succeeded or failed. An admin can resolve a run
(`db/cc_pair_run_resolution.py:resolve_runs__no_commit`). The fleet view on the
status page reads the same builders across every pair the caller can read
(`backend/onyx/server/documents/index_monitoring.py`).

---

## Contracts and traps

1. `pair-is-the-unit` **The cc-pair, not the connector, is what indexing,
   access, document sets, user groups and deletion act on.** One `Connector` row
   can serve several pairs with different credentials and access types. Status,
   access type, sync watermarks and deletion state live on
   `db/models.py:ConnectorCredentialPair`. Code that keys off `connector_id`
   alone is almost always wrong.
2. `pair-id-is-not-the-primary-key` **`ConnectorCredentialPair.id` is unique but
   is not the primary key.** The key is `(connector_id, credential_id)`.
   Document sets, user groups and attempts reference `id`.
   `db/models.py:DocumentByConnectorCredentialPair` references the composite
   pair instead. A join on the wrong column compiles and returns nothing.
3. `one-pair-per-connector-credential` **A connector and a credential pair at
   most once.** `backend/onyx/server/documents/cc_pair.py:associate_credential_to_connector` returns `CONFLICT` for a
   duplicate before validation runs, because validation would overwrite the live
   pair's check report. A caller must not treat a duplicate as a success.
4. `connector-settings-are-shared` **Refresh, prune and check frequencies live
   on the `Connector` row, so they apply to every pair on it.**
   `backend/onyx/server/documents/cc_pair.py:update_cc_pair_property` checks
   that the user can operate every pair on the connector. A new connector-level
   setting needs the same check. A pair-level setting goes on the pair.
5. `delete-only-through-deleting` **Only the `DELETING` flow removes
   documents.** It keeps a document that another pair still indexes
   ([[background-jobs]]). Two other routes delete rows with no index cleanup:
   `backend/onyx/server/documents/connector.py:delete_connector_by_id` calls
   `backend/onyx/db/connector.py:delete_connector`, and
   `backend/onyx/server/documents/cc_pair.py:dissociate_credential_from_connector`
   calls `backend/onyx/db/connector_credential_pair.py:remove_credential_from_connector`. Neither sets `DELETING` or starts a
   cleanup task, and the chunks stay in the index. A connector delete cascades
   to its pairs and, through the `connector_id` foreign key, to their
   `document_by_connector_credential_pair` rows. The dissociate route deletes
   only the pair row. Its document rows stay, because they key on the connector
   and credential, which both still exist, so the documents still count the
   deleted pair. Do not route an established pair's delete through either
   route.
6. `status-route-cannot-delete` **The status route accepts only `ACTIVE` and
   `PAUSED`.** `backend/onyx/server/documents/cc_pair.py:update_cc_pair_status` needs only
   operate access. Accepting `DELETING` there would
   let an operator delete a pair, which needs edit access.
7. `pause-stops-background-work` **A pause must cancel work, not only change the
   column.** `backend/onyx/server/documents/cc_pair.py:update_cc_pair_status` sets the stop fence, cancels open attempts
   and queued syncs, and drops a queued prune under the row lock. A status write
   that skips these leaves a running task unaware. A started prune and a running
   doc permission sync stop on the fence. A running group sync finishes, because
   a stopped one would remove group memberships after resume.
8. `credential-reads-masked` **No API response returns a secret unmasked by
   default.** `MASK_CREDENTIAL_PREFIX` defaults to true. The credential
   routes, the pair detail and the connector status also mask each credential
   that
   `backend/onyx/server/documents/credential.py:credential_ids_to_mask` returns
   for the caller, whatever the setting. The user-group and document-set views
   follow the setting alone. A new route that returns credential JSON must go
   through `backend/onyx/server/documents/models.py:CredentialSnapshot` and default to
   masked. `backend/onyx/utils/encryption.py:reject_masked_credentials` and
   `backend/onyx/utils/encryption.py:restore_masked_credentials` let a form send a masked value back without
   overwriting the real secret.
9. `sensitive-value-not-mutable` **Do not mutate the dict that
   `SensitiveValue.get_value(apply_mask=False)` returns.** It is the cached
   decrypted value, so a change desyncs the cache from the stored bytes. Copy it
   first.
10. `encryption-needs-ee-code-and-key` **Secrets are encrypted only when EE code
    is loaded and `ENCRYPTION_KEY_SECRET` is set.** Both conditions are in
    [[editions-and-gating]]. The column type name `EncryptedJson` does not mean
    the bytes are encrypted. A change to
    `utils/variable_functionality.py:set_is_ee_if_available`, to
    `utils/variable_functionality.py:is_ee_available`, or to the `ee` copy in `backend/Dockerfile` changes
    storage for every deployment.
11. `credential-use-rule` **Every use of a credential goes through
    `connectors/factory.py:assert_user_can_use_credential`.** A pairing, a swap,
    an edit and a check run all call it before anything builds a connector. The
    owner can use it. A global `MANAGE_CONNECTORS` holder can use one with no
    owner. A user it is shared with can use it only when its source has no
    account-bound fields or no real secret, or the bound values match a pair
    that already uses it ([[connectors]] owns the bindings). The stored `source` of a credential may
    differ from the connector's source when the two share a credential family.
12. `access-type-paths` **A change to an existing pair's access type must
    re-gate and resync.** The connector edit flow
    (`db/connector_edit_requests.py:apply_access_change__no_commit`,
    [[connectors]]) and the Community downgrade
    (`ee/onyx/db/community_downgrade.py:make_all_cc_pairs_public__no_commit`,
    [[billing]]) change it. A new path must call
    `connectors/pairing_access.py:validate_pairing_access`
    first, unless it only widens to public, and must mark the pair's documents
    for sync, or the index keeps the old chunk ACLs.
13. `google-oauth-callback-by-route` **The Google OAuth callback picks Gmail or
    Drive from its `[connector]` route parameter.**
    `web/src/app/admin/connectors/[connector]/auth/callback/route.ts` accepts
    only `gmail` and `google-drive` and forwards to that source's backend
    callback. A shared Google credential returns scopes for both sources, so
    never pick the source by searching the callback URL for `gmail`.

**Who may act on a pair.** The levels come from
`get_connector_credential_pair_from_id_for_user`; [[access-control]] owns how a
user reaches each level.

| Action | Level |
|---|---|
| Read the detail page, runs, errors, hierarchy breakdown | READ |
| Pause, resume, rename, change schedules, prune, start a permission or group sync, cancel an attempt, resolve runs, release the indexing hold | OPERATE |
| Delete, set data-access or manage-access groups, pair a credential to a connector that has pairs | EDIT (on every existing pair of the connector, for pairing) |

**Who may act on a credential.** `backend/onyx/db/credentials.py:_add_user_filters` applies
the three levels of `CredentialAccessLevel`. Drafts are hidden from all but the
owner's form.

| Who | Use: list, pair, swap, run checks | Change values, sharing or name | Delete |
|---|---|---|---|
| The owner | Yes | Yes | Yes |
| A global `MANAGE_CONNECTORS` holder | A credential with no owner, with `admin_public`, or of a source with no real secret | No | A credential with no owner, but never the seeded public credential |
| A connector manager of a group the credential is shared with (EE) | Yes | No | No |
| Anyone else | No | No | No |

Use access does not finish the check: [[#credential-use-rule]] can still refuse
a shared credential of a source with bound fields. `curator_public` grants
nothing. A global admin cannot change a credential that another user owns, even
on the admin routes.

---

## Decisions

- **Connector and credential are separate rows.** One admin can index several
  spaces with one credential, and several admins can run one config with their
  own credentials (`ConnectorCredentialPair` docstring).
- **The pause route returns at once.** It sets signals and lets running tasks
  stop themselves, so the admin does not wait on a worker.
- **Resolving a run leaves its error rows open.** Resolution adds a
  `CCPairRunResolution` row and keeps `IndexAttemptError.is_resolved` false,
  because the poll cursor and the targeted reindex (Retry) read that flag.
  A reader that counts open errors must also exclude resolved runs, as
  `db/index_attempt.py:get_open_error_counts_for_index_attempts` does with
  `run_is_resolved`. Resolution clears the repeated-error flag and alert when
  the pair's latest failed attempt is resolved, but keeps the pair's status,
  so a Cloud auto-pause stays.

---

## Known issues

- **The connector PATCH route runs no connection check.**
  `backend/onyx/server/documents/connector.py:update_connector_from_model`
  checks credential bindings but does not call `validate_ccpair_for_user`. A
  bad config fails at the next index attempt.
- **The errors route's open filter shows errors of a resolved run.**
  `db/index_attempt.py:_cc_pair_errors` filters on `is_resolved` alone, so it
  lists errors that the attempt's open-error count leaves out.
- **`check_deletion_attempt_is_allowed` gates nothing.** Its only caller,
  `backend/onyx/server/documents/connector.py:get_currently_failed_indexing_status`, uses it
  to fill `is_deletable` for display. The real guard against deleting a pair
  that still runs work is the dependency wait in the deletion task.

---

## Dependencies

- [[access-control]]: access levels, manage roles, data-access groups, and the
  scope check in `authorize_pairing`.
- [[permission-sync]]: `validate_pairing_access` and the meaning of the
  perm-synced access types.
- [[connectors]]: connector classes, credential bindings and the edit flow.
- [[connector-capability-checks]]: pairing validation and the indexing hold.
- [[background-jobs]]: deletion and pruning tasks, Redis fences.
- [[indexing-pipeline]]: index attempts and their cancellation.
- [[editions-and-gating]]: EE dispatch for encryption and group sharing.
- [[multi-tenancy]]: every read uses a tenant-scoped session.

---

## Recipes

- `new-pair-setting` **Add a pair-level or connector-level setting.** Copy `check_frequency` in
  `update_cc_pair_property`: a connector-level value needs operate access on
  every pair of the connector ([[#connector-settings-are-shared]]). List the
  settings with `git grep -n "update_request.name ==" backend/onyx/server/documents/cc_pair.py`.
- `credential-route` **Add a route that returns credential data.** Copy `get_cc_pair_full_info`:
  build the snapshot with `CredentialSnapshot.from_credential_db_model` and pass
  `credential_ids_to_mask` ([[#credential-reads-masked]]). List the current
  callers with `git grep -n from_credential_db_model backend`.
- `reproduce-shared-document-delete` **Reproduce the shared-document delete.** Create two File connectors on the
  same file, let both index, then delete one from the UI. The document must
  stay searchable with the other pair's access. Read the pairs with
  `select id, connector_id, credential_id, status, access_type from connector_credential_pair order by id desc limit 5;`.
- `stuck-deleting` **Investigate a pair stuck in `DELETING`.** Check
  `deletion_failure_message` on the pair first, then follow
  [[background-jobs#investigate-deletion]].

---

## Verification

- `backend/tests/external_dependency_unit/server/documents/`: pairing,
  rollback, sharing, credential use and group visibility.
- `backend/tests/external_dependency_unit/indexing/`: the run feed, run
  resolution and the errors route.
- `backend/tests/integration/tests/connector/` and
  `backend/tests/integration/tests/permissions_resources/`: deletion, manage
  roles and data access, with `backend/tests/integration/common_utils/managers/cc_pair.py`
  as the harness.
- By hand: set `MASK_CREDENTIAL_PREFIX=false`, restart the API server, and
  open a user group or document set that holds a pair. Its credential JSON
  shows in full, which is what the default protects.
