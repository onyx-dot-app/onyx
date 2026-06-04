# Skills — Product Proposal (v1)

## Summary

**Skills are reusable capability bundles that extend what the Craft AI coworker can do.** A skill is a self-describing directory containing a `SKILL.md` instruction file plus any mix of supporting assets — Python scripts, bash helpers, executables, schemas, fonts, fixture data, additional markdown — that the agent reads, executes, or references on demand when the skill's description matches the user's task.

Skills come from two sources in V1:

- **Built-in skills** ship with the deploy and become available automatically when their dependencies are configured. They live in the codebase under `onyx/skills/builtin/<slug>/` and are registered at app boot in the in-memory `BuiltinSkillRegistry`.
- **Custom skills** are uploaded as zip bundles by admins through `/admin/skills`. Each custom skill is one row in the `skill` table plus a bundle blob in the file store, scoped to the tenant.

Bundles are validated synchronously on upload; on success they're stored, indexed, and immediately pushed into every sandbox that should see them.

**Skills live in the sandbox at the user level, not per session.** Each user's sandbox keeps a directory of the skills they currently have access to at `/workspace/managed/skills/<slug>/` (the agent reads them via the `.opencode/skills/` symlink). The backend keeps that directory in sync as bundles, grants, and availability change by pushing to running pods through `SandboxManager.push_to_sandboxes`. Sessions running inside the sandbox see the live skill set — no need to wait for a new session to pick up a granted, replaced, or revoked skill.

The agent automatically gets every skill the running user has access to — no per-session picking, no manual selection. Visible surfaces are: an admin skills page (`/admin/skills`) for org-wide governance, and a read-only "what's available" panel inside Craft sessions for transparency.

The full engineering plan lives at [`../features/skills/`](../features/skills/) — read `skills-requirements.md`, `skills-db-layer-status.md`, and `skills-api-plan.md` in that order. This document is the product spec.

### V1 API surface

These are the endpoints the product behaviors in this doc rely on (see `../features/skills/skills-api-plan.md` for the full plan):

| Endpoint | Purpose |
|---|---|
| `GET /admin/skills` | Admin: list built-ins (with availability) + customs (with grants, including disabled) |
| `POST /admin/skills/custom` | Admin: upload a new custom skill (multipart bundle + metadata) |
| `PATCH /admin/skills/custom/{id}` | Admin: edit `is_public`, `enabled` |
| `PUT /admin/skills/custom/{id}/bundle` | Admin: replace the bundle bytes |
| `PUT /admin/skills/custom/{id}/grants` | Admin: atomic replace of group grants |
| `DELETE /admin/skills/custom/{id}` | Admin: hard-delete (no soft-delete in V1) |
| `GET /skills` | User: list available built-ins + accessible customs |

Mutations push bundle bytes to running sandboxes via `SandboxManager.push_to_sandboxes` after commit; the FileStore blob is still written for persistence and cold-start hydration on next session start.

---

## Requirements

### What a skill is, from the user's point of view

1. **A skill has a name, a description, and a body.** The description is what the agent reads when deciding whether to invoke the skill. The body is whatever instructions, scripts, or assets the skill needs.
2. **A skill is a directory, not a single file.** Bundles can include any mix of:
   - `SKILL.md` (required) and other markdown documentation.
   - Python files, bash scripts, Node scripts, or any other source the agent can `python …` / `bash …` from inside the sandbox.
   - Compiled executables and platform binaries that ship with the bundle.
   - Data files: JSON / YAML / XML schemas, CSV fixtures, prompt templates, font files, images, small ML model artifacts, etc.

   The runtime treats the bundle as an opaque directory the agent can read, execute from, and reference by path. There is no whitelist of allowed file types — only a per-file size cap (25 MiB) and a total bundle cap (100 MiB), both enforced by `validate_custom_bundle` in `backend/onyx/skills/bundle.py`. The existing `pptx` built-in is the canonical example: it ships `SKILL.md`, several supporting `*.md` guides, a `scripts/` directory of Python helpers, and template `.pptx` assets.
