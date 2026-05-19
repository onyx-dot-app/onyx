# User File Sync to Sandboxes

Reimplement user library file delivery to sandbox pods using the existing push daemon, and migrate storage from the Craft-specific S3 bucket to the default file store (same as skills).

## 1. Context

User library uploads (PDFs, spreadsheets, slides) are stored in a dedicated S3 bucket (`SANDBOX_S3_BUCKET`) via `S3PersistentDocumentWriter` and tracked in PostgreSQL. The old sync mechanism was removed in PR #11042. Files are currently invisible to the sandbox agent.

Skills use a simpler pattern: store via `get_default_file_store().save_file()`, read via `file_store.read_file(file_id)`. User files should do the same — one storage backend, one read path, no Craft-specific S3 client.

The push daemon and `write_files_to_sandbox()` are production-ready (used by skills). User libraries are small — typical usage is a handful of office documents totaling single-digit MB, well within the 100 MiB bundle limit.

## 2. Design

### Storage migration

Replace `S3PersistentDocumentWriter` / `PersistentDocumentWriter` with the default file store.

**Before (current):**
```
upload → S3PersistentDocumentWriter → s3://{SANDBOX_S3_BUCKET}/{tenant}/knowledge/{user}/user_library/{path}
                                      tracked via Document.link = storage_key
```

**After:**
```
upload → get_default_file_store().save_file() → standard file store location
                                                 tracked via Document.link = file_id
```

This eliminates `get_persistent_document_writer()`, `S3PersistentDocumentWriter`, and the `SANDBOX_S3_BUCKET` dependency for user files. Reading files back is just `file_store.read_file(file_id)` — identical to how skills read bundles.

### Mount path

`/workspace/managed/user_library`

Same atomic symlink swap as skills. The agent sees files at this stable path; the daemon swaps the underlying versioned directory on each push.

### Trigger points

| Trigger | Where | Mechanism |
|---------|-------|-----------|
| Session creation | `SessionManager.create_session__no_commit()` | Synchronous, after skills hydration |
| File upload | `user_library.py` upload endpoints | Synchronous, after upload completes |
| File delete | `user_library.py` delete endpoint | Synchronous, after delete completes |
| File toggle (sync_disabled) | `user_library.py` toggle endpoint | Synchronous, after toggle completes |

All triggers are synchronous — same pattern as skills. No Celery tasks needed.

### Data flow

```
Upload/delete API         Session creation
    │                          │
    ▼                          ▼
sync_user_library_to_     hydrate_user_library()
  active_sandboxes()           │
    │                          │
    └──────────┬───────────────┘
               ▼
    build_user_library_fileset(user_id, db_session)
        1. Query CRAFT_FILE documents for user (sync_disabled != True, is_directory != True)
        2. Read each file from default file store via file_id
        3. Return FileSet dict keyed by relative path
               │
               ▼
    write_files_to_sandbox(mount_path="/workspace/managed/user_library", files=fileset)
        1. tar.gz the FileSet
        2. Sign with Ed25519
        3. POST to push daemon
        4. Daemon extracts + atomic swap
```

### Scope rules

- All non-disabled files for the user sync to all of the user's active sandboxes.
- No per-session file selection.
- `sync_disabled` flag in `doc_metadata` controls exclusion.
- Directories (is_directory=True) are skipped — directory structure is implicit in file paths.

## 3. Implementation

### Part A: Migrate storage to default file store

**Modify `api/user_library.py`:**

Replace all `get_persistent_document_writer()` calls with `get_default_file_store()`:

- `upload_files()`: Replace `writer.write_raw_file(content, path)` with `file_store.save_file(content, display_name, file_origin=FileOrigin.USER_FILE, file_type=mime)`. Store the returned `file_id` in `Document.link`.
- `upload_zip()`: Same pattern for each extracted file.
- `delete_files()`: Replace `writer.delete_raw_file_by_path()` with `file_store.delete_file(file_id)`.

`FileOrigin.USER_FILE` already exists in the enum — no change needed.

**Update `doc_metadata` schema:** Replace `storage_key` with `file_id`. Keep `file_path` (relative path for display/sync), `file_size`, `mime_type`, `is_directory`, `sync_disabled`.

**Remove:** `get_persistent_document_writer()` factory, `S3PersistentDocumentWriter` class (if no other consumers), `PersistentDocumentWriter` class (if no other consumers). Check for other callers first.

### Part B: Sync to sandboxes

**New file: `backend/onyx/server/features/build/sandbox/user_library.py`**

