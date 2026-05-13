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

- `[REVIEW @codex-charged-perovskite #11061]` `P1.010-P1.015` Module skeletons
- `[REVIEW @codex-charged-perovskite #11061]` `P1.020-P1.027` BuiltinSkillRegistry core
- `[REVIEW @codex-charged-perovskite #11061]` `P1.028-P1.029` BuiltinSkillRegistry unit tests
- `[REVIEW @claude-coupled-lattice #11060]` `P1.060-P1.068` Phase 1.6 DB ops (`backend/onyx/db/skill.py`)
- `[REVIEW @claude-coupled-josephson #11059]` `P1.030-P1.041` Bundle validator (excl. P1.035 reserved-slug check — depends on registry WIP)
- `[REVIEW @claude-collapsing-meson #11064]` `P5.030-P5.038` Phase 5.4 orphan-blob + aged-soft-delete sweep

---

## Phase 1 — Foundation (universal primitive)

**Goal:** the universal layer compiles and is unit-testable. No HTTP routes yet, no sandbox wiring.
**Effort:** M (2–5 days)  ·  **Blocks:** everything

### 1.1 Database + migration  (spec §3)

- `[DONE @rohoswagger #10996]` `P1.001` Add `Skill` model to `backend/onyx/db/models.py` with all columns + indexes per §3
- `[DONE @rohoswagger #10996]` `P1.002` Add `Skill__UserGroup` join table to `backend/onyx/db/models.py`
- `[DONE @rohoswagger #10996]` `P1.003` Add `FileOrigin.SKILL_BUNDLE` to `backend/onyx/configs/constants.py:373`
- `[DONE @rohoswagger #10996]` `P1.005` Create Alembic revision under `backend/alembic/versions/<hash>_skills.py` — `CREATE TABLE skill`, then `CREATE UNIQUE INDEX ux_skill_slug ON skill (slug) WHERE deleted_at IS NULL` (partial unique so slugs can be reused after soft-delete); `CREATE TABLE skill__user_group`; `ALTER TYPE fileorigin ADD VALUE 'skill_bundle'`. No extra perf index in V1.  (deps: P1.001, P1.002, P1.003)
- `[DONE @rohoswagger #10996]` `P1.006` Run `alembic -n schema_private upgrade head` on a fresh EE tenant; confirm clean apply + idempotent re-run  (deps: P1.005)

### 1.2 Module skeletons  (spec §2)

- `[REVIEW @codex-charged-perovskite #11061]` `P1.010` Create empty `backend/onyx/skills/__init__.py`
- `[REVIEW @codex-charged-perovskite #11061]` `P1.011` Create empty `backend/onyx/skills/registry.py`
- `[REVIEW @codex-charged-perovskite #11061]` `P1.012` Create empty `backend/onyx/skills/bundle.py`
- `[REVIEW @codex-charged-perovskite #11061]` `P1.013` Create empty `backend/onyx/skills/materialize.py`
- `[REVIEW @codex-charged-perovskite #11061]` `P1.014` Create empty `backend/onyx/skills/render.py`
- `[REVIEW @codex-charged-perovskite #11061]` `P1.015` Create empty `backend/onyx/db/skill.py`

### 1.3 BuiltinSkillRegistry  (spec §4)

- `[REVIEW @codex-charged-perovskite #11061]` `P1.020` Define `BuiltinSkill` in `registry.py` as a Pydantic `BaseModel` with frozen + arbitrary-types config, including optional `is_available` and `unavailable_reason` fields  (deps: P1.011)
- `[REVIEW @codex-charged-perovskite #11061]` `P1.021` Keep built-in availability as a single optional callable on `BuiltinSkill`; do not introduce a separate `SkillRequirement` abstraction in V1  (deps: P1.020)
- `[REVIEW @codex-charged-perovskite #11061]` `P1.022` Implement `BuiltinSkillRegistry` singleton accessor (`.instance()`)  (deps: P1.021)
- `[REVIEW @codex-charged-perovskite #11061]` `P1.023` Implement `register(slug, source_dir, is_available=..., unavailable_reason=None)` — read frontmatter, detect `SKILL.md.template` presence, slug regex validation, raise on duplicate or missing SKILL.md  (deps: P1.022)
- `[REVIEW @codex-charged-perovskite #11061]` `P1.024` Implement `list_all() -> list[BuiltinSkill]`  (deps: P1.022)
- `[REVIEW @codex-charged-perovskite #11061]` `P1.025` Implement `list_available(db) -> list[BuiltinSkill]` — filter by `skill.is_available(db) == True`  (deps: P1.020, P1.024)
- `[REVIEW @codex-charged-perovskite #11061]` `P1.026` Admin callers can derive availability from `BuiltinSkill.is_available` and `unavailable_reason`; no separate `BuiltinSkillStatus` DTO in the registry layer  (deps: P1.025)
- `[REVIEW @codex-charged-perovskite #11061]` `P1.027` Implement `get(slug)` and `reserved_slugs()`  (deps: P1.022)
- `[REVIEW @codex-charged-perovskite #11061]` `P1.028` Unit test: register two slugs with collision → raise; register with missing SKILL.md → raise  (deps: P1.023)
- `[REVIEW @codex-charged-perovskite #11061]` `P1.029` Unit test: `list_available` excludes a skill whose `is_available` returns False and preserves admin-facing unavailable metadata  (deps: P1.025, P1.026)

