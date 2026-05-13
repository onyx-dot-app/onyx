# Part 4: Craft Integration — Implementation Plan

> Parent design: [search-design.md](search-design.md) (Part 4)

## Objective

Wire onyx-cli into the Craft sandbox as the primary search tool, replacing the legacy `files/` corpus sync. Provision per-user PATs with encrypted-at-rest storage, bundle the CLI binary, create a `company-search` skill with the user's available sources, and tear down the file-sync infrastructure.

**Parts 1–3 are complete.** Part 1 repositioned onyx-cli as an agent-first tool with `ONYX_SERVER_URL`/`ONYX_PAT` env var support, clean exit codes, and `validate-config`. Part 2 shipped `POST /api/search` backed by the full `SearchTool.run()` pipeline (query expansion, hybrid retrieval, LLM document selection, context expansion). Part 3 added the `search` CLI command wrapping that endpoint with `--source`, `--days`, `--limit`, `--agent-id`, `--raw`, and `--no-query-expansion` flags.

> Key implementation details from Parts 1–3 that affect this plan:
> - **IOStreams pattern** (Part 1): CLI commands use an `IOStreams` struct for testable I/O. Agent-facing output goes to stdout, progress to stderr.
> - **`NullEmitter`** (Part 2): Located in `backend/onyx/chat/emitter.py`. Allows `SearchTool` to run without a streaming consumer.
> - **`message_history`** (Part 2): The search API accepts optional conversation context for better query expansion — not needed for Part 4's skill-based usage, but available.
> - **`doJSONLong()`** (Part 3): CLI uses a 5-minute HTTP timeout for the search endpoint since `SearchTool.run()` includes multiple LLM calls.
> - **Default output** (Part 3): `onyx-cli search` prints `llm_facing_text` (a JSON string with `{"results": [...]}`) to stdout by default. `--raw` prints the full `SearchAPIResponse`.

---

## End State

After this work, the sandbox has one path to company knowledge: `onyx-cli search`.

### What the agent sees

| Resource | Before | After |
|----------|--------|-------|
| Company knowledge | `find`/`grep` over JSON files in `files/` | `onyx-cli search "<query>"` |
| Available sources | Scanned from `files/` directory at setup | Listed in `company-search` SKILL.md, queried from user's connectors |
| Auth | None (files are pre-synced) | Per-user PAT via `ONYX_PAT` env var |
| AGENTS.md guidance | "Start at `files/`, use `find`/`grep`" | "Use the `company-search` skill" |

### What the sandbox contains

| Component | Before | After |
|-----------|--------|-------|
| `/workspace/files/` | S3-synced corpus dump | Gone |
| S3 sidecar container | Runs `aws s3 sync` at pod start | Gone |
| `onyx-cli` binary | Not present | `/usr/local/bin/onyx-cli` |
| `company-search` skill | Does not exist | `.opencode/skills/company-search/SKILL.md` with user's sources |
| `ONYX_PAT` env var | Not set | Per-user PAT, 30-day expiry, re-minted when expired |
| `ONYX_SERVER_URL` env var | Not set | Internal Kube service address |

### PAT lifecycle

One PAT per user, stored encrypted at rest on the `Sandbox` row. Injected as a pod-level env var at provisioning time — all sessions inherit it automatically.

```
Pod provisioned (_create_sandbox_pod)
  └─ _ensure_sandbox_pat(): lock Sandbox row, decrypt or mint PAT
  └─ set ONYX_PAT as container env var in pod spec
  └─ all sessions in this pod inherit the env var

Session setup / resume
  └─ onyx-cli validate-config (uses inherited ONYX_PAT)
  └─ no PAT logic needed — env var is already set

Pod sleeps or is terminated
  └─ PAT and encrypted_pat preserved on Sandbox row
  └─ env var dies with the pod — token safe (encrypted at rest in DB)

Pod re-provisioned (resume or fresh start)
  └─ _ensure_sandbox_pat(): decrypt from Sandbox row, reuse as-is
  └─ set ONYX_PAT on new pod spec

PAT expires (user inactive for 30+ days)
  └─ next provisioning: _ensure_sandbox_pat() detects expiry, mints new PAT

User deactivated
  └─ PAT stops working automatically (fetch_user_for_pat checks User.is_active)
```

