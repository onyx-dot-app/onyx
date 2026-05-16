> **Archived.** Superseded by `../skills-requirements.md`. The "what is a skill / built-in vs custom / V1 scope" content here is restated cleanly there. Kept for historical context only — do not use as an implementation reference.

# Skills System

## Objective

Introduce a **first-class, Onyx-wide Skills primitive** — not a Craft-only feature. The data models, admin/user endpoints, validation, file-store integration, and rendering helpers all live outside `features/build/` and use neutral names (`skill`, `/api/admin/skills`). Craft is the **first consumer** of this primitive — it adds a sandbox-materialization adapter — but Personas, Chat, and any future Onyx surface can adopt the same primitive without touching the universal layer.

Within that universal system, skills get **two intentionally different paths**:

- **Built-in skills** ship with the deploy as on-disk directories in the Onyx repo. They support **template rendering** at materialization (e.g. project #1's `company_search` injects the user's accessible sources into its `SKILL.md`). Each built-in declares its own **availability check** at registration — a function that returns whether the deployment can actually run the skill (e.g. image-generation requires a configured provider). Admins do not get a per-org disable toggle: a built-in is either available because the deployment is wired up for it, or it's not. They move with the deploy — no admin upload path.
- **Custom skills** are uploaded by admins as plain zip bundles. They live in Postgres + the existing `FileStore`, are share-able per group/user, and are written into the consumer environment **verbatim** — no template rendering. There's a single bundle per custom skill: re-uploading replaces it.

**No per-session pinning.** Each consumer materializes the full set of available built-ins plus every custom skill the running user has access to via grants. There is no user-facing "pick which skills this session uses" picker. If the total skill count exceeds a threshold (default 15, configurable), the agent's `AGENTS.md` lists only the built-ins inline and adds a one-line **skill-discovery instruction** that tells the agent to enumerate `.opencode/skills/` and read individual `SKILL.md` files on demand. Built-ins are always listed inline because they're the small, stable set the agent is expected to reach for first.

The bar for V1: an admin uses `/api/admin/skills` to upload custom skills; users with appropriate grants automatically get those skills materialized into their Craft sessions; the agent finds built-ins under `.opencode/skills/` and discovers customs from the same directory when needed. The same `/api/admin/skills` page later powers Persona/Chat consumers without schema changes.

## Issues to Address

1. **Skills are baked into the sandbox image.** `backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/` is `COPY`-ed into the image and symlinked into every session. Adding/changing a skill requires a full image rebuild. The on-disk source stays (it's the canonical built-in location for now) but the in-image symlink path goes away in favor of a per-session materialization step.
2. **No access control on custom skills.** Every session that runs the image gets every skill. Custom skills need full per-group / per-user grants. (Built-ins don't need this — see issue #3.)
3. **No path for customer-supplied skills.** No admin upload, no validation, no storage today. The custom-skill side of this system is the path.
4. **Built-in availability is implicit.** Today, every built-in is "available" because they're all in the image. With Craft heading toward more skills (e.g. image-generation, which needs a provider key) we need a per-skill availability check so a deployment that doesn't have the provider configured doesn't list the skill in the agent's instructions.
5. **No per-session rendered content.** Project #1's `company_search` needs `SKILL.md.template` substitution. The current flat-symlink materialization can't do that. Built-in materialization needs a render step.
6. **No re-use across Onyx surfaces.** Building this as `craft_*` tables and `/api/build/skills` would force a second skills system the moment Personas or Chat want skills. The universal layer ships V1 even though only Craft consumes it.
7. **Listing every skill in AGENTS.md doesn't scale.** Three skills today, plausibly twenty soon (built-ins + customer custom skills). Pasting all of them inline blows the agent's context window for no reason — it usually only needs one or two per session. We need a list-the-essentials-and-let-the-agent-discover-the-rest pattern for the long-tail.

V1: a universal skill primitive (DB + APIs + materializer + bundle validator) plus a Craft consumer adapter (one join table, one wire-up to the sandbox setup path).

## Important Notes

- **Two-layer architecture, named to match.** The universal layer lives under `backend/onyx/skills/` (new top-level module) and `backend/onyx/db/skill.py`. Tables are `skill`, `skill__user_group`, `skill__user`. APIs are `/api/admin/skills/...` and `/api/skills`. The Craft-consumer layer lives under `backend/onyx/server/features/build/skills/` and adds the sandbox-write adapter (no consumer-side join table — the session has no per-session pin set). No "craft" or "build" appears in any universal-layer name.
- **Universal layer is intentionally a primitive, not a runtime.** It defines what a skill *is* (a slug, frontmatter metadata, a directory of files), where its bytes live (on disk for built-ins, file store for customs), and how to materialize a chosen set into a destination path. It does not know what a "session" is, what a "sandbox" is, or what `.opencode/skills` is. Each consumer translates its own selection state into the materializer's input and chooses the destination path. That separation is what lets Personas or Chat adopt this without forking.
- **OpenCode/Codex skill shape stays identical.** Disk layout the agent sees doesn't change — `.opencode/skills/<slug>/SKILL.md` plus optional `scripts/` and supporting `*.md` files. YAML frontmatter (`name`, `description`) is what OpenCode and Codex skill systems already read. We are *not* defining a new skill format; we are defining a *distribution and selection* layer around the existing format.
- **Built-ins are sourced from disk, every deploy.** No seeder, no DB rows, no hash tracking, no per-org state. Built-ins are registered at app boot as `(slug, source_dir, is_available)` triples — the build feature registers its own at `backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/`. The `is_available(db_session) -> bool` callable is consulted at materialization time; the skill is included only if it returns True. Admins do not get a per-org disable toggle: a built-in is available because the deployment has the dependencies it needs (provider key, feature flag, ...), or it isn't.
- **Built-ins support `SKILL.md.template`.** If a built-in's directory contains `SKILL.md.template`, materialization renders it through the existing `agent_instructions.py` placeholder logic against a `SkillRenderContext`. If only `SKILL.md` is present, it's written verbatim. This is the hook project #1's `company_search` skill needs.
- **Custom skills are write-verbatim, plain `SKILL.md` only.** Validation rejects bundles containing any `*.template` file. Templating is reserved for built-ins because the `SkillRenderContext` shape will evolve and we don't want admin-uploaded skills referencing fields we're still designing.
- **Custom bundles are zips stored in the existing `FileStore`.** Same abstraction as sandbox snapshots and user files (`backend/onyx/file_store/file_store.py`). New `FileOrigin.SKILL_BUNDLE` value (no `CRAFT_` / `BUILD_` prefix). One blob per skill, addressed by file id and fingerprinted by sha256. Re-uploading a skill replaces the blob (and the prior blob is deleted in the same request).
- **No skill versioning in V1.** A custom skill is one row. The bundle attaches directly to the row. Re-upload = replace. Scheduled triggers see whatever bundle is current at run time — same model as built-ins, which always reflect the running deploy. If a customer needs rollback, they keep the previous zip locally and re-upload it. Admins can opt to disable a skill before re-uploading if they want to freeze in-progress sessions from picking up the new bundle.
- **No in-browser skill authoring in V1** (per main plan). Custom skills are uploaded as a zip. The admin UI lets you upload, replace, share, enable/disable; it does not let you edit a `SKILL.md` in a textarea.
- **Validation runs synchronously in the upload request.** Read bytes → validate in memory → compute sha256 → save to file store → insert/update `skill` row, in that order, in one request. Bundles are size-capped at 100 MiB, so the full pass is sub-second. Failure → `OnyxError(INVALID_REQUEST, ...)` with reason; nothing persists. Validation rules: `SKILL.md` exists at the root, frontmatter parses with `name` + `description`, `name` matches the bundle's slug, **no `SKILL.md.template`**, no path traversal entries, no symlinks, no individual file > 25 MiB, total uncompressed size under 100 MiB.
- **Skills are not executed by the backend.** Execution happens inside whatever consumer environment runs them (the Craft sandbox, in V1).
- **Every session gets every skill the user has access to, materialized.** Available built-ins (per their availability checks) plus the union of custom skills granted to the user. There is no user-side pinning UI and no per-session subset selection — the user implicitly "has" what they have access to. Custom-skill grants (`is_public` + groups + direct user grants) are the only filter on customs; built-in availability checks are the only filter on built-ins.
- **AGENTS.md skill listing is bounded.** The materializer writes a `.skills_manifest.json` into the materialized skills directory listing built-in vs custom slugs separately. The agent-instructions generator reads it: if total count ≤ `BUILD_SKILLS_INLINE_LIMIT` (default 15), it inlines descriptions for every skill in `{{AVAILABLE_SKILLS_SECTION}}`. If total count exceeds the limit, it inlines only built-ins and appends a discovery instruction telling the agent to `ls .opencode/skills/` and read individual `SKILL.md` files for any custom skill names it sees that look relevant. Built-ins are the always-listed core because they're a small, stable set; customs are the long tail the agent can browse on demand.
- **Skill discovery is plain shell.** The agent already has `ls`, `cat`, `find`. We don't ship a custom discovery tool; we just instruct the agent on the convention: `ls .opencode/skills/` lists slugs, `cat .opencode/skills/<slug>/SKILL.md` reads the contract.
- **Materialization is fresh per consumer "run."** For Craft, that's per session. The materializer takes a destination path on the local file system; consumers handle delivery to remote environments (e.g. tarball-into-pod for Kubernetes).
- **Reserved built-in slugs are unavailable for custom uploads.** The registry is the source of truth — at upload time we union all registered built-in slugs and reject collisions.
- **Out of scope for V1:** in-browser skill editor, marketplace/registry, signed skills, skill telemetry, dependency declarations between skills, per-skill secrets (project #4 interception), templating for custom skills, per-session skill picking, non-Craft consumers (Persona/Chat skill attachment is a future project — V1 just makes the primitive ready).

## Approaches Considered

### A. Build it as `craft_*` / `/api/build/skills` and refactor later (rejected)

Stand up the data model and APIs under the build feature now; rename and split when the second consumer arrives.

**Why rejected:** Renaming database tables across a deployed product is a real cost (Alembic migrations, env-var/config audits, downstream tooling). Splitting an API surface that customers integrate against is worse. The universal-vs-consumer split is **structural**, not aesthetic — the cost of getting it right on day one is one extra module path and one extra import; the cost of getting it wrong is a migration we don't want to run. We also already know V2 wants Personas to attach skills, which means a second consumer is on the roadmap.

### B. Keep skills baked into the image, add "extension" skills via volume mount (rejected)

Leave in-image skills as-is; add a per-tenant volume admins drop bundles into; sandbox merges the two directories.

**Why rejected:** No versioning (volumes are mutable). Forces a shared filesystem story for the Kubernetes backend. The docker-compose backend (project #2) would need a parallel volume convention. Doesn't generalize beyond the Craft sandbox.

### C. Built-ins and customs share one DB-backed system with a startup seeder (rejected)

Earlier draft of this plan: zip every on-disk built-in, hash it, upload to the file store, create matching `skill` + `skill_version` rows on every boot.

**Why rejected:** The seeder is real complexity for no real benefit. Built-ins move with the deploy by definition — there's nothing useful you can do with a "built-in version 1.4.7 from two deploys ago" that you can't do with `git checkout`. Hash-based version churn fills the file store with copies of skills nobody can roll back to. Once we admit built-ins don't need versioning, we also drop most of the row machinery (immutable bundles, latest_version_id pointers, orphaned-blob cleanup) for them.

### D. Inline skill bodies in Postgres rows (rejected)

Store `SKILL.md` and helpers as `text` columns.

**Why rejected:** Skills carry binary data (XML schemas, scripts, fonts) — text columns aren't the right primitive. Postgres rows over a few MB stop being friendly to inspect or replicate. The file store already exists.

### E. Pull skills from a remote registry at session start (rejected)

Backend calls a hosted "Onyx Skills" service for bundles at session setup.

**Why rejected:** External dependency for self-hosted, network on the critical path, new auth/trust story to design. The file store already gives us durable per-tenant storage.

### F. Universal skill primitive, automatic per-user materialization, built-ins on disk + customs in DB+filestore (winner)

`backend/onyx/skills/` ships the universal layer: `skill` table (one row, one bundle), `skill__user_group` / `skill__user` grants, `/api/admin/skills` + `/api/skills`, and a `materialize_skills(...)` helper. Built-ins are registered at boot as `(slug, source_dir, is_available)` triples. Custom uploads go through file-store + synchronous validation. Each session gets every available built-in plus every custom skill its user has access to. The agent's instructions inline either the full list or just the built-ins (with a discovery line) depending on count.

**Why this wins:**

- **Models the universal/consumer split cleanly.** The skill primitive is a noun the whole product can reach for.
- **Models the built-in/custom difference honestly.** Built-ins ship with the deploy and need templating + availability checks; customs are uploaded by admins and gated by grants.
- **Smallest plausible Craft adapter.** One helper call from the existing sandbox setup path — no consumer-side join table, no pin/list endpoints, no skill-picker UI. The materializer doesn't know what Craft is.
- **One materialization function per skill.** Heterogeneous skill lists (built-in slugs + custom skill rows) resolve to a single typed list the materializer walks. Both sandbox backends call this helper the same way.
- **Smallest plausible custom-skill validator.** No template placeholders to track in `manifest_metadata`, no `SkillRenderContext` shape check at upload. The validator is "is this a sane zip with a SKILL.md."
- **No version machinery.** No `skill_version` rows, no `latest_version_id` pointers, no promote endpoint, no version history view. Replace the bundle and that's the bundle.
- **No per-session selection state.** Nothing for the user to manage. Nothing to migrate when grants change. Skill access changes are picked up on the next session.

## Key Design Decisions

1. **Universal layer is consumer-blind.** `backend/onyx/skills/` knows nothing about `BuildSession`, sandboxes, or `.opencode/skills`. Its public API is "given a destination path and a user, resolve and write all the skills they have access to." Consumers choose the destination path and pass the user.
2. **Built-ins are a registry of `(slug, source_dir, is_available)` triples.** Registered at app boot. The registry exposes `list_available_for(db_session) -> list[BuiltinSkill]` which evaluates each `is_available` lazily. The build feature owns its own registration module (`backend/onyx/server/features/build/skills/builtins_registration.py`) that wires up Craft's built-ins. Other features add their own registration modules.
3. **No DB rows for built-in state.** Admins do not configure built-ins per-org. Whether a built-in is available is determined entirely by code — its `is_available` callable inspects whatever it needs (env vars, configured providers, feature flags, sub-feature DB rows). This trades configurability for simplicity: there's no per-tenant "we don't want pptx" toggle, but also no admin surface to reason about, no state-row-vs-registry-mismatch failure mode, and no migration when we add or remove built-ins.
4. **Built-ins ship `SKILL.md.template` to opt into rendering.** The materializer checks for `SKILL.md.template` in the source directory; if present, renders against `SkillRenderContext` and writes `SKILL.md`. Otherwise copies the existing `SKILL.md` verbatim. Other files always copy verbatim.
5. **Custom skills cannot ship templates.** Validation rejects bundles containing any `*.template` file.
6. **Custom skill identity = `(tenant, slug)`.** Slug is the directory name under `.opencode/skills/` and the value of `name` in the frontmatter. Lowercase, hyphens, ≤ 64 chars, regex-validated. Reserved slugs (the union of all registered built-ins) are rejected at upload time. Two custom skills in the same tenant cannot share a slug.
7. **One bundle per custom skill.** The bundle's `file_store` id and sha256 live directly on the `skill` row. Re-uploading replaces the bundle: the old blob is deleted in the same request as the new one is saved. No version rows, no `latest_version_id` pointer, no "promote" step.
8. **Bundle blobs live under `FileOrigin.SKILL_BUNDLE`.** Same shape as sandbox snapshots. File ids are random UUIDs (not slugs).
9. **Access control mirrors Persona, custom skills only.** Custom skills get `is_public` (org-wide) plus `skill__user_group` and `skill__user` join tables, queried with the same pattern as `fetch_persona_by_id_for_user` (`backend/onyx/db/persona.py:81`). Built-ins have no org/group access control — they're available to whoever can use the consuming feature, subject to their own `is_available` callable.
10. **No per-session pinning.** Sessions don't carry a skills selection. The materializer is called with a `(user, db_session)` pair; it returns/writes the union of available built-ins and access-granted customs. Skill grant changes propagate at the next session start. There's no consumer-side join table — the build adapter just calls the materializer at session setup.
11. **AGENTS.md skill listing is count-bounded.** The materializer writes a `.skills_manifest.json` listing built-in vs custom slugs. The agent-instructions generator inlines all skills if total ≤ `BUILD_SKILLS_INLINE_LIMIT` (default 15); otherwise inlines only built-ins and adds a one-line discovery instruction (`ls .opencode/skills/ | cat each SKILL.md as needed`). Built-ins are always inline because they're the small stable core.
12. **`materialize_skills(dest, user, db_session, render_context)` is the single materialization function.** Internally it resolves the user's skill set, walks built-ins (reading from disk + rendering templates) and customs (downloading from file store + unzipping), writes the manifest, and returns. Both Craft sandbox backends call it the same way.
13. **`SkillRenderContext` is extensible.** Pydantic model with well-known optional fields plus an `extra: dict[str, str]` bag for consumer-specific keys. Unknown placeholders in templates are left in place and logged.
14. **Bundle cleanup is in-line on replace; the orphan task is just a safety net.** When admin re-uploads, the old blob is deleted as part of the same DB transaction that updates the skill row. When a skill is hard-deleted, its blob is deleted immediately. The weekly Celery beat task is a defensive sweep for blobs left over from interrupted requests.
15. **Validation runs synchronously in the upload request.** Read bytes → validate in memory → compute sha256 → save to file store → upsert `skill` row → delete prior blob (on replace), in that order, in one request. Validator failure short-circuits before anything persists.

## Architecture

```
                                Universal layer (backend/onyx/skills/)
                                ──────────────────────────────────────
                                ┌──────────────────────────────────────────┐
                                │  BuiltinSkillRegistry (in-memory)        │
                                │  ├─ register(slug, dir, is_available)    │
                                │  └─ list_available_for(db_session)       │
                                │                                          │
                                │  DB (backend/onyx/db/skill.py)           │
                                │  ├─ skill (one bundle per row)           │
                                │  └─ skill__user_group, skill__user       │
                                │                                          │
                                │  APIs                                    │
                                │  ├─ /api/admin/skills/... (CRUD)         │
                                │  └─ /api/skills (read-only user list)    │
                                │                                          │
                                │  Helpers                                 │
                                │  ├─ validate_custom_bundle(zip_bytes)    │
                                │  │   (called synchronously on upload)    │
                                │  └─ materialize_skills(dest, user, db,   │
                                │                         render_ctx)      │
                                │       └─ writes .skills_manifest.json    │
                                └──────────────────────────────────────────┘
                                                    ▲
                                                    │ uses
                                                    │
                            ┌───────────────────────┴────────────────────────┐
                            │                                                │
              ┌─────────────┴────────────┐                  ┌────────────────┴─────────────┐
              │  Craft consumer (V1)     │                  │  Future consumers (post-V1)   │
              │  features/build/skills/  │                  │  Persona, Chat, ...           │
              │                          │                  │                               │
              │  builtins_registration   │                  │  Their own builtins reg.      │
              │   (registers Craft's     │                  │   if they ship built-ins      │
              │    built-ins at boot)    │                  │                               │
              │                          │                  │  Their own materialize-       │
              │  Sandbox materialization │                  │   destination logic           │
              │   (writes into pod /     │                  │                               │
              │    docker volume)        │                  │   May add a join table iff    │
              │                          │                  │    explicit attachment is     │
              │   No pin table, no       │                  │    needed for their UX        │
              │    pin endpoints, no     │                  │                               │
              │    picker UI             │                  │                               │
              └──────────────────────────┘                  └───────────────────────────────┘
```

Materialization sequence (per Craft session start):

```
SessionManager.setup_session
  └─ skills.materialize_skills(staging_dir, user, db_session, render_context)
        ├─ resolve:
        │     ├─ available_builtins = registry.list_available_for(db_session)
        │     └─ accessible_customs = list_skills_for_user(user, db_session)
        ├─ for each available built-in:
        │     ├─ copy source_dir → staging_dir/<slug>/
        │     └─ if has_template: render SKILL.md.template → SKILL.md
        ├─ for each accessible custom:
        │     ├─ file_store.read_file(bundle_file_id) → zip
        │     └─ unzip into staging_dir/<slug>/
        └─ write staging_dir/.skills_manifest.json {builtin: [...], custom: [...]}
  └─ build adapter copies/streams staging_dir → sandbox/.opencode/skills/
  └─ AGENTS.md generation reads .skills_manifest.json:
        ├─ if total ≤ BUILD_SKILLS_INLINE_LIMIT: inline all skills
        └─ else: inline only built-ins + add discovery instruction
```

The Kubernetes path (`KubernetesSandboxManager._setup_session_workspace`, around `kubernetes_sandbox_manager.py:1300`) wraps `staging_dir` in a tarball and streams it into the pod via the existing `kubectl exec` mechanism. The local / docker-compose path copies into the mounted workspace. Either way, the universal `materialize_skills` call produces a directory; what to do with that directory is the consumer's call.

## Relevant Files / Onyx Subsystems

**To modify (existing):**

- `backend/onyx/db/models.py` — add `Skill`, `Skill__UserGroup`, `Skill__User` near the other top-level features. No build-session-specific table — Craft sessions don't store pinned skills.
- `backend/onyx/configs/constants.py:372` — add `FileOrigin.SKILL_BUNDLE`.
- `backend/onyx/server/features/build/sandbox/manager/directory_manager.py:321` — replace `setup_skills` with a call into the universal `materialize_skills(...)`. Drop the `_skills_path` constructor arg.
- `backend/onyx/server/features/build/sandbox/kubernetes/kubernetes_sandbox_manager.py:1338` — replace the `ln -sf /workspace/skills` block with code that builds a staging tarball from `materialize_skills`'s output and streams it into the pod.
- `backend/onyx/server/features/build/sandbox/util/agent_instructions.py:267` — rewrite `build_skills_section` to read `.skills_manifest.json` from the materialized skills dir and apply the threshold logic: inline all skills under the limit, otherwise inline only built-ins and append the discovery instruction. Drop `_skills_cache` — skills are per-session now.
- `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile:99` — delete `COPY skills/` and `mkdir -p /workspace/skills`. The image stops shipping skills; built-ins are read at runtime from the api_server / Celery worker host file system.
- `backend/onyx/main.py` (or equivalent boot entry point) — add a call from the build feature's init module that registers the build built-in directory with `BuiltinSkillRegistry`.

**New files (universal layer):**

- `backend/onyx/skills/__init__.py` — public API: `materialize_skills`, `resolve_skills`, `validate_custom_bundle`, `BuiltinSkillRegistry`, `SkillRenderContext`, `ResolvedSkill`, `BuiltinSkillRef`.
- `backend/onyx/skills/registry.py` — `BuiltinSkillRegistry` singleton; `register(slug: str, source_dir: Path, is_available: Callable[[Session], bool], unavailable_reason: str | None = None)`, `list_available_for(db_session) -> list[BuiltinSkill]`, `evaluate_for_admin(db_session) -> list[BuiltinSkillAvailability]` (returns each registered slug + bool + reason, used by the admin GET endpoint), `read_metadata(slug) -> BuiltinMetadata | None`. In-memory; rebuilt at boot.
- `backend/onyx/skills/bundle.py` — zip helpers: `validate_custom_bundle(zip_bytes) -> ManifestMetadata | InvalidBundleError`, `compute_bundle_sha256(zip_bytes)`. Deterministic checks.
- `backend/onyx/skills/materialize.py` — `materialize_skills(...)`, `SkillRenderContext` (Pydantic), the manifest writer. The render step delegates to a small `_render_template_placeholders` helper migrated from `agent_instructions.py` so it can be reused outside the build feature.
- `backend/onyx/db/skill.py` — DB ops: `list_skills_for_user`, `fetch_skill_for_user`, `create_skill`, `replace_skill_bundle`, `delete_skill`. Mirrors `backend/onyx/db/persona.py` patterns.
- `backend/onyx/server/features/skills/api.py` — universal admin + user routers (mounted at `/api/admin/skills` and `/api/skills`).
- `backend/onyx/background/celery/tasks/skills/tasks.py` — weekly orphan-bundle sweep. `@shared_task` with `expires=`. Defensive sweep for `FileOrigin.SKILL_BUNDLE` blobs that no `skill.bundle_file_id` references — picks up the rare case where a request crashed between file-store save and DB write. (No async validation task — validation is synchronous on upload. No reference-counting across consumers either, since there's only one bundle per skill and it's already keyed by skill id.)
- `backend/alembic/versions/<new>.py` — schema migration creating the universal tables only (no consumer join table in V1).
- `web/src/app/admin/skills/page.tsx` (and supporting components) — admin UI at the universal route, not under `/admin/build`.

**New files (Craft consumer adapter):**

- `backend/onyx/server/features/build/skills/builtins_registration.py` — registers Craft's built-ins with `BuiltinSkillRegistry` at boot. One `register(...)` call per built-in slug, including the `is_available` callable.
- `backend/onyx/server/features/build/skills/materialize_adapter.py` — thin wrapper called from sandbox setup; calls `skills.materialize_skills(...)` with the running session's user and a `SkillRenderContext` populated from session state, then hands the staging directory to the sandbox manager for delivery.
- (No `/api/build/sessions/{id}/skills` endpoints — sessions don't carry pin state. No skill-picker UI in Craft.)

**To leave alone (just calls, not changes):**

- `backend/onyx/file_store/file_store.py` — `save_file`, `read_file`, `delete_file` used as-is.
- `backend/onyx/db/persona.py:81` — read-only reference for the access-control query pattern; we mirror it for `Skill`.

## Data Model

```python
# backend/onyx/db/models.py

# ── Universal layer ─────────────────────────────────────────────────────────

# Note: there is no `builtin_skill_state` table. Built-in availability is
# determined entirely by the per-built-in `is_available(db_session)` callable
# registered with BuiltinSkillRegistry at boot.

class Skill(Base):
    """A custom (admin-uploaded) skill. One bundle per skill — re-upload replaces."""
    __tablename__ = "skill"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)  # unique per tenant
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Bundle (lives directly on the skill row; replaced on re-upload).
    bundle_file_id: Mapped[str] = mapped_column(String, nullable=False)  # file_store id
    bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_metadata: Mapped[dict[str, Any]] = mapped_column(PGJSONB, nullable=False)

    owner_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    groups: Mapped[list["UserGroup"]] = relationship(
        "UserGroup", secondary="skill__user_group", viewonly=True,
    )
    users: Mapped[list["User"]] = relationship(
        "User", secondary="skill__user", viewonly=True,
    )

    __table_args__ = (Index("ux_skill_slug", "slug", unique=True),)


class Skill__UserGroup(Base):
    __tablename__ = "skill__user_group"
    skill_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("skill.id", ondelete="CASCADE"), primary_key=True,
    )
    user_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user_group.id", ondelete="CASCADE"), primary_key=True,
    )


class Skill__User(Base):
    __tablename__ = "skill__user"
    skill_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("skill.id", ondelete="CASCADE"), primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True,
    )

# ── Craft consumer ─────────────────────────────────────────────────────────
# No consumer-specific table. The Craft sandbox setup path calls
# materialize_skills(...) at session start; there is no per-session skill
# selection state to persist.
```

Notes:

- Universal table names (`skill`, `skill__user_group`, `skill__user`) deliberately have no consumer prefix — adding a Persona consumer in V2 that wants explicit attachment is "add `persona_skill`" with no migration of these tables.
- `skill.bundle_file_id`, `bundle_sha256`, and `manifest_metadata` are `NOT NULL` — a skill always has a bundle. The first upload is the create; subsequent uploads replace.
- Soft-delete (`deleted=true`) is the standard path. Hard delete is only used after admins confirm no consumer references the skill (currently trivial since no consumer stores references; future consumers with their own join tables will need the same protection).
- Future consumers that want explicit attachment add their own join table (e.g. `persona_skill (persona_id, builtin_slug, custom_skill_id, ...)`). V1 Craft does not.

## API Spec

All endpoints raise `OnyxError`, return typed FastAPI models (no `response_model=`). Admin endpoints are gated by the existing admin dependency.

### Universal — `/api/admin/skills` (admin)

**`GET /api/admin/skills`** → `SkillsAdminList` containing `builtin: list[BuiltinSkillAdmin]` and `custom: list[CustomSkillAdmin]`. Built-ins come from the registry; each entry includes its slug, description, and a computed `available: bool` (the result of evaluating `is_available` against the current DB session) plus a one-line `unavailable_reason` if it returned False. Customs come from DB.

**`POST /api/admin/skills/custom`** (multipart: `bundle: UploadFile`, `slug: str`, `name: str`, `description: str`) → `CustomSkill`.
- Validates the bundle synchronously: zip well-formed, `SKILL.md` present, frontmatter ok, slug match, no `*.template`, no path traversal, size limits. Failure → `OnyxError(INVALID_REQUEST, ...)` with reason; nothing persists.
- Rejects if `slug` collides with a registered built-in, an existing custom skill, or fails the slug regex.
- On success: saves the bundle to the file store, inserts the `skill` row referencing it, returns the row.

**`PUT /api/admin/skills/custom/{skill_id}/bundle`** (multipart: `bundle: UploadFile`) → `CustomSkill`. Same synchronous validate-and-persist flow. The new bundle's `name` (frontmatter) must match the existing slug — slug cannot change via re-upload. On success: saves the new blob, updates the `skill` row's `bundle_file_id` / `bundle_sha256` / `manifest_metadata` / `updated_at`, deletes the old blob from the file store, all in one transaction.

**`PATCH /api/admin/skills/custom/{skill_id}`** body: `CustomSkillEdit` (name, description, is_public, enabled). Cannot mutate slug or bundle. Use the bundle endpoint to replace bundle.

**`PUT /api/admin/skills/custom/{skill_id}/grants`** body: `{group_ids: list[int], user_ids: list[UUID]}`. Replaces grants atomically.

**`DELETE /api/admin/skills/custom/{skill_id}`** → soft delete (`deleted=true`).

There is **no** built-in toggle endpoint. Built-ins are not configurable per-org; they're available iff their `is_available` callable returns True for the deployment's state.

### Universal — `/api/skills` (user, read-only)

**`GET /api/skills`** → `SkillsForUser` (`builtin`, `custom`) of skills the user actually has available right now:
- All available built-ins — those whose `is_available(db_session)` returns True.
- All custom skills the user has access to via `is_public` + group + direct grant — same access query pattern as `fetch_persona_by_id_for_user`.

Read-only. There is no "select" or "pin" action; this endpoint exists so the user can see what their session will have access to (and so admin tooling can preview a user's effective skill set). The Craft session does not call this — the materializer reaches into the registry and DB directly at session start.

### No Craft consumer endpoints

There is no `/api/build/sessions/{id}/skills`. Sessions don't carry pin state; the materializer fully determines what gets written into `.opencode/skills/`.

### Internal (no HTTP)

```python
# backend/onyx/skills/__init__.py

class SkillRenderContext(BaseModel):
    user_name: str | None = None
    user_email: str | None = None
    backend_url: str | None = None
    session_id: UUID | None = None
    # consumer-specific keys, e.g. {"accessible_sources": "..."}
    extra: dict[str, str] = Field(default_factory=dict)

def materialize_skills(
    dest_path: Path,
    user: User,
    db_session: Session,
    render_context: SkillRenderContext,
) -> SkillsManifest:
    """
    Resolve and write every skill the user has access to into dest_path/<slug>/.
    Returns the manifest (also written as dest_path/.skills_manifest.json).

    Available built-ins (from BuiltinSkillRegistry.list_available_for) get
    their SKILL.md.template rendered if present; custom skills the user has
    access to (via list_skills_for_user) are unzipped verbatim.
    """

class SkillsManifest(BaseModel):
    builtin: list[SkillManifestEntry]   # slug, name, description
    custom: list[SkillManifestEntry]    # slug, name, description
```

`BuiltinSkillRegistry` is a process-wide singleton populated at app boot.

## Bundle Format

### Built-ins (on disk, from any registered directory)

```
<registered_dir>/<slug>/
├── SKILL.md                    # OR SKILL.md.template (built-ins only)
├── scripts/                    # arbitrary helpers
└── *.md                        # supporting docs
```

If `SKILL.md.template` is present, the materializer renders it through `_render_template_placeholders` against `SkillRenderContext` and writes the result as `SKILL.md`. If both exist, the template wins. Other files copy verbatim.

### Custom uploads (zip)

```
<bundle.zip>
├── SKILL.md                    # required, plain
├── scripts/                    # optional
└── *.md                        # optional
```

Validation rejects: missing `SKILL.md`, frontmatter without `name`/`description`, `name != slug`, **any `*.template` file**, any zip entry whose normalized path escapes the bundle root, any symlink, any individual file > 25 MiB, total uncompressed size > 100 MiB. Limits configurable via `SKILL_BUNDLE_MAX_FILE_BYTES` / `SKILL_BUNDLE_MAX_TOTAL_BYTES`.

`manifest_metadata` JSON column stores parsed frontmatter, list of files (relative paths only), total uncompressed size.

### `SkillRenderContext`

Built-ins reference well-known fields (`user_name`, `accessible_sources`, ...) via Mustache-style placeholders. Consumers populate the model before calling `materialize_skills`. The Craft consumer fills in `accessible_sources` via the same `get_connector_credential_pairs_for_user` call described in `search-design.md`. Unknown placeholders in templates are left in place and logged.

## Built-in Skills (V1 set)

Each built-in is registered at app boot by the build feature with a slug, source directory, and `is_available(db_session) -> bool` callable. The materializer evaluates `is_available` once per session-setup call; only-True skills are written. Admins do **not** get a per-org override — availability is purely a function of the deployment's state.

| Slug | Source | Description | `is_available` |
|------|--------|-------------|----------------|
| `pptx` | `docker/skills/pptx/` | Read, edit, and create `.pptx` decks via LibreOffice + pptxgenjs | `True` (LibreOffice + pptxgenjs are baked into the sandbox image) |
| `image-generation` | `docker/skills/image-generation/` | Generate images via the Gemini "Nano Banana" image API | `os.environ.get("GEMINI_API_KEY") is not None` (V1; later: check a configured image-gen provider row) |
| `bio-builder` | `docker/skills/bio-builder/` | Compose proposal-ready bios using company knowledge sources | `True` (pure prompt skill — no external dependencies) |
| `company-search` | `docker/skills/company-search/` (added by project #1) | Permissioned hybrid search over the user's accessible Onyx data | `True` whenever Craft is enabled (the endpoint it calls lives in the same backend) |

**How to add a new built-in:** drop a directory under `backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/<slug>/`, ship a `SKILL.md` (or `SKILL.md.template`), and add one `BuiltinSkillRegistry.register(...)` call in `backend/onyx/server/features/build/skills/builtins_registration.py` with an `is_available` callable and an `unavailable_reason` string (the latter is shown to admins in the admin UI when the check returns False). No DB migration, no admin-UI change, no toggle wiring. The next deploy picks it up.

**How `is_available` should be implemented:**

- **Always-true skills** (`pptx`, `bio-builder`, `company-search`): pass `lambda _db: True`. No state to check.
- **Provider-dependent skills** (`image-generation`): inspect whatever the provider needs — env var presence (V1) or, eventually, a provider-config DB row queried with the passed `db_session`. Cheap reads only — `is_available` runs on the session-setup hot path.
- **Feature-flag-dependent skills**: read from the existing settings/feature-flag table.

The callable should be **fast and cheap** (it runs per session start) and **side-effect-free** (it must not write to the DB). Errors raised by `is_available` are caught — the skill is treated as unavailable and a warning is logged.

`SkillRenderContext` placeholders used by V1 built-ins:

- `company-search` — `{{accessible_sources}}` (rendered list of the user's CC pairs; see `search-design.md`).
- Future built-ins — extend `SkillRenderContext` (well-known fields) or use `extra: dict[str, str]` for consumer-specific keys.

## UI

**Admin** (`web/src/app/admin/skills/`):

- One list view, two sections:
  - **Built-in skills**: read-only rows showing slug, description, and an availability badge (Available / Unavailable + one-line reason from the `unavailable_reason` field). No toggles. Admins who want a built-in to stop appearing in sessions for their deployment must remove or disable the underlying dependency (e.g. unset the provider key) — this is intentional.
  - **Custom skills**: full CRUD.
- Custom upload modal: file picker (zip), slug, name, description. POST returns either the created skill (success, list refreshes) or an `INVALID_REQUEST` error with a reason inline.
- Custom detail view: replace-bundle action (drag-and-drop zip; warns "this overwrites the current bundle and will be picked up by all sessions starting from now"), grants editor (group + user multi-selects, mirrors persona admin), enable / soft-delete actions, last-updated timestamp + sha256 fingerprint.

This page is mounted at `/admin/skills`, not `/admin/build/skills`. Future consumers reuse it as-is.

**User (Craft)**: no skill-picker UI. Sessions automatically receive every available built-in plus every custom skill the user has access to. A read-only "Skills available in this session" panel can be added later if users ask for visibility, but V1 ships nothing — the agent surfaces the skill list itself via `AGENTS.md`.

## AGENTS.md Skills Section

After materialization, `agent_instructions.py` reads `.skills_manifest.json` and produces `{{AVAILABLE_SKILLS_SECTION}}` based on the total count.

**Under the limit (default 15):** all skills inlined.

```
## Skills

You have these skills available under `.opencode/skills/<slug>/`. Read the relevant
SKILL.md before starting work that the skill covers.

Built-in:
- **pptx**: Read, edit, and create .pptx decks via LibreOffice + pptxgenjs.
- **company-search**: Permissioned hybrid search over the user's accessible Onyx data.
- ...

Custom:
- **deal-summary**: Generate per-customer deal-status briefings.
- ...
```

**Over the limit:** built-ins inlined, customs replaced by a discovery instruction.

```
## Skills

You have these skills available under `.opencode/skills/<slug>/`. Read the relevant
SKILL.md before starting work that the skill covers.

Built-in:
- **pptx**: Read, edit, and create .pptx decks via LibreOffice + pptxgenjs.
- **company-search**: Permissioned hybrid search over the user's accessible Onyx data.
- ...

Additional custom skills are also available in `.opencode/skills/`. Run
`ls .opencode/skills/` to enumerate them, then `cat .opencode/skills/<slug>/SKILL.md`
for any name that looks relevant to your task. Built-in skills are listed above; custom
skill names are not pre-listed because there are too many to include here without
crowding out other context.
```

The threshold is `BUILD_SKILLS_INLINE_LIMIT` (default 15). Tune on data — if agents start missing custom skills they should have used, lower it; if context bloat becomes a problem, raise it. The discovery convention (`ls` + `cat`) is just shell — no special tool, no MCP server, no parsing the manifest from inside the agent.

## Cleanup / Migrations

- Migration creates universal tables only (`skill`, `skill__user_group`, `skill__user`) plus the new `FileOrigin.SKILL_BUNDLE` enum value. No consumer-side join table. No data migration — existing Craft sessions just start receiving the auto-resolved skill set on next setup.
- Dockerfile change: drop `COPY skills/` and `mkdir -p /workspace/skills`. The on-disk skills at `backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/` stay as-is — they're now read at runtime by the api_server / Celery worker host file system, not baked into the sandbox image.
- Weekly Celery beat task `cleanup_orphaned_skill_bundles` (`@shared_task`, `expires=3600`): defensive sweep for `FileOrigin.SKILL_BUNDLE` blobs older than 14 days that no `skill.bundle_file_id` row references. The replace-bundle and delete-skill paths both clean up in-line during the request, so this task should normally find nothing — it exists to catch the rare case where a request crashed between file-store save and DB commit.

## Tests

Lightweight — agent-visible behavior (`.opencode/skills/<slug>/SKILL.md`) is unchanged, so we don't retest OpenCode's skill discovery. We test the *new* surface: bundle validation, materialization, access control, session pinning, built-in registry semantics.

**External-dependency unit (the bulk of the value):**
`backend/tests/external_dependency_unit/skills/test_skills_lifecycle.py`
- Upload a valid custom bundle → assert 200, `skill` row created with `bundle_file_id` set, blob in file store.
- Upload an invalid bundle (path traversal entry, missing `SKILL.md`, contains `SKILL.md.template`) → assert 4xx with `INVALID_REQUEST` and reason; assert no `skill` row, no blob in file store.
- Replace bundle on an existing skill → assert `skill` row's `bundle_file_id` and `bundle_sha256` updated, **old blob deleted from the file store**.
- Grant skill to group A → user in group A sees it via `GET /api/skills`, user not in group A doesn't.
- Built-in registry: register a temp slug with `is_available=lambda _: True` → confirm it appears in `GET /api/skills`. Register one with `is_available=lambda _: False` → confirm it doesn't.
- Built-in availability error path: register a slug whose `is_available` raises → confirm it's treated as unavailable and a warning is logged.
- `materialize_skills` for a user with two granted customs and three available built-ins → confirm five directories under the destination + `.skills_manifest.json` listing them.

**Integration (one E2E):**
`backend/tests/integration/tests/skills/test_skill_materialization.py`
- Provision a Craft session for a user with one custom skill granted (and one not granted, to verify the access filter), start the sandbox, exec/read into it, assert:
  - `.opencode/skills/<granted-custom-slug>/SKILL.md` matches the uploaded bundle.
  - `.opencode/skills/<not-granted-slug>/` does **not** exist.
  - `.opencode/skills/<builtin-slug>/SKILL.md` is the rendered template — placeholders expanded, no `{{...}}` remaining (for built-ins shipping `.template`).
  - `.skills_manifest.json` lists built-ins and customs separately.
  - `{{AVAILABLE_SKILLS_SECTION}}` in the materialized `AGENTS.md` includes the granted skills' names + descriptions when count is under the limit.

`backend/tests/integration/tests/skills/test_skills_inline_limit.py`
- Set `BUILD_SKILLS_INLINE_LIMIT=2`, upload three customs and grant all to a user, start a session, assert: `AGENTS.md` lists the built-ins inline + the discovery instruction; the three custom slugs are present in `.opencode/skills/` but not in the inline list.

**Unit (only for the bundle helper):**
`backend/tests/unit/onyx/skills/test_bundle.py`
- `validate_custom_bundle` rejects each documented failure mode (including `SKILL.md.template` present) and accepts a known-good fixture.
- `compute_bundle_sha256` is deterministic across two zips of the same content with different timestamps.

**Manual smoke (do this before merging):**
- Boot a fresh tenant; admin UI at `/admin/skills` lists each registered built-in with an "Available" badge. Unset `GEMINI_API_KEY`, refresh, confirm `image-generation` flips to "Unavailable" with a reason.
- Upload a custom skill, grant it to a group the test user is in, start a session, confirm `.opencode/skills/<slug>/SKILL.md` materialized.
- Revoke the grant, start a new session, confirm `.opencode/skills/<slug>/` is absent.
- Upload a custom skill containing `SKILL.md.template`; confirm the request is rejected inline with an explanatory reason and nothing is persisted.
- Edit a built-in's `SKILL.md.template` on disk, redeploy, start a new session; confirm rendered `SKILL.md` reflects the edit and contains a real source list.
- With `BUILD_SKILLS_INLINE_LIMIT=2` and three customs granted, confirm the agent's `AGENTS.md` has the discovery instruction and the agent can `ls .opencode/skills/` and read individual `SKILL.md` files to find a custom one.

That's it. No load test, no fuzzer for the validator — the bundle is admin-uploaded, the surface is small, and the materialization is just file IO.
