"""Arguments and result details of the sandbox tools (sandbox_tools.py), and
the chat file copies (file_copies.py). The saved-details unions import it,
so it imports only models and constants."""

from collections.abc import Callable, Mapping
from datetime import datetime
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


# The largest search result file that a sandbox chat copies into its VM.
SEARCH_FILE_MAX_BYTES = 100 << 20


class SearchResultFile(BaseModel):
    """The file of shown search results that a tool can open."""

    model_config = ConfigDict(frozen=True)

    # The title of the first result that shows it.
    title: str
    # The file record's size; None: not recorded.
    size: int | None
    # The shown results' documents that have this file.
    document_ids: tuple[str, ...]


# Offers a search's files (by file store ID) to the sandbox chat's turn, which
# copies them into the VM in the background; gives the path, relative to the
# working directory, of each file that it copies.
SearchFileOffer = Callable[[Mapping[str, SearchResultFile]], dict[str, str]]


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


def published_display_path(path: str) -> str:
    """The path to show of a published file at `path`: relative to the
    working directory of the chat that published it, or the whole path
    outside it. publish_files accepts only that chat's working directory under
    SESSION_WORKSPACE_ROOT."""
    workspaces = f"{SESSION_WORKSPACE_ROOT}/"
    if not path.startswith(workspaces):
        return path
    _, _, relative = path.removeprefix(workspaces).partition("/")
    return relative or path


class PublishedFileView(PublishedFile):
    """A published file as clients get it, in packets and the session load:
    with the path to show. Saved details keep the plain `PublishedFile`."""

    @computed_field
    @property
    def display_path(self) -> str:
        return published_display_path(self.path)


class PublishedFiles(BaseModel):
    """Saved details of a publish_files call."""

    type: Literal["published_files"] = "published_files"
    files: list[PublishedFile]


# artifacts_list: the most entries of one page, and the default.
ARTIFACTS_LIST_MAX_LIMIT = 50
ARTIFACTS_LIST_DEFAULT_LIMIT = 25
# The longest query, and the longest name, path and chat title that a page
# keeps; a version's title is at most PUBLISH_FILES_MAX_TITLE_CHARS.
ARTIFACTS_QUERY_MAX_CHARS = 200
ARTIFACTS_NAME_MAX_CHARS = 200
ARTIFACTS_PATH_MAX_CHARS = 300
ARTIFACTS_CHAT_TITLE_MAX_CHARS = 200
# The longest artifacts_list result; a page drops its last entries to fit.
# Below spill.RESULT_MAX_CHARS, the spill limit of one result; the step's
# budget (spill.STEP_MAX_CHARS) can still spill a page.
ARTIFACTS_LIST_MAX_CHARS = 40_000


class ArtifactsListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The tool checks the bounds, so the strict schema keeps to plain types.
    query: str | None = Field(
        default=None,
        description="Case-insensitive text to find in the file name, the "
        f"file's title or the chat's title, at most {ARTIFACTS_QUERY_MAX_CHARS} "
        "characters. Omit it to list every file.",
    )
    chat_id: str | None = Field(
        default=None,
        description="List only the files of this chat (a chat_id of an entry).",
    )
    limit: int = Field(
        default=ARTIFACTS_LIST_DEFAULT_LIMIT,
        description=f"The most files to return, from 1 to {ARTIFACTS_LIST_MAX_LIMIT}.",
    )
    cursor: str | None = Field(
        default=None,
        description="The next_cursor of the previous page, with the same "
        "query and chat_id, for the next older files.",
    )


class ArtifactsDownloadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(
        description="The file ID of a listed file, or of any version in a "
        "publish_files result."
    )


class ArtifactCursor(BaseModel):
    """Where a page of artifacts_list ends: the last entry's artifact and its
    latest publish. A cursor is this model's JSON in base64url."""

    updated_at: datetime
    artifact_id: UUID


class ListedArtifact(BaseModel):
    """A published file in an artifacts_list page, or the file that
    artifacts_download looks up."""

    file_id: str
    # The file record's display name; at most ARTIFACTS_NAME_MAX_CHARS in a
    # page.
    name: str
    title: str | None
    # published_display_path of the artifact's path; in a page, a longer one
    # keeps its last ARTIFACTS_PATH_MAX_CHARS.
    path: str
    # More than 1: older versions exist.
    version: int
    chat_id: UUID
    # At most ARTIFACTS_CHAT_TITLE_MAX_CHARS in a page.
    chat_title: str | None
    published_at: datetime
    size: int
    mime_type: str


class ArtifactList(BaseModel):
    """What artifacts_list returns: newest publish first."""

    artifacts: list[ListedArtifact]
    # None: no older files.
    next_cursor: str | None


class DownloadedArtifact(BaseModel):
    """What artifacts_download returns."""

    # Relative to the working directory.
    path: str
    file_id: str
    name: str
    size: int
    mime_type: str
    chat_id: UUID
    # The file was already at the path; nothing was written.
    cached: bool
