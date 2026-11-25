"""Arguments and result details of the sandbox tools (sandbox_tools.py), and
the chat file copies (file_copies.py). The saved-details unions import it,
so it imports only models and constants."""

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal
from urllib.parse import urlsplit
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
from pydantic_core import PydanticCustomError

from onyx.configs.app_configs import WEB_DOMAIN
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


# Largest file that a publish copies to the file store.
PUBLISH_FILES_MAX_BYTES = 100 << 20
# Most files that one library_create_library_file call publishes.
PUBLISH_FILES_MAX_FILES = 20
# Longest title that a publish keeps; it cuts a longer one.
PUBLISH_FILES_MAX_TITLE_CHARS = 200


class PublishFileArgument(BaseModel):
    """A file that a publish asks for, as the model wrote it: a VM path and
    an optional title."""

    path: str
    title: str | None = None


class LibraryCreateLibraryFileArguments(BaseModel):
    """One file with an optional title, or several files."""

    model_config = ConfigDict(extra="forbid")

    file: str | None = Field(
        default=None,
        description="A file in the VM: relative to the working directory, or "
        "absolute. Give this or files.",
    )
    files: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=PUBLISH_FILES_MAX_FILES,
        description="Several files in the VM instead of file; all are published, "
        "or none.",
    )
    title: str | None = Field(
        default=None,
        description="With file: a short title for the user. Defaults to the file name.",
    )
    description: str | None = Field(
        default=None, description="One sentence about the files, for the user."
    )

    @model_validator(mode="after")
    def _one_source(self) -> "LibraryCreateLibraryFileArguments":
        if (self.file is None) == (self.files is None):
            raise ValueError("give exactly one of file and files")
        if self.title is not None and self.file is None:
            raise ValueError("title goes with file")
        return self


class PublishedFile(BaseModel):
    """A file that a publish (library_create_library_file, library_replace_library_file
    or the artifact tool) copied from the VM to the file store."""

    file_id: str
    # The chat's artifact at this path and this file's version of it, from 1.
    # Details saved without them have neither; such a file is an artifact of
    # its own.
    artifact_id: UUID | None = None
    version: int | None = None
    # The root chat that owns the artifact, which can be another chat than
    # the one that published this version. Details saved without it have none.
    chat_id: UUID | None = None
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
    outside it. A publish accepts only that chat's working directory under
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
    """Saved details of a call that published files: the publish card."""

    type: Literal["published_files"] = "published_files"
    files: list[PublishedFile]


# library_list: the most entries of one page, and the default.
ARTIFACTS_LIST_MAX_LIMIT = 50
ARTIFACTS_LIST_DEFAULT_LIMIT = 25
# The longest query, and the longest name, path and chat title that a page
# keeps; a version's title is at most PUBLISH_FILES_MAX_TITLE_CHARS.
# ARTIFACTS_PATH_MAX_CHARS also bounds each path, url, file ID or name that
# the artifact tool takes: its results echo them and are never spilled.
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


# The path of a link to an artifact, or to one of its versions: the web app
# opens it in the output panel (web/src/app/app/artifacts), on any origin.
# The web's parseArtifactLink takes the same paths.
_ARTIFACT_URL_PATH = re.compile(
    r"/app/artifacts/(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{12})(?:/v(?P<version>[0-9]+))?/?",
    re.IGNORECASE,
)


def artifact_url(artifact_id: UUID, version: int) -> str:
    return f"{WEB_DOMAIN.rstrip('/')}/app/artifacts/{artifact_id}/v{version}"


