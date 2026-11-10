# Skills

> Agent Skills for Craft: instruction bundles that Onyx renders for each user and pushes into that user's Craft sandbox, where the coding agent reads them. This component owns skill sharing, installation policy, per-user rendering and the hashed push; skills do not reach the chat product.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE. Group shares need the EE group tables.

---

## User experience

- **A Craft user** opens the skills library and sees built-in skills and the
  custom skills they can see: their own, shared with them, or published to the
  organization. The Admin Panel lists custom skills in a table with access and installation
  columns; the personal library keeps cards. They preview a
  skill's instructions, and turn custom skills on or off.
- **Built-in skills** are always on. A built-in that depends on an unavailable
  service, such as image generation with no provider or the browser with
  `ENABLE_BROWSER` off, is hidden. A skill for an external app is ready only
  after the user connects that app. Until then the user cannot turn it on, and
  the library says why.
- **Authoring.** A user writes a skill in the browser editor, uploads a `.zip`
  or a single SKILL.md, or syncs a marketplace from GitHub after a catalog preview.
  Sync uses the user's GitHub connection in Craft. Owners and editors of uploaded
  skills can share with users or groups as viewer or editor, subject to group scope.
  Owners can transfer ownership; global `MANAGE_SKILLS` holders can transfer skills
  with vacant ownership. Synced skills keep their source ownership.
  Publishing requires global `MANAGE_SKILLS`.
- **Global skill managers** set the installation policy of a custom skill: available (the user
  opts in), installed by default (on until the user opts out), required (on,
  and the user cannot turn it off), or Not available (hidden except from owners and direct recipients, and never loaded). Global manage-skills permission is required to delete a required skill.
- **Bulk management.** Craft's Skills library and **Admin Panel → Skills**
  support selection of custom skills, bulk access and installation changes,
  personal enable/disable, and confirmed deletion. Admins see all manageable
  custom skills. Bulk sharing adds or updates supplied individual grants;
  omitted visibility and installation settings remain unchanged. Failed items
  stay selected. Search changes clear selection. The admin table header selects all filtered
  custom skills. It uses Opal multi-selection, disabled during bulk requests. Row activation
  opens the preview; checkbox activation changes selection without opening it.
  Admin search spans the table width. A compact row below it anchors the count at the start and bulk actions at the end. Actions wrap below the count when space is limited.
  Admin search and bulk controls stay pinned while the title header scrolls away.
  Table focus targets reserve the controls' measured height with scroll margins; the scroll container has no extra padding.
  The count appears only for a nonempty list after a successful load and changes from the filtered total to the selection count.
  Hidden actions and a reserved loading-icon slot keep search, count and table positions fixed during selection and bulk requests.
  The loading icon sits beside the count for every bulk action. The personal toolbar stays separate.
  Bulk failures appear as separate list items in an alert below the pinned controls. Keyboard focus moves to the alert, which scrolls into view only when needed. Failed rows stay selected for retry.
  Only a fully successful bulk response shows a success toast.
  Pending retries retain the alert to prevent scroll jumps. Tall alerts reveal
  their heading first; both page variants reserve their sticky header height.
  Cards and admin rows show Personal, Shared, or Organization access from
  `public_permission` and the server's `is_personal`; share-detail arrays can
  be hidden, so empty arrays do not mean a skill is personal. The table shows
  groups only when supplied. Owner identity is not an access grant. The list
  currently omits share details. The Enable for me column controls personal use.
  Narrow tables use two lines for names without descriptions. Duplicate names use one line and keep their descriptions; warnings remain visible.
  Mobile Create stays beside the title, and the personal-use column is labeled For me.
  Sharing settings stay in the dialog. Access badges have an outline, and keyboard focus uses a rounded neutral outline.
  App dependency status has its own line, so it does not replace desktop descriptions.
  The table keeps page ordering and all filtered rows without pagination.
  Content-sized rows keep names and marketplace folders visible above and below descriptions.
  Row actions wrap within their column when enlarged text leaves too little space.
  `web/src/lib/skills/hooks.ts` is shared by cards and rows for permission, dependency,
  validity and toggle presentation.
- **Skill dialog.** Owners and editors open custom cards or rows in a single
  Details/Sharing dialog. Share actions open its Sharing tab directly. Draft
  sharing edits survive tab switches. Other recipients and built-in skills
  keep a preview-only dialog. The sharing endpoint requires EDIT; do not
  require that endpoint for a VIEW-only preview.
- **Version history UI.** Custom Skills with OWNER or EDITOR permission expose
  Versions in the sharing dialog or read-only preview, including app details. Viewers and built-ins make no history requests.
  `web/src/sections/skills/SkillVersions.tsx` shares retained preview and confirmed restore.
  Desktop history uses a table; narrow screens keep every field in compact entries.
  Narrow dialog headings scroll with the body, and Versions hides the current description.
  Pending restore blocks close and tab changes. Sharing drafts stay mounted and survive restore.
  Successful restore refreshes history, current details, preview and the library.
  The restore response updates cached library content before revalidation, so a failed refresh does not retain the old version.
  The editor replaces its local fields from the restore response. Unsaved editor changes disable restore but keep preview available.
  Synced Skills show their source revision and have no local restore action.
  Marketplace detail exposes retired history to its personal owner or a token-capped global Skill manager.
  Former editors and viewers cannot read retired history. Restore remains refused, and retired rows stay out of libraries.
- **Access at import.** GitHub import and multiple-ZIP upload accept one set
  of sharing settings for the selection. The single-skill editor accepts
  sharing before creation. These use the same sharing checks as later edits.
- **In a running Craft session**, a skill change does not reach the agent at
  once. The session shows a stale-skills notice with a reload action. The
  reload restarts the agent's runtime with the current skills.
