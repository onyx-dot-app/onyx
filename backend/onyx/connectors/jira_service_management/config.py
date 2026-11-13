"""Typed configuration model for the Jira Service Management connector."""

from typing import Annotated

from onyx.connectors.connector_config import (
    BaseUrlCredentialBinding,
    ConnectorConfig,
)
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude


class JiraServiceManagementConnectorConfig(
    BaseUrlCredentialBinding,
    ConnectorConfig,
):
    """Typed shape of Jira Service Management ``connector_specific_config``."""

    project_key: Annotated[
        str,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=False),
            depends_on=("service_desk_id",),
        ),
    ] = ""
    service_desk_id: Annotated[
        str,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=False),
            depends_on=("project_key",),
        ),
    ] = ""
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = 50
    include_comments: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = True
