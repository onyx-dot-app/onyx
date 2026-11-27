"""The sandbox interface for an agent harness that runs outside the sandbox.

The harness (agent loop, LLM calls, event stream) runs in an Onyx process and
calls into the sandbox only through `HarnessSandbox`. One sandbox serves one
user; each chat session has its own directory in it
(`SESSION_WORKSPACE_ROOT/<session_id>`), which is the default working
directory. Commands are not confined to that directory.

Every call blocks the calling thread (agent runtime tools run in threads).
`exec_command` and `write_stdin` stream output as it arrives: iterate their
events and read the last one, an `ExecCommandResult`, or call
`collect_exec_result`.

Exec contract (`exec_command` / `write_stdin`):
- `exec_command` starts a command and waits up to `yield_time_ms`. If the
  command ended, the result has its exit code. Otherwise it has a
  `session_id` for `write_stdin`.
- `write_stdin` with no chars polls for new output. Chars go to the
  command's stdin. "\\x03" interrupts the command.
- Output of one call keeps at most `EXEC_CALL_OUTPUT_MAX_BYTES`: the
  result has its head and tail, and the characters dropped between them.
  The caller cuts what its reader gets, and stops forwarding live output
  where its cut would.
- Exec session IDs stay valid across turns and API pods until the command's
  record is evicted, or the sandbox stops (idle stop, restore): then the call
  raises `ExecSessionEndedError`.
- A cancel of the current signal (`onyx.llm.cancellation`: a Stop, or the
  end of the code mode cell that made the call) ends the wait at once and
  kills the command (SIGKILL), however the wait ends; the call raises
  `AgentCancelled`. A call cancelled before it starts its command, or writes
  its input, does neither.
- Each command has a command ID, which its app requests carry to the egress
  proxy. With a `CommandHold`, the call calls `begin` with the ID before it
  starts the command or writes to it, and does not yield while `holds` is
  true (a request of the command waits for the user's approval).
"""

import abc
import hashlib
import os
import posixpath
import string
import unicodedata
from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from typing import IO, Protocol
from uuid import UUID

from pydantic import JsonValue

from onyx.file_processing.file_types import (
    OFFICE_MIME_TYPES_BY_EXTENSION,
    PRESENTATION_MIME_TYPE,
    WORD_PROCESSING_MIME_TYPE,
)
from onyx.microvm.browser_protocol import BrowserFrame
from onyx.microvm.models import FileListing
from onyx.server.features.build.sandbox.models import (
    ExecCommandResult,
    ExecEvent,
    FileSet,
    HarnessSandboxRef,
    RenderedPreview,
    RenderFileBytes,
    RenderSessionFile,
    SandboxPathInfo,
    session_workspace,
)

# The directory of the chat's files in its session directory: copies of file
# store files (tools/tool_implementations/sandbox/file_copies.py).
CHAT_FILES_DIR = "attachments"
# Uploads for the chat browser's file chooser, in the session directory.
BROWSER_UPLOADS_DIR = "browser-uploads"
# The chat's project files and its agent's files, in CHAT_FILES_DIR.
PROJECT_FILES_DIR = f"{CHAT_FILES_DIR}/project"
AGENT_FILES_DIR = f"{CHAT_FILES_DIR}/agent"
# Published files that the model copied from the user's chats
# (library_prepare_materialize), in CHAT_FILES_DIR. The chat file copies never
# clean it up.
ARTIFACT_FILES_DIR = f"{CHAT_FILES_DIR}/artifacts"
# The original files of the chat's search results, in CHAT_FILES_DIR.
SEARCH_FILES_DIR = f"{CHAT_FILES_DIR}/search"
# The longest file name, in UTF-8 bytes, of the VM's file system.
_MAX_NAME_BYTES = 255
# The longest file name, in characters, that the Python tool stages
# (CODE_INTERPRETER_FILENAME_MAX_LENGTH).
_MAX_NAME_CHARS = 200
# Characters that chat file names never keep: the ones that a shell reads,
# also inside double quotes (the tools tell the model to use the paths in
# commands), and ":", which the Python tool replaces when it stages a file.
_REPLACED_CHARACTERS = frozenset("$`'\"\\;&|()<>!*?[]{}~#:")

