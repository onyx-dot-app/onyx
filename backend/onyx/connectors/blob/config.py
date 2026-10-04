from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import BlobType
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding


class BlobStorageCredentialBinding(CredentialBinding):
    # The connector annotates this as str and converts it with BlobType(...).
    bucket_type: BlobType
    european_residency: bool = False
    region_name: str | None = None


class BlobStorageConnectorConfig(BlobStorageCredentialBinding, ConnectorConfig):
    bucket_name: str
    prefix: str = ""
    batch_size: int = INDEX_BATCH_SIZE
