"""Background copies of chat files and of search result files into the
chat's sandbox VM, in the chat's working directory. No call waits for a copy.

Two roots, each with its own copy:
- Chat files: at the turn's first sandbox call, `SandboxTurn` starts the
  turn's `TurnFileCopies` with the chat's complete set of chat files in
  attachments/, attachments/project/ and attachments/agent/.
- Search result files: when a search returns, `TurnSearchFiles.offer` takes
  the files of the results that the model is shown and copies them into
  attachments/search/.

The rules:

- Paths. A path names one file for good: it holds 8 hex digits of the file
  store ID, or for a search file of the ID's SHA-256
  (`harness_base.search_file_name`). Writes are atomic (the daemon renames
  each file into place), so a path holds a whole file or nothing.
- In place. The chat file copy lists the session directory and its
  directories, and the search file copy lists attachments/search/, one level
  each, so a large tree that the model makes there costs the listing
  nothing. A file is in place when the listing shows a regular file of its
  size at its path; the copy writes any other file. So a VM restart,
  or a file that is missing or has another size, gets the file again. A
  listing that fails other than by a timeout is unknown, and the copy writes
  every file.
- Cleanup. The chat file copy deletes the entries of attachments/project/
  and attachments/agent/ that are not in its set of chat files (a file that
  left the project or the agent). Other entries in attachments/ (the
  model's own) stay, and a deleted upload's copy stays until the VM
  restarts. It never deletes in attachments/search/ or attachments/artifacts/.
  A file that a copy leaves out (over a limit, or not in the file store)
  keeps what is at its path.
- Search files. A search offers the files of its shown results that a tool
  can open (`search_tool.py:SearchTool._build_search_result`: connector
  files whose object is not confirmed missing, at most
  SEARCH_FILE_MAX_BYTES), each once per turn, while the turn's budget lasts:
  MAX_TURN_SEARCH_FILES files and MAX_TURN_SEARCH_BYTES, shared by the root
  and its subagents. The search result names exactly the offered files, so a
  cancelled search offers nothing. A file that the turn does not write (in
  place, refused or failed intake) gives its share back; a record with no
  size is checked against the limits with its real size. The copy checks
  once, in one query, which files a document that the user can read still
  has, and copies only those. An offered file can still miss: refused at
  copy time, over a limit by its real size, dropped by the cap, or failed;
  its path stays in the result, and a search in a later turn copies it
  again. Before it writes, the copy picks the writes that fit in
  MAX_CHAT_SEARCH_BYTES next to the turn's offered files and its earlier
  writes, then deletes the chat's oldest other search files (by
  modification time) to make room for them, and for nothing else; a
  truncated or failed listing deletes nothing. A failed delete stops the
  intake: no other file is deleted or written. Only this eviction deletes
  search files. Accepted: an eviction can delete a file that a later
  command of an earlier turn's result opens, and a file ID whose bytes
  change at the same size keeps the old copy.
- Links. A directory of chat files that the model replaced with a link or a
  file is not listed, cleaned up or written to; its files are not copied, and
  the link stays. A directory whose type a failed or truncated listing did
  not show is treated the same way. The search file copy has no such check:
  a link that the model makes in its own session can redirect its writes and
  evictions, which is accepted.
- Generations. Each turn takes the chat's next copy generation when its
  `SandboxTurn` is created, for the copies of both roots, and a chat purge
  takes one too. So a later turn always holds a higher generation than an
  earlier turn's late copies (a background subagent's search). Before the
  listing, each delete, and each write once its file is
  downloaded, a copy reads the generation; a copy whose generation is not
  the chat's is superseded and stops. So the newest turn wins, and a purge
  stops the chat's copies. A late write of a file that just left the project
  can stay until the next turn's cleanup. A late write after a purge deletes
  the session directory that it made (`SessionFiles.write`).
- No response. A write, delete or listing that times out, or finds the VM
  instance gone, fails the copy's remaining files at once. Per-VM slot caps
  keep a hung VM from holding the other VMs' copies.
- Status. Only chat files have the `[files]` status line; the search result
  is the only place that names search files.
- Session saves skip attachments/, since the copies come from the file store
  again after a restart.
- Pod shutdown stops the copies before their next try; a write in flight
  runs to its end, or until the pod is killed.
"""

import itertools
import posixpath
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextvars import Context, copy_context
from datetime import datetime, timezone
from enum import Enum
from functools import partial
from typing import IO, NamedTuple, cast
from uuid import UUID

import grpc

