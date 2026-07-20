import copy
import fnmatch
import tarfile
import tempfile
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from datetime import timezone
from enum import Enum
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from typing import BinaryIO
from urllib.parse import quote

import gitlab
from gitlab.v4.objects import Project
from pydantic import BaseModel
from pydantic import Field
from typing_extensions import override

from onyx.configs.app_configs import GITLAB_CONNECTOR_INCLUDE_CODE_FILES
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import detect_encoding
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.extract_file_text import get_file_ext
from onyx.file_processing.extract_file_text import is_text_file
from onyx.file_processing.extract_file_text import read_text_file
from onyx.file_processing.file_types import OnyxFileExtensions
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.datetime import datetime_to_utc
from onyx.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_EXCLUDED_PATH_SEGMENTS = {
    ".git",
    ".github",
    ".gitlab",
    ".idea",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "logs",
    "node_modules",
    "vendor",
}
DEFAULT_EXCLUDED_FILE_PATTERNS = [
    ".pre-commit-config.yaml",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".DS_Store",
    "Thumbs.db",
    "*.log",
    "*.tmp",
    "*.temp",
]

# Slashless patterns match basenames; paths use full recursive-glob semantics.
DEFAULT_CODE_FILE_PATTERNS = [
    "*.py",
    "*.js",
    "*.ts",
    "*.java",
    "*.cpp",
    "*.c",
    "*.h",
    "*.hpp",
    "*.cs",
    "*.php",
    "*.rb",
    "*.go",
    "*.rs",
    "*.kt",
    "*.scala",
    "*.swift",
    "*.m",
    "*.mm",
    "*.r",
    "*.sql",
    "*.html",
    "*.htm",
    "*.css",
    "*.scss",
    "*.sass",
    "*.less",
    "*.xml",
    "*.json",
    "*.yaml",
    "*.yml",
    "*.toml",
    "*.ini",
    "*.cfg",
    "*.config",
    "*.md",
    "*.rst",
    "*.txt",
    "*.sh",
    "*.bash",
    "*.ps1",
    "*.bat",
    "*.cmd",
    "*.bazel",
    "Makefile",
    "Dockerfile",
]

# Initial and explicit reindexes use an epoch-starting poll window.
_FULL_INDEX_START_CUTOFF = datetime(2005, 1, 1, tzinfo=timezone.utc)
MAX_ARCHIVE_SIZE_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_CONTENT_SIZE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_FILE_COUNT = 100_000
MAX_INDEXED_FILE_SIZE_BYTES = 20 * 1024 * 1024
MAX_GLOB_PATTERNS = 200
MAX_GLOB_PATTERN_LENGTH = 1_000
ARCHIVE_DOWNLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
GITLAB_ARCHIVE_SYNC_VERSION = 1


class GitlabSyncStage(str, Enum):
    CODE_FILES = "code_files"
    MERGE_REQUESTS = "merge_requests"
    ISSUES = "issues"
    COMPLETE = "complete"


class GitlabObjectType(str, Enum):
    MERGE_REQUEST = "merge request"
    ISSUE = "issue"


class GitlabConnectorCheckpoint(ConnectorCheckpoint):
    has_more: bool = True
    stage: GitlabSyncStage = GitlabSyncStage.CODE_FILES


class GitlabArchiveLimits(BaseModel):
    file_count: int = 0
    content_size_bytes: int = 0


class GitlabBranchCommit(BaseModel):
    id: str


class GitlabComparisonDiff(BaseModel):
    new_path: str | None = None
    deleted_file: bool = False


class GitlabComparison(BaseModel):
    compare_timeout: bool = False
    diffs: list[GitlabComparisonDiff] = Field(default_factory=list)


def _normalize_patterns(patterns: Iterable[str]) -> list[str]:
    """Normalize path separators and preserve legacy ``.*`` matching."""
    normalized: list[str] = []
    for pattern in patterns:
        cleaned = pattern.strip().replace("\\", "/")
        if not cleaned:
            continue
        if cleaned == ".*":
            cleaned = "*"
        if cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _extension_to_glob(extension: str) -> str:
    """Convert a legacy bare extension (e.g. ``.py`` or ``py``) to a glob."""
    cleaned = extension.strip()
    if not cleaned:
        return ""
    return f"*{cleaned}" if cleaned.startswith(".") else f"*.{cleaned}"


