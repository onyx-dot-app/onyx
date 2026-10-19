import copy
import os
import re
from collections.abc import Callable, Generator, Iterator
from datetime import datetime, timedelta, timezone
from enum import Enum
from io import BytesIO
from typing import Any, TypeVar

from pydantic import BaseModel
from typing_extensions import override

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import CheckpointOutputWrapper, ConnectorRunner
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.cross_connector_utils.miscellaneous_utils import reindex_failure
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
    ValidationError,
)
from onyx.connectors.github.models import (
    GitHubCursorItem,
    GitHubFileContent,
    GitHubGitTree,
    GitHubIssue,
    GitHubPullRequest,
    GitHubRepository,
    GitHubUser,
    SerializedRepository,
)
from onyx.connectors.github.rate_limit_utils import sleep_after_rate_limit_exception
from onyx.connectors.github.source_operations import (
    GitHubApiError,
    GitHubRateLimitError,
    GitHubSourceOperations,
)
from onyx.connectors.github.utils import (
    get_external_access_permission,
    parse_repository_names,
    resolve_github_base_url,
)
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    ConnectorCheckpoint,
    ConnectorFailure,
    GenerateSlimDocumentOutput,
    IndexingHeartbeatInterface,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.file_processing.extract_file_text import file_io_to_text, is_text_file
from onyx.utils.logger import setup_logger

logger = setup_logger()

CURSOR_LOG_FREQUENCY = 50

_MAX_NUM_RATE_LIMIT_RETRIES = 5
# Profiles the connector keeps for the user fields of the metadata. The cache
# starts over when it is full.
_MAX_CACHED_USERS = 10_000

ONE_DAY = timedelta(days=1)
SLIM_BATCH_SIZE = 100

# Prose document extensions eligible for document indexing. Intentionally
# limited to human-readable docs — source code as well as data/config/log
# formats (.json, .csv, .tsv, .xml, .yml, .yaml, .sql, .log, .conf) are
# excluded, as they are rarely useful to search as documents.
GITHUB_INDEXABLE_FILE_EXTENSIONS = {
    ".md",
    ".mdx",
    ".markdown",
    ".rst",
    ".txt",
}
# Common documentation files that conventionally have no extension. Matched
# case-insensitively against the file's basename (stem before any extension).
GITHUB_INDEXABLE_FILENAMES = {
    "readme",
    "license",
    "licence",
    "changelog",
    "contributing",
    "authors",
    "notice",
    "copying",
    "install",
    "maintainers",
    "codeowners",
    "security",
    "support",
}
# Path segments whose presence anywhere in a file's path excludes it.
GITHUB_PATH_DENYLIST = {
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".venv",
    "__pycache__",
}
# Skip files larger than this (checked against the git tree size before fetching).
GITHUB_MAX_FILE_SIZE_BYTES = 1_000_000
# Number of files emitted per checkpoint batch in the FILES stage.
FILE_BATCH_SIZE = 100

_GITHUB_EMPTY_REPOSITORY_TREE_STATUS = 409
_GITHUB_EMPTY_REPOSITORY_TREE_MESSAGE = "Git Repository is empty."


def is_indexable_path(path: str, size: int | None) -> bool:
    """Pure predicate: should this repo file be indexed?

    Filters on a max size and path-segment denylist, then matches either a
    document extension (.md, .txt, ...) or a conventional extensionless
    document basename (README, LICENSE, ...).
    """
    if size is not None and size > GITHUB_MAX_FILE_SIZE_BYTES:
        return False

    segments = set(path.split("/"))
    if segments & GITHUB_PATH_DENYLIST:
        return False

    basename = path.rsplit("/", 1)[-1]
    _, extension = os.path.splitext(basename)
    if extension.lower() in GITHUB_INDEXABLE_FILE_EXTENSIONS:
        return True

    # Extensionless docs like README / LICENSE (basename has no extension).
    if not extension and basename.lower() in GITHUB_INDEXABLE_FILENAMES:
        return True

    return False


# Cases
# X (from start) standard run, no fallback to cursor-based pagination
# X (from start) standard run errors, fallback to cursor-based pagination
#  X error in the middle of a page
#  X no errors: run to completion
# X (from checkpoint) standard run, no fallback to cursor-based pagination
# X (from checkpoint) continue from cursor-based pagination
#  - retrying
#  - no retrying

# things to check:
# checkpoint state on return
# checkpoint progress (no infinite loop)


class DocMetadata(BaseModel):
    repo: str


_ItemT = TypeVar("_ItemT", GitHubPullRequest, GitHubIssue)


def _paginate_until_error(
    # Iterates by cursor from a cursor URL (None: the first page), skipping
    # the given number of items.
    iter_by_cursor: Callable[[str | None, int], Iterator[GitHubCursorItem[_ItemT]]],
    cursor_url: str | None,
    prev_num_objs: int,
    cursor_url_callback: Callable[[str | None, int], None],
    retrying: bool = False,
) -> Generator[_ItemT, None, None]:
    num_objs = prev_num_objs
    skip = 0
    if not cursor_url and retrying:
        # if we are retrying, we want to skip the objects retrieved
        # over previous calls. Unfortunately, this WILL retrieve all
        # pages before the one we are resuming from, so we really
        # don't want this case to be hit often
        logger.warning(
            "Retrying from a previous cursor-based pagination call. "
            "This will retrieve all pages before the one we are resuming from, "
            "which may take a while and consume many API calls."
        )
        skip = prev_num_objs
        num_objs = 0

    # Before the first page arrives, the first page is the next page to read.
    has_next_page = True
    try:
        # this for loop handles cursor-based pagination
        for cursor_item in iter_by_cursor(cursor_url, skip):
            num_objs += 1
            has_next_page = cursor_item.next_url is not None
            yield cursor_item.item
            # used to store the current cursor url in the checkpoint. This value
            # is updated during iteration.
            cursor_url_callback(cursor_item.next_url, num_objs)

            if num_objs % CURSOR_LOG_FREQUENCY == 0:
                logger.info(
                    "Retrieved %s objects with current cursor url: %s",
                    num_objs,
                    cursor_item.next_url,
                )

    except Exception as e:
        logger.exception("Error during cursor-based pagination: %s", e)
        if num_objs - prev_num_objs > 0:
            raise

        if has_next_page and not retrying:
            logger.info(
                "Assuming that this error is due to cursor "
                "expiration because no objects were retrieved. "
                "Retrying from the first page."
            )
            yield from _paginate_until_error(
                iter_by_cursor, None, prev_num_objs, cursor_url_callback, retrying=True
            )
            return

        # for no cursor url or if we reach this point after a retry, raise the error
        raise


