from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeDirection,
    ScopeInclude,
    ScopeOpaque,
)
from onyx.connectors.planning_rule import ConnectorChangeOverride
from onyx.connectors.salesforce.utils import resolve_parent_object_types

_REQUESTED_OBJECTS = "requested_objects"


class SalesforceConnectorConfig(ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    requested_objects: Annotated[
        list[str] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=False),
            depends_on=("custom_query_config",),
        ),
    ] = None
    # JSON that sets the object types and the fields of each document, so a
    # change can both change scope and rewrite documents.
    custom_query_config: Annotated[
        str | None, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())
    ] = None


def salesforce_planning_rule(
    old: SalesforceConnectorConfig, new: SalesforceConnectorConfig
) -> ConnectorChangeOverride | None:
    if old.custom_query_config and new.custom_query_config:
        # The connector ignores requested_objects while a custom query is set.
        return ConnectorChangeOverride(
            scope_directions={_REQUESTED_OBJECTS: ScopeDirection.NONE}
        )
    if old.custom_query_config or new.custom_query_config:
        return None
    # An empty list means the default types, and the connector
    # normalizes the case of each type.
    old_types = set(resolve_parent_object_types(old.requested_objects))
    new_types = set(resolve_parent_object_types(new.requested_objects))
    widens = bool(new_types - old_types)
    narrows = bool(old_types - new_types)
    if widens and narrows:
        direction = ScopeDirection.BOTH
    elif widens:
        direction = ScopeDirection.WIDEN
    elif narrows:
        direction = ScopeDirection.NARROW
    else:
        direction = ScopeDirection.NONE
    return ConnectorChangeOverride(scope_directions={_REQUESTED_OBJECTS: direction})
