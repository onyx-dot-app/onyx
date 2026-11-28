"""JSM models.

A JSM project is served by the same Atlassian REST API as Jira, so the JSM
connector reuses Jira's page models verbatim. They are re-exported here under
the JSM namespace so the rest of the JSM connector can depend on
``onyx.connectors.jsm`` without reaching into the Jira package.
"""

from onyx.connectors.jira.models import JiraGroupMemberSample as JsmGroupMemberSample
from onyx.connectors.jira.models import JiraGroupPage as JsmGroupPage
from onyx.connectors.jira.models import JiraIssueIdPage as JsmIssueIdPage
from onyx.connectors.jira.models import JiraProjectSample as JsmProjectSample

__all__ = [
    "JsmIssueIdPage",
    "JsmGroupPage",
    "JsmGroupMemberSample",
    "JsmProjectSample",
]