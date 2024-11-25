from collections.abc import Callable
from collections.abc import Iterator
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from google.oauth2.credentials import Credentials as OAuthCredentials  # type: ignore
from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # type: ignore

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.google_drive.doc_conversion import build_slim_document
from danswer.connectors.google_drive.doc_conversion import (
    convert_drive_item_to_document,
)
from danswer.connectors.google_drive.file_retrieval import crawl_folders_for_files
from danswer.connectors.google_drive.file_retrieval import get_all_files_in_my_drive
from danswer.connectors.google_drive.file_retrieval import get_files_in_shared_drive
from danswer.connectors.google_drive.models import GoogleDriveFileType
from danswer.connectors.google_utils.google_auth import get_google_creds
from danswer.connectors.google_utils.google_utils import execute_paginated_retrieval
from danswer.connectors.google_utils.resources import get_admin_service
from danswer.connectors.google_utils.resources import get_drive_service
from danswer.connectors.google_utils.resources import get_google_docs_service
from danswer.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
)
from danswer.connectors.google_utils.shared_constants import MISSING_SCOPES_ERROR_STR
from danswer.connectors.google_utils.shared_constants import ONYX_SCOPE_INSTRUCTIONS
from danswer.connectors.google_utils.shared_constants import SCOPE_DOC_URL
from danswer.connectors.google_utils.shared_constants import SLIM_BATCH_SIZE
from danswer.connectors.google_utils.shared_constants import USER_FIELDS
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import GenerateSlimDocumentOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.interfaces import SlimConnector
from danswer.utils.logger import setup_logger

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


class GoogleDriveConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(
        self,
        include_shared_drives: bool = True,
        shared_drive_urls: str | None = None,
        include_my_drives: bool = True,
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
            and not shared_folder_urls
        ):
            raise ValueError(
                "At least one of include_shared_drives, include_my_drives,"
                " or shared_folder_urls must be true"
            )

        self.batch_size = batch_size

        self.include_shared_drives = include_shared_drives
        shared_drive_url_list = _extract_str_list_from_comma_str(shared_drive_urls)
        self._requested_shared_drive_ids = set(
            _extract_ids_from_urls(shared_drive_url_list)
        )

        self.include_my_drives = include_my_drives
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
        primary_admin_email = credentials[DB_CREDENTIALS_PRIMARY_ADMIN_KEY]
        self._primary_admin_email = primary_admin_email

        self._creds, new_creds_dict = get_google_creds(
            credentials=credentials,
            source=DocumentSource.GOOGLE_DRIVE,
        )
        return new_creds_dict

    def _update_traversed_parent_ids(self, folder_id: str) -> None:
        self._retrieved_ids.add(folder_id)

    def _get_all_user_emails(self, admins_only: bool) -> list[str]:
        admin_service = get_admin_service(
            creds=self.creds,
            user_email=self.primary_admin_email,
        )
        query = "isAdmin=true" if admins_only else "isAdmin=false"
        emails = []
        for user in execute_paginated_retrieval(
            retrieval_function=admin_service.users().list,
            list_key="users",
            fields=USER_FIELDS,
            domain=self.google_domain,
            query=query,
        ):
            if email := user.get("primaryEmail"):
                emails.append(email)
        return emails

    def _get_all_drive_ids(self) -> set[str]:
        primary_drive_service = get_drive_service(
            creds=self.creds,
            user_email=self.primary_admin_email,
        )
        all_drive_ids = set()
        for drive in execute_paginated_retrieval(
            retrieval_function=primary_drive_service.drives().list,
            list_key="drives",
            useDomainAdminAccess=True,
            fields="drives(id)",
        ):
            all_drive_ids.add(drive["id"])
        return all_drive_ids

    def _initialize_all_class_variables(self) -> None:
        # Get all user emails
        # Get admins first becuase they are more likely to have access to the most files
        user_emails = [self.primary_admin_email]
        for admins_only in [True, False]:
            for email in self._get_all_user_emails(admins_only=admins_only):
                if email not in user_emails:
                    user_emails.append(email)
        self._all_org_emails = user_emails

        self._all_drive_ids: set[str] = self._get_all_drive_ids()

        # remove drive ids from the folder ids because they are queried differently
        self._requested_folder_ids -= self._all_drive_ids

        # Remove drive_ids that are not in the all_drive_ids and check them as folders instead
        invalid_drive_ids = self._requested_shared_drive_ids - self._all_drive_ids
        if invalid_drive_ids:
            logger.warning(
                f"Some shared drive IDs were not found. IDs: {invalid_drive_ids}"
            )
            logger.warning("Checking for folder access instead...")
            self._requested_folder_ids.update(invalid_drive_ids)

        if not self.include_shared_drives:
            self._requested_shared_drive_ids = set()
        elif not self._requested_shared_drive_ids:
            self._requested_shared_drive_ids = self._all_drive_ids

    def _impersonate_user_for_retrieval(
        self,
        user_email: str,
        is_slim: bool,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[GoogleDriveFileType]:
        drive_service = get_drive_service(self.creds, user_email)
        if self.include_my_drives and (
            not self._requested_my_drive_emails
            or user_email in self._requested_my_drive_emails
        ):
            yield from get_all_files_in_my_drive(
                service=drive_service,
                update_traversed_ids_func=self._update_traversed_parent_ids,
                is_slim=is_slim,
                start=start,
                end=end,
            )

        remaining_drive_ids = self._requested_shared_drive_ids - self._retrieved_ids
        for drive_id in remaining_drive_ids:
            yield from get_files_in_shared_drive(
                service=drive_service,
                drive_id=drive_id,
                is_slim=is_slim,
                update_traversed_ids_func=self._update_traversed_parent_ids,
                start=start,
                end=end,
            )

        remaining_folders = self._requested_folder_ids - self._retrieved_ids
        for folder_id in remaining_folders:
            yield from crawl_folders_for_files(
                service=drive_service,
                parent_id=folder_id,
                traversed_parent_ids=self._retrieved_ids,
                update_traversed_ids_func=self._update_traversed_parent_ids,
                start=start,
                end=end,
            )

    def _fetch_drive_items(
        self,
        is_slim: bool,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> Iterator[GoogleDriveFileType]:
        self._initialize_all_class_variables()

        # Process users in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_email = {
                executor.submit(
                    self._impersonate_user_for_retrieval, email, is_slim, start, end
                ): email
                for email in self._all_org_emails
            }

            # Yield results as they complete
            for future in as_completed(future_to_email):
                yield from future.result()

        remaining_folders = self._requested_folder_ids - self._retrieved_ids
        if remaining_folders:
            logger.warning(
                f"Some folders/drives were not retrieved. IDs: {remaining_folders}"
            )

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
