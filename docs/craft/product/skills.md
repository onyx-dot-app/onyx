# Skills — Product Proposal (v1)

## Summary

**Skills are reusable capability bundles that extend what the Craft AI coworker can do.** A skill is a self-describing directory containing a `SKILL.md` instruction file plus any mix of supporting assets — Python scripts, bash helpers, executables, schemas, fonts, fixture data, additional markdown — that the agent reads, executes, or references on demand when the skill's description matches the user's task.

Skills come from three sources:

- **Built-in skills** ship with the deploy and become available automatically when their dependencies are configured.
- **Admin-authored skills** are org-wide or scoped to specific groups / users.
- **User-authored skills** are private by default; their author can share them with specific users or with groups they belong to, and can request admin promotion to org-wide.

Both admins and regular users author skills the same way: by uploading a zip bundle. The bundle is validated synchronously; on success it's stored, indexed, and immediately reflected in every sandbox that should see it.

**Skills live in the sandbox at the user level, not per session.** Each user's sandbox keeps a directory of the skills they currently have access to; the backend keeps that directory in sync as access, bundles, and visibility change. Sessions running inside the sandbox see the live skill set — no need to wait for a new session to pick up a granted, replaced, or revoked skill.

The agent automatically gets every skill the running user has access to — no per-session picking, no manual selection. Visible surfaces are: an admin skills page (`/admin/skills`) for org-wide governance; a personal skills page (`/skills`) for any user to upload, share, and manage their own skills; and a read-only "what's available" panel inside Craft sessions.

The full engineering plan lives at [`../features/skills.md`](../features/skills.md). This document is the product spec.

---

## Requirements

### What a skill is, from the user's point of view

1. **A skill has a name, a description, and a body.** The description is what the agent reads when deciding whether to invoke the skill. The body is whatever instructions, scripts, or assets the skill needs.
2. **A skill is a directory, not a single file.** Bundles can include any mix of:
   - `SKILL.md` (required) and other markdown documentation.
   - Python files, bash scripts, Node scripts, or any other source the agent can `python …` / `bash …` from inside the sandbox.
   - Compiled executables and platform binaries that ship with the bundle.
   - Data files: JSON / YAML / XML schemas, CSV fixtures, prompt templates, font files, images, small ML model artifacts, etc.

   The runtime treats the bundle as an opaque directory the agent can read, execute from, and reference by path. There is no whitelist of allowed file types — only a per-file size cap (25 MiB) and a total bundle cap (100 MiB), both configurable. The existing `pptx` built-in is the canonical example: it ships `SKILL.md`, several supporting `*.md` guides, a `scripts/` directory of Python helpers, and template `.pptx` assets.
3. **Skills are reached by the agent, not invoked by the user.** Users don't pick skills from a menu before sending a prompt. The agent matches the user's intent against available skill descriptions and reaches for the right one.
4. **Skills are scoped to the user.** The set of skills the agent has access to in a session is exactly the set the running user has access to — no more, no less.

### Built-in skills

5. **Onyx ships a curated built-in set.** V1 includes presentation/deck (`pptx`), image generation (`image-generation`), and permissioned company search (`company-search`). New built-ins ship via deploy, not configuration.
6. **Built-ins auto-enable when their dependencies are met.** If `image-generation` requires a Gemini key and the deploy doesn't have one configured, the skill is unavailable. Admins don't toggle built-ins on/off — wiring up the dependency is the toggle.
7. **Admins can see which built-ins are available and why not.** The admin skills page shows each registered built-in with an Available / Unavailable badge and a one-line reason for the unavailable case (e.g. *"Requires GEMINI_API_KEY"*).

### Custom skills — authoring

8. **Anyone with Craft access can author a custom skill.** Both admins and regular users can create skills. The author's role bounds the maximum visibility they can set themselves (see #10).
9. **Custom skills are uploaded as zip bundles.** Authors prepare a bundle locally — `SKILL.md` at the root with frontmatter `name` + `description`, plus any supporting files (additional markdown, Python / bash / Node scripts, executables, schemas, fixtures, fonts, images, etc.) — and upload it through `/skills` (regular users) or `/admin/skills` (admins). Re-uploading replaces the bundle.

### Custom skills — visibility and sharing

10. **Custom skills have one of four visibility levels** (which can be combined except where noted):
    - **Private** — only the author has access. Default for newly-created skills.
    - **Specific users** — author picks one or more individual users in the org.
    - **Groups** — author picks one or more groups; combinable with user-share.
    - **Org-wide** — every user in the org has access. **Admin-only.** A regular user who wants org-wide reach uses the *Request org-wide* action; an admin promotes the skill.
