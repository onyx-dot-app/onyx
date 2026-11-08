# Skills

> Agent Skills for Craft: instruction bundles that Onyx renders for each user and pushes into that user's Craft sandbox, where the coding agent reads them. This component owns skill sharing, installation policy, per-user rendering and the hashed push; skills do not reach the chat product.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE. Group shares need the EE group tables.

---

## User experience

- **A Craft user** opens the skills library and sees built-in skills and the
  custom skills they can see: their own, shared with them, or published to the
  organization. The Admin Panel lists custom skills only. They preview a
  skill's instructions, and turn custom skills on or off.
- **Built-in skills** are always on. A built-in that depends on an unavailable
  service, such as image generation with no provider or the browser with
  `ENABLE_BROWSER` off, is hidden. A skill for an external app is ready only
  after the user connects that app. Until then the user cannot turn it on, and
  the library says why.
- **Authoring.** A user writes a skill in the browser editor, uploads a `.zip`
  or a single SKILL.md, or imports skills from a GitHub repository after a
  preview of every SKILL.md found. A private repository needs the user's
  GitHub connection in Craft; without it the import is anonymous. The owner
  shares with users or groups as viewer or editor, publishes to the
  organization, or transfers ownership.
- **Admins** set the installation policy of a custom skill: available (the user
  opts in), installed by default (on until the user opts out), or required (on,
  and the user cannot turn it off). Global manage-skills permission is required to delete a required skill.
- **Bulk management.** Craft's Skills library and **Admin Panel → Skills**
  support selection of custom skills, bulk access and installation changes,
  personal enable/disable, and confirmed deletion. Admins see all manageable
  custom skills. Bulk sharing adds or updates supplied individual grants;
  omitted visibility and installation settings remain unchanged. Failed items
  stay selected. Search changes clear selection.
  Custom cards show Personal, Shared, or Organization access from
  `public_permission` and the server's `is_personal`; share-detail arrays can
  be hidden, so empty arrays do not mean a skill is personal.
- **Skill dialog.** Owners and editors open custom cards in a single
  Details/Sharing dialog. Share actions open its Sharing tab directly. Draft
  sharing edits survive tab switches. Other recipients and built-in skills
  keep a preview-only dialog. The sharing endpoint requires EDIT; do not
  require that endpoint for a VIEW-only preview.
- **Access at import.** GitHub import and multiple-ZIP upload accept one set
  of sharing settings for the selection. The single-skill editor accepts
  sharing before creation. These use the same sharing checks as later edits.
- **In a running Craft session**, a skill change does not reach the agent at
  once. The session shows a stale-skills notice with a reload action. The
  reload restarts the agent's runtime with the current skills.
- **Version history API.** Owners, editors and admins can list custom skill
  versions with their creator and timestamp, preview retained content, and
  restore it. Viewers can preview current instructions but cannot read history.
  Restore creates a new version unless its content equals the current version.

When it fails:
- A bundle with bad frontmatter, an unsafe path, a reserved name, or a
  `.template` file is rejected with a message. A bundle over a size or file
  count limit is rejected with a 413 that names the limit.
- Turning on a skill whose name another enabled skill uses returns a name
  conflict. The client can retry with `replace_conflict` to switch skills.
- A required skill rejects a toggle.
- If a push to a sandbox fails, the change still saves. The sandbox keeps its
  old skills until the next push, session start or reload.
- A reload while a turn runs is refused with a message to wait.

---

## Scope

This component owns the skill row and version snapshots, its shares,
installation policy and user preferences; bundle parsing and validation;
built-in skill definitions; per-user rendering of templates; GitHub import
and marketplace storage and provider adapters;
the push of a user's skill files into a sandbox; and the skills library UI.

Neighbours own the rest:
- [[craft-sandboxes]]: the sandbox, the managed volume and the push transport.
- [[craft-sessions]]: `BuildSession.skills_hash`, the stale check and the
  reload.
- [[craft-external-apps]]: app connection, action policy, and credential
  injection at call time. The sandbox proxy enforces policy, not the skill
  text.
