import copy
import threading
from collections.abc import Callable
from collections.abc import Iterator
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from functools import partial
from typing import Any
from typing import Protocol
from urllib.parse import urlparse

from google.oauth2.credentials import Credentials as OAuthCredentials  # type: ignore
from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import MAX_DRIVE_WORKERS
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.google_drive.doc_conversion import build_slim_document
from onyx.connectors.google_drive.doc_conversion import (
    convert_drive_item_to_document,
)
from onyx.connectors.google_drive.file_retrieval import crawl_folders_for_files
from onyx.connectors.google_drive.file_retrieval import get_all_files_for_oauth
from onyx.connectors.google_drive.file_retrieval import get_all_files_in_my_drive
from onyx.connectors.google_drive.file_retrieval import get_files_in_shared_drive
from onyx.connectors.google_drive.file_retrieval import get_root_folder_id
from onyx.connectors.google_drive.models import DriveRetrievalStage
from onyx.connectors.google_drive.models import GoogleDriveCheckpoint
from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_drive.models import RetrievedDriveFile
from onyx.connectors.google_drive.models import StageCompletion
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.connectors.google_utils.google_utils import GoogleFields
from onyx.connectors.google_utils.resources import get_admin_service
from onyx.connectors.google_utils.resources import get_drive_service
from onyx.connectors.google_utils.resources import get_google_docs_service
from onyx.connectors.google_utils.resources import GoogleDriveService
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.google_utils.shared_constants import MISSING_SCOPES_ERROR_STR
from onyx.connectors.google_utils.shared_constants import ONYX_SCOPE_INSTRUCTIONS
from onyx.connectors.google_utils.shared_constants import SLIM_BATCH_SIZE
from onyx.connectors.google_utils.shared_constants import USER_FIELDS
from onyx.connectors.interfaces import CheckpointConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.lazy import lazy_eval
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder
from onyx.utils.threadpool_concurrency import parallel_yield
from onyx.utils.threadpool_concurrency import ThreadSafeDict

logger = setup_logger()
# TODO: Improve this by using the batch utility: https://googleapis.github.io/google-api-python-client/docs/batch.html
# All file retrievals could be batched and made at once

BATCHES_PER_CHECKPOINT = 10


def _extract_str_list_from_comma_str(string: str | None) -> list[str]:
    if not string:
        return []
    return [s.strip() for s in string.split(",") if s.strip()]


def _extract_ids_from_urls(urls: list[str]) -> list[str]:
    return [urlparse(url).path.strip("/").split("/")[-1] for url in urls]


def _convert_single_file(
    creds: Any,
    primary_admin_email: str,
    file: dict[str, Any],
) -> Document | ConnectorFailure | None:
    user_email = file.get("owners", [{}])[0].get("emailAddress") or primary_admin_email

    # Only construct these services when needed
    user_drive_service = lazy_eval(
        lambda: get_drive_service(creds, user_email=user_email)
    )
    docs_service = lazy_eval(
        lambda: get_google_docs_service(creds, user_email=user_email)
    )
    return convert_drive_item_to_document(
        file=file,
        drive_service=user_drive_service,
        docs_service=docs_service,
    )


def _clean_requested_drive_ids(
    requested_drive_ids: set[str],
    requested_folder_ids: set[str],
    all_drive_ids_available: set[str],
) -> tuple[set[str], set[str]]:
    invalid_requested_drive_ids = requested_drive_ids - all_drive_ids_available
    filtered_folder_ids = requested_folder_ids - all_drive_ids_available
    if invalid_requested_drive_ids:
        logger.warning(
            f"Some shared drive IDs were not found. IDs: {invalid_requested_drive_ids}"
        )
        logger.warning("Checking for folder access instead...")
        filtered_folder_ids.update(invalid_requested_drive_ids)

    valid_requested_drive_ids = requested_drive_ids - invalid_requested_drive_ids
    return valid_requested_drive_ids, filtered_folder_ids


