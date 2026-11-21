"""Connector config for Jira Service Management (DRAFT).

Mirrors the Jira connector's config shape (same credential family), with the
service-project key as the only scope field of the first version.
"""

from typing import Annotated, ClassVar

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.connectors.connector_config import (
    ConnectorConfig,
    CredentialBinding,
)
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class JiraServiceManagementCredentialBinding(CredentialBinding):
    site_url_fields: ClassVar[frozenset[str]] = frozenset({"jira_base_url"})

    # Document ids are request URLs on this base URL.
    jira_base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]


class JiraServiceManagementConnectorConfig(
    JiraServiceManagementCredentialBinding, ConnectorConfig
):
    # The JSM service project whose requests get indexed.
    project_key: Annotated[
        str,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude()),
    ]
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
    # Internal (agent-only) comments stay out of the index unless enabled.
    include_internal_comments: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = (
        False
    )
