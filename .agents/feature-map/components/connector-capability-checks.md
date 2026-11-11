# Connector Capability Checks

> Named probes that test whether a credential and a connector config can sign
> in, list the scope, read content and sync permissions. They run on the unsaved
> form, at creation, on an edit, on a schedule and on demand, and their results
> can block Create and hold the first index attempt.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE runs INDEXING checks. EE adds DOC_PERMISSION_SYNC and
EXTERNAL_GROUP_SYNC checks (`ee/onyx/connectors/capability_checks.py`) for the
sources that sync permissions.

---

## User experience

- **An admin fills in the add-connector form.** A checks card runs the
  source's checks against the account and settings. Each row passes, fails
  with a fix and a docs link, or does not finish. A failed or unfinished row
  can show Error Details: the request, the HTTP status and part of the
  source's response. The rest of the form unlocks after the sign-in check and
  the checks that prove the account works with its site pass. Create stays off
  while a required check on the current form has failed, was stopped, or has
  not run. A required check that could not finish does not hold Create.
- **Checks can fill pick lists.** A passing check can list what the account
  reaches, such as the channels or spaces it can read. The form offers them as
  options for the matching field.
- **The admin can skip a check.** Skipping an optional check lets Create go
  ahead. Skipping a required check stops it, and Create stays off. A failed
  optional check makes Create ask for confirmation first. A skip applies only
  to that admin.
- **On an edit,** the plan modal shows the result of each check for the
  proposed state. A required failure blocks Apply.
- **After creation,** the connector page lists check runs with their results.
  The admin can re-run the checks or set a check frequency. When the
  deployment sets `CONNECTOR_CHECKS_ENABLED` and the source has named checks,
  a required failure holds the first index attempt. The admin can release the
  hold from the status card.
- **A source with no named checks** gets one generic "Test connection" row that
  wraps the connector's settings probe. A source whose connector has no
  settings probe gets no INDEXING check.

---

## Scope

This component owns the check model and its status rules, the check registry
and the per-source check definitions, the runner, draft runs on the unsaved
form, pairing validation with named checks, stored runs and their Celery tasks,
findings, the first-index hold, and the web state and cards that show checks.

Its neighbours own:
- [[connectors]]: the `SourceOperations` gateway that every named check calls,
  `validate_connector_settings`, and the factory, which decides at pairing
  whether named checks or the settings probe run.
- [[cc-pairs-and-creds]]: the report and run tables, draft credentials, and
  the credential use rule that every run applies first.
- [[permission-sync]]: the perm-sync validator that scheduled syncs run, and
  what the synced permissions become.
- [[indexing-pipeline]]: dispatches the first index attempt after
  `get_first_indexing_hold` allows it. An admin release stamps
  `ConnectorCredentialPair.indexing_hold_released_at`.

---

## Architecture

```
registry.py:get_capability_checks(source)
  INDEXING checks from <source>/capability_checks.py, else the generic row
  + EE perm-sync checks (empty on CE)
        │
runner.py:generate_capability_report
  build connector in isolation (timeout guard) + build the source's gateway
  run_capability_checks: dependency order, at most MAX_PARALLEL_CHECKS at once
  map each exception to a status and an error kind
        │
   ┌────┴─────────────┬───────────────────────┬─────────────────────────┐
draft run           pairing / edit          stored run                indexing hold
(cache backend,     creation.py: run        RUN_CAPABILITY_CHECKS     indexing_hold.py
 no DB rows)        within a time budget,   task, writes report       reads the pair's
draft_runs.py       store report            and run history           connector report
```

**Two report scopes.** A credential-scoped report has no connector and runs
with no config. Checks that need a config skip there. A new credential of a
source with named checks starts one in the background
(`server/documents/capability_check_runs.py:start_capability_checks_for_new_credential`).
A connector-scoped report belongs to one pair and holds its indexing.

**Status mapping.** A check's `run` raises on failure.
`connectors/capability_checks/models.py:check_error_kind` maps the exception
class to a kind, and `CapabilityCheck.outcome_status` maps the kind to a
status. The `ConnectorValidationError` family is FAILED. Timeouts, rate limits,
unreachable sources, inconclusive samples and unknown errors are INCOMPLETE,
because they prove nothing about the credential. One exception: on a form run,
a check with `fails_when_unreachable` (the sign-in checks) FAILS on a timeout
or an unreachable source.

