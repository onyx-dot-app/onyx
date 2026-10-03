from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class LocalFileConnectorConfig(ConnectorConfig):
    # The connector also accepts Path entries, but stored JSON only holds str.
    file_locations: list[str]
    file_names: list[str] | None = None
    zip_metadata_file_id: str | None = None
    # Deprecated inline metadata: arbitrary JSON keyed by file name.
    zip_metadata: dict[str, Any] | None = None
    batch_size: int = INDEX_BATCH_SIZE