Pods don't live long enough for the PAT to expire mid-session — the 1-hour idle timeout terminates the pod, and re-provisioning reuses the same token. No revocation, no per-session token management, no shared files. The only event that triggers a new PAT is natural expiry (30 days).

---

## Current State

- **One pod per user**, shared across sessions. Per-session workspaces at `/workspace/sessions/{session_id}/`.
- **File sync**: S3 `file-sync` sidecar (`peakcom/s5cmd:v2.3.0`) syncs documents to `/workspace/files/`. Main container mounts it read-only. Sessions get a `files/` symlink → `/workspace/files/` (or → `/workspace/demo_data` in demo mode). A standalone `_build_filtered_symlink_script()` helper produces filtered symlinks when `excluded_user_library_paths` is set. `generate_agents_md.py` scans `files/` to populate `{{KNOWLEDGE_SOURCES_SECTION}}` in AGENTS.md. The sidecar stays alive for incremental syncs triggered by `sync_files()`.
- **Skills**: Baked into image at `/workspace/skills/` (two skills: `image-generation`, `pptx`). **Kubernetes** symlinks skills into sessions (`ln -sf /workspace/skills {session_path}/.opencode/skills`). **Local** already symlinks them via `DirectoryManager.setup_skills()` (`session/.opencode/skills` -> `sandbox-root/skills/`).
- **No sandbox auth**: `Sandbox` has no token. The sandbox cannot call the Onyx API.
- **AGENTS.md**: References `files/`, JSON documents, `find`/`grep`. Uses `{{KNOWLEDGE_SOURCES_SECTION}}` placeholder — filled by `generate_agents_md.py` at container runtime (K8s) or by `generate_agent_instructions()` with a `files_path` argument (local).
- **OpenCode config**: Whitelists `/workspace/files` and `/workspace/demo_data` as external directories.
- **Restore path**: `restore_snapshot()` calls `_regenerate_session_config()` (K8s manager, ~line 1748) which creates the `files/` symlink and runs `generate_agents_md.py` — it must receive the same updates as `setup_session_workspace()`.
- **Existing encryption infrastructure**: `EncryptedString` column type handles encrypt-on-write / decrypt-on-read transparently. Already used for connector credentials, LLM API keys, OAuth tokens. Backed by `encrypt_string_to_bytes()` / `decrypt_bytes_to_string()` in `onyx/utils/encryption.py`.

### User Library

User library files (spreadsheets, PDFs, etc.) are raw binaries the agent opens directly with Python libraries — search can't replace them. They're written to S3 via `PersistentDocumentWriter.write_raw_file()` and currently synced to the sandbox by the file-sync sidecar.

Replace the sidecar with a shared `/workspace/user_library/` directory at the pod level. Sync via one-shot `kubectl exec` (running `aws s3 sync`) triggered at session setup and after each upload. Sessions access files directly at `/workspace/user_library/`. Sidecar removal is in PR 3 (pure deletion); the new user library delivery mechanism is in PR 4 (steps 23–28).

This preserves `PersistentDocumentWriter.write_raw_file()` and `S3PersistentDocumentWriter` (the S3 write path) while eliminating the sidecar. The `write_documents()` path (connector document serialization) is dead and removed.

---

## Implementation — Stacked PRs

Each PR is self-contained. Every intermediate state is deployable and leaves the system working.

### PR 1: PAT Infrastructure

Pure backend. No image changes, no session behavior changes. Adds the PAT column and helpers — nothing calls them yet.

**1. Add `pat_type` column to `PersonalAccessToken` and `encrypted_pat` column to `Sandbox`** (`db/models.py`, new migration)

```python
# PersonalAccessToken — distinguish user-created from system-managed PATs
pat_type: Mapped[PatType] = mapped_column(
    Enum(PatType, native_enum=False),
    nullable=False,
    server_default=PatType.USER.value,
)

# Sandbox — store raw PAT encrypted for re-injection on pod provisioning
encrypted_pat: Mapped[SensitiveValue[str] | None] = mapped_column(
    EncryptedString(), nullable=True
)
```

