"""The operations over the user's published files (artifacts) that both
tool families run: the library tools and the artifact tool
(sandbox_tools.py). Each takes the library tools' argument model, runs
one operation and returns its typed result; errors that the model can act
on are ToolCallExceptions (errors.py:artifact_errors)."""

import base64
import posixpath
import time
from collections.abc import Sequence
from concurrent.futures import Future
from functools import partial
from itertools import count
from uuid import UUID

from onyx.db.chat import (
    delete_unpublished_chat_artifacts,
    get_user_published_file,
    get_user_published_files,
    save_chat_artifact,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.file_store.utils import chat_output_file_type
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
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.sandbox import file_copies
from onyx.tools.tool_implementations.sandbox.errors import artifact_errors, tool_error
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACT_CURSOR,
    ARTIFACTS_LIST_MAX_CHARS,
    ARTIFACTS_LIST_MAX_LIMIT,
    ARTIFACTS_QUERY_MAX_CHARS,
    PUBLISH_FILES_MAX_BYTES,
    PUBLISH_FILES_MAX_TITLE_CHARS,
    ArtifactAtPath,
    ArtifactById,
    ArtifactCursor,
    ArtifactList,
    KeptTitle,
    LibraryListArguments,
    LibraryListFilters,
    LibraryPrepareMaterializeArguments,
    LibraryReplaceLibraryFileArguments,
    ListedArtifact,
    MaterializeDestination,
    MaterializedItem,
    MaterializedItems,
    PublishedFile,
    PublishFileArgument,
    artifact_extension,
    artifact_url,
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


def publish(
    turn: SandboxTurn,
    cancellation: CancellationSignal,
    files: Sequence[PublishFileArgument],
    *,
    artifact: ListedArtifact | None = None,
    expected_version: int | None = None,
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
                # Postgres text cannot hold NUL, and a blank title is no
                # title
                title = (
                    KeptTitle.NEWEST
                    if artifact is not None and requested.title is None
                    else sanitize_string(requested.title or "")
                    .strip()[:PUBLISH_FILES_MAX_TITLE_CHARS]
                    .rstrip()
                    or None
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
                    )
                )
            # A Stop during the last copy publishes nothing.
            cancellation.check()
    except BaseException:
        # A failed clean-up must not replace the call's own error or Stop.
        try:
            delete_unpublished_chat_artifacts(published)
        except Exception:
            logger.warning(
                "artifact_publish_cleanup_failed files=%s",
                [file.file_id for file in published],
                exc_info=True,
            )
        raise
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
            artifact = get_user_published_file(
                db_session, turn.user_id, artifact_id=arguments.library_file_id
            )
    if artifact is None:
        raise tool_error(f"No published file {arguments.library_file_id} in your chats")
    check_same_type(artifact, arguments.file)
    [published] = publish(
        turn,
        cancellation,
        [PublishFileArgument(path=arguments.file, title=arguments.title)],
        artifact=artifact,
        expected_version=arguments.expected_current_version,
    )
    return published


def list_artifacts(user_id: UUID, arguments: LibraryListArguments) -> ArtifactList:
    """A page of the published files in the user's listable chats, from the
    database only; it never starts the VM. A page keeps to
    ARTIFACTS_LIST_MAX_CHARS, under the spill limit of one result, and the
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
        if len(page.model_dump_json()) <= ARTIFACTS_LIST_MAX_CHARS or len(shown) <= 1:
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
    with artifact_errors("The copy"):
        with get_session_with_current_tenant() as db_session:
            found = [
                get_user_published_file(
                    db_session,
                    turn.user_id,
                    file_id=item.file_id,
                    artifact_id=item.library_file_id,
                    version=item.version_number,
                )
                for item in arguments.items
            ]
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
    for index, (item, file) in enumerate(zip(arguments.items, found, strict=True)):
        try:
            if file is None:
                raise tool_error(
                    f"No published file {item.file_id} in your chats"
                    if item.file_id is not None
                    else f"No version {item.version_number} of published file "
                    f"{item.library_file_id} in your chats"
                    if item.version_number is not None
                    else f"No published file {item.library_file_id} in your chats"
                )
            item_directory = (
                directory
                if item.relative_directory is None
                else _copy_directory(
                    session_id, posixpath.join(directory, item.relative_directory)
                )
            )
            prefixed = item_directory == ARTIFACT_FILES_DIR and not item.file_name
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
