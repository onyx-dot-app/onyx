from typing import Annotated
from pydantic import field_validator

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class ShortcutConnectorConfig(ConnectorConfig):
    project_ids: Annotated[
        list[int] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    epic_ids: Annotated[
        list[int] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE

    @field_validator("batch_size")
    @classmethod
    def _validate_batch_size(cls, value: int) -> int:
        if value < 1 or value > 100:
            raise ValueError("batch_size must be between 1 and 100")
        return value