- [[file-store-and-user-files]]: stores custom bundles as blobs.
- The chat product does not read skills. The chat loop has no reference to
  them; a "skill" in a chat bug report is something else.

---

## Architecture

```
skill mutation (server/features/skill/api.py)   compute affected users BEFORE the change
  -> db write, commit
  -> push_skills_for_users       skills/push.py
       lock_sandbox_skills_hashes        SELECT ... FOR UPDATE on Sandbox rows
       build_user_skills_payload         per sandbox user
         list_runtime_skills_for_user    db/skill.py: the one runtime gate
         _assemble_fileset               built-ins from disk, custom from FileStore;
                                         resolves ${CLAUDE_SKILL_DIR} in each SKILL.md
         build_connectable_apps_list     guidance for unconnected apps
       compute_skill_runtime_hash        once per sandbox; skip sandboxes whose hash matches
       push_to_sandboxes(SKILLS_MOUNT_PATH)
       set_sandbox_skills_hashes__no_commit   only for successful pushes
  -> commit
session start: sandbox_lifecycle.py:build_managed_content_payload
  uses the same payload and hash, before the sandbox is RUNNING
```

**The runtime gate.** `db/skill.py:list_runtime_skills_for_user` decides what
a sandbox gets. It combines visibility (`skill_visible_to_user`), enablement
(`_is_enabled_for_user`), app readiness, bundle validity (`is_valid` not
false) and built-in availability (`_exclude_unavailable_built_in_skills`).
These inputs stay independent. A required skill still needs a ready app and a
valid bundle.

**Enablement.** `_is_enabled_for_user` is the one SQL rule for API responses
and the runtime gate. Built-ins are on. A visible required skill is on and
hides other skills with its name. Else an explicit preference wins. Else a
default skill is on unless another visible skill with its name is selected.

**Two hashes.** `compute_skill_runtime_hash` is a SHA-256 over every rendered
file path and its bytes, plus the connectable-apps text. `Sandbox.skills_hash`
records what was last pushed to the sandbox. `BuildSession.skills_hash`
records what the live runtime of a session loaded. A session is stale when the
two differ
(`server/features/build/db/build_session.py:session_runtime_stale`). A push
changes only the sandbox side. The runtime reads the skills directory once per
instance, so only a reload (`SessionManager.reload_session_skills`) or a new
session applies the change. The craft MCP set has its own `mcp_config_hash`
and triggers the same reload.

**Templates.** A built-in with a SKILL.md.template is rendered per user in
`skills/push.py:_render_template`. `company-search` lists the user's connected
sources. External-app skills fill app values, cloud-only blocks, and a list of
actions the admin denied (`skills/rendering.py:render_external_app_skill`).
The library preview of an external-app skill calls the same renderer
(`server/features/skill/response_helpers.py:skill_preview_response`). The
`company-search` preview shows the unrendered template.

---

## Contracts and traps

1. `rendering-input-changes-hash` **A new rendering input must change the
   hash.** If a value that changes the rendered files is not in the bytes that
   `skills/push.py:compute_skill_runtime_hash` reads, an edit never re-pushes and sessions
   never go stale.
2. `affected-users-before-change` **Compute affected users before the
   change.** `db/skill.py:affected_user_ids_for_skill` finds users with a running sandbox
   who can see the skill. It ignores preferences on purpose, so that a delete
   or a disable still pushes to the users who had the skill. The delete route
   reads the audience before it deletes. The share, transfer and edit routes
   push to the union of the audience before and after. A new mutation must do
   the same, or a user who loses access keeps the files.
3. `shared-read-predicates` **Every new read path must use the shared
   predicates.** Reads use `db/skill.py:skill_visible_to_user`. Edits use
   `db/skill.py:_is_editable_by_user`, through
   `db/skill.py:_skill_select_for_management_policy`. A
   query on `Skill` without them skips sharing.
4. `enablement-not-preference-row` **Never infer enablement from a preference
   row.** Use `db/skill.py:_is_enabled_for_user`. Disable writes `enabled=False`; it does
   not delete the row. A required policy overrides an opt-out without deleting
   it, so the opt-out returns when the policy goes back to default.
