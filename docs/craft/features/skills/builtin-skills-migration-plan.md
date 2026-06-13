# Built-in Skills Migration Plan

Migrate the three built-in skills (`pptx`, `image-generation`, `company-search`) out of
the baked-in sandbox Docker image and into the same push system used for custom skills.
After this change, all skills land at `/workspace/managed/skills/{slug}/` via
`push_to_sandbox`.

No database migration is required — built-in skills remain purely in-memory in the
`BuiltinSkillRegistry` singleton. Only custom skills use the `skill` table.

## Issues to Address

1. **Built-in skills baked into the Docker image** aren't updateable without a full image
   rebuild + pod restart. Push-based delivery lets us ship changes instantly.

2. **Two delivery paths** to maintain: built-ins via `COPY skills/ /workspace/skills/`
   (Dockerfile L92) + per-session symlink; customs via FileStore + push. Unifying them
   means one code path.

3. **`BuiltinSkillRegistry` is defined but never populated.** The API calls `.instance()`,
   `.list_available()`, `.reserved_slugs()` — nothing calls `.register()` outside tests.

4. **company-search is dynamic** — its `SKILL.md.template` must be rendered per-user with
   the user's available connector sources. The push system has to handle template
   rendering, not just static bundles.

5. **AGENTS.md `{{AVAILABLE_SKILLS_SECTION}}`** scans the on-disk skills directory. Once
   skills are pushed (not baked), that directory is empty at AGENTS.md generation time.
   The section must come from the registry + DB instead.

## Important Notes

- **pptx (~1.4 MB)** ships scripts, XSD schemas, and supporting markdown. Its `SKILL.md`
  references relative paths like `.opencode/skills/pptx/scripts/thumbnail.py`. The
  symlink target changes (`/workspace/skills` → `/workspace/managed/skills`), but the
  relative-path traversal is unchanged, so these references keep working.
- **K8s manager hardcodes `/workspace/skills/pptx/scripts/preview.py`** at
  `kubernetes_sandbox_manager.py:2012`. This bypasses the symlink and must be updated
  to `/workspace/managed/skills/pptx/scripts/preview.py`.
- **`push_dynamic_skills` has 3 call sites**: `session/manager.py:600`,
  `session/manager.py:661`, `api/sessions_api.py:508`.
- **Sandbox managers are intentionally DB-agnostic.** `DirectoryManager` and
  `KubernetesSandboxManager` don't receive `db_session` or `User`. Phase 5 pre-builds the
  skills section in `SessionManager` and passes it down as a string.
- **`SKILLS_TEMPLATE_PATH`** resolves to
  `backend/onyx/server/features/build/sandbox/kubernetes/docker/skills/`. The path exists
  inside the **API server** container too — the backend Dockerfile copies all of `./onyx`
  to `/app/onyx`. So the API server can read built-in skill source files directly from
  disk at push time; no need to round-trip them through FileStore.
- **Local sandbox `write_files_to_sandbox`** strips `/workspace/` from `mount_path`, so
  pushed files land at `$sandbox_path/managed/skills/`. The local symlink target must be
  `sandbox_path / "managed" / "skills"`.
- **`__pycache__` directories** must be excluded when walking built-in source dirs (the
  current Dockerfile already does this via `--exclude=__pycache__`).

## Implementation Strategy

### Phase 1: Register built-in skills at boot

**Goal:** Populate `BuiltinSkillRegistry` so the API returns built-ins.

1. Create `backend/onyx/skills/builtins.py` with a `register_builtins()` function that
   calls `registry.register()` for each of `pptx`, `image-generation`, `company-search`.
   - All three use `is_available=lambda _: True`. The company-search template's "no
     sources" branch already handles the empty-CC-pairs case gracefully — no need for an
     `is_available` gate.
   - `source_dir = Path(SKILLS_TEMPLATE_PATH) / slug`.

2. Call `register_builtins()` in `main.py`'s `lifespan()`, before the
   `if not MULTI_TENANT` branch around L362. Registration is process-wide (not
   tenant-scoped) and doesn't need DB access, so it sits outside the multi-tenant fork.

3. Verify: `GET /admin/skills` and `GET /skills` return the three built-ins.

### Phase 2: Read built-in skills from disk during push

**Goal:** `build_skills_fileset_for_user` returns a `FileSet` (`dict[str, bytes]`) with
both custom and built-in skills.

The API server container already has built-in skill files on disk at
`SKILLS_TEMPLATE_PATH`. The push code reads them directly — no FileStore round-trip.

1. Move `render_company_search_skill` from `sandbox/skills/rendering.py` to a new
   `skills/rendering.py`. The function has no sandbox-specific imports, so the move is
   mechanical.

2. Extend `build_skills_fileset_for_user` in `skills/push.py`:
   - Iterate `BuiltinSkillRegistry.instance().list_available(db_session)`.
   - **Static built-ins** (`has_template=False`): walk `skill.source_dir.rglob("*")`,
     skipping directories named `__pycache__` and any dotfiles. For each regular file,
     compute a relative path and add `f"{slug}/{rel}": path.read_bytes()` to the FileSet.
   - **Template built-ins** (`has_template=True`, currently only `company-search`):
     dispatch on slug, call `render_company_search_skill(db_session, user, source_dir)`,
     and add `f"{slug}/SKILL.md": rendered.content.encode("utf-8")` to the FileSet.
     (Note: `RenderedSkillFile.content` is `str`; `FileSet` values are `bytes`, so the
     `.encode("utf-8")` is required.) A simple `if slug == "company-search"` dispatch is
     fine — premature to design a plugin system for one template skill.