```python
def build_user_library_fileset(user_id: UUID, db_session: Session) -> FileSet:
    """Read user's CRAFT_FILE documents from file store, return as FileSet."""

def hydrate_user_library(
    sandbox_manager: SandboxManager,
    sandbox_id: UUID,
    user_id: UUID,
    db_session: Session,
) -> None:
    """Push user's files to sandbox. Called on session creation."""

def sync_user_library_to_active_sandboxes(user_id: UUID, db_session: Session) -> None:
    """Push updated file set to all active sandboxes for user."""
```

**Wire into session creation: `session/manager.py`**

After `_hydrate_skills()`, call `hydrate_user_library()`.

**Wire into upload/delete/toggle: `api/user_library.py`**

After mutations, call `sync_user_library_to_active_sandboxes(user_id, db_session)` synchronously — same pattern as `push_skill_to_affected_sandboxes()`.

### No daemon changes

The push daemon already supports `/workspace/managed/` prefix. No new endpoints needed.

## 4. Files changed

| File | Change |
|------|--------|
| `api/user_library.py` | Replace PersistentDocumentWriter with default file store; enqueue sync task after mutations |
| `sandbox/user_library.py` | New — `build_user_library_fileset`, `hydrate_user_library`, `sync_user_library_to_active_sandboxes` |
| `session/manager.py` | Call `hydrate_user_library()` on session creation |
| `skills/push.py` | Per-failure logging (matching user_library pattern) |

## 5. Important notes

- **No backwards compatibility required.** Craft is pre-GA. Existing files in `SANDBOX_S3_BUCKET` can be dropped — no migration script or fallback read path needed.
- The `PersistentDocumentWriter` classes may have other consumers (snapshots, etc.). Audit before removing — if shared, leave in place and only change the user library upload path.
- The connector/credential pair pattern (`get_or_create_craft_connector`) is unchanged — it's orthogonal to storage.

## 6. Tests

Tests follow the layered paradigm from `docs/craft/tests/coverage-and-overview.md`. Branch: `whuang/craft-user-file-sync` (off `whuang/craft-test-overhaul`).

### Unit tests (`backend/tests/unit/onyx/server/features/build/`)

Pure logic, no DB or network. Already covered by the test overhaul branch:
- `test_upload_validation.py` — extension filtering, MIME checks, filename sanitization, size caps

### External dependency tests (`backend/tests/external_dependency_unit/craft/`)

Real Postgres + real `LocalSandboxManager` on `tmp_path`. Mock nothing except where injecting errors.

**New: `test_user_file_sync.py`** — mirrors `test_skill_push.py` structure:
- `test_hydrate_pushes_files_to_sandbox` — upload files via file store + DB, call `hydrate_user_library()`, assert files land at `managed/user_library/{path}` on disk with correct contents
- `test_sync_disabled_files_excluded` — set `sync_disabled=True` in doc_metadata, verify file is absent from fileset
- `test_directories_excluded_from_fileset` — `is_directory=True` entries don't appear in fileset
- `test_empty_library_is_noop` — no files → no push call, no error
- `test_sync_to_active_sandboxes_skips_sleeping` — only RUNNING sandboxes get the push
- `test_sync_after_delete_removes_file` — upload, sync, delete, re-sync → file gone from sandbox
- `test_one_failing_sandbox_does_not_abort_others` — use `StubSandboxManager` to inject `FatalWriteError` on one sandbox, verify others still receive files

### Integration tests (`backend/tests/integration/tests/craft/`)

Real HTTP against a running Onyx deployment. Already covered by the test overhaul branch:
- `test_user_library_api.py` — upload/delete/toggle/cross-user isolation (9 tests)
- `test_upload_api.py` — session-scoped upload, auth, blocked extensions, unicode filenames (8 tests)

**New tests to add to `test_user_library_api.py`:**
- `test_upload_triggers_sync_to_sandbox` — upload a file, verify it appears at `/workspace/managed/user_library/` via the sandbox's file listing (local backend: check disk; hit the tree endpoint to confirm round-trip)
- `test_delete_triggers_resync` — upload, confirm present, delete, confirm absent from sandbox

### K8s tests (`test_kubernetes_sandbox.py`)

Gated by `SANDBOX_BACKEND=kubernetes`. Runs in dedicated CI job only.

No new K8s-specific tests needed — the push daemon contract (signed tarball delivery, atomic swap) is already covered by the existing K8s push tests. User file sync reuses `write_files_to_sandbox()` unchanged.

## 7. Not in scope

- Per-session file selection
- Streaming for large files
- New DB tables or migrations (reuse Document + doc_metadata)
- Changes to the push daemon
