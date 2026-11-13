from collections.abc import Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from onyx.connectors.google_utils.shared_constants import GoogleCredentialKind
from onyx.connectors.interfaces import ConnectorCheckpoint, SecondsSinceUnixEpoch
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


# Stages of the OAuth flow:
# get_all_files_for_oauth(),
# get_all_drive_ids(),
# get_files_in_shared_drive(),
# crawl_folders_for_files()
#
# The service account flow advances through DriveRetrievalPhase instead. It
# still labels each RetrievedDriveFile with a stage, for error reporting, and
# sets completion_stage to DONE when its last phase ends.
class DriveRetrievalStage(str, Enum):
    START = "start"
    DONE = "done"
    # OAuth specific stages
    OAUTH_FILES = "oauth_files"

    # Service account specific stages
    USER_EMAILS = "user_emails"
    MY_DRIVE_FILES = "my_drive_files"

    # Used for both oauth and service account flows
    DRIVE_IDS = "drive_ids"
    SHARED_DRIVE_FILES = "shared_drive_files"
    FOLDER_FILES = "folder_files"


class DriveRetrievalPhase(str, Enum):
    """Phases of the redesigned retrieval, run once for the whole connector.

    This replaces the per-user DriveRetrievalStage loop, where every user walked
    every stage independently. One phase is active at a time, so a phase can be
    closed and its state dropped once it finishes.

    Shared drives run before My Drives on purpose: once the shared drive phase
    is done, later phases can discard any file whose driveId was already
    covered, which kills the shortcut duplication path with a check against a
    list of drive ids rather than a set of file ids.
    """

    INVENTORY = "inventory"
    SHARED_DRIVES = "shared_drives"
    MY_DRIVES = "my_drives"
    REQUESTED_TARGETS = "requested_targets"
    EXTERNAL_SHARES = "external_shares"
    DONE = "done"


# Order the connector advances through. INVENTORY collects the partition keys
# the later phases walk, so it has to come first.
PHASE_ORDER: tuple[DriveRetrievalPhase, ...] = (
    DriveRetrievalPhase.INVENTORY,
    DriveRetrievalPhase.SHARED_DRIVES,
    DriveRetrievalPhase.MY_DRIVES,
    DriveRetrievalPhase.REQUESTED_TARGETS,
    DriveRetrievalPhase.EXTERNAL_SHARES,
    DriveRetrievalPhase.DONE,
)


def next_phase(phase: DriveRetrievalPhase) -> DriveRetrievalPhase:
    if phase is DriveRetrievalPhase.DONE:
        return DriveRetrievalPhase.DONE
    return PHASE_ORDER[PHASE_ORDER.index(phase) + 1]


class PhaseProgress(BaseModel):
    """Position inside one phase: which partition, and where inside it.

    Every item belongs to exactly one partition (a drive id, or an owner email),
    so resuming needs only an index into a stable key list plus a page token.
    That is what keeps the checkpoint proportional to drives and users instead
    of to documents.
    """

    phase: DriveRetrievalPhase
    # Stable order. Built once when the phase starts so a resumed run walks the
    # same partitions in the same sequence.
    partition_keys: list[str] = []
    partition_index: int = Field(default=0, ge=0)
    # Resume point inside the current partition. The listing that produced it
    # must be repeated with the same query, so resumes reuse the run's range.
    next_page_token: str | None = None
    # Latest modifiedTime yielded in the current partition. Diagnostic only.
    completed_until: SecondsSinceUnixEpoch = 0

    @property
    def current_partition(self) -> str | None:
        if self.partition_index >= len(self.partition_keys):
            return None
        return self.partition_keys[self.partition_index]

    @property
    def is_complete(self) -> bool:
        return self.partition_index >= len(self.partition_keys)

    @property
    def remaining_partitions(self) -> list[str]:
        return self.partition_keys[self.partition_index :]

    def advance_partition(self) -> None:
        """Finish the current partition and reset the within-partition cursor."""
        self.partition_index += 1
        self.next_page_token = None
        self.completed_until = 0


# Requested target partitions pair a target id with the email that crawls it.
# Drive file ids never contain the separator, so splitting on the first one is
# safe for any email.
_TARGET_KEY_SEPARATOR = "|"


def target_partition_key(target_id: str, email: str) -> str:
    return f"{target_id}{_TARGET_KEY_SEPARATOR}{email}"


