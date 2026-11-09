from enum import StrEnum
from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude
from onyx.connectors.hubspot.models import HubSpotObjectSpec


class HubSpotObjectType(StrEnum):
    TICKETS = "tickets"
    COMPANIES = "companies"
    DEALS = "deals"
    CONTACTS = "contacts"


HUBSPOT_OBJECT_SPECS: dict[HubSpotObjectType, HubSpotObjectSpec] = {
    HubSpotObjectType.TICKETS: HubSpotObjectSpec(
        type_id="0-5",
        document_noun="ticket",
        modified_date_property="hs_lastmodifieddate",
        read_scope="tickets",
    ),
    HubSpotObjectType.COMPANIES: HubSpotObjectSpec(
        type_id="0-2",
        document_noun="company",
        modified_date_property="hs_lastmodifieddate",
        read_scope="crm.objects.companies.read",
    ),
    HubSpotObjectType.DEALS: HubSpotObjectSpec(
        type_id="0-3",
        document_noun="deal",
        modified_date_property="hs_lastmodifieddate",
        read_scope="crm.objects.deals.read",
    ),
    HubSpotObjectType.CONTACTS: HubSpotObjectSpec(
        type_id="0-1",
        document_noun="contact",
        modified_date_property="lastmodifieddate",
        read_scope="crm.objects.contacts.read",
    ),
}


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