3. **Skills are reached by the agent, not invoked by the user.** Users don't pick skills from a menu before sending a prompt. The agent matches the user's intent against available skill descriptions and reaches for the right one.
4. **Skills are scoped to the user.** The set of skills the agent has access to in a session is exactly the set the running user has access to — no more, no less.

### Built-in skills

5. **Onyx ships a curated built-in set.** V1 includes presentation/deck (`pptx`), image generation (`image-generation`), and permissioned company search (`company-search`). New built-ins ship via deploy, not configuration. They are registered in `BuiltinSkillRegistry` at app boot, not stored in the database.
6. **Built-ins auto-enable when their dependencies are met.** Each built-in declares an `is_available(db_session) -> bool` callable. If `image-generation` requires a Gemini key and the deploy doesn't have one configured, the skill is unavailable. Admins don't toggle built-ins on/off — wiring up the dependency is the toggle.
7. **Admins can see which built-ins are available and why not.** The admin skills page shows each registered built-in with an Available / Unavailable badge and a one-line reason for the unavailable case (e.g. *"Requires GEMINI_API_KEY"*). Computed per-request from `BuiltinSkill.is_available` and `unavailable_reason`.

### Custom skills — authoring (admin-only in V1)

8. **V1 authoring is admin-only.** Both the upload endpoint (`POST /admin/skills/custom`) and the management page (`/admin/skills`) are admin-gated. User-authored skills are a future enhancement (see below).
9. **Custom skills are uploaded as zip bundles.** Admins prepare a bundle locally — `SKILL.md` at the root with frontmatter `name` + `description`, plus any supporting files (additional markdown, Python / bash / Node scripts, executables, schemas, fixtures, fonts, images, etc.) — and upload it through `/admin/skills`. Re-uploading via `PUT /admin/skills/custom/{id}/bundle` replaces the bundle atomically.

### Custom skills — visibility and access

10. **Custom skills have one of three V1 visibility states:**
    - **Private** — `is_public = false` with no group grants. Only admins can see it via `/admin/skills`; no end users have access. Useful as a staging state before sharing.
    - **Group-scoped** — `is_public = false` plus one or more entries in `skill__user_group`. Users in any granted group have access; others don't.
    - **Org-wide** — `is_public = true`. Every user in the tenant has access.

    Visibility is set on create and editable via `PATCH /admin/skills/custom/{id}` (`is_public` flag) and `PUT /admin/skills/custom/{id}/grants` (atomic replace of group grants). Direct user grants ("share with user X specifically") are out of scope for V1 — group membership is the only per-user access mechanism.

11. **Admins manage every custom skill.** Authorship is recorded (`author_user_id`) for audit, but in V1 the author is always an admin and every admin can edit every custom skill. Curator-or-admin access controls the admin router.
12. **Custom skills can be disabled and re-enabled.** Setting `enabled = false` via `PATCH` immediately removes the skill from every sandbox that had it, without losing the bundle, metadata, or grants. Useful as a kill-switch or as a way to take a skill out of circulation while reworking it. Disabled skills remain visible to admins in `/admin/skills`; users do not see them.

### Custom skills — lifecycle

13. **Bundles validate synchronously on upload.** Bundle errors (missing `SKILL.md`, slug collision with a built-in or another custom skill, path traversal, symlinks, oversize files, forbidden template files) surface inline with a clear `OnyxError` and reason. Nothing partially persists.
14. **Replacing the bundle is the canonical edit path.** `PUT /admin/skills/custom/{id}/bundle` atomically replaces the prior bundle with a new fingerprint, pushes to affected sandboxes, then deletes the old blob inline (best-effort, logged on failure). Slug is immutable post-create unless explicitly changed via `PATCH`; the rest of the metadata (name, description, visibility, enabled state) is editable inline without re-uploading.
15. **Custom skills are hard-deleted.** `DELETE /admin/skills/custom/{id}` removes the row, removes the skill from every sandbox immediately, and cleans up the bundle blob inline. There is no soft-delete in V1 — slug reuse works because the row is gone. If you need to take something out of circulation without losing it, disable it instead.

