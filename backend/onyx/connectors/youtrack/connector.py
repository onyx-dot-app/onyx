from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    CredentialsConnector,
    CredentialsProviderInterface,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnectorWithPermSync,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorCheckpoint,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    ImageSection,
    SlimDocument,
    TabularSection,
    TextSection,
)
from onyx.connectors.youtrack.access import (
    get_issue_access,
    get_project_node_access,
)
from onyx.connectors.youtrack.models import (
    YouTrackComment,
    YouTrackCustomField,
    YouTrackFieldValue,
    YouTrackIssue,
    YouTrackProject,
    YouTrackUser,
)
from onyx.connectors.youtrack.source_operations import (
    YouTrackSourceOperations,
)
from onyx.db.enums import HierarchyNodeType
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.logger import setup_logger

logger = setup_logger()

_DATE_FIELD_TYPE: str = "DateIssueCustomField"
# Search dates are calendar days in the token user's time zone, so the query
# widens the window by a day each side and the exact bounds are applied to
# each issue's epoch-ms `updated`.
_QUERY_DAY_MARGIN: timedelta = timedelta(days=1)
# Created never changes, so $skip paging stays stable while issues are edited
# during the walk. New issues land at the end.
_SORT_CLAUSE: str = "sort by: created asc"


def _utc(epoch_ms: int) -> datetime:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)


class YouTrackCheckpoint(ConnectorCheckpoint):
    # Ids of projects still to index, listed on the first run. Each run indexes one.
    project_ids: list[str] | None = None


def issue_query(
    projects: list[str], start: datetime | None = None, end: datetime | None = None
) -> str:
    clauses: list[str] = []
    if projects:
        clauses.append("project: " + ", ".join(f"{{{p}}}" for p in projects))
    if start is not None or end is not None:
        low: str = (start - _QUERY_DAY_MARGIN).date().isoformat() if start else "*"
        high: str = (end + _QUERY_DAY_MARGIN).date().isoformat() if end else "*"
        clauses.append(f"updated: {low} .. {high}")
    clauses.append(_SORT_CLAUSE)
    return " ".join(clauses)


def active_projects(
    ops: YouTrackSourceOperations, projects: list[str]
) -> list[YouTrackProject]:
    """Readable, unarchived projects in scope. YouTrack hides an archived
    project's issues and rejects a search that names the project."""
    wanted: set[str] = {name.lower() for name in projects}
    return [
        project
        for project in ops.list_projects()
        if not project.archived and (not wanted or project.short_name.lower() in wanted)
    ]


def scoped_query(
    ops: YouTrackSourceOperations,
    projects: list[str],
    start: datetime | None = None,
    end: datetime | None = None,
) -> str | None:
    """The search for issues in scope, or None when every configured project
    is gone or archived."""
    if not projects:
        return issue_query([], start, end)
    names: list[str] = [
        project.short_name for project in active_projects(ops, projects)
    ]
    return issue_query(names, start, end) if names else None


def missing_projects(ops: YouTrackSourceOperations, projects: list[str]) -> list[str]:
    readable: set[str] = {project.short_name.lower() for project in ops.list_projects()}
    return sorted(name for name in projects if name.lower() not in readable)


def projects_not_found(missing: list[str]) -> ConnectorValidationError:
    return ConnectorValidationError(
        f"YouTrack projects not found: {', '.join(missing)}. Check each short "
        "name, or give the token's user access to the project."
    )


def _expert(user: YouTrackUser | None) -> BasicExpertInfo | None:
    if user is None:
        return None
    return BasicExpertInfo(display_name=user.full_name or user.login, email=user.email)


def _field_text(field: YouTrackCustomField) -> str | list[str] | None:
    value = field.value
    if value is None:
        return None
    if isinstance(value, list):
        texts: list[str] = [text for v in value if (text := v.display())]
        return texts or None
    if isinstance(value, YouTrackFieldValue):
        return value.display()
    if field.type == _DATE_FIELD_TYPE and isinstance(value, int):
        return _utc(value).date().isoformat()
    return str(value)


def _is_public_comment(comment: YouTrackComment) -> bool:
    """Deleted comments, and restricted ones since they are narrower than
    their issue, stay out of the issue's text."""
    return not comment.deleted and not (
        comment.visibility is not None and comment.visibility.is_restricted
    )


