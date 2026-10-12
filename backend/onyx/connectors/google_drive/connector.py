import copy
import json
import os
import sys
from collections.abc import Generator, Iterator
from datetime import datetime
from typing import Any, Protocol, cast
from urllib.parse import ParseResult, parse_qs, urlparse

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.errors import HttpError
from typing_extensions import override

from onyx.access.models import ExternalAccess
from onyx.configs.app_configs import (
    GOOGLE_DRIVE_CONNECTOR_SIZE_THRESHOLD,
    INDEX_BATCH_SIZE,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.google_drive.doc_conversion import (
    _FALLBACK_BINARY_WEB_VIEW_LINK_TEMPLATE,
    _FALLBACK_WEB_VIEW_LINK_TEMPLATES,
    WEB_VIEW_LINK_KEY,
    PermissionSyncContext,
    build_slim_document,
    convert_drive_item_to_document,
    onyx_document_id_from_drive_file,
)
from onyx.connectors.google_drive.drive_access import (
    can_list_drive,
    internal_principals_of,
    list_drive_members,
    list_group_member_emails,
    probe_target,
    select_drive_organizer,
)
from onyx.connectors.google_drive.file_retrieval import (
    RESOLVED_FROM_SHORTCUT_KEY,
    DriveFileFieldType,
    crawl_folders_for_files,
    get_all_files_for_oauth,
    get_all_files_in_my_drive_and_shared,
    get_external_access_for_folder,
    get_files_by_web_view_links_batch,
    get_files_in_shared_drive,
    get_folder_metadata,
    get_root_folder_id,
    get_shared_drive_name,
    has_link_only_permission,
)
from onyx.connectors.google_drive.models import (
    DriveRetrievalPhase,
    DriveRetrievalStage,
    GoogleDriveCheckpoint,
    GoogleDriveFileType,
    PhaseProgress,
    RetrievedDriveFile,
    StageCompletion,
    next_phase,
    split_target_partition_key,
    target_partition_key,
)
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.google_utils import (
    GoogleFields,
    execute_paginated_retrieval,
    get_file_owners,
    is_access_denied,
)
from onyx.connectors.google_utils.resources import (
    GoogleDriveService,
    ImpersonationError,
    get_admin_service,
    get_drive_service,
    make_user_removal_checker,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
    MISSING_SCOPES_ERROR_STR,
    ONYX_SCOPE_INSTRUCTIONS,
    SLIM_BATCH_SIZE,
    USER_FIELDS,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    NormalizationResult,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
)
from onyx.db.enums import HierarchyNodeType
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder
from onyx.utils.threadpool_concurrency import (
    ThreadSafeDict,
    ThreadSafeSet,
    run_functions_tuples_in_parallel,
)

logger = setup_logger()
# TODO: Improve this by using the batch utility: https://googleapis.github.io/google-api-python-client/docs/batch.html
# All file retrievals could be batched and made at once

BATCHES_PER_CHECKPOINT = 1

# Documents converted per sub-batch. At up to CONNECTOR_MAX_EXTRACTED_TEXT_CHARS
# (~10 MB) each, 50 caps resident docs near ~500 MB regardless of drive size.
DRIVE_CONVERSION_BATCH_SIZE = 50

SHARED_DRIVE_PAGES_PER_CHECKPOINT = 2
MY_DRIVE_PAGES_PER_CHECKPOINT = 2
OAUTH_PAGES_PER_CHECKPOINT = 2
# Partitions (drives or users) started per service account checkpoint call.
PARTITIONS_PER_CHECKPOINT = 4

# Upper bound on the dedup set. Drive file ids measure ~119 bytes per entry with
# deep_getsizeof, so this holds it near 95 MB, well under
# CHECKPOINT_SIZE_LIMIT_BYTES.
MAX_DEDUP_DRIVE_FILE_IDS = 800_000


def _extract_str_list_from_comma_str(string: str | None) -> list[str]:
    if not string:
        return []
    return [s.strip() for s in string.split(",") if s.strip()]


def _extract_ids_from_urls(urls: list[str]) -> list[str]:
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


def _resume_start(
    completed_until: SecondsSinceUnixEpoch,
    start: SecondsSinceUnixEpoch | None,
) -> SecondsSinceUnixEpoch:
    """Resume from the checkpointed frontier, but never before the configured
    range start (a corrupted frontier must not widen the requested time range)."""
    return max(completed_until, start) if start is not None else completed_until


def _owner_email(drive_file: GoogleDriveFileType) -> str | None:
    """Lowercased owner of a My Drive file. Drive allows one owner; shared
    drive files have none."""
    owners = drive_file.get("owners") or []
    if not owners:
        return None
    email = owners[0].get("emailAddress")
    return email.lower() if isinstance(email, str) else None


def _note_modified_time(
    progress: PhaseProgress, drive_file: GoogleDriveFileType
) -> None:
    modified_time = drive_file.get(GoogleFields.MODIFIED_TIME.value)
    if not isinstance(modified_time, str):
        return
    try:
        timestamp = datetime.fromisoformat(modified_time).timestamp()
    except ValueError:
        return
    progress.completed_until = max(progress.completed_until, timestamp)


def _ignore_traversed_id(_folder_id: str) -> None:
    """The phased flow tracks coverage by partition, not by traversed folder."""


def _public_access() -> ExternalAccess:
    return ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids=set(),
        is_public=True,
    )


class CredentialedRetrievalMethod(Protocol):
    def __call__(
        self,
        field_type: DriveFileFieldType,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]: ...


def add_retrieval_info(
    drive_files: Iterator[GoogleDriveFileType | str],
    user_email: str,
    completion_stage: DriveRetrievalStage,
    parent_id: str | None = None,
) -> Iterator[RetrievedDriveFile | str]:
    for file in drive_files:
        if isinstance(file, str):
            yield file
            continue
        yield RetrievedDriveFile(
            drive_file=file,
            user_email=user_email,
            parent_id=parent_id,
            completion_stage=completion_stage,
        )


class UnreachableTargetsError(RuntimeError):
    """A requested drive or folder could not be listed by anyone."""


