from collections.abc import Callable
from collections.abc import Iterator
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any
from typing import cast

from google.oauth2.credentials import Credentials as OAuthCredentials  # type: ignore
from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import MAX_FILE_SIZE_BYTES
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive.doc_conversion import build_slim_document
from onyx.connectors.google_drive.doc_conversion import (
    convert_drive_item_to_document,
)
from onyx.connectors.google_drive.file_retrieval import crawl_folders_for_files
from onyx.connectors.google_drive.file_retrieval import get_all_files_for_oauth
from onyx.connectors.google_drive.file_retrieval import get_all_files_in_my_drive
from onyx.connectors.google_drive.file_retrieval import get_files_in_shared_drive
from onyx.connectors.google_drive.file_retrieval import get_root_folder_id
from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.google_utils import execute_paginated_retrieval
from onyx.connectors.google_utils.resources import get_admin_service
from onyx.connectors.google_utils.resources import get_drive_service
from onyx.connectors.google_utils.resources import get_google_docs_service
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from onyx.connectors.google_utils.shared_constants import MISSING_SCOPES_ERROR_STR
from onyx.connectors.google_utils.shared_constants import ONYX_SCOPE_INSTRUCTIONS
from onyx.connectors.google_utils.shared_constants import SCOPE_DOC_URL
from onyx.connectors.google_utils.shared_constants import SLIM_BATCH_SIZE
from onyx.connectors.google_utils.shared_constants import USER_FIELDS
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()
# TODO: Improve this by using the batch utility: https://googleapis.github.io/google-api-python-client/docs/batch.html
# All file retrievals could be batched and made at once


def _extract_str_list_from_comma_str(string: str | None) -> list[str]:
    if not string:
        return []
    return [s.strip() for s in string.split(",") if s.strip()]


def _extract_ids_from_urls(urls: list[str]) -> list[str]:
    return [url.split("/")[-1] for url in urls]


def _convert_single_file(
    creds: Any, primary_admin_email: str, file: dict[str, Any]
) -> Any:
    user_email = file.get("owners", [{}])[0].get("emailAddress") or primary_admin_email
    user_drive_service = get_drive_service(creds, user_email=user_email)
    docs_service = get_google_docs_service(creds, user_email=user_email)
    return convert_drive_item_to_document(
        file=file,
        drive_service=user_drive_service,
        docs_service=docs_service,
    )


def _process_files_batch(
    files: list[GoogleDriveFileType], convert_func: Callable, batch_size: int
) -> GenerateDocumentsOutput:
    doc_batch = []
    with ThreadPoolExecutor(max_workers=min(16, len(files))) as executor:
        for doc in executor.map(convert_func, files):
            if doc:
                doc_batch.append(doc)
                if len(doc_batch) >= batch_size:
                    yield doc_batch
                    doc_batch = []
    if doc_batch:
        yield doc_batch


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


