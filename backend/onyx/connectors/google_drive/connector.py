import copy
import itertools
import json
import os
import sys
import time
import zlib
from collections import deque
from collections.abc import Callable, Collection, Generator, Iterable, Iterator
from contextlib import closing
from typing import Any, cast
from urllib.parse import ParseResult, parse_qs, urlparse

from typing_extensions import override

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import (
    GOOGLE_DRIVE_CONNECTOR_SIZE_THRESHOLD,
    GOOGLE_DRIVE_CONVERSION_WORKERS,
    INDEX_BATCH_SIZE,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.doc_conversion import (
    _FALLBACK_BINARY_WEB_VIEW_LINK_TEMPLATE,
    _FALLBACK_WEB_VIEW_LINK_TEMPLATES,
    MAX_RETRIEVER_EMAILS,
    WEB_VIEW_LINK_KEY,
    PermissionSyncContext,
    build_slim_document,
    build_slim_document_stub,
    convert_drive_item_to_document,
    drive_file_size,
    drive_file_skip_reason,
    onyx_document_id_from_drive_file,
)
from onyx.connectors.google_drive.drive_access import (
    internal_principals_of,
    list_drive_members,
    list_group_member_emails,
    select_drive_organizer,
)
from onyx.connectors.google_drive.file_retrieval import (
    DriveFileFieldType,
    get_external_access_for_folder,
    get_files_by_web_view_links_batch,
    get_folder_metadata,
    has_link_only_permission,
    owner_email,
)
from onyx.connectors.google_drive.models import (
    DriveListingPayload,
    DriveListingState,
    GoogleDriveCheckpoint,
    GoogleDriveFileType,
    ImpersonationError,
    ListingPartition,
    ListingPartitionKind,
    RetrievedDriveFile,
    make_user_removal_checker,
)
from onyx.connectors.google_drive.parallel_listing import (
    FolderTargetPlan,
    ParallelDriveLister,
    drive_document_type,
    extend_window,
    open_window_end,
    retry_transient,
    window_ms,
)
from onyx.connectors.google_drive.source_operations import (
    DriveCorpus,
    GoogleDriveHttpError,
    GoogleDriveRefreshError,
    GoogleDriveSourceOperations,
    attach_source_api_limiter,
)
from onyx.connectors.google_utils.google_utils import (
    get_file_owners,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
    MISSING_SCOPES_ERROR_STR,
    ONYX_SCOPE_INSTRUCTIONS,
    SLIM_BATCH_SIZE,
    GoogleCredentialKind,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointedSlimConnector,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    NormalizationResult,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimCheckpointOutput,
    SlimConnector,
    SlimConnectorWithPermSync,
    SourceApiLimiter,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    ResolveTarget,
    SlimDocument,
)
from onyx.db.enums import HierarchyNodeType
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder
from onyx.utils.threadpool_concurrency import (
    BoundedParallelRunner,
    ThreadSafeDict,
    ThreadSafeSet,
    run_functions_tuples_in_parallel,
)

logger = setup_logger()
# TODO: Improve this by using the batch utility: https://googleapis.github.io/google-api-python-client/docs/batch.html
# All file retrievals could be batched and made at once

BATCHES_PER_CHECKPOINT = 1

# Listed folders and files whose parents are recorded together.
DRIVE_CONVERSION_BATCH_SIZE = 50
# Files converting at once. Each conversion makes one to three Drive calls
# (download or export, Docs API, permissions.list), so this sets the requests
# in flight. At up to CONNECTOR_MAX_EXTRACTED_TEXT_CHARS (~10 MB) a document,
# it also bounds resident documents. Against Google's latency, past 32 the
# conversions' parsing (one core, under the GIL) limits a run, not the calls.
DRIVE_CONVERSION_WORKERS: int = GOOGLE_DRIVE_CONVERSION_WORKERS
# Conversions submitted and not yet yielded. Waiting ones hold only metadata.
DRIVE_CONVERSION_MAX_IN_FLIGHT: int = 2 * DRIVE_CONVERSION_WORKERS
# Pool width for reindex, slim-document builds (pruning, permission sync) and
# folder reads. GOOGLE_DRIVE_CONVERSION_WORKERS does not change it.
DRIVE_FETCH_WORKERS = 8

# Listed files read ahead of conversion so conversions spread over users. Each
# holds only metadata.
DRIVE_INTERLEAVE_LOOKAHEAD = 2000


# Upper bound on the dedup set. Drive file ids measure ~119 bytes per entry with
# deep_getsizeof, so this holds it near 95 MB, well under
# CHECKPOINT_SIZE_LIMIT_BYTES.
MAX_DEDUP_DRIVE_FILE_IDS = 800_000


def extract_str_list_from_comma_str(string: str | None) -> list[str]:
    if not string:
        return []
    return [s.strip() for s in string.split(",") if s.strip()]


def extract_ids_from_urls(urls: list[str]) -> list[str]:
    return [urlparse(url).path.strip("/").split("/")[-1] for url in urls]


def _extract_drive_file_id(parsed: ParseResult) -> str | None:
    """Extract the file id from a Drive/Docs URL.

    Covers `?id=<id>`, `/d/<id>/...`, and the multi-account `/u/<N>/d/<id>/...` form.
    """
    id_query_param = parse_qs(parsed.query).get("id", [None])[0]
    if id_query_param:
        return id_query_param

    path_parts = parsed.path.split("/")
    for i, part in enumerate(path_parts):
        if part == "d" and i + 1 < len(path_parts):
            return path_parts[i + 1]
    return None


def _candidate_document_ids_from_file_id(file_id: str) -> list[str]:
    """Every canonical Document.id a Drive file id could have been indexed under.

    A file id is globally unique, so at most one of the native Doc/Sheet/Slide forms
    and the uploaded-binary form is ever indexed; the caller matches whichever exists.
    """
    native_doc_links = [
        template.format(file_id)
        for template in _FALLBACK_WEB_VIEW_LINK_TEMPLATES.values()
    ]
    uploaded_binary_link = _FALLBACK_BINARY_WEB_VIEW_LINK_TEMPLATE.format(file_id)

    candidates: list[str] = []
    for link in [*native_doc_links, uploaded_binary_link]:
        doc_id = onyx_document_id_from_drive_file({WEB_VIEW_LINK_KEY: link}).rstrip("/")
        if doc_id not in candidates:
            candidates.append(doc_id)
    return candidates


def _clean_requested_drive_ids(
    requested_drive_ids: set[str],
    requested_folder_ids: set[str],
    all_drive_ids_available: set[str],
) -> tuple[list[str], list[str]]:
    invalid_requested_drive_ids = requested_drive_ids - all_drive_ids_available
    filtered_folder_ids = requested_folder_ids - all_drive_ids_available
    if invalid_requested_drive_ids:
        logger.warning(
            "Some shared drive IDs were not found. IDs: %s", invalid_requested_drive_ids
        )
        logger.warning("Checking for folder access instead...")
        filtered_folder_ids.update(invalid_requested_drive_ids)

    valid_requested_drive_ids = requested_drive_ids - invalid_requested_drive_ids
    return sorted(valid_requested_drive_ids), sorted(filtered_folder_ids)


# Folders one step of the read of unlisted parents reads, and the most nodes
# it holds before it yields them.
PARENT_READ_BATCH_SIZE = 500
# The most users kept as readers to try for one unlisted parent folder. It
# bounds the checkpoint: the map has one entry for each such folder.
MAX_PARENT_READERS = 4


def _add_parent_reader(
    unresolved: dict[str, list[str]], parent_id: str, email: str
) -> None:
    """Records ``email`` as a user who can try to read the parent. The first
    user to see a child is not always one who can read its parent."""
    readers = unresolved.setdefault(parent_id, [])
    if email not in readers and len(readers) < MAX_PARENT_READERS:
        readers.append(email)


def _take[T](pending: dict[str, T], count: int) -> dict[str, T]:
    """Removes up to ``count`` entries from ``pending`` and returns them."""
    taken: dict[str, T] = {}
    for key in list(itertools.islice(pending, count)):
        taken[key] = pending.pop(key)
    return taken


def _rotated_readers(
    drive_file: GoogleDriveFileType, payload: DriveListingPayload
) -> list[str]:
    """The users who can read the file, starting at a place set by a hash of
    the file id. This spreads reads over the users with no shared state. The
    listing user stays in the list, so it is the fallback on 403/404."""
    readers = list(dict.fromkeys([*payload.reader_emails, payload.retriever_email]))
    start = zlib.crc32(str(drive_file.get("id", "")).encode()) % len(readers)
    rotated = readers[start:] + readers[:start]
    # Conversion tries at most MAX_RETRIEVER_EMAILS users. Keep the listing
    # user (and a slot for the admin) inside that limit.
    head = [r for r in rotated if r != payload.retriever_email]
    return head[: MAX_RETRIEVER_EMAILS - 2] + [payload.retriever_email]


def _get_parent_id_from_file(drive_file: GoogleDriveFileType) -> str | None:
    """Extract the first parent ID from a drive file."""
    parents = drive_file.get("parents")
    if parents and len(parents) > 0:
        return parents[0]  # files have a unique parent
    return None


def _is_shared_drive_root(folder: GoogleDriveFileType) -> bool:
    """
    Check if a folder is a verified shared drive root.

    For shared drives, we can verify using driveId:
    - If driveId is set and folder_id == driveId AND no parents, it's the shared drive root
    - If driveId is set but folder_id != driveId with empty parents, it's a permission issue

    Returns True only for verified shared drive roots.
    """
    folder_id = folder.get("id")
    drive_id = folder.get("driveId")
    parents = folder.get("parents", [])

    # Must have no parents to be a root
    if parents:
        return False

    # For shared drive content, the root has id == driveId
    return bool(drive_id and folder_id == drive_id)


def _stop_or_report_progress(
    callback: IndexingHeartbeatInterface | None, tag: str
) -> None:
    """Raises on a stop signal, since a slim walk cut short reads as deletions."""
    if callback is None:
        return
    if callback.should_stop():
        raise RuntimeError(f"{tag}: Stop signal detected")
    callback.progress(tag, 1)


def _retrieval_failure(retrieved_file: RetrievedDriveFile) -> ConnectorFailure:
    logger.error(
        "retrieval failure, user: %s, parent drive/folder: %s, error: %s",
        retrieved_file.user_email,
        retrieved_file.parent_id,
        retrieved_file.error,
    )
    return ConnectorFailure(
        failed_entity=EntityFailure(
            entity_id=retrieved_file.drive_file.get("id", "drive_listing"),
        ),
        failure_message=(
            f"retrieval failure, user: {retrieved_file.user_email}, "
            f"parent drive/folder: {retrieved_file.parent_id}, "
            f"error: {retrieved_file.error}"
        ),
        exception=retrieved_file.error,
    )


def _count_listed_file(
    state: DriveListingState, drive_file: GoogleDriveFileType
) -> None:
    """Adds a file that passed the metadata check to the running count."""
    label = drive_document_type(drive_file.get("mimeType") or "")
    state.docs_by_type[label] = state.docs_by_type.get(label, 0) + 1
    size = drive_file_size(drive_file)
    if size is not None:
        state.bytes_by_type[label] = state.bytes_by_type.get(label, 0) + size


def _drop_listing_state(checkpoint: GoogleDriveCheckpoint) -> None:
    """Clears what a listing recorded, so the attempt lists again from its
    window start. Documents are keyed by id, so a file listed twice is
    stored once. The hierarchy nodes already sent stay recorded."""
    checkpoint.listing = None
    # The claims of the old listing would make the new one drop those files.
    checkpoint.retrieved_drive_file_ids = set()
    checkpoint.drive_ids_to_retrieve = None
    checkpoint.folder_ids_to_retrieve = None
    checkpoint.user_emails = None
    checkpoint.organizer_email_by_drive_id = {}
    checkpoint.incomplete_drive_ids = set()
    checkpoint.failed_impersonation_emails = set()
    checkpoint.unreachable_target_ids = set()


def _listing_done(checkpoint: GoogleDriveCheckpoint) -> bool:
    return checkpoint.listing is not None and checkpoint.listing.is_done


def _public_access() -> ExternalAccess:
    return ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids=set(),
        is_public=True,
    )


