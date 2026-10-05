from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
    ScopeOpaque,
)

_EMPTY_MEANS_ALL = FieldPolicy(
    FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)
)


class DiscordConnectorConfig(ConnectorConfig):
    server_ids: Annotated[list[str] | None, _EMPTY_MEANS_ALL] = None
    channel_names: Annotated[list[str] | None, _EMPTY_MEANS_ALL] = None
    # YYYY-MM-DD. Messages before it are not fetched; no descriptor compares dates.
    start_date: Annotated[
        str | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
