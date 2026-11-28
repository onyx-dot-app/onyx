from enum import StrEnum
from typing import Annotated

from onyx.connectors.connector_config import ConnectorConfig
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class ZendeskContentType(StrEnum):
    ARTICLES = "articles"
    TICKETS = "tickets"


class ZendeskConnectorConfig(ConnectorConfig):
    # The two types are disjoint document sets, so a switch is a removal and an
    # addition.
    content_type: Annotated[
        ZendeskContentType,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False)),
    ] = ZendeskContentType.ARTICLES
    calls_per_minute: Annotated[int | None, FieldPolicy(FieldClass.COSMETIC)] = None
    # With permission sync, also grant end users (requesters, CCs, members of
    # an organization that shares tickets) the tickets without internal notes.
    # Finding those reads every such ticket's comments on each sync.
    grant_end_users: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = False
