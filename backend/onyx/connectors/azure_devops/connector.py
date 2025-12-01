"""Azure DevOps connector for indexing Git repositories and Pull Requests."""

import fnmatch
import itertools
from collections import deque
from collections.abc import Iterable
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import TypeVar

from azure.devops.connection import Connection
from azure.devops.v7_1.git import GitClient
from azure.devops.v7_1.git.models import (
    GitPullRequest,
    GitRepository,
    GitItem,
    GitVersionDescriptor,
)
from msrest.authentication import BasicAuthentication

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
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.utils.logger import setup_logger

T = TypeVar("T")

logger = setup_logger()

# File extensions to index for code files
CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cs", ".cpp", ".c", ".h",
    ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".sql", ".sh",
    ".bash", ".ps1", ".yaml", ".yml", ".json", ".xml", ".html", ".css",
    ".md", ".rst", ".txt", ".dockerfile", ".tf", ".bicep",
}

# Directories/files to exclude from indexing
EXCLUDE_PATTERNS = [
    "node_modules/",
    ".git/",
    ".github/",
    ".vscode/",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "bin/",
    "obj/",
    "dist/",
    "build/",
    ".env",
    "*.lock",
    "package-lock.json",
    "yarn.lock",
]


def _batch_objects(objects: Iterable[T], batch_size: int) -> Iterator[list[T]]:
    """Batch objects into chunks of batch_size."""
    it = iter(objects)
    while True:
        batch = list(itertools.islice(it, batch_size))
        if not batch:
            break
        yield batch


def _should_exclude(path: str) -> bool:
    """Check if a path matches any of the exclude patterns."""
    # Normalize path: remove leading slash if present
    normalized_path = path.lstrip("/")
    
    for pattern in EXCLUDE_PATTERNS:
        # Check if pattern appears anywhere in the path
        if pattern.endswith("/"):
            # Directory pattern - check if it appears as a path component
            dir_name = pattern.rstrip("/")
            # Check if directory name appears in path components
            if dir_name in normalized_path.split("/"):
                return True
        else:
            # File pattern - use fnmatch on the full path or filename
            if fnmatch.fnmatch(normalized_path, pattern):
                return True
            # Also check just the filename
            filename = normalized_path.split("/")[-1] if "/" in normalized_path else normalized_path
            if fnmatch.fnmatch(filename, pattern):
                return True
    return False


def _should_index_file(path: str) -> bool:
    """Check if a file should be indexed based on its extension."""
    if _should_exclude(path):
        return False
    # Check if file has an indexable extension
    for ext in CODE_EXTENSIONS:
        if path.lower().endswith(ext):
            return True
    return False


def _get_author(author_info: dict[str, Any] | None) -> BasicExpertInfo:
    """Extract author information."""
    if not author_info:
        return BasicExpertInfo(display_name="Unknown")
    return BasicExpertInfo(
        display_name=author_info.get("displayName"),
        email=author_info.get("uniqueName"),
    )


def _convert_pr_to_document(
    pr: GitPullRequest,
    organization: str,
    project: str,
    repo_name: str,
) -> Document:
    """Convert an Azure DevOps Pull Request to an Onyx Document."""
    pr_id = pr.pull_request_id
    title = pr.title or ""
    description = pr.description or ""
    status = pr.status or "unknown"
    source_ref = pr.source_ref_name or ""
    target_ref = pr.target_ref_name or ""
    merge_status = pr.merge_status or ""
    closed_date = pr.closed_date
    creation_date = pr.creation_date
    created_by = pr.created_by
    
    pr_url = f"https://dev.azure.com/{organization}/{project}/_git/{repo_name}/pullrequest/{pr_id}"
    
    # Get creator info - created_by is IdentityRef object
    creator = None
    if created_by:
        creator = BasicExpertInfo(
            display_name=created_by.display_name,
            email=created_by.unique_name if hasattr(created_by, 'unique_name') else None,
        )
    
    # Parse dates - API returns datetime objects
    doc_date = None
    if closed_date:
        doc_date = closed_date.replace(tzinfo=timezone.utc) if closed_date.tzinfo is None else closed_date
    elif creation_date:
        doc_date = creation_date.replace(tzinfo=timezone.utc) if creation_date.tzinfo is None else creation_date
    
    return Document(
        id=pr_url,
        sections=[TextSection(link=pr_url, text=description)],
        source=DocumentSource.AZURE_DEVOPS,
        semantic_identifier=f"PR #{pr_id}: {title}",
        doc_updated_at=doc_date,
        primary_owners=[creator] if creator else None,
        metadata={
            "object_type": "PullRequest",
            "id": str(pr_id),
            "status": status,
            "source_branch": source_ref,
            "target_branch": target_ref,
            "repo": repo_name,
            "project": project,
            "merge_status": merge_status,
        },
    )


