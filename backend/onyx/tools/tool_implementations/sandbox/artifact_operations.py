"""The operations over the user's published files (artifacts) that both
tool families run: the library tools and the artifact tool
(sandbox_tools.py). Each takes the library tools' argument model, runs
one operation and returns its typed result; errors that the model can act
on are ToolCallExceptions (errors.py:artifact_errors)."""

import base64
import posixpath
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from functools import partial
from itertools import count
from uuid import UUID

import regex
from pydantic import JsonValue
from sqlalchemy.orm import Session

from onyx.db.chat import (
    append_copied_artifact_version,
    delete_chat_artifact,
    delete_unpublished_chat_artifacts,
    get_user_published_file,
    get_user_published_files,
    rename_chat_artifact,
    save_chat_artifact,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
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
from onyx.microvm.models import FileType
from onyx.server.features.build.sandbox.harness_base import (
    ARTIFACT_FILES_DIR,
    CHAT_FILES_DIR,
    RENDER_FIRST_PAGE_BUDGET_SECONDS,
    RENDER_FIRST_PAGE_MAX_INPUT_BYTES,
    RENDER_FIRST_PAGE_SUFFIXES,
    SandboxPathError,
    chat_file_name,
    safe_file_name,
    session_relative_path,
)
from onyx.server.features.build.sandbox.models import session_workspace
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
    ARTIFACTS_QUERY_MAX_CHARS,
    DELETE_OF_A_VERSION,
    FIND_TIMEOUT_SECONDS,
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
    LibraryFileTarget,
    LibraryFindArguments,
    LibraryListArguments,
    LibraryListFilters,
    LibraryPrepareMaterializeArguments,
    LibraryReadArguments,
    LibraryReplaceLibraryFileArguments,
    ListedArtifact,
    ManageLibraryArguments,
    ManageResult,
    ManageResults,
    MaterializeDestination,
    MaterializedItem,
    MaterializedItems,
    PublishedFile,
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
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_string

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
    in the VM, when it renders within the call's render budget. A call
    publishes all of its files or none."""
    sandbox = turn.sandbox
    published: list[PublishedFile] = []
    try:
        with artifact_errors("The publish"):
            # The turn's chat session is the root chat's, whose readers
            # may download the files; subagent runs share it.
            ref = turn.start_call()
            # The budget starts once the call has its sandbox, so a wake
            # or a skills sync does not spend it.
            render_until = time.monotonic() + RENDER_FIRST_PAGE_BUDGET_SECONDS
            for requested in files:
                cancellation.check()
                data = sandbox.read_file(
                    ref, requested.path, max_bytes=PUBLISH_FILES_MAX_BYTES
                )
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
                # A file with no thumbnail still publishes. Once the
                # budget is spent, no render looks up its file or logs.
                thumbnail = (
                    sandbox.render_first_page(ref, path, until=render_until)
                    if posixpath.splitext(path)[1].lower() in RENDER_FIRST_PAGE_SUFFIXES
                    and len(data) <= RENDER_FIRST_PAGE_MAX_INPUT_BYTES
                    and time.monotonic() < render_until
                    else None
                )
                published.append(
                    save_chat_artifact(
                        data,
                        name=name,
                        mime_type=chat_output_file_type(name),
                        title=title,
                        thumbnail=thumbnail,
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


def list_artifacts(user_id: UUID, arguments: LibraryListArguments) -> ArtifactList:
    """A page of the published files in the user's listable chats, from the
    database only; it never starts the VM. A page keeps to
    ARTIFACT_RESULT_MAX_CHARS, under the spill limit of one result, and the
    step's budget does not spill it."""
    chat_id: UUID | None = None
    if arguments.chat_id is not None:
        try:
            chat_id = UUID(arguments.chat_id)
        except ValueError as error:
            raise tool_error(f"No chat {arguments.chat_id} of yours") from error
    cursor: ArtifactCursor | None = None
    if arguments.cursor is not None:
        try:
            cursor = ARTIFACT_CURSOR.validate_json(
                base64.urlsafe_b64decode(arguments.cursor)
            )
        except ValueError as error:
            raise tool_error(
                "The cursor is not a next_cursor of this tool; list again without it"
            ) from error
        if (cursor.sort, cursor.sort_order) != (
            arguments.sort,
            arguments.sort_order,
        ):
            raise tool_error(
                f"The cursor is from a list with sort {cursor.sort} and "
                f"sort_order {cursor.sort_order}; send those, or list again "
                "without the cursor"
            )
    query = (arguments.query or "").strip()
    if len(query) > ARTIFACTS_QUERY_MAX_CHARS:
        raise tool_error(
            f"The query is longer than {ARTIFACTS_QUERY_MAX_CHARS} characters"
        )
    limit = min(max(arguments.limit, 1), ARTIFACTS_LIST_MAX_LIMIT)
    with artifact_errors("The listing"):
        with get_session_with_current_tenant() as db_session:
            rows = get_user_published_files(
                db_session,
                user_id,
                query=query or None,
                chat_session_id=chat_id,
                filters=arguments.filters or LibraryListFilters(),
                sort=arguments.sort,
                sort_order=arguments.sort_order,
                limit=limit,
                cursor=cursor,
            )
    if rows is None:
        raise tool_error(f"No chat {arguments.chat_id} of yours")
    shown, more = rows[:limit], len(rows) > limit
    while True:
        page = ArtifactList(
            files=[artifact for artifact, _ in shown],
            next_cursor=base64.urlsafe_b64encode(
                ARTIFACT_CURSOR.dump_json(shown[-1][1])
            ).decode()
            if more and shown
            else None,
        )
        if len(page.model_dump_json()) <= ARTIFACT_RESULT_MAX_CHARS or len(shown) <= 1:
            return page
        shown, more = shown[:-1], True


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
    user_id: UUID, operations: Sequence[DeleteOperation | _OtherOperation]
) -> ToolApprovalDetails | None:
    """The approval card of a call with these operations, which both tool
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
    deletes = [
        operation.target
        for operation in operations
        if isinstance(operation, DeleteOperation)
    ]
    others = [
        operation
        for operation in operations
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
