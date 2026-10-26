import io
import os
from collections.abc import Callable
from typing import cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.chat.models import AvailableFiles, ChatMessageSimple, SearchParams
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import (
    DEFAULT_PERSONA_ID,
    FileOrigin,
    MessageType,
)
from onyx.context.search.models import SearchDoc
from onyx.context.search.utils import sandbox_filename_for_document
from onyx.db.enums import (
    UserFileStatus,
)
from onyx.db.file_record import FileRecordNotFoundError
from onyx.db.models import ChatMessage, Persona, UserFile
from onyx.db.projects import get_user_files_from_project
from onyx.db.user_file import get_user_file_by_id
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_store.models import (
    ChatFileType,
    ChatLoadedFile,
    ContextFileMetadata,
    ExtractedContextFiles,
    FileDescriptor,
    FileToolMetadata,
    InMemoryChatFile,
    UserFileMetadata,
)
from onyx.file_store.utils import (
    get_default_file_store,
    load_in_memory_chat_files,
    plaintext_file_name_for_id,
    store_plaintext,
)
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.tools.models import ChatFile, SearchToolUsage
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time

logger = setup_logger()

APPROX_CHARS_PER_TOKEN = 4


def _collect_available_file_ids(
    chat_history: list[ChatMessage],
    context_user_files: list[UserFile],
) -> AvailableFiles:
    """Collect all file IDs the FileReaderTool should be allowed to access.

    Returns *separate* lists for chat-attached files (``file_record`` IDs) and
    project/user files (``user_file`` IDs) so the tool can pick the right
    loader without a try/except fallback."""
    chat_file_ids: set[UUID] = set()
    user_file_ids: set[UUID] = set()

    for msg in chat_history:
        if not msg.files:
            continue
        for fd in msg.files:
            try:
                chat_file_ids.add(UUID(fd["id"]))
            except (ValueError, KeyError):
                pass

    user_file_ids.update(file.id for file in context_user_files)

    return AvailableFiles(
        user_file_ids=list(user_file_ids),
        chat_file_ids=list(chat_file_ids),
    )


def _convert_loaded_files_to_chat_files(
    loaded_files: list[ChatLoadedFile],
) -> list[ChatFile]:
    """Convert ChatLoadedFile objects to ChatFile for tool usage (e.g., PythonTool).

    Returns lazy ChatFile objects: ``.content`` materializes via the underlying
    ``loaded_file.content`` only when a tool actually accesses it. Previously
    this function gated on ``len(loaded_file.content) > 0`` to filter out
    zero-byte files, but evaluating ``len(content)`` would force every lazy
    file to materialize and defeat the OOM fix. The guard is dropped; tools
    receive zero-byte content for empty files, which PythonTool handles fine
    (sha256 of empty bytes + upload of an empty body — the LLM will see the
    empty result and react).
    """
    chat_files: list[ChatFile] = []
    for loaded_file in loaded_files:
        filename = loaded_file.filename or f"file_{loaded_file.file_id}"
        # Pull content via a closure so the bytes only flow through one
        # materialization (the ChatLoadedFile's loader), then ride along.
        chat_files.append(
            ChatFile.lazy_from_filename(
                filename=filename,
                loader=lambda lf=loaded_file: lf.content,
            )
        )
    return chat_files


def _deduped_filename(filename: str, seen_filenames: set[str], file_id: str) -> str:
    if filename not in seen_filenames:
        seen_filenames.add(filename)
        return filename

    stem, suffix = os.path.splitext(filename)
    deduped_filename = f"{stem}_{file_id}{suffix}"
    seen_filenames.add(deduped_filename)
    return deduped_filename


