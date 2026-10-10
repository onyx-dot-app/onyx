from collections.abc import Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from onyx.connectors.interfaces import ConnectorCheckpoint, SecondsSinceUnixEpoch
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
