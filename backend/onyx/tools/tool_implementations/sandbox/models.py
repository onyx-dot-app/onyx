"""Arguments and result details of the sandbox tools (sandbox_tools.py), and
the chat file copies (file_copies.py). The saved-details unions import it,
so it imports only models and constants."""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    computed_field,
    model_validator,
)

from onyx.server.features.build.sandbox.exec_output import (
    EXEC_DEFAULT_YIELD_MS,
    EXEC_MAX_YIELD_MS,
    EXEC_MIN_YIELD_MS,
    POLL_MAX_YIELD_MS,
    POLL_MIN_YIELD_MS,
    WRITE_STDIN_DEFAULT_YIELD_MS,
    WRITE_STDIN_MAX_YIELD_MS,
)
from onyx.server.features.build.sandbox.harness_base import (
    ARTIFACT_FILES_DIR,
    CHAT_FILES_DIR,
)
from onyx.server.features.build.sandbox.models import (
    SESSION_WORKSPACE_ROOT,
    ExecCompletionName,
)
from onyx.tools.constants import DEFAULT_MAX_OUTPUT_CHARS, MAX_OUTPUT_CHARS_DESCRIPTION
from onyx.utils.datetime import datetime_to_utc
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
    # The file record's last write.
    updated_at: datetime
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


# library_list: the most entries of one page, and the default.
ARTIFACTS_LIST_MAX_LIMIT = 50
ARTIFACTS_LIST_DEFAULT_LIMIT = 25
# The longest query, and the longest name, path and chat title that a page
# keeps; a version's title is at most PUBLISH_FILES_MAX_TITLE_CHARS.
ARTIFACTS_QUERY_MAX_CHARS = 200
ARTIFACTS_NAME_MAX_CHARS = 200
ARTIFACTS_PATH_MAX_CHARS = 300
ARTIFACTS_CHAT_TITLE_MAX_CHARS = 200
# The most extensions that one file type filter takes.
ARTIFACTS_MAX_FILE_TYPES = 50
# The longest library_list result; a page drops its last entries to fit.
# Below spill.RESULT_MAX_CHARS, the spill limit of one result, so neither
# that limit nor the step's budget spills a page.
ARTIFACTS_LIST_MAX_CHARS = 40_000
# Model text that a result or its error can echo. Such a result may never
# spill, so the text has a cap.
_EchoedText = Annotated[str, Field(max_length=ARTIFACTS_PATH_MAX_CHARS)]

# The kind of a published file, from the extension of its name. Image tool
# outputs are not artifacts, so no type is kept for them.
ArtifactType = Literal["image", "sheet", "slides", "report", "other"]
ARTIFACT_TYPE_EXTENSIONS: dict[ArtifactType, frozenset[str]] = {
    "image": frozenset(
        {
            "png",
            "jpg",
            "jpeg",
            "gif",
            "webp",
            "svg",
            "bmp",
            "tif",
            "tiff",
            "heic",
            "avif",
        }
    ),
    "sheet": frozenset({"csv", "tsv", "xls", "xlsx", "xlsm", "xlsb", "ods"}),
    "slides": frozenset({"ppt", "pptx", "pptm", "odp", "key"}),
    "report": frozenset({"pdf", "doc", "docx", "odt", "md", "html", "htm"}),
}


def artifact_extension(file_name: str) -> str | None:
    """The lowercase text after the last dot of a file's name, None without
    a dot; the list's SQL filters read the same text."""
    _, dot, extension = file_name.rpartition(".")
    return extension.lower() if dot else None


def artifact_type(file_name: str) -> ArtifactType:
    """The type of a file by its extension (`artifact_extension`)."""
    extension = artifact_extension(file_name)
    return next(
        (
            kind
            for kind, extensions in ARTIFACT_TYPE_EXTENSIONS.items()
            if extension in extensions
        ),
        "other",
    )


ArtifactSort = Literal["created_at", "modified_at", "name", "size"]
SortOrder = Literal["asc", "desc"]