### 1.4 Bundle validator  (spec §5)

- `[REVIEW @claude-coupled-josephson #11059]` `P1.030` Define `InvalidBundleError(OnyxError)` with `INVALID_REQUEST` code  (deps: P1.012)
- `[REVIEW @claude-coupled-josephson #11059]` `P1.031` Implement `validate_custom_bundle(zip_bytes, slug) -> ManifestMetadata` — zip parse, SKILL.md root check, frontmatter parse, no `*.template`  (deps: P1.030)
- `[REVIEW @claude-coupled-josephson #11059]` `P1.032` Add path-traversal + symlink rejection to `validate_custom_bundle`  (deps: P1.031)
- `[REVIEW @claude-coupled-josephson #11059]` `P1.033` Add per-file + total-size streaming check (defaults 25 MiB / 100 MiB)  (deps: P1.031)
- `[TODO]` `P1.035` Add slug regex + reserved-slug check (uses `BuiltinSkillRegistry.reserved_slugs()`)  (deps: P1.031, P1.027)
- `[REVIEW @claude-coupled-josephson #11059]` `P1.036` Implement `_safe_unzip(zip_bytes, dest)` for defensive re-check at materialization
- `[REVIEW @claude-coupled-josephson #11059]` `P1.037` Implement `compute_bundle_sha256(zip_bytes)` — deterministic over raw bytes
- `[REVIEW @claude-coupled-josephson #11059]` `P1.038` Unit test fixture: valid bundle zip (`SKILL.md` + frontmatter + scripts dir)
- `[REVIEW @claude-coupled-josephson #11059]` `P1.039` Unit test fixture: invalid bundles, one per failure mode (no SKILL.md, traversal entry, symlink, oversized, contains `*.template`)
- `[REVIEW @claude-coupled-josephson #11059]` `P1.040` Unit test: each invalid fixture rejected with the correct error reason  (deps: P1.039, P1.031-P1.033, P1.035)
- `[REVIEW @claude-coupled-josephson #11059]` `P1.041` Unit test: `compute_bundle_sha256` deterministic across two zips of same content with different timestamps  (deps: P1.037)

### 1.5 Materializer  (spec §6)

- `[TODO]` `P1.050` Define `SkillRenderContext`, `SkillManifestEntry`, `SkillsManifest` Pydantic models  (deps: P1.013)
- `[TODO]` `P1.051` Implement `materialize_skills(dest, user, db, render_ctx) -> SkillsManifest` per §6 algorithm  (deps: P1.025, P1.036, P1.050)
- `[TODO]` `P1.052` Extract `render_template_placeholders` from `agent_instructions.py` into `backend/onyx/skills/render.py`  (deps: P1.014)
- `[TODO]` `P1.053` Public re-exports in `backend/onyx/skills/__init__.py`  (deps: P1.020-P1.052)
- `[TODO]` `P1.054` External-dep unit test: materialize for fixture user with 1 granted custom + 1 not-granted + 2 built-ins → 3 directories + valid `.skills_manifest.json`  (deps: P1.051)
- `[TODO]` `P1.055` External-dep unit test: built-in with `SKILL.md.template` materializes with placeholders rendered  (deps: P1.051, P1.052)

### 1.6 DB ops  (spec §3)