- **Version history API.** Owners, editors and admins can list custom skill
  versions with their creator and timestamp, preview retained content, and
  restore uploaded content. Synced content changes in GitHub and cannot be restored locally.
  Viewers can preview current instructions but cannot read history.
  History returns at most 50 rows. The positive `before_version` cursor excludes
  that version and loads older rows without shifting when a new version is saved.
  Restore creates a new version unless its content equals the current version.
  The shared `SkillVersions` panel chains cursor pages and refetches loaded pages after restore.
  It keeps earlier rows on load errors, announces the error, and moves focus only after an explicit older-page request.
  Restore loads another page when a new version would hide the oldest displayed row.
  The previous boundary stays pending through refresh failures and retries until that row is loaded again.
  Skill list/detail responses expose `current_version_number` (null without a version).
  Version labels stay hidden if an older API omits the field during an upgrade.
  History rows expose their `marketplace_revision`; this is source provenance, not an operation audit log.
- **Synced source metadata.** Skill responses include the marketplace name,
  scope, repository-relative folder and access-inheritance flag. Ordinary Skill
  viewers can read these labels without gaining marketplace management access.
  `db/skill.py:skill_marketplace_sources` selects only display fields in one
  query per list. `server/features/skill/response_helpers.py` omits list rows
  whose source was deleted during the request; a detail request returns not found.
  `sections/skills/SkillMarketplaceLabel.tsx` shows the source and folder in
  cards, the admin table and the content page. `views/SkillEditorPage.tsx`
  keeps synced content copyable but removes content-write controls. Sharing
  remains separate. `lib/skills/permissions.ts:canDeleteSkill` gates row,
  editor and bulk deletion; active synced skills cannot be deleted.
  `sections/modals/skills/ShareSkillModal.tsx` shows company default inheritance
  and confirms reset for global managers of overridden company skills. Reset replaces
  the draft with saved defaults; failures keep the draft. Personal synced owners
  control audience, while other managers can change installation policy only.
  Synced ownership transfer is hidden. Non-owner personal editors have no sharing action.
  `marketplace.can_share` supplies synced sharing eligibility to every row,
  editor, preview and bulk action. The server reuses `within_scope` with preloaded
  managed groups for company Skills; all current groups must be managed and
  the Skill must be private unless the actor is global. Explicit Editor grants
  alone do not allow company sharing. The flag respects token caps and retirement;
  writes still recheck authority. Other editors use a read-only Details/Versions dialog.
  Individual grants on ownerless Skills require global management authority;
  scoped managers keep group controls in single and bulk sharing dialogs.

When it fails:
- A bundle with bad frontmatter, an unsafe path, a reserved name, or a
  `.template` file is rejected with a message. A bundle over a size or file
  count limit is rejected with a 413 that names the limit.
- Turning on a skill whose name another enabled skill uses returns a name
  conflict. The client can retry with `replace_conflict` to switch skills.
- A required skill rejects a toggle.
- If a push to a sandbox fails, the change still saves. The sandbox keeps its
  old skills until the next push, session start or reload. After a group
  membership change, the sandbox has no confirmed skills until a push
  succeeds. The next turn, restore or session create retries the push and
  fails with a 502 while the push fails.
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
false) and built-in availability.
These inputs stay independent. A required skill still needs a ready app and a
valid bundle.

**Enablement.** `_is_enabled_for_user` is the one SQL rule for API responses
and the runtime gate. Built-ins and visible Required Skills are eligible.
Otherwise, an explicit preference wins over the installation default.
Name resolution then selects company, own, and shared libraries in that order,
regardless of installation setting. A Required shared Skill can lose to an
enabled own Skill. A company Default can hide an explicitly enabled own Skill;
the saved preference remains, and applies again when the company candidate is off.

**Two hashes.** `compute_skill_runtime_hash` is a SHA-256 over every rendered
file path and its bytes, plus the connectable-apps text. `Sandbox.skills_hash`
records what was last pushed to the sandbox. `BuildSession.skills_hash`
records what the live runtime of a session loaded. A session is stale when the
two differ or when `Sandbox.skills_hash` is null
(`server/features/build/db/build_session.py:session_runtime_stale`). A null
sandbox hash means no push is confirmed, so the pod can still hold revoked
skills. `server/features/build/session/sandbox_lifecycle.py:deliver_pending_skills`
retries the push before a reload, a workspace restore or a session create,
and refuses to continue while it fails. `SessionManager.yield_sandbox_events`
checks the committed hash again before it sends a prompt, for every session
origin. The stale check also covers every origin, because a scheduled session
can take a later interactive turn. A push
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
This keeps digest, size, and count after retention deletes the files.
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
   the same, or a user who loses access keeps the files. Group membership
   routes (user groups and SCIM) capture the delta under the membership lock,
   clear `skills_hash` on the changed members' sandboxes in the same
   transaction
   (`server/features/build/db/sandbox.py:mark_user_sandbox_skills_pending__no_commit`),
   then commit even no-op mutations and push to the changed members. Marking
   uses `NOWAIT` across all target rows. Contention rolls back the entire request
   and releases its membership lock. Admin requests return 409; SCIM requests
   return a SCIM 503 error with `Retry-After: 1`. No timeout settings change.
   The push from an earlier membership request can cause this contention too;
   retries have no fairness guarantee while deliveries keep holding target rows.
   A failed push leaves the hash null, so later admission requires a retry.
   Never write the new hash before a push succeeds.
3. `shared-read-predicates` **Every new read path must use the shared
   predicates.** Reads use `db/skill.py:skill_visible_to_user`. Edits use
   `db/skill.py:_is_editable_by_user`, through
   `db/skill.py:_skill_select_for_management_policy`. A
   query on `Skill` without them skips sharing.
