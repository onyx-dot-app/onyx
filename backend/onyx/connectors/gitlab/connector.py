import fnmatch
import itertools
import re
import tempfile
import shutil
import os
from collections import deque
from collections.abc import Iterable
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import TypeVar

import git
import gitlab
import pytz
from gitlab.v4.objects import Project

from onyx.configs.app_configs import GITLAB_CONNECTOR_INCLUDE_CODE_FILES
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
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

# Common file extensions to include for code files
code_file_extensions = {
    '.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.hpp', '.cs', '.php',
    '.rb', '.go', '.rs', '.kt', '.scala', '.swift', '.m', '.mm', '.r', '.R',
    '.sql', '.html', '.htm', '.css', '.scss', '.sass', '.less', '.xml', '.json',
    '.yaml', '.yml', '.toml', '.ini', '.cfg', '.config', '.md', '.rst', '.txt',
    '.sh', '.bash', '.ps1', '.bat', '.cmd', '.dockerfile', '.makefile', '   .bazel'
}


def _ensure_utc_datetime(dt: datetime) -> datetime:
    """Ensure datetime has UTC timezone information."""
    if dt is None:
        return datetime.now(timezone.utc)
    
    if dt.tzinfo is None:
        # If no timezone info, assume UTC
        return dt.replace(tzinfo=timezone.utc)
    
    # If timezone info exists, convert to UTC
    return dt.astimezone(timezone.utc)


def _batch_gitlab_objects(git_objs: Iterable[T], batch_size: int) -> Iterator[list[T]]:
    """Batch GitLab objects into chunks."""
    logger.debug(f"Starting to batch objects with batch size: {batch_size}")
    it = iter(git_objs)
    batch_count = 0
    while True:
        batch = list(itertools.islice(it, batch_size))
        if not batch:
            logger.debug(f"Finished batching. Total batches created: {batch_count}")
            break
        batch_count += 1
        logger.debug(f"Created batch #{batch_count} with {len(batch)} objects")
        yield batch


def get_author(author: Any) -> BasicExpertInfo:
    """Convert author info to BasicExpertInfo."""
    author_name = author.get("name") if author else "Unknown"
    logger.debug(f"Converting author info: {author_name}")
    return BasicExpertInfo(
        display_name=author_name,
    )


def _convert_merge_request_to_document(mr: Any) -> Document:
    """Convert GitLab merge request to Document."""
    logger.debug(f"Converting merge request to document: {mr.title} (ID: {mr.id})")
    logger.debug(f"MR state: {mr.state}, updated_at: {mr.updated_at}")
    
    # Ensure updated_at is properly formatted UTC datetime
    updated_at = _ensure_utc_datetime(mr.updated_at)
    
    doc = Document(
        id=mr.web_url,
        sections=[TextSection(link=mr.web_url, text=mr.description or "")],
        source=DocumentSource.GITLAB,
        semantic_identifier=mr.title,
        doc_updated_at=updated_at,
        primary_owners=[get_author(mr.author)],
        metadata={"state": mr.state, "type": "MergeRequest"},
    )
    logger.debug(f"Successfully converted MR document: {doc.semantic_identifier}")
    return doc


def _convert_issue_to_document(issue: Any) -> Document:
    """Convert GitLab issue to Document."""
    logger.debug(f"Converting issue to document: {issue.title} (ID: {issue.id})")
    logger.debug(f"Issue state: {issue.state}, type: {getattr(issue, 'type', 'Issue')}, updated_at: {issue.updated_at}")
    
    # Ensure updated_at is properly formatted UTC datetime
    updated_at = _ensure_utc_datetime(issue.updated_at)
    
    doc = Document(
        id=issue.web_url,
        sections=[TextSection(link=issue.web_url, text=issue.description or "")],
        source=DocumentSource.GITLAB,
        semantic_identifier=issue.title,
        doc_updated_at=updated_at,
        primary_owners=[get_author(issue.author)],
        metadata={"state": issue.state, "type": issue.type if issue.type else "Issue"},
    )
    logger.debug(f"Successfully converted issue document: {doc.semantic_identifier}")
    return doc