`PatType` is a `str` enum with `USER = "USER"` and `CRAFT = "CRAFT"` (name == value, consistent with `AccountType` and `ProcessingMode`). The `server_default` backfills existing rows automatically. This replaces name-prefix-based filtering with an explicit type column.

`encrypted_pat` on `Sandbox` is nullable. Existing sandbox rows get the PAT on their first pod provisioning after deploy.

**2. Add `ensure_sandbox_pat` helper** (`server/features/build/db/sandbox.py`)

Called during pod provisioning (before `_create_sandbox_pod()`), not during session setup. Returns the raw token for injection as a pod-level env var. Lives in the build DB layer per the project convention that all DB operations go under `db/` directories.

```python
def ensure_sandbox_pat(
    db_session: Session, sandbox: Sandbox, user: User
) -> str:
    """Return a valid PAT for this sandbox, minting if needed."""
    now = datetime.datetime.now(datetime.timezone.utc)

    # Single query: find the user's active craft PAT
    existing_craft_pat = db_session.scalar(
        select(PersonalAccessToken)
        .where(PersonalAccessToken.user_id == user.id)
        .where(PersonalAccessToken.pat_type == PatType.CRAFT)
        .where(
            (PersonalAccessToken.expires_at.is_(None))
            | (PersonalAccessToken.expires_at > now)
        )
    )

    # Reuse if the stored token matches the active PAT
    if existing_craft_pat and sandbox.encrypted_pat:
        raw_token = sandbox.encrypted_pat.get_value(apply_mask=False)
        if hash_pat(raw_token) == existing_craft_pat.hashed_token:
            return raw_token

    # Revoke stale/orphaned craft PAT before minting
    if existing_craft_pat:
        revoke_pat(db_session, existing_craft_pat.id, user.id)

    # Mint fresh PAT — create_pat() flushes (does not commit)
    _pat_record, raw_token = create_pat(
        db_session=db_session,
        user_id=user.id,
        name=f"craft-{user.id}",
        expiration_days=30,
        pat_type=PatType.CRAFT,
    )

    # Store encrypted token and commit atomically with the PAT
    sandbox.encrypted_pat = raw_token
    db_session.commit()
    return raw_token
```

**Transaction boundaries:** `create_pat()` and `revoke_pat()` both flush (not commit) — the caller owns the transaction. `ensure_sandbox_pat()` commits once at the end, persisting the PAT record and `encrypted_pat` atomically. This follows the project-wide convention that DB helpers flush and callers commit.

**`PatType` enum:** `PatType.USER` and `PatType.CRAFT` with `name == value` (uppercase), consistent with `AccountType` and `ProcessingMode`. The `server_default` uses the enum name so SQLAlchemy's non-native enum lookup works correctly on backfilled rows.

The raw token is passed to `_create_sandbox_pod()` which sets it as a container env var (`ONYX_PAT`) in the pod spec. All sessions in the pod inherit it automatically — no per-session token injection needed.

**3. Hide Craft PATs from user's PAT list and guard deletion** (`server/pat/api.py`, `db/pat.py`)

`list_user_pats()` gains an optional `pat_type` filter pushed to the SQL query. The `GET /user/pats` endpoint passes `pat_type=PatType.USER` so CRAFT PATs never leave the DB layer. The `DELETE /user/pats/{id}` endpoint passes `pat_type=PatType.USER` to `revoke_pat()` so users cannot revoke system-managed CRAFT PATs.

`create_pat()` and `revoke_pat()` both flush (not commit) — callers own the transaction boundary. The PAT API endpoints commit explicitly after each operation.

**4. Add `SANDBOX_API_SERVER_URL` config** (`server/features/build/configs.py`)

```python
SANDBOX_API_SERVER_URL = os.environ.get("SANDBOX_API_SERVER_URL", "")
```

No default — must be set when `SANDBOX_BACKEND=kubernetes`. Validated at provisioning time alongside `onyx_pat`.

#### PR 1 file changes