5. `name-uniqueness-in-db` **Name uniqueness is in the database.** The partial
   unique index `uq_user_skill_preference_name` allows one enabled choice per
   user and name. `uq_skill_automatic_name` covers every policy except
   AVAILABLE. `server/features/skill/models.py:SkillShareRequest` and
   `db/skill.py:set_skill_installation_policy`
   reject NOT_AVAILABLE until effective-policy resolution and write rules support it.
   Every write that enables a preference first
   takes `db/skill.py:_lock_user_skill_preferences`, a `FOR NO KEY UPDATE`
   lock on the user row. The lock orders concurrent enables of one name, so
   the second one gets `SKILL_NAME_CONFLICT`, not an `IntegrityError`. The
   lock does not block the `FOR KEY SHARE` locks that foreign-key checks take,
   so sharing writes that reference the user still run. A new preference
   writer, such as an auto-enable, must take the same lock.
   `skills/push.py:_assemble_fileset` raises if two skills in one fileset share a name,
   because the name is the sandbox directory.
6. `name-immutable` **A skill name never changes.** The frontmatter `name`,
   `Skill.name` and the bundle's wrapper directory, when there is one, must
   match (`skills/metadata.py:parse_skill_document`). Storage removes the
   wrapper. A rename is a delete and a new skill. Custom names cannot match a
   built-in.
7. `validate-before-sandbox` **Validate before content reaches a sandbox.**
   `_assemble_fileset` unzips a custom bundle only when `is_valid` is true, or
   after `skills/validation.py:validate_stored_custom_skill` passes for an
   unclassified row. `db/skill.py:persist_skill_validity` writes only to rows that are still unclassified
   and still point at the observed version and bundle. The skill lock serializes
   this update with replacement; the legacy validity column is dual-written.
   Writes check four limits in `skills/bundle.py:normalize_custom_bundle`.
   Count all non-directory archive entries, including ignored files. Check
   both the incoming and normalized ZIP sizes. Raw uploads use the per-file
   read cap; ZIP uploads use the ZIP cap.
   Stored-bundle reads (`skills/validation.py:load_stored_custom_skill_bundle`)
   skip the upload ZIP-size and file-count limits. Their separate
   `SKILL_BUNDLE_STORED_ZIP_MAX_BYTES` allowance must cover previously accepted ZIPs.
   Upload ZIP limits cannot exceed that allowance; lowering an upload limit must not lower it.
   Stored reads retain the existing per-file and expanded-total limits.
8. `templates-built-in-only` **Only built-ins use templates.**
   `skills/bundle.py:normalize_custom_bundle` and
   `skills/bundle.py:update_custom_bundle_files` reject `.template` files. If
   you convert a built-in's SKILL.md into a template, add its renderer branch
   in `skills/push.py:_render_template` in the same change. The
   static copy skips template sources, and a templated built-in with no
   renderer only logs a warning, so the skill ships no SKILL.md.
9. `unresolved-marker-fails` **An unresolved `{{` marker fails the render.**
   `skills/rendering.py:render_external_app_skill` raises rather than send broken instructions.
   Other `.template` files in an app skill get only `{{APP:...}}` values and no
   such check.
10. `app-skill-org-visible` **An app skill stays visible to the
    organization.** `db/skill.py:set_skill_public_permission` accepts only `VIEWER` for a
    skill linked to an external app, except company marketplace skills. App linking
    preserves their access. A private custom skill must have an
    owner or a marketplace: `ck_private_skill_has_owner` enforces this in SQL,
    and the visibility setter applies the same rule. Transfer or delete private
    uploaded skills before removing their owner.
11. `push-holds-row-locks` **The push holds row locks during network I/O.**
    `skills/push.py:push_skills_for_users` locks the target `Sandbox` rows, then calls the
    sandbox push while the transaction is open. The hash write is a savepoint,
    and the caller commits. The push catches and logs every exception, so a
    failed push never fails the API call. The next push repairs it, because
    the hash of a failed sandbox is not written.