**Dependencies.** `depends_on` lists checks that must pass first.
`depends_on_any` lists alternatives, of which one must pass. `run_order` puts
discovery checks last. A check whose dependency failed, did not finish or did
not run is SKIPPED with a `not_run_reason`. After a rate limit, no new check
starts.

**Draft runs.** The unsaved form runs checks through
`server/documents/capability_check_runs.py:start_draft_capability_check_run`.
Results live in the cache backend, keyed per check by credential, its
`updated_at`, access type and the config the check reads
(`connectors/capability_checks/draft_runs.py:draft_result_cache_key`). An edit
to one field re-runs only the checks that read it. Creation reuses fresh draft
results, so the admin does not wait twice. An edit's dry run
(`/admin/cc-pair/{id}/edit/checks`) is a draft run scoped to the pair.

**Pairing.** At creation and on an edit, for a source with named checks,
`connectors/factory.py:validate_and_record_pairing` skips the settings probe
and calls `connectors/capability_checks/creation.py:validate_pairing_with_named_checks`. Only a required
check that FAILED within `CREATION_BLOCKING_BUDGET_SECONDS` blocks the pairing.
A background run finishes the rest. Index attempts keep the settings probe, and
`connectors/capability_checks/recorder.py:record_blocking_validation_outcome` stores its outcome as a coarse
report that never replaces a richer one.

**Stored runs.** `start_capability_check_run` marks the scope RUNNING with a
lease, commits, then enqueues. The task renews the lease after every result. A
read past the lease shows the run as failed to run, and
`CHECK_FOR_STALE_CAPABILITY_RUNS` retires it. A manual trigger replaces only a
live run older than five minutes, so double clicks start one run.

---

## Contracts and traps

1. `validation-error-family-blocks` **A check blocks only when it raises the
   `ConnectorValidationError` family.** A raw `requests.HTTPError` or SDK error
   maps to UNEXPECTED, which is INCOMPLETE and never blocks Create or indexing.
   Translate a 401 to `CredentialInvalidError` and a 403 to
   `InsufficientPermissionsError` (`connectors/exceptions.py`).
