from onyx.configs.app_configs import (
    GITLAB_CONNECTOR_INCLUDE_CODE_FILES,
    INDEX_BATCH_SIZE,
)
from onyx.connectors.connector_config import ConnectorConfig


class GitlabConnectorConfig(ConnectorConfig):
    project_owner: str
    project_name: str
    batch_size: int = INDEX_BATCH_SIZE
    state_filter: str = "all"
    include_mrs: bool = True
    include_issues: bool = True
    include_code_files: bool = GITLAB_CONNECTOR_INCLUDE_CODE_FILES