| Action | File |
|--------|------|
| New | `alembic/versions/<new>_add_pat_type_and_encrypted_pat.py` |
| New | `db/enums.py` — `PatType` enum (`USER`, `CRAFT`) |
| Modify | `db/models.py` — add `pat_type` to `PersonalAccessToken`, add `encrypted_pat` to `Sandbox` |
| Modify | `db/pat.py` — add `pat_type` param to `create_pat()`, `list_user_pats()`, `revoke_pat()`; change both to flush instead of commit |
| Modify | `server/features/build/db/sandbox.py` — add `ensure_sandbox_pat()` |
| Modify | `server/features/build/session/manager.py` — add `_provision_sandbox()`, call during pod provisioning |
| Modify | `server/pat/api.py` — filter by `PatType.USER` at DB layer, guard DELETE, migrate to `OnyxError`, add explicit commits |
| Modify | `server/features/build/configs.py` — add `SANDBOX_API_SERVER_URL` |
| Modify | `sandbox/kubernetes/kubernetes_sandbox_manager.py` — accept `onyx_pat` in `_create_sandbox_pod()`, set `ONYX_PAT` + `ONYX_SERVER_URL` as container env vars, validate both at provisioning |
| Modify | `sandbox/base.py` — add `onyx_pat` parameter to `provision()` |
| Modify | `sandbox/local/local_sandbox_manager.py` — add `onyx_pat` parameter (unused) |

#### PR 1 tests

**File:** `tests/external_dependency_unit/craft/test_sandbox_pat.py`

1. **Provisioning.** Create Sandbox, call `ensure_sandbox_pat()`, verify PAT minted with `PatType.CRAFT` and `encrypted_pat` set on Sandbox row.
2. **Reuse.** Call twice, verify same raw token returned (no re-mint).
3. **Expired token.** Create PAT with already-passed expiry, call `ensure_sandbox_pat()`, verify new PAT minted and `encrypted_pat` updated.
4. **Hidden from user list.** Verify `list_user_pats(pat_type=PatType.USER)` does not return CRAFT PATs.
5. **Default type.** Verify `create_pat()` defaults to `PatType.USER`.

---

### PR 2: Search Tool Wiring

Purely additive (~160 lines). Adds the search tool to the sandbox. After this PR, the agent has **both** `onyx-cli search` and `files/` available — no breakage. Old file-based knowledge code (dead after the AGENTS.template.md rewrite) is left in place and cleaned up in PR 3.

**5. Add onyx-cli to Dockerfile** (`sandbox/kubernetes/docker/Dockerfile`)

The binary version must be pinned to the Onyx release — the sandbox image build should pull (or copy) the exact CLI version that matches the backend it talks to. No version mismatch between the CLI and its backend.

```dockerfile
COPY --chown=sandbox:sandbox onyx-cli /usr/local/bin/onyx-cli
RUN chmod +x /usr/local/bin/onyx-cli
```

**6. Add company-search skill template** (`sandbox/kubernetes/docker/skills/company-search/SKILL.md.template`)

Baked into the Docker image at `/workspace/skills/company-search/SKILL.md.template`. After `setup_session_workspace()` creates symlinks from sessions into `/workspace/skills/`, `write_sandbox_file()` overwrites the pod-level `skills/company-search/SKILL.md` with rendered content. All session symlinks point there automatically — no change from symlink to copy.

```markdown
---
name: company-search
description: Search company knowledge using onyx-cli. Returns permissioned, citation-rich results from connected sources.
---

# company-search

Search the company's knowledge base — restricted to what the current user has
permission to see.

## Sources Available in This Session

{{AVAILABLE_SOURCES_SECTION}}

If a source you'd expect isn't listed, it isn't connected for this user — do not
assume it exists.

## Usage

    onyx-cli search "<query>"

| Flag | Description | Example |
|------|-------------|---------|
| `--source` | Filter by source type (comma-separated) | `--source slack,google_drive` |
| `--days` | Only return results from the last N days | `--days 30` |
| `--limit` | Maximum number of results | `--limit 5` |

## Output

Stdout is JSON with a top-level `results` array. Each result has a `document`
field (the citation ID), plus `title`, `content`, `source_type`, and other
metadata. Cite results by their `document` number when referencing them in your
response.
```

**7. Add `build_available_sources_section` and `render_company_search_skill`**

Both functions live in `sandbox/skills/rendering.py`:

