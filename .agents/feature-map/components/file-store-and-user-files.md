# File Store and User Files

> Files the user provides directly, not through a connector: chat attachments,
> project files, and generated images. Covers the blob abstraction, upload,
> text extraction, token counting, the two ways a file reaches the model
> (inlined text or RAG over an index), and how a file gets served back.

**Verified against:** `268e4d5a3d` (2026-10-05)
**Domain:** core-loop
**Edition:** CE
**Owns:**
`backend/onyx/file_store/`, `backend/onyx/file_processing/`,
`backend/onyx/db/file_record.py`, `file_content.py`, `user_file.py`, `projects.py`,
`backend/onyx/indexing/adapters/user_file_indexing_adapter.py`,
`backend/onyx/background/celery/tasks/user_file_processing/`,
`backend/onyx/server/features/projects/`,
`backend/onyx/tools/tool_implementations/file_reader/file_reader_tool.py`,
`web/src/lib/projects/`, `web/src/app/app/components/files/`

**Read first:** `backend/onyx/file_store/README.md` for the storage-backend
configuration matrix. `[[context-assembly]]` describes what happens to a file's
content once it reaches the LLM; this document owns everything upstream of
that: where the bytes live, how they get extracted and counted, and how they
get indexed or served.

---

## 1. What the user experiences

The user drags a PDF into the chat composer, or attaches a spreadsheet to a
project, then asks a question about it. A small file's content shows up in the
answer almost immediately. A large project file takes a moment to say
"processing", then becomes searchable: the model finds the relevant section
and cites it, rather than having the whole document stuffed into the prompt.

An uploaded image is described or analyzed directly by the model. When the
assistant generates an image (through code execution or an image tool), it
appears inline in the chat and can be downloaded.

Deleting a file that is still attached to a project or a custom agent is
blocked with an explicit warning, rather than silently breaking the project.
Attaching a file inside an incognito chat behaves like a normal upload except
that a background sweep deletes the file's blob and its row after the session ends.

---

## 2. Surfaces

### HTTP endpoints

| Method | Path | Handler | Notes |
|---|---|---|---|
| POST | `/user/projects/file/upload` | `api.py:upload_user_files` | The upload endpoint. Accepts a project id, an incognito session id, and a temp-id map for optimistic UI. |
| GET | `/user/files/recent` | | Files not attached to any project (`server/manage/users.py`). |
| GET | `/user/projects/files/{project_id}` | `api.py:get_files_in_project` | |
| DELETE | `/user/projects/file/{file_id}` | `api.py:delete_user_file` | Refuses when the file has project or persona associations. |
| GET | `/user/projects/file/{file_id}` | `api.py:get_user_file` | Metadata (`UserFileSnapshot`), not bytes. |
| POST | `/user/projects/file/statuses` | `api.py:get_user_file_statuses` | Poll target while a file is `PROCESSING`. |
| DELETE/POST | `/user/projects/{project_id}/files/{file_id}` | `unlink_user_file_from_project`, `link_user_file_to_project` | |
| GET | `/user/projects/{project_id}/token-count`, `/user/projects/session/{id}/token-count` | | Aggregate token counts for the file-budget UI. |
| GET | `/chat/file/{file_id:path}` | `chat_backend.py:fetch_chat_file` | **The serving endpoint.** Accepts either a storage `file_id` or a `UserFile.id`; see §4.5. |

### Environment configuration

