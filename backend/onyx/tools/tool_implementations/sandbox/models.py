"""Arguments and result details of the sandbox tools (sandbox_tools.py), the
browser tools' arguments (browser_tools.py), and
the chat file copies (file_copies.py). The saved-details unions import it,
so it imports only models and constants."""

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import (
    AfterValidator,
    AliasGenerator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    computed_field,
    model_validator,
)
from pydantic.alias_generators import to_camel

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.prompts.browser_tools import TAB_ARGUMENT, TIMEOUT_ARGUMENT, URL_ARGUMENT
from onyx.server.features.build.sandbox.harness_base import (
    ARTIFACT_FILES_DIR,
    CHAT_FILES_DIR,
)
from onyx.server.features.build.sandbox.models import (
    SESSION_WORKSPACE_ROOT,
    ExecCompletionName,
)
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
    """What a code mode program receives from the shell tools (SHELL_SHAPES)."""

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
    """Saved details of a call of a shell tool (SHELL_SHAPES)."""

    type: Literal["sandbox_exec"] = "sandbox_exec"
    # `output` is not all of the output: the call's output budget cut it,
    # the byte cap (EXEC_CALL_OUTPUT_MAX_BYTES) dropped some, or the daemon
    # lost some. In the full value, only the last two.
    truncated: bool = False
    # Set, with an empty `output`, when the output went to the sandbox VM.
    spilled: Annotated[SpilledOutput | None, OMITTED_WHEN_NONE] = None


class CommandApprovalRequest(BaseModel):
    """Progress of an exec_command or write_stdin call: an app request of
    its command waits in the egress proxy for the user's decision
    (command_approvals.py)."""

    approval_id: str
    app_name: str
    action_type: str
    display_name: str
    # Method, path and body of the request.
    arguments: dict[str, JsonValue]
    can_approve_for_command: bool
    # When the proxy stops waiting and the request expires.
    expires_at: datetime


CommandApprovalOutcome = Literal[
    "approved", "approved_for_command", "rejected", "disabled", "cancelled"
]


