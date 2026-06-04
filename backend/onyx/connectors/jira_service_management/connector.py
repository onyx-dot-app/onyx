"""
Jira Service Management (JSM) Connector.

JSM uses the same Atlassian REST API surface as Jira Software, but tickets
(called "requests" or "issues") live in Service Desk projects.  We reuse the
entire Jira connector implementation and simply restrict indexing to projects
whose type is "service_desk" — identified by the presence of the project in
the Service Desk API response (``/rest/servicedeskapi/servicedesk``).

For the actual document loading we delegate to :class:`JiraConnector` after
setting a JQL query that is scoped to the configured JSM project key.
"""

from typing import Any

from jira import JIRA
from requests import HTTPError
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import CheckpointedConnectorWithPermSync
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira.utils import build_jira_client
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

# JSM-specific API path (Atlassian Service Desk REST API)
_JSM_SERVICEDESK_API_PATH = "rest/servicedeskapi/servicedesk"
# JSM issue type filter — only index request types (not every Jira issue type)
# We filter via JQL using the project key; JSM exposes all ticket types via
# the standard Jira search API so no additional type filtering is required.


def _get_jsm_project_keys(jira_client: JIRA) -> list[str]:
    """
    Query the JSM Service Desk API to get all service desk project keys.

    Follows pagination via the ``isLastPage`` flag so all service desks are
    returned even when there are more than 100.

    Returns a list of project keys for all accessible service desk projects.
    Falls back to an empty list if the JSM API is not available on this
    instance (e.g. Jira Server without the JSM add-on).

    Raises:
        HTTPError: Re-raised when the server responds with a 401 or 403 so
            that the caller does NOT silently skip credential/permission
            validation.
    """
    try:
        base_url = jira_client.server_url.rstrip("/")
        api_url = f"{base_url}/{_JSM_SERVICEDESK_API_PATH}"

        all_keys: list[str] = []
        start = 0
        limit = 100

        while True:
            response = jira_client._session.get(  # ty: ignore[unresolved-attribute]
                api_url,
                params={"limit": limit, "start": start},
            )
            # Auth / permission errors must NOT be swallowed — let them surface
            # so that validate_connector_settings actually validates.
            if response.status_code in (401, 403):
                response.raise_for_status()

            response.raise_for_status()
            data = response.json()
            values = data.get("values", [])
            all_keys.extend(sd["projectKey"] for sd in values if "projectKey" in sd)

            if data.get("isLastPage", True):
                break
            start += limit

        return all_keys
    except HTTPError:
        # Re-raise auth/permission errors so the caller knows validation failed.
        raise
    except Exception as e:
        logger.warning(
            "Failed to fetch JSM service desk projects via Service Desk API: %s. "
            "Proceeding without JSM-specific project validation.",
            e,
        )
        return []


class JiraServiceManagementConnector(
    CheckpointedConnectorWithPermSync[JiraConnectorCheckpoint],
    SlimConnectorWithPermSync,
):
    """
    Connector for Jira Service Management (JSM) projects.

    Indexes all tickets from a given JSM service desk project.  Authentication
    uses the same credentials as the Jira connector (email + API token for
    Atlassian Cloud, or API token for Jira Server/DC).

    The connector verifies that the configured project is a service desk project
    by calling the JSM-specific ``/rest/servicedeskapi/servicedesk`` endpoint
    during validation.
    """

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
    ) -> None:
        self.jira_base = jira_base_url.rstrip("/")
        self.project_key = project_key
        self._comment_email_blacklist = comment_email_blacklist or []
        self.labels_to_skip = set(labels_to_skip)
        self.batch_size = batch_size
        self._jira_client: JIRA | None = None
        # Delegate to JiraConnector internally; we configure it once credentials
        # are loaded so we can share all of the heavy-lifting logic.
        self._jira_connector: JiraConnector | None = None

    # ------------------------------------------------------------------
    # Credential loading
    # ------------------------------------------------------------------

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self._jira_client = build_jira_client(
            credentials=credentials,
            jira_base=self.jira_base,
        )
        # Build the inner JiraConnector and inject the same authenticated client.
        # Pass JIRA_SERVICE_MANAGEMENT as the document source so that all
        # indexed documents are correctly tagged and filterable separately from
        # plain Jira tickets.
        self._jira_connector = JiraConnector(
            jira_base_url=self.jira_base,
            project_key=self.project_key,
            comment_email_blacklist=self._comment_email_blacklist,
            batch_size=self.batch_size,
            labels_to_skip=list(self.labels_to_skip),
            document_source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
        )
        self._jira_connector._jira_client = self._jira_client
        return None

    # ------------------------------------------------------------------
    # Internal helper: delegate everything to JiraConnector
    # ------------------------------------------------------------------

    @property
    def _connector(self) -> JiraConnector:
        if self._jira_connector is None:
            raise ConnectorMissingCredentialError("Jira Service Management")
        return self._jira_connector

    # ------------------------------------------------------------------
    # CheckpointedConnectorWithPermSync interface
    # ------------------------------------------------------------------

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        return self._connector.load_from_checkpoint(start, end, checkpoint)

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        return self._connector.load_from_checkpoint_with_perm_sync(
            start, end, checkpoint
        )

    # ------------------------------------------------------------------
    # SlimConnectorWithPermSync interface
    # ------------------------------------------------------------------

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._connector.retrieve_all_slim_docs_perm_sync(
            start=start,
            end=end,
            callback=callback,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        # Verify the project is a service desk project
        jsm_project_keys = _get_jsm_project_keys(self._jira_client)
        if jsm_project_keys and self.project_key not in jsm_project_keys:
            raise ConnectorValidationError(
                f"Project '{self.project_key}' is not a Jira Service Management "
                f"(Service Desk) project, or you do not have access to it. "
                f"Available service desk projects: {', '.join(jsm_project_keys)}"
            )

        # Validate via the inner connector as well (checks project access + credentials)
        self._connector.validate_connector_settings()

    # ------------------------------------------------------------------
    # Checkpoint helpers
    # ------------------------------------------------------------------

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> JiraConnectorCheckpoint:
        return JiraConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> JiraConnectorCheckpoint:
        return JiraConnectorCheckpoint(has_more=True)


if __name__ == "__main__":
    import os
    from datetime import datetime

    from onyx.utils.variable_functionality import global_version
    from tests.daily.connectors.utils import load_all_from_connector

    global_version.set_ee()

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JIRA_BASE_URL"],
        project_key=os.environ["JSM_PROJECT_KEY"],
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

    for doc in load_all_from_connector(
        connector=connector,
        start=start,
        end=end,
    ).documents:
        print(doc)