`build_available_sources_section(db_session, user)`: Queries `get_connector_credential_pairs_for_user()`, deduplicates by source type, and formats each as `- \`{source_name}\` — {description}`. Descriptions reuse the existing `DocumentSourceDescription` dict from `configs/constants.py` (with improved wording) — no separate `SOURCE_DESCRIPTIONS` duplication.

`render_company_search_skill(db_session, user, skills_dir) -> RenderedSkillFile`: Takes the skills template directory as a parameter (via `SKILLS_TEMPLATE_PATH` config constant). Returns a `RenderedSkillFile` (a NamedTuple with `path` and `content` fields). Raises `FileNotFoundError` if the template is missing.

**8. Add `write_sandbox_file` and `push_dynamic_skills`**

`write_sandbox_file(sandbox_id, path, content)` — new abstract method on `SandboxManager` (`sandbox/base.py`). Writes a file to `/workspace/{path}` on the pod (or sandbox root for local). Used to push rendered dynamic skill content. NOT per-session — writes to the pod-level directory. Existing symlinks make it visible to all sessions.

`push_dynamic_skills(sandbox_id, user_id)` — on `SessionManager` (`session/manager.py`). Resolves the user from UUID, calls `render_company_search_skill()` then calls `write_sandbox_file()` with the result. Catches all exceptions and logs a warning so skill rendering failures don't block session setup. Called after `setup_session_workspace()` in create, reuse, and restore paths. No skill-specific parameters on any manager method — the rendering is fully decoupled from the manager interface.

**9. Rewrite AGENTS.template.md** (`server/features/build/AGENTS.template.md`)

Remove `files/` references and `{{KNOWLEDGE_SOURCES_SECTION}}`. Point the agent at `onyx-cli search` and the company-search skill. Old code (`CONNECTOR_INFO`, `build_knowledge_sources_section`, `generate_agents_md.py`, etc.) is NOT removed in this PR — it becomes dead code, cleaned up in PR 3.

```markdown
### Step 1: Information Retrieval

1. **Search** company knowledge using the `company-search` skill. Run
   `onyx-cli search "<query>"` and read the returned JSON; each result has a
   `document` field (the citation ID) — cite results by that number when you
   reference them.
2. Read the `company-search` SKILL.md for available sources and flags.
3. **Iterate** — run additional searches to refine. Use `--source` to narrow by
   connector and `--days` for recent content.
4. **Summarize** key findings before proceeding to output generation.
```

#### PR 2 file changes

| Action | File |
|--------|------|
| New | `sandbox/kubernetes/docker/skills/company-search/SKILL.md.template` |
| New | `sandbox/skills/rendering.py` |
| New | `tests/external_dependency_unit/craft/test_company_search_skill.py` |
| Modify | `configs.py` — add `SKILLS_TEMPLATE_PATH` constant |
| Modify | `sandbox/manager/directory_manager.py` — `setup_skills()` changed from copy to symlink |
| Modify | `configs/constants.py` — improve `DocumentSourceDescription` wording |
| Modify | `sandbox/base.py` — add `write_sandbox_file()` abstract method |
| Modify | `sandbox/kubernetes/kubernetes_sandbox_manager.py` — implement `write_sandbox_file()` |
| Modify | `sandbox/local/local_sandbox_manager.py` — implement `write_sandbox_file()` |
| Modify | `session/manager.py` — add `push_dynamic_skills()` |
| Modify | `api/sessions_api.py` — call `push_dynamic_skills()` in restore path |
| Modify | `AGENTS.template.md` — rewrite for onyx-cli search |
| Modify | `sandbox/util/__init__.py` — remove stale exports (`build_knowledge_sources_section`, etc.) |
| Modify | `sandbox/manager/test_directory_manager.py` — update tests for `setup_skills()` symlink change |

#### PR 2 tests

**File:** `tests/external_dependency_unit/craft/test_company_search_skill.py`

1. **Source list rendering.** Create test CC pairs, call `build_available_sources_section()`, assert correct sources and descriptions.
2. **Empty sources.** User with no connectors → `"No connected sources available for this user."`.
3. **Deduplication and format.** Multiple CC pairs for the same source produce one line; output lines match `- \`{source}\` — {description}` format.

