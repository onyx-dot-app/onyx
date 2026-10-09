from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding


class ZulipCredentialBinding(CredentialBinding):
    realm_name: str
    realm_url: str


class ZulipConnectorConfig(ZulipCredentialBinding, ConnectorConfig):
    batch_size: int = INDEX_BATCH_SIZE
