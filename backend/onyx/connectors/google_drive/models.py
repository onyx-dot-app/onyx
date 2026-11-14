from collections.abc import Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from onyx.connectors.google_utils.shared_constants import GoogleCredentialKind
from onyx.connectors.interfaces import ConnectorCheckpoint
from onyx.connectors.models import DocumentTypeLabel, ListingPayload
from onyx.utils.threadpool_concurrency import ThreadSafeDict, ThreadSafeSet


class GDriveMimeType(str, Enum):
    DOC = "application/vnd.google-apps.document"
    SPREADSHEET = "application/vnd.google-apps.spreadsheet"
    SPREADSHEET_OPEN_FORMAT = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    SPREADSHEET_MS_EXCEL = "application/vnd.ms-excel"
    PDF = "application/pdf"
    WORD_DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    PPT = "application/vnd.google-apps.presentation"
    FORM = "application/vnd.google-apps.form"
    POWERPOINT = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    PLAIN_TEXT = "text/plain"
    MARKDOWN = "text/markdown"


GoogleDriveFileType = dict[str, Any]


class ImpersonationError(Exception):
    """Raised when the service account cannot impersonate a user."""

    def __init__(self, user_email: str, original: Exception) -> None:
        super().__init__(f"Cannot impersonate '{user_email}'")
        self.user_email = user_email
        self.original = original


class UserRemovedError(ImpersonationError):
    """Raised when the impersonation failure is confirmed to be a deleted/suspended user."""


def make_user_removal_checker(
    user_email: str,
    get_fresh_emails: Callable[[], list[str]] | None = None,
) -> Callable[[], bool]:
    """Return a callable that checks whether user_email was removed from the workspace.

    The Admin SDK callback is fired at most once regardless of how many times
    the returned callable is invoked.
    """
    checked = False
    user_removed = False

    def is_user_removed() -> bool:
        nonlocal checked, user_removed
        if not checked:
            checked = True
            if get_fresh_emails is not None:
                try:
                    user_removed = user_email not in get_fresh_emails()
                except Exception:
                    pass
        return user_removed

    return is_user_removed


