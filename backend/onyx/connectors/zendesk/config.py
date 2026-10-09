from enum import StrEnum
from typing import Annotated

from onyx.connectors.connector_config import (
    ConnectorConfig,
    RealmCredentialBinding,
    normalize_realm,
)
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class ZendeskContentType(StrEnum):
    ARTICLES = "articles"
    TICKETS = "tickets"


class ZendeskCredentialBinding(RealmCredentialBinding):
    REALM_KEY = "zendesk_subdomain"

    # Where the account works. The connector reads it from the credential.
    zendesk_subdomain: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None

    @classmethod
    def normalize(cls, realm: str) -> str:
        return normalize_realm(realm).removesuffix(".zendesk.com")


class ZendeskConnectorConfig(ZendeskCredentialBinding, ConnectorConfig):
    # The two types are disjoint document sets, so a switch is a removal and an
    # addition.
    content_type: Annotated[
        ZendeskContentType,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False)),
    ] = ZendeskContentType.ARTICLES
    calls_per_minute: Annotated[int | None, FieldPolicy(FieldClass.COSMETIC)] = None