def _load_context_user_files_for_tools(
    user_files: list[UserFile],
    existing_filenames: set[str],
) -> list[ChatFile]:
    """Stage tabular project/persona files for code-interpreter as lazy
    ChatFile instances.

    Raw bytes are not read here; each ChatFile carries a loader closure that
    pulls from the file store only when PythonTool actually accesses
    ``.content`` during staging. This avoids loading every project/persona
    file into RAM for chats that never invoke the Python tool.
    """
    if not user_files:
        return []

    chat_files: list[ChatFile] = []
    seen_file_ids: set[str] = set()

    for user_file in user_files:
        if user_file.file_id in seen_file_ids:
            continue
        seen_file_ids.add(user_file.file_id)

        if not mime_type_to_chat_file_type(user_file.file_type).use_metadata_only():
            continue

        filename = _deduped_filename(
            user_file.name or f"file_{user_file.id}",
            existing_filenames,
            str(user_file.id),
        )

        def _load(
            file_id: str = user_file.file_id, user_file_id: UUID = user_file.id
        ) -> bytes:
            # Preserve the pre-lazy degraded-but-functional behavior: if the
            # underlying file is gone or temporarily unreachable, log it and
            # hand PythonTool an empty payload instead of letting the
            # exception propagate out of ChatFile.__getattribute__.
            try:
                return get_default_file_store().read_file(file_id, mode="b").read()
            except Exception as e:
                logger.warning(
                    "Failed to load context file %s for Python execution: %s",
                    user_file_id,
                    e,
                )
                return b""

        chat_files.append(ChatFile.lazy_from_filename(filename=filename, loader=_load))

    return chat_files


def resolve_context_user_files(
    persona: Persona,
    project_id: int | None,
    user_id: UUID | None,
    db_session: Session,
) -> list[UserFile]:
    """Combine project files with a custom persona's files, without duplicates."""
    user_files: list[UserFile] = []
    if project_id:
        user_files.extend(
            get_user_files_from_project(
                project_id=project_id,
                user_id=user_id,
                db_session=db_session,
            )
        )
    if persona.id != DEFAULT_PERSONA_ID and persona.user_files:
        user_files.extend(persona.user_files)
    seen_ids: set[UUID] = set()
    selected_files: list[UserFile] = []
    for user_file in user_files:
        if user_file.id not in seen_ids:
            seen_ids.add(user_file.id)
            selected_files.append(user_file)
    return selected_files


def _empty_extracted_context_files() -> ExtractedContextFiles:
    return ExtractedContextFiles(
        file_texts=[],
        image_files=[],
        use_as_search_filter=False,
        total_token_count=0,
        file_metadata=[],
        uncapped_token_count=None,
    )


def _extract_text_from_in_memory_file(f: InMemoryChatFile) -> str | None:
    """Extract text content from an InMemoryChatFile.

    PLAIN_TEXT: the content is pre-extracted UTF-8 plaintext stored during
    ingestion — decode directly.
    DOC / CSV / other text types: the content is the original file bytes —
    use extract_file_text which handles encoding detection and format parsing.
    Embedded-image summaries are only generated at index time; chat-time
    extraction is text-only and any image context comes through search.
    """
    try:
        if f.file_type == ChatFileType.PLAIN_TEXT:
            return f.content.decode("utf-8", errors="ignore").replace("\x00", "")

        text_content = extract_file_text(
            file=io.BytesIO(f.content),
            file_name=f.filename or "",
            break_on_unprocessable=False,
        )
        return text_content or None
    except Exception:
        logger.warning("Failed to extract text from file %s", f.file_id, exc_info=True)
        return None


