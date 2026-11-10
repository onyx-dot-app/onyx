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
  and the user cannot turn it off). Only an admin can delete a required skill.
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
  History returns at most 50 rows. The positive `before_version` cursor excludes
  that version and loads older rows without shifting when a new version is saved.
  Restore always creates a new version, also for the current version's content.

When it fails:
- A bundle with bad frontmatter, an unsafe path, a reserved name, or a
  `.template` file is rejected with a message. A direct upload over a size or
  file count limit is rejected with a 413 that names the limit. Batch uploads
  list the Skill in `not_imported`, and a GitHub preview marks it unavailable.
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
built-in skill definitions; per-user rendering of templates; GitHub import;
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

Version history selects the current marker in the same SQL snapshot as its rows.
Restores use stored-data admission, including the stored-byte ceiling and
expanded-byte checks. Upload file-count limits do not reject retained versions.

Metadata repair recovers retained history before clearing old bundle links.
This keeps size and file count after retention deletes the files.
Versions with incomplete metadata keep their links and remain repair candidates.
Only confirmed absence clears a non-current link; transient failures retain it.
Background repair isolates each skill in a savepoint. Both scan phases advance
through failures and retry pending work after the cursor wraps. User saves
still propagate unexpected storage errors.

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
   user and name. `uq_skill_automatic_name` allows one default or required
   skill per name in the tenant. Every write that enables a preference first
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
   Stored-bundle reads follow `bundle-size-limits`.
   Current-content reads, history preview and restore return 413 with the stored read
   limit when that allowance is exceeded (`skills/content.py:read_stored_version_bundle`).
   A missing current bundle returns `INTERNAL_ERROR`, not the 404 for a pruned version.
   Version metadata repair also bounds compressed reads at the storage backend
   and expanded work per file and in total, without applying upload file counts.
   Skill deletion collects every retained bundle before cascading version deletion.
   Cleanup runs after commit and checks both legacy and version references.
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
    skill linked to an external app. A private custom skill must have an
    owner: `ck_private_skill_has_owner` rejects a private skill with no
    author, so transfer or delete private skills before their owner is
    removed.
11. `push-holds-row-locks` **The push holds row locks during network I/O.**
    `skills/push.py:push_skills_for_users` locks the target `Sandbox` rows, then calls the
    sandbox push while the transaction is open. The hash write is a savepoint,
    and the caller commits. The push catches and logs every exception, so a
    failed push never fails the API call. The next push repairs it, because
    the hash of a failed sandbox is not written.
