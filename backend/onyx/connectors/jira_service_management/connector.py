"""Jira Service Management connector.

Closes #2281: "Pull in all tickets from a specified Jira Service Management
project."

Design note: JSM projects are still regular Jira projects under the hood
(project type "service_desk") and JSM tickets are still regular Jira issues,
queryable via the same JQL search JiraConnector already uses. Two prior
attempts at this issue (PR #7877, PR #5392, both since closed) appear to
have reimplemented issue fetching, checkpointing, and permission sync from
scratch. That duplicates ~1,000 lines of already-tested logic and doubles
the surface area a maintainer has to trust.

Instead, this connector subclasses JiraConnector directly and changes only
what's actually JSM-specific:

1. `validate_connector_settings` additionally confirms the configured
   project's `projectTypeKey` really is "service_desk" — so pointing this
   connector at a plain Jira project fails fast with a clear message,
   rather than silently indexing the wrong thing. When a project is
   configured, this fully replaces (rather than calls alongside) the
   parent's own project-existence check: both checks need the same
   `jira_client.project(...)` call, so doing it once covers both instead
   of hitting the Jira API twice on every validation.
2. Documents are re-tagged with `DocumentSource.JIRA_SERVICE_MANAGEMENT`
   instead of `DocumentSource.JIRA`, so JSM content is distinguishable in
   search results and admin UI.

`process_jira_issue` (which hardcodes `source=DocumentSource.JIRA`) is a
module-level function in jira/connector.py, not a method, so it can't be
overridden by subclassing. Rather than patch that shared, already-tested
function, `load_from_checkpoint(_with_perm_sync)` here wrap the parent
generator and re-tag each yielded `Document` in place — zero changes to
the existing Jira connector, so this PR can't regress it.

`retrieve_all_slim_docs(_perm_sync)` need no override: `SlimDocument` has
no `source` field, so the parent implementation is correct unchanged.
"""

from typing import cast

from typing_extensions import override

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import CheckpointOutput, SecondsSinceUnixEpoch
from onyx.connectors.jira.connector import JiraConnector, JiraConnectorCheckpoint
from onyx.connectors.models import (
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SERVICE_DESK_PROJECT_TYPE = "service_desk"

_YieldItem = Document | HierarchyNode | ConnectorFailure


class JiraServiceManagementConnector(JiraConnector):
    """Pulls tickets from a specified Jira Service Management project.

    Same constructor, credentials, and JQL-based fetching as JiraConnector
    (see its __init__ for full parameter docs) — this class only overrides
    project-type validation and document source tagging.
    """

    @override
    def validate_connector_settings(self) -> None:
        if self._jira_client is None:
            raise ConnectorMissingCredentialError("Jira")

        if self.jql_query:
            # A custom JQL query takes priority over project_key for the
            # actual fetch — see JiraConnector._get_jql_query's own
            # docstring: "If a custom JQL query is provided, it will be
            # used... Otherwise, the query will be constructed based on
            # project key." The UI never sets both (this connector's form
            # only exposes project_key, no JQL field), but the constructor
            # accepts both, so: if a caller sets both directly, validating
            # the project's type would be checking something the real query
            # never touches. Validate the JQL instead, via the parent, and
            # skip the project-type check entirely.
            super().validate_connector_settings()
            return

        if not self.jira_project:
            # Neither a JQL query nor a specific project configured
            # (indexing everything) — the parent's own API-access check is
            # all there is to do.
            super().validate_connector_settings()
            return

        # One call covers both existence (a nonexistent/inaccessible project
        # raises here, same as the parent's own project-key branch) and the
        # service-desk type check — deliberately not also calling
        # super().validate_connector_settings() here, since that would issue
        # this same .project() call a second time for no new information.
        try:
            project = self.jira_client.project(self.jira_project)
        except Exception as e:
            self._handle_jira_connector_settings_error(e)
            return

        project_type = getattr(project, "projectTypeKey", None)
        if project_type is not None and project_type != _SERVICE_DESK_PROJECT_TYPE:
            raise ConnectorValidationError(
                f"Project '{self.jira_project}' is a '{project_type}' project, "
                "not a Jira Service Management project. Use the regular Jira "
                "connector for non-service-desk projects."
            )

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        gen = super().load_from_checkpoint(start, end, checkpoint)
        while True:
            try:
                item = next(gen)
            except StopIteration as stop:
                # The parent generator's own return type guarantees this is a
                # JiraConnectorCheckpoint; StopIteration.value is untyped in
                # typeshed (Any) so a type checker can't see that on its own.
                return cast(JiraConnectorCheckpoint, stop.value)
            yield _retag(item)

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraConnectorCheckpoint,
    ) -> CheckpointOutput[JiraConnectorCheckpoint]:
        gen = super().load_from_checkpoint_with_perm_sync(start, end, checkpoint)
        while True:
            try:
                item = next(gen)
            except StopIteration as stop:
                return cast(JiraConnectorCheckpoint, stop.value)
            yield _retag(item)


def _retag(item: _YieldItem) -> _YieldItem:
    """Re-tags a yielded Document with DocumentSource.JIRA_SERVICE_MANAGEMENT.
    ConnectorFailure and HierarchyNode items pass through unchanged — neither
    carries a DocumentSource."""
    if isinstance(item, Document):
        return item.model_copy(
            update={"source": DocumentSource.JIRA_SERVICE_MANAGEMENT}
        )
    return item
