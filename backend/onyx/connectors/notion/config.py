from typing import Annotated

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    NOTION_CONNECTOR_DISABLE_RECURSIVE_PAGE_LOOKUP,
)
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeInclude,
    ScopeToggle,
)
from onyx.connectors.planning_rule import ConnectorChangeOverride

_RECURSIVE_INDEX_ENABLED = "recursive_index_enabled"


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


def notion_planning_rule(
    old: NotionConnectorConfig, new: NotionConnectorConfig
) -> ConnectorChangeOverride | None:
    # The connector always follows child pages from a root page.
    if old.root_page_id and new.root_page_id:
        return ConnectorChangeOverride(
            scope_directions={_RECURSIVE_INDEX_ENABLED: ScopeDirection.NONE}
        )
    return None
