from datetime import datetime
from typing import ClassVar

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector


class JiraServiceManagementConnector(JiraConnector):
    """Indexes Jira Service Management requests under their own source.

    A JSM request is a Jira issue raised through a service desk, so the whole
    Jira pipeline (checkpointing, Cloud/DC search, permission sync, slim
    retrieval) applies unchanged; only the ``DocumentSource`` differs. Going
    through the JQL search APIs also avoids the limitations of the customer
    portal API (``/rest/servicedeskapi``), which pages requests one call at a
    time and only lists the requests the calling user participated in unless
    the account holds a JSM license.
    """

    jira_source: ClassVar[DocumentSource] = DocumentSource.JIRA_SERVICE_MANAGEMENT


if __name__ == "__main__":
    import os

    from onyx.utils.variable_functionality import global_version
    from tests.daily.connectors.utils import load_all_from_connector

    # For connector permission testing, set EE to true.
    global_version.set_ee()

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        project_key=os.environ.get("JIRA_PROJECT_KEY"),
        comment_email_blacklist=[],
    )

    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )

    start = 0
    end = datetime.now().timestamp()

    for slim_doc in connector.retrieve_all_slim_docs_perm_sync(
        start=start,
        end=end,
    ):
        print(slim_doc)

    for doc in load_all_from_connector(
        connector=connector,
        start=start,
        end=end,
    ).documents:
        print(doc)