# Parent of the files that Onyx writes outside every session directory (for
# example large tool results). No session save keeps them; they go when the
# sandbox stops.
ONYX_VM_FILES_ROOT = "/tmp/onyx"  # noqa: S108 - a path in the sandbox VM.
# Large tool results, in one directory for each chat session
# (tools/tool_implementations/sandbox/spill.py). The purge rule: a session's
# purge deletes its directory whenever the VM runs, also for a session that
# never used the sandbox otherwise, and a write that lands after the purge
# deletes the directory again and raises HarnessSandboxError.
TOOL_RESULTS_ROOT = f"{ONYX_VM_FILES_ROOT}/tool-results"

# render_preview: the longer side, in pixels, of the JPEG of a file's first
# page, and the root of each render's own scratch directory.
RENDER_PREVIEW_SIZE_PX = 640
RENDER_PREVIEW_ROOT = f"{ONYX_VM_FILES_ROOT}/renders"
# The Office types that LibreOffice converts to a PDF, which the render
# returns. The web's list is OFFICE_MIME_TYPES in
# web/src/lib/filePreview/format.ts.
RENDER_PREVIEW_PDF_MIME_TYPES = frozenset(
    {PRESENTATION_MIME_TYPE, WORD_PROCESSING_MIME_TYPE}
)
# The suffixes it draws: a PDF directly, the Office types above through
# LibreOffice.
RENDER_PREVIEW_SUFFIXES = frozenset(
    {
        ".pdf",
        *(
            suffix
            for suffix, mime_type in OFFICE_MIME_TYPES_BY_EXTENSION.items()
            if mime_type in RENDER_PREVIEW_PDF_MIME_TYPES
        ),
    }
)
# Largest file that callers render, and largest JPEG and PDF that it reads
# back. The PDF limit matches PREVIEW_BYTE_LIMITS.pdf in
# web/src/lib/filePreview/loadChatFilePreview.ts.
RENDER_PREVIEW_MAX_INPUT_BYTES = 20 << 20
RENDER_PREVIEW_MAX_OUTPUT_BYTES = 4 << 20
RENDER_PREVIEW_MAX_PDF_BYTES = 100 << 20
# The renders of one publish call, or the render of one preview request, end
# by this budget, which starts once the sandbox's VM runs. A publish file
# after it publishes without a thumbnail or a PDF.
RENDER_PREVIEW_BUDGET_SECONDS = 30.0

# Most exec session records per sandbox; the least recently used goes
# first. The guest daemon caps the running commands.
MAX_EXEC_SESSIONS_PER_SANDBOX = 64

# The env of every command, so that tools write plain, unpaged UTF-8 text.
EXEC_DEFAULT_ENV: dict[str, str] = {
    "NO_COLOR": "1",
    "TERM": "dumb",
    "PAGER": "cat",
    "GIT_PAGER": "cat",
    "GH_PAGER": "cat",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
}

INTERRUPT_CHAR = "\x03"

# An open live view keeps the sandbox busy this long after each renewal.
BROWSER_VIEW_LEASE_SECONDS = 60.0


def _strip_trailing_spaces_and_dots(text: str) -> str:
    """`text` without the whitespace and dots at its end, which the Python
    tool strips when it stages a file. A chat file name starts with a hex
    digit or `-`, so the Python tool's strip of the start changes nothing."""
    end = len(text)
    while end and (text[end - 1].isspace() or text[end - 1] == "."):
        end -= 1
    return text[:end]


