# Connectors

> The boundary between Onyx and an outside source: the connector interfaces, the
> registry and factory, typed configs with the edit plan, and source gateways. A
> connector yields documents, hierarchy nodes and failures; it never chunks,
> embeds or writes to the index.

**Verified against:** `a4e97fcea1` (2026-10-29)
**Edition:** CE. EE adds the permission-sync callers and the permission-sync
settings probe (`validate_perm_sync`).

---

## User experience

- **An admin adds a connector.** They pick a source, connect an account (a
  token, an OAuth sign-in or a service-account key), and set the scope, such
  as Confluence spaces or Slack channels. On sources with capability checks,
  the form runs the checks before Create ([[connector-capability-checks]]).
  Saving pairs the connector with the account and starts the first index run.
  The status page then shows a document count and the last successful run.
- **Background jobs keep the index current.** An update run fetches new and
  changed documents on a schedule. A prune run removes deleted documents.
- **An admin edits a connector.** The edit page shows a plan before it saves:
  which steps the change needs, such as a full re-index, a scoped backfill or a
  prune. The admin confirms, and the steps run in the background.
- **When it fails.** A wrong credential shows as an error at creation only
  when the source has a settings probe or named checks. Without them, the first
  index run fails or finds nothing. A document that fails to fetch shows in the
  pair's failure list, and the admin can re-index it.
- **A chat user** sees connector documents as search results and citations.

---

## Scope

This component owns the contract between Onyx and every source: the connector
interfaces and document model, the registry and factory, typed configs and
their field policies, the config edit planner, the gateway base, and the source
packages. Per-source rules that the code does not show quickly are in the
per-connector documents, such as [[confluence]], [[slack]], [[google-drive]],
[[microsoft-graph]], [[outlook]] and [[teams]].

Its neighbours own:
- [[connector-capability-checks]]: the named checks on a credential and config.
- [[indexing-pipeline]]: the docfetching loop and everything after a batch.
- [[background-jobs]]: the fetch, prune, hierarchy and re-index tasks.
- [[cc-pairs-and-creds]]: the connector, credential and pair tables,
  encryption, sharing, and the rule for who may use a credential.
- [[permission-sync]] and [[access-control]]: what `external_access` becomes.

---

## Architecture

```
DocumentSource ── registry.py:CONNECTOR_CLASS_MAP ──> ConnectorMapping(module, class, config_class)
                                                       │ class imported lazily on first use
factory.py:instantiate_connector                       │ config_class imported eagerly
  ├─ build_connector_kwargs        stored config -> typed config -> __init__ kwargs
  ├─ CredentialsConnector?  yes -> set_credentials_provider(DB provider)
  │                         no  -> load_credentials(decrypted JSON); a returned dict is written back
  └─ set_allow_images, set_raw_file_callback
        │
        ├─ docfetching:   ConnectorRunner.run(checkpoint)   -> [[indexing-pipeline]]
        ├─ pruning:       celery_utils.py:extract_ids_from_runnable_connector -> id diff
        ├─ hierarchy:     HierarchyConnector.load_hierarchy
        └─ re-index:      Resolver.reindex(failures)
```

