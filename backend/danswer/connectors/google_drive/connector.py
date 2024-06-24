import io
from collections.abc import Iterator
from collections.abc import Sequence
from datetime import datetime
from datetime import timezone
from enum import Enum
from itertools import chain
from typing import Any
from typing import cast

from google.oauth2.credentials import Credentials as OAuthCredentials  # type: ignore
from google.oauth2.service_account import Credentials as ServiceAccountCredentials  # type: ignore
from googleapiclient import discovery  # type: ignore
from googleapiclient.errors import HttpError  # type: ignore

from danswer.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE
from danswer.configs.app_configs import GOOGLE_DRIVE_FOLLOW_SHORTCUTS
from danswer.configs.app_configs import GOOGLE_DRIVE_INCLUDE_SHARED
from danswer.configs.app_configs import GOOGLE_DRIVE_ONLY_ORG_PUBLIC
from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.configs.constants import IGNORE_FOR_QA
from danswer.connectors.cross_connector_utils.retry_wrapper import retry_builder
from danswer.connectors.google_drive.connector_auth import (
    get_google_drive_creds_for_authorized_user,
)
from danswer.connectors.google_drive.connector_auth import (
    get_google_drive_creds_for_service_account,
)
from danswer.connectors.google_drive.constants import (
    DB_CREDENTIALS_DICT_DELEGATED_USER_KEY,
)
from danswer.connectors.google_drive.constants import (
    DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY,
)
from danswer.connectors.google_drive.constants import DB_CREDENTIALS_DICT_TOKEN_KEY
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.file_processing.extract_file_text import docx_to_text
from danswer.file_processing.extract_file_text import pdf_to_text
from danswer.file_processing.extract_file_text import pptx_to_text
from danswer.utils.batching import batch_generator
from danswer.utils.logger import setup_logger

logger = setup_logger()

DRIVE_FOLDER_TYPE = "application/vnd.google-apps.folder"
DRIVE_SHORTCUT_TYPE = "application/vnd.google-apps.shortcut"
UNSUPPORTED_FILE_TYPE_CONTENT = ""  # keep empty for now


class GDriveMimeType(str, Enum):
    DOC = "application/vnd.google-apps.document"
    SPREADSHEET = "application/vnd.google-apps.spreadsheet"
    PDF = "application/pdf"
    WORD_DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    PPT = "application/vnd.google-apps.presentation"
    POWERPOINT = (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


GoogleDriveFileType = dict[str, Any]

# Google Drive APIs are quite flakey and may 500 for an
# extended period of time. Trying to combat here by adding a very
# long retry period (~20 minutes of trying every minute)
add_retries = retry_builder(tries=50, max_delay=30)


def _run_drive_file_query(
    service: discovery.Resource,
    query: str,
    continue_on_failure: bool,
    include_shared: bool = GOOGLE_DRIVE_INCLUDE_SHARED,
    follow_shortcuts: bool = GOOGLE_DRIVE_FOLLOW_SHORTCUTS,
    batch_size: int = INDEX_BATCH_SIZE,
) -> Iterator[GoogleDriveFileType]:
    next_page_token = ""
    while next_page_token is not None:
        logger.debug(f"Running Google Drive fetch with query: {query}")
        results = add_retries(
            lambda: (
                service.files()
                .list(
                    corpora="allDrives"
                    if include_shared
                    else "user",  # needed to search through shared drives
                    pageSize=batch_size,
                    supportsAllDrives=include_shared,
                    includeItemsFromAllDrives=include_shared,
                    fields=(
                        "nextPageToken, files(mimeType, id, name, permissions, "
                        "modifiedTime, webViewLink, shortcutDetails)"
                    ),
                    pageToken=next_page_token,
                    q=query,
                )
                .execute()
            )
        )()
        next_page_token = results.get("nextPageToken")
        files = results["files"]
        for file in files:
            if follow_shortcuts and "shortcutDetails" in file:
                try:
                    file_shortcut_points_to = add_retries(
                        lambda: (
                            service.files()
                            .get(
                                fileId=file["shortcutDetails"]["targetId"],
                                supportsAllDrives=include_shared,
                                fields="mimeType, id, name, modifiedTime, webViewLink, permissions, shortcutDetails",
                            )
                            .execute()
                        )
                    )()
                    yield file_shortcut_points_to
                except HttpError:
                    logger.error(
                        f"Failed to follow shortcut with details: {file['shortcutDetails']}"
                    )
                    if continue_on_failure:
                        continue
                    raise
            else:
                yield file


def _get_folder_id(
    service: discovery.Resource,
    parent_id: str,
    folder_name: str,
    include_shared: bool,
    follow_shortcuts: bool,
) -> str | None:
    """
    Get the ID of a folder given its name and the ID of its parent folder.
    """
    query = f"'{parent_id}' in parents and name='{folder_name}' and "
    if follow_shortcuts:
        query += f"(mimeType='{DRIVE_FOLDER_TYPE}' or mimeType='{DRIVE_SHORTCUT_TYPE}')"
    else:
        query += f"mimeType='{DRIVE_FOLDER_TYPE}'"

    # TODO: support specifying folder path in shared drive rather than just `My Drive`
    results = add_retries(
        lambda: (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, shortcutDetails)",
                supportsAllDrives=include_shared,
                includeItemsFromAllDrives=include_shared,
            )
            .execute()
        )
    )()
    items = results.get("files", [])

    folder_id = None
    if items:
        if follow_shortcuts and "shortcutDetails" in items[0]:
            folder_id = items[0]["shortcutDetails"]["targetId"]
        else:
            folder_id = items[0]["id"]
    return folder_id


