"""Arguments and result details of the sandbox tools (sandbox_tools.py), and
the chat file copies (file_copies.py). The saved-details unions import it,
so it imports only models and constants."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from onyx.server.features.build.sandbox.exec_output import (
    EXEC_DEFAULT_YIELD_MS,
    EXEC_MAX_YIELD_MS,
    EXEC_MIN_YIELD_MS,
    POLL_MAX_YIELD_MS,
    POLL_MIN_YIELD_MS,
    WRITE_STDIN_DEFAULT_YIELD_MS,
    WRITE_STDIN_MAX_YIELD_MS,
)
from onyx.server.features.build.sandbox.models import (
    SESSION_WORKSPACE_ROOT,
    ExecCompletionName,
)
from onyx.tools.constants import DEFAULT_MAX_OUTPUT_CHARS, MAX_OUTPUT_CHARS_DESCRIPTION
from onyx.utils.pydantic_util import OMITTED_WHEN_NONE


class VmChatFile(BaseModel):
    """A chat file in the chat's sandbox: a file store file and its path,
    relative to the chat's working directory."""

    model_config = ConfigDict(frozen=True)

    file_id: str
    path: str


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
    max_output_chars: int = Field(
        default=DEFAULT_MAX_OUTPUT_CHARS, description=MAX_OUTPUT_CHARS_DESCRIPTION
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
    max_output_chars: int = Field(
        default=DEFAULT_MAX_OUTPUT_CHARS, description=MAX_OUTPUT_CHARS_DESCRIPTION
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


class SpilledOutput(BaseModel):
    """What the user's card shows of a result whose full value went to a
    file in the sandbox VM (spill.py): its head and tail, with a plain note."""

    head: str
    tail: str


class SandboxExecResult(ExecCommandOutput):
    """Saved details of an exec_command or write_stdin call."""

    type: Literal["sandbox_exec"] = "sandbox_exec"
    # `output` is not all of the output: the call's max_output_chars cut it,
    # the byte cap (EXEC_CALL_OUTPUT_MAX_BYTES) dropped some, or the daemon
    # lost some. In the full value, only the last two.
    truncated: bool = False
    # Set, with an empty `output`, when the output went to the sandbox VM.
    spilled: Annotated[SpilledOutput | None, OMITTED_WHEN_NONE] = None


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


# Largest file that publish_files copies to the file store.
PUBLISH_FILES_MAX_BYTES = 100 << 20
# Most files that one publish_files call publishes.
PUBLISH_FILES_MAX_FILES = 20
# Longest title that publish_files keeps; it cuts a longer one.
PUBLISH_FILES_MAX_TITLE_CHARS = 200


class PublishFileArgument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        description="Path of the file in the VM: relative to the working "
        "directory, or absolute."
    )
    title: str | None = Field(
        default=None,
        description="A short title for the user. Defaults to the file name.",
    )


class PublishFilesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[PublishFileArgument] = Field(
        min_length=1,
        max_length=PUBLISH_FILES_MAX_FILES,
        description="The files to give the user.",
    )
    description: str | None = Field(
        default=None, description="One sentence about the files, for the user."
    )


class PublishedFile(BaseModel):
    """A file that publish_files copied from the VM to the file store."""

    file_id: str
    # The chat's artifact at this path and this file's version of it, from 1.
    # Details saved without them have neither; such a file is an artifact of
    # its own.
    artifact_id: UUID | None = None
    version: int | None = None
    # The file name, which the download keeps.
    name: str
    title: str | None = None
    # Absolute and normalized.
    path: str
    size: int
    mime_type: str
    # A JPEG of the file's first page, for a PDF, PowerPoint or Word file
    # that rendered; it downloads from /chat/file/{thumbnail_file_id}.
    thumbnail_file_id: str | None = None


class PublishedFileView(PublishedFile):
    """A published file as clients get it, in packets and the session load:
    with the path to show. Saved details keep the plain `PublishedFile`."""

    @computed_field
    @property
    def display_path(self) -> str:
        """The path to show: relative to the working directory of the chat
        that published the file, or the whole path outside it. publish_files
        accepts only that chat's working directory under
        SESSION_WORKSPACE_ROOT."""
        workspaces = f"{SESSION_WORKSPACE_ROOT}/"
        if not self.path.startswith(workspaces):
            return self.path
        _, _, relative = self.path.removeprefix(workspaces).partition("/")
        return relative or self.path


class PublishedFiles(BaseModel):
    """Saved details of a publish_files call."""

    type: Literal["published_files"] = "published_files"
    files: list[PublishedFile]
