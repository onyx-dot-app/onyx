"""Tools that run commands, edit files and publish files in the user's
private sandbox (`server/features/build/sandbox/harness_base.py:HarnessSandbox`).
`sandbox_tools_for_model` gives the set that a turn's model gets.

They have no tool row: a chat turn builds them when it offers the sandbox
(`chat/execution.py:create_chat_agent`), and they share a `SandboxTurn`. The
sandbox is the isolation, so calls need no approval.
"""

import posixpath
import time
from collections.abc import Callable, Generator, Hashable, Iterator, Sequence
from contextlib import closing, contextmanager
from functools import partial
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.tools import (
    ToolExecutionMode,
    ToolInvocation,
    ToolProgress,
)
from onyx.db.chat import delete_unpublished_chat_artifacts, save_chat_artifact
from onyx.file_store.utils import chat_output_file_type
from onyx.llm.model_capabilities import is_claude_model
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.prompts.sandbox_tools import (
    APPLY_PATCH_DESCRIPTION,
    APPLY_PATCH_USE,
    ATTACHMENTS_NOT_SAVED_NOTE,
    CHAT_FILES_LAYOUT,
    EDIT_DESCRIPTION,
    EDIT_USE,
    EXEC_COMMAND_DESCRIPTION,
    EXEC_COMMAND_USE,
    PUBLISH_FILES_DESCRIPTION,
    SANDBOX_CODE_MODE_NOTE,
    SANDBOX_GUIDANCE,
    WRITE_DESCRIPTION,
    WRITE_STDIN_DESCRIPTION,
    WRITE_STDIN_USE,
    WRITE_USE,
)
from onyx.server.features.build.sandbox.harness_base import (
    CHAT_FILES_DIR,
    RENDER_FIRST_PAGE_BUDGET_SECONDS,
    RENDER_FIRST_PAGE_MAX_INPUT_BYTES,
    RENDER_FIRST_PAGE_SUFFIXES,
    HarnessSandbox,
    HarnessSandboxError,
    SandboxPathError,
    session_relative_path,
)
from onyx.server.features.build.sandbox.models import (
    CHAT_SKILLS_PATH,
    ExecCommandResult,
    ExecEvent,
    HarnessSandboxRef,
    SandboxPathInfo,
    session_workspace,
)
from onyx.tools.constants import LOAD_SKILL_TOOL_NAME
from onyx.tools.interface import (
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import (
    CodeModeExposure,
    CodeModeResultKind,
    CodeModeResultSpec,
    CustomToolCallSummary,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.sandbox.models import (
    PUBLISH_FILES_MAX_BYTES,
    PUBLISH_FILES_MAX_TITLE_CHARS,
    ApplyPatchArguments,
    ApplyPatchFileChange,
    ApplyPatchResult,
    EditArguments,
    ExecCommandArguments,
    ExecCommandOutput,
    FileToolName,
    PublishedFile,
    PublishedFiles,
    PublishFilesArguments,
    SandboxExecResult,
    WriteArguments,
    WriteStdinArguments,
)
from onyx.tools.tool_implementations.sandbox.patch import (
    APPLY_PATCH_MAX_STAGED_BYTES,
    FILE_TOOL_MAX_FILE_BYTES,
    FILE_TOOL_MAX_INPUT_BYTES,
    AddFile,
    DeleteFile,
    PatchError,
    PatchHunk,
    SeekBudget,
    UpdateFile,
    edit_text,
    ensure_unique_targets,
    parse_patch,
    summarize,
    update_contents,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn, SkillLoadError
from onyx.tools.tool_implementations.utils import cut_middle, output_chars
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_string

logger = setup_logger()

# The saved result of a call that a lost server left running; it is not run
# again because its command or edit may have taken effect.
INTERRUPTED_SANDBOX_RESULT = ToolResult(
    content="The call was interrupted before it returned and was not run again. "
    "Check the sandbox state with exec_command before you retry.",
    is_error=True,
)

_CHANGES: dict[type[PatchHunk], Literal["add", "update", "delete"]] = {
    AddFile: "add",
    UpdateFile: "update",
    DeleteFile: "delete",
}

_EXEC_RESULT = CodeModeResultSpec(
    kind=CodeModeResultKind.DETAILS, model=ExecCommandOutput
)
_FILE_TOOL_RESULT = CodeModeResultSpec(
    kind=CodeModeResultKind.TEXT, annotation="str", returns="The result message."
)


@contextmanager
def _sandbox_errors_as_tool_errors() -> Iterator[None]:
    """Sandbox errors that the model can act on become tool errors with their
    message."""
    try:
        yield
    except HarnessSandboxError as error:
        raise ToolCallException(str(error), str(error)) from error


def _exec_tool_result(
    events: Generator[ExecEvent], invocation: ToolInvocation, max_chars: int
) -> ToolResult:
    """Stream the output as progress, up to the `max_chars` that the result
    can show; the result is `_exec_result`'s."""
    result: ExecCommandResult | None = None
    streamed = 0
    # Closed at once when the progress callback raises for a Stop, so the
    # client kills the command before the call ends.
    with _sandbox_errors_as_tool_errors(), closing(events):
        for event in events:
            if isinstance(event, ExecCommandResult):
                result = event
                continue
            text = event.text[: max(max_chars - streamed, 0)]
            # Closed once a piece is cut: a later, smaller piece must not
            # skip the cut text.
            streamed = (
                streamed + len(text) if len(text) == len(event.text) else max_chars
            )
            if text:
                invocation.update(
                    ToolProgress(details=event.model_copy(update={"text": text}))
                )
    if result is None:
        raise RuntimeError("The exec stream ended without a result")
    return _exec_result(result, max_chars)


def _exec_result(result: ExecCommandResult, max_chars: int) -> ToolResult:
    """The exec header and the output cut in the middle to `max_chars`, with
    one marker that counts every omitted character; the details save that
    cut. When the cut leaves output out, the full value is the details with
    all the output that the call kept."""
    kept_chars = len(result.head) + len(result.tail)
    output = cut_middle(
        result.head,
        result.tail,
        max_chars,
        omitted=result.omitted_chars,
        label="exec output",
    )
    cut = kept_chars > max_chars
    details = SandboxExecResult(
        output=output,
        wall_time_seconds=result.wall_time_seconds,
        exit_code=result.exit_code,
        session_id=result.session_id,
        completion=result.completion,
        truncated=result.truncated or cut,
    )
    header = [f"Wall time: {result.wall_time_seconds:.4f} seconds"]
    if result.exit_code is not None:
        header.append(f"Process exited with code {result.exit_code}")
    elif result.completion is not None:
        header.append(f"Process ended: {result.completion}")
    if result.session_id is not None:
        header.append(f"Process running with session ID {result.session_id}")
    header.append(f"Original character count: {kept_chars + result.omitted_chars}")
    header.append("Output:")
    return ToolResult(
        content="\n".join(header) + "\n" + output,
        details=details,
        full_value=details.model_copy(
            update={
                "output": cut_middle(
                    result.head,
                    result.tail,
                    kept_chars,
                    omitted=result.omitted_chars,
                    label="exec output",
                ),
                "truncated": result.truncated,
            }
        )
        if cut
        else None,
    )


class SandboxTool(Tool):
    """What the sandbox tools share: the turn, the crash rule, and the name,
    description and arguments that each declares as class attributes."""

    id = None
    interrupted_result = INTERRUPTED_SANDBOX_RESULT
    NAME: str
    DESCRIPTION: str
    ARGUMENTS: type[BaseModel]
    # The tool's use in the system prompt's sandbox section; `{name}` is the
    # name that the model calls. None: only the tool description names it.
    USE: str | None

    def __init__(self, turn: SandboxTurn) -> None:
        self._turn = turn

    @property
    def turn(self) -> SandboxTurn:
        return self._turn

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE

    def tool_definition(self) -> ToolDefinition:
        return tool_definition_from_arguments(
            self.name, self.description, self.ARGUMENTS, strict=True
        )


class ExecCommandTool(SandboxTool):
    NAME = "exec_command"
    USE = EXEC_COMMAND_USE
    DESCRIPTION = EXEC_COMMAND_DESCRIPTION
    ARGUMENTS = ExecCommandArguments
    # Matches the web card title.
    display_name = "Terminal"

    @property
    def description(self) -> str:
        if self._turn.vm_chat_files:
            return f"{self.DESCRIPTION} {CHAT_FILES_LAYOUT}"
        return self.DESCRIPTION

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return _EXEC_RESULT

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(ExecCommandArguments, invocation.arguments)
        max_chars = output_chars(arguments.max_output_chars)
        return _exec_tool_result(
            self._turn.sandbox.exec_command(
                self._turn.start_call(),
                arguments.cmd,
                workdir=arguments.workdir,
                yield_time_ms=arguments.yield_time_ms,
            ),
            invocation,
            max_chars,
        )


class WriteStdinTool(SandboxTool):
    NAME = "write_stdin"
    USE = WRITE_STDIN_USE
    DESCRIPTION = WRITE_STDIN_DESCRIPTION
    ARGUMENTS = WriteStdinArguments
    # Matches the web card title.
    display_name = "Terminal"

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return _EXEC_RESULT

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(WriteStdinArguments, invocation.arguments)
        max_chars = output_chars(arguments.max_output_chars)
        return _exec_tool_result(
            self._turn.sandbox.write_stdin(
                self._turn.start_call(),
                arguments.session_id,
                arguments.chars,
                yield_time_ms=arguments.yield_time_ms,
            ),
            invocation,
            max_chars,
        )


def _verification_failed(message: str) -> ToolCallException:
    return _tool_error(f"apply_patch verification failed: {message}")


def _file_path(ref: HarnessSandboxRef, path: str) -> str:
    """The session-relative path of a file that a patch names."""
    relative = session_relative_path(ref, path)
    if not relative:
        raise SandboxPathError(f"{path!r} is the session directory, not a file")
    return relative


def _check_patchable(path: str, info: SandboxPathInfo) -> None:
    """Raise PatchError unless a file tool can read and write `path` itself:
    it does not follow a link at the path, and the path's parents must lead
    to a place in the session directory."""
    if info.is_link:
        raise PatchError(
            f"{path} is a symbolic link to {info.link_target}; edit that path instead"
        )
    if info.error == "escapes":
        raise PatchError(
            f"{path} goes through a link with an absolute target or one that "
            "leads outside the session directory; use a path inside the "
            "session, or change the file with exec_command"
        )
    if info.error == "loop":
        raise PatchError(f"{path} goes through too many symbolic links")
    if info.error is not None:
        raise PatchError(f"{path} cannot be reached in the session directory")


def _check_writable(path: str, info: SandboxPathInfo) -> None:
    """Raise PatchError unless a file tool can write a file at `path`."""
    _check_patchable(path, info)
    if info.type == "directory":
        raise PatchError(f"Failed to write file {path}: it is a directory")


def _read_text(
    sandbox: HarnessSandbox, ref: HarnessSandboxRef, path: str, info: SandboxPathInfo
) -> str:
    """The text of the existing file at `path`, which `_check_patchable`
    accepted. Raises PatchError unless it is a UTF-8 regular file."""
    if info.type is None or info.mode is None:
        raise PatchError(
            f"Failed to read file to update {path}: No such file or directory"
        )
    if info.type != "file":
        raise PatchError(
            f"Failed to read file to update {path}: "
            f"it is a {info.type}, not a regular file"
        )
    data = sandbox.read_file(ref, path, max_bytes=FILE_TOOL_MAX_FILE_BYTES)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise PatchError(
            f"Failed to read file to update {path}: the file is not UTF-8 text"
        ) from error


def _write_file(
    sandbox: HarnessSandbox,
    ref: HarnessSandboxRef,
    path: str,
    data: bytes,
    info: SandboxPathInfo,
) -> None:
    """Write `path`, whose facts are `info`; an existing file keeps its mode."""
    sandbox.write_file(
        ref, path, data, **({} if info.mode is None else {"mode": info.mode})
    )


def _tool_error(message: str) -> ToolCallException:
    return ToolCallException(message, message)


class _FileTool(SandboxTool):
    """What the file tools share: the order of calls."""

    # File changes of one step read and write the same files, so all file
    # tools take turns.
    sequence_group = "sandbox_file_changes"

    @property
    def execution_mode(self) -> ToolExecutionMode:
        return ToolExecutionMode.SEQUENTIAL


def _change_file(
    turn: SandboxTurn,
    invocation: ToolInvocation,
    file_path: str,
    input_bytes: int,
    contents: Callable[[Callable[[], str | None]], str],
) -> ApplyPatchFileChange:
    """Write one file (edit, write) after the checks that apply_patch makes,
    and return the change. `contents` gets a reader of the file's text (None
    when it is missing) and returns the new text."""
    if input_bytes > FILE_TOOL_MAX_INPUT_BYTES:
        raise _tool_error(
            f"the input is larger than {FILE_TOOL_MAX_INPUT_BYTES} bytes; "
            "make smaller changes"
        )
    sandbox = turn.sandbox
    with _sandbox_errors_as_tool_errors():
        ref = turn.start_call()
        path = _file_path(ref, file_path)
        [info] = sandbox.stat_files(ref, [path])
        created = info.type is None
        try:
            _check_writable(path, info)
            data = contents(
                lambda: None if created else _read_text(sandbox, ref, path, info)
            ).encode()
        except PatchError as error:
            raise _tool_error(str(error)) from error
        # A Stop during the checks changes nothing.
        invocation.cancellation.check()
        _write_file(sandbox, ref, path, data, info)
    return ApplyPatchFileChange(path=path, change="add" if created else "update")


def _noted(content: str, changes: Sequence[ApplyPatchFileChange]) -> str:
    """The result text of file changes; a later turn can put back the
    original chat files in attachments/."""
    changed = [
        path
        for change in changes
        for path in (change.path, change.move_path)
        if path is not None
    ]
    if any(path.startswith(CHAT_FILES_DIR + "/") for path in changed):
        return f"{content}\n\n{ATTACHMENTS_NOT_SAVED_NOTE}"
    return content


class ApplyPatchTool(_FileTool):
    NAME: FileToolName = "apply_patch"
    USE = APPLY_PATCH_USE
    DESCRIPTION = APPLY_PATCH_DESCRIPTION
    ARGUMENTS = ApplyPatchArguments
    # Matches the web card title.
    display_name = "Apply Patch"

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return CodeModeResultSpec(
            kind=CodeModeResultKind.TEXT,
            annotation="str",
            returns="The summary: A (added), M (updated) and D (deleted) "
            "lines with the session-relative path of each file.",
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        patch = parse_tool_arguments(ApplyPatchArguments, invocation.arguments).input
        if len(patch.encode()) > FILE_TOOL_MAX_INPUT_BYTES:
            raise _verification_failed(
                f"the patch is larger than {FILE_TOOL_MAX_INPUT_BYTES} bytes; "
                "split it into smaller patches"
            )
        try:
            parsed = parse_patch(patch)
        except PatchError as error:
            raise _verification_failed(str(error)) from error
        sandbox = self._turn.sandbox
        with _sandbox_errors_as_tool_errors():
            ref = self._turn.start_call()
            hunks: list[PatchHunk] = [
                hunk.model_copy(
                    update={
                        "path": _file_path(ref, hunk.path),
                        "move_path": _file_path(ref, hunk.move_path)
                        if hunk.move_path is not None
                        else None,
                    }
                )
                if isinstance(hunk, UpdateFile)
                else hunk.model_copy(update={"path": _file_path(ref, hunk.path)})
                for hunk in parsed
            ]
            paths = list(
                dict.fromkeys(
                    path
                    for hunk in hunks
                    for path in (
                        hunk.path,
                        hunk.move_path if isinstance(hunk, UpdateFile) else None,
                    )
                    if path is not None
                )
            )
            # A new file or a link is known by its directory and name.
            checked = list(
                dict.fromkeys(
                    [*paths, *(posixpath.dirname(path) or "." for path in paths)]
                )
            )
            facts = dict(zip(checked, sandbox.stat_files(ref, checked), strict=True))

            def file_key(path: str) -> Hashable:
                info = facts[path]
                if info.identity is not None and not info.is_link:
                    return info.identity
                parent = facts[posixpath.dirname(path) or "."].identity
                return path if parent is None else (parent, posixpath.basename(path))

            # Every file is read and every result computed before any
            # write. Each change is (the path it changes, the write or
            # delete).
            writes: list[tuple[str, Callable[[], object]]] = []
            deletes: list[tuple[str, Callable[[], object]]] = []
            staged_bytes = 0
            # The searches of the whole patch; a Stop ends them.
            budget = SeekBudget(invocation.cancellation.check)
            try:
                ensure_unique_targets(hunks, file_key)
                for hunk in hunks:
                    info = facts[hunk.path]
                    if isinstance(hunk, AddFile):
                        _check_writable(hunk.path, info)
                        writes.append(
                            (
                                hunk.path,
                                partial(
                                    _write_file,
                                    sandbox,
                                    ref,
                                    hunk.path,
                                    hunk.contents.encode(),
                                    info,
                                ),
                            )
                        )
                    elif isinstance(hunk, DeleteFile):
                        # A link goes, not its target.
                        if not info.is_link:
                            _check_patchable(hunk.path, info)
                            if not info.exists:
                                raise PatchError(
                                    f"Failed to delete file {hunk.path}: "
                                    "No such file or directory"
                                )
                            if info.type == "directory":
                                raise PatchError(
                                    f"Failed to delete file {hunk.path}: it "
                                    "is a directory"
                                )
                        deletes.append(
                            (
                                hunk.path,
                                partial(sandbox.delete_file, ref, hunk.path),
                            )
                        )
                    else:
                        _check_patchable(hunk.path, info)
                        if hunk.move_path is not None:
                            _check_writable(hunk.move_path, facts[hunk.move_path])
                        original = _read_text(sandbox, ref, hunk.path, info)
                        updated = update_contents(
                            hunk.path, original, hunk.chunks, budget
                        ).encode()
                        staged_bytes += len(updated)
                        if staged_bytes > APPLY_PATCH_MAX_STAGED_BYTES:
                            raise PatchError(
                                "the updated files are larger than "
                                f"{APPLY_PATCH_MAX_STAGED_BYTES} bytes in "
                                "total; split the patch into smaller patches"
                            )
                        writes.append(
                            (
                                hunk.move_path or hunk.path,
                                # A move keeps the mode of its source.
                                partial(
                                    _write_file,
                                    sandbox,
                                    ref,
                                    hunk.move_path or hunk.path,
                                    updated,
                                    info,
                                ),
                            )
                        )
                        if hunk.move_path is not None:
                            deletes.append(
                                (
                                    hunk.path,
                                    partial(sandbox.delete_file, ref, hunk.path),
                                )
                            )
            except PatchError as error:
                raise _verification_failed(str(error)) from error

            # A Stop during the checks changes nothing.
            invocation.cancellation.check()
            changed: list[str] = []
            for path, change in writes + deletes:
                try:
                    change()
                except Exception as error:
                    logger.warning(
                        "apply_patch_change_failed path=%s changed=%d",
                        path,
                        len(changed),
                        exc_info=True,
                    )
                    message = f"apply_patch failed to change {path}: {error}. " + (
                        f"Files already changed: {', '.join(changed)}."
                        if changed
                        else "No file changed."
                    )
                    raise ToolCallException(message, message) from error
                changed.append(path)
        changes = [
            ApplyPatchFileChange(
                path=hunk.path,
                change=_CHANGES[type(hunk)],
                move_path=hunk.move_path if isinstance(hunk, UpdateFile) else None,
            )
            for hunk in hunks
        ]
        return ToolResult(
            content=_noted(summarize(hunks), changes),
            details=ApplyPatchResult(files=changes),
        )


class EditTool(_FileTool):
    """Replaces a string in a file (`patch.edit_text`), in the shape of
    Claude Code's Edit tool."""

    NAME: FileToolName = "edit"
    USE = EDIT_USE
    DESCRIPTION = EDIT_DESCRIPTION
    ARGUMENTS = EditArguments
    # Matches the web card title.
    display_name = "Edit File"

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return _FILE_TOOL_RESULT

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(EditArguments, invocation.arguments)
        change = _change_file(
            self._turn,
            invocation,
            arguments.file_path,
            len(arguments.old_string.encode()) + len(arguments.new_string.encode()),
            lambda read: edit_text(
                read(),
                arguments.old_string,
                arguments.new_string,
                arguments.replace_all,
            ),
        )
        return ToolResult(
            content=_noted(
                f"The file {change.path} has been updated. All occurrences were "
                "successfully replaced."
                if arguments.replace_all
                else f"The file {change.path} has been updated successfully.",
                [change],
            ),
            details=ApplyPatchResult(files=[change]),
        )


class WriteTool(_FileTool):
    """Creates or overwrites a file, in the shape of Claude Code's Write tool.
    Claude Code's rule that a file is read before it is overwritten does not
    apply: the sandbox tools do not track reads."""

    NAME: FileToolName = "write"
    USE = WRITE_USE
    DESCRIPTION = WRITE_DESCRIPTION
    ARGUMENTS = WriteArguments
    # Matches the web card title.
    display_name = "Write File"

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return _FILE_TOOL_RESULT

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(WriteArguments, invocation.arguments)
        change = _change_file(
            self._turn,
            invocation,
            arguments.file_path,
            len(arguments.content.encode()),
            lambda _read: arguments.content,
        )
        return ToolResult(
            content=_noted(
                f"File created successfully at: {change.path}"
                if change.change == "add"
                else f"The file {change.path} has been updated successfully.",
                [change],
            ),
            details=ApplyPatchResult(files=[change]),
        )


class PublishFilesTool(_FileTool):
    """Copies files from the VM to the file store, each as the next version
    of the root chat's artifact at its path, so that everyone who can read the
    chat can download them (`access/access.py:user_can_access_chat_file`). The
    response's save attaches them to its message
    (`db/chat_response.py:save_chat_turn`), and a hard chat delete deletes
    them through their artifacts, saved or not
    (`db/chat.py:delete_messages_and_files_from_chat_session`). A PDF,
    PowerPoint or Word file also gets a thumbnail of its first page, drawn in
    the VM, when it renders within the call's render budget. A call publishes
    all of its files or none. It takes turns with the file tools, so it
    publishes their changes."""

    NAME = "publish_files"
    # The tool description is its only instruction to the model.
    USE = None
    DESCRIPTION = PUBLISH_FILES_DESCRIPTION
    ARGUMENTS = PublishFilesArguments
    display_name = "Publish Files"

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return _FILE_TOOL_RESULT

    def tool_definition(self) -> ToolDefinition:
        # Not strict: the file entries are `$defs` references.
        return tool_definition_from_arguments(
            self.name, self.description, PublishFilesArguments
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(PublishFilesArguments, invocation.arguments)
        sandbox = self._turn.sandbox
        published: list[PublishedFile] = []
        try:
            with _sandbox_errors_as_tool_errors():
                # The turn's chat session is the root chat's, whose readers
                # may download the files; subagent runs share it.
                ref = self._turn.start_call()
                # The budget starts once the call has its sandbox, so a wake
                # or a skills sync does not spend it.
                render_until = time.monotonic() + RENDER_FIRST_PAGE_BUDGET_SECONDS
                for requested in arguments.files:
                    invocation.cancellation.check()
                    data = sandbox.read_file(
                        ref, requested.path, max_bytes=PUBLISH_FILES_MAX_BYTES
                    )
                    path = posixpath.normpath(
                        posixpath.join(
                            session_workspace(ref.session_id), requested.path
                        )
                    )
                    name = posixpath.basename(path)
                    # Postgres text cannot hold NUL, and a blank title is no
                    # title
                    title = (
                        sanitize_string(requested.title or "")
                        .strip()[:PUBLISH_FILES_MAX_TITLE_CHARS]
                        .rstrip()
                        or None
                    )
                    # A file with no thumbnail still publishes. Once the
                    # budget is spent, no render looks up its file or logs.
                    thumbnail = (
                        sandbox.render_first_page(ref, path, until=render_until)
                        if posixpath.splitext(name)[1].lower()
                        in RENDER_FIRST_PAGE_SUFFIXES
                        and len(data) <= RENDER_FIRST_PAGE_MAX_INPUT_BYTES
                        and time.monotonic() < render_until
                        else None
                    )
                    published.append(
                        save_chat_artifact(
                            data,
                            name=name,
                            mime_type=chat_output_file_type(name),
                            chat_session_id=ref.session_id,
                            path=path,
                            title=title,
                            thumbnail=thumbnail,
                        )
                    )
                # A Stop during the last copy publishes nothing.
                invocation.cancellation.check()
        except BaseException:
            # A failed clean-up must not replace the call's own error or Stop.
            try:
                delete_unpublished_chat_artifacts(published)
            except Exception:
                logger.warning(
                    "publish_files_cleanup_failed files=%s",
                    [file.file_id for file in published],
                    exc_info=True,
                )
            raise
        listed = "\n".join(
            f"- {file.path}: version {file.version}, file ID {file.file_id}, "
            f"{file.size} bytes, {file.mime_type}"
            for file in published
        )
        return ToolResult(
            content="Published. The user sees a download card for each file; "
            f"do not repeat their contents.\n{listed}",
            details=PublishedFiles(files=published),
        )


class LoadSkillArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Skill name.")


class LoadSkillTool(SandboxTool):
    """Copies one of the user's skills into its read-only sandbox folder.
    Only a turn whose user has chat skills gets it."""

    NAME = LOAD_SKILL_TOOL_NAME
    USE = None
    DESCRIPTION = (
        "Copy a skill's files into the sandbox, read-only, at "
        f"{CHAT_SKILLS_PATH}/<name>/. Call it before you run the skill's "
        "scripts or open its other files. It returns when the copy is done."
    )
    ARGUMENTS = LoadSkillArguments
    display_name = "Load skill"

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DEFERRED

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(LoadSkillArguments, invocation.arguments)
        try:
            folder = self._turn.load_skill(self._turn.start_call(), arguments.name)
        except SkillLoadError as e:
            raise ToolCallException(message=str(e), llm_facing_message=str(e)) from e
        return ToolResult(
            content=f"Skill '{arguments.name}' is at {folder}/ (read-only).",
            details=CustomToolCallSummary(
                tool_name=self.name,
                response_type="json",
                tool_result={"skill": arguments.name},
            ),
        )


def sandbox_tools_for_model(
    model_names: Sequence[str],
) -> tuple[type[SandboxTool], ...]:
    """The sandbox tools of a chat turn whose model has these names
    (model_identity_names), in the order the prompt names them: Claude models
    edit files with edit and write, the tools they are trained on; the others
    with apply_patch. Every model gets publish_files. The turn builds them,
    and its prompt and token estimate name them."""
    file_tools = (
        (EditTool, WriteTool) if is_claude_model(model_names) else (ApplyPatchTool,)
    )
    return (ExecCommandTool, WriteStdinTool, *file_tools, PublishFilesTool)


def sandbox_guidance(
    tools: Sequence[SandboxTool | type[SandboxTool]],
    called_name: Callable[[str], str],
    *,
    code_mode: bool,
) -> str | None:
    """The system prompt's sandbox section: the use of each of `tools`, in
    order, by the name that `called_name` gives for its tool name; None
    without any."""
    uses = [
        tool.USE.format(name=f"`{called_name(tool.NAME)}`")
        for tool in tools
        if tool.USE is not None
    ]
    if not uses:
        return None
    listed = uses[0] if len(uses) == 1 else f"{', '.join(uses[:-1])} and {uses[-1]}"
    return SANDBOX_GUIDANCE.format(
        uses=f"{listed[0].upper()}{listed[1:]}."
        + (SANDBOX_CODE_MODE_NOTE if code_mode else "")
    )