def _convert_file_to_document(
    file_path: Path, 
    repo_path: Path, 
    project_url: str, 
    project_name: str, 
    project_owner: str,
    default_branch: str,
    last_commit_date: datetime = None
) -> Document:
    """Convert a file to Document."""
    logger.debug(f"Converting file to document: {file_path}")
    
    try:
        # Read file content
        logger.debug(f"Attempting to read file content with UTF-8 encoding")
        with open(file_path, 'r', encoding='utf-8') as f:
            file_content = f.read()
        logger.debug(f"Successfully read file content ({len(file_content)} characters)")
    except UnicodeDecodeError:
        logger.warning(f"UTF-8 decode failed for {file_path}, trying latin-1")
        try:
            with open(file_path, 'r', encoding='latin-1') as f:
                file_content = f.read()
            logger.debug(f"Successfully read file content with latin-1 ({len(file_content)} characters)")
        except Exception as e:
            logger.error(f"Could not read file {file_path} with latin-1: {e}")
            file_content = f"[Could not read file content: {e}]"
    except Exception as e:
        logger.error(f"Could not read file {file_path}: {e}")
        file_content = f"[Could not read file content: {e}]"

    # Get relative path from repo root
    relative_path = file_path.relative_to(repo_path)
    logger.debug(f"File relative path: {relative_path}")
    
    # Construct the file URL
    file_url = f"{project_url}/{project_owner}/{project_name}/-/blob/{default_branch}/{relative_path}"
    logger.debug(f"Constructed file URL: {file_url}")
    
    # Generate unique ID using file path
    file_id = f"{project_url}/{project_owner}/{project_name}/blob/{default_branch}/{relative_path}"
    logger.debug(f"Generated file ID: {file_id}")
    
    # Use last commit date if available, otherwise current time - ensure UTC
    doc_updated_at = _ensure_utc_datetime(last_commit_date)
    logger.debug(f"Document updated_at: {doc_updated_at}")
    
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
    logger.debug(f"Successfully converted file document: {doc.semantic_identifier}")
    return doc


def _should_exclude_by_patterns(path: str, patterns: list[str]) -> bool:
    """Check if a path matches any of the exclude patterns."""
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            logger.debug(f"Path '{path}' excluded by pattern '{pattern}'")
            return True
    return False


def _should_include_by_regex(path: str, include_patterns: list[str]) -> bool:
    """Check if a path matches any of the include regex patterns."""
    if not include_patterns:
        logger.debug(f"No include patterns specified, including path: {path}")
        return True  # If no include patterns specified, include all
    
    for pattern in include_patterns:
        if re.search(pattern, path):
            logger.debug(f"Path '{path}' included by regex pattern '{pattern}'")
            return True
    
    logger.debug(f"Path '{path}' does not match any include patterns")
    return False


def _should_exclude_by_regex(path: str, exclude_patterns: list[str]) -> bool:
    """Check if a path matches any of the exclude regex patterns."""
    if not exclude_patterns:
        return False  # If no exclude patterns specified, exclude none
    
    for pattern in exclude_patterns:
        if re.search(pattern, path):
            logger.debug(f"Path '{path}' excluded by regex pattern '{pattern}'")
            return True
            
    return False


def _is_code_file(file_path: Path) -> bool:
    """Check if file is a code file based on extension."""
    is_code = file_path.suffix.lower() in code_file_extensions
    logger.debug(f"File '{file_path}' is {'a' if is_code else 'not a'} code file (extension: {file_path.suffix})")
    return is_code


def _get_file_last_commit_date(repo: git.Repo, file_path: str) -> datetime:
    """Get the last commit date for a specific file."""
    logger.debug(f"Getting last commit date for file: {file_path}")
    try:
        commits = list(repo.iter_commits(paths=file_path, max_count=1))
        if commits:
            commit_date = commits[0].committed_datetime
            # Ensure timezone info is present and convert to UTC
            commit_date = _ensure_utc_datetime(commit_date)
            logger.debug(f"Last commit date for '{file_path}': {commit_date}")
            return commit_date
        else:
            logger.debug(f"No commits found for file: {file_path}")
    except Exception as e:
        logger.warning(f"Could not get commit date for {file_path}: {e}")
    
    fallback_date = datetime.now(timezone.utc)
    logger.debug(f"Using fallback date for '{file_path}': {fallback_date}")
    return fallback_date