| Variable | File | Effect |
|---|---|---|
| `FILE_STORE_BACKEND` | `configs/app_configs.py` | `s3` (default), `gcs`, `azure`, or `postgres`. Selects the `FileStore` implementation (§3, §4.1). |
| `S3_FILE_STORE_BUCKET_NAME`, `S3_ENDPOINT_URL`, `S3_AWS_ACCESS_KEY_ID`/`SECRET`, `AWS_REGION_NAME`, `S3_FILE_STORE_PREFIX`, `S3_VERIFY_SSL` | | S3-compatible backend config (also covers the bundled object store and DO Spaces). Onyx logs a warning when the endpoint uses the default `minioadmin` credentials. |
| `S3_LEGACY_ENDPOINT_URL`, `S3_LEGACY_AWS_ACCESS_KEY_ID`/`SECRET`, `LEGACY_COPY_SETTLE_SECONDS`, `LEGACY_COPY_WORKERS`, `LEGACY_COPY_ALL_OBJECTS` | `configs/app_configs.py` | The old MinIO store that earlier releases wrote to. See §4.1. |
| `GCS_FILE_STORE_BUCKET_NAME`, `GCS_PROJECT_ID`, `GCS_SERVICE_ACCOUNT_KEY_PATH`/`JSON` | | GCS backend config. |
| `AZURE_FILE_STORE_CONTAINER_NAME`, `AZURE_STORAGE_ACCOUNT_NAME`/`URL`, `AZURE_STORAGE_CONNECTION_STRING`/`ACCOUNT_KEY` | | Azure Blob backend config. |
| `DISABLE_VECTOR_DB` | `configs/app_configs.py` | Skips the vector-DB indexing path entirely; project files fall back to `FileReaderTool` metadata instead of RAG (§4.4). Also switches upload/delete/project-sync from Celery tasks to in-request `BackgroundTasks`. |
| `MAX_EMBEDDED_IMAGES_PER_FILE`, `MAX_EMBEDDED_IMAGES_PER_UPLOAD` | `configs/app_configs.py` | Caps on embedded images inside one PDF/DOCX and across one upload batch, checked in `projects_file_utils.py:categorize_uploaded_files`. |
| `PDF_TEXT_EXTRACTION_TIMEOUT_SECONDS`, `MAX_XLSX_CELLS_PER_SHEET` | `configs/app_configs.py` | Extraction limits (`extract_file_text.py`). |
| Admin setting `user_file_max_upload_size_mb`, `file_token_count_threshold_k` | `server/settings/store.py:load_settings` | Per-deployment upload size cap and token-count rejection threshold (`projects_file_utils.py:categorize_uploaded_files`). |

---

## 3. Data model

```
FileRecord (file_record)              FileContent (file_content, postgres backend only)
  file_id PK  ─────────────────┐        file_id PK/FK → file_record.file_id (CASCADE)
  display_name                 │        lobj_oid       (pg_largeobject reference)
  file_origin (enum)           │        file_size
  file_type                    │
  file_metadata (JSONB)        │      UserFile (user_file)
  bucket_name / object_key     │        id PK (UUID)
  file_size                    │        user_id FK → user.id
  created_at / updated_at      │        file_id ─────────┘  (references FileRecord.file_id,
                                │                             not a DB foreign key)
                                │        name, file_type, content_type, link_url
                                │        token_count, chunk_count
                                │        status (PROCESSING/INDEXING/COMPLETED/SKIPPED/FAILED/CANCELED/DELETING)
                                │        incognito, incognito_session_id
                                │        needs_project_sync, needs_persona_sync
                                │        secondary_reconcile_pending
                                │        last_project_sync_at, last_accessed_at

Project__UserFile (project__user_file)      Persona__UserFile
  project_id FK → user_project.id             persona_id FK
  user_file_id FK → user_file.id              user_file_id FK
  created_at                                (owned by [[agents-personas]])

UserProject (user_project)
  id PK, user_id FK, name, description, instructions
```

- `FileRecord` (`onyx/db/models.py:FileRecord`) is the metadata row every
  backend writes, regardless of where bytes live. `bucket_name`/`object_key`
  are deliberately generic so all four backends share one schema
  (`file_store/README.md`).
- `FileContent` (`onyx/db/models.py:FileContent`) exists only for the
  Postgres-Large-Object backend; it is a satellite table, not an alternative
  to `FileRecord`. A Postgres-backed file always has both rows.
- `UserFile` (`onyx/db/models.py:UserFile`) is the chat-facing identity: what
  the frontend and the LLM address by `UserFile.id` (a UUID). It points at a
  `FileRecord.file_id` by value, not a SQL foreign key
  (`onyx/db/models.py:UserFile.file_id`), so a storage rename
  (`FileStore.change_file_id`) must update both sides by hand.
- `file_id` (`FileRecord`) and `UserFile.id` are two different identifier
  spaces. `chat_backend.py:fetch_chat_file` and
  `db/user_file.py:get_file_id_by_user_file_id` translate between them; mixing
  them up is a common bug source (§9).
- `Project__UserFile` is the many-to-many join; a `UserFile` can belong to
  zero, one, or more projects, and separately to zero or more personas via
  `Persona__UserFile` ([[agents-personas]]).

---

## 4. How it works

### 4.1 The storage abstraction

