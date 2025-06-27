import logging
from typing import Optional

from jira import JIRA

from danswer.configs.danswerbot_configs import JIRA_API_TOKEN
from danswer.configs.danswerbot_configs import JIRA_EMAIL
from danswer.configs.danswerbot_configs import JIRA_SERVER_URL

logger = logging.getLogger(__name__)


def create_jira_ticket(
    title: str,
    description: str,
    slack_message_link: str,
    project_key: str,
    issue_type: str,
    component: str | None = None,
) -> Optional[str]:
    """
    Create a JIRA ticket with the given details

    Args:
        title: Title of the JIRA ticket
        description: Description of the issue
        slack_message_link: Link to the Slack message that triggered this ticket
        project_key: JIRA project key to create the ticket in
        issue_type: Type of JIRA issue (default: Task)
        component: Component to assign the ticket to (optional)

    Returns:
        str: URL of the created JIRA ticket if successful, None otherwise
    """
    try:
        # Initialize JIRA client with email and API token
        jira = JIRA(server=JIRA_SERVER_URL, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))

        # Create the issue
        issue_dict = {
            "project": {"key": project_key},
            "summary": title,
            "description": f"{description}\n\nRelated Slack Message: {slack_message_link}",
            "issuetype": {"name": issue_type},
        }

        # Only add component if specified
        if component:
            issue_dict["components"] = [{"name": component}]

        new_issue = jira.create_issue(fields=issue_dict)
        return f"{JIRA_SERVER_URL}/browse/{new_issue.key}"

    except Exception as e:
        logger.error(f"Failed to create JIRA ticket: {str(e)}")
        return None


if __name__ == "__main__":
    create_jira_ticket(
        title="Test Ticket - 3",
        description="This is a test ticket",
        slack_message_link="https://example.com/slack-message",
        project_key="ABC",
        issue_type="Task",
        component="abc",
    )
