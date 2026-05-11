# Skills V1 — Live Task Board

**Source of truth for execution status.** The design lives in [`skills_plan.md`](./skills_plan.md). The current state of work lives here.

---

## How to use this doc

If you're an agent picking up work:

1. **Read the spec first.** `skills_plan.md` — start with the invariants at the top, then the phase you'll be working in.
2. **Find an unblocked `[TODO]` whose dependencies are all `[DONE]`.** Don't pick a task with unfinished deps.
3. **Claim it** by editing the line in place: `[TODO]` → `[WIP @your-handle]`. Push a commit on this file ("claim P1.012") before starting other work so two agents don't claim the same thing.
4. **Open a PR.** When the PR is up, update to `[REVIEW @your-handle #PR]`.
5. **Mark done** when merged: `[DONE @your-handle #PR]`. Leave the handle + PR for future archaeology.
6. **Get blocked?** Move to `[BLOCKED @your-handle] reason: <why>`. Add a note. Free the task back to `[TODO]` if you can't unblock soon — someone else may be able.

**Don't:** add new tasks here without also updating `skills_plan.md`. The two files have to stay coherent — TODOS.md is execution, the spec is design.

**Do:** add subtasks under an existing task if you discover them. Indent them under the parent.

**On conflict resolution:** Each task is one line. If two agents edit the file simultaneously, conflicts are line-level and trivial to resolve. Don't reformat the file; don't reorder tasks. Append-only for sub-discoveries.

---

## Status legend

| Status | Meaning |
|---|---|
| `[TODO]` | Unclaimed, ready to pick up if deps are met |
| `[WIP @handle]` | In progress, do not duplicate |
| `[REVIEW @handle #PR]` | PR open, in review |
| `[DONE @handle #PR]` | Merged to main |
| `[BLOCKED @handle]` | Stuck — see `reason:` note |
| `[SKIP]` | Explicitly cut from V1 (see V1.5 list at bottom) |

---

## In flight right now