4. `enablement-not-preference-row` **Never infer enablement from a preference
   row.** Use `db/skill.py:_is_enabled_for_user`. Disable writes `enabled=False`; it does
   not delete the row. A required policy overrides an opt-out without deleting
   it, so the opt-out returns when the policy goes back to default.
   `db/skill.py:_skill_installation_policy_rows` resolves applicable group shares: null
   inherits the company setting; Required wins over Default, Available, and
   Not available, in that order. With no applicable shares, use the company setting.
   `resolve_skill_installation_policies` resolves many user/skill pairs in one query.
   Library, runtime and state queries join the grouped policy result once. Pass
   that column into shared predicates; repeated scalar policy queries cause
   expensive subplans and JIT compilation on large libraries.
   Not available prevents runtime use and toggling without changing preferences.
   Owners and direct recipients retain visibility; public and group access alone do not.
   Management visibility still lets managers inspect these skills.
   An explicit enable clears saved choices for other skills with the same name,
   including hidden skills, after checking visible conflicts under the user lock.
5. `name-uniqueness-in-db` **Resolve names after runtime eligibility.**
   `db/skill.py:resolve_skill_runtime_names` ranks usable, enabled skills by
   company library, the user's library, then another user's library. Older rows
   win within a library; UUID breaks equal timestamps. `skill_library_owner`
   also defines marketplace reconciliation's library identity. A personal
   marketplace remains personal when one of its skills becomes public.
   The library and detail response report `hidden_by_skill_id` and
   `hidden_reason="same_name"` for losing candidates. Reads must resolve against
   all eligible skills, even when the caller requests one row.
   Invalid, unavailable, retired, disabled and disconnected-app skills cannot
   hide a usable competitor. `list_runtime_skills_for_user` returns database-known
   winners by default. Delivery requests all eligible candidates in the same order
   with `include_fallbacks=True`, using one resolver query. Library reads perform
   no storage I/O, so temporary read failures do not change duplicate metadata.
   The partial
   unique index `uq_user_skill_preference_name` allows one enabled choice per
   user and name. No automatic-name index exists. Retirement disables
   explicit preferences in the same transaction.
   New manual and synced skills reject live names in their library. Both use
   `db/skill_library.py:lock_skill_library_names`, ordered after membership and
   marketplace locks and before skill rows. Batch import locks names in sorted order.
   Creation checks its intended final visibility, so company creation does not
   conflict with the creator's personal library during its private insertion.
   Existing duplicates remain valid. Sharing and ownership changes can also create
   same-library duplicates; creation checks do not cover those changes. Runtime
   name resolution still delivers one winner. Low-level test fixtures can seed duplicates.
   Built-in app skills bypass this custom-library check. Older custom names must
   not block provider setup; new custom uploads still reject reserved built-in names.
   `db/skill.py:enable_new_skill_if_name_available__no_commit` resolves the effective
   setting before writing a preference; Required keeps opt-outs, and Not available writes nothing.
   Responses keep the company setting in `installation_policy` and return the
   user's setting in `effective_installation_policy`, from the batched state query.
   Every write that enables a preference first
   takes `db/skill.py:_lock_user_skill_preferences`, a `FOR NO KEY UPDATE`
   lock on the user row. The lock orders concurrent enables of one name, so
   the second one gets `SKILL_NAME_CONFLICT`, not an `IntegrityError`. The
   lock does not block the `FOR KEY SHARE` locks that foreign-key checks take,
   so sharing writes that reference the user still run. A new preference
   writer, such as an auto-enable, must take the same lock.
   `skills/push.py:_assemble_fileset` stages each candidate separately and claims
   its name only after complete assembly, including rendering, size admission and path replacement.
   Failed candidates leave no files; delivery tries the next eligible candidate.
   After success, it never reads losing bundles for that name. Temporary storage
   failures do not persist invalidity. Do not bypass the shared resolver.
6. `name-immutable` **A skill name never changes.** The frontmatter `name`,
   `Skill.name` and the bundle's wrapper directory, when there is one, must
   match (`skills/metadata.py:parse_skill_document`). The shared
   `db/skill_version.py:save_skill_version` also rejects a different canonical name. Storage removes the
   wrapper. A rename is a delete and a new skill. Custom names cannot match a
   built-in.
7. `validate-before-sandbox` **Validate before content reaches a sandbox.**
   `_assemble_fileset` unzips a custom bundle only when `is_valid` is true, or
   after `skills/validation.py:validate_stored_custom_skill` passes for an
   unclassified row. `db/skill.py:persist_skill_validity` writes only to rows that are still unclassified
   and still point at the observed version and bundle. The skill lock serializes
   this update with replacement; the legacy validity column is dual-written.
   Runtime and history use the same missing-object classification. Ambiguous cloud
   404s need a physical metadata check before runtime persists invalidity. Unknown
   metadata or storage outages leave validity unclassified so later reads can retry.
   Writes check five limits in `skills/bundle.py:normalize_custom_bundle`.
   Count all non-directory archive entries, including ignored files. Check
   both the incoming and normalized ZIP sizes. ZIP refusal messages preserve the
   exact configured byte limit instead of rounding it down to whole MiB. Raw uploads use the per-file
   read cap; ZIP uploads use the ZIP cap.
   Stored-bundle reads (`skills/validation.py:load_stored_custom_skill_bundle`)
   skip the upload ZIP-size and file-count limits. Their separate
   `SKILL_BUNDLE_STORED_ZIP_MAX_BYTES` allowance must cover previously accepted ZIPs.
   When unset, it inherits `SKILL_BUNDLE_TOTAL_MAX_BYTES`, the previous stored-read
   allowance, including operator values above 100 MiB.
   Upload ZIP limits cannot exceed that allowance; lowering an upload limit must not lower it.
   Current-content reads return 413 with the stored read limit when that allowance is exceeded.
   Stored reads retain the existing per-file and expanded-total limits.
   Version metadata repair also bounds compressed reads at the storage backend
   and expanded work per file and in total, without applying upload file counts.
   Skill deletion collects every retained bundle before cascading version deletion.
   Cleanup runs after commit and checks both legacy and version references.
   New upload inputs have a 1 MiB central-directory cap before parsing. Stored reads
   and edits read the saved input without this cap. Saves check the rewritten
   directory against the 1 MiB cap. `file_processing/zip_index.py:ZipIndex` parses
   one central directory record at a time and keeps entry names and offsets in an
   anonymous SQLite file, preserving digest order.
   `db/zip_metadata.py` owns all entry-index, written-entry, and path-set queries.
   `file_processing/zip_index.py` owns the end record, central record, extra field and local
   header parsing; `file_processing/zip_stream.py` decompresses member data with
   `zlib`, `bz2` and `lzma`. Both use documented interfaces only. Errors and
   values match the installed `zipfile`, with stream behavior as in 3.13.16. A
   pair of side-effect-free `zipfile` probes selects the ZIP64 end record checks
   and comment search window on first use, not during import. Entries that share
   a local header all end
   at the next greater header, so they read without the 3.13.16 warning.
   `file_processing/zip_writer.py:SpooledZipWriter` writes the bytes of
   `zipfile.ZipFile(output, "w", ZIP_DEFLATED)` with `struct` and the documented
   compressors, to a seekable output only. It exposes only member writes and
   close, and keeps entry metadata on disk. A refused close with an open member
   keeps that metadata until the member closes and the caller retries. Editor/history responses
   and sandbox file maps still allocate per file; only directory parsing is bounded.