class GoogleDriveConnector(
    SlimConnector,
    SlimConnectorWithPermSync,
    CheckpointedConnectorWithPermSync[GoogleDriveCheckpoint],
    Resolver,
):
    slim_listing_honors_indexing_start = True

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

        shared_drive_url_list = _extract_str_list_from_comma_str(shared_drive_urls)
        self._requested_shared_drive_ids = set(
            _extract_ids_from_urls(shared_drive_url_list)
        )

        self._requested_my_drive_emails = set(
            _extract_str_list_from_comma_str(my_drive_emails)
        )

        shared_folder_url_list = _extract_str_list_from_comma_str(shared_folder_urls)
        self._requested_folder_ids = set(_extract_ids_from_urls(shared_folder_url_list))
        self._specific_user_emails = _extract_str_list_from_comma_str(
            specific_user_emails
        )
        self.exclude_domain_link_only = exclude_domain_link_only

        self._primary_admin_email: str | None = None

        self._creds: OAuthCredentials | ServiceAccountCredentials | None = None
        self._creds_dict: dict[str, Any] | None = None

        # ids of folders and shared drives that have been traversed
        self._retrieved_folder_and_drive_ids: set[str] = set()

        # Cache of known My Drive root IDs (user_email -> root_id)
        # Used to verify if a folder with no parents is actually a My Drive root
        # Thread-safe because multiple impersonation threads access this concurrently
        self._my_drive_root_id_cache: ThreadSafeDict[str, str] = ThreadSafeDict()

        self.allow_images = False

        self.size_threshold = GOOGLE_DRIVE_CONNECTOR_SIZE_THRESHOLD

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
    def creds(self) -> OAuthCredentials | ServiceAccountCredentials:
        if self._creds is None:
            raise RuntimeError(
                "Creds missing, should not call this property before calling load_credentials"
            )
        return self._creds

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

        self._creds, new_creds_dict = get_google_creds(
            credentials=credentials,
            source=DocumentSource.GOOGLE_DRIVE,
        )

        # Service account connectors don't have a specific setting determining whether
        # to include "shared with me" for each user, so we default to true unless the connector
        # is in specific folders/drives mode. Note that shared files are only picked up during
        # the My Drive stage, so this does nothing if the connector is set to only index shared drives.
        if (
            isinstance(self._creds, ServiceAccountCredentials)
            and not self.specific_requests_made
        ):
            self.include_files_shared_with_me = True

        self._creds_dict = new_creds_dict

        return new_creds_dict

    def _update_traversed_parent_ids(self, folder_id: str) -> None:
        self._retrieved_folder_and_drive_ids.add(folder_id)

    def _get_all_user_emails(self) -> list[str]:
        if self._specific_user_emails:
            return self._specific_user_emails

        # Start with primary admin email
        user_emails = [self.primary_admin_email]

        # Only fetch additional users if using service account
        if isinstance(self.creds, OAuthCredentials):
            return user_emails

        admin_service = get_admin_service(
            creds=self.creds,
            user_email=self.primary_admin_email,
        )

        # Get admins first since they're more likely to have access to most files
        for is_admin in [True, False]:
            query = "isAdmin=true" if is_admin else "isAdmin=false"
            for user in execute_paginated_retrieval(
                retrieval_function=admin_service.users().list,  # ty: ignore[unresolved-attribute]
                list_key="users",
                fields=USER_FIELDS,
                domain=self.google_domain,
                query=query,
            ):
                if email := user.get("primaryEmail"):
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
            drive_service = get_drive_service(self.creds, user_email)
            root_id = get_root_folder_id(drive_service)
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

    def _get_new_ancestors_for_files(
        self,
        files: list[RetrievedDriveFile],
        seen_hierarchy_node_raw_ids: ThreadSafeSet[str],
        fully_walked_hierarchy_node_raw_ids: ThreadSafeSet[str],
        failed_folder_ids_by_email: (
            ThreadSafeDict[str, ThreadSafeSet[str]] | None
        ) = None,
        permission_sync_context: PermissionSyncContext | None = None,
        add_prefix: bool = False,
    ) -> list[HierarchyNode]:
        """
        Get all NEW ancestor hierarchy nodes for a batch of files.

        For each file, walks up the parent chain until reaching a root/drive
        (terminal node with no parent). Returns HierarchyNode objects for all
        new ancestors.

        The function tracks two separate sets:
        - seen_hierarchy_node_raw_ids: Nodes we've already yielded (used to dedupe
          emissions from walks that did NOT reach a verified terminal).
        - fully_walked_hierarchy_node_raw_ids: Nodes where we've successfully walked
          to a terminal root. Only skip walking from a node if it's in this set.

        This separation ensures that if User A can access folder C but not its parent B,
        a later User B who has access to both can still complete the walk to the root.

        Cross-yield healing: when a walk *does* reach a verified terminal, every node
        encountered along that walk is re-emitted (regardless of `seen`). The downstream
        upsert is idempotent and keys on `raw_node_id`, so any node that was previously
        emitted with an unresolvable parent (and therefore parented to SOURCE) gets its
        `parent_id` corrected once the full chain becomes known. Walks that *don't*
        reach a terminal keep the seen-based dedup so we don't churn upserts for
        chains we still can't fully resolve.

        Args:
            files: List of retrieved drive files to get ancestors for
            seen_hierarchy_node_raw_ids: Set of already-yielded node IDs (modified in place)
            fully_walked_hierarchy_node_raw_ids: Set of node IDs where the walk to root
                succeeded (modified in place)
            failed_folder_ids_by_email: Map of email → folder IDs where that email
                previously confirmed no accessible parent. Skips the API call if the same
                (folder, email) is encountered again (modified in place).
            permission_sync_context: If provided, permissions will be fetched for hierarchy nodes.
                Contains google_domain and primary_admin_email needed for permission syncing.
            add_prefix: When True, prefix group IDs with source type (for indexing path).
                       When False (default), leave unprefixed (for permission sync path).

        Returns:
            List of HierarchyNode objects for new ancestors (ordered parent-first)
        """
        service = get_drive_service(self.creds, self.primary_admin_email)
        field_type = (
            DriveFileFieldType.WITH_PERMISSIONS
            if permission_sync_context
            else DriveFileFieldType.STANDARD
        )
        new_nodes: list[HierarchyNode] = []

        for file in files:
            parent_id = _get_parent_id_from_file(file.drive_file)
            if not parent_id:
                continue

            # Only skip if we've already successfully walked from this node to a root.
            # Don't skip just because it's "seen" - a previous user may have failed
            # to walk to the root, and this user might have better access.
            if parent_id in fully_walked_hierarchy_node_raw_ids:
                continue

            # Walk up the parent chain.
            # `walk_nodes` collects every node we build during this walk (no dedup).
            # `ancestors_to_add` collects only nodes that are new to the seen-set.
            # Which one we ultimately emit depends on whether we reach a terminal.
            ancestors_to_add: list[HierarchyNode] = []
            walk_nodes: list[HierarchyNode] = []
            node_ids_in_walk: list[str] = []
            current_id: str | None = parent_id
            reached_terminal = False

            while current_id:
                node_ids_in_walk.append(current_id)

                # If we hit a node that's already been fully walked, we know
                # the path from here to root is complete
                if current_id in fully_walked_hierarchy_node_raw_ids:
                    reached_terminal = True
                    break

                # Fetch folder metadata
                folder = self._get_folder_metadata(
                    current_id, file.user_email, field_type, failed_folder_ids_by_email
                )
                if not folder:
                    # Can't access this folder - stop climbing.
                    # If the terminal node is a confirmed orphan, backfill all
                    # intermediate folders into failed_folder_ids_by_email so
                    # future files short-circuit via _get_folder_metadata's
                    # cache check instead of re-climbing the whole chain.
                    if failed_folder_ids_by_email is not None:
                        for email in {file.user_email, self.primary_admin_email}:
                            email_failed_ids = failed_folder_ids_by_email.get(email)
                            if email_failed_ids and current_id in email_failed_ids:
                                failed_folder_ids_by_email.setdefault(
                                    email, ThreadSafeSet()
                                ).update(set(node_ids_in_walk))
                    break

                folder_parent_id = _get_parent_id_from_file(folder)

                # Create the node BEFORE marking as seen to avoid a race condition where:
                # 1. Thread A marks node as "seen"
                # 2. Thread A fails to create node (e.g., API error in get_external_access)
                # 3. Thread B sees node as "already seen" and skips it
                # 4. Result: node is never yielded
                #
                # By creating first and then atomically checking/marking, we ensure that
                # if creation fails, another thread can still try. If both succeed,
                # only one will add to ancestors_to_add (the one that wins check_and_add).
                if permission_sync_context:
                    external_access = get_external_access_for_folder(
                        folder,
                        permission_sync_context.google_domain,
                        service,
                        add_prefix,
                    )
                else:
                    external_access = _public_access()

                node = HierarchyNode(
                    raw_node_id=current_id,
                    raw_parent_id=folder_parent_id,
                    display_name=folder.get("name", "Unknown Folder"),
                    link=folder.get("webViewLink"),
                    node_type=HierarchyNodeType.FOLDER,
                    external_access=external_access,
                )

                # Always remember the node we built; if this walk reaches a verified
                # terminal we re-emit it below to heal any prior incomplete walk.
                walk_nodes.append(node)

                # Now atomically check and add - only append if we're the first thread
                # to successfully create this node
                already_seen = seen_hierarchy_node_raw_ids.check_and_add(current_id)
                if not already_seen:
                    ancestors_to_add.append(node)

                # Check if this is a verified terminal node (actual root, not just
                # empty parents due to permission limitations)
                # Check shared drive root first (simple ID comparison)
                if _is_shared_drive_root(folder):
                    # files().get() returns 'Drive' for shared drive roots;
                    # fetch the real name via drives().get().
                    # Try both the retriever and admin since the admin may
                    # not have access to private shared drives.
                    drive_name = self._get_shared_drive_name(
                        current_id, file.user_email
                    )
                    if drive_name:
                        node.display_name = drive_name
                    node.node_type = HierarchyNodeType.SHARED_DRIVE
                    reached_terminal = True
                    break

                # Check if this is a My Drive root (requires API call, but cached)
                if self._is_my_drive_root(folder, file.user_email):
                    reached_terminal = True
                    break

                # If parents is empty but we couldn't verify it's a true root,
                # stop walking but don't mark as fully walked (another user
                # with better access might be able to continue)
                if folder_parent_id is None:
                    break

                # Move to parent
                current_id = folder_parent_id

            # If we successfully reached a terminal node (or a fully-walked node),
            # mark all nodes in this walk as fully walked AND re-emit every node
            # we touched. The downstream upsert is idempotent, so any node
            # previously emitted with an unresolvable parent (parented to SOURCE)
            # gets corrected once the chain can be fully resolved.
            # Otherwise fall back to the seen-deduped subset to avoid churning
            # upserts for chains we still can't fully resolve.
            if reached_terminal:
                fully_walked_hierarchy_node_raw_ids.update(set(node_ids_in_walk))
                new_nodes += walk_nodes[::-1]  # locally parent-first
            else:
                new_nodes += ancestors_to_add[::-1]  # locally parent-first

        return new_nodes

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
                logger.debug(
                    "Skipping folder %s using %s (previously confirmed no parents)",
                    folder_id,
                    email,
                )
                continue

            service = get_drive_service(self.creds, email)
            folder = get_folder_metadata(service, folder_id, field_type)

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
            svc = get_drive_service(self.creds, email)
            name = get_shared_drive_name(svc, drive_id)
            if name:
                return name
        return None

    def get_all_drive_ids(self) -> set[str]:
        return self._get_all_drives_for_user(self.primary_admin_email)

    def _get_all_drives_for_user(self, user_email: str) -> set[str]:
        drive_service = get_drive_service(self.creds, user_email)
        is_service_account = isinstance(self.creds, ServiceAccountCredentials)
        logger.info(
            "Getting all drives for user %s with service account: %s",
            user_email,
            is_service_account,
        )
        all_drive_ids: set[str] = set()
        for drive in execute_paginated_retrieval(
            retrieval_function=drive_service.drives().list,  # ty: ignore[unresolved-attribute]
            list_key="drives",
            useDomainAdminAccess=is_service_account,
            fields="drives(id),nextPageToken",
        ):
            all_drive_ids.add(drive["id"])

        if not all_drive_ids:
            logger.warning(
                "No drives found even though indexing shared drives was requested."
            )

        return all_drive_ids

    def _phased_retrieval(
        self,
        field_type: DriveFileFieldType,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        """Service account retrieval: one pass per phase over exact partitions.

        Each item belongs to one partition with one principal guaranteed to see
        it (a drive's organizer, a file's owner), so the checkpoint is a cursor
        into the partition list plus a page token, never a per-document set.
        Returns whenever a page token is saved or the partition budget for this
        call is spent; the next call resumes from `checkpoint.phase_progress`.
        """
        if checkpoint.phase_progress is None:
            if checkpoint.completion_stage is not DriveRetrievalStage.START:
                logger.info(
                    "Checkpoint was written by the per-user stage loop; "
                    "restarting with phased retrieval."
                )
            checkpoint.phase_progress = PhaseProgress(
                phase=DriveRetrievalPhase.INVENTORY
            )

        budget: int = PARTITIONS_PER_CHECKPOINT
        while True:
            progress = checkpoint.phase_progress
            if progress is None:
                raise RuntimeError("phase_progress is unset during phased retrieval")
            if progress.phase is DriveRetrievalPhase.DONE:
                checkpoint.completion_stage = DriveRetrievalStage.DONE
                return

            if progress.phase is DriveRetrievalPhase.INVENTORY:
                self._run_inventory(checkpoint)
                self._enter_phase(checkpoint, next_phase(progress.phase))
                continue

            while not progress.is_complete:
                if budget <= 0:
                    return
                budget -= self._partition_cost(progress.phase)
                partition: str = progress.remaining_partitions[0]
                paused: bool = yield from self._list_partition(
                    progress, partition, field_type, checkpoint, start, end
                )
                if paused:
                    return
                progress.advance_partition()

            self._finish_phase(checkpoint)
            self._enter_phase(checkpoint, next_phase(progress.phase))

    @staticmethod
    def _partition_cost(phase: DriveRetrievalPhase) -> int:
        # A folder crawl has no page cursor, so it takes a whole call.
        if phase is DriveRetrievalPhase.REQUESTED_TARGETS:
            return PARTITIONS_PER_CHECKPOINT
        return 1

    def _run_inventory(self, checkpoint: GoogleDriveCheckpoint) -> None:
        checkpoint.user_emails = self._get_all_user_emails()
        drive_ids, folder_ids = self._compute_retrieval_ids()
        checkpoint.drive_ids_to_retrieve = drive_ids
        checkpoint.folder_ids_to_retrieve = folder_ids
        logger.info(
            "Phased retrieval inventory: %s users, %s drives, %s folders",
            len(checkpoint.user_emails),
            len(drive_ids),
            len(folder_ids),
        )

    def _enter_phase(
        self, checkpoint: GoogleDriveCheckpoint, phase: DriveRetrievalPhase
    ) -> None:
        partition_keys: list[str] = []
        if phase is DriveRetrievalPhase.SHARED_DRIVES:
            partition_keys = list(checkpoint.drive_ids_to_retrieve or [])
        elif phase is DriveRetrievalPhase.MY_DRIVES:
            partition_keys = self._my_drive_partition_emails(checkpoint)
        elif phase is DriveRetrievalPhase.REQUESTED_TARGETS:
            partition_keys = self._plan_requested_targets(checkpoint)
        elif (
            phase is DriveRetrievalPhase.EXTERNAL_SHARES
            and self.include_files_shared_with_me
        ):
            # Shared files were only ever listed for users whose My Drive is
            # in scope, so this phase walks the same users.
            partition_keys = [
                email
                for email in self._my_drive_partition_emails(checkpoint)
                if email not in checkpoint.failed_impersonation_emails
            ]
        logger.info("Entering phase %s with %s partitions", phase, len(partition_keys))
        checkpoint.phase_progress = PhaseProgress(
            phase=phase, partition_keys=partition_keys
        )

    def _finish_phase(self, checkpoint: GoogleDriveCheckpoint) -> None:
        progress = checkpoint.phase_progress
        if (
            progress is not None
            and progress.phase is DriveRetrievalPhase.REQUESTED_TARGETS
        ):
            # A target whose every planned principal failed was never listed,
            # so pruning must not read its absence as deletion.
            planned = {
                split_target_partition_key(key)[0] for key in progress.partition_keys
            }
            missed = planned - checkpoint.crawled_target_ids
            if missed:
                logger.warning(
                    "Requested targets %s were not crawled by any principal.",
                    sorted(missed),
                )
            checkpoint.unreachable_target_ids.update(missed)

        # The orphan-folder cache is per impersonated email; the next phase
        # impersonates a different set. Keep the admin's, which every phase uses.
        for email in list(checkpoint.failed_folder_ids_by_email.keys()):
            if email != self.primary_admin_email:
                checkpoint.failed_folder_ids_by_email.pop(email, None)

    def _list_partition(
        self,
        progress: PhaseProgress,
        partition: str,
        field_type: DriveFileFieldType,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
    ) -> Generator[RetrievedDriveFile, None, bool]:
        """Yield one partition's files. Returns True when it paused on a page
        token, so the same partition resumes on the next call."""
        if progress.phase is DriveRetrievalPhase.SHARED_DRIVES:
            return (
                yield from self._list_shared_drive(
                    progress, partition, field_type, checkpoint, start, end
                )
            )
        if progress.phase is DriveRetrievalPhase.MY_DRIVES:
            return (
                yield from self._list_my_drive(
                    progress, partition, field_type, checkpoint, start, end
                )
            )
        if progress.phase is DriveRetrievalPhase.REQUESTED_TARGETS:
            yield from self._crawl_requested_target(
                partition, field_type, checkpoint, start, end
            )
            return False
        if progress.phase is DriveRetrievalPhase.EXTERNAL_SHARES:
            return (
                yield from self._list_external_shares(
                    progress, partition, field_type, checkpoint, start, end
                )
            )
        raise ValueError(f"Phase {progress.phase} has no partitions to list")

    def _list_shared_drive(
        self,
        progress: PhaseProgress,
        drive_id: str,
        field_type: DriveFileFieldType,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
    ) -> Generator[RetrievedDriveFile, None, bool]:
        email = checkpoint.organizer_email_by_drive_id.get(drive_id)
        if progress.next_page_token is None or email is None:
            progress.next_page_token = None
            checkpoint.incomplete_drive_ids.discard(drive_id)
            email, complete = self._choose_drive_principal(drive_id, checkpoint)
            if email is None:
                checkpoint.incomplete_drive_ids.add(drive_id)
                if drive_id in self._requested_shared_drive_ids:
                    checkpoint.unreachable_target_ids.add(drive_id)
                return False
            checkpoint.organizer_email_by_drive_id[drive_id] = email
            if not complete:
                checkpoint.incomplete_drive_ids.add(drive_id)

        complete = drive_id not in checkpoint.incomplete_drive_ids
        # Drives an organizer already listed in full earlier in this phase.
        finished_drive_ids = self._covered_drive_ids(checkpoint) - {drive_id}
        logger.info("Listing shared drive %s as %s", drive_id, email)
        try:
            for item in get_files_in_shared_drive(
                service=get_drive_service(self.creds, email),
                drive_id=drive_id,
                field_type=field_type,
                max_num_pages=SHARED_DRIVE_PAGES_PER_CHECKPOINT,
                cache_folders=False,
                start=start,
                end=end,
                page_token=progress.next_page_token,
            ):
                if isinstance(item, str):
                    progress.next_page_token = item
                    return True
                in_this_drive = item.get("driveId") == drive_id
                via_shortcut = RESOLVED_FROM_SHORTCUT_KEY in item
                # A shortcut to a file in this drive: the listing reaches the
                # file itself.
                if via_shortcut and in_this_drive:
                    continue
                # Only an organizer listing is a complete record of the drive;
                # anything else may also arrive through another partition.
                exact = complete and in_this_drive and not via_shortcut
                if not exact and item.get("driveId") in finished_drive_ids:
                    continue
                if not self._admit_file(checkpoint, item, exact):
                    continue
                _note_modified_time(progress, item)
                yield RetrievedDriveFile(
                    completion_stage=DriveRetrievalStage.SHARED_DRIVE_FILES,
                    drive_file=item,
                    user_email=email,
                    parent_id=drive_id,
                )
        except RefreshError as error:
            # Relist the drive from the start with another principal; the
            # failed email is excluded from the next selection.
            yield from self._impersonation_failed(email, error, checkpoint)
            checkpoint.organizer_email_by_drive_id.pop(drive_id, None)
            progress.next_page_token = None
            return True
        return False

    def _choose_drive_principal(
        self, drive_id: str, checkpoint: GoogleDriveCheckpoint
    ) -> tuple[str | None, bool]:
        """The email to list a drive as, and whether its listing is complete."""
        admin_drive_service = get_drive_service(self.creds, self.primary_admin_email)
        try:
            members = list_drive_members(admin_drive_service, drive_id)
        except HttpError as error:
            # Only a denial means "fall back"; a server error must fail the
            # run, or a prune would delete the drive's documents.
            if not is_access_denied(error):
                raise
            logger.warning("Cannot read members of drive %s: %s", drive_id, error)
            members = []

        def _can_list(email: str) -> bool:
            if not self._may_impersonate(email, checkpoint):
                return False
            return can_list_drive(get_drive_service(self.creds, email), drive_id)

        choice = select_drive_organizer(
            drive_id=drive_id,
            members=members,
            google_domain=self.google_domain,
            expand_group=self._expand_group,
            can_list_drive=_can_list,
        )
        if choice.email is not None:
            return choice.email, choice.complete

        # Membership was unreadable or names nobody we can impersonate. The
        # admin may still be able to list it, as the old per-user loop did.
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
        admin_service = get_admin_service(
            creds=self.creds, user_email=self.primary_admin_email
        )
        return list_group_member_emails(admin_service, group_email)

    def _list_my_drive(
        self,
        progress: PhaseProgress,
        email: str,
        field_type: DriveFileFieldType,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
    ) -> Generator[RetrievedDriveFile, None, bool]:
        if progress.next_page_token is None:
            usable: bool = yield from self._impersonation_gate(email, checkpoint)
            if not usable:
                return False

        covered_drive_ids = self._covered_drive_ids(checkpoint)
        # Owners whose own partition already finished cleanly. A shortcut to
        # their file adds nothing; a later owner might still fail, so it does.
        finished_owners = {
            owner.lower()
            for owner in progress.partition_keys[: progress.partition_index]
            if owner not in checkpoint.failed_impersonation_emails
        }
        logger.info("Listing My Drive of %s", email)
        try:
            for item in get_all_files_in_my_drive_and_shared(
                service=get_drive_service(self.creds, email),
                update_traversed_ids_func=_ignore_traversed_id,
                field_type=field_type,
                include_shared_with_me=False,
                max_num_pages=MY_DRIVE_PAGES_PER_CHECKPOINT,
                start=start,
                end=end,
                cache_folders=False,
                page_token=progress.next_page_token,
            ):
                if isinstance(item, str):
                    progress.next_page_token = item
                    return True
                owner = _owner_email(item)
                owned_here = owner == email.lower() and not item.get("driveId")
                via_shortcut = RESOLVED_FROM_SHORTCUT_KEY in item
                # A shortcut to this user's own file: the listing reaches the
                # file itself.
                if via_shortcut and owned_here:
                    continue
                exact = owned_here and not via_shortcut
                if not exact and (
                    item.get("driveId") in covered_drive_ids or owner in finished_owners
                ):
                    continue
                if not self._admit_file(checkpoint, item, exact):
                    continue
                _note_modified_time(progress, item)
                yield RetrievedDriveFile(
                    completion_stage=DriveRetrievalStage.MY_DRIVE_FILES,
                    drive_file=item,
                    user_email=email,
                )
        except RefreshError as error:
            # The rest of this owner's files are no longer covered, so the
            # shared-file phase will keep them when other users see them.
            yield from self._impersonation_failed(email, error, checkpoint)
        return False

    def _list_external_shares(
        self,
        progress: PhaseProgress,
        email: str,
        field_type: DriveFileFieldType,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
    ) -> Generator[RetrievedDriveFile, None, bool]:
        """Everything this user can see that no exact partition covered: files
        owned outside the org, by users out of scope, or by users whose
        impersonation failed."""
        if progress.next_page_token is None:
            usable: bool = yield from self._impersonation_gate(email, checkpoint)
            if not usable:
                return False

        covered_drive_ids = self._covered_drive_ids(checkpoint)
        covered_owners = {
            owner.lower()
            for owner in self._my_drive_partition_emails(checkpoint)
            if owner not in checkpoint.failed_impersonation_emails
        }
        suppressed: int = 0
        try:
            for item in get_all_files_in_my_drive_and_shared(
                service=get_drive_service(self.creds, email),
                update_traversed_ids_func=_ignore_traversed_id,
                field_type=field_type,
                include_shared_with_me=True,
                max_num_pages=MY_DRIVE_PAGES_PER_CHECKPOINT,
                start=start,
                end=end,
                cache_folders=False,
                page_token=progress.next_page_token,
            ):
                if isinstance(item, str):
                    progress.next_page_token = item
                    return True
                if (
                    item.get("driveId") in covered_drive_ids
                    or _owner_email(item) in covered_owners
                ):
                    suppressed += 1
                    continue
                if not self._claim_file(checkpoint, item):
                    continue
                _note_modified_time(progress, item)
                yield RetrievedDriveFile(
                    completion_stage=DriveRetrievalStage.MY_DRIVE_FILES,
                    drive_file=item,
                    user_email=email,
                )
        except RefreshError as error:
            yield from self._impersonation_failed(email, error, checkpoint)
        finally:
            logger.info(
                "Shared-file listing for %s dropped %s files covered elsewhere",
                email,
                suppressed,
            )
        return False

    def _plan_requested_targets(self, checkpoint: GoogleDriveCheckpoint) -> list[str]:
        """Choose who crawls each requested folder (and each requested drive
        that drives.list did not return).

        In order: a target in a drive already listed in full is skipped; a
        target in an in-domain shared drive goes to that drive's organizer; a
        target in an in-domain user's My Drive goes to its owner. Anything else
        has no guaranteed principal, so it is crawled by every in-domain user
        on its permission list, which is best effort.
        """
        covered_drive_ids = self._covered_drive_ids(checkpoint)
        partition_keys: list[str] = []
        for target_id in checkpoint.folder_ids_to_retrieve or []:
            if target_id in covered_drive_ids:
                continue
            found = self._find_target_viewer(target_id, checkpoint)
            if found is None:
                logger.warning(
                    "Requested target %s is not visible to any user; it will "
                    "not be indexed and pruning is blocked until it is.",
                    target_id,
                )
                checkpoint.unreachable_target_ids.add(target_id)
                continue
            viewer, metadata = found
            if metadata.get("driveId") in covered_drive_ids:
                continue
            partition_keys.extend(
                target_partition_key(target_id, email)
                for email in self._target_principals(
                    target_id, viewer, metadata, checkpoint
                )
            )
        return partition_keys

    def _find_target_viewer(
        self, target_id: str, checkpoint: GoogleDriveCheckpoint
    ) -> tuple[str, GoogleDriveFileType] | None:
        candidates = [self.primary_admin_email, *(checkpoint.user_emails or [])]
        seen: set[str] = set()
        for email in candidates:
            if email in seen or not self._may_impersonate(email, checkpoint):
                continue
            seen.add(email)
            metadata = probe_target(get_drive_service(self.creds, email), target_id)
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
            owner = _owner_email(metadata)
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
            get_drive_service(self.creds, viewer),
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

    def _crawl_requested_target(
        self,
        partition: str,
        field_type: DriveFileFieldType,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
    ) -> Generator[RetrievedDriveFile, None, None]:
        target_id, email = split_target_partition_key(partition)
        usable: bool = yield from self._impersonation_gate(email, checkpoint)
        if not usable:
            return

        logger.info("Crawling requested target %s as %s", target_id, email)
        try:
            # A fresh traversed set per principal: a folder another principal
            # crawled may hold limited-access children only this one can see.
            for retrieved in crawl_folders_for_files(
                service=get_drive_service(self.creds, email),
                parent_id=target_id,
                field_type=field_type,
                user_email=email,
                traversed_parent_ids=set(),
                update_traversed_ids_func=_ignore_traversed_id,
                start=start,
                end=end,
            ):
                if (
                    retrieved.error is None
                    and retrieved.drive_file
                    and not self._claim_file(checkpoint, retrieved.drive_file)
                ):
                    continue
                yield retrieved
        except RefreshError as error:
            yield from self._impersonation_failed(email, error, checkpoint)
            return
        checkpoint.crawled_target_ids.add(target_id)

    def _impersonation_gate(
        self, email: str, checkpoint: GoogleDriveCheckpoint
    ) -> Generator[RetrievedDriveFile, None, bool]:
        """Check that `email` can call the Drive API before listing as them.

        A user without Drive access (401) or removed from the workspace is
        skipped quietly; any other impersonation failure is reported. Either
        way the user is recorded as failed so no phase relies on their pass.
        """
        try:
            # The default retry runs ~17 minutes; a user without Drive access
            # should not cost that on every run.
            retry_builder(tries=3, delay=1)(get_root_folder_id)(
                get_drive_service(self.creds, email)
            )
        except HttpError as error:
            if error.status_code != 401:
                raise
            logger.warning("User '%s' does not have access to the drive APIs.", email)
            checkpoint.failed_impersonation_emails.add(email)
            return False
        except RefreshError as error:
            yield from self._impersonation_failed(email, error, checkpoint)
            return False
        return True

    def _impersonation_failed(
        self, email: str, error: RefreshError, checkpoint: GoogleDriveCheckpoint
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
            completion_stage=DriveRetrievalStage.DONE,
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

    @staticmethod
    def _covered_drive_ids(checkpoint: GoogleDriveCheckpoint) -> set[str]:
        """Drives an organizer listed in full during the shared drive phase."""
        return {
            drive_id
            for drive_id in checkpoint.organizer_email_by_drive_id
            if drive_id not in checkpoint.incomplete_drive_ids
        }

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

    def _determine_retrieval_ids(
        self,
        checkpoint: GoogleDriveCheckpoint,
        next_stage: DriveRetrievalStage,
    ) -> tuple[list[str], list[str]]:
        if checkpoint.completion_stage == DriveRetrievalStage.DRIVE_IDS:
            sorted_drive_ids, sorted_folder_ids = self._compute_retrieval_ids()
            checkpoint.drive_ids_to_retrieve = sorted_drive_ids
            checkpoint.folder_ids_to_retrieve = sorted_folder_ids
            checkpoint.completion_stage = next_stage
            return sorted_drive_ids, sorted_folder_ids

        if checkpoint.drive_ids_to_retrieve is None:
            raise ValueError("drive ids to retrieve not set in checkpoint")
        if checkpoint.folder_ids_to_retrieve is None:
            raise ValueError("folder ids to retrieve not set in checkpoint")
        # When loading from a checkpoint, load the previously cached drive and folder ids
        return checkpoint.drive_ids_to_retrieve, checkpoint.folder_ids_to_retrieve

    def _oauth_retrieval_all_files(
        self,
        field_type: DriveFileFieldType,
        drive_service: GoogleDriveService,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        page_token: str | None = None,
    ) -> Iterator[RetrievedDriveFile | str]:
        if not self.include_files_shared_with_me and not self.include_my_drives:
            return

        logger.info(
            "Getting shared files/my drive files for OAuth with include_files_shared_with_me=%s, include_my_drives=%s, include_shared_drives=%s.Using '%s' as the account.",
            self.include_files_shared_with_me,
            self.include_my_drives,
            self.include_shared_drives,
            self.primary_admin_email,
        )
        yield from add_retrieval_info(
            get_all_files_for_oauth(
                service=drive_service,
                include_files_shared_with_me=self.include_files_shared_with_me,
                include_my_drives=self.include_my_drives,
                include_shared_drives=self.include_shared_drives,
                field_type=field_type,
                max_num_pages=OAUTH_PAGES_PER_CHECKPOINT,
                start=start,
                end=end,
                page_token=page_token,
            ),
            self.primary_admin_email,
            DriveRetrievalStage.OAUTH_FILES,
        )

    def _oauth_retrieval_drives(
        self,
        field_type: DriveFileFieldType,
        drive_service: GoogleDriveService,
        drive_ids_to_retrieve: list[str],
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile | str]:
        def _yield_from_drive(
            drive_id: str, drive_start: SecondsSinceUnixEpoch | None
        ) -> Iterator[RetrievedDriveFile | str]:
            yield from add_retrieval_info(
                get_files_in_shared_drive(
                    service=drive_service,
                    drive_id=drive_id,
                    field_type=field_type,
                    max_num_pages=SHARED_DRIVE_PAGES_PER_CHECKPOINT,
                    cache_folders=not bool(
                        drive_start
                    ),  # only cache folders for 0 or None
                    update_traversed_ids_func=self._update_traversed_parent_ids,
                    start=drive_start,
                    end=end,
                    page_token=checkpoint.completion_map[
                        self.primary_admin_email
                    ].next_page_token,
                ),
                self.primary_admin_email,
                DriveRetrievalStage.SHARED_DRIVE_FILES,
                parent_id=drive_id,
            )

        # If we are resuming from a checkpoint, we need to finish retrieving the files from the last drive we retrieved
        if (
            checkpoint.completion_map[self.primary_admin_email].stage
            == DriveRetrievalStage.SHARED_DRIVE_FILES
        ):
            drive_id = checkpoint.completion_map[
                self.primary_admin_email
            ].current_folder_or_drive_id
            if drive_id is None:
                raise ValueError("drive id not set in checkpoint")
            resume_start = _resume_start(
                checkpoint.completion_map[self.primary_admin_email].completed_until,
                start,
            )
            for file_or_token in _yield_from_drive(drive_id, resume_start):
                # Propagate page tokens so the caller records them and pauses at
                # this stage. Consuming a token here looks like normal completion
                # to the caller, which then advances the stage and drops the
                # remaining pages of the drive.
                yield file_or_token
                if isinstance(file_or_token, str):
                    return  # done with the max num pages, return checkpoint
            checkpoint.completion_map[self.primary_admin_email].next_page_token = None

        for drive_id in drive_ids_to_retrieve:
            if drive_id in self._retrieved_folder_and_drive_ids:
                logger.info(
                    "Skipping drive '%s' as it has already been retrieved", drive_id
                )
                continue
            logger.info(
                "Getting files in shared drive '%s' as '%s'",
                drive_id,
                self.primary_admin_email,
            )
            # Record the stage and drive being listed before any file is
            # yielded (as the service account path does), so a page token
            # emitted before the first yielded file resumes this drive, not the
            # previous one. Without the stage, the resume branch above is
            # skipped and the token leaks into the first unretrieved drive's
            # fresh listing.
            checkpoint.completion_map[self.primary_admin_email].update(
                stage=DriveRetrievalStage.SHARED_DRIVE_FILES,
                completed_until=0,
                current_folder_or_drive_id=drive_id,
            )
            for file_or_token in _yield_from_drive(drive_id, start):
                # See the resume loop above: the caller records page tokens.
                yield file_or_token
                if isinstance(file_or_token, str):
                    return  # done with the max num pages, return checkpoint
            checkpoint.completion_map[self.primary_admin_email].next_page_token = None

    def _oauth_retrieval_folders(
        self,
        field_type: DriveFileFieldType,
        drive_service: GoogleDriveService,
        drive_ids_to_retrieve: set[str],
        folder_ids_to_retrieve: set[str],
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        """
        If there are any remaining folder ids to retrieve found earlier in the
        retrieval process, we recursively descend the file tree and retrieve all
        files in the folder(s).
        """
        # Even if no folders were requested, we still check if any drives were requested
        # that could be folders.
        remaining_folders = (
            folder_ids_to_retrieve - self._retrieved_folder_and_drive_ids
        )

        def _yield_from_folder_crawl(
            folder_id: str, folder_start: SecondsSinceUnixEpoch | None
        ) -> Iterator[RetrievedDriveFile]:
            yield from crawl_folders_for_files(
                service=drive_service,
                parent_id=folder_id,
                field_type=field_type,
                user_email=self.primary_admin_email,
                traversed_parent_ids=self._retrieved_folder_and_drive_ids,
                update_traversed_ids_func=self._update_traversed_parent_ids,
                start=folder_start,
                end=end,
            )

        # resume from a checkpoint
        # TODO: actually checkpoint folder retrieval. Since we moved towards returning from
        # generator functions to indicate when a checkpoint should be returned, this code
        # shouldn't be used currently. Unfortunately folder crawling is quite difficult to checkpoint
        # effectively (likely need separate folder crawling and file retrieval stages),
        # so we'll revisit this later.
        if checkpoint.completion_map[
            self.primary_admin_email
        ].stage == DriveRetrievalStage.FOLDER_FILES and (
            folder_id := checkpoint.completion_map[
                self.primary_admin_email
            ].current_folder_or_drive_id
        ):
            resume_start = _resume_start(
                checkpoint.completion_map[self.primary_admin_email].completed_until,
                start,
            )
            yield from _yield_from_folder_crawl(
                folder_id,
                resume_start,
            )

        # the times stored in the completion_map aren't used due to the crawling behavior
        # instead, the traversed_parent_ids are used to determine what we have left to retrieve
        for folder_id in remaining_folders:
            logger.info(
                "Getting files in folder '%s' as '%s'",
                folder_id,
                self.primary_admin_email,
            )
            yield from _yield_from_folder_crawl(folder_id, start)

        remaining_folders = (
            drive_ids_to_retrieve | folder_ids_to_retrieve
        ) - self._retrieved_folder_and_drive_ids
        if remaining_folders:
            logger.warning(
                "Some folders/drives were not retrieved. IDs: %s", remaining_folders
            )

    def _checkpointed_retrieval(
        self,
        retrieval_method: CredentialedRetrievalMethod,
        field_type: DriveFileFieldType,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        drive_files = retrieval_method(
            field_type=field_type,
            checkpoint=checkpoint,
            start=start,
            end=end,
        )

        for file in drive_files:
            drive_file = file.drive_file or {}
            completion = checkpoint.completion_map[file.user_email]

            completed_until = completion.completed_until
            modified_time = drive_file.get(GoogleFields.MODIFIED_TIME.value)
            if isinstance(modified_time, str):
                try:
                    completed_until = datetime.fromisoformat(modified_time).timestamp()
                except ValueError:
                    logger.warning(
                        "Invalid modifiedTime for file '%s' (stage=%s, user=%s).",
                        drive_file.get("id"),
                        file.completion_stage,
                        file.user_email,
                    )

            # Never move the frontier backward within the same stage and
            # drive/folder: a regression changes the listing query, invalidates
            # the saved page token, and restarts retrieval from the regressed
            # timestamp — which can loop forever.
            if (
                file.completion_stage == completion.stage
                and file.parent_id == completion.current_folder_or_drive_id
            ):
                completed_until = max(completed_until, completion.completed_until)

            completion.update(
                stage=file.completion_stage,
                completed_until=completed_until,
                current_folder_or_drive_id=file.parent_id,
            )

            if file.error is not None or not drive_file:
                yield file
                continue

            try:
                onyx_document_id_from_drive_file(drive_file)
            except KeyError as exc:
                logger.warning(
                    "Drive file missing id/webViewLink (stage=%s user=%s). Skipping.",
                    file.completion_stage,
                    file.user_email,
                )
                if file.error is None:
                    file.error = exc
                yield file
                continue

            if not self._claim_file(checkpoint, drive_file):
                continue
            yield file

    def _manage_oauth_retrieval(
        self,
        field_type: DriveFileFieldType,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        if checkpoint.completion_stage == DriveRetrievalStage.START:
            checkpoint.completion_stage = DriveRetrievalStage.OAUTH_FILES
            checkpoint.completion_map[self.primary_admin_email] = StageCompletion(
                stage=DriveRetrievalStage.START,
                completed_until=0,
                current_folder_or_drive_id=None,
            )

        drive_service = get_drive_service(self.creds, self.primary_admin_email)

        if checkpoint.completion_stage == DriveRetrievalStage.OAUTH_FILES:
            completion = checkpoint.completion_map[self.primary_admin_email]
            all_files_start = start
            # if resuming from a checkpoint
            if completion.stage == DriveRetrievalStage.OAUTH_FILES:
                all_files_start = _resume_start(completion.completed_until, start)

            for file_or_token in self._oauth_retrieval_all_files(
                field_type=field_type,
                drive_service=drive_service,
                start=all_files_start,
                end=end,
                page_token=checkpoint.completion_map[
                    self.primary_admin_email
                ].next_page_token,
            ):
                if isinstance(file_or_token, str):
                    checkpoint.completion_map[
                        self.primary_admin_email
                    ].next_page_token = file_or_token
                    return  # done with the max num pages, return checkpoint
                yield file_or_token
            checkpoint.completion_stage = DriveRetrievalStage.DRIVE_IDS
            checkpoint.completion_map[self.primary_admin_email].next_page_token = None
            return  # create a new checkpoint

        all_requested = (
            self.include_files_shared_with_me
            and self.include_my_drives
            and self.include_shared_drives
        )
        if all_requested:
            # If all 3 are true, we already yielded from get_all_files_for_oauth
            checkpoint.completion_stage = DriveRetrievalStage.DONE
            return

        sorted_drive_ids, sorted_folder_ids = self._determine_retrieval_ids(
            checkpoint, DriveRetrievalStage.SHARED_DRIVE_FILES
        )

        if checkpoint.completion_stage == DriveRetrievalStage.SHARED_DRIVE_FILES:
            for file_or_token in self._oauth_retrieval_drives(
                field_type=field_type,
                drive_service=drive_service,
                drive_ids_to_retrieve=sorted_drive_ids,
                checkpoint=checkpoint,
                start=start,
                end=end,
            ):
                if isinstance(file_or_token, str):
                    checkpoint.completion_map[
                        self.primary_admin_email
                    ].next_page_token = file_or_token
                    return  # done with the max num pages, return checkpoint
                yield file_or_token
            checkpoint.completion_stage = DriveRetrievalStage.FOLDER_FILES
            checkpoint.completion_map[self.primary_admin_email].next_page_token = None
            return  # create a new checkpoint

        if checkpoint.completion_stage == DriveRetrievalStage.FOLDER_FILES:
            yield from self._oauth_retrieval_folders(
                field_type=field_type,
                drive_service=drive_service,
                drive_ids_to_retrieve=set(sorted_drive_ids),
                folder_ids_to_retrieve=set(sorted_folder_ids),
                checkpoint=checkpoint,
                start=start,
                end=end,
            )

        checkpoint.completion_stage = DriveRetrievalStage.DONE

    def _fetch_drive_items(
        self,
        field_type: DriveFileFieldType,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        if isinstance(self.creds, ServiceAccountCredentials):
            return self._phased_retrieval(
                field_type=field_type,
                checkpoint=checkpoint,
                start=start,
                end=end,
            )

        return self._checkpointed_retrieval(
            retrieval_method=self._manage_oauth_retrieval,
            field_type=field_type,
            checkpoint=checkpoint,
            start=start,
            end=end,
        )

    def _convert_retrieved_files_to_documents(
        self,
        drive_files_iter: Iterator[RetrievedDriveFile],
        checkpoint: GoogleDriveCheckpoint,
        include_permissions: bool,
    ) -> Iterator[Document | ConnectorFailure | HierarchyNode]:
        """
        Converts retrieved files to documents, yielding HierarchyNode
        objects for ancestor folders before the converted documents.
        """
        permission_sync_context = (
            PermissionSyncContext(
                primary_admin_email=self.primary_admin_email,
                google_domain=self.google_domain,
            )
            if include_permissions
            else None
        )

        files_batch: list[RetrievedDriveFile] = []
        # Files awaiting their parent folder's node, keyed by folder raw id
        # (lightweight metadata, never documents). Released when the node is
        # emitted; whatever never resolves falls back to the source root.
        pending_by_folder: dict[str, list[RetrievedDriveFile]] = {}
        for retrieved_file in drive_files_iter:
            if self.exclude_domain_link_only and has_link_only_permission(
                retrieved_file.drive_file
            ):
                continue
            if retrieved_file.error is not None:
                failure_stage = retrieved_file.completion_stage.value
                logger.error(
                    "retrieval failure during stage: %s, user: %s, "
                    "parent drive/folder: %s, error: %s",
                    failure_stage,
                    retrieved_file.user_email,
                    retrieved_file.parent_id,
                    retrieved_file.error,
                )
                yield ConnectorFailure(
                    failed_entity=EntityFailure(
                        entity_id=retrieved_file.drive_file.get("id", failure_stage),
                    ),
                    failure_message=(
                        f"retrieval failure during stage: {failure_stage}, "
                        f"user: {retrieved_file.user_email}, "
                        f"parent drive/folder: {retrieved_file.parent_id}, "
                        f"error: {retrieved_file.error}"
                    ),
                    exception=retrieved_file.error,
                )
                continue

            files_batch.append(retrieved_file)
            # Flush in bounded sub-batches so resident converted documents stay
            # capped (pending metadata is bounded by one checkpoint's fetch).
            if len(files_batch) >= DRIVE_CONVERSION_BATCH_SIZE:
                yield from self._convert_files_sub_batch(
                    files_batch,
                    checkpoint,
                    permission_sync_context,
                    pending_by_folder,
                )
                files_batch = []

        if files_batch or pending_by_folder:
            yield from self._convert_files_sub_batch(
                files_batch,
                checkpoint,
                permission_sync_context,
                pending_by_folder,
                force_flush=True,
            )

    def _convert_files_sub_batch(
        self,
        files_batch: list[RetrievedDriveFile],
        checkpoint: GoogleDriveCheckpoint,
        permission_sync_context: PermissionSyncContext | None,
        pending_by_folder: dict[str, list[RetrievedDriveFile]],
        force_flush: bool = False,
    ) -> Iterator[Document | ConnectorFailure | HierarchyNode]:
        """Emit this sub-batch's new ancestor nodes, then convert the files whose
        parent node is now in `seen`. Resolution fetches each parent folder by id
        (file's user + admin), so a parent normally resolves in the file's own
        sub-batch; parking is only the cross-user case — a folder reachable solely
        by a later sub-batch's user — held in `pending_by_folder` until its node is
        emitted. `force_flush` roots whatever never resolves."""
        new_ancestors = (
            self._get_new_ancestors_for_files(
                files=files_batch,
                seen_hierarchy_node_raw_ids=checkpoint.seen_hierarchy_node_raw_ids,
                fully_walked_hierarchy_node_raw_ids=checkpoint.fully_walked_hierarchy_node_raw_ids,
                failed_folder_ids_by_email=checkpoint.failed_folder_ids_by_email,
                permission_sync_context=permission_sync_context,
                add_prefix=True,
            )
            if files_batch
            else []
        )
        if new_ancestors:
            logger.debug("Yielding %s new hierarchy nodes", len(new_ancestors))
            yield from new_ancestors

        # A folder enters `seen` only when its node is emitted (atomically, in
        # _get_new_ancestors_for_files), so a parked file is always released the
        # first time its folder appears below — no "seen but unemitted" stranding.
        newly_ready: list[RetrievedDriveFile] = []
        for retrieved_file in files_batch:
            parent_id = _get_parent_id_from_file(retrieved_file.drive_file)
            if not parent_id or parent_id in checkpoint.seen_hierarchy_node_raw_ids:
                newly_ready.append(retrieved_file)
            else:
                pending_by_folder.setdefault(parent_id, []).append(retrieved_file)

        # Release parked files whose folder node was just emitted (they came
        # earlier in the stream), then this sub-batch's own ready files.
        ready_files: list[RetrievedDriveFile] = []
        for node in new_ancestors:
            ready_files.extend(pending_by_folder.pop(node.raw_node_id, []))
        if force_flush and pending_by_folder:
            rooted = sum(len(waiters) for waiters in pending_by_folder.values())
            # Surfaces hierarchy degradation: these files' folders never resolved,
            # so they index under the source root instead of their real parent.
            logger.warning(
                "Rooting %s files under %s folders whose ancestor never resolved",
                rooted,
                len(pending_by_folder),
            )
            for waiters in pending_by_folder.values():
                ready_files.extend(waiters)
            pending_by_folder.clear()
        ready_files.extend(newly_ready)

        # Chunk so resident documents never exceed one chunk, however many resolved.
        for chunk in batch_generator(ready_files, DRIVE_CONVERSION_BATCH_SIZE):
            func_with_args = [
                (
                    self._convert_retrieved_file_to_document,
                    (retrieved_file, permission_sync_context),
                )
                for retrieved_file in chunk
            ]
            raw_results = cast(
                list[Document | ConnectorFailure | None],
                run_functions_tuples_in_parallel(func_with_args, max_workers=8),
            )
            results: list[Document | ConnectorFailure] = [
                r for r in raw_results if r is not None
            ]
            logger.debug("sub-batch has %s docs or failures", len(results))
            yield from results

    def _convert_retrieved_file_to_document(
        self,
        retrieved_file: RetrievedDriveFile,
        permission_sync_context: PermissionSyncContext | None,
    ) -> Document | ConnectorFailure | None:
        """
        Converts a single retrieved file to a document.
        """
        try:
            return convert_drive_item_to_document(
                self.creds,
                self.allow_images,
                self.size_threshold,
                permission_sync_context,
                [retrieved_file.user_email, self.primary_admin_email]
                + get_file_owners(retrieved_file.drive_file, self.primary_admin_email),
                retrieved_file.drive_file,
                self.raw_file_callback,
            )
        except Exception as e:
            logger.exception(
                "Error extracting document: %s from Google Drive",
                retrieved_file.drive_file.get("name"),
            )
            return ConnectorFailure(
                failed_entity=EntityFailure(
                    entity_id=retrieved_file.drive_file.get("id", "unknown"),
                ),
                failure_message=(
                    f"Error extracting document: "
                    f"{retrieved_file.drive_file.get('name')}"
                ),
                exception=e,
            )

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
        if self._creds is None or self._primary_admin_email is None:
            raise RuntimeError(
                "Credentials missing, should not call this method before calling load_credentials"
            )

        logger.info(
            "Loading from checkpoint with completion stage: %s,num retrieved ids: %s",
            checkpoint.completion_stage,
            len(checkpoint.retrieved_drive_file_ids),
        )
        checkpoint = copy.deepcopy(checkpoint)
        self._retrieved_folder_and_drive_ids = checkpoint.retrieved_folder_and_drive_ids
        try:
            field_type = (
                DriveFileFieldType.WITH_PERMISSIONS
                if include_permissions or self.exclude_domain_link_only
                else DriveFileFieldType.STANDARD
            )
            drive_files_iter = self._fetch_drive_items(
                field_type=field_type,
                checkpoint=checkpoint,
                start=start,
                end=end,
            )
            yield from self._convert_retrieved_files_to_documents(
                drive_files_iter, checkpoint, include_permissions
            )
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e
        checkpoint.retrieved_folder_and_drive_ids = self._retrieved_folder_and_drive_ids

        logger.info(
            "num drive files retrieved: %s", len(checkpoint.retrieved_drive_file_ids)
        )
        if checkpoint.completion_stage == DriveRetrievalStage.DONE:
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
        if self._creds is None or self._primary_admin_email is None:
            raise RuntimeError(
                "Credentials missing, should not call this method before calling load_credentials"
            )

        logger.info("Reindexing %s docs from errors", len(errors))
        doc_ids = [
            failure.failed_document.document_id
            for failure in errors
            if failure.failed_document
        ]
        service = get_drive_service(self.creds, self.primary_admin_email)
        field_type = (
            DriveFileFieldType.WITH_PERMISSIONS
            if include_permissions or self.exclude_domain_link_only
            else DriveFileFieldType.STANDARD
        )
        batch_result = get_files_by_web_view_links_batch(service, doc_ids, field_type)

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
                completion_stage=DriveRetrievalStage.DONE,
            )
            for file in batch_result.files.values()
        ]

        yield from self._get_new_ancestors_for_files(
            files=retrieved_files,
            seen_hierarchy_node_raw_ids=ThreadSafeSet(),
            fully_walked_hierarchy_node_raw_ids=ThreadSafeSet(),
            permission_sync_context=permission_sync_context,
            add_prefix=True,
        )

        func_with_args = [
            (
                self._convert_retrieved_file_to_document,
                (rf, permission_sync_context),
            )
            for rf in retrieved_files
        ]
        results = cast(
            list[Document | ConnectorFailure | None],
            run_functions_tuples_in_parallel(func_with_args, max_workers=8),
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
    ) -> GenerateSlimDocumentOutput:
        files_batch: list[RetrievedDriveFile] = []
        slim_batch: list[SlimDocument | HierarchyNode] = []

        def _yield_slim_batch() -> list[SlimDocument | HierarchyNode]:
            """Process files batch and return items to yield (hierarchy nodes + slim docs)."""
            nonlocal files_batch, slim_batch

            # Get new ancestor hierarchy nodes first
            permission_sync_context = (
                PermissionSyncContext(
                    primary_admin_email=self.primary_admin_email,
                    google_domain=self.google_domain,
                )
                if include_permissions
                else None
            )
            new_ancestors = self._get_new_ancestors_for_files(
                files=files_batch,
                seen_hierarchy_node_raw_ids=checkpoint.seen_hierarchy_node_raw_ids,
                fully_walked_hierarchy_node_raw_ids=checkpoint.fully_walked_hierarchy_node_raw_ids,
                failed_folder_ids_by_email=checkpoint.failed_folder_ids_by_email,
                permission_sync_context=permission_sync_context,
            )

            # Build slim documents
            slim_batch.extend(
                doc
                for file in files_batch
                if (
                    doc := build_slim_document(
                        self.creds,
                        file.drive_file,
                        permission_sync_context,
                        retriever_email=file.user_email,
                    )
                )
            )

            # Combine: hierarchy nodes first, then slim docs
            result: list[SlimDocument | HierarchyNode] = []
            result.extend(new_ancestors)
            result.extend(slim_batch)
            files_batch = []
            slim_batch = []
            return result

        for file in self._fetch_drive_items(
            field_type=DriveFileFieldType.SLIM,
            checkpoint=checkpoint,
            start=start,
            end=end,
        ):
            if file.error is not None:
                raise file.error
            if self.exclude_domain_link_only and has_link_only_permission(
                file.drive_file
            ):
                continue
            files_batch.append(file)

            if len(files_batch) >= SLIM_BATCH_SIZE:
                yield _yield_slim_batch()
                if callback:
                    if callback.should_stop():
                        raise RuntimeError(
                            "_extract_slim_docs_from_google_drive: Stop signal detected"
                        )
                    callback.progress("_extract_slim_docs_from_google_drive", 1)

        # Yield remaining files
        if files_batch:
            yield _yield_slim_batch()

    def _retrieve_all_slim_docs_impl(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
        include_permissions: bool = True,
        fail_on_unreachable_targets: bool = False,
    ) -> GenerateSlimDocumentOutput:
        try:
            checkpoint = self.build_dummy_checkpoint()
            while checkpoint.completion_stage != DriveRetrievalStage.DONE:
                yield from self._extract_slim_docs_from_google_drive(
                    checkpoint=checkpoint,
                    start=start,
                    end=end,
                    callback=callback,
                    include_permissions=include_permissions,
                )
            if fail_on_unreachable_targets and checkpoint.unreachable_target_ids:
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
            fail_on_unreachable_targets=True,
        )

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        return self._retrieve_all_slim_docs_impl(
            start=start, end=end, callback=callback, include_permissions=True
        )

    def validate_connector_settings(self) -> None:
        if self._creds is None:
            raise ConnectorMissingCredentialError(
                "Google Drive credentials not loaded."
            )

        if self._primary_admin_email is None:
            raise ConnectorValidationError(
                "Primary admin email not found in credentials. Ensure DB_CREDENTIALS_PRIMARY_ADMIN_KEY is set."
            )

        try:
            drive_service = get_drive_service(self._creds, self._primary_admin_email)
            drive_service.files().list(  # ty: ignore[unresolved-attribute]
                pageSize=1, fields="files(id)"
            ).execute()

            if isinstance(self._creds, ServiceAccountCredentials):
                # default is ~17mins of retries, don't do that here since this is called from
                # the UI
                retry_builder(tries=3, delay=0.1)(get_root_folder_id)(drive_service)

        except HttpError as e:
            status_code = e.resp.status if e.resp else None
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
        admin_service = get_admin_service(
            creds=self.creds,
            user_email=self.primary_admin_email,
        )
        try:
            admin_service.users().get(  # ty: ignore[unresolved-attribute]
                userKey=self.primary_admin_email
            ).execute()
        except HttpError as e:
            status_code = e.resp.status if e.resp else None
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
        return GoogleDriveCheckpoint(
            retrieved_folder_and_drive_ids=set(),
            completion_stage=DriveRetrievalStage.START,
            completion_map=ThreadSafeDict(),
            retrieved_drive_file_ids=set(),
            has_more=True,
        )

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