---

### PR 3: File Sync Removal (Pure Deletion)

Removal-only (~1500 lines deleted). After this PR, `files/` is gone and connector documents are accessed only via search. No new functionality — user library rework is deferred to PR 4. Ship after verifying search works end-to-end in PR 2.

Grouped by subsystem for clarity, but ships as one PR.

#### Pod spec

**11. Remove S3 sidecar and files volume** (`sandbox/kubernetes/kubernetes_sandbox_manager.py`)

In `_create_sandbox_pod()`:
- Remove the `file-sync` sidecar container (`peakcom/s5cmd:v2.3.0`)
- Remove the `files` EmptyDir volume (5Gi)
- Remove the IRSA service account that was specific to the sidecar

Remove `SANDBOX_FILE_SYNC_SERVICE_ACCOUNT` from `configs.py`. **Keep `SANDBOX_S3_BUCKET`** — `S3PersistentDocumentWriter` (user library writes) still depends on it.

#### Session setup / restore

**12. Remove files/ symlink** (`sandbox/kubernetes/kubernetes_sandbox_manager.py`)

In **both** `setup_session_workspace()` and `restore_snapshot()`: delete the `files/` symlink creation (real-data path, demo-data path, and filtered-symlink path).

Remove:
- `_build_filtered_symlink_script()` helper (~line 202)
- Its call in `setup_session_workspace()` (~line 1312)

**13. Remove `generate_agents_md.py` call sites** (`sandbox/kubernetes/kubernetes_sandbox_manager.py`)

Remove the two invocations:
- `setup_session_workspace()` (~line 1367): `python3 /usr/local/bin/generate_agents_md.py ... || true`
- `_regenerate_session_config()` (~line 1803, called by `restore_snapshot()`): same

#### Sandbox image

**14. Clean up Dockerfile** (`sandbox/kubernetes/docker/Dockerfile`)

- Remove `mkdir -p /workspace/files`
- Remove `COPY generate_agents_md.py /usr/local/bin/`

#### Agent instructions

**15. Remove knowledge sources rendering** (`sandbox/util/agent_instructions.py`)

Delete:
- `CONNECTOR_INFO` dict
- `_normalize_connector_name()`, `_scan_directory_to_depth()`, `build_knowledge_sources_section()`
- The `{{KNOWLEDGE_SOURCES_SECTION}}` replacement in `generate_agent_instructions()`
- The `files_path` parameter from `generate_agent_instructions()`

Update callers:
- `LocalSandboxManager.setup_session_workspace()` — remove `files_path` argument
- `KubernetesSandboxManager` — already passes `files_path=None`; remove the parameter

`sandbox/util/__init__.py` exports were already removed in PR 2 — no further changes needed here.

#### OpenCode config

**16. Remove `/workspace/files` allowlist** (`sandbox/util/opencode_config.py`)

Remove `/workspace/files`, `/workspace/files/**`, `/workspace/demo_data`, and `/workspace/demo_data/**` allow rules from `external_directory` (~lines 150-155).

#### File sync methods

**17. Remove `sync_files()` method and implementations**

- `sandbox/base.py` (~line 448): remove abstract method
- `sandbox/kubernetes/kubernetes_sandbox_manager.py` (~line 2299): remove K8s implementation
- `sandbox/local/local_sandbox_manager.py` (~line 1425): remove local no-op implementation

#### Celery tasks

**18. Remove `sync_sandbox_files` task and helpers** (`sandbox/tasks/tasks.py`)

Remove the current `sync_sandbox_files()` task (~lines 324-394) entirely. Connector documents no longer need filesystem sync — they're accessed via search.

Delete `_get_disabled_user_library_paths()` helper (~lines 272-315) — filtered symlinks are gone.

#### Task dispatches

**19. Remove file sync dispatches**

- `background/indexing/run_docfetching.py` (~lines 940-958): remove the `SANDBOX_FILE_SYNC` dispatch entirely. Connector documents no longer need filesystem sync — they're accessed via search.
- `server/features/build/api/user_library.py` (~line 223): remove the `SANDBOX_FILE_SYNC` dispatch. (User library upload sync is re-added in PR 4.)

