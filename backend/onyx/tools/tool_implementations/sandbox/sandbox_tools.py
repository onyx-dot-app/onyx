"""Tools that run commands, edit files and publish files in the user's
private sandbox (`server/features/build/sandbox/harness_base.py:HarnessSandbox`).
`SANDBOX_TOOLS` gives the set that a turn's model gets.

They have no tool row: a chat turn builds them when it offers the sandbox
(`chat/execution.py:create_chat_agent`), and they share a `SandboxTurn`. The
sandbox is the isolation, so calls need no approval; only a delete of a
published file asks (ARTIFACTS_DELETE_APPROVAL).
"""

import abc
import posixpath
from collections.abc import Callable, Generator, Hashable, Mapping, Sequence
from contextlib import closing
from functools import partial
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field, JsonValue

from onyx.agents.tools import (
    ToolExecutionMode,
    ToolInvocation,
    ToolProgress,
)
from onyx.llm.model_capabilities import ToolFamily
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.prompts.sandbox_tools import (
    APPLY_PATCH_DESCRIPTION,
    APPLY_PATCH_USE,
    ARTIFACT_DESCRIPTION,
    ARTIFACT_RESULTS,
    ATTACHMENTS_NOT_SAVED_NOTE,
    CHAT_FILES_LAYOUT,
    EDIT_DESCRIPTION,
    EDIT_USE,
    EXEC_COMMAND_DESCRIPTION,
    EXEC_COMMAND_USE,
    LIBRARY_CREATE_LIBRARY_FILE_DESCRIPTION,
    LIBRARY_FIND_DESCRIPTION,
    LIBRARY_LIST_DESCRIPTION,
    LIBRARY_MANAGE_LIBRARY_DESCRIPTION,
    LIBRARY_PREPARE_MATERIALIZE_DESCRIPTION,
    LIBRARY_READ_DESCRIPTION,
    LIBRARY_REPLACE_LIBRARY_FILE_DESCRIPTION,
    LIBRARY_SEARCH_DESCRIPTION,
    SANDBOX_CODE_MODE_NOTE,
    SANDBOX_GUIDANCE,
    WRITE_DESCRIPTION,
    WRITE_STDIN_DESCRIPTION,
    WRITE_STDIN_USE,
    WRITE_USE,
)
from onyx.server.features.build.sandbox.harness_base import (
    CHAT_FILES_DIR,
    HarnessSandbox,
    SandboxPathError,
    session_relative_path,
)
from onyx.server.features.build.sandbox.models import (
    CHAT_SKILLS_PATH,
    ExecCommandResult,
    ExecEvent,
    HarnessSandboxRef,
    SandboxPathInfo,
    chat_skill_folder,
)
from onyx.skills.chat import SkillLoadError, load_chat_skill_files
from onyx.tools.constants import (
    LOAD_SKILL_TOOL_NAME,
    WRITE_STDIN_TOOL_NAME,
)
from onyx.tools.interface import (
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import (
    CodeModeExposure,
    CodeModeFunctionName,
    CodeModeResultKind,
    CodeModeResultSpec,
    CustomToolCallSummary,
    ToolApprovalDetails,
    ToolApprovalScope,
    ToolCallException,
    ToolContext,
)
from onyx.tools.ordering import ToolRank
from onyx.tools.tool_implementations.sandbox import artifact_operations
from onyx.tools.tool_implementations.sandbox.errors import (
    sandbox_errors_as_tool_errors,
    tool_error,
)
from onyx.tools.tool_implementations.sandbox.models import (
    ApplyPatchArguments,
    ApplyPatchFileChange,
    ApplyPatchResult,
    ArtifactList,
    ArtifactPublished,
    ArtifactsFound,
    ArtifactsRead,
    ArtifactVersionConflict,
    EditArguments,
    ExecCommandOutput,
    FileToolName,
    LibraryCreateLibraryFileArguments,
    LibraryFindArguments,
    LibraryListArguments,
    LibraryPrepareMaterializeArguments,
    LibraryReadArguments,
    LibraryReplaceLibraryFileArguments,
    LibraryRequest,
    LibrarySearchArguments,
    LibrarySearchResult,
    ManageLibraryArguments,
    ManageResults,
    MaterializedItems,
    SandboxExecResult,
    WriteArguments,
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
from onyx.tools.tool_implementations.sandbox.shapes import (
    SHELL_SHAPES,
    ArtifactArguments,
    ShellShape,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.utils import cut_middle
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The saved result of a call that a lost server left running; it is not run
# again because its command or edit may have taken effect. `{shell}` is the
# shape's command tool, by its tool name: only a direct call gets this result,
# since code mode never reruns a program's calls on their own.
INTERRUPTED_SANDBOX_MESSAGE = (
    "The call was interrupted before it returned and was not run again. "
    "Check the sandbox state with {shell} before you retry."
)

_CHANGES: dict[type[PatchHunk], Literal["add", "update", "delete"]] = {
    AddFile: "add",
    UpdateFile: "update",
    DeleteFile: "delete",
}

# The built-in action whose calls wait for the user's approval: a delete of a
# published file, by either artifact tool family, so one chat grant covers
# both. A turn that runs without asking builds the tools without it
# (chat/execution.py).
ARTIFACTS_DELETE_APPROVAL = ToolApprovalScope(
    integration_id=None, action_id="onyx:artifacts.delete"
)

_EXEC_RESULT = CodeModeResultSpec(
    kind=CodeModeResultKind.DETAILS, model=ExecCommandOutput
)
_FILE_TOOL_RESULT = CodeModeResultSpec(
    kind=CodeModeResultKind.TEXT, annotation="str", returns="The result message."
)


def _exec_tool_result(
    events: Generator[ExecEvent], invocation: ToolInvocation, max_chars: int
) -> ToolResult:
    """Stream the output as progress, up to the `max_chars` that the result
    can show; the result is `_exec_result`'s."""
    result: ExecCommandResult | None = None
    streamed = 0
    # Closed at once when the progress callback raises for a Stop, so the
    # client kills the command before the call ends.
    with sandbox_errors_as_tool_errors(), closing(events):
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
    """What the sandbox tools share: the turn, whose shell shape names the
    command tool, the crash rule, the name (`tool_name`: the NAME class
    attribute, except for the command tool) and description that each
    declares, and its arguments model. A description names other tools by
    `{shell}` and the other fields of `describe`."""

    id = None
    NAME: str
    DESCRIPTION: str
    # The tool's use in the system prompt's sandbox section; `{name}` is the
    # name that the model calls. None: only the tool description names it.
    USE: str | None
    # True: a call that a lost server left running runs again, because it
    # changes nothing.
    RUNS_AGAIN = False

    def __init__(self, turn: SandboxTurn) -> None:
        self._turn = turn
        self.interrupted_result = (
            None
            if self.RUNS_AGAIN
            else ToolResult(
                content=INTERRUPTED_SANDBOX_MESSAGE.format(shell=turn.shell.name),
                is_error=True,
            )
        )

    @property
    def turn(self) -> SandboxTurn:
        return self._turn

    @property
    @abc.abstractmethod
    def arguments(self) -> type[BaseModel]:
        """The model of the tool's arguments, which its definition shows."""
        raise NotImplementedError

    @classmethod
    def tool_name(cls, shell: ShellShape) -> str:  # noqa: ARG003
        """The tool's name in a turn of the given shell shape."""
        return cls.NAME

    @property
    def name(self) -> str:
        return self.tool_name(self._turn.shell)

    @property
    def description(self) -> str:
        return self.describe(str)

    def describe(self, called_name: Callable[[str], str]) -> str:
        return self.DESCRIPTION.format(
            shell=called_name(self._turn.shell.name),
            edit=called_name(EditTool.NAME),
            create=called_name(LibraryCreateLibraryFileTool.NAME),
            list=called_name(LibraryListTool.NAME),
            materialize=called_name(LibraryPrepareMaterializeTool.NAME),
            replace=called_name(LibraryReplaceLibraryFileTool.NAME),
        )

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE

    def tool_definition(self) -> ToolDefinition:
        return tool_definition_from_arguments(
            self.name, self.description, self.arguments, strict=True
        )


class ExecCommandTool(SandboxTool):
    """Runs a command; the turn's shell shape names it and takes its
    arguments."""

    rank = ToolRank.SHELL
    USE = EXEC_COMMAND_USE
    DESCRIPTION = EXEC_COMMAND_DESCRIPTION
    # Matches the web card title.
    display_name = "Terminal"

    @classmethod
    def tool_name(cls, shell: ShellShape) -> str:
        return shell.name

    def describe(self, called_name: Callable[[str], str]) -> str:
        description = super().describe(called_name)
        if self._turn.vm_chat_files:
            return f"{description} {CHAT_FILES_LAYOUT}"
        return description

    @property
    def arguments(self) -> type[BaseModel]:
        return self._turn.shell.arguments

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return _EXEC_RESULT

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(
            self._turn.shell.arguments, invocation.arguments
        ).request()
        return _exec_tool_result(
            self._turn.sandbox.exec_command(
                self._turn.start_call(),
                request.cmd,
                workdir=request.workdir,
                yield_time_ms=request.yield_time_ms,
            ),
            invocation,
            request.max_chars,
        )


class WriteStdinTool(SandboxTool):
    rank = ToolRank.SHELL_INPUT
    NAME = WRITE_STDIN_TOOL_NAME
    USE = WRITE_STDIN_USE
    DESCRIPTION = WRITE_STDIN_DESCRIPTION
    # Matches the web card title.
    display_name = "Terminal"

    @property
    def arguments(self) -> type[BaseModel]:
        return self._turn.shell.write_stdin_arguments

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return _EXEC_RESULT

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        request = parse_tool_arguments(
            self._turn.shell.write_stdin_arguments, invocation.arguments
        ).request()
        return _exec_tool_result(
            self._turn.sandbox.write_stdin(
                self._turn.start_call(),
                request.session_id,
                request.chars,
                yield_time_ms=request.yield_time_ms,
            ),
            invocation,
            request.max_chars,
        )


def _verification_failed(message: str) -> ToolCallException:
    return tool_error(f"apply_patch verification failed: {message}")


def _file_path(ref: HarnessSandboxRef, path: str) -> str:
    """The session-relative path of a file that a patch names."""
    relative = session_relative_path(ref.session_id, path)
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
            "session, or change the file with a shell command"
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
        raise tool_error(
            f"the input is larger than {FILE_TOOL_MAX_INPUT_BYTES} bytes; "
            "make smaller changes"
        )
    sandbox = turn.sandbox
    with sandbox_errors_as_tool_errors():
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
            raise tool_error(str(error)) from error
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
    rank = ToolRank.FILE_EDIT
    NAME: FileToolName = "apply_patch"
    USE = APPLY_PATCH_USE
    DESCRIPTION = APPLY_PATCH_DESCRIPTION
    arguments = ApplyPatchArguments
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
        with sandbox_errors_as_tool_errors():
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

    rank = ToolRank.FILE_EDIT

    NAME: FileToolName = "edit"
    USE = EDIT_USE
    DESCRIPTION = EDIT_DESCRIPTION
    arguments = EditArguments
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

    rank = ToolRank.FILE_EDIT

    NAME: FileToolName = "write"
    USE = WRITE_USE
    DESCRIPTION = WRITE_DESCRIPTION
    arguments = WriteArguments
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


class _LibraryTool(SandboxTool):
    """What the tools over the user's published files share. They run the
    artifact operations (artifact_operations.run_operation), which reach only
    the files published in the user's own root chats that are not deleted
    (`db/chat.py:get_user_published_files`), this chat included. In code mode
    each is a deferred function of its group, which the program search
    finds; the group's line in the run tool's description says what the group
    is for, and no listed function or prompt names a function. Running a list
    or copy again changes nothing, so a call that a lost server left running
    runs again; the tools that publish say otherwise."""

    rank = ToolRank.PUBLISHED_FILES

    USE = None
    RUNS_AGAIN = True
    CODE_MODE_NAMESPACE = "library"
    # The group's line in the run tool's description.
    CODE_MODE_NAMESPACE_DESCRIPTION = (
        "Find and read the user's published files, copy them into this chat, "
        "add versions to them, and change or delete them; create a file here "
        "to give it to the user."
    )
    CODE_MODE_NAME: str
    RESULT: type[BaseModel]

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DEFERRED

    @property
    def code_mode_function_name(self) -> CodeModeFunctionName:
        return CodeModeFunctionName(
            name=self.CODE_MODE_NAME,
            namespace=self.CODE_MODE_NAMESPACE,
            namespace_description=self.CODE_MODE_NAMESPACE_DESCRIPTION,
        )

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return CodeModeResultSpec(
            kind=CodeModeResultKind.JSON_OBJECT, model=self.RESULT
        )

    def tool_definition(self) -> ToolDefinition:
        # Not strict: the arguments have nested models.
        return tool_definition_from_arguments(
            self.name, self.description, self.arguments
        )

    def operation_request(self, arguments: dict[str, JsonValue]) -> LibraryRequest:
        """The operation's arguments of a call with `arguments`; a library
        tool's arguments are its operation's. Raises ToolCallException when
        they do not fit."""
        request = parse_tool_arguments(self.arguments, arguments)
        if not isinstance(request, LibraryRequest):
            raise TypeError(f"{self.name} takes no library operation's arguments")
        return request

    def conflict_message(self, error: ArtifactVersionConflict) -> str:
        """The tool's words for a new version whose expected version is not
        the newest."""
        return (
            f"Current version is {error.current_version}, not the one you "
            "named; nothing changed. Copy the newest version, merge your change "
            "and try again, or omit expected_current_version"
        )

    def approval_details(
        self, arguments: dict[str, JsonValue]
    ) -> ToolApprovalDetails | None:
        try:
            request = self.operation_request(arguments)
        except ToolCallException:
            return None
        return artifact_operations.delete_approval_details(self._turn.user_id, request)

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        return artifact_operations.run_operation(
            self._turn,
            invocation.cancellation,
            self.operation_request(invocation.arguments),
            conflict_message=self.conflict_message,
        )


class LibraryListTool(_LibraryTool):
    NAME = "library_list"
    CODE_MODE_NAME = "list"
    DESCRIPTION = LIBRARY_LIST_DESCRIPTION
    arguments = LibraryListArguments
    RESULT = ArtifactList
    display_name = "Find Published Files"


class LibraryPrepareMaterializeTool(_LibraryTool):
    NAME = "library_prepare_materialize"
    CODE_MODE_NAME = "prepare_materialize"
    DESCRIPTION = LIBRARY_PREPARE_MATERIALIZE_DESCRIPTION
    arguments = LibraryPrepareMaterializeArguments
    RESULT = MaterializedItems
    display_name = "Copy Published Files"


class LibraryReadTool(_LibraryTool):
    NAME = "library_read"
    CODE_MODE_NAME = "read"
    DESCRIPTION = LIBRARY_READ_DESCRIPTION
    arguments = LibraryReadArguments
    RESULT = ArtifactsRead
    display_name = "Read Published Files"


class LibraryFindTool(_LibraryTool):
    NAME = "library_find"
    CODE_MODE_NAME = "find"
    DESCRIPTION = LIBRARY_FIND_DESCRIPTION
    arguments = LibraryFindArguments
    RESULT = ArtifactsFound
    display_name = "Find in Published Files"


class LibraryCreateLibraryFileTool(_LibraryTool, _FileTool):
    """Gives files from the VM to the user, each as the next version of the
    root chat's artifact at its path (artifact_operations.publish). It takes
    turns with the file tools, so it publishes their changes, and a call
    that a lost server left running is not run again."""

    NAME = "library_create_library_file"
    CODE_MODE_NAME = "create_library_file"
    DESCRIPTION = LIBRARY_CREATE_LIBRARY_FILE_DESCRIPTION
    arguments = LibraryCreateLibraryFileArguments
    RESULT = ArtifactPublished
    display_name = "Publish Files"
    RUNS_AGAIN = False


class LibraryReplaceLibraryFileTool(_LibraryTool, _FileTool):
    """Adds a version to an artifact of any of the user's chats
    (artifact_operations.replace_file). It returns PublishedFiles, so the
    call shows the publish card and the version joins this chat's message
    files. A replace is not idempotent, so a call that a lost server left
    running is not run again."""

    NAME = "library_replace_library_file"
    CODE_MODE_NAME = "replace_library_file"
    DESCRIPTION = LIBRARY_REPLACE_LIBRARY_FILE_DESCRIPTION
    arguments = LibraryReplaceLibraryFileArguments
    RESULT = ArtifactPublished
    display_name = "Replace Published File"
    RUNS_AGAIN = False


class LibraryManageLibraryTool(_LibraryTool, _FileTool):
    """Changes artifacts of any of the user's chats
    (artifact_operations.manage): a list of operations, each a member of a
    union on `operation`. It shows
    the generic card. A call with a delete waits for the user's approval of
    the whole call. Its operations are not all idempotent, so a call that a
    lost server left running is not run again."""

    NAME = "library_manage_library"
    CODE_MODE_NAME = "manage_library"
    DESCRIPTION = LIBRARY_MANAGE_LIBRARY_DESCRIPTION
    arguments = ManageLibraryArguments
    RESULT = ManageResults
    display_name = "Manage Published Files"
    RUNS_AGAIN = False
    approval = ARTIFACTS_DELETE_APPROVAL


class LibrarySearchTool(_LibraryTool):
    NAME = "library_search"
    CODE_MODE_NAME = "search"
    DESCRIPTION = LIBRARY_SEARCH_DESCRIPTION
    arguments = LibrarySearchArguments
    RESULT = LibrarySearchResult
    display_name = "Search Published Files"


class ArtifactTool(_LibraryTool, _FileTool):
    """One tool with an action for each artifact operation, which Claude
    models get instead of the library tools (SANDBOX_TOOLS), in
    the shape they are trained on. Each action gives the arguments of a
    library tool's operation (ArtifactArguments.request), so both families
    publish, list and copy alike, and a publish gives the same PublishedFiles
    card. Execution settings are per tool, so the tool takes turns with the
    file tools and keeps the interrupted result, as publish needs; its list
    and read calls take turns too. In code mode it is the deferred function
    `artifact.artifact`, in its own group."""

    NAME = "artifact"
    CODE_MODE_NAMESPACE = "artifact"
    CODE_MODE_NAMESPACE_DESCRIPTION = (
        "Give files from the VM to the user, and find, read, copy, change and "
        "delete the files published in this chat and the user's other chats."
    )
    CODE_MODE_NAME = "artifact"
    DESCRIPTION = ARTIFACT_DESCRIPTION
    arguments = ArtifactArguments
    # The generic card of list and read; publish has the publish card.
    display_name = "Published Files"
    RUNS_AGAIN = False
    approval = ARTIFACTS_DELETE_APPROVAL

    def operation_request(self, arguments: dict[str, JsonValue]) -> LibraryRequest:
        return parse_tool_arguments(ArtifactArguments, arguments).request()

    def conflict_message(self, error: ArtifactVersionConflict) -> str:
        return (
            f"Current version is {error.current_version}; read it with out_dir, "
            "merge your change, then publish with the url from that result, or "
            "pass force:true"
        )

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return CodeModeResultSpec(
            kind=CodeModeResultKind.JSON_OBJECT, returns=ARTIFACT_RESULTS
        )


class LoadSkillArguments(BaseModel):
    name: str = Field(min_length=1, description="Skill name.")


class LoadSkillTool(SandboxTool):
    """Copies one of the user's custom skills into its read-only sandbox
    folder. The turn offers it when the user has custom skills with files;
    the built-ins reach the VM through file_copies.py:TurnSkillCopies."""

    rank = ToolRank.SKILLS_LOAD
    NAME = LOAD_SKILL_TOOL_NAME
    USE = None
    DESCRIPTION = (
        "Copy the files of one of the user's own skills into the sandbox, "
        f"read-only, at {CHAT_SKILLS_PATH}/<name>/. Call it before you run "
        "that skill's scripts or open its other files. It returns when the "
        "copy is done."
    )
    arguments = LoadSkillArguments
    display_name = "Load skill"

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.DEFERRED

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(LoadSkillArguments, invocation.arguments)
        try:
            skill = load_chat_skill_files(self._turn.user_id, arguments.name)
        except SkillLoadError as e:
            raise ToolCallException(message=str(e), llm_facing_message=str(e)) from e
        self._turn.sandbox.install_skill(
            self._turn.start_call(), arguments.name, skill.version, skill.files
        )
        return ToolResult(
            content=f"Skill '{arguments.name}' is at {chat_skill_folder(arguments.name)}/ (read-only).",
            details=CustomToolCallSummary(
                tool_name=self.name,
                response_type="json",
                tool_result={"skill": arguments.name},
            ),
        )


class SandboxToolset(NamedTuple):
    """The sandbox tools of one tool family: the shell shape that its turns
    carry, and the tool classes by rank (onyx/tools/ordering.py)."""

    shell: ShellShape
    tools: tuple[type[SandboxTool], ...]


# The sandbox tools of a chat turn by the tool family of its model. Claude
# models get the tools they work with: edit and write for files, and the
# artifact tool for published files. The others get apply_patch and the
# library tools. No turn gets both sets. The turn builds them, and its prompt
# and token estimate name them.
SANDBOX_TOOLS: Mapping[ToolFamily, SandboxToolset] = {
    ToolFamily.CLAUDE: SandboxToolset(
        shell=SHELL_SHAPES[ToolFamily.CLAUDE],
        tools=(
            ExecCommandTool,
            WriteStdinTool,
            EditTool,
            WriteTool,
            ArtifactTool,
        ),
    ),
    ToolFamily.OPENAI: SandboxToolset(
        shell=SHELL_SHAPES[ToolFamily.OPENAI],
        tools=(
            ExecCommandTool,
            WriteStdinTool,
            ApplyPatchTool,
            LibraryCreateLibraryFileTool,
            LibraryListTool,
            LibraryPrepareMaterializeTool,
            LibraryReadTool,
            LibraryFindTool,
            LibraryReplaceLibraryFileTool,
            LibraryManageLibraryTool,
            LibrarySearchTool,
        ),
    ),
}


def sandbox_guidance(
    tools: Sequence[type[SandboxTool]],
    shell: ShellShape,
    called_name: Callable[[str], str],
    *,
    code_mode_run_name: str | None,
) -> str | None:
    """The system prompt's sandbox section: the use of each of `tools`, in
    order, by the name that `called_name` gives for its name in a turn of
    the `shell` shape; None without any. `code_mode_run_name` is the code
    mode run tool's name, when code mode applies."""
    uses = [
        tool.USE.format(name=f"`{called_name(tool.tool_name(shell))}`")
        for tool in tools
        if tool.USE is not None
    ]
    if not uses:
        return None
    listed = uses[0] if len(uses) == 1 else f"{', '.join(uses[:-1])} and {uses[-1]}"
    return SANDBOX_GUIDANCE.format(
        uses=f"{listed[0].upper()}{listed[1:]}."
        + (
            ""
            if code_mode_run_name is None
            else SANDBOX_CODE_MODE_NOTE.format(name=code_mode_run_name)
        )
    )