2. `named-checks-need-gateway` **Named checks need a gateway, and listing
   validates them.** `connectors/capability_checks/registry.py:get_capability_checks`
   and the EE dispatch assert that a
   source with named checks has a `SourceOperations` class
   ([[connectors#gateway-fenced-and-thread-safe]]). Checks call gateway
   operations, never the SDK. The same listing calls
   `connectors/capability_checks/two_step.py:validate_step_links`, which raises when a `CheckStep` link of a
   two-step row (checks that share a `row_id`) is not sound.
3. `perm-sync-checks-skip-settings-probe` **`has_named_capability_checks`
   counts EE perm-sync checks**
   (`connectors/capability_checks/registry.py:has_named_capability_checks`), so on EE a source with only named perm-sync
   checks also skips the settings probe at pairing.
4. `declare-config-fields` **Declare `config_fields` accurately.** A check that
   needs a connector instance, or reads the config without declaring the
   fields it reads, keys its cached draft result on the whole form
   (`connectors/capability_checks/draft_runs.py:draft_result_cache_key`). A declaration that misses a field reuses a
   stale result after that field changes. The gateway's `config_keys` adds to
   the key: `None` means the gateway reads every key, so nothing is reused
   across edits.
5. `transient-results-not-cached` **INCOMPLETE and transient results are never
   cached** (`connectors/capability_checks/draft_runs.py:cache_draft_result`).
   A sign-in FAILED by a timeout is not cached either. A re-run tries again.
6. `request-timeout-below-hang-guard` **Per-request timeouts must stay below
   the check's hang guard.** On a timeout,
   `utils/threadpool_concurrency.py:run_with_timeout` abandons the
   thread, which may still have a request in flight. The default guard is
   `connectors/capability_checks/runner.py:CAPABILITY_CHECK_TIMEOUT_SECONDS`. A slow probe sets its own
   `timeout_seconds`.
7. `error-details-scrub-secrets` **Error details must not leak secrets.**
   `connectors/capability_checks/models.py:check_error_detail` removes URL
   query strings and the run's credential values from the response excerpt and
   the stack trace. The detail comes from the first `requests.HTTPError` or
   `connectors/exceptions.py:SourceApiError` in the cause chain
   (`connectors/capability_checks/generic_row.py:http_response_in_chain`). Wrap
   any other SDK error in a `SourceApiError` subclass, or the row shows no
   request.
8. `findings-names-ids-counts` **Findings carry names, ids and counts only.**
   No document content, and users only as a count. With the workspace setting
   `allow_connector_check_findings` off, the runner stores no findings and
   responses hide stored ones (`connectors/capability_checks/findings_setting.py`). A new `CheckFindingKey`
   needs the matching union member in `web/src/lib/connectors/checks/types.ts`
   and a label. The setting does not hide advisories, so an advisory must not
   list what the credential reaches.
9. `discovery-never-decides` **A discovery check never counts toward a
   verdict.** It runs after the validation checks, does not run at creation,
   and is skipped when findings are off or a required check failed.
10. `indexing-hold-fails-closed` **The indexing hold fails closed.**
    `connectors/capability_checks/indexing_hold.py:decide_indexing_hold` holds on a running run, a dead run,
    an unreadable report or a required FAILED check. It ignores a finished
    report with another config hash. A release outranks only runs that started
    before it. Nothing is held with `CONNECTOR_CHECKS_ENABLED` off, for a source
    without named checks, for a pair with no report row, or after the pair's
    first dispatched attempt
    (`connectors/capability_checks/indexing_hold.py:get_first_indexing_hold`).
11. `runs-apply-credential-use-rule` **Each run that a user starts applies the
    credential use rule first.** Draft runs, dry runs and manual stored runs
    call `connectors/factory.py:assert_user_can_use_credential` before they build a connector
    ([[cc-pairs-and-creds]]). System triggers pass no user.
12. `draft-actions-fixed-meaning` **Draft actions have fixed meanings.**
    `check_ids` runs those checks again and ignores the cache. `skip_check_ids`
    makes an optional check SKIPPED and a required check STOPPED, which still
    holds Create (`connectors/capability_checks/draft_runs.py:skip_draft_check`).
    `start_check_id` moves that check and its dependencies to the front. A
    check both run and skipped is INVALID_INPUT
    (`server/documents/capability_check_runs.py:validate_draft_check_actions`).
    A skip is cached per user
    (`connectors/capability_checks/draft_runs.py:cache_user_skip`), so creation
    by that user reuses an optional skip and runs a stopped check. A result
    from an older run does not replace a newer skip
    (`connectors/capability_checks/draft_runs.py:cache_run_result`).
13. `draft-check-runs-once` **A check that a draft run still runs is not
    started again.** The draft task marks its pending result keys in flight
    (`connectors/capability_checks/draft_runs.py:mark_draft_results_in_flight`).
    Creation and the background run of unfinished checks wait for those keys
    (`connectors/capability_checks/draft_runs.py:wait_for_draft_result`) before
    they run the check. A path that skips the marker runs a slow probe twice
    against a rate-limited source. A newer run with the same draft key
    supersedes the older one, and
    `server/documents/capability_check_runs.py:cancel_draft_capability_check_run`
    supersedes with no successor. The task checks
    `connectors/capability_checks/draft_runs.py:is_superseded` after each result
    and stops before its next check, so an old run cannot overwrite newer form
    state. When prior results join a limited run,
    `connectors/capability_checks/runner.py:merge_capability_results` applies the dependency stop rule again
    (`connectors/capability_checks/runner.py:stop_blocked_results`).

---

## Decisions

- **Checks live in a registry, not on the connector class.** The form must list
  a source's checks before any connector exists, so `/connector-checks/plan`
  needs no credential.
- **Applicability is a separate light module.** `connectors/capability_checks/applicability.py` and the EE
  `ee/onyx/connectors/capability_applicability.py` do not import check modules, because the
  blocking-validation recorder runs on the docfetching hot path.
- **A slow source never blocks.** Creation waits a short budget and lets a
  background run finish. Only a proven failure blocks. The web follows the same
  rule: `INDETERMINATE_CHECKS_BLOCK` in
  `web/src/lib/connectors/checks/constants.ts` is `false`.

---

## Known issues

- **The hold flag comment names a web flag that does not exist.** The comment on
  `CONNECTOR_CHECKS_ENABLED` in `configs/app_configs.py` says to enable it with
  `NEXT_PUBLIC_CONNECTOR_CHECKS_CARD_ENABLED`. The web code has no such flag,
  and the checks card always shows.
- **Stored reports can hold the status `indeterminate`.** No new result uses
  it. Readers treat it as INCOMPLETE
  (`connectors/capability_checks/models.py:INCOMPLETE_STATUSES`).
- **Option findings stop at `MAX_FINDING_OPTIONS`.** A larger listing is cut
  and marked truncated. No search endpoint exists for the rest.
- **Perm-sync check definitions live in two places.** Most sources define them
  in the CE source module next to their INDEXING checks, and only the EE
  dispatch imports them. Sources whose checks need EE permission code define
  them under `ee/onyx/external_permissions/<source>/`, as `youtrack` and
  `linear` do.

---

## Dependencies

- [[connectors]]: gateways, connector instantiation and the settings probe.
- [[cc-pairs-and-creds]]: report and run tables, drafts, the credential use rule.
- [[background-jobs]]: the run, draft-run, stale-sweep, schedule and cleanup tasks.
- [[editions-and-gating]]: perm-sync checks load through `fetch_ee_implementation_or_noop`.

---

## Recipes

- `named-checks` **Named checks for a source.** The source needs a gateway
  ([[#named-checks-need-gateway]]). Copy `connectors/youtrack/capability_checks.py`; list the
  sources with checks with
  `git ls-files 'backend/onyx/connectors/*/capability_checks.py'`. Write a
  `build_<source>_indexing_checks` function and add it to
  `_INDEXING_CHECKS_BY_SOURCE`. Give the sign-in check `validates_binding=True`
  and `fails_when_unreachable=True`. YouTrack's sign-in check omits the second
  flag; copy it and `timeout_text` from `connectors/linear/capability_checks.py`. Every gateway operation must be exercised
  by a check of its capability or carry an `untested` reason. Pick the outcome
  by what the check raises or returns (`connectors/exceptions.py`,
  [[#validation-error-family-blocks]]): `InconclusiveValidationError` when the
  sample cannot decide (INCOMPLETE), `NothingToCheckError` when the scope holds
  nothing to test (SKIPPED with `nothing_in_scope`), and
  `CheckOutput(partial=True)` when a Find confirms only part of the scope
  (INCOMPLETE, and dependents still run).
- `perm-sync-checks` **Perm-sync checks.** Copy the `build_slack_doc_permission_sync_checks`
  pattern in the source's check module, or
  `ee/onyx/external_permissions/youtrack/capability_checks.py` when the checks
  need EE permission code. List the current set in the EE maps in
  `ee/onyx/connectors/capability_checks.py` and register the new builders
  there. They apply only to perm-synced access types unless `access_types` says
  otherwise.
- `investigate-blocking-check` **Investigate a check that blocks Create or holds indexing.** Open the row's
  Error Details. A FAILED row raised the validation family
  ([[#validation-error-family-blocks]]): read the request and status. A row
  that stays INCOMPLETE raised something else, often a raw SDK error. A pair
  that does not start its first index attempt is held: the status card names
  the reason ([[#indexing-hold-fails-closed]]). To reproduce a hold locally,
  set `CONNECTOR_CHECKS_ENABLED=true` for the API server and the Celery workers,
  and create a pair with a token that lacks one scope.
- `investigate-stale-draft-result` **Investigate a stale result on the form.** A result that does not change
  after a field edit comes from the draft cache. Check the check's
  `config_fields` and the gateway's `config_keys`
  ([[#declare-config-fields]]).

---

## Verification

- Unit tests: `backend/tests/unit/onyx/connectors/capability_checks/`, which
  holds the declaration and ratchet tests over every registered check.
- External dependency tests:
  `backend/tests/external_dependency_unit/connectors/capability_checks/`.
- Integration tests: `backend/tests/integration/tests/capability_checks/`.
- Web: the tests in `web/src/lib/connectors/checks/` cover form unlock and
  Create gating.
- By hand: on the add-connector form, enter a token without one scope. The row
  must fail with a fix, and Create must stay off.