12. `sharing-single-entry` **Access writes use the resource adapter.**
    `db/resource_access.py:mutate_resource_access` handles single and bulk changes.
    `db/skill.py:SkillAccessAdapter` supplies skill grants with real foreign keys,
    locked EDIT authorization and eligibility checks. Company visibility and
    installation settings require global `MANAGE_SKILLS`, even for owners.
    Changed group grants and explicit group settings use `assert_within_scope`
    against stored groups and visibility. Group managers cannot change another
    group's settings or company settings. An omitted group setting preserves
    its value; explicit NULL clears it. Group settings remain unused at runtime
    until effective-policy resolution ships. NOT_AVAILABLE remains rejected.
    Bulk sharing adds or updates grants and preserves omitted grants. It reads
    affected users in two batch queries and pushes once after commit. Expected
    failures roll back one skill's savepoint. Bulk toggles affect only the caller.
    Company marketplace access changes clear `follows_marketplace_access`;
    unchanged shares keep the setting.
    `db/skill_mutation.py:assert_skill_mutable` refuses retired user mutations;
    deletion explicitly allows retirement. New access entry points must use the
    adapter function, not `db/skill.py:replace_skill_shares`.
    `POST /skills/custom/batch` and GitHub import create each bundle through
    `db/skill.py:create_skill_from_bundle__no_commit`, one savepoint per skill,
    so a bad bundle or a name conflict under a DEFAULT or REQUIRED policy lands
    in `not_imported` and the other skills still import.
13. `pptx-scripts-serve-previews` **The `pptx` skill's preview scripts also
    render Craft output previews.**
    `server/features/build/sandbox/base.py:document_preview_command` runs
    `skills/builtin/pptx/scripts/preview.py` and its LibreOffice helper,
    mounted under a versioned path apart from the managed skills. A change to
    those scripts changes PDF and PowerPoint thumbnails in the output panel
    ([[craft-sandboxes]]).
14. `built-in-removal-needs-migration` **Removing a built-in needs a
    migration that deletes its rows.** `_assemble_fileset` skips, with a
    warning, a `skill` row whose `built_in_skill_id` is not in
    `skills/built_in.py:_REGISTRY`, so the rows otherwise stay.
