from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import (
    ConnectorConfig,
    RealmCredentialBinding,
    normalize_realm,
)
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class EgnyteCredentialBinding(RealmCredentialBinding):
    REALM_KEY = "domain"

    # Where the account works. The connector reads it from the credential.
    domain: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None

    @classmethod
    def normalize(cls, realm: str) -> str:
        return normalize_realm(realm).removesuffix(".egnyte.com")


class EgnyteConnectorConfig(EgnyteCredentialBinding, ConnectorConfig):
    # Empty indexes from the root folder.
    folder_path: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True, split_on_commas=False),
        ),
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