def _converted(
    results: Iterable[Document | ConnectorFailure | None],
) -> Iterator[Document | ConnectorFailure]:
    """The conversion results to yield; None is a file with nothing to index."""
    return (result for result in results if result is not None)


def _interleave_by_user(
    files: Iterator[RetrievedDriveFile], lookahead: int
) -> Iterator[RetrievedDriveFile]:
    """The files of `files`, taken round-robin across their retriever users,
    reading at most `lookahead` files ahead.

    Partitions list one after another, each as one user. Taken in order, every
    conversion in flight acts as that one user and meets Google's per-user
    quotas (the Docs API allows 300 reads a minute per user) long before the
    project's. Interleaved, the conversions spread over the users of every
    partition listed so far. A connector call converts everything it lists
    before it returns, so the order does not change what the checkpoint
    records."""
    queues: dict[str, deque[RetrievedDriveFile]] = {}
    turns: deque[str] = deque()
    buffered = 0
    exhausted = False
    while True:
        while not exhausted and buffered < lookahead:
            retrieved_file = next(files, None)
            if retrieved_file is None:
                exhausted = True
                break
            queue = queues.get(retrieved_file.user_email)
            if queue is None:
                queue = queues[retrieved_file.user_email] = deque()
                turns.append(retrieved_file.user_email)
            queue.append(retrieved_file)
            buffered += 1
        if not turns:
            return
        user_email = turns.popleft()
        queue = queues[user_email]
        yield queue.popleft()
        buffered -= 1
        if queue:
            turns.append(user_email)
        else:
            del queues[user_email]


class UnreachableTargetsError(RuntimeError):
    """A requested drive or folder could not be listed by anyone."""