def safe_file_name(names: Sequence[str], *, prefix: str = "", suffix: str = "") -> str:
    """`prefix` and the first of `names` that keeps a name after this rule:
    the last part of the name, NFC, with control characters and
    _REPLACED_CHARACTERS replaced by `_`, and without trailing whitespace or
    dots, with `suffix` after its stem. Its stem is cut so that the whole
    name fits _MAX_NAME_CHARS and _MAX_NAME_BYTES; it keeps its extension
    unless the extension takes more than half of either. `prefix` + "file"
    when none keeps a name. The Python tool stages each such name
    unchanged."""
    for raw in names:
        base = _strip_trailing_spaces_and_dots(
            "".join(
                "_"
                if char in _REPLACED_CHARACTERS or unicodedata.category(char) == "Cc"
                else char
                for char in posixpath.basename(
                    unicodedata.normalize("NFC", raw).replace("\\", "/")
                )
            )
        )
        stem, extension = os.path.splitext(base)
        if (
            len(extension) > _MAX_NAME_CHARS // 2
            or len(extension.encode()) > _MAX_NAME_BYTES // 2
        ):
            stem, extension = base, ""
        kept = f"{prefix}{suffix}{extension}"
        stem = stem.encode()[: _MAX_NAME_BYTES - len(kept.encode())].decode(
            errors="ignore"
        )[: _MAX_NAME_CHARS - len(kept)]
        # A cut stem without an extension can end in whitespace or dots.
        tail = _strip_trailing_spaces_and_dots(f"{stem}{suffix}{extension}")
        if tail:
            return f"{prefix}{tail}"
    return f"{prefix}file"


def chat_file_name(file_id: str, name: str | None) -> str:
    """The name of a file store file in a directory of chat files, a function
    of the file alone, so it never names another file: `<the first 8 hex
    digits of the file ID>-<name>`, by safe_file_name of `name`, else of the
    file ID."""
    return safe_file_name(
        (name or "", file_id),
        prefix="".join(c for c in file_id if c in string.hexdigits)[:8].lower() + "-",
    )


def search_file_name(file_id: str, title: str) -> str:
    """The name of a search result's file in the sandbox: `chat_file_name`
    with 8 hex digits of the file ID's SHA-256, since connector file IDs are
    arbitrary strings. A title is not a path, so its `/` and `\\` become `_`
    and it stays whole. The search result, the Python staging and the VM copy
    use it, so they name a file alike."""
    return chat_file_name(
        hashlib.sha256(file_id.encode()).hexdigest(),
        title.replace("/", "_").replace("\\", "_"),
    )


def session_tool_results(session_id: UUID) -> str:
    return f"{TOOL_RESULTS_ROOT}/{session_id}"


def collect_exec_result(events: Iterator[ExecEvent]) -> ExecCommandResult:
    """Drain an exec stream and return its result. Reads the stream to its
    end, so the implementation releases what it holds."""
    result: ExecCommandResult | None = None
    for event in events:
        if isinstance(event, ExecCommandResult):
            result = event
    if result is None:
        raise RuntimeError("The exec stream ended without a result")
    return result


class HarnessSandboxError(Exception):
    """A sandbox call failed in a way the model can read and act on."""


class ExecSessionNotFoundError(HarnessSandboxError):
    def __init__(self, exec_session_id: str) -> None:
        super().__init__(
            f"Unknown exec session {exec_session_id!r}: it was never started in "
            "this chat session, or it was evicted"
        )


class ExecSessionEndedError(HarnessSandboxError):
    def __init__(self, exec_session_id: str) -> None:
        super().__init__(
            f"Exec session {exec_session_id!r} ended: the sandbox restarted, "
            "and processes do not survive a restart. Run the command again."
        )


class ExecCapReachedError(HarnessSandboxError):
    def __init__(self) -> None:
        super().__init__(
            "Too many commands run in this sandbox. Stop one (write_stdin "
            'with "\\x03") or wait for one to end, then run the command again.'
        )


class SandboxPathError(HarnessSandboxError):
    """The path is outside the session directory."""


class SandboxFileTooLargeError(HarnessSandboxError):
    pass


