import fnmatch
import itertools
import os
import shutil
import tempfile
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar

import git
import gitlab
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

# List of directories/Files to exclude by default
exclude_patterns = [
    "logs",
    ".github/",
    ".gitlab/",
    ".pre-commit-config.yaml",
    ".git/",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".DS_Store",
    "Thumbs.db",
    "node_modules/",
    ".vscode/",
    ".idea/",
    "*.log",
    "*.tmp",
    "*.temp",
]

# Default glob patterns matched against repo files when code-file indexing is
# enabled. Patterns without a "/" match the basename anywhere in the tree (e.g.
# "*.py", "Makefile"); patterns with a "/" match the full relative path (e.g.
# "src/*.py"). Users can override this list from the connector configuration
# (see ``code_file_patterns``). Unlike a plain extension list, glob patterns also
# match extensionless files such as ``Makefile`` and ``Dockerfile``.
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

# Anything before this cutoff is treated as a "from the beginning" full index.
# Onyx passes a poll window starting at the unix epoch (1970) for the very first
# index attempt (or when re-indexing from scratch), so a real incremental poll
# window will always start well after this date.
_FULL_INDEX_START_CUTOFF = datetime(2005, 1, 1, tzinfo=timezone.utc)


def _normalize_patterns(patterns: Iterable[str]) -> list[str]:
    """Normalize user-supplied glob patterns.

    Strips whitespace, drops empties and duplicates, and rewrites the legacy
    regex "match everything" pattern (``.*``) to its glob equivalent (``*``) so
    that connectors created before the glob migration keep matching all files.
    """
    normalized: list[str] = []
    for pattern in patterns:
        cleaned = pattern.strip()
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


def _ensure_utc_datetime(dt: datetime | None) -> datetime:
    """Ensure datetime has UTC timezone information (None -> now)."""
    if dt is None:
        return datetime.now(timezone.utc)

    if dt.tzinfo is None:
        # If no timezone info, assume UTC
        return dt.replace(tzinfo=timezone.utc)

    # If timezone info exists, convert to UTC
    return dt.astimezone(timezone.utc)


def _batch_gitlab_objects(git_objs: Iterable[T], batch_size: int) -> Iterator[list[T]]:
    """Batch GitLab objects into chunks."""
    logger.debug("Starting to batch objects with batch size: %s", batch_size)
    it = iter(git_objs)
    batch_count = 0
    while True:
        batch = list(itertools.islice(it, batch_size))
        if not batch:
            logger.debug("Finished batching. Total batches created: %s", batch_count)
            break
        batch_count += 1
        logger.debug("Created batch #%s with %s objects", batch_count, len(batch))
        yield batch


def get_author(author: Any) -> BasicExpertInfo:
    # GitLab masks the `name` field as "****" for blocked users and as an
    # anti-scraping measure on free-tier public projects. Fall back to
    # `username` so we surface a usable identifier instead.
    name = author.get("name") if author else None
    if not name or name == "****":
        name = author.get("username") if author else None
    return BasicExpertInfo(
        display_name=name,
    )


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