`file_store/file_store.py:get_default_file_store` reads `FILE_STORE_BACKEND`
and returns one of four `FileStore` implementations: `S3BackedFileStore`
(also covers MinIO, DigitalOcean Spaces, any S3-compatible endpoint),
`GCSBackedFileStore`, `AzureBlobBackedFileStore`, or `PostgresBackedFileStore`
(`onyx/file_store/postgres_file_store.py`, using `FileContent.lobj_oid`
against `pg_largeobject`, chosen only when `FILE_STORE_BACKEND=postgres`; there is no automatic fallback).
Every implementation writes the same `FileRecord` row
(`file_store.py:S3BackedFileStore.save_file` calls
`db/file_record.py:upsert_filerecord`); only where the bytes physically land
differs. Callers never branch on backend; they always go through
`FileStore`'s abstract interface (`initialize`, `has_file`, `save_file`,
`read_file`, `delete_file`, `get_file_with_mime_type`, `change_file_id`,
`list_files_by_prefix`).

**Legacy MinIO store.** While `S3_LEGACY_ENDPOINT_URL` is set (and differs from
`S3_ENDPOINT_URL`), `S3BackedFileStore` writes and deletes in both stores. A read that
misses the main store falls back to the legacy store. The copy tool
`python -m onyx.file_store.legacy_copy [--retire | --replay]` (`legacy_copy.py`) copies the
objects that file records point at into the main store. After `--retire`, a marker object
(`LEGACY_RETIRED_MARKER_KEY`) makes writes and deletes skip the legacy store. Reads still fall
back to it.

`file_store.py:content_byte_size` computes the stored size at save time;
`FILE_SIZE_MISSING_SENTINEL` (-1) marks a row whose backing object was
confirmed missing so listings stop re-probing.

### 4.2 Upload flow

```
POST /user/projects/file/upload          server/features/projects/api.py:upload_user_files
  └─ upload_files_to_user_files_with_indexing   db/projects.py
      ├─ create_user_files                      db/projects.py
      │   ├─ categorize_uploaded_files          server/features/projects/projects_file_utils.py
      │   ├─ upload_files                       server/documents/connector.py  (blob write)
      │   └─ UserFile row insert, status=PROCESSING (or SKIPPED)
      └─ per indexable file (not `SKIPPED`), enqueue:
          PROCESS_SINGLE_USER_FILE  →  background/celery/tasks/user_file_processing/tasks.py
```

Synchronous, inside the request:
- `projects_file_utils.py:categorize_uploaded_files` extracts text (or
  estimates image tokens) and token-counts every file, rejecting anything over
  the admin size limit, over the token limit (spreadsheets over the limit are
  accepted and skip indexing instead), password-protected, or with too many
  embedded images. It calls `extract_file_text` with `break_on_unprocessable=False`, so
  extraction failure here becomes a *rejection*, not a silent empty result.
- `server/documents/connector.py:upload_files` writes the accepted bytes to
  the blob store immediately (`FileOrigin.USER_FILE`), returning storage
  `file_id`s.
- `db/projects.py:create_user_files` creates the `UserFile` row per accepted
  file with `status=UserFileStatus.PROCESSING` (or `SKIPPED` for files
  exempted from indexing, e.g. spreadsheets over the token threshold) and
  links it to `project_id` if one was given (never for incognito uploads,
  `create_user_files`'s `if project_id and incognito_session_id is None`
  branch).

Asynchronous, in `PROCESS_SINGLE_USER_FILE`
(`tasks.py:process_user_file_impl`): loads the blob back through
`LocalFileConnector` (`tasks.py:_load_user_file_documents`), then dispatches
to one of the two consumption paths (§4.4).

### 4.3 Extraction

`file_processing/extract_file_text.py` and `file_processing/extract_file_text.py:extract_text_and_images`
dispatch by extension:

| Extension | Function | Notes |
|---|---|---|
| `.pdf` | `read_pdf_file` (via `pdf_to_text` for text-only callers) | Runs in an isolated subprocess by default (`isolate_pdfium=True`); embedded images extracted via `pdf_image_utils.py:iter_pdf_extracted_images`. |
| `.docx` | `read_docx_file` | Embedded images via `extract_docx_images`. |
| `.pptx` | `read_pptx_file` / `pptx_to_text` | Embedded images via `extract_pptx_images`; chart-to-markdown conversion is patched to a no-op for performance (`image_summarization.py:get_markitdown_converter`). |
| `.xlsx` | `xlsx_sheet_extraction` / `xlsx_to_text` | Streams rows; `stage_xlsx_sheets` materializes large tabular sections to a staged file rather than holding them in memory. |
| `.xlsm` | `extract_file_text_locally` calls `xlsx_to_text` | `extract_text_and_images` has no `.xlsm` dispatch, so that path returns empty text for it. |
| `.eml` | `eml_to_text` | |
| `.epub` | `epub_to_text` | |
| `.html` | `html_utils.py:parse_html_page_basic` | |
| unknown / code files | `is_text_file` heuristic, then `file_io_to_text` | Lets `.py`, `.js`, `.rs`, etc. through as plain text. |
| images | not text-extracted here | See below. |

