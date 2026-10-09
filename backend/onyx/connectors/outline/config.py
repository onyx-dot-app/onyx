from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, RealmCredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy


class OutlineCredentialBinding(RealmCredentialBinding):
    REALM_KEY = "outline_base_url"

    # Where the account works. The connector reads it from the credential.
    outline_base_url: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None


class OutlineConnectorConfig(OutlineCredentialBinding, ConnectorConfig):
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
