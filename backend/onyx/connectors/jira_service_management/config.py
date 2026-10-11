from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy


class JiraServiceManagementCredentialBinding(CredentialBinding):
    # Document ids are built from issue keys on this base URL.
    jira_base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]


class JiraServiceManagementConnectorConfig(
    JiraServiceManagementCredentialBinding, ConnectorConfig
):
    # The Jira Service Management project key whose requests get indexed.
    # Document ids contain the project's issue keys.
    project_name: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
