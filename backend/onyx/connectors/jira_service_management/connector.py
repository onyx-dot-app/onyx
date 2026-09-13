from typing import Any, ClassVar

from jira.resources import Issue

from onyx.configs.app_configs import (
    INDEX_BATCH_SIZE,
    JIRA_CONNECTOR_LABELS_TO_SKIP,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.connector import (
    JiraConnector,
    _perform_jql_search,
    process_jira_issue,
)
from onyx.connectors.jira_service_management.utils import (
    JsmFieldMap,
    build_jsm_metadata,
    discover_jsm_fields,
    get_jsm_comment_strs,
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document
from onyx.utils.logger import setup_logger

logger = setup_logger()


class JiraServiceManagementConnector(JiraConnector):
    """Indexes all tickets from a specified Jira Service Management project.

    JSM is backed by the same Jira REST API as regular Jira, so this connector
    subclasses the Jira connector (checkpointed pagination, slim docs, hierarchy
    and permission sync all carry over) and specializes:

    - document source branding (``DocumentSource.JIRA_SERVICE_MANAGEMENT``)
    - comment handling: JSM internal agent notes (``jsdPublic`` comments) are
      excluded unless ``include_internal_comments`` is set, in which case they
      are tagged with an ``[Internal Note]`` prefix
    - JSM specific metadata: customer request type, organizations and SLA
      statuses, discovered by field name so no instance-specific field IDs are
      hard-coded
    - settings validation: a service desk project key is required and the
      project must be a JSM (``service_desk``) project
    """

    document_source: ClassVar[DocumentSource] = DocumentSource.JIRA_SERVICE_MANAGEMENT

    def __init__(
        self,
        jira_base_url: str,
        project_key: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        jql_query: str | None = None,
        scoped_token: bool = False,
        include_internal_comments: bool = False,
    ) -> None:
        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=jql_query,
            scoped_token=scoped_token,
        )
        self.include_internal_comments = include_internal_comments
        self._jsm_field_map: JsmFieldMap | None = None

    @property
    def jsm_field_map(self) -> JsmFieldMap:
        """JSM field IDs, discovered lazily and cached for the connector's lifetime."""
        if self._jsm_field_map is None:
            self._jsm_field_map = discover_jsm_fields(self.jira_client)
        return self._jsm_field_map

    def _process_issue(
        self,
        issue: Issue,
        parent_hierarchy_raw_node_id: str | None = None,
    ) -> Document | None:
        document = process_jira_issue(
            jira_base_url=self.jira_base,
            issue=issue,
            comment_email_blacklist=self.comment_email_blacklist,
            labels_to_skip=self.labels_to_skip,
            parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
            source=self.document_source,
            comment_extractor=lambda issue: get_jsm_comment_strs(
                issue=issue,
                comment_email_blacklist=self.comment_email_blacklist,
                include_internal_comments=self.include_internal_comments,
            ),
        )
        if document is None:
            return None

        # Enrichment is best effort: a failure to extract JSM metadata should
        # not lose the ticket itself.
        try:
            document.metadata.update(build_jsm_metadata(issue, self.jsm_field_map))
        except Exception:
            logger.exception(
                "Failed to extract JSM metadata for %s; continuing without it.",
                issue.key,
            )
        return document

    @staticmethod
    def _best_effort_project_type(project: Any) -> str | None:
        project_type = getattr(project, "projectTypeKey", None)
        if isinstance(project_type, str) and project_type:
            return project_type
        raw = getattr(project, "raw", None)
        if isinstance(raw, dict):
            raw_type = raw.get("projectTypeKey")
            if isinstance(raw_type, str) and raw_type:
                return raw_type
        return None

    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira Service Management")

        # A JSM project key is mandatory; the general-purpose Jira connector is
        # the right tool for indexing everything a credential can access.
        if not self.jira_project or not self.jira_project.strip():
            raise ConnectorValidationError(
                "A Jira Service Management project key is required."
            )

        try:
            project = self.jira_client.project(self.jira_project)
        except Exception as e:
            self._handle_jira_connector_settings_error(e)
            raise  # _handle_jira_connector_settings_error always raises

        # Enforce that the project actually is a service desk project. Only
        # checked when the project type is exposed by the instance.
        project_type = self._best_effort_project_type(project)
        if project_type is not None and project_type != "service_desk":
            raise ConnectorValidationError(
                f"Project '{self.jira_project}' is a '{project_type}' project, but "
                "the Jira Service Management connector requires a service desk "
                "project (projectTypeKey == 'service_desk'). Use the Jira "
                "connector for traditional Jira projects."
            )

        # If a custom JQL query is set, validate it's valid
        if self.jql_query:
            try:
                next(
                    iter(
                        _perform_jql_search(
                            jira_client=self.jira_client,
                            jql=self.jql_query,
                            start=0,
                            max_results=1,
                            all_issue_ids=[],
                        )
                    ),
                    None,
                )
            except Exception as e:
                self._handle_jira_connector_settings_error(e)


if __name__ == "__main__":
    import os
    from datetime import datetime

    from onyx.utils.variable_functionality import global_version
    from tests.daily.connectors.utils import load_all_from_connector

    # For connector permission testing, set EE to true.
    global_version.set_ee()

    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ["JSM_BASE_URL"],
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
