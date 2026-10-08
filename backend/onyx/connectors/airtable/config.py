from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class AirtableConnectorConfig(ConnectorConfig):
    base_id: str = ""
    table_name_or_id: str = ""
    airtable_url: str = ""
    treat_all_non_attachment_fields_as_metadata: bool = False
    view_id: str | None = None
    share_id: str | None = None
    batch_size: int = INDEX_BATCH_SIZE