def extract_context_files(
    user_files: list[UserFileMetadata],
    llm_max_context_window: int,
    reserved_token_count: int,
    # Because the tokenizer is a generic tokenizer, the token count may be incorrect.
    # to account for this, the maximum context that is allowed for this function is
    # 60% of the LLM's max context window. The other benefit is that for projects with
    # more files, this makes it so that we don't throw away the history too quickly every time.
    max_llm_context_percentage: float = 0.6,
) -> ExtractedContextFiles:
    """Load user files into context if they fit; otherwise flag for search.

    The caller is responsible for deciding *which* user files to pass in
    (project files, persona files, etc.).  This function only cares about
    the all-or-nothing fit check and the actual content loading.

    Args:
        user_files: Captured metadata for authorized files
        llm_max_context_window: Maximum tokens allowed in the LLM context window
        reserved_token_count: Number of tokens to reserve for other content
        max_llm_context_percentage: Maximum percentage of the LLM context window to use.
    Returns:
        ExtractedContextFiles containing:
        - List of text content strings from context files (text files only)
        - List of image files from context (ChatLoadedFile objects)
        - Total token count of all extracted files
        - File metadata for context files
        - Uncapped token count of all extracted files
        - File metadata for files that don't fit in context and vector DB is disabled
    """
    # TODO(yuhong): I believe this is not handling all file types correctly.

    if not user_files:
        return _empty_extracted_context_files()

    # Aggregate tokens for the file content that will be added
    # Skip tokens for those with metadata only
    aggregate_tokens = sum(
        uf.token_count or 0
        for uf in user_files
        if not mime_type_to_chat_file_type(uf.file_type).use_metadata_only()
    )
    max_actual_tokens = (
        llm_max_context_window - reserved_token_count
    ) * max_llm_context_percentage

    if aggregate_tokens >= max_actual_tokens:
        use_as_search_filter = not DISABLE_VECTOR_DB
        if DISABLE_VECTOR_DB:
            overflow_tool_metadata = [_build_tool_metadata(uf) for uf in user_files]
        else:
            overflow_tool_metadata = [
                _build_tool_metadata(uf)
                for uf in user_files
                if mime_type_to_chat_file_type(uf.file_type).use_metadata_only()
            ]
        return ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=use_as_search_filter,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=aggregate_tokens,
            file_metadata_for_tool=overflow_tool_metadata,
        )

    # Files fit — load them into context
    user_file_map = {uf.file_id: uf for uf in user_files}
    in_memory_files = load_in_memory_chat_files(user_files)

    file_texts: list[str] = []
    image_files: list[ChatLoadedFile] = []
    file_metadata: list[ContextFileMetadata] = []
    tool_metadata: list[FileToolMetadata] = []
    total_token_count = 0

    for f in in_memory_files:
        uf = user_file_map.get(str(f.file_id))
        filename = f.filename or f"file_{f.file_id}"

        if f.file_type.use_metadata_only():
            # Metadata-only files are not injected as full text.
            # Only the metadata is provided, with LLM using tools
            if not uf:
                logger.error(
                    "File with id=%s in metadata-only path with no associated user file",
                    f.file_id,
                )
                continue
            tool_metadata.append(_build_tool_metadata(uf))
        elif f.file_type.is_text_file():
            text_content = _extract_text_from_in_memory_file(f)
            if not text_content:
                continue
            if not uf:
                logger.warning("No user file for file_id=%s", f.file_id)
                continue
            file_texts.append(text_content)
            file_metadata.append(
                ContextFileMetadata(
                    file_id=str(uf.id),
                    filename=filename,
                    file_content=text_content,
                )
            )
            if uf.token_count:
                total_token_count += uf.token_count
        elif f.file_type == ChatFileType.IMAGE:
            token_count = uf.token_count if uf and uf.token_count else 0
            total_token_count += token_count
            image_files.append(
                ChatLoadedFile(
                    file_id=f.file_id,
                    content=f.content,
                    file_type=f.file_type,
                    filename=f.filename,
                    content_text=None,
                    token_count=token_count,
                )
            )

    return ExtractedContextFiles(
        file_texts=file_texts,
        image_files=image_files,
        use_as_search_filter=False,
        total_token_count=total_token_count,
        file_metadata=file_metadata,
        uncapped_token_count=aggregate_tokens,
        file_metadata_for_tool=tool_metadata,
    )


def _build_tool_metadata(user_file: UserFileMetadata) -> FileToolMetadata:
    """Build lightweight FileToolMetadata from captured file fields.

    Delegates to ``build_file_context`` so that the file ID exposed to the
    LLM is always consistent with what FileReaderTool expects.
    """
    file_type = mime_type_to_chat_file_type(user_file.file_type)
    metadata = build_file_context(
        tool_file_id=str(user_file.id),
        filename=user_file.name,
        file_type=file_type,
        approx_char_count=(user_file.token_count or 0) * APPROX_CHARS_PER_TOKEN,
    ).tool_metadata
    # `_load_context_user_files_for_tools` only loads metadata-only files into
    # `chat_files_for_tools`, so those are the only context files PythonTool
    # ever receives. The rest are listed for the LLM but never staged — only
    # read_file can fetch them.
    return metadata.model_copy(
        update={"staged_for_tools": file_type.use_metadata_only()}
    )


