from enum import StrEnum
from typing import Annotated, Any

from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
    ScopeOpaque,
)


class ClickupDocsConnectorType(StrEnum):
    DOC = "doc"
    LIST = "list"
    FOLDER = "folder"
    SPACE = "space"
    WORKSPACE = "workspace"


class ClickupDocsConnectorConfig(ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    # Picks the kind of object that connector_ids names.
    connector_type: Annotated[
        ClickupDocsConnectorType | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque()),
    ] = None
    # Only a workspace connector may leave this empty; it then fetches every Doc.
    connector_ids: Annotated[
        list[str] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=("connector_type",),
        ),
    ] = None

    # The constructor treats "" like None (a workspace connector).
    @field_validator("connector_type", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        return None if value == "" else value
