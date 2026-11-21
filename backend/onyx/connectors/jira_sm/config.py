from typing import Annotated, ClassVar

from onyx.connectors.connector_config import (
    ConnectorConfig,
    CredentialBinding,
)
from onyx.connectors.field_policy import (
    FieldClass,
    FieldPolicy,
    ScopeInclude,
    ScopeOpaque,
)

_PROJECT_KEY = "project_key"
_JQL_QUERY = "jql_query"


class JiraSmCredentialBinding(CredentialBinding):
    site_url_fields: ClassVar[frozenset[str]] = frozenset({"jira_base_url"})

    jira_base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    scoped_token: Annotated[bool, FieldPolicy(FieldClass.COSMETIC)] = False


class JiraSmConnectorConfig(JiraSmCredentialBinding, ConnectorConfig):
    """Configuration for the Jira Service Management connector.

    Pulls all tickets from a specified JSM project. Uses the same
    Atlassian authentication as the standard Jira connector, but
    scopes queries to service-desk (JSM) projects by default.
    """

    project_key: Annotated[
        str | None,
        FieldPolicy(
            FieldClass.SCOPE,
            scope=ScopeInclude(empty_means_all=True),
            depends_on=(_JQL_QUERY,),
        ),
    ] = None
    jql_query: Annotated[
        str | None,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque()),
    ] = None
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = 100
    include_attachments: Annotated[bool, FieldPolicy(FieldClass.COSMETIC)] = False