class SandboxFileNotFoundError(HarnessSandboxError):
    def __init__(self, path: str) -> None:
        super().__init__(f"{path!r} does not exist")


class RenderBudgetSpentError(TimeoutError):
    """A render ran out of its budget, which starts once the VM runs, so a
    retry of the file most likely runs out too."""


def session_relative_path(session_id: UUID, path: str) -> str:
    """The session-relative form of `path` ("" = the session directory).
    Accepts a relative path or an absolute path in the session directory."""
    root = session_workspace(session_id)
    normalized = posixpath.normpath(path or ".")
    if posixpath.isabs(normalized):
        if normalized == root:
            return ""
        if not normalized.startswith(root + "/"):
            raise SandboxPathError(
                f"{path!r} is outside the working directory {root}; use "
                "a shell command elsewhere"
            )
        return normalized[len(root) + 1 :]
    if normalized == ".." or normalized.startswith("../"):
        raise SandboxPathError(f"{path!r} leaves the working directory")
    return "" if normalized == "." else normalized


def onyx_vm_path(path: str) -> str | None:
    """`path` normalized when it is an absolute path under
    ONYX_VM_FILES_ROOT, the only place outside the session directories that
    file calls reach; else None."""
    normalized = posixpath.normpath(path)
    return normalized if normalized.startswith(ONYX_VM_FILES_ROOT + "/") else None


class SessionFiles(abc.ABC):
    """File calls in one chat session's directory on one running VM
    instance. The VM is placed and the session set up once, so each call is
    one guest daemon call; a call fails once the instance stopped. Paths are
    relative to the session directory. Safe to call from several threads."""

    @abc.abstractmethod
    def write(
        self, path: str, data: IO[bytes], *, timeout_seconds: float, overwrite: bool
    ) -> None:
        """write_file, mode 0644, on this instance. A write makes a missing
        session directory; a write that finds the session purged deletes
        that directory again and raises HarnessSandboxError. Without
        `overwrite`, a file at the path raises SandboxDaemonError
        FILE_EXISTS and stays."""

    @abc.abstractmethod
    def delete(self, path: str) -> bool:
        """Delete a file or a link (not a directory) inside the session
        directory; a link is never followed. False when nothing was at the
        path. Never sets the session up again, so after a purge it deletes
        nothing."""

    @abc.abstractmethod
    def list_files(
        self, directory: str, *, max_entries: int, include_hidden: bool = False
    ) -> FileListing:
        """The entries directly in `directory`, not those of its
        subdirectories; none for a missing directory. Hidden entries, such
        as the daemon's temporary file of a write in progress, only with
        `include_hidden`."""

    @abc.abstractmethod
    def mark_busy(self, seconds: float | None) -> None:
        """Keep the sandbox busy (no idle stop) for `seconds` from now, or
        end that (None). Each SessionFiles has one such mark."""


class BrowserStream(abc.ABC):
    """A live view connection to the sandbox's browser service, in the
    service's frames (`onyx.microvm.browser_protocol`). The caller sends the
    view hello first."""

    @abc.abstractmethod
    async def send(self, frame: BrowserFrame) -> None:
        pass

    @abc.abstractmethod
    async def receive(self) -> BrowserFrame | None:
        """The next frame; None once the service closed the connection."""

    @abc.abstractmethod
    async def aclose(self) -> None:
        pass


class CommandHold(Protocol):
    """A call's link to the proxy approvals of the command it waits on
    (`tools/tool_implementations/sandbox/command_approvals.py`)."""

    def begin(self, command_id: UUID) -> None:
        """The call waits on the command from now on."""

    def holds(self) -> bool:
        """A request of the command waits for the user's decision."""


