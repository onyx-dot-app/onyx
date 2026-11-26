# File Store and User Files

> Files that users give Onyx directly (chat attachments, project files and agent files) and the files that tools generate. This component owns the blob store, the `UserFile` lifecycle from upload to deletion, text extraction and token counts, user-file indexing, and the route that serves a file back.

**Verified against:** `6bac4e012f` (2026-10-29)
**Edition:** CE

---

## User experience

- **A user** drops a file into the composer, a project or an agent. The upload
  returns at once. While the request sends, the file card shows the percent
  sent (`lib/projects/uploadProgress.ts`; the request uses `XMLHttpRequest`
  for progress). In the composer, removing an uploading file cancels it with
  no error toast. When no file of its batch is left, the request aborts if
  part of its body is unsent; once the whole body is sent, it finishes and
  the cancelled files are deleted with the delete endpoint. The
  file shows "processing" until indexing finishes. A file
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
  upload_files_to_user_files_with_indexing  server/features/projects/upload.py
    create_user_files
      categorize_uploaded_files             extract text, count tokens, reject (in the request)
      upload_files(FileOrigin.USER_FILE)    blob + FileRecord
      UserFile rows                         PROCESSING or SKIPPED, project link
    enqueue PROCESS_SINGLE_USER_FILE        or BackgroundTasks when DISABLE_VECTOR_DB
process_user_file_impl                      user_file_processing/tasks.py
  consume_user_file_processing_attempt      db/user_file.py; FAILED past USER_FILE_PROCESSING_MAX_ATTEMPTS pickups
  _load_user_file_documents                 LocalFileConnector; document id = str(UserFile.id)
  incognito or DISABLE_VECTOR_DB -> _process_user_file_without_vector_db (plaintext, no chunks)
  else -> _process_user_file_with_indexing  run_indexing_pipeline + UserFileIndexingAdapter
  -> COMPLETED, or FAILED on error
link, unlink, share change -> needs_project_sync / needs_persona_sync
  project_sync_user_file_impl               rewrites project_ids, persona_ids and ACL on chunks
DELETE /user/projects/file/{id} -> DELETING -> delete_user_file_impl
  index delete -> preview + blob + plaintext delete -> row delete
