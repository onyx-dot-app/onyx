import os

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JIRA_CONNECTOR_LABELS_TO_SKIP


class JiraServiceManagementConnector(JiraConnector):
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
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
            document_source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        )


if __name__ == "__main__":
    import time
    from onyx.connectors.jira.connector import get_jira_client

    jira_base_url = os.environ.get("JIRA_BASE_URL", "")
    jira_user_email = os.environ.get("JIRA_USER_EMAIL", "")
    jira_api_token = os.environ.get("JIRA_API_TOKEN", "")

    if not jira_base_url or not jira_user_email or not jira_api_token:
        print("Please set JIRA_BASE_URL, JIRA_USER_EMAIL, and JIRA_API_TOKEN")
        exit(1)

    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
    )

    connector.load_credentials(
        {
            "jira_user_email": jira_user_email,
            "jira_api_token": jira_api_token,
        }
    )

    for doc_batch in connector.poll_source(0, time.time()):
        for doc in doc_batch:
            print(doc.semantic_identifier)
            print(doc.source)