class HarnessSandbox(abc.ABC):
    """What the harness calls. All methods block; see the module docstring."""

    @abc.abstractmethod
    def ensure_running(self, ref: HarnessSandboxRef) -> None:
        """Start the sandbox if needed and return when the guest is
        initialized. Every other call does this first."""

    @abc.abstractmethod
    def install_skill(
        self,
        ref: HarnessSandboxRef,
        name: str,
        version: str,
        files: FileSet,
    ) -> bool:
        """Put the skill's files (`<name>/<path>` to bytes) in the read-only
        folder `chat_skill_folder(name)`, unless the VM already has
        `version`. True when it copied."""

    @abc.abstractmethod
    def exec_command(
        self,
        ref: HarnessSandboxRef,
        cmd: str,
        *,
        workdir: str | None = None,
        yield_time_ms: int | None = None,
        hold: CommandHold | None = None,
    ) -> Generator[ExecEvent]:
        """Run `cmd` with bash in `workdir` (default: the session
        directory)."""

    @abc.abstractmethod
    def write_stdin(
        self,
        ref: HarnessSandboxRef,
        exec_session_id: str,
        chars: str = "",
        *,
        yield_time_ms: int | None = None,
        hold: CommandHold | None = None,
    ) -> Generator[ExecEvent]:
        """Write to a running command, or poll it with empty chars."""

    # Files: only what exec_command cannot do well. A publish needs exact
    # bytes (exec output is text), and apply_patch needs exact writes of any
    # content (no shell quoting) and typed path facts. Paths are relative to
    # the session directory, or absolute inside it; read_file, write_file,
    # delete_file and list_files also take an absolute path under
    # ONYX_VM_FILES_ROOT (onyx_vm_path), which starts the sandbox but sets up
    # no session. Write data is bytes, a seekable binary file (for example a
    # file store temp file) that is streamed whole, from its start, in
    # chunks, or the bytes in parts, which are sent without joining them.

    @abc.abstractmethod
    def read_file(self, ref: HarnessSandboxRef, path: str, *, max_bytes: int) -> bytes:
        """Read a regular file in the session directory, or under
        ONYX_VM_FILES_ROOT; links are followed only inside that root. Raises
        SandboxPathError for another path, SandboxFileNotFoundError for a
        missing file, SandboxFileTooLargeError over max_bytes, and
        HarnessSandboxError for a path that is not a regular file or that a
        link takes out of its root."""

    @abc.abstractmethod
    def stream_file(
        self, ref: HarnessSandboxRef, path: str, *, max_bytes: int
    ) -> Iterator[bytes]:
        """read_file, as chunks that are not kept in memory. Raises the
        same errors before the first chunk, and SandboxFileTooLargeError
        while it reads a file that grows over max_bytes. Dropping the
        iterator unread cancels the transfer."""

    @abc.abstractmethod
    def write_file(
        self,
        ref: HarnessSandboxRef,
        path: str,
        data: bytes | IO[bytes] | list[bytes],
        *,
        mode: int = 0o644,
        timeout_seconds: float | None = None,
    ) -> None:
        """Atomic replace (a link is replaced, not followed); creates parent
        directories. `mode`: permission bits. The transfer ends by
        `timeout_seconds`, if set. A write under TOOL_RESULTS_ROOT follows
        its purge rule."""

    @abc.abstractmethod
    def delete_listed_files(
        self,
        ref: HarnessSandboxRef,
        directory: str,
        select: Callable[[FileListing], Iterable[str]],
        *,
        max_entries: int,
    ) -> None:
        """List the entries below a directory, at any depth, with their size
        and modification time, then delete the files that `select` picks from
        the listing, on one lookup of the VM. A selected path that is not in
        the listing is ignored. The listing has at most
        `max_entries` (the guest daemon allows 100,000), and `truncated` when
        more exist. Paths under ONYX_VM_FILES_ROOT are absolute, others
        session-relative. A missing directory deletes nothing."""

    @abc.abstractmethod
    def stat_files(
        self, ref: HarnessSandboxRef, paths: Sequence[str]
    ) -> list[SandboxPathInfo]:
        """The facts of each path, in order: the entry itself, and what it
        names through the links inside the session directory. A missing path,
        a link out of the session and a link loop are reported, not raised."""

    @abc.abstractmethod
    def delete_file(self, ref: HarnessSandboxRef, path: str) -> bool:
        """Delete a file or a link (not a directory). False when nothing was
        at the path."""

    @abc.abstractmethod
    def session_files(self, ref: HarnessSandboxRef) -> SessionFiles:
        """Start the sandbox if needed, set up the chat session's directory,
        and return file calls bound to the running VM instance. Raises
        HarnessSandboxError for a purged session."""

    @abc.abstractmethod
    def render_preview(
        self,
        source: RenderSessionFile | RenderFileBytes,
        *,
        first_page: bool,
        budget_seconds: float,
    ) -> RenderedPreview | None:
        """Render a file with a RENDER_PREVIEW_SUFFIXES suffix, up to
        RENDER_PREVIEW_MAX_INPUT_BYTES, with the VM's LibreOffice and
        poppler: the PDF that LibreOffice makes of an Office file, and with
        `first_page`, a JPEG of the first page, RENDER_PREVIEW_SIZE_PX on its
        longer side. The callers ask for the first page or pass an Office
        file. The budget starts once the sandbox's VM runs.

        Returns None, and logs why, when the converter rejects the file: a
        step fails, or LibreOffice makes no PDF. An output that is too large,
        or a first page that poppler cannot draw from a converted PDF, is
        None in the result. Raises RenderBudgetSpentError when the budget
        runs out, and the sandbox's own errors when the sandbox cannot be
        reached, after which a retry can succeed. A cancel of the current
        signal kills the render and raises AgentCancelled."""

    @abc.abstractmethod
    def touch(self, ref: HarnessSandboxRef) -> None:
        """Record activity for the idle stop. Never starts the sandbox."""

    @abc.abstractmethod
    def begin_turn(self, ref: HarnessSandboxRef) -> None:
        """Mark a turn in progress (the sandbox is busy). Call again to
        renew; the mark expires on its own if end_turn never runs."""

    @abc.abstractmethod
    def end_turn(self, ref: HarnessSandboxRef) -> None:
        pass

    @abc.abstractmethod
    def set_approval_parked(self, ref: HarnessSandboxRef, parked: bool) -> None:
        """Mark or clear an approval that waits for the user (busy)."""

    @abc.abstractmethod
    def is_busy(self, *, tenant_id: str, sandbox_id: UUID) -> bool:
        """True while a command runs, a turn is in progress, a copy runs, an
        approval waits, or a live view is open. Never starts the sandbox."""

    # Browser. Each call names the chat by `ref.session_id`; the service
    # shows a chat only its own tabs.

    @abc.abstractmethod
    def browser_call(
        self,
        ref: HarnessSandboxRef,
        method: str,
        params: dict[str, JsonValue],
        *,
        timeout_seconds: float,
    ) -> dict[str, JsonValue]:
        """One agent call to the browser service; returns its result. Starts
        the sandbox and the browser if needed; that startup has its own
        limits and does not count against `timeout_seconds`. Raises
        HarnessSandboxError when the service refuses the call or does not
        answer within `timeout_seconds`. A cancel of the
        current signal ends the call and raises AgentCancelled."""

    @abc.abstractmethod
    async def open_browser_stream(self, ref: HarnessSandboxRef) -> BrowserStream:
        """Start the sandbox and the browser if needed, and open a live view
        connection. Raises when the browser cannot be reached."""

    @abc.abstractmethod
    def renew_browser_view(self, ref: HarnessSandboxRef) -> None:
        """Keep the sandbox busy for BROWSER_VIEW_LEASE_SECONDS more: a live
        view of the chat is open. Never starts the sandbox."""

    @abc.abstractmethod
    def clear_browser_data(self, ref: HarnessSandboxRef) -> None:
        """Stop the browser and delete its profile (sign-ins, cookies,
        storage) and the profile's save. Never starts the sandbox."""
