# User Library Sync to Sandboxes

How user-uploaded files (PDFs, spreadsheets, slides) get from the user's library into the agent's sandbox. Replaces the symbiotic-S3 sync that was removed in PR #11042.

## 1. Architecture

Three layers, mirroring the skills pipeline:

```
HTTP layer        backend/onyx/server/features/build/user_library/api.py
  │ thin: validate input, call db helpers, return response
  ▼
DB layer          backend/onyx/server/features/build/db/user_library.py
  │ owns: file_store I/O, Document upserts, ownership checks, quota
  ▼
Sandbox sync      backend/onyx/server/features/build/sandbox/user_library.py
                  builds FileSet from DB + file_store, pushes via push daemon
```

Files are stored in the **default file store** (`get_default_file_store()`) — same backend skills use. There is no Craft-specific S3 bucket for user files.

## 2. Storage model

| Field | Where | Purpose |
|-------|-------|---------|
| File contents | `file_store` (S3/local) | Raw bytes |
| `Document.id` | `CRAFT_FILE__{user_id}__{sha256(path)[:16]}` | Deterministic, ownership encoded in prefix |
| `Document.link` | file_store `file_id` | Pointer for retrieval |
| `Document.file_id` | file_store `file_id` (mirror) | Schema-level pointer |
| `Document.doc_metadata` | `{file_path, file_size, mime_type, is_directory, sync_disabled, file_store_id}` | Display + filtering |
| `Connector` | shared "User Library" connector, `DocumentSource.CRAFT_FILE` | Reuses indexing infrastructure |
| `Credential` | one per user, empty `credential_json={}` | Pairs with connector for ownership |

`FileOrigin.USER_FILE` is the file-store origin tag.

## 3. Sync pipeline

### Mount path

`/workspace/managed/user_library/` in the sandbox pod. Same atomic symlink swap as skills — the agent sees a stable path while the daemon swaps versioned directories underneath.

### Trigger points

| Trigger | Calls |
|---------|-------|
| Session creation (cold start) | `hydrate_user_library(sandbox_id, user_id, db_session)` |
| Existing session resume | `hydrate_user_library(...)` (same — re-hydrate to get latest state) |
| File upload (single or zip) | `sync_user_library_to_active_sandboxes(user_id, db_session)` |
| File delete | `sync_user_library_to_active_sandboxes(...)` |
| Toggle sync_disabled | `sync_user_library_to_active_sandboxes(...)` |

All synchronous — no Celery, matching the skills pattern.

### Data flow

```
build_user_library_fileset(user_id, db_session)
    1. list_user_files() → CRAFT_FILE Document rows for user
    2. Filter: skip is_directory=True, skip sync_disabled=True
    3. For each remaining doc: file_store.read_file(doc.link)
    4. Strip leading "/" from file_path (push daemon rejects absolute paths)
    5. Return FileSet { relative_path: bytes }
              │
              ▼
sandbox_manager.push_to_sandbox / push_to_sandboxes
    mount_path="/workspace/managed/user_library"
    → tar.gz, Ed25519-sign, POST to push daemon, atomic swap
```

Empty filesets push too (clears stale files via the swap).

## 4. DB layer API

`backend/onyx/server/features/build/db/user_library.py`:

| Function | Purpose |
|----------|---------|
| `get_or_create_craft_connector(db, user)` | Returns `(connector_id, credential_id)`. Idempotent. |
| `get_user_storage_bytes(db, user_id)` | SQL aggregation for quota |
| `build_document_id(user_id, path)` | Deterministic doc_id |
| `list_user_files(db, user_id)` | All CRAFT_FILE docs for the user |
| `fetch_user_file_for_user(db, doc_id, user_id)` | Lookup + ownership check; raises `OnyxError(NOT_FOUND)` on miss |
| `store_user_file(db, ..., file_path, content, mime_type)` | Save to file store + upsert Document. Returns `(doc_id, file_id, old_blob_id_to_delete)`. The new blob is saved first; the caller must pass `old_blob_id_to_delete` to `cleanup_old_blobs` after their final commit. |
| `cleanup_old_blobs(blob_ids)` | Delete superseded blobs. Must be called after the final DB commit — if called before and the commit fails, the document rolls back to point at the now-deleted blob. |
| `create_directory_record(db, user_id, connector_id, credential_id, dir_path)` | Virtual directory document (no file store object) |
| `set_sync_disabled(db, user_id, doc, sync_disabled)` | Toggle file or directory (recursive into children) |
| `delete_user_file(db, doc)` | Delete blob from file store + Document row |