- `[REVIEW @claude-coupled-lattice #11060]` `P1.060` Implement `list_skills_for_user(user, db)` — public OR group-grant query, filtered to **`enabled = True AND deleted_at IS NULL`**. Mirror `fetch_persona_by_id_for_user` at `backend/onyx/db/persona.py:81` (drop the user-direct-grant branch).  (deps: P1.015)
- `[REVIEW @claude-coupled-lattice #11060]` `P1.061` Implement `fetch_skill_for_user(skill_id, user, db)` — same `enabled = True AND deleted_at IS NULL` filter as `list_skills_for_user`.  (deps: P1.060)
- `[REVIEW @claude-coupled-lattice #11060]` `P1.062` Implement `fetch_skill_for_admin(skill_id, db)` — `deleted_at IS NULL` only (admins need disabled skills to re-enable them).  (deps: P1.015)
- `[REVIEW @claude-coupled-lattice #11060]` `P1.063` Implement `list_skills_for_admin(db)` — `deleted_at IS NULL` only (admin UI shows disabled skills; soft-deleted hidden by default).  (deps: P1.015)
- `[REVIEW @claude-coupled-lattice #11060]` `P1.064` Implement `create_skill(slug, name, description, bundle_file_id, bundle_sha256, manifest_metadata, is_public, author_user_id, db) -> Skill`  (deps: P1.015)
- `[REVIEW @claude-coupled-lattice #11060]` `P1.065` Implement `replace_skill_bundle(skill_id, new_bundle_file_id, new_sha256, new_manifest_metadata, db) -> Skill` — returns `old_bundle_file_id` for caller blob cleanup  (deps: P1.015)
- `[REVIEW @claude-coupled-lattice #11060]` `P1.066` Implement `patch_skill(...)` — partial update; re-validate slug uniqueness if changing  (deps: P1.015)
- `[REVIEW @claude-coupled-lattice #11060]` `P1.067` Implement `replace_skill_grants(skill_id, group_ids, db)` — atomic delete + insert in one transaction  (deps: P1.015)
- `[REVIEW @claude-coupled-lattice #11060]` `P1.068` Implement `delete_skill(skill_id, db) -> None` — soft-delete by setting `deleted_at = func.now()`. Blob NOT removed inline; sweep (P5.031–P5.033) handles it after 14 days.  (deps: P1.015)

---

## Phase 2 — Operability (API surface)

**Goal:** fully operable via HTTP. No sandbox wiring, no admin UI — but `curl` works end-to-end.
**Effort:** M  ·  **Depends:** Phase 1 done

### 2.1 Universal admin router  (spec §7)

