# Skills

> Agent Skills for Craft: instruction bundles that Onyx renders for each user and pushes into that user's Craft sandbox, where the coding agent reads them. This component owns skill sharing, installation policy, per-user rendering and the hashed push; skills do not reach the chat product.

**Verified against:** `73e0ae3c31` (2026-10-28)
**Edition:** CE. Group shares need the EE group tables.

---

## User experience

- **A Craft user** opens the skills library and sees built-in skills and the
  custom skills they can see: their own, shared with them, or published to the
  organization. They preview a skill's instructions, and turn custom skills
  on or off.
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
- **In a running Craft session**, a skill change does not reach the agent at
  once. The session shows a stale-skills notice with a reload action. The
  reload restarts the agent's runtime with the current skills.

When it fails:
- A bundle with bad frontmatter, an unsafe path, a reserved name, or a
  `.template` file is rejected with a message.
- Turning on a skill whose name another enabled skill uses returns a name
  conflict. The client can retry with `replace_conflict` to switch skills.
- A required skill rejects a toggle.
- If a push to a sandbox fails, the change still saves. The sandbox keeps its
  old skills until the next push, session start or reload.
- A reload while a turn runs is refused with a message to wait.

---

## Scope

This component owns the skill row, its shares, installation policy and user
preferences; bundle parsing and validation; built-in skill definitions;
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
       lock_sandbox_skills_hashes        SELECT ... FOR UPDATE on Sandbox rows
       build_user_skills_payload         per sandbox user
         list_runtime_skills_for_user    db/skill.py: the one runtime gate
         _assemble_fileset               built-ins from disk, custom from FileStore
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
   and still point at the same bundle.
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
    `server/features/skill/api.py:_apply_skill_sharing__no_commit`.** The share route and the editor create
    route both call it. A change to `installation_policy` needs
    `FULL_ADMIN_PANEL_ACCESS`, and `db/skill.py:set_skill_installation_policy` refuses a
    built-in. EDIT on a skill is not enough to change its groups:
    `server/features/skill/api.py:_assert_group_share_within_scope` treats any
    change to the group set or levels as a `MANAGE_SKILLS` action within scope
    ([[authorization]]). Without it, an owner could push a skill into any
    group manager's scope. It compares against the stored shares, and the
    privacy check uses the stored visibility and the request, so a
    public-to-private change in the same request cannot get past it. A
    `public_permission` change needs the author or global `MANAGE_SKILLS`
    (`_ensure_can_edit_org_visibility`; the patch route calls it too). A new
    sharing entry point must call this function, not `db/skill.py:replace_skill_shares`.
    Agents apply a looser form of the rule
    ([[agents-personas#group-share-needs-manage-agents]]).
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
  `_is_enabled_for_user`, app readiness, `Skill.is_valid`, and built-in
  availability. Then compare `Sandbox.skills_hash` with
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
- `backend/tests/integration/tests/skills/` covers the API.
  `backend/tests/integration/tests/craft/k8s/` covers a real push.
- By hand: edit a skill while a Craft session runs. The stale notice must
  appear, and after reload the agent must read the new text.