def is_cursor_pagination_required(error: GitHubApiError) -> bool:
    """GitHub refuses offset pages for a large listing; indexing then
    switches to cursor pages."""
    return error.status_code == 422 and "cursor" in (
        f"{error.github_message or ''} {error}"
    )


def _get_batch_rate_limited(
    fetch_page: Callable[[int], list[_ItemT]],
    iter_by_cursor: Callable[[str | None, int], Iterator[GitHubCursorItem[_ItemT]]],
    page_num: int,
    cursor_url: str | None,
    prev_num_objs: int,
    cursor_url_callback: Callable[[str | None, int], None],
    source_operations: GitHubSourceOperations,
    detail: Callable[[_ItemT], _ItemT] | None = None,
    attempt_num: int = 0,
) -> Generator[_ItemT, None, None]:
    """Yields one page of pull requests or issues. ``detail`` reads each item
    of an offset page on its own, inside the rate-limit retry, for the fields
    a listing leaves out."""
    if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
        raise RuntimeError(
            "Re-tried fetching batch too many times. Something is going wrong with fetching objects from Github"
        )
    try:
        if cursor_url:
            # when this is set, we are resuming from an earlier
            # cursor-based pagination call.
            yield from _paginate_until_error(
                iter_by_cursor, cursor_url, prev_num_objs, cursor_url_callback
            )
            return
        objs = fetch_page(page_num)
        if detail is not None:
            objs = [detail(obj) for obj in objs]
        yield from objs
    except GitHubRateLimitError:
        sleep_after_rate_limit_exception(source_operations)
        yield from _get_batch_rate_limited(
            fetch_page,
            iter_by_cursor,
            page_num,
            cursor_url,
            prev_num_objs,
            cursor_url_callback,
            source_operations,
            detail,
            attempt_num + 1,
        )
    except GitHubApiError as e:
        if e.status_code == 404:
            # 404 on the listing endpoint means the collection is unavailable
            # for this repo (e.g. pull requests or issues are disabled on a
            # mirror). Treat it as empty so the connector skips the stage
            # instead of crashing.
            logger.warning(
                "Got 404 listing objects (page %s); treating as empty. "
                "The pull requests or issues feature is likely disabled for this repo.",
                page_num,
            )
            return
        if not is_cursor_pagination_required(e):
            raise
        # Fallback to a cursor-based pagination strategy
        # This can happen for "large datasets," but there's no documentation
        # On the error on the web as far as we can tell.
        # Error message:
        # "Pagination with the page parameter is not supported for large datasets,
        # please use cursor based pagination (after/before)"
        yield from _paginate_until_error(
            iter_by_cursor, cursor_url, prev_num_objs, cursor_url_callback
        )


# Reads the profile of a login, for the user fields of the metadata. None when
# the profile cannot be read.
UserLookup = Callable[[str], GitHubUser | None]


def _get_userinfo(login: str, lookup_user: UserLookup) -> dict[str, str]:
    user: GitHubUser | None = lookup_user(login)
    return {
        k: v
        for k, v in {
            "login": login,
            "name": user.name if user else None,
            "email": user.email if user else None,
        }.items()
        if v is not None
    }


def _utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value else None


# A document id is the object's web URL: a pull request, an issue, or a file at
# a branch. The branch of a file URL is split off against the connector's branch,
# since a branch name may itself contain slashes.
_DOCUMENT_URL = re.compile(
    r"^https?://[^/]+/(?P<owner>[^/]+)/(?P<repo>[^/]+)/"
    r"(?:(?P<kind>pull|issues)/(?P<number>\d+)|blob/.+)$"
)


def _file_url(repo: GitHubRepository, branch: str, path: str) -> str:
    """A file's web URL, which is its document id."""
    return f"{repo.html_url}/blob/{branch}/{path}"


def _convert_pr_to_document(
    pull_request: GitHubPullRequest,
    repo_external_access: ExternalAccess | None,
    lookup_user: UserLookup,
) -> Document:
    repo_full_name = pull_request.base_repo_full_name or ""
    # Split full_name (e.g., "owner/repo") into owner and repo
    parts = repo_full_name.split("/", 1)
    owner_name = parts[0] if parts else ""
    repo_name = parts[1] if len(parts) > 1 else repo_full_name

    doc_metadata = {
        "repo": repo_full_name,
        "hierarchy": {
            "source_path": [owner_name, repo_name, "pull_requests"],
            "owner": owner_name,
            "repo": repo_name,
            "object_type": "pull_request",
        },
    }
    return Document(
        id=pull_request.html_url,
        sections=[
            TextSection(link=pull_request.html_url, text=pull_request.body or "")
        ],
        external_access=repo_external_access,
        source=DocumentSource.GITHUB,
        semantic_identifier=f"{pull_request.number}: {pull_request.title}",
        # updated_at is UTC time but is timezone unaware, explicitly add UTC
        # as there is logic in indexing to prevent wrong timestamped docs
        # due to local time discrepancies with UTC
        doc_updated_at=_utc(pull_request.updated_at),
        doc_created_at=_utc(pull_request.created_at),
        # this metadata is used in perm sync
        doc_metadata=doc_metadata,
        metadata={
            k: [str(vi) for vi in v] if isinstance(v, list) else str(v)
            for k, v in {
                "object_type": "PullRequest",
                "id": pull_request.number,
                "merged": pull_request.merged,
                "state": pull_request.state,
                "user": (
                    _get_userinfo(pull_request.user_login, lookup_user)
                    if pull_request.user_login
                    else None
                ),
                "assignees": [
                    _get_userinfo(assignee, lookup_user)
                    for assignee in pull_request.assignee_logins
                ],
                "repo": pull_request.base_repo_full_name,
                "num_commits": str(pull_request.commits),
                "num_files_changed": str(pull_request.changed_files),
                "labels": pull_request.label_names,
                "created_at": _utc(pull_request.created_at),
                "updated_at": _utc(pull_request.updated_at),
                "closed_at": _utc(pull_request.closed_at),
                "merged_at": _utc(pull_request.merged_at),
                "merged_by": (
                    _get_userinfo(pull_request.merged_by_login, lookup_user)
                    if pull_request.merged_by_login
                    else None
                ),
            }.items()
            if v is not None
        },
    )