### Admin governance

16. **The admin skills page lists every custom skill regardless of grants.** Built-ins appear in their own section (read-only with availability badges); customs are listed in a single table with author column, visibility summary (Org-wide / Groups / Private), enabled flag, last-updated timestamp, and an action menu. Filterable by visibility and enabled state.
17. **Changes propagate immediately.** Granting a group, revoking a group, flipping `is_public`, replacing a bundle, disabling, enabling, or deleting — every change is reflected in the affected sandboxes as soon as the request commits. The skills feature computes the set of affected users from the before-and-after state, resolves their `sandbox_id`s, builds a per-user file set, and pushes through `SandboxManager.push_to_sandboxes(mount_path="/workspace/managed/skills", sandbox_files=...)`. Sessions in flight see the new state without restarting. Push failures are logged inside `SandboxManager` and recorded in `PushResult`; they don't surface as request errors — cold-start hydration on the next session covers the long tail.

### Materialization and discovery

18. **Skills live in the user's sandbox, independent of any session.** The sandbox holds every skill the user currently has access to: available built-ins + org-wide customs + customs granted via any of the user's groups. There is no per-session pinning and no skill picker.
19. **Cold-start hydration runs on session bring-up.** When a sandbox is first created (or wakes from a stopped state), `skills.push_to_pod(sandbox_id, user, db_session)` materializes the user's accessible skill set from the DB + FileStore and pushes via `SandboxManager.push_to_sandbox`. After bring-up, all changes flow through the per-mutation push path described in #17.
20. **Bundles materialize into the sandbox verbatim.** Every file in the bundle (markdown, scripts, executables, data) lands at `/workspace/managed/skills/<slug>/<original-path>` exactly as authored. File modes are preserved so executable bits survive — the agent can run a bundled `scripts/foo.sh` directly. Built-ins additionally support template rendering of `SKILL.md.template` against the user's `SkillRenderContext` at materialization time; custom skills do not.
21. **The agent finds skills via convention.** From inside the sandbox, skills appear at `.opencode/skills/<slug>/SKILL.md` (a symlink to the managed mount); the agent enumerates and reads them as needed. The session's `AGENTS.md` lists either every skill inline (when the count is small) or the built-ins inline plus a discovery instruction to enumerate the rest. Because the agent re-reads the directory on demand, additions during a session are discoverable; descriptions the agent has already pulled into context, however, persist until that context is cleared.

### Surfaces

22. **One admin page (`/admin/skills`) for org-wide governance.** Two sections: built-ins (read-only with availability) and customs (every custom skill in the tenant, with replace / patch / grants / disable / delete actions). The page is not nested under Craft because skills are a cross-surface primitive. Backed by `GET /admin/skills`.
23. **Users can see what skills are available in their session.** A read-only panel in the Craft session UI lists the names + descriptions of the skills the user actually has, sourced from `GET /skills` — the same access query as the materializer. This is for transparency; users don't act on it.
24. **`/` opens a skill picker in any prompt input.** Typing `/` in the Craft session chat input — or in a scheduled trigger's prompt field — opens a popover listing every skill the user has access to (same set as `GET /skills`), with name and description. Continued typing filters the list by slug, name, and description. Arrow keys move the selection; **Enter** or **Tab** inserts `/<skill-slug>` into the input (replacing the `/` token) so the user can continue writing. Pressing **Escape** or clicking outside dismisses without inserting. This is a hint — the agent still uses description-based matching — but it gives the user a way to nudge the agent toward a specific skill when they already know which one they want. For scheduled triggers the available skills are scoped to the trigger owner's accessible set (same access query as `GET /skills`).

### Sandbox runtime