class YouTrackConnector(
    CheckpointedConnector[YouTrackCheckpoint],
    SlimConnectorWithPermSync,
    CredentialsConnector,
):
    def __init__(
        self,
        base_url: str,
        projects: list[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.projects: list[str] = projects or []
        self._ops: YouTrackSourceOperations | None = None

    @property
    def ops(self) -> YouTrackSourceOperations:
        if self._ops is None:
            raise ConnectorMissingCredentialError("YouTrack")
        return self._ops

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError("Use set_credentials_provider with this connector.")

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        self._ops = YouTrackSourceOperations(
            credentials_provider=credentials_provider,
            connector_specific_config={"base_url": self.base_url},
        )

    def validate_connector_settings(self) -> None:
        """One message names every configured project the token cannot read.
        The gateway checks the base URL before its first request."""
        self.ops.get_me()
        if not self.projects:
            return
        missing: list[str] = missing_projects(self.ops, self.projects)
        if missing:
            raise projects_not_found(missing)

    def _issue_link(self, issue: YouTrackIssue) -> str:
        return f"{self.base_url}/issue/{issue.id_readable}"

    def doc_id(self, issue_id: str) -> str:
        """Database ids survive a move between projects, unlike readable ids."""
        return f"{self.base_url}/api/issues/{issue_id}"

    def project_node_id(self, project_id: str) -> str:
        """Project ids repeat across YouTrack instances, so the node id carries
        the instance's URL like document ids do."""
        return f"{self.base_url}/api/admin/projects/{project_id}"

    def _project_node(self, project: YouTrackProject) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=self.project_node_id(project.id),
            raw_parent_id=None,
            display_name=project.name,
            link=f"{self.base_url}/projects/{project.short_name}",
            node_type=HierarchyNodeType.PROJECT,
        )

    def _comments(self, issue: YouTrackIssue) -> list[YouTrackComment]:
        if issue.comments_count is None or len(issue.comments) >= issue.comments_count:
            return issue.comments
        return self.ops.list_issue_comments(issue_id=issue.id)

    def _to_document(self, issue: YouTrackIssue) -> Document:
        link: str = self._issue_link(issue)
        sections: list[TextSection | ImageSection | TabularSection] = [
            TextSection(link=link, text=issue.description or "")
        ]
        sections.extend(
            TextSection(link=f"{link}#focus=Comments-{c.id}.0-0", text=c.text or "")
            for c in self._comments(issue)
            if _is_public_comment(c)
        )
        metadata: dict[str, str | list[str]] = {"project": issue.project.name}
        for field in issue.custom_fields:
            # Private fields need a permission most readers lack.
            if field.project_custom_field and not field.project_custom_field.is_public:
                continue
            if (text := _field_text(field)) is not None:
                metadata[field.name] = text
        if issue.resolved is not None:
            metadata["resolved_at"] = _utc(issue.resolved).isoformat()
        reporter: BasicExpertInfo | None = _expert(issue.reporter)
        return Document(
            id=self.doc_id(issue.id),
            sections=sections,
            source=DocumentSource.YOUTRACK,
            semantic_identifier=f"[{issue.id_readable}] {issue.summary or ''}".strip(),
            title=issue.summary,
            doc_updated_at=_utc(issue.updated),
            doc_created_at=_utc(issue.created),
            primary_owners=[reporter] if reporter else None,
            metadata=metadata,
            parent_hierarchy_raw_node_id=self.project_node_id(issue.project.id),
        )

    def _project_documents(
        self, project: YouTrackProject, start: datetime | None, end: datetime
    ) -> Iterator[Document]:
        start_ms: int | None = int(start.timestamp() * 1000) if start else None
        end_ms: int = int(end.timestamp() * 1000)
        query: str = issue_query([project.short_name], start, end)
        for issues in self.ops.iterate_issues(query=query):
            for issue in issues:
                if start_ms is not None and issue.updated < start_ms:
                    continue
                if issue.updated > end_ms:
                    continue
                yield self._to_document(issue)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: YouTrackCheckpoint,
    ) -> CheckpointOutput[YouTrackCheckpoint]:
        checkpoint = checkpoint.model_copy(deep=True)
        # Listed every run: YouTrack rejects a search naming a project archived
        # or removed while it waited in the queue, so those are skipped.
        active: dict[str, YouTrackProject] = {
            project.id: project for project in active_projects(self.ops, self.projects)
        }
        if checkpoint.project_ids is None:
            checkpoint.project_ids = list(active)
        project: YouTrackProject | None = None
        while checkpoint.project_ids and project is None:
            project = active.get(checkpoint.project_ids.pop(0))
        if project is not None:
            yield self._project_node(project)
            # A first run starts at the epoch, which needs no date clause.
            yield from self._project_documents(
                project,
                datetime.fromtimestamp(start, tz=timezone.utc) if start > 0 else None,
                datetime.fromtimestamp(end, tz=timezone.utc),
            )
        checkpoint.has_more = bool(checkpoint.project_ids)
        return checkpoint

    def build_dummy_checkpoint(self) -> YouTrackCheckpoint:
        return YouTrackCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> YouTrackCheckpoint:
        return YouTrackCheckpoint.model_validate_json(checkpoint_json)

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        query: str | None = scoped_query(self.ops, self.projects)
        if query is None:
            return
        for issues in self.ops.iterate_slim_issues(query=query):
            # A partial walk would read as deleted issues, so stopping raises.
            if callback is not None and callback.should_stop():
                raise RuntimeError("YouTrack slim retrieval: stop signal detected")
            yield [
                SlimDocument(
                    id=self.doc_id(issue.id),
                    parent_hierarchy_raw_node_id=self.project_node_id(issue.project.id),
                    doc_created_at=_utc(issue.created),
                )
                for issue in issues
            ]
            if callback is not None:
                callback.progress("youtrack_slim_docs", len(issues))

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Every issue in scope with who may read it. The doc sync makes any
        indexed issue this does not list private, so the window is ignored."""
        query: str | None = scoped_query(self.ops, self.projects)
        if query is None:
            return
        seen_projects: set[str] = set()
        for page in self.ops.iterate_issue_access(query=query):
            if callback is not None and callback.should_stop():
                raise RuntimeError("YouTrack permission sync: stop signal detected")
            batch: list[SlimDocument | HierarchyNode] = []
            for issue in page:
                if issue.project.id not in seen_projects:
                    seen_projects.add(issue.project.id)
                    node: HierarchyNode = self._project_node(issue.project)
                    node.external_access = get_project_node_access(
                        self.base_url, issue.project.id
                    )
                    batch.append(node)
                batch.append(
                    SlimDocument(
                        id=self.doc_id(issue.id),
                        external_access=get_issue_access(self.base_url, issue),
                        parent_hierarchy_raw_node_id=self.project_node_id(
                            issue.project.id
                        ),
                    )
                )
            yield batch
            if callback is not None:
                callback.progress("youtrack_perm_sync", len(page))