15. `version-rollout-reads` **Custom readers use `Skill.current_version`.**
    Its eager outer join retains built-ins, which have no versions. A custom
    row without a pointer cannot load or enable. Locks on joined skill queries
    must specify `of=Skill`. Reload `current_version` after a locking read before
    using its content or validity. A statement that waits on a concurrent edit
    can combine the new skill pointer with the old joined version snapshot.
    Publishing also refreshes the loaded relationship. Custom writers call `db/skill_version.py`, which
    adapts the generic `db/resource_version.py` service. A row lock serializes
    version numbers. The version, pointer and legacy columns change in one
    transaction. Equal content digests keep the current version and stored-byte
    hash. `utils/bundle.py:compute_bundle_metadata` computes the digest without
    database imports; ZIP timestamps and entry order do not affect it. See
    [[#bundle-retention]] for which bundle files stay.
    Legacy columns remain for V2 compatibility and repair. A save repairs a stale
    or missing pointer before writing its new content. A recovery snapshot has
    no creator; a user content change follows it. Runtime classification updates
    the observed current version only while it remains unclassified. It also
    updates legacy validity when the bundle links match, without creating history.
    Identical user saves verify the existing bundle before reusing it. A missing,
    changed or unreadable current file creates a fresh version from the upload.
    Missing, corrupt or oversized historical files retain unknown metadata.
    Repair receives `skills/bundle.py:STORED_BUNDLE_LIMITS`: stored bytes use
    the larger configured total or ZIP allowance. Expansion counts actual
    per-file and total bytes. No upload ZIP or file-count cap applies to history.
    Current-content reads verify expansion before inspection or editing.
    Stored-byte and expansion limits return 400 through the ValueError handler.
    Metadata hashes original entries without normalization. Built-ins have
    no versions. `background/celery/tasks/skill_versions/tasks.py` repairs each
    tenant in bounded batches through Celery or Lite's API poller. The base
    interval is five minutes; cloud uses the standard beat multiplier (eight
    by default). Repair prunes bundle links under the skill lock, then deletes
    unreferenced files after commit, with the same retention rule as saves.
    The deadline is cooperative between skills;
    a single skill's blob reads can exceed it. Each skill commits before its
    UUID cursor advances. Transient reads fail without advancing progress.
    Progress reloads from PostgreSQL because KV caching precedes its commit.
    After the initial scan, `db/skill_version.py:skill_version_repair_batch`
    checks pointer, file, hash and validity drift with an outer join and
    null-safe comparisons. This catches old-writer edits and pointerless
    inserts below the cursor. The completed flag means only the initial scan
    finished. Before switching readers, drain old writers and require a fresh
    empty drift query, not that flag. Follow [[#cut-over-version-readers]].
    No migration reads blobs.
16. `skill-dir-placeholder` **Skill paths resolve to the sandbox folder.**
    `skills/push.py:_resolve_skill_dirs` replaces each `${CLAUDE_SKILL_DIR}` in
    a skill's root SKILL.md with `/workspace/managed/skills/<name>`. Only the
    sent bytes change. The stored bundle, its SHA-256 and other files keep the
    placeholder. The sent bytes feed the runtime hash. OpenCode adds the base
    folder line and the relative-path rule itself, so the push adds neither.
    `backend/tests/unit/onyx/skills/test_skill_dir.py` fails when the sandbox
    `OPENCODE_VERSION` pin changes, so the next pin bump checks that OpenCode
    still does this. A harness that loads skills in the API server must give the
    model `skills/rendering.py:render_skill_for_model`, which resolves the
    placeholder and adds the same two lines. No such harness is on main yet.
17. `marketplace-provider-boundary` **Only the provider adapter reads provider
    config.** `skills/marketplace/provider.py:MarketplaceProviderAdapter` owns
    login checks, ref resolution, change checks and webhook capability. GitHub
    verifies every ref, including pinned commits, and fetches one bounded archive
    at that commit. The reader receives bytes and a folder. Reconciliation receives
    its result and staged bundle metadata.
    Config and import share repository-name and folder validation in `utils/github.py`.
    Empty folders become NULL; trailing slashes are removed. Absolute paths and
    dot segments are rejected.
    Webhooks remain unsupported until the self-hosted webhook ticket ships.
18. `marketplace-ownership` **A personal marketplace blocks owner deletion.**
    Its owner FK uses RESTRICT; the login and version creator FKs use SET NULL.
    `db/users.py:delete_user_from_db__no_commit` names owned marketplaces and
    records a login error when deleting another marketplace's login user.
    A missing, inactive or disconnected login stops the adapter before fetch.
    A missing or disabled workspace GitHub app instead asks an admin to enable it.
    Downgrade refuses every ownerless marketplace skill, including public ones,
    and every retired skill. Dropping retirement state would revive deleted entries.
    Entry keys identify the plugin entry and skill, not the folder; only live
    entries are unique, so a retired entry can return as a new skill.
    Every marketplace skill must have an entry key; the database rejects NULL keys.

19. `bundle-retention` **Every version row stays; retained files follow `BUNDLES_KEPT`.**
    Under the version lock, `db/resource_version.py:prune_resource_bundles`
    empties `bundle_file_id` on versions older than the retention cutoff (never the
    current one). Writers and skill delete return file ids; callers delete them
    after commit with `db/skill_version.py:delete_unreferenced_skill_bundles`,
    which keeps any file that a version row or the legacy
    `Skill.bundle_file_id` still uses. Old writers and pointerless skills use
    only the legacy column, so a cleanup that checks only versions deletes
    live bundles. The hourly `check_for_orphan_skill_bundle_cleanup` task uses
    the configured tenant-scoped cache lock. It retries failed deletes and
    removes `SKILL_BUNDLE` files older than `ORPHAN_BUNDLE_MIN_AGE` that nothing uses.
    Lite runs the same cleanup through `background/periodic_poller.py`.
    A pass stops between files after 30 seconds or 500 candidates. The cursor
    advances only past attempted files. One storage call can exceed the deadline.
    The cleanup renews its lease around each file deletion and before cursor writes;
    losing the lease stops the pass without advancing its cursor.
    A durable cursor advances past failed files within a fixed scan boundary,
    then wraps. New arrivals cannot postpone retries of earlier failures.
    An upload saves its file before its row commits, so
    a younger file can be live. A version preview or restore must read through
    `read_version_bundle` with the resource's stored-byte limit. It gives NOT_FOUND "The files of this version are
    no longer kept." for a pruned bundle, also when pruning wins a race. A
    restore that copies an old version must read it under the version lock.
20. `history-requires-edit` **History uses EDIT access, including its reads.**
    The `/skills/custom/{skill_id}/versions` family calls `fetch_skill` with
    `SkillManagementPolicy.EDIT` before listing or reading any history.
    `db/skill_version.py:fetch_skill_version` scopes version ids to that skill.
    Preview returns the historical bundle's description, instructions, and file
    list through `SkillBundleInspectResponse`; it validates expansion before inspection.
    Restore locks the skill, then reads the selected version and calls
    `server/features/skill/api.py:_replace_skill_bundle_from_editor`.
    Ingestion validates current upload limits and stages a new blob. The shared
    replacement refreshes the description and applies digest equality and retention.
    Never reuse the historical blob: this restore can prune its source version.
    Cleanup stays after the content commit and before the sandbox push.
21. `marketplace-processing-limits` **Archive processing has separate read and index limits.**
    `skills/marketplace/archive.py:archive_files` bounds gzip expansion and member
    reads separately from skill limits. Every supported stream read charges the
    shared byte budget. ZIP metadata reads are bounded before directory parsing;
    only stored and deflated members are supported. Path depth, path bytes and
    the aggregate parent index
    are bounded before retained path allocations can grow without limit.
    The index budget also counts each retained TAR PAX dictionary and its text
    objects; global headers must not multiply retained metadata without a limit.
    TAR enumeration also charges all metadata reads before a member returns.
    Each member also has its own metadata budget, so chained headers and sparse
    maps stop before large allocation or deep parser recursion. Sparse members
    fail the read. One member stream call returns at most `MEMBER_CALL_MAX_BYTES`
    and fails instead of truncating; callers read large members in chunks.
    It inflates gzip once into a temporary spool.
    `skills/marketplace/reader.py:read_marketplace_archive` reads only the
    declared marketplace. Blocked keys retain their current version; a failed
    read cannot retire anything. Shared paths reuse bundle bytes. Unique output
    has a separate ceiling, including nested paths. Mixed plugins are unsupported.
    Completed entries form an immutable snapshot. Present catalog metadata must
    be an object. Empty declarations cannot hide agent or command Markdown files.
    Tar reads require an end marker, including when gzip itself is intact.
    Missing explicit skill definitions keep their keys as blocked entries.
    Plugin manifest skill paths participate in discovery; Claude paths add to
    defaults, while Codex compatibility paths replace defaults. Entry paths
    suppress defaults but retain manifest paths. Overlapping paths load once.
    Declaring the default `skills/` directory preserves default child keys even
    when every definition is broken. Plugin entries and declared paths each
    have a 500-count processing budget; all manifests share the path budget, including agents and commands.
    Unique manifest bytes share a 25 MiB budget, and parsed configs are reused by path.
    Invalid YAML, including excessive nesting, blocks only the affected skill.
    See `backend/onyx/skills/marketplace/README.md` for limits and format differences.
    This pure reader does not change the one-time GitHub import.
22. `marketplace-reconciliation` **Only complete reads can retire entries.**
    `db/marketplace.py:reconcile_marketplace__no_commit` takes S2 results and staged
    `IngestedBundle` values. It does no provider or FileStore I/O. Failed reads
    change nothing. A savepoint covers rows, versions, paths, blocked reasons,
    and the synced revision. The caller owns commit and post-commit cleanup.
    Changed entries require a staged bundle whose name and digest match the read.
    Healthy unchanged digests need no upload. Explicit `recovery_keys` require
    fresh staged bundles and bypass digest reuse. The shared version writer and retention
    functions maintain history and legacy columns; save-time storage repair is skipped.
    Missing keys retire permanently; reappearance creates a new id. Moves retain ids.
    Unsupported plugin keys protect all their existing child skills. Blocked keys
    keep their versions; `Marketplace.blocked_entries` stores reasons for the later UI.
    More than five retirements AND more than half the live marketplace sets
    `last_error` to "needs confirmation" and leaves skills and synced revision intact.
    New names conflict only within a library. Synced skills use marketplace ownership;
    public manual skills use the company library, private manual skills use their author.
    Reconciliation serializes each tenant/library with a transaction advisory lock.
    G3 must use that same lock for manual name checks. S5 owns job
    freshness; S6 owns retired-read/write guards; S7 owns access materialization.
    No API or worker calls the sync service yet.
23. `marketplace-sync-staging` **Upload first, commit once, then clean unused files.**
    `skills/sync.py:sync_marketplace` owns the sessions and commit. Call it in the
    target tenant context after authorization. A detached current-version snapshot
    uses object metadata to detect missing bundles without reading their content.
    Source changes trigger bounded content verification; unchanged sources do not
    detect corruption in existing blobs. Unknown size falls back to bounded verification.
    Missing bundles force a fetch, except keys already blocked at that revision.
    A forced fetch that changes nothing returns no work. Storage failures stop sync.
    Ingestion preparation runs before upload; validation failures become blocked
    entries with their original keys. Storage failures abort the entire sync.
    Each attempted upload uses a fresh tracked file id. Reconciliation commits all
    skill, version and revision changes together. Before a commit attempt, failure
    cleanup checks only this run's ids. After a commit attempt fails, defer cleanup
    to the aged orphan sweep: the server may still commit. Success cleanup also
    checks pruned ids. Cleanup preserves version and legacy references.
    V3 retries failed cleanup and removes aged uploads left by a stopped worker.
    S5 must serialize the full read/upload/write operation and reject stale revisions.
    S8 owns the retirement confirmation override. Neither is implemented here.

---

## Decisions

- **Rendered files, not a manifest, go into the hash.** Any change in rendered
  output, such as a new app connection or a denied action, marks sessions
  stale with no list of inputs to maintain.
- **A stale notice, not an automatic reload.** Reload disposes the live
  runtime, so the user chooses when. It refuses while a turn runs.
- **App lifecycle keeps user intent.** Disconnecting an app deletes the user's
  enabled selections for its skills and keeps opt-outs
  (`db/external_app.py`). Deleting an app resets its custom skills to
  available and deletes their preferences. Its built-in skill row is deleted.

---

## Known issues

- **Marketplace access reset is not connected.** Marketplace storage has group
  grants but no company visibility or installation-policy fields. S7 must add
  those defaults and copy them through the access mutation function, restoring
  `follows_marketplace_access` in the same transaction. Plugin membership is not
  modeled yet; its access guard belongs in `SkillAccessAdapter.load`.

- **GitHub import checks a skill's shape, not its content.** Import enforces
  archive size and member limits, path safety and frontmatter rules. Nothing
  inspects the instructions or bundled scripts. A harmful skill is contained
  only by the sandbox and its egress proxy ([[craft-sandboxes]],
  [[craft-external-apps]]).
- **App skills reflect only workspace DENY.** `skills/rendering.py` lists an
  action as unavailable when its workspace policy (stored override or catalog
  default) is DENY, or when cloud withholds it. Personal and task DENY choices
  are not listed, so the agent can try an action that the proxy then blocks
  ([[craft-external-apps]]).
- **External-app admin writes push in different orders.**
  `server/features/build/external_apps/api.py:update_external_app_admin`
  commits and then pushes. `create_built_in_external_app` and
  `delete_external_app_admin` push before the commit. Their comments say a
  push failure rolls back the change, but `push_skills_for_users` logs and
  drops every failure ([[#push-holds-row-locks]]), so the change commits
  anyway. If that commit fails, the sandboxes hold files that the database
  does not.
- **Membership changes do not push.** A user added to a group that a skill is
  shared with gets it at the next push, session start or reload.

---

## Dependencies

- [[craft-sandboxes]]: `push_to_sandboxes` and the managed volume.
- [[craft-sessions]]: the stale check and the reload that apply a push to a
  live runtime.
- [[craft-external-apps]]: app readiness and action policy views. GitHub
  import and preview authenticate with the user's GitHub app credential
  (`skills/github_auth.py:github_authorization_header`).
- [[authorization]]: `MANAGE_SKILLS` and the scoped-manager group check
  (`assert_within_scope`).
- [[file-store-and-user-files]]: bundle blobs.
- [[image-generation]]: the image skill is available only when image
  generation is configured.

---

## Recipes

- `add-built-in-skill` **Add a built-in skill.** Copy `pptx` for a static skill, or
  `image-generation` for one that depends on a service through
  `is_available`. List the current set with `ls backend/onyx/skills/builtin/`
  and the providers in `skills/built_in.py:_REGISTRY`. Import-time checks fail
  on a duplicate id, a duplicate app type, a missing source file, or
  frontmatter whose `name` does not match the directory. A seeded
  built-in needs a migration that creates its row. An app built-in gets its
  row when an admin connects the app ([[craft-external-apps]]).
- `add-templated-built-in` **Add a templated built-in.** Copy `company-search`: a SKILL.md.template
  plus a renderer branch in `_render_template`
  ([[#templates-built-in-only]]). Put every value the renderer reads into the
  rendered bytes ([[#rendering-input-changes-hash]]).
- `add-skill-mutation-route` **Add a skill mutation route.** Copy `share_current_user_skill` in
  `server/features/skill/api.py`: compute `affected_user_ids_for_skill`
  before the change, apply it, compute it again, commit, call
  `push_skills_for_users` with the union, then commit again
  ([[#affected-users-before-change]]).
- `investigate-skill-missing` **Investigate "my skill is not in the sandbox".** Check the inputs of
  `list_runtime_skills_for_user` one at a time for that user: visibility,
  `_is_enabled_for_user`, app readiness, `Skill.current_is_valid`, and built-in
  availability. Then compare `Sandbox.skills_hash` with
  `BuildSession.skills_hash`: equal means the runtime loaded the last push;
  different means the session waits for a reload. Search the API server log
  for `Skill push failed` for a failed push.
- `cut-over-version-readers` **Gate version readers after legacy writers drain.**
  First deploy version writers and the version repair task everywhere. Stop and drain every API,
  worker, Lite poller and script that can still write only legacy columns.
  Keep current-version readers off until the following check passes for every tenant and shard.
  Run the existing repair task until a fresh drift query returns no rows.
  The repair completed marker does not authorize cutover. Old writers can create
  drift after that marker is set.

  Use the target shard's database configuration and the application's backend path:

  ```bash
  PYTHONPATH=backend uv run python backend/scripts/check_skill_version_cutover.py --tenant-id public
  ```

  Substitute each tenant schema for `public`. Exit 1 reports the first batch of
  drifted skill IDs; a database error also blocks deployment. Run the existing
  `repair_skill_versions` task for that tenant, then repeat the check in a new
  process. Do not replace missing blobs with empty bundles. Recover their source
  and upload again when repair cannot recover them. The query checks database
  drift, not blob availability. Retain the command output, tenant, shard and
  deployed writer revision. Deploy current-version readers only after every check exits 0 and legacy
  writers remain stopped. Keep legacy dual writes and version repair through this release.
- `test-skill-setup` **Set up skills for a test.** Use the integration manager
  `backend/tests/integration/common_utils/managers/skill.py`. A real push
  needs the Kubernetes harness in `backend/tests/integration/tests/craft/k8s/`.

---

## Verification

- `backend/tests/unit/onyx/skills/` covers bundles, validation, rendering and
  GitHub import.
- `backend/tests/external_dependency_unit/craft/` (the `test_skill*` files)
  covers visibility, the fileset, affected users, ownership and push faults.
- `backend/tests/integration/tests/skills/` covers the API, bulk actions and
  import sharing. `backend/tests/integration/tests/craft/k8s/` covers a real
  push.
- By hand: edit a skill while a Craft session runs. The stale notice must
  appear, and after reload the agent must read the new text.
