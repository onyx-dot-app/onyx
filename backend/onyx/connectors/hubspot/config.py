from enum import StrEnum
from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class HubSpotObjectType(StrEnum):
    TICKETS = "tickets"
    COMPANIES = "companies"
    DEALS = "deals"
    CONTACTS = "contacts"


class HubSpotConnectorConfig(ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    # None fetches every type. [] fetches none, but the form cannot send it.
    object_types: Annotated[
        list[HubSpotObjectType] | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True, empty_list_means_none=True),
        ),
    ] = None