If `get_unstructured_api_key()` is configured, every file first tries
`unstructured.py:unstructured_to_text` (the Unstructured API) before falling
back to the in-process parsers above (`extract_file_text.py:extract_file_text`
and `_extract_text_and_images`).

**Images do not go through OCR.** A standalone uploaded image is never
text-extracted; `_extract_text_and_images` returns empty text for image
extensions and the model receives the raw image bytes directly as a vision
input (`ChatFileType.IMAGE`, consumed in
`process_message.py:extract_context_files`). Embedded images inside a PDF or
DOCX, by contrast, are decoded and sent through a **vision LLM** captioning
pipeline, `file_processing/image_summarization.py:summarize_image_with_error_handling`
→ `summarize_image_pipeline` → `_summarize_image`, gated by
`configs/llm_configs.py:get_image_extraction_and_analysis_enabled`. There is
no OCR step in either path; both eventually rely on a multimodal LLM call,
either directly (loose image) or via captioning (embedded image).
`_encode_image_for_llm_prompt` rejects unsupported MIME types by raising
`UnsupportedImageFormatError`, which the wrapper turns into a logged skip, not
a hard failure.

`extract_text_and_images`'s outer `except Exception` (`_extract_text_and_images`)
logs the exception (`logger.exception`) and returns an empty `ExtractionResult`
on any unexpected parser crash. This is the one place extraction failure is *not* surfaced to the caller (see §5 and §9);
the upload-time path (`categorize_uploaded_files`) is stricter and rejects
empty text, except for a PDF or DOCX that has detected embedded images (see §5).

### 4.4 The two consumption paths

Every project/context file goes through
`process_message.py:extract_context_files`, which decides per-turn whether the
aggregate token count of eligible files fits under
`(llm_max_context_window - reserved_token_count) * 0.6`
([[context-assembly]] §4.3 owns this ceiling and the reasoning behind 60%).

**Path A: inlined as text.** Below the ceiling, `extract_context_files` calls
`file_store/utils.py:load_in_memory_chat_files` to pull the plaintext (or
original bytes for non-text types) into memory, and returns `file_texts` that
`[[context-assembly]]`'s `_create_context_files_message` renders into the
`document`-keyed JSON block injected as a user message.

**Path B: chunked and embedded into the search index.** At or above the
ceiling, files are flagged `use_as_search_filter=True` instead
(`extract_context_files`, the `aggregate_tokens >= max_actual_tokens` branch)
and the model must retrieve them via the internal search tool
([[tools-framework]], [[internal-search]]). This path does not wait for the
ceiling, though: **indexable project files are vectorized at upload time**,
independent of whether a given turn's context would fit them
(`chat/README.md`, "Projects"). Files marked `UserFileStatus.SKIPPED`
(`db/projects.py`, over-threshold tabular files in `skip_indexing`) are not indexed. The indexing side is
`indexing/adapters/user_file_indexing_adapter.py:UserFileIndexingAdapter`,
driven by `background/celery/tasks/user_file_processing/tasks.py:_process_user_file_with_indexing`,
which runs the same `run_indexing_pipeline` used for connector documents
([[indexing-pipeline]]) with `UserFileIndexingAdapter` supplying the
lock/prepare/enrich hooks. The document's id is stamped as
`str(UserFile.id)` (`tasks.py:_load_user_file_documents`), which is what lets
a search-tool citation resolve back to the same `UserFile.id` the frontend
already knows (§5, contract 3).

When `DISABLE_VECTOR_DB` is set, or the file is an incognito attachment
(`skip_search_index = uf.incognito`, `tasks.py:process_user_file_impl`),
indexing is skipped entirely: `_process_user_file_without_vector_db` computes
a token count with the default LLM's tokenizer
(`llm/factory.py:get_llm_tokenizer_encode_func`), stores plaintext via
`file_store/utils.py:store_user_file_plaintext`, and marks the file
`COMPLETED` with `chunk_count=0`. In this mode, an over-budget file falls back
to `FileToolMetadata` entries naming the `FileReaderTool`
([[tools-framework]]) instead of RAG, since there is no vector index to
search (`extract_context_files`'s `DISABLE_VECTOR_DB` branch;
`FileReaderTool.is_available` is itself gated on `DISABLE_VECTOR_DB`).