11. **Group sharing is bounded by membership for non-admins.** A regular user can share their skill with groups they're a member of. They can't share into a group they don't belong to. Admins can share into any group.
12. **Authors manage their own skills; admins manage any skill.** A regular user's replace / share / disable / delete actions are scoped to skills they own. Admins see and can act on every custom skill in the org.
13. **Recipients of a shared skill don't get edit rights.** Sharing exposes read + materialize access, not write access. If a recipient wants to modify a shared skill, they fork it — download the bundle, edit locally, upload as their own. There is no in-product fork action in v1.

### Custom skills — lifecycle

14. **Bundles validate synchronously on upload.** Bundle errors (missing `SKILL.md`, slug collision with a built-in or another custom skill, path traversal, symlinks, oversize files, forbidden template files) surface inline with a clear reason. Nothing partially persists.
15. **Replacing the bundle is the canonical edit path.** Re-uploading a zip atomically replaces the prior bundle with a new fingerprint. Slug is immutable post-create; metadata (name, description, visibility, enabled state) is editable inline without re-uploading.
16. **Custom skills can be disabled and re-enabled.** Disabling immediately removes the skill from every sandbox that had it, without losing the bundle, metadata, or sharing settings. Useful as a kill-switch or as a way to take a skill out of circulation while reworking it. Authors can disable skills they own; admins can disable any.
17. **Custom skills can be soft-deleted.** Deleted skills disappear from the catalog and from every sandbox immediately. Authors can delete skills they own; admins can delete any (with a one-line reason that's surfaced to the original author on their `/skills` page).

### Admin governance over user-authored skills

18. **Admins can promote a user-authored skill to org-wide.** The skill keeps its author; visibility extends to the entire org. Admins can also demote and revert to the author's prior visibility setting.
19. **Admins can disable or delete any user-authored skill.** Used for compliance, content moderation, or removing skills whose authors have left the org. Admins supply a one-line reason that's shown to the original author on their `/skills` page.
20. **The admin skills page lists author and visibility for every custom skill.** Built-ins appear in their own section (read-only with availability badges); customs are listed regardless of author with author column, visibility summary, last-updated timestamp, and an action menu. Filterable by author, visibility, and enabled state.

### Materialization and discovery

21. **Skills live in the user's sandbox, independent of any session.** The sandbox keeps a directory of every skill the user currently has access to: available built-ins + org-wide customs + customs shared with the user (directly or via group) + customs the user authored. There is no per-session pinning and no skill picker.
22. **Skill access changes propagate immediately.** Granting access, revoking access, replacing a bundle, disabling, deleting, sharing, or unsharing — every change is reflected in the affected sandboxes as soon as the operation commits. Sessions in flight see the new state without restarting; the agent observes whatever's currently on disk the next time it lists or reads the skills directory.
23. **Bundles materialize into the sandbox verbatim.** Every file in the bundle (markdown, scripts, executables, data) lands at `.opencode/skills/<slug>/<original-path>` exactly as authored. File modes are preserved so executable bits survive — the agent can run a bundled `scripts/foo.sh` directly. Built-ins additionally support template rendering of their `SKILL.md.template`; custom skills do not.
24. **The agent finds skills via convention.** Skills live at a known path (`.opencode/skills/<slug>/SKILL.md`); the agent enumerates and reads them as needed. The session's `AGENTS.md` lists either every skill inline (when the count is small) or the built-ins inline plus a discovery instruction to enumerate the rest. Because the agent re-reads the directory on demand, additions during a session are discoverable; descriptions the agent has already pulled into context, however, persist until that context is cleared.

### Surfaces

25. **One admin page (`/admin/skills`) for org-wide governance.** Two sections: built-ins (read-only with availability) and customs (every custom skill in the org, regardless of author or visibility, with promote / disable / delete actions). The page is not nested under Craft because skills are a cross-surface primitive.
26. **One user page (`/skills`) for personal upload, sharing, and discovery.** Lists skills the user owns (with replace / share / disable / delete actions) and skills shared with them (read-only metadata). This page is where users upload their own skills.
27. **Users can see what skills are available in their session.** A read-only panel in the Craft session UI lists the names + descriptions of the skills the user actually has, sourced from the same access query as the materializer. This is for transparency; users don't act on it.

### Sandbox runtime

28. **Sandbox runtime requirements for executables are the bundle author's responsibility.** Skills run in the standard Craft sandbox image, which already includes Python, Node, bash, common CLI utilities, and LibreOffice. If a custom skill needs an interpreter or library not in the image, the author bundles a self-contained binary or installs the dependency at run time inside the sandbox (e.g. via `pip install`). Onyx does not provide a per-skill image-extension mechanism in v1.

### Cross-surface readiness

29. **Skills are a universal primitive, not a Craft-only feature.** Database tables, APIs, validation, and UI live in a non-Craft module. Craft is the v1 consumer; Personas, Chat, or other surfaces can adopt skills later without touching the universal layer.

---

## Out of scope (v1)

These are intentionally deferred. Listed with the reason so we can revisit when the constraint changes.

- **In-browser skill authoring.** The product surface is upload-and-manage; there is no markdown editor for `SKILL.md`, no file tree, no inline script editor, no drag-and-drop bundle assembler.
  *Why:* The bundle format and lifecycle should settle on uploaded zips before we invest in editing UX. Most early authors already keep their skill content in git or a local folder; a zip is a thin packaging step on top of that. Once we see how authors actually maintain skills, we'll know what to optimize for.
- **Per-session skill picking.** Users can't select a subset of their granted skills for a given session.
  *Why:* The agent's description-based matching is the selection mechanism. Adding a manual picker creates two systems for the same job and forces the user to predict what they'll need.
- **Versioning and rollback.** One bundle per skill — re-uploading replaces it. No version history, no "promote a draft" step, no rollback UI.
  *Why:* Keeping older bundles around is real complexity for a small benefit. Authors who want manual rollback can keep a copy locally and re-upload. Worth revisiting once skills get complex enough to justify the overhead.
- **Templating in custom skills.** Bundles containing `*.template` files are rejected at upload.
  *Why:* The render context shape is still evolving for built-ins. Locking it in publicly via custom uploads would create a compatibility surface we'd have to support indefinitely.
- **Formal skill review queue.** *Request org-wide* is a single flag — no comment threads, no rejection reasons, no draft-and-review workflow.
  *Why:* Most orgs will manage promotion lightly. We'll see how often promotions happen and how much friction the simple flag creates before building a queue.
- **In-product fork.** A recipient can't click "fork this skill" and immediately start editing their own copy.
  *Why:* The download-zip + edit-locally + re-upload path covers the same ground; an in-product fork is a small incremental UX win we can add once usage patterns are clearer.
- **Co-authoring / multi-user write access.** Each custom skill has one owner with edit rights; sharing exposes read access, not write access.
  *Why:* Concurrent editing with conflict resolution is real complexity. Authors who want to collaborate hand ownership to an admin or use the download-zip + re-upload pattern.
- **Ownership transfer (in-place).** No "transfer this skill to alice@" button.
  *Why:* The current admin override path (admin re-uploads the skill, ownership transfers to admin) covers the orphan-owner case. A first-class transfer action is a follow-up.
- **In-browser script execution / preview.** No way to test a skill from the management page; previewing skill behavior means starting a Craft session and prompting the agent.
  *Why:* Sandboxed code execution from the skills page is non-trivial infrastructure with a separate threat model. Out-of-scope until usage shows it's needed.
- **Signed / verified skills.** No cryptographic signing, no trusted-publisher badge, no chain-of-custody metadata.
  *Why:* All v1 skills come from the deploy, an admin, or a user inside the same tenant. The trust boundary is the tenant + the admin role.
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
- **Built-in toggling.** Admins can't disable a built-in for their org.
  *Why:* Availability is a function of the deploy's wiring. If you don't want `image-generation`, don't configure the provider. Adding a per-org override creates a state-vs-config divergence we don't want to debug.

---

## User flows

### Admin

#### A1. See what skills exist in the org

1. Admin opens `/admin/skills`.
2. Two sections:
   - **Built-in skills** — one row per registered built-in: name, description, availability badge. Unavailable rows show a one-line reason (e.g. *"Requires GEMINI_API_KEY"*).
   - **Custom skills** — one row per custom skill, regardless of author: name, description, **author** (admin or user name), **visibility** (Org-wide / Groups / Users / Private), last-updated timestamp, enabled toggle, action menu. Filterable by author, visibility, and enabled state.

#### A2. Make a built-in available

Implicit. Admin configures the underlying dependency (`GEMINI_API_KEY`, provider row, feature flag) elsewhere. The built-in flips to Available on the next page load.

#### A3. Upload a custom skill

1. Admin clicks **Upload skill** on `/admin/skills`.
2. Modal collects: zip, slug, name, description, visibility (Private / specific users / specific groups / Org-wide, combinable).
3. Admin selects a local zip with `SKILL.md` at the root + supporting files (markdown, scripts in any language, executables, schemas, fixtures, fonts, images).
4. Click **Upload**. Bundle validates synchronously.
   - **Validation fails** → modal shows the specific reason (e.g. *"`SKILL.md` is missing"*, *"Bundle contains `SKILL.md.template` (templates aren't supported in custom skills)"*). Nothing persists.
   - **Validation succeeds** → skill row created, modal closes, list refreshes.

#### A4. Replace a custom skill bundle

1. From `/admin/skills`, admin opens any custom skill.
2. Drag-and-drops a new zip onto the **Replace bundle** target (or uses a file picker).
3. Confirmation: *"This replaces the current bundle in every active sandbox immediately. The agent will pick up the new version the next time it reads from the skill's directory."*
4. Backend validates and atomically: stores new blob → updates skill row → updates affected sandboxes → deletes old blob. Updated `last-updated` and fingerprint shown.

If the admin wants no sandbox to use the skill while reworking it, they disable the skill before replacing and re-enable after the new bundle is in place.

#### A5. Edit metadata (without replacing the bundle)

Name, description, visibility, and enabled flag are editable inline on the detail page. Slug and bundle content are not — slug is the immutable identity; bundle changes go through Replace (A4).

#### A6. Configure visibility on any custom skill

1. Admin opens a custom skill (admin-authored or user-authored).
2. **Edit visibility** drawer: Org-wide toggle, Group multi-select (any group), User multi-select.
3. Save replaces grants atomically.

#### A7. Promote a user-authored skill to org-wide

1. Admin opens a user-authored skill (the list flags skills whose authors requested promotion).
2. Visibility section shows the author's setting.
3. Click **Promote to org-wide**. Optional one-line reason for the audit log.
4. Skill is now org-wide. Author retains ownership; their `/skills` page shows "Org-wide (promoted by admin)".
5. **Demote** reverts to the author's prior visibility — no extra prompt, the system remembers.

#### A8. Disable / delete any custom skill

- **Disable**: flips the enabled toggle off. Skill stays in the catalog; immediately removed from every sandbox that had it. If user-authored, the author sees the disabled status with the admin-supplied reason.
- **Soft-delete**: removes the skill from every sandbox and from the catalog. Same author notice.

#### A9. Inspect a skill's content

The detail page shows: slug, name, description, frontmatter, file tree (relative paths, sizes, "executable" badge for files with the executable bit set), total uncompressed size, sha256 fingerprint, author, last-updated timestamp, and visibility summary. Downloading the bundle as a zip is a v1 affordance for re-upload-as-rollback.

### Regular user

#### U1. Start a Craft session and use available skills

1. User opens Craft and starts a new session (interactively or via a scheduled trigger).
2. The session attaches to the user's sandbox, which already holds their full skill set (available built-ins + org-wide customs + customs shared with them directly or via group + customs they authored). If the sandbox is being created for the first time, the skills directory is provisioned as part of bring-up; otherwise the session just sees the live state.
3. User prompts the agent.
4. Agent matches against descriptions, reads `SKILL.md`, follows it.
5. User sees the result.

The user does not select a skill or see a picker.

#### U2. See what skills are available in a session

1. From the Craft session UI, open the **Skills available** panel.
2. Panel lists each available skill with name and description.
3. Read-only.

A future enhancement may distinguish source (built-in / shared / mine), but v1 just shows the flat list.

#### U3. Upload a custom skill

1. User opens `/skills` and clicks **Upload skill**.
2. Modal: zip picker, slug, name, description.
3. User selects a local zip with `SKILL.md` and any supporting files.
4. Backend validates synchronously (same rules as the admin path).
5. Skill defaults to **Private (only me)** and **enabled**. The skill appears in the user's sandbox immediately — any active session sees it the next time the agent reads the skills directory.

#### U4. Share an authored skill

1. From `/skills`, user opens a skill they own.
2. Click **Share**.
3. Visibility drawer with three controls:
   - User multi-select (any user in the org).
   - Group multi-select (only groups the user is a member of).
   - **Request org-wide** button — flags the skill for admin attention. Admins see the flag in `/admin/skills` and can promote (A7).
4. Save. Grants update atomically. Recipients' sandboxes pick up the skill immediately; their next agent action sees it.

#### U5. Replace an authored skill bundle

1. From `/skills`, user opens a skill they own.
2. Drag-and-drops a new zip (or uses the file picker).
3. Confirmation: same as A4 — the new bundle replaces the old in every active sandbox immediately.
4. Backend validates and atomically replaces. Updated `last-updated` and fingerprint shown.

#### U6. Edit authored skill metadata

Name, description, visibility, and enabled flag are editable inline on the detail page. Slug is immutable; bundle changes go through Replace (U5).

#### U7. Disable / delete an authored skill

- **Disable**: removed from every sandbox immediately; remains in the user's `/skills` so they can re-enable later.
- **Delete** (soft): removed from every sandbox and from the user's catalog. Recipients lose access immediately.

#### U8. Use a skill in a scheduled trigger

Same as U1, but the session is started by the trigger system. The trigger attaches to the trigger owner's sandbox, so it sees that user's live skill set. The trigger config does not carry per-skill toggles in v1.

#### U9. Encounter an admin action against a user-authored skill

If an admin disables, deletes, or demotes a user's skill, the author sees a notice on their `/skills` page (e.g. *"Disabled by admin: <reason>"*). The author can edit / re-enable a disabled skill if appropriate; deleted skills are gone from the catalog.

### Cross-cutting

#### X1. A built-in suddenly becomes unavailable

If the dependency that powered a built-in is removed (key unset, provider row deleted), the built-in flips to Unavailable and is removed from every sandbox immediately. The agent stops being able to invoke it on its next directory read.

#### X2. A user's group membership changes

Adding the user to a group that's granted a custom skill puts the skill in their sandbox immediately. Removing them takes it out immediately. Active sessions see the change on the agent's next read of the skills directory.

#### X3. A bundle is replaced while a user has a session open

Every active sandbox that had the prior bundle is updated in place. The agent picks up the new version the next time it reads from the skill's directory. Already-running scripts inside the agent finish against whatever was on disk when they started; new invocations see the new bundle.

If the author wants to be sure no agent reaches for the skill mid-replace, they disable the skill before replacing and re-enable after.

#### X4. A user-authored skill's owner leaves the org

Skill stays in the catalog with its existing visibility and remains usable by recipients. Admins can disable / delete it, or take ownership by re-uploading the bundle. In v1 there's no first-class transfer button — the admin re-upload path covers this.

#### X5. An admin promotes a user skill, then the user keeps editing it

The user can keep replacing — uploads replace the bundle in every sandbox immediately and the skill remains org-wide. The admin can demote at any time; recipients lose access on demote. There's no "frozen post-promotion" state in v1.

#### X6. The agent has already pulled a skill's `SKILL.md` into context, then the bundle changes

The skill's files on disk are updated; the agent's in-memory copy of the prior `SKILL.md` (if any) persists until the conversation context is cleared. This is a property of how LLMs handle context, not a sync gap — the next read against `.opencode/skills/<slug>/SKILL.md` returns the new content. For most skills the agent re-reads on demand, so the practical impact is small.

---

## Open questions

These do not block v1 but are worth flagging for product follow-up:

1. **Should users see *why* a skill isn't in their session?** ("This skill exists but you don't have access.") V1 hides anything they're not granted — by design — but it can confuse users when they hear about a skill from a colleague.
2. **Should admins see effective-skill-set previews?** "Show me the skills user X currently has in their sandbox." Cheaper than asking the user.
3. **Should the user-facing skills panel distinguish source?** Built-in vs shared vs "I authored this." Probably yes, low cost.
4. **Should we surface a skill-author audit trail in the admin UI?** "Last replaced by alice@ on 2026-04-12, fingerprint abc123." Probably yes, low cost.
5. **How prominently should *Request org-wide* surface to admins?** Too quiet and authors won't get traction; too loud and admins drown in requests. V1 ships a simple flag and we tune from there.
6. **Should recipients of a shared skill be able to fork in-product?** V1 covers it via download-zip + create-new; first-class fork is a small UX win.

---

## Future enhancements

Things explicitly considered for a future version, captured here so they don't get rediscovered every quarter:

- **In-browser skill authoring.** A first-class authoring surface inside Onyx — markdown editor for `SKILL.md` with frontmatter helpers, file tree for the bundle, inline editing for text files (scripts, additional markdown, schemas), drag-and-drop for binary assets, executable-bit toggle, pre-save preview. Same validator, same artifact, same lifecycle as today's zip upload — just a different production path. Worth doing once we see how authors actually maintain skills and what friction the upload-only flow creates.
- **In-browser preview / test run.** Spin up an ephemeral Craft session to test a skill from the skills page without going to the main Craft surface.
- **In-product fork.** "Make this my own" button on a shared skill that copies the bundle into the user's catalog as a private skill they can edit.
- **Ownership transfer.** First-class "transfer to user X" without re-uploading.
- **Skill review queue.** Comment threads, rejection reasons, and a draft-review-promote workflow on top of *Request org-wide*.
- **Versioning / rollback.** Keep the prior N bundles; let authors and admins roll back without re-uploading.
- **Persona / Chat consumption.** Wire skills into other Onyx surfaces — the universal primitive is already shaped for this.