def _convert_issue_to_document(
    issue: GitHubIssue,
    repo_external_access: ExternalAccess | None,
    lookup_user: UserLookup,
) -> Document:
    repo_full_name = issue.repo_full_name
    # Split full_name (e.g., "owner/repo") into owner and repo
    parts = repo_full_name.split("/", 1)
    owner_name = parts[0] if parts else ""
    repo_name = parts[1] if len(parts) > 1 else repo_full_name

    doc_metadata = {
        "repo": repo_full_name,
        "hierarchy": {
            "source_path": [owner_name, repo_name, "issues"],
            "owner": owner_name,
            "repo": repo_name,
            "object_type": "issue",
        },
    }
    return Document(
        id=issue.html_url,
        sections=[TextSection(link=issue.html_url, text=issue.body or "")],
        source=DocumentSource.GITHUB,
        external_access=repo_external_access,
        semantic_identifier=f"{issue.number}: {issue.title}",
        # updated_at is UTC time but is timezone unaware
        doc_updated_at=issue.updated_at.replace(tzinfo=timezone.utc),
        doc_created_at=_utc(issue.created_at),
        # this metadata is used in perm sync
        doc_metadata=doc_metadata,
        metadata={
            k: [str(vi) for vi in v] if isinstance(v, list) else str(v)
            for k, v in {
                "object_type": "Issue",
                "id": issue.number,
                "state": issue.state,
                "user": (
                    _get_userinfo(issue.user_login, lookup_user)
                    if issue.user_login
                    else None
                ),
                "assignees": [
                    _get_userinfo(assignee, lookup_user)
                    for assignee in issue.assignee_logins
                ],
                "repo": issue.repo_full_name,
                "labels": issue.label_names,
                "created_at": _utc(issue.created_at),
                "updated_at": _utc(issue.updated_at),
                "closed_at": _utc(issue.closed_at),
                "closed_by": (
                    _get_userinfo(issue.closed_by_login, lookup_user)
                    if issue.closed_by_login
                    else None
                ),
            }.items()
            if v is not None
        },
    )


def _decode_file_content(raw: bytes) -> str | None:
    """Decode raw file bytes to text, or None if the content looks binary."""
    buf = BytesIO(raw)
    if not is_text_file(buf):
        return None
    return file_io_to_text(buf)


def _convert_file_to_document(
    repo: GitHubRepository,
    path: str,
    content_text: str,
    repo_external_access: ExternalAccess | None,
    branch: str,
) -> Document:
    repo_full_name = repo.full_name
    parts = repo_full_name.split("/", 1)
    owner_name = parts[0] if parts else ""
    repo_name = parts[1] if len(parts) > 1 else repo_full_name

    html_url = _file_url(repo, branch, path)
    _, extension = os.path.splitext(path)

    # NOTE: GitHub's tree API does not expose per-file modification times without
    # additional per-file commit-history calls. repo.pushed_at is the closest
    # proxy available without extra API requests, but it reflects any push to
    # any branch, so every file in the repo shares the same timestamp.
    updated_at = repo.pushed_at.replace(tzinfo=timezone.utc) if repo.pushed_at else None

    doc_metadata = {
        "repo": repo_full_name,
        "hierarchy": {
            "source_path": [owner_name, repo_name, "files", *path.split("/")],
            "owner": owner_name,
            "repo": repo_name,
            "object_type": "file",
        },
    }
    return Document(
        id=html_url,
        sections=[TextSection(link=html_url, text=content_text)],
        source=DocumentSource.GITHUB,
        external_access=repo_external_access,
        semantic_identifier=path,
        doc_updated_at=updated_at,
        doc_metadata=doc_metadata,
        metadata={
            "object_type": "File",
            "repo": repo_full_name,
            "path": path,
            "file_extension": extension.lower(),
            "branch": branch,
        },
    )


class GithubConnectorStage(Enum):
    START = "start"
    PRS = "prs"
    ISSUES = "issues"
    FILES = "files"


class GithubConnectorCheckpoint(ConnectorCheckpoint):
    stage: GithubConnectorStage
    curr_page: int

    cached_repo_ids: list[int] | None = None
    cached_repo: SerializedRepository | None = None

    # Resolved + filtered file paths for the current repo's FILES stage.
    # Populated once when the stage begins, then paginated via curr_page.
    file_paths: list[str] | None = None
    # Branch file_paths was listed from; a resumed checkpoint whose branch no
    # longer matches (connector edited, default branch changed) is re-listed.
    file_paths_branch: str | None = None

    # Used for the fallback cursor-based pagination strategy
    num_retrieved: int
    cursor_url: str | None = None

    def reset(self) -> None:
        """
        Resets curr_page, num_retrieved, cursor_url, file_paths, and
        file_paths_branch to their initial values (0, 0, None, None, None)
        """
        self.curr_page = 0
        self.num_retrieved = 0
        self.cursor_url = None
        self.file_paths = None
        self.file_paths_branch = None


def make_cursor_url_callback(
    checkpoint: GithubConnectorCheckpoint,
) -> Callable[[str | None, int], None]:
    def cursor_url_callback(cursor_url: str | None, num_objs: int) -> None:
        # we want to maintain the old cursor url so code after retrieval
        # can determine that we are using the fallback cursor-based pagination strategy
        if cursor_url:
            checkpoint.cursor_url = cursor_url
        checkpoint.num_retrieved = num_objs

    return cursor_url_callback


