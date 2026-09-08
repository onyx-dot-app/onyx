"""Jira Service Management (JSM) connector.

JSM runs on top of the same Jira Cloud/Data Center REST API as regular Jira, so
this connector reuses all of the fetching, parsing, checkpointing and
permission-sync logic in :class:`~onyx.connectors.jira.connector.JiraConnector`.

Only two things differ from a plain Jira connector:

1. Indexed tickets are stamped with ``DocumentSource.JIRA_SERVICE_MANAGEMENT`` so
   they are attributed to the correct source in the UI and search filters.
2. When the admin does not pin a specific project or supply a custom JQL query,
   indexing is automatically scoped to *service desk* projects
   (``projectTypeKey == "service_desk"``) instead of every project the
   credentials can see. This keeps a JSM connector from silently pulling in
   ordinary software/business Jira projects.
"""

from typing import Any

from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Atlassian's project type key for Jira Service Management projects.
# https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-projects/
_SERVICE_DESK_PROJECT_TYPE_KEY = "service_desk"


class JiraServiceManagementConnector(JiraConnector):
    """A Jira connector scoped to Jira Service Management projects.

    Accepts exactly the same configuration as :class:`JiraConnector`
    (``jira_base_url``, optional ``project_key``, optional ``jql_query``, etc.),
    so no additional factory or credential wiring is required beyond registering
    the class for ``DocumentSource.JIRA_SERVICE_MANAGEMENT``.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Cache the discovered service desk project keys so we do not re-list
        # projects on every poll window.
        self._service_desk_project_keys: list[str] | None = None

    @property
    @override
    def document_source(self) -> DocumentSource:
        return DocumentSource.JIRA_SERVICE_MANAGEMENT

    def _get_service_desk_project_keys(self) -> list[str]:
        """Return the keys of all service desk projects the credentials can see.

        The result is cached for the lifetime of the connector instance.
        """
        if self._service_desk_project_keys is not None:
            return self._service_desk_project_keys

        service_desk_keys: list[str] = []
        for project in self.jira_client.projects():
            project_type = getattr(project, "projectTypeKey", None)
            if project_type == _SERVICE_DESK_PROJECT_TYPE_KEY:
                service_desk_keys.append(project.key)

        self._service_desk_project_keys = service_desk_keys
        logger.info(
            "Discovered %d Jira Service Management project(s): %s",
            len(service_desk_keys),
            service_desk_keys,
        )
        return service_desk_keys

    @override
    def _get_jql_query(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> str:
        """JQL for the configured scope plus the poll window.

        Mirrors :meth:`JiraConnector._get_jql_query` (same unquoted epoch-ms time
        bounds) but, when neither an explicit project key nor a custom JQL query
        is configured, restricts results to service desk projects rather than
        every accessible project.
        """
        time_jql = f"updated >= {int(start * 1000)} AND updated <= {int(end * 1000)}"

        # An explicit custom JQL query is the admin's responsibility - honor it
        # exactly as the base connector does.
        if self.jql_query:
            return f"({self.jql_query}) AND {time_jql}"

        # An explicit project key wins over auto-discovery so admins can point a
        # JSM connector at a single service desk project.
        if self.jira_project:
            base_jql = f"project = {self.quoted_jira_project}"
            return f"{base_jql} AND {time_jql}"

        # Otherwise auto-scope to every service desk project we can see.
        service_desk_keys = self._get_service_desk_project_keys()
        if not service_desk_keys:
            raise ConnectorValidationError(
                "No Jira Service Management (service desk) projects were found for "
                "the provided credentials. Ensure the account has access to at "
                "least one service desk project, or configure a specific project "
                "key or JQL query."
            )

        quoted_keys = ", ".join(f'"{key}"' for key in service_desk_keys)
        return f"project in ({quoted_keys}) AND {time_jql}"


if __name__ == "__main__":
    import os
    import time

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )

    current = time.time()
    one_day_ago = current - 24 * 60 * 60
    checkpoint = connector.build_dummy_checkpoint()
    gen = connector.load_from_checkpoint(one_day_ago, current, checkpoint)
    for doc_or_failure in gen:
        print(doc_or_failure)