12. `sharing-single-entry` **Sharing and policy writes go through
    `db/skill.py:share_skill__no_commit`.** The share route, the editor create
    route, the patch route's visibility change, bulk sharing and imports with
    access settings all call it with a `SkillSharingChange`
    (`SkillShareRequest.to_change()` builds one). A change
    to `installation_policy` needs `FULL_ADMIN_PANEL_ACCESS`, and
    `db/skill.py:set_skill_installation_policy` refuses a built-in. EDIT on a
    skill is not enough to change its groups:
    `db/skill.py:_assert_group_share_within_scope` treats any change to the
    group set or levels as a `MANAGE_SKILLS` action within scope
    ([[authorization]]). Without it, an owner could push a skill into any
    group manager's scope. It compares against the stored shares, and the
    privacy check uses the stored visibility and the request, so a
    public-to-private change in the same request cannot get past it. A
    `public_permission` change needs the author or global `MANAGE_SKILLS`
    (`db/skill.py:ensure_can_edit_org_visibility`; the patch route calls it
    too). A new sharing entry point must call `share_skill__no_commit`, not
    `db/skill.py:replace_skill_shares`.
    Agents apply a looser form of the rule
    ([[agents-personas#group-share-needs-manage-agents]]).
    `POST /skills/bulk` applies each item in a savepoint, reports expected
    business errors per skill, and pushes the combined affected audience after
    commit. Bulk enable and disable change only the caller's preference.
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
    Publishing also refreshes the loaded relationship. Custom writers call
    `db/skill_version.py:write_skill_version`. A row lock serializes
    version numbers. The version, pointer and legacy columns change in one
    transaction. Every save and upload adds a version, also when its content
    is equal to the current version; there is no content digest.
    `utils/bundle.py:compute_bundle_metadata` computes the unpacked size and
    file count without database imports. See
    [[#bundle-retention]] for which bundle files stay.
    Legacy columns remain for V2 compatibility and repair. A save repairs a stale
    or missing pointer before writing its new content. A recovery snapshot has
    no creator; a user content change follows it. Runtime classification updates
    the observed current version only while it remains unclassified. It also
    updates legacy validity when the bundle links match, without creating history.
    Unexpected storage errors abort the save and keep the current version.
    Missing or corrupt historical files retain unknown metadata. Each version
    also stores its root SKILL.md outside the bundle: `name` (the frontmatter
    name), `frontmatter` (the parsed YAML as JSON) and `skill_md` (the raw file,
    loaded on access only). The raw `skill_md` is authoritative; `frontmatter`
    is a derived JSON copy with dates as ISO strings. A value that PostgreSQL
    cannot store (NaN, non-string keys, NUL, binary) leaves that column NULL
    and marks the version `metadata_unrepairable`. Writers fill them from the
    ingest parse in the same transaction. The initial and recovery snapshots
    keep them NULL until repair.
    Repair checks physical object metadata for complete history without downloading
    its payload. Incomplete metadata still needs a bounded bundle read.
    Confirmed missing historical objects lose their file links; current links remain
    recoverable. Missing primary buckets, containers, and uncertain errors keep the links.
    A confirmed primary object miss plus an absent legacy bucket confirms absence.
    Historical failures use separate savepoints so current pointer recovery can commit.
    Built-ins have no versions. `background/celery/tasks/skill_versions/tasks.py` repairs each
    tenant in bounded batches through Celery or Lite's API poller. The base
    interval is five minutes; cloud uses the standard beat multiplier (eight
    by default). Repair prunes bundle links under the skill lock, then deletes
    unreferenced files after commit, with the same retention rule as saves.
    The task has a 300-second soft time limit. Its 30-second deadline is checked
    between skills and between historical versions of one skill; a single blob
    read can exceed it. The current version is always repaired. When the
    deadline stops a skill, the KV key `skill_version_repair_resume:<skill id>`
    saves the version number, and the next pass starts with older versions.
    Versions left without metadata stay in the drift query.
    Metadata includes the SKILL.md columns. When `frontmatter` is NULL, repair
    fills `name`, `frontmatter` and `skill_md` from the bundle's root SKILL.md
    with `skills/metadata.py:parse_skill_md_frontmatter`, within the stored limits.
    Invalid YAML keeps the raw `skill_md` and leaves `frontmatter` NULL. A
    missing root SKILL.md stores nothing. Each of these, and any column that
    PostgreSQL cannot store, sets `metadata_unrepairable`, so repair stops.
    A bundle that cannot be decoded sets `metadata_unrepairable`. Repair stops
    retrying it, the drift query skips it, and pruning treats it as complete.
    A bundle over a configurable size limit keeps empty metadata. It stays in
    the drift query and keeps its file, so repair succeeds after the limit rises. Each skill commits
    before its UUID cursor advances, including failed attempts. Failed work remains eligible
    for retry after the cursor wraps.
    Progress reloads from PostgreSQL because KV caching precedes its commit.
    After the initial scan, `db/skill_version.py:skill_version_repair_batch`
    checks pointer, file, hash and validity drift with an outer join and
    null-safe comparisons. This catches old-writer edits and pointerless
    inserts below the cursor. The completed flag means only the initial scan
    finished. After an upgrade, a fresh empty drift query confirms the result,
    not that flag. Follow [[#cut-over-version-readers]].
    No migration reads blobs.
16. `skill-dir-placeholder` **Skill paths resolve to the sandbox folder.**
    `skills/push.py:_resolve_skill_dirs` replaces each `${CLAUDE_SKILL_DIR}` in
    a skill's root SKILL.md with `/workspace/managed/skills/<name>`. Only the
    sent bytes change. The stored bundle, its SHA-256 and other files keep the
    placeholder. Before substitution, the push checks the predicted instruction
    size against both the configured file limit and the receiver file limit.
    Expansion must also fit the receiver total, including other Skills. An
    oversized expansion skips that whole Skill, logs a warning and continues.
    Files without placeholders keep their previous delivery behavior.
    The sent bytes feed the runtime hash. OpenCode adds the base
    folder line and the relative-path rule itself, so the push adds neither.
    `backend/tests/unit/onyx/skills/test_skill_dir.py` fails when the sandbox
    `OPENCODE_VERSION` pin changes, so the next pin bump checks that OpenCode
    still does this.
17. `bundle-size-limits` **Upload limits never lower the stored-read
    allowance.** `skills/bundle.py` reads its five `SKILL_BUNDLE_*` settings
    with `configs/constants.py:positive_int_from_env`. A value that is not a
    positive integer logs an error and sets `SKILL_BUNDLE_SETTINGS_ERROR`.
    Then `assert_skill_bundle_settings_valid` refuses every upload, edit,
    GitHub import and stored read with `SERVICE_UNAVAILABLE`, and the zero
    limits fail closed. Batch uploads catch it per Skill and report
    `not_imported`. `skills/validation.py:validate_stored_custom_skill` returns
    `is_valid=None` for `SERVICE_UNAVAILABLE` and `PAYLOAD_TOO_LARGE`, so the
    push skips the Skill without saving it invalid; it loads again when the
    settings change. Stored-bundle reads
    (`skills/validation.py:load_stored_custom_skill_bundle`) skip the upload
    ZIP-size and file-count limits but keep the per-file and expanded-total
    limits. Their allowance defaults to `stored_zip_allowance`: the larger of
    100 MiB and the total limit, plus ZIP framing, so bundles saved before the
    ZIP limit existed still load. An explicit
    `SKILL_BUNDLE_STORED_ZIP_MAX_BYTES` wins. The upload ZIP limit is capped at
    the allowance. A direct upload over a limit returns 413; batch uploads
    report `not_imported` and GitHub previews mark the Skill unavailable.
18. `bundle-retention` **Every version row stays; retained files follow `BUNDLES_KEPT`.**
    Under the version lock, `db/skill_version.py:prune_skill_bundles`
    empties `bundle_file_id` on versions older than the retention cutoff (never the
    current one). Writers and skill delete return file ids; callers delete them
    after commit with `db/skill_version.py:delete_unreferenced_skill_bundles`,
    which keeps any file that a version row or the legacy
    `Skill.bundle_file_id` still uses. Old writers and pointerless skills use
    only the legacy column, so a cleanup that checks only versions deletes
    live bundles. The hourly `check_for_orphan_skill_bundle_cleanup` task runs
    on the primary queue with a 300-second soft time limit and uses
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
    `read_version_bundle`, which gives NOT_FOUND "The files of this version are
    no longer kept." for a pruned bundle, also when pruning wins a race. A
    restore that copies an old version must read it under the version lock.
19. `history-requires-edit` **History uses EDIT access, including its reads.**
    The `/skills/custom/{skill_id}/versions` family calls `fetch_skill` with
    `SkillManagementPolicy.EDIT` before listing or reading any history.
    `db/skill_version.py:fetch_skill_version` scopes version ids to that skill.
    Preview returns the historical bundle's description, instructions, and file
    list through `SkillBundleInspectResponse`; it validates expansion before inspection.
    Restore locks the skill, then reads the selected version and calls
    `server/features/skill/api.py:_replace_skill_bundle_from_editor`.
    Ingestion uses stored-bundle limits and stages a new blob. It preserves legacy
    file counts while checking bytes, paths, and names. The shared
    replacement refreshes the description, adds a version and applies retention.
    Never reuse the historical blob: this restore can prune its source version.
    Cleanup stays after the content commit and before the sandbox push.

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
  (`server/features/skill/api.py:_github_authorization_header`).
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
- `cut-over-version-readers` **Check version readers after an upgrade.**
  Version writers, the version repair task and current-version readers ship in
  one release. No setting turns current-version readers on or off. During a
  rolling upgrade, a pod that still runs the old code can edit only the legacy
  columns. Until the repair task runs (every five minutes), that skill can show
  its previous content. The repair completed marker does not prove that no drift
  remains, because old pods can create drift after it is set.

  After every pod runs the new release, run this check for every tenant and
  shard. Use the target shard's database configuration and the application's
  backend path:

  ```bash
  PYTHONPATH=backend uv run python backend/scripts/check_skill_version_cutover.py --tenant-id public
  ```

  Substitute each tenant schema for `public`. Exit 1 reports the first batch of
  drifted skill IDs; a database error also fails the check. Run the existing
  `repair_skill_versions` task for that tenant, then repeat the check in a new
  process. Do not replace missing blobs with empty bundles. Recover their source
  and upload again when repair cannot recover them. The query checks database
  drift, not blob availability. Versions marked `metadata_unrepairable` do not block it. A version over a
  configurable size limit blocks it until you raise that limit and repair runs again.
  Keep legacy dual writes and version repair in this release.
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