- `[TODO]` `P2.001` Create `backend/onyx/server/features/skills/__init__.py`
- `[TODO]` `P2.002` Create `backend/onyx/server/features/skills/api.py` with router scaffolding
- `[TODO]` `P2.003` Define Pydantic response models: `SkillsAdminList`, `BuiltinSkillAdmin`, `CustomSkillAdmin`, `SkillsForUser`, `SkillSummary`  (deps: P2.002)
- `[TODO]` `P2.004` Implement `GET /api/admin/skills` — combine `registry.list_all()` (evaluating each built-in's `is_available(db)`) + `list_skills_for_admin(db)`  (deps: P2.003, P1.026, P1.063)
- `[TODO]` `P2.005` Implement `POST /api/admin/skills/custom` — full create flow per §7 (validate → save blobs → row → grants); inline blob cleanup on failure  (deps: P2.003, P1.031, P1.064, P1.067)
- `[TODO]` `P2.006` Implement `PATCH /api/admin/skills/custom/{id}` — slug/name/description/is_public/enabled; re-validate slug uniqueness on slug change  (deps: P2.003, P1.066)
- `[TODO]` `P2.007` Implement `PUT /api/admin/skills/custom/{id}/bundle` — replace flow; delete old blobs AFTER commit  (deps: P2.003, P1.031, P1.065)
- `[TODO]` `P2.008` Implement `PUT /api/admin/skills/custom/{id}/grants` — atomic group_ids replacement  (deps: P2.003, P1.067)
- `[TODO]` `P2.009` Implement `DELETE /api/admin/skills/custom/{id}` — soft-delete (do not delete blobs; sweep handles)  (deps: P2.003, P1.068)

### 2.2 User router  (spec §7)

- `[TODO]` `P2.020` Implement `GET /api/skills` — built-ins (filtered by `list_available`) + customs visible to user  (deps: P2.003, P1.025, P1.060)

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
- `[TODO]` `P3.004` Register `image-generation` built-in with `is_available=lambda db: get_default_image_generation_config(db) is not None` and `unavailable_reason`  (deps: P3.002, P1.020)
- `[TODO]` `P3.005` Call `register_craft_builtins(BuiltinSkillRegistry.instance())` from `backend/onyx/main.py` startup (after DB init, before `app.include_router`)  (deps: P3.003, P3.004)
- `[TODO]` `P3.006` Startup integration test: `assert registry.get("pptx") is not None`; `list_available` excludes `image-generation` when no provider is configured  (deps: P3.005)

### 3.2 Render-context helper

- `[TODO]` `P3.010` Implement `render_accessible_cc_pairs(user, db)` helper — confirm/reuse from `search.md`; if new, implement using existing `get_connector_credential_pairs_for_user`

### 3.3 Generic bundle pipeline (`sandbox-file-sync.md`)

These tasks stand up the reusable bundle abstraction. Skills is the first consumer (§3.4–§3.4b); user_library and future org-files plug in later via the same interface. Implement these before §3.4.

- `[TODO]` `P3.020` Create `backend/onyx/sandbox_sync/` package: `bundle.py` (`SandboxBundle` ABC, `BundleEntry`, `SandboxContext`), `registry.py` (`BundleRegistry`), `tarball.py` (streaming tar builder over BundleEntry iterator).
- `[TODO]` `P3.021` Implement `backend/onyx/sandbox_sync/enqueue.py` — `enqueue_change(db, tenant_id, bundle_key, user_id=None)`. If the bundle's `cache_on_mutation=True`, synchronously materialize and write tarball bytes to Redis under `bundle:tar:{tenant}:{bundle_key}:{last_modified_iso}` with 15-min TTL, then enqueue `propagate_bundle_change`.
- `[TODO]` `P3.022` Implement `backend/onyx/sandbox_sync/cache.py` — Redis-backed tarball cache (get / materialize_and_store) + hit/miss metrics.
- `[TODO]` `P3.023` Implement Celery `@shared_task(name="propagate_bundle_change", expires=60)` in `backend/onyx/background/celery/tasks/sandbox_sync/propagate.py` — calls `bundle.pod_label_selector(...)`, lists pods, fans out `refresh_pod_bundle.delay(pod, bundle_key)` per pod.
- `[TODO]` `P3.024` Implement Celery `@shared_task(name="refresh_pod_bundle", expires=120)` in `backend/onyx/background/celery/tasks/sandbox_sync/refresh.py` — single `kubectl exec` invoking `/usr/local/bin/refresh-bundle <bundle_key>`. Log non-zero exit and bail (lifecycle triggers reconcile).
- `[TODO]` `P3.025` Add `GET /api/internal/sandbox/{sandbox_id}/bundles/{bundle_key}/tarball` to `backend/onyx/server/internal/sandbox_bundles.py`. Resolves sandbox → `SandboxContext`. `If-Modified-Since` → 304 short-circuit. On a populated cache key (write-through bundles), stream cached bytes. Else stream `tar(bundle.materialize(...))`. Always sets `Last-Modified`.
- `[TODO]` `P3.026` Add `POST /api/sandbox/{sandbox_id}/refresh` to the existing sandbox router. Auth via standard user session. Resolves sandbox → pod name. Invokes `refresh_pod_bundle` (or sync kubectl-exec) for each registered bundle.
- `[TODO]` `P3.027` Implement pod-token auth for `/api/internal/sandbox/*` — bearer token minted at sandbox provisioning, validated against active-sandbox table. If Onyx already has a pod→api_server auth path, reuse it.
- `[TODO]` `P3.028` Inject `SANDBOX_TOKEN` + `SANDBOX_ID` + `ONYX_API_URL` env vars into the sandbox pod spec at provisioning (`kubernetes_sandbox_manager.py` — pod creation).
- `[TODO]` `P3.029` Add `onyx.app/tenant-id=<id>` label to sandbox pods at provisioning, alongside the existing `onyx.app/sandbox-id` (`kubernetes_sandbox_manager.py:619`). Shared across all bundle consumers.

### 3.4 In-pod refresh-bundle script + entrypoint hook (`sandbox-file-sync.md`)

- `[TODO]` `P3.030` Create `backend/onyx/server/features/build/sandbox/kubernetes/docker/refresh-bundle` — POSIX-sh script. Hardcoded case statement maps bundle_key → mount_path (`skills` → `/skills`, `user_library` → `/workspace/files/user_library`). Uses `flock` for race safety, sends `If-Modified-Since` header from `/var/lib/sandbox/<key>.last-modified`, on 200 extracts to sibling dir + atomic `mv`-swap, writes the new `Last-Modified` response header back to the sentinel file.
- `[TODO]` `P3.031` Update the sandbox container entrypoint to run `refresh-bundle skills && refresh-bundle user_library` (iterating the registered bundles) before `exec`ing the agent. Same code path serves both fresh boot and snapshot restore.
- `[TODO]` `P3.032` Mount a pod-level emptyDir volume at `/skills/` in the pod spec. (user_library still mounts at its existing path.)
- `[TODO]` `P3.033` Frontend "Refresh sandbox" button in the Craft sandbox menu, wired to `POST /api/sandbox/{sid}/refresh`. Place near other sandbox-control actions, not as a primary action.

### 3.4b Skills consumer of the bundle pipeline (`spec §9.7`)

The skills-specific consumer plugged into the generic pipeline from §3.3. ~1-3 sec end-to-end on the happy path; lifecycle triggers reconcile the ~5% push-failure tail.

- `[TODO]` `P3.035` Implement `SkillsBundle` in `backend/onyx/sandbox_sync/bundles/skills.py`: `bundle_key = "skills"`, `mount_path = "/skills/"`, `cache_on_mutation = True`. `materialize` walks built-ins on disk + reads custom skill zip blobs from FileStore (via `file_store.read_file(skill.bundle_file_id)`, streaming members directly into the output tar — no on-disk unpack). Applies template rendering via `materialize_skills(...)` from §6. `pod_label_selector(tenant_id, _)` returns `onyx.app/tenant-id={tenant_id}`. `last_modified` returns `SELECT MAX(updated_at) FROM skill WHERE tenant_id=...`.  (deps: P3.020–P3.025)
- `[TODO]` `P3.036` Register `SkillsBundle` in `backend/onyx/sandbox_sync/bundles/__init__.py` (called at import time).
- `[TODO]` `P3.040x` Hook `enqueue_change(db, tenant_id, "skills")` at the 5 mutation endpoints AFTER their respective commits:
  - POST `/api/admin/skills/custom`
  - PATCH `/api/admin/skills/custom/{id}`
  - PUT `/api/admin/skills/custom/{id}/bundle`
  - PUT `/api/admin/skills/custom/{id}/grants`
  - DELETE `/api/admin/skills/custom/{id}`
- `[TODO]` `P3.041x` Integration test: admin upload → wait ~5 sec → assert pod's `/skills/` reflects new content AND agent's `skill` tool lists it on the next turn.
- `[TODO]` `P3.042x` Failure test: simulate kubectl-exec failure during push → call `POST /api/sandbox/{sid}/refresh` → assert pod reconciles.
- `[TODO]` `P3.042y` Write-through cache test: provision two sandboxes in same tenant, instrument `SkillsBundle.materialize` with a call counter, upload a skill. After all pods finish refreshing, assert `materialize` ran exactly once (the upload-time call) and the second pod served from cache.

### 3.5 Per-session symlink  (spec §9)

- `[TODO]` `P3.040` Implement `_setup_session_skills_symlink(session_path)` helper — creates/recreates `.agents/skills` symlink → `/skills/`. Used by both K8s and local backends.
- `[TODO]` `P3.041` Call `_setup_session_skills_symlink(...)` from `setup_session_workspace` (replaces the legacy `ln -sf /workspace/skills` block at `kubernetes_sandbox_manager.py:1338-1340`).
- `[TODO]` `P3.042` Call `_setup_session_skills_symlink(...)` from `_regenerate_session_config` at `kubernetes_sandbox_manager.py:1736` (so resumed sessions get the symlink too).
- `[TODO]` `P3.043` Remove `directory_manager.setup_skills(...)` and its `_skills_path` constructor argument. Update callers at `directory_manager.py:78` and `:309`.

### 3.6 Local backend refresh path  (spec §9)

- `[TODO]` `P3.050` For dev/local: invoke `refresh-bundle skills` as a subprocess (same script, no kubectl needed). Alternative: bind-mount a host path that the materializer writes to directly into the sandbox container at `/skills/`.
- `[TODO]` `P3.051` Verify the local backend's session-setup uses `_setup_session_skills_symlink(...)`.

### 3.7 Panel data source  (spec §11)

- `[TODO]` `P3.060` Create `backend/onyx/server/features/build/skills/api.py` with router scaffolding
- `[TODO]` `P3.061` Implement `GET /api/build/sessions/{id}/skills` — reads `.skills_manifest.json` from session (`.agents/skills/.skills_manifest.json` → `/skills/.skills_manifest.json` via symlink), returns `SkillsManifest`  (deps: P3.060, P3.070 sandbox-helper)
- `[TODO]` `P3.062` Implement `GET /api/build/sessions/{id}/skills/{slug}/content` — returns rendered SKILL.md text  (deps: P3.060)
- `[TODO]` `P3.063` Wire build-feature router into Onyx app  (deps: P3.060-P3.062)

### 3.8 Sandbox file-read helper

- `[TODO]` `P3.070` Add `read_file_from_session(session, path) -> str` to `SandboxManagerBase`
- `[TODO]` `P3.071` Implement `read_file_from_session` in `KubernetesSandboxManager` (kubectl exec cat)  (deps: P3.070)
- `[TODO]` `P3.072` Implement `read_file_from_session` in local sandbox manager (direct FS read)  (deps: P3.070)

### 3.9 AGENTS.md skill section — drop entirely  (spec §10)

OpenCode's native `skill` tool handles inventory; AGENTS.md inlining is duplicative. Empirically verified 2026-05-12 — OpenCode rescans `.agents/skills/` per turn.

- `[TODO]` `P3.080` Remove `{{AVAILABLE_SKILLS_SECTION}}` placeholder from `AGENTS.template.md`
- `[TODO]` `P3.081` Remove `available_skills_section = build_skills_section(skills_path)` and the `content.replace("{{AVAILABLE_SKILLS_SECTION}}", ...)` line at `agent_instructions.py:481-495`
- `[TODO]` `P3.082` Delete `build_skills_section(skills_path)` at `agent_instructions.py:267-296`
- `[TODO]` `P3.083` Delete `_scan_skills_directory` (unused after P3.082)
- `[TODO]` `P3.084` Delete `_skills_cache` and `_skills_cache_lock` (unused after P3.082)
- `[TODO]` `P3.085` Verify no other call sites reference `build_skills_section` or `{{AVAILABLE_SKILLS_SECTION}}`
- `[TODO]` `P3.086` Smoke test: launch a session, confirm the agent lists current skills correctly via OpenCode's `skill` tool without the inlined section

### 3.10 Dockerfile

- `[TODO]` `P3.090` Remove `COPY skills/ /workspace/skills/` from `backend/onyx/server/features/build/sandbox/kubernetes/docker/Dockerfile:99`
- `[TODO]` `P3.091` Remove `RUN mkdir -p /workspace/skills` from same Dockerfile
- `[TODO]` `P3.092` Add `COPY refresh-bundle /usr/local/bin/refresh-bundle` + `chmod +x` + `RUN mkdir -p /skills` (refresh-bundle is the shared in-pod script from `sandbox-file-sync.md`, not skills-specific)
- `[TODO]` `P3.093` Update sandbox image build pipeline (the on-disk skills dir in the Onyx repo stays — read at runtime by api_server materializer)

### 3.11 Integration tests

- `[TODO]` `P3.100` Create `backend/tests/integration/tests/skills/` directory
- `[TODO]` `P3.101` Integration test `test_skill_materialization.py`: session with 1 granted + 1 not-granted custom → verify `.agents/skills/<slug>/SKILL.md`, manifest contents, AGENTS.md inline list  (deps: P3.041, P3.080)
- `[TODO]` `P3.102` Integration test: built-in `SKILL.md.template` renders with placeholders expanded inside the session  (deps: P3.101)
- `[TODO]` `P3.103` Integration test `test_live_skill_propagation.py`: start session A, agent reads SKILL.md for X; admin replaces X bundle; trigger refresh; re-read → new content; AGENTS.md still shows pre-replace inventory in the same conversation  (deps: P3.030, P3.020)

---

## Phase 4 — Admin UI

**Goal:** admins manage skills without `curl`.
**Effort:** L (1+ week)  ·  **Depends:** Phase 2 endpoints stable  ·  **Parallel with Phase 3**

### 4.1 Page shell + routing

- `[TODO]` `P4.000` **Register SWR keys FIRST** in `web/src/lib/swr-keys.ts` — repo convention forbids inline `useSWR("...")` strings (~170 existing `SWR_KEYS.*` refs, zero inline). Add: `skills`, `adminSkills`, `adminSkillsCustom`, `adminSkillsCustomById(id)`, `adminSkillsCustomBundle(id)`, `adminSkillsCustomGrants(id)`, `buildSessionSkills(sessionId)`, `buildSessionSkillContent(sessionId, slug)`. Mutation handlers in P4.020-P4.053 will call `mutate(SWR_KEYS.adminSkills)` after success. Blocks every frontend component task that follows.
- `[TODO]` `P4.001` Create `web/src/app/admin/skills/page.tsx` using `SettingsLayouts.Root`/`.Header`/`.Body` pattern from `AgentsPage.tsx`  (deps: P4.000)
- `[TODO]` `P4.002` Add Skills entry to admin nav in `web/src/lib/admin-routes.ts`
- `[TODO]` `P4.003` Frontend type definitions matching backend Pydantic models (`BuiltinSkillAdmin`, `CustomSkillAdmin`, etc.)  (deps: P2.003)

### 4.2 List view

- `[TODO]` `P4.010` `web/src/app/admin/skills/SkillsList.tsx` — table renderer using `@opal/components` Table
- `[TODO]` `P4.011` `web/src/app/admin/skills/SkillRow.tsx` — icon + name + slug + description + source badge + access + action menu
- `[TODO]` `P4.012` `web/src/app/admin/skills/SourceBadge.tsx` — Platform / Custom pill
- `[TODO]` `P4.013` Access column rendering: `Available` for satisfied built-ins, `Needs setup · Configure →` for unmet; frontend derives configure routes from built-in slugs  (deps: P4.011)
- `[TODO]` `P4.014` Search + filters: by name/slug, source (All/Platform/Custom), availability
- `[TODO]` `P4.015` Loading / error / empty states

### 4.3 Upload modal

- `[TODO]` `P4.020` `UploadSkillModal.tsx` — file picker + slug/name/description/visibility fields + Trust-check banner
- `[TODO]` `P4.021` Client-side frontmatter pre-fill: parse uploaded zip with `jszip`, extract SKILL.md frontmatter, populate name/description fields
- `[TODO]` `P4.022` Slug regex validation client-side
- `[TODO]` `P4.023` Submit → multipart POST to `/api/admin/skills/custom`; on success close modal + refetch list; on failure show inline error from `OnyxError.detail`  (deps: P2.005)
- `[TODO]` `P4.024` **Pre-upload SKILL.md preview pane** — right-side panel in the modal showing parsed-and-markdown-rendered `SKILL.md` + file list of the rest of the bundle. Reuse the `jszip` reader from P4.021 (no new endpoint). Include inline soft-attestation note: "This text is read by the agent inside user sessions; confirm it reflects your intent."  (deps: P4.020, P4.021)

### 4.3b Example skill download (empty-state aid)

- `[TODO]` `P4.025` Ship `backend/onyx/server/features/skills/example_bundle/` with a minimal `hello-world` skill (SKILL.md with frontmatter + one short script). Zipped into the deploy artifact at build time.
- `[TODO]` `P4.026` `GET /api/admin/skills/example-bundle` — static endpoint returning the bundle as `application/zip`. Admin-only auth.
- `[TODO]` `P4.027` Empty-state card in `SkillsList.tsx`: when there are zero custom skills, render an inline "Get started" card with a `Download example skill (.zip)` link/button alongside `Upload skill`. Hide the card once any custom skill exists.

### 4.4 Visibility picker (shared component)

- `[TODO]` `P4.030` `VisibilityPicker.tsx` — radio: Private / Org-wide / Specific groups + conditional group multi-select
- `[TODO]` `P4.031` Group multi-select uses existing Onyx groups API (reuse from Persona admin)
- `[TODO]` `P4.032` Reuse `VisibilityPicker` in upload modal + standalone grants editor

### 4.5 Built-in detail drawer

- `[TODO]` `P4.040` `BuiltinDetailDrawer.tsx` — read-only metadata (name, slug, description, source path, files, frontmatter)
- `[TODO]` `P4.041` Availability section: show `Available` or the built-in's `unavailable_reason`; frontend derives any Configure button route from the built-in slug  (deps: P4.040)
- `[TODO]` `P4.042` Section omitted entirely if the built-in is available and has no setup copy/link

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

### 5.4 Sweep: orphan blobs + aged soft-deletes  (spec §16)

- `[REVIEW @claude-collapsing-meson #11064]` `P5.030` Create `backend/onyx/background/celery/tasks/skills/__init__.py`
- `[REVIEW @claude-collapsing-meson #11064]` `P5.031` Create `backend/onyx/background/celery/tasks/skills/tasks.py` with `@shared_task(name="cleanup_orphaned_skill_blobs")` (must include `expires=3600` per `CLAUDE.md`)
- `[REVIEW @claude-collapsing-meson #11064]` `P5.032` Implement `_orphan_skill_blob_ids(db, older_than)` — FileStore records with `origin = SKILL_BUNDLE`, `created_at < now() - older_than`, whose IDs are NOT referenced by any `skill.bundle_file_id` (crash-recovery path)
- `[REVIEW @claude-collapsing-meson #11064]` `P5.033` Implement `_aged_soft_deleted_skills(db, older_than)` — `Skill` rows with `deleted_at IS NOT NULL AND deleted_at < now() - older_than` (lifecycle-cleanup path)
- `[REVIEW @claude-collapsing-meson #11064]` `P5.034` Task body: for each orphan blob, delete from FileStore; for each aged soft-deleted skill, delete its `bundle_file_id` blob THEN hard-delete the row
- `[REVIEW @claude-collapsing-meson #11064]` `P5.035` Add weekly beat schedule entry
- `[REVIEW @claude-collapsing-meson #11064]` `P5.036` Unit test: orphan blob older than 14 days → deleted by task
- `[REVIEW @claude-collapsing-meson #11064]` `P5.037` Unit test: skill with `deleted_at` older than 14 days → blob deleted AND row hard-deleted
- `[REVIEW @claude-collapsing-meson #11064]` `P5.038` Integration test: soft-delete a skill, run sweep immediately → blob NOT deleted, row still present with `deleted_at` set; advance time by 15 days → run sweep → blob deleted, row gone

### 5.5 Per-session skills UI  (spec §11)

- `[TODO]` `P5.040` `SkillsPanel.tsx` in Craft session UI — fetches `/api/build/sessions/{id}/skills`, renders read-only list  (deps: P3.061)
- `[TODO]` `P5.041` Skill card sub-component: icon + name + description + source badge
- `[TODO]` `P5.042` Click card → drawer showing rendered SKILL.md preview via `GET .../skills/{slug}/content`  (deps: P3.062)
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

### 6.1 Snapshot semantics verification  (spec §12)

- `[TODO]` `P6.001` Confirm snapshot tarball **excludes** `/skills/` (it's a separate pod-level mount, not part of `/workspace/sessions/`). Verify in `backend/onyx/server/features/build/sandbox/manager/snapshot_manager.py`.
- `[TODO]` `P6.002` Verify resume path does NOT re-materialize per-session. The pod's `/skills/` is kept fresh by the background refresh loop; resume just needs the symlink (P3.042).
- `[TODO]` `P6.003` Add invariant docstring to `backend/onyx/skills/__init__.py`: `"Skill content and inventory are both live (~1-3 sec typical via event-driven push through the bundle pipeline; lifecycle triggers — session setup, snapshot restore, manual refresh — reconcile the failure tail; OpenCode rescans per turn)."`
- `[TODO]` `P6.004` Integration test `test_snapshot_excludes_skills.py`: pause session A → inspect snapshot tar, confirm no `/skills/` content; resume → `.agents/skills` is a symlink to `/skills/` resolving to current admin state

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
- `[SKIP]` `V15.011` Shared/bundled availability-check modules
- `[SKIP]` `V15.012` In-browser skill editor
- `[SKIP]` `V15.013` Slug rename history table
- `[SKIP]` `V15.014` **Skill author tooling** — CLI scaffolder (`onyx-cli skill new`), local validator (`onyx-cli skill validate`), `--dry-run` upload mode, format-spec docs page. V1 assumes a developer hand-crafts the zip; the example-skill download (P4.025–P4.027) is the V1 cold-start aid. Pairs with V15.015 (user-authored skills) but useful for admin-authored too.
- `[SKIP]` `V15.015` **User-authored skills (third tier)** — user-side `POST /api/skills` upload with per-user quota, `Skill__User` brought back for user→user sharing, skill promotion workflow (request/approve table + admin UI tab), `source = "user"` on the manifest discriminator (V1 already designs for this), and a §18 threat-model expansion since the lateral-attacker model becomes first-class. ~+4–6 weeks after V1.
- `[SKIP]` `V15.016` **Skill audit history** — `skill_audit_event (id, skill_id, tenant_id, actor_user_id, event_type, payload jsonb, created_at)` table in the private schema, write path on every mutation endpoint (single helper ~10 lines), admin UI "Activity" tab with filtering by skill/date, retention policy (default 13 months). Compliance-grade; strictly additive to V1.

---

## Decisions log

_(Append cross-cutting decisions or clarifications that come up during implementation. Don't update the spec mid-flight — record here, surface to the spec at the end of the phase.)_

- 2026-05-13: Phase 1 work is being split across multiple stacked PRs branching off `skills-phase-1`.
