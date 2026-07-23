import fnmatch
import itertools
from collections import deque
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from typing import Any, TypeVar

import gitlab
import pytz
from gitlab.exceptions import GitlabGetError
from gitlab.v4.objects import Project

from onyx.configs.app_configs import (
    GITLAB_CONNECTOR_INCLUDE_CODE_FILES,
    INDEX_BATCH_SIZE,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput,
    LoadConnector,
    PollConnector,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorMissingCredentialError,
    Document,
    HierarchyNode,
    TextSection,
)
from onyx.utils.datetime import datetime_to_utc
from onyx.utils.logger import setup_logger

T = TypeVar("T")


logger = setup_logger()

# List of directories/Files to exclude
exclude_patterns = [
    "logs",
    ".github/",
    ".gitlab/",
    ".pre-commit-config.yaml",
]


def _batch_gitlab_objects(git_objs: Iterable[T], batch_size: int) -> Iterator[list[T]]:
    it = iter(git_objs)
    while True:
        batch = list(itertools.islice(it, batch_size))
        if not batch:
            break
        yield batch


def get_author(author: Any) -> BasicExpertInfo:
    # GitLab masks the `name` field as "****" for blocked users and as an
    # anti-scraping measure on free-tier public projects. Fall back to
    # `username` so we surface a usable identifier instead.
    name = author.get("name")
    if not name or name == "****":
        name = author.get("username")
    return BasicExpertInfo(
        display_name=name,
    )