Search scoping for the RAG path uses `project_id_filter` and
`persona_id_filter` on the document index
(`onyx/document_index/FILTER_SEMANTICS.md`,
`onyx/document_index/opensearch/search.py`). Both are **primary** triggers: a
chat inside a project is scoped to that project's files
(`project_id_filter` alone restricts search to the project, it does not also
search team knowledge), and a persona with attached user files is scoped to
those files via `persona_id_filter`. See `[[internal-search]]` for the full
filter-composition rules.

Lazy file descriptors share one byte loader and cache across shallow and deep copies.
Concurrent first reads load the bytes once. Serialization excludes this shared resource.

### 4.5 Token counting

Computed **at upload time**, before any chat turn runs:
`projects_file_utils.py:categorize_uploaded_files` resolves a tokenizer via
`natural_language_processing/utils.py:get_tokenizer(model_name, provider_type)`
from the workspace's default LLM model
(`db/llm.py:fetch_default_llm_model`), falling back to
`_get_default_tokenizer()` (`HuggingFaceTokenizer(DOCUMENT_ENCODER_MODEL)`)
when the provider type is unrecognized. Text/document files are counted with
`natural_language_processing/utils.py:count_tokens` against the extracted
text. Images are **not** tokenized against real content; their count is a
heuristic, `projects_file_utils.py:estimate_image_tokens_for_upload`, which
opens the image, caps its long side at 2048px, and estimates
`patches + overhead` assuming 16px ViT-style patches. The result is written to
`UserFile.token_count` (`db/projects.py:create_user_files`) and never
recomputed unless the file is reprocessed
(`_process_user_file_without_vector_db` overwrites it with a real LLM-tokenizer
count in the no-vector-DB path).

### 4.6 Chat attachments vs. project files

Both load through the same `extract_context_files` function, but their
product lifetime differs, and [[context-assembly]] (§4.3 there) is the
authority on how this changes prompt position: a chat attachment is a
point-in-time inclusion that can drift out of context under truncation
pressure; a project file moves forward every cycle and is never dropped. This
document is only concerned with where each lives at rest: a chat attachment's
`UserFile` row has no `Project__UserFile` link and is discoverable via
`GET /user/files/recent`; a project file has a `Project__UserFile` row and is
scoped by `project_id_filter` in search.

### 4.7 Generated files

The image-generation tool (`tools/tool_implementations/images/image_generation_tool.py`)
saves its output through `file_store/utils.py:save_files` →
`save_file_from_url` / `save_file_from_base64`, both writing
`FileOrigin.CHAT_IMAGE_GEN` (`file_store/utils.py`). These blobs get a
`FileRecord` but **no `UserFile` row**: they are addressed directly by storage
`file_id` and rendered inline via `buildImgUrl`
(`web/src/app/app/components/files/images/utils.ts`) pointing at
`/chat/file/{file_id}`. The Python/code-interpreter tool
(`tools/tool_implementations/python/python_tool.py`) writes files the same
way, under the same `FileOrigin.CHAT_IMAGE_GEN` origin (despite the name, it
covers any tool-generated chat file, not only images). See §5 and §9 for the
access-control consequence of this.

### 4.8 Serving: `GET /chat/file/{file_id}`

`server/query_and_chat/chat_backend.py:fetch_chat_file`:

1. Accepts either a storage `file_id` or a `UserFile.id`; if
   `db/user_file.py:get_file_id_by_user_file_id` resolves the input as a
   `UserFile.id`, it is translated to the underlying `FileRecord.file_id`
   before anything else runs.
2. Authorizes with `access/access.py:user_can_access_chat_file` (§5).
3. Reads the record via `get_default_file_store().read_file_record`.
4. For spreadsheets requested with `?parsed=true`, serves a JSON preview
   instead of raw bytes (`is_spreadsheet_mime_type`); otherwise streams the
   stored bytes with `Content-Disposition: attachment` unless
   `serving.py:resolve_inline_disposition` says the MIME type is safe to
   render inline.
