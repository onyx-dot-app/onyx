"""Arguments and result details of the sandbox tools (sandbox_tools.py). The
saved-details unions import it, so it imports only models and constants."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from onyx.server.features.build.sandbox.exec_output import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    EXEC_DEFAULT_YIELD_MS,
    EXEC_MAX_YIELD_MS,
    EXEC_MIN_YIELD_MS,
    POLL_MAX_YIELD_MS,
    POLL_MIN_YIELD_MS,
    WRITE_STDIN_DEFAULT_YIELD_MS,
    WRITE_STDIN_MAX_YIELD_MS,
)
from onyx.server.features.build.sandbox.models import ExecCompletionName
from onyx.utils.pydantic_util import OMITTED_WHEN_NONE

_MAX_OUTPUT_TOKENS_DESCRIPTION = (
    f"Output token budget. Defaults to {DEFAULT_MAX_OUTPUT_TOKENS} tokens."
)


class ExecCommandArguments(BaseModel):
    cmd: str = Field(description="Shell command to execute.")
    workdir: str | None = Field(
        default=None,
        description="Working directory for the command. Defaults to the chat "
        "session directory.",
    )
    yield_time_ms: int | None = Field(
        default=None,
        description=f"Wait before yielding output. Defaults to "
        f"{EXEC_DEFAULT_YIELD_MS} ms; effective range is "
        f"{EXEC_MIN_YIELD_MS}-{EXEC_MAX_YIELD_MS} ms.",
    )
    max_output_tokens: int | None = Field(
        default=None, description=_MAX_OUTPUT_TOKENS_DESCRIPTION
    )


class WriteStdinArguments(BaseModel):
    # Models may send the session ID as a number.
    model_config = ConfigDict(coerce_numbers_to_str=True)

    session_id: str = Field(description="Identifier of the running command.")
    chars: str = Field(
        default="",
        description="Characters to write to stdin. Defaults to empty, which polls "
        'without writing. "\\u0003" interrupts the command.',
    )
    yield_time_ms: int | None = Field(
        default=None,
        description=f"Wait before yielding output. Non-empty writes default to "
        f"{WRITE_STDIN_DEFAULT_YIELD_MS} ms and cap at {WRITE_STDIN_MAX_YIELD_MS} "
        f"ms; empty polls wait {POLL_MIN_YIELD_MS}-{POLL_MAX_YIELD_MS} ms.",
    )
    max_output_tokens: int | None = Field(
        default=None, description=_MAX_OUTPUT_TOKENS_DESCRIPTION
    )


class ApplyPatchArguments(BaseModel):
    input: str = Field(description="The full patch text.")


_FILE_PATH_DESCRIPTION = (
    "Path of the file, relative to the chat session directory or absolute inside it."
)


class EditArguments(BaseModel):
    """The arguments of Claude Code's Edit tool."""

    file_path: str = Field(description=_FILE_PATH_DESCRIPTION)
    old_string: str = Field(description="The text to replace")
    new_string: str = Field(
        description="The text to replace it with (must be different from old_string)"
    )
    replace_all: bool = Field(
        default=False,
        description="Replace all occurrences of old_string (default false)",
    )


class WriteArguments(BaseModel):
    """The arguments of Claude Code's Write tool."""

    file_path: str = Field(description=_FILE_PATH_DESCRIPTION)
    content: str = Field(description="The content to write to the file")


class ExecCommandOutput(BaseModel):
    """What a code mode program receives from exec_command and write_stdin."""

    output: str = Field(description="Command output text, possibly truncated.")
    wall_time_seconds: float
    exit_code: Annotated[int | None, OMITTED_WHEN_NONE] = Field(
        default=None,
        description="Process exit code when the command exited during this call.",
    )
    session_id: Annotated[str | None, OMITTED_WHEN_NONE] = Field(
        default=None,
        description="Pass to write_stdin while the command still runs.",
    )
    completion: Annotated[ExecCompletionName | None, OMITTED_WHEN_NONE] = Field(
        default=None, description="How the command ended."
    )
    original_token_count: int = Field(
        description="Approximate token count before output truncation."
    )


class SandboxExecResult(ExecCommandOutput):
    """Saved details of an exec_command or write_stdin call."""

    type: Literal["sandbox_exec"] = "sandbox_exec"
    # A byte or token cap removed output.
    truncated: bool = False


# The names of the file tools (sandbox_tools.py), which the patch card shows.
FileToolName = Literal["apply_patch", "edit", "write"]


class ApplyPatchFileChange(BaseModel):
    # Relative to the chat session directory.
    path: str
    change: Literal["add", "update", "delete"]
    move_path: str | None = None


class ApplyPatchResult(BaseModel):
    """Saved details of a file tool call (FileToolName) that changed files."""

    type: Literal["apply_patch"] = "apply_patch"
    files: list[ApplyPatchFileChange]
