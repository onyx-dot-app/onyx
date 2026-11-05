from typing import List
from typing import Optional

from pydantic import Field

from danswer.connectors.models import BasicConnectorConfig


class JiraServiceManagementConfig(BasicConnectorConfig):
    jira_url: str = Field(
        title="Jira URL",
        description="The base URL of your Jira instance (e.g., https://your-company.atlassian.net)",
    )
    jira_username: str = Field(
        title="Jira Username (Email)",
        description="The email address of a Jira user with access to the desired projects.",
    )
    jira_api_token: str = Field(
        title="Jira API Token",
        description="An API token generated for the Jira username. Go to https://id.atlassian.com/manage-api-tokens to create one.",
        json_schema_extra={"password": True},
    )
    project_keys: List[str] = Field(
        title="Jira Project Keys",
        description="Comma-separated list of Jira Service Management project keys (e.g., SERVICE,HELPDESK).",
        examples=[["SERVICE", "HELPDESK"]],
    )
    include_attachments: bool = Field(
        default=True,
        title="Include Attachments",
        description="If checked, file attachments from Jira tickets will be included.",
    )
    include_comments: bool = Field(
        default=True,
        title="Include Comments",
        description="If checked, comments from Jira tickets will be included.",
    )
    include_subtasks: bool = Field(
        default=False,
        title="Include Subtasks",
        description="If checked, subtasks will also be included. By default, only parent tasks are included.",
    )
    custom_jql_query: Optional[str] = Field(
        default=None,
        title="Custom JQL Query",
        description="Optional: A custom JQL query to filter tickets. If provided, this query will override the default JSM-specific filter.",
        examples=["status in ('Open', 'In Progress') AND resolution is EMPTY"],
    )