**Two construction paths.** Docfetching, pruning, hierarchy fetching,
targeted re-index, the creation validation and the capability check runner
(`connectors/capability_checks/runner.py`) call `instantiate_connector`. EE
permission sync constructs each class itself in
`ee/onyx/external_permissions/<source>/`, with
`build_connector_kwargs` and `external_permissions/utils.py:credential_json`
([[permission-sync]]). User-file ingestion also builds `LocalFileConnector`
directly. [[#one-credential-path]] gives the rule for a change to construction.

**Interfaces.** A connector subclasses bases in `connectors/interfaces.py`. Prefer
`CheckpointedConnector`: it returns the next checkpoint, so an interrupted
attempt resumes. `ConnectorRunner` runs a `LoadConnector` or `PollConnector` as
one pass with a finished checkpoint, so a failure restarts the window.
`connectors/factory.py:_validate_connector_supports_input_type` accepts a
checkpointed connector for `InputType.POLL` and rejects `InputType.EVENT`.

**Permission fetching.** Two interfaces return `external_access` for EE
permission sync ([[permission-sync]]). `SlimConnectorWithPermSync` lists every
id with its access. Doc sync needs it
(`ee/onyx/external_permissions/utils.py:generic_doc_sync`), and prune uses it
when the connector has no plain slim listing.
`CheckpointedConnectorWithPermSync` fetches documents with their access.
Docfetching asks for it on a perm-synced pair's first index or a run from the
beginning, when the source's doc sync config sets `initial_index_should_sync`.
`connectors/connector_runner.py:ConnectorRunner` then raises when the connector
does not implement it.

**Checkpoints.** `background/indexing/run_docfetching.py` loops while `checkpoint.has_more`. It
starts from `build_dummy_checkpoint` for a run from the beginning, a backfill,
a run after a successful attempt, or a config whose
`connectors/config_hash.py:compute_connector_config_hash` changed since the last attempt.
Otherwise it resumes the latest checkpoint of a failed attempt with the same
window and config hash
(`background/indexing/checkpointing_utils.py:get_latest_valid_checkpoint`).

**Pruning.** The prune task lists the source's ids and deletes every indexed
id that is not in the list. `extract_ids_from_runnable_connector` uses the slim
listing when the connector has one. Otherwise it runs a full load, poll or
checkpoint pass, which downloads every body. Ids from `ConnectorFailure` items
are kept, so a document that failed to fetch is not pruned.

**Typed config.** Each `ConnectorMapping` carries a `ConnectorConfig`
subclass whose fields mirror the `__init__` kwargs, with `extra="forbid"`. A
config can inherit a `CredentialBinding` for fields that depend on the account,
such as a site URL. `connectors/factory.py:validate_credential_binding` checks
them against what the credential records. [[cc-pairs-and-creds]] describes the
rule for using another user's credential
(`connectors/factory.py:credential_use_refusal`). Related sources can share one
stored credential, and `to_source_credential_json` converts it to the source's
own keys first.

**Config edits.** An edit computes a plan before it saves
(`server/documents/connector_edit.py`). `connectors/config_diff.py:classify_config_change`
classes each changed field by its `FieldPolicy`, and `connectors/edit_plan/planner.py`
maps the class to steps: IDENTITY (in the document id) needs a full re-index
and a prune; BEHAVIOR needs a full re-index; COSMETIC needs nothing. A SCOPE
field that widens needs a scoped backfill, or a full re-index when the source
cannot run a window. A SCOPE field that narrows needs a prune, and an unknown
direction makes the admin pick. A planning rule (`connectors/planning_rule_registry.py`)
handles mode fields that change what other fields mean. `connectors/edit_plan/apply.py`
writes the state and the steps in one transaction, and beat tasks run the
steps. A stored plan applies only to the pair state it was computed from
(`connectors/edit_plan/store.py:ensure_base_state_matches`).

**Source gateways.** A source can put every remote call in one
`SourceOperations` subclass in `<source>/source_operations.py`, which indexing,
EE permission sync and capability checks all call. To list them, run
`git ls-files 'backend/onyx/connectors/*/source_operations.py'`.

**Spreadsheets.** A connector turns a tabular file into sections with
`connectors/cross_connector_utils/tabular_section_utils.py:tabular_file_to_sections`.
With `SKIP_SPREADSHEET_CONTENT` on, it passes `skip_content`, and the file
becomes one placeholder text section. The placeholder is part of the content
hash, so a change to the setting re-indexes each file on its next fetch. Pass
the setting at every extraction site; list them with
`git grep -n 'skip_content=' -- backend/onyx/connectors`. [[indexing-pipeline]]
owns the chunking of the sections.

---

## Contracts and traps

1. `slim-listing-raises-on-auth-failure` **A slim listing must raise on an auth
   failure, never return empty.** The prune diff in
   `background/celery/tasks/pruning/tasks.py:connector_pruning_generator_task` has no minimum-count or
   ratio check, so an empty listing deletes every document of the pair. Only an
   exception aborts the prune. [[google-drive]] raises when a requested target
   is visible to no user, for the same reason.
2. `slim-and-index-same-ids` **The slim listing must return the same id set as
   the indexing pass.** An id the slim pass omits is pruned. An id the main
   pass never indexes leaves a row with `chunk_count IS NULL`. This applies to
   `include_attachments` too: gate both passes on the flag
   (`backend/onyx/connectors/README.md`). The flag defaults to `False`, except
   on a connector that indexed attachments before it had the flag: its stored
   rows have no key, so it defaults to `True`.
3. `stable-document-id` **`Document.id` must be stable across runs.** It is the
   dedup key. An id built from a mutable field creates a duplicate document on
   every run.
4. `failure-id-is-document-id` **`DocumentFailure.document_id` must equal the
   `Document.id`, not a native source id.** The docprocessing task,
   `background/indexing/run_targeted_reindex.py` and the prune failure guard
   (`background/celery/celery_utils.py:_get_failure_id`) compare it with
   document ids. A mismatch breaks targeted re-index and lets prune delete the
   document. Copy an existing connector's failure site.
5. `checkpoint-compatible` **A checkpoint must round-trip through
   `validate_checkpoint_json`, and the dummy checkpoint must have
   `has_more=True`.** Otherwise the docfetching loop never starts. Saved
   checkpoints of in-flight attempts outlive a deploy: a change to a
   checkpoint's fields makes them unreadable, and
   `background/indexing/checkpointing_utils.py:get_latest_valid_checkpoint`
   then logs the error and starts the attempt over from the dummy checkpoint.
   Accept the old shape with a field alias, as
   `connectors/sharepoint/connector.py:SharepointConnectorCheckpoint` does.
6. `honor-time-window` **Honor the `start` and `end` window.** A poll or
   checkpointed connector that ignores it re-reads everything or misses
   changes. A slim listing that filters by the indexing start must set
   `slim_listing_honors_indexing_start`. Prune then lists only documents from
   that date, and deletes older ones
   (`connectors/interfaces.py:prune_listing_honors_indexing_start`). A dated
   listing omits unchanged folders, so
   `background/celery/tasks/pruning/tasks.py:_get_live_hierarchy_node_ids` keeps the hierarchy nodes
   above each kept document.
7. `one-credential-path` **Pick one credential path.**
   `connectors/factory.py:instantiate_connector` calls `set_credentials_provider` for a `CredentialsConnector` and
   `load_credentials` for the others. A connector that implements the provider
   path makes `load_credentials` raise `NotImplementedError`, as Confluence and
   Slack do. Entering the provider takes its lock. When the provider's
   `is_dynamic()` is true, wrap each renewal in `with <provider>:`, or
   parallel attempts race on a refresh
   (`connectors/interfaces.py:CredentialsProviderInterface`). The
   [[confluence]] gateway shows the pattern. EE permission sync does not call
   `instantiate_connector`, so a change to construction (the credential
   write-back, `set_allow_images`, the raw-file callback) does not reach it.
   Check each perm-sync builder too.
8. `field-policy-required` **Each config field needs a `FieldPolicy`.** A field
   without one counts as BEHAVIOR, so every edit of it forces a full re-index.
   `tests/unit/onyx/connectors/test_config_diff.py` asserts that
   `connectors/config_diff.py:build_field_policy_report` is empty, and
   `tests/unit/onyx/connectors/test_connector_config_models.py` asserts that the config mirrors the
   `__init__` kwargs. Config modules must stay light to import, because the
   registry imports all of them.
9. `url-ids-need-normalize-url` **A connector whose document ids are URLs
   should override `normalize_url`**
   (`connectors/interfaces.py:BaseConnector.normalize_url`). The open-URL tool
   (`tools/tool_implementations/open_url/url_normalization.py`) uses it to map
   a pasted URL to an indexed document ([[web-search]]).
10. `gateway-fenced-and-thread-safe` **A gateway is fenced at import time, must
    be thread safe, and returns plain data.** The class shape
    (`connectors/source_operations.py:SourceOperations.__init_subclass__`) fails
    at import. `tests/unit/onyx/connectors/test_source_operation_import_fence.py`
    keeps the SDKs in `sdk_modules` out of other files, and
    `tests/unit/onyx/connectors/test_source_operation_coverage.py` needs a check
    for each new operation or an `untested="<reason>"` stamp. Nothing enforces thread safety, and the check runner calls one gateway from
    parallel checks: follow the rules in the
    `connectors/source_operations.py:SourceOperations` docstring. An operation
    must never return an SDK object. Lazy SDK objects (PyGithub attributes,
    office365 fluent chains) make network calls outside the gateway when a
    caller reads them.
11. `hierarchy-before-documents` **Hierarchy nodes must arrive before the
    documents under them.** `connectors/connector_runner.py:ConnectorRunner`
    flushes pending nodes before each document batch and at the end.
    Docfetching (`background/indexing/run_docfetching.py`) caches each node
    batch, then resolves each document's parent from that cache. A parent it
    cannot find becomes the SOURCE root, with no error. Yield a parent node
    before its documents, and keep this order in any change to the runner's
    batching.
12. `realm-not-in-config` **The account realm never reaches the connector
    config.** The realm (site, host or subdomain) is stored in the credential
    only. The add-connector form shows it as a form-only field
    (`web/src/lib/connectors/utils.ts:formOnlyFieldNames`) to fill a new account
    and filter saved accounts. Every request that sends form values as config
    goes through `web/src/lib/connectors/utils.ts:withoutFormOnlyFields`. A new
    call site that skips it fails validation, because typed configs use
    `extra="forbid"`.

---

## Decisions

- **The registry stores module paths, not classes.** Importing the registry
  must not import every source SDK. The cost: a missing entry raises
  `ConnectorMissingException` when a pair first runs, not at import.
- **Stored configs that fail validation still run.** Rows written before typed
  configs may not conform, so `build_connector_kwargs` logs a warning and passes
  them through. An upgrade does not break running pairs.

---

## Known issues

- **`backend/onyx/connectors/README.md` lags the code.** It names `connectors/factory.py`
  for the source mapping (in `connectors/registry.py`) and omits configs and gateways.
  Do not follow it as the add-a-connector checklist; use the recipe below.
- **`SourceOperations` is opt-in.** Many sources still call their SDK inline,
  so the one-gateway guarantee holds only for sources with a
  gateway module.

---

## Dependencies

- [[cc-pairs-and-creds]]: stored config, credential JSON and the credential use rule.
- [[file-store-and-user-files]]: `RawFileCallback` staging and file text extraction.
- [[editions-and-gating]]: EE permission-sync probes load through `fetch_ee_implementation_or_noop`.

---

## Recipes

- `new-connector` **A new connector.** Copy the `youtrack` source. List the sources in
  `connectors/registry.py:CONNECTOR_CLASS_MAP`. Add a `DocumentSource` member,
  a package with the connector class and a config module whose fields carry a
  `FieldPolicy` ([[#field-policy-required]]), and a registry entry. Implement
  `CheckpointedConnector` and a slim listing that raises on auth failure
  ([[#slim-listing-raises-on-auth-failure]], [[#slim-and-index-same-ids]]).
  Register named capability checks ([[connector-capability-checks]]) or
  override `validate_connector_settings`; a source with neither gets no check
  at creation. With named checks, pairing does not run the settings probe
  (`connectors/factory.py:validate_proposed_pairing`). To find every registration point, run
  `git grep -il youtrack -- backend web` and repeat each hit that is not in the
  source's own package. A config with a `CredentialBinding` also needs
  `backend/scripts/generate_credential_bound_fields.py` run again. For
  permission sync, implement the permission interfaces (Architecture,
  Permission fetching). Add daily tests and a docs page
  (`documentation/AGENTS.md`).
- `source-gateway` **A source gateway.** Copy
  `connectors/youtrack/source_operations.py:YouTrackSourceOperations`; list the gateways with
  `git ls-files 'backend/onyx/connectors/*/source_operations.py'`. Subclass
  `SourceOperations`, declare `source`, `sdk_modules` and `config_keys`, and
  stamp every public method ([[#gateway-fenced-and-thread-safe]]).
- `oauth-sign-in` **An OAuth sign-in.** Implement `OAuthConnector`. The generic
  `/connector/oauth/*` routes find every subclass in `onyx.connectors`
  (`server/documents/standard_oauth.py:_discover_oauth_connectors`), so no
  route change is needed. Do not copy Google Drive or Gmail, which have their
  own routes in `server/documents/connector.py`.
- `config-field` **A config field.** Add it to `__init__` and the config with a `FieldPolicy`,
  plus `depends_on` or a planning rule when a mode field changes its meaning.
  Copy a source with a planning rule; list them in `connectors/planning_rule_registry.py`.
- `investigate-prune-deletions` **Investigate documents that left the index after a prune.** Find the prune
  run in the backend log directory by the "Pruning set collected" line, which gives
  `docs_to_remove`. A large count with no error means the listing returned
  less than it should: an auth failure that returned empty
  ([[#slim-listing-raises-on-auth-failure]]), a slim pass that differs from the
  index pass ([[#slim-and-index-same-ids]]), or a listing that honors the
  indexing start ([[#honor-time-window]]). To reproduce, delete one document at
  the source and run `POST /api/manage/admin/cc-pair/{id}/prune` through the
  frontend. Only that document must leave the index.
- `investigate-unrepaired-failure` **Investigate a failed document that re-index never repairs.** Compare the
  failure's `document_id` with the indexed `Document.id`
  ([[#failure-id-is-document-id]]). A source-native id never matches.

---

## Verification

- Unit tests: `backend/tests/unit/onyx/connectors/`, with the gateway harnesses
  in `tests/unit/onyx/connectors/source_operation_harnesses.py` (import fence and check coverage over every
  registered gateway).
- External dependency tests: `backend/tests/external_dependency_unit/connectors/`
  and the prune tests in `backend/tests/external_dependency_unit/celery/`.
- Integration tests: `backend/tests/integration/tests/connector_edit/` and
  `backend/tests/integration/tests/pruning/`.
- Daily tests against live sources: `backend/tests/daily/connectors/`.
