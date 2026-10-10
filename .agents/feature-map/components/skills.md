# Skills

> Agent Skills for Craft. A skill is an `SKILL.md` bundle, optionally with
> supporting files, that gets rendered per user and pushed onto a session's
> sandbox so the coding agent can read it as instructions. This is a Craft
> feature, not a chat configuration surface: `backend/onyx/chat/` has no
> reference to skills, and there is no admin route for skills in
> `web/src/lib/admin-routes.ts`. Management happens through the same
> user-facing router as browsing, gated by the `MANAGE_SKILLS` permission.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** craft
**Edition:** CE (Craft ships in both editions; no EE-specific code in this path)
**Owns:**
`backend/onyx/skills/` (`models.py`, `metadata.py`, `content.py`, `bundle.py`,
`rendering.py`, `validation.py`, `built_in.py`, `builtin/`, `ingest.py`,
`ingest_from_github.py`, `push.py`), `backend/onyx/db/skill.py`,
`backend/onyx/server/features/skill/` (`api.py`, `models.py`,
`response_helpers.py`), `web/src/views/SkillsPage.tsx`,
`web/src/views/SkillEditorPage.tsx`, `web/src/lib/skills/`,
`web/src/hooks/useUserSkills.ts`, `web/src/sections/skills/`,
`web/src/sections/cards/SkillCard.tsx`,
`web/src/sections/modals/skills/`, `web/src/sections/modals/SkillPreviewModal.tsx`,
`web/src/app/craft/components/SkillsStaleNotice.tsx`,
`web/src/app/craft/v1/skills/`

**Read first:** `[[craft-sandboxes]]` for the sandbox this component pushes
files into, `[[craft-external-apps]]` for the credential and policy layer some
skills depend on, and
`docs/craft/features/external-apps/external-app-skill-action-availability.md`
for the design rationale behind per-action availability rendering (already
shipped; see §4.2).

---

## 1. What the user experiences

A Craft user opens the skills library at `/craft/v1/skills`
(`web/src/app/craft/v1/skills/page.tsx` renders `SkillsPage`). It lists two
groups: built-in skills (pptx, image generation, company search, Craft
documentation, browser, and one per connectable app such as Slack, Linear,
Gmail, Google Calendar, Google Drive, GitHub, HubSpot, Notion) and custom
skills (their own, shared with them, or published organization-wide). Each
card shows an enable/disable toggle, a preview of the rendered instructions,
and, for a custom skill they can edit, an edit action.

Turning a skill on or off changes what the agent can do on its next turn: an
enabled skill's files land in the sandbox and its `SKILL.md` becomes
something the agent can discover and read; disabling removes it. A user can
author a skill directly in the browser (`SkillEditorPage`, name, description,
markdown instructions, optional files) or import one or more skills from a
GitHub repository (`ImportSkillsFromGitHubModal`), which previews every
`SKILL.md` found in the repo and lets the user pick which to bring in.

An external-app-backed skill (Slack, Linear, Gmail, Google Calendar, Google
Drive, GitHub, HubSpot, Notion) only becomes usable once the user has
connected that app; until then it is visible but not enable-able, and the
card explains why (see §4.3). If the admin has restricted specific actions
of a connected app, the pushed skill file itself carries a short list of
what not to attempt (§4.2) - the sandbox proxy is still the real enforcement
point (`[[craft-external-apps]]`), this is just guidance to save a wasted
turn.