```

**Two ids.** `FileRecord.file_id` names a blob. `UserFile.id` is a UUID that
the frontend, the model and the index use. `UserFile.file_id` holds the blob id
by value, with no foreign key, and several user files can hold one blob id.
`fetch_chat_file` accepts either id: it loads a user file by its id
(`db/user_file.py:get_user_file_by_id`) and serves its blob.

**One record for every backend.** `db/file_record.py:upsert_filerecord` writes
the `FileRecord` row for every backend. The Postgres backend adds a
`FileContent` row that points at a large object. Callers use `FileStore`
through `get_default_file_store` and never branch on the backend. The one
exception is presigned URLs: only the cloud backends have them, so a caller
checks `isinstance(store, PresignableFileStore)` first.

The S3, GCS and Azure stores upload the object first, then write and commit
the record through `file_store/file_store.py:record_uploaded_object`. When the
record write or commit fails, it deletes the upload unless a committed record
points at that object, then raises the original error. The S3 store also
deletes the copy in the legacy MinIO store ([[#minio-dual-store]]). The Postgres
store writes its large object in the record's transaction.

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
`FileOrigin.CHAT_IMAGE_GEN` and the session stamp, through
`file_store/utils.py:save_chat_output_file`. The sandbox tool
`library_create_library_file` saves files from the user's VM with `FileOrigin.CHAT_ARTIFACT`
(`tools/tool_implementations/sandbox/sandbox_tools.py:LibraryCreateLibraryFileTool`)
through `db/chat.py:save_chat_artifact`. Each file is a version of an
artifact: `db/models.py:ChatArtifact` is one VM path in one root chat
session, with the chat's owner (`user_id`, set from the chat when the
artifact is created),
and `ChatArtifactVersion` numbers its files from 1 and holds each
file's title and `version_reason` (a replace's, update's or restore's note).
A delete (`library_manage_library`, after the user approves) removes
an artifact (`db/chat.py:delete_chat_artifact`). Cleanup has one owner per
level: `delete_chat_artifact_files` cleans up one version by its file id (its
thumbnail and preview PDF, then its file, whose delete removes the version
row, in the transaction that holds the version's row lock and finds no link
left, so a preview that a conversion links meanwhile goes too or never
links), and whatever belongs
to the whole artifact runs after the commit that removes the artifact row,
in every path that removes one. Other chats' cards of a deleted artifact
keep their saved name, and their download is not found. A restore or update
(`library_manage_library`) copies a version's file, thumbnail and preview PDF into new records
(`db/chat.py:append_copied_artifact_version`), since the file store has no
copy. An artifact's name
is `ChatArtifact.name` once a rename (`library_manage_library`) sets it, else the
`FileRecord.display_name` of the version that the read selects, by default the
newest available one; every read of the name
uses that one expression (`db/chat.py:_newest_available_version`), and a
later publish of the path keeps it. The download's Content-Disposition keeps
the record's name. The sandbox tools `library_list` and `library_prepare_materialize`
([[code-execution]]) read these rows for the owner's chats that are not
deleted; the default list order reads the index on `(user_id, updated_at
DESC)`, and the other sorts read all of the owner's artifacts. The save writes the file record, upserts the artifact (its row
lock serializes concurrent publishes of one path) and adds the next version in
one commit. A replace (`library_replace_library_file`, or the artifact
tool's publish with a url and file_path) adds the version to an existing
artifact by ID instead (`ArtifactById`), also from another chat of the owner:
the artifact keeps its chat, path, name and type (the file's extension must
match), and the version's file joins the replacing chat's message files. The
artifact tool's publish with a url and path is an update instead: it shows
the generic tool card and attaches no file to the message. A PDF, PowerPoint or Word file of at most 20 MiB also gets a
thumbnail: `HarnessSandbox.render_preview` draws a JPEG of its first page in
the VM, and the save writes it first as a `FileOrigin.CHAT_ARTIFACT_THUMBNAIL`
record that `ChatArtifactVersion.thumbnail_file_id` links (`ON DELETE SET
NULL`: a version stays valid without it). A PowerPoint or Word file also gets
the PDF of the same render, a `FileOrigin.CHAT_FILE_PREVIEW` record that
`ChatArtifactVersion.preview_file_id` links the same way
(`db/chat.py:save_chat_file_preview` owns its origin, type and name). A
render that fails, raises or runs out of the publish budget, and a
thumbnail or preview save that fails, leave the link null; they never fail
the publish. A PDF over `RENDER_PREVIEW_MAX_PDF_BYTES` leaves only the
preview out. They get a
`FileRecord` but no `UserFile`. The chat shows them
through `/chat/file/{file_id}`. `GET /chat/artifacts/{artifact_id}?version=N`
(`server/query_and_chat/chat_backend.py:get_chat_artifact`) gives a version,
by default the newest available, with its chat and how the user may open
it (`access`): `owner` of the chat, `chat_reader` of it
(`db/access.py:user_can_read_chat_session`, a public share), or, only for an
explicit version, `file_only` for anyone who can download that version
(`backend/onyx/access/access.py:user_can_access_chat_file`, such as a reader of another
chat whose replace added it). Otherwise, and for a deleted chat, 404; the
web opens an artifact link (`{WEB_DOMAIN}/app/artifacts/<artifact_id>/v<N>`)
with it. A chat delete deletes a published file and its
thumbnail through its artifact's versions, also when its response never saved; a saved response
also lists it in `ChatMessage.files` ([[chat-persistence]]). The version rows
cascade from the file record and the artifact, and the artifact from the chat
session, so a chat delete must delete the files before the session.

**Published file text and search.** Each artifact is one search document,
`str(chat_artifact.id)`, with source `DocumentSource.CHAT_ARTIFACT`, the
owner's current email as its only ACL entry, no projects, personas or document
sets, and the link `tools/tool_implementations/sandbox/models.py:artifact_url` of its newest available
version ([[internal-search]]). `ChatArtifact.index_status` (`PENDING`,
`INDEXED`, `FAILED`, `REMOVED`) and `index_attempts` hold its state; a partial index on
`PENDING` serves the beat. `save_chat_artifact` sets `PENDING` with no
attempts, and the publish operation
(`tools/tool_implementations/sandbox/artifact_operations.py:publish`)
sends the indexing task after its commit
(`indexing/chat_artifact_index.py:send_chat_artifact_index_tasks`). A failed
publish makes the artifacts it keeps `PENDING` again, since the beat may have
indexed the version it deleted. The task
`background/celery/tasks/chat_artifact_indexing/tasks.py:process_single_chat_artifact`
runs on the user file processing queue: it counts a pickup before the slow
work (`db/chat.py:start_chat_artifact_indexing`; past
`CHAT_ARTIFACT_INDEX_MAX_ATTEMPTS` the artifact is `FAILED`), builds one
`TextSection` per page from the text cache, and writes through
`run_indexing_pipeline` with
`indexing/adapters/chat_artifact_indexing_adapter.py`. The adapter holds the
artifact's row while it writes. It writes and marks the row `INDEXED` only if
no publish (`updated_at`), newer pickup or model swap (`index_attempts`)
changed it since the pickup. The beat `check-for-chat-artifact-indexing` sends the `PENDING`
rest at low priority, at most the shared queue's room below
`USER_FILE_PROCESSING_MAX_QUEUE_DEPTH` each tick, and
`db/swap_index.py:_perform_index_swap` makes every artifact that is not
`REMOVED` `PENDING` again. A row is `INDEXED` only while its document holds
the newest available version. Rows that existed before the column started
`PENDING`, so the beat indexes them too; the rows of deleted chats started
`REMOVED`. An email change makes the owner's artifacts that are not `REMOVED`
`PENDING` (`db/users.py:reconcile_user_email__no_commit`), so their
ACL gets the new email. An artifact with nothing to index has no document
and is never `INDEXED`: a chat delete makes the chat's artifacts `REMOVED`,
outside the beat's partial index, and one with no available version ends `FAILED`
after its pickups. The text cache is `ARTIFACT_TEXT_FILE_PREFIX` + `file_id`
(`FileOrigin.PLAINTEXT_CACHE`), written by
`file_store/utils.py:get_or_extract_artifact_text`, the one entry point for
a version's text. It extracts with
`file_processing/extract_file_text.py:extract_text_pages` (PDF pages,
PowerPoint slides, spreadsheet sheets; any other file as one text; no image
captions), ends each page with a form feed, and keeps at most 10 M characters
of a file up to 50 MiB. A version's file never changes
([[#file-id-write-once]]), so its cached text never goes stale. The sandbox
tools `library_read` and `library_find` ([[code-execution]]) read it.
`library_search` (and the `artifact` tool's list with a
query) searches these documents with `attached_document_ids` set to the
artifacts that its database query keeps, with no ACL, and reports
`content_indexed` from `index_status` ([[code-execution]]).

**Serving.** `server/query_and_chat/chat_backend.py:fetch_chat_file` resolves
the id, calls `backend/onyx/access/access.py:user_can_access_chat_file`, and
streams the blob. It sends `Content-Disposition: attachment` unless
`file_store/serving.py` allows the type inline. It caches for a year with an
ETag on the file id, because a file id never changes content
([[#file-id-write-once]]). With `?parsed=true`, a spreadsheet returns a JSON
preview. With `?preview=pdf`, a PowerPoint or Word file returns only the PDF
that its preview row links, and the GET never writes:
`ChatArtifactVersion.preview_file_id` or `UserFile.preview_file_id`
(`chat/file_preview.py:resolve_chat_file_preview` finds the row; the route
streams the link, or returns 409 `PREVIEW_NOT_READY` when the row has none).
`POST /chat/file/{file_id}/preview` (`server/query_and_chat/chat_backend.py:make_chat_file_preview`,
the same access check) returns the linked PDF, or converts the file and links
the result (`chat/file_preview.py:convert_chat_file_preview_pdf`, which owns
the flow; the route maps its errors), with `Cache-Control: private, no-store`
and no ETag. The preview row is the file's artifact version, else the oldest
of its user files that is not being deleted, whichever id the request used
(`db/chat.py:get_chat_file_preview_row`, on `ix_user_file_file_id`: user
files can share one file, so `user_file.file_id` is not unique), and the
link updates that row by its key. The type is the record's MIME type when
it converts, else the one that `guess_mime_type` gives the name. The
conversion runs only in the sandbox of the file's owner
(`ChatArtifact.user_id` or `UserFile.user_id`), whoever asks, so a reader
cannot plant a preview and the PDF has the trust of the file; a publish
converts in the publisher's sandbox, who is the owner. It runs
`render_preview` from bytes, at most 20 MiB, without the first page, in a
30 s budget from when the VM runs, and the flow saves the PDF and links it
(`link_chat_file_preview`, only when the row has none, so a concurrent
conversion returns and then deletes its own copy; a link that raises deletes
it too). Both requests return 422 `PREVIEW_UNAVAILABLE` for another type or
a file that no row owns (a Python tool output) or a user file that is being
deleted. The POST also returns 422 for a larger file, a file that the
converter rejects or does not convert within the budget, a PDF over
`RENDER_PREVIEW_MAX_PDF_BYTES` or a deployment with no harness sandbox, and
503 when the sandbox cannot start or be reached; other failures are 500.
None of them is stored. The access check is the
source file's; no branch of `user_can_access_chat_file` admits the preview's
own id, so `/chat/file/{preview id}` is a 404.

---

## Contracts and traps

1. `read-check-404` **Every read checks the acting user, and denial is a
   404.** `backend/onyx/access/access.py:user_can_access_chat_file` admits, in order: the file owner;
   readers of an agent the file is attached to; readers of a session whose
   `ChatMessage.files` lists it; readers of the session of a chat output file
   (`configs/constants.py:CHAT_OUTPUT_FILE_ORIGINS`: the session stamped on a
   generated image, the artifact's session of a published file and of its
   thumbnail, which `db/access.py:get_chat_output_file_row` matches on
   either version column);
   and the document ACL for connector files. A new kind of file must fit
   one of these branches, or nobody can read it.
   `FileStore.presign_download` checks no user: a caller that hands a URL to
   anyone else must authorize first.
2. `generated-file-session-stamp` **Every generated image must carry the
   session stamp, and every published file its artifact version.** A
   `chat_session_id` in the `file_metadata` of a `CHAT_IMAGE_GEN` file gives
   the file to every reader of that session: its owner, and everyone while
   it is shared as `PUBLIC`. On any other origin the stamp grants nothing. A
   `CHAT_IMAGE_GEN` file with no stamp is open to every signed-in user
   (`backend/onyx/access/access.py:user_can_access_chat_file`). Unstamped
   generated images depend on this, so the open branch must stay. A new writer
   that forgets the stamp creates an open file, and nothing fails. Save
   through `file_store/utils.py:save_chat_output_file`, which stamps the
   file. A `CHAT_ARTIFACT` file, and a `CHAT_ARTIFACT_THUMBNAIL` file,
   gets its chat from its version's artifact instead. Without a version, only a saved message that lists the file
   gives access to it (`db/access.py:user_can_access_chat_message_file`), and
   the chat's file list leaves it out. Save it through
   `db/chat.py:save_chat_artifact`.
3. `say-which-id` **Say which id you mean.** A new route or tool that accepts
   "a file id" must state whether it is a blob id or a `UserFile.id`. Pass a
   `UserFile.id` to `FileStore.read_file` and you get "not found" for a file
   that exists.
4. `index-inline-share-id` **Index and inline paths share the
   `UserFile.id`.** `background/celery/tasks/user_file_processing/tasks.py:_load_user_file_documents` sets the document id to
   `str(UserFile.id)`, and inline context cites the same id. Citations survive
   when a project crosses the fit limit ([[projects]]).
5. `delete-order` **Delete in order: index, blobs, row.**
   `background/celery/tasks/user_file_processing/tasks.py:delete_user_file_impl` deletes the preview PDF, the blob and the
   plaintext, and keeps the row when a blob delete fails, because the
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
   analysis is on. A code or script file
   (`file_processing/file_types.py:OnyxFileExtensions.SANDBOX_ONLY_EXTENSIONS`,
   for example `.py`, `.ts`, `.sh`) must be text. Upload marks it `SKIPPED`, so
   it is never indexed. The sets that connectors index do not include these
   extensions. `file_processing/extract_file_text.py:_extract_text_and_images`
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
    (`chat/restoration.py:persist_checkpoint_files`). The dumps of parked code
    mode programs use `agent-checkpoint/<root session id>/<unique id>`
    instead, and the checkpoint row that saved them deletes them when it ends
    or is replaced; session hard delete removes every blob by that prefix
    ([[chat-persistence#checkpoints-for-approvals]]).
13. `artifact-cleanup-levels` **A published file has two cleanup levels.**
    Per version, `db/chat.py:delete_chat_artifact_files` deletes the
    thumbnail and the preview PDF, then the text cache, then the file. Per artifact, the search
    document goes after the commit that removes the artifact row or deletes
    its chat or owner
    (`indexing/chat_artifact_index.py:delete_chat_artifacts_from_index`, a
    plain delete: a write that committed within the second before it can
    leave owner-only chunks). The chat delete functions return the artifact
    ids, and their callers delete after the commit: the chat delete routes
    (soft and hard), the chat retention task and the clean-up of a failed
    publish. The user delete collects the ids, and each version's files
    under its row lock (`lock_chat_artifact_version_files`), in
    `db/users.py:delete_user_from_db__no_commit` before the cascade from
    the user removes the rows, and deletes both in `finish_user_delete`
    (the files with the user's other files), which the admin delete
    (`db/users.py:delete_user_from_db`) and the auth delete
    (`backend/onyx/auth/users.py:UserManager.delete`) run after their commit. The index delete is not
    in the per-version cleanup, because a failed publish that drops one
    version must keep a live artifact's document. A new path that removes
    artifact rows, or hides their chat, must call it after its commit, or the
    owner's ordinary search keeps finding the file.
14. `minio-dual-store` **While `S3_LEGACY_ENDPOINT_URL` is set, the S3 store
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
    upgrade disappear. A presigned upload skips the dual write, so its finalize
    leaves the marker instead
    (`file_store/file_store.py:S3BackedFileStore._on_presigned_upload_finalized`),
    and a file only in MinIO gets no download URL.

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

- [[indexing-pipeline]]: `run_indexing_pipeline` for user files and
  published files.
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
  save through `file_store/utils.py:save_chat_output_file`
  ([[#generated-file-session-stamp]]). List
  the current writers with `git grep -n "save_chat_output_file(" backend/onyx`.
- `add-storage-backend` **Add a storage backend.** Copy `file_store/gcs_file_store.py`. List the
  current backends in `file_store/file_store.py:get_default_file_store`.
  Implement every `FileStore` method, write the record through
  `upsert_filerecord` so incognito blobs get their cleanup stamp, and keep
  [[#file-id-write-once]]. An object-store backend subclasses
  `PresignableFileStore` and implements its signing hooks, because the Craft
  Firecracker runtime will move files through presigned URLs. Override
  `FileStore.is_transient_error` for the service's throttling and connection
  errors, so a chat run that parks retries them instead of ending.
- `investigate-file-404` **Investigate a 404 on `/chat/file/{file_id}`.** Find which id the caller
  sent ([[#say-which-id]]). Then walk the branches of
  `user_can_access_chat_file` in order for that user: `user_file.user_id`,
  agent links, `chat_message.files`, the `chat_session_id` in
  `file_record.file_metadata` (a published file: its version's artifact),
  and the connector document ACL.
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
- `backend/tests/external_dependency_unit/indexing/test_chat_artifact_indexing.py`
  covers published file indexing and the text cache, and
  `backend/tests/external_dependency_unit/opensearch/test_chat_artifact_search.py`
  covers their search access and deletes.
- `backend/tests/integration/tests/projects/` covers upload, link and delete.
- By hand: as a second user, request another user's upload and generated image
  through `/chat/file/{file_id}`. Both must return 404 unless the session is
  shared as public.
