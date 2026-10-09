from typing import Any

from pydantic import BaseModel, ConfigDict

from onyx.connectors.planning_rule import PlanningData
from onyx.file_store.models import StoredFileFacts


class FilePlanningData(PlanningData):
    # By file id. A file without a record gives no document and is absent.
    files: dict[str, StoredFileFacts]
    # Metadata entries by file name, as indexing reads them.
    old_metadata: dict[str, Any]
    new_metadata: dict[str, Any]


class FileDocument(BaseModel):
    """The document one stored file gives under one config."""

    model_config = ConfigDict(frozen=True)

    file_id: str
    document_id: str
    facts: StoredFileFacts
    metadata_entry: dict[str, Any]