def parse_artifact_url(url: str) -> tuple[UUID, int | None]:
    """The artifact and the version (None: the newest) of a link to an
    artifact, on any origin or without one, with any query or fragment.
    Raises ValueError for anything else."""
    match = _ARTIFACT_URL_PATH.fullmatch(urlsplit(url.strip()).path)
    if match is None:
        raise ValueError(f"{url!r} is not an artifact url")
    version = match["version"]
    return UUID(match["id"]), None if version is None else int(version)


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
        description="Files whose latest change (publish or rename) is at or after "
        f"this time. {_TIME_FILTER}",
    )
    modified_before: _UtcDatetime | None = Field(
        default=None,
        description="Files whose latest change (publish or rename) is before this "
        f"time. {_TIME_FILTER}",
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
        description="created_at: first publish; modified_at: latest change (publish "
        "or rename); name: file name; size: file size.",
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


class LibraryReplaceLibraryFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    library_file_id: UUID = Field(
        description="The library file to add a version to, from any of your chats."
    )
    file: str = Field(
        description="The new content: a file in the VM, relative to the working "
        "directory or absolute, with the library file's extension."
    )
    expected_current_version: int | None = Field(
        default=None,
        description="The version_number that you last read. The replace fails "
        "when the library file has a newer one.",
    )
    title: str | None = Field(
        default=None,
        description="A short title for the new version. Defaults to the "
        "current version's title.",
    )


class ArtifactAtPath(BaseModel):
    """The root chat's artifact of a VM path, which the first publish of the
    path creates."""

    model_config = ConfigDict(frozen=True)

    chat_session_id: UUID
    path: str


class ArtifactById(BaseModel):
    """An artifact that exists; its path stays."""

    model_config = ConfigDict(frozen=True)

    artifact_id: UUID


# The artifact that a publish adds a version to.
ArtifactTarget = ArtifactAtPath | ArtifactById


class KeptTitle(Enum):
    """The title of a new version that keeps the artifact's: its newest
    available version's when the save holds the artifact's row lock."""

    NEWEST = "newest"


class ArtifactVersionConflict(Exception):
    """A new version named a current version that is no longer the
    artifact's newest available one; nothing was saved."""

    def __init__(self, current_version: int) -> None:
        super().__init__(f"The artifact's current version is {current_version}")
        self.current_version = current_version


class ArtifactNotFound(Exception):
    """The artifact is gone, or its chat is deleted; nothing was saved."""

    def __init__(self, artifact_id: UUID) -> None:
        super().__init__(f"No published file {artifact_id} in your chats")


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
    # The artifact's newest available version, in a lookup
    # (db/chat.py:get_user_published_file); a list page has none, because
    # it shows the newest.
    latest_version_number: Annotated[int | None, OMITTED_WHEN_NONE] = None
    # The artifact's name: a rename's, else the file record's; a page cuts
    # it (shown_artifact).
    file_name: str
    title: str | None
    artifact_type: ArtifactType
    mime_type: str
    file_size_bytes: int
    # The artifact's first publish and latest change (publish or rename).
    created_at: datetime
    modified_at: datetime
    chat_id: UUID
    # A page cuts it (shown_artifact).
    chat_title: str | None
    # published_display_path of the artifact's path; a page cuts it
    # (shown_artifact).
    path: str
    # artifact_url of this version.
    url: str


def shown_artifact(artifact: ListedArtifact) -> ListedArtifact:
    """`artifact` as a list page shows it: its name and chat title cut to
    ARTIFACTS_NAME_MAX_CHARS and ARTIFACTS_CHAT_TITLE_MAX_CHARS, and a longer
    path to its last ARTIFACTS_PATH_MAX_CHARS."""
    return artifact.model_copy(
        update={
            "file_name": artifact.file_name[:ARTIFACTS_NAME_MAX_CHARS],
            "chat_title": None
            if artifact.chat_title is None
            else artifact.chat_title[:ARTIFACTS_CHAT_TITLE_MAX_CHARS],
            "path": artifact.path
            if len(artifact.path) <= ARTIFACTS_PATH_MAX_CHARS
            else "…" + artifact.path[-(ARTIFACTS_PATH_MAX_CHARS - 1) :],
        }
    )


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


class ArtifactFileReference(BaseModel):
    """A published file version: by its file ID, or an artifact's newest
    available version by its library file ID, or that artifact's version
    `version_number`."""

    model_config = ConfigDict(extra="forbid")

    file_id: _EchoedText | None = Field(
        default=None,
        description="A version's file ID. Give this or library_file_id.",
    )
    library_file_id: UUID | None = Field(
        default=None,
        description="A library file ID, for its newest version. Give this or file_id.",
    )
    version_number: int | None = Field(
        default=None,
        description="With library_file_id: that version instead of the newest.",
    )

    @model_validator(mode="after")
    def _one_reference(self) -> "ArtifactFileReference":
        if (self.file_id is None) == (self.library_file_id is None):
            raise ValueError("give exactly one of file_id and library_file_id")
        if self.version_number is not None and self.library_file_id is None:
            raise ValueError("version_number goes with library_file_id")
        return self


class MaterializeItem(ArtifactFileReference):
    """One file to copy, and the name and directory of the copy."""

    file_name: _EchoedText | None = Field(
        default=None,
        description="The name of the copy, not a path. Defaults to the file's name.",
    )
    relative_directory: _EchoedText | None = Field(
        default=None,
        description="A directory relative to the destination directory, "
        f"{_DIRECTORY_RULE}. `..` is allowed while the path stays there.",
    )


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
    # The version copied; for a refused item, the version that it asked for.
    version_number: Annotated[int | None, OMITTED_WHEN_NONE] = None
    file_name: Annotated[str | None, OMITTED_WHEN_NONE] = None
    # Relative to the working directory.
    path: Annotated[str | None, OMITTED_WHEN_NONE] = None
    file_size_bytes: Annotated[int | None, OMITTED_WHEN_NONE] = None
    mime_type: Annotated[str | None, OMITTED_WHEN_NONE] = None
    url: Annotated[str | None, OMITTED_WHEN_NONE] = None
    # cached: the same file was already at the path; nothing was written.
    status: Literal["written", "cached", "error"]
    error: Annotated[str | None, OMITTED_WHEN_NONE] = None


class MaterializedItems(BaseModel):
    """What library_prepare_materialize returns."""

    items: list[MaterializedItem]


# The arguments of the artifact tool's publish that name its file, or its
# files; the renderer reads them for the publish card.
ARTIFACT_PUBLISH_PATHS = ("file_path", "file_paths")


# library_manage_library: the most operations of one call.
MANAGE_LIBRARY_MAX_OPERATIONS = 20


class LibraryFileTarget(ArtifactFileReference):
    """The file that an operation changes: the artifact of the version that
    the reference names."""

    kind: Literal["file"] = "file"


# A delete removes every version, so a target that names a version names
# the newest one.
DELETE_OF_A_VERSION = (
    "delete removes every version, so name the file by its newest version"
)


class DeleteOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["delete"]
    target: LibraryFileTarget


class RenameOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["rename"]
    target: LibraryFileTarget
    new_name: _EchoedText = Field(
        description="The new file name, not a path, with the current extension."
    )


ManageOperation = Annotated[
    DeleteOperation | RenameOperation, Field(discriminator="operation")
]


class ManageLibraryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: list[ManageOperation] = Field(
        min_length=1,
        max_length=MANAGE_LIBRARY_MAX_OPERATIONS,
        description="The operations, run in order.",
    )


class ManageResult(BaseModel):
    """The outcome of one library_manage_library operation, in the operations'
    order: the artifact as the operation left it, or the error."""

    operation: Literal["delete", "rename"]
    ok: bool
    error: Annotated[str | None, OMITTED_WHEN_NONE] = None
    library_file_id: Annotated[UUID | None, OMITTED_WHEN_NONE] = None
    # The artifact's version that the operation read or added.
    file_id: Annotated[str | None, OMITTED_WHEN_NONE] = None
    version_number: Annotated[int | None, OMITTED_WHEN_NONE] = None
    file_name: Annotated[str | None, OMITTED_WHEN_NONE] = None
    url: Annotated[str | None, OMITTED_WHEN_NONE] = None
    # A delete's: the versions that it deleted.
    deleted_versions: Annotated[int | None, OMITTED_WHEN_NONE] = None


class ManageResults(BaseModel):
    """What library_manage_library returns."""

    results: list[ManageResult]


# The arguments that each action of the artifact tool takes.
ArtifactAction = Literal["publish", "list", "read", "delete", "rename"]
ARTIFACT_ACTION_ARGUMENTS: dict[ArtifactAction, frozenset[str]] = {
    "publish": frozenset({*ARTIFACT_PUBLISH_PATHS, "title", "url", "force"}),
    "list": frozenset({"scope", "type", "query", "limit", "after"}),
    "read": frozenset({"url", "path", "paths", "out_dir"}),
    "delete": frozenset({"url"}),
    "rename": frozenset({"url", "name"}),
}


class ArtifactArguments(BaseModel):
    """The arguments of the artifact tool: an action and the arguments of
    each action. Each action takes only its own arguments
    (ARTIFACT_ACTION_ARGUMENTS)."""

    model_config = ConfigDict(extra="forbid")

    action: ArtifactAction = Field(
        default="publish",
        description="publish (the default) gives files from the VM to the user; "
        "list finds published files; read copies published files into the VM; "
        "delete deletes a published file, after the user approves; rename "
        "renames a published file.",
    )
    file_path: _EchoedText | None = Field(
        default=None,
        description="publish: a file in the VM, relative to the working "
        "directory or absolute.",
    )
    file_paths: list[_EchoedText] | None = Field(
        default=None,
        description=f"publish: up to {PUBLISH_FILES_MAX_FILES} files instead of "
        "file_path; all are published, or none.",
    )
    title: str | None = Field(
        default=None, description="publish with file_path: a short title."
    )
    url: _EchoedText | None = Field(
        default=None,
        description="read: the url of a published file from an earlier result; "
        "one that ends in /v<N> names that version. publish with file_path: "
        "the file to add a version to, by the url of the version you last saw. "
        "delete: the file to delete, with all its versions, by the url of its "
        "newest version. rename: the file to rename.",
    )
    name: _EchoedText | None = Field(
        default=None,
        description="rename: the new file name, not a path, with the current "
        "extension.",
    )
    force: bool | None = Field(
        default=None,
        description="publish with url: add the version even when the file has a "
        "newer version than the url names. Older versions stay.",
    )
    path: _EchoedText | None = Field(
        default=None, description="read: a file ID, or the url of a published file."
    )
    paths: list[_EchoedText] | None = Field(
        default=None,
        description=f"read: up to {ARTIFACTS_MATERIALIZE_MAX_ITEMS} file IDs or urls.",
    )
    out_dir: _EchoedText | None = Field(
        default=None,
        description="read: the directory for the copies, relative to the "
        "working directory.",
    )
    scope: Literal["mine"] | None = Field(
        default=None, description="list: only mine, the user's own files."
    )
    type: ArtifactType | None = Field(
        default=None, description="list: only files of this type."
    )
    query: str | None = Field(
        default=None,
        description="list: text to find in the file name, the file's title or "
        "the chat's title.",
    )
    limit: int | None = Field(
        default=None,
        description=f"list: the most files, from 1 to {ARTIFACTS_LIST_MAX_LIMIT}.",
    )
    after: str | None = Field(
        default=None, description="list: the next_cursor of the previous page."
    )

    @model_validator(mode="after")
    def _action_arguments(self) -> "ArtifactArguments":
        takes = ARTIFACT_ACTION_ARGUMENTS[self.action]
        extra = sorted(
            name
            for name, value in self
            if value is not None and name != "action" and name not in takes
        )
        if extra:
            raise PydanticCustomError(
                "action_arguments",
                "Action {action} does not take {extra}; it takes {takes}",
                {
                    "action": self.action,
                    "extra": ", ".join(extra),
                    "takes": ", ".join(sorted(takes)),
                },
            )
        if self.action in ("delete", "rename") and self.url is None:
            raise PydanticCustomError(
                "action_arguments", "{action} takes url", {"action": self.action}
            )
        if self.action == "rename" and self.name is None:
            raise PydanticCustomError("action_arguments", "rename takes url and name")
        return self


class PublishedArtifact(BaseModel):
    """A file that a publish gave the user."""

    library_file_id: UUID
    file_id: str
    version_number: int
    file_name: str
    title: str | None
    # published_display_path of the artifact's path.
    path: str
    url: str


class ArtifactPublished(BaseModel):
    """What a publish or replace returns to the model, in both tool
    families."""

    files: list[PublishedArtifact]

    @classmethod
    def of(cls, published: list[PublishedFile]) -> "ArtifactPublished":
        return cls(
            files=[
                PublishedArtifact(
                    library_file_id=file.artifact_id,
                    file_id=file.file_id,
                    version_number=file.version,
                    file_name=file.name,
                    title=file.title,
                    path=published_display_path(file.path),
                    url=artifact_url(file.artifact_id, file.version),
                )
                for file in published
                # A new publish always has both.
                if file.artifact_id is not None and file.version is not None
            ]
        )
