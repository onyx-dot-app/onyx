"""Tools that run commands and edit files in the user's private sandbox
(`server/features/build/sandbox/harness_base.py:HarnessSandbox`):
exec_command, write_stdin and apply_patch.

They have no tool row: a chat turn builds all three when it offers the
sandbox (`chat/execution.py:create_chat_agent`), and they share a
`SandboxTurn`. The sandbox is the isolation, so calls need no approval.
"""

import posixpath
from collections.abc import Callable, Generator, Hashable, Iterator, Sequence
from contextlib import closing, contextmanager
from functools import partial
from typing import Literal

from pydantic import BaseModel

from onyx.agents.tools import (
    ToolExecutionMode,
    ToolInvocation,
    ToolProgress,
)
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.prompts.sandbox_tools import (
    APPLY_PATCH_DESCRIPTION,
    APPLY_PATCH_USE,
    EXEC_COMMAND_DESCRIPTION,
    EXEC_COMMAND_USE,
    SANDBOX_CODE_MODE_NOTE,
    SANDBOX_GUIDANCE,
    WRITE_STDIN_DESCRIPTION,
    WRITE_STDIN_USE,
)
from onyx.server.features.build.sandbox.harness_base import (
    HarnessSandboxError,
    SandboxPathError,
    session_relative_path,
)
from onyx.server.features.build.sandbox.models import (
    ExecCommandResult,
    ExecEvent,
    HarnessSandboxRef,
    SandboxPathInfo,
)
from onyx.tools.interface import (
    Tool,
    parse_tool_arguments,
    tool_definition_from_arguments,
)
from onyx.tools.models import (
    CodeModeExposure,
    CodeModeResultKind,
    CodeModeResultSpec,
    ToolCallException,
    ToolContext,
)
from onyx.tools.tool_implementations.sandbox.models import (
    ApplyPatchArguments,
    ApplyPatchFileChange,
    ApplyPatchResult,
    ExecCommandArguments,
    ExecCommandOutput,
    SandboxExecResult,
    WriteStdinArguments,
)
from onyx.tools.tool_implementations.sandbox.patch import (
    APPLY_PATCH_MAX_FILE_BYTES,
    APPLY_PATCH_MAX_INPUT_BYTES,
    APPLY_PATCH_MAX_STAGED_BYTES,
    AddFile,
    DeleteFile,
    PatchError,
    PatchHunk,
    SeekBudget,
    UpdateFile,
    ensure_unique_targets,
    parse_patch,
    summarize,
    update_contents,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
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


@contextmanager
def _sandbox_errors_as_tool_errors() -> Iterator[None]:
    """Sandbox errors that the model can act on become tool errors with their
    message."""
    try:
        yield
    except HarnessSandboxError as error:
        raise ToolCallException(str(error), str(error)) from error


def _exec_tool_result(
    events: Generator[ExecEvent], invocation: ToolInvocation
) -> ToolResult:
    """Stream the output as progress; the result has the exec header text and
    the saved details."""
    result: ExecCommandResult | None = None
    # Closed at once when the progress callback raises for a Stop, so the
    # client kills the command before the call ends.
    with _sandbox_errors_as_tool_errors(), closing(events):
        for event in events:
            if isinstance(event, ExecCommandResult):
                result = event
            else:
                invocation.update(ToolProgress(details=event))
    if result is None:
        raise RuntimeError("The exec stream ended without a result")
    return _exec_result(result)


def _exec_result(result: ExecCommandResult) -> ToolResult:
    """The exec header text and output, with the saved details."""
    header = [f"Wall time: {result.wall_time_seconds:.4f} seconds"]
    if result.exit_code is not None:
        header.append(f"Process exited with code {result.exit_code}")
    elif result.completion is not None:
        header.append(f"Process ended: {result.completion}")
    if result.session_id is not None:
        header.append(f"Process running with session ID {result.session_id}")
    header.append(f"Original token count: {result.original_token_count}")
    header.append("Output:")
    return ToolResult(
        content="\n".join(header) + "\n" + result.output,
        details=SandboxExecResult.model_validate(result, from_attributes=True),
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
    # name that the model calls.
    USE: str

    def __init__(self, turn: SandboxTurn) -> None:
        self._turn = turn

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
    def code_mode_result(self) -> CodeModeResultSpec:
        return _EXEC_RESULT

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(ExecCommandArguments, invocation.arguments)
        return _exec_tool_result(
            self._turn.sandbox.exec_command(
                self._turn.start_call(),
                arguments.cmd,
                workdir=arguments.workdir,
                yield_time_ms=arguments.yield_time_ms,
                max_output_tokens=arguments.max_output_tokens,
            ),
            invocation,
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
        return _exec_tool_result(
            self._turn.sandbox.write_stdin(
                self._turn.start_call(),
                arguments.session_id,
                arguments.chars,
                yield_time_ms=arguments.yield_time_ms,
                max_output_tokens=arguments.max_output_tokens,
            ),
            invocation,
        )


def _verification_failed(message: str) -> ToolCallException:
    text = f"apply_patch verification failed: {message}"
    return ToolCallException(text, text)


def _file_path(ref: HarnessSandboxRef, path: str) -> str:
    """The session-relative path of a file that a patch names."""
    relative = session_relative_path(ref, path)
    if not relative:
        raise SandboxPathError(f"{path!r} is the session directory, not a file")
    return relative


def _check_patchable(path: str, info: SandboxPathInfo) -> None:
    """Raise PatchError unless a patch can read and write `path` itself: it
    does not follow a link at the path, and the path's parents must lead to
    a place in the session directory."""
    if info.is_link:
        raise PatchError(
            f"{path} is a symbolic link to {info.link_target}; patch that path instead"
        )
    if info.error == "escapes":
        raise PatchError(
            f"{path} goes through a link with an absolute target or one that "
            "leads outside the session directory; patch the file by a path "
            "inside the session, or edit it with exec_command"
        )
    if info.error == "loop":
        raise PatchError(f"{path} goes through too many symbolic links")
    if info.error is not None:
        raise PatchError(f"{path} cannot be reached in the session directory")


def _check_writable(path: str, info: SandboxPathInfo) -> None:
    """Raise PatchError unless a patch can write a file at `path`."""
    _check_patchable(path, info)
    if info.type == "directory":
        raise PatchError(f"Failed to write file {path}: it is a directory")


class ApplyPatchTool(SandboxTool):
    NAME = "apply_patch"
    USE = APPLY_PATCH_USE
    DESCRIPTION = APPLY_PATCH_DESCRIPTION
    ARGUMENTS = ApplyPatchArguments
    # Matches the web card title.
    display_name = "Apply Patch"

    @property
    def execution_mode(self) -> ToolExecutionMode:
        # Patches of one step read and write the same files.
        return ToolExecutionMode.SEQUENTIAL

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
        if len(patch.encode()) > APPLY_PATCH_MAX_INPUT_BYTES:
            raise _verification_failed(
                f"the patch is larger than {APPLY_PATCH_MAX_INPUT_BYTES} bytes; "
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
                                # An existing file keeps its mode.
                                partial(
                                    sandbox.write_file,
                                    ref,
                                    hunk.path,
                                    hunk.contents.encode(),
                                    **(
                                        {} if info.mode is None else {"mode": info.mode}
                                    ),
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
                        if info.type is None or info.mode is None:
                            raise PatchError(
                                f"Failed to read file to update {hunk.path}: "
                                "No such file or directory"
                            )
                        if info.type != "file":
                            raise PatchError(
                                f"Failed to read file to update {hunk.path}: "
                                f"it is a {info.type}, not a regular file"
                            )
                        if hunk.move_path is not None:
                            _check_writable(hunk.move_path, facts[hunk.move_path])
                        data = sandbox.read_file(
                            ref, hunk.path, max_bytes=APPLY_PATCH_MAX_FILE_BYTES
                        )
                        try:
                            original = data.decode("utf-8")
                        except UnicodeDecodeError as error:
                            raise PatchError(
                                f"Failed to read file to update {hunk.path}: "
                                "the file is not UTF-8 text"
                            ) from error
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
                                partial(
                                    sandbox.write_file,
                                    ref,
                                    hunk.move_path or hunk.path,
                                    updated,
                                    mode=info.mode,
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
        return ToolResult(
            content=summarize(hunks),
            details=ApplyPatchResult(
                files=[
                    ApplyPatchFileChange(
                        path=hunk.path,
                        change=_CHANGES[type(hunk)],
                        move_path=hunk.move_path
                        if isinstance(hunk, UpdateFile)
                        else None,
                    )
                    for hunk in hunks
                ]
            ),
        )


# The sandbox tools that a chat turn builds, in the order the prompt names them.
SANDBOX_TOOLS: tuple[type[SandboxTool], ...] = (
    ExecCommandTool,
    WriteStdinTool,
    ApplyPatchTool,
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
    uses = [tool.USE.format(name=f"`{called_name(tool.NAME)}`") for tool in tools]
    if not uses:
        return None
    listed = uses[0] if len(uses) == 1 else f"{', '.join(uses[:-1])} and {uses[-1]}"
    return SANDBOX_GUIDANCE.format(
        uses=f"{listed[0].upper()}{listed[1:]}."
        + (SANDBOX_CODE_MODE_NOTE if code_mode else "")
    )
