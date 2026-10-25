from typing import Annotated, ClassVar
from pydantic import field_validator

from onyx.connectors.connector_config import (
    ConnectorConfig,
    CredentialBinding,
)
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
)


class JiraServiceManagementCredentialBinding(CredentialBinding):
    site_url_fields: ClassVar[frozenset[str]] = frozenset({"jira_base_url"})

    # The base URL of the Jira instance (e.g. https://company.atlassian.net)
    jira_base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]

    @field_validator("jira_base_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

class JiraServiceManagementConnectorConfig(
    JiraServiceManagementCredentialBinding, ConnectorConfig
):
    # Optional project key to scope tickets (e.g. "IT", "HELP", "SUPPORT")
    project_key: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
        ),
    ] = None

    # Optional service desk ID
    service_desk_id: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
        ),
    ] = None

    # Whether to include internal agent notes alongside public customer comments
    include_internal_comments: Annotated[
        bool,
        FieldPolicy(FieldClass.BEHAVIOR),
    ] = True

    # Batch size for indexing requests
    batch_size: Annotated[
        int,
        FieldPolicy(FieldClass.COSMETIC),
    ] = 50
