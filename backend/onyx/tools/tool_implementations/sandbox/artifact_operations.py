"""The operations over the user's published files (artifacts) that both
tool families run: the library tools and the artifact tool
(sandbox_tools.py). Each takes the library tools' argument model, runs
one operation and returns its typed result; errors that the model can act
on are ToolCallExceptions (errors.py:artifact_errors)."""

import base64
import posixpath
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from datetime import datetime
from functools import partial
from io import BytesIO
from itertools import chain, count, zip_longest
from uuid import UUID

import regex
from pydantic import BaseModel, JsonValue, TypeAdapter
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import ChunkIndexRequest, IndexFilters, InferenceChunk
from onyx.context.search.retrieval.search_runner import search_chunks
from onyx.db.chat import (
    append_copied_artifact_version,
    delete_chat_artifact,
    delete_unpublished_chat_artifacts,
    get_user_artifact_search_candidates,
    get_user_published_file,
    get_user_published_files,
    get_user_published_files_by_id,
    rename_chat_artifact,
    save_chat_artifact,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import DocumentIndex
from onyx.file_store.constants import ARTIFACT_TEXT_MAX_FILE_BYTES
from onyx.file_store.models import ArtifactText
from onyx.file_store.utils import (
    chat_output_file_type,
    get_or_extract_artifact_text,
)
from onyx.indexing.chat_artifact_index import (
    delete_chat_artifacts_from_index,
    send_chat_artifact_index_tasks,
)
from onyx.llm.cancellation import CancellationSignal, wait_for_future
from onyx.llm.models import ToolResult
from onyx.microvm.models import FileType
from onyx.natural_language_processing.english_stopwords import strip_stopwords
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.server.features.build.sandbox.harness_base import (
    ARTIFACT_FILES_DIR,
    CHAT_FILES_DIR,
    RENDER_PREVIEW_BUDGET_SECONDS,
    RENDER_PREVIEW_MAX_INPUT_BYTES,
    RENDER_PREVIEW_SUFFIXES,
    SandboxPathError,
    chat_file_name,
    safe_file_name,
    session_relative_path,
)
from onyx.server.features.build.sandbox.models import (
    RenderedPreview,
    RenderSessionFile,
    session_workspace,
)
from onyx.tools.models import ToolApprovalDetails, ToolCallException
from onyx.tools.tool_implementations.sandbox import file_copies
from onyx.tools.tool_implementations.sandbox.artifact_text import (
    artifact_lines,
    find_lines,
    read_lines,
)
from onyx.tools.tool_implementations.sandbox.errors import artifact_errors, tool_error
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACT_CURSOR,
    ARTIFACT_RESULT_MAX_CHARS,
    ARTIFACTS_LIST_MAX_LIMIT,
    DELETE_OF_A_VERSION,
    FIND_TIMEOUT_SECONDS,
    LIBRARY_SEARCH_CHUNKS_PER_QUERY,
    LIBRARY_SEARCH_MAX_CANDIDATES,
    LIBRARY_SEARCH_MAX_SNIPPETS,
    LIBRARY_SEARCH_MAX_TOP_K,
    LIBRARY_SEARCH_RETRIEVALS_PER_QUERY,
    LIBRARY_SEARCH_SNIPPET_MAX_CHARS,
    LIBRARY_SEARCH_WINDOW,
    PUBLISH_FILES_MAX_BYTES,
    PUBLISH_FILES_MAX_TITLE_CHARS,
    VERSION_REASON_MAX_CHARS,
    ArtifactAtPath,
    ArtifactById,
    ArtifactCursor,
    ArtifactFileReference,
    ArtifactList,
    ArtifactPublished,
    ArtifactsFound,
    ArtifactsRead,
    ArtifactVersionConflict,
    DeleteOperation,
    FoundText,
    KeptTitle,
    LibraryCreateLibraryFileArguments,
    LibraryFileTarget,
    LibraryFindArguments,
    LibraryListArguments,
    LibraryListFilters,
    LibraryPrepareMaterializeArguments,
    LibraryReadArguments,
    LibraryReplaceLibraryFileArguments,
    LibraryRequest,
    LibrarySearchArguments,
    LibrarySearchCursor,
    LibrarySearchHit,
    LibrarySearchResult,
    ListedArtifact,
    ManageLibraryArguments,
    ManageResult,
    ManageResults,
    MaterializeDestination,
    MaterializedItem,
    MaterializedItems,
    PublishedFile,
    PublishedFiles,
    PublishFileArgument,
    ReadText,
    RenameOperation,
    RestoreVersionOperation,
    UpdateOperation,
    artifact_extension,
    artifact_url,
    parse_file_reference,
    shown_artifact,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.search.search_utils import (
    weighted_reciprocal_rank_fusion_with_scores,
)
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_string
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.configs import MODEL_SERVER_HOST, MODEL_SERVER_PORT

logger = setup_logger()

# How often a copy that waits for its write checks for pod shutdown.
_SLOT_CHECK_SECONDS = 1.0
# The most writes of one dedupe copy: other writers can take names after
# the listing.
_MATERIALIZE_NAME_TRIES = 5


def _copy_directory(session_id: UUID, directory: str) -> str:
    """`directory`, relative to the working directory or absolute in it, as
    a normalized path relative to it ("" is the working directory). A tool
    error unless it is in the working directory, outside CHAT_FILES_DIR or in
    ARTIFACT_FILES_DIR: the chat file copies own the rest of CHAT_FILES_DIR."""
    try:
        relative = session_relative_path(session_id, directory)
    except SandboxPathError as error:
        raise tool_error(str(error)) from error
    if f"{relative}/".startswith(
        f"{CHAT_FILES_DIR}/"
    ) and not f"{relative}/".startswith(f"{ARTIFACT_FILES_DIR}/"):
        raise tool_error(
            f"{directory!r} is not a destination: use a directory outside "
            f"{CHAT_FILES_DIR}/ or in {ARTIFACT_FILES_DIR}/"
        )
    return relative


def _published_file(
    db_session: Session, user_id: UUID, reference: ArtifactFileReference
) -> ListedArtifact:
    """The published file version that `reference` names, in a listable
    chat of the user (`get_user_published_file`). A tool error when there
    is none; it names the artifact's newest version when only the version
    is missing."""
    file = get_user_published_file(
        db_session,
        user_id,
        file_id=reference.file_id,
        artifact_id=reference.library_file_id,
        version=reference.version_number,
    )
    if file is not None:
        return file
    newest = (
        None
        if reference.version_number is None
        else get_user_published_file(
            db_session, user_id, artifact_id=reference.library_file_id
        )
    )
    if newest is not None:
        raise tool_error(
            f"No version {reference.version_number} of {reference.library_file_id}; "
            f"its newest is {newest.version_number}"
        )
    raise tool_error(
        f"No published file {reference.file_id or reference.library_file_id} "
        "in your chats"
    )


def _deleted_file(
    db_session: Session, user_id: UUID, target: LibraryFileTarget
) -> ListedArtifact:
    """The file that a delete of `target` removes (`_published_file`). A
    tool error when the target's version_number names a version older than
    the newest: a delete removes every version."""
    file = _published_file(db_session, user_id, target)
    if (
        target.version_number is not None
        and file.version_number != file.latest_version_number
    ):
        raise tool_error(
            f"Version {file.version_number} of {file.file_name} is not its "
            f"newest, {file.latest_version_number}; {DELETE_OF_A_VERSION}"
        )
    return file


def _short_text(text: str | None, max_chars: int) -> str | None:
    """A title or version reason as a save keeps it: without NUL, which
    Postgres text cannot hold, trimmed and cut to `max_chars`; None when
    blank."""
    return sanitize_string(text or "").strip()[:max_chars].rstrip() or None


def _checked_name(new_name: str, current: str) -> str:
    """`new_name` as the new name of the artifact named `current`: a name
    that safe_file_name keeps, so the file keeps it in the VM, with the
    extension of `current` by the list's last-dot rule
    (`artifact_extension`), in any case, after a non-empty name, which gives
    the file's type."""
    if safe_file_name([new_name]) != new_name:
        raise tool_error(
            f"{new_name!r} is not a file name that the VM keeps; "
            f"try {safe_file_name([new_name])!r}"
        )
    extension = artifact_extension(current)
    if artifact_extension(new_name) != extension:
        raise tool_error(
            f"The file's content is {current}, so its name "
            + (
                "must have no extension"
                if extension is None
                else f"must end in {'.' + extension!r}"
            )
        )
    if new_name.rpartition(".")[:2] == ("", "."):
        raise tool_error(f"{new_name!r} has no name before its extension")
    return new_name


def publish(
    turn: SandboxTurn,
    cancellation: CancellationSignal,
    files: Sequence[PublishFileArgument],
    *,
    artifact: ListedArtifact | None = None,
    expected_version: int | None = None,
    version_reason: str | None = None,
) -> list[PublishedFile]:
    """Copy files from the VM to the file store, each as the next version of
    an artifact (`db/chat.py:save_chat_artifact`): the root chat's artifact
    at the file's path, or `artifact`, whose name stays, and whose newest
    version's title stays unless the file gives one, with the
    `expected_version` check. Everyone who can read the artifact's chat can
    download them (`access/access.py:user_can_access_chat_file`). The
    response's save attaches them to its message
    (`db/chat_response.py:save_chat_turn`), and a hard chat delete of the
    artifact's chat deletes them, saved or not
    (`db/chat.py:delete_messages_and_files_from_chat_session`). A PDF,
    PowerPoint or Word file also gets a thumbnail of its first page, drawn
    in the VM, and a PowerPoint or Word file the PDF of the same render,
    which the preview shows. The renders of a call share one budget
    (RENDER_PREVIEW_BUDGET_SECONDS); a file whose render fails or comes
    after the budget publishes without them. A call publishes all of its
    files or none."""
    sandbox = turn.sandbox
    published: list[PublishedFile] = []
    try:
        with artifact_errors("The publish"):
            # The turn's chat session is the root chat's, whose readers
            # may download the files; subagent runs share it.
            ref = turn.start_call()
            # The budget starts once the first read has woken the VM.
            render_until: float | None = None
            for requested in files:
                cancellation.check()
                data = sandbox.read_file(
                    ref, requested.path, max_bytes=PUBLISH_FILES_MAX_BYTES
                )
                if render_until is None:
                    render_until = time.monotonic() + RENDER_PREVIEW_BUDGET_SECONDS
                path = posixpath.normpath(
                    posixpath.join(session_workspace(ref.session_id), requested.path)
                )
                name = (
                    posixpath.basename(path) if artifact is None else artifact.file_name
                )
                title = (
                    KeptTitle.NEWEST
                    if artifact is not None and requested.title is None
                    else _short_text(requested.title, PUBLISH_FILES_MAX_TITLE_CHARS)
                )
                # A file with no render still publishes. Once the budget is
                # spent, no render looks up its file or logs.
                rendered: RenderedPreview | None = None
                if (
                    posixpath.splitext(path)[1].lower() in RENDER_PREVIEW_SUFFIXES
                    and len(data) <= RENDER_PREVIEW_MAX_INPUT_BYTES
                    and time.monotonic() < render_until
                ):
                    try:
                        rendered = sandbox.render_preview(
                            RenderSessionFile(ref=ref, path=path),
                            first_page=True,
                            budget_seconds=render_until - time.monotonic(),
                        )
                    except Exception:
                        logger.warning(
                            "artifact_publish_render_failed path=%r",
                            path,
                            exc_info=True,
                        )
                published.append(
                    save_chat_artifact(
                        data,
                        name=name,
                        mime_type=chat_output_file_type(name),
                        title=title,
                        thumbnail=None if rendered is None else rendered.first_page,
                        preview_pdf=None
                        if rendered is None or rendered.pdf is None
                        else BytesIO(rendered.pdf),
                        target=ArtifactAtPath(chat_session_id=ref.session_id, path=path)
                        if artifact is None
                        else ArtifactById(artifact_id=artifact.library_file_id),
                        expected_version=expected_version,
                        version_reason=_short_text(
                            version_reason, VERSION_REASON_MAX_CHARS
                        ),
                    )
                )
            # A Stop during the last copy publishes nothing.
            cancellation.check()
    except BaseException:
        # A failed clean-up must not replace the call's own error or Stop.
        try:
            # An indexing beat may have indexed an artifact that the
            # clean-up deletes.
            delete_chat_artifacts_from_index(
                delete_unpublished_chat_artifacts(published)
            )
        except Exception:
            logger.warning(
                "artifact_publish_cleanup_failed files=%s",
                [file.file_id for file in published],
                exc_info=True,
            )
        raise
    send_chat_artifact_index_tasks(
        [file.artifact_id for file in published if file.artifact_id is not None]
    )
    return published


def check_same_type(artifact: ListedArtifact, file: str) -> None:
    """A tool error unless `file`, a new version's content, has the
    extension of the artifact's name by the list's last-dot rule
    (`artifact_extension`), in any case: a new version keeps the name, and
    so the type. `file` is normalized as publish does, so a trailing slash
    or dot names the same file."""
    name = posixpath.basename(posixpath.normpath(file))
    if artifact_extension(name) != artifact_extension(artifact.file_name):
        raise tool_error(
            f"{name} is not a file of the type of "
            f"{artifact.file_name}; a new version keeps the file's name and "
            "type, so publish it as a new file instead"
        )


def replace_file(
    turn: SandboxTurn,
    cancellation: CancellationSignal,
    arguments: LibraryReplaceLibraryFileArguments,
) -> PublishedFile:
    """Publish a file from the VM as the next version of an artifact in any
    listable chat of the user (`publish`), with its name, and its newest
    version's title unless the arguments give one. The lookup and the type
    check come first, so a refused replace never starts the VM. Raises
    ArtifactVersionConflict when `expected_current_version` is not the
    newest available version; each tool words it."""
    with artifact_errors("The replace"):
        with get_session_with_current_tenant() as db_session:
            artifact = _published_file(
                db_session,
                turn.user_id,
                ArtifactFileReference(library_file_id=arguments.library_file_id),
            )
    check_same_type(artifact, arguments.file)
    [published] = publish(
        turn,
        cancellation,
        [PublishFileArgument(path=arguments.file, title=arguments.title)],
        artifact=artifact,
        expected_version=arguments.expected_current_version,
        version_reason=arguments.version_reason,
    )
    return published


_SEARCH_CURSOR = TypeAdapter(LibrarySearchCursor)


def _encode_cursor[T](adapter: TypeAdapter[T], cursor: T) -> str:
    return base64.urlsafe_b64encode(adapter.dump_json(cursor)).decode()


def _decode_cursor[T](adapter: TypeAdapter[T], cursor: str, again: str) -> T:
    """The cursor that _encode_cursor made; a tool error that asks the model
    to `again` ("list", "search") without it for any other text."""
    try:
        return adapter.validate_json(base64.urlsafe_b64decode(cursor))
    except ValueError as error:
        raise tool_error(
            f"The cursor is not a next_cursor of this tool; {again} again without it"
        ) from error


def _fit_page[T, P: BaseModel](shown: list[T], page: Callable[[list[T]], P]) -> P:
    """The page of the most leading entries of `shown` whose JSON keeps to
    ARTIFACT_RESULT_MAX_CHARS, with at least one entry."""
    while True:
        result = page(shown)
        if (
            len(result.model_dump_json()) <= ARTIFACT_RESULT_MAX_CHARS
            or len(shown) <= 1
        ):
            return result
        shown = shown[:-1]


def list_artifacts(user_id: UUID, arguments: LibraryListArguments) -> ArtifactList:
    """A page of the published files in the user's listable chats, from the
    database only; it never starts the VM. A page keeps to
    ARTIFACT_RESULT_MAX_CHARS, under the spill limit of one result, and the
    step's budget does not spill it."""
    cursor: ArtifactCursor | None = None
    if arguments.cursor is not None:
        cursor = _decode_cursor(ARTIFACT_CURSOR, arguments.cursor, "list")
        if (cursor.sort, cursor.sort_order) != (
            arguments.sort,
            arguments.sort_order,
        ):
            raise tool_error(
                f"The cursor is from a list with sort {cursor.sort} and "
                f"sort_order {cursor.sort_order}; send those, or list again "
                "without the cursor"
            )
    limit = min(max(arguments.limit, 1), ARTIFACTS_LIST_MAX_LIMIT)
    with artifact_errors("The listing"):
        with get_session_with_current_tenant() as db_session:
            rows = get_user_published_files(
                db_session,
                user_id,
                chat_session_id=arguments.chat_id,
                filters=arguments.filters or LibraryListFilters(),
                sort=arguments.sort,
                sort_order=arguments.sort_order,
                limit=limit,
                cursor=cursor,
            )
    if rows is None:
        raise tool_error(f"No chat {arguments.chat_id} of yours")
    shown = rows[:limit]
    return _fit_page(
        shown,
        lambda page: ArtifactList(
            files=[artifact for artifact, _ in page],
            next_cursor=_encode_cursor(ARTIFACT_CURSOR, page[-1][1])
            if page and len(page) < len(rows)
            else None,
        ),
    )


def materialize(
    turn: SandboxTurn,
    cancellation: CancellationSignal,
    arguments: LibraryPrepareMaterializeArguments,
) -> MaterializedItems:
    """Copy published files into the chat's working directory, one item at
    a time in order, with one result for each item. The lookups and the
    destination checks of every item come first, so a call whose items are
    all refused never starts the VM; it fails only when no item succeeds. In
    ARTIFACT_FILES_DIR without a file_name, a copy has its chat file name
    (`chat_file_name`), which only that file has: a file there that is in
    place (`file_copies.in_place`) is cached, and any other is written over.
    Any other copy has the safe form of its name (`safe_file_name`), and the
    conflict policy decides when the directory's listing shows that name, or
    is cut at file_copies.MAX_LISTED entries. Under `error` and `dedupe` the
    write never replaces a file: a name taken after the listing fails an
    `error` copy and moves a `dedupe` copy to the next free name, up to
    _MATERIALIZE_NAME_TRIES writes. Each write is a FileWrites of the chat
    file copies, with their tries, write slots and timeouts; an item waits
    for it until a Stop or pod shutdown. A Stop ends the call: a started
    write lands on its own, and the next one does not start. A sandbox that
    stops responding to a listing or a write fails the remaining items."""
    session_id = turn.chat_session_id
    destination = arguments.destination or MaterializeDestination()
    directory = _copy_directory(
        session_id,
        ARTIFACT_FILES_DIR if destination.directory is None else destination.directory,
    )
    results: list[MaterializedItem] = [
        MaterializedItem(
            library_file_id=item.library_file_id,
            file_id=item.file_id,
            version_number=item.version_number,
            status="error",
        )
        for item in arguments.items
    ]
    # Each copy to make: its index, file, directory, name, and whether
    # the name is the file's chat file name.
    copies: list[tuple[int, ListedArtifact, str, str, bool]] = []
    with artifact_errors("The copy"):
        with get_session_with_current_tenant() as db_session:
            for index, item in enumerate(arguments.items):
                try:
                    file = _published_file(db_session, turn.user_id, item)
                    item_directory = (
                        directory
                        if item.relative_directory is None
                        else _copy_directory(
                            session_id,
                            posixpath.join(directory, item.relative_directory),
                        )
                    )
                    prefixed = (
                        item_directory == ARTIFACT_FILES_DIR and not item.file_name
                    )
                    copies.append(
                        (
                            index,
                            file,
                            item_directory,
                            chat_file_name(file.file_id, file.file_name)
                            if prefixed
                            else safe_file_name(
                                (item.file_name or file.file_name, file.file_id)
                            ),
                            prefixed,
                        )
                    )
                except ToolCallException as error:
                    results[index].error = error.llm_facing_message
    if copies:
        with artifact_errors("The copy"):
            ref = turn.start_call()
            files = turn.sandbox.session_files(ref)
        pool = file_copies.file_copy_pool()
        # Each listed directory: the size of each regular file by name, None
        # for any other entry, and whether the listing is cut. The names that
        # this call wrote or found taken join it.
        listings: dict[str, tuple[dict[str, int | None], bool]] = {}
        # Why the sandbox stopped responding, once it did.
        stopped: str | None = None
        for index, file, item_directory, name, prefixed in copies:
            # Before each item, as a cached or refused item writes nothing.
            cancellation.check()
            try:
                if stopped is not None:
                    raise tool_error(f"The copy failed: {stopped}; try again")
                # The listing is a snapshot, and a cut one can miss a file at
                # the name, so these writes never replace a file.
                no_replace = not prefixed and destination.conflict_policy != "overwrite"
                with artifact_errors("The copy"):
                    if (prefixed or no_replace) and item_directory not in listings:
                        try:
                            listing = files.list_files(
                                item_directory,
                                max_entries=file_copies.MAX_LISTED,
                                include_hidden=True,
                            )
                        except Exception as error:
                            stopped = (
                                file_copies.NO_RESPONSE.reason
                                if file_copies.no_response(error)
                                else None
                            )
                            raise
                        listings[item_directory] = (
                            {
                                entry.name: entry.size
                                if entry.type is FileType.REGULAR
                                else None
                                for entry in listing.entries
                            },
                            listing.truncated,
                        )
                # An overwrite outside the chat file names needs no listing.
                names, truncated = listings.get(item_directory, ({}, False))
                # In place, as file_copies.in_place: a regular file of the
                # file's size.
                cached = prefixed and names.get(name) == file.file_size_bytes
                # Each candidate is cut to fit the name limits; partial binds
                # the requested name, which the loop below rebinds.
                numbered = partial(safe_file_name, (name,))
                free_names = (
                    candidate
                    for number in count(1)
                    if (candidate := numbered(suffix=f" ({number})")) not in names
                )
                if no_replace and (name in names or truncated):
                    if destination.conflict_policy == "error":
                        raise tool_error(
                            f"{posixpath.join(item_directory, name)} may already exist"
                            if truncated and name not in names
                            else f"{posixpath.join(item_directory, name)} "
                            "already exists"
                        )
                    name = next(free_names)
                path = posixpath.join(item_directory, name)
                tries = 0
                while not cached:
                    tries += 1
                    cancellation.check()
                    written: Future[file_copies.CopyFailure | None] = Future()
                    file_copies.FileWrites(
                        ref,
                        pool,
                        files,
                        [
                            file_copies.FileWrite(
                                path,
                                file.file_id,
                                file.file_size_bytes,
                                overwrite=not no_replace,
                            )
                        ],
                        lambda: cancellation.cancelled,
                        lambda _files, failure, done=written: done.set_result(failure),
                    )
                    # The wait has no timeout: the write's tries have theirs,
                    # and pod shutdown drops a queued write.
                    while True:
                        try:
                            failure = wait_for_future(
                                written, _SLOT_CHECK_SECONDS, cancellation
                            )
                            break
                        except TimeoutError:
                            if pool.stopped.is_set():
                                stopped = "the server is shutting down"
                                raise tool_error(
                                    f"The copy stopped: {stopped}; try again"
                                ) from None
                    if failure is not None and failure != file_copies.EXISTS:
                        stopped = failure.reason if failure.ends_copy else None
                        raise tool_error(
                            f"The copy failed: {failure.reason}; try again"
                        )
                    # A written name holds the file's size, so the same file
                    # again is cached.
                    names[name] = file.file_size_bytes if failure is None else None
                    if failure is None:
                        break
                    if (
                        destination.conflict_policy == "error"
                        or tries == _MATERIALIZE_NAME_TRIES
                    ):
                        raise tool_error(
                            f"{path} already exists"
                            if destination.conflict_policy == "error"
                            else f"{path} and the names before it are taken; try again"
                        )
                    name = next(free_names)
                    path = posixpath.join(item_directory, name)
            except ToolCallException as error:
                results[index].error = error.llm_facing_message
                continue
            results[index] = MaterializedItem(
                library_file_id=file.library_file_id,
                file_id=file.file_id,
                version_number=file.version_number,
                file_name=name,
                path=path,
                file_size_bytes=file.file_size_bytes,
                mime_type=file.mime_type,
                url=artifact_url(file.library_file_id, file.version_number),
                status="cached" if cached else "written",
            )
    logger.info(
        "library_prepare_materialize statuses=%s",
        [result.status for result in results],
    )
    if all(result.status == "error" for result in results):
        raise tool_error(
            "No file was copied:\n"
            + "\n".join(f"- {result.error}" for result in results)
        )
    return MaterializedItems(items=results)


def _card_path(file: ListedArtifact) -> str:
    """How an approval card names `file`, as shown_artifact cut it: its
    display path's folder, which tells apart files of one name, with the
    name that the artifact has now."""
    return posixpath.join(posixpath.dirname(file.path), file.file_name)


_OtherOperation = RenameOperation | RestoreVersionOperation | UpdateOperation


def _changed_file(operation: _OtherOperation) -> ArtifactFileReference:
    """The file that an operation other than a delete changes."""
    return (
        operation.target
        if isinstance(operation, RenameOperation)
        else ArtifactFileReference(library_file_id=operation.library_file_id)
    )


def _other_operation_line(operation: _OtherOperation, name: str) -> str:
    """The card line of an operation that a delete's approval covers too,
    for the file named `name`."""
    if isinstance(operation, RenameOperation):
        return f"rename {name} to {operation.new_name}"
    line = (
        f"restore version {operation.version_number} of {name}"
        if isinstance(operation, RestoreVersionOperation)
        else f"add {operation.file_uri.file_id} as a new version of {name}"
    )
    return (
        line
        if operation.file_name is None
        else f"{line} and rename it to {operation.file_name}"
    )


def _reference_text(reference: ArtifactFileReference) -> str:
    """A file reference as the call gives it, for a card line."""
    if reference.file_id is not None:
        return reference.file_id
    return f"{reference.library_file_id}" + (
        ""
        if reference.version_number is None
        else f" version {reference.version_number}"
    )


def _card_chat(file: ListedArtifact) -> str:
    """How an approval card names the chat of `file`."""
    return (
        f"chat \u201c{file.chat_title}\u201d" if file.chat_title else "an untitled chat"
    )


def delete_approval_details(
    user_id: UUID, request: LibraryRequest
) -> ToolApprovalDetails | None:
    """The approval card of a call that runs `request`, which both tool
    families show; None for a call without a delete. A line for each of
    the user's artifacts that the deletes name, as the delete finds it
    (`_deleted_file`), with its display path, its newest version number
    and its chat. A delete target that the delete refuses or finds nothing
    for yet still gets a line: a version older than the newest, which the
    delete refuses, and a version newer than the newest, which another chat
    can still publish, by the artifact's display path; any other target as
    given, as another chat can still publish it. An earlier restore or
    update of the call can also make the newer version. Each other
    operation gets a line, which the approval covers too, with the display
    path and the chat of the file that it changes. It never raises: a failed
    lookup asks with the targets as given."""
    if not isinstance(request, ManageLibraryArguments):
        return None
    deletes = [
        operation.target
        for operation in request.operations
        if isinstance(operation, DeleteOperation)
    ]
    others = [
        operation
        for operation in request.operations
        if not isinstance(operation, DeleteOperation)
    ]
    if not deletes:
        return None
    # Each artifact's or unresolved target's card name and line
    entries: dict[UUID | str, tuple[str, str]] = {}
    also: list[JsonValue] = []
    try:
        with get_session_with_current_tenant() as db_session:
            for target in deletes:
                try:
                    file = shown_artifact(_deleted_file(db_session, user_id, target))
                except ToolCallException:
                    given = _reference_text(target)
                    newest = (
                        None
                        if target.library_file_id is None
                        else get_user_published_file(
                            db_session, user_id, artifact_id=target.library_file_id
                        )
                    )
                    if newest is None or target.version_number is None:
                        entries[given] = (given, f"{given} (not found yet)")
                        continue
                    name = _card_path(shown_artifact(newest))
                    # The delete of a newer version removes the whole file.
                    entries[given] = (
                        name,
                        f"{name} (version {target.version_number} not published "
                        "yet; the delete removes the file and every version)"
                        if target.version_number > newest.version_number
                        else f"{name} version {target.version_number} (not its "
                        f"newest version, {newest.version_number}; the delete "
                        "refuses it while it is not the newest)",
                    )
                    continue
                name = _card_path(file)
                # A lookup always sets the newest version.
                versions = file.latest_version_number
                entries[file.library_file_id] = (
                    name,
                    f"{name} ({versions} version{'' if versions == 1 else 's'}) "
                    f"from {_card_chat(file)}",
                )
            for operation in others:
                changed = _changed_file(operation)
                try:
                    shown = shown_artifact(
                        _published_file(db_session, user_id, changed)
                    )
                    name = f"{_card_path(shown)} from {_card_chat(shown)}"
                except ToolCallException:
                    name = _reference_text(changed)
                also.append(_other_operation_line(operation, name))
    except Exception:
        logger.exception("artifacts_delete_approval_lookup_failed")
        also = [
            _other_operation_line(operation, _reference_text(_changed_file(operation)))
            for operation in others
        ]
        return ToolApprovalDetails(
            display_name="Delete published files",
            payload={
                "Delete": [_reference_text(target) for target in deletes],
                **({"Also in this call": also} if also else {}),
            },
        )
    names = [name for name, _line in entries.values()]
    lines: list[JsonValue] = [line for _name, line in entries.values()]
    return ToolApprovalDetails(
        display_name=f"Delete {names[0]}"
        if len(names) == 1
        else f"Delete {len(names)} published files",
        payload={
            "Delete": lines,
            **({"Also in this call": also} if also else {}),
        },
    )


def manage(
    user_id: UUID,
    cancellation: CancellationSignal,
    arguments: ManageLibraryArguments,
    *,
    conflict_message: Callable[[ArtifactVersionConflict], str],
) -> ManageResults:
    """Run the operations on the artifacts of the user's listable chats in
    order, each in its own transaction, with one result for each; from the
    database and the file store only, so it never starts the VM. It fails
    only when no operation succeeds. A Stop ends the call, as in
    materialize: a started operation ends, and the next one does not
    start. A delete removes the artifact with every version
    (delete_chat_artifact), also the versions published since the user
    approved it; the tools ask first (delete_approval_details). A rename
    sets the artifact's name (_checked_name). A restore_version or an
    update copies a published file, a version of this artifact or of
    another one of the user's, of the artifact's type (check_same_type), as
    the artifact's next version (append_copied_artifact_version), with the
    expected_current_version check, whose error `conflict_message` words for
    the calling tool. The name stays unless file_name renames it within its
    type; the title is the restored version's, or for an update the newest
    version's. After its commit, each operation sends the artifact's
    indexing task, or deletes the removed artifact from the search index."""
    results: list[ManageResult] = []
    for operation in arguments.operations:
        cancellation.check()
        try:
            with artifact_errors(f"The {operation.operation}"):
                if isinstance(operation, RestoreVersionOperation | UpdateOperation):
                    with get_session_with_current_tenant() as db_session:
                        artifact = _published_file(
                            db_session,
                            user_id,
                            ArtifactFileReference(
                                library_file_id=operation.library_file_id
                            ),
                        )
                        source = _published_file(
                            db_session,
                            user_id,
                            ArtifactFileReference(
                                library_file_id=operation.library_file_id,
                                version_number=operation.version_number,
                            )
                            if isinstance(operation, RestoreVersionOperation)
                            else parse_file_reference(operation.file_uri.file_id),
                        )
                    check_same_type(artifact, source.file_name)
                    version_reason = _short_text(
                        operation.version_reason, VERSION_REASON_MAX_CHARS
                    )
                    try:
                        [added] = ArtifactPublished.of(
                            [
                                append_copied_artifact_version(
                                    source,
                                    artifact_id=artifact.library_file_id,
                                    name=artifact.file_name
                                    if operation.file_name is None
                                    else _checked_name(
                                        operation.file_name, artifact.file_name
                                    ),
                                    rename=operation.file_name is not None,
                                    title=source.title
                                    if isinstance(operation, RestoreVersionOperation)
                                    else KeptTitle.NEWEST,
                                    expected_version=operation.expected_current_version,
                                    version_reason=version_reason,
                                )
                            ]
                        ).files
                    except ArtifactVersionConflict as error:
                        raise tool_error(conflict_message(error)) from error
                    send_chat_artifact_index_tasks([added.library_file_id])
                    result = ManageResult(
                        operation=operation.operation,
                        ok=True,
                        library_file_id=added.library_file_id,
                        file_id=added.file_id,
                        version_number=added.version_number,
                        file_name=added.file_name,
                        url=added.url,
                        version_reason=version_reason,
                    )
                else:
                    with get_session_with_current_tenant() as db_session:
                        file = (
                            _published_file(db_session, user_id, operation.target)
                            if isinstance(operation, RenameOperation)
                            else _deleted_file(db_session, user_id, operation.target)
                        )
                    if isinstance(operation, RenameOperation):
                        name = _checked_name(operation.new_name, file.file_name)
                        with get_session_with_current_tenant() as db_session:
                            rename_chat_artifact(db_session, file.library_file_id, name)
                            db_session.commit()
                            # The target can name an older version.
                            newest = _published_file(
                                db_session,
                                user_id,
                                ArtifactFileReference(
                                    library_file_id=file.library_file_id
                                ),
                            )
                        send_chat_artifact_index_tasks([file.library_file_id])
                        result = ManageResult(
                            operation=operation.operation,
                            ok=True,
                            library_file_id=newest.library_file_id,
                            file_id=newest.file_id,
                            version_number=newest.version_number,
                            file_name=newest.file_name,
                            url=newest.url,
                        )
                    else:
                        deleted_versions = delete_chat_artifact(file.library_file_id)
                        delete_chat_artifacts_from_index([file.library_file_id])
                        result = ManageResult(
                            operation=operation.operation,
                            ok=True,
                            library_file_id=file.library_file_id,
                            file_name=file.file_name,
                            deleted_versions=deleted_versions,
                        )
        except ToolCallException as error:
            result = ManageResult(
                operation=operation.operation,
                ok=False,
                error=error.llm_facing_message,
            )
        results.append(result)
    logger.info(
        "library_manage_library operations=%s ok=%s",
        [result.operation for result in results],
        [result.ok for result in results],
    )
    if not any(result.ok for result in results):
        raise tool_error(
            "No operation succeeded:\n"
            + "\n".join(f"- {result.error}" for result in results)
        )
    return ManageResults(results=results)


# Room in a read or find item's JSON for the numbers that its lines,
# text or matches set (total_lines, total_pages, start_line, end_line,
# next_start_line, total_matches_seen, next_match_offset, reached_line); the
# empty item shows them as 0, null or not at all.
_ITEM_NUMBERS_CHARS = 64


def _published_texts(
    user_id: UUID, references: Sequence[ArtifactFileReference], action: str
) -> list[tuple[ListedArtifact, ArtifactText]]:
    """Each reference's published file and its text, from the database and
    the file store only; later calls reuse a version's cached text
    (artifact_text.py). A call reads all of its files or none: a refused
    reference, a file larger than ARTIFACT_TEXT_MAX_FILE_BYTES or a file
    without text fails the call with every such error. Every lookup comes
    before any text, so no database session waits on an extraction."""
    errors: list[str] = []
    files: list[ListedArtifact] = []
    with artifact_errors(action):
        with get_session_with_current_tenant() as db_session:
            for reference in references:
                try:
                    files.append(_published_file(db_session, user_id, reference))
                except ToolCallException as error:
                    errors.append(error.llm_facing_message)
    texts: list[tuple[ListedArtifact, ArtifactText]] = []
    for file in files:
        with artifact_errors(action):
            text = get_or_extract_artifact_text(
                file.file_id, file.file_name, file.file_size_bytes
            )
        if text is None:
            errors.append(
                f"{file.file_name} is larger than "
                f"{ARTIFACT_TEXT_MAX_FILE_BYTES >> 20} MiB; copy it into the "
                "sandbox to work with it"
            )
        elif not any(page.strip() for page in text.pages):
            errors.append(
                f"{file.file_name} has no text; copy it into the sandbox to "
                "work with it"
            )
        else:
            texts.append((file, text))
    if errors:
        raise tool_error("\n".join(errors))
    return texts


def _page_lines(
    file: ListedArtifact,
    page_starts: Sequence[int],
    total_lines: int,
    start_page: int,
    end_page: int,
) -> tuple[int, int]:
    """The first and last line of pages `start_page` to `end_page` of
    `file`; the last page stops at the file's last."""
    if not page_starts:
        raise tool_error(
            f"{file.file_name} has no pages; read or search it by line instead"
        )
    if start_page > len(page_starts):
        raise tool_error(f"{file.file_name} has {len(page_starts)} pages")
    end_page = min(end_page, len(page_starts))
    return page_starts[start_page - 1], (
        page_starts[end_page] - 1 if end_page < len(page_starts) else total_lines
    )


def read(user_id: UUID, arguments: LibraryReadArguments) -> ArtifactsRead:
    """The numbered lines of published files at any version, from the
    database and the file store only; it never starts the VM. Every item
    has its file (shown_artifact), and their text shares
    ARTIFACT_RESULT_MAX_CHARS in order: an item that the limit cuts gives
    the line where its text continues. One item's lines are in memory at a
    time."""
    texts = _published_texts(user_id, arguments.read, "The read")
    result = ArtifactsRead(
        items=[
            ReadText(
                file=shown_artifact(file),
                total_lines=0,
                total_pages=None,
                start_line=0,
                end_line=0,
                text="",
                next_start_line=None,
                truncated=text.truncated,
            )
            for file, text in texts
        ]
    )
    for index, (item, (file, text), shown) in enumerate(
        zip(arguments.read, texts, result.items, strict=True)
    ):
        lines, page_starts = artifact_lines(text)
        if item.mode == "pages":
            end_page = item.end_page or item.start_page
            first, last = _page_lines(
                file, page_starts, len(lines), item.start_page, end_page
            )
            # A start_line resumes a read of the same pages that the limit cut.
            if "start_line" in item.model_fields_set:
                if not first <= item.start_line <= last:
                    raise tool_error(
                        f"start_line {item.start_line} is outside pages "
                        f"{item.start_page} to {end_page} of {file.file_name}, "
                        f"lines {first} to {last}"
                    )
                first = item.start_line
        else:
            first, last = item.start_line, item.start_line + item.max_lines - 1
        shown.total_lines = len(lines)
        shown.total_pages = len(page_starts) or None
        shown.start_line = first
        shown.text, shown.end_line = read_lines(
            lines,
            page_starts,
            first,
            last,
            ARTIFACT_RESULT_MAX_CHARS
            - len(result.model_dump_json())
            - (len(texts) - index) * _ITEM_NUMBERS_CHARS,
        )
        # Pages mode continues only inside its pages; lines mode to the file's end.
        shown.next_start_line = (
            shown.end_line + 1
            if shown.end_line < (last if item.mode == "pages" else len(lines))
            else None
        )
    return result


def find(user_id: UUID, arguments: LibraryFindArguments) -> ArtifactsFound:
    """The lines of published files at any version in which a pattern
    matches, as grep finds them, from the database and the file store
    only; it never starts the VM. A literal pattern cannot backtrack; a
    regular expression runs in `regex` under the item's time limit. Every
    item has its file (shown_artifact), and their matches share
    ARTIFACT_RESULT_MAX_CHARS in order. One item's lines are in memory at a
    time."""
    patterns: list[regex.Pattern[str]] = []
    for item in arguments.find:
        try:
            patterns.append(
                regex.compile(
                    item.pattern if item.regex else regex.escape(item.pattern),
                    0 if item.case_sensitive else regex.IGNORECASE,
                )
            )
        except regex.error as error:
            raise tool_error(
                f"The pattern {item.pattern!r} is not a regular expression: {error}"
            ) from error
    texts = _published_texts(user_id, arguments.find, "The find")
    result = ArtifactsFound(
        items=[
            FoundText(
                file=shown_artifact(file),
                total_matches_seen=0,
                matches=[],
                next_match_offset=None,
                timed_out=False,
                truncated=text.truncated,
            )
            for file, text in texts
        ]
    )
    for index, (item, pattern, (file, text), found) in enumerate(
        zip(arguments.find, patterns, texts, result.items, strict=True)
    ):
        lines, page_starts = artifact_lines(text)
        first, last = (
            _page_lines(
                file,
                page_starts,
                len(lines),
                item.start_page or 1,
                item.end_page or len(page_starts),
            )
            if item.start_page is not None or item.end_page is not None
            else (1, len(lines))
        )
        found.matches, found.total_matches_seen, found.reached_line = find_lines(
            lines,
            page_starts,
            pattern,
            max(first, item.start_line or 1),
            min(last, item.end_line or last),
            before=item.context_before_lines,
            after=item.context_after_lines,
            max_matches=item.max_matches,
            offset=item.match_offset,
            max_chars=ARTIFACT_RESULT_MAX_CHARS
            - len(result.model_dump_json())
            - (len(texts) - index) * _ITEM_NUMBERS_CHARS,
            timeout=FIND_TIMEOUT_SECONDS,
        )
        shown = item.match_offset + len(found.matches)
        found.next_match_offset = shown if found.total_matches_seen > shown else None
        found.timed_out = found.reached_line is not None
    return result


# How much text a snippet keeps before the first query word that it shows.
_SNIPPET_LEAD_CHARS = 60


def search_snippet(
    match_highlights: Sequence[str], content: str, words: Sequence[str]
) -> str:
    """The snippet of a matching chunk: its first match highlight without
    the <hi> tags, or else its content from _SNIPPET_LEAD_CHARS before the
    first of `words` that it contains (any case), or from its start. The
    lead starts at a word when one starts early enough to keep the match in
    the snippet. Runs of white space become one space, and a cut shows as
    "…"; at most LIBRARY_SEARCH_SNIPPET_MAX_CHARS."""
    highlight = next((text for text in match_highlights if text.strip()), None)
    text = " ".join(
        (
            content
            if highlight is None
            else highlight.replace("<hi>", "").replace("</hi>", "")
        ).split()
    )
    if highlight is None:
        found = [
            match.span()
            for word in words
            if word
            and (match := regex.search(regex.escape(word), text, regex.IGNORECASE))
        ]
        if found and min(found)[0] > _SNIPPET_LEAD_CHARS:
            match_start, match_end = min(found)
            start = match_start - _SNIPPET_LEAD_CHARS
            word_start = text.rfind(" ", 0, start) + 1
            # "…" and the text up to the match's end fit before the cut.
            if word_start and 1 + match_end - word_start < (
                LIBRARY_SEARCH_SNIPPET_MAX_CHARS
            ):
                start = word_start
            text = "…" + text[start:]
    if len(text) > LIBRARY_SEARCH_SNIPPET_MAX_CHARS:
        text = text[: LIBRARY_SEARCH_SNIPPET_MAX_CHARS - 1] + "…"
    return text


def _search_file_chunks(
    user_id: UUID,
    cancellation: CancellationSignal,
    document_index: DocumentIndex,
    embedding_model: EmbeddingModel | None,
    query: str,
    document_ids: list[str],
) -> list[InferenceChunk]:
    """The chunks of the documents that match the query, at most
    LIBRARY_SEARCH_MAX_SNIPPETS of each, by document from its best chunk.
    Hybrid search with an embedding model, keyword search without one. A
    full retrieval can hold the chunks of a few long documents only: when
    the per-document cap dropped chunks of a full retrieval, the next one
    searches the documents that no retrieval found, up to
    LIBRARY_SEARCH_RETRIEVALS_PER_QUERY. A Stop ends the search before its
    next retrieval."""
    kept: dict[str, list[InferenceChunk]] = {}
    for _ in range(LIBRARY_SEARCH_RETRIEVALS_PER_QUERY):
        unfound = [
            document_id for document_id in document_ids if document_id not in kept
        ]
        if not unfound:
            break
        cancellation.check()
        chunks = search_chunks(
            ChunkIndexRequest(
                query=query,
                query_keywords=strip_stopwords(query),
                filters=IndexFilters(
                    source_type=[DocumentSource.CHAT_ARTIFACT],
                    attached_document_ids=unfound,
                    access_control_list=None,
                ),
                limit=LIBRARY_SEARCH_CHUNKS_PER_QUERY,
                hybrid_alpha=None if embedding_model is not None else 0.0,
            ),
            user_id,
            document_index,
            None,
            embedding_model,
            [],
        )
        dropped = False
        for chunk in chunks:
            document_chunks = kept.setdefault(chunk.document_id, [])
            if len(document_chunks) < LIBRARY_SEARCH_MAX_SNIPPETS:
                document_chunks.append(chunk)
            else:
                dropped = True
        if (
            not dropped
            or len(chunks) < LIBRARY_SEARCH_CHUNKS_PER_QUERY
            or len(kept) >= LIBRARY_SEARCH_WINDOW
        ):
            break
    return [chunk for document_chunks in kept.values() for chunk in document_chunks]


def search_artifacts(
    user_id: UUID,
    cancellation: CancellationSignal,
    arguments: LibrarySearchArguments,
) -> LibrarySearchResult:
    """The user's published files that match the queries, from the database
    and the search index only; it never starts the VM.

    The database gives the files in scope (`get_user_artifact_search_candidates`):
    the newest LIBRARY_SEARCH_MAX_CANDIDATES that the scope, chat and
    filters keep, and which of them have each query's words, without
    stopwords and punctuation, in their name, title or chat title. Each
    content query searches the chunks of exactly those files
    (`search_chunks`), with no ACL: the database lookup is the access check.
    A file gives a query at most LIBRARY_SEARCH_MAX_SNIPPETS chunks. Another
    retrieval, over the files that no retrieval found, runs only when that
    cap dropped chunks of a full retrieval, up to
    LIBRARY_SEARCH_RETRIEVALS_PER_QUERY (`_search_file_chunks`), so a
    matching file can stay out of the content ranking.
    For relevance the search is hybrid; for the other sorts it is keyword
    only, because vector search always returns the nearest chunks, which
    would list unrelated files. Each query gives two rankings: its content
    matches by their best chunk, and its name matches by latest change
    (publish or rename), which covers files not indexed yet. A title-only query, and every query
    without a search index (DISABLE_VECTOR_DB), gives the name ranking only.
    The rankings fuse by reciprocal rank into the search's window of
    LIBRARY_SEARCH_WINDOW files, and the other sorts reorder only the
    window. A cursor is an offset into the window, and a page keeps to
    ARTIFACT_RESULT_MAX_CHARS."""
    offset = (
        0
        if arguments.cursor is None
        else _decode_cursor(_SEARCH_CURSOR, arguments.cursor, "search").offset
    )
    top_k = min(max(arguments.top_k, 1), LIBRARY_SEARCH_MAX_TOP_K)
    filters = arguments.filters or LibraryListFilters()
    queries = arguments.search_query
    content = [
        not DISABLE_VECTOR_DB and not query.search_title_only for query in queries
    ]
    # The words of each query that a name, a title and a snippet match.
    # Stopwords go after the split, so "What's" leaves no stray "s". An
    # underscore splits words, as a name's other separators do.
    term_sets = [
        strip_stopwords(" ".join(words)) or words
        for words in (regex.findall(r"[^\W_]+", query.q) for query in queries)
    ]
    with artifact_errors("The search"):
        with get_session_with_current_tenant() as db_session:
            artifact_ids: list[UUID] | None = None
            if arguments.scope is not None:
                artifact_ids = []
                for reference in arguments.scope.file_refs:
                    file = _published_file(db_session, user_id, reference)
                    if file.version_number != file.latest_version_number:
                        raise tool_error(
                            f"{reference.file_id or reference.library_file_id} is "
                            f"version {file.version_number} of "
                            f"{file.library_file_id}; only the newest version is "
                            "searchable: find text in that version instead"
                        )
                    artifact_ids.append(file.library_file_id)
            candidates = get_user_artifact_search_candidates(
                db_session,
                user_id,
                chat_session_id=arguments.chat_id,
                filters=filters,
                artifact_ids=artifact_ids,
                term_sets=term_sets,
                limit=LIBRARY_SEARCH_MAX_CANDIDATES + 1,
            )
            if candidates is None:
                raise tool_error(f"No chat {arguments.chat_id} of yours")
            document_index: DocumentIndex | None = None
            embedding_model: EmbeddingModel | None = None
            if any(content) and candidates:
                search_settings = get_current_search_settings(db_session)
                document_index = get_default_document_index(search_settings, None)
                # The other sorts search by keyword only and embed no query.
                if arguments.sort == "relevance":
                    embedding_model = EmbeddingModel.from_db_model(
                        search_settings=search_settings,
                        server_host=MODEL_SERVER_HOST,
                        server_port=MODEL_SERVER_PORT,
                    )
        complete = len(candidates) <= LIBRARY_SEARCH_MAX_CANDIDATES
        candidates = candidates[:LIBRARY_SEARCH_MAX_CANDIDATES]
        by_document_id = {
            str(artifact_id): artifact_id for artifact_id, _ in candidates
        }

        chunk_sets: list[list[InferenceChunk]] = (
            run_functions_tuples_in_parallel(
                [
                    (
                        _search_file_chunks,
                        (
                            user_id,
                            cancellation,
                            document_index,
                            embedding_model,
                            query.q,
                            list(by_document_id),
                        ),
                    )
                    for query, is_content in zip(queries, content, strict=True)
                    if is_content
                ]
            )
            if document_index is not None
            else []
        )
    # Each file's chunks by the index of the query that found them, best
    # first, with that query's words.
    chunks_of: dict[UUID, dict[int, list[tuple[InferenceChunk, list[str]]]]] = (
        defaultdict(dict)
    )
    rankings: list[list[UUID]] = []
    found_chunks = iter(chunk_sets)
    for index, is_content in enumerate(content):
        if document_index is not None and is_content:
            # The files that the query's chunks found, by their best chunk.
            found: dict[UUID, None] = {}
            for chunk in next(found_chunks):
                artifact_id = by_document_id.get(chunk.document_id)
                if artifact_id is not None:
                    found[artifact_id] = None
                    chunks_of[artifact_id].setdefault(index, []).append(
                        (chunk, term_sets[index])
                    )
            rankings.append(list(found))
        rankings.append(
            [artifact_id for artifact_id, matched in candidates if matched[index]]
        )
    window = weighted_reciprocal_rank_fusion_with_scores(
        rankings, [1.0] * len(rankings), str
    )[:LIBRARY_SEARCH_WINDOW]
    files: dict[UUID, tuple[ListedArtifact, bool]] = {}
    if window:
        with artifact_errors("The search"):
            with get_session_with_current_tenant() as db_session:
                files = get_user_published_files_by_id(
                    db_session,
                    user_id,
                    [artifact_id for artifact_id, _ in window],
                    chat_session_id=arguments.chat_id,
                    filters=filters,
                )
    hits = [
        LibrarySearchHit(
            file=files[artifact_id][0],
            score=score,
            content_indexed=files[artifact_id][1],
        )
        for artifact_id, score in window
        if artifact_id in files
    ]
    if arguments.sort != "relevance":
        sort_key: Callable[[LibrarySearchHit], datetime | str | int] = {
            "created_at": lambda hit: hit.file.created_at,
            "modified_at": lambda hit: hit.file.modified_at,
            "name": lambda hit: hit.file.file_name.casefold(),
            "size": lambda hit: hit.file.file_size_bytes,
        }[arguments.sort]
        # Stable: equal keys keep their relevance order.
        hits.sort(key=sort_key, reverse=arguments.sort_order == "desc")
    shown = hits[offset : offset + top_k]
    if arguments.result_format == "snippets":
        for hit in shown:
            # A snippet from each query in turn, so that one query cannot
            # take every slot.
            in_turn = chain.from_iterable(
                zip_longest(
                    *(
                        (
                            search_snippet(chunk.match_highlights, chunk.content, words)
                            for chunk, words in query_chunks
                        )
                        for query_chunks in chunks_of.get(
                            hit.file.library_file_id, {}
                        ).values()
                    )
                )
            )
            hit.snippets = [
                snippet for snippet in dict.fromkeys(in_turn) if snippet is not None
            ][:LIBRARY_SEARCH_MAX_SNIPPETS]
    logger.info(
        "library_search queries=%d candidates=%d window=%d",
        len(queries),
        len(candidates),
        len(hits),
    )
    return _fit_page(
        shown,
        lambda page: LibrarySearchResult(
            results=page,
            next_cursor=_encode_cursor(
                _SEARCH_CURSOR, LibrarySearchCursor(offset=offset + len(page))
            )
            if page and offset + len(page) < len(hits)
            else None,
            complete=complete,
            content_search="unavailable" if DISABLE_VECTOR_DB else None,
        ),
    )


def run_operation(
    turn: SandboxTurn,
    cancellation: CancellationSignal,
    request: LibraryRequest,
    *,
    conflict_message: Callable[[ArtifactVersionConflict], str],
) -> ToolResult:
    """Run the operation that `request` asks for. Every tool over the user's
    published files runs it, so both tool families give the same results; a
    publish or a replace shows the publish card (PublishedFiles).
    `conflict_message` words a new version's version conflict for the calling
    tool."""
    if isinstance(request, LibraryCreateLibraryFileArguments):
        published = publish(
            turn,
            cancellation,
            [PublishFileArgument(path=request.file, title=request.title)]
            if request.file is not None
            else [PublishFileArgument(path=path) for path in request.files or []],
        )
    elif isinstance(request, LibraryReplaceLibraryFileArguments):
        try:
            published = [replace_file(turn, cancellation, request)]
        except ArtifactVersionConflict as error:
            raise tool_error(conflict_message(error)) from error
    elif isinstance(request, ManageLibraryArguments):
        return ToolResult(
            content=manage(
                turn.user_id,
                cancellation,
                request,
                conflict_message=conflict_message,
            ).model_dump_json()
        )
    elif isinstance(request, LibraryListArguments):
        return ToolResult(
            content=list_artifacts(turn.user_id, request).model_dump_json()
        )
    elif isinstance(request, LibrarySearchArguments):
        return ToolResult(
            content=search_artifacts(
                turn.user_id, cancellation, request
            ).model_dump_json()
        )
    elif isinstance(request, LibraryReadArguments):
        return ToolResult(content=read(turn.user_id, request).model_dump_json())
    elif isinstance(request, LibraryFindArguments):
        return ToolResult(content=find(turn.user_id, request).model_dump_json())
    else:
        return ToolResult(
            content=materialize(turn, cancellation, request).model_dump_json()
        )
    return ToolResult(
        content=ArtifactPublished.of(published).model_dump_json(),
        details=PublishedFiles(files=published),
    )