25. **Sandbox runtime requirements for executables are the bundle author's responsibility.** Skills run in the standard Craft sandbox image, which already includes Python, Node, bash, common CLI utilities, and LibreOffice. If a custom skill needs an interpreter or library not in the image, the author bundles a self-contained binary or installs the dependency at run time inside the sandbox (e.g. via `pip install`). Onyx does not provide a per-skill image-extension mechanism in v1.

### Cross-surface readiness

26. **Skills are a universal primitive, not a Craft-only feature.** Database tables, APIs, validation, and UI live in a non-Craft module (`backend/onyx/db/skill.py`, `backend/onyx/skills/`, `backend/onyx/server/features/skill/`). Craft is the v1 consumer; Personas, Chat, or other surfaces can adopt skills later without touching the universal layer.

---

## Out of scope (v1)

These are intentionally deferred. Listed with the reason so we can revisit when the constraint changes.

- **User-authored skills.** Only admins can upload custom skills in V1; there is no `POST /skills/custom` endpoint for regular users, and no `/skills` upload UI.
  *Why:* The admin-only path covers the most common case (a tenant admin distributing skills to their org) and avoids designing share, fork, and visibility-bounding flows before we see how skills are actually used. The DB schema already tracks `author_user_id`, so user-authoring is a clean follow-up — add a user-scoped router, default new uploads to `is_public=false` with no grants, and bound group sharing by membership.
- **"Specific users" / direct user grants.** Visibility is org-wide (`is_public`), group-scoped (via `skill__user_group`), or private — there's no "share with user@" picker, and no `skill__user` junction table.
  *Why:* Group membership is the existing access primitive in the rest of the product; reusing it keeps the surface small. A direct-grant table is a backwards-compatible add when the demand surfaces.
- **Request org-wide / promotion workflow.** No "request promotion" flag, no demotion path, no draft-and-review queue.
  *Why:* Only admins author skills in V1, so there's nothing to request — admins set `is_public = true` directly when they want org-wide reach. Worth revisiting when user-authoring lands.
- **Soft-delete.** `DELETE /admin/skills/custom/{id}` is destructive — the row is gone, the blob is cleaned up inline, and the slug becomes available for reuse. There's no `deleted_at` column and no recovery path.
  *Why:* Disable (`enabled = false`) is the kill-switch that preserves the bundle, metadata, and grants. Soft-delete adds a column, a filter on every read, and a slug-uniqueness wrinkle without buying anything disable doesn't already provide.
- **In-browser skill authoring.** The product surface is upload-and-manage; there is no markdown editor for `SKILL.md`, no file tree, no inline script editor, no drag-and-drop bundle assembler.
  *Why:* The bundle format and lifecycle should settle on uploaded zips before we invest in editing UX. Most early authors already keep their skill content in git or a local folder; a zip is a thin packaging step on top of that. Once we see how authors actually maintain skills, we'll know what to optimize for.
- **Per-session skill picking.** Users can't select a subset of their granted skills for a given session.
  *Why:* The agent's description-based matching is the selection mechanism. Adding a manual picker creates two systems for the same job and forces the user to predict what they'll need.
- **Versioning and rollback.** One bundle per skill — re-uploading replaces it. No version history, no "promote a draft" step, no rollback UI.
  *Why:* Keeping older bundles around is real complexity for a small benefit. Authors who want manual rollback can keep a copy locally and re-upload. Worth revisiting once skills get complex enough to justify the overhead.
- **Templating in custom skills.** Bundles containing `*.template` files are rejected at upload by `validate_custom_bundle`.
  *Why:* The render context shape (`SkillRenderContext`) is still evolving for built-ins. Locking it in publicly via custom uploads would create a compatibility surface we'd have to support indefinitely.
- **In-product fork.** A recipient can't click "fork this skill" and immediately start editing their own copy.
  *Why:* Without user-authoring there's no "their own copy" target; this becomes meaningful once `POST /skills/custom` exists for regular users.
