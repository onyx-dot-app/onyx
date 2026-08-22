"""Jira Service Management Connector.

This connector is a wrapper around the Jira connector that is specifically
designed for Jira Service Management projects. Jira Service Management uses
the same Jira REST API as Jira Software, but focuses on service desk/ITSM
use cases.

The connector inherits all functionality from the JiraConnector and can
index tickets, requests, incidents, and other issues from JSM projects.
"""

from typing import Any

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    """Connector for Jira Service Management.

    This connector extends the JiraConnector to work with Jira Service Management
    projects. JSM uses the same REST API as regular Jira, so all functionality
    is inherited from the base Jira connector.

    JSM-specific features like SLAs, request types, and customer portals are
    accessible through the standard Jira issue fields.
    """

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
    ) -> None:
        """Initialize the Jira Service Management connector.

        Args:
            jira_base_url: Base URL of the Jira Service Management instance
                (e.g., https://your-domain.atlassian.net)
            project_key: Optional project key to filter issues to a specific JSM project
            comment_email_blacklist: Optional list of email addresses whose comments
                should not be indexed (useful for filtering bot comments)
            batch_size: Number of issues to process in each batch
            labels_to_skip: List of labels - issues with these labels will be skipped
            jql_query: Optional custom JQL query to filter issues. Note: do not
                include time-based filters as they conflict with the connector's
                polling logic
            scoped_token: Whether to use scoped tokens for authentication
        """
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )


if __name__ == "__main__":
    import time

    # Example usage for testing
    connector = JiraServiceManagementConnector(
        jira_base_url="https://your-domain.atlassian.net",
        project_key="SERVICEDESK",
    )
    connector.load_credentials(
        {
            "jira_user_email": "user@example.com",
            "jira_api_token": "your_api_token",
        }
    )

    # Load all documents
    print("Loading all documents...")
    doc_batch_generator = connector.load_from_checkpoint(
        start=0,
        end=time.time(),
        checkpoint=connector.build_dummy_checkpoint(),
    )

    try:
        for doc_batch in doc_batch_generator:
            print(f"Got document or hierarchy node: {doc_batch}")
    except StopIteration as e:
        checkpoint = e.value
        print(f"Final checkpoint: {checkpoint}")