def split_target_partition_key(key: str) -> tuple[str, str]:
    target_id, email = key.split(_TARGET_KEY_SEPARATOR, 1)
    return target_id, email


class StageCompletion(BaseModel):
    """
    Describes the point in the retrieval+indexing process that the
    connector is at. completed_until is the timestamp of the latest
    file that has been retrieved or error that has been yielded.
    Optional fields are used for retrieval stages that need more information
    for resuming than just the timestamp of the latest file.
    """

    stage: DriveRetrievalStage
    completed_until: SecondsSinceUnixEpoch
    current_folder_or_drive_id: str | None = None
    next_page_token: str | None = None

    def update(
        self,
        stage: DriveRetrievalStage,
        completed_until: SecondsSinceUnixEpoch,
        current_folder_or_drive_id: str | None = None,
    ) -> None:
        self.stage = stage
        self.completed_until = completed_until
        self.current_folder_or_drive_id = current_folder_or_drive_id


class RetrievedDriveFile(BaseModel):
    """
    Describes a file that has been retrieved from google drive.
    user_email is the email of the user that the file was retrieved
    by impersonating. If an error worthy of being reported is encountered,
    error should be set and later propagated as a ConnectorFailure.
    """

    # The stage at which this file was retrieved
    completion_stage: DriveRetrievalStage

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


class ListingPartition(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ListingPartitionKind
    # A drive id for a shared drive, a user email for the other kinds.
    key: str


class ListingShardKind(str, Enum):
    FILES = "files"


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
    # Running count of the stubs the listing yielded.
    docs_by_type: dict[DocumentTypeLabel, int] = {}
    # Bytes per type. Only files that Drive lists with a size add to it.
    bytes_by_type: dict[DocumentTypeLabel, int] = {}

    @property
    def is_done(self) -> bool:
        return not self.pending_partitions and not self.shards

    @property
    def total_docs(self) -> int:
        return sum(self.docs_by_type.values())


class GoogleDriveCheckpoint(ConnectorCheckpoint):
    # Checkpoint version of _retrieved_ids
    retrieved_folder_and_drive_ids: set[str]

    # Describes the point in the retrieval+indexing process that the
    # checkpoint is at. when this is set to a given stage, the connector
    # has finished yielding all values from the previous stage.
    completion_stage: DriveRetrievalStage

    # The latest timestamp of a file that has been retrieved per user email.
    # StageCompletion is used to track the completion of each stage, but the
    # timestamp part is not used for folder crawling.
    completion_map: ThreadSafeDict[str, StageCompletion]

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

    # --- Phased retrieval state, used by the service account flow. Sized by
    # drives and users, never by documents.

    # None until the first phased run; a checkpoint written by the per-user
    # stage loop also has None here and restarts at INVENTORY.
    phase_progress: PhaseProgress | None = None

    # Drive id -> the email that listed it. Once the shared drive phase is
    # over, a drive here and not in incomplete_drive_ids is fully covered.
    organizer_email_by_drive_id: dict[str, str] = {}

    # Drives listed by someone who is not an organizer, or by nobody, so
    # limited-access folders may be missing.
    incomplete_drive_ids: set[str] = set()

    # Users whose impersonation failed this run. Their files are not covered by
    # an owner pass, so other users' listings must not drop them.
    failed_impersonation_emails: set[str] = set()

    # Requested targets at least one principal crawled. At the end of the
    # requested-target phase, every planned target missing here is unreachable.
    crawled_target_ids: set[str] = set()

    # Requested drives and folders that no impersonable user could reach.
    # Pruning refuses to run while this is non-empty, because absence from the
    # listing would delete every document indexed from them.
    unreachable_target_ids: set[str] = set()

    # State of the parallel sharded listing. None until the checkpointed slim
    # listing of a service account starts. The phased retrieval does not use
    # it.
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

    @field_serializer("completion_map")
    def serialize_completion_map(
        self, completion_map: ThreadSafeDict[str, StageCompletion], _info: Any
    ) -> dict[str, StageCompletion]:
        return completion_map._dict

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

    @field_validator("completion_map", mode="before")
    def validate_completion_map(cls, v: Any) -> ThreadSafeDict[str, StageCompletion]:
        assert isinstance(v, dict) or isinstance(v, ThreadSafeDict)
        return ThreadSafeDict(
            {k: StageCompletion.model_validate(val) for k, val in v.items()}
        )

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