def _get_folders(
    service: discovery.Resource,
    continue_on_failure: bool,
    folder_id: str | None = None,  # if specified, only fetches files within this folder
    include_shared: bool = GOOGLE_DRIVE_INCLUDE_SHARED,
    follow_shortcuts: bool = GOOGLE_DRIVE_FOLLOW_SHORTCUTS,
    batch_size: int = INDEX_BATCH_SIZE,
) -> Iterator[GoogleDriveFileType]:
    query = f"mimeType = '{DRIVE_FOLDER_TYPE}' "
    if follow_shortcuts:
        query = "(" + query + f" or mimeType = '{DRIVE_SHORTCUT_TYPE}'" + ") "

    if folder_id:
        query += f"and '{folder_id}' in parents "
    query = query.rstrip()  # remove the trailing space(s)

    for file in _run_drive_file_query(
        service=service,
        query=query,
        continue_on_failure=continue_on_failure,
        include_shared=include_shared,
        follow_shortcuts=follow_shortcuts,
        batch_size=batch_size,
    ):
        # Need to check this since file may have been a target of a shortcut
        # and not necessarily a folder
        if file["mimeType"] == DRIVE_FOLDER_TYPE:
            yield file
        else:
            pass


def _get_files(
    service: discovery.Resource,
    continue_on_failure: bool,
    time_range_start: SecondsSinceUnixEpoch | None = None,
    time_range_end: SecondsSinceUnixEpoch | None = None,
    folder_id: str | None = None,  # if specified, only fetches files within this folder
    include_shared: bool = GOOGLE_DRIVE_INCLUDE_SHARED,
    follow_shortcuts: bool = GOOGLE_DRIVE_FOLLOW_SHORTCUTS,
    batch_size: int = INDEX_BATCH_SIZE,
) -> Iterator[GoogleDriveFileType]:
    query = f"mimeType != '{DRIVE_FOLDER_TYPE}' "
    if time_range_start is not None:
        time_start = datetime.utcfromtimestamp(time_range_start).isoformat() + "Z"
        query += f"and modifiedTime >= '{time_start}' "
    if time_range_end is not None:
        time_stop = datetime.utcfromtimestamp(time_range_end).isoformat() + "Z"
        query += f"and modifiedTime <= '{time_stop}' "
    if folder_id:
        query += f"and '{folder_id}' in parents "
    query = query.rstrip()  # remove the trailing space(s)

    files = _run_drive_file_query(
        service=service,
        query=query,
        continue_on_failure=continue_on_failure,
        include_shared=include_shared,
        follow_shortcuts=follow_shortcuts,
        batch_size=batch_size,
    )

    return files


def get_all_files_batched(
    service: discovery.Resource,
    continue_on_failure: bool,
    include_shared: bool = GOOGLE_DRIVE_INCLUDE_SHARED,
    follow_shortcuts: bool = GOOGLE_DRIVE_FOLLOW_SHORTCUTS,
    batch_size: int = INDEX_BATCH_SIZE,
    time_range_start: SecondsSinceUnixEpoch | None = None,
    time_range_end: SecondsSinceUnixEpoch | None = None,
    folder_id: str | None = None,  # if specified, only fetches files within this folder
    # if True, will fetch files in sub-folders of the specified folder ID.
    # Only applies if folder_id is specified.
    traverse_subfolders: bool = True,
    folder_ids_traversed: list[str] | None = None,
) -> Iterator[list[GoogleDriveFileType]]:
    """Gets all files matching the criteria specified by the args from Google Drive
    in batches of size `batch_size`.
    """
    found_files = _get_files(
        service=service,
        continue_on_failure=continue_on_failure,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        folder_id=folder_id,
        include_shared=include_shared,
        follow_shortcuts=follow_shortcuts,
        batch_size=batch_size,
    )
    yield from batch_generator(
        items=found_files,
        batch_size=batch_size,
        pre_batch_yield=lambda batch_files: logger.info(
            f"Parseable Documents in batch: {[file['name'] for file in batch_files]}"
        ),
    )

    if traverse_subfolders and folder_id is not None:
        folder_ids_traversed = folder_ids_traversed or []
        subfolders = _get_folders(
            service=service,
            folder_id=folder_id,
            continue_on_failure=continue_on_failure,
            include_shared=include_shared,
            follow_shortcuts=follow_shortcuts,
            batch_size=batch_size,
        )
        for subfolder in subfolders:
            if subfolder["id"] not in folder_ids_traversed:
                logger.info("Fetching all files in subfolder: " + subfolder["name"])
                folder_ids_traversed.append(subfolder["id"])
                yield from get_all_files_batched(
                    service=service,
                    continue_on_failure=continue_on_failure,
                    include_shared=include_shared,
                    follow_shortcuts=follow_shortcuts,
                    batch_size=batch_size,
                    time_range_start=time_range_start,
                    time_range_end=time_range_end,
                    folder_id=subfolder["id"],
                    traverse_subfolders=traverse_subfolders,
                    folder_ids_traversed=folder_ids_traversed,
                )
            else:
                logger.debug(
                    "Skipping subfolder since already traversed: " + subfolder["name"]
                )


