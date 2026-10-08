from enum import StrEnum
from typing import Any

from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class ClickupConnectorType(StrEnum):
    LIST = "list"
    FOLDER = "folder"
    SPACE = "space"
    WORKSPACE = "workspace"


class ClickupConnectorConfig(ConnectorConfig):
    COMMA_SEPARATED_FIELDS = frozenset({"connector_ids"})

    batch_size: int = INDEX_BATCH_SIZE
    connector_type: ClickupConnectorType | None = None
    connector_ids: list[str] | None = None
    retrieve_task_comments: bool = True

    # The constructor treats "" like None (a workspace connector).
    @field_validator("connector_type", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return None if value == "" else value