class GithubConnector(
    CheckpointedConnectorWithPermSync[GithubConnectorCheckpoint],
    SlimConnector,
    SlimConnectorWithPermSync,
    Resolver,
):
    def __init__(
        self,
        repo_owner: str,
        repositories: str | None = None,
        state_filter: str = "all",
        include_prs: bool = True,
        include_issues: bool = False,
        include_files: bool = False,
        branch: str | None = None,
    ) -> None:
        self.repo_owner = repo_owner.strip()
        # None means every repository of the owner, also for a list of only
        # commas.
        self.repositories = (
            (repositories or "").strip()
            if parse_repository_names(repositories)
            else None
        )
        self.state_filter = state_filter
        self.include_prs = include_prs
        self.include_issues = include_issues
        self.include_files = include_files
        # Branch to index files from; None means each repo's default branch.
        self.branch = (branch or "").strip() or None
        self._source_operations: GitHubSourceOperations | None = None
        # Profiles read for the user fields of the metadata, by login. None
        # marks a profile that could not be read.
        self._user_cache: dict[str, GitHubUser | None] = {}

    @property
    def source_operations(self) -> GitHubSourceOperations:
        if self._source_operations is None:
            raise ConnectorMissingCredentialError("GitHub")
        return self._source_operations

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # Raises ConnectorValidationError for an unsafe Enterprise Server URL
        # now, not on the first call.
        resolve_github_base_url(credentials)
        self._source_operations = GitHubSourceOperations(
            credentials_provider=OnyxStaticCredentialsProvider(
                None, DocumentSource.GITHUB.value, credentials
            ),
        )
        return None

    def _lookup_user(self, login: str) -> GitHubUser | None:
        """The profile of a login, read once per connector. A profile that
        cannot be read leaves only the login in the metadata."""
        if login not in self._user_cache:
            if len(self._user_cache) >= _MAX_CACHED_USERS:
                self._user_cache.clear()
            try:
                self._user_cache[login] = self.source_operations.get_user(login=login)
            except GitHubApiError:
                logger.debug("Error getting profile for user %s", login)
                self._user_cache[login] = None
        return self._user_cache[login]

    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        """Reads each failed pull request, issue or file again from its web
        URL, which is its document id. A file is read at the connector's
        branch, so one indexed from another branch stays a failure."""
        repos: dict[str, tuple[GitHubRepository, ExternalAccess | None]] = {}
        for error in errors:
            failed = error.failed_document
            if failed is None:
                continue
            try:
                yield self._reindex_target(
                    failed.document_id, repos, include_permissions
                )
            except Exception as e:
                logger.warning(
                    "Failed to resolve GitHub target %s: %s", failed.document_id, e
                )
                yield reindex_failure(failed, str(e), e)

    def _reindex_target(
        self,
        url: str,
        repos: dict[str, tuple[GitHubRepository, ExternalAccess | None]],
        include_permissions: bool,
        attempt_num: int = 0,
    ) -> Document:
        try:
            return self._reindex_document(url, repos, include_permissions)
        except GitHubRateLimitError:
            if attempt_num >= _MAX_NUM_RATE_LIMIT_RETRIES:
                raise
            sleep_after_rate_limit_exception(self.source_operations)
            return self._reindex_target(
                url, repos, include_permissions, attempt_num + 1
            )

    def _reindex_document(
        self,
        url: str,
        repos: dict[str, tuple[GitHubRepository, ExternalAccess | None]],
        include_permissions: bool,
    ) -> Document:
        match = _DOCUMENT_URL.match(url)
        if match is None:
            raise ValueError(f"Not a GitHub document URL: {url}")
        full_name = f"{match['owner']}/{match['repo']}"
        if full_name not in repos:
            repo = self.source_operations.get_repository(
                owner=match["owner"], name=match["repo"]
            )
            repos[full_name] = (
                repo,
                get_external_access_permission(repo) if include_permissions else None,
            )
        repo, access = repos[full_name]
        if match["kind"] == "pull":
            document = _convert_pr_to_document(
                self.source_operations.get_pull_request(
                    repo_full_name=full_name, number=int(match["number"])
                ),
                access,
                self._lookup_user,
            )
        elif match["kind"] == "issues":
            document = _convert_issue_to_document(
                self.source_operations.get_issue(
                    repo_full_name=full_name, number=int(match["number"])
                ),
                access,
                self._lookup_user,
            )
        else:
            document = self._reindex_file(repo, url, access)
        if document.id != url:
            raise ValueError(f"GitHub now serves this document as {document.id}")
        return document

    def _reindex_file(
        self, repo: GitHubRepository, url: str, access: ExternalAccess | None
    ) -> Document:
        branch = self._resolve_branch(repo)
        prefix = _file_url(repo, branch, "")
        if not url.startswith(prefix):
            raise ValueError(f"The file is not on the connector's branch {branch!r}")
        path = url[len(prefix) :]
        content_text = _decode_file_content(self._fetch_file_content(repo, path))
        if content_text is None:
            raise ValueError(f"Non-text or undecodable file: {path}")
        return _convert_file_to_document(repo, path, content_text, access, branch)

    def get_github_repo(self, attempt_num: int = 0) -> GitHubRepository:
        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError(
                "Re-tried fetching repo too many times. Something is going wrong with fetching objects from Github"
            )

        try:
            return self.source_operations.get_repository(
                owner=self.repo_owner, name=self.repositories or ""
            )
        except GitHubRateLimitError:
            sleep_after_rate_limit_exception(self.source_operations)
            return self.get_github_repo(attempt_num + 1)

    def get_github_repos(self, attempt_num: int = 0) -> list[GitHubRepository]:
        """Get specific repositories based on comma-separated repo_name string."""
        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError(
                "Re-tried fetching repos too many times. Something is going wrong with fetching objects from Github"
            )

        try:
            repos = []
            for repo_name in parse_repository_names(self.repositories):
                try:
                    repo = self.source_operations.get_repository(
                        owner=self.repo_owner, name=repo_name
                    )
                    repos.append(repo)
                except GitHubRateLimitError:
                    raise
                except GitHubApiError as e:
                    logger.warning(
                        "Could not fetch repo %s/%s: %s",
                        self.repo_owner,
                        repo_name,
                        e,
                    )

            return repos
        except GitHubRateLimitError:
            sleep_after_rate_limit_exception(self.source_operations)
            return self.get_github_repos(attempt_num + 1)

    def get_all_repos(self, attempt_num: int = 0) -> list[GitHubRepository]:
        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError(
                "Re-tried fetching repos too many times. Something is going wrong with fetching objects from Github"
            )

        try:
            # Try to get organization first
            try:
                self.source_operations.get_organization(login=self.repo_owner)
                return self.source_operations.list_organization_repositories(
                    org_login=self.repo_owner
                )
            except GitHubRateLimitError:
                raise
            except GitHubApiError:
                # If not an org, try as a user
                return self.source_operations.list_user_repositories(
                    login=self.repo_owner
                )
        except GitHubRateLimitError:
            sleep_after_rate_limit_exception(self.source_operations)
            return self.get_all_repos(attempt_num + 1)

    def fetch_configured_repos(self) -> list[GitHubRepository]:
        """
        Fetch the configured repositories based on the connector settings.

        Returns:
            list[GitHubRepository]: The configured repositories.
        """
        if self.repositories:
            if "," in self.repositories:
                return self.get_github_repos()
            else:
                return [self.get_github_repo()]
        else:
            return self.get_all_repos()

    def _pull_request_listers(
        self, repo: GitHubRepository
    ) -> tuple[
        Callable[[int], list[GitHubPullRequest]],
        Callable[[str | None, int], Iterator[GitHubCursorItem[GitHubPullRequest]]],
    ]:
        source_operations = self.source_operations

        def fetch_page(page: int) -> list[GitHubPullRequest]:
            return source_operations.list_pull_requests(
                repo_full_name=repo.full_name, state=self.state_filter, page=page
            )

        def iter_by_cursor(
            cursor_url: str | None, skip: int
        ) -> Iterator[GitHubCursorItem[GitHubPullRequest]]:
            return source_operations.iter_pull_requests_by_cursor(
                repo_full_name=repo.full_name,
                state=self.state_filter,
                cursor_url=cursor_url,
                skip=skip,
            )

        return fetch_page, iter_by_cursor

    def _issue_listers(
        self, repo: GitHubRepository
    ) -> tuple[
        Callable[[int], list[GitHubIssue]],
        Callable[[str | None, int], Iterator[GitHubCursorItem[GitHubIssue]]],
    ]:
        source_operations = self.source_operations

        def fetch_page(page: int) -> list[GitHubIssue]:
            return source_operations.list_issues(
                repo_full_name=repo.full_name, state=self.state_filter, page=page
            )

        def iter_by_cursor(
            cursor_url: str | None, skip: int
        ) -> Iterator[GitHubCursorItem[GitHubIssue]]:
            return source_operations.iter_issues_by_cursor(
                repo_full_name=repo.full_name,
                state=self.state_filter,
                cursor_url=cursor_url,
                skip=skip,
            )

        return fetch_page, iter_by_cursor

    def _detailed_pull_request(
        self, pull_request: GitHubPullRequest
    ) -> GitHubPullRequest:
        if pull_request.detailed or pull_request.base_repo_full_name is None:
            return pull_request
        return self.source_operations.get_pull_request(
            repo_full_name=pull_request.base_repo_full_name,
            number=pull_request.number,
        )

    def _detailed_issue(self, issue: GitHubIssue) -> GitHubIssue:
        if issue.detailed:
            return issue
        return self.source_operations.get_issue(
            repo_full_name=issue.repo_full_name, number=issue.number
        )

    def _resolve_branch(self, repo: GitHubRepository) -> str:
        return self.branch or repo.default_branch or ""

    def _list_indexable_files(
        self, repo: GitHubRepository, attempt_num: int = 0
    ) -> tuple[list[str], bool]:
        """Resolve the configured (or default) branch tree and return indexable file paths.

        Returns (sorted paths, truncated) where `truncated` is True when GitHub
        capped the recursive tree (>100k entries or >7MB), meaning some files
        could not be enumerated and will be missing from the index.
        """
        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError(
                "Re-tried listing repo files too many times. "
                "Something is going wrong with fetching objects from Github"
            )
        try:
            git_tree: GitHubGitTree = self.source_operations.get_git_tree(
                repo_full_name=repo.full_name, ref=self._resolve_branch(repo)
            )
            truncated = git_tree.truncated
            if truncated:
                logger.error(
                    "Git tree for repo %s was truncated by GitHub; "
                    "some files will not be indexed",
                    repo.full_name,
                )
            paths = [
                element.path
                for element in git_tree.entries
                if element.type == "blob"
                and is_indexable_path(element.path, element.size)
            ]
            paths.sort()
            return paths, truncated
        except GitHubRateLimitError:
            sleep_after_rate_limit_exception(self.source_operations)
            return self._list_indexable_files(repo, attempt_num + 1)
        except GitHubApiError as e:
            if e.status_code == 404 and self.branch:
                raise ConnectorValidationError(
                    f"Branch '{self.branch}' not found in repository "
                    f"{repo.full_name}. Leave the branch setting blank to use "
                    f"the repository's default branch."
                ) from e

            if not (
                e.status_code == _GITHUB_EMPTY_REPOSITORY_TREE_STATUS
                and e.github_message == _GITHUB_EMPTY_REPOSITORY_TREE_MESSAGE
            ):
                raise

            logger.info(
                "Skipping files for empty repo: %s",
                repo.full_name,
            )
            return [], False

    def _fetch_file_content(
        self, repo: GitHubRepository, path: str, attempt_num: int = 0
    ) -> bytes:
        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError(
                "Re-tried fetching file content too many times. "
                "Something is going wrong with fetching objects from Github"
            )
        try:
            content: GitHubFileContent = self.source_operations.get_file_content(
                repo_full_name=repo.full_name,
                path=path,
                ref=self._resolve_branch(repo),
            )
            if content.content is None:
                raise ValueError(
                    f"Could not decode content for {path} "
                    f"(encoding={content.encoding!r})"
                )
            return content.content
        except GitHubRateLimitError:
            sleep_after_rate_limit_exception(self.source_operations)
            return self._fetch_file_content(repo, path, attempt_num + 1)

    def _fetch_repo_files(
        self,
        repo: GitHubRepository,
        checkpoint: GithubConnectorCheckpoint,
        start: datetime | None,
        is_slim: bool,
        repo_external_access: ExternalAccess | None,
    ) -> Generator[Document | ConnectorFailure, None, bool]:
        """Emit one batch of indexable documents for `repo`, advancing the checkpoint.

        On first entry for a repo (file_paths is None) it resolves and caches the
        filtered file list, applying the pushed_at gate and surfacing tree
        truncation as a failure. Returns True if more file batches remain (the
        caller should return the checkpoint to resume), False once drained.
        """
        branch = self._resolve_branch(repo)
        branch_changed = (
            checkpoint.file_paths is not None and checkpoint.file_paths_branch != branch
        )
        if branch_changed:
            # The cached listing came from a different branch (resumed
            # checkpoint after a connector edit or default-branch change) —
            # discard it so paths and content come from the same branch.
            checkpoint.file_paths = None
            checkpoint.file_paths_branch = None
            checkpoint.curr_page = 0

        if checkpoint.file_paths is None:
            pushed_at = (
                repo.pushed_at.replace(tzinfo=timezone.utc) if repo.pushed_at else None
            )
            # After a branch change the new branch was never indexed, so the
            # pushed_at freshness gate must not skip the re-listing.
            if (
                not branch_changed
                and start is not None
                and pushed_at is not None
                and pushed_at < start
            ):
                # Nothing changed in this repo since the last poll — skip.
                logger.info("Skipping files for repo %s (pushed_at < start)", repo.name)
                checkpoint.file_paths = []
                checkpoint.file_paths_branch = branch
            else:
                logger.info("Listing files for repo: %s", repo.name)
                paths, truncated = self._list_indexable_files(repo)
                checkpoint.file_paths = paths
                checkpoint.file_paths_branch = branch
                logger.info(
                    "Found %s indexable files for repo: %s", len(paths), repo.name
                )
                # Surface truncation as a failure so the incomplete index is
                # visible in the connector UI, not just buried in logs.
                if truncated and not is_slim:
                    yield ConnectorFailure(
                        failed_entity=EntityFailure(
                            entity_id=f"{repo.full_name}:files",
                        ),
                        failure_message=(
                            f"GitHub truncated the file tree for "
                            f"{repo.full_name}; some files could not be "
                            f"enumerated and were not indexed."
                        ),
                    )

        file_paths = checkpoint.file_paths
        page = checkpoint.curr_page
        batch = file_paths[page * FILE_BATCH_SIZE : (page + 1) * FILE_BATCH_SIZE]
        checkpoint.curr_page += 1

        for path in batch:
            html_url = _file_url(repo, branch, path)
            if is_slim:
                yield Document(
                    id=html_url,
                    sections=[],
                    external_access=repo_external_access,
                    source=DocumentSource.GITHUB,
                    semantic_identifier="",
                    metadata={},
                )
                continue
            try:
                raw = self._fetch_file_content(repo, path)
                content_text = _decode_file_content(raw)
                if content_text is None:
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=html_url,
                            document_link=html_url,
                        ),
                        failure_message=f"Skipping non-text/undecodable file: {path}",
                    )
                    continue
                yield _convert_file_to_document(
                    repo, path, content_text, repo_external_access, branch
                )
            except Exception as e:
                error_msg = f"Error converting file {path} to document: {e}"
                logger.exception(error_msg)
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=html_url,
                        document_link=html_url,
                    ),
                    failure_message=error_msg,
                    exception=e,
                )
                continue

        # True if more file batches remain for this repo.
        return (page + 1) * FILE_BATCH_SIZE < len(file_paths)

    def _fetch_from_github(
        self,
        checkpoint: GithubConnectorCheckpoint,
        start: datetime | None = None,
        end: datetime | None = None,
        include_permissions: bool = False,
        is_slim: bool = False,
    ) -> Generator[Document | ConnectorFailure, None, GithubConnectorCheckpoint]:
        source_operations = self.source_operations

        checkpoint = copy.deepcopy(checkpoint)

        # First run of the connector, fetch all repos and store in checkpoint
        if checkpoint.cached_repo_ids is None:
            repos = self.fetch_configured_repos()
            if not repos:
                checkpoint.has_more = False
                return checkpoint

            curr_repo = repos.pop()
            checkpoint.cached_repo_ids = [repo.id for repo in repos]
            checkpoint.cached_repo = SerializedRepository(
                id=curr_repo.id,
                raw_data=curr_repo.raw_data,
            )
            checkpoint.stage = GithubConnectorStage.PRS
            checkpoint.curr_page = 0
            # save checkpoint with repo ids retrieved
            return checkpoint

        if checkpoint.cached_repo is None:
            raise ValueError("No repo saved in checkpoint")

        # Deserialize the repository from the checkpoint
        repo = GitHubRepository.from_raw(checkpoint.cached_repo.raw_data)

        cursor_url_callback = make_cursor_url_callback(checkpoint)
        repo_external_access: ExternalAccess | None = None
        if include_permissions:
            repo_external_access = get_external_access_permission(repo)
        if self.include_prs and checkpoint.stage == GithubConnectorStage.PRS:
            logger.info("Fetching PRs for repo: %s", repo.name)

            fetch_pull_requests, iter_pull_requests = self._pull_request_listers(repo)
            pr_batch = _get_batch_rate_limited(
                fetch_pull_requests,
                iter_pull_requests,
                checkpoint.curr_page,
                checkpoint.cursor_url,
                checkpoint.num_retrieved,
                cursor_url_callback,
                source_operations,
                # Slim documents need no detail.
                detail=None if is_slim else self._detailed_pull_request,
            )
            checkpoint.curr_page += 1  # NOTE: not used for cursor-based fallback
            done_with_prs = False
            num_prs = 0
            pr = None
            for pr in pr_batch:
                num_prs += 1

                if is_slim:
                    yield Document(
                        id=pr.html_url,
                        sections=[],
                        external_access=repo_external_access,
                        source=DocumentSource.GITHUB,
                        semantic_identifier="",
                        metadata={},
                        doc_created_at=_utc(pr.created_at),
                    )
                else:
                    # we iterate backwards in time, so at this point we stop processing prs
                    if (
                        start is not None
                        and pr.updated_at
                        and pr.updated_at.replace(tzinfo=timezone.utc) < start
                    ):
                        done_with_prs = True
                        break
                    # Skip PRs updated after the end date
                    if (
                        end is not None
                        and pr.updated_at
                        and pr.updated_at.replace(tzinfo=timezone.utc) > end
                    ):
                        continue
                    try:
                        yield _convert_pr_to_document(
                            self._detailed_pull_request(pr),
                            repo_external_access,
                            self._lookup_user,
                        )
                    except Exception as e:
                        error_msg = f"Error converting PR to document: {e}"
                        logger.exception(error_msg)
                        yield ConnectorFailure(
                            failed_document=DocumentFailure(
                                document_id=pr.html_url, document_link=pr.html_url
                            ),
                            failure_message=error_msg,
                            exception=e,
                        )
                        continue

            # If we reach this point with a cursor url in the checkpoint, we were using
            # the fallback cursor-based pagination strategy. That strategy tries to get all
            # PRs, so having curosr_url set means we are done with prs. However, we need to
            # return AFTER the checkpoint reset to avoid infinite loops.

            # if we found any PRs on the page and there are more PRs to get, return the checkpoint.
            # In offset mode, while indexing without time constraints, the pr batch
            # will be empty when we're done.
            used_cursor = checkpoint.cursor_url is not None
            logger.info("Fetched %s PRs for repo: %s", num_prs, repo.name)
            if num_prs > 0 and not done_with_prs and not used_cursor:
                return checkpoint

            # if we went past the start date during the loop or there are no more
            # prs to get, we move on to issues
            checkpoint.stage = GithubConnectorStage.ISSUES
            checkpoint.reset()

            if used_cursor:
                # save the checkpoint after changing stage; next run will continue from issues
                return checkpoint

        # Advance into ISSUES only from PRS — never regress a later stage
        # (e.g. a resumed FILES checkpoint) back to ISSUES.
        if checkpoint.stage == GithubConnectorStage.PRS:
            checkpoint.stage = GithubConnectorStage.ISSUES

        if self.include_issues and checkpoint.stage == GithubConnectorStage.ISSUES:
            logger.info("Fetching issues for repo: %s", repo.name)

            fetch_issues, iter_issues = self._issue_listers(repo)
            issue_batch = list(
                _get_batch_rate_limited(
                    fetch_issues,
                    iter_issues,
                    checkpoint.curr_page,
                    checkpoint.cursor_url,
                    checkpoint.num_retrieved,
                    cursor_url_callback,
                    source_operations,
                    # Slim documents need no detail, and pull requests are
                    # handled separately.
                    detail=(
                        None
                        if is_slim
                        else lambda issue: (
                            issue
                            if issue.is_pull_request
                            else self._detailed_issue(issue)
                        )
                    ),
                )
            )
            logger.info("Fetched %s issues for repo: %s", len(issue_batch), repo.name)
            checkpoint.curr_page += 1
            done_with_issues = False
            num_issues = 0
            for issue in issue_batch:
                num_issues += 1
                if issue.is_pull_request:
                    # PRs are handled separately
                    continue

                if is_slim:
                    yield Document(
                        id=issue.html_url,
                        sections=[],
                        external_access=repo_external_access,
                        source=DocumentSource.GITHUB,
                        semantic_identifier="",
                        metadata={},
                        doc_created_at=_utc(issue.created_at),
                    )
                else:
                    # we iterate backwards in time, so at this point we stop processing issues
                    if (
                        start is not None
                        and issue.updated_at.replace(tzinfo=timezone.utc) < start
                    ):
                        done_with_issues = True
                        break
                    # Skip issues updated after the end date
                    if (
                        end is not None
                        and issue.updated_at.replace(tzinfo=timezone.utc) > end
                    ):
                        continue
                    try:
                        yield _convert_issue_to_document(
                            self._detailed_issue(issue),
                            repo_external_access,
                            self._lookup_user,
                        )
                    except Exception as e:
                        error_msg = f"Error converting issue to document: {e}"
                        logger.exception(error_msg)
                        yield ConnectorFailure(
                            failed_document=DocumentFailure(
                                document_id=issue.html_url,
                                document_link=issue.html_url,
                            ),
                            failure_message=error_msg,
                            exception=e,
                        )
                        continue

            logger.info("Fetched %s issues for repo: %s", num_issues, repo.name)
            # if we found any issues on the page, and we're not done, return the checkpoint.
            # don't return if we're using cursor-based pagination to avoid infinite loops
            if num_issues > 0 and not done_with_issues and not checkpoint.cursor_url:
                return checkpoint

            # if we went past the start date during the loop or there are no more
            # issues to get, we move on to indexing files
            checkpoint.stage = GithubConnectorStage.FILES
            checkpoint.reset()

        # Advance into FILES from PRS/ISSUES, but never regress a resumed FILES
        # checkpoint (mid file-pagination) — that would null out file_paths and
        # re-index from page 0.
        if checkpoint.stage in (
            GithubConnectorStage.PRS,
            GithubConnectorStage.ISSUES,
        ):
            checkpoint.stage = GithubConnectorStage.FILES

        if self.include_files and checkpoint.stage == GithubConnectorStage.FILES:
            has_more_file_batches = yield from self._fetch_repo_files(
                repo, checkpoint, start, is_slim, repo_external_access
            )
            # More file batches remain for this repo — checkpoint and resume.
            if has_more_file_batches:
                return checkpoint

        # files complete (or disabled) -> fall through to next repo

        checkpoint.has_more = len(checkpoint.cached_repo_ids) > 0
        if checkpoint.cached_repo_ids:
            next_id = checkpoint.cached_repo_ids.pop()
            next_repo = source_operations.get_repository_by_id(repo_id=next_id)
            checkpoint.cached_repo = SerializedRepository(
                id=next_id,
                raw_data=next_repo.raw_data,
            )
            checkpoint.stage = GithubConnectorStage.PRS
            checkpoint.reset()

        if checkpoint.cached_repo_ids:
            logger.info(
                "%s repos remaining (IDs: %s)",
                len(checkpoint.cached_repo_ids),
                checkpoint.cached_repo_ids,
            )
        else:
            logger.info("No more repos remaining")

        return checkpoint

    def _load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GithubConnectorCheckpoint,
        include_permissions: bool = False,
    ) -> CheckpointOutput[GithubConnectorCheckpoint]:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        # add a day for timezone safety
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc) + ONE_DAY

        # Move start time back by 3 hours, since some Issues/PRs are getting dropped
        # Could be due to delayed processing on GitHub side
        # The non-updated issues since last poll will be shortcut-ed and not embedded
        adjusted_start_datetime = start_datetime - timedelta(hours=3)

        epoch = datetime.fromtimestamp(0, tz=timezone.utc)
        if adjusted_start_datetime < epoch:
            adjusted_start_datetime = epoch

        return self._fetch_from_github(
            checkpoint,
            start=adjusted_start_datetime,
            end=end_datetime,
            include_permissions=include_permissions,
        )

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GithubConnectorCheckpoint,
    ) -> CheckpointOutput[GithubConnectorCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=False
        )

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GithubConnectorCheckpoint,
    ) -> CheckpointOutput[GithubConnectorCheckpoint]:
        return self._load_from_checkpoint(
            start, end, checkpoint, include_permissions=True
        )

    def _retrieve_slim_docs(
        self,
        include_permissions: bool,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        """Iterate all PRs and issues across all configured repos as SlimDocuments.

        Drives _fetch_from_github in a checkpoint loop — each call processes one
        page and returns an updated checkpoint. CheckpointOutputWrapper handles
        draining the generator and extracting the returned checkpoint. Rate
        limiting and pagination are handled centrally by _fetch_from_github via
        _get_batch_rate_limited.
        """
        checkpoint = self.build_dummy_checkpoint()
        while checkpoint.has_more:
            batch: list[SlimDocument | HierarchyNode] = []
            gen = self._fetch_from_github(
                checkpoint, include_permissions=include_permissions, is_slim=True
            )
            wrapper: CheckpointOutputWrapper[GithubConnectorCheckpoint] = (
                CheckpointOutputWrapper()
            )
            for document, _, _, next_checkpoint in wrapper(gen):
                if document is not None:
                    batch.append(
                        SlimDocument(
                            id=document.id,
                            external_access=document.external_access,
                            doc_created_at=document.doc_created_at,
                        )
                    )
                if next_checkpoint is not None:
                    checkpoint = next_checkpoint
            if batch:
                yield batch
            if callback and callback.should_stop():
                raise RuntimeError("github_slim_docs: Stop signal detected")

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        return self._retrieve_slim_docs(include_permissions=False, callback=callback)

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        return self._retrieve_slim_docs(include_permissions=True, callback=callback)

    def validate_connector_settings(self) -> None:
        if self._source_operations is None:
            raise ConnectorMissingCredentialError("GitHub credentials not loaded.")
        source_operations = self._source_operations

        if not self.repo_owner:
            raise ConnectorValidationError(
                "Invalid connector settings: 'repo_owner' must be provided."
            )

        if not (self.include_prs or self.include_issues or self.include_files):
            raise ConnectorValidationError(
                "Invalid connector settings: at least one of pull requests, "
                "issues, or files must be selected for indexing."
            )

        try:
            if self.repositories:
                if "," in self.repositories:
                    # Multiple repositories specified
                    repo_names = [name.strip() for name in self.repositories.split(",")]
                    if not repo_names:
                        raise ConnectorValidationError(
                            "Invalid connector settings: No valid repository names provided."
                        )

                    # Validate at least one repository exists and is accessible
                    valid_repos = False
                    validation_errors = []

                    for repo_name in repo_names:
                        if not repo_name:
                            continue

                        try:
                            test_repo = source_operations.get_repository(
                                owner=self.repo_owner, name=repo_name
                            )
                            logger.info(
                                "Successfully accessed repository: %s/%s",
                                self.repo_owner,
                                repo_name,
                            )
                            source_operations.list_root_contents(
                                repo_full_name=test_repo.full_name
                            )
                            valid_repos = True
                            # If at least one repo is valid, we can proceed
                            break
                        except GitHubRateLimitError:
                            raise
                        except GitHubApiError as e:
                            validation_errors.append(
                                f"Repository '{repo_name}': {e.github_message or e}"
                            )

                    if not valid_repos:
                        error_msg = (
                            "None of the specified repositories could be accessed: "
                        )
                        error_msg += ", ".join(validation_errors)
                        raise ConnectorValidationError(error_msg)
                else:
                    # Single repository (backward compatibility)
                    test_repo = source_operations.get_repository(
                        owner=self.repo_owner, name=self.repositories
                    )
                    source_operations.list_root_contents(
                        repo_full_name=test_repo.full_name
                    )
                    if self.branch:
                        try:
                            source_operations.get_branch(
                                repo_full_name=test_repo.full_name, branch=self.branch
                            )
                        except GitHubApiError as e:
                            if e.status_code == 404:
                                raise ConnectorValidationError(
                                    f"Branch '{self.branch}' not found in repository "
                                    f"{self.repo_owner}/{self.repositories}."
                                )
                            raise
            else:
                # Try to get organization first
                try:
                    source_operations.get_organization(login=self.repo_owner)
                    if not source_operations.list_organization_repositories(
                        org_login=self.repo_owner, limit=1
                    ):
                        raise ConnectorValidationError(
                            f"Found no repos for organization: {self.repo_owner}. Does the credential have the right scopes?"
                        )
                except GitHubRateLimitError:
                    raise
                except GitHubApiError as e:
                    # Check for missing SSO
                    MISSING_SSO_ERROR_MESSAGE = "You must grant your Personal Access token access to this organization".lower()
                    if MISSING_SSO_ERROR_MESSAGE in str(e).lower():
                        SSO_GUIDE_LINK = (
                            "https://docs.github.com/en/enterprise-cloud@latest/authentication/"
                            "authenticating-with-saml-single-sign-on/"
                            "authorizing-a-personal-access-token-for-use-with-saml-single-sign-on"
                        )
                        raise ConnectorValidationError(
                            f"Your GitHub token is missing authorization to access the "
                            f"`{self.repo_owner}` organization. Please follow the guide to "
                            f"authorize your token: {SSO_GUIDE_LINK}"
                        )
                    # If not an org, try as a user; check that it has any repos
                    if not source_operations.list_user_repositories(
                        login=self.repo_owner, limit=1
                    ):
                        raise ConnectorValidationError(
                            f"Found no repos for user: {self.repo_owner}. Does the credential have the right scopes?"
                        )

        except GitHubRateLimitError:
            raise UnexpectedValidationError(
                "Validation failed due to GitHub rate-limits being exceeded. Please try again later."
            )

        except GitHubApiError as e:
            if e.status_code == 401:
                raise CredentialExpiredError(
                    "GitHub credential appears to be invalid or expired (HTTP 401)."
                )
            elif e.status_code == 403:
                raise InsufficientPermissionsError(
                    "Your GitHub token does not have sufficient permissions for this repository (HTTP 403)."
                )
            elif e.status_code == 404:
                if self.repositories:
                    if "," in self.repositories:
                        raise ConnectorValidationError(
                            f"None of the specified GitHub repositories could be found for owner: {self.repo_owner}"
                        )
                    else:
                        raise ConnectorValidationError(
                            f"GitHub repository not found with name: {self.repo_owner}/{self.repositories}"
                        )
                else:
                    raise ConnectorValidationError(
                        f"GitHub user or organization not found: {self.repo_owner}"
                    )
            else:
                raise ConnectorValidationError(
                    f"Unexpected GitHub error (status={e.status_code}): {e.github_message or e}"
                )

        except ValidationError:
            # Let typed validation errors propagate so the API can surface the
            # real reason instead of collapsing them into a generic 500.
            raise

        except Exception as exc:
            raise UnexpectedValidationError(
                f"Unexpected error during GitHub settings validation: {exc}"
            )

    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> GithubConnectorCheckpoint:
        return GithubConnectorCheckpoint.model_validate_json(checkpoint_json)

    def build_dummy_checkpoint(self) -> GithubConnectorCheckpoint:
        return GithubConnectorCheckpoint(
            stage=GithubConnectorStage.PRS, curr_page=0, has_more=True, num_retrieved=0
        )


if __name__ == "__main__":
    import os

    # Initialize the connector
    connector = GithubConnector(
        repo_owner=os.environ["REPO_OWNER"],
        repositories=os.environ.get("REPOSITORIES"),
    )
    connector.load_credentials(
        {"github_access_token": os.environ["ACCESS_TOKEN_GITHUB"]}
    )

    get_external_access_permission(connector.fetch_configured_repos().pop())

    # Create a time range from epoch to now
    end_time = datetime.now(timezone.utc)
    start_time = datetime.fromtimestamp(0, tz=timezone.utc)
    time_range = (start_time, end_time)

    # Initialize the runner with a batch size of 10
    runner: ConnectorRunner[GithubConnectorCheckpoint] = ConnectorRunner(
        connector, batch_size=10, include_permissions=False, time_range=time_range
    )

    # Get initial checkpoint
    checkpoint = connector.build_dummy_checkpoint()

    # Run the connector
    while checkpoint.has_more:
        for doc_batch, _hierarchy_node_batch, failure, next_checkpoint in runner.run(
            checkpoint
        ):
            if doc_batch:
                print(f"Retrieved batch of {len(doc_batch)} documents")
                for doc in doc_batch:
                    print(f"Document: {doc.semantic_identifier}")
            if failure:
                print(f"Failure: {failure.failure_message}")
            if next_checkpoint:
                checkpoint = next_checkpoint