def extract_text(file: dict[str, str], service: discovery.Resource) -> str:
    mime_type = file["mimeType"]
    if mime_type not in set(item.value for item in GDriveMimeType):
        # Unsupported file types can still have a title, finding this way is still useful
        return UNSUPPORTED_FILE_TYPE_CONTENT

    if mime_type == GDriveMimeType.DOC.value:
        return (
            service.files()
            .export(fileId=file["id"], mimeType="text/plain")
            .execute()
            .decode("utf-8")
        )
    elif mime_type == GDriveMimeType.SPREADSHEET.value:
        return (
            service.files()
            .export(fileId=file["id"], mimeType="text/csv")
            .execute()
            .decode("utf-8")
        )
    elif mime_type == GDriveMimeType.WORD_DOC.value:
        response = service.files().get_media(fileId=file["id"]).execute()
        return docx_to_text(file=io.BytesIO(response))
    elif mime_type == GDriveMimeType.PDF.value:
        response = service.files().get_media(fileId=file["id"]).execute()
        return pdf_to_text(file=io.BytesIO(response))
    elif mime_type == GDriveMimeType.POWERPOINT.value:
        response = service.files().get_media(fileId=file["id"]).execute()
        return pptx_to_text(file=io.BytesIO(response))
    elif mime_type == GDriveMimeType.PPT.value:
        response = service.files().get_media(fileId=file["id"]).execute()
        return pptx_to_text(file=io.BytesIO(response))

    return UNSUPPORTED_FILE_TYPE_CONTENT


class GoogleDriveConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        # optional list of folder paths e.g. "[My Folder/My Subfolder]"
        # if specified, will only index files in these folders
        folder_paths: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        include_shared: bool = GOOGLE_DRIVE_INCLUDE_SHARED,
        follow_shortcuts: bool = GOOGLE_DRIVE_FOLLOW_SHORTCUTS,
        only_org_public: bool = GOOGLE_DRIVE_ONLY_ORG_PUBLIC,
        continue_on_failure: bool = CONTINUE_ON_CONNECTOR_FAILURE,
    ) -> None:
        self.folder_paths = folder_paths or []
        self.batch_size = batch_size
        self.include_shared = include_shared
        self.follow_shortcuts = follow_shortcuts
        self.only_org_public = only_org_public
        self.continue_on_failure = continue_on_failure
        self.creds: OAuthCredentials | ServiceAccountCredentials | None = None

    @staticmethod
    def _process_folder_paths(
        service: discovery.Resource,
        folder_paths: list[str],
        include_shared: bool,
        follow_shortcuts: bool,
    ) -> list[str]:
        """['Folder/Sub Folder'] -> ['<FOLDER_ID>']"""
        folder_ids: list[str] = []
        for path in folder_paths:
            folder_names = path.split("/")
            parent_id = "root"
            for folder_name in folder_names:
                found_parent_id = _get_folder_id(
                    service=service,
                    parent_id=parent_id,
                    folder_name=folder_name,
                    include_shared=include_shared,
                    follow_shortcuts=follow_shortcuts,
                )
                if found_parent_id is None:
                    raise ValueError(
                        (
                            f"Folder '{folder_name}' in path '{path}' "
                            "not found in Google Drive"
                        )
                    )
                parent_id = found_parent_id
            folder_ids.append(parent_id)

        return folder_ids

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, str] | None:
        """Checks for two different types of credentials.
        (1) A credential which holds a token acquired via a user going thorough
        the Google OAuth flow.
        (2) A credential which holds a service account key JSON file, which
        can then be used to impersonate any user in the workspace.
        """
        creds: OAuthCredentials | ServiceAccountCredentials | None = None
        new_creds_dict = None
        if DB_CREDENTIALS_DICT_TOKEN_KEY in credentials:
            access_token_json_str = cast(
                str, credentials[DB_CREDENTIALS_DICT_TOKEN_KEY]
            )
            creds = get_google_drive_creds_for_authorized_user(
                token_json_str=access_token_json_str
            )

            # tell caller to update token stored in DB if it has changed
            # (e.g. the token has been refreshed)
            new_creds_json_str = creds.to_json() if creds else ""
            if new_creds_json_str != access_token_json_str:
                new_creds_dict = {DB_CREDENTIALS_DICT_TOKEN_KEY: new_creds_json_str}

        if DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY in credentials:
            service_account_key_json_str = credentials[
                DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY
            ]
            creds = get_google_drive_creds_for_service_account(
                service_account_key_json_str=service_account_key_json_str
            )

            # "Impersonate" a user if one is specified
            delegated_user_email = cast(
                str | None, credentials.get(DB_CREDENTIALS_DICT_DELEGATED_USER_KEY)
            )
            if delegated_user_email:
                creds = creds.with_subject(delegated_user_email) if creds else None  # type: ignore

        if creds is None:
            raise PermissionError(
                "Unable to access Google Drive - unknown credential structure."
            )

        self.creds = creds
        return new_creds_dict

    def _fetch_docs_from_drive(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateDocumentsOutput:
        if self.creds is None:
            raise PermissionError("Not logged into Google Drive")

        service = discovery.build("drive", "v3", credentials=self.creds)
        folder_ids: Sequence[str | None] = self._process_folder_paths(
            service, self.folder_paths, self.include_shared, self.follow_shortcuts
        )
        if not folder_ids:
            folder_ids = [None]

        file_batches = chain(
            *[
                get_all_files_batched(
                    service=service,
                    continue_on_failure=self.continue_on_failure,
                    include_shared=self.include_shared,
                    follow_shortcuts=self.follow_shortcuts,
                    batch_size=self.batch_size,
                    time_range_start=start,
                    time_range_end=end,
                    folder_id=folder_id,
                    traverse_subfolders=True,
                )
                for folder_id in folder_ids
            ]
        )
        for files_batch in file_batches:
            doc_batch = []
            for file in files_batch:
                try:
                    # Skip files that are shortcuts
                    if file.get("mimeType") == DRIVE_SHORTCUT_TYPE:
                        logger.info("Ignoring Drive Shortcut Filetype")
                        continue

                    if self.only_org_public:
                        if "permissions" not in file:
                            continue
                        if not any(
                            permission["type"] == "domain"
                            for permission in file["permissions"]
                        ):
                            continue

                    text_contents = extract_text(file, service) or ""

                    doc_batch.append(
                        Document(
                            id=file["webViewLink"],
                            sections=[
                                Section(link=file["webViewLink"], text=text_contents)
                            ],
                            source=DocumentSource.GOOGLE_DRIVE,
                            semantic_identifier=file["name"],
                            doc_updated_at=datetime.fromisoformat(
                                file["modifiedTime"]
                            ).astimezone(timezone.utc),
                            metadata={} if text_contents else {IGNORE_FOR_QA: "True"},
                        )
                    )
                except Exception as e:
                    if not self.continue_on_failure:
                        raise e

                    logger.exception(
                        "Ran into exception when pulling a file from Google Drive"
                    )

            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        yield from self._fetch_docs_from_drive()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        # need to subtract 10 minutes from start time to account for modifiedTime
        # propogation if a document is modified, it takes some time for the API to
        # reflect these changes if we do not have an offset, then we may "miss" the
        # update when polling
        yield from self._fetch_docs_from_drive(start, end)


if __name__ == "__main__":
    import json
    import os

    service_account_json_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY_JSON_PATH")
    if not service_account_json_path:
        raise ValueError(
            "Please set GOOGLE_SERVICE_ACCOUNT_KEY_JSON_PATH environment variable"
        )
    with open(service_account_json_path) as f:
        creds = json.load(f)

    credentials_dict = {
        DB_CREDENTIALS_DICT_SERVICE_ACCOUNT_KEY: json.dumps(creds),
    }
    delegated_user = os.environ.get("GOOGLE_DRIVE_DELEGATED_USER")
    if delegated_user:
        credentials_dict[DB_CREDENTIALS_DICT_DELEGATED_USER_KEY] = delegated_user

    connector = GoogleDriveConnector(include_shared=True, follow_shortcuts=True)
    connector.load_credentials(credentials_dict)
    document_batch_generator = connector.load_from_state()
    for document_batch in document_batch_generator:
        print(document_batch)
        break