#### Local sandbox

**20. Remove local file sync infrastructure** (`sandbox/manager/directory_manager.py`, `sandbox/local/local_sandbox_manager.py`)

Remove `setup_files_symlink()`, `_setup_filtered_files()`, `_setup_filtered_user_library()` from `DirectoryManager`.

Remove file-system path construction using `PERSISTENT_DOCUMENT_STORAGE_PATH` from `session/manager.py` (~lines 438-441).

#### Persistent document writer

**21. Remove connector document write path, keep user library write path** (`persistent_document_writer.py`, `run_docfetching.py`)

In `run_docfetching.py`: remove the `get_persistent_document_writer()` import and the code block (~lines 790-818) that writes indexed connector documents to persistent storage. This is the connector-document serialization path — dead now that search replaces file access.

In `persistent_document_writer.py`: remove `write_documents()`, `serialize_document()`, and the hierarchical path builder helpers. Keep `write_raw_file()`, `delete_raw_file()`, and the `get_persistent_document_writer()` factory — these are still used by `user_library.py` for raw file writes to S3. `SANDBOX_S3_BUCKET` stays for the same reason.

#### Demo data

**22. Remove demo data** (`sandbox/kubernetes/docker/Dockerfile`, `sandbox/kubernetes/kubernetes_sandbox_manager.py`)

Remove `demo_data/` from the Docker image (the `COPY` of `demo_data.zip` and its extraction). Remove the demo-data symlink path in `setup_session_workspace()` and `_regenerate_session_config()`. Remove `/workspace/demo_data` allowlist rules from `opencode_config.py` (covered by step 16). Demo data is no longer a supported path.

#### Deleted files

| File | Reason |
|------|--------|
| `sandbox/kubernetes/docker/generate_agents_md.py` | Only populated `{{KNOWLEDGE_SOURCES_SECTION}}` from `files/` |
| `tests/external_dependency_unit/craft/test_persistent_document_writer.py` | Tests deleted code path |
| `tests/external_dependency_unit/craft/test_kubernetes_sandbox.py` | References `sync_files()` — update or delete |

#### PR 3 file changes

| Action | File |
|--------|------|
| Delete | `sandbox/kubernetes/docker/generate_agents_md.py` |
| Delete | `tests/external_dependency_unit/craft/test_persistent_document_writer.py` |
| Modify | `sandbox/kubernetes/kubernetes_sandbox_manager.py` — remove sidecar, remove files volume, remove files/ symlink, remove `generate_agents_md.py` calls, remove `sync_files()`, remove `_build_filtered_symlink_script()` |
| Modify | `sandbox/kubernetes/docker/Dockerfile` — remove `files/` mkdir, remove `generate_agents_md.py` copy, remove `demo_data.zip` copy + extraction |
| Modify | `sandbox/util/agent_instructions.py` — remove `CONNECTOR_INFO`, `build_knowledge_sources_section()`, helpers, `files_path` param |
| Modify | `sandbox/util/__init__.py` — already cleared in PR 2; no further changes needed |
| Modify | `sandbox/util/opencode_config.py` — remove `/workspace/files` and `/workspace/demo_data` allowlists |
| Modify | `sandbox/base.py` — remove `sync_files()` abstract method |
| Modify | `sandbox/local/local_sandbox_manager.py` — remove `sync_files()` impl, remove files/ setup |
| Modify | `sandbox/manager/directory_manager.py` — remove file symlink helpers |
| Modify | `sandbox/tasks/tasks.py` — remove `sync_sandbox_files` task, delete `_get_disabled_user_library_paths()` |
| Modify | `background/indexing/run_docfetching.py` — remove persistent writer call + `SANDBOX_FILE_SYNC` dispatch |
| Modify | `server/features/build/api/user_library.py` — remove `SANDBOX_FILE_SYNC` dispatch |
| Modify | `server/features/build/indexing/persistent_document_writer.py` — remove `write_documents()`, `serialize_document()`, path builder helpers; keep `write_raw_file()`, `delete_raw_file()`, factory |
| Modify | `server/features/build/session/manager.py` — remove `PERSISTENT_DOCUMENT_STORAGE_PATH` usage |
| Modify | `server/features/build/configs.py` — remove `SANDBOX_FILE_SYNC_SERVICE_ACCOUNT` (keep `SANDBOX_S3_BUCKET`) |
| Update | `tests/external_dependency_unit/craft/test_kubernetes_sandbox.py` — remove `sync_files()` references |