_(Update this section as you claim things. Keep it short — just the active `WIP` and `REVIEW` items so anyone glancing at the file can see what's hot.)_

- _(nothing yet)_

---

## Phase 1 — Foundation (universal primitive)

**Goal:** the universal layer compiles and is unit-testable. No HTTP routes yet, no sandbox wiring.
**Effort:** M (2–5 days)  ·  **Blocks:** everything

### 1.1 Database + migration  (spec §3)

- `[TODO]` `P1.001` Add `Skill` model to `backend/onyx/db/models.py` with all columns + indexes per §3
- `[TODO]` `P1.002` Add `Skill__UserGroup` join table to `backend/onyx/db/models.py`
- `[TODO]` `P1.003` Add `FileOrigin.SKILL_BUNDLE` to `backend/onyx/configs/constants.py:373`
- `[TODO]` `P1.005` Create Alembic revision under `backend/alembic/versions/<hash>_skills.py` — `CREATE TABLE skill` (with `ux_skill_slug` unique index, no extra perf index in V1), `CREATE TABLE skill__user_group`, `ALTER TYPE fileorigin ADD VALUE 'skill_bundle'`  (deps: P1.001, P1.002, P1.003)
- `[TODO]` `P1.006` Run `alembic -n schema_private upgrade head` on a fresh EE tenant; confirm clean apply + idempotent re-run  (deps: P1.005)

### 1.2 Module skeletons  (spec §2)

- `[TODO]` `P1.010` Create empty `backend/onyx/skills/__init__.py`
- `[TODO]` `P1.011` Create empty `backend/onyx/skills/registry.py`
- `[TODO]` `P1.012` Create empty `backend/onyx/skills/bundle.py`
- `[TODO]` `P1.013` Create empty `backend/onyx/skills/materialize.py`
- `[TODO]` `P1.014` Create empty `backend/onyx/skills/render.py`
- `[TODO]` `P1.015` Create empty `backend/onyx/db/skill.py`

### 1.3 BuiltinSkillRegistry  (spec §4)

- `[TODO]` `P1.020` Define `SkillRequirement` dataclass in `registry.py`  (deps: P1.011)
- `[TODO]` `P1.021` Define `BuiltinSkill` dataclass in `registry.py`  (deps: P1.011)
- `[TODO]` `P1.022` Implement `BuiltinSkillRegistry` singleton accessor (`.instance()`)  (deps: P1.021)
- `[TODO]` `P1.023` Implement `register(slug, source_dir, requirements=[])` — read frontmatter, detect `SKILL.md.template` presence, slug regex validation, raise on duplicate or missing SKILL.md  (deps: P1.022)
- `[TODO]` `P1.024` Implement `list_all() -> list[BuiltinSkill]`  (deps: P1.022)
- `[TODO]` `P1.025` Implement `list_satisfied(db) -> list[BuiltinSkill]` — filter by all `requirement.check(db) == True`  (deps: P1.020, P1.024)
- `[TODO]` `P1.026` Implement `evaluate_for_admin(db) -> list[BuiltinSkillStatus]` for admin UI  (deps: P1.025)
- `[TODO]` `P1.027` Implement `get(slug)` and `reserved_slugs()`  (deps: P1.022)
- `[TODO]` `P1.028` Unit test: register two slugs with collision → raise; register with missing SKILL.md → raise  (deps: P1.023)
- `[TODO]` `P1.029` Unit test: `list_satisfied` excludes a skill whose `check` returns False; `evaluate_for_admin` returns the unmet requirement with description  (deps: P1.025, P1.026)

### 1.4 Bundle validator  (spec §5)

- `[TODO]` `P1.030` Define `InvalidBundleError(OnyxError)` with `INVALID_REQUEST` code  (deps: P1.012)
- `[TODO]` `P1.031` Implement `validate_custom_bundle(zip_bytes, slug) -> ManifestMetadata` — zip parse, SKILL.md root check, frontmatter parse, no `*.template`  (deps: P1.030)
- `[TODO]` `P1.032` Add path-traversal + symlink rejection to `validate_custom_bundle`  (deps: P1.031)
- `[TODO]` `P1.033` Add per-file + total-size streaming check (defaults 25 MiB / 100 MiB)  (deps: P1.031)
- `[TODO]` `P1.035` Add slug regex + reserved-slug check (uses `BuiltinSkillRegistry.reserved_slugs()`)  (deps: P1.031, P1.027)
- `[TODO]` `P1.036` Implement `_safe_unzip(zip_bytes, dest)` for defensive re-check at materialization
- `[TODO]` `P1.037` Implement `compute_bundle_sha256(zip_bytes)` — deterministic over raw bytes
- `[TODO]` `P1.038` Unit test fixture: valid bundle zip (`SKILL.md` + frontmatter + scripts dir)
- `[TODO]` `P1.039` Unit test fixture: invalid bundles, one per failure mode (no SKILL.md, traversal entry, symlink, oversized, contains `*.template`)
- `[TODO]` `P1.040` Unit test: each invalid fixture rejected with the correct error reason  (deps: P1.039, P1.031-P1.033, P1.035)
- `[TODO]` `P1.041` Unit test: `compute_bundle_sha256` deterministic across two zips of same content with different timestamps  (deps: P1.037)

### 1.5 Materializer  (spec §6)

- `[TODO]` `P1.050` Define `SkillRenderContext`, `SkillManifestEntry`, `SkillsManifest` Pydantic models  (deps: P1.013)
- `[TODO]` `P1.051` Implement `materialize_skills(dest, user, db, render_ctx) -> SkillsManifest` per §6 algorithm  (deps: P1.025, P1.036, P1.050)
- `[TODO]` `P1.052` Extract `render_template_placeholders` from `agent_instructions.py` into `backend/onyx/skills/render.py`  (deps: P1.014)
- `[TODO]` `P1.053` Public re-exports in `backend/onyx/skills/__init__.py`  (deps: P1.020-P1.052)
- `[TODO]` `P1.054` External-dep unit test: materialize for fixture user with 1 granted custom + 1 not-granted + 2 built-ins → 3 directories + valid `.skills_manifest.json`  (deps: P1.051)
- `[TODO]` `P1.055` External-dep unit test: built-in with `SKILL.md.template` materializes with placeholders rendered  (deps: P1.051, P1.052)

### 1.6 DB ops  (spec §3)

- `[TODO]` `P1.060` Implement `list_skills_for_user(user, db)` — public OR group-grant query, mirror `fetch_persona_by_id_for_user` at `backend/onyx/db/persona.py:81` (drop the user-direct-grant branch)  (deps: P1.015)
- `[TODO]` `P1.061` Implement `fetch_skill_for_user(skill_id, user, db)`  (deps: P1.060)
- `[TODO]` `P1.062` Implement `fetch_skill_for_admin(skill_id, db)` — no access filter  (deps: P1.015)
- `[TODO]` `P1.063` Implement `list_skills_for_admin(db)` — no access filter  (deps: P1.015)
- `[TODO]` `P1.064` Implement `create_skill(slug, name, description, bundle_file_id, bundle_sha256, manifest_metadata, is_public, owner_user_id, db) -> Skill`  (deps: P1.015)
- `[TODO]` `P1.065` Implement `replace_skill_bundle(skill_id, new_bundle_file_id, new_sha256, new_manifest_metadata, db) -> Skill` — returns `old_bundle_file_id` for caller blob cleanup  (deps: P1.015)
- `[TODO]` `P1.066` Implement `patch_skill(...)` — partial update; re-validate slug uniqueness if changing  (deps: P1.015)
- `[TODO]` `P1.067` Implement `replace_skill_grants(skill_id, group_ids, db)` — atomic delete + insert in one transaction  (deps: P1.015)
- `[TODO]` `P1.068` Implement `delete_skill(skill_id, db) -> str` — soft-delete; returns `bundle_file_id`  (deps: P1.015)

---

## Phase 2 — Operability (API surface)

**Goal:** fully operable via HTTP. No sandbox wiring, no admin UI — but `curl` works end-to-end.
**Effort:** M  ·  **Depends:** Phase 1 done

### 2.1 Universal admin router  (spec §7)

- `[TODO]` `P2.001` Create `backend/onyx/server/features/skills/__init__.py`
- `[TODO]` `P2.002` Create `backend/onyx/server/features/skills/api.py` with router scaffolding
- `[TODO]` `P2.003` Define Pydantic response models: `SkillsAdminList`, `BuiltinSkillAdmin`, `RequirementStatus`, `CustomSkillAdmin`, `SkillsForUser`, `SkillSummary`  (deps: P2.002)
- `[TODO]` `P2.004` Implement `GET /api/admin/skills` — combine `registry.evaluate_for_admin(db)` + `list_skills_for_admin(db)`  (deps: P2.003, P1.026, P1.063)
- `[TODO]` `P2.005` Implement `POST /api/admin/skills/custom` — full create flow per §7 (validate → save blobs → row → grants); inline blob cleanup on failure  (deps: P2.003, P1.031, P1.064, P1.067)
- `[TODO]` `P2.006` Implement `PATCH /api/admin/skills/custom/{id}` — slug/name/description/is_public/enabled; re-validate slug uniqueness on slug change  (deps: P2.003, P1.066)
- `[TODO]` `P2.007` Implement `PUT /api/admin/skills/custom/{id}/bundle` — replace flow; delete old blobs AFTER commit  (deps: P2.003, P1.031, P1.065)
- `[TODO]` `P2.008` Implement `PUT /api/admin/skills/custom/{id}/grants` — atomic group_ids replacement  (deps: P2.003, P1.067)
- `[TODO]` `P2.009` Implement `DELETE /api/admin/skills/custom/{id}` — soft-delete (do not delete blobs; sweep handles)  (deps: P2.003, P1.068)

### 2.2 User router  (spec §7)

- `[TODO]` `P2.020` Implement `GET /api/skills` — built-ins (filtered by `list_satisfied`) + customs visible to user  (deps: P2.003, P1.025, P1.060)

### 2.3 Wire-up + tests

- `[TODO]` `P2.030` Add admin dependency to admin routes (match existing Onyx pattern)
- `[TODO]` `P2.031` Wire router into `backend/onyx/main.py` via `app.include_router(...)`  (deps: P2.001-P2.021)
- `[TODO]` `P2.032` External-dep unit test: POST valid bundle → 200 + row + blob; each invalid bundle → 4xx + no row/blob  (deps: P2.005)
- `[TODO]` `P2.033` External-dep unit test: replace bundle → old blob deleted after commit  (deps: P2.007)
- `[TODO]` `P2.034` External-dep unit test: grant to group A → user in A sees it via `GET /api/skills`; user not in A doesn't  (deps: P2.020, P2.008)
- `[TODO]` `P2.035` External-dep unit test: slug rename via PATCH → uniqueness re-checked  (deps: P2.006)
- `[TODO]` `P2.036` External-dep unit test: `GET /api/admin/skills` returns `available: false` + populated `requirements` when image-gen provider is not configured  (deps: P2.004)

---

## Phase 3 — Craft consumer wiring

**Goal:** skills actually materialize into running sandboxes. End-to-end works without any admin UI.
**Effort:** M  ·  **Depends:** Phase 1 done  ·  **Blocks:** Phase 6

### 3.1 Built-ins registration

- `[TODO]` `P3.001` Create `backend/onyx/server/features/build/skills/__init__.py`
- `[TODO]` `P3.002` Create `backend/onyx/server/features/build/skills/builtins_registration.py` with `register_craft_builtins(registry)`  (deps: P3.001, P1.022)
- `[TODO]` `P3.003` Register `pptx` built-in (no requirements)  (deps: P3.002)
- `[TODO]` `P3.004` Register `image-generation` built-in with `SkillRequirement` checking `get_default_image_generation_config(db) is not None`, `configure_url=/admin/configuration/image-generation`  (deps: P3.002, P1.020)
- `[TODO]` `P3.005` Call `register_craft_builtins(BuiltinSkillRegistry.instance())` from `backend/onyx/main.py` startup (after DB init, before `app.include_router`)  (deps: P3.003, P3.004)
- `[TODO]` `P3.006` Startup integration test: `assert registry.get("pptx") is not None`; `list_satisfied` excludes `image-generation` when no provider is configured  (deps: P3.005)

### 3.2 Materialization adapter

- `[TODO]` `P3.010` Implement `render_accessible_cc_pairs(user, db)` helper — confirm/reuse from `search.md`; if new, implement using existing `get_connector_credential_pairs_for_user`
- `[TODO]` `P3.011` Create `backend/onyx/server/features/build/skills/materialize_adapter.py` with `materialize_for_session(session, user, db) -> (Path, SkillsManifest)`  (deps: P3.010, P1.051)

### 3.3 Sandbox delivery — K8s

- `[TODO]` `P3.020` Implement `_stream_skills_into_pod(pod_name, staging_dir, session_path)` in `KubernetesSandboxManager` (use existing `_kubectl_exec_stdin` pattern from snapshot restore)
- `[TODO]` `P3.021` Replace `ln -sf /workspace/skills` block at `kubernetes_sandbox_manager.py:1338-1340` with: call `materialize_for_session`, then `_stream_skills_into_pod`, then `rmtree(staging_dir)`  (deps: P3.011, P3.020)
- `[TODO]` `P3.022` Gate the new path behind `SKILLS_MATERIALIZATION_V2_ENABLED` (defined in P5.001)  (deps: P3.021, P5.001)

### 3.4 Sandbox delivery — local

- `[TODO]` `P3.030` Implement `_setup_skills_local(staging_dir, session_path)` in local sandbox manager (shutil.copytree + cleanup)
- `[TODO]` `P3.031` Replace `directory_manager.setup_skills(...)` call sites with `_setup_skills_local`; drop `_skills_path` constructor arg from `DirectoryManager`  (deps: P3.011, P3.030)
- `[TODO]` `P3.032` Update callers of `DirectoryManager` to drop the `skills_path` argument (look at `directory_manager.py:78` and `:309`)  (deps: P3.031)

### 3.5 Sandbox helper

- `[TODO]` `P3.040` Add `read_file_from_session(session, path) -> str` to `SandboxManagerBase`
- `[TODO]` `P3.041` Implement `read_file_from_session` in `KubernetesSandboxManager` (kubectl exec cat)  (deps: P3.040)
- `[TODO]` `P3.042` Implement `read_file_from_session` in local sandbox manager (direct FS read)  (deps: P3.040)

### 3.6 Panel data source

- `[TODO]` `P3.050` Create `backend/onyx/server/features/build/skills/api.py` with router scaffolding
- `[TODO]` `P3.051` Implement `GET /api/build/sessions/{id}/skills` — reads `.skills_manifest.json` from session, returns `SkillsManifest`  (deps: P3.050, P3.040)
- `[TODO]` `P3.052` Implement `GET /api/build/sessions/{id}/skills/{slug}/content` — returns rendered SKILL.md text  (deps: P3.050, P3.040)
- `[TODO]` `P3.053` Wire build-feature router into Onyx app  (deps: P3.050-P3.052)

### 3.7 AGENTS.md generation

- `[TODO]` `P3.060` Rewrite `build_skills_section(skills_dir)` at `agent_instructions.py:267` — read `.skills_manifest.json`, inline every entry, no threshold
- `[TODO]` `P3.061` Delete `_skills_cache` and `_skills_cache_lock` (top of `agent_instructions.py`)  (deps: P3.060)
- `[TODO]` `P3.062` Delete `_scan_skills_directory` if unused after rewrite  (deps: P3.060)
- `[TODO]` `P3.063` Confirm callsite at `agent_instructions.py:481` still works (signature unchanged)  (deps: P3.060)
- `[TODO]` `P3.064` Confirm `build_skills_section` is called with materialized dir path, not source dir  (deps: P3.060)

### 3.8 Dockerfile

- `[TODO]` `P3.070` Remove `COPY skills/ /workspace/skills/` from `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile:99`
- `[TODO]` `P3.071` Remove `RUN mkdir -p /workspace/skills` from same Dockerfile
- `[TODO]` `P3.072` Update sandbox image build pipeline to rebuild without skills dir (the dir on disk in the Onyx repo stays)

### 3.9 Integration tests

- `[TODO]` `P3.080` Create `backend/tests/integration/tests/skills/` directory
- `[TODO]` `P3.081` Integration test `test_skill_materialization.py`: session with 1 granted + 1 not-granted custom → verify `.agents/skills/<slug>/SKILL.md`, manifest contents, AGENTS.md inline list  (deps: P3.022 OR P3.031, P3.060)
- `[TODO]` `P3.082` Integration test: built-in `SKILL.md.template` renders with placeholders expanded inside the session  (deps: P3.081)

---

## Phase 4 — Admin UI

**Goal:** admins manage skills without `curl`.
**Effort:** L (1+ week)  ·  **Depends:** Phase 2 endpoints stable  ·  **Parallel with Phase 3**

### 4.1 Page shell + routing

- `[TODO]` `P4.001` Create `web/src/app/admin/skills/page.tsx` using `SettingsLayouts.Root`/`.Header`/`.Body` pattern from `AgentsPage.tsx`
- `[TODO]` `P4.002` Add Skills entry to admin nav in `web/src/lib/admin-routes.ts`
- `[TODO]` `P4.003` Frontend type definitions matching backend Pydantic models (`BuiltinSkillAdmin`, `CustomSkillAdmin`, etc.)  (deps: P2.003)

### 4.2 List view

- `[TODO]` `P4.010` `web/src/app/admin/skills/SkillsList.tsx` — table renderer using `@opal/components` Table
- `[TODO]` `P4.011` `web/src/app/admin/skills/SkillRow.tsx` — icon + name + slug + description + source badge + access + action menu
- `[TODO]` `P4.012` `web/src/app/admin/skills/SourceBadge.tsx` — Platform / Custom pill
- `[TODO]` `P4.013` Access column rendering: `Available` for satisfied built-ins, `Needs setup · Configure →` (deep-link to `requirements[0].configure_url`) for unmet  (deps: P4.011)
- `[TODO]` `P4.014` Search + filters: by name/slug, source (All/Platform/Custom), availability
- `[TODO]` `P4.015` Loading / error / empty states

### 4.3 Upload modal

- `[TODO]` `P4.020` `UploadSkillModal.tsx` — file picker + slug/name/description/visibility fields + Trust-check banner
- `[TODO]` `P4.021` Client-side frontmatter pre-fill: parse uploaded zip with `jszip`, extract SKILL.md frontmatter, populate name/description fields
- `[TODO]` `P4.022` Slug regex validation client-side
- `[TODO]` `P4.023` Submit → multipart POST to `/api/admin/skills/custom`; on success close modal + refetch list; on failure show inline error from `OnyxError.detail`  (deps: P2.005)

### 4.4 Visibility picker (shared component)

- `[TODO]` `P4.030` `VisibilityPicker.tsx` — radio: Private / Org-wide / Specific groups + conditional group multi-select
- `[TODO]` `P4.031` Group multi-select uses existing Onyx groups API (reuse from Persona admin)
- `[TODO]` `P4.032` Reuse `VisibilityPicker` in upload modal + standalone grants editor

### 4.5 Built-in detail drawer

- `[TODO]` `P4.040` `BuiltinDetailDrawer.tsx` — read-only metadata (name, slug, description, source path, files, frontmatter)
- `[TODO]` `P4.041` Requirements section: list each `RequirementStatus` with ✓ if satisfied or ! + Configure button if missing  (deps: P4.040)
- `[TODO]` `P4.042` Section omitted entirely if skill has no requirements

### 4.6 Edit / Replace / Grants / Delete modals

- `[TODO]` `P4.050` `EditSkillModal.tsx` — slug/name/description editable; PATCH on submit  (deps: P2.006)
- `[TODO]` `P4.051` `ReplaceBundleModal.tsx` — drag-drop zip; mandatory "new sessions only" copy; PUT on submit  (deps: P2.007)
- `[TODO]` `P4.052` Standalone `ManageGrantsModal.tsx` using VisibilityPicker; PUT on submit  (deps: P4.030, P2.008)
- `[TODO]` `P4.053` Delete confirmation modal with both "existing sessions unaffected" + "workspace persistence" callouts; DELETE on submit  (deps: P2.009)

### 4.7 Stretch (defer if behind)

- `[TODO]` `P4.060` Row action menu polish (icons, hover transitions)
- `[TODO]` `P4.061` Validation error inline display refinement
- `[TODO]` `P4.062` Frontend tests beyond smoke

---

## Phase 5 — Security & operations

**Goal:** production-ready security and observability posture.
**Effort:** M  ·  **Parallel with Phase 3/4**

### 5.1 Feature flag

- `[TODO]` `P5.001` Add `SKILLS_MATERIALIZATION_V2_ENABLED` to `backend/onyx/configs/...` (match existing flag conventions)
- `[TODO]` `P5.002` Document the staged rollout sequence in PR description for the implementation PRs
- `[TODO]` `P5.003` File cleanup ticket: remove flag + legacy `ln -sf` code one release after flag is fully on

### 5.2 Sandbox hardening verification  (spec §18)

- `[TODO]` `P5.010` Confirm `securityContext.runAsNonRoot: true` on Craft sandbox pod
- `[TODO]` `P5.011` Confirm `securityContext.readOnlyRootFilesystem: true` (with explicit writable mounts for `/workspace`, `/tmp`)
- `[TODO]` `P5.012` Confirm `capabilities.drop: [ALL]` on the container
- `[TODO]` `P5.013` Confirm CPU + memory limits set on the container
- `[TODO]` `P5.014` (AWS) Confirm IMDSv2 enforced with `httpPutResponseHopLimit: 1`
- `[TODO]` `P5.015` Confirm `automountServiceAccountToken: false` unless K8s API access is required
- `[TODO]` `P5.016` Audit IRSA role on `file-sync` sidecar — confirm scope is per-session S3 prefix, not tenant-wide
- `[TODO]` `P5.017` Confirm no env vars in sandbox carry secrets (secrets path is interception)
- `[TODO]` `P5.018` Confirm NetworkPolicy denies direct egress; only interception proxy is reachable

### 5.3 Interception team coordination

- `[TODO]` `P5.020` File ticket: **Deny POST/PUT/PATCH/DELETE to non-classified domains** (allow GET) — see §18 ask #1
- `[TODO]` `P5.021` File ticket: **Approval required for any write within classified services**, not just destructive ones — see §18 ask #2
- `[TODO]` `P5.022` Cross-reference `docs/craft/features/interception.md` from skills_plan §18 once that doc lands

### 5.4 Orphan blob sweep  (spec §16)

- `[TODO]` `P5.030` Create `backend/onyx/background/celery/tasks/skills/__init__.py`
- `[TODO]` `P5.031` Create `backend/onyx/background/celery/tasks/skills/tasks.py` with `@shared_task(name="cleanup_orphaned_skill_blobs")` (must include `expires=3600` per `CLAUDE.md`)
- `[TODO]` `P5.032` Implement `_stale_skill_blobs(db, age_days=14)` query — FileStore records with origin `SKILL_BUNDLE` older than 14d with no `skill` row reference
- `[TODO]` `P5.033` Add weekly beat schedule entry
- `[TODO]` `P5.034` Unit test: orphan blob older than 14 days → deleted by task
- `[TODO]` `P5.035` Integration test: soft-delete skill → blob NOT immediately deleted; advance time → task deletes it

### 5.5 Per-session skills UI  (spec §11)

- `[TODO]` `P5.040` `SkillsPanel.tsx` in Craft session UI — fetches `/api/build/sessions/{id}/skills`, renders read-only list  (deps: P3.051)
- `[TODO]` `P5.041` Skill card sub-component: icon + name + description + source badge
- `[TODO]` `P5.042` Click card → drawer showing rendered SKILL.md preview via `GET .../skills/{slug}/content`  (deps: P3.052)
- `[TODO]` `P5.043` Inline mention: pattern-match OpenCode tool-use/file-read events on `^\.agents/skills/([a-z][a-z0-9-]{0,63})/SKILL\.md$`; render "Using `<slug>`" pill at matching position in chat stream
- `[TODO]` `P5.044` Mount `SkillsPanel` in Craft session UI shell

### 5.6 Stretch — Invocation audit log (V1.5)  (spec §18)

- `[SKIP]` `P5.050` New table `skill_invocation_log (id, tenant_id, session_id, user_id, skill_id, slug, source, bundle_sha256, opened_at)`
- `[SKIP]` `P5.051` Event emitter on SKILL.md-read pattern match (same source as inline pill)
- `[SKIP]` `P5.052` Aggregation query for admin UI usage surface
- `[SKIP]` `P5.053` Surface usage counts in built-in detail drawer + custom skill detail view

---

## Phase 6 — Polish, rollout, ship

**Goal:** actually flip the switch and verify it works in prod.
**Effort:** S–M  ·  **Depends:** Phase 3 + Phase 5

### 6.1 Snapshot fidelity verification  (spec §12)

- `[TODO]` `P6.001` Confirm `backend/onyx/server/features/build/sandbox/manager/snapshot_manager.py` includes `.agents/skills/` in the tarball (likely already does — it's part of workspace)
- `[TODO]` `P6.002` Verify resume path does NOT call materializer — restore is purely tarball expansion
- `[TODO]` `P6.003` Add invariant docstring "Sessions are skill-immutable after start" to `backend/onyx/skills/__init__.py`
- `[TODO]` `P6.004` Integration test `test_snapshot_fidelity.py`: pause session, change skill state, resume → snapshot contents unchanged

### 6.2 Multi-tenant test  (spec §14)

- `[TODO]` `P6.010` Integration test `test_multi_tenant_isolation.py`: two tenants both create custom skill `deal-summary` → both succeed, isolated

### 6.3 Unit + manual smoke  (spec §17)

- `[TODO]` `P6.020` Create `backend/tests/unit/onyx/skills/test_bundle.py` — see Phase 1.4 fixtures + tests (P1.038-P1.041 already cover this; this task is verifying coverage)
- `[TODO]` `P6.021` Manual smoke: `/admin/skills` lists built-ins + customs with correct badges
- `[TODO]` `P6.022` Manual smoke: upload Org-wide skill; another user gets it in their session
- `[TODO]` `P6.023` Manual smoke: re-upload bundle; old session unchanged; new session has new bundle
- `[TODO]` `P6.024` Manual smoke: rename slug; new session uses new slug; resumed old session keeps old slug
- `[TODO]` `P6.025` Manual smoke: soft-delete; running session unaffected; new session doesn't see it
- `[TODO]` `P6.026` Manual smoke: inline mention pill appears when agent reads a SKILL.md
- `[TODO]` `P6.027` Manual smoke: unset image-gen provider config, refresh admin UI → `image-generation` shows "Needs setup" with Configure CTA; configure provider, refresh → shows "Available"

### 6.4 Deploy sequence  (spec §15)

- `[TODO]` `P6.030` Deploy api_server with all new code, flag `SKILLS_MATERIALIZATION_V2_ENABLED=false`
- `[TODO]` `P6.031` Deploy new sandbox image (no `/workspace/skills`)
- `[TODO]` `P6.032` Flip the flag to `true`
- `[TODO]` `P6.033` Soak one release cycle
- `[TODO]` `P6.034` Remove flag + legacy `ln -sf` code (this is the ticket from P5.003)

---

## Explicitly cut from V1 — pick up in V1.5+

Listed so agents don't accidentally pick these up. Lift to a real task only if priorities change.

- `[SKIP]` `V15.001` Invocation audit log (P5.050–P5.053 above)
- `[SKIP]` `V15.002` Per-user skill grants (`Skill__User` table)
- `[SKIP]` `V15.003` Per-org built-in toggle (`org_enabled`)
- `[SKIP]` `V15.004` Per-session user opt-out / pinning
- `[SKIP]` `V15.005` AGENTS.md threshold + discovery fallback
- `[SKIP]` `V15.006` Skill versioning / rollback
- `[SKIP]` `V15.007` Two-person upload approval
- `[SKIP]` `V15.008` Per-skill permission declarations (network/fs/integrations)
- `[SKIP]` `V15.009` Skill provenance / signing
- `[SKIP]` `V15.010` Content scanning at upload (intentionally — false-confidence risk)
- `[SKIP]` `V15.011` Shared/bundled `SkillRequirement` modules
- `[SKIP]` `V15.012` In-browser skill editor
- `[SKIP]` `V15.013` Slug rename history table

---

## Decisions log

_(Append cross-cutting decisions or clarifications that come up during implementation. Don't update the spec mid-flight — record here, surface to the spec at the end of the phase.)_

- _(nothing yet)_