- **In-browser script execution / preview.** No way to test a skill from the management page; previewing skill behavior means starting a Craft session and prompting the agent.
  *Why:* Sandboxed code execution from the skills page is non-trivial infrastructure with a separate threat model. Out-of-scope until usage shows it's needed.
- **Signed / verified skills.** No cryptographic signing, no trusted-publisher badge, no chain-of-custody metadata.
  *Why:* All v1 skills come from the deploy or a tenant admin. The trust boundary is the tenant + the admin role.
- **Public marketplace / cross-org sharing.** No registry of community-authored skills, no install-from-URL.
  *Why:* We need to see what skills customers actually build before designing distribution. Local zips are sufficient to share between orgs out-of-band today.
- **Skill-level secrets.** Skills can't carry their own API keys, OAuth client IDs, or tokens.
  *Why:* That's what the egress interception + OAuth-for-apps systems are for. Embedding secrets in skill bundles would fragment the secrets story.
- **Skill telemetry / analytics.** No "which skill was invoked" dashboards, no per-skill usage counts.
  *Why:* The run audit layer (project #9) covers skill usage at a per-run level for governance. A dedicated analytics surface is a nice-to-have once usage patterns are clearer.
- **Cross-skill dependencies.** A skill cannot declare "I require skill X to be installed."
  *Why:* No real demand yet, and the file-discovery convention means the agent can already chain skills implicitly. Worth revisiting if customers start shipping skill suites.
- **MCP-based skills.** Skills are file-based directories the agent reads, not MCP servers.
  *Why:* This matches the broader Craft direction (interception layer + skills + raw API calls instead of MCP). One distribution model is simpler to operate.
- **Persona and Chat consumption.** V1 builds the primitive ready for other consumers but only Craft uses it.
  *Why:* Scope discipline. Personas and Chat skill attachment is a follow-up project; the universal layer just makes it cheap when we get there.
- **Built-in toggling.** Admins can't disable a built-in for their tenant.
  *Why:* Availability is a function of the deploy's wiring and the built-in's `is_available` callable. If you don't want `image-generation`, don't configure the provider. Adding a per-tenant override creates a state-vs-config divergence we don't want to debug.
- **Orphan-blob sweep.** Delete/replace clean up old blobs inline (best-effort, logged on failure). No periodic sweep job.
  *Why:* Inline cleanup covers the common case; a sweep is a future hardening step if leaks show up in storage metrics.
- **`GET /skills/{slug_or_id}` single-skill endpoint.** Listing returns enough metadata; there's no detail-fetch endpoint.
  *Why:* The list payload already includes every field the UI needs. Deferred until a concrete UI flow demands it.

---

## User flows

### Admin

#### A1. See what skills exist in the tenant

1. Admin opens `/admin/skills` (backed by `GET /admin/skills`).
2. Two sections:
   - **Built-in skills** — one row per registered built-in: name, description, availability badge. Unavailable rows show a one-line reason (e.g. *"Requires GEMINI_API_KEY"*). Computed from `BuiltinSkill.is_available(db_session)` and `unavailable_reason`.
   - **Custom skills** — one row per custom skill: name, description, **author** (admin who uploaded), **visibility** (Org-wide / Groups / Private), last-updated timestamp, enabled toggle, action menu. Filterable by visibility and enabled state. Includes disabled skills.

#### A2. Make a built-in available

Implicit. Admin configures the underlying dependency (`GEMINI_API_KEY`, provider row, feature flag) elsewhere. The built-in flips to Available on the next page load. Built-ins re-converge into sandboxes on the next session start / wakeup (no push trigger for built-in availability flips in V1 — see `skills-api-plan.md` §2).

#### A3. Upload a custom skill

1. Admin clicks **Upload skill** on `/admin/skills`.
2. Modal collects: zip, `is_public` flag, group IDs (JSON-encoded list). The slug is derived from the zip filename, and `name` + `description` are parsed from `SKILL.md` frontmatter — they are not separate form fields.
3. Admin selects a local zip with `SKILL.md` at the root + supporting files (markdown, scripts in any language, executables, schemas, fixtures, fonts, images).
4. Click **Upload**. `POST /admin/skills/custom` runs `validate_custom_bundle` synchronously.
   - **Validation fails** → modal shows the specific `OnyxError` reason (e.g. *"`SKILL.md` is missing"*, *"Bundle contains `SKILL.md.template` (templates aren't supported in custom skills)"*, *"Slug reserved by a built-in skill"*). Nothing persists.
   - **Validation succeeds** → bundle written to FileStore, `skill` row created, group grants inserted, commit, push to affected sandboxes, modal closes, list refreshes.

#### A4. Replace a custom skill bundle

1. From `/admin/skills`, admin opens any custom skill.
2. Drag-and-drops a new zip onto the **Replace bundle** target (or uses a file picker).
3. Confirmation: *"This replaces the current bundle in every active sandbox immediately. The agent will pick up the new version the next time it reads from the skill's directory."*
4. `PUT /admin/skills/custom/{id}/bundle`: backend validates and atomically writes the new blob → updates the skill row (new `bundle_file_id`, new `bundle_sha256`) → commits → pushes to affected sandboxes → deletes the old blob inline. Updated `last-updated` and fingerprint shown.

If the admin wants no sandbox to use the skill while reworking it, they disable the skill before replacing and re-enable after the new bundle is in place.

#### A5. Edit metadata (without replacing the bundle)

`PATCH /admin/skills/custom/{id}` accepts a `SkillPatchRequest` covering `is_public` and `enabled`. Slug, name, and description are derived from the bundle (filename + `SKILL.md` frontmatter) and are only mutated via Replace (A4). Bundle content is not editable here — bundle changes go through Replace (A4).

The endpoint pushes to affected sandboxes when visibility-affecting fields change (`is_public`, `enabled`).

#### A6. Configure visibility on a custom skill

Two endpoints cover visibility:

- **Org-wide flip** — `PATCH /admin/skills/custom/{id}` with `is_public: true`/`false`.
- **Group grants** — `PUT /admin/skills/custom/{id}/grants` with `{"group_ids": [...]}`. Atomic replace: the new list is the full set of granted groups.

The drawer in the UI presents both controls together. Save replaces grants atomically; combined `is_public` + group state determines who sees the skill.

#### A7. Disable / delete a custom skill

- **Disable**: `PATCH /admin/skills/custom/{id}` with `enabled: false`. Skill stays in the catalog; immediately removed from every sandbox that had it.
- **Delete**: `DELETE /admin/skills/custom/{id}`. Hard-delete — the row is removed, the bundle blob is cleaned up inline, the skill is removed from every sandbox. Idempotent (404 on second call is acceptable).

#### A8. Inspect a skill's content

The detail page shows: slug, name, description, frontmatter, file tree (relative paths, sizes, "executable" badge for files with the executable bit set), total uncompressed size, sha256 fingerprint, author, last-updated timestamp, and visibility summary (org-wide flag + granted group IDs). Downloading the bundle as a zip is a v1 affordance for re-upload-as-rollback.

### Regular user

#### U1. Start a Craft session and use available skills

1. User opens Craft and starts a new session (interactively or via a scheduled trigger).
2. The session attaches to the user's sandbox, which already holds their full skill set (available built-ins + org-wide customs + customs granted via any of the user's groups). If the sandbox is being created for the first time, `skills.push_to_pod` provisions the skills directory as part of bring-up; otherwise the session just sees the live state.
3. User prompts the agent.
4. Agent matches against descriptions, reads `SKILL.md`, follows it.
5. User sees the result.