class CommandApprovalResolved(BaseModel):
    """Progress of the call: a request of its command stopped waiting."""

    approval_id: str
    outcome: CommandApprovalOutcome


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
# Most files that one publish call publishes.
PUBLISH_FILES_MAX_FILES = 25
# Longest title that a publish keeps; it cuts a longer one.
PUBLISH_FILES_MAX_TITLE_CHARS = 200
# Longest version_reason that a save keeps; it cuts a longer one.
VERSION_REASON_MAX_CHARS = 500
_VERSION_REASON = "A short note on why this version exists, for the version history."


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
        default=None,
        description="One sentence about the files. Accepted, not shown.",
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
# The longest library_search query, and the longest name, path and chat
# title that a page keeps; a version's title is at most
# PUBLISH_FILES_MAX_TITLE_CHARS. ARTIFACTS_PATH_MAX_CHARS also bounds each
# path, url, file ID or name that the artifact tool takes: its results echo
# them and are never spilled.
ARTIFACTS_QUERY_MAX_CHARS = 200
ARTIFACTS_NAME_MAX_CHARS = 200
ARTIFACTS_PATH_MAX_CHARS = 300
ARTIFACTS_CHAT_TITLE_MAX_CHARS = 200
# The most extensions that one file type filter takes.
ARTIFACTS_MAX_FILE_TYPES = 50
# The longest result of a list, search, read or find: a list or search page
# drops its last entries to fit, and a read or find stops its text there.
# Below spill.RESULT_MAX_CHARS, the spill limit of one result, and the spill
# exempts these tools, so the step's budget does not spill one either.
ARTIFACT_RESULT_MAX_CHARS = 40_000
# Model text that a result or its error can echo. Such a result may never
# spill, so the text has a cap.
EchoedText = Annotated[str, Field(max_length=ARTIFACTS_PATH_MAX_CHARS)]

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
    chat_id: EchoedText | None = Field(
        default=None,
        description="List only the files of this chat (a chat_id of an entry).",
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
    version_reason: str | None = Field(default=None, description=_VERSION_REASON)


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


class ChatDeleted(ArtifactNotFound):
    """The chat of a publish is gone or deleted; nothing was saved."""

    def __init__(self, chat_session_id: UUID) -> None:
        Exception.__init__(self, f"The chat {chat_session_id} is deleted")


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
    """A published file in an library_list page, or the file that a copy,
    read or find looks up: one version of an artifact."""

    # The artifact's ID, the same for every version.
    library_file_id: UUID
    file_id: str
    # More than 1: older versions exist.
    version_number: int
    # The artifact's newest available version, in a lookup
    # (db/chat.py:get_user_published_file); a list page has none, because
    # it shows the newest.
    latest_version_number: Annotated[int | None, OMITTED_WHEN_NONE] = None
    # The artifact's name: a rename's, else the file record's. A result
    # shows it, the chat title and the path cut (shown_artifact).
    file_name: str
    title: str | None
    artifact_type: ArtifactType
    mime_type: str
    file_size_bytes: int
    # The artifact's first publish and latest change (publish or rename).
    created_at: datetime
    modified_at: datetime
    chat_id: UUID
    chat_title: str | None
    # published_display_path of the artifact's path.
    path: str
    # artifact_url of this version.
    url: str


def shown_artifact(artifact: ListedArtifact) -> ListedArtifact:
    """`artifact` as a list page, read or find shows it: its name and chat
    title cut to ARTIFACTS_NAME_MAX_CHARS and ARTIFACTS_CHAT_TITLE_MAX_CHARS,
    and a longer path to its last ARTIFACTS_PATH_MAX_CHARS."""
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

    file_id: EchoedText | None = Field(
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


def parse_file_reference(text: str) -> ArtifactFileReference:
    """The published file version that `text` names: the url of an artifact
    or of one of its versions, or else a version's file ID."""
    try:
        artifact_id, version = parse_artifact_url(text)
    except ValueError:
        return ArtifactFileReference(file_id=text)
    return ArtifactFileReference(library_file_id=artifact_id, version_number=version)


class MaterializeItem(ArtifactFileReference):
    """One file to copy, and the name and directory of the copy."""

    file_name: EchoedText | None = Field(
        default=None,
        description="The name of the copy, not a path. Defaults to the file's name.",
    )
    relative_directory: EchoedText | None = Field(
        default=None,
        description="A directory relative to the destination directory, "
        f"{_DIRECTORY_RULE}. `..` is allowed while the path stays there.",
    )


ConflictPolicy = Literal["dedupe", "overwrite", "error"]


class MaterializeDestination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: EchoedText | None = Field(
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
    new_name: EchoedText = Field(
        description="The new file name, not a path, with the current extension."
    )


_EXPECTED_CURRENT_VERSION = (
    "The version_number that you last read. The operation fails when the "
    "artifact has a newer one."
)
_NEW_FILE_NAME = (
    "Also renames the artifact: a file name, not a path, with the current "
    "extension. Defaults to the current name."
)


# Adds a copy of an older version as the newest version.
class RestoreVersionOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["restore_version"]
    library_file_id: UUID
    version_number: int = Field(description="The version to copy.")
    expected_current_version: int | None = Field(
        default=None, description=_EXPECTED_CURRENT_VERSION
    )
    file_name: EchoedText | None = Field(default=None, description=_NEW_FILE_NAME)
    version_reason: str | None = Field(default=None, description=_VERSION_REASON)


# A stored file by its ID. The stored record gives its size and type, so the
# ones given here are not used.
class FileUri(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: EchoedText = Field(
        description="The file ID of a version of any of your published files, "
        "or its url."
    )
    # Not used: the operation's own file_name renames.
    file_name: str | None = None
    file_size_bytes: int | None = None
    mime_type: str | None = None


# Adds a copy of a stored version, of this or another artifact, as the newest
# version.
class UpdateOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["update"]
    library_file_id: UUID
    file_uri: FileUri
    file_name: EchoedText | None = Field(default=None, description=_NEW_FILE_NAME)
    expected_current_version: int | None = Field(
        default=None, description=_EXPECTED_CURRENT_VERSION
    )
    version_reason: str | None = Field(default=None, description=_VERSION_REASON)


ManageOperation = Annotated[
    DeleteOperation | RenameOperation | RestoreVersionOperation | UpdateOperation,
    Field(discriminator="operation"),
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

    operation: Literal["delete", "rename", "restore_version", "update"]
    ok: bool
    error: Annotated[str | None, OMITTED_WHEN_NONE] = None
    library_file_id: Annotated[UUID | None, OMITTED_WHEN_NONE] = None
    # The artifact's version that the operation read or added.
    file_id: Annotated[str | None, OMITTED_WHEN_NONE] = None
    version_number: Annotated[int | None, OMITTED_WHEN_NONE] = None
    file_name: Annotated[str | None, OMITTED_WHEN_NONE] = None
    url: Annotated[str | None, OMITTED_WHEN_NONE] = None
    # The added version's, as saved.
    version_reason: Annotated[str | None, OMITTED_WHEN_NONE] = None
    # A delete's: the versions that it deleted.
    deleted_versions: Annotated[int | None, OMITTED_WHEN_NONE] = None


class ManageResults(BaseModel):
    """What library_manage_library returns."""

    results: list[ManageResult]


# library_read and library_find: the most items of one call.
ARTIFACT_TEXT_MAX_ITEMS = 5
# library_read: the lines of an item by default and at most, and the longest
# line that it shows whole.
READ_DEFAULT_LINES = 400
READ_MAX_LINES = 2_000
READ_LINE_MAX_CHARS = 1_000
# library_find: the longest pattern, the matches of an item by default and
# at most, the context lines on each side at most, the longest line that it
# shows whole, and the time that the matching of one item may take.
FIND_PATTERN_MAX_CHARS = 500
FIND_DEFAULT_MATCHES = 20
FIND_MAX_MATCHES = 100
FIND_MAX_CONTEXT_LINES = 5
FIND_LINE_MAX_CHARS = 400
FIND_TIMEOUT_SECONDS = 1.0


class ReadItem(ArtifactFileReference):
    mode: Literal["lines", "pages"] = Field(
        default="lines",
        description="lines reads max_lines from start_line; pages reads whole "
        "pages start_page to end_page of a PDF, a slide deck or a spreadsheet "
        "(one page per sheet), from start_line, which must be inside them.",
    )
    start_line: int = Field(
        default=1,
        ge=1,
        description="lines: the first line. pages: the next_start_line of a "
        "result that the limit cut, with the same pages, to read on to their end.",
    )
    max_lines: int = Field(
        default=READ_DEFAULT_LINES,
        ge=1,
        le=READ_MAX_LINES,
        description=f"lines: the most lines, at most {READ_MAX_LINES}.",
    )
    start_page: int = Field(default=1, ge=1, description="pages: the first page.")
    end_page: int | None = Field(
        default=None,
        ge=1,
        description="pages: the last page. Defaults to start_page.",
    )

    @model_validator(mode="after")
    def _forward_pages(self) -> "ReadItem":
        if self.end_page is not None and self.end_page < self.start_page:
            raise ValueError("end_page comes before start_page")
        return self


class LibraryReadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    read: list[ReadItem] = Field(
        min_length=1,
        max_length=ARTIFACT_TEXT_MAX_ITEMS,
        description="The files to read, in order.",
    )


class FindItem(ArtifactFileReference):
    pattern: str = Field(
        min_length=1,
        max_length=FIND_PATTERN_MAX_CHARS,
        description="The text to find in each line.",
    )
    regex: bool = Field(
        default=False, description="The pattern is a regular expression."
    )
    case_sensitive: bool = False
    start_line: int | None = Field(
        default=None,
        ge=1,
        description="Search from this line; after a timed_out result with no "
        "next_match_offset, its reached_line.",
    )
    end_line: int | None = Field(default=None, ge=1, description="Search to this line.")
    start_page: int | None = Field(
        default=None, ge=1, description="Search from this page."
    )
    end_page: int | None = Field(default=None, ge=1, description="Search to this page.")
    context_before_lines: int = Field(
        default=0,
        ge=0,
        le=FIND_MAX_CONTEXT_LINES,
        description="Lines to show before each match.",
    )
    context_after_lines: int = Field(
        default=0,
        ge=0,
        le=FIND_MAX_CONTEXT_LINES,
        description="Lines to show after each match.",
    )
    max_matches: int = Field(
        default=FIND_DEFAULT_MATCHES,
        ge=1,
        le=FIND_MAX_MATCHES,
        description=f"The most matches to return, at most {FIND_MAX_MATCHES}.",
    )
    match_offset: int = Field(
        default=0,
        ge=0,
        description="Skip this many matches: the next_match_offset of the "
        "previous result.",
    )

    @model_validator(mode="after")
    def _forward_ranges(self) -> "FindItem":
        for start, end, name in (
            (self.start_line, self.end_line, "line"),
            (self.start_page, self.end_page, "page"),
        ):
            if start is not None and end is not None and end < start:
                raise ValueError(f"end_{name} comes before start_{name}")
        return self


class LibraryFindArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    find: list[FindItem] = Field(
        min_length=1,
        max_length=ARTIFACT_TEXT_MAX_ITEMS,
        description="The files to search, in order.",
    )


class ReadText(BaseModel):
    """The text of one library_read item."""

    file: ListedArtifact
    total_lines: int
    # None: the file's format has no pages.
    total_pages: int | None
    start_line: int
    # The last line shown; start_line - 1 when none is.
    end_line: int
    # Numbered lines, as `cat -n` prints them, with a `--- page N ---` line
    # where each page starts.
    text: str
    # The next line to read; None: the text ends at the file's last line, or
    # in pages mode at the last line of the pages.
    next_start_line: int | None
    # The stored text stopped at ARTIFACT_TEXT_MAX_CHARS, or a sheet stopped
    # at MAX_XLSX_CELLS_PER_SHEET.
    truncated: bool


class ArtifactsRead(BaseModel):
    """What library_read returns."""

    items: list[ReadText]


class FindMatch(BaseModel):
    """A line that matches; a long line shows its part around the match."""

    line: int
    page: Annotated[int | None, OMITTED_WHEN_NONE] = None
    text: str
    before: list[str]
    after: list[str]


class FoundText(BaseModel):
    """The matches of one library_find item."""

    file: ListedArtifact
    # The matching lines that the search reached, the skipped ones included.
    total_matches_seen: int
    matches: list[FindMatch]
    # The match_offset that shows the next matches; None: no more.
    next_match_offset: int | None
    # The search stopped at its time limit, before the line `reached_line`.
    # Matches before it can be unshown (next_match_offset); once those are
    # shown, a search from start_line=reached_line, match_offset 0, continues.
    timed_out: bool
    reached_line: Annotated[int | None, OMITTED_WHEN_NONE] = None
    # The stored text stopped at ARTIFACT_TEXT_MAX_CHARS, or a sheet stopped
    # at MAX_XLSX_CELLS_PER_SHEET.
    truncated: bool


class ArtifactsFound(BaseModel):
    """What library_find returns."""

    items: list[FoundText]


# library_search: the most queries and file references of one call; the
# results by default and at most on one page; the files that a search ranks
# (its window), which its pages and sorts go through; the newest files of the
# user that a search reaches; the chunks that each retrieval of a content
# query gives and the most retrievals of one query; the snippets of a file
# and the longest snippet.
LIBRARY_SEARCH_MAX_QUERIES = 3
LIBRARY_SEARCH_MAX_FILE_REFS = 20
LIBRARY_SEARCH_DEFAULT_TOP_K = 10
LIBRARY_SEARCH_MAX_TOP_K = 25
LIBRARY_SEARCH_WINDOW = 100
LIBRARY_SEARCH_MAX_CANDIDATES = 10_000
LIBRARY_SEARCH_CHUNKS_PER_QUERY = 100
LIBRARY_SEARCH_RETRIEVALS_PER_QUERY = 3
LIBRARY_SEARCH_MAX_SNIPPETS = 3
LIBRARY_SEARCH_SNIPPET_MAX_CHARS = 300

LibrarySearchSort = Literal["relevance", ArtifactSort]


class LibrarySearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=ARTIFACTS_QUERY_MAX_CHARS
        ),
    ] = Field(
        description="What to find: words or a question about the content, or "
        "words of the name or title."
    )
    search_title_only: bool = Field(
        default=False,
        description="Match every word in the file name, the file's title or "
        "the chat's title, not the content.",
    )


class LibrarySearchScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_refs: list[ArtifactFileReference] = Field(
        min_length=1,
        max_length=LIBRARY_SEARCH_MAX_FILE_REFS,
        description="Search only these files, each at its newest version.",
    )


class LibrarySearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_query: list[LibrarySearchQuery] = Field(
        min_length=1,
        max_length=LIBRARY_SEARCH_MAX_QUERIES,
        description="One to three queries; a file that matches several ranks higher.",
    )
    filters: LibraryListFilters | None = None
    scope: LibrarySearchScope | None = None
    chat_id: EchoedText | None = Field(
        default=None,
        description="Search only the files of this chat (a chat_id of a result).",
    )
    result_format: Literal["snippets", "metadata_only"] = Field(
        default="snippets",
        description="metadata_only leaves out the snippets.",
    )
    sort: LibrarySearchSort = Field(
        default="relevance",
        description="relevance: best match first. The others match content "
        "by its words only, and order the best matches by first publish "
        "(created_at), latest change, a publish or rename (modified_at), file "
        "name or size.",
    )
    sort_order: SortOrder = Field(
        default="desc", description="For the sorts other than relevance."
    )
    # The tool clamps top_k.
    top_k: int = Field(
        default=LIBRARY_SEARCH_DEFAULT_TOP_K,
        description=f"The most results, from 1 to {LIBRARY_SEARCH_MAX_TOP_K}.",
    )
    cursor: str | None = Field(
        default=None,
        description="The next_cursor of the previous page, with the same "
        "arguments otherwise.",
    )


class LibrarySearchCursor(BaseModel):
    """Where the next page of a search starts in its window. A cursor is its
    JSON in base64url."""

    offset: int = Field(ge=0)


class LibrarySearchHit(BaseModel):
    """A file that a search found, at its newest available version."""

    file: ListedArtifact
    # The fused rank score (reciprocal rank fusion over the queries).
    score: float
    # False: the newest version is not in the search index yet, so the
    # content search missed it or matched an older version.
    content_indexed: bool
    # Text of the file's best matching chunks; none for metadata_only.
    snippets: Annotated[list[str] | None, OMITTED_WHEN_NONE] = None


class LibrarySearchResult(BaseModel):
    """What library_search returns."""

    results: list[LibrarySearchHit]
    # None: no more results.
    next_cursor: str | None
    # False: the user has more than LIBRARY_SEARCH_MAX_CANDIDATES files in
    # scope, and only the newest were searched.
    complete: bool
    # Set when the deployment has no search index: only names and titles
    # matched.
    content_search: Annotated[Literal["unavailable"] | None, OMITTED_WHEN_NONE] = None


# The arguments of each operation over the user's published files
# (artifact_operations.run_operation): each library tool takes one, and the
# artifact tool's arguments give one (ArtifactArguments.request).
LibraryRequest = (
    LibraryCreateLibraryFileArguments
    | LibraryReplaceLibraryFileArguments
    | ManageLibraryArguments
    | LibraryListArguments
    | LibrarySearchArguments
    | LibraryReadArguments
    | LibraryFindArguments
    | LibraryPrepareMaterializeArguments
)


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


# Browser tool input limits, in characters (and list items).
_BROWSER_MAX_URL_CHARS = 8192
_BROWSER_MAX_TEXT_CHARS = 64_000
_BROWSER_MAX_SELECTOR_CHARS = 2048
_BROWSER_MAX_LIST_ITEMS = 100
_BROWSER_MAX_UPLOAD_PATHS = 20
# The service's default and largest wait of one call.
BROWSER_DEFAULT_TIMEOUT_MS = 15_000
BROWSER_MAX_TIMEOUT_MS = 60_000

BrowserAction = Literal[
    "click", "type", "hover", "select", "drag", "press", "scroll", "upload"
]
Modifier = Literal["Alt", "Control", "Meta", "Shift"]


class BrowserArguments(BaseModel):
    """The model names the arguments in snake_case, and the service takes
    them in camelCase (the serialization alias)."""

    model_config = ConfigDict(
        extra="forbid",
        alias_generator=AliasGenerator(serialization_alias=to_camel),
    )


class BrowserTabArguments(BrowserArguments):
    tab: str | None = Field(
        default=None, max_length=_BROWSER_MAX_SELECTOR_CHARS, description=TAB_ARGUMENT
    )


class BrowserTimeoutArguments(BrowserTabArguments):
    timeout_ms: int | None = Field(
        default=None, ge=1, le=BROWSER_MAX_TIMEOUT_MS, description=TIMEOUT_ARGUMENT
    )


class BrowserStatusArguments(BrowserArguments):
    pass


class BrowserOpenArguments(BrowserArguments):
    url: str | None = Field(
        default=None,
        max_length=_BROWSER_MAX_URL_CHARS,
        description=f"Page to open. {URL_ARGUMENT} Omit for a blank tab.",
    )
    new_tab: bool = Field(
        default=False,
        description="Open a new tab instead of reusing your current tab, for "
        "example when a human controls it.",
    )


class BrowserNavigateArguments(BrowserTimeoutArguments):
    url: str | None = Field(
        default=None, max_length=_BROWSER_MAX_URL_CHARS, description=URL_ARGUMENT
    )
    history: Literal["back", "forward", "reload"] | None = Field(
        default=None, description="Go back, forward, or reload."
    )

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.url is None) == (self.history is None):
            raise ValueError("pass exactly one of url and history")
        return self


class BrowserSnapshotArguments(BrowserTabArguments):
    screenshot_path: str | None = Field(
        default=None,
        max_length=_BROWSER_MAX_SELECTOR_CHARS,
        description="Also write a PNG screenshot to this path in the working "
        "directory.",
    )


class BrowserActArguments(BrowserTimeoutArguments):
    action: BrowserAction
    ref: str | None = Field(
        default=None,
        max_length=_BROWSER_MAX_SELECTOR_CHARS,
        description="Element ref from browser_snapshot.",
    )
    selector: str | None = Field(
        default=None,
        max_length=_BROWSER_MAX_SELECTOR_CHARS,
        description="CSS selector.",
    )
    x: float | None = None
    y: float | None = None
    button: Literal["left", "right", "middle"] | None = Field(
        default=None, description="Default left. Right opens the menu."
    )
    click_count: int | None = Field(
        default=None, description="1 click, 2 double, 3 triple. Default 1."
    )
    text: str | None = Field(default=None, max_length=_BROWSER_MAX_TEXT_CHARS)
    clear: bool | None = Field(
        default=None, description="Clear the input first. Default false."
    )
    values: list[str] | None = Field(default=None, max_length=_BROWSER_MAX_LIST_ITEMS)
    target_ref: str | None = Field(
        default=None,
        max_length=_BROWSER_MAX_SELECTOR_CHARS,
        description="drag: the element ref to drop onto.",
    )
    key: str | None = Field(default=None, max_length=_BROWSER_MAX_SELECTOR_CHARS)
    modifiers: list[Modifier] | None = None
    delta_x: float | None = None
    delta_y: float | None = None
    paths: list[str] | None = Field(
        default=None,
        max_length=_BROWSER_MAX_UPLOAD_PATHS,
        description="upload: files in the working directory.",
    )

    @model_validator(mode="after")
    def _paired_coordinates(self) -> Self:
        if (self.x is None) != (self.y is None):
            raise ValueError("x and y go together")
        return self


class BrowserWaitForArguments(BrowserTimeoutArguments):
    ref: str | None = Field(
        default=None,
        max_length=_BROWSER_MAX_SELECTOR_CHARS,
        description="Element ref from browser_snapshot.",
    )
    selector: str | None = Field(
        default=None,
        max_length=_BROWSER_MAX_SELECTOR_CHARS,
        description="CSS selector.",
    )
    text: str | None = Field(
        default=None, max_length=_BROWSER_MAX_TEXT_CHARS, description="Case counts."
    )
    url_includes: str | None = Field(default=None, max_length=_BROWSER_MAX_URL_CHARS)

    @model_validator(mode="after")
    def _some_condition(self) -> Self:
        if (
            self.ref is None
            and self.selector is None
            and self.text is None
            and self.url_includes is None
        ):
            raise ValueError("pass at least one wait condition")
        return self


class BrowserEvaluateArguments(BrowserTimeoutArguments):
    expression: str = Field(
        min_length=1,
        max_length=_BROWSER_MAX_TEXT_CHARS,
        description="JavaScript expression; a promise is awaited.",
    )


class BrowserDialogArguments(BrowserTabArguments):
    accept: bool
    prompt_text: str | None = Field(default=None, max_length=_BROWSER_MAX_TEXT_CHARS)
