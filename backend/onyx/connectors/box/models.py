from enum import Enum
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import field_serializer
from pydantic import field_validator

from onyx.connectors.interfaces import ConnectorCheckpoint
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.utils.threadpool_concurrency import ThreadSafeDict


BoxFileType = dict[str, Any]


class BoxRetrievalStage(str, Enum):
    """Stages of retrieval for Box connector."""

    START = "start"
    FOLDER_FILES = "folder_files"
    DONE = "done"


class StageCompletion(BaseModel):
    """
    Tracks progress through the retrieval process for a user.

    completed_until: Timestamp of the latest file retrieved or error yielded.
    current_folder_id: Folder currently being processed (for resumption).
    next_marker: Pagination marker for resuming from a specific page.
    """

    stage: BoxRetrievalStage
    completed_until: SecondsSinceUnixEpoch
    current_folder_id: str | None = None
    next_marker: str | None = None


class RetrievedBoxFile(BaseModel):
    """
    Represents a file retrieved from Box.

    If an error occurs during retrieval, the error field is set
    and will be propagated as a ConnectorFailure.
    """

    # The stage at which this file was retrieved
    completion_stage: BoxRetrievalStage

    # The file that was retrieved
    box_file: BoxFileType

    # The ID of the user that the file was retrieved by
    user_id: str

    # The id of the parent folder of the file
    parent_id: str | None = None

    # Any unexpected error that occurred while retrieving the file.
    error: Exception | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class BoxCheckpoint(ConnectorCheckpoint):
    """Checkpoint for Box connector retrieval state."""

    retrieved_folder_ids: set[str]
    completion_stage: BoxRetrievalStage
    completion_map: ThreadSafeDict[str, StageCompletion]
    all_retrieved_file_ids: set[str] = set()
    folder_ids_to_retrieve: list[str] | None = None

    @field_serializer("completion_map")
    def serialize_completion_map(
        self, completion_map: ThreadSafeDict[str, StageCompletion], _info: Any
    ) -> dict[str, StageCompletion]:
        return completion_map._dict

    @field_validator("completion_map", mode="before")
    def validate_completion_map(cls, v: Any) -> ThreadSafeDict[str, StageCompletion]:
        assert isinstance(v, dict) or isinstance(v, ThreadSafeDict)
        return ThreadSafeDict(
            {k: StageCompletion.model_validate(val) for k, val in v.items()}
        )