def _gitlab_datetime_to_utc(value: Any) -> datetime | None:
    """Normalize a GitLab timestamp to tz-aware UTC.

    python-gitlab exposes REST attributes as raw JSON, so these arrive as
    ISO-8601 strings; handle datetime values defensively too. Uses the shared
    parser rather than a fixed format so whole-second timestamps (no fractional
    part) don't raise.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return datetime_to_utc(value)
    return time_str_to_utc(value)


def _convert_merge_request_to_document(mr: Any) -> Document:
    doc = Document(
        id=mr.web_url,
        sections=[TextSection(link=mr.web_url, text=mr.description or "")],
        source=DocumentSource.GITLAB,
        semantic_identifier=mr.title,
        doc_updated_at=_gitlab_datetime_to_utc(mr.updated_at),
        # NOTE: doc_created_at population not yet verified against live data
        doc_created_at=_gitlab_datetime_to_utc(mr.created_at),
        primary_owners=[get_author(mr.author)],
        metadata={"state": mr.state, "type": "MergeRequest"},
    )
    return doc


def _convert_issue_to_document(issue: Any) -> Document:
    doc = Document(
        id=issue.web_url,
        sections=[TextSection(link=issue.web_url, text=issue.description or "")],
        source=DocumentSource.GITLAB,
        semantic_identifier=issue.title,
        doc_updated_at=_gitlab_datetime_to_utc(issue.updated_at),
        # NOTE: doc_created_at population not yet verified against live data
        doc_created_at=_gitlab_datetime_to_utc(issue.created_at),
        primary_owners=[get_author(issue.author)],
        metadata={"state": issue.state, "type": issue.type if issue.type else "Issue"},
    )
    return doc


def _convert_code_to_document(
    project: Project,
    file: Any,
    url: str,
    projectName: str,
    projectOwner: str,
    branch: str | None = None,
) -> Document:
    # Use the explicitly configured branch if provided, otherwise fall back
    # to the project's default branch (preserves prior behavior).
    target_branch = branch or project.default_branch

    # Fetch the file content using the resolved branch
    try:
        file_content_obj = project.files.get(
            file_path=file["path"],
            ref=target_branch,
        )
    except GitlabGetError as e:
        if e.response_code == 404:
            raise ValueError(
                f"Could not fetch '{file['path']}' from branch '{target_branch}' in "
                f"project '{projectOwner}/{projectName}'. Check that the branch exists "
                "and that the configured access token has permission to read it."
            ) from e
        raise
    try:
        file_content = file_content_obj.decode().decode("utf-8")
    except UnicodeDecodeError:
        file_content = file_content_obj.decode().decode("latin-1")

    # Construct the file URL dynamically using the resolved branch
    file_url = (
        f"{url}/{projectOwner}/{projectName}/-/blob/{target_branch}/{file['path']}"
    )

    # Create and return a Document object
    doc = Document(
        id=file["id"],
        sections=[TextSection(link=file_url, text=file_content)],
        source=DocumentSource.GITLAB,
        semantic_identifier=file["name"],
        doc_updated_at=datetime.now().replace(tzinfo=timezone.utc),
        primary_owners=[],  # Add owners if needed
        metadata={"type": "CodeFile"},
    )
    return doc


def _should_exclude(path: str) -> bool:
    """Check if a path matches any of the exclude patterns."""
    return any(fnmatch.fnmatch(path, pattern) for pattern in exclude_patterns)


class GitlabConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        project_owner: str,
        project_name: str,
        batch_size: int = INDEX_BATCH_SIZE,
        state_filter: str = "all",
        include_mrs: bool = True,
        include_issues: bool = True,
        include_code_files: bool = GITLAB_CONNECTOR_INCLUDE_CODE_FILES,
        branch: str | None = None,
    ) -> None:
        self.project_owner = project_owner
        self.project_name = project_name
        self.batch_size = batch_size
        self.state_filter = state_filter
        self.include_mrs = include_mrs
        self.include_issues = include_issues
        self.include_code_files = include_code_files
        # Normalize "" (e.g. from an empty form field) to None so it falls
        # back cleanly to the project's default branch.
        self.branch = branch or None
        self.gitlab_client: gitlab.Gitlab | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.gitlab_client = gitlab.Gitlab(
            credentials["gitlab_url"], private_token=credentials["gitlab_access_token"]
        )
        return None

    def _fetch_from_gitlab(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        if self.gitlab_client is None:
            raise ConnectorMissingCredentialError("Gitlab")
        project: Project = self.gitlab_client.projects.get(
            f"{self.project_owner}/{self.project_name}"
        )

        # Fetch code files
        if self.include_code_files:
            # Fetching using BFS as project.report_tree with recursion causing slow load
            queue = deque([""])  # Start with the root directory
            while queue:
                current_path = queue.popleft()
                try:
                    files = project.repository_tree(
                        path=current_path, ref=self.branch, all=True
                    )
                except GitlabGetError as e:
                    if e.response_code == 404 and self.branch:
                        raise ValueError(
                            f"Could not list files from branch '{self.branch}' in "
                            f"project '{self.project_owner}/{self.project_name}'. "
                            "Check that the branch exists and that the configured "
                            "access token has permission to read it."
                        ) from e
                    raise
                for file_batch in _batch_gitlab_objects(files, self.batch_size):
                    code_doc_batch: list[Document | HierarchyNode] = []
                    for file in file_batch:
                        if _should_exclude(file["path"]):
                            continue

                        if file["type"] == "blob":
                            code_doc_batch.append(
                                _convert_code_to_document(
                                    project,
                                    file,
                                    self.gitlab_client.url,
                                    self.project_name,
                                    self.project_owner,
                                    self.branch,
                                )
                            )
                        elif file["type"] == "tree":
                            queue.append(file["path"])

                    if code_doc_batch:
                        yield code_doc_batch

        if self.include_mrs:
            merge_requests = project.mergerequests.list(
                state=self.state_filter,
                order_by="updated_at",
                sort="desc",
                iterator=True,
            )

            for mr_batch in _batch_gitlab_objects(merge_requests, self.batch_size):
                mr_doc_batch: list[Document | HierarchyNode] = []
                for mr in mr_batch:
                    mr.updated_at = datetime.strptime(
                        mr.updated_at, "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                    if start is not None and mr.updated_at < start.replace(
                        tzinfo=pytz.UTC
                    ):
                        yield mr_doc_batch
                        return
                    if end is not None and mr.updated_at > end.replace(tzinfo=pytz.UTC):
                        continue
                    mr_doc_batch.append(_convert_merge_request_to_document(mr))
                yield mr_doc_batch

        if self.include_issues:
            issues = project.issues.list(state=self.state_filter, iterator=True)

            for issue_batch in _batch_gitlab_objects(issues, self.batch_size):
                issue_doc_batch: list[Document | HierarchyNode] = []
                for issue in issue_batch:
                    issue.updated_at = datetime.strptime(
                        issue.updated_at, "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                    if start is not None:
                        start = start.replace(tzinfo=pytz.UTC)
                        if issue.updated_at < start:
                            yield issue_doc_batch
                            return
                    if end is not None:
                        end = end.replace(tzinfo=pytz.UTC)
                        if issue.updated_at > end:
                            continue
                    issue_doc_batch.append(_convert_issue_to_document(issue))
                yield issue_doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._fetch_from_gitlab()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        return self._fetch_from_gitlab(start_datetime, end_datetime)


if __name__ == "__main__":
    import os

    connector = GitlabConnector(
        # gitlab_url="https://gitlab.com/api/v4",
        project_owner=os.environ["PROJECT_OWNER"],
        project_name=os.environ["PROJECT_NAME"],
        batch_size=10,
        state_filter="all",
        include_mrs=True,
        include_issues=True,
        include_code_files=GITLAB_CONNECTOR_INCLUDE_CODE_FILES,
        branch=os.environ.get("BRANCH"),  # optional, defaults to the default branch
    )

    connector.load_credentials(
        {
            "gitlab_access_token": os.environ["GITLAB_ACCESS_TOKEN"],
            "gitlab_url": os.environ["GITLAB_URL"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