def _filter_time_in_utc(value: datetime) -> datetime:
    """A filter time without a zone is UTC."""
    try:
        return datetime_to_utc(value)
    except OverflowError:
        # Such as year 1 with a positive offset.
        raise ValueError("the time in UTC is outside years 1 to 9999") from None


_UtcDatetime = Annotated[datetime, AfterValidator(_filter_time_in_utc)]
# Extensions match in any case, with or without the dot.
_FileTypes = Annotated[
    list[Annotated[str, AfterValidator(lambda ext: ext.strip().lstrip(".").lower())]],
    Field(max_length=ARTIFACTS_MAX_FILE_TYPES),
]
_TIME_FILTER = "An ISO 8601 date or time; a time without a zone is UTC."


class LibraryListFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_after: _UtcDatetime | None = Field(
        default=None,
        description=f"Files first published at or after this time. {_TIME_FILTER}",
    )
    created_before: _UtcDatetime | None = Field(
        default=None,
        description=f"Files first published before this time. {_TIME_FILTER}",
    )
    modified_after: _UtcDatetime | None = Field(
        default=None,
        description=f"Files last published at or after this time. {_TIME_FILTER}",
    )
    modified_before: _UtcDatetime | None = Field(
        default=None,
        description=f"Files last published before this time. {_TIME_FILTER}",
    )
    include_file_types: _FileTypes | None = Field(
        default=None,
        description='Only files with one of these extensions, such as ["xlsx", '
        '".csv"]; any case, with or without the dot.',
    )
    exclude_file_types: _FileTypes | None = Field(
        default=None,
        description="No files with one of these extensions; any case, with or "
        "without the dot.",
    )
    category: ArtifactType | None = Field(
        default=None,
        description="Only files of this kind, from the file extension: image, "
        "sheet (csv, tsv, xls*, ods), slides (ppt*, odp, key), report (pdf, "
        "doc*, odt, md, html) or other.",
    )


class LibraryListArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cursor: str | None = Field(
        default=None,
        description="The next_cursor of the previous page, with the same "
        "arguments otherwise.",
    )
    # The tool clamps the limit.
    limit: int = Field(
        default=ARTIFACTS_LIST_DEFAULT_LIMIT,
        description=f"The most files to return, from 1 to {ARTIFACTS_LIST_MAX_LIMIT}.",
    )
    sort: ArtifactSort = Field(
        default="modified_at",
        description="created_at: first publish; modified_at: latest publish; "
        "name: file name; size: file size.",
    )
    sort_order: SortOrder = "desc"
    filters: LibraryListFilters | None = None
    chat_id: _EchoedText | None = Field(
        default=None,
        description="List only the files of this chat (a chat_id of an entry).",
    )
    query: str | None = Field(
        default=None,
        description="Case-insensitive text to find in the file name, the "
        f"file's title or the chat's title, at most {ARTIFACTS_QUERY_MAX_CHARS} "
        "characters.",
    )


class _CursorBase(BaseModel):
    sort_order: SortOrder
    artifact_id: UUID


class _TimeCursor(_CursorBase):
    sort: Literal["created_at", "modified_at"]
    key: datetime


class _NameCursor(_CursorBase):
    sort: Literal["name"]
    key: str


class _SizeCursor(_CursorBase):
    sort: Literal["size"]
    key: int


# Where a page of library_list ends: the sort, and the last entry's sort key
# and artifact. A cursor is its JSON in base64url.
ArtifactCursor = Annotated[
    _TimeCursor | _NameCursor | _SizeCursor, Field(discriminator="sort")
]
ARTIFACT_CURSOR: TypeAdapter[ArtifactCursor] = TypeAdapter(ArtifactCursor)


