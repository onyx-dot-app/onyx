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
  opts in), installed by default (on until the user opts out), required (on,
  and the user cannot turn it off), or not available (hidden). With no own
  setting ("Organization default") the skill follows Default Access; an own
  `AVAILABLE` overrides a stricter Default Access. This needs
  organization-wide `MANAGE_PLUGINS`, which only admins hold today. A group
  setting (`SkillGroupShareRequest.installation_policy`, or
  `SkillShareRequest.group_settings` with no share change) replaces it for that
  group's members; a group manager sets it only for their groups, on a private
  skill shared only within them. The group page reads and writes these
  settings through `GET /manage/admin/user-group/{id}/plugins` and
  `PUT .../plugins/{plugin_id}` (EE, `ee/onyx/server/user_group/api.py`): a
  published skill gets a setting-only row; a private skill the group does not
  have yet is shared as viewer. The **Plugins** tab of the group page
  (`web/src/views/admin/GroupsPage/GroupPluginsTab.tsx`, shown with
  `manage:plugins` while Craft is available) edits them; each row saves on
  its own, apart from the group form's Save. The share dialog and the bulk
  dialog have a **Group Access** section
  (`web/src/sections/modals/skills/SkillGroupAccess.tsx`) for `manage:plugins`
  holders: one row per group with its setting. Every level label and help text
  (share dialog, bulk dialog, group tab, Default Access, card badge) comes from
  `web/src/lib/skills/installationPolicy.ts` and the
  `skills.installationPolicy.*` keys. Only organization-wide `MANAGE_PLUGINS`
  deletes a skill that is required for anyone.