def _convert_file_to_document(
    file_path: Path,
    repo_path: Path,
    project_url: str,
    project_name: str,
    project_owner: str,
    default_branch: str,
    last_commit_date: datetime | None = None,
) -> Document:
    """Convert a file to Document."""
    logger.debug("Converting file to document: %s", file_path)

    try:
        # Read file content
        logger.debug("Attempting to read file content with UTF-8 encoding")
        with open(file_path, "r", encoding="utf-8") as f:
            file_content = f.read()
        logger.debug(
            "Successfully read file content (%s characters)", len(file_content)
        )
    except UnicodeDecodeError:
        logger.warning("UTF-8 decode failed for %s, trying latin-1", file_path)
        try:
            with open(file_path, "r", encoding="latin-1") as f:
                file_content = f.read()
            logger.debug(
                "Successfully read file content with latin-1 (%s characters)",
                len(file_content),
            )
        except Exception as e:
            logger.error("Could not read file %s with latin-1: %s", file_path, e)
            file_content = f"[Could not read file content: {e}]"
    except Exception as e:
        logger.error("Could not read file %s: %s", file_path, e)
        file_content = f"[Could not read file content: {e}]"

    # Get relative path from repo root
    relative_path = file_path.relative_to(repo_path)
    logger.debug("File relative path: %s", relative_path)

    # Construct the file URL
    file_url = f"{project_url}/{project_owner}/{project_name}/-/blob/{default_branch}/{relative_path}".replace(
        "\\\\", "\\"
    )
    logger.debug("Constructed file URL: %s", file_url)

    # Generate unique ID using file path
    file_id = f"{project_url}/{project_owner}/{project_name}/blob/{default_branch}/{relative_path}".replace(
        "\\\\", "\\"
    )
    logger.debug("Generated file ID: %s", file_id)

    # Leave doc_updated_at unset when no reliable commit date is available —
    # the indexing pipeline's content hash then governs change detection. A
    # fabricated now() timestamp would mark every doc as updated on each run.
    doc_updated_at = (
        _ensure_utc_datetime(last_commit_date) if last_commit_date else None
    )

    # Create and return a Document object
    doc = Document(
        id=file_id,
        sections=[TextSection(link=file_url, text=file_content)],
        source=DocumentSource.GITLAB,
        semantic_identifier=str(relative_path),
        doc_updated_at=doc_updated_at,
        primary_owners=[],  # Could be enhanced to include git blame info
        metadata={"type": "CodeFile", "file_extension": file_path.suffix},
    )
    logger.debug("Successfully converted file document: %s", doc.semantic_identifier)
    return doc


def _should_exclude_by_patterns(path: str, patterns: list[str]) -> bool:
    """Check if a path matches any of the exclude patterns."""
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            logger.debug("Path '%s' excluded by pattern '%s'", path, pattern)
            return True
    return False


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
        return fnmatch.fnmatch(path, pattern)
    return fnmatch.fnmatch(Path(path).name, pattern)


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


def _get_file_last_commit_date(repo: git.Repo, file_path: str) -> datetime | None:
    """Get the last commit date for a specific file (None when unavailable)."""
    try:
        commits = list(repo.iter_commits(paths=file_path, max_count=1))
        if commits:
            return _ensure_utc_datetime(commits[0].committed_datetime)
        logger.debug("No commits found for file: %s", file_path)
    except Exception as e:
        logger.warning("Could not get commit date for %s: %s", file_path, e)
    return None


