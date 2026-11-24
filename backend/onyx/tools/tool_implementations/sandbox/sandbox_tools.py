"""Tools that run commands, edit files and publish files in the user's
private sandbox (`server/features/build/sandbox/harness_base.py:HarnessSandbox`).
`sandbox_tools_for_model` gives the set that a turn's model gets.

They have no tool row: a chat turn builds them when it offers the sandbox
(`chat/execution.py:create_chat_agent`), and they share a `SandboxTurn`. The
sandbox is the isolation, so calls need no approval.
"""

import posixpath
from collections.abc import Callable, Generator, Hashable, Sequence
from contextlib import closing
from functools import partial
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from onyx.agents.tools import (
    ToolExecutionMode,
    ToolInvocation,
    ToolProgress,
)
from onyx.llm.model_capabilities import is_claude_model
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
    LIBRARY_LIST_DESCRIPTION,
    LIBRARY_PREPARE_MATERIALIZE_DESCRIPTION,
    LIBRARY_REPLACE_LIBRARY_FILE_DESCRIPTION,
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
from onyx.tools.constants import LOAD_SKILL_TOOL_NAME
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
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.sandbox import artifact_operations
from onyx.tools.tool_implementations.sandbox.errors import (
    sandbox_errors_as_tool_errors,
    tool_error,
)
from onyx.tools.tool_implementations.sandbox.models import (
    ARTIFACT_ACTION_ARGUMENTS,
    ARTIFACTS_MATERIALIZE_MAX_ITEMS,
    PUBLISH_FILES_MAX_FILES,
    ApplyPatchArguments,
    ApplyPatchFileChange,
    ApplyPatchResult,
    ArtifactArguments,
    ArtifactList,
    ArtifactPublished,
    ArtifactVersionConflict,
    EditArguments,
    ExecCommandArguments,
    ExecCommandOutput,
    FileToolName,
    LibraryCreateLibraryFileArguments,
    LibraryListArguments,
    LibraryPrepareMaterializeArguments,
    LibraryReplaceLibraryFileArguments,
    MaterializeDestination,
    MaterializedItems,
    MaterializeItem,
    PublishedFiles,
    PublishFileArgument,
    SandboxExecResult,
    WriteArguments,
    WriteStdinArguments,
    parse_artifact_url,
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
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.tools.tool_implementations.utils import cut_middle, output_chars
from onyx.utils.logger import setup_logger

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


class _LibraryTool(SandboxTool):
    """What the tools over the user's published files share. They run the
    artifact operations (artifact_operations.py), which reach only the files
    published in the user's own root chats that are not deleted
    (`db/chat.py:get_user_published_files`), this chat included. In code mode
    each is a deferred function of its group, which tool_search finds; the
    group's line in the execute_code description says what the group is for,
    and no listed function or prompt names a function. Running a list or copy
    again changes nothing, so a call that a lost server left running runs
    again; the tools that publish say otherwise."""

    USE = None
    interrupted_result = None
    CODE_MODE_NAMESPACE = "library"
    # The group's line in the execute_code description.
    CODE_MODE_NAMESPACE_DESCRIPTION = (
        "Find the user's published files, copy them into this chat and add "
        "versions to them; create a file here to give it to the user."
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
            self.name, self.description, self.ARGUMENTS
        )


class LibraryListTool(_LibraryTool):
    NAME = "library_list"
    CODE_MODE_NAME = "list"
    DESCRIPTION = LIBRARY_LIST_DESCRIPTION
    ARGUMENTS = LibraryListArguments
    RESULT = ArtifactList
    display_name = "Find Published Files"

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        return ToolResult(
            content=artifact_operations.list_artifacts(
                self._turn.user_id,
                parse_tool_arguments(LibraryListArguments, invocation.arguments),
            ).model_dump_json()
        )


class LibraryPrepareMaterializeTool(_LibraryTool):
    NAME = "library_prepare_materialize"
    CODE_MODE_NAME = "prepare_materialize"
    DESCRIPTION = LIBRARY_PREPARE_MATERIALIZE_DESCRIPTION
    ARGUMENTS = LibraryPrepareMaterializeArguments
    RESULT = MaterializedItems
    display_name = "Copy Published Files"

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        return ToolResult(
            content=artifact_operations.materialize(
                self._turn,
                invocation.cancellation,
                parse_tool_arguments(
                    LibraryPrepareMaterializeArguments, invocation.arguments
                ),
            ).model_dump_json()
        )


class LibraryCreateLibraryFileTool(_LibraryTool, _FileTool):
    """Gives files from the VM to the user, each as the next version of the
    root chat's artifact at its path (artifact_operations.publish). It takes
    turns with the file tools, so it publishes their changes, and a call
    that a lost server left running is not run again."""

    NAME = "library_create_library_file"
    CODE_MODE_NAME = "create_library_file"
    DESCRIPTION = LIBRARY_CREATE_LIBRARY_FILE_DESCRIPTION
    ARGUMENTS = LibraryCreateLibraryFileArguments
    RESULT = ArtifactPublished
    display_name = "Publish Files"
    interrupted_result = INTERRUPTED_SANDBOX_RESULT

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(
            LibraryCreateLibraryFileArguments, invocation.arguments
        )
        published = artifact_operations.publish(
            self._turn,
            invocation.cancellation,
            [PublishFileArgument(path=arguments.file, title=arguments.title)]
            if arguments.file is not None
            else [PublishFileArgument(path=path) for path in arguments.files or []],
        )
        return ToolResult(
            content=ArtifactPublished.of(published).model_dump_json(),
            details=PublishedFiles(files=published),
        )


class LibraryReplaceLibraryFileTool(_LibraryTool, _FileTool):
    """Adds a version to an artifact of any of the user's chats
    (artifact_operations.replace_file). It returns PublishedFiles, so the
    call shows the publish card and the version joins this chat's message
    files. A replace is not idempotent, so a call that a lost server left
    running is not run again."""

    NAME = "library_replace_library_file"
    CODE_MODE_NAME = "replace_library_file"
    DESCRIPTION = LIBRARY_REPLACE_LIBRARY_FILE_DESCRIPTION
    ARGUMENTS = LibraryReplaceLibraryFileArguments
    RESULT = ArtifactPublished
    display_name = "Replace Published File"
    interrupted_result = INTERRUPTED_SANDBOX_RESULT

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(
            LibraryReplaceLibraryFileArguments, invocation.arguments
        )
        try:
            published = artifact_operations.replace_file(
                self._turn, invocation.cancellation, arguments
            )
        except ArtifactVersionConflict as error:
            raise tool_error(
                f"Current version is {error.current_version}; materialize it and "
                "merge your change, or omit expected_current_version"
            ) from error
        return ToolResult(
            content=ArtifactPublished.of([published]).model_dump_json(),
            details=PublishedFiles(files=[published]),
        )


class ArtifactTool(_LibraryTool, _FileTool):
    """One tool with an action for each artifact operation
    (artifact_operations.py), which Claude models get instead of the
    library tools (sandbox_tools_for_model), for
    compatibility with how they work with artifacts. Each action builds the
    library tools' arguments of its operation, so both families publish,
    list and copy alike, and a publish gives the same PublishedFiles card.
    Execution settings are per tool, so the tool takes turns with the file
    tools and keeps the interrupted result, as publish needs; its list and
    read calls take turns too. In code mode it is the deferred function
    `artifact.artifact`, in its own group."""

    NAME = "artifact"
    CODE_MODE_NAMESPACE = "artifact"
    CODE_MODE_NAMESPACE_DESCRIPTION = (
        "Give files from the VM to the user, and find and copy the files "
        "published in this chat and the user's other chats."
    )
    CODE_MODE_NAME = "artifact"
    DESCRIPTION = ARTIFACT_DESCRIPTION
    ARGUMENTS = ArtifactArguments
    # The generic card of list and read; publish has the publish card.
    display_name = "Published Files"
    interrupted_result = INTERRUPTED_SANDBOX_RESULT

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return CodeModeResultSpec(
            kind=CodeModeResultKind.JSON_OBJECT, returns=ARTIFACT_RESULTS
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(ArtifactArguments, invocation.arguments)
        action = arguments.action
        extra = sorted(
            name
            for name, value in arguments
            if value is not None
            and name != "action"
            and name not in ARTIFACT_ACTION_ARGUMENTS[action]
        )
        if extra:
            raise tool_error(
                f"Action {action} does not take {', '.join(extra)}; it takes "
                f"{', '.join(sorted(ARTIFACT_ACTION_ARGUMENTS[action]))}"
            )
        if action == "publish":
            paths = (
                [arguments.file_path]
                if arguments.file_path is not None
                else arguments.file_paths or []
            )
            if not paths or (
                arguments.file_path is not None and arguments.file_paths is not None
            ):
                raise tool_error("publish takes file_path or file_paths")
            if len(paths) > PUBLISH_FILES_MAX_FILES:
                raise tool_error(
                    f"publish takes at most {PUBLISH_FILES_MAX_FILES} file_paths"
                )
            if arguments.file_path is None and (
                arguments.title is not None or arguments.url is not None
            ):
                raise tool_error("title and url go with file_path")
            if arguments.force is not None and arguments.url is None:
                raise tool_error("force goes with url")
            if arguments.url is None:
                published = artifact_operations.publish(
                    self._turn,
                    invocation.cancellation,
                    [
                        PublishFileArgument(path=path, title=arguments.title)
                        for path in paths
                    ],
                )
            else:
                try:
                    artifact_id, version = parse_artifact_url(arguments.url)
                except ValueError as error:
                    raise tool_error(str(error)) from error
                if version is None and not arguments.force:
                    raise tool_error(
                        "Pass the url from your last result, which names the "
                        "version you saw, or force:true"
                    )
                try:
                    published = [
                        artifact_operations.replace_file(
                            self._turn,
                            invocation.cancellation,
                            LibraryReplaceLibraryFileArguments(
                                library_file_id=artifact_id,
                                file=paths[0],
                                expected_current_version=None
                                if arguments.force
                                else version,
                                title=arguments.title,
                            ),
                        )
                    ]
                except ArtifactVersionConflict as error:
                    raise tool_error(
                        f"Current version is {error.current_version}; read it, "
                        "merge your change, then publish with the url from that "
                        "result, or pass force:true"
                    ) from error
            return ToolResult(
                content=ArtifactPublished.of(published).model_dump_json(),
                details=PublishedFiles(files=published),
            )
        if action == "list":
            return ToolResult(
                content=artifact_operations.list_artifacts(
                    self._turn.user_id,
                    parse_tool_arguments(
                        LibraryListArguments,
                        {
                            "limit": arguments.limit,
                            "cursor": arguments.after,
                            "query": arguments.query,
                            "filters": {"category": arguments.type},
                        },
                    ),
                ).model_dump_json()
            )
        if arguments.out_dir is None:
            raise tool_error(
                "read copies published files into the VM: pass out_dir, the "
                "directory for the copies"
            )
        targets = [
            *([] if arguments.url is None else [arguments.url]),
            *([] if arguments.path is None else [arguments.path]),
            *(arguments.paths or []),
        ]
        if not targets:
            raise tool_error("read takes url, path or paths")
        if len(targets) > ARTIFACTS_MATERIALIZE_MAX_ITEMS:
            raise tool_error(
                f"read copies at most {ARTIFACTS_MATERIALIZE_MAX_ITEMS} files; "
                "pass fewer paths"
            )
        items: list[MaterializeItem] = []
        for target in targets:
            try:
                artifact_id, version = parse_artifact_url(target)
            except ValueError as error:
                if target == arguments.url:
                    raise tool_error(str(error)) from error
                items.append(MaterializeItem(file_id=target))
            else:
                items.append(
                    MaterializeItem(library_file_id=artifact_id, version_number=version)
                )
        return ToolResult(
            content=artifact_operations.materialize(
                self._turn,
                invocation.cancellation,
                LibraryPrepareMaterializeArguments(
                    items=items,
                    destination=MaterializeDestination(directory=arguments.out_dir),
                ),
            ).model_dump_json()
        )


class LoadSkillArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Skill name.")


class LoadSkillTool(SandboxTool):
    """Copies one of the user's skills into its read-only sandbox folder."""

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


def sandbox_tools_for_model(
    model_names: Sequence[str],
) -> tuple[type[SandboxTool], ...]:
    """The sandbox tools of a chat turn whose model has these names
    (model_identity_names), in the order the prompt names them. Claude
    models get the tools they work with: edit and write for files, and the
    artifact tool for published files. The others get apply_patch and the
    library tools. No turn gets both sets. The turn
    builds them, and its prompt and token estimate name them."""
    if is_claude_model(model_names):
        return (ExecCommandTool, WriteStdinTool, EditTool, WriteTool, ArtifactTool)
    return (
        ExecCommandTool,
        WriteStdinTool,
        ApplyPatchTool,
        LibraryCreateLibraryFileTool,
        LibraryListTool,
        LibraryPrepareMaterializeTool,
        LibraryReplaceLibraryFileTool,
    )


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