class GoogleDriveConnector(LoadConnector, PollConnector, SlimConnector):
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
        if (
            folder_paths is not None
            or include_shared is not None
            or follow_shortcuts is not None
            or only_org_public is not None
            or continue_on_failure is not None
        ):
            logger.exception(
                "Google Drive connector received old input parameters. "
                "Please visit the docs for help with the new setup: "
                f"{SCOPE_DOC_URL}"
            )
            raise ValueError(
                "Google Drive connector received old input parameters. "
                "Please visit the docs for help with the new setup: "
                f"{SCOPE_DOC_URL}"
            )

        if (
            not include_shared_drives
            and not include_my_drives
            and not include_files_shared_with_me
            and not shared_folder_urls
            and not my_drive_emails
            and not shared_drive_urls
        ):
            raise ValueError(
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

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, str] | None:
        self._primary_admin_email = credentials[DB_CREDENTIALS_PRIMARY_ADMIN_KEY]

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

    def _get_all_drive_ids(self) -> set[str]:
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
                "No drives found even though we are indexing shared drives was requested."
            )

        return all_drive_ids

    def _impersonate_user_for_retrieval(
        self,
        user_email: str,
        is_slim: bool,
        filtered_drive_ids: set[str],
        filtered_folder_ids: set[str],
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[GoogleDriveFileType]:
        logger.info(f"Impersonating user {user_email}")

        drive_service = get_drive_service(self.creds, user_email)

        # validate that the user has access to the drive APIs by performing a simple
        # request and checking for a 401
        try:
            retry_builder()(get_root_folder_id)(drive_service)
        except HttpError as e:
            if e.status_code == 401:
                # fail gracefully, let the other impersonations continue
                # one user without access shouldn't block the entire connector
                logger.exception(
                    f"User '{user_email}' does not have access to the drive APIs."
                )
                return
            raise

        # if we are including my drives, try to get the current user's my
        # drive if any of the following are true:
        # - include_my_drives is true
        # - the current user's email is in the requested emails
        if self.include_my_drives or user_email in self._requested_my_drive_emails:
            logger.info(f"Getting all files in my drive as '{user_email}'")
            yield from get_all_files_in_my_drive(
                service=drive_service,
                update_traversed_ids_func=self._update_traversed_parent_ids,
                is_slim=is_slim,
                start=start,
                end=end,
            )

        remaining_drive_ids = filtered_drive_ids - self._retrieved_ids
        for drive_id in remaining_drive_ids:
            logger.info(f"Getting files in shared drive '{drive_id}' as '{user_email}'")
            yield from get_files_in_shared_drive(
                service=drive_service,
                drive_id=drive_id,
                is_slim=is_slim,
                update_traversed_ids_func=self._update_traversed_parent_ids,
                start=start,
                end=end,
            )

        remaining_folders = filtered_folder_ids - self._retrieved_ids
        for folder_id in remaining_folders:
            logger.info(f"Getting files in folder '{folder_id}' as '{user_email}'")
            yield from crawl_folders_for_files(
                service=drive_service,
                parent_id=folder_id,
                traversed_parent_ids=self._retrieved_ids,
                update_traversed_ids_func=self._update_traversed_parent_ids,
                start=start,
                end=end,
            )

    def _manage_service_account_retrieval(
        self,
        is_slim: bool,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[GoogleDriveFileType]:
        all_org_emails: list[str] = self._get_all_user_emails()

        all_drive_ids: set[str] = self._get_all_drive_ids()

        drive_ids_to_retrieve: set[str] = set()
        folder_ids_to_retrieve: set[str] = set()
        if self._requested_shared_drive_ids or self._requested_folder_ids:
            drive_ids_to_retrieve, folder_ids_to_retrieve = _clean_requested_drive_ids(
                requested_drive_ids=self._requested_shared_drive_ids,
                requested_folder_ids=self._requested_folder_ids,
                all_drive_ids_available=all_drive_ids,
            )
        elif self.include_shared_drives:
            drive_ids_to_retrieve = all_drive_ids

        # checkpoint - we've found all users and drives, now time to actually start
        # fetching stuff
        logger.info(f"Found {len(all_org_emails)} users to impersonate")
        logger.debug(f"Users: {all_org_emails}")
        logger.info(f"Found {len(drive_ids_to_retrieve)} drives to retrieve")
        logger.debug(f"Drives: {drive_ids_to_retrieve}")
        logger.info(f"Found {len(folder_ids_to_retrieve)} folders to retrieve")
        logger.debug(f"Folders: {folder_ids_to_retrieve}")

        # Process users in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_email = {
                executor.submit(
                    self._impersonate_user_for_retrieval,
                    email,
                    is_slim,
                    drive_ids_to_retrieve,
                    folder_ids_to_retrieve,
                    start,
                    end,
                ): email
                for email in all_org_emails
            }

            # Yield results as they complete
            for future in as_completed(future_to_email):
                yield from future.result()

        remaining_folders = (
            drive_ids_to_retrieve | folder_ids_to_retrieve
        ) - self._retrieved_ids
        if remaining_folders:
            logger.warning(
                f"Some folders/drives were not retrieved. IDs: {remaining_folders}"
            )

    def _manage_oauth_retrieval(
        self,
        is_slim: bool,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[GoogleDriveFileType]:
        drive_service = get_drive_service(self.creds, self.primary_admin_email)

        if self.include_files_shared_with_me or self.include_my_drives:
            logger.info(
                f"Getting shared files/my drive files for OAuth "
                f"with include_files_shared_with_me={self.include_files_shared_with_me}, "
                f"include_my_drives={self.include_my_drives}, "
                f"include_shared_drives={self.include_shared_drives}."
                f"Using '{self.primary_admin_email}' as the account."
            )
            yield from get_all_files_for_oauth(
                service=drive_service,
                include_files_shared_with_me=self.include_files_shared_with_me,
                include_my_drives=self.include_my_drives,
                include_shared_drives=self.include_shared_drives,
                is_slim=is_slim,
                start=start,
                end=end,
            )

        all_requested = (
            self.include_files_shared_with_me
            and self.include_my_drives
            and self.include_shared_drives
        )
        if all_requested:
            # If all 3 are true, we already yielded from get_all_files_for_oauth
            return

        all_drive_ids = self._get_all_drive_ids()
        drive_ids_to_retrieve: set[str] = set()
        folder_ids_to_retrieve: set[str] = set()
        if self._requested_shared_drive_ids or self._requested_folder_ids:
            drive_ids_to_retrieve, folder_ids_to_retrieve = _clean_requested_drive_ids(
                requested_drive_ids=self._requested_shared_drive_ids,
                requested_folder_ids=self._requested_folder_ids,
                all_drive_ids_available=all_drive_ids,
            )
        elif self.include_shared_drives:
            drive_ids_to_retrieve = all_drive_ids

        for drive_id in drive_ids_to_retrieve:
            logger.info(
                f"Getting files in shared drive '{drive_id}' as '{self.primary_admin_email}'"
            )
            yield from get_files_in_shared_drive(
                service=drive_service,
                drive_id=drive_id,
                is_slim=is_slim,
                update_traversed_ids_func=self._update_traversed_parent_ids,
                start=start,
                end=end,
            )

        # Even if no folders were requested, we still check if any drives were requested
        # that could be folders.
        remaining_folders = folder_ids_to_retrieve - self._retrieved_ids
        for folder_id in remaining_folders:
            logger.info(
                f"Getting files in folder '{folder_id}' as '{self.primary_admin_email}'"
            )
            yield from crawl_folders_for_files(
                service=drive_service,
                parent_id=folder_id,
                traversed_parent_ids=self._retrieved_ids,
                update_traversed_ids_func=self._update_traversed_parent_ids,
                start=start,
                end=end,
            )

        remaining_folders = (
            drive_ids_to_retrieve | folder_ids_to_retrieve
        ) - self._retrieved_ids
        if remaining_folders:
            logger.warning(
                f"Some folders/drives were not retrieved. IDs: {remaining_folders}"
            )

    def _fetch_drive_items(
        self,
        is_slim: bool,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[GoogleDriveFileType]:
        retrieval_method = (
            self._manage_service_account_retrieval
            if isinstance(self.creds, ServiceAccountCredentials)
            else self._manage_oauth_retrieval
        )
        drive_files = retrieval_method(
            is_slim=is_slim,
            start=start,
            end=end,
        )

        return drive_files

    def _extract_docs_from_google_drive(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        # Create a larger process pool for file conversion
        convert_func = partial(
            _convert_single_file, self.creds, self.primary_admin_email
        )

        # Process files in larger batches
        LARGE_BATCH_SIZE = self.batch_size * 4
        files_to_process = []
        # Gather the files into batches to be processed in parallel
        for file in self._fetch_drive_items(is_slim=False, start=start, end=end):
            if (
                file.get("size")
                and int(cast(str, file.get("size"))) > MAX_FILE_SIZE_BYTES
            ):
                logger.warning(
                    f"Skipping file {file.get('name', 'Unknown')} as it is too large: {file.get('size')} bytes"
                )
                continue

            files_to_process.append(file)
            if len(files_to_process) >= LARGE_BATCH_SIZE:
                yield from _process_files_batch(
                    files_to_process, convert_func, self.batch_size
                )
                files_to_process = []

        # Process any remaining files
        if files_to_process:
            yield from _process_files_batch(
                files_to_process, convert_func, self.batch_size
            )

    def load_from_state(self) -> GenerateDocumentsOutput:
        try:
            yield from self._extract_docs_from_google_drive()
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        try:
            yield from self._extract_docs_from_google_drive(start, end)
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e

    def _extract_slim_docs_from_google_drive(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateSlimDocumentOutput:
        slim_batch = []
        for file in self._fetch_drive_items(
            is_slim=True,
            start=start,
            end=end,
        ):
            if doc := build_slim_document(file):
                slim_batch.append(doc)
            if len(slim_batch) >= SLIM_BATCH_SIZE:
                yield slim_batch
                slim_batch = []
        yield slim_batch

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateSlimDocumentOutput:
        try:
            yield from self._extract_slim_docs_from_google_drive(start, end)
        except Exception as e:
            if MISSING_SCOPES_ERROR_STR in str(e):
                raise PermissionError(ONYX_SCOPE_INSTRUCTIONS) from e
            raise e