class DriveBatchResult(BaseModel):
    """Files read in a batch request, and the errors of the reads that failed,
    keyed by the caller's key."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    files: dict[str, GoogleDriveFileType] = Field(default_factory=dict)
    errors: dict[str, Exception] = Field(default_factory=dict)


TOKEN_EXPIRATION_TIME = 3600  # 1 hour


class RetrievedDriveFile(BaseModel):
    """
    Describes a file that has been retrieved from google drive.
    user_email is the email of the user that the file was retrieved
    by impersonating. If an error worthy of being reported is encountered,
    error should be set and later propagated as a ConnectorFailure.
    """

    # The file that was retrieved
    drive_file: GoogleDriveFileType

    # The email of the user that the file was retrieved by impersonating
    user_email: str

    # The id of the parent folder or drive of the file
    parent_id: str | None = None

    # Any unexpected error that occurred while retrieving the file.
    # In particular, this is not used for 403/404 errors, which are expected
    # in the context of impersonating all the users to try to retrieve all
    # files from all their Drives and Folders.
    error: Exception | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class DriveListingPayload(ListingPayload):
    # The user whose listing returned the file. This user can read it.
    retriever_email: str


class ListingPartitionKind(str, Enum):
    """What one partition of the parallel listing lists."""

    # A shared drive, listed as one of its members.
    SHARED_DRIVE = "shared_drive"
    # The files a user owns.
    MY_DRIVE = "my_drive"
    # All files a user sees. Files that another partition covers are dropped.
    SHARED_WITH_USER = "shared_with_user"
    # A requested folder and every folder under it, listed one folder at a
    # time. Files that another partition covers are dropped.
    FOLDER_SUBTREE = "folder_subtree"


class ListingPartition(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ListingPartitionKind
    # A drive id for a shared drive, a folder id for a folder subtree, a user
    # email for the other kinds.
    key: str


class ListingShardKind(str, Enum):
    # Files other than folders, in the shard's modifiedTime range.
    FILES = "files"
    # All folders of the partition, or with folder_id the subfolders of one
    # folder. It has no time range and does not split.
    FOLDERS = "folders"
    # The files in the shard's range and the subfolders of one folder of a
    # folder subtree. A folder with more than one page becomes a FILES and a
    # FOLDERS shard of that folder.
    SUBTREE = "subtree"


class ListingShard(BaseModel):
    """One listing of a partition over the modifiedTime range [t0, t1), in
    whole milliseconds. The ranges of a partition's open shards do not
    overlap, and together they cover what is still to list."""

    id: int
    partition: ListingPartition
    # The user the shard lists as.
    principal: str
    kind: ListingShardKind = ListingShardKind.FILES
    t0: int
    t1: int
    # The page to list next. None for the first page.
    page_token: str | None = None
    # The newest modifiedTime in the partition, when it was read. It only
    # steers where a split puts its cuts. A wrong value loses no file.
    newest_ms: int | None = None
    # The partition owns the files this shard lists, so they need no dedup.
    exact: bool = True
    # The newest modifiedTime of the pages this shard kept, and the ids it
    # kept at that time. A split on a later page starts there.
    frontier_ms: int | None = None
    frontier_ids: list[str] = []
    # True when more files share the frontier time than the shard keeps ids
    # for. A page that starts at that time cannot split. A page that starts
    # later can, because it needs no ids.
    frontier_overflow: bool = False
    # False when a page had a file older than the frontier. A later page
    # then cannot split.
    in_order: bool = True
    # Files on the pages this shard kept, and the oldest modifiedTime among
    # them. With the frontier they give the density of the range so far.
    kept_files: int = 0
    kept_since_ms: int | None = None
    # Ids at the start of the range that an earlier shard already listed.
    skip_ids: list[str] = []
    # Lists only the files of this owner. Set on a shared-with-user shard
    # that lists again the files of an owner whose My Drive partition failed.
    owner_filter: str | None = None
    # True when the shard has no upper bound: it lists every file modified at
    # t0 or later, and t1 is not used. Such a shard does not split.
    open_end: bool = False
    # The folder whose children the shard lists. Set on each shard of a
    # folder subtree.
    folder_id: str | None = None
    # The folders that this walk reached through a shortcut, from the root
    # down. A shortcut to one of them, or to the root, is not followed again,
    # so a shortcut cycle ends.
    shortcut_path: list[str] = []


class DriveListingState(BaseModel):
    """Checkpoint of the parallel sharded listing (the service account flow).
    Its size follows the drives, the users and the open shards, not the
    files."""

    # The window of the listing, [t0, t1) in milliseconds.
    window_t0: int
    window_t1: int
    # Partitions with no shard yet, in the order they start.
    pending_partitions: list[ListingPartition] = []
    # Partitions whose listing began, with the user and whether it is exact.
    # A later call with a later window end adds a shard for each of them.
    started_partitions: list[tuple[ListingPartition, str, bool]] = []
    # Open shards by id.
    shards: dict[int, ListingShard] = {}
    next_shard_id: int = 0
    # Coverage: drives (complete listings only) and owners whose listing has
    # begun. A copy of their files on another path is dropped.
    listed_drive_ids: set[str] = set()
    listed_owners: set[str] = set()
    # The worker limit the last call ended with. The next call starts from it.
    concurrency_limit: int | None = None
    # Running count of the files the listing yielded that pass the metadata
    # check.
    docs_by_type: dict[DocumentTypeLabel, int] = {}
    # Bytes per type. Only files that Drive lists with a size add to it.
    bytes_by_type: dict[DocumentTypeLabel, int] = {}
    # True after open_window_end: shards that start from now on have no
    # upper bound.
    open_end: bool = False
    # Requested folder id -> shared drive id, for a folder that no usable
    # user can walk and that a full listing of its drive covers. If that
    # listing fails, the folder is unreachable.
    folders_covered_by_drive: dict[str, str] = {}
    # Parent folder id -> users who saw a child of it, for parents that no
    # folder listing has yielded yet. After the listing, only the ones still
    # missing are read with files.get, as each of these users in turn until
    # one can read the folder. Its size follows the folders.
    unresolved_parent_emails: dict[str, list[str]] = {}

    @field_validator("unresolved_parent_emails", mode="before")
    @classmethod
    def _one_email_to_list(cls, value: object) -> object:
        """A checkpoint from before this field held lists has one email."""
        if not isinstance(value, dict):
            return value
        return {
            parent_id: [emails] if isinstance(emails, str) else emails
            for parent_id, emails in value.items()
        }

    # Folder id -> the user who listed it, for folders yielded with no parent
    # because that user cannot see the parent. A later copy with the parent,
    # or a read after the listing, yields the folder again with it.
    parentless_folder_emails: dict[str, str] = {}

    @property
    def is_done(self) -> bool:
        return not self.pending_partitions and not self.shards

    @property
    def total_docs(self) -> int:
        return sum(self.docs_by_type.values())


class GoogleDriveCheckpoint(ConnectorCheckpoint):
    """The listing of one connector call. A checkpoint of the serial listing
    that came before parses with its old keys ignored, and the next call
    lists again from its window start."""

    # Drive file ids already yielded this run, used only for dedup. Previously
    # keyed on the document URL under the name `all_retrieved_file_ids`; the
    # rename is deliberate so checkpoints written by the old code deserialize
    # with an empty set rather than a set of keys in the other format.
    # Capped at MAX_DEDUP_DRIVE_FILE_IDS, so it is not a completeness record.
    retrieved_drive_file_ids: set[str] = set()

    # cached version of the drive and folder ids to retrieve
    drive_ids_to_retrieve: list[str] | None = None
    folder_ids_to_retrieve: list[str] | None = None

    # cached user emails
    user_emails: list[str] | None = None

    # --- Listing state. Sized by drives and users, never by documents.

    # Drive id -> the email that listed it. A drive here and not in
    # incomplete_drive_ids is fully covered.
    organizer_email_by_drive_id: dict[str, str] = {}

    # Drives listed by someone who is not an organizer, or by nobody, so
    # limited-access folders may be missing.
    incomplete_drive_ids: set[str] = set()

    # Users whose impersonation failed this run. Their files are not covered by
    # an owner pass, so other users' listings must not drop them.
    failed_impersonation_emails: set[str] = set()

    # Requested drives and folders that no impersonable user could reach.
    # Pruning refuses to run while this is non-empty, because absence from the
    # listing would delete every document indexed from them.
    unreachable_target_ids: set[str] = set()

    # State of the shard engine. None before the first call of an attempt.
    listing: DriveListingState | None = None

    # Hierarchy node raw IDs that have already been yielded.
    # Used to avoid yielding duplicate hierarchy nodes across checkpoints.
    # Thread-safe because multiple impersonation threads access this concurrently.
    # Uses default_factory to ensure each checkpoint instance gets a fresh set.
    seen_hierarchy_node_raw_ids: ThreadSafeSet[str] = Field(
        default_factory=ThreadSafeSet
    )

    # Hierarchy node raw IDs where we have successfully walked up to a terminal
    # node (a drive root with no parent). This is separate from seen_hierarchy_node_raw_ids
    # because a node might be yielded before we've walked its full ancestry chain.
    # We only skip walking from a node if it's in this set, ensuring that if one user
    # fails to walk to the root, another user with better access can still complete the walk.
    # Thread-safe because multiple impersonation threads access this concurrently.
    # Uses default_factory to ensure each checkpoint instance gets a fresh set.
    fully_walked_hierarchy_node_raw_ids: ThreadSafeSet[str] = Field(
        default_factory=ThreadSafeSet
    )

    # Maps email → set of folder IDs that email should skip when walking the
    # parent chain. Covers two cases:
    #   1. Folders where that email confirmed no accessible parent (true orphans).
    #   2. Intermediate folders on a path that dead-ended at a confirmed orphan —
    #      backfilled so future walks short-circuit earlier in the chain.
    # In both cases _get_folder_metadata skips the API call and returns None.
    failed_folder_ids_by_email: ThreadSafeDict[str, ThreadSafeSet[str]] = Field(
        default_factory=ThreadSafeDict
    )

    @field_serializer("seen_hierarchy_node_raw_ids")
    def serialize_seen_hierarchy(
        self, seen_hierarchy_node_raw_ids: ThreadSafeSet[str], _info: Any
    ) -> set[str]:
        return seen_hierarchy_node_raw_ids.copy()

    @field_serializer("fully_walked_hierarchy_node_raw_ids")
    def serialize_fully_walked_hierarchy(
        self, fully_walked_hierarchy_node_raw_ids: ThreadSafeSet[str], _info: Any
    ) -> set[str]:
        return fully_walked_hierarchy_node_raw_ids.copy()

    @field_validator("seen_hierarchy_node_raw_ids", mode="before")
    def validate_seen_hierarchy(cls, v: Any) -> ThreadSafeSet[str]:
        if isinstance(v, ThreadSafeSet):
            return v
        if isinstance(v, set):
            return ThreadSafeSet(v)
        if isinstance(v, list):
            return ThreadSafeSet(set(v))  # ty: ignore[invalid-return-type]
        return ThreadSafeSet()

    @field_validator("fully_walked_hierarchy_node_raw_ids", mode="before")
    def validate_fully_walked_hierarchy(cls, v: Any) -> ThreadSafeSet[str]:
        if isinstance(v, ThreadSafeSet):
            return v
        if isinstance(v, set):
            return ThreadSafeSet(v)
        if isinstance(v, list):
            return ThreadSafeSet(set(v))  # ty: ignore[invalid-return-type]
        return ThreadSafeSet()

    @field_serializer("failed_folder_ids_by_email")
    def serialize_failed_folder_ids_by_email(
        self,
        failed_folder_ids_by_email: ThreadSafeDict[str, ThreadSafeSet[str]],
        _info: Any,
    ) -> dict[str, set[str]]:
        return {
            k: inner.copy() for k, inner in failed_folder_ids_by_email.copy().items()
        }

    @field_validator("failed_folder_ids_by_email", mode="before")
    def validate_failed_folder_ids_by_email(
        cls, v: Any
    ) -> ThreadSafeDict[str, ThreadSafeSet[str]]:
        if isinstance(v, ThreadSafeDict):
            return v
        if isinstance(v, dict):
            return ThreadSafeDict(
                {k: ThreadSafeSet(set(vals)) for k, vals in v.items()}
            )
        return ThreadSafeDict()


class GoogleDriveAuth(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: GoogleCredentialKind
    primary_admin_email: str
    # The credential to store when loading it refreshed the OAuth token, else
    # None.
    refreshed_credential_json: dict[str, str] | None = None


class GoogleDirectoryUser(BaseModel):
    is_admin: bool
    is_delegated_admin: bool


class GoogleSharedDrive(BaseModel):
    id: str
    name: str


class GoogleGroupMember(BaseModel):
    email: str | None
    # USER, GROUP or CUSTOMER.
    type: str | None