def determine_search_params(
    persona_id: int,
    project_id: int | None,
    extracted_context_files: ExtractedContextFiles,
) -> SearchParams:
    """Search both file scopes when their combined contents exceed the prompt budget.

    Custom personas keep their search-tool policy. Default personas in projects
    enable search only when the project files need retrieval.
    """
    is_custom_persona = persona_id != DEFAULT_PERSONA_ID

    project_id_filter: int | None = None
    persona_id_filter: int | None = None
    if extracted_context_files.use_as_search_filter:
        project_id_filter = project_id
        if is_custom_persona:
            persona_id_filter = persona_id

    search_usage = SearchToolUsage.AUTO
    if not is_custom_persona and project_id:
        has_context_files = bool(extracted_context_files.uncapped_token_count)
        files_loaded_in_context = bool(extracted_context_files.file_texts)

        if extracted_context_files.use_as_search_filter:
            search_usage = SearchToolUsage.ENABLED
        elif files_loaded_in_context or not has_context_files:
            search_usage = SearchToolUsage.DISABLED

    return SearchParams(
        project_id_filter=project_id_filter,
        persona_id_filter=persona_id_filter,
        search_usage=search_usage,
    )


class FileContextResult(BaseModel):
    """Result of building a file's LLM context representation."""

    message: ChatMessageSimple
    tool_metadata: FileToolMetadata


CONTENT_PENDING_NOTICE = (
    "[This file is still being processed and its contents are not yet "
    "available. Do not guess what it contains — tell the user the file is "
    "still processing and to ask again in a moment.]"
)


CONTENT_UNAVAILABLE_NOTICE = (
    "[No machine-readable text could be extracted from this file. It is "
    "likely image-only (e.g. a scanned document) or in an unsupported "
    "format. Its contents are not available to you — do not guess them. If "
    "needed, ask the user for a text-based copy.]"
)