- **Admin skill policies** on Admin Panel → Craft → Preferences: Skill
  Publishing ([[#publishing-review]]), **Default Access** (the Organization
  library default for published skills with no own setting: Available,
  Installed by default or Not available; never Required) and **Sharing** (off:
  only organization-wide managers add user or group shares).
- **Bulk management.** Craft's Skills library and **Admin Panel → Skills**
  support selection of custom skills, bulk access and installation changes,
  personal enable/disable, and confirmed deletion. Admins see all manageable
  custom skills. Bulk sharing adds or updates supplied individual grants;
  omitted visibility and installation settings remain unchanged. Failed items
  stay selected. Search and group filter changes clear selection.
  `SkillResponse.group_summaries` lists every `plugin__user_group` row (group,
  permission or none, setting) to a caller who may edit the skill, and to a
  scoped manager only the rows of their groups
  (`server/features/skill/response_helpers.py:_group_summaries`). Custom cards
  show them as a groups line, and the list has a group filter built from them;
  other members get an empty list, so the filter is hidden for them.
  Custom cards show Personal, Shared, or Organization access from
  `public_permission` and the server's `is_personal`; share-detail arrays can
  be hidden, so empty arrays do not mean a skill is personal.
- **Skill limit notices.** A refused write (413 `SKILL_LIMIT_EXCEEDED`) shows
  its error where the user made the change: a user sees their size and file
  count after the change, an admin the number of users who would go over. One
  formatter, `web/src/lib/skills/limits.ts:useSkillLimitCopy`, reads
  `skill_limit` from a skills API error (`responseBody`) or a `FetchError`;
  per-item failures (bulk, batch upload, GitHub import) carry their own
  `skill_limit`. At session start, `SkillRuntimeNotice`
  (`web/src/app/craft/components/`) raises one error toast when
  `SessionResponse.skill_omissions` lists skills the run-time rule left out:
  count, 900 MB, each skill with its size, **Manage skills** and **Dismiss**.
  It waits while the session is stale and shows once for each omission set
  (`skillOmissionsKey`). App connect shows the skills it left off
  (`web/src/sections/skills/SkillOmissionList.tsx:useSkillsLeftOffToast`),
  also through an OAuth completion message. The admin Skills page shows
  `SkillLimitUsersBanner` (`web/src/sections/skills/`) when
  `GET /skills/users-over-limit` lists users.
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

When it fails:
- A bundle with bad frontmatter, an unsafe path, a reserved name, or a
  `.template` file is rejected with a message. A direct upload over a size or
  file count limit is rejected with a 413 that names the limit. Batch uploads
  list the Skill in `not_imported`, and a GitHub preview marks it unavailable.
- Turning on a skill whose name another enabled skill the user can see uses
  returns a name conflict. The client can retry with `replace_conflict` to
  switch skills. The kept choice of a skill the user can no longer see neither
  blocks the switch nor changes.
- When two enabled skills still share a name, for example after a share or a
  publish, the sandbox gets one of them by the name order. The other shows as
  off. The push does not fail.
- A required skill rejects a toggle.
- If a push to a sandbox fails, the change still saves. The sandbox keeps its
  old skills until the next push, session start or reload.
- A reload while a turn runs is refused with a message to wait.

---

## Scope

This component owns the skill row, its shares, installation policy and user
preferences; the plugin tables ([[#plugin-tables]]); bundle parsing and validation; built-in skill definitions;
per-user rendering of templates; GitHub import; the push of a user's skill
files into a sandbox; and the skills library UI.

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
       lock_sandbox_skills_states        SELECT ... FOR UPDATE on Sandbox rows
       per sandbox, in id order (one payload in memory at a time):
       build_user_skills_payload         -> UserSkillsPayload (files, omissions)
         list_runtime_skills_for_user    db/skill.py: the one runtime gate; each custom
                                         skill comes with the plugin version the user
                                         runs (version_user_runs, outer joins)
         runtime_plugin_charges          db/plugin_access.py: keep group, order time and
                                         charged size of each plugin (run-time limit)
         _assemble_skills                keep order, whole plugins within 900 MB and
                                         10,000 files; built-ins from disk, custom from
                                         the FileStore bundle of that version, in a
                                         folder named by its frontmatter; resolves
                                         ${CLAUDE_SKILL_DIR}
         build_connectable_apps_list     guidance for unconnected apps
       compute_skill_runtime_hash        skip a sandbox whose hash matches
       push_to_sandbox(SKILLS_MOUNT_PATH)
       set_sandbox_skills_states__no_commit   hash + skill_omissions, only for
                                         successful pushes (omissions also on a hash skip)
  -> commit
session start: sandbox_lifecycle.py:build_managed_content_payload
  uses the same payload and hash, before the sandbox is RUNNING
```

**Two data models.** Each custom skill is also a plugin with the same id
(`db/plugin.py`). Every write goes to the legacy skill rows and the plugin
rows in one transaction. Every read of a custom skill uses the plugin rows
(`db/plugin_access.py`, [[#plugin-tables]]): access, names, validity, bundles
and content. Built-in skills have no plugin. Each access
write in `db/skill.py`, `db/external_app.py` and
`ee/onyx/db/community_downgrade.py` calls one `db/plugin.py` helper that
mirrors it. Lock order: the skill row, then the plugin row; many in id order.
A skill switch locks its target skill `FOR NO KEY UPDATE`: another user's
switch inserts a preference for that skill while it holds a plugin lock, and
a `FOR UPDATE` blocks that foreign-key check into a deadlock. App connect
locks the app row `FOR KEY SHARE`, the user, the app's skill rows
`FOR KEY SHARE`, then the plugin rows, so it queues behind an app edit or an
admin setting change instead of a deadlock.

**The runtime gate.** `db/skill.py:list_runtime_skills_for_user` decides what
a sandbox gets. It combines visibility (`skill_visible_to_user`), enablement
and the name order (`_user_skill_selection`), app readiness, bundle validity
(`is_valid` of the version the user runs not false) and built-in availability
(`_exclude_unavailable_built_in_skills`). These inputs stay independent. A
required skill still needs a ready app and a valid bundle.

**Enablement.** `db/plugin_access.py:load_user_plugin_states` is the one rule
for API responses, toggles and the runtime gate. One query gives, for many
users and plugins, the install setting, visibility, the version the user runs,
its skill names and the user's choice under the setting: required is on,
default is on until an opt-out, available is on after an opt-in, a hidden
plugin is off and its saved choice stays. Built-ins are on.
`db/skill.py:_user_skill_selection` reads it for one user.

**Name order.** When two enabled skills of a user have one name,
`db/plugin_access.py:order_skill_names` keeps one: a built-in name, then a
plugin required for the user, then a published one, then the user's own,
then a shared one. The older plugin (`plugin.created_at`, then id) wins a
tie. The others come back as `HiddenSkillName` with a reason
(`SkillUserState.name_hidden`). Only skills that can run (valid version,
ready app) take part.

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
   never go stale. The hash covers the bytes of the version each user runs, so a
   change to `published_version_id` re-pushes to organization-only users.
2. `affected-users-before-change` **Compute affected users before the
   change.** `db/skill.py:affected_user_ids_for_skill` finds users with a running sandbox
   who can see the skill, by the plugin visibility rule in one query
   (`db/plugin_access.py:affected_user_ids_for_plugins`, which takes a set). It ignores preferences on purpose, so that a delete
   or a disable still pushes to the users who had the skill. The delete route
   reads the audience before it deletes. The share, transfer and edit routes
   push to the union of the audience before and after. A new mutation must do
   the same, or a user who loses access keeps the files.
3. `shared-read-predicates` **Every new read path must use the shared
   predicates.** Reads use `db/skill.py:skill_visible_to_user`. Edits use
   `db/skill.py:_is_editable_by_user`, through
   `db/skill.py:_skill_select_for_management_policy`. A
   query on `Skill` without them skips sharing. For a custom skill both read
   the plugin tables through the one copy of the rule in
   `db/plugin_access.py` (`plugin_visible_to_user`,
   `plugin_editable_by_user`, `installation_rank_for_user`,
   `version_user_runs`). There is no organization-wide edit: a legacy
   organization `EDITOR` row gives view access only. A `plugin__user_group`
   row with no permission holds only a group install setting and grants
   nothing. A group row whose own setting is `NOT_AVAILABLE` grants nothing
   either. The author and a direct share get at least available, also past a
   group `NOT_AVAILABLE`. Built-in skills have no plugin and keep their skill
   rows. A scoped manager edits a private skill only when every group share is
   in their groups and every user share goes to a member of those groups
   (`db/skill.py:_is_group_shared_only_within_managed_scope`, mirrored in
   `server/features/skill/response_helpers.py:user_permission_for_skill`).
4. `enablement-not-preference-row` **Never infer enablement from a preference
   row.** Use `db/plugin_access.py:load_user_plugin_states`. It reads
   `user_plugin_preference` and the install setting that applies to the user
   (`db/plugin_access.py:installation_rank_for_user`: the plugin's setting or
   its marketplace default, the most open non-default group setting, and at
   least available for the author or with a share). Disable writes `enabled=False`; it does
   not delete the row. A required policy overrides an opt-out without deleting
   it, so the opt-out returns when the policy goes back to default.
5. `name-uniqueness-in-db` **Only plugin.name is unique, per marketplace.**
   `uq_plugin_marketplace_name`: a new plugin with a used name takes the next
   free name (`db/plugin.py:free_plugin_name`), also when a concurrent create
   takes it first (`create_plugin__no_commit` retries). Publish and transfer
   refuse a clash with `CONFLICT`. Skill names repeat across plugins; never
   compare one with `plugin.name`. The legacy index
   `uq_skill_automatic_name` is gone: the run-time name order picks one of
   two automatic skills with one name. The dual write stores `AVAILABLE` for
   `NOT_AVAILABLE` and for no setting. The legacy `uq_user_skill_preference_name` allows one enabled
   legacy choice per user and name; `db/skill.py:_write_legacy_choice__no_commit`
   skips a legacy row it refuses, because reads use `user_plugin_preference`.
   A toggle conflicts only with skills the user can see. Every write that
   enables a preference first takes `db/skill.py:_lock_user_skill_preferences`,
   a `FOR NO KEY UPDATE` lock on the user row. The lock orders concurrent
   enables of one name, so the second one gets `SKILL_NAME_CONFLICT`. The
   lock does not block the `FOR KEY SHARE` locks that foreign-key checks take,
   so sharing writes that reference the user still run. A new preference
   writer, such as an auto-enable, must take the same lock.
   The run-time name order (Architecture, Name order) keeps one skill for each name,
   because the name is the sandbox directory. `skills/push.py:_assemble_fileset`
   applies it again (`db/skill.py:keep_one_skill_per_name`), so a duplicate
   never fails a push. For a custom skill that name is
   `frontmatter->>'name'` of the version the user runs.
6. `name-immutable` **A skill name never changes.** The frontmatter `name`,
   `Skill.name` and the bundle's wrapper directory, when there is one, must
   match (`skills/metadata.py:parse_skill_document`). Storage removes the
   wrapper. A rename is a delete and a new skill. Custom names cannot match a
   built-in.
7. `validate-before-sandbox` **Validate before content reaches a sandbox.**
   `_assemble_fileset` unzips the bundle of the version a user runs only when
   that version's `is_valid` is true, or after
   `skills/validation.py:validate_stored_custom_skill` passes for an
   unclassified version (it checks the name in the version's frontmatter).
   `db/skill.py:persist_skill_validity` writes the result to the plugin
   versions that hold that bundle and are still unclassified
   (`db/plugin.py:persist_plugin_version_validity__no_commit`), and copies it to
   the legacy skill row only while that row points at the same bundle.
   Writes check four limits in `skills/bundle.py:normalize_custom_bundle`.
   Count all non-directory archive entries, including ignored files. Check
   both the incoming and normalized ZIP sizes. Raw uploads use the per-file
   read cap; ZIP uploads use the ZIP cap.
   Stored-bundle reads follow `bundle-size-limits`.
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
    organization.** `db/skill.py:_ensure_external_app_skill_stays_public`
    accepts only `VIEWER` for a custom or built-in skill linked to an external
    app. The app link
    (`db/external_app.py:associate_custom_skill_with_external_app__no_commit`,
    `replace_custom_skill_associations__no_commit`) publishes the skill through
    `db/plugin.py:publish_plugin__no_commit`, and a name clash in the
    Organization library returns `CONFLICT`. A newly linked skill with no own
    setting gets an explicit `AVAILABLE`
    (`db/plugin.py:make_plugins_available_by_default__no_commit`), so Default
    Access Not available does not hide it. Publishing is one-way, so an
    unlinked skill stays published. A private custom skill must have an
    owner: `ck_private_skill_has_owner` rejects a private skill with no
    author, so transfer or delete private skills before their owner is
    removed.
11. `push-holds-row-locks` **The push holds row locks during network I/O.**
    `skills/push.py:push_skills_for_users` locks the target `Sandbox` rows, then builds
    and sends one sandbox at a time while the transaction is open. The hash write is a savepoint,
    and the caller commits. The push catches and logs every exception, so a
    failed push never fails the API call. The next push repairs it, because
    the hash of a failed sandbox is not written.
12. `sharing-single-entry` **Every share, publish and install setting change
    goes through `db/plugin.py:apply_plugin_access_change__no_commit`.** It
    takes a set of plugin ids, a `PluginAccessChange` (user and group grants,
    group settings with no share change (`PluginGroupSetting`: creates a
    setting-only row; None removes the setting and deletes a row with no
    permission), `publish`, a three-state company install setting, and a mode:
    replace or add-only) and the actor. A skill has no access of its own: the skills API
    passes the plugin with the skill's id. The function locks the legacy skill
    rows, then the plugins, in id order; checks the rules once for the set;
    writes each plugin and its legacy rows in a savepoint, so one failure rolls
    back that plugin only; and reads the affected users for the whole set
    before and after. The routes then commit and push once. The skills layer
    calls it through `db/skill.py:share_skill__no_commit` (share route, editor
    create, patch visibility, imports with access settings) and
    `db/skill.py:bulk_share_skills__no_commit` (bulk, add-only shares). The
    group page calls it through `db/plugin.py:set_group_install_setting__no_commit`
    (`ee/onyx/db/user_group_plugin.py` first checks that a scoped manager can
    edit a private plugin, because A1 does not check edit access).
    `db/skill.py:replace_skill_shares`, `set_skill_installation_policy`,
    `set_skill_public_permission` and `transfer_skill_ownership` are thin
    callers with no actor, so they skip the permission checks. Do not write
    `plugin__user`, `plugin__user_group`, `skill__user` or
    `skill__user_group` anywhere else.
    Rules: a company install setting needs organization-wide `MANAGE_PLUGINS`
    (`has_global_permission`; never `has_permission`, which accepts a scoped
    grant). In `SkillShareRequest`, a missing `installation_policy` changes
    nothing, null means no own setting (the marketplace default applies), and
    a value, `AVAILABLE` too, is the own setting. `SkillResponse.installation_policy`
    is the own setting or null, and `default_installation_policy` is the
    marketplace default. The share dialog sends the company setting only when
    the admin changed it (`lib/skills/sharing.ts:serializeSkillSharing`), so a
    save never turns "no own setting" into `AVAILABLE`. The legacy mirror
    (`db/plugin.py:plugin_installation_policy`, the backfill) still maps legacy
    `AVAILABLE` to no setting. A group
    keeps its install setting when the change does not set one, also when its
    share is removed (the row stays with no permission). A group install
    setting needs global `MANAGE_PLUGINS`, or `MANAGE_PLUGINS` for that group
    on a private plugin whose group and user shares all stay within the
    actor's groups (`db/plugin.py:_check_scoped_group_setting`). A group row
    cannot be `EDITOR` with `NOT_AVAILABLE`. With `Settings.plugin_sharing`
    off, only global `MANAGE_PLUGINS` adds a share or changes its level
    (`db/plugin.py:_check_sharing_setting`); removing one stays allowed. The
    legacy group rows leave out a row with `NOT_AVAILABLE`. A group
    membership change (group API, SCIM) pushes to the users who joined or
    left (`skills/push.py:push_skills_after_membership_change`). The
    Organization library default is written by
    `db/plugin.py:set_organization_library_default__no_commit`, which refuses
    `REQUIRED` and returns the affected users. EDIT on a skill is not enough
    to change its groups: any
    change to the group set or levels is a `MANAGE_PLUGINS` action within scope
    (`auth/scoped_permissions.py:assert_within_scope`, [[authorization]]).
    Without it, an owner could push a skill into any group manager's scope.
    It compares against the stored plugin group shares (rows with a
    permission), and the privacy check uses the stored visibility and the
    request, so a public-to-private change in the same request cannot get past
    it. Publishing needs the author or global `MANAGE_PLUGINS`
    (`db/skill.py:ensure_can_edit_org_visibility`; the patch route calls it
    too). `db/skill.py:_publish_requested` checks every request for
    organization access: it refuses organization `EDITOR` and a change from
    published to private, for every route, bulk included. The admin
    Publishing setting then decides what a publish does
    ([[#publishing-review]]). A publish moves the
    plugin to the Organization library (`db/plugin.py:publish_plugin__no_commit`);
    a name clash there returns `CONFLICT`. Only global `MANAGE_PLUGINS` deletes
    a published or a required skill
    (`db/skill.py:delete_skill_for_user__no_commit`); the card, bulk menu and
    editor hide Delete to match. A transfer moves a private plugin to the new
    owner's "My uploads", and a name clash there returns `CONFLICT`.
    Agents apply a looser form of the rule
    ([[agents-personas#group-share-needs-manage-agents]]).
    `POST /skills/bulk` sharing applies one change to every skill the user
    can edit, reports refusals and failures per skill, and pushes the combined
    affected audience once after commit. A refusal for the whole set, such as
    a scope or install setting refusal, fails every skill. Bulk delete applies
    each item in a savepoint. Bulk enable and disable change only the caller's preference.
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
15. `skill-dir-placeholder` **Skill paths resolve to the sandbox folder.**
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
17. `bundle-size-limits` **Upload limits do not apply to saved bundles.**
    `skills/bundle.py` limits are constants, not env vars: 25 MiB per file and
    100 MiB expanded for every bundle, plus a 25 MiB ZIP and 500 files for new
    uploads. Stored reads
    (`skills/validation.py:read_stored_bundle_bytes`) stop at
    `STORED_ZIP_MAX_BYTES` (the expanded-total limit), and an edit that would
    save a larger ZIP is refused, so every saved bundle loads again. They skip
    the ZIP-size
    and file-count limits. `skills/validation.py:validate_stored_custom_skill`
    returns `is_valid=None` for `PAYLOAD_TOO_LARGE`, so the push skips the Skill
    without saving it invalid. Edits that cannot add files (a SKILL.md rewrite, a
    file removal) and the editor's re-ingest use
    `skills/bundle.py:normalize_stored_bundle`, so a saved bundle over the ZIP-size
    or file-count limit stays editable. Merges that add files keep the upload
    limits, so repeated merges cannot pass them. A full-replacement upload in the
    editor does not read the current bundle. One limit applies to every new
    version, edits included: `skills/bundle.py:check_skill_md_size` refuses a
    SKILL.md over `SKILL_MD_MAX_BYTES` (256 KiB) or with a NUL character
    (400), because each version stores the text in a Postgres text column.
    `skills/ingest.py:ingest_skill_bundle` and the GitHub preview call
    it. Only direct uploads return 413. Batch uploads report
    `not_imported` and GitHub previews mark the Skill unavailable.
18. `bundle-file-list-memory` **ZIP metadata memory has a fixed bound.**
    Every Skill ZIP opens through `skills/bundle.py:open_bundle_zip`, which uses
    `file_processing/zip_limits.py:open_zip_within_directory_limit`. `zipfile`
    keeps one `ZipInfo` (about 550 bytes) for each file-list record, so a small
    ZIP with many empty entries can use hundreds of MiB. The opener limits the
    bytes `zipfile` reads while it opens: 1 MiB of file list for uploads
    (`ZIP_DIRECTORY_MAX_BYTES`) and 4 MiB for saved bundles
    (`STORED_ZIP_DIRECTORY_MAX_BYTES`). Over the limit is a 413
    `zip_metadata_bytes`. `normalize_custom_bundle` finds duplicate and
    file-versus-folder paths by sorting the paths, not by building every parent
    path. `skills/push.py:_add_bundle_bytes` skips a Skill whose declared file
    sizes would take the push over the transport cap
    (`skills/limits.py:SKILL_RUNTIME_MAX_BYTES`, 900 MiB), before it reads the
    files. The running total counts each root SKILL.md at its resolved size
    (`_sent_bytes`), so a Skill that `skill-dir-placeholder` would drop never
    counts against later Skills.
19. `plugin-tables` **Access reads come from the plugin tables;
    the skill rows are still written.** Migration `cdec9dd9ca3d` adds `plugin_marketplace`,
    `plugin`, `plugin_version`, `plugin_skill`, `plugin__user`,
    `plugin__user_group` and `user_plugin_preference` (`db/models.py:Plugin`
    and its neighbours), and fills them from each custom skill. Built-in
    skills get no plugin. A plugin and the legacy skill row share one id.
    Public and author-less skills go to the Organization library, published.
    Other skills go to the author's "My uploads". A duplicate name in one
    marketplace gets the first free `-N` suffix on `plugin.name` only
    (`db/plugin.py:free_plugin_name` in app code). The skill name lives only
    in `plugin_skill.frontmatter` (NOT NULL, a check requires a string
    `name`); the backfill seeds it with the name and description of the
    legacy row. No column stores the kind (skill or plugin):
    `db/plugin.py:plugin_version_kind` reads it from the layout of each
    version. Creates, bundle changes, deletes, shares, publishing, install
    settings, choices and transfers write the plugin rows and the skill rows
    ([[#bundle-change-adds-version]]). Visibility, edit, enablement, the
    runtime list, affected users, the scoped-manager checks, the skill
    responses (`db/plugin_access.py:load_plugin_access`), the community
    downgrade and the user-delete guard read the plugin rows. The list and
    runtime names and descriptions come from the frontmatter of the version
    the user runs. A custom skill with no plugin is hidden from everyone but
    an admin; an admin write makes its plugin from the legacy rows first
    (`db/plugin.py:lock_skill_plugin__no_commit`). A user delete is refused
    while the user's "My uploads" holds a plugin
    (`db/users.py:delete_user_from_db__no_commit`); published plugins stay
    with no author. Migrations `88184258ae59`, `4ea385d01d75` and
    `55bf66dd54dd` re-sync every plugin from the skill rows; each copies
    `backfill_plugins_from_skills` instead of importing it. Reads of bundles,
    validity and content also come from the version: the runtime list, the
    push, session start and the hash take the version each user runs
    (`db/plugin_access.py:version_user_runs`). The editor and the edits read
    the current version. The preview and `is_valid` in responses read the
    version the user runs. External-app association checks the current
    version, and the app admin list shows the version the organization runs.
    Content of a version comes from one function,
    `skills/content.py:read_version_contents`: `plugin_version.file_manifest`
    and `plugin_skill.skill_md` from the database, and the bundle only when
    they are NULL (a version copied from a legacy row).
    The legacy `bundle_file_id`, `bundle_sha256` and `is_valid` columns are
    only written, by the dual writes; `db/plugin.py:legacy_skill_version_content`
    reads them once to make a plugin for a skill that has none.
20. `bundle-change-adds-version` **A file change adds a plugin version and
    keeps the old bundle.** Each create and each change to a custom skill's
    files goes through `db/skill.py:create_custom_skill__no_commit` or
    `db/skill.py:replace_skill_bundle`, which call `db/plugin.py`. In one
    transaction they lock the skill row, then the plugin row, add the next
    `plugin_version` with its file list (`skills/bundle.py:compute_bundle_manifest`)
    and `plugin_skill` row, move `current_version_id`, and copy the bundle,
    name and description to the legacy skill row. A save never moves
    `published_version_id`: on a published skill the organization keeps the
    published version until a publish update ([[#publishing-review]]). An editor save
    whose file list equals the current version's adds no version, and the
    route deletes the new blob. A version copied from a legacy row has no
    file list, so editor routes pass `previous_manifest`, the list of the
    stored bundle; the bytes of a rewritten ZIP differ even when its files
    do not. A bundle upload always adds one. An edit
    request may carry `base_version_id`; if it is not the current version,
    the edit gets 409 `PLUGIN_VERSION_STALE`. Skill responses return the plugin's
    `current_version_id`, read with the name and description; the editor
    returns the id of the version whose content it read, so the editor's base
    always matches its fields. Routes no longer delete the
    previous bundle, because older versions still point at it
    ([[#bundle-retention]]). Each new version stores `plugin_skill.skill_md`
    ([[#bundle-size-limits]]). `skills/metadata.py:frontmatter_for_jsonb`
    drops a frontmatter value that JSONB cannot hold and keeps every other
    key; name and description are always the validated strings.
21. `bundle-retention` **A plugin keeps 100 bundles, and every version row.**
    `db/plugin.py:prune_plugin_bundles__no_commit` runs in
    `add_plugin_version__no_commit`, under the plugin lock and in the same
    transaction. It keeps the bundles of the newest `BUNDLES_KEPT` versions
    and of the published and pending versions. Other versions get
    `bundle_file_id` NULL and keep `bundle_sha256`, the file list and
    `plugin_skill` rows. It returns only files that no version and no legacy
    skill row still uses, and the routes delete them after the commit. A skill
    delete, single or bulk, deletes every bundle of the skill and its versions
    after the commit. A failed file delete only logs, as on main. A read of a
    pruned bundle gets 404 "The files of this version are no longer kept."
    (`skills/content.py:read_skill_bundle_blob`). A version copied from a
    legacy row stores no file list or `skill_md`, so after its bundle is pruned
    its preview also gets that 404.
22. `version-history-api` **Version history uses the EDIT policy.** The
    owner, editors and global `MANAGE_PLUGINS` list every version, newest
    first (`GET /skills/custom/{id}/versions`), preview one
    (`GET .../versions/{version_id}`) and restore one
    (`POST .../versions/{version_id}/restore`); a viewer gets 404, and a
    version of another skill gets 404 (`db/plugin.py:get_plugin_version`).
    Each listed version's `review_status` is `published` when it is
    `plugin.published_version_id`, else its stored value. The preview reads
    the database (`skills/content.py:read_version_preview`), so a version
    with no bundle still previews when its content is stored. Restore needs
    `base_version_id` (409 `PLUGIN_VERSION_STALE`, checked by the save path
    under the plugin lock), copies the old bundle into a new blob and saves it
    through the editor save path, so it adds no version when the files equal
    the current files, and the new version prunes like any save
    ([[#bundle-retention]]). A version with no bundle gets 404
    `skills/content.py:VERSION_FILES_NOT_KEPT`. Skill responses carry
    `current_version_number`. The UI is the **Versions** tab of the skill
    dialog (`web/src/sections/modals/skills/SkillVersionsTab.tsx`, inside
    `ShareSkillModal` for OWNER or EDITOR). Each row shows badges for
    current, published, in review and denied. Restore sends the listed
    current version as `base_version_id` and shows the editor's stale message
    on 409; it is hidden for the current version and a version with no
    bundle. `SkillCard` shows `v{current_version_number}`.
23. `publishing-review` **The Publishing setting governs every publish by
    authors.** Only the author or a user with global `MANAGE_PLUGINS`
    publishes or publishes an update
    (`db/skill.py:ensure_can_edit_org_visibility`); an editor saves versions
    only. `Settings.plugin_publishing` is `OPEN`, `REQUIRES_REVIEW` or `OFF`
    (default `OPEN`). `db/plugin_review.py:publish_action_for` reads it once
    per publish, and a failed settings read stops the publish (it does not
    fall back to `OPEN`); a user with global `MANAGE_PLUGINS` always publishes
    at once. `db/plugin.py:publish_or_request_review__no_commit` is the one
    place it applies. The access-change write path calls it for a private
    plugin (share route, PATCH, bulk share, batch upload, editor create and
    GitHub import), and so do `POST /skills/custom/{id}/publish` and approve.
    A system write (`actor` None: the external app link, the community
    downgrade, approve) always publishes. A new skill created published takes
    the next free name on a clash (`on_name_clash="rename"`), as main allowed;
    other publishes refuse a clash with CONFLICT. `OFF` refuses with 403. `REQUIRES_REVIEW` leaves the
    skill private and makes its current version `pending`. The publish route
    also does a publish update for a published skill: it moves
    `published_version_id` to the current version, or makes it pending.
    `plugin_version.review_status` stores only `draft`, `pending` or `denied`;
    "published" is derived from `plugin.published_version_id`, so no stored
    state has to follow the pointer. `publish_plugin__no_commit` is the one
    writer of `published_version_id` after create, and every publish sets the
    plugin's pending version back to `draft`, so a pending version is always
    newer than the published one. A newer request also sets the old pending
    version to `draft`; the partial unique index `uq_plugin_version_one_pending`
    allows one per plugin. Global `MANAGE_PLUGINS` lists requests
    (`GET /skills/review-requests`; the requester shown is the skill author,
    the only user who can request), approves
    (`db/skill.py:approve_skill_review__no_commit`, which calls
    `publish_plugin__no_commit` with the version, "raise" on a name clash) and
    denies them. The Versions tab shows an **Unpublished changes** badge when
    `current_version_number` is newer than `published_version_number`, and
    **Publish update** (or **Waiting for review** while the current version is
    pending) for the author and organization-wide managers
    (`canChangeOrganizationAccess`, which takes the global `MANAGE_PLUGINS`
    holder, not full admin). One web hook mirrors `publish_action_for` for the
    share dialog and the Versions tab. Admin UI: the **Skill Publishing**
    select on Admin Panel → Craft → Preferences
    (`web/src/views/admin/CraftPreferencesPage/SkillPublishingCard.tsx`, saved
    with `updateAdminSettings({ plugin_publishing })` so the PATCH changes only
    that field; the same card holds **Default Access**, saved with
    `PUT /skills/organization-library/default-access`, and **Sharing**, saved
    as `plugin_sharing`), and **Publish Requests** with Approve and Deny on
    Admin Panel → Skills (`web/src/sections/skills/SkillReviewRequests.tsx`; a
    global manager without full admin sees it on the Craft Skills page); an
    approve error such as a name clash shows the server detail.
25. `write-skill-limit` **No write moves an active user past 500 MB or 5,000
    files of skills.** Limits are `skills/limits.py` constants. A user's total
    is `plugin_version.unpacked_size_bytes` and `file_count` of the version
    the user runs, for each plugin enabled for the user (before the name
    order) with a version that is not invalid and a connected app
    (`db/plugin_access.py:plugin_usage_by_user`, one query for many users),
    plus every offered built-in (`skills/built_in.py:BUILT_IN_SKILL_USAGE`,
    measured at import). A backfilled version with no sizes counts as 0.
    `db/skill_limit.py:skill_limit_check`
    wraps every write that can grow a total: A1 (shares, bulk, group
    settings, group page, first publish), Default Access, create (upload,
    editor, import), auto-enable, toggle, save/restore/replace, publish
    update, approve and transfer. `track` measures the changed plugins
    before the write; `finish` takes the tenant-wide advisory lock
    (`lock_skill_limit`, wait logged), measures them again and reads full
    totals only for users whose share grew. Refuse only under -> over (413
    `SKILL_LIMIT_EXCEEDED`, body `skill_limit`: `users_over`, `usage` for the
    acting user, `max_bytes`, `max_files`; a per-item failure in bulk,
    batch upload or GitHub import carries the same `skill_limit` through
    `db/skill_limit.py:skill_limit_refusal`); already over is a logged warning;
    inactive users and bot/external accounts do not count. The lock is taken
    after the write's row locks and nothing waits for a row lock while it is
    held. A nested check joins the session's outer one. App connect
    (`db/skill.py:connect_external_app_within_skill_limit__no_commit`)
    connects and saves an off choice for app skills that do not fit; the
    response lists them in `skills_left_off_for_limit` (`SkillLimitNotice`:
    each `SkillOmission` with its write-limit size and reason, and the limits). Group membership
    changes are never checked: the run-time rule applies.
26. `runtime-skill-limit` **A sandbox gets every plugin that fits in 900 MB
    and 10,000 files.** `skills/push.py:build_user_skills_payload` applies it,
    so session start (`build_managed_content_payload`) and the push both do.
    Each file counts as at least 4 KB: the charge comes from
    `plugin_version.file_manifest` sizes of the version the user runs
    (`db/plugin_access.py:runtime_plugin_charges`, one query per user set and
    one per version set); a version with no sizes is measured from its bundle
    while the push loads it. Keep order (`skills/limits.py:KeepGroup`):
    built-in, Required, turned on (also Installed by default turned on again),
    Installed by default. Inside a group the newest first: `enabled_at` for
    turned on (empty is oldest), else the latest `plugin__user` or
    `plugin__user_group` row of the user, else `plugin.created_at`; then
    `plugin.id`. Whole plugins only, after the name order. Left-out plugins
    (`SkillOmission`: id, name, charged bytes, files, reason) go to
    `sandbox.skill_omissions` together with `skills_hash`, so they describe
    the content on that disk. `SessionResponse.skill_omissions`
    (`SkillLimitNotice` with the run-time limits, or null) carries them to the
    session UI on every session read. `GET /skills/users-over-limit` (`MANAGE_PLUGINS`,
    `db/skill_limit.py:users_past_write_limit`) lists active users past the
    write limit with their size, files and the count of plugins that do not
    load (sizes only, no bundle opened). The transport cap (900 MiB of sent
    bytes, `SKILL_RUNTIME_MAX_BYTES`, see [[craft-sandboxes]]) applies on top,
    in the same keep order: a plugin whose files do not fit after
    `${CLAUDE_SKILL_DIR}` resolution is left out and recorded as an omission
    with reason `bytes`; the push still goes out.

---

## Decisions

- **Rendered files, not a manifest, go into the hash.** Any change in rendered
  output, such as a new app connection or a denied action, marks sessions
  stale with no list of inputs to maintain.
- **A stale notice, not an automatic reload.** Reload disposes the live
  runtime, so the user chooses when. It refuses while a turn runs.
- **A push can change files during a turn (R30).** "A new version applies at
  the next message" holds only for the harness. The OpenCode push swaps the
  `/workspace/managed/skills` link at once, so a turn that is running can read
  the new files of a Skill. The previous tree stays readable until the next
  push to that mount or for 60 seconds.
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

---

## Dependencies

- [[craft-sandboxes]]: `push_to_sandbox` and the managed volume.
- [[craft-sessions]]: the stale check and the reload that apply a push to a
  live runtime.
- [[craft-external-apps]]: app readiness and action policy views. GitHub
  import and preview authenticate with the user's GitHub app credential
  (`server/features/skill/api.py:_github_authorization_header`).
- [[authorization]]: `MANAGE_PLUGINS` and the scoped-manager group check
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
  `load_user_plugin_states` (setting and choice), the name order
  (`order_skill_names`: another skill may hold the name), app readiness, `plugin_version.is_valid` of the
  version the user runs (`version_user_runs`), and built-in availability. Then compare `Sandbox.skills_hash` with
  `BuildSession.skills_hash`: equal means the runtime loaded the last push;
  different means the session waits for a reload. Search the API server log
  for `Skill push failed` for a failed push.
- `test-skill-setup` **Set up skills for a test.** Use the integration manager
  `backend/tests/integration/common_utils/managers/skill.py`. A real push
  needs the Kubernetes harness in `backend/tests/integration/tests/craft/k8s/`.

---

## Verification

- `backend/tests/unit/onyx/skills/` covers bundles, validation, rendering and
  GitHub import.
- `backend/tests/external_dependency_unit/craft/` (the `test_skill*` files)
  covers visibility, the fileset, affected users, ownership and push faults.
  `backend/tests/external_dependency_unit/craft/test_skill_version_reads.py` covers the version each user runs (an
  organization-only user runs the published version, a share recipient the
  current one, also in the push), and that the editor, the preview and the
  list make no file store read for content stored in the database.
- `backend/tests/external_dependency_unit/db/test_plugin_tables_migration.py`
  covers the plugin backfill,
  `backend/tests/external_dependency_unit/db/test_plugin_resync_migration.py`
  the re-sync, and
  `backend/tests/external_dependency_unit/db/test_plugin_constraints.py` the
  database rules of the plugin tables.
- `backend/tests/integration/tests/skills/` covers the API, bulk actions,
  import sharing and plugin version writes
  (`backend/tests/integration/tests/skills/test_skill_plugin_versions.py`),
  bundle retention and deletes
  (`backend/tests/integration/tests/skills/test_skill_bundle_retention.py`),
  the version list, preview and restore
  (`backend/tests/integration/tests/skills/test_skill_version_api.py`), and
  publish, review and the Publishing setting
  (`backend/tests/integration/tests/skills/test_skill_publish_review.py`).
  `backend/tests/external_dependency_unit/craft/test_skill_pruned_version_read.py`
  covers the read of a pruned bundle.
  `backend/tests/external_dependency_unit/craft/test_plugin_access_change.py`
  and `backend/tests/external_dependency_unit/craft/test_plugin_setting_writes.py`
  cover the setting and name rules of
  writes; `backend/tests/integration/tests/skills/test_skill_setting_writes.py`
  covers Default Access, Not available, Sharing and the response fields;
  `backend/tests/integration/tests/skills/test_skill_group_summaries.py`
  covers group summaries, `group_settings`, the explicit company Available and
  app skills under Default Access Not available.
  `backend/tests/integration/tests/skills/test_skill_write_limit.py` covers
  the write limit through the API, and
  `backend/tests/external_dependency_unit/craft/test_skill_write_limit.py`
  the warning, app connect, backfilled sizes and the lock wait.
  `backend/tests/external_dependency_unit/craft/test_session_lifecycle.py`
  (`TestSessionSkillOmissions`) covers `skill_omissions` on the session read.
  Jest: `web/src/app/craft/components/SkillRuntimeNotice.test.tsx`,
  `web/src/lib/skills/limits.test.tsx`,
  `web/src/sections/skills/SkillLimitUsersBanner.test.tsx`,
  `web/src/sections/skills/SkillOmissionList.test.tsx` and the refused toggle
  and bulk cases in `web/src/views/SkillsPage.test.tsx`.
  `backend/tests/integration/tests/craft/k8s/` covers a real
  push.
- By hand: edit a skill while a Craft session runs. The stale notice must
  appear, and after reload the agent must read the new text.
