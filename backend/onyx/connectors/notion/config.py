from typing import Annotated

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP,
)
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
    ScopeToggle,
)


class NotionConnectorConfig(ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    # Also follows child pages that search does not return.
    recursive_index_enabled: Annotated[
        bool, FieldPolicy(FieldClass.SCOPE, scope=ScopeToggle(widens_when=True))
    ] = not NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP
    # Empty indexes every page that search returns.
    root_page_id: Annotated[
        str | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