def _convert_code_file_to_document(
    item: GitItem,
    content: str,
    organization: str,
    project: str,
    repo_name: str,
    default_branch: str,
) -> Document:
    """Convert a code file to an Onyx Document."""
    item_path = item.path
    
    file_path = item_path.lstrip("/")
    file_url = f"https://dev.azure.com/{organization}/{project}/_git/{repo_name}?path={item_path}&version=GB{default_branch}"
    file_name = file_path.split("/")[-1] if "/" in file_path else file_path
    
    return Document(
        id=f"{organization}/{project}/{repo_name}/{file_path}",
        sections=[TextSection(link=file_url, text=content)],
        source=DocumentSource.AZURE_DEVOPS,
        semantic_identifier=file_name,
        doc_updated_at=datetime.now(timezone.utc),
        metadata={
            "object_type": "CodeFile",
            "file_path": file_path,
            "repo": repo_name,
            "project": project,
        },
    )


class AzureDevOpsConnector(LoadConnector, PollConnector):
    """Connector for indexing Azure DevOps Git repositories and Pull Requests."""
    
    def __init__(
        self,
        organization: str,
        project: str | None = None,
        repositories: str | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        include_code_files: bool = True,
        include_prs: bool = True,
        state_filter: str = "all",  # all, active, completed, abandoned
    ) -> None:
        self.organization = organization
        self.project = project
        self.repositories = repositories
        self.batch_size = batch_size
        self.include_code_files = include_code_files
        self.include_prs = include_prs
        self.state_filter = state_filter
        
        self._connection: Connection | None = None
        self._git_client: GitClient | None = None
    
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load Azure DevOps credentials (Personal Access Token)."""
        pat = credentials.get("azure_devops_pat")
        if not pat:
            raise ConnectorMissingCredentialError("Azure DevOps")
        
        # Create connection to Azure DevOps
        organization_url = f"https://dev.azure.com/{self.organization}"
        credentials_auth = BasicAuthentication("", pat)
        self._connection = Connection(base_url=organization_url, creds=credentials_auth)
        self._git_client = self._connection.clients.get_git_client()
        
        return None
    
    def _get_repositories(self) -> list[GitRepository]:
        """Get list of repositories to index."""
        if self._git_client is None:
            raise ConnectorMissingCredentialError("Azure DevOps")
        
        repos = []
        
        if self.repositories:
            # Specific repositories requested
            repo_names = [r.strip() for r in self.repositories.split(",")]
            for repo_name in repo_names:
                try:
                    repo = self._git_client.get_repository(
                        repository_id=repo_name,
                        project=self.project,
                    )
                    if repo:
                        repos.append(repo)
                except Exception as e:
                    logger.warning(f"Could not fetch repository {repo_name}: {e}")
        else:
            # Get all repositories in project(s)
            try:
                all_repos = self._git_client.get_repositories(project=self.project)
                repos = list(all_repos) if all_repos else []
            except Exception as e:
                logger.error(f"Error fetching repositories: {e}")
        
        return repos
    
    def _fetch_code_files(
        self,
        repo: GitRepository,
    ) -> Iterator[Document]:
        """Fetch and yield code files from a repository."""
        if self._git_client is None:
            raise ConnectorMissingCredentialError("Azure DevOps")
        
        project_name = repo.project.name if repo.project else self.project
        if not project_name:
            logger.warning(f"No project name for repo {repo.name}, skipping code files")
            return
        
        default_branch = repo.default_branch
        if default_branch:
            # Remove refs/heads/ prefix if present
            default_branch = default_branch.replace("refs/heads/", "")
        else:
            default_branch = "main"
        
        # Create version descriptor for branch
        version_desc = GitVersionDescriptor(
            version=default_branch,
            version_type="branch",
        )
        
        # Use BFS to traverse repository tree
        queue: deque[str] = deque([""])
        
        while queue:
            current_path = queue.popleft()
            
            try:
                items = self._git_client.get_items(
                    repository_id=repo.id,
                    project=project_name,
                    scope_path=current_path if current_path else None,
                    recursion_level="OneLevel",
                    version_descriptor=version_desc,
                )
                
                if not items:
                    continue
                
                for item in items:
                    # GitClient.get_items returns GitItem objects
                    item_path = item.path
                    is_folder = item.is_folder
                    
                    if not item_path or item_path == current_path:
                        continue
                    
                    if _should_exclude(item_path):
                        continue
                    
                    if is_folder:
                        queue.append(item_path)
                    elif _should_index_file(item_path):
                        try:
                            # Get file content
                            content_stream = self._git_client.get_item_content(
                                repository_id=repo.id,
                                project=project_name,
                                path=item_path,
                                version_descriptor=version_desc,
                            )
                            
                            # Read content
                            content_bytes = b"".join(content_stream)
                            try:
                                content = content_bytes.decode("utf-8")
                            except UnicodeDecodeError:
                                content = content_bytes.decode("latin-1")
                            
                            yield _convert_code_file_to_document(
                                item=item,
                                content=content,
                                organization=self.organization,
                                project=project_name,
                                repo_name=repo.name,
                                default_branch=default_branch,
                            )
                        except Exception as e:
                            logger.warning(f"Error fetching file {item_path}: {e}")
                            
            except Exception as e:
                logger.warning(f"Error listing items in {current_path}: {e}")
    
    def _fetch_pull_requests(
        self,
        repo: GitRepository,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Iterator[Document]:
        """Fetch and yield pull requests from a repository."""
        if self._git_client is None:
            raise ConnectorMissingCredentialError("Azure DevOps")
        
        project_name = repo.project.name if repo.project else self.project
        if not project_name:
            logger.warning(f"No project name for repo {repo.name}, skipping PRs")
            return
        
        # Map state filter to Azure DevOps status
        status_map = {
            "all": "all",
            "active": "active",
            "completed": "completed",
            "abandoned": "abandoned",
        }
        status = status_map.get(self.state_filter, "all")
        
        try:
            pull_requests = self._git_client.get_pull_requests(
                repository_id=repo.id,
                project=project_name,
                search_criteria={
                    "status": status,
                },
            )
            
            if not pull_requests:
                return
            
            for pr in pull_requests:
                # GitClient.get_pull_requests returns GitPullRequest objects
                closed_date = pr.closed_date
                creation_date = pr.creation_date
                
                # API returns datetime objects
                pr_date = closed_date or creation_date
                if pr_date:
                    pr_date = pr_date.replace(tzinfo=timezone.utc) if pr_date.tzinfo is None else pr_date
                    
                    if start and pr_date < start:
                        continue
                    if end and pr_date > end:
                        continue
                
                yield _convert_pr_to_document(
                    pr=pr,
                    organization=self.organization,
                    project=project_name,
                    repo_name=repo.name,
                )
                
        except Exception as e:
            logger.error(f"Error fetching pull requests for {repo.name}: {e}")
    
    def _fetch_from_azure_devops(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> GenerateDocumentsOutput:
        """Fetch documents from Azure DevOps."""
        if self._git_client is None:
            raise ConnectorMissingCredentialError("Azure DevOps")
        
        repos = self._get_repositories()
        
        for repo in repos:
            logger.info(f"Processing repository: {repo.name}")
            
            # Fetch code files
            if self.include_code_files:
                doc_batch: list[Document] = []
                for doc in self._fetch_code_files(repo):
                    doc_batch.append(doc)
                    if len(doc_batch) >= self.batch_size:
                        yield doc_batch
                        doc_batch = []
                if doc_batch:
                    yield doc_batch
            
            # Fetch pull requests
            if self.include_prs:
                doc_batch = []
                for doc in self._fetch_pull_requests(repo, start, end):
                    doc_batch.append(doc)
                    if len(doc_batch) >= self.batch_size:
                        yield doc_batch
                        doc_batch = []
                if doc_batch:
                    yield doc_batch
    
    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load all documents (full sync)."""
        return self._fetch_from_azure_devops()
    
    def poll_source(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> GenerateDocumentsOutput:
        """Poll for updated documents within the time range."""
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        return self._fetch_from_azure_devops(start_datetime, end_datetime)

    # --- CheckpointedConnector compatibility ---
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ConnectorCheckpoint,
    ) -> Iterator[Document | ConnectorFailure]:
        """Checkpointed loading interface expected by the test harness.

        This implementation maps to the existing polling/load logic. It yields
        individual Document objects (or ConnectorFailure) and returns a final
        ConnectorCheckpoint indicating there is no more data.
        """
        if self._git_client is None:
            raise ConnectorMissingCredentialError("Azure DevOps")

        start_dt = datetime.fromtimestamp(start, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end, tz=timezone.utc)

        try:
            for doc_batch in self._fetch_from_azure_devops(start_dt, end_dt):
                for doc in doc_batch:
                    yield doc
        except Exception as e:
            # Wrap unexpected errors as ConnectorFailure so the runner can handle them
            yield ConnectorFailure(failure_message=str(e), failed_document=None, failed_entity=None, exception=e)

        # Final checkpoint indicates no more data
        return ConnectorCheckpoint(has_more=False)

    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ConnectorCheckpoint,
    ) -> Iterator[Document | ConnectorFailure]:
        """For now, permission sync is not implemented; behave like load_from_checkpoint."""
        yield from self.load_from_checkpoint(start, end, checkpoint)

    def build_dummy_checkpoint(self) -> ConnectorCheckpoint:
        """Return an initial checkpoint object for the test harness."""
        return ConnectorCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> ConnectorCheckpoint:
        """Simple validator that returns a ConnectorCheckpoint. This can be extended if
        we store checkpoints with more structure later.
        """
        # Best-effort: ignore contents and return a checkpoint with has_more=True
        return ConnectorCheckpoint(has_more=True)


if __name__ == "__main__":
    import os
    
    connector = AzureDevOpsConnector(
        organization=os.environ["AZURE_DEVOPS_ORG"],
        project=os.environ.get("AZURE_DEVOPS_PROJECT"),
        repositories=os.environ.get("AZURE_DEVOPS_REPOS"),
        include_code_files=True,
        include_prs=True,
    )
    
    connector.load_credentials({
        "azure_devops_pat": os.environ["AZURE_DEVOPS_PAT"],
    })
    
    for doc_batch in connector.load_from_state():
        print(f"Got {len(doc_batch)} documents")
        for doc in doc_batch[:2]:  # Print first 2 of each batch
            print(f"  - {doc.semantic_identifier}")