from onyx.access.hierarchy_access import get_user_external_group_ids
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.db.document_access import get_accessible_documents_by_ids
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.file_record import get_filerecords_by_file_ids
from onyx.db.users import fetch_user_by_id
from onyx.file_store.file_store import (
    FILE_SIZE_MISSING_SENTINEL,
    get_default_file_store,
)
from onyx.microvm.agent_client import (
    HostAgentError,
    InstanceMismatchError,
    VmNotRunningError,
)
from onyx.microvm.daemon_client import SandboxDaemonError
from onyx.microvm.models import FileEntry, FileListing, FileType
from onyx.server.features.build.sandbox.file_copy_state import copy_generation_key
from onyx.server.features.build.sandbox.harness_base import (
    AGENT_FILES_DIR,
    CHAT_FILES_DIR,
    PROJECT_FILES_DIR,
    SEARCH_FILES_DIR,
    HarnessSandbox,
    SandboxPathError,
    SessionFiles,
    search_file_name,
    session_relative_path,
)
from onyx.server.features.build.sandbox.models import HarnessSandboxRef
from onyx.server.settings.store import load_settings
from onyx.tools.tool_implementations.sandbox.models import (
    SEARCH_FILE_MAX_BYTES,
    SearchResultFile,
    VmChatFile,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_MIB = 1 << 20
_GIB = 1 << 30
# Tries of one file: the first and two retries.
COPY_TRIES = 3
RETRY_PAUSE_SECONDS = 1.0
# The timeout of one try: this much, plus the file's size at this rate.
COPY_BASE_SECONDS = 30.0
COPY_MIN_BYTES_PER_SECOND = 2 * _MIB
MAX_TURN_BYTES = _GIB
# The longest cache call of a copy.
COPY_CACHE_SECONDS = 5.0
# The shortest busy mark of a copy's downloads and writes.
BUSY_MARK_SECONDS = 120.0
# The most entries listed in one directory.
_MAX_LISTED = 100_000
# The directories of chat files, and those that the copy cleans up.
_CHAT_FILE_DIRS = (CHAT_FILES_DIR, PROJECT_FILES_DIR, AGENT_FILES_DIR)
_CLEANED_DIRS = (PROJECT_FILES_DIR, AGENT_FILES_DIR)
# The search files of one turn of a chat, and of one chat.
MAX_TURN_SEARCH_FILES = 50
MAX_TURN_SEARCH_BYTES = 512 * _MIB
MAX_CHAT_SEARCH_BYTES = _GIB
# The modification time of a listed file that has none: it goes last.
_UNKNOWN_AGE = datetime.max.replace(tzinfo=timezone.utc)
# The status line names at most this many files of each state.
_NAMED_FILES = 5
_INDENT = "\n        "
# Threads per API pod, and per VM. With the Postgres cache and file store,
# copies hold at most 6 * 3 + 12 of the API server's database connections.
POD_INTAKE_THREADS = 6
POD_COPY_THREADS = 12
VM_INTAKES = 2
VM_COPY_WRITES = 2


Task = Callable[[], None]


class _Slots:
    """Tasks of the pod's copies on one thread pool, at most `per_vm` at a
    time in one VM, taken in turn by the copies that wait for that VM. A copy
    gives its next task, or None when it has none left. Each task runs in a
    copy of the context of the `want` call that queued its copy."""

    def __init__(
        self, threads: int, name: str, per_vm: int, stopped: threading.Event
    ) -> None:
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(threads, thread_name_prefix=name)
        self._per_vm = per_vm
        self._stopped = stopped
        # By sandbox: the tasks that run, and the copies that wait, in turn.
        self._running: dict[UUID, int] = {}
        self._waiting: dict[UUID, deque[tuple[Context, Callable[[], Task | None]]]] = {}

    def want(self, sandbox_id: UUID, next_task: Callable[[], Task | None]) -> None:
        context = copy_context()
        with self._lock:
            if self._stopped.is_set():
                return
            self._waiting.setdefault(sandbox_id, deque()).append((context, next_task))
            starts = self._take(sandbox_id)
        self._start(sandbox_id, starts)

    def shutdown(self) -> None:
        """Drop the waiting tasks and cancel the queued ones; running ones end
        on their own."""
        with self._lock:
            self._waiting.clear()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def idle(self) -> bool:
        """Whether no task runs or waits."""
        with self._lock:
            return not self._running and not self._waiting

    def _take(self, sandbox_id: UUID) -> list[tuple[Context, Task]]:
        """Give the VM's free slots to its waiting copies, one task each in
        turn (under the lock)."""
        starts: list[tuple[Context, Task]] = []
        waiting = self._waiting.get(sandbox_id)
        while waiting and self._running.get(sandbox_id, 0) < self._per_vm:
            context, next_task = waiting.popleft()
            task = next_task()
            if task is None:
                continue
            waiting.append((context, next_task))
            self._running[sandbox_id] = self._running.get(sandbox_id, 0) + 1
            # Two tasks of one copy can run at once, each in its own context.
            starts.append((context.copy(), task))
        if not waiting:
            self._waiting.pop(sandbox_id, None)
        return starts

    def _start(self, sandbox_id: UUID, starts: list[tuple[Context, Task]]) -> None:
        for context, task in starts:

            def in_slot(task: Task = task) -> None:
                try:
                    task()
                except Exception:
                    logger.exception("sandbox_file_copy_task_failed")
                finally:
                    with self._lock:
                        self._running[sandbox_id] -= 1
                        if not self._running[sandbox_id]:
                            del self._running[sandbox_id]
                        starts = self._take(sandbox_id)
                    self._start(sandbox_id, starts)

            self._pool.submit(context.run, in_slot)


class FileCopyPool:
    """The copy work of the API pod: intakes (set the session up, list the
    files, clean up) in intake slots, and writes in write slots. A VM has at
    most VM_INTAKES intake slots and VM_COPY_WRITES write slots in use, so a
    slow or hung VM leaves the other threads to other VMs."""

    def __init__(self) -> None:
        # Pod shutdown: no task starts, and copies stop before their next try.
        self.stopped = threading.Event()
        self.intake = _Slots(
            POD_INTAKE_THREADS, "sandbox-file-intake", VM_INTAKES, self.stopped
        )
        self.writes = _Slots(
            POD_COPY_THREADS, "sandbox-file-copy", VM_COPY_WRITES, self.stopped
        )

    def idle(self) -> bool:
        """Whether the copies have no task running or waiting. The intake
        slots go first: an intake queues its writes before it ends."""
        return self.intake.idle() and self.writes.idle()

    def shutdown(self) -> None:
        self.stopped.set()
        self.intake.shutdown()
        self.writes.shutdown()


# The pod's pool: the first copy makes it, and API shutdown stops it.
_pool: FileCopyPool | None = None
_pool_lock = threading.Lock()


def file_copy_pool() -> FileCopyPool:
    """The pod's pool, made on first use."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = FileCopyPool()
        return _pool


def shutdown_file_copies() -> None:
    """Stop the pod's copies (API shutdown). The chat's next turn copies
    what they left."""
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown()


class CopyState(str, Enum):
    COPYING = "copying"
    DONE = "done"
    FAILED = "failed"
    # Over a limit, or not in the file store.
    NOT_COPIED = "not_copied"


class _Failure(NamedTuple):
    # For the status line only.
    reason: str
    # The copy stops, and its waiting files fail too.
    ends_copy: bool = False


# A newer copy of the chat, a purge, or pod shutdown.
_SUPERSEDED = _Failure("the copy stopped", ends_copy=True)
_NO_RESPONSE = _Failure("the sandbox did not respond", ends_copy=True)
_NO_START = _Failure("the sandbox did not start")
_ERROR = _Failure("the copy stopped on an error")
_NO_DOWNLOAD = _Failure("the file store did not return the file")
_NOT_TAKEN = _Failure("the sandbox did not take the file")


class _File(NamedTuple):
    path: str
    file_id: str
    size: int


class _Listing(NamedTuple):
    # By path: the entries in the directories of chat files; None: unknown.
    entries: dict[str, FileEntry] | None
    # By directory of chat files that is not a verified directory: why. The
    # copy neither lists nor writes in it.
    not_dirs: dict[str, str]


def _list_chat_dirs(files: SessionFiles, sandbox_id: UUID) -> _Listing | None:
    """List the session directory and the directories of chat files; None
    when the instance did not respond. A listing that fails or is truncated
    marks the chat directories below it whose type it did not show; the copy
    neither lists nor writes in them."""
    entries: dict[str, FileEntry] = {}
    not_dirs: dict[str, str] = {}

    def unchecked(directory: str, seen: set[str]) -> None:
        """Mark the chat directories below `directory` whose entry, or whose
        parent's entry, the listing of `directory` did not show."""
        prefix = f"{directory}/" if directory else ""
        for chat_dir in _CHAT_FILE_DIRS:
            if chat_dir in not_dirs or not chat_dir.startswith(prefix):
                continue
            child = prefix + chat_dir.removeprefix(prefix).split("/", 1)[0]
            if child not in seen:
                not_dirs[chat_dir] = "could not be checked"

    for directory in ("", *_CHAT_FILE_DIRS):
        if directory in not_dirs:
            continue
        try:
            listing = files.list_files(directory, max_entries=_MAX_LISTED)
        except Exception as error:
            if _no_response(error):
                return None
            logger.warning(
                "sandbox_file_listing_failed sandbox=%s path=%s",
                sandbox_id,
                directory,
                exc_info=True,
            )
            unchecked(directory, set())
            return _Listing(None, not_dirs)
        for entry in listing.entries:
            if entry.path in _CHAT_FILE_DIRS and entry.type is not FileType.DIRECTORY:
                # What a link names is not the chat's to clean up or fill.
                not_dirs.update(
                    (chat_dir, f"{entry.path} is not a directory")
                    for chat_dir in _CHAT_FILE_DIRS
                    if f"{chat_dir}/".startswith(f"{entry.path}/")
                )
        if listing.truncated:
            unchecked(directory, {entry.path for entry in listing.entries})
        if directory:
            entries.update((entry.path, entry) for entry in listing.entries)
    return _Listing(entries, not_dirs)


def _no_response(error: Exception) -> bool:
    """The call timed out, or the VM instance stopped or was replaced."""
    if isinstance(error, (TimeoutError, VmNotRunningError, InstanceMismatchError)):
        return True
    if isinstance(error, SandboxDaemonError) and error.vm_unusable:
        return True
    return (
        isinstance(error, (HostAgentError, SandboxDaemonError))
        and error.code is grpc.StatusCode.DEADLINE_EXCEEDED
    )


def _size_text(size: int) -> str:
    if size >= _GIB:
        return f"{size / _GIB:.1f} GB"
    if size >= _MIB:
        return f"{size / _MIB:.0f} MB"
    return f"{size} bytes"


def _named(names: Iterable[str], count: int, separator: str = ", ") -> str:
    shown = list(itertools.islice(names, _NAMED_FILES))
    more = count - len(shown)
    text = separator.join(shown)
    return f"{text}{separator}and {more:,} more" if more > 0 else text


class CopyStatus:
    """The states of the turn's files, and the `[files]` status line. Each
    file is in one state; the line counts every file and names at most
    _NAMED_FILES of each state."""

    def __init__(self, paths: Iterable[str]) -> None:
        self._lock = threading.Lock()
        # By path, in the order that the files got their states: the state
        # and the text that the line names.
        self._files: dict[str, tuple[CopyState, str]] = {
            path: (CopyState.COPYING, path) for path in paths
        }
        self._new_done: list[str] = []
        self._new_done_count = 0
        self._changed = True
        # The last line given, and whether it named files as copying.
        self._last: str | None = None
        self._saw_copying = False

    def update(
        self,
        changes: Iterable[tuple[str, CopyState, str | None]],
        *,
        written: bool = False,
    ) -> None:
        """Set the states of files. `written`: the files are done because
        they were just written."""
        with self._lock:
            for path, state, reason in changes:
                self._files.pop(path, None)
                self._files[path] = (state, f"{path} ({reason})" if reason else path)
                if written and state is CopyState.DONE:
                    if len(self._new_done) < _NAMED_FILES:
                        self._new_done.append(path)
                    self._new_done_count += 1
            self._changed = True

    def settle(self, reason: str) -> None:
        """Fail every file that is still copying."""
        with self._lock:
            copying = [
                path
                for path, (state, _) in self._files.items()
                if state is CopyState.COPYING
            ]
        self.update((path, CopyState.FAILED, reason) for path in copying)

    def line(self) -> str | None:
        """The `[files]` line when it differs from the last line given; the
        model sees it now (also when the result that it goes into is then
        cancelled). Files that were all in place have nothing to say, unless
        the model saw files copying."""
        with self._lock:
            if not self._changed:
                return None
            self._changed = False
            by_state: dict[CopyState, list[str]] = {state: [] for state in CopyState}
            for state, text in self._files.values():
                by_state[state].append(text)
            done, copying = by_state[CopyState.DONE], by_state[CopyState.COPYING]
            if (
                not self._saw_copying
                and not self._new_done_count
                and len(done) == len(self._files)
            ):
                return None

            def part(state: CopyState, separator: str = ", ") -> str:
                return _named(by_state[state], len(by_state[state]), separator)

            lines: list[str] = []
            if copying:
                lines.append(f"Copying: {part(CopyState.COPYING)}.")
            if by_state[CopyState.FAILED]:
                lines.append(
                    f"Failed: {part(CopyState.FAILED, '; ')}; retrying next turn."
                )
            if by_state[CopyState.NOT_COPIED]:
                lines.append(f"Not copied: {part(CopyState.NOT_COPIED, '; ')}.")
            if self._new_done_count:
                named = _named(self._new_done, self._new_done_count)
                lines.append(f"Done since last status: {named}.")
            if done and not copying:
                lines.append(
                    f"All files are in {CHAT_FILES_DIR}/."
                    if len(done) == len(self._files)
                    else f"All other files are in {CHAT_FILES_DIR}/."
                )
            self._new_done, self._new_done_count = [], 0
            line = "[files] " + _INDENT.join(lines) if lines else None
            if line is None or line == self._last:
                return None
            self._last = line
            self._saw_copying = bool(copying)
            return line


def _superseded(cache: CacheBackend, session_id: UUID, generation: int) -> bool:
    """The chat's generation is not the copy's (a newer turn or a purge)."""
    raw = cache.get(copy_generation_key(session_id))
    return raw is None or int(raw) != generation


class _Writes:
    """The writes of one intake, in the VM's write slots: each file with its
    tries from one download, all under one busy mark of `files`. Creating it
    queues the writes. `on_end` gets every file once: None when it was
    written, or why it failed."""

    def __init__(
        self,
        ref: HarnessSandboxRef,
        pool: FileCopyPool,
        files: SessionFiles,
        writes: Sequence[_File],
        superseded: Callable[[], bool],
        on_end: Callable[[Sequence[_File], _Failure | None], None],
    ) -> None:
        self._pool = pool
        self._files = files
        self._superseded = superseded
        self._on_end = on_end
        self._lock = threading.Lock()
        # The files that wait for a write slot, and the number being written.
        self._pending = deque(sorted(writes, key=lambda file: file.size))
        self._writing = 0
        # A call timed out or found the VM instance gone: no more tries.
        self._no_response = False
        # Until when (monotonic) the busy mark lasts, once it is set; the
        # lock keeps the writes from setting it twice.
        self._mark_lock = threading.Lock()
        self._busy_until = 0.0
        pool.writes.want(ref.sandbox_id, self._next_write)

    def _next_write(self) -> Task | None:
        """The next file's write task, if any (for the pool)."""
        with self._lock:
            if not self._pending:
                return None
            file = self._pending.popleft()
            self._writing += 1

        def write() -> None:
            """Write the file. A failure that ends the copy fails its
            waiting files too."""
            try:
                failure = self._write(file)
                if failure is None:
                    self._on_end([file], None)
                    return
                with self._lock:
                    failed = [file]
                    if failure.ends_copy:
                        failed.extend(self._pending)
                        self._pending.clear()
                self._on_end(failed, failure)
            except Exception:
                logger.exception("sandbox_file_copy_failed path=%s", file.path)
                self._on_end([file], _ERROR)
            finally:
                with self._lock:
                    self._writing -= 1
                    end = not self._writing and not self._pending
                if end:
                    with self._mark_lock:
                        if self._busy_until:
                            try:
                                self._files.mark_busy(None)
                            except Exception:
                                # The mark expires on its own.
                                logger.warning(
                                    "sandbox_file_copy_mark_clear_failed",
                                    exc_info=True,
                                )

        return write

    def _renew_busy_mark(self, seconds: float) -> None:
        """Keep the VM busy for at least `seconds` from now. A mark that
        fails to set leaves the copy running; only an idle stop can come
        sooner."""
        with self._mark_lock:
            now = time.monotonic()
            if now + seconds + COPY_CACHE_SECONDS <= self._busy_until:
                return
            ttl = max(seconds, BUSY_MARK_SECONDS) + COPY_CACHE_SECONDS
            try:
                self._files.mark_busy(ttl)
            except Exception:
                logger.warning("sandbox_file_copy_mark_failed", exc_info=True)
                return
            self._busy_until = now + ttl

    def _write(self, file: _File) -> _Failure | None:
        """Copy the file with its tries from one download; None, or why it
        failed."""
        timeout = COPY_BASE_SECONDS + file.size / COPY_MIN_BYTES_PER_SECOND
        content: IO[bytes] | None = None
        failure = _ERROR
        try:
            for attempt in range(COPY_TRIES):
                if attempt:
                    time.sleep(RETRY_PAUSE_SECONDS)
                if self._no_response:
                    return _NO_RESPONSE
                if content is None:
                    if self._pool.stopped.is_set() or self._superseded():
                        return _SUPERSEDED
                    # The download, at the write's rate, and then the write.
                    self._renew_busy_mark(2 * timeout)
                    try:
                        content = get_default_file_store().read_file(
                            file.file_id, use_tempfile=True
                        )
                    except Exception:
                        failure = _NO_DOWNLOAD
                        logger.warning(
                            "sandbox_file_download_failed file=%s try=%d",
                            file.file_id,
                            attempt + 1,
                            exc_info=True,
                        )
                        continue
                # The download, the mark and the cache call can block; check
                # the flags last, just before the write.
                self._renew_busy_mark(timeout)
                if self._superseded():
                    return _SUPERSEDED
                if self._no_response:
                    return _NO_RESPONSE
                if self._pool.stopped.is_set():
                    return _SUPERSEDED
                try:
                    # The write streams the file from its start each time.
                    self._files.write(file.path, content, timeout_seconds=timeout)
                except Exception as error:
                    logger.warning(
                        "sandbox_file_write_failed path=%s try=%d",
                        file.path,
                        attempt + 1,
                        exc_info=True,
                    )
                    if _no_response(error):
                        self._no_response = True
                        return _NO_RESPONSE
                    failure = _NOT_TAKEN
                    continue
                return None
            return failure
        finally:
            if content is not None:
                content.close()


class TurnFileCopies:
    """The chat file copies of one turn of a chat session. Creating it
    starts the copy and returns at once; `status` has its progress."""

    def __init__(
        self,
        ref: HarnessSandboxRef,
        sandbox: HarnessSandbox,
        vm_chat_files: Sequence[VmChatFile],
        *,
        generation: int,
    ) -> None:
        """Copy `vm_chat_files`, the chat's complete set of chat files, into
        `ref`'s session under the turn's copy `generation`. The copy reads
        any file store file that it gets, so callers must authorize every
        `file_id`. Raises SandboxPathError for a path outside the directories
        of chat files."""
        # By path: the file store file.
        self._vm_chat_files: dict[str, str] = {}
        for chat_file in vm_chat_files:
            path = session_relative_path(ref, chat_file.path)
            if posixpath.dirname(path) not in _CHAT_FILE_DIRS:
                raise SandboxPathError(
                    f"{chat_file.path!r} is not in a directory of chat files"
                )
            self._vm_chat_files[path] = chat_file.file_id
        self._ref = ref
        self._sandbox = sandbox
        self._pool = file_copy_pool()
        self._superseded = partial(
            _superseded,
            get_cache_backend(
                tenant_id=ref.tenant_id, operation_timeout_s=COPY_CACHE_SECONDS
            ),
            ref.session_id,
            generation,
        )
        self.status = CopyStatus(self._vm_chat_files)
        intake = [self._intake]
        self._pool.intake.want(ref.sandbox_id, lambda: intake.pop() if intake else None)

    def _written(self, files: Sequence[_File], failure: _Failure | None) -> None:
        if failure is None:
            self.status.update(
                ((file.path, CopyState.DONE, None) for file in files), written=True
            )
        else:
            self.status.update(
                (file.path, CopyState.FAILED, failure.reason) for file in files
            )

    # The intake runs in a VM intake slot.

    def _intake(self) -> None:
        try:
            # Before the session setup, the listing and the size lookups.
            if self._superseded() or self._pool.stopped.is_set():
                self.status.settle(_SUPERSEDED.reason)
            else:
                self._take_in()
        except Exception:
            logger.exception(
                "sandbox_file_copies_failed session=%s", self._ref.session_id
            )
            self.status.settle(_ERROR.reason)

    def _take_in(self) -> None:
        """List the files, classify them, clean up, and queue the writes."""
        ref = self._ref
        try:
            files = self._sandbox.session_files(ref)
        except Exception:
            logger.warning(
                "sandbox_file_copy_no_vm sandbox=%s", ref.sandbox_id, exc_info=True
            )
            self.status.settle(_NO_START.reason)
            return
        listing = _list_chat_dirs(files, ref.sandbox_id)
        if listing is None:
            self.status.settle(_NO_RESPONSE.reason)
            return

        with get_session_with_current_tenant() as db_session:
            sizes: dict[str, int | None] = {
                record.file_id: record.file_size
                for record in get_filerecords_by_file_ids(
                    list(set(self._vm_chat_files.values())), db_session
                )
            }
        store = get_default_file_store()
        # load_settings fills the upload limit.
        max_file_bytes = cast(int, load_settings().user_file_max_upload_size_mb) * _MIB
        budget = MAX_TURN_BYTES
        changes: list[tuple[str, CopyState, str | None]] = []
        writes: list[_File] = []
        for path, file_id in self._vm_chat_files.items():
            size: int | None = None
            if file_id in sizes:
                size = sizes[file_id]
                if size is None:
                    try:
                        size = store.get_file_size(file_id)
                    except FileNotFoundError:
                        pass
                elif size == FILE_SIZE_MISSING_SENTINEL:
                    # The file store found the object gone.
                    size = None
            entry = None if listing.entries is None else listing.entries.get(path)
            state, reason = CopyState.COPYING, None
            not_dir = listing.not_dirs.get(posixpath.dirname(path))
            if not_dir is not None:
                state, reason = CopyState.NOT_COPIED, not_dir
            elif size is None:
                state, reason = (
                    CopyState.NOT_COPIED,
                    "the file is not in the file store",
                )
            elif (
                entry is not None
                and entry.type is FileType.REGULAR
                and entry.size == size
            ):
                state = CopyState.DONE
            elif size > max_file_bytes:
                state = CopyState.NOT_COPIED
                reason = (
                    f"{_size_text(size)}, over the {_size_text(max_file_bytes)} "
                    "limit for one file"
                )
            elif size > MAX_TURN_BYTES:
                state = CopyState.NOT_COPIED
                reason = (
                    f"{_size_text(size)}, over the {_size_text(MAX_TURN_BYTES)} "
                    "copy limit of one turn"
                )
            elif size > budget:
                state = CopyState.NOT_COPIED
                reason = "over the copy limit of one turn; copying next turn"
            else:
                budget -= size
                writes.append(_File(path, file_id, size))
            changes.append((path, state, reason))
        self.status.update(changes)

        stale = (
            []
            if listing.entries is None
            else sorted(
                path
                for path, entry in listing.entries.items()
                if posixpath.dirname(path) in _CLEANED_DIRS
                and entry.type is not FileType.DIRECTORY
                and path not in self._vm_chat_files
            )
        )
        for path in stale:
            # The cache call can block; check the stop after it.
            if self._superseded() or self._pool.stopped.is_set():
                self.status.settle(_SUPERSEDED.reason)
                return
            try:
                files.delete(path)
            except Exception as error:
                logger.warning(
                    "sandbox_file_delete_failed sandbox=%s path=%s",
                    ref.sandbox_id,
                    path,
                    exc_info=True,
                )
                if _no_response(error):
                    self.status.settle(_NO_RESPONSE.reason)
                    return
        if writes:
            _Writes(ref, self._pool, files, writes, self._superseded, self._written)


def _evictions(
    held: Mapping[str, FileEntry],
    writing: Mapping[str, int],
    writes: Sequence[_File],
    protected: set[str],
) -> tuple[list[str], list[_File]]:
    """The search files to delete, oldest first, and the writes that go
    ahead, so that attachments/search/ holds at most MAX_CHAT_SEARCH_BYTES.
    `held`: the listed entries of the folder; `writing`: by path, the sizes of
    the turn's earlier writes that are queued or running, which the listing
    may not show yet. A `protected` path (the turn's offers) stays. The writes
    that fit next to the protected files and earlier writes go ahead, in
    order; deletes make room only for them, so no write means no delete. A
    write can fail and keep what is at its path, so until it lands its path
    counts the larger of its current bytes and the write's."""
    # By path: the most bytes that can stay.
    kept = {path: entry.size for path, entry in held.items() if path in protected}
    for path, size in writing.items():
        kept[path] = max(size, held[path].size if path in held else 0)
    room = MAX_CHAT_SEARCH_BYTES - sum(kept.values())
    fitting: list[_File] = []
    for write in writes:
        listed = held[write.path].size if write.path in held else 0
        charge = max(write.size, kept.get(write.path, listed))
        growth = charge - kept.get(write.path, 0)
        if growth <= room:
            fitting.append(write)
            room -= growth
            kept[write.path] = charge
    if not fitting:
        return [], []
    others = [entry for path, entry in held.items() if path not in kept]
    excess = sum(entry.size for entry in others) - room
    evicted: list[str] = []
    for entry in sorted(others, key=lambda entry: entry.modified_at or _UNKNOWN_AGE):
        if excess <= 0:
            break
        evicted.append(entry.path)
        excess -= entry.size
    return evicted, fitting


class CopyTarget(NamedTuple):
    """Where a turn copies: the chat's session in the user's sandbox, and
    the turn's copy generation."""

    ref: HarnessSandboxRef
    sandbox: HarnessSandbox
    generation: int


class _SearchFile(NamedTuple):
    file_id: str
    path: str
    # The file record's size; None: not recorded.
    size: int | None
    document_ids: tuple[str, ...]


class TurnSearchFiles:
    """The search result files of one turn of a chat, which the root agent
    and its subagents share. `offer` runs on a search's thread and only
    counts and queues; the access check, the listing, the eviction and the
    writes run in the pod's copy slots."""

    def __init__(self, target: Callable[[], CopyTarget], user_id: UUID) -> None:
        """`target`: the turn's copy target, which the first offer of new
        files resolves. `user_id`: the chat's user, whose access the copy
        checks."""
        self._target = target
        self._user_id = user_id
        self._lock = threading.Lock()
        # By file store ID: the files that the turn offered.
        self._offered: dict[str, _SearchFile] = {}
        # By file store ID: the bytes that each offered file holds of the
        # turn's budget; MAX_TURN_SEARCH_FILES counts the entries.
        self._shares: dict[str, int] = {}
        self._bytes = 0
        # Offered files that no intake took yet, and whether an intake is
        # queued or runs; it takes them all.
        self._waiting: list[_SearchFile] = []
        self._intake_queued = False
        # By path: the sizes of the turn's writes that are queued or running.
        self._writing: dict[str, int] = {}

    def offer(self, files: Mapping[str, SearchResultFile]) -> dict[str, str]:
        """Offer the files of a search's shown results, by file store ID. The
        path, relative to the working directory, of each file that the turn
        copies: a file that it offered before, and a new one while the turn's
        budget lasts. A new file's copy starts in the background."""
        with self._lock:
            fresh = any(file_id not in self._offered for file_id in files)
        target: CopyTarget | None = None
        if fresh:
            try:
                target = self._target()
            except Exception:
                logger.exception("sandbox_search_files_no_sandbox")
        paths: dict[str, str] = {}
        new: list[_SearchFile] = []
        again = over_budget = 0
        with self._lock:
            for file_id, file in files.items():
                known = self._offered.get(file_id)
                if known is not None:
                    paths[file_id] = known.path
                    again += 1
                    continue
                if target is None:
                    continue
                if (
                    len(self._shares) >= MAX_TURN_SEARCH_FILES
                    or self._bytes + (file.size or 0) > MAX_TURN_SEARCH_BYTES
                ):
                    over_budget += 1
                    continue
                self._shares[file_id] = file.size or 0
                self._bytes += file.size or 0
                offered = _SearchFile(
                    file_id,
                    f"{SEARCH_FILES_DIR}/{search_file_name(file_id, file.title)}",
                    file.size,
                    file.document_ids,
                )
                self._offered[file_id] = offered
                paths[file_id] = offered.path
                new.append(offered)
            self._waiting.extend(new)
            start = bool(new) and not self._intake_queued
            if start:
                self._intake_queued = True
        if files:
            logger.info(
                "sandbox_search_files_offered new=%d again=%d over_budget=%d",
                len(new),
                again,
                over_budget,
            )
        if start and target is not None:
            self._start_intake(target)
        return paths

    def _start_intake(self, target: CopyTarget) -> None:
        pool = file_copy_pool()
        intake = [partial(self._intake, target, pool)]
        pool.intake.want(
            target.ref.sandbox_id, lambda: intake.pop() if intake else None
        )

    # The intake runs in a VM intake slot.

    def _intake(self, target: CopyTarget, pool: FileCopyPool) -> None:
        """Take in the waiting files: check access, list attachments/search/,
        evict, and queue the writes of the files that are not in place. A file
        that the turn does not write gives its budget back, also when the
        intake fails. Files that an offer queues meanwhile get the next
        intake."""
        superseded = partial(
            _superseded,
            get_cache_backend(
                tenant_id=target.ref.tenant_id, operation_timeout_s=COPY_CACHE_SECONDS
            ),
            target.ref.session_id,
            target.generation,
        )
        with self._lock:
            batch, self._waiting = self._waiting, []
        released = {file.file_id for file in batch}
        try:
            if superseded() or pool.stopped.is_set():
                logger.info(
                    "sandbox_search_files_superseded session=%s files=%d",
                    target.ref.session_id,
                    len(batch),
                )
                return
            with get_session_with_current_tenant() as db_session:
                user = fetch_user_by_id(db_session, self._user_id)
                # A file is copied when a document that the user can
                # read still has it.
                readable = (
                    set()
                    if user is None
                    else {
                        document.file_id
                        for document in get_accessible_documents_by_ids(
                            db_session,
                            list({d for file in batch for d in file.document_ids}),
                            user.email,
                            get_user_external_group_ids(db_session, user),
                            user_id=user.id,
                            prior_emails=user.prior_emails,
                        )
                    }
                )
            store = get_default_file_store()
            sized: list[tuple[_SearchFile, int]] = []
            for file in batch:
                if file.file_id not in readable:
                    continue
                size = file.size
                if size is None:
                    try:
                        size = store.get_file_size(file.file_id)
                    except Exception:
                        logger.warning(
                            "sandbox_search_file_size_failed file=%s",
                            file.file_id,
                            exc_info=True,
                        )
                    with self._lock:
                        # The record had no size: the limits apply to
                        # the real one.
                        if (
                            size is not None
                            and size <= SEARCH_FILE_MAX_BYTES
                            and self._bytes + size <= MAX_TURN_SEARCH_BYTES
                        ):
                            self._shares[file.file_id] = size
                            self._bytes += size
                        else:
                            size = None
                if size is not None:
                    sized.append((file, size))
            no_access = sum(file.file_id not in readable for file in batch)
            not_copied = len(batch) - no_access - len(sized)
            if not sized:
                logger.info(
                    "sandbox_search_files_intake session=%s in_place=0 "
                    "copying=0 not_copied=%d no_access=%d evicted=0",
                    target.ref.session_id,
                    not_copied,
                    no_access,
                )
                return
            files = target.sandbox.session_files(target.ref)
            # Before the listing: a write that ends while it runs is counted
            # here or listed there.
            with self._lock:
                protected = {file.path for file in self._offered.values()}
                writing = dict(self._writing)
            # None: unknown, so every file is written and none deleted.
            listing: FileListing | None = None
            try:
                listing = files.list_files(SEARCH_FILES_DIR, max_entries=_MAX_LISTED)
            except Exception as error:
                logger.warning(
                    "sandbox_file_listing_failed sandbox=%s path=%s",
                    target.ref.sandbox_id,
                    SEARCH_FILES_DIR,
                    exc_info=True,
                )
                if _no_response(error):
                    return
            held = {
                entry.path: entry
                for entry in (listing.entries if listing else [])
                if entry.type is not FileType.DIRECTORY
            }
            writes = [
                _File(file.path, file.file_id, size)
                for file, size in sized
                if not (
                    file.path in held
                    and held[file.path].type is FileType.REGULAR
                    and held[file.path].size == size
                )
            ]
            in_place = len(sized) - len(writes)
            evicted: list[str] = []
            # A truncated or failed listing deletes nothing.
            if listing is not None and not listing.truncated:
                evicted, fitting = _evictions(held, writing, writes, protected)
                not_copied += len(writes) - len(fitting)
                writes = fitting
            for path in evicted:
                # The cache call can block; check the stop after it.
                if superseded() or pool.stopped.is_set():
                    writes = []
                    break
                try:
                    files.delete(path)
                except Exception:
                    logger.warning(
                        "sandbox_file_delete_failed sandbox=%s path=%s",
                        target.ref.sandbox_id,
                        path,
                        exc_info=True,
                    )
                    # The writes fit only if every eviction deletes its file.
                    return
            logger.info(
                "sandbox_search_files_intake session=%s in_place=%d "
                "copying=%d not_copied=%d no_access=%d evicted=%d",
                target.ref.session_id,
                in_place,
                len(writes),
                not_copied,
                no_access,
                len(evicted),
            )
            if writes:
                with self._lock:
                    self._writing.update((write.path, write.size) for write in writes)
                released -= {write.file_id for write in writes}
                _Writes(target.ref, pool, files, writes, superseded, self._written)
        except Exception:
            logger.exception(
                "sandbox_search_files_failed session=%s", target.ref.session_id
            )
        finally:
            with self._lock:
                for file_id in released:
                    self._bytes -= self._shares.pop(file_id, 0)
                restart = bool(self._waiting) and not pool.stopped.is_set()
                self._intake_queued = restart
            if restart:
                self._start_intake(target)

    def _written(self, files: Sequence[_File], failure: _Failure | None) -> None:
        with self._lock:
            for file in files:
                self._writing.pop(file.path, None)
                # A file that the turn did not write gives its budget back.
                if failure is not None:
                    self._bytes -= self._shares.pop(file.file_id, 0)
        for file in files:
            if failure is None:
                logger.info("sandbox_search_file_copied path=%s", file.path)
            else:
                logger.warning(
                    "sandbox_search_file_not_copied path=%s reason=%r",
                    file.path,
                    failure.reason,
                )
