"""Codex-style tools that run in the user's private sandbox
(`server/features/build/sandbox/harness_base.py:HarnessSandbox`):
exec_command, write_stdin and apply_patch.

They have no tool row: a chat turn builds all three when it offers the
sandbox (`chat/execution.py:create_chat_agent`), and they share a
`SandboxTurn`. The sandbox is the isolation, so calls need no approval.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from typing import Literal

from onyx.agents.tools import (
    ToolExecutionMode,
    ToolInvocation,
    ToolProgress,
)
from onyx.llm.models import ToolDefinition, ToolResult
from onyx.prompts.sandbox_tools import (
    APPLY_PATCH_DESCRIPTION,
    EXEC_COMMAND_DESCRIPTION,
    WRITE_STDIN_DESCRIPTION,
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
    AddFile,
    DeleteFile,
    PatchError,
    PatchHunk,
    UpdateFile,
    ensure_unique_targets,
    parse_patch,
    summarize,
    update_contents,
)
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Largest apply_patch input, in UTF-8 bytes.
APPLY_PATCH_MAX_INPUT_BYTES = 1 << 20
# Largest file that apply_patch reads to update it.
APPLY_PATCH_MAX_FILE_BYTES = 10 << 20

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
    events: Iterator[ExecEvent], invocation: ToolInvocation
) -> ToolResult:
    """Stream the output as progress; the result has Codex's text and the
    saved details."""
    result: ExecCommandResult | None = None
    for event in events:
        if isinstance(event, ExecCommandResult):
            result = event
        else:
            invocation.update(ToolProgress(details=event))
    if result is None:
        raise RuntimeError("The exec stream ended without a result")
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


class _SandboxTool(Tool):
    """What the three sandbox tools share: the turn and the crash rule."""

    id = None
    display_name = "Sandbox"
    interrupted_result = INTERRUPTED_SANDBOX_RESULT

    def __init__(self, turn: SandboxTurn) -> None:
        self._turn = turn
        self.end_run = turn.end

    @property
    def code_mode_exposure(self) -> CodeModeExposure:
        return CodeModeExposure.IMMEDIATE


class ExecCommandTool(_SandboxTool):
    NAME = "exec_command"

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return EXEC_COMMAND_DESCRIPTION

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return _EXEC_RESULT

    def tool_definition(self) -> ToolDefinition:
        return tool_definition_from_arguments(
            self.name, self.description, ExecCommandArguments, strict=True
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(ExecCommandArguments, invocation.arguments)
        with _sandbox_errors_as_tool_errors():
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


class WriteStdinTool(_SandboxTool):
    NAME = "write_stdin"

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return WRITE_STDIN_DESCRIPTION

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        return _EXEC_RESULT

    def tool_definition(self) -> ToolDefinition:
        return tool_definition_from_arguments(
            self.name, self.description, WriteStdinArguments, strict=True
        )

    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        arguments = parse_tool_arguments(WriteStdinArguments, invocation.arguments)
        with _sandbox_errors_as_tool_errors():
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


def _session_file(ref: HarnessSandboxRef, path: str, resolved: str) -> str:
    """The session path of `resolved`, the file where the patch path `path`
    leads."""
    try:
        relative = session_relative_path(ref, resolved)
    except SandboxPathError as error:
        raise PatchError(
            f"{path} leads to {resolved}, outside the session directory; edit "
            "that file with exec_command"
        ) from error
    if not relative:
        raise PatchError(
            f"{path} leads to {resolved}, which is the session directory, not a file"
        )
    return relative


class ApplyPatchTool(_SandboxTool):
    NAME = "apply_patch"

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return APPLY_PATCH_DESCRIPTION

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

    def tool_definition(self) -> ToolDefinition:
        return tool_definition_from_arguments(
            self.name, self.description, ApplyPatchArguments, strict=True
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
            try:
                facts = dict(zip(paths, sandbox.stat_files(ref, paths), strict=True))
            except SandboxPathError as error:
                raise _verification_failed(str(error)) from error

            # Every file is read and every result computed before any write.
            # Each change is (the path it changes, the write or delete).
            writes: list[tuple[str, Callable[[], object]]] = []
            deletes: list[tuple[str, Callable[[], object]]] = []
            try:
                ensure_unique_targets(
                    hunks,
                    lambda path: facts[path].real_path,
                    lambda path: facts[path].entry_path,
                )
                for hunk in hunks:
                    info = facts[hunk.path]
                    if isinstance(hunk, AddFile):
                        target = _session_file(ref, hunk.path, info.real_path)
                        if info.type == "directory":
                            raise PatchError(
                                f"Failed to write file {hunk.path}: it is a directory"
                            )
                        writes.append(
                            (
                                hunk.path,
                                # An existing file keeps its mode.
                                partial(
                                    sandbox.write_file,
                                    ref,
                                    target,
                                    hunk.contents.encode(),
                                    **(
                                        {} if info.mode is None else {"mode": info.mode}
                                    ),
                                ),
                            )
                        )
                    elif isinstance(hunk, DeleteFile):
                        _session_file(ref, hunk.path, info.entry_path)
                        if info.type is None and not info.is_link:
                            raise PatchError(
                                f"Failed to delete file {hunk.path}: "
                                "No such file or directory"
                            )
                        if info.type == "directory" and not info.is_link:
                            raise PatchError(
                                f"Failed to delete file {hunk.path}: it is a directory"
                            )
                        # The path as spelled: a link goes, not its target.
                        deletes.append(
                            (hunk.path, partial(sandbox.delete_file, ref, hunk.path))
                        )
                    else:
                        source = _session_file(ref, hunk.path, info.real_path)
                        if info.type is None or info.mode is None:
                            raise PatchError(
                                f"Failed to read file to update {hunk.path}: "
                                "No such file or directory"
                            )
                        if info.type != "file":
                            raise PatchError(
                                f"Failed to read file to update {hunk.path}: it is "
                                f"a {info.type}, not a regular file"
                            )
                        destination = source
                        if hunk.move_path is not None:
                            moved = facts[hunk.move_path]
                            destination = _session_file(
                                ref, hunk.move_path, moved.real_path
                            )
                            if moved.type == "directory":
                                raise PatchError(
                                    f"Failed to write file {hunk.move_path}: it is "
                                    "a directory"
                                )
                        data = sandbox.read_file(
                            ref, source, max_bytes=APPLY_PATCH_MAX_FILE_BYTES
                        )
                        try:
                            original = data.decode("utf-8")
                        except UnicodeDecodeError as error:
                            raise PatchError(
                                f"Failed to read file to update {hunk.path}: "
                                "the file is not UTF-8 text"
                            ) from error
                        writes.append(
                            (
                                hunk.move_path or hunk.path,
                                partial(
                                    sandbox.write_file,
                                    ref,
                                    destination,
                                    update_contents(
                                        hunk.path, original, hunk.chunks
                                    ).encode(),
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