The HTTP layer (`api/user_library.py`) calls these directly — no business logic in the endpoints.

## 5. Ownership

Encoded in the document_id prefix: `CRAFT_FILE__{user_id}__{hash}`. `fetch_user_file_for_user` checks the prefix matches the calling user before any DB lookup. A foreign user's doc_id returns `NOT_FOUND` (not 403), so existence is never leaked across users.

## 6. Files

**New:**
- `backend/onyx/server/features/build/sandbox/user_library.py` — sync module
- `backend/tests/integration/tests/craft/k8s/test_user_library_sync.py` — API-driven k8s integration tests against the Helm-installed kind lane with real API, web_server, Celery, backing services, sandbox proxy, and sandbox pods
- `backend/tests/external_dependency_unit/craft/test_user_library_fileset.py` — direct fileset/sync helper coverage

**Modified:**
- `backend/onyx/server/features/build/db/user_library.py` — added all the CRUD/storage helpers
- `backend/onyx/server/features/build/user_library/api.py` — thinned to call db helpers; `PersistentDocumentWriter` usage removed; `HTTPException` → `OnyxError`
- `backend/onyx/server/features/build/session/manager.py` — `_hydrate_user_library` called in both `create_session__no_commit` and `get_or_create_empty_session`
- `backend/onyx/skills/push.py` — per-failure logging (consistent with user_library push logging)
- `backend/tests/integration/tests/craft/k8s/k8s_fixtures.py` — `SandboxHandle.provision_api_user` returns a `WorkspaceProxy` for API-created users, eliminating duplicated `_provision_with_status` helpers

**Deleted:**
- `backend/onyx/server/features/build/indexing/persistent_document_writer.py`
- `backend/tests/external_dependency_unit/craft/test_persistent_document_writer.py`

## 7. Tests

Tests follow the layered Craft testing strategy: API-driven integration coverage
where real sandbox behavior matters, with narrower tests for pure file-set logic.

### K8s Integration (`test_user_library_sync.py`)

Real Postgres + Redis + MinIO from the Helm-installed kind chart, plus real
api_server, web_server, Celery workers, sandbox-proxy, and sandbox pods. Tests
seed data through the deployed `/build/user-library` APIs and assert the
resulting files inside the sandbox pod.

- `test_upload_api_syncs_file_to_running_sandbox` — upload API pushes a file
- `test_upload_zip_api_syncs_nested_file` — zip upload pushes nested file paths
- `test_session_workspace_links_user_library_after_api_upload` — session symlink exposes synced files
- `test_delete_api_removes_file_from_running_sandbox` — delete API removes the file

### External-dependency unit (`test_user_library_fileset.py`)

Direct helper coverage for the pieces that do not need Kubernetes:

- `build_user_library_fileset` excludes sync-disabled files and directory records.
- `hydrate_user_library` pushes the current fileset to one sandbox manager target.
- `sync_user_library_to_active_sandboxes` targets only active sandbox rows.

### Integration (`test_user_library_api.py`, pre-existing)

HTTP-level coverage including cross-user 404, toggle, delete, upload caps. Already on the test-overhaul branch.

### K8s

`backend/tests/integration/tests/craft/k8s/test_user_library_sync.py` covers
API-triggered sync against the real deployed API and sandbox pods. The lower-level push daemon
contract (signed tarball, atomic swap) remains covered by the broader Craft
k8s integration suite; user library sync reuses `write_files_to_sandbox()`
unchanged.

## 8. Not in scope

- Per-session file selection (all of the user's non-disabled files go to all of their active sandboxes)
- Streaming for large files (office docs are typically MB-scale; 100 MiB bundle limit is fine)
- New DB tables or migrations (reuses Document + doc_metadata)
- Changes to the push daemon or extract logic