8. `templates-built-in-only` **Only built-ins use templates.**
   `skills/bundle.py:normalize_custom_bundle` and
   `skills/bundle.py:update_custom_bundle_files` reject `.template` files. If
   you convert a built-in's SKILL.md into a template, add its renderer branch
   in `skills/push.py:_render_template` in the same change. The
   static copy skips template sources, and a templated built-in with no
   renderer logs a warning. Assembly rejects a candidate without root SKILL.md
   and tries the next eligible candidate.
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
    sandbox push while the transaction is open. `sync_managed_content` and the
    provisioning push lock the row before they build the payload and keep it
    until the hash record commits. User-library assembly and delivery run outside
    this transaction ([[craft-sandboxes]]). Without that lock, a membership change that
    commits during the push gets its null hash overwritten with the old
    payload's hash. Lock order is membership lock, then `Sandbox` rows; no
    code holding a `Sandbox` row takes the membership lock. The hash write is a savepoint,
    and the caller commits. The push catches and logs every exception, so a
    failed push never fails the API call. The next push repairs it, because
    the hash of a failed sandbox is not written.
12. `sharing-single-entry` **Access writes use the resource adapter.**
    `db/resource_access.py:mutate_resource_access` handles single and bulk changes.
    `db/skill.py:SkillAccessAdapter` supplies skill grants with real foreign keys,
    locked EDIT authorization and eligibility checks. Company visibility and
    installation settings require global `MANAGE_SKILLS`, even for owners, except
    that personal synced skill owners control their own audience. Their adapter
    state sets `sharing_owner_id`; only that actor may change user/group grants
    or public visibility. Unchanged grants do not block a manager's policy edit.
    All personal synced owners can grant groups without changing installation
    settings, including owners who also manage groups. Their audience authority
    does not depend on managed groups or the skill being private.
    Client company controls use `usePermissionAuthority` with that permission,
    not ownership or scoped admin capabilities. `web/src/lib/skills/sharing.ts:serializeSkillSharing`
    omits company fields without global authority, preserving existing public access.
    The personal synced owner can supply public access separately; this never grants
    installation-policy authority.
    Changed group grants and explicit group settings use `assert_within_scope`
    against stored groups and visibility. Group managers cannot change another
    group's settings or company settings. An omitted group setting preserves
    its value; explicit NULL clears it. Removing a share with a non-null policy
    requires the same management authority as changing that policy. Personal synced
    owners keep audience rights for shares without policies. Not available is accepted through these guards.
    Bulk organization access shows Keep unchanged when the actor or selection cannot change it.
    Bulk sharing adds or updates grants and preserves omitted grants and policies. It reads
    affected users in two batch queries and pushes once after commit. Expected
    failures roll back one skill's savepoint. Bulk toggles affect only the caller.
    Access and preference writes acquire the membership lock before resource/user locks.
    Content and metadata preparation holds no Skill row or membership lock.
    `db/resource_access.py:lock_resource_access_user` reloads active authority after acquiring membership.
    Authentication uses a separate session. Skill writes and their response permissions use the refreshed request-session actor.
    Creation and import recheck authority after staging, even when auto-enable and sharing are omitted.
    The final content write takes membership then Skill.
    Derived edits compare their observed content; a changed snapshot returns a retryable conflict.
    Full replacements append on stale observations without reusing unverified content.
    Metadata repair refreshes each batch row before staging reads without locks.
    The locked pass refreshes historical versions and discards prepared metadata when their bundle link changed.
    It retries snapshots changed during staging; earlier completed edits do not stop the batch.
    Batch imports stage all uploads before access locks and clean rejected blobs after
    commit. Single creation and replacement roll back before failure cleanup.
    Uncertain commits leave staged blobs for the orphan sweep.
    Unexpected storage or credential errors during content preparation abort the save;
    only the shared metadata reader classifies missing or malformed stored content.
    Company marketplace access changes clear `follows_marketplace_access`;
    unchanged shares keep the setting. Marketplace defaults and reset use
    `db/marketplace_access.py` and the same skill writer. Only live company followers
    receive defaults; personal shares and company overrides survive sync. Reset clears
    individual grants and restores following. Membership locks precede resource locks,
    including reset's marketplace-before-skill order and preference user locks.
    Scoped managers may preserve but cannot change direct-user grants on company skills. MIT-only company
    followers are public. Licensed builds copy stored defaults even during license
    failures. A Community access write may preserve existing groups but cannot
    change or clear them. Explicit downgrade persists public defaults and removes marketplace
    group grants so sync cannot recreate them.
    `db/skill_mutation.py:assert_skill_mutable` refuses retired user mutations;
    deletion explicitly allows retirement only for the personal owner or global
    `MANAGE_SKILLS`. Single and bulk routes cap that global authority by token scopes.
    Reset requires manage-skills token scope as well as refreshed global authority.
    Library reads, sharing, creation/import, content/version routes, enable,
    transfer and deletion cap management authority by the request token. Response permissions use the
    same cap as selection. Required-skill deletion also requires that scope. The capped EDIT query still permits ownership and
    explicit editor grants, but neither global nor scoped management fallback.
    The access adapter carries the same cap through the locked write. Internal
    database callers retain their own authority. Creation/import carries the cap
    through staging into the access savepoint; rejected uploads are cleaned after
    rollback. App-linked creation also caps full-admin authority before storage
    and after actor reload.
    Active synced skills reject content changes,
    restore, ownership transfer, and deletion through shared database guards.
    Content routes check before storage and again at publication. Access and personal
    toggles remain editable, subject to policy. User reads, including admin and app
    associations, omit retired rows; internal history and recipient capture retain them.
    App association replacement preserves already-linked retired rows without changing them,
    even when a stale form includes their ids. New retired associations remain refused.
    New access entry points must use the
    adapter function, not `db/skill.py:replace_skill_shares`.
    `POST /skills/custom/batch` and GitHub import create each bundle through
    `db/skill.py:create_skill_from_bundle__no_commit`, one savepoint per skill,
    so a bad bundle or a live name conflict in the destination library lands
    in `not_imported` and the other skills still import.