If a skill changes while a session is already running (edited, toggled,
shared, an app's policy changed), the running agent keeps whatever it already
loaded until the user reloads. The UI surfaces this as a stale-skills notice
in the session (`SkillsStaleNotice.tsx`) with a manual reload button.

---

## 2. Surfaces

### HTTP endpoints (router prefix `/skills`, mounted at the global API prefix, `backend/onyx/server/features/skill/api.py`)

| Method | Path | Handler | Notes |
|---|---|---|---|
| GET | `/skills` | `list_skills_for_current_user` | Built-ins + customs visible to the caller. |
| GET | `/skills/{skill_id}` | `fetch_skill_for_current_user` | |
| GET | `/skills/{skill_id}/preview` | `preview_skill_for_current_user` | Rendered instructions, read-only. |
| PUT | `/skills/{skill_id}/enabled` | `set_skill_enabled_for_current_user` | Per-user toggle; pushes to the caller's own sandbox. |
| POST | `/skills/custom` | `create_custom_skill` | Upload a `.zip` or standalone `SKILL.md`. |
| POST | `/skills/custom/editor` | `create_custom_skill_from_editor` | Build a skill from name/description/markdown form fields; `external_app_id` (admin-only) associates it with an app. |
| GET | `/skills/custom/{skill_id}/edit` | `fetch_custom_skill_for_edit` | Requires `EDIT` policy. |
| POST | `/skills/custom/bundle/inspect` | `inspect_custom_skill_bundle_upload` | Stateless preview of an upload before committing to it. |
| PUT | `/skills/custom/{skill_id}/bundle` | `replace_current_user_skill_bundle` | Full bundle replacement. |
| POST/DELETE | `/skills/custom/{skill_id}/files` | `upload_current_user_skill_files` / `remove_current_user_skill_file` | Incremental file add/remove, re-renders `SKILL.md` (§4.1). |
| PATCH | `/skills/custom/{skill_id}` | `patch_current_user_skill` | Description/instructions/visibility. |
| PATCH | `/skills/custom/{skill_id}/share` | `share_current_user_skill` | User/group shares, org visibility. |
| POST | `/skills/custom/{skill_id}/transfer-ownership` | `transfer_current_user_skill_ownership` | |
| DELETE | `/skills/custom/{skill_id}` | `delete_current_user_skill` | Hard delete, see §5.6. |
| POST | `/skills/github/preview` | `preview_github_skills` | Discover skills in a repo without importing. |
| POST | `/skills/github/import` | `import_github_skills` | Import selected discovered skills. |

Every mutation that can change what a sandbox should have calls
`push_skill_to_affected_sandboxes` or `push_skills_for_users`
(`backend/onyx/skills/push.py`) after its own commit, then commits again for
the hash record (§4.4). There is no separate admin router: management
authorization is `Permission.MANAGE_SKILLS`, checked inline
(`db/skill.py:_skill_select_for_management_policy`,
`has_global_permission`/`has_permission`), not a distinct `/admin/*` surface.

### Environment / configuration

| Variable | Where | Effect |
|---|---|---|
| `SKILL_BUNDLE_PER_FILE_MAX_BYTES` | `skills/bundle.py` (default 25 MiB) | Per-file cap inside a custom bundle. |
| `SKILL_BUNDLE_TOTAL_MAX_BYTES` | `skills/bundle.py` (default 100 MiB) | Total uncompressed cap for a custom bundle. |
| `GITHUB_SKILL_MAX_COUNT` | `skills/models.py` (500) | Max skills discoverable in one GitHub import. |
| `ENABLE_BROWSER` | `server/features/build/configs.py`, read by `skills/built_in.py` | Gates the `browser` built-in's availability. |

---

## 3. Data model

```
Skill  (one row per built-in or custom skill)
    built_in_skill_id  XOR  bundle_file_id     (ck_skill_definition_source)
    name  (canonical, immutable identity + sandbox directory name)
    is_valid  (custom only: NULL=unclassified, True, False)
    public_permission  (NULL = not org-wide, else VIEWER|EDITOR)
    author_user_id
  |
  +--< Skill__User        (skill_id, user_id, permission)
  +--< Skill__UserGroup    (skill_id, user_group_id, permission)
  +--< ExternalApp__Skill  (external_app_id, skill_id)  -- at most one app per skill
  +--< UserSkillPreference (user_id, skill_id, name)  -- per-user "enabled"

Sandbox
    skills_hash        -- last skill fileset+guidance hash pushed to THIS sandbox
    mcp_config_hash     -- separate craft-MCP fingerprint (not this doc)

BuildSession
    skills_hash         -- hash the live opencode instance was configured with
    mcp_config_hash
```

- `Skill` (`backend/onyx/db/models.py:Skill`): `built_in_skill_id` and
  `bundle_file_id` are mutually exclusive
  (`ck_skill_definition_source`). A built-in's real content lives on disk
  under `BUILTIN_SKILLS_PATH` (`skills/built_in.py:BUILTIN_SKILLS_PATH`), not
  in the row; a custom row's content is a zip in FileStore, referenced by
  `bundle_file_id`, hashed in `bundle_sha256`. `is_valid` is populated lazily
  the first time a custom skill's stored bundle is inspected
  (`validation.py:validate_stored_custom_skill`) and gates whether it's ever
  hydrated into a fileset.
- `Skill__User` / `Skill__UserGroup` (`models.py:Skill__User`, `models.py:Skill__UserGroup`): one
  row per explicit share, `permission` is `VIEWER` or `EDITOR`
  (`SkillSharePermission`). `Skill.public_permission` is the org-wide grade,
  independent of any explicit share.
- `UserSkillPreference` (`models.py:UserSkillPreference`): the only row that represents
  "this user has this skill turned on." Built-ins don't need one -
  `_is_enabled_for_user` (`db/skill.py`) treats every built-in as
  enabled unconditionally; only custom (or org-shared) skills need an
  opt-in row. The unique index is on `(user_id, name)`, not `(user_id,
  skill_id)`: two skills can never both be "enabled" under the same name for
  one user, which is what produces `SKILL_NAME_CONFLICT` on enable.
- `ExternalApp__Skill` (`models.py:ExternalApp__Skill`): non-owning link, unique on
  `skill_id`, so a skill depends on at most one external app.
- `Sandbox.skills_hash` / `Sandbox.mcp_config_hash`
  (`models.py:Sandbox`): the last runtime fingerprint successfully pushed to
  that sandbox. `BuildSession.skills_hash` /
  `.mcp_config_hash` (`models.py:BuildSession`) record what the session's live
  opencode instance was actually configured with, which can lag the
  sandbox's stored hash until the user reloads (§4.4, §5.1).

---

## 4. How it works

### 4.1 Authoring or importing a skill

```
Editor form            SkillsPage -> CreateSkillModal -> create_custom_skill_from_editor
  build_skill_md              skills/bundle.py            frontmatter + body -> SKILL.md text
  build_single_file_bundle    skills/bundle.py             wrap as a one-file zip
  ingested_skill_bundle       skills/ingest.py             normalize, parse, hash, store
  add_new_skill__no_commit    db/skill.py                  insert Skill row
  enable_new_skill_if_name_available__no_commit  db/skill.py  opt in UserSkillPreference
  push_skill_to_affected_sandboxes  skills/push.py          hydrate + push if newly enabled

GitHub import           ImportSkillsFromGitHubModal -> preview_github_skills / import_github_skills
  fetch_github_skill_bundles  skills/ingest_from_github.py  download one archive, find every SKILL.md
  parse_skill_document        skills/metadata.py            validate frontmatter per candidate
  normalize_custom_bundle     skills/bundle.py               per-skill zip, path-safety checked
  ingested_skill_bundle       skills/ingest.py                same store path as manual upload
```

Every entry point into a stored custom bundle funnels through
`normalize_custom_bundle` (`skills/bundle.py`), which: rejects zip-slip and
symlink entries (`_validated_bundle_path`), flattens one optional wrapper
directory (`zip -r skill.zip skill/`-style archives), rejects duplicate or
conflicting paths, strips `.DS_Store`/`Thumbs.db`/`__MACOSX`, and requires
`SKILL.md` at the resulting root. `parse_skill_document`
(`skills/metadata.py`) then requires: YAML frontmatter delimited by `---`
lines with no duplicate keys (`_UniqueKeySafeLoader`), a `name` matching
`^[a-z0-9]+(?:-[a-z0-9]+)*$` and <= 64 chars, a non-empty `description` <=
1024 chars, and (when a `directory_name` is known, e.g. a GitHub skill's
folder or a stored bundle's wrapper) `name` must equal that directory name.
`ingest_skill_bundle` (`skills/ingest.py`) additionally rejects any name that
collides with `BUILT_IN_SKILLS`. Custom skills cannot ship a `.template`
file (`bundle.py`: "custom skills cannot ship templates") - templating is a
built-in-only mechanism (§4.2).

### 4.2 Built-in skills and templating

`skills/built_in.py:_REGISTRY` is the single source of truth: one
`SeededBuiltInProvider` (pptx, image-generation, company-search,
craft-documentation, browser) or `ExternalAppBuiltInProvider` (slack, linear,
google-calendar, google-drive, gmail, github, hubspot, notion) per built-in,
each pinned to a directory under `backend/onyx/skills/builtin/<skill_id>/`.
Import-time validation (`BuiltInSkillRegistry.__init__`) parses every
built-in's `SKILL.md`/`SKILL.md.template` and fails the process if two
providers share a `skill_id` or an `app_type`, or a declared directory is
missing its source file. `SeededBuiltInProvider` rows are created and
enabled by Alembic migrations; `ExternalAppBuiltInProvider` rows come into
existence only when an admin connects that app
(`onyx.db.external_app.create_external_app`). Availability beyond "the row
exists" is codified per skill: `image-generation` needs
`is_image_generation_configured`, `browser` needs `ENABLE_BROWSER`; both are
filtered out of user-facing listings when unavailable
(`db/skill.py:_exclude_unavailable_built_in_skills`), with a
human-readable `unavailable_reason`.

`has_template` (`BuiltInSkillDefinition.has_template`) is derived from
whether `SKILL.md.template` exists on disk, not stored anywhere. A templated
built-in's `SKILL.md` is regenerated per user at push time
(`skills/push.py:_render_template`): `company-search` calls
`render_company_search_skill` (`skills/rendering.py`), substituting
`{{AVAILABLE_SOURCES_SECTION}}` with the user's connected, non-internal-only
document sources; an external-app skill calls `render_external_app_skill`,
which resolves a `cloud-description:` frontmatter override on cloud
deployments, strips or keeps `{{#IF_CLOUD_SCOPE}}...{{/IF_CLOUD_SCOPE}}`
blocks, and fills `{{ACTION_AVAILABILITY_SECTION}}` with a "these actions are
unavailable and should not be attempted" list built from
`build_action_availability_section`: cloud-withheld actions plus the admin's
stored `DENY` overrides (`external_apps/providers/registry.py:action_policy_views`).
Only `DENY` is surfaced; `ALWAYS` and `ASK` actions are left undocumented
here because the skill body already covers them and `ASK` is handled at call
time by the sandbox proxy (`[[craft-external-apps]]`). An unresolved
`{{...}}` placeholder after rendering raises rather than shipping broken
markup to the agent (`rendering.py:render_external_app_skill`, the trailing
`if "{{" in rendered` check). This whole mechanism matches
`docs/craft/features/external-apps/external-app-skill-action-availability.md`
- that plan has already shipped; it is not a stale doc.

### 4.3 Pushing the active set into a sandbox

```
push_skills_for_users(user_ids, db_session)         skills/push.py
  get_sandbox_user_map                    server/features/build/db/sandbox.py
  lock_sandbox_skills_hashes  (SELECT ... FOR UPDATE on Sandbox rows)
  build_user_skills_payload(user, db_session)  per user:
    list_runtime_skills_for_user            db/skill.py
    _assemble_fileset                       skills/push.py  -> FileSet {path: bytes}
    build_connectable_apps_list             sandbox/util/agent_instructions.py -> connectable_apps_section
  compute_skill_runtime_hash(files, connectable_apps_section)   skills/push.py
  compare against current_hashes (the locked Sandbox.skills_hash) -> only changed sandboxes proceed
  get_sandbox_manager().push_to_sandboxes(mount_path=SKILLS_MOUNT_PATH, sandbox_files=changed_files)
  set_sandbox_skills_hashes__no_commit  for every sandbox whose push succeeded
```

`list_runtime_skills_for_user` (`db/skill.py`) is the single gate for "does
this user's sandbox get this skill": visibility (`skill_visible_to_user`),
per-user enablement (`_is_enabled_for_user`), external-app readiness (an
app-backed skill is excluded unless
`get_skill_external_app_dependencies(...).ready`), custom-bundle validity
(excluded if `is_valid is False`), and built-in availability
(`_exclude_unavailable_built_in_skills`). `_assemble_fileset` then hydrates
each surviving row: built-ins copy every non-excluded file from
`BUILTIN_SKILLS_PATH/<id>/` (skipping `__pycache__`, dotfiles, and raw
`.template` sources) and, if templated, overwrite `SKILL.md` per §4.2;
custom rows lazily validate an unclassified bundle
(`validate_stored_custom_skill`), persist that classification
(`persist_skill_validity`), and unzip a valid bundle's bytes under
`{skill.name}/`. A name collision between two enabled skills in the same
fileset raises rather than silently overwriting one
(`_assemble_fileset`'s `seen_names` check).

`sandbox_lifecycle.py:build_managed_content_payload` (owned by
`[[craft-sandboxes]]`) calls `build_user_skills_payload` directly and is what
runs at session-provisioning time, before the sandbox is reported
`RUNNING`; `push_skills_for_users` is the same payload construction plus the
locked hash comparison, used by every skill-mutation endpoint to push to
already-running sandboxes. Both write through
`SandboxManager.push_to_sandbox(es)` to the fixed mount path
`SKILLS_MOUNT_PATH = "/workspace/managed/skills"` (`skills/push.py`), which
lands on the sidecar-managed `managed` volume described in
`[[craft-sandboxes]] §4.3-4.4`; sessions symlink `.opencode/skills` into it.

### 4.4 The hash: what it invalidates, and how staleness surfaces

`compute_skill_runtime_hash(files, connectable_apps_section)`
(`skills/push.py`) is a SHA-256 over every rendered file's path and bytes
(sorted by path) plus the connectable-apps guidance text, each length-prefixed
to avoid ambiguity. It is a pure function of *rendered output*, so it changes
whenever any input to rendering changes: a skill's files, its enabled set for
that user, an external app's connection/policy state feeding
`render_external_app_skill`, or the set of connectable-but-unconnected apps
(`build_connectable_apps_list`). It intentionally does **not** cover the
craft MCP set - that has its own `mcp_config_hash`, tracked and pushed
independently (`sandbox_lifecycle.py`, `refresh_mcp_config_hashes_for_users`).

Two hash fields exist at two levels: `Sandbox.skills_hash` is "what was last
successfully pushed to this sandbox's managed volume"; `BuildSession.skills_hash`
is "what the currently-running opencode instance for this session was
configured with." `session_runtime_stale`
(`server/features/build/db/build_session.py`) compares the two: a live,
interactive, already-started session is stale if `sandbox.skills_hash !=
session.skills_hash` (or the MCP equivalent). This is what
`SkillsStaleNotice.tsx` renders and what
`SessionManager.reload_session_skills` (`session/manager.py`) resolves: it
regenerates the session's `opencode.json`/`AGENTS.md` and disposes the live
opencode instance so the next turn starts fresh with current skills, then
copies `sandbox.skills_hash`/`mcp_config_hash` onto the session row. A skill
push that only touches `Sandbox.skills_hash` (§4.3) does **not** by itself
change agent behavior mid-session; it only makes the *next* reload (or new
session) current, and flips the stale flag so the user can request an
explicit reload without waiting for a new session.

`push_skills_for_users` locks every target sandbox's `skills_hash` row
(`lock_sandbox_skills_hashes`, `SELECT ... FOR UPDATE`) before computing the
desired hash and diffing, so a skill push can't race a concurrent push for
the same sandbox into recording a stale hash as current. The push and the
hash write are not atomic with each other, though: `push_to_sandboxes`
happens outside any DB transaction, and only sandboxes for which the file
push actually succeeded get their hash updated
(`push_skills_for_users`'s `successful_sandbox_ids`); a partial failure
therefore self-heals on the next push attempt rather than recording a hash
for content that never landed.

---

## 5. Contracts and invariants

1. **A skill's `name` is immutable identity and the sandbox directory name.**
   Frontmatter `name`, `Skill.name`, and (for a stored bundle) the wrapper
   directory it was flattened from must all agree
   (`parse_skill_document`'s `directory_name` check,
   `validate_stored_custom_skill`'s post-load re-check). Renaming a skill in
   place is not supported by this code path; a rename is a delete-and-recreate.
2. **`built_in_skill_id` XOR `bundle_file_id`** (`ck_skill_definition_source`).
   A change that leaves both or neither set is a DB-level rejection, not a
   soft validation failure.
3. **The runtime hash must change whenever rendered content changes, or a
   sandbox keeps stale skills.** `compute_skill_runtime_hash` must cover
   every input to `_assemble_fileset`/`build_connectable_apps_list`. Adding a
   new rendering input (a new template placeholder, a new gating signal)
   without folding it into the hash means an edited skill silently fails to
   re-push.
4. **A skill whose external app is not connected does not half-work: it is
   excluded from the fileset entirely** (`list_runtime_skills_for_user`'s
   `ready_external_app_skill_ids` filter). It never reaches the sandbox in a
   broken state; it simply isn't there until the app is connected.
5. **Disabling a personal skill must stay reversible.** Disable is
   `DELETE FROM user_skill_preference WHERE user_id=... AND skill_id=...`
   (`db/skill.py:set_skill_enabled_for_user`) - re-inserting the same row
   (re-enabling) fully restores prior state. Only `delete_skill`
   (`db/skill.py`, a hard `DELETE FROM skill`) is irreversible. A change that
   makes "disable" write a tombstone flag instead of removing the row, or
   that starts cascading deletes from a disable action, breaks this
   deliberately-chosen semantic (see `project_personal_skill_disable_is_reversible_mute`
   precedent for the same distinction elsewhere in Craft).
6. **Custom skill validation must run before content reaches a sandbox.**
   `_assemble_fileset` never unzips an unvalidated or invalid custom bundle;
   `validate_stored_custom_skill` is the sole gate, and its classification is
   persisted (`persist_skill_validity`) only when the row was previously
   unclassified, never overwriting an already-decided `is_valid`.
7. **Sharing must not let a user read a skill they were not granted.**
   `skill_visible_to_user` (`db/skill.py`) is the single predicate every
   listing/fetch/runtime query uses; a new read path that queries `Skill`
   directly without this predicate (or without `_is_editable_by_user` for
   mutation) bypasses sharing.
8. **An app-associated skill cannot go fully private.**
   `set_skill_public_permission` rejects any value other than `VIEWER` for a
   skill with an `ExternalApp__Skill` row - it must stay organization-visible
   at read level even if only the connected app's users can use it.
9. **A skill name can be "enabled" by only one row per user.**
   `UserSkillPreference`'s unique index is on `(user_id, name)`; two
   different skills sharing a name can never both be the user's active
   choice under that name, by construction, not by an application check.

---

## 6. Relationships

**Depends on**
- `[[craft-sandboxes]]`: the pushed fileset lands on the sandbox's `managed`
  volume; provisioning calls `build_managed_content_payload`/`push_managed_content`
  directly.
- `[[craft-external-apps]]`: connection state and per-action policy gate
  which external-app skills are runtime-visible and what their rendered
  `SKILL.md` warns against; credential injection at call time is that
  component's job, not this one's.
- `[[craft-sessions]]`: `BuildSession.skills_hash`/`mcp_config_hash` and
  `session_runtime_stale`/`reload_session_skills` live in the session
  manager; this component only produces the hash it compares against.
- `[[access-control]]`: `Permission.MANAGE_SKILLS`, `Skill__User`/`Skill__UserGroup`
  visibility, and scoped-manager group checks (`within_managed_scope_clause`)
  reuse the platform's permission and group-scoping primitives.
- `[[file-store-and-user-files]]`: custom skill bundles are stored blobs
  (`FileOrigin.SKILL_BUNDLE`) read/written through the shared `FileStore`
  abstraction.
- `[[auth-and-identity]]`: GitHub import authenticates as the user's
  connected GitHub app credentials when available
  (`_github_authorization_header`).

**Depended on by**
- `[[craft-admin]]`: an admin connecting/disconnecting an external app, or
  changing its action policy, changes what a dependent skill renders and
  whether it's runtime-visible; that surface calls into this one indirectly
  via `push_skill_to_affected_sandboxes`/re-render on next push.
- Craft session provisioning and reload (`[[craft-sessions]]`,
  `[[craft-sandboxes]]`) consume `build_user_skills_payload` as one half of
  "managed content," alongside the user library.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a built-in skill | `built_in.py:_REGISTRY` entry, its `builtin/<id>/` directory and `SKILL.md`, whether it needs `is_available`, and whether a new template needs a renderer branch in `push.py:_render_template` |
| changes the bundle format (zip layout, `SKILL.md` frontmatter shape) | `bundle.py` (`normalize_custom_bundle`, `_validated_bundle_path`), `metadata.py` (`SkillMetadata`), `validation.py`, and every existing stored custom skill's bundle (a schema tightening can retroactively invalidate real rows) |
| changes the hash inputs (`compute_skill_runtime_hash`, `_assemble_fileset`, `build_connectable_apps_list`) | confirm the new input is actually folded into the hash bytes, or a real content change won't mark sandboxes/sessions stale; also check `[[craft-sessions]]`'s `session_runtime_stale` still reads the right fields |
| changes app coupling (`ExternalApp__Skill`, `EXTERNAL_APP_SKILL_ID_TO_APP_TYPE`, `get_skill_external_app_dependencies`) | `[[craft-external-apps]]`'s action-policy views, `db/skill.py:list_runtime_skills_for_user`'s readiness filter, and `response_helpers.py`'s dependency response shown in the UI |
| changes sharing (`Skill__User`, `Skill__UserGroup`, `public_permission`) | `skill_visible_to_user`/`_is_editable_by_user` (both must move together), the scoped-manager GATE 2 check in `api.py:_assert_group_share_within_scope`, and `set_skill_public_permission`'s app-association guard |
| changes enable/disable semantics | §5.5 above; verify disable stays a row delete, not a flag flip, and that `delete_skill` remains the only irreversible path |
| changes GitHub ingestion (`ingest_from_github.py`) | path-traversal/symlink checks, `GITHUB_SKILL_MAX_COUNT`, and that `parse_skill_document`'s validation still runs before any bundle is stored |
| changes what gets pushed or where (`SKILLS_MOUNT_PATH`, `push_to_sandbox(es)`) | `[[craft-sandboxes]]`'s sidecar `/push` contract and the `managed` volume mount |

---

## 8. How to verify a change

### Tests

```bash
# External dependency unit tests (need Postgres for Skill/ExternalApp rows)
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit -k skill
# e.g. backend/tests/external_dependency_unit/craft/test_external_app_fileset.py

# Frontend unit/component tests already covering this surface
cd web && bun run test -- src/views/SkillsPage.test.tsx
cd web && bun run test -- src/views/SkillEditorPage.test.tsx
cd web && bun run test -- src/sections/cards/SkillCard.test.tsx
cd web && bun run test -- src/sections/modals/SkillPreviewModal.test.tsx
cd web && bun run test -- src/sections/modals/skills/CreateSkillModal.test.tsx
cd web && bun run test -- src/sections/modals/skills/ImportSkillsFromGitHubModal.test.tsx
cd web && bun run test -- src/sections/skills/SkillBundlePicker.test.tsx
cd web && bun run test -- src/sections/skills/SkillFileTree.test.tsx
cd web && bun run test -- src/app/craft/components/SkillsStaleNotice.test.tsx
```

See `backend/AGENTS.md` for authoritative test commands and required env.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log`.
2. Open `http://localhost:3000/craft/v1/skills`, sign in as
   `admin_user@example.com` / `TestPassword123!`.
3. Create a custom skill with a short instruction body, leave it enabled.
4. Start (or resume) a Craft session and ask the agent to list its available
   skills or read `AGENTS.md`/the skills directory; confirm the new skill's
   instructions are visible to it.
5. Edit the skill's instructions, save. Return to the running session:
   confirm the stale-skills notice appears, then click reload; confirm the
   agent's next turn reflects the edit.
6. Disable the skill, confirm the next push removes its files from the
   sandbox (or the reload clears it from what the agent sees); re-enable it
   and confirm it comes back with no data loss.
7. For an external-app skill: as a user with the app disconnected, confirm
   it's visible but not toggleable; connect the app; confirm it becomes
   enable-able and, once enabled, its `SKILL.md` renders without an
   unavailable-actions warning until an admin denies a specific action.

### What "working" looks like

- A skill push only rewrites sandboxes whose desired hash actually differs
  from `Sandbox.skills_hash`.
- Disabling and re-enabling a personal skill round-trips with no visible
  side effect.
- An external-app skill never appears half-configured in a sandbox; it is
  either fully present (app connected) or fully absent (not connected).

---

## 9. Footguns

- **The runtime hash is computed twice per push and is not atomic with the
  push itself.** `push_skills_for_users` locks and compares hashes, pushes
  files with no open transaction, then records the hash only for sandboxes
  whose push succeeded. A crash between file-push success and hash-record
  leaves the sandbox correct but the DB stale; the next push recomputes the
  same desired hash, sees a mismatch, and re-pushes harmlessly. Don't
  "optimize" this into a single transaction spanning the external push -
  that was deliberately avoided (mirrors the reserve/reconcile/finalize
  split in `[[craft-sandboxes]]`).
- **Two different staleness signals exist and are easy to conflate.**
  `Sandbox.skills_hash` (has this sandbox received the current push) and
  `BuildSession.skills_hash` (has this session's live opencode instance been
  told to reload) are compared against each other by
  `session_runtime_stale`, not against some third "current" value. A skill
  push updates only the sandbox side; nothing proactively updates every open
  session's row, which is why the stale notice exists as a discoverable
  affordance instead of a silent auto-heal.
- **Custom skills cannot ship `.template` files** - only built-ins are
  templated, and `normalize_custom_bundle`/`update_custom_bundle_files`
  actively reject an uploaded `.template` path. A custom skill that wants
  per-user rendering has no supported way to do it in this code.
- **GitHub ingestion trusts the repository's file *shape* (path safety, size
  limits, one `SKILL.md` per directory) but not its *content*.** Beyond
  `parse_skill_document`'s frontmatter/name/description checks, nothing
  inspects what the instructions or any bundled script actually say or do.
  A skill's Markdown body and any bundled files (Python, JS, arbitrary
  binaries) are pushed into the sandbox and read as agent instructions
  verbatim; the only asymmetric protections that exist here are archive
  bounds (`_ARCHIVE_MAX_BYTES`, `_ARCHIVE_MAX_MEMBERS`, per-file/total byte
  caps) and path-traversal/symlink rejection. **A malicious skill's
  instructions themselves are not sandboxed against by this code beyond
  that** - whatever containment a malformed-content or prompt-injection-style
  skill gets comes entirely from the sandbox's own execution boundaries
  (`[[craft-sandboxes]]`, `[[craft-external-apps]]`'s egress proxy), not from
  anything in `onyx/skills/`.
- **A skill row can reference a built-in id that no longer exists in
  `BUILT_IN_SKILLS`** (a removed or renamed entry, or cross-deployment drift).
  Every read path logs a warning and silently excludes/hides the row
  (`list_skills`, `list_runtime_skills_for_user`,
  `skills_list_response_for_user`) rather than erroring - a missing built-in
  degrades silently, not loudly.
- **`is_valid=None` (unclassified) is a distinct third state from `True`/`False`,**
  not just "not yet checked." `list_runtime_skills_for_user` treats `None`
  the same as `True` (include and attempt to hydrate); only an explicit
  `False` excludes. A skill can therefore ride along as "probably fine"
  until its bundle is actually read and classified.

### Shared document preview script

The built-in PowerPoint preview script also renders first-page PDF and PowerPoint
thumbnails for Outputs. Both sandbox providers deploy this script and its LibreOffice
helper in a versioned bundle. Preview requests do not update managed skills or the
running agent's context. PDF rendering uses Poppler directly.

Thumbnail conversion has a 30-second deadline; full-slide conversion has a
120-second deadline. Both include lock waiting. Finished JPEGs replace cached files
atomically, and failed conversion retains the last complete image. The converter
checks source revisions before publication and cache reuse.

See [[craft-sandboxes]] for advisory size checks, bundle deployment, and snapshot exclusions.
