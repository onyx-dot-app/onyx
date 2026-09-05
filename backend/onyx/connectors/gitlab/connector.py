import fnmatch
import itertools
from collections import deque
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from typing import Any, TypeVar

import gitlab
import pytz
from gitlab.exceptions import GitlabError, GitlabGetError
from gitlab.v4.objects import Project

from onyx.configs.app_configs import (
    GITLAB_CONNECTOR_EXCLUDE_PATTERNS,
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

# Default set of files and directories to exclude when indexing GitLab code
# files. These are near-universally either vendored third-party code, machine-
# generated output, or minified/built artifacts that add cost and noise to
# retrieval (and inflate contextual-RAG LLM spend) without adding real signal.
#
# Patterns are matched via fnmatch. Patterns without a "/" are matched against
# every path segment, so a bare directory name like "node_modules" excludes at
# any depth. Patterns containing "/" are matched against the full path.
#
# Operators can extend this list via the GITLAB_CONNECTOR_EXCLUDE_PATTERNS
# environment variable (comma-separated).
DEFAULT_EXCLUDE_PATTERNS: list[str] = [
    # Historical entries.
    "logs",
    ".github/",
    ".gitlab/",
    ".pre-commit-config.yaml",
    # Vendored / third-party dependencies.
    "node_modules",
    "vendor",
    "bower_components",
    "third_party",
    "third-party",
    ".bundle",
    # Build / distribution output.
    "dist",
    "build",
    "out",
    "target",
    "public/assets",
    "public/packs",
    ".next",
    ".nuxt",
    ".turbo",
    ".cache",
    # Test / coverage output.
    "coverage",
    ".nyc_output",
    "htmlcov",
    # Minified assets.
    "*.min.js",
    "*.min.css",
    "*.min.map",
    "*.map",
    # Lockfiles (unhelpful for retrieval, large diffs on every bump).
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lock",
    "bun.lockb",
    "Gemfile.lock",
    "Cargo.lock",
    "poetry.lock",
    "uv.lock",
    "composer.lock",
    "Pipfile.lock",
    # Machine-generated code (Protobuf, gRPC).
    "*_pb.rb",
    "*_pb2.py",
    "*_pb2_grpc.py",
    "*.pb.go",
    "*_pb.js",
    "*_pb.ts",
    "*.pb.cc",
    "*.pb.h",
    # Binary / non-text assets that don't decode meaningfully.
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.ico",
    "*.svg",
    "*.pdf",
    "*.zip",
    "*.tar",
    "*.tar.gz",
    "*.tgz",
    "*.7z",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.eot",
    "*.mp3",
    "*.mp4",
    "*.mov",
    # Runtime state.
    "tmp",
    ".DS_Store",
]

# The effective exclude list is the built-in defaults plus any operator
# overrides supplied via GITLAB_CONNECTOR_EXCLUDE_PATTERNS.
exclude_patterns: list[str] = DEFAULT_EXCLUDE_PATTERNS + list(
    GITLAB_CONNECTOR_EXCLUDE_PATTERNS
)

# Upper bound on commits a single poll will diff. Above this, the poll falls back
# to a full tree walk: many commits usually mean a wide change set, and the walk
# costs fewer API calls than diffing every commit. Also caps the very first poll,
# which arrives with a window starting at the epoch.
MAX_POLL_COMMITS = 100


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


def _looks_like_binary(data: bytes, sample_size: int = 8192) -> bool:
    """Heuristic to detect binary content that shouldn't be indexed as text.

    Checks a leading sample for:
      - A NUL byte (definitive signal of binary content in text formats).
      - A high proportion (>30%) of bytes outside the printable ASCII / common
        whitespace range, which reliably flags encoded images, fonts, archives
        etc. even when they lack NUL bytes.

    UTF-8 encoded text of any language passes because valid multi-byte
    sequences are still counted as "text-like" per byte on average.
    """
    if not data:
        return False
    sample = data[:sample_size]
    if b"\x00" in sample:
        return True
    text_bytes = set(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D, 0x0C}
    non_text = sum(1 for b in sample if b not in text_bytes and b < 0x80)
    return (non_text / len(sample)) > 0.30


def _decode_file_content(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        # Fall back to latin-1 for legitimately text-encoded files that use
        # a legacy single-byte encoding. Guarded by the binary check above.
        return raw_bytes.decode("latin-1")


def _build_code_document(
    blob_id: str,
    file_name: str,
    file_path: str,
    file_content: str,
    url: str,
    project_name: str,
    project_owner: str,
    default_branch: str,
    doc_updated_at: datetime | None,
) -> Document:
    """Build a code-file Document.

    `doc_updated_at` is the commit time that last touched the blob, or None when
    the caller does not know it. Never use fetch time here: the indexing pipeline
    treats an advanced timestamp as proof of change and then skips its content
    hash check, so a fetch-time stamp re-embeds every file on every poll.
    """
    file_url = (
        f"{url}/{project_owner}/{project_name}/-/blob/{default_branch}/{file_path}"
    )

    return Document(
        id=blob_id,
        sections=[TextSection(link=file_url, text=file_content)],
        source=DocumentSource.GITLAB,
        semantic_identifier=file_name,
        doc_updated_at=doc_updated_at,
        primary_owners=[],  # Add owners if needed
        metadata={"type": "CodeFile"},
    )


def _convert_code_to_document(
    project: Project, file: Any, url: str, projectName: str, projectOwner: str
) -> Document | None:
    # Dynamically get the default branch from the project object
    default_branch = project.default_branch

    # Fetch the file content using the correct branch
    file_content_obj = project.files.get(
        file_path=file["path"],
        ref=default_branch,  # Use the default branch
    )
    raw_bytes = file_content_obj.decode()
    if _looks_like_binary(raw_bytes):
        # Skip binary blobs (images, fonts, archives, compiled artifacts).
        # The extension-based exclude list catches most of these up front,
        # but this is the last line of defense against binaries slipping
        # through with unrecognized extensions.
        logger.debug(
            "Skipping likely-binary GitLab file %s", file.get("path", "<unknown>")
        )
        return None

    return _build_code_document(
        blob_id=file["id"],
        file_name=file["name"],
        file_path=file["path"],
        file_content=_decode_file_content(raw_bytes),
        url=url,
        project_name=projectName,
        project_owner=projectOwner,
        default_branch=default_branch,
        # A full walk has no per-file commit time. Leaving this unset lets the
        # pipeline's content hash gate skip files whose bytes have not changed.
        doc_updated_at=None,
    )


def _fetch_code_document_by_path(
    project: Project,
    file_path: str,
    url: str,
    project_name: str,
    project_owner: str,
    doc_updated_at: datetime | None,
) -> Document | None:
    """Fetch one blob by path. Returns None when the path is gone or is binary.

    The blob id returned here is the same git object id that `repository_tree`
    reports as `id`, so a document built by a poll and one built by a full walk
    share an id. Pruning relies on that: it enumerates ids with `load_from_state`
    and deletes indexed ids the walk does not produce.
    """
    default_branch = project.default_branch

    try:
        file_content_obj = project.files.get(file_path=file_path, ref=default_branch)
    except GitlabGetError as e:
        if e.response_code == 404:
            # The branch moved between listing the commit and reading the blob.
            logger.debug("Skipping %s: not present on %s", file_path, default_branch)
            return None
        raise

    raw_bytes = file_content_obj.decode()
    if _looks_like_binary(raw_bytes):
        # Apply the same guard as the full walk, so a poll and a walk agree on
        # which blobs produce a document.
        logger.debug("Skipping likely-binary GitLab file %s", file_path)
        return None

    return _build_code_document(
        blob_id=file_content_obj.blob_id,
        file_name=file_content_obj.file_name,
        file_path=file_path,
        file_content=_decode_file_content(raw_bytes),
        url=url,
        project_name=project_name,
        project_owner=project_owner,
        default_branch=default_branch,
        doc_updated_at=doc_updated_at,
    )


def _changed_paths_in_window(
    project: Project, start: datetime, end: datetime
) -> dict[str, datetime] | None:
    """Map each path changed on the default branch in [start, end] to its commit time.

    Returns None when the change set cannot be determined and the caller must fall
    back to a full tree walk. An empty dict means the window held no commits, so
    there is nothing to re-index.

    Deleted paths are left out. `poll_source` cannot express a deletion — it only
    yields documents that exist — so the pruning job removes those documents.
    """
    default_branch = project.default_branch
    if not default_branch:
        logger.warning("Project has no default branch; falling back to a full walk")
        return None

    try:
        commits = list(
            project.commits.list(
                ref_name=default_branch,
                since=start.isoformat(),
                until=end.isoformat(),
                page=1,
                per_page=MAX_POLL_COMMITS,
            )
        )
    except GitlabError:
        logger.exception("Listing commits failed; falling back to a full walk")
        return None

    if len(commits) >= MAX_POLL_COMMITS:
        logger.info(
            "Window holds at least %s commits; falling back to a full walk",
            MAX_POLL_COMMITS,
        )
        return None

    path_to_updated_at: dict[str, datetime] = {}
    for commit in commits:
        # Fall back to the window end so an unparseable commit date still yields
        # the file rather than dropping the change.
        committed_at = _gitlab_datetime_to_utc(commit.committed_date) or end
        try:
            # For a merge commit GitLab diffs against the first parent, so a
            # branch merged into the window contributes all of its changes even
            # when its own commits are older than the window.
            diffs = commit.diff(get_all=True)
        except GitlabError:
            logger.exception(
                "Diffing commit %s failed; falling back to a full walk", commit.id
            )
            return None

        for diff in diffs:
            if diff.get("deleted_file"):
                continue
            # A rename reports the destination in new_path; the source path's
            # document keeps its own id and the pruning job removes it.
            path = diff.get("new_path") or diff.get("old_path")
            if not path:
                continue
            known_at = path_to_updated_at.get(path)
            if known_at is None or committed_at > known_at:
                path_to_updated_at[path] = committed_at

    return path_to_updated_at


def _should_exclude(path: str) -> bool:
    """Check if a path matches any of the exclude patterns.

    Matching rules:
      - Patterns containing "/" match against the full path via fnmatch, and
        also against anything nested under it. Trailing-slash patterns like
        ".github/" are normalized to ".github" and treated as directory-name
        patterns.
      - Patterns without "/" match against any path segment, so a bare
        directory or file name (e.g. "node_modules", "*.min.js") excludes
        at any depth in the tree.
    """
    segments = path.split("/")
    for raw_pattern in exclude_patterns:
        pattern = raw_pattern.rstrip("/")
        if not pattern:
            continue
        if "/" in pattern:
            # Match the directory entry itself and everything under it, so
            # "public/assets" excludes "public/assets/main.css" too.
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, f"{pattern}/*"):
                return True
            continue
        if any(fnmatch.fnmatch(segment, pattern) for segment in segments):
            return True
    return False


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
    ) -> None:
        self.project_owner = project_owner
        self.project_name = project_name
        self.batch_size = batch_size
        self.state_filter = state_filter
        self.include_mrs = include_mrs
        self.include_issues = include_issues
        self.include_code_files = include_code_files
        self.gitlab_client: gitlab.Gitlab | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.gitlab_client = gitlab.Gitlab(
            credentials["gitlab_url"], private_token=credentials["gitlab_access_token"]
        )
        return None

    def _walk_all_code_files(self, project: Project) -> GenerateDocumentsOutput:
        """Yield every blob on the default branch.

        The pruning job calls `load_from_state` to enumerate the ids that still
        exist and deletes any indexed id this walk does not produce. It must stay
        complete, so a partial result here would delete live documents.
        """
        assert self.gitlab_client is not None

        # Fetching using BFS as project.report_tree with recursion causing slow load
        queue = deque([""])  # Start with the root directory
        while queue:
            current_path = queue.popleft()
            files = project.repository_tree(path=current_path, all=True)
            for file_batch in _batch_gitlab_objects(files, self.batch_size):
                code_doc_batch: list[Document | HierarchyNode] = []
                for file in file_batch:
                    if _should_exclude(file["path"]):
                        continue

                    if file["type"] == "blob":
                        code_doc = _convert_code_to_document(
                            project,
                            file,
                            self.gitlab_client.url,
                            self.project_name,
                            self.project_owner,
                        )
                        if code_doc is not None:
                            code_doc_batch.append(code_doc)
                    elif file["type"] == "tree":
                        queue.append(file["path"])

                if code_doc_batch:
                    yield code_doc_batch

    def _fetch_changed_code_files(
        self, project: Project, path_to_updated_at: dict[str, datetime]
    ) -> GenerateDocumentsOutput:
        """Yield only the blobs the poll window changed."""
        assert self.gitlab_client is not None

        paths = [
            path for path in sorted(path_to_updated_at) if not _should_exclude(path)
        ]
        for path_batch in _batch_gitlab_objects(paths, self.batch_size):
            code_doc_batch: list[Document | HierarchyNode] = []
            for path in path_batch:
                doc = _fetch_code_document_by_path(
                    project,
                    path,
                    self.gitlab_client.url,
                    self.project_name,
                    self.project_owner,
                    path_to_updated_at[path],
                )
                if doc is not None:
                    code_doc_batch.append(doc)

            if code_doc_batch:
                yield code_doc_batch

    def _fetch_code_files(
        self, project: Project, start: datetime | None, end: datetime | None
    ) -> GenerateDocumentsOutput:
        if start is None or end is None:
            yield from self._walk_all_code_files(project)
            return

        path_to_updated_at = _changed_paths_in_window(project, start, end)
        if path_to_updated_at is None:
            yield from self._walk_all_code_files(project)
            return

        logger.info(
            "Poll window changed %s code file(s) in %s/%s",
            len(path_to_updated_at),
            self.project_owner,
            self.project_name,
        )
        yield from self._fetch_changed_code_files(project, path_to_updated_at)

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
            yield from self._fetch_code_files(project, start, end)

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
    )

    connector.load_credentials(
        {
            "gitlab_access_token": os.environ["GITLAB_ACCESS_TOKEN"],
            "gitlab_url": os.environ["GITLAB_URL"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
