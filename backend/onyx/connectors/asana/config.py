from onyx.configs.app_configs import CONTINUE_ON_CONNECTOR_FAILURE, INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig


class AsanaConnectorConfig(ConnectorConfig):
    asana_workspace_id: str
    asana_project_ids: str | None = None
    asana_team_id: str | None = None
    batch_size: int = INDEX_BATCH_SIZE
    continue_on_failure: bool = CONTINUE_ON_CONNECTOR_FAILURE