class GoogleDriveConnector(
    SlimConnector,
    SlimConnectorWithPermSync,
    CheckpointedSlimConnector[GoogleDriveCheckpoint],
    CheckpointedConnectorWithPermSync[GoogleDriveCheckpoint],
    Resolver,
):
    slim_listing_honors_indexing_start = True
    listing_payload_type = DriveListingPayload

    def __init__(
        self,
        include_shared_drives: bool = False,
        include_my_drives: bool = False,
        include_files_shared_with_me: bool = False,
        shared_drive_urls: str | None = None,
        my_drive_emails: str | None = None,
        shared_folder_urls: str | None = None,
        specific_user_emails: str | None = None,
        exclude_domain_link_only: bool = False,
        batch_size: int = INDEX_BATCH_SIZE,  # noqa: ARG002
        # Read by capability checks only; the kind comes from the credential.
        credential_kind: GoogleCredentialKind | None = None,  # noqa: ARG002
        # OLD PARAMETERS
        folder_paths: list[str] | None = None,
        include_shared: bool | None = None,
        follow_shortcuts: bool | None = None,
        only_org_public: bool | None = None,
        continue_on_failure: bool | None = None,
    ) -> None:
        # Check for old input parameters
        if folder_paths is not None:
            logger.warning(
                "The 'folder_paths' parameter is deprecated. Use 'shared_folder_urls' instead."
            )
        if include_shared is not None:
            logger.warning(
                "The 'include_shared' parameter is deprecated. Use 'include_files_shared_with_me' instead."
            )
        if follow_shortcuts is not None:
            logger.warning("The 'follow_shortcuts' parameter is deprecated.")
        if only_org_public is not None:
            logger.warning("The 'only_org_public' parameter is deprecated.")
        if continue_on_failure is not None:
            logger.warning("The 'continue_on_failure' parameter is deprecated.")

        if not any(
            (
                include_shared_drives,
                include_my_drives,
                include_files_shared_with_me,
                shared_folder_urls,
                my_drive_emails,
                shared_drive_urls,
            )
        ):
            raise ConnectorValidationError(
                "Nothing to index. Please specify at least one of the following: "
                "include_shared_drives, include_my_drives, include_files_shared_with_me, "
                "shared_folder_urls, or my_drive_emails"
            )

        specific_requests_made = False
        if bool(shared_drive_urls) or bool(my_drive_emails) or bool(shared_folder_urls):
            specific_requests_made = True
        self.specific_requests_made = specific_requests_made

        # NOTE: potentially modified in load_credentials if using service account
        self.include_files_shared_with_me = (
            False if specific_requests_made else include_files_shared_with_me
        )
        self.include_my_drives = False if specific_requests_made else include_my_drives
        self.include_shared_drives = (
            False if specific_requests_made else include_shared_drives
        )

        shared_drive_url_list = extract_str_list_from_comma_str(shared_drive_urls)
        self._requested_shared_drive_ids = set(
            extract_ids_from_urls(shared_drive_url_list)
        )

        self._requested_my_drive_emails = set(
            extract_str_list_from_comma_str(my_drive_emails)
        )

        shared_folder_url_list = extract_str_list_from_comma_str(shared_folder_urls)
        self._requested_folder_ids = set(extract_ids_from_urls(shared_folder_url_list))
        self._specific_user_emails = extract_str_list_from_comma_str(
            specific_user_emails
        )
        self.exclude_domain_link_only = exclude_domain_link_only

        self._primary_admin_email: str | None = None

        self._ops: GoogleDriveSourceOperations | None = None
        self._is_service_account = False

        # Cache of known My Drive root IDs (user_email -> root_id)
        # Used to verify if a folder with no parents is actually a My Drive root
        # Thread-safe because multiple impersonation threads access this concurrently
        self._my_drive_root_id_cache: ThreadSafeDict[str, str] = ThreadSafeDict()

        self.allow_images = False

        self.size_threshold = GOOGLE_DRIVE_CONNECTOR_SIZE_THRESHOLD

    @override
    def set_source_api_limiter(self, limiter: SourceApiLimiter) -> None:
        self.source_api_limiter = limiter
        if self._ops is not None:
            attach_source_api_limiter(self._ops, limiter)

    def set_allow_images(self, value: bool) -> None:
        self.allow_images = value

    @property
    def primary_admin_email(self) -> str:
        if self._primary_admin_email is None:
            raise RuntimeError(
                "Primary admin email missing, should not call this property before calling load_credentials"
            )
        return self._primary_admin_email

    @property
    def google_domain(self) -> str:
        if self._primary_admin_email is None:
            raise RuntimeError(
                "Primary admin email missing, should not call this property before calling load_credentials"
            )
        return self._primary_admin_email.split("@")[-1]

    @property
    def ops(self) -> GoogleDriveSourceOperations:
        if self._ops is None:
            raise RuntimeError(
                "Source operations missing, should not call this property before calling load_credentials"
            )
        return self._ops

    @property
    def is_service_account(self) -> bool:
        return self._is_service_account

    @classmethod
    @override
    def normalize_url(cls, url: str) -> NormalizationResult:
        """Normalize a Google Drive URL to candidate Document.id values.

        The pasted URL often doesn't encode the file's type, so the canonical
        Document.id could take any of several forms; emit them all as candidates and
        let resolution match whichever is indexed. `normalized_url` is a single best
        guess for callers that don't consult the candidate list.
        """
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()

        if not netloc.startswith(("docs.google.com", "drive.google.com")):
            return NormalizationResult(normalized_url=None, use_default=False)

        file_id = _extract_drive_file_id(parsed)
        if not file_id:
            return NormalizationResult(normalized_url=None, use_default=False)

        # Best guess: keep the pasted URL's type if it has one; a ?id= link has none.
        if parse_qs(parsed.query).get("id"):
            normalized = onyx_document_id_from_drive_file(
                {
                    WEB_VIEW_LINK_KEY: _FALLBACK_BINARY_WEB_VIEW_LINK_TEMPLATE.format(
                        file_id
                    )
                }
            ).rstrip("/")
        else:
            normalized = onyx_document_id_from_drive_file(
                {WEB_VIEW_LINK_KEY: url, "id": file_id}
            ).rstrip("/")
        return NormalizationResult(
            normalized_url=normalized,
            candidate_document_ids=_candidate_document_ids_from_file_id(file_id),
        )

    # TODO: ensure returned new_creds_dict is actually persisted when this is called?
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, str] | None:
        try:
            self._primary_admin_email = credentials[DB_CREDENTIALS_PRIMARY_ADMIN_KEY]
        except KeyError:
            raise ValueError("Credentials json missing primary admin key")

        self._ops = GoogleDriveSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.GOOGLE_DRIVE.value, credentials
            )
        )
        if self.source_api_limiter is not None:
            attach_source_api_limiter(self._ops, self.source_api_limiter)
        auth = self._ops.authenticate()
        self._is_service_account = auth.kind == GoogleCredentialKind.SERVICE_ACCOUNT

        # Service account connectors don't have a specific setting determining whether
        # to include "shared with me" for each user, so we default to true unless the connector
        # is in specific folders/drives mode. Shared files are listed only for users whose My Drive
        # is listed, so this does nothing if the connector is set to only index shared drives.
        if self._is_service_account and not self.specific_requests_made:
            self.include_files_shared_with_me = True

        return auth.refreshed_credential_json

    def _get_all_user_emails(self) -> list[str]:
        if self._specific_user_emails:
            return self._specific_user_emails

        # Start with primary admin email
        user_emails = [self.primary_admin_email]

        # Only fetch additional users if using service account
        if not self._is_service_account:
            return user_emails

        # Get admins first since they're more likely to have access to most files
        for is_admin in [True, False]:
            query = "isAdmin=true" if is_admin else "isAdmin=false"
            for email in self.ops.list_user_emails(query=query):
                if email not in user_emails:
                    user_emails.append(email)
        return user_emails

    def _get_my_drive_root_id(self, user_email: str) -> str | None:
        """
        Get the My Drive root folder ID for a user.

        Uses a cache to avoid repeated API calls. Returns None if the user
        doesn't have access to Drive APIs or the call fails.
        """
        if user_email in self._my_drive_root_id_cache:
            return self._my_drive_root_id_cache[user_email]

        try:
            root_id = self.ops.get_root_folder_id(user_email=user_email)
            self._my_drive_root_id_cache[user_email] = root_id
            return root_id
        except Exception:
            # User might not have access to Drive APIs
            return None

    def _is_my_drive_root(
        self, folder: GoogleDriveFileType, retriever_email: str
    ) -> bool:
        """
        Check if a folder is a My Drive root.

        For My Drive folders (no driveId), we verify by comparing the folder ID
        to the actual My Drive root ID obtained via files().get(fileId='root').
        """
        folder_id = folder.get("id")
        drive_id = folder.get("driveId")
        parents = folder.get("parents", [])

        # If there are parents, this is not a root
        if parents:
            return False

        # If driveId is set, this is shared drive content, not My Drive
        if drive_id:
            return False

        # Get the My Drive root ID for this user and compare
        root_id = self._get_my_drive_root_id(retriever_email)
        if root_id and folder_id == root_id:
            return True

        # Also check with admin in case the retriever doesn't have access
        admin_root_id = self._get_my_drive_root_id(self.primary_admin_email)
        if admin_root_id and folder_id == admin_root_id:
            return True

        return False

    def _folder_node(
        self,
        folder: GoogleDriveFileType,
        permission_sync_context: PermissionSyncContext | None,
        add_prefix: bool,
        raw_id: str | None = None,
    ) -> HierarchyNode:
        if permission_sync_context:
            external_access = get_external_access_for_folder(
                folder,
                permission_sync_context.google_domain,
                self.ops,
                self.primary_admin_email,
                add_prefix,
            )
        else:
            external_access = _public_access()
        return HierarchyNode(
            raw_node_id=raw_id or folder["id"],
            raw_parent_id=_get_parent_id_from_file(folder),
            display_name=folder.get("name", "Unknown Folder"),
            link=folder.get("webViewLink"),
            node_type=HierarchyNodeType.FOLDER,
            external_access=external_access,
        )

    def _get_folder_metadata(
        self,
        folder_id: str,
        retriever_email: str,
        field_type: DriveFileFieldType,
        failed_folder_ids_by_email: (
            ThreadSafeDict[str, ThreadSafeSet[str]] | None
        ) = None,
    ) -> GoogleDriveFileType | None:
        """
        Fetch metadata for a folder by ID.

        Important: When a user has access to a shared folder but NOT its parent,
        the Google Drive API returns the folder metadata WITHOUT the parent info.
        To handle this, if the retriever gets a folder without parents, we also
        try with admin who may have better access and can see the parent chain.
        """
        best_folder: GoogleDriveFileType | None = None

        # Use a set to deduplicate if retriever_email == primary_admin_email
        for email in {retriever_email, self.primary_admin_email}:
            failed_ids = (
                failed_folder_ids_by_email.get(email)
                if failed_folder_ids_by_email
                else None
            )
            if failed_ids and folder_id in failed_ids:
                # Logged once, when the folder was added to the set.
                continue

            folder = retry_transient(get_folder_metadata)(
                self.ops, email, folder_id, field_type
            )

            if not folder:
                logger.debug("Failed to fetch folder %s using %s", folder_id, email)
                continue

            logger.debug("Successfully fetched folder %s using %s", folder_id, email)

            # If this folder has parents, use it
            if folder.get("parents"):
                return folder

            # Folder has no parents - could be a root OR user lacks access to parent
            # Keep this as a fallback but try admin to see if they can see parents
            if failed_folder_ids_by_email is not None:
                failed_folder_ids_by_email.setdefault(email, ThreadSafeSet()).add(
                    folder_id
                )
                logger.debug(
                    "Folder %s has no parents for %s; later walks skip it",
                    folder_id,
                    email,
                )
            if best_folder is None:
                best_folder = folder
                logger.debug(
                    "Folder %s has no parents when fetched by %s, will try admin to check for parent access",
                    folder_id,
                    email,
                )

        if best_folder:
            logger.debug(
                "Successfully fetched folder %s but no parents found", folder_id
            )
            return best_folder

        logger.debug(
            "All attempts failed to fetch folder %s (tried %s and %s)",
            folder_id,
            retriever_email,
            self.primary_admin_email,
        )
        return None

    def _get_shared_drive_name(self, drive_id: str, retriever_email: str) -> str | None:
        """Fetch the name of a shared drive, trying both the retriever and admin."""
        for email in {retriever_email, self.primary_admin_email}:
            name = self.ops.get_shared_drive_name(user_email=email, drive_id=drive_id)
            if name:
                return name
        return None

    def get_all_drive_ids(self) -> set[str]:
        return self._get_all_drives_for_user(self.primary_admin_email)

    def _get_all_drives_for_user(self, user_email: str) -> set[str]:
        logger.info(
            "Getting all drives for user %s with service account: %s",
            user_email,
            self._is_service_account,
        )
        all_drive_ids: set[str] = set(
            self.ops.list_drives(
                user_email=user_email,
                use_domain_admin_access=self._is_service_account,
            )
        )

        if not all_drive_ids:
            logger.warning(
                "No drives found even though indexing shared drives was requested."
            )

        return all_drive_ids

    def _run_inventory(self, checkpoint: GoogleDriveCheckpoint) -> None:
        checkpoint.user_emails = self._get_all_user_emails()
        drive_ids, folder_ids = self._compute_retrieval_ids()
        checkpoint.drive_ids_to_retrieve = drive_ids
        checkpoint.folder_ids_to_retrieve = folder_ids
        logger.info(
            "Listing inventory: %s users, %s drives, %s folders",
            len(checkpoint.user_emails),
            len(drive_ids),
            len(folder_ids),
        )

    def _choose_drive_principal(
        self,
        drive_id: str,
        checkpoint: GoogleDriveCheckpoint,
        busy: Collection[str] = (),
    ) -> tuple[str | None, bool]:
        """The email to list a drive as, and whether its listing is complete.
        Members in ``busy`` already list another drive, so they come last."""
        try:
            members = list_drive_members(self.ops, drive_id)
        except GoogleDriveHttpError as error:
            # Only a denial means "fall back"; a server error must fail the
            # run, or a prune would delete the drive's documents.
            if not error.access_denied:
                raise
            logger.warning("Cannot read members of drive %s: %s", drive_id, error)
            members = []

        def _can_list(email: str) -> bool:
            if not self._may_impersonate(email, checkpoint):
                return False
            return self.ops.can_list_drive(user_email=email, drive_id=drive_id)

        choice = select_drive_organizer(
            drive_id=drive_id,
            members=members,
            google_domain=self.google_domain,
            expand_group=self._expand_group,
            can_list_drive=_can_list,
            busy=busy,
        )
        if choice.email is not None:
            return choice.email, choice.complete

        # Membership was unreadable or names nobody we can impersonate. The
        # admin may still be able to list it, so try it.
        if _can_list(self.primary_admin_email):
            logger.warning(
                "Drive %s: no impersonable member; listing as the admin. "
                "Limited-access folders may be missed.",
                drive_id,
            )
            return self.primary_admin_email, False
        logger.warning("Drive %s: no principal can list it; skipping.", drive_id)
        return None, False

    def _expand_group(self, group_email: str) -> list[str]:
        return list_group_member_emails(self.ops, group_email)

    def _find_target_viewer(
        self, target_id: str, checkpoint: GoogleDriveCheckpoint
    ) -> tuple[str, GoogleDriveFileType] | None:
        candidates = [self.primary_admin_email, *(checkpoint.user_emails or [])]
        seen: set[str] = set()
        for email in candidates:
            if email in seen or not self._may_impersonate(email, checkpoint):
                continue
            seen.add(email)
            metadata = self.ops.probe_target(user_email=email, target_id=target_id)
            if metadata is not None:
                return email, metadata
        return None

    def _target_principals(
        self,
        target_id: str,
        viewer: str,
        metadata: GoogleDriveFileType,
        checkpoint: GoogleDriveCheckpoint,
    ) -> list[str]:
        drive_id = metadata.get("driveId")
        if drive_id:
            email, _complete = self._choose_drive_principal(drive_id, checkpoint)
            if email is not None:
                return [email]
        else:
            owner = owner_email(metadata)
            if (
                owner is not None
                and owner.endswith(f"@{self.google_domain.lower()}")
                and self._may_impersonate(owner, checkpoint)
            ):
                return [owner]

        logger.info(
            "Requested target %s has no guaranteed principal; crawling it as "
            "each in-domain user on its permission list (best effort).",
            target_id,
        )
        principals = internal_principals_of(
            self.ops,
            viewer,
            target_id,
            self.google_domain,
            self._expand_group,
        )
        if principals is None:
            principals = list(checkpoint.user_emails or [])
        return sorted(
            email
            for email in set(principals) | {viewer}
            if self._may_impersonate(email, checkpoint)
        )

    def _impersonation_gate(
        self, email: str, checkpoint: GoogleDriveCheckpoint
    ) -> Generator[RetrievedDriveFile, None, bool]:
        """Check that `email` can call the Drive API before listing as them.

        A user without Drive access (401) or removed from the workspace is
        skipped quietly; any other impersonation failure is reported. Either
        way the user is recorded as failed so no listing relies on their pass.
        """
        try:
            # The default retry runs ~17 minutes; a user without Drive access
            # should not cost that on every run.
            retry_builder(tries=3, delay=1)(self.ops.get_root_folder_id)(
                user_email=email
            )
        except GoogleDriveHttpError as error:
            if error.status_code != 401:
                raise
            logger.warning("User '%s' does not have access to the drive APIs.", email)
            checkpoint.failed_impersonation_emails.add(email)
            return False
        except GoogleDriveRefreshError as error:
            yield from self._impersonation_failed(email, error, checkpoint)
            return False
        return True

    def _impersonation_failed(
        self,
        email: str,
        error: GoogleDriveRefreshError,
        checkpoint: GoogleDriveCheckpoint,
    ) -> Iterator[RetrievedDriveFile]:
        checkpoint.failed_impersonation_emails.add(email)
        is_user_removed = make_user_removal_checker(email, self._get_all_user_emails)
        if is_user_removed():
            logger.warning(
                "User '%s' confirmed removed from workspace, skipping.", email
            )
            return
        logger.warning("User '%s' impersonation failed. Error: %s", email, error)
        yield RetrievedDriveFile(
            drive_file={},
            user_email=email,
            error=ImpersonationError(email, error),
        )

    def _may_impersonate(self, email: str, checkpoint: GoogleDriveCheckpoint) -> bool:
        """Whether a principal may be used this run. specific_user_emails
        limits the connector to acting as those users, so an organizer or
        owner outside that list is not a candidate, the admin included."""
        if email in checkpoint.failed_impersonation_emails:
            return False
        if not self._specific_user_emails:
            return True
        allowed = {user.lower() for user in checkpoint.user_emails or []}
        return email.lower() in allowed

    def _my_drive_partition_emails(
        self, checkpoint: GoogleDriveCheckpoint
    ) -> list[str]:
        users = checkpoint.user_emails or []
        if self.include_my_drives:
            return list(users)
        requested = {email.lower() for email in self._requested_my_drive_emails}
        return [email for email in users if email.lower() in requested]

    @classmethod
    def _admit_file(
        cls,
        checkpoint: GoogleDriveCheckpoint,
        drive_file: GoogleDriveFileType,
        exact: bool,
    ) -> bool:
        """Whether to yield a file. An exact file (listed by the partition that
        owns it) is never added to the dedup set, but it is still skipped if a
        shortcut already brought it in earlier in the run."""
        if exact:
            return drive_file.get("id") not in checkpoint.retrieved_drive_file_ids
        return cls._claim_file(checkpoint, drive_file)

    @staticmethod
    def _claim_file(
        checkpoint: GoogleDriveCheckpoint, drive_file: GoogleDriveFileType
    ) -> bool:
        """Record a file in the dedup set. False if it was already yielded.

        Only files without an exact partition go through here. Past the cap
        the set stops growing and duplicates are yielded again; each costs a
        re-download, which is cheaper than failing the sync.
        """
        file_id = drive_file.get("id") or drive_file.get(WEB_VIEW_LINK_KEY)
        if not isinstance(file_id, str):
            return True
        seen_file_ids: set[str] = checkpoint.retrieved_drive_file_ids
        if file_id in seen_file_ids:
            return False
        if len(seen_file_ids) < MAX_DEDUP_DRIVE_FILE_IDS:
            seen_file_ids.add(file_id)
            if len(seen_file_ids) == MAX_DEDUP_DRIVE_FILE_IDS:
                logger.warning(
                    "Reached the %s file dedup cap; later duplicates will be "
                    "re-yielded to indexing.",
                    MAX_DEDUP_DRIVE_FILE_IDS,
                )
        return True

    def _compute_retrieval_ids(self) -> tuple[list[str], list[str]]:
        """Sorted shared drive ids and folder ids this connector should list.

        A requested drive id that drives.list does not return is treated as a
        folder, since the user may have pasted a folder URL as a drive.
        """
        if self._requested_shared_drive_ids or self._requested_folder_ids:
            return _clean_requested_drive_ids(
                requested_drive_ids=self._requested_shared_drive_ids,
                requested_folder_ids=self._requested_folder_ids,
                all_drive_ids_available=self.get_all_drive_ids(),
            )
        if self.include_shared_drives:
            return sorted(self.get_all_drive_ids()), []
        return [], []

    def _listing_skip_reason(self, drive_file: GoogleDriveFileType) -> str | None:
        """The metadata check for a listed file. Every listing applies it, so
        pruning removes the documents of files that indexing skips."""
        return drive_file_skip_reason(
            drive_file,
            allow_images=self.allow_images,
            size_threshold=self.size_threshold,
            # Indexing always stages raw files, and conversion checks again.
            has_raw_file_callback=True,
            exclude_domain_link_only=self.exclude_domain_link_only,
        )

    def _convert_retrieved_files_to_documents(
        self,
        drive_files_iter: Iterator[RetrievedDriveFile],
        checkpoint: GoogleDriveCheckpoint,
        listing: DriveListingState,
        include_permissions: bool,
    ) -> Iterator[Document | ConnectorFailure | HierarchyNode]:
        """Converts listed files to documents. The listing's stream also holds
        folders, which become hierarchy nodes. No file waits for its folder:
        docfetching gives a document a STUB parent until the folder arrives.

        The one step of inline indexing after the listing: it takes the
        listing's file stream as it is, so the conversion loop can change
        without a change to the listing.
        """
        permission_sync_context = (
            PermissionSyncContext(
                primary_admin_email=self.primary_admin_email,
                google_domain=self.google_domain,
            )
            if include_permissions
            else None
        )
        # Files whose parents are not recorded yet. Metadata only.
        files_batch: list[RetrievedDriveFile] = []
        folders_batch: list[RetrievedDriveFile] = []
        # Conversions run while the listing goes on, at most
        # DRIVE_CONVERSION_MAX_IN_FLIGHT at once.
        with BoundedParallelRunner[Document | ConnectorFailure | None](
            max_workers=DRIVE_CONVERSION_WORKERS,
            max_in_flight=DRIVE_CONVERSION_MAX_IN_FLIGHT,
        ) as runner:
            for retrieved_file in drive_files_iter:
                yield from _converted(runner.ready())
                if retrieved_file.error is not None:
                    yield _retrieval_failure(retrieved_file)
                    continue
                if retrieved_file.drive_file.get("mimeType") == DRIVE_FOLDER_TYPE:
                    folders_batch.append(retrieved_file)
                elif self._listing_skip_reason(retrieved_file.drive_file) is not None:
                    continue
                else:
                    files_batch.append(retrieved_file)
                    yield from _converted(
                        runner.submit(
                            self._convert_retrieved_file_to_document,
                            retrieved_file,
                            permission_sync_context,
                        )
                    )
                if len(folders_batch) + len(files_batch) >= DRIVE_CONVERSION_BATCH_SIZE:
                    yield from self._listed_folder_nodes(
                        listing,
                        checkpoint,
                        folders_batch,
                        files_batch,
                        permission_sync_context,
                        add_prefix=True,
                    )
                    folders_batch = []
                    files_batch = []

            yield from self._listed_folder_nodes(
                listing,
                checkpoint,
                folders_batch,
                files_batch,
                permission_sync_context,
                add_prefix=True,
            )
            yield from _converted(runner.drain())

    def _convert_retrieved_file_to_document(
        self,
        retrieved_file: RetrievedDriveFile,
        permission_sync_context: PermissionSyncContext | None,
    ) -> Document | ConnectorFailure | None:
        """
        Converts a single retrieved file to a document.
        """
        return self._convert_drive_file(
            retrieved_file.drive_file,
            [retrieved_file.user_email, self.primary_admin_email]
            + get_file_owners(retrieved_file.drive_file, self.primary_admin_email),
            permission_sync_context,
        )

    def _convert_drive_file(
        self,
        drive_file: GoogleDriveFileType,
        retriever_emails: list[str],
        permission_sync_context: PermissionSyncContext | None,
        folder_path: list[str] | None = None,
    ) -> Document | ConnectorFailure | None:
        try:
            return convert_drive_item_to_document(
                self.ops,
                self.allow_images,
                self.size_threshold,
                permission_sync_context,
                retriever_emails,
                drive_file,
                self.raw_file_callback,
                folder_path,
            )
        except Exception as e:
            logger.exception(
                "Error extracting document: %s from Google Drive",
                drive_file.get("name"),
            )
            return ConnectorFailure(
                failed_entity=EntityFailure(
                    entity_id=drive_file.get("id", "unknown"),
                ),
                failure_message=(
                    f"Error extracting document: {drive_file.get('name')}"
                ),
                exception=e,
            )

    def resolve_targets(
        self,
        targets: list[ResolveTarget],
        include_permissions: bool = False,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        """Converts each target from the file fields its listing stored, with
        no metadata fetch and no ancestor walk. A target without them goes
        through `reindex`."""
        if self._ops is None or self._primary_admin_email is None:
            raise RuntimeError(
                "Credentials missing, should not call this method before calling load_credentials"
            )
        # Permission sync and the link-only filter read the file's
        # permissions. A listing without them cannot stand in for the fetch.
        need_permissions = include_permissions or self.exclude_domain_link_only
        listed: list[tuple[GoogleDriveFileType, list[str], list[str] | None]] = []
        unlisted: list[ResolveTarget] = []
        for target in targets:
            payload = target.listing_payload
            if (
                isinstance(payload, DriveListingPayload)
                and payload.drive_file
                and (not need_permissions or "permissionIds" in payload.drive_file)
            ):
                drive_file = cast(GoogleDriveFileType, payload.drive_file)
                readers = _rotated_readers(drive_file, payload)
                if self.primary_admin_email not in readers:
                    readers.append(self.primary_admin_email)
                listed.append((drive_file, readers, payload.folder_path))
            else:
                unlisted.append(target)
        if unlisted:
            yield from super().resolve_targets(unlisted, include_permissions)

        permission_sync_context = (
            PermissionSyncContext(
                primary_admin_email=self.primary_admin_email,
                google_domain=self.google_domain,
            )
            if include_permissions
            else None
        )
        results = cast(
            list[Document | ConnectorFailure | None],
            run_functions_tuples_in_parallel(
                [
                    (
                        self._convert_drive_file,
                        (drive_file, readers, permission_sync_context, folder_path),
                    )
                    for drive_file, readers, folder_path in listed
                ],
                max_workers=DRIVE_CONVERSION_WORKERS,
            ),
        )
        for result in results:
            if result is not None:
                yield result

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GoogleDriveCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[GoogleDriveCheckpoint]:
        """
        Entrypoint for the connector; first run is with an empty checkpoint.
        """
        if self._ops is None or self._primary_admin_email is None:
            raise RuntimeError(
                "Credentials missing, should not call this method before calling load_credentials"
            )

        logger.info(
            "Loading from checkpoint, num retrieved ids: %s",
            len(checkpoint.retrieved_drive_file_ids),
        )
        checkpoint = copy.deepcopy(checkpoint)
        try:
            listing = self._plan_listing(checkpoint, start, end)
            # Closed also when this call fails or its caller stops early, so
            # the listing threads stop now.
            with closing(
                self._fetch_drive_items(
                    checkpoint, include_permissions=include_permissions, inline=True
                )
            ) as listed_files:
                yield from self._convert_retrieved_files_to_documents(
                    _interleave_by_user(listed_files, DRIVE_INTERLEAVE_LOOKAHEAD),
                    checkpoint,
                    listing,
                    include_permissions,
                )
            if listing.is_done:
                for parents in self._resolve_unlisted_parents(
                    checkpoint, include_permissions, add_prefix=True
                ):
                    yield from parents
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

        logger.info(
            "num drive files retrieved: %s", len(checkpoint.retrieved_drive_file_ids)
        )
        if listing.is_done:
            checkpoint.has_more = False
        return checkpoint

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GoogleDriveCheckpoint,
    ) -> CheckpointOutput[GoogleDriveCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=False
        )

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GoogleDriveCheckpoint,
    ) -> CheckpointOutput[GoogleDriveCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=True
        )

    @override
    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        if self._ops is None or self._primary_admin_email is None:
            raise RuntimeError(
                "Credentials missing, should not call this method before calling load_credentials"
            )

        logger.info("Reindexing %s docs from errors", len(errors))
        doc_ids = [
            failure.failed_document.document_id
            for failure in errors
            if failure.failed_document
        ]
        field_type = (
            DriveFileFieldType.WITH_PERMISSIONS
            if include_permissions or self.exclude_domain_link_only
            else DriveFileFieldType.STANDARD
        )
        batch_result = get_files_by_web_view_links_batch(
            self.ops, self.primary_admin_email, doc_ids, field_type
        )

        for doc_id, error in batch_result.errors.items():
            yield ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=doc_id,
                    document_link=doc_id,
                ),
                failure_message=f"Failed to retrieve file during error resolution: {error}",
                exception=error,
            )

        permission_sync_context = (
            PermissionSyncContext(
                primary_admin_email=self.primary_admin_email,
                google_domain=self.google_domain,
            )
            if include_permissions
            else None
        )

        retrieved_files = [
            RetrievedDriveFile(
                drive_file=file,
                user_email=self.primary_admin_email,
            )
            for file in batch_result.files.values()
            if self._listing_skip_reason(file) is None
        ]

        # The files' folders, read up to their roots as a listing reads the
        # parents that no folder listing returned.
        parents = self.build_dummy_checkpoint()
        parents.listing = DriveListingState(
            window_t0=0,
            window_t1=0,
            unresolved_parent_emails={
                parent_id: [retrieved.user_email]
                for retrieved in retrieved_files
                if (parent_id := _get_parent_id_from_file(retrieved.drive_file))
            },
        )
        for nodes in self._resolve_unlisted_parents(
            parents, include_permissions, add_prefix=True
        ):
            yield from nodes

        func_with_args = [
            (
                self._convert_retrieved_file_to_document,
                (rf, permission_sync_context),
            )
            for rf in retrieved_files
        ]
        results = cast(
            list[Document | ConnectorFailure | None],
            run_functions_tuples_in_parallel(
                func_with_args, max_workers=DRIVE_FETCH_WORKERS
            ),
        )
        for result in results:
            if result is not None:
                yield result

    def _extract_slim_docs_from_google_drive(
        self,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
        include_permissions: bool = True,
        stub_failures: list[ConnectorFailure] | None = None,
    ) -> Generator[list[SlimDocument | HierarchyNode], None, None]:
        """Lists the files that indexing would index. With ``stub_failures``,
        the listing is for indexing: it yields ``SlimDocumentStub``s and adds a
        retrieval error to ``stub_failures``. Without it, a retrieval error is
        raised."""
        for_indexing = stub_failures is not None
        listing = self._plan_listing(checkpoint, start, end)
        # The stream also holds folders, which become hierarchy nodes.
        drive_files = self._fetch_drive_items(
            checkpoint, include_permissions=include_permissions
        )
        permission_sync_context = (
            PermissionSyncContext(
                primary_admin_email=self.primary_admin_email,
                google_domain=self.google_domain,
            )
            if include_permissions
            else None
        )
        files_batch: list[RetrievedDriveFile] = []
        folders_batch: list[RetrievedDriveFile] = []

        def _yield_slim_batch() -> list[SlimDocument | HierarchyNode]:
            """Process files batch and return items to yield (hierarchy nodes + slim docs)."""
            nonlocal files_batch, folders_batch

            # Hierarchy nodes of the new folders first
            new_ancestors = self._listed_folder_nodes(
                listing,
                checkpoint,
                folders_batch,
                files_batch,
                permission_sync_context,
                add_prefix=False,
            )

            # Build slim documents. With permissions, each may call permissions.list
            slim_docs = [
                doc
                for doc in cast(
                    list[SlimDocument | None],
                    run_functions_tuples_in_parallel(
                        [
                            (
                                (
                                    build_slim_document_stub
                                    if for_indexing
                                    else build_slim_document
                                ),
                                (
                                    self.ops,
                                    file.drive_file,
                                    permission_sync_context,
                                    file.user_email,
                                ),
                            )
                            for file in files_batch
                        ],
                        max_workers=DRIVE_FETCH_WORKERS,
                    ),
                )
                if doc
            ]

            # Combine: hierarchy nodes first, then slim docs
            result: list[SlimDocument | HierarchyNode] = []
            result.extend(new_ancestors)
            result.extend(slim_docs)
            files_batch = []
            folders_batch = []
            return result

        # Closed also when the caller fails or stops early, so the listing
        # threads stop now.
        with closing(drive_files):
            for file in drive_files:
                if file.error is not None:
                    if stub_failures is None:
                        raise file.error
                    stub_failures.append(_retrieval_failure(file))
                    continue
                if file.drive_file.get("mimeType") == DRIVE_FOLDER_TYPE:
                    folders_batch.append(file)
                    if len(folders_batch) >= SLIM_BATCH_SIZE:
                        yield _yield_slim_batch()
                    continue
                if self._listing_skip_reason(file.drive_file) is not None:
                    continue
                files_batch.append(file)

                if len(files_batch) >= SLIM_BATCH_SIZE:
                    yield _yield_slim_batch()
                    _stop_or_report_progress(
                        callback, "_extract_slim_docs_from_google_drive"
                    )

        # Yield remaining files
        if files_batch or folders_batch:
            yield _yield_slim_batch()
        if listing.is_done:
            for parents in self._resolve_unlisted_parents(
                checkpoint, include_permissions, add_prefix=False
            ):
                parent_batch: list[SlimDocument | HierarchyNode] = list(parents)
                yield parent_batch

    def _listed_folder_nodes(
        self,
        listing: DriveListingState,
        checkpoint: GoogleDriveCheckpoint,
        folders: list[RetrievedDriveFile],
        files: list[RetrievedDriveFile],
        permission_sync_context: PermissionSyncContext | None,
        add_prefix: bool,
    ) -> list[HierarchyNode]:
        """Hierarchy nodes for the listed folders that are new. Records each
        parent that is not yielded yet, with a user who can see its child.

        A user who cannot see a folder's parent gets the folder with no
        parent. A later copy that shows the parent yields the node again
        with it. A folder shared only by link, with link-only exclusion on,
        is a node only as the parent of another node: the read of unlisted
        parents yields it then."""
        seen = checkpoint.seen_hierarchy_node_raw_ids
        parentless = listing.parentless_folder_emails
        new_folders: list[RetrievedDriveFile] = []
        repaired: list[RetrievedDriveFile] = []
        for folder in folders:
            drive_file = folder.drive_file
            folder_id = drive_file["id"]
            if self.exclude_domain_link_only and has_link_only_permission(drive_file):
                continue
            if not seen.check_and_add(folder_id):
                new_folders.append(folder)
            elif folder_id in parentless and _get_parent_id_from_file(drive_file):
                del parentless[folder_id]
                repaired.append(folder)
        yielded = [*new_folders, *repaired]
        nodes = cast(
            list[HierarchyNode],
            run_functions_tuples_in_parallel(
                [
                    (
                        self._folder_node,
                        (folder.drive_file, permission_sync_context, add_prefix),
                    )
                    for folder in yielded
                ],
                max_workers=DRIVE_FETCH_WORKERS,
            ),
        )
        unresolved = listing.unresolved_parent_emails
        for folder in yielded:
            unresolved.pop(folder.drive_file["id"], None)
        for folder in new_folders:
            if not _get_parent_id_from_file(folder.drive_file):
                parentless[folder.drive_file["id"]] = folder.user_email
        for item in [*yielded, *files]:
            parent_id = _get_parent_id_from_file(item.drive_file)
            if (
                parent_id
                and parent_id not in seen
                and parent_id not in checkpoint.fully_walked_hierarchy_node_raw_ids
            ):
                _add_parent_reader(unresolved, parent_id, item.user_email)
        return nodes

    def _resolve_unlisted_parents(
        self,
        checkpoint: GoogleDriveCheckpoint,
        include_permissions: bool,
        add_prefix: bool,
    ) -> Iterator[list[HierarchyNode]]:
        """After the listing: reads what no folder listing gave. First the
        folders listed with no parent: a read as the lister or the admin can
        show the parent. Then the parents that no folder listing yielded, for
        example the folder of a file shared with a user who cannot see that
        folder, or a drive root, up the tree. Each folder is read once in this
        attempt. The reads stop at a folder already yielded and at a drive
        root. Yields the nodes in batches of at most PARENT_READ_BATCH_SIZE
        reads; the work left stays in the checkpoint."""
        listing = checkpoint.listing
        if listing is None:
            return
        permission_sync_context = (
            PermissionSyncContext(
                primary_admin_email=self.primary_admin_email,
                google_domain=self.google_domain,
            )
            if include_permissions
            else None
        )
        seen = checkpoint.seen_hierarchy_node_raw_ids
        walked = checkpoint.fully_walked_hierarchy_node_raw_ids
        if listing.parentless_folder_emails or listing.unresolved_parent_emails:
            logger.info(
                "Reading %s folders listed with no parent and %s parent folders "
                "that no folder listing returned",
                len(listing.parentless_folder_emails),
                len(listing.unresolved_parent_emails),
            )
        while listing.parentless_folder_emails:
            batch = _take(listing.parentless_folder_emails, PARENT_READ_BATCH_SIZE)
            nodes = [
                node
                for node in cast(
                    list[HierarchyNode | None],
                    run_functions_tuples_in_parallel(
                        [
                            (
                                self._read_parentless_folder,
                                (
                                    folder_id,
                                    email,
                                    checkpoint,
                                    permission_sync_context,
                                    add_prefix,
                                ),
                            )
                            for folder_id, email in batch.items()
                        ],
                        max_workers=DRIVE_FETCH_WORKERS,
                    ),
                )
                if node is not None
            ]
            for node in nodes:
                parent_id = node.raw_parent_id
                if parent_id and parent_id not in seen and parent_id not in walked:
                    _add_parent_reader(
                        listing.unresolved_parent_emails,
                        parent_id,
                        batch[node.raw_node_id],
                    )
            # Also when no read gave a node: the consumer checks its stop
            # signal and reports progress for each batch.
            yield nodes
        while listing.unresolved_parent_emails:
            batch = _take(listing.unresolved_parent_emails, PARENT_READ_BATCH_SIZE)
            batch = {
                folder_id: emails
                for folder_id, emails in batch.items()
                if folder_id not in seen
            }
            results = cast(
                list[tuple[HierarchyNode | None, str | None]],
                run_functions_tuples_in_parallel(
                    [
                        (
                            self._read_unlisted_folder,
                            (
                                folder_id,
                                emails,
                                checkpoint,
                                permission_sync_context,
                                add_prefix,
                            ),
                        )
                        for folder_id, emails in batch.items()
                    ],
                    max_workers=DRIVE_FETCH_WORKERS,
                ),
            )
            nodes = []
            for (folder_id, emails), (node, parent_id) in zip(
                batch.items(), results, strict=True
            ):
                if node is not None:
                    nodes.append(node)
                if (
                    parent_id is not None
                    and parent_id not in seen
                    and (parent_id not in walked)
                ):
                    for email in emails:
                        _add_parent_reader(
                            listing.unresolved_parent_emails, parent_id, email
                        )
                logger.debug("Read unlisted folder %s as one of %s", folder_id, emails)
            yield nodes

    def _read_parentless_folder(
        self,
        folder_id: str,
        email: str,
        checkpoint: GoogleDriveCheckpoint,
        permission_sync_context: PermissionSyncContext | None,
        add_prefix: bool,
    ) -> HierarchyNode | None:
        """The node of a folder listed with no parent, when the lister or the
        admin can now see its parent. None leaves the folder at the root."""
        field_type = (
            DriveFileFieldType.WITH_PERMISSIONS
            if permission_sync_context
            else DriveFileFieldType.STANDARD
        )
        folder = self._get_folder_metadata(
            folder_id, email, field_type, checkpoint.failed_folder_ids_by_email
        )
        if folder is None or not _get_parent_id_from_file(folder):
            return None
        return self._folder_node(
            folder, permission_sync_context, add_prefix, raw_id=folder_id
        )

    def _read_unlisted_folder(
        self,
        folder_id: str,
        emails: list[str],
        checkpoint: GoogleDriveCheckpoint,
        permission_sync_context: PermissionSyncContext | None,
        add_prefix: bool,
    ) -> tuple[HierarchyNode | None, str | None]:
        """The node for one folder, and the parent to read next (None at a
        root or when the folder cannot be read). Reads as each of ``emails``
        and then as the admin, until one can read the folder."""
        if checkpoint.seen_hierarchy_node_raw_ids.check_and_add(folder_id):
            return None, None
        field_type = (
            DriveFileFieldType.WITH_PERMISSIONS
            if permission_sync_context
            else DriveFileFieldType.STANDARD
        )
        folder: GoogleDriveFileType | None = None
        email = ""
        for email in emails:
            folder = self._get_folder_metadata(
                folder_id, email, field_type, checkpoint.failed_folder_ids_by_email
            )
            if folder is not None:
                break
        if folder is None:
            # Documents under it keep their STUB parent.
            return None, None
        node = self._folder_node(
            folder, permission_sync_context, add_prefix, raw_id=folder_id
        )
        if _is_shared_drive_root(folder):
            drive_name = self._get_shared_drive_name(folder_id, email)
            if drive_name:
                node.display_name = drive_name
            node.node_type = HierarchyNodeType.SHARED_DRIVE
            checkpoint.fully_walked_hierarchy_node_raw_ids.add(folder_id)
            return node, None
        if self._is_my_drive_root(folder, email):
            checkpoint.fully_walked_hierarchy_node_raw_ids.add(folder_id)
            return node, None
        return node, node.raw_parent_id

    def _retrieve_all_slim_docs_impl(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
        include_permissions: bool = True,
        for_pruning: bool = False,
        checkpoint: GoogleDriveCheckpoint | None = None,
        on_checkpoint: Callable[[GoogleDriveCheckpoint], None] | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Runs the listing to its end in this process, one call at a time.
        ``for_pruning`` raises ``UnreachableTargetsError`` at the end when a
        requested target was not listed."""
        try:
            if checkpoint is None:
                checkpoint = self.build_dummy_checkpoint()
            # The shard engine lists [start, end). A file edited during the
            # listing moves past the end. Pruning reads a missing file as
            # deleted, and permission sync would keep its old permissions. So
            # a listing with no end from the caller finishes with a pass with
            # no upper bound, and it is complete only after that pass.
            last_pass = end is None
            while True:
                while not _listing_done(checkpoint):
                    yield from self._extract_slim_docs_from_google_drive(
                        checkpoint=checkpoint,
                        start=start,
                        end=end,
                        callback=callback,
                        include_permissions=include_permissions,
                    )
                    # The caller consumed every batch yielded so far before
                    # this resumed
                    if on_checkpoint and not _listing_done(checkpoint):
                        on_checkpoint(checkpoint)
                    # A pass ends after a budget even when every file was
                    # filtered or none changed, so it counts as progress
                    _stop_or_report_progress(callback, "_retrieve_all_slim_docs_impl")
                if not last_pass or checkpoint.listing is None:
                    break
                last_pass = False
                open_window_end(checkpoint.listing)
            if for_pruning and checkpoint.unreachable_target_ids:
                # Pruning deletes whatever this listing lacks, which for an
                # unreachable target is every document indexed from it.
                raise UnreachableTargetsError(
                    "Refusing to report a complete listing: requested targets "
                    f"{sorted(checkpoint.unreachable_target_ids)} are not visible "
                    "to any user."
                )
            logger.info("Drive slim doc retrieval complete")
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        return self._retrieve_all_slim_docs_impl(
            start=start,
            end=end,
            callback=callback,
            include_permissions=False,
            for_pruning=True,
        )

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
        checkpoint: GoogleDriveCheckpoint | None = None,
        on_checkpoint: Callable[[GoogleDriveCheckpoint], None] | None = None,
    ) -> GenerateSlimDocumentOutput:
        """``checkpoint`` resumes a stopped crawl. ``on_checkpoint`` receives the
        crawl state at each point where it can resume without skipping files."""
        return self._retrieve_all_slim_docs_impl(
            start=start,
            end=end,
            callback=callback,
            include_permissions=True,
            checkpoint=checkpoint,
            on_checkpoint=on_checkpoint,
        )

    @override
    def retrieve_slim_docs_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GoogleDriveCheckpoint,
        include_permissions: bool = False,
    ) -> SlimCheckpointOutput[GoogleDriveCheckpoint]:
        """One call of the slim listing, for indexing. The call ends only at
        its time or file budget (CALL_BUDGET_SECONDS, CALL_BUDGET_FILES). The
        returned checkpoint covers exactly the stubs this call yielded."""
        if self._ops is None or self._primary_admin_email is None:
            raise RuntimeError(
                "Credentials missing, should not call this method before calling load_credentials"
            )
        checkpoint = copy.deepcopy(checkpoint)
        failures: list[ConnectorFailure] = []
        try:
            # Closed also when the caller stops early, so the listing threads
            # stop now.
            with closing(
                self._extract_slim_docs_from_google_drive(
                    checkpoint=checkpoint,
                    start=start,
                    end=end,
                    include_permissions=include_permissions,
                    stub_failures=failures,
                )
            ) as batches:
                for batch in batches:
                    yield from failures
                    failures.clear()
                    yield from batch
            yield from failures
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise
        if _listing_done(checkpoint):
            checkpoint.has_more = False
        return checkpoint

    def _plan_listing(
        self,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
    ) -> DriveListingState:
        """Sets up ``checkpoint.listing`` for this call and returns it. With
        no ``end``, a new listing ends now and a started one keeps its end.

        The first call plans the partitions: shared drives, then My Drives,
        then the files shared with each user, then the requested folders
        (including requested drive ids that are folders). An OAuth credential
        lists as its one user."""
        state = checkpoint.listing
        if state is None:
            # A new attempt, or a checkpoint of the serial listing that this
            # version removed. Its claims and progress do not apply, so the
            # attempt lists again from its window start.
            _drop_listing_state(checkpoint)
        t0, t1 = window_ms(start or 0, time.time() if end is None else end)
        if state is not None and state.window_t0 != t0:
            logger.warning(
                "The listing window start changed from %s to %s; listing again "
                "from the start.",
                state.window_t0,
                t0,
            )
            state = None
            _drop_listing_state(checkpoint)
        if state is not None:
            if end is not None:
                # A resumed attempt has a later end. List the added range too.
                extend_window(state, t1)
            return state

        self._run_inventory(checkpoint)
        partitions = [
            ListingPartition(kind=ListingPartitionKind.SHARED_DRIVE, key=drive_id)
            for drive_id in checkpoint.drive_ids_to_retrieve or []
        ]
        if self._is_service_account:
            user_emails = self._my_drive_partition_emails(checkpoint)
            shared_with_emails = (
                user_emails if self.include_files_shared_with_me else []
            )
        else:
            # The OAuth user's own files and the files shared with the user.
            # Together with the member drives, this is the allDrives corpus.
            # my_drive_emails does not apply to OAuth.
            oauth_user = [self.primary_admin_email]
            user_emails = oauth_user if self.include_my_drives else []
            shared_with_emails = oauth_user if self.include_files_shared_with_me else []
        partitions.extend(
            ListingPartition(kind=ListingPartitionKind.MY_DRIVE, key=email)
            for email in user_emails
        )
        partitions.extend(
            ListingPartition(kind=ListingPartitionKind.SHARED_WITH_USER, key=email)
            for email in shared_with_emails
        )
        partitions.extend(
            ListingPartition(kind=ListingPartitionKind.FOLDER_SUBTREE, key=folder_id)
            for folder_id in checkpoint.folder_ids_to_retrieve or []
        )
        state = DriveListingState(
            window_t0=t0, window_t1=t1, pending_partitions=partitions
        )
        checkpoint.listing = state
        logger.info("Parallel listing: %s partitions planned", len(partitions))
        return state

    def _fetch_drive_items(
        self,
        checkpoint: GoogleDriveCheckpoint,
        include_permissions: bool = False,
        inline: bool = False,
    ) -> Generator[RetrievedDriveFile, None, None]:
        """One call of the listing (``ParallelDriveLister``), for a service
        account and for OAuth. ``_plan_listing`` runs first. Counts the files
        that pass the metadata check. The engine asks for permissions only
        when ``include_permissions`` or the link-only filter needs them. With
        ``inline``, the caller converts each file in this call."""

        def choose_drive_principal(
            drive_id: str, busy: Collection[str]
        ) -> tuple[str | None, bool]:
            if not self._is_service_account:
                # The OAuth user is the only principal. Its drives come from
                # its own drives.list, so it is a member: the listing is
                # complete.
                return self.primary_admin_email, True
            return self._choose_drive_principal(drive_id, checkpoint, busy)

        def check_impersonation(email: str) -> tuple[bool, list[RetrievedDriveFile]]:
            if not self._is_service_account:
                # OAuth uses its own token. A failure fails the listing.
                return True, []
            failures: list[RetrievedDriveFile] = []
            gate = self._impersonation_gate(email, checkpoint)
            while True:
                try:
                    failures.append(next(gate))
                except StopIteration as stop:
                    return bool(stop.value), failures

        def impersonation_failed(
            email: str, error: GoogleDriveRefreshError
        ) -> list[RetrievedDriveFile]:
            if not self._is_service_account:
                # No other principal can list the OAuth user's files. A
                # partial listing would read as deleted files.
                raise error
            return list(self._impersonation_failed(email, error, checkpoint))

        def listing_denied(
            partition: ListingPartition, email: str, error: GoogleDriveHttpError
        ) -> list[RetrievedDriveFile]:
            if not self._is_service_account:
                # No other principal can list the OAuth user's files. A
                # denied page read as empty would read as deleted files.
                raise error
            logger.warning(
                "Drive denied the %s listing of %s as %s: %s",
                partition.kind.value,
                partition.key,
                email,
                error,
            )
            # A partition keyed by a drive or a folder id names its parent.
            keyed_by_parent = partition.kind in (
                ListingPartitionKind.SHARED_DRIVE,
                ListingPartitionKind.FOLDER_SUBTREE,
            )
            return [
                RetrievedDriveFile(
                    drive_file={},
                    user_email=email,
                    parent_id=partition.key if keyed_by_parent else None,
                    error=error,
                )
            ]

        def admit_file(drive_file: GoogleDriveFileType, exact: bool) -> bool:
            return self._admit_file(checkpoint, drive_file, exact)

        def plan_folder_target(
            folder_id: str, covered_drive_ids: Collection[str]
        ) -> FolderTargetPlan:
            def covered_drive(metadata: GoogleDriveFileType) -> str | None:
                drive_id = metadata.get("driveId")
                if isinstance(drive_id, str) and drive_id in covered_drive_ids:
                    return drive_id
                return None

            if not self._is_service_account:
                # The OAuth user is the only principal.
                metadata = self.ops.probe_target(
                    user_email=self.primary_admin_email, target_id=folder_id
                )
                if metadata is None:
                    return FolderTargetPlan()
                return FolderTargetPlan(
                    principals=[self.primary_admin_email],
                    covered_drive_id=covered_drive(metadata),
                )
            found = self._find_target_viewer(folder_id, checkpoint)
            if found is None:
                return FolderTargetPlan()
            viewer, metadata = found
            return FolderTargetPlan(
                principals=self._target_principals(
                    folder_id, viewer, metadata, checkpoint
                ),
                covered_drive_id=covered_drive(metadata),
            )

        lister = ParallelDriveLister(
            ops=self.ops,
            checkpoint=checkpoint,
            # Without permission sync, pages carry no permissions, so Drive
            # can serve 1000 files a page.
            field_type=(
                DriveFileFieldType.WITH_PERMISSIONS
                if include_permissions or self.exclude_domain_link_only
                else DriveFileFieldType.STANDARD
            ),
            requested_shared_drive_ids=self._requested_shared_drive_ids,
            choose_drive_principal=choose_drive_principal,
            check_impersonation=check_impersonation,
            impersonation_failed=impersonation_failed,
            listing_denied=listing_denied,
            admit_file=admit_file,
            plan_folder_target=plan_folder_target,
            inline=inline,
            # As the serial OAuth listing's allDrives corpus.
            shared_with_all_drives=(
                not self._is_service_account
                and self.include_shared_drives
                and self.include_my_drives
                and self.include_files_shared_with_me
            ),
        )
        state = checkpoint.listing
        if state is None:
            raise RuntimeError("The listing has no state")
        with closing(lister.run()) as files:
            for file in files:
                if (
                    file.error is None
                    and self._listing_skip_reason(file.drive_file) is None
                ):
                    _count_listed_file(state, file.drive_file)
                yield file

    def validate_connector_settings(self) -> None:
        if self._ops is None:
            raise ConnectorMissingCredentialError(
                "Google Drive credentials not loaded."
            )

        if self._primary_admin_email is None:
            raise ConnectorValidationError(
                "Primary admin email not found in credentials. Ensure DB_CREDENTIALS_PRIMARY_ADMIN_KEY is set."
            )

        try:
            next(
                self.ops.list_files(
                    variant=DriveCorpus.USER,
                    user_email=self._primary_admin_email,
                    fields="nextPageToken, files(id)",
                    page_size=1,
                    max_num_pages=1,
                ),
                None,
            )

            if self._is_service_account:
                # default is ~17mins of retries, don't do that here since this is called from
                # the UI
                retry_builder(tries=3, delay=0.1)(self.ops.get_root_folder_id)(
                    user_email=self._primary_admin_email
                )

        except GoogleDriveHttpError as e:
            status_code = e.status_code
            if status_code == 401:
                raise CredentialExpiredError(
                    "Invalid or expired Google Drive credentials (401)."
                )
            elif status_code == 403:
                raise InsufficientPermissionsError(
                    "Google Drive app lacks required permissions (403). "
                    "Please ensure the necessary scopes are granted and Drive "
                    "apps are enabled."
                )
            else:
                raise ConnectorValidationError(
                    f"Unexpected Google Drive error (status={status_code}): {e}"
                )

        except Exception as e:
            # Check for scope-related hints from the error message
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise InsufficientPermissionsError(
                    f"Google Drive credentials are missing required scopes. {ONYX_SCOPE_INSTRUCTIONS}"
                )
            raise ConnectorValidationError(
                f"Unexpected error during Google Drive validation: {e}"
            )

    def probe_directory_admin_permission(self) -> None:
        """Verify the configured primary admin can call the Workspace directory API.

        Required for permission sync, which calls
        `admin.directory.users.get` to enumerate Workspace users and groups.
        A 403 here predicts the same 403 in `_get_drive_members` mid-sync, so
        misconfigured connectors fail at creation time instead of generating a
        steady stream of `PermissionError` log lines on every group-sync tick.
        """
        try:
            self.ops.get_admin_user()
        except GoogleDriveHttpError as e:
            status_code = e.status_code
            if status_code == 403:
                raise InsufficientPermissionsError(
                    f"Primary admin {self.primary_admin_email} is not authorized "
                    "on the Google Workspace directory API. Reconnect the connector "
                    "with an account that has admin directory access."
                )
            if status_code == 401:
                raise CredentialExpiredError(
                    "Invalid or expired Google Drive credentials (401)."
                )
            raise ConnectorValidationError(
                f"Unexpected Google Workspace directory API error (status={status_code}): {e}"
            )
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise InsufficientPermissionsError(
                    f"Google Drive credentials are missing required scopes. {ONYX_SCOPE_INSTRUCTIONS} Full error: {e}"
                )
            raise ConnectorValidationError(
                f"Unexpected error during Google Workspace directory API probe: {e}"
            )

    @override
    def build_dummy_checkpoint(self) -> GoogleDriveCheckpoint:
        return GoogleDriveCheckpoint(retrieved_drive_file_ids=set(), has_more=True)

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> GoogleDriveCheckpoint:
        return GoogleDriveCheckpoint.model_validate_json(checkpoint_json)


def get_credentials_from_env(email: str, oauth: bool) -> dict:
    if oauth:
        raw_credential_string = os.environ["GOOGLE_DRIVE_OAUTH_CREDENTIALS_JSON_STR"]
    else:
        raw_credential_string = os.environ["GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR"]

    refried_credential_string = json.dumps(json.loads(raw_credential_string))

    # This is the Oauth token
    DB_CREDENTIALS_DICT_TOKEN_KEY = "google_tokens"
    # This is the service account key
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY = "google_service_account_key"
    # The email saved for both auth types
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY = "google_primary_admin"
    DB_CREDENTIALS_AUTHENTICATION_METHOD = "authentication_method"
    cred_key = (
        DB_CREDENTIALS_DICT_TOKEN_KEY
        if oauth
        else DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY
    )
    return {
        cred_key: refried_credential_string,
        DB_CREDENTIALS_PRIMARY_ADMIN_KEY: email,
        DB_CREDENTIALS_AUTHENTICATION_METHOD: "uploaded",
    }


class CheckpointOutputWrapper:
    """
    Wraps a CheckpointOutput generator to give things back in a more digestible format.
    The connector format is easier for the connector implementor (e.g. it enforces exactly
    one new checkpoint is returned AND that the checkpoint is at the end), thus the different
    formats.
    """

    def __init__(self) -> None:
        self.next_checkpoint: GoogleDriveCheckpoint | None = None

    def __call__(
        self,
        checkpoint_connector_generator: CheckpointOutput[GoogleDriveCheckpoint],
    ) -> Generator[
        tuple[Document | None, ConnectorFailure | None, GoogleDriveCheckpoint | None],
        None,
        None,
    ]:
        # grabs the final return value and stores it in the `next_checkpoint` variable
        def _inner_wrapper(
            checkpoint_connector_generator: CheckpointOutput[GoogleDriveCheckpoint],
        ) -> CheckpointOutput[GoogleDriveCheckpoint]:
            self.next_checkpoint = yield from checkpoint_connector_generator
            return self.next_checkpoint  # not used

        for document_or_failure in _inner_wrapper(checkpoint_connector_generator):
            if isinstance(document_or_failure, Document):
                yield document_or_failure, None, None
            elif isinstance(document_or_failure, ConnectorFailure):
                yield None, document_or_failure, None
            else:
                raise ValueError(
                    f"Invalid document_or_failure type: {type(document_or_failure)}"
                )

        if self.next_checkpoint is None:
            raise RuntimeError(
                "Checkpoint is None. This should never happen - the connector should always return a checkpoint."
            )

        yield None, None, self.next_checkpoint


def yield_all_docs_from_checkpoint_connector(
    connector: GoogleDriveConnector,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> Iterator[Document | ConnectorFailure]:
    num_iterations = 0

    checkpoint = connector.build_dummy_checkpoint()
    while checkpoint.has_more:
        doc_batch_generator = CheckpointOutputWrapper()(
            connector.load_from_checkpoint(start, end, checkpoint)
        )
        for document, failure, next_checkpoint in doc_batch_generator:
            if failure is not None:
                yield failure
            if document is not None:
                yield document
            if next_checkpoint is not None:
                checkpoint = next_checkpoint

        num_iterations += 1
        if num_iterations > 100_000:
            raise RuntimeError("Too many iterations. Infinite loop?")


if __name__ == "__main__":
    import time

    creds = get_credentials_from_env(
        os.environ["GOOGLE_DRIVE_PRIMARY_ADMIN_EMAIL"], False
    )
    connector = GoogleDriveConnector(
        include_shared_drives=True,
        shared_drive_urls=None,
        include_my_drives=True,
        my_drive_emails=None,
        shared_folder_urls=None,
        include_files_shared_with_me=True,
        specific_user_emails=None,
    )
    connector.load_credentials(creds)
    max_fsize = 0
    biggest_fsize = 0
    num_errors = 0
    start_time = time.time()
    with open("stats.txt", "w") as f:
        for num, doc_or_failure in enumerate(
            yield_all_docs_from_checkpoint_connector(connector, 0, time.time())
        ):
            if num % 200 == 0:
                f.write(f"Processed {num} files\n")
                f.write(f"Max file size: {max_fsize / 1000_000:.2f} MB\n")
                f.write(f"Time so far: {time.time() - start_time:.2f} seconds\n")
                f.write(
                    f"Docs per minute: {num / (time.time() - start_time) * 60:.2f}\n"
                )
                biggest_fsize = max(biggest_fsize, max_fsize)
                max_fsize = 0
            if isinstance(doc_or_failure, Document):
                max_fsize = max(max_fsize, sys.getsizeof(doc_or_failure))
            elif isinstance(doc_or_failure, ConnectorFailure):
                num_errors += 1
        print(f"Num errors: {num_errors}")
        print(f"Biggest file size: {biggest_fsize / 1000_000:.2f} MB")
        print(f"Time taken: {time.time() - start_time:.2f} seconds")
