from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, RealmCredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class HighspotCredentialBinding(RealmCredentialBinding):
    REALM_KEY = "highspot_url"
    DEFAULT_REALM = "https://api-su2.highspot.com/v1.0/"

    # Where the account works. The connector reads it from the credential.
    highspot_url: Annotated[str | None, FieldPolicy(FieldClass.COSMETIC)] = None


class HighspotConnectorConfig(HighspotCredentialBinding, ConnectorConfig):
    spot_names: Annotated[
        list[str] | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=True)),
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