3. Remove `SessionManager.push_dynamic_skills()` and update **all 3 call sites** to call
   `hydrate_sandbox_skills(sandbox_id, user, db_session)` instead:
   - `session/manager.py:600` (in `create_session__no_commit`)
   - `session/manager.py:661` (in `get_or_create_empty_session`) — fetch the `User` via
     `fetch_user_by_id(db_session, user_id)` since only `user_id` is in scope here.
   - `api/sessions_api.py:508` (in the session restore endpoint).

### Phase 3: Wire skills push into session setup

**Goal:** New sessions get all skills (built-in + custom) pushed to
`/workspace/managed/skills/`, and the per-session symlink points there.

1. The 3 call-site updates in Phase 2 step 3 already wire push into setup. No additional
   call-site work here.

2. **K8s setup script** (`kubernetes_sandbox_manager.py:1146-1151`): change
   `ln -sf /workspace/skills {session_path}/.opencode/skills` to
   `ln -sf /workspace/managed/skills {session_path}/.opencode/skills`. Drop the
   `if [ -d /workspace/skills ]` guard — the directory is gone after Phase 5.

3. **Local sandbox manager** (`local_sandbox_manager.py:368-369`): change
   `skills_target=sandbox_path / "skills"` to
   `skills_target=sandbox_path / "managed" / "skills"`. (Local push lands files at
   `$sandbox_path/managed/skills/` after the `/workspace/` strip in
   `write_files_to_sandbox`.) Also ensure that directory exists before the symlink is
   created.

4. **K8s manager hardcoded pptx path** (`kubernetes_sandbox_manager.py:2012`): change
   `/workspace/skills/pptx/scripts/preview.py` to
   `/workspace/managed/skills/pptx/scripts/preview.py`.

5. `/workspace/managed/` already exists in the sandbox image (Dockerfile L61:
   `mkdir -p /workspace/sessions /workspace/templates /workspace/managed`).

### Phase 4: Update AGENTS.md skills section

**Goal:** `{{AVAILABLE_SKILLS_SECTION}}` comes from the registry + DB, not a filesystem
scan. Sandbox managers stay DB-agnostic.

1. In `agent_instructions.py`, replace `build_skills_section(skills_path)` with
   `build_skills_section_from_data(builtins, customs)` that formats pre-queried
   names + descriptions. No filesystem access, no caching.

2. Change `generate_agent_instructions` to take a `skills_section: str` parameter
   instead of `skills_path: Path`. Update both callers
   (`DirectoryManager.setup_agent_instructions` at L283-294 and
   `KubernetesSandboxManager._load_agent_instructions` at L287-298) to accept and forward
   it.

3. Thread the parameter from `SessionManager` through `setup_session_workspace()` and
   the sandbox managers' `setup_agent_instructions`/`_load_agent_instructions`. In
   `SessionManager`, before calling `setup_session_workspace`:
   - `builtins = BuiltinSkillRegistry.instance().list_available(db_session)`
   - `customs = list_skills_for_user(user, db_session)`
   - `skills_section = build_skills_section_from_data(builtins, customs)`

4. Remove `_skills_cache`, `_skills_cache_lock`, `_scan_skills_directory`, and
   `extract_skill_description` from `agent_instructions.py` — all dead after the
   signature change.

### Phase 5: Remove dead infrastructure

**Goal:** Clean up everything the push system replaces.

1. **Dockerfile L92**: remove `COPY --exclude=__pycache__ skills/ /workspace/skills/`.

2. **`LocalSandboxManager.provision()` L212-218**: remove the
   `shutil.copytree(skills_source_path, sandbox_skills)` block.

3. **`DirectoryManager.setup_skills()`**: remove. Only callers are the local sandbox
   manager (Phase 3 step 3 inlines the equivalent) and tests.

4. **`DirectoryManager._skills_path` / `skills_source_path`**: remove if no remaining
   callers after step 3. Both `DirectoryManager` constructors still pass it for now to
   keep diffs small; can be removed in a follow-up.

5. **`sandbox/skills/rendering.py`** and the `sandbox/skills/` package: delete after
   Phase 2 step 1 moves the function out.

6. **`SKILLS_TEMPLATE_PATH`**: keep — Phase 2 step 2 reads from it.

## Tests

### Unit Tests

- **`test_register_builtins.py`** — all three skills registered with the right metadata
  (slug, name, description, `has_template`, `source_dir`). Use
  `BuiltinSkillRegistry._reset_for_testing()` for isolation.
- **`test_build_fileset_with_builtins.py`** — given a registered registry, mock CC pair
  query and verify `build_skills_fileset_for_user` returns:
  - Static built-ins as directory trees (multiple files per slug).
  - `company-search/SKILL.md` rendered with sources section (and the "no sources" branch
    when CC pairs are empty).
  - `__pycache__` paths excluded.
- **`test_build_skills_section_from_data.py`** — formatter output is correct for empty,
  built-ins-only, customs-only, and mixed inputs.

### Integration Tests

Extend `tests/integration/tests/skills/`:

- **`test_builtin_skills_listed.py`** — `GET /skills` and `GET /admin/skills` return the
  three built-ins with `source: "builtin"`.
- **`test_builtin_and_custom_coexist.py`** — create a custom skill, verify both
  built-ins and the custom appear in the response.

### Manual / E2E Verification

- After deploy, create a sandbox session and confirm:
  - `.opencode/skills/` symlink resolves to `/workspace/managed/skills/`.
  - All three built-in slugs present as subdirectories with expected files.
  - `python .opencode/skills/pptx/scripts/thumbnail.py --help` runs (proves pptx
    internal path references still resolve).
  - `company-search/SKILL.md` contains rendered sources matching the user's CC pairs.