class GitlabConnector(LoadConnector, PollConnector):
    """Enhanced GitLab connector that clones entire repository and indexes with glob filtering."""

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
        clone_depth: int | None = None,  # None for a full clone
        branch: str | None = None,  # None for the default branch
        code_file_patterns: list[str] | None = None,  # None for defaults
        # Deprecated: previously a list of bare extensions (e.g. ".py"). Still
        # accepted so connectors created before the glob migration keep working;
        # the extensions are converted to equivalent globs ("*.py").
        code_file_extensions: list[str] | None = None,
    ) -> None:
        include_path_patterns = _normalize_patterns(include_path_patterns or [])
        exclude_path_patterns = _normalize_patterns(exclude_path_patterns or [])

        logger.info(
            "Initializing GitlabConnector for %s/%s", project_owner, project_name
        )
        logger.debug(
            "Configuration - batch_size: %s, state_filter: %s", batch_size, state_filter
        )
        logger.debug(
            "Include options - MRs: %s, Issues: %s, Code files: %s",
            include_mrs,
            include_issues,
            include_code_files,
        )
        logger.debug(
            "Filter patterns - Include: %s, Exclude: %s",
            include_path_patterns,
            exclude_path_patterns,
        )
        logger.debug("Clone options - Depth: %s, Branch: %s", clone_depth, branch)

        self.project_owner = project_owner
        self.project_name = project_name
        self.batch_size = batch_size
        self.state_filter = state_filter
        self.include_mrs = include_mrs
        self.include_issues = include_issues
        self.include_code_files = include_code_files
        self.include_path_patterns = include_path_patterns
        self.exclude_path_patterns = exclude_path_patterns
        self.clone_depth = clone_depth
        self.branch = branch
        if code_file_patterns:
            self.code_file_patterns = _normalize_patterns(code_file_patterns)
        elif code_file_extensions:
            # Back-compat: convert legacy bare extensions to globs.
            self.code_file_patterns = _normalize_patterns(
                [_extension_to_glob(ext) for ext in code_file_extensions]
            )
        else:
            self.code_file_patterns = list(DEFAULT_CODE_FILE_PATTERNS)
        logger.debug("Code file patterns: %s", self.code_file_patterns)
        self.gitlab_client: gitlab.Gitlab | None = None
        self.repo_path: Path | None = None
        self.git_repo: git.Repo | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load GitLab credentials."""
        logger.info("Loading GitLab credentials")
        gitlab_url = credentials.get("gitlab_url", "Unknown")
        logger.debug("GitLab URL: %s", gitlab_url)
        self.gitlab_url = gitlab_url.rstrip("/")

        try:
            self.gitlab_client = gitlab.Gitlab(
                credentials["gitlab_url"],
                private_token=credentials["gitlab_access_token"],
            )
            # Test the connection
            self.gitlab_client.auth()
            logger.info("Successfully authenticated with GitLab")
        except Exception as e:
            logger.error("Failed to authenticate with GitLab: %s", e)
            raise

        return None

    def _clone_repository(self, since: datetime | None = None) -> Path:
        """Clone the repository to a temporary directory.

        When ``since`` is provided we perform an incremental sync, so we clone
        with ``--shallow-since`` to fetch just enough history to diff the current
        HEAD against the state that was indexed during the previous sync. When it
        is ``None`` (full index) we honor ``clone_depth`` instead, which can be a
        shallow ``depth=1`` snapshot since we index every file in the tree.
        """
        logger.info(
            "Starting repository clone process for %s/%s",
            self.project_owner,
            self.project_name,
        )

        if self.gitlab_client is None:
            logger.error("GitLab client not initialized")
            raise ConnectorMissingCredentialError("Gitlab")

        try:
            logger.debug("Fetching project information from GitLab API")
            project: Project = self.gitlab_client.projects.get(
                f"{self.project_owner}/{self.project_name}"
            )
            logger.info("Found project: %s (ID: %s)", project.name, project.id)
        except Exception as e:
            logger.error("Failed to fetch project information: %s", e)
            raise

        # Create temporary directory
        temp_dir = tempfile.mkdtemp(prefix=f"gitlab_repo_{self.project_name}_")
        repo_path = Path(temp_dir)
        logger.info("Created temporary directory: %s", repo_path)

        try:
            # Get clone URL with token
            clone_url = project.http_url_to_repo
            logger.debug("Original clone URL: %s", clone_url)

            if self.gitlab_client.private_token:
                # Insert token into URL for authentication
                clone_url = clone_url.replace(
                    "://", f"://oauth2:{self.gitlab_client.private_token}@"
                )
                logger.debug("Added authentication token to clone URL")

            # Clone repository
            clone_kwargs: dict[str, Any] = {
                "url": clone_url,
                "to_path": str(repo_path),
            }
            multi_options: list[str] = []

            if since is not None:
                # Fetch history back to (just before) the previous sync so we can
                # diff against it. Subtract a day of slack to make sure the
                # boundary commit that predates the window is included.
                shallow_since = (since - timedelta(days=1)).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                )
                multi_options.append(f"--shallow-since={shallow_since}")
                logger.debug(
                    "Incremental clone using --shallow-since=%s", shallow_since
                )
            elif self.clone_depth:
                clone_kwargs["depth"] = self.clone_depth
                logger.debug("Using shallow clone with depth: %s", self.clone_depth)

            if self.branch:
                clone_kwargs["branch"] = self.branch
                logger.debug("Cloning specific branch: %s", self.branch)

            if multi_options:
                clone_kwargs["multi_options"] = multi_options

            logger.info("Starting git clone operation...")
            self.git_repo = git.Repo.clone_from(**clone_kwargs)

            # Log repository information
            active_branch = self.git_repo.active_branch.name
            commit_count = sum(1 for _ in self.git_repo.iter_commits())
            logger.info(
                "Successfully cloned repository - Active branch: %s, Commits: %s",
                active_branch,
                commit_count,
            )

            return repo_path

        except Exception:
            logger.exception("Failed to clone repository")
            # Clean up on failure
            shutil.rmtree(repo_path, ignore_errors=True)
            raise

    def _cleanup_repository(self) -> None:
        """Clean up cloned repository."""
        if self.repo_path and self.repo_path.exists():
            logger.info("Cleaning up repository at %s", self.repo_path)
            try:
                shutil.rmtree(self.repo_path, ignore_errors=True)
                logger.debug("Repository cleanup completed successfully")
            except Exception as e:
                logger.warning("Error during repository cleanup: %s", e)
            finally:
                self.repo_path = None
                self.git_repo = None
        else:
            logger.debug("No repository to clean up")

    def _iter_candidate_files(
        self, candidate_rel_paths: set[str] | None
    ) -> Iterator[Path]:
        """Yield repository files to consider for indexing.

        For a full index (``candidate_rel_paths is None``) we walk the whole
        working tree. For an incremental sync we only look at the supplied set of
        changed relative paths (skipping any that no longer exist on disk).
        """
        if not self.repo_path:
            return

        if candidate_rel_paths is None:
            for root, dirs, files in os.walk(self.repo_path):
                # Skip .git directory
                if ".git" in dirs:
                    dirs.remove(".git")
                    logger.debug("Skipped .git directory")
                for file in files:
                    file_path = Path(root) / file
                    if self._is_safe_repo_file(file_path):
                        yield file_path
            return

        for rel_path in candidate_rel_paths:
            file_path = self.repo_path / rel_path
            if self._is_safe_repo_file(file_path):
                yield file_path

    def _is_safe_repo_file(self, file_path: Path) -> bool:
        """Reject symlinks and anything resolving outside the checkout.

        A repository-controlled symlink (e.g. ``secret -> /etc/passwd``) must
        not let indexing read and publish files from the host filesystem.
        """
        if self.repo_path is None:
            return False
        if file_path.is_symlink() or not file_path.is_file():
            return False
        try:
            file_path.resolve().relative_to(self.repo_path.resolve())
        except ValueError:
            logger.warning(
                "Skipping %s: resolves outside the repository checkout", file_path
            )
            return False
        return True

    def _get_filtered_files(
        self, candidate_rel_paths: set[str] | None = None
    ) -> list[Path]:
        """Get list of files that match the filtering criteria.

        ``candidate_rel_paths`` restricts the scan to a specific set of changed
        files for incremental syncs; ``None`` scans the entire repository.
        """
        logger.info("Starting file filtering process")

        if not self.repo_path:
            logger.warning("Repository path not available")
            return []

        all_files = []
        total_files_scanned = 0
        excluded_by_default = 0
        excluded_by_glob = 0
        excluded_by_include_filter = 0
        excluded_not_code = 0

        # Walk through all candidate files in the repository
        logger.debug("Scanning files in repository: %s", self.repo_path)
        for file_path in self._iter_candidate_files(candidate_rel_paths):
            total_files_scanned += 1
            relative_path = str(file_path.relative_to(self.repo_path))

            # Apply default exclude patterns
            if _should_exclude_by_patterns(relative_path, exclude_patterns):
                excluded_by_default += 1
                continue

            # Apply glob exclude patterns
            if _should_exclude_by_glob(relative_path, self.exclude_path_patterns):
                excluded_by_glob += 1
                continue

            # Apply glob include patterns
            if not _should_include_by_glob(relative_path, self.include_path_patterns):
                excluded_by_include_filter += 1
                continue

            # Check if it's a code file (matches a code-file glob pattern)
            if self.include_code_files and not _matches_any_glob(
                relative_path, self.code_file_patterns
            ):
                excluded_not_code += 1
                continue

            all_files.append(file_path)
            logger.debug("Included file: %s", relative_path)

        # Log filtering statistics
        logger.info("File filtering completed:")
        logger.info("  Total files scanned: %s", total_files_scanned)
        logger.info("  Excluded by default patterns: %s", excluded_by_default)
        logger.info("  Excluded by glob patterns: %s", excluded_by_glob)
        logger.info("  Excluded by include filter: %s", excluded_by_include_filter)
        logger.info("  Excluded (not code files): %s", excluded_not_code)
        logger.info("  Final files included: %s", len(all_files))

        return all_files

    def _get_changed_paths_since(self, start: datetime) -> set[str] | None:
        """Compute repository paths changed since the previous successful sync.

        Returns a set of repo-relative paths that were added/modified/renamed in
        commits after ``start`` (deletions are excluded — they are handled by
        pruning, not indexing). Returns ``None`` when no commit predates
        ``start`` (i.e. the whole history is newer than the window), signalling
        the caller to fall back to a full index.
        """
        if not self.git_repo:
            logger.warning(
                "Git repo not available for diff; falling back to full index"
            )
            return None

        start_utc = _ensure_utc_datetime(start)
        # git rev-list --until expects the committer's local representation; an
        # ISO-8601 string with offset is unambiguous and accepted by git.
        until_str = start_utc.strftime("%Y-%m-%dT%H:%M:%S%z")

        try:
            base_commit = next(
                iter(self.git_repo.iter_commits("HEAD", until=until_str, max_count=1)),
                None,
            )
        except Exception as e:
            logger.warning(
                "Could not determine base commit for diff: %s. Full index.", e
            )
            return None

        if base_commit is None:
            logger.info(
                "No commit found at or before the previous sync window; "
                "performing a full index."
            )
            return None

        logger.info(
            "Computing diff from base commit %s (committed %s) to HEAD",
            base_commit.hexsha[:12],
            base_commit.committed_datetime.isoformat(),
        )
        try:
            # --diff-filter=d excludes deletions; name-only gives changed paths.
            diff_output = self.git_repo.git.diff(
                "--name-only", "--diff-filter=d", f"{base_commit.hexsha}..HEAD"
            )
        except Exception as e:
            logger.warning("git diff failed: %s. Falling back to full index.", e)
            return None

        changed_paths = {
            line.strip() for line in diff_output.splitlines() if line.strip()
        }
        logger.info("Detected %s changed file(s) since last sync", len(changed_paths))
        return changed_paths

    def _fetch_code_files(
        self, changed_rel_paths: set[str] | None = None
    ) -> GenerateDocumentsOutput:
        """Fetch and convert code files to documents.

        ``changed_rel_paths`` restricts processing to the given set of changed
        files for incremental syncs; ``None`` processes the entire repository.
        """
        logger.info("Starting code files fetch process")

        if not self.include_code_files:
            logger.info("Code files inclusion disabled, skipping")
            return

        if not self.repo_path:
            logger.error("Repository path not available for code files processing")
            return

        if changed_rel_paths is not None and not changed_rel_paths:
            logger.info("No files changed since last sync; nothing to re-index")
            return

        if self.gitlab_client is None:
            raise ConnectorMissingCredentialError("Gitlab")

        filtered_files = self._get_filtered_files(changed_rel_paths)

        if not filtered_files:
            logger.warning("No files found matching filter criteria")
            return

        # Get project info for URL construction
        try:
            project: Project = self.gitlab_client.projects.get(
                f"{self.project_owner}/{self.project_name}"
            )
            default_branch = self.branch or project.default_branch
            logger.info("Using branch '%s' for URL construction", default_branch)
        except Exception as e:
            logger.error("Failed to get project information: %s", e)
            raise

        # Process files in batches
        logger.info(
            "Processing %s files in batches of %s", len(filtered_files), self.batch_size
        )
        batch_count = 0
        total_documents = 0

        for file_batch in _batch_gitlab_objects(filtered_files, self.batch_size):
            batch_count += 1
            logger.info(
                "Processing code file batch #%s (%s files)",
                batch_count,
                len(file_batch),
            )

            code_doc_batch: list[Document | HierarchyNode] = []

            # On a shallow full clone (clone_depth set) the truncated history
            # attributes every file to the boundary commit — skip the per-file
            # lookup and let content hashing govern change detection instead.
            history_is_reliable = changed_rel_paths is not None or not self.clone_depth

            for file_path in file_batch:
                try:
                    # Get last commit date for the file
                    relative_path = str(file_path.relative_to(self.repo_path))
                    last_commit_date = None
                    if self.git_repo and history_is_reliable:
                        last_commit_date = _get_file_last_commit_date(
                            self.git_repo, relative_path
                        )

                    doc = _convert_file_to_document(
                        file_path=file_path,
                        repo_path=self.repo_path,
                        project_url=self.gitlab_url,
                        project_name=self.project_name,
                        project_owner=self.project_owner,
                        default_branch=default_branch,
                        last_commit_date=last_commit_date,
                    )
                    code_doc_batch.append(doc)
                    total_documents += 1

                except Exception as e:
                    logger.error("Error processing file %s: %s", file_path, e)
                    continue

            if code_doc_batch:
                logger.info(
                    "Yielding batch #%s with %s code documents",
                    batch_count,
                    len(code_doc_batch),
                )
                yield code_doc_batch

        logger.info(
            "Code files processing completed. Total documents: %s", total_documents
        )

    def _fetch_merge_requests(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        """Fetch merge requests."""
        logger.info("Starting merge requests fetch process")

        if not self.include_mrs:
            logger.info("Merge requests inclusion disabled, skipping")
            return

        if self.gitlab_client is None:
            raise ConnectorMissingCredentialError("Gitlab")

        if start:
            logger.info("Fetching MRs updated after: %s", start)
        if end:
            logger.info("Fetching MRs updated before: %s", end)

        try:
            project: Project = self.gitlab_client.projects.get(
                f"{self.project_owner}/{self.project_name}"
            )
            logger.debug(
                "Fetching merge requests with state filter: %s", self.state_filter
            )
        except Exception as e:
            logger.error("Failed to get project for MRs: %s", e)
            raise

        try:
            merge_requests = project.mergerequests.list(
                state=self.state_filter,
                order_by="updated_at",
                sort="desc",
                iterator=True,
            )
            logger.debug("Successfully initialized merge requests iterator")
        except Exception as e:
            logger.error("Failed to get merge requests list: %s", e)
            raise

        batch_count = 0
        total_mrs = 0

        for mr_batch in _batch_gitlab_objects(merge_requests, self.batch_size):
            batch_count += 1
            logger.info("Processing MR batch #%s (%s MRs)", batch_count, len(mr_batch))

            mr_doc_batch: list[Document | HierarchyNode] = []
            for mr in mr_batch:
                try:
                    updated_at = _gitlab_datetime_to_utc(mr.updated_at)

                    # Time filtering
                    if updated_at is not None and start is not None:
                        start_utc = _ensure_utc_datetime(start)
                        if updated_at < start_utc:
                            logger.debug(
                                "MR %s is older than start time, stopping", mr.title
                            )
                            if mr_doc_batch:
                                yield mr_doc_batch
                            return
                    if updated_at is not None and end is not None:
                        end_utc = _ensure_utc_datetime(end)
                        if updated_at > end_utc:
                            logger.debug(
                                "MR %s is newer than end time, skipping", mr.title
                            )
                            continue

                    mr_doc_batch.append(_convert_merge_request_to_document(mr))
                    total_mrs += 1

                except Exception as e:
                    logger.error(
                        "Error processing MR %s: %s", getattr(mr, "title", "Unknown"), e
                    )
                    continue

            if mr_doc_batch:
                logger.info(
                    "Yielding MR batch #%s with %s documents",
                    batch_count,
                    len(mr_doc_batch),
                )
                yield mr_doc_batch

        logger.info("Merge requests processing completed. Total MRs: %s", total_mrs)

    def _fetch_issues(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        """Fetch issues."""
        logger.info("Starting issues fetch process")

        if not self.include_issues:
            logger.info("Issues inclusion disabled, skipping")
            return

        if self.gitlab_client is None:
            raise ConnectorMissingCredentialError("Gitlab")

        if start:
            logger.info("Fetching issues updated after: %s", start)
        if end:
            logger.info("Fetching issues updated before: %s", end)

        try:
            project: Project = self.gitlab_client.projects.get(
                f"{self.project_owner}/{self.project_name}"
            )
            logger.debug("Fetching issues with state filter: %s", self.state_filter)
        except Exception as e:
            logger.error("Failed to get project for issues: %s", e)
            raise

        try:
            issues = project.issues.list(state=self.state_filter, iterator=True)
            logger.debug("Successfully initialized issues iterator")
        except Exception as e:
            logger.error("Failed to get issues list: %s", e)
            raise

        batch_count = 0
        total_issues = 0

        for issue_batch in _batch_gitlab_objects(issues, self.batch_size):
            batch_count += 1
            logger.info(
                "Processing issue batch #%s (%s issues)", batch_count, len(issue_batch)
            )

            issue_doc_batch: list[Document | HierarchyNode] = []
            for issue in issue_batch:
                try:
                    updated_at = _gitlab_datetime_to_utc(issue.updated_at)

                    # Time filtering
                    if updated_at is not None and start is not None:
                        start_utc = _ensure_utc_datetime(start)
                        if updated_at < start_utc:
                            logger.debug(
                                "Issue %s is older than start time, stopping",
                                issue.title,
                            )
                            if issue_doc_batch:
                                yield issue_doc_batch
                            return
                    if updated_at is not None and end is not None:
                        end_utc = _ensure_utc_datetime(end)
                        if updated_at > end_utc:
                            logger.debug(
                                "Issue %s is newer than end time, skipping", issue.title
                            )
                            continue

                    issue_doc_batch.append(_convert_issue_to_document(issue))
                    total_issues += 1

                except Exception as e:
                    logger.error(
                        "Error processing issue %s: %s",
                        getattr(issue, "title", "Unknown"),
                        e,
                    )
                    continue

            if issue_doc_batch:
                logger.info(
                    "Yielding issue batch #%s with %s documents",
                    batch_count,
                    len(issue_doc_batch),
                )
                yield issue_doc_batch

        logger.info("Issues processing completed. Total issues: %s", total_issues)

    def _fetch_from_gitlab(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        """Main method to fetch data from GitLab."""
        logger.info("Starting GitLab data fetch process")

        if self.gitlab_client is None:
            logger.error("GitLab client not initialized")
            raise ConnectorMissingCredentialError("Gitlab")

        # Log the fetch parameters
        if start:
            logger.info("Fetch start time: %s", start)
        if end:
            logger.info("Fetch end time: %s", end)

        # A poll window starting at (or before) the cutoff means Onyx is asking
        # for a full index (first attempt / re-index from scratch), so we index
        # every file. Otherwise we only re-index files changed since `start`.
        is_full_index = (
            start is None or _ensure_utc_datetime(start) <= _FULL_INDEX_START_CUTOFF
        )

        try:
            # Clone repository if including code files
            if self.include_code_files:
                logger.info("Code files inclusion enabled, starting repository clone")
                self.repo_path = self._clone_repository(
                    since=None if is_full_index else start
                )

                if is_full_index or start is None:
                    logger.info("Performing full index of code files")
                    changed_rel_paths: set[str] | None = None
                else:
                    logger.info("Performing incremental (diff-based) code file sync")
                    changed_rel_paths = self._get_changed_paths_since(start)

                # Yield code file documents
                logger.info("Processing code files")
                yield from self._fetch_code_files(changed_rel_paths)
            else:
                logger.info("Code files inclusion disabled, skipping repository clone")

            # Fetch merge requests
            logger.info("Processing merge requests")
            yield from self._fetch_merge_requests(start, end)

            # Fetch issues
            logger.info("Processing issues")
            yield from self._fetch_issues(start, end)

            logger.info("GitLab data fetch process completed successfully")

        except Exception:
            logger.exception("Error during GitLab data fetch")
            raise
        finally:
            # Always cleanup cloned repository
            logger.info("Starting cleanup process")
            self._cleanup_repository()

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load all documents from GitLab."""
        logger.info("Starting full load from GitLab (load_from_state)")
        return self._fetch_from_gitlab()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Poll GitLab for updates within time range."""
        logger.info("Starting GitLab polling (poll_source) from %s to %s", start, end)
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        logger.info(
            "Converted to datetime range: %s to %s", start_datetime, end_datetime
        )
        return self._fetch_from_gitlab(start_datetime, end_datetime)


if __name__ == "__main__":
    import os

    connector = GitlabConnector(
        project_owner=os.environ["PROJECT_OWNER"],
        project_name=os.environ["PROJECT_NAME"],
        batch_size=10,
        state_filter="all",
        include_mrs=True,
        include_issues=True,
        include_code_files=True,
        code_file_patterns=["*.py", "*.js", "*.ts", "*.md", "Makefile"],
        include_path_patterns=["src/*", "backend/*", "docs/*"],
        exclude_path_patterns=["*_test.py", "*.tmp", "temp/*"],
        clone_depth=1,
        branch="main",
    )
    connector.load_credentials(
        {
            "gitlab_access_token": os.environ["GITLAB_ACCESS_TOKEN"],
            "gitlab_url": os.environ["GITLAB_URL"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