class ListedArtifact(BaseModel):
    """A published file in an library_list page, or the file that
    library_prepare_materialize looks up: one version of an artifact."""

    # The artifact's ID, the same for every version.
    library_file_id: UUID
    file_id: str
    # More than 1: older versions exist.
    version_number: int
    # The file record's display name; at most ARTIFACTS_NAME_MAX_CHARS in a
    # page.
    file_name: str
    title: str | None
    artifact_type: ArtifactType
    mime_type: str
    file_size_bytes: int
    # The artifact's first and latest publish.
    created_at: datetime
    modified_at: datetime
    chat_id: UUID
    # At most ARTIFACTS_CHAT_TITLE_MAX_CHARS in a page.
    chat_title: str | None
    # published_display_path of the artifact's path; in a page, a longer one
    # keeps its last ARTIFACTS_PATH_MAX_CHARS.
    path: str


class ArtifactList(BaseModel):
    """What library_list returns."""

    files: list[ListedArtifact]
    # None: no more files.
    next_cursor: str | None


# library_prepare_materialize: the most items of one call.
ARTIFACTS_MATERIALIZE_MAX_ITEMS = 20
_DIRECTORY_RULE = (
    f"in the working directory, outside {CHAT_FILES_DIR}/ or in {ARTIFACT_FILES_DIR}/"
)


class MaterializeItem(BaseModel):
    """One file to copy: a version by its file ID, or an artifact's newest
    available version by its library file ID."""

    model_config = ConfigDict(extra="forbid")

    file_id: _EchoedText | None = Field(
        default=None,
        description="A version's file ID. Give this or library_file_id.",
    )
    library_file_id: UUID | None = Field(
        default=None,
        description="A library file ID, for its newest version. Give this or file_id.",
    )
    file_name: _EchoedText | None = Field(
        default=None,
        description="The name of the copy, not a path. Defaults to the file's name.",
    )
    relative_directory: _EchoedText | None = Field(
        default=None,
        description="A directory relative to the destination directory, "
        f"{_DIRECTORY_RULE}. `..` is allowed while the path stays there.",
    )

    @model_validator(mode="after")
    def _one_reference(self) -> "MaterializeItem":
        if (self.file_id is None) == (self.library_file_id is None):
            raise ValueError(
                "each item takes exactly one of file_id and library_file_id"
            )
        return self


ConflictPolicy = Literal["dedupe", "overwrite", "error"]


class MaterializeDestination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: _EchoedText | None = Field(
        default=None,
        description=f"Where the copies go, {_DIRECTORY_RULE}. Defaults to "
        f"{ARTIFACT_FILES_DIR}.",
    )
    conflict_policy: ConflictPolicy = Field(
        default="dedupe",
        description="For every copy except one to the default "
        f"{ARTIFACT_FILES_DIR}/<short file ID>-<name>, when a file is already at "
        "the path: dedupe names "
        'the copy "<name> (N).<ext>", overwrite replaces the file, error fails '
        "the item. A copy to the default ID-prefixed name uses the file there "
        "when its size matches, and writes it again otherwise.",
    )


class LibraryPrepareMaterializeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[MaterializeItem] = Field(
        min_length=1,
        max_length=ARTIFACTS_MATERIALIZE_MAX_ITEMS,
        description="The files to copy, in order.",
    )
    destination: MaterializeDestination | None = None


class MaterializedItem(BaseModel):
    """The outcome of one library_prepare_materialize item, in the items' order.
    A refused item has only the reference that it gave, the status and the
    error."""

    library_file_id: Annotated[UUID | None, OMITTED_WHEN_NONE] = None
    file_id: Annotated[str | None, OMITTED_WHEN_NONE] = None
    version_number: Annotated[int | None, OMITTED_WHEN_NONE] = None
    file_name: Annotated[str | None, OMITTED_WHEN_NONE] = None
    # Relative to the working directory.
    path: Annotated[str | None, OMITTED_WHEN_NONE] = None
    file_size_bytes: Annotated[int | None, OMITTED_WHEN_NONE] = None
    mime_type: Annotated[str | None, OMITTED_WHEN_NONE] = None
    # cached: the same file was already at the path; nothing was written.
    status: Literal["written", "cached", "error"]
    error: Annotated[str | None, OMITTED_WHEN_NONE] = None


class MaterializedItems(BaseModel):
    """What library_prepare_materialize returns."""

    items: list[MaterializedItem]