def _gitlab_datetime_to_utc(value: Any) -> datetime | None:
    """Normalize python-gitlab's raw ISO timestamps to UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return datetime_to_utc(value)
    return time_str_to_utc(value)


def _ensure_utc_datetime(dt: datetime | None) -> datetime:
    """Ensure datetime has UTC timezone information (None -> now)."""
    if dt is None:
        return datetime.now(timezone.utc)

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_author(author: Any) -> BasicExpertInfo:
    # GitLab masks names for some blocked and public-project users.
    name = author.get("name") if author else None
    if not name or name == "****":
        name = author.get("username") if author else None
    return BasicExpertInfo(
        display_name=name,
    )


def _convert_merge_request_to_document(mr: Any) -> Document:
    return Document(
        id=mr.web_url,
        sections=[TextSection(link=mr.web_url, text=mr.description or "")],
        source=DocumentSource.GITLAB,
        semantic_identifier=mr.title,
        doc_updated_at=_gitlab_datetime_to_utc(mr.updated_at),
        doc_created_at=_gitlab_datetime_to_utc(mr.created_at),
        primary_owners=[get_author(mr.author)],
        metadata={"state": mr.state, "type": "MergeRequest"},
    )


def _convert_issue_to_document(issue: Any) -> Document:
    return Document(
        id=issue.web_url,
        sections=[TextSection(link=issue.web_url, text=issue.description or "")],
        source=DocumentSource.GITLAB,
        semantic_identifier=issue.title,
        doc_updated_at=_gitlab_datetime_to_utc(issue.updated_at),
        doc_created_at=_gitlab_datetime_to_utc(issue.created_at),
        primary_owners=[get_author(issue.author)],
        metadata={"state": issue.state, "type": issue.type if issue.type else "Issue"},
    )


def _build_file_link(project_url: str, branch: str, relative_path: str) -> str:
    return (
        f"{project_url}/-/blob/{quote(branch, safe='')}/"
        f"{quote(relative_path, safe='/')}"
    )


def _build_file_id(project_url: str, branch: str, relative_path: str) -> str:
    return (
        f"{project_url}/blob/{quote(branch, safe='')}/{quote(relative_path, safe='/')}"
    )


def _convert_file_to_document(
    file_content: str,
    relative_path: str,
    project_url: str,
    branch: str,
) -> Document:
    file_link = _build_file_link(project_url, branch, relative_path)
    return Document(
        id=_build_file_id(project_url, branch, relative_path),
        sections=[TextSection(link=file_link, text=file_content)],
        source=DocumentSource.GITLAB,
        semantic_identifier=relative_path,
        primary_owners=[],
        metadata={
            "type": "CodeFile",
            "file_extension": PurePosixPath(relative_path).suffix,
        },
    )


def _should_exclude_by_patterns(path: str, patterns: list[str]) -> bool:
    """Check if a path matches any of the exclude patterns."""
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            logger.debug("Path '%s' excluded by pattern '%s'", path, pattern)
            return True
    return False


def _is_default_excluded(path: str) -> bool:
    path_parts = set(PurePosixPath(path).parts)
    return bool(path_parts & DEFAULT_EXCLUDED_PATH_SEGMENTS) or (
        _should_exclude_by_patterns(path, DEFAULT_EXCLUDED_FILE_PATTERNS)
    )


def _matches_glob(path: str, pattern: str) -> bool:
    """Match a repo-relative path against a single glob pattern.

    Patterns without a ``/`` match the file's basename anywhere in the tree
    (e.g. ``*.py``, ``Makefile``); patterns containing a ``/`` match the full
    relative path (e.g. ``src/*.py``, ``docs/**``).
    """
    pattern = pattern.strip()
    if not pattern:
        return False
    if "/" in pattern:
        return PurePosixPath(path).full_match(pattern)
    return fnmatch.fnmatchcase(PurePosixPath(path).name, pattern)


def _matches_any_glob(path: str, patterns: list[str]) -> bool:
    return any(_matches_glob(path, pattern) for pattern in patterns)


def _should_include_by_glob(path: str, include_patterns: list[str]) -> bool:
    """Include the path if it matches any include glob (empty = include all)."""
    if not include_patterns:
        return True
    return _matches_any_glob(path, include_patterns)


def _should_exclude_by_glob(path: str, exclude_patterns: list[str]) -> bool:
    """Exclude the path if it matches any exclude glob (empty = exclude none)."""
    if not exclude_patterns:
        return False
    return _matches_any_glob(path, exclude_patterns)


def _validate_patterns(name: str, patterns: list[str]) -> None:
    if len(patterns) > MAX_GLOB_PATTERNS:
        raise ValueError(
            f"{name} cannot contain more than {MAX_GLOB_PATTERNS} patterns"
        )
    if any(len(pattern) > MAX_GLOB_PATTERN_LENGTH for pattern in patterns):
        raise ValueError(
            f"{name} patterns cannot exceed {MAX_GLOB_PATTERN_LENGTH} characters"
        )


def _archive_relative_path(member_name: str) -> str | None:
    path = PurePosixPath(member_name)
    if path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
        return None
    relative_path = PurePosixPath(*path.parts[1:])
    return relative_path.as_posix() if relative_path.name else None


class GitlabConnector(
    CheckpointedConnector[GitlabConnectorCheckpoint],
    SlimConnector,
):
    """Indexes GitLab issues, merge requests, and repository files."""

    def __init__(
        self,
        project_owner: str,
        project_name: str,
        batch_size: int = INDEX_BATCH_SIZE,
        state_filter: str = "all",
        include_mrs: bool = True,
        include_issues: bool = True,
        include_code_files: bool = GITLAB_CONNECTOR_INCLUDE_CODE_FILES,
        include_path_patterns: list[str] | None = None,
        exclude_path_patterns: list[str] | None = None,
        clone_depth: int | None = None,
        branch: str | None = None,
        code_file_patterns: list[str] | None = None,
        code_file_extensions: list[str] | None = None,
        archive_sync_version: int = GITLAB_ARCHIVE_SYNC_VERSION,
    ) -> None:
        del clone_depth
        if archive_sync_version != GITLAB_ARCHIVE_SYNC_VERSION:
            raise ValueError(
                f"Unsupported GitLab archive sync version: {archive_sync_version}"
            )
        include_path_patterns = _normalize_patterns(include_path_patterns or [])
        exclude_path_patterns = _normalize_patterns(exclude_path_patterns or [])
        self.project_owner = project_owner
        self.project_name = project_name
        self.batch_size = batch_size
        self.state_filter = state_filter
        self.include_mrs = include_mrs
        self.include_issues = include_issues
        self.include_code_files = include_code_files
        self.include_path_patterns = include_path_patterns
        self.exclude_path_patterns = exclude_path_patterns
        self.branch = branch or None
        if code_file_patterns:
            self.code_file_patterns = _normalize_patterns(code_file_patterns)
        elif code_file_extensions:
            self.code_file_patterns = _normalize_patterns(
                [_extension_to_glob(ext) for ext in code_file_extensions]
            )
        else:
            self.code_file_patterns = list(DEFAULT_CODE_FILE_PATTERNS)
        _validate_patterns("code_file_patterns", self.code_file_patterns)
        _validate_patterns("include_path_patterns", self.include_path_patterns)
        _validate_patterns("exclude_path_patterns", self.exclude_path_patterns)
        self.gitlab_client: gitlab.Gitlab | None = None
        self.gitlab_url: str | None = None

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        gitlab_url = credentials["gitlab_url"]
        self.gitlab_url = gitlab_url.rstrip("/")
        self.gitlab_client = gitlab.Gitlab(
            self.gitlab_url,
            private_token=credentials["gitlab_access_token"],
            timeout=REQUEST_TIMEOUT_SECONDS,
            retry_transient_errors=True,
        )
        return None

    def _get_project(self) -> Project:
        if self.gitlab_client is None:
            raise ConnectorMissingCredentialError("Gitlab")
        return self.gitlab_client.projects.get(
            f"{self.project_owner}/{self.project_name}"
        )

    def _get_commit_at_or_before(
        self,
        project: Project,
        branch: str,
        timestamp: datetime,
    ) -> str | None:
        commits = list(
            project.commits.list(
                ref_name=branch,
                until=_ensure_utc_datetime(timestamp).isoformat(),
                per_page=1,
                get_all=False,
            )
        )
        return str(commits[0].id) if commits else None

    def _get_changed_paths(
        self,
        project: Project,
        branch: str,
        start: datetime,
        target_sha: str,
    ) -> set[str] | None:
        # Without a durable SHA cursor, backdated or rewritten history can be missed.
        base_sha = self._get_commit_at_or_before(project, branch, start)
        if base_sha is None:
            return None
        if base_sha == target_sha:
            return set()

        comparison_response = project.repository_compare(
            base_sha,
            target_sha,
            straight=True,
        )
        if not isinstance(comparison_response, dict):
            logger.warning("GitLab compare returned an unexpected response")
            return None
        comparison = GitlabComparison.model_validate(comparison_response)
        if comparison.compare_timeout:
            logger.warning("GitLab compare was incomplete; scanning the full archive")
            return None
        return {
            diff.new_path
            for diff in comparison.diffs
            if not diff.deleted_file and diff.new_path is not None
        }

    @contextmanager
    def _download_archive(
        self,
        project: Project,
        target_sha: str,
    ) -> Iterator[BinaryIO]:
        downloaded_bytes = 0
        with tempfile.TemporaryFile() as archive_file:

            def write_chunk(chunk: bytes) -> None:
                nonlocal downloaded_bytes
                downloaded_bytes += len(chunk)
                if downloaded_bytes > MAX_ARCHIVE_SIZE_BYTES:
                    raise ValueError(
                        f"GitLab archive exceeds {MAX_ARCHIVE_SIZE_BYTES} bytes"
                    )
                archive_file.write(chunk)

            project.repository_archive(
                sha=target_sha,
                streamed=True,
                action=write_chunk,
                chunk_size=ARCHIVE_DOWNLOAD_CHUNK_SIZE_BYTES,
            )
            archive_file.seek(0)
            yield archive_file

    def _should_index_path(
        self,
        relative_path: str,
        changed_paths: set[str] | None,
    ) -> bool:
        if changed_paths is not None and relative_path not in changed_paths:
            return False
        if _is_default_excluded(relative_path):
            return False
        if _should_exclude_by_glob(relative_path, self.exclude_path_patterns):
            return False
        if not _should_include_by_glob(relative_path, self.include_path_patterns):
            return False
        return _matches_any_glob(relative_path, self.code_file_patterns)

    def _iter_archive_files(
        self,
        archive: tarfile.TarFile,
        changed_paths: set[str] | None,
    ) -> Iterator[tuple[tarfile.TarInfo, str]]:
        limits = GitlabArchiveLimits()
        for member in archive:
            if not member.isfile():
                continue

            limits.file_count += 1
            limits.content_size_bytes += member.size
            if limits.file_count > MAX_ARCHIVE_FILE_COUNT:
                raise ValueError(
                    f"GitLab archive exceeds {MAX_ARCHIVE_FILE_COUNT} files"
                )
            if limits.content_size_bytes > MAX_ARCHIVE_CONTENT_SIZE_BYTES:
                raise ValueError(
                    "GitLab archive extracted content exceeds "
                    f"{MAX_ARCHIVE_CONTENT_SIZE_BYTES} bytes"
                )

            relative_path = _archive_relative_path(member.name)
            if relative_path is None or not self._should_index_path(
                relative_path, changed_paths
            ):
                continue
            if member.size > MAX_INDEXED_FILE_SIZE_BYTES:
                logger.warning(
                    "Skipping oversized GitLab file %s (%s bytes)",
                    relative_path,
                    member.size,
                )
                continue
            yield member, relative_path

    def _read_archive_file(
        self,
        archive: tarfile.TarFile,
        member: tarfile.TarInfo,
        relative_path: str,
    ) -> str:
        extracted_file = archive.extractfile(member)
        if extracted_file is None:
            raise ValueError(f"Archive member {relative_path} has no content")
        content = extracted_file.read(MAX_INDEXED_FILE_SIZE_BYTES + 1)
        if len(content) > MAX_INDEXED_FILE_SIZE_BYTES:
            raise ValueError(
                f"Archive member {relative_path} exceeds the indexed file size limit"
            )
        file = BytesIO(content)
        extension = get_file_ext(relative_path)
        if extension in OnyxFileExtensions.DOCUMENT_EXTENSIONS:
            return extract_file_text(file, relative_path)
        if not is_text_file(file):
            raise ValueError("File is not recognized as text")
        encoding = detect_encoding(file)
        return read_text_file(file, encoding=encoding)[0]

    def _file_failure(
        self,
        project_url: str,
        branch: str,
        relative_path: str,
        exception: Exception,
    ) -> ConnectorFailure:
        return ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=_build_file_id(project_url, branch, relative_path),
                document_link=_build_file_link(project_url, branch, relative_path),
            ),
            failure_message=f"Failed to process GitLab file {relative_path}: {exception}",
            exception=exception,
        )

    def _fetch_code_files(
        self,
        project: Project,
        branch: str,
        target_sha: str,
        changed_paths: set[str] | None,
    ) -> Iterator[Document | ConnectorFailure]:
        if changed_paths == set():
            return

        project_url = str(project.web_url)
        with self._download_archive(project, target_sha) as archive_file:
            with tarfile.open(fileobj=archive_file, mode="r:*") as archive:
                for member, relative_path in self._iter_archive_files(
                    archive, changed_paths
                ):
                    try:
                        file_content = self._read_archive_file(
                            archive, member, relative_path
                        )
                        yield _convert_file_to_document(
                            file_content=file_content,
                            relative_path=relative_path,
                            project_url=project_url,
                            branch=branch,
                        )
                    except Exception as exception:
                        logger.warning(
                            "Failed to process GitLab file %s: %s",
                            relative_path,
                            exception,
                        )
                        yield self._file_failure(
                            project_url,
                            branch,
                            relative_path,
                            exception,
                        )

    def _iter_objects(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        objects: Iterable[Any],
        converter: Callable[[Any], Document],
        object_type: GitlabObjectType,
    ) -> Iterator[Document | ConnectorFailure]:
        start_utc = _ensure_utc_datetime(start) if start else None
        end_utc = _ensure_utc_datetime(end) if end else None
        for gitlab_object in objects:
            try:
                updated_at = _gitlab_datetime_to_utc(gitlab_object.updated_at)
                if updated_at is not None and start_utc and updated_at < start_utc:
                    return
                if updated_at is not None and end_utc and updated_at > end_utc:
                    continue
                yield converter(gitlab_object)
            except Exception as exception:
                object_url = getattr(gitlab_object, "web_url", None)
                object_id = str(
                    object_url
                    or f"gitlab-{object_type.value}-"
                    f"{getattr(gitlab_object, 'id', 'unknown')}"
                )
                logger.warning(
                    "Failed to process GitLab %s %s: %s",
                    object_type.value,
                    object_id,
                    exception,
                )
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=object_id,
                        document_link=str(object_url) if object_url else None,
                    ),
                    failure_message=(
                        f"Failed to process GitLab {object_type.value}: {exception}"
                    ),
                    exception=exception,
                )

    def _list_merge_requests(self, project: Project) -> Iterable[Any]:
        if not self.include_mrs:
            return ()
        return project.mergerequests.list(
            state=self.state_filter,
            order_by="updated_at",
            sort="desc",
            iterator=True,
        )

    def _list_issues(self, project: Project) -> Iterable[Any]:
        if not self.include_issues:
            return ()
        return project.issues.list(
            state=self.state_filter,
            order_by="updated_at",
            sort="desc",
            iterator=True,
        )

    def _get_target_sha(
        self,
        project: Project,
        branch: str,
    ) -> str | None:
        branch_data = project.branches.get(branch)
        return GitlabBranchCommit.model_validate(branch_data.commit).id

    def _fetch_code_documents(
        self,
        project: Project,
        start: datetime,
    ) -> Iterator[Document | ConnectorFailure]:
        branch = self.branch or project.default_branch
        if not self.include_code_files or not branch:
            return
        target_sha = self._get_target_sha(project, branch)
        if not target_sha:
            return
        changed_paths = (
            None
            if _ensure_utc_datetime(start) <= _FULL_INDEX_START_CUTOFF
            else self._get_changed_paths(project, branch, start, target_sha)
        )
        yield from self._fetch_code_files(
            project,
            branch,
            target_sha,
            changed_paths,
        )

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GitlabConnectorCheckpoint,
    ) -> CheckpointOutput[GitlabConnectorCheckpoint]:
        next_checkpoint = copy.deepcopy(checkpoint)
        if not next_checkpoint.has_more:
            return next_checkpoint

        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        project = self._get_project()

        if next_checkpoint.stage == GitlabSyncStage.CODE_FILES:
            yield from self._fetch_code_documents(project, start_datetime)
            next_checkpoint.stage = GitlabSyncStage.MERGE_REQUESTS
            return next_checkpoint

        if next_checkpoint.stage == GitlabSyncStage.MERGE_REQUESTS:
            if not self.include_mrs:
                next_checkpoint.stage = GitlabSyncStage.ISSUES
                return next_checkpoint
            objects = self._list_merge_requests(project)
            converter = _convert_merge_request_to_document
            object_type = GitlabObjectType.MERGE_REQUEST
        elif next_checkpoint.stage == GitlabSyncStage.ISSUES:
            if not self.include_issues:
                next_checkpoint.stage = GitlabSyncStage.COMPLETE
                next_checkpoint.has_more = False
                return next_checkpoint
            objects = self._list_issues(project)
            converter = _convert_issue_to_document
            object_type = GitlabObjectType.ISSUE
        else:
            next_checkpoint.has_more = False
            return next_checkpoint

        yield from self._iter_objects(
            start_datetime,
            end_datetime,
            objects=objects,
            converter=converter,
            object_type=object_type,
        )
        if next_checkpoint.stage == GitlabSyncStage.MERGE_REQUESTS:
            next_checkpoint.stage = GitlabSyncStage.ISSUES
        else:
            next_checkpoint.stage = GitlabSyncStage.COMPLETE
            next_checkpoint.has_more = False
        return next_checkpoint

    @override
    def build_dummy_checkpoint(self) -> GitlabConnectorCheckpoint:
        return GitlabConnectorCheckpoint(has_more=True)

    @override
    def validate_checkpoint_json(
        self,
        checkpoint_json: str,
    ) -> GitlabConnectorCheckpoint:
        return GitlabConnectorCheckpoint.model_validate_json(checkpoint_json)

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        del start, end
        project = self._get_project()
        branch = self.branch or project.default_branch
        batch: list[SlimDocument | HierarchyNode] = []

        if self.include_code_files and branch:
            target_sha = self._get_target_sha(project, branch)
            if target_sha:
                with self._download_archive(project, target_sha) as archive_file:
                    with tarfile.open(fileobj=archive_file, mode="r:*") as archive:
                        for _, relative_path in self._iter_archive_files(archive, None):
                            if callback and callback.should_stop():
                                raise RuntimeError("GitLab slim retrieval stopped")
                            batch.append(
                                SlimDocument(
                                    id=_build_file_id(
                                        str(project.web_url),
                                        branch,
                                        relative_path,
                                    )
                                )
                            )
                            if len(batch) >= self.batch_size:
                                yield batch
                                batch = []

        for objects in (
            self._list_merge_requests(project),
            self._list_issues(project),
        ):
            for gitlab_object in objects:
                if callback and callback.should_stop():
                    raise RuntimeError("GitLab slim retrieval stopped")
                batch.append(SlimDocument(id=str(gitlab_object.web_url)))
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []

        if batch:
            yield batch