class GitlabConnector(LoadConnector, PollConnector):
    """Enhanced GitLab connector that clones entire repository and indexes with regex filtering."""
    
    def __init__(
        self,
        project_owner: str,
        project_name: str,
        batch_size: int = INDEX_BATCH_SIZE,
        state_filter: str = "all",
        include_mrs: bool = True,
        include_issues: bool = True,
        include_code_files: bool = GITLAB_CONNECTOR_INCLUDE_CODE_FILES,
        include_path_patterns: list[str] = None,  # Regex patterns for paths to include
        exclude_path_patterns: list[str] = None,  # Regex patterns for paths to exclude
        clone_depth: int = None,  # Git clone depth (None for full clone)
        branch: str = None,  # Specific branch to clone (None for default)
    ) -> None:
        def compile_patterns(patterns):
            compiled = []
            for pattern in patterns or []:
                if isinstance(pattern, str):
                    try:
                        compiled.append(re.compile(pattern))
                    except re.error as e:
                        logger.warning(f"Invalid regex pattern '{pattern}': {e}. Skipping.")
                elif isinstance(pattern, re.Pattern):
                    compiled.append(pattern)
                else:
                    logger.warning(f"Unrecognized pattern type: {type(pattern)}. Skipping: {pattern}")
            return compiled

        include_path_patterns = compile_patterns(include_path_patterns)
        exclude_path_patterns = compile_patterns(exclude_path_patterns)

        logger.info(f"Initializing GitlabConnector for {project_owner}/{project_name}")
        logger.debug(f"Configuration - batch_size: {batch_size}, state_filter: {state_filter}")
        logger.debug(f"Include options - MRs: {include_mrs}, Issues: {include_issues}, Code files: {include_code_files}")
        logger.debug(f"Filter patterns - Include: {include_path_patterns}, Exclude: {exclude_path_patterns}")
        logger.debug(f"Clone options - Depth: {clone_depth}, Branch: {branch}")
    
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
        self.gitlab_client: gitlab.Gitlab | None = None
        self.repo_path: Path | None = None
        self.git_repo: git.Repo | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load GitLab credentials."""
        logger.info("Loading GitLab credentials")
        gitlab_url = credentials.get("gitlab_url", "Unknown")
        logger.debug(f"GitLab URL: {gitlab_url}")
        self.gitlab_url = gitlab_url
        
        try:
            self.gitlab_client = gitlab.Gitlab(
                credentials["gitlab_url"], private_token=credentials["gitlab_access_token"]
            )
            # Test the connection
            self.gitlab_client.auth()
            logger.info("Successfully authenticated with GitLab")
        except Exception as e:
            logger.error(f"Failed to authenticate with GitLab: {e}")
            raise
            
        return None

    def _clone_repository(self) -> Path:
        """Clone the entire repository to a temporary directory."""
        logger.info(f"Starting repository clone process for {self.project_owner}/{self.project_name}")
        
        if self.gitlab_client is None:
            logger.error("GitLab client not initialized")
            raise ConnectorMissingCredentialError("Gitlab")
            
        try:
            logger.debug(f"Fetching project information from GitLab API")
            project: Project = self.gitlab_client.projects.get(
                f"{self.project_owner}/{self.project_name}"
            )
            logger.info(f"Found project: {project.name} (ID: {project.id})")
        except Exception as e:
            logger.error(f"Failed to fetch project information: {e}")
            raise
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp(prefix=f"gitlab_repo_{self.project_name}_")
        repo_path = Path(temp_dir)
        logger.info(f"Created temporary directory: {repo_path}")
        
        try:
            # Get clone URL with token
            clone_url = project.http_url_to_repo
            logger.debug(f"Original clone URL: {clone_url}")
            
            if self.gitlab_client.private_token:
                # Insert token into URL for authentication
                clone_url = clone_url.replace(
                    "://", 
                    f"://oauth2:{self.gitlab_client.private_token}@"
                )
                logger.debug("Added authentication token to clone URL")
            
            # Clone repository
            clone_kwargs = {
                'url': clone_url,
                'to_path': str(repo_path),
            }
            
            if self.clone_depth:
                clone_kwargs['depth'] = self.clone_depth
                logger.debug(f"Using shallow clone with depth: {self.clone_depth}")
                
            if self.branch:
                clone_kwargs['branch'] = self.branch
                logger.debug(f"Cloning specific branch: {self.branch}")
            
            logger.info("Starting git clone operation...")
            self.git_repo = git.Repo.clone_from(**clone_kwargs)
            
            # Log repository information
            active_branch = self.git_repo.active_branch.name
            commit_count = sum(1 for _ in self.git_repo.iter_commits())
            logger.info(f"Successfully cloned repository - Active branch: {active_branch}, Commits: {commit_count}")
            
            return repo_path
            
        except Exception as e:
            logger.error('Failed to clone repository')
            # Clean up on failure
            shutil.rmtree(repo_path, ignore_errors=True)
            raise Exception(f"Failed to clone repository")

    def _cleanup_repository(self):
        """Clean up cloned repository."""
        if self.repo_path and self.repo_path.exists():
            logger.info(f"Cleaning up repository at {self.repo_path}")
            try:
                shutil.rmtree(self.repo_path, ignore_errors=True)
                logger.debug("Repository cleanup completed successfully")
            except Exception as e:
                logger.warning(f"Error during repository cleanup: {e}")
            finally:
                self.repo_path = None
                self.git_repo = None
        else:
            logger.debug("No repository to clean up")

    def _get_filtered_files(self) -> list[Path]:
        """Get list of files that match the filtering criteria."""
        logger.info("Starting file filtering process")
        
        if not self.repo_path:
            logger.warning("Repository path not available")
            return []
            
        all_files = []
        total_files_scanned = 0
        excluded_by_default = 0
        excluded_by_regex = 0
        excluded_by_include_filter = 0
        excluded_not_code = 0
        
        # Walk through all files in the repository
        logger.debug(f"Scanning files in repository: {self.repo_path}")
        for root, dirs, files in os.walk(self.repo_path):
            # Skip .git directory
            if '.git' in dirs:
                dirs.remove('.git')
                logger.debug("Skipped .git directory")
                
            for file in files:
                total_files_scanned += 1
                file_path = Path(root) / file
                relative_path = str(file_path.relative_to(self.repo_path))
                
                # Apply default exclude patterns
                if _should_exclude_by_patterns(relative_path, exclude_patterns):
                    excluded_by_default += 1
                    continue
                    
                # Apply regex exclude patterns
                if _should_exclude_by_regex(relative_path, self.exclude_path_patterns):
                    excluded_by_regex += 1
                    continue
                    
                # Apply regex include patterns
                if not _should_include_by_regex(relative_path, self.include_path_patterns):
                    excluded_by_include_filter += 1
                    continue
                    
                # Check if it's a code file (if we're only including code files)
                if self.include_code_files and not _is_code_file(file_path):
                    excluded_not_code += 1
                    continue
                    
                all_files.append(file_path)
                logger.debug(f"Included file: {relative_path}")
        
        # Log filtering statistics
        logger.info(f"File filtering completed:")
        logger.info(f"  Total files scanned: {total_files_scanned}")
        logger.info(f"  Excluded by default patterns: {excluded_by_default}")
        logger.info(f"  Excluded by regex patterns: {excluded_by_regex}")
        logger.info(f"  Excluded by include filter: {excluded_by_include_filter}")
        logger.info(f"  Excluded (not code files): {excluded_not_code}")
        logger.info(f"  Final files included: {len(all_files)}")
        
        return all_files

    def _fetch_code_files(self) -> GenerateDocumentsOutput:
        """Fetch and convert code files to documents."""
        logger.info("Starting code files fetch process")
        
        if not self.include_code_files:
            logger.info("Code files inclusion disabled, skipping")
            return
            
        if not self.repo_path:
            logger.error("Repository path not available for code files processing")
            return
            
        filtered_files = self._get_filtered_files()
        
        if not filtered_files:
            logger.warning("No files found matching filter criteria")
            return
        
        # Get project info for URL construction
        try:
            project: Project = self.gitlab_client.projects.get(
                f"{self.project_owner}/{self.project_name}"
            )
            default_branch = self.branch or project.default_branch
            logger.info(f"Using branch '{default_branch}' for URL construction")
        except Exception as e:
            logger.error(f"Failed to get project information: {e}")
            raise
        
        # Process files in batches
        logger.info(f"Processing {len(filtered_files)} files in batches of {self.batch_size}")
        batch_count = 0
        total_documents = 0
        
        for file_batch in _batch_gitlab_objects(filtered_files, self.batch_size):
            batch_count += 1
            logger.info(f"Processing code file batch #{batch_count} ({len(file_batch)} files)")
            
            code_doc_batch: list[Document] = []
            
            for file_path in file_batch:
                try:
                    # Get last commit date for the file
                    relative_path = str(file_path.relative_to(self.repo_path))
                    last_commit_date = None
                    if self.git_repo:
                        last_commit_date = _get_file_last_commit_date(self.git_repo, relative_path)
                    
                    doc = _convert_file_to_document(
                        file_path=file_path,
                        repo_path=self.repo_path,
                        project_url=self.gitlab_url,
                        project_name=self.project_name,
                        project_owner=self.project_owner,
                        default_branch=default_branch,
                        last_commit_date=last_commit_date
                    )
                    code_doc_batch.append(doc)
                    total_documents += 1
                    
                except Exception as e:
                    logger.error(f"Error processing file {file_path}: {e}")
                    continue
                    
            if code_doc_batch:
                logger.info(f"Yielding batch #{batch_count} with {len(code_doc_batch)} code documents")
                yield code_doc_batch
        
        logger.info(f"Code files processing completed. Total documents: {total_documents}")

    def _fetch_merge_requests(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        """Fetch merge requests."""
        logger.info("Starting merge requests fetch process")
        
        if not self.include_mrs:
            logger.info("Merge requests inclusion disabled, skipping")
            return
        
        if start:
            logger.info(f"Fetching MRs updated after: {start}")
        if end:
            logger.info(f"Fetching MRs updated before: {end}")
            
        try:
            project: Project = self.gitlab_client.projects.get(
                f"{self.project_owner}/{self.project_name}"
            )
            logger.debug(f"Fetching merge requests with state filter: {self.state_filter}")
        except Exception as e:
            logger.error(f"Failed to get project for MRs: {e}")
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
            logger.error(f"Failed to get merge requests list: {e}")
            raise

        batch_count = 0
        total_mrs = 0
        
        for mr_batch in _batch_gitlab_objects(merge_requests, self.batch_size):
            batch_count += 1
            logger.info(f"Processing MR batch #{batch_count} ({len(mr_batch)} MRs)")
            
            mr_doc_batch: list[Document] = []
            for mr in mr_batch:
                try:
                    # Parse the datetime string properly
                    if isinstance(mr.updated_at, str):
                        mr.updated_at = datetime.strptime(
                            mr.updated_at, "%Y-%m-%dT%H:%M:%S.%f%z"
                        )
                    
                    # Ensure UTC timezone
                    mr.updated_at = _ensure_utc_datetime(mr.updated_at)
                    
                    # Time filtering
                    if start is not None:
                        start_utc = _ensure_utc_datetime(start)
                        if mr.updated_at < start_utc:
                            logger.debug(f"MR {mr.title} is older than start time, stopping")
                            if mr_doc_batch:
                                yield mr_doc_batch
                            return
                    if end is not None:
                        end_utc = _ensure_utc_datetime(end)
                        if mr.updated_at > end_utc:
                            logger.debug(f"MR {mr.title} is newer than end time, skipping")
                            continue
                    
                    mr_doc_batch.append(_convert_merge_request_to_document(mr))
                    total_mrs += 1
                    
                except Exception as e:
                    logger.error(f"Error processing MR {getattr(mr, 'title', 'Unknown')}: {e}")
                    continue
                    
            if mr_doc_batch:
                logger.info(f"Yielding MR batch #{batch_count} with {len(mr_doc_batch)} documents")
                yield mr_doc_batch
        
        logger.info(f"Merge requests processing completed. Total MRs: {total_mrs}")

    def _fetch_issues(
        self, start: datetime | None = None, end: datetime | None = None
    ) -> GenerateDocumentsOutput:
        """Fetch issues."""
        logger.info("Starting issues fetch process")
        
        if not self.include_issues:
            logger.info("Issues inclusion disabled, skipping")
            return
        
        if start:
            logger.info(f"Fetching issues updated after: {start}")
        if end:
            logger.info(f"Fetching issues updated before: {end}")
            
        try:
            project: Project = self.gitlab_client.projects.get(
                f"{self.project_owner}/{self.project_name}"
            )
            logger.debug(f"Fetching issues with state filter: {self.state_filter}")
        except Exception as e:
            logger.error(f"Failed to get project for issues: {e}")
            raise
        
        try:
            issues = project.issues.list(state=self.state_filter, iterator=True)
            logger.debug("Successfully initialized issues iterator")
        except Exception as e:
            logger.error(f"Failed to get issues list: {e}")
            raise

        batch_count = 0
        total_issues = 0

        for issue_batch in _batch_gitlab_objects(issues, self.batch_size):
            batch_count += 1
            logger.info(f"Processing issue batch #{batch_count} ({len(issue_batch)} issues)")
            
            issue_doc_batch: list[Document] = []
            for issue in issue_batch:
                try:
                    # Parse the datetime string properly
                    if isinstance(issue.updated_at, str):
                        issue.updated_at = datetime.strptime(
                            issue.updated_at, "%Y-%m-%dT%H:%M:%S.%f%z"
                        )
                    
                    # Ensure UTC timezone
                    issue.updated_at = _ensure_utc_datetime(issue.updated_at)
                    
                    # Time filtering
                    if start is not None:
                        start_utc = _ensure_utc_datetime(start)
                        if issue.updated_at < start_utc:
                            logger.debug(f"Issue {issue.title} is older than start time, stopping")
                            if issue_doc_batch:
                                yield issue_doc_batch
                            return
                    if end is not None:
                        end_utc = _ensure_utc_datetime(end)
                        if issue.updated_at > end_utc:
                            logger.debug(f"Issue {issue.title} is newer than end time, skipping")
                            continue
                    
                    issue_doc_batch.append(_convert_issue_to_document(issue))
                    total_issues += 1
                    
                except Exception as e:
                    logger.error(f"Error processing issue {getattr(issue, 'title', 'Unknown')}: {e}")
                    continue
                    
            if issue_doc_batch:
                logger.info(f"Yielding issue batch #{batch_count} with {len(issue_doc_batch)} documents")
                yield issue_doc_batch
        
        logger.info(f"Issues processing completed. Total issues: {total_issues}")

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
            logger.info(f"Fetch start time: {start}")
        if end:
            logger.info(f"Fetch end time: {end}")

        try:
            # Clone repository if including code files
            if self.include_code_files:
                logger.info("Code files inclusion enabled, starting repository clone")
                self.repo_path = self._clone_repository()
                
                # Yield code file documents
                logger.info("Processing code files")
                yield from self._fetch_code_files()
            else:
                logger.info("Code files inclusion disabled, skipping repository clone")
                
            # Fetch merge requests
            logger.info("Processing merge requests")
            yield from self._fetch_merge_requests(start, end)
            
            # Fetch issues  
            logger.info("Processing issues")
            yield from self._fetch_issues(start, end)
            
            logger.info("GitLab data fetch process completed successfully")
            
        except Exception as e:
            logger.error('Error during GitLab data fetch')
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
        logger.info(f"Starting GitLab polling (poll_source) from {start} to {end}")
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        logger.info(f"Converted to datetime range: {start_datetime} to {end_datetime}")
        return self._fetch_from_gitlab(start_datetime, end_datetime)


if __name__ == "__main__":
    import os

    # Set up more detailed logging for debugging
    import logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('gitlab_connector_debug.log')
        ]
    )

    logger.info("Starting GitLab connector example")

    # Example usage with regex filtering
    connector = GitlabConnector(
        project_owner=os.environ["PROJECT_OWNER"],
        project_name=os.environ["PROJECT_NAME"],
        batch_size=10,
        state_filter="all",
        include_mrs=True,
        include_issues=True,
        include_code_files=True,
        # Include only Python and JavaScript files in specific directories
        include_path_patterns=[
            r"^src/.*\.py$",           # Python files in src directory
            r"^backend/.*\.py$",       # Python files in backend directory  
            r"^frontend/.*\.(js|ts)$", # JS/TS files in frontend directory
            r"^docs/.*\.md$",          # Markdown files in docs directory
        ],
        # Exclude test files and temporary files
        exclude_path_patterns=[
            r".*test.*\.py$",          # Test files
            r".*\.tmp$",               # Temporary files
            r"^temp/.*",               # Anything in temp directory
        ],
        clone_depth=1,  # Shallow clone for faster downloading
        branch="main",  # Specific branch (optional)
    )

    try:
        logger.info("Loading credentials")
        connector.load_credentials(
            {
                "gitlab_access_token": os.environ["GITLAB_ACCESS_TOKEN"],
                "gitlab_url": os.environ["GITLAB_URL"],
            }
        )
        
        logger.info("Starting document processing")
        document_batches = connector.load_from_state()
        
        total_batches = 0
        total_documents = 0
        
        for batch in document_batches:
            total_batches += 1
            total_documents += len(batch)
            logger.info(f"Processed batch #{total_batches} with {len(batch)} documents")
            
            if batch:
                logger.info(f"Sample document from batch: {batch[0].semantic_identifier}")
                logger.debug(f"Document metadata: {batch[0].metadata}")
        
        logger.info(f"Processing completed successfully!")
        logger.info(f"Total batches processed: {total_batches}")
        logger.info(f"Total documents processed: {total_documents}")
        
    except Exception as e:
        logger.error(f"Error during execution: {e}", exc_info=True)
        raise
