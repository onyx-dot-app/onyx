"""JSM source operations.

A JSM project is served by the same Atlassian REST API as Jira, so the JSM
connector uses :class:`JiraSourceOperations` directly. This module re-exports
the gateway and its error types under the JSM namespace so the rest of the JSM
connector (and its capability checks) can depend on ``onyx.connectors.jsm``
without reaching into the Jira package.
"""

from onyx.connectors.jira.source_operations import (
    JiraApiError as JsmApiError,
)
from onyx.connectors.jira.source_operations import (
    JiraCloudIdError as JsmCloudIdError,
)
from onyx.connectors.jira.source_operations import (
    JiraSourceOperations as JsmSourceOperations,
)
from onyx.connectors.jira.source_operations import (
    JiraTimeoutError as JsmTimeoutError,
)
from onyx.connectors.jira.source_operations import (
    is_cloud_gateway as is_cloud_gateway,
)

__all__ = [
    "JsmSourceOperations",
    "JsmApiError",
    "JsmCloudIdError",
    "JsmTimeoutError",
    "is_cloud_gateway",
]