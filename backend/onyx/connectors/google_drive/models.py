from enum import Enum
from typing import Any

from onyx.connectors.interfaces import ConnectorCheckpoint
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.utils.threadpool_concurrency import ThreadSafeDict


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


TOKEN_EXPIRATION_TIME = 3600  # 1 hour


# These correspond to The major stages of retrieval for google drive.
# The stages for the oauth flow are:
# get_all_files_for_oauth(),
# get_all_drive_ids(),
# get_files_in_shared_drive(),
# crawl_folders_for_files()
#
# The stages for the service account flow are roughly:
# get_all_user_emails(),
# get_all_drive_ids(),
# get_files_in_shared_drive(),
# Then for each user:
#   get_files_in_my_drive()
#   get_files_in_shared_drive()
#   crawl_folders_for_files()
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


class GoogleDriveCheckpoint(ConnectorCheckpoint):
    # The doc ids that were completed in the previous run
    prev_run_doc_ids: list[str]

    # Checkpoint version of _retrieved_ids
    retrieved_ids: list[str]

    # Describes the point in the retrieval+indexing process that the
    # checkpoint is at. when this is set to a given stage, the connector
    # will have already yielded at least 1 file or error from that stage.
    # The Done stage is used to signal that has_more should become False.
    completion_stage: DriveRetrievalStage

    # The key into completion_map that is currently being processed.
    # For stages that directly make a big (paginated) api call, this
    # will be the stage itself. For stages with multiple sub-stages,
    # this will be the id of the sub-stage. For example, when processing
    # shared drives, it will be the id of the shared drive.
    curr_completion_key: str

    # The latest timestamp of a file that has been retrieved per completion key.
    # See curr_completion_key for more details on completion keys.
    completion_map: ThreadSafeDict[str, SecondsSinceUnixEpoch] = ThreadSafeDict()

    # cached version of the drive and folder ids to retrieve
    drive_ids_to_retrieve: list[str] | None = None
    folder_ids_to_retrieve: list[str] | None = None

    # cached user emails
    user_emails: list[str] | None = None

    # @field_serializer("completion_map")
    # def serialize_completion_map(
    #     self, completion_map: ThreadSafeDict[str, SecondsSinceUnixEpoch], _info: Any
    # ) -> dict[str, SecondsSinceUnixEpoch]:
    #     return completion_map._dict
