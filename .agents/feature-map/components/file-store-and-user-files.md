# File Store and User Files

> Files that users give Onyx directly (chat attachments, project files and agent files) and the files that tools generate. This component owns the blob store, the `UserFile` lifecycle from upload to deletion, text extraction and token counts, user-file indexing, and the route that serves a file back.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE

---

## User experience

- **A user** drops a file into the composer, a project or an agent. The upload
  returns at once. The file shows "processing" until indexing finishes. A file
  that is too large, has too many tokens, has a password, or has no
  extractable text is rejected with a reason. Spreadsheets over the token limit
  are accepted but not indexed.
- **An image** goes to the model as an image. Images inside a PDF, DOCX or
  PPTX are described by a vision model at indexing time, when an admin turns
  image analysis on. No step does OCR. A PDF image extraction failure is logged;
  extracted text remains available.
- **Generated files**, such as images from the image tool or files from the
  Python tool, show inline and can be downloaded by users who can read the
  chat session.
- **Deleting a file** that is still in a project or on an agent does not
  delete it. The response lists the projects and agents to remove it from
  first.
- **Incognito attachments** work like other uploads, but are never indexed for
  search and never join a project. A sweep deletes them after the session ends.
- **Admins** set the upload size limit and the token limit in workspace
  settings. They can set an Unstructured API key, which sends every file to
  that service for extraction ([[#unstructured-key-changes-extraction]]).
- **Operators** choose the storage backend (S3-compatible, GCS, Azure or
  Postgres) with `FILE_STORE_BACKEND`. `backend/onyx/file_store/README.md`
  lists the settings.

When a file cannot be read later, the user sees a 404 for a file they cannot
read and for a file that does not exist. The two cases look the same on
purpose ([[#read-check-404]]).

---

## Scope

This component owns the blob store and its backends, the file records, text
extraction and file-type rules, the `UserFile` rows and their processing,
sync and delete tasks, the user-file indexing adapter, `FileReaderTool`, the
upload, status and delete routes, and the `/chat/file/{file_id}` serving route
with its read check.

Neighbours own the rest:
- [[projects]]: project rows, and whether context files go inline or through
  retrieval on a turn. The upload routes sit in the projects API module but
  belong here.
- [[context-assembly]]: how inline file text sits in the prompt.
- [[agents-personas]]: which agents a file is attached to, and their audience.
- [[access-control]]: the document ACL that connector files use.
- [[indexing-pipeline]]: the pipeline that the user-file adapter plugs into.
- [[craft-sandboxes]]: the Craft user library, which also writes
  `FileOrigin.USER_FILE` blobs but has no `UserFile` rows.

---

## Architecture

```
POST /user/projects/file/upload             server/features/projects/api.py:upload_user_files
  upload_files_to_user_files_with_indexing  db/projects.py
    create_user_files
      categorize_uploaded_files             extract text, count tokens, reject (in the request)
      upload_files(FileOrigin.USER_FILE)    blob + FileRecord
      UserFile rows                         PROCESSING or SKIPPED, project link
    enqueue PROCESS_SINGLE_USER_FILE        or BackgroundTasks when DISABLE_VECTOR_DB
process_user_file_impl                      user_file_processing/tasks.py
  _load_user_file_documents                 LocalFileConnector; document id = str(UserFile.id)
  incognito or DISABLE_VECTOR_DB -> _process_user_file_without_vector_db (plaintext, no chunks)
  else -> _process_user_file_with_indexing  run_indexing_pipeline + UserFileIndexingAdapter
  -> COMPLETED, or FAILED on error
link, unlink, share change -> needs_project_sync / needs_persona_sync
  project_sync_user_file_impl               rewrites project_ids, persona_ids and ACL on chunks
DELETE /user/projects/file/{id} -> DELETING -> delete_user_file_impl
  index delete -> blob + plaintext delete -> row delete
```

**Two ids.** `FileRecord.file_id` names a blob. `UserFile.id` is a UUID that
the frontend, the model and the index use. `UserFile.file_id` holds the blob id
by value, with no foreign key. `db/user_file.py:get_file_id_by_user_file_id`
translates. `fetch_chat_file` accepts either id.

**One record for every backend.** `db/file_record.py:upsert_filerecord` writes
the `FileRecord` row for every backend. The Postgres backend adds a
`FileContent` row that points at a large object. Callers use `FileStore`
through `get_default_file_store` and never branch on the backend.
`upsert_filerecord` also stamps a blob saved during a `USAGE_ONLY` incognito
turn with its session id (`CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR`, set by
`chat/execution.py:start_chat_turn`). The incognito cleanup finds blobs only
through that stamp.

**Token counts are written twice.** `categorize_uploaded_files` counts tokens
at upload with the default chat model's tokenizer, and estimates images from
their pixel size. Processing then writes `UserFile.token_count` again: the
indexing adapter counts the extracted text, and the no-index path counts it
with the default LLM tokenizer. [[projects]] reads the count for its fit check.

**The indexing adapter.** `indexing/adapters/user_file_indexing_adapter.py`
locks `UserFile` rows with `NOWAIT` and retries
(`_acquire_user_file_locks`). It raises `UserFileDeletingSkip`, a
`ConnectorStopSignal`, for a file that is being deleted, so a write cannot
bring back a document that the delete path removes. On a secondary-index write
its `post_index` changes no status and sends no notification; the primary pass
does them ([[indexing-pipeline]]).

**Generated files.** The image tool (through
`file_store/utils.py:save_files`) and the Python tool save blobs with
`FileOrigin.CHAT_IMAGE_GEN` and the session stamp from
`file_store/utils.py:chat_image_gen_metadata`. They get a `FileRecord` but no
`UserFile`. The chat shows them through `/chat/file/{file_id}`.

**Serving.** `server/query_and_chat/chat_backend.py:fetch_chat_file` resolves
the id, calls `backend/onyx/access/access.py:user_can_access_chat_file`, and
streams the blob. It sends `Content-Disposition: attachment` unless
`file_store/serving.py` allows the type inline. It caches for a year with an
ETag on the file id, because a file id never changes content
([[#file-id-write-once]]). With `?parsed=true`, a spreadsheet returns a JSON
preview.

---

## Contracts and traps

1. `read-check-404` **Every read checks the acting user, and denial is a
   404.** `backend/onyx/access/access.py:user_can_access_chat_file` admits, in order: the file owner;
   readers of an agent the file is attached to; readers of a session whose
   `ChatMessage.files` lists it; readers of the session stamped on a generated
   file; and the document ACL for connector files. A new kind of file must fit
   one of these branches, or nobody can read it.
2. `generated-file-session-stamp` **Every generated file must carry the
   session stamp.** A `CHAT_IMAGE_GEN` file with no `chat_session_id` in
   `file_metadata` is open to every signed-in user
   (`backend/onyx/access/access.py:_user_can_access_chat_image_gen_file`). Files written before stamping
   depend on this, so the open branch must stay. A new writer that forgets the
   stamp creates an open file, and nothing fails. Use
   `file_store/utils.py:chat_image_gen_metadata`.
3. `say-which-id` **Say which id you mean.** A new route or tool that accepts
   "a file id" must state whether it is a blob id or a `UserFile.id`. Pass a
   `UserFile.id` to `FileStore.read_file` and you get "not found" for a file
   that exists.
4. `index-inline-share-id` **Index and inline paths share the
   `UserFile.id`.** `background/celery/tasks/user_file_processing/tasks.py:_load_user_file_documents` sets the document id to
   `str(UserFile.id)`, and inline context cites the same id. Citations survive
   when a project crosses the fit limit ([[projects]]).
5. `delete-order` **Delete in order: index, blobs, row.**
   `background/celery/tasks/user_file_processing/tasks.py:delete_user_file_impl` keeps the row when a blob delete fails, because the
   row is the only handle a retry has. Blob deletes use
   `error_on_missing=False`, so a retry after a partial delete is safe.
   `server/features/projects/api.py:delete_user_file` refuses while any project or agent link exists and
   returns `has_associations=True` with a 200, not an error.
6. `file-id-write-once` **A file id is write-once.** On S3, GCS and Azure,
   `change_file_id` repoints the `FileRecord` and leaves the object at its old
   key. A later `save_file` with the old id overwrites the object that the
   renamed record still reads. The Postgres store moves the `FileContent` row
   instead. Both `change_file_id` and `delete_file` lock the record, and
   `change_file_id` returns false when a delete won. The serving cache also
   assumes immutable content.
7. `upload-rejects-indexing-does-not` **Upload rejects what extraction cannot
   read; indexing does not.**
   `server/features/projects/projects_file_utils.py:categorize_uploaded_files` rejects a file with
   empty extracted text, except a PDF or DOCX with embedded images when image
   analysis is on. `file_processing/extract_file_text.py:_extract_text_and_images`
   catches every parser error and returns empty text. A parser crash during
   indexing can therefore give a `COMPLETED` file with no content, not
   `FAILED`: the chunker emits one empty chunk for an empty document
   (`indexing/chunking/document_chunker.py:DocumentChunker`).
8. `sync-flags-drive-chunk-metadata` **Sync flags drive chunk metadata.**
   Link, unlink and agent audience changes set `needs_project_sync` or
   `needs_persona_sync`. `background/celery/tasks/user_file_processing/tasks.py:project_sync_user_file_impl` rewrites
   `project_ids`, `persona_ids` and the ACL in place, with no new embedding.
   The beat task picks up only `COMPLETED` files. A file linked during
   processing gets its ids from the indexing adapter
   (`db/user_file.py:fetch_user_project_ids_for_user_files`).
9. `no-session-across-file-reads` **Do not hold an ORM session across file
   reads.** `db/user_file.py:capture_user_file_metadata` copies context file
   fields into `UserFileMetadata`, and `db/user_file.py:prepare_chat_file_inputs`
   copies each attachment's token count and processing status, before the turn
   closes its session. `file_store/utils.py:load_in_memory_chat_files` and
   `chat/files.py:load_chat_files` read blobs from those values only. The tasks
   use short read sessions and run index and blob I/O with no connection held.
10. `disable-vector-db-paths` **`DISABLE_VECTOR_DB` changes three paths.**
    Processing stores plaintext with no chunks, overflow files go to
    `FileReaderTool` (available only in this mode), and upload, delete and
    sync run as in-request `BackgroundTasks`, not Celery tasks.
11. `unstructured-key-changes-extraction` **An Unstructured API key changes
    every extraction.** When an admin sets the key (Admin > Document
    Processing; stored in the KV store by `file_processing/unstructured.py`),
    `file_processing/extract_file_text.py:extract_file_text` and
    `_extract_text_and_images` both send the file to
    the Unstructured service before any local parser. This covers uploads and
    connector and user-file indexing. File bytes leave the deployment. On
    success, `_extract_text_and_images` returns no embedded images and no
    metadata, so image analysis, PDF metadata and per-file `ONYX_METADATA` do
    nothing. An Unstructured error falls back to the local parsers.
12. `checkpoint-file-is-blob-id` **A saved run file keeps only a blob id.**
    `tools/file_snapshot.py:SavedChatFile.capture` drops the bytes of a
    `ChatFile` that has a `file_id`, and
    `tools/file_snapshot.py:SavedContextFiles.capture` keeps only the blob id
    of each project or agent context image. `restore` reads these ids from the
    file store with no access check and no `UserFile` lookup. A
    `ChatFile.file_id` must be a `FileRecord.file_id` the run may read, never
    a `UserFile.id` ([[#say-which-id]]). File deletion does not check for
    these references. If a user deletes a context file while a run is
    suspended, the resumed run fails when it loads that image. Inline bytes become
    `agent-checkpoint/<root session id>/<sha256>` blobs with
    `FileOrigin.OTHER` and no `UserFile`
    (`chat/restoration.py:persist_checkpoint_files`); session hard delete
    removes them by that prefix ([[chat-persistence#checkpoints-not-written]]).
13. `minio-dual-store` **While `S3_LEGACY_ENDPOINT_URL` is set, the S3 store
    serves two stores.** A deployment that upgrades from the bundled MinIO
    keeps it as a second, read-fallback store. `S3BackedFileStore` writes and
    deletes in both
    (`file_store/file_store.py:S3BackedFileStore._put_legacy_object`,
    `file_store/file_store.py:S3BackedFileStore._delete_legacy_object`), and a
    read that misses the main store falls back to MinIO
    (`file_store/file_store.py:S3BackedFileStore._with_legacy_fallback`). A
    failed MinIO write leaves an out-of-sync marker for
    `python -m onyx.file_store.legacy_copy`. A new method that writes, deletes
    or reads objects must use the same helpers, or files written before the
    upgrade disappear.

---

## Decisions

- **Index every indexable file at upload.** A project that grows past the fit
  limit, or a smaller-context model, needs no new indexing.
- **Generated files have no `UserFile` row.** They belong to a chat session,
  not to a user's file library, so access follows the session.
- **A 404 for denial.** A caller cannot learn that a file exists in another
  account.

---

## Known issues

- **Orphaned blobs from a failed upload stay.** `create_user_files` writes the
  blobs, then the rows. No task deletes a `USER_FILE` blob or `FileRecord`
  that no `UserFile` references.
- **Custom tool output has no session stamp.**
  `tools/tool_implementations/custom/custom_tool.py` saves response files as
  `FileOrigin.CHAT_UPLOAD` with no session. Such a file can be read only
  through the `ChatMessage.files` branch of [[#read-check-404]].
- **Agent files ignore group shares when served.** See
  [[agents-personas]] Known issues.

---

## Dependencies

- [[indexing-pipeline]]: `run_indexing_pipeline` for user files.
- [[document-index]]: stores and filters the chunks.
- [[llm-providers]]: tokenizers and the vision model for embedded images.
- [[background-jobs]]: the user-file processing, sync and delete workers.
- [[access-control]]: the connector-file branch of the read check.

---

## Recipes

- `add-file-type` **Add a file type.** Copy `.epub`: it sits in
  `file_processing/file_types.py:OnyxFileExtensions` and has a branch in both
  `extract_file_text_locally` and `_extract_text_and_images`. List the current types
  in `OnyxFileExtensions`. Then check the upload branch in
  `categorize_uploaded_files` ([[#upload-rejects-indexing-does-not]]).
- `add-generated-file-writer` **Add a generated-file writer.** Copy `file_store/utils.py:save_file_from_base64`:
  save through `FileStore.save_file` with `FileOrigin.CHAT_IMAGE_GEN` and
  `chat_image_gen_metadata` ([[#generated-file-session-stamp]]). List the
  current writers with `git grep -n "FileOrigin.CHAT_IMAGE_GEN" backend/onyx`.
- `add-storage-backend` **Add a storage backend.** Copy `file_store/gcs_file_store.py`. List the
  current backends in `file_store/file_store.py:get_default_file_store`.
  Implement every `FileStore` method, write the record through
  `upsert_filerecord` so incognito blobs get their cleanup stamp, and keep
  [[#file-id-write-once]].
- `investigate-file-404` **Investigate a 404 on `/chat/file/{file_id}`.** Find which id the caller
  sent ([[#say-which-id]]). Then walk the branches of
  `user_can_access_chat_file` in order for that user: `user_file.user_id`,
  agent links, `chat_message.files`, the `chat_session_id` in
  `file_record.file_metadata`, and the connector document ACL.
- `investigate-file-processing` **Investigate a file stuck in processing, or
  `COMPLETED` with no answers.**
  Read `user_file.status`, `chunk_count` and the sync flags. Search the
  user-file processing worker log for the `UserFile.id`. A `COMPLETED` file
  with one chunk usually means extraction returned empty text
  ([[#upload-rejects-indexing-does-not]]).

---

## Verification

- `backend/tests/unit/onyx/file_processing/` covers extraction.
  `backend/tests/unit/onyx/server/` (the `test_projects_file_utils` and
  `test_upload_files` modules) covers upload rejection.
- `backend/tests/external_dependency_unit/file_store/` covers the backends,
  the MinIO compatibility store and generated-file access.
- `backend/tests/integration/tests/projects/` covers upload, link and delete.
- By hand: as a second user, request another user's upload and generated image
  through `/chat/file/{file_id}`. Both must return 404 unless the session is
  shared as public.
