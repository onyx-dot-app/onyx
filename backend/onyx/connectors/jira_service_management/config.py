import re
from typing import Annotated, ClassVar

from pydantic import field_validator

from onyx.connectors.connector_config import (
    ConnectorConfig,
    CredentialBinding,
    field_format_error,
)
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeInclude

# A Jira project key is 2 to 10 characters, starts with a letter, and has no
# spaces. Quoting it in JQL is then safe.
_PROJECT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,9}$")


class JiraServiceManagementCredentialBinding(CredentialBinding):
    site_url_fields: ClassVar[frozenset[str]] = frozenset({"jira_base_url"})

    # Document ids are request URLs on this site. A change reindexes.
    jira_base_url: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]


class JiraServiceManagementConnectorConfig(
    JiraServiceManagementCredentialBinding, ConnectorConfig
):
    # The service project. One connector indexes one service desk.
    project_key: Annotated[
        str,
        FieldPolicy(FieldClass.SCOPE, scope=ScopeInclude(empty_means_all=False)),
    ]
    # Agent-only comments are part of the request text when this is on.
    # Turning it off removes them on the next full index.
    include_internal_comments: Annotated[bool, FieldPolicy(FieldClass.BEHAVIOR)] = True

    @field_validator("project_key")
    @classmethod
    def _normalize_project_key(cls, value: str) -> str:
        key = value.strip().upper()
        if _PROJECT_KEY.fullmatch(key) is None:
            raise field_format_error(
                "Enter a Jira project key, such as IT. Use letters and digits only."
            )
        return key