The user does not have to select a skill — the agent reaches for the right one. If the user already knows which skill they want, U3 lets them nudge the agent toward it via the `/` picker.

#### U2. See what skills are available in a session

1. From the Craft session UI, open the **Skills available** panel.
2. Panel calls `GET /skills` and lists each available skill with name and description.
3. Read-only.

A future enhancement may distinguish source (built-in vs. custom), but v1 just shows the flat list.

#### U3. Hint the agent toward a specific skill via the `/` picker

1. In the Craft session chat input, user types `/`.
2. A popover opens listing every skill the user has access to (sourced from the same `GET /skills` payload as the **Skills available** panel), each row showing slug, name, and description. The first row is selected by default.
3. Continued typing filters the list by slug, name, and description; arrow keys move the selection.
4. User presses **Enter** or **Tab** on the highlighted row. The popover closes and the chat bar's `/` token is replaced with `/<skill-slug>` followed by a space, with the cursor positioned after it so the user can keep typing their prompt.
5. **Escape** or click-outside dismisses the popover without inserting.

The inserted `/<skill-slug>` is a hint, not a hard invocation — the agent still chooses based on descriptions. The picker exists for cases where the user already knows which skill they want and wants to save the agent the matching step.

#### U4. Use a skill in a scheduled trigger