13. `pptx-scripts-serve-previews` **The `pptx` skill's preview scripts also
    render Craft output previews.**
    `server/features/build/sandbox/base.py:document_preview_command` runs
    `skills/builtin/pptx/scripts/preview.py` and its LibreOffice helper,
    mounted under a versioned path apart from the managed skills. A change to
    those scripts changes PDF and PowerPoint thumbnails in the output panel
    ([[craft-sandboxes]]).
14. `built-in-removal-needs-migration` **Removing a built-in needs a
    migration that deletes its rows.** User listings and runtime resolution exclude
    unknown `built_in_skill_id` values, so stale rows cannot hide custom skills.
    Management reads retain these rows until a migration deletes them.
    `_assemble_fileset` also skips unknown definitions defensively.
15. `version-rollout-reads` **Custom readers use `Skill.current_version`.**
    History rows and their current-version markers come from one SQL statement,
    so an edit after authorization cannot mark an older version as current.
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
    application database or server imports. It uses only the temporary SQLite
    store in `db/zip_metadata.py`; ZIP timestamps and entry order do not affect it. See
    [[#bundle-retention]] for which bundle files stay.
    Legacy columns remain for V2 compatibility and repair. A save repairs a stale
    or missing pointer before writing its new content. A recovery snapshot has
    no creator; a user content change follows it. Runtime classification updates
    the observed current version only while it remains unclassified. It also
    updates legacy validity when the bundle links match, without creating history.
    Identical user saves verify the existing bundle before reusing it. A missing,
    changed or corrupt current file creates a fresh version from the upload.
    Unexpected storage errors abort the save and keep the current version.
    Repair checks physical object metadata for complete history without downloading
    its payload. Incomplete metadata still needs a bounded bundle read.
    Confirmed missing historical objects lose their file links; current links remain
    recoverable. Missing primary buckets, containers, and uncertain errors keep the links.
    A confirmed primary object miss plus an absent legacy bucket confirms absence.
    Historical failures use separate savepoints so current pointer recovery can commit.
    Repair receives `skills/bundle.py:STORED_BUNDLE_LIMITS`: stored bytes use
    `SKILL_BUNDLE_STORED_ZIP_MAX_BYTES`. Expansion counts actual per-file and total bytes.
    No upload ZIP or file-count cap applies to history.
    Current-content reads verify expansion before inspection or editing.
    Current-content stored-byte limits return a specific 413; its expansion failures
    return 400 through the ValueError handler. History preview and restore retain
    their structured 413 responses for stored-byte and expansion limits.
    Metadata hashes original entries without normalization.
    Built-ins have no versions. `background/celery/tasks/skill_versions/tasks.py` repairs each
    tenant in bounded batches through Celery or Lite's API poller. The base
    interval is five minutes; cloud uses the standard beat multiplier (eight
    by default). Repair saves recovered metadata before pruning bundle links
    under the skill lock, then deletes
    unreferenced files after commit, with the same retention rule as saves.
    The deadline is cooperative between skills;
    a single skill's blob reads can exceed it. Each skill commits before its
    UUID cursor advances, including failed attempts. Failed work remains eligible
    for retry after the cursor wraps.
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
    placeholder. Before substitution, assembly checks every predicted file size
    against both the configured file limit and the receiver file limit.
    Assembly checks predicted bytes against the receiver total, including already
    accepted Skills, before substitution. This includes files without placeholders.
    A size refusal skips the whole candidate, logs a warning and tries the next
    eligible candidate without claiming the name. Assembly does not raise for
    size refusals, so session preparation and other users' pushes can continue.
    The sent bytes feed the runtime hash. OpenCode adds the base
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
    Repository, ref and folder are fixed at creation; no API edits them.
    A future source edit must clear the synced revision and invalidate active sync
    ownership and retirement approval before allowing publication from the new source.
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
    restore stages the old bytes before locking. Then
    `db/skill_version.py:assert_skill_version_bundle_unchanged` reloads the historical
    version and rejects a changed bundle reference before publishing the copy.
20. `history-requires-edit` **History uses EDIT access, including its reads.**
    The `/skills/custom/{skill_id}/versions` family calls `fetch_skill` with
    `SkillManagementPolicy.EDIT` before listing or reading any history.
    Retired history additionally requires personal ownership or global Manage Skills within the token cap.
    The history UI hides cached rows and closes previews when list revalidation returns
    an auth, tier or not-found error. A cached denial replaces the list and every
    page until a successful response, including after remounts or transient errors.
    It clears that Skill's preview cache and request deduplication, so access
    recovery must fetch preview content again. Transient errors keep loaded rows.
    Skill API errors retain HTTP status through the shared `FetchError` type.
    `db/skill_version.py:fetch_skill_version` scopes version ids to that skill.
    Preview returns the historical bundle's description, instructions, and file
    list through `SkillBundleInspectResponse`; it validates expansion before inspection.
    Restore reads the selected version before locking, then calls
    `server/features/skill/api.py:_replace_skill_bundle_from_editor`.
    The final locked phase rechecks EDIT access and the selected bundle identity.
    Ingestion uses stored-bundle limits and stages a new blob. It preserves legacy
    file counts while checking bytes, paths, and names. The shared
    replacement refreshes the description and applies digest equality and retention.
    Never reuse the historical blob: this restore can prune its source version.
    Cleanup stays after the content commit and before the sandbox push.
21. `marketplace-processing-limits` **Archive processing has separate read and index limits.**
    `skills/marketplace/archive.py:archive_files` bounds gzip expansion and member
    reads separately from skill limits. Every supported stream read charges the
    shared byte budget. ZIP metadata reads are bounded before directory parsing;
    only stored and deflated members without encryption or patched-data flags are
    supported. ZIP member streams
    reject seeking, which could otherwise bypass the decompression budget. TAR
    streams can seek within the already expanded spool. Path depth, path bytes and
    the aggregate parent index
    are bounded before retained path allocations can grow without limit.
    The index budget also counts each retained TAR PAX dictionary and its text
    objects; global headers must not multiply retained metadata without a limit.
    TAR enumeration propagates parser-detected header errors, including failures
    inside extension chains. Normal zero-header and member-boundary EOF endings
    remain accepted; TAR cannot distinguish those endings from all lost data.
    Enumeration also charges metadata reads before a member returns.
    Each member also has its own metadata budget, so chained headers and sparse
    maps stop before large allocation or deep parser recursion. Sparse members
    fail the read. `read`, `readline` and `readlines` fail above
    `MEMBER_CALL_MAX_BYTES` instead of truncating. `read1` can return less;
    `readinto` fills larger buffers in bounded steps. All reads share the byte budget.
    It inflates gzip once into a temporary spool.
    `skills/marketplace/reader.py:read_marketplace_archive` reads only the
    declared marketplace. Blocked keys retain their current version; a failed
    read cannot retire anything. Shared paths reuse bundle bytes. Unique output
    has a separate ceiling, including nested paths. Mixed plugins are unsupported.
    Completed entries form an immutable snapshot. Present catalog metadata must
    be an object. Empty declarations cannot hide agent or command Markdown files.
    Marketplace discovery enables `archive_files(require_complete=True)`: TAR discovery requires two zero end blocks and zero padding afterward. General archive
    reads retain member-boundary EOF support. ZIP discovery verifies the end-record
    entry count and each local header/name, including unselected members, without
    inflating their data. Truncated sparse extensions become
    parsing errors, so the reader returns a failed result instead of raising IndexError.
    A nested plugin root that loses its definition keeps its blocked key while other files remain.
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
    Healthy unchanged digests need no upload. Explicit `recovery_keys` bypass digest
    reuse; only ready recovery entries require fresh staged bundles. The shared version writer and retention
    functions maintain history and legacy columns; save-time storage repair is skipped.
    Missing keys retire permanently; reappearance creates a new id. Moves retain ids.
    Unsupported plugin keys protect all their existing child skills. Blocked keys
    keep their versions; `Marketplace.blocked_entries` stores reasons for the later UI.
    More than five retirements AND more than half the live marketplace sets
    `last_error` to "needs confirmation" and leaves skills and synced revision intact.
    `Marketplace.retirement_proposal` persists the exact source revision and sorted
    missing live skill ids. `db/marketplace.py:confirm_marketplace_retirement__no_commit`
    refreshes the actor under the membership lock before locking the marketplace.
    A personal owner or global `MANAGE_SKILLS` actor can approve. Confirmation
    requires NEEDS_CONFIRMATION status and compares the caller's revision and ids
    with the locked proposal. Reconciliation bypasses the guard only for that exact approved pair.
    A changed pair replaces the proposal without approval. Successful reconciliation
    clears it in the content transaction; rollback preserves both approval and content.
    Failed reads at the same revision preserve the proposal, but confirmation
    requires a new sync to restore NEEDS_CONFIRMATION status. A fenced sync that
    resolves a different revision clears it before bundle validation or staging,
    including a no-op revert to the last synced revision. A storage failure or
    stopped worker cannot preserve approval for the old revision. Consumed approval
    cannot authorize a later replay.
    Library name locks use the tenant context, not PostgreSQL search_path, so
    unrelated tenant schemas do not contend for the same company name.
    New names conflict only within a library. Synced skills use marketplace ownership;
    public manual skills use the company library, private manual skills use their author.
    Reconciliation locks all incoming and live names in sorted order through
    `db/skill_library.py:lock_skill_library_names`, sharing the manual creation namespace.
    Its namespace uses tenant context, not PostgreSQL search_path, because schema
    translation can leave current_schema() identical across tenants.
    Sync ownership fences control job freshness. Retirement releases enabled preferences and automatic-policy names.
    Access materialization and audience
    capture share the reconciliation transaction without tier lookups or external I/O.
    Management API writes persist requests for the background sync service.
23. `marketplace-sync-staging` **Upload first, commit once, then clean unused files.**
    `skills/sync.py:sync_marketplace` owns the tenant context, sessions and commit.
    Callers must authorize access first. A detached current-version snapshot
    uses object metadata to detect missing bundles without reading their content.
    Source changes trigger bounded content verification; unchanged sources do not
    detect corruption in existing blobs. Unknown size falls back to bounded verification.
    Missing bundles force a fetch, except keys already blocked at that revision.
    A forced fetch that changes nothing returns no work. Storage failures stop sync.
    Ingestion preparation runs before upload; validation failures become blocked
    entries with their original keys. Storage failures abort the entire sync.
    Each attempted upload uses a fresh tracked file id. The sync caller commits all
    skill, version, revision and completion status together. Ownership release and
    pending-request reads share that transaction. Before a commit attempt, failure
    cleanup checks only this run's ids. After a commit attempt fails, defer cleanup
    to the aged orphan sweep: the server may still commit. Success cleanup also
    checks pruned ids. Cleanup preserves version and legacy references.
    After commit, lease renewal stops before cleanup and sandbox I/O.
    One push covers users affected by content, retirement, or access changes.
    A failed push is logged; it cannot change the committed sync result.
    V3 retries failed cleanup and removes aged uploads left by a stopped worker.
    `db/marketplace_sync.py` owns durable requests and per-marketplace leases.
    The shared heartbeat renews each lease for at most five minutes. Publication
    checks ownership and expiry before reconciliation, with membership before
    marketplace locks. `MarketplaceSyncPublication` binds completion to the transaction
    that holds that row lock. Lease expiry during reconciliation does not revoke it;
    the five-minute operation deadline still applies. Commit or rollback invalidates
    the publication object. Unfenced expired workers cannot publish or clear another owner.
    Finalization releases ownership and reads pending work under the same row lock.
    After two passes, recovery dispatches any remaining request. An unchanged repeat
    preserves the last nonempty result; a later failure or confirmation result takes precedence.
    Temporary upstream
    failures and expired workers share a three-attempt budget, with 60/120-second
    backoff. Other exceptions, failed reads and confirmation guards are terminal.
    Explicit requests reset the budget and delay, including during a running attempt.
    Lost login errors survive completion; publication checks the login under the row lock.
    An unchanged success clears the prior error. Errors contain no provider bodies.
    Management writes persist intent in their transaction, then call
    `background/celery/tasks/marketplace_sync/tasks.py:dispatch_marketplace_sync` after commit.
    Other authorized callers can use `enqueue_marketplace_sync` to persist intent first. Recovery
    retries requested work, expired queue reservations and expired owners; it never
    polls idle sources. Cloud recovery skips gated tenants and uses tenant activity
    gating. API requests mark activity before saving sync intent, including when
    dispatch fails or the commit acknowledgement is lost. Request, claim and retry
    paths mark activity outside database locks;
    reaping marks activity even when backoff postpones dispatch. Idle recovery does
    not mark activity. Single-tenant deployments skip activity flag reads and writes,
    so Lite does not need Redis for sync. The cloud scheduler stretches the recovery interval, so
    60/120 seconds are minimum retry delays, not dispatch guarantees. Both recovery
    and sync messages live for 15 minutes; database claims reject duplicates and enforce retry delays.
    Celery uses the heavy worker's sandbox queue. Lite dispatches
    through a bounded background thread path, outside the periodic poller thread.
    Recovery errors do not prevent the Lite file drains from running.
    Exact retirement confirmation is persisted by the database prerequisite.
    The confirmation helper records approval and requested work in one transaction.
    The management endpoint must commit before dispatch.


24. `marketplace-sync-ownership` **Bound each durable request and fence its owner.**
    `db/marketplace_sync.py` stores requested work and per-marketplace leases.
    Claim, renewal, completion and recovery lock the marketplace row. Publication
    fences take membership first, then the marketplace lock. Expired owners cannot
    enter publication. A fenced publication can complete while it retains that lock,
    until the five-minute operation deadline. A released transaction cannot reuse
    its publication object. A lease lasts at most five minutes from its claim.
    Temporary failures and expired owners share three attempts with 60/120-second
    backoff. Explicit requests reset the budget and delay without replacing a live
    owner. Completion preserves a request made during the run and a deleted login's
    error. Queue reservations expire separately from retry delays.
    The background worker uses these transitions for all sync attempts.

25. `marketplace-management-transactions` **Manage sources through the database service.**
    `db/marketplace_management.py` refreshes active Basic authority. Reads do not take
    the membership lock. Mutations take membership before marketplace and sorted skill locks.
    Recheck active authority after marketplace locks, and after child Skill locks before removal;
    user deactivation does not take the membership lock. Owners manage personal sources;
    global `MANAGE_SKILLS` manages company sources. Global managers can also read,
    sync, replace logins and remove personal sources, including deactivated owners' sources.
    Scoped group authority does not permit company source management.
    List/detail return safe typed snapshots with batched live/retired counts.
    Snapshots expose `sync_pending` for queued or claimed work; claiming clears
    `sync_requested`, so clients must not use it to stop polling.
    `server/features/skill/marketplace_api.py` exposes reads, preview and mutations.
    Preview uses the provider adapter and reader, then ingestion validation without
    saving bundles or rows. It checks active authority before and after provider I/O,
    outside database locks, and returns descriptions/statuses rather than bundle bytes.
    Token scopes cap company previews, management reads and mutations through the shared
    `auth/permissions.py:token_allows_permission` check. A Basic-only token sees only
    its owner's personal sources, even when that owner has global manage-skills.
    Creation and login replacement follow caller provider validation and recheck
    stored active login, enabled app and credential presence without network calls.
    The login is always the actor; company sources have no owner. MIT-only creation
    uses public defaults; installed licensed builds start private regardless of tier lookup.
    Company creation can include initial access. The source, access defaults and first
    sync request share one savepoint and commit before dispatch. Invalid defaults
    roll back creation; personal sources reject source-wide defaults.
    Replacement validates the acting login's repository access before the write. It clears
    retirement approval, old status/error and sync ownership before requesting work.
    Source config is fixed at creation; no route changes it. Replacement keeps
    `last_synced_revision`, so the next sync rereads an unapplied revision and proposes
    retirements again. A future config edit must clear that revision in the same write,
    or an unchanged revision would end as a no-op and hide a needed confirmation.
    Default access requires global authority before the existing access adapter;
    resolve tier before locking, then commit and push its returned audience once.
    Removal captures all version/legacy file IDs and sandbox recipients before cascading.
    Commit before dispatch, push or unreferenced-file cleanup. Rollback preserves rows
    and blobs. Replacement and deletion fence workers that already staged content.
    The source list refreshes host resources after completion, revision/count changes,
    or source removal. Hidden host tabs neither read nor poll marketplace status.
    The shared web client in `web/src/lib/marketplaces/` validates management and
    preview responses with Yup before components use them. Its types come from
    those schemas. A queued request stays distinct from an applied revision;
    confirmation sends only the displayed revision and skill IDs, never an
    approval flag. Fetch errors retain server status and detail through the common
    fetcher. Shared preview and GitHub connection components live in
    `web/src/sections/marketplaces/`. Preview distinguishes ready, blocked and
    unsupported entries and offers a sample for a missing catalog. Connection
    guidance uses the existing Apps flow and cache. The sync dialog requires an
    explicit ref and invalidates preview on edits and close. Company creation
    requires global authority. The dialog owns a fresh access draft and saves
    source and defaults in one creation request.
    Revoked company authority keeps the checked scope visible so the user can return to personal creation.
    Acceptance means sync requested. Shared summaries separate pending work
    from the last applied revision. Hosts can override or hide skill counts
    without inferring unsupported plugin data. Detail polls pending work while
    visible. Closing detail restores focus to its opening control.
    Retirement confirmation sends the reviewed revision and IDs only;
    names come from detail. A rejected proposal needs a fresh review. Removal
    and login replacement require confirmation. Host access callbacks open
    `CompanyMarketplaceAccessModal`, which loads a fresh draft per opening,
    preserves edits across refreshes, and blocks dismissal while saving. A failed
    PATCH retains edits and the server error. Only success revalidates list and
    detail caches and calls the host to refresh Skills.
    `CompanyMarketplaceAccessControls` and
    `useCompanyMarketplaceAccess` provide a session-owned company draft.
    Visibility changes preserve the session's last organization permission.
    Creation submits it atomically. Readiness requires global MANAGE_SKILLS and
    known settings; a settings failure never implies Community. Community allows
    organization Viewer access without groups. Group lookup failures preserve
    grants and per-group policies, including unresolved IDs. Closing the dialog
    resets its creation session. The list owns its SWR read and accepts host kind
    filters and count labels. Hiding the list clears its open detail. List changes
    refresh host Skills once, including after removal. Pending work polls every three seconds while
    visible; polling never requests source sync. Both Skills pages mount the list
    before the library controls. Add offers Upload a skill, Create a skill, and
    Sync from GitHub. Pending and failed sources stay visible with zero Skills.
    Opening company defaults closes source detail first. Retired detail rows show
    a Retired badge, read-only Versions and confirmed deletion. The existing Skill endpoint
    rechecks owner/global authority. Pending deletion blocks dismissal; failures
    keep the confirmation. Success refreshes detail, source counts and Skills.
26. `group-skills-api` **Group pages list rows, not every Skill grant.**
    `ee/onyx/db/user_group_skill.py:list_user_group_skills` returns one row per
    company marketplace share and per direct Skill share for one group. Company
    followers appear only under their marketplace; detached company Skills and
    personal marketplace Skills are direct rows. Retired Skills, personal
    marketplace shares, other groups and provider data stay out. Reads use the
    refreshed actor without the membership lock. Writes change only
    `group_installation_policies` through `mutate_resource_access`:
    `GroupSkillAccessAdapter` refuses followers, and marketplace rows use
    `MarketplaceAccessAdapter`, which copies changes to followers. Routes require
    `MANAGE_SKILLS` and the same token scope. Global holders can target any group;
    scoped holders can target only managed groups. The resource must also pass
    A1's existing scope check (private and shared only within the managed groups).
    No separate group-management permission is required. Writes recheck authority
    under the membership lock, resolve tier before locks, commit, then push once.
    `can_edit` is a hint only. The client hook replaces cached rows with a denial
    after an authorization or not-found response. Only an authorized response
    restores rows, including after a transient failure or remount. A delayed PUT
    cannot replace a cached denial or write into a different group after navigation.


---

## Decisions

- **Rendered files, not a manifest, go into the hash.** Any change in rendered
  output, such as a new app connection or a denied action, marks sessions
  stale with no list of inputs to maintain.
- **A stale notice, not an automatic reload.** Reload disposes the live
  runtime, so the user chooses when. It refuses while a turn runs.
- **App lifecycle keeps user intent.** Disconnecting an app deletes enabled
  choices except those hidden by effective Not available; opt-outs remain.
  Deleting an app resets automatic company and group settings to Available,
  preserves Not available settings and hidden choices, and keeps opt-outs.
  Changed synced skills stop inheriting marketplace access. The built-in row is deleted.
  `db/skill.py:clear_enabled_skill_preferences__no_commit` uses the grouped policy
  resolver and user preference locks; `db/external_app.py` owns the lifecycle.
  Deletion locks the app before its skills, matching association edits. Retired
  skills keep their policy and history.

---

## Known issues

- **Other membership writers have marking gaps.** Admin-access toggles in
  `db/users.py:set_user_admin_access` and Community downgrade in
  `ee/onyx/db/community_downgrade.py` can remove group Skill access without
  marking sandbox delivery pending. These paths need separate fixes.

- **Marketplace browser acceptance remains pending.** Preview, management mutations and skill reset
  are available through the API. Plugin membership is not modeled yet; its access
  guard belongs in `SkillAccessAdapter.load`.
  Company inheritance/reset and personal owner audience controls are wired in the
  skill sharing dialog. Source creation/list pages are wired. Retired deletion is wired; live browser acceptance remains pending.

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
- `downgrade-name-resolution` **Check name collisions before restoring the automatic-name index.**
  Revision `54013115725e` permits duplicate names. Its downgrade restores unique `name`
  for `installation_policy <> 'AVAILABLE' AND retired_at IS NULL`.
  Group those rows by name and stop if any group has more than one row.
  Operators must choose policy changes explicitly, then stop writers and repeat the check.
  The admin Skills guide contains the read-only query and procedure.
  Never silently rewrite policies or delete customer Skills during downgrade.

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