5. Sets a long-lived, `private` cache with an `ETag` keyed on `file_id` and a
   `RESPONSE_POLICY_VERSION`, since content is immutable and access-controlled
   per request regardless of caching.

### 4.9 Cleanup

- **Explicit delete**: `DELETE /user/projects/file/{file_id}`
  (`api.py:delete_user_file`) refuses when the file has project or persona
  associations (`user_file.projects`, `user_file.assistants`), forcing the
  caller to unlink first. Otherwise it sets `status=DELETING` and enqueues
  `DELETE_SINGLE_USER_FILE`, whose implementation
  (`tasks.py:delete_user_file_impl`) deletes the file from every document
  index, deletes both the original and plaintext blobs
  (`FileStore.delete_file`, `error_on_missing=False`), and only then deletes
  the `UserFile` row, in that order, so a failed blob delete keeps the row for
  retry rather than losing the pointer.
- **Project delete**: `DELETE /user/projects/{project_id}`
  (`api.py:delete_project`) unlinks `Project__UserFile` rows and chat
  sessions but does **not** delete the underlying `UserFile` rows or blobs;
  files fall back to being ordinary (unassociated) recent files. Deleting a
  project cannot orphan a blob.
- **Incognito uploads**: `sweep_stale_incognito_user_files`
  (`chat/incognito.py`, run from `check_for_user_file_delete`) marks uploads of
  ended incognito sessions as deleting. `delete_user_file_impl` then deletes the
  blob, the plaintext blob, and the `UserFile` row. No redacted row remains.
- **Incognito sweep**: `check_for_incognito_file_cleanup`
  (`tasks.py`) retries deletion of tool-generated blobs whose session-teardown
  pass failed, driven by the `INCOGNITO_SESSION_METADATA_KEY` stamp every
  `FileRecord` gets when written under a content-free session
  (`db/file_record.py:upsert_filerecord`); `db/file_record.py:get_incognito_file_ids`
  / `get_session_ids_with_incognito_files` are its query surface.
- **Staged files** (large tabular sections materialized during extraction,
  `file_store/staging.py:stage_raw_file`) are cleaned up by the caller
  explicitly (`tasks.py:_load_user_file_documents`'s
  `delete_files_best_effort` on both the success and failure paths), not by a
  background sweep.
- No sweep was found for orphaned `FileRecord` rows created by a crashed
  upload (a blob written but no `UserFile` row committed). Treat this as
  unverified rather than confirmed-absent; it was not found in the searched
  paths.

---

## 5. Contracts and invariants

1. **A file read must be authorized against the acting user.**
   `chat_backend.py:fetch_chat_file` always calls
   `access.py:user_can_access_chat_file` before touching the file store, and
   returns 404 (not 403) on denial so a caller cannot use the status code to
   probe for existence across ownership boundaries. **This holds for
   `UserFile`-backed files** (owned, or attached to a readable persona, or
   attached to a session the user owns or that is public). For tool-generated
   files, a `CHAT_IMAGE_GEN` file carries its owning chat session in
   `FileRecord.file_metadata` (`file_store/utils.py:chat_image_gen_metadata`), and
   `access.py:_user_can_access_chat_image_gen_file` grants it to the session owner,
   or to anyone when the session is shared as `PUBLIC` and not deleted. A row
   written before stamping carries no session and cannot be scoped; see §9.
   Every new writer of a `CHAT_IMAGE_GEN` file must pass the session id, or the
   file silently falls into the unscoped legacy case.
2. **Token counts must be computed before a file is offered to a model.**
   `UserFile.token_count` is set at upload
   (`projects_file_utils.py:categorize_uploaded_files`) and read, never
   recomputed, by `extract_context_files`'s budget check. A file type added
   without updating `categorize_uploaded_files` will silently carry
   `token_count=None` or 0 into the budget math ([[context-assembly]] §4.8
   depends on this being accurate).
3. **The two consumption paths must agree on identity.** The inline path
   cites `UserFile.id`; the RAG path indexes the document under
   `str(UserFile.id)` (`tasks.py:_load_user_file_documents`). A change to
   either identifier breaks citation resolution across the boundary where a
   file crosses from "fits in context" to "must be searched," or vice versa
   as a project grows.
4. **Deleting a project or session must not orphan blobs.** `delete_project`
   only unlinks; `delete_user_file` refuses while associations exist and
   otherwise deletes index entries, blobs, and the row, in that order
   (`tasks.py:delete_user_file_impl`). If a blob delete fails, the row stays
   so a retry can find the blob. If the blob delete succeeds and the final row
   commit fails, the row briefly points at a deleted blob. The retry is safe
   because the blob deletes use `error_on_missing=False`.