Same as U1, but the session is started by the trigger system. The trigger attaches to the trigger owner's sandbox, so it sees that user's live skill set. The trigger config does not carry per-skill toggles in v1.

When authoring or editing a scheduled trigger, the prompt field supports the same `/` picker as U3: typing `/` opens a popover listing the trigger owner's accessible skills (sourced from `GET /skills`), filtering as the user types, with **Enter** or **Tab** inserting `/<skill-slug>` into the prompt. The inserted slug is stored verbatim in the trigger's prompt text — at run time it's just a hint to the agent, same semantics as in an interactive session. If the trigger owner later loses access to a referenced skill (group revoked, skill disabled or deleted), the prompt text doesn't change; the agent simply won't find the skill in the sandbox and falls back to description-based matching across whatever is still available.

### Cross-cutting

#### X1. A built-in suddenly becomes unavailable

If the dependency that powered a built-in is removed (key unset, provider row deleted), `is_available(db_session)` returns false. The built-in flips to Unavailable in `GET /admin/skills` and `GET /skills`. Active sandboxes still hold the prior files until the next session start / wakeup (no push trigger for built-in availability flips in V1).

#### X2. A user's group membership changes

Adding the user to a group that's granted a custom skill puts the skill in their sandbox on the next mutation that triggers a push, or at the next session start / wakeup. Removing them takes it out on the same triggers. V1's push triggers are skill mutations (create / patch / bundle replace / grants replace / delete); group-membership changes are not currently a push trigger — they re-converge through session bring-up. (Adding a group-membership push trigger is a low-risk extension once the push API is stable.)

#### X3. A bundle is replaced while a user has a session open

Every active sandbox that had the prior bundle is updated in place through `push_to_sandboxes`. The agent picks up the new version the next time it reads from the skill's directory. Already-running scripts inside the agent finish against whatever was on disk when they started; new invocations see the new bundle.

If the author wants to be sure no agent reaches for the skill mid-replace, they disable the skill before replacing and re-enable after.

#### X4. A push partially fails

Push failures are recorded in `PushResult` from `SandboxManager.push_to_sandboxes` and logged inside the push API. The HTTP request still returns success (the DB commit happened; the source of truth is consistent). The affected sandbox re-converges to the correct state on the next mutation or cold-start hydration. Acceptable for V1; if partial failures become common, the synchronous fan-out can move to a background task with retry.

#### X5. The agent has already pulled a skill's `SKILL.md` into context, then the bundle changes

The skill's files on disk are updated; the agent's in-memory copy of the prior `SKILL.md` (if any) persists until the conversation context is cleared. This is a property of how LLMs handle context, not a sync gap — the next read against `/workspace/managed/skills/<slug>/SKILL.md` returns the new content. For most skills the agent re-reads on demand, so the practical impact is small.

---

## Open questions

These do not block v1 but are worth flagging for product follow-up:

1. **Should users see *why* a skill isn't in their session?** ("This skill exists but you don't have access.") V1 hides anything they're not granted — by design — but it can confuse users when they hear about a skill from a colleague.
2. **Should admins see effective-skill-set previews?** "Show me the skills user X currently has in their sandbox." Cheaper than asking the user. Backed easily by the existing `list_skills_for_user(user, db_session)` helper.
3. **Should the user-facing skills panel distinguish source?** Built-in vs. custom. Probably yes, low cost — `SkillsList` already separates `builtins` from `customs`.
4. **Should we surface a skill-author audit trail in the admin UI?** "Last replaced by alice@ on 2026-04-12, fingerprint abc123." Probably yes, low cost; `author_user_id`, `updated_at`, and `bundle_sha256` are all already in the schema.
5. **Should group-membership changes be a push trigger?** V1 re-converges through session bring-up; a push trigger is a small extension once the push API is stable (see X2).
6. **How big is the per-tenant fan-out cost for org-wide mutations?** An `is_public = true` flip in a large tenant rebuilds the per-user file dict for every user with an active sandbox. Capped by the push API at 100 MiB total, but the skills-side rebuild cost is unmeasured. Acceptable for v1; revisit if it shows up in admin-mutation latency.

---

## Future enhancements

Things explicitly considered for a future version, captured here so they don't get rediscovered every quarter:

- **User-authored custom skills.** Add a user-scoped router (`POST /skills/custom`, `PATCH /skills/custom/{id}`, `PUT /skills/custom/{id}/bundle`, `PUT /skills/custom/{id}/grants`, `DELETE /skills/custom/{id}`) that mirrors the admin endpoints but scopes mutations to the author's own skills, bounds group-sharing by the author's group membership, and defaults new uploads to `is_public = false`. Add a `/skills` page where users upload, share, and manage their own skills. The schema already supports this (`author_user_id` is in place); the work is API + UI + access checks.
- **Direct user grants.** Add a `skill__user` junction table for "share with user X specifically", plus a `PUT /admin/skills/custom/{id}/user-grants` (and user equivalent) endpoint. Visibility filter becomes `is_public OR user-granted OR group-granted`.
- **Request org-wide / promotion workflow.** Once user-authoring exists, add a "request promotion" flag, an admin promote action in `/admin/skills`, a demote path that restores the author's prior visibility setting, and a notice on the author's `/skills` page when admins disable, delete, demote, or promote their skills.
- **In-browser skill authoring.** A first-class authoring surface inside Onyx — markdown editor for `SKILL.md` with frontmatter helpers, file tree for the bundle, inline editing for text files (scripts, additional markdown, schemas), drag-and-drop for binary assets, executable-bit toggle, pre-save preview. Same validator, same artifact, same lifecycle as today's zip upload — just a different production path.
- **In-browser preview / test run.** Spin up an ephemeral Craft session to test a skill from the skills page without going to the main Craft surface.
- **In-product fork.** "Make this my own" button on a shared skill that copies the bundle into the user's catalog as a private skill they can edit. Depends on user-authoring landing first.
- **Ownership transfer.** First-class "transfer to user X" without re-uploading.
- **Skill review queue.** Comment threads, rejection reasons, and a draft-review-promote workflow on top of *Request org-wide*.
- **Soft-delete + versioning / rollback.** Add `deleted_at` and a bundle-history table; let authors and admins roll back without re-uploading.
- **Persona / Chat consumption.** Wire skills into other Onyx surfaces — the universal primitive is already shaped for this.
- **Group-membership push trigger.** Push on group-add / group-remove so newly-granted skills appear in sandboxes without waiting for the next session bring-up (see X2).
- **Background push fan-out.** Move the synchronous push for org-wide mutations to a background task with retry, for tenants where the fan-out cost shows up in admin-mutation latency (see open question #6).
- **`GET /skills/{slug_or_id}` single-skill detail.** Currently the listing endpoints return all fields the UI needs; add a detail-fetch endpoint when a concrete flow demands it.