class CredentialedRetrievalMethod(Protocol):
    def __call__(
        self,
        is_slim: bool,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        ...


def add_retrieval_info(
    drive_files: Iterator[GoogleDriveFileType],
    user_email: str,
    completion_stage: DriveRetrievalStage,
    parent_id: str | None = None,
) -> Iterator[RetrievedDriveFile]:
    for file in drive_files:
        yield RetrievedDriveFile(
            drive_file=file,
            user_email=user_email,
            parent_id=parent_id,
            completion_stage=completion_stage,
        )


class DriveIdStatus(Enum):
    AVAILABLE = "available"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class GoogleDriveConnector(SlimConnector, CheckpointConnector[GoogleDriveCheckpoint]):
    def __init__(
        self,
        include_shared_drives: bool = False,
        include_my_drives: bool = False,
        include_files_shared_with_me: bool = False,
        shared_drive_urls: str | None = None,
        my_drive_emails: str | None = None,
        shared_folder_urls: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
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

        self.batch_size = batch_size

        specific_requests_made = False
        if bool(shared_drive_urls) or bool(my_drive_emails) or bool(shared_folder_urls):
            specific_requests_made = True

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

        self._primary_admin_email: str | None = None

        self._creds: OAuthCredentials | ServiceAccountCredentials | None = None

        self._retrieved_ids: set[str] = set()

    @property
    def primary_admin_email(self) -> str:
        if self._primary_admin_email is None:
            raise RuntimeError(
                "Primary admin email missing, "
                "should not call this property "
                "before calling load_credentials"
            )
        return self._primary_admin_email

    @property
    def google_domain(self) -> str:
        if self._primary_admin_email is None:
            raise RuntimeError(
                "Primary admin email missing, "
                "should not call this property "
                "before calling load_credentials"
            )
        return self._primary_admin_email.split("@")[-1]

    @property
    def creds(self) -> OAuthCredentials | ServiceAccountCredentials:
        if self._creds is None:
            raise RuntimeError(
                "Creds missing, "
                "should not call this property "
                "before calling load_credentials"
            )
        return self._creds

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

        return new_creds_dict

    def _update_traversed_parent_ids(self, folder_id: str) -> None:
        self._retrieved_ids.add(folder_id)

    def _get_all_user_emails(self) -> list[str]:
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
                retrieval_function=admin_service.users().list,
                list_key="users",
                fields=USER_FIELDS,
                domain=self.google_domain,
                query=query,
            ):
                if email := user.get("primaryEmail"):
                    if email not in user_emails:
                        user_emails.append(email)
        return user_emails

    def get_all_drive_ids(self) -> set[str]:
        primary_drive_service = get_drive_service(
            creds=self.creds,
            user_email=self.primary_admin_email,
        )
        is_service_account = isinstance(self.creds, ServiceAccountCredentials)
        all_drive_ids = set()
        for drive in execute_paginated_retrieval(
            retrieval_function=primary_drive_service.drives().list,
            list_key="drives",
            useDomainAdminAccess=is_service_account,
            fields="drives(id)",
        ):
            all_drive_ids.add(drive["id"])

        if not all_drive_ids:
            logger.warning(
                "No drives found even though indexing shared drives was requested."
            )

        return all_drive_ids

    def make_drive_id_iterator(
        self, drive_ids: set[str], checkpoint: GoogleDriveCheckpoint
    ) -> Callable[[str], Iterator[str]]:
        cv = threading.Condition()
        drive_id_status = {
            drive_id: DriveIdStatus.FINISHED
            if drive_id in self._retrieved_ids
            else DriveIdStatus.AVAILABLE
            for drive_id in drive_ids
        }

        def _get_available_drive_id(
            processed_ids: set[str], thread_id: str
        ) -> tuple[str | None, bool]:
            found_future_work = False
            for drive_id, status in drive_id_status.items():
                if drive_id in self._retrieved_ids:
                    drive_id_status[drive_id] = DriveIdStatus.FINISHED
                    continue
                if drive_id in processed_ids:
                    continue

                if status == DriveIdStatus.AVAILABLE:
                    return drive_id, True
                elif status == DriveIdStatus.IN_PROGRESS:
                    found_future_work = True
            return None, found_future_work

        def drive_id_iterator(thread_id: str) -> Iterator[str]:
            completion = checkpoint.completion_map[thread_id]
            # continue iterating until this thread has no more work to do
            while True:
                # this locks operations on _retrieved_ids and drive_id_status
                with cv:
                    available_drive_id, found_future_work = _get_available_drive_id(
                        completion.processed_drive_ids, thread_id
                    )

                    # wait while there is no work currently available but still drives that may need processing
                    while available_drive_id is None and found_future_work:
                        cv.wait()
                        available_drive_id, found_future_work = _get_available_drive_id(
                            completion.processed_drive_ids, thread_id
                        )

                    # if there is no work available and no future work, we are done
                    if available_drive_id is None:
                        return

                    drive_id_status[available_drive_id] = DriveIdStatus.IN_PROGRESS

                yield available_drive_id
                with cv:
                    completion.processed_drive_ids.add(available_drive_id)
                    drive_id_status[available_drive_id] = (
                        DriveIdStatus.FINISHED
                        if available_drive_id in self._retrieved_ids
                        else DriveIdStatus.AVAILABLE
                    )
                    # wake up other threads waiting for work
                    cv.notify_all()

        return drive_id_iterator

    def _impersonate_user_for_retrieval(
        self,
        user_email: str,
        is_slim: bool,
        checkpoint: GoogleDriveCheckpoint,
        concurrent_drive_itr: Callable[[str], Iterator[str]],
        filtered_folder_ids: set[str],
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        logger.info(f"Impersonating user {user_email}")
        curr_stage = checkpoint.completion_map[user_email]
        resuming = True
        if curr_stage.stage == DriveRetrievalStage.START:
            curr_stage.stage = DriveRetrievalStage.MY_DRIVE_FILES
            resuming = False
        drive_service = get_drive_service(self.creds, user_email)

        # validate that the user has access to the drive APIs by performing a simple
        # request and checking for a 401
        try:
            # default is ~17mins of retries, don't do that here for cases so we don't
            # waste 17mins everytime we run into a user without access to drive APIs
            retry_builder(tries=3, delay=1)(get_root_folder_id)(drive_service)
        except HttpError as e:
            if e.status_code == 401:
                # fail gracefully, let the other impersonations continue
                # one user without access shouldn't block the entire connector
                logger.warning(
                    f"User '{user_email}' does not have access to the drive APIs."
                )
                return
            raise

        # if we are including my drives, try to get the current user's my
        # drive if any of the following are true:
        # - include_my_drives is true
        # - the current user's email is in the requested emails
        if curr_stage.stage == DriveRetrievalStage.MY_DRIVE_FILES:
            if self.include_my_drives or user_email in self._requested_my_drive_emails:
                logger.info(f"Getting all files in my drive as '{user_email}'")

                yield from add_retrieval_info(
                    get_all_files_in_my_drive(
                        service=drive_service,
                        update_traversed_ids_func=self._update_traversed_parent_ids,
                        is_slim=is_slim,
                        start=curr_stage.completed_until if resuming else start,
                        end=end,
                    ),
                    user_email,
                    DriveRetrievalStage.MY_DRIVE_FILES,
                )
            curr_stage.stage = DriveRetrievalStage.SHARED_DRIVE_FILES

        if curr_stage.stage == DriveRetrievalStage.SHARED_DRIVE_FILES:

            def _yield_from_drive(
                drive_id: str, drive_start: SecondsSinceUnixEpoch | None
            ) -> Iterator[RetrievedDriveFile]:
                yield from add_retrieval_info(
                    get_files_in_shared_drive(
                        service=drive_service,
                        drive_id=drive_id,
                        is_slim=is_slim,
                        update_traversed_ids_func=self._update_traversed_parent_ids,
                        start=drive_start,
                        end=end,
                    ),
                    user_email,
                    DriveRetrievalStage.SHARED_DRIVE_FILES,
                    parent_id=drive_id,
                )

            # resume from a checkpoint
            if resuming:
                drive_id = curr_stage.completed_until_parent_id
                assert drive_id is not None, "drive id not set in checkpoint"
                resume_start = curr_stage.completed_until
                yield from _yield_from_drive(drive_id, resume_start)
                # Don't enter resuming case for folder retrieval
                resuming = False

            for drive_id in concurrent_drive_itr(user_email):
                logger.info(
                    f"Getting files in shared drive '{drive_id}' as '{user_email}'"
                )
                yield from _yield_from_drive(drive_id, start)
            curr_stage.stage = DriveRetrievalStage.FOLDER_FILES

        if curr_stage.stage == DriveRetrievalStage.FOLDER_FILES:

            def _yield_from_folder_crawl(
                folder_id: str, folder_start: SecondsSinceUnixEpoch | None
            ) -> Iterator[RetrievedDriveFile]:
                yield from crawl_folders_for_files(
                    service=drive_service,
                    parent_id=folder_id,
                    is_slim=is_slim,
                    user_email=user_email,
                    traversed_parent_ids=self._retrieved_ids,
                    update_traversed_ids_func=self._update_traversed_parent_ids,
                    start=folder_start,
                    end=end,
                )

            # resume from a checkpoint
            if resuming:
                folder_id = curr_stage.completed_until_parent_id
                assert folder_id is not None, "folder id not set in checkpoint"
                resume_start = curr_stage.completed_until
                yield from _yield_from_folder_crawl(folder_id, resume_start)

            remaining_folders = filtered_folder_ids - self._retrieved_ids
            for folder_id in remaining_folders:
                logger.info(f"Getting files in folder '{folder_id}' as '{user_email}'")
                yield from _yield_from_folder_crawl(folder_id, start)
        curr_stage.stage = DriveRetrievalStage.DONE

    def _manage_service_account_retrieval(
        self,
        is_slim: bool,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        if checkpoint.completion_stage == DriveRetrievalStage.START:
            checkpoint.completion_stage = DriveRetrievalStage.USER_EMAILS

        if checkpoint.completion_stage == DriveRetrievalStage.USER_EMAILS:
            all_org_emails: list[str] = self._get_all_user_emails()
            if not is_slim:
                checkpoint.user_emails = all_org_emails
            checkpoint.completion_stage = DriveRetrievalStage.DRIVE_IDS
        else:
            assert checkpoint.user_emails is not None, "user emails not set"
            all_org_emails = checkpoint.user_emails

        drive_ids_to_retrieve, folder_ids_to_retrieve = self._determine_retrieval_ids(
            checkpoint, is_slim, DriveRetrievalStage.MY_DRIVE_FILES
        )

        # we've found all users and drives, now time to actually start
        # fetching stuff
        logger.info(f"Found {len(all_org_emails)} users to impersonate")
        logger.debug(f"Users: {all_org_emails}")
        logger.info(f"Found {len(drive_ids_to_retrieve)} drives to retrieve")
        logger.debug(f"Drives: {drive_ids_to_retrieve}")
        logger.info(f"Found {len(folder_ids_to_retrieve)} folders to retrieve")
        logger.debug(f"Folders: {folder_ids_to_retrieve}")

        drive_id_iterator = self.make_drive_id_iterator(
            drive_ids_to_retrieve, checkpoint
        )

        for email in all_org_emails:
            checkpoint.completion_map[email] = StageCompletion(
                stage=DriveRetrievalStage.START,
                completed_until=0,
            )
        user_retrieval_gens = [
            self._impersonate_user_for_retrieval(
                email,
                is_slim,
                checkpoint,
                drive_id_iterator,
                folder_ids_to_retrieve,
                start,
                end,
            )
            for email in all_org_emails
        ]
        yield from parallel_yield(user_retrieval_gens, max_workers=MAX_DRIVE_WORKERS)

        remaining_folders = (
            drive_ids_to_retrieve | folder_ids_to_retrieve
        ) - self._retrieved_ids
        if remaining_folders:
            logger.warning(
                f"Some folders/drives were not retrieved. IDs: {remaining_folders}"
            )
        assert all(
            checkpoint.completion_map[user_email].stage == DriveRetrievalStage.DONE
            for user_email in all_org_emails
        ), "some users did not complete retrieval"
        checkpoint.completion_stage = DriveRetrievalStage.DONE

    def _determine_retrieval_ids(
        self,
        checkpoint: GoogleDriveCheckpoint,
        is_slim: bool,
        next_stage: DriveRetrievalStage,
    ) -> tuple[set[str], set[str]]:
        all_drive_ids = self.get_all_drive_ids()
        drive_ids_to_retrieve: set[str] = set()
        folder_ids_to_retrieve: set[str] = set()
        if checkpoint.completion_stage == DriveRetrievalStage.DRIVE_IDS:
            if self._requested_shared_drive_ids or self._requested_folder_ids:
                (
                    drive_ids_to_retrieve,
                    folder_ids_to_retrieve,
                ) = _clean_requested_drive_ids(
                    requested_drive_ids=self._requested_shared_drive_ids,
                    requested_folder_ids=self._requested_folder_ids,
                    all_drive_ids_available=all_drive_ids,
                )
            elif self.include_shared_drives:
                drive_ids_to_retrieve = all_drive_ids

            if not is_slim:
                checkpoint.drive_ids_to_retrieve = list(drive_ids_to_retrieve)
                checkpoint.folder_ids_to_retrieve = list(folder_ids_to_retrieve)
            checkpoint.completion_stage = next_stage
        else:
            assert (
                checkpoint.drive_ids_to_retrieve is not None
            ), "drive ids to retrieve not set"
            assert (
                checkpoint.folder_ids_to_retrieve is not None
            ), "folder ids to retrieve not set"
            # When loading from a checkpoint, load the previously cached drive and folder ids
            drive_ids_to_retrieve = set(checkpoint.drive_ids_to_retrieve)
            folder_ids_to_retrieve = set(checkpoint.folder_ids_to_retrieve)

        return drive_ids_to_retrieve, folder_ids_to_retrieve

    def _oauth_retrieval_all_files(
        self,
        is_slim: bool,
        drive_service: GoogleDriveService,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        if not self.include_files_shared_with_me and not self.include_my_drives:
            return

        logger.info(
            f"Getting shared files/my drive files for OAuth "
            f"with include_files_shared_with_me={self.include_files_shared_with_me}, "
            f"include_my_drives={self.include_my_drives}, "
            f"include_shared_drives={self.include_shared_drives}."
            f"Using '{self.primary_admin_email}' as the account."
        )
        yield from add_retrieval_info(
            get_all_files_for_oauth(
                service=drive_service,
                include_files_shared_with_me=self.include_files_shared_with_me,
                include_my_drives=self.include_my_drives,
                include_shared_drives=self.include_shared_drives,
                is_slim=is_slim,
                start=start,
                end=end,
            ),
            self.primary_admin_email,
            DriveRetrievalStage.OAUTH_FILES,
        )

    def _oauth_retrieval_drives(
        self,
        is_slim: bool,
        drive_service: GoogleDriveService,
        drive_ids_to_retrieve: set[str],
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        def _yield_from_drive(
            drive_id: str, drive_start: SecondsSinceUnixEpoch | None
        ) -> Iterator[RetrievedDriveFile]:
            yield from add_retrieval_info(
                get_files_in_shared_drive(
                    service=drive_service,
                    drive_id=drive_id,
                    is_slim=is_slim,
                    update_traversed_ids_func=self._update_traversed_parent_ids,
                    start=drive_start,
                    end=end,
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
            ].completed_until_parent_id
            assert drive_id is not None, "drive id not set in checkpoint"
            resume_start = checkpoint.completion_map[
                self.primary_admin_email
            ].completed_until
            yield from _yield_from_drive(drive_id, resume_start)

        for drive_id in drive_ids_to_retrieve:
            if drive_id in self._retrieved_ids:
                logger.info(
                    f"Skipping drive '{drive_id}' as it has already been retrieved"
                )
                continue
            logger.info(
                f"Getting files in shared drive '{drive_id}' as '{self.primary_admin_email}'"
            )
            yield from _yield_from_drive(drive_id, start)

    def _oauth_retrieval_folders(
        self,
        is_slim: bool,
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
        remaining_folders = folder_ids_to_retrieve - self._retrieved_ids

        def _yield_from_folder_crawl(
            folder_id: str, folder_start: SecondsSinceUnixEpoch | None
        ) -> Iterator[RetrievedDriveFile]:
            yield from crawl_folders_for_files(
                service=drive_service,
                parent_id=folder_id,
                is_slim=is_slim,
                user_email=self.primary_admin_email,
                traversed_parent_ids=self._retrieved_ids,
                update_traversed_ids_func=self._update_traversed_parent_ids,
                start=folder_start,
                end=end,
            )

        # resume from a checkpoint
        if (
            checkpoint.completion_map[self.primary_admin_email].stage
            == DriveRetrievalStage.FOLDER_FILES
        ):
            folder_id = checkpoint.completion_map[
                self.primary_admin_email
            ].completed_until_parent_id
            assert folder_id is not None, "folder id not set in checkpoint"
            resume_start = checkpoint.completion_map[
                self.primary_admin_email
            ].completed_until
            yield from _yield_from_folder_crawl(folder_id, resume_start)

        # the times stored in the completion_map aren't used due to the crawling behavior
        # instead, the traversed_parent_ids are used to determine what we have left to retrieve
        for folder_id in remaining_folders:
            logger.info(
                f"Getting files in folder '{folder_id}' as '{self.primary_admin_email}'"
            )
            yield from _yield_from_folder_crawl(folder_id, start)

        remaining_folders = (
            drive_ids_to_retrieve | folder_ids_to_retrieve
        ) - self._retrieved_ids
        if remaining_folders:
            logger.warning(
                f"Some folders/drives were not retrieved. IDs: {remaining_folders}"
            )

    def _checkpointed_retrieval(
        self,
        retrieval_method: CredentialedRetrievalMethod,
        is_slim: bool,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        drive_files = retrieval_method(
            is_slim=is_slim,
            checkpoint=checkpoint,
            start=start,
            end=end,
        )
        if is_slim:
            yield from drive_files
            return

        for file in drive_files:
            if file.error is not None:
                checkpoint.completion_map[file.user_email].update(
                    stage=file.completion_stage,
                    completed_until=file.drive_file[GoogleFields.MODIFIED_TIME.value],
                    completed_until_parent_id=file.parent_id,
                )
            yield file

    def _manage_oauth_retrieval(
        self,
        is_slim: bool,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        if checkpoint.completion_stage == DriveRetrievalStage.START:
            checkpoint.completion_stage = DriveRetrievalStage.OAUTH_FILES
            checkpoint.completion_map[self.primary_admin_email] = StageCompletion(
                stage=DriveRetrievalStage.START,
                completed_until=0,
                completed_until_parent_id=None,
            )

        drive_service = get_drive_service(self.creds, self.primary_admin_email)

        if checkpoint.completion_stage == DriveRetrievalStage.OAUTH_FILES:
            completion = checkpoint.completion_map[self.primary_admin_email]
            all_files_start = start
            # if resuming from a checkpoint
            if completion.stage == DriveRetrievalStage.OAUTH_FILES:
                all_files_start = completion.completed_until

            yield from self._oauth_retrieval_all_files(
                drive_service=drive_service,
                is_slim=is_slim,
                start=all_files_start,
                end=end,
            )
            checkpoint.completion_stage = DriveRetrievalStage.DRIVE_IDS

        all_requested = (
            self.include_files_shared_with_me
            and self.include_my_drives
            and self.include_shared_drives
        )
        if all_requested:
            # If all 3 are true, we already yielded from get_all_files_for_oauth
            checkpoint.completion_stage = DriveRetrievalStage.DONE
            return

        drive_ids_to_retrieve, folder_ids_to_retrieve = self._determine_retrieval_ids(
            checkpoint, is_slim, DriveRetrievalStage.SHARED_DRIVE_FILES
        )

        if checkpoint.completion_stage == DriveRetrievalStage.SHARED_DRIVE_FILES:
            yield from self._oauth_retrieval_drives(
                is_slim=is_slim,
                drive_service=drive_service,
                drive_ids_to_retrieve=drive_ids_to_retrieve,
                checkpoint=checkpoint,
                start=start,
                end=end,
            )

            checkpoint.completion_stage = DriveRetrievalStage.FOLDER_FILES

        if checkpoint.completion_stage == DriveRetrievalStage.FOLDER_FILES:
            yield from self._oauth_retrieval_folders(
                is_slim=is_slim,
                drive_service=drive_service,
                drive_ids_to_retrieve=drive_ids_to_retrieve,
                folder_ids_to_retrieve=folder_ids_to_retrieve,
                checkpoint=checkpoint,
                start=start,
                end=end,
            )

        checkpoint.completion_stage = DriveRetrievalStage.DONE

    def _fetch_drive_items(
        self,
        is_slim: bool,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[RetrievedDriveFile]:
        retrieval_method = (
            self._manage_service_account_retrieval
            if isinstance(self.creds, ServiceAccountCredentials)
            else self._manage_oauth_retrieval
        )

        return self._checkpointed_retrieval(
            retrieval_method=retrieval_method,
            is_slim=is_slim,
            checkpoint=checkpoint,
            start=start,
            end=end,
        )

    def _extract_docs_from_google_drive(
        self,
        checkpoint: GoogleDriveCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[list[Document | ConnectorFailure]]:
        try:
            # Create a larger process pool for file conversion
            with ThreadPoolExecutor(max_workers=8) as executor:
                # Prepare a partial function with the credentials and admin email
                convert_func = partial(
                    _convert_single_file,
                    self.creds,
                    self.primary_admin_email,
                )

                # Fetch files in batches
                batches_complete = 0
                files_batch: list[GoogleDriveFileType] = []
                for retrieved_file in self._fetch_drive_items(
                    is_slim=False,
                    checkpoint=checkpoint,
                    start=start,
                    end=end,
                ):
                    if retrieved_file.error is not None:
                        failure_stage = retrieved_file.completion_stage.value
                        failure_message = (
                            f"retrieval failure during stage: {failure_stage},"
                        )
                        failure_message += f"user: {retrieved_file.user_email},"
                        failure_message += (
                            f"parent drive/folder: {retrieved_file.parent_id},"
                        )
                        failure_message += f"error: {retrieved_file.error}"
                        logger.error(failure_message)
                        yield [
                            ConnectorFailure(
                                failed_entity=EntityFailure(
                                    entity_id=failure_stage,
                                ),
                                failure_message=failure_message,
                                exception=retrieved_file.error,
                            )
                        ]
                        continue
                    files_batch.append(retrieved_file.drive_file)

                    if len(files_batch) < self.batch_size:
                        continue

                    # Process the batch
                    futures = [
                        executor.submit(convert_func, file) for file in files_batch
                    ]
                    documents = []
                    for future in as_completed(futures):
                        try:
                            doc = future.result()
                            if doc is not None:
                                documents.append(doc)
                        except Exception as e:
                            error_str = f"Error converting file: {e}"
                            logger.error(error_str)
                            yield [
                                ConnectorFailure(
                                    failed_document=DocumentFailure(
                                        document_id=retrieved_file.drive_file["id"],
                                        document_link=retrieved_file.drive_file[
                                            "webViewLink"
                                        ],
                                    ),
                                    failure_message=error_str,
                                    exception=e,
                                )
                            ]

                    if documents:
                        yield documents
                        batches_complete += 1
                    files_batch = []

                    if batches_complete > BATCHES_PER_CHECKPOINT:
                        checkpoint.retrieved_folder_and_drive_ids = self._retrieved_ids
                        return  # create a new checkpoint

                # Process any remaining files
                if files_batch:
                    futures = [
                        executor.submit(convert_func, file) for file in files_batch
                    ]
                    documents = []
                    for future in as_completed(futures):
                        try:
                            doc = future.result()
                            if doc is not None:
                                documents.append(doc)
                        except Exception as e:
                            error_str = f"Error converting file: {e}"
                            logger.error(error_str)
                            yield [
                                ConnectorFailure(
                                    failed_document=DocumentFailure(
                                        document_id=retrieved_file.drive_file["id"],
                                        document_link=retrieved_file.drive_file[
                                            "webViewLink"
                                        ],
                                    ),
                                    failure_message=error_str,
                                    exception=e,
                                )
                            ]

                    if documents:
                        yield documents
        except Exception as e:
            logger.exception(f"Error extracting documents from Google Drive: {e}")
            raise e

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GoogleDriveCheckpoint,
    ) -> CheckpointOutput[GoogleDriveCheckpoint]:
        """
        Entrypoint for the connector; first run is with an empty checkpoint.
        """
        if self._creds is None or self._primary_admin_email is None:
            raise RuntimeError(
                "Credentials missing, should not call this method before calling load_credentials"
            )

        checkpoint = copy.deepcopy(checkpoint)
        self._retrieved_ids = checkpoint.retrieved_folder_and_drive_ids
        try:
            for doc_list in self._extract_docs_from_google_drive(
                checkpoint, start, end
            ):
                yield from doc_list
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e
        checkpoint.retrieved_folder_and_drive_ids = self._retrieved_ids
        if checkpoint.completion_stage == DriveRetrievalStage.DONE:
            checkpoint.has_more = False
        return checkpoint

    def _extract_slim_docs_from_google_drive(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        slim_batch = []
        for file in self._fetch_drive_items(
            checkpoint=self.build_dummy_checkpoint(),
            is_slim=True,
            start=start,
            end=end,
        ):
            if file.error is not None:
                raise file.error
            if doc := build_slim_document(file.drive_file):
                slim_batch.append(doc)
            if len(slim_batch) >= SLIM_BATCH_SIZE:
                yield slim_batch
                slim_batch = []
                if callback:
                    if callback.should_stop():
                        raise RuntimeError(
                            "_extract_slim_docs_from_google_drive: Stop signal detected"
                        )

                    callback.progress("_extract_slim_docs_from_google_drive", 1)

        yield slim_batch

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        try:
            yield from self._extract_slim_docs_from_google_drive(
                start, end, callback=callback
            )
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

    def validate_connector_settings(self) -> None:
        if self._creds is None:
            raise ConnectorMissingCredentialError(
                "Google Drive credentials not loaded."
            )

        if self._primary_admin_email is None:
            raise ConnectorValidationError(
                "Primary admin email not found in credentials. "
                "Ensure DB_CREDENTIALS_PRIMARY_ADMIN_KEY is set."
            )

        try:
            drive_service = get_drive_service(self._creds, self._primary_admin_email)
            drive_service.files().list(pageSize=1, fields="files(id)").execute()

            if isinstance(self._creds, ServiceAccountCredentials):
                retry_builder()(get_root_folder_id)(drive_service)

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
                    "Google Drive credentials are missing required scopes. "
                    f"{ONYX_SCOPE_INSTRUCTIONS}"
                )
            raise ConnectorValidationError(
                f"Unexpected error during Google Drive validation: {e}"
            )

    @override
    def build_dummy_checkpoint(self) -> GoogleDriveCheckpoint:
        return GoogleDriveCheckpoint(
            retrieved_folder_and_drive_ids=set(),
            completion_stage=DriveRetrievalStage.START,
            completion_map=ThreadSafeDict(),
            has_more=True,
        )

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> GoogleDriveCheckpoint:
        return GoogleDriveCheckpoint.model_validate_json(checkpoint_json)