def build_file_context(
    tool_file_id: str,
    filename: str,
    file_type: ChatFileType,
    content_text: str | None = None,
    token_count: int = 0,
    approx_char_count: int | None = None,
    content_pending: bool = False,
) -> FileContextResult:
    """Build the LLM context representation for a single file.

    Centralises how files should appear in the LLM prompt
    — the ID that FileReaderTool accepts (``UserFile.id`` for user files).
    """
    if file_type.use_metadata_only():
        # Name read_file only where it is attached (FileReaderTool.is_available),
        # and drop the id with it: read_file is that UUID's only consumer, since
        # the python tool addresses files by filename. Tools are constructed
        # after this runs, so the other branch cannot know what is available and
        # names nothing rather than promising a tool the model may not have.
        message_text: str = (
            f"File: {filename} (id={tool_file_id})\n"
            "Use the read_file or python tools to access this file's contents."
            if DISABLE_VECTOR_DB
            else f"File: {filename}\n"
            "This file's contents are not included here. Use your available "
            "tools to read it. Do not guess the contents and do not search "
            "the web for this file."
        )
        message = ChatMessageSimple(
            message=message_text,
            token_count=max(1, len(message_text) // 4),
            message_type=MessageType.USER,
            file_id=tool_file_id,
        )
    elif not (content_text or "").strip():
        # An empty file block gives the model nothing to go on, and it tends
        # to invent workarounds (search the web for the document, guess its
        # contents). Say explicitly why there is no content.
        notice = (
            CONTENT_PENDING_NOTICE if content_pending else CONTENT_UNAVAILABLE_NOTICE
        )
        message_text = f"File: {filename}\n{notice}\nEnd of File"
        message = ChatMessageSimple(
            message=message_text,
            token_count=max(1, len(message_text) // 4),
            message_type=MessageType.USER,
            file_id=tool_file_id,
        )
    else:
        message_text = f"File: {filename}\n{content_text or ''}\nEnd of File"
        message = ChatMessageSimple(
            message=message_text,
            token_count=token_count,
            message_type=MessageType.USER,
            file_id=tool_file_id,
        )

    metadata = FileToolMetadata(
        file_id=tool_file_id,
        filename=filename,
        approx_char_count=(
            approx_char_count
            if approx_char_count is not None
            else len(content_text or "")
        ),
    )

    return FileContextResult(message=message, tool_metadata=metadata)


def _get_or_extract_plaintext(
    file_id: str,
    extract_fn: Callable[[], str],
    store_on_miss: bool = True,
) -> str:
    """Load cached plaintext for a file, or extract and store it.

    Tries to read pre-stored plaintext from the file store.  On a miss,
    calls extract_fn to produce the text, then stores the result so
    future calls skip the expensive extraction.
    """
    file_store = get_default_file_store()
    plaintext_key = plaintext_file_name_for_id(file_id)

    # Try cached plaintext first.
    try:
        plaintext_io = file_store.read_file(plaintext_key, mode="b")
        return plaintext_io.read().decode("utf-8")
    except Exception:
        logger.info("Cache miss for file with id=%s", file_id)

    # Cache miss — extract and store.  We cache the result unconditionally
    # (including the empty string) so that files we cannot extract text from
    # (e.g. .zip, or any extension without a handler in extract_file_text)
    # don't get re-fetched from object storage and re-attempted on every
    # subsequent chat turn.  Transient extraction errors surface as raised
    # exceptions, not empty returns, so they propagate without poisoning the
    # cache.  Callers pass store_on_miss=False when another writer owns the
    # canonical plaintext for this key (e.g. the user-file worker, whose
    # result may include image captions this inline extraction can't produce).
    content_text = extract_fn()
    if store_on_miss:
        store_plaintext(file_id, content_text)
    return content_text


def _get_chat_file_processing_info(
    file_descriptor: FileDescriptor, db_session: Session
) -> tuple[int, bool]:
    """Read session-bound fields before attachment content work starts."""
    user_file_id_str = file_descriptor.get("user_file_id", "")
    user_file: UserFile | None = None
    if user_file_id_str:
        try:
            user_file = get_user_file_by_id(UUID(user_file_id_str), db_session)
        except (ValueError, TypeError) as e:
            logger.warning(
                "Failed to look up user file for %s: %s", file_descriptor["id"], e
            )
    token_count = user_file.token_count if user_file and user_file.token_count else 0
    content_pending = user_file is not None and user_file.status in (
        UserFileStatus.PROCESSING,
        UserFileStatus.INDEXING,
    )

    return token_count, content_pending


@log_function_time()
def load_chat_file(
    file_descriptor: FileDescriptor, token_count: int, content_pending: bool
) -> ChatLoadedFile:
    """Build a ChatLoadedFile whose raw ``content`` bytes are loaded lazily.

    Chat sessions accumulate hundreds of files over time, and a new message
    sent in such a session previously triggered an unbounded parallel fan-out
    of full-bytes-into-memory reads, the vast majority of which were
    immediately discarded by chat-history truncation. We now defer the raw
    bytes read until something downstream actually accesses ``.content`` —
    typically only a handful of files survive truncation per turn.

    ``content_text`` (used for LLM context injection) and ``token_count``
    remain eager because they're cheap: the cached-plaintext store hit avoids
    reading the original bytes entirely on the common path, and token_count
    is captured before content loading.
    """
    file_id = file_descriptor["id"]
    # `FileDescriptor` is often JSON-roundtripped (e.g. JSONB / API), so `type`
    # may arrive as a raw string value instead of a `ChatFileType`.
    file_type = ChatFileType(file_descriptor["type"])
    filename = file_descriptor.get("name")
    user_file_id_str = file_descriptor.get("user_file_id", "")

    # Extract text content if it's a text file type (not an image). The
    # cached-plaintext path avoids reading the original bytes on the steady
    # state; only the cache miss branch opens the binary stream.
    content_text: str | None = None
    if file_type.is_text_file():

        def _extract() -> str:
            # Only invoked on cache miss; bytes-read happens here, not upfront.
            file_io = get_default_file_store().read_file(file_id, mode="b")
            return extract_file_text(
                file=file_io,
                file_name=filename or "",
                break_on_unprocessable=False,
            )

        # Use the user_file_id as cache key when available (matches what
        # the celery indexing worker stores), otherwise fall back to the
        # file store id (covers code-interpreter-generated files, etc.).
        cache_key = user_file_id_str or file_id

        try:
            # While the worker is still processing, don't store the inline
            # extraction under its key: the worker's canonical plaintext (which
            # may include image captions) should be what later turns read.
            content_text = _get_or_extract_plaintext(
                cache_key, _extract, store_on_miss=not content_pending
            )
        except Exception as e:
            logger.warning(
                "Failed to retrieve content for file %s: %s",
                file_id,
                str(e),
            )

    def _load_content() -> bytes:
        # Chat messages keep file references in their JSONB `files` column, but
        # user-file deletion does not scrub those references — a file in the
        # history may no longer exist in the file store. Since this loader runs
        # lazily (on first `.content` access, often mid-LLM-flow), a raised
        # exception here would kill the whole send-message request, so degrade
        # to empty content instead. Deletion is expected and logs at warning;
        # anything else (e.g. transient object-store failure) logs at error so
        # outages remain distinguishable in alerting.
        try:
            return get_default_file_store().read_file(file_id, mode="b").read()
        except FileRecordNotFoundError:
            logger.warning(
                "Chat file %s no longer exists (deleted after being referenced "
                "in chat history); substituting empty content",
                file_id,
            )
            return b""
        except Exception:
            logger.error(
                "Unexpected error loading content for chat file %s; "
                "substituting empty content",
                file_id,
                exc_info=True,
            )
            return b""

    return ChatLoadedFile.lazy_loaded(
        file_id=file_id,
        file_type=file_type,
        filename=filename,
        content_text=content_text,
        token_count=token_count,
        loader=_load_content,
        content_pending=content_pending,
    )


_MAX_PARALLEL_CHAT_FILE_LOADS = 16


def load_all_chat_files(
    chat_messages: list[ChatMessage],
    db_session: Session,
) -> list[ChatLoadedFile]:
    # Returns lazy ChatLoadedFile instances — raw bytes are not read here.
    # Defense-in-depth: even though per-file work is now cheap (an optional
    # cached-plaintext fetch), cap fan-out so no future regression
    # can re-introduce a 500-thread storm.
    file_descriptors_for_history: list[FileDescriptor] = []
    for chat_message in chat_messages:
        if chat_message.files:
            file_descriptors_for_history.extend(chat_message.files)

    # Build all arguments before starting workers. A Session cannot be shared
    # across threads, so workers receive only the descriptor and scalar metadata.
    files = cast(
        list[ChatLoadedFile],
        run_functions_tuples_in_parallel(
            [
                (
                    load_chat_file,
                    (file, *_get_chat_file_processing_info(file, db_session)),
                )
                for file in file_descriptors_for_history
            ],
            max_workers=_MAX_PARALLEL_CHAT_FILE_LOADS,
        ),
    )
    return files


def build_python_chat_files_from_search_docs(
    search_docs: list[SearchDoc],
) -> list[ChatFile]:
    """Turn each eligible search hit into a ready-to-upload `ChatFile`.
    The associated file needs to have been uploaded to the file store
    by a Connector.
    """
    if not search_docs:
        return []

    file_store = get_default_file_store()

    chat_files: list[ChatFile] = []
    seen_file_ids: set[str] = set()
    for doc in search_docs:
        if not doc.file_id or doc.file_id in seen_file_ids:
            continue
        seen_file_ids.add(doc.file_id)

        try:
            record = file_store.read_file_record(doc.file_id)
        except Exception as e:
            logger.warning(
                "file_id=%r not found in file store (%s); skipping.", doc.file_id, e
            )
            continue

        if record.file_origin not in (
            FileOrigin.CONNECTOR,
            FileOrigin.CONNECTOR_FILE_UPLOAD,
        ):
            logger.warning(
                "file_id=%r has origin=%r, not eligible for code-interpreter staging; skipping.",
                doc.file_id,
                record.file_origin,
            )
            continue

        try:
            content = file_store.read_file(doc.file_id, mode="b").read()
        except Exception as e:
            logger.warning(
                "Failed to read bytes for file_id=%r: %s; skipping.", doc.file_id, e
            )
            continue

        filename = sandbox_filename_for_document(doc.semantic_identifier, doc.file_id)
        chat_files.append(ChatFile(filename=filename, content=content))

    return chat_files
