"""Connector for Jira Service Management (JSM) projects.

JSM is built on Jira's data model — JSM "requests" are stored as Jira issues
with a specific set of issue types (Service Request, Incident, Problem, Change,
etc.). The underlying REST API for fetching them is the same Jira REST API
used by the standard Jira connector, so this connector reuses
`JiraConnector` and adds two things on top:

  1. A default JQL filter scoped to JSM issue types. Users can override this
     by setting `jsm_issue_types` or by providing their own `jql_query` (which
     replaces the default filter entirely).
  2. A document `source` tag of `JIRA_SERVICE_MANAGEMENT` instead of `JIRA`,
     so JSM tickets show up distinctly in Onyx.

Authentication and credential handling are identical to the standard Jira
connector — JSM is part of the same Atlassian Cloud tenant and uses the same
API tokens / scoped tokens.
"""

from jira.resources import Issue
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.models import Document
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Default JSM issue types. Covers the standard out-of-the-box JSM ticket
# types — projects with custom issue types can override via `jsm_issue_types`
# or supply their own `jql_query`.
DEFAULT_JSM_ISSUE_TYPES: tuple[str, ...] = (
    "Service Request",
    "Service Request with Approvals",
    "Incident",
    "Problem",
    "Change",
    "Emergency Change",
    "Task",
)


def _build_jsm_issue_type_clause(issue_types: tuple[str, ...]) -> str:
    """Build a JQL `issuetype IN (...)` clause from a tuple of type names.

    Returns an empty string if `issue_types` is empty — caller is expected to
    fall back to whatever filter the user explicitly provided.
    """
    if not issue_types:
        return ""
    quoted = ", ".join(f'"{t}"' for t in issue_types)
    return f"issuetype in ({quoted})"


def process_jsm_issue(
    jira_base_url: str,
    issue: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
    parent_hierarchy_raw_node_id: str | None = None,
) -> Document | None:
    """Convert a JSM issue into an Onyx Document.

    This is a thin wrapper around `process_jira_issue` that re-tags the result
    with the `JIRA_SERVICE_MANAGEMENT` source. We re-build the Document rather
    than mutating in place because `Document` is a frozen pydantic model in
    most code paths.
    """
    base_doc = process_jira_issue(
        jira_base_url=jira_base_url,
        issue=issue,
        comment_email_blacklist=comment_email_blacklist,
        labels_to_skip=labels_to_skip,
        parent_hierarchy_raw_node_id=parent_hierarchy_raw_node_id,
    )
    if base_doc is None:
        return None
    # Rebuild with the JSM source. `Document` is a pydantic model; using
    # `model_copy(update=...)` preserves immutability semantics for callers
    # that rely on it.
    return base_doc.model_copy(update={"source": DocumentSource.JIRA_SERVICE_MANAGEMENT})


class JsmConnector(JiraConnector):
    """Jira Service Management connector.

    Subclass of `JiraConnector` that scopes the JQL search to JSM issue types
    by default and tags resulting documents with `JIRA_SERVICE_MANAGEMENT`.
    """

    def __init__(
        self,
        jira_base_url: str,
        project_key: str | None = None,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
        # If `jql_query` is provided, it is used verbatim and the JSM issue-type
        # filter is NOT auto-injected. Users with custom workflows should set
        # both `jql_query` and (if needed) include the issuetype clause there.
        jql_query: str | None = None,
        # Override which JSM issue types are pulled. Defaults to the standard
        # out-of-the-box JSM types. Pass an empty tuple to disable the filter
        # entirely (equivalent to using the regular Jira connector).
        jsm_issue_types: tuple[str, ...] | None = None,
        scoped_token: bool = False,
    ) -> None:
        # Determine the JQL we'll pass to the underlying Jira connector.
        # When the user provides an explicit `jql_query`, honor it as-is and
        # do not auto-inject the issuetype filter — they've taken control.
        effective_issue_types = (
            jsm_issue_types if jsm_issue_types is not None else DEFAULT_JSM_ISSUE_TYPES
        )
        effective_jql: str | None
        if jql_query is not None:
            effective_jql = jql_query
        else:
            type_clause = _build_jsm_issue_type_clause(effective_issue_types)
            effective_jql = type_clause if type_clause else None

        self.jsm_issue_types = effective_issue_types

        super().__init__(
            jira_base_url=jira_base_url,
            project_key=project_key,
            comment_email_blacklist=comment_email_blacklist,
            batch_size=batch_size,
            labels_to_skip=labels_to_skip,
            jql_query=effective_jql,
            scoped_token=scoped_token,
        )

    @override
    def _load_from_checkpoint(
        self,
        jql: str,
        checkpoint: JiraConnectorCheckpoint,
        include_permissions: bool,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        """Delegate to JiraConnector's load logic, then re-tag each Document's
        source as JIRA_SERVICE_MANAGEMENT.

        We wrap the parent generator rather than reimplementing the checkpoint
        machinery — the checkpoint shape, JQL search, bulk fetch, and error
        handling are all identical to the regular Jira connector. Only the
        document `source` tag differs.

        Signature exactly mirrors `JiraConnector._load_from_checkpoint`:
        `(jql, checkpoint, include_permissions)`. The public entry points
        (`load_from_checkpoint`, `load_from_checkpoint_with_perm_sync`) build
        the JQL via `_get_jql_query(start, end)` and dispatch here.
        """
        for item in super()._load_from_checkpoint(
            jql=jql,
            checkpoint=checkpoint,
            include_permissions=include_permissions,
        ):
            if isinstance(item, Document):
                yield item.model_copy(
                    update={"source": DocumentSource.JIRA_SERVICE_MANAGEMENT}
                )
            else:
                yield item

    def validate_connector_settings(self) -> None:
        """Reuse parent validation. JSM uses the same auth + project setup."""
        return super().validate_connector_settings()