5. **Extraction failure must be surfaced, not silently indexed as empty**, at
   upload time: `categorize_uploaded_files` rejects a file it cannot extract
   text from (`extract_file_text(..., break_on_unprocessable=False)` returning
   `""` becomes a `RejectedFile`, not silent acceptance). The exception is a PDF
   or DOCX with empty text but detected embedded images (image extraction on):
   it is accepted with a token count of 0 and indexed through the captioning
   path. The other exception is
   `extract_text_and_images`'s internal exception handler, which does return
   an empty `ExtractionResult` on an unexpected parser crash during indexing
   (§4.3, §9); a new caller of `extract_text_and_images` must not assume a
   non-empty result implies successful extraction.
6. **`FileRecord.file_id` and `UserFile.id` are different keys with no SQL
   foreign key between them.** Any new code path that accepts "a file id"
   must be explicit about which one it means, or resolve through
   `db/user_file.py:get_file_id_by_user_file_id` the way `fetch_chat_file`
   does.
7. **On the object-store backends (S3, GCS, Azure), a storage rename
   (`FileStore.change_file_id`) does not move the backing object**, only
   repoints the `FileRecord`. The old `file_id` must never be reused for a new
   `save_file` call, or the new write silently overwrites the renamed object
   still referenced by the old key. The Postgres backend is safe: it moves the
   `FileContent` row to the new id, so a reused id makes a new large object.

---

## 6. Relationships

**Depends on**
- [[llm-providers]]: tokenizer resolution (`get_tokenizer`) and the default
  LLM used for image summarization and no-vector-DB token counting.
- [[indexing-pipeline]]: `UserFileIndexingAdapter` runs the same
  `run_indexing_pipeline` connectors use.
- [[document-index]]: the RAG path's chunks live in the same index as
  connector documents, scoped by `project_id_filter`/`persona_id_filter`.
- [[access-control]]: `user_can_access_chat_file` is this component's sole
  authorization gate.
- [[background-jobs]]: all indexing, deletion, and project-sync work after
  upload runs through Celery (`user_file_processing` worker), or in-request
  `BackgroundTasks` when `DISABLE_VECTOR_DB` is set.

**Depended on by**
- [[context-assembly]]: consumes `load_in_memory_chat_files`,
  `UserFile.token_count`, and `extract_context_files`'s output directly.
- [[projects]]: owns `UserProject`/`Project.instructions`; this component owns
  the files a project holds and how they get into search.
- [[tools-framework]]: `FileReaderTool` and the internal search tool both
  resolve file content through this component.
- [[image-generation]]: writes through `save_files`/`FileOrigin.CHAT_IMAGE_GEN`
  and is served through the same `/chat/file/{file_id}` endpoint.
- [[chat-frontend]]: `web/src/lib/projects/svc.ts` is the sole client for
  upload, list, delete, and token-count endpoints; upload UI lives under
  `web/src/app/app/components/files/`.

---

## 7. Blast radius

| If your change… | Also check |
|---|---|
| adds a file type | `file_processing/file_types.py:OnyxFileExtensions`, the dispatch table in `extract_file_text.py:extract_file_text_locally` / `_extract_text_and_images`, and whether `categorize_uploaded_files` needs a new branch (image vs. text/document path) |
| changes the storage backend or adds a fifth backend | `file_store/README.md`'s config matrix, `get_default_file_store`'s factory, and every implementation of the abstract `FileStore` interface (`has_file`, `save_file`, `read_file`, `delete_file`, `change_file_id`, `list_files_by_prefix`) must stay behaviorally identical |
| changes token counting | [[context-assembly]] §4.8's reserved-token math and the 60% ceiling in `extract_context_files`; re-verify the image-token heuristic still matches provider reality if you touch `estimate_image_tokens_for_upload` |
| changes the user-file index path (`UserFileIndexingAdapter`, `_process_user_file_with_indexing`) | [[indexing-pipeline]], [[internal-search]]'s `project_id_filter`/`persona_id_filter` composition, and citation resolution (contract 3) |
| changes the serving endpoint (`fetch_chat_file`) | [[access-control]]; re-run the CHAT_IMAGE_GEN access check explicitly (§5, §9); the ETag/cache-control scheme assumes content is immutable per `file_id`, so a mutable-file feature needs a new caching story |
| changes deletion or project unlinking | Re-verify contract 4: no path should be able to delete a `UserFile` row while a blob or index entry still references it, or vice versa |