#### PR 3 tests

**Integration test:** `tests/integration/tests/craft/test_craft_search_e2e.py`

1. **Full round-trip.** Create session → verify PAT on Sandbox → `onyx-cli search` returns results → sleep → resume → verify same PAT reused.

**Smoke tests** (before merging):

1. Run a Craft session, watch the agent use `onyx-cli search`, confirm it cites real results.
2. Same query in Onyx chat — top results should overlap.
3. `find files/` returns nothing.
4. Session with no sources — SKILL.md says so, agent doesn't hallucinate.

---

### PR 4: User Library Rework (Net New)

New delivery mechanism for raw user library files. With the sidecar removed in PR 3, user library files (spreadsheets, PDFs, etc.) need a new path into the sandbox. This PR adds a shared `/workspace/user_library/` volume, kubectl exec sync, and a Celery task to keep it up to date.

#### Pod spec

**23. Add user library volume** (`sandbox/kubernetes/kubernetes_sandbox_manager.py`)

In `_create_sandbox_pod()`:
- Add a `user-library` EmptyDir volume (~1Gi) mounted at `/workspace/user_library/`
- Keep AWS credential injection on the **main container** (needed for `aws s3` exec calls for user library sync)

#### Celery tasks

**24. Add `sync_user_library_files` task** (`sandbox/tasks/tasks.py`)

New `sync_user_library_files()` Celery task that:
1. Finds the user's running sandbox via `get_sandbox_by_user_id()`
2. Runs a one-shot `kubectl exec` in the main container (not a sidecar): `aws s3 sync s3://{bucket}/{tenant}/knowledge/{user_id}/user_library/ /workspace/user_library/`
3. Returns immediately — no persistent process

#### Task dispatches

**25. Add user library sync dispatch on upload**

- `server/features/build/api/user_library.py` (~line 223): add `SYNC_USER_LIBRARY_FILES` dispatch. This triggers the new kubectl exec sync so uploaded files appear in the sandbox immediately.

#### User library sync at session setup

**26. Sync user library on workspace setup** (`sandbox/kubernetes/kubernetes_sandbox_manager.py`)

In `setup_session_workspace()` and `restore_snapshot()`, after creating the session directory, run the same one-shot sync:

```bash
aws s3 sync "s3://{bucket}/{tenant}/knowledge/{user_id}/user_library/" /workspace/user_library/
```

This populates the shared directory on first session and on resume (pulling any files uploaded while the pod was sleeping). Sessions access files at `/workspace/user_library/` directly — no symlink needed since it's a pod-level shared directory.

#### OpenCode config

**27. Add user library allowlist** (`sandbox/util/opencode_config.py`)

Add `/workspace/user_library` and `/workspace/user_library/**` to the `external_directory` allowlist in `opencode_config.py`.

#### Dockerfile

**28. Add user library directory** (`sandbox/kubernetes/docker/Dockerfile`)

Add `mkdir -p /workspace/user_library` to the Dockerfile.

#### PR 4 file changes

| Action | File |
|--------|------|
| Modify | `sandbox/kubernetes/kubernetes_sandbox_manager.py` — add user-library volume, add user library sync via kubectl exec in setup + restore |
| Modify | `sandbox/kubernetes/docker/Dockerfile` — add `mkdir -p /workspace/user_library` |
| Modify | `sandbox/util/opencode_config.py` — add `/workspace/user_library` allowlist |
| Modify | `sandbox/tasks/tasks.py` — add `sync_user_library_files` task |
| Modify | `server/features/build/api/user_library.py` — add `SYNC_USER_LIBRARY_FILES` dispatch |

#### PR 4 tests

**Smoke tests** (before merging):

1. Upload a spreadsheet via user library, verify it appears at `/workspace/user_library/` in the sandbox.
2. Upload a file mid-session, verify the agent can access it without restarting.
