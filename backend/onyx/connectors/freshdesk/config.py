from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import (
    ConnectorConfig,
    RealmCredentialBinding,
    normalize_realm,
)
from onyx.connectors.field_policy import FieldClass, FieldPolicy


class FreshdeskCredentialBinding(RealmCredentialBinding):
    REALM_KEY = "freshdesk_domain"

    # Where the account works. The connector reads it from the credential.
    freshdesk_domain: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None

    @classmethod
    def normalize(cls, realm: str) -> str:
        return normalize_realm(realm).removesuffix(".freshdesk.com")


class FreshdeskConnectorConfig(FreshdeskCredentialBinding, ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