---

## 8. How to verify a change

### Tests

```bash
uv run --env-file .vscode/.env pytest backend/tests/unit -k "file_store or extract_file_text or projects_file_utils"
uv run --env-file .vscode/.env pytest backend/tests/external_dependency_unit -k "file_store or user_file"
uv run --env-file .vscode/.env pytest backend/tests/integration -k "user_file or projects or file"
```

See `backend/AGENTS.md` for the authoritative commands. Prefer integration
tests over unit tests for anything touching the upload-to-index pipeline.

### Manual reproduction

1. Confirm services are up: `tail -f backend/log/api_server_debug.log` and
   `backend/log/user_file_processing_debug.log` (or the matching
   `background_debug.log` if the worker is unsplit).
2. Sign in at `http://localhost:3000` as
   `admin_user@example.com` / `TestPassword123!`.
3. Create a project, attach a small text file, and ask a question about it.
   Confirm the answer cites it and the content appears in-context (check
   `GET /chat/available-context-tokens/{id}` reflects the file's token count).
4. Attach a large file (large enough to exceed the 60% ceiling given the
   active model's context window) to the same project. Confirm its status
   moves `PROCESSING` → `COMPLETED` (`GET /user/projects/file/statuses`), and
   that a question about content only in that file triggers an internal
   search tool call rather than being answered from raw context.
5. Upload an image. Confirm the model can describe its contents directly
   (no tool call).
6. Trigger image generation. Confirm the image renders inline and that
   `GET /chat/file/{file_id}` for it succeeds for the generating user.
7. As a second user, attempt `GET /chat/file/{file_id}` for the first user's
   plain uploaded `UserFile`: expect 404. Attempt the same for the
   first user's generated image `file_id`: expect 404 when the image carries its
   chat-session stamp and the session is not public (§5, §9). An image written before stamping
   still succeeds.

---

## 9. Footguns

- **A `CHAT_IMAGE_GEN` file with no session stamp is not session-scoped.**
  Rows written before stamping existed keep the old grant-to-any-authenticated-
  user behaviour, so existing images keep rendering. A new writer that forgets
  to pass `chat_session_id` produces the same unscoped row, and nothing fails
  loudly. Check the stamp whenever you add a path that saves a generated file.
- **`FileRecord.file_id` and `UserFile.id` look interchangeable and are not.**
  `fetch_chat_file` silently translates one into the other via
  `get_file_id_by_user_file_id`; a new caller that skips this step and passes
  a `UserFile.id` straight to `FileStore.read_file` will get a "not found"
  for a file that clearly exists.
- **`extract_text_and_images` swallows unexpected parser exceptions and
  returns empty text** (`_extract_text_and_images`'s outer `except Exception`),
  which will silently index a file as content-free during the async indexing
  path, even though the synchronous upload-time path
  (`categorize_uploaded_files`) is stricter and would have rejected the same
  failure. A parser bug can therefore produce a `COMPLETED` file with zero
  useful content instead of a visible `FAILED` status.
- **Images are never OCR'd.** A loose image upload goes to the model as raw
  vision input; an embedded image inside a PDF/DOCX goes through a
  vision-LLM captioning pass. There is no text-layer OCR step in this
  component at all; don't look for one when debugging "the model can't read
  text in this scanned PDF" (that content-free scan case is only rescued if
  it also has embedded images that survive the captioning path).
- **Project files are vectorized on upload regardless of the current turn's
  budget.** A project can look "small enough to fit" today and still have
  every file indexed; this is intentional (so growth doesn't require
  reindexing), not evidence of a bug when you see indexing work you didn't
  expect.
- **On object-store backends, `change_file_id` does not move the object.**
  Reusing a renamed-away `file_id` for a fresh `save_file` overwrites the object
  the renamed record still points at. Treat every `file_id` as write-once. The
  Postgres backend moves the `FileContent` row, so it does not have this hazard.
- **Deleting a `UserFile` is blocked, not cascaded**, while it has project or
  persona associations. A script that force-deletes without unlinking first
  will get a `has_associations=True` result, not a deletion; don't paper over
  that response as an error.
- **Incognito uploads never join a project even when a `project_id` is
  passed** (`create_user_files`'s incognito guard). If you see an incognito
  attachment missing from a project's file list, that is by design, not a
  sync bug.
