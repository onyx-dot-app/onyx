import io
import re
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Generator
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from github import Github
from github import RateLimitExceededException
from github.GithubException import GithubException
from markdown import markdown
from pydantic import BaseModel
from typing_extensions import override

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.github.rate_limit_utils import sleep_after_rate_limit_exception
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Configuration constants
DEFAULT_BRANCH = "gh-pages"
MAX_FILES_PER_SCAN = 1000
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
MAX_RETRIES = 3

# Supported file extensions for indexing
SUPPORTED_EXTENSIONS = {
    ".html", ".htm", ".md", ".markdown", ".txt", ".rst", ".asciidoc", ".adoc"
}

# File extensions to skip
SKIP_EXTENSIONS = {
    ".css", ".js", ".json", ".xml", ".yml", ".yaml", ".toml", ".ini", ".cfg",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf", ".zip", ".tar", ".gz"
}


class GitHubPagesFileInfo(BaseModel):
    """Information about a file in the GitHub Pages repository"""
    path: str  # Relative path for processing (adjusted for root_directory)
    sha: str
    size: int
    url: str
    download_url: str  # Full GitHub raw URL (uses original item.path)
    last_modified: datetime | None = None


class GitHubPagesConnector(LoadConnector, PollConnector):
    """
    Connector for indexing GitHub Pages sites via the GitHub API.
    
    This connector:
    - Retrieves the list of files from a GitHub Pages branch
    - Filters relevant files (HTML, Markdown, etc.)
    - Extracts textual content from files
    - Respects configurable size and quantity limits
    """

    def __init__(
        self,
        repo_owner: str,
        repo_name: str,
        branch: str = DEFAULT_BRANCH,
        root_directory: str = "",
        max_files: int = MAX_FILES_PER_SCAN,
        max_depth: int | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        """
        Initialize the GitHub Pages connector.
        
        Args:
            repo_owner: GitHub repository owner
            repo_name: GitHub repository name
            branch: Branch to scan (default 'gh-pages')
            root_directory: Root directory to scan (default '')
            max_files: Maximum number of files to index
            max_depth: Maximum scan depth (None = unlimited)
            batch_size: Size of document batches
        """
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.branch = branch
        self.root_directory = root_directory.strip("/")
        self.max_files = max_files
        self.max_depth = max_depth
        self.batch_size = batch_size
        self.github_client: Github | None = None
        
        # Build GitHub Pages base URL
        self.pages_base_url = f"https://{repo_owner}.github.io/{repo_name}/"

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load GitHub credentials"""
        github_token = credentials.get("github_access_token")
        if github_token:
            self.github_client = Github(github_token)
        else:
            # Allow access to public repositories without token
            self.github_client = Github()
        return None

    def _should_process_file(self, file_path: str) -> bool:
        """
        Determines if a file should be processed based on its extension.
        
        Args:
            file_path: File path
            
        Returns:
            True if file should be processed, False otherwise
        """
        # Get file extension
        _, ext = file_path.lower().rsplit(".", 1) if "." in file_path else ("", "")
        ext = f".{ext}" if ext else ""
        
        # Check if extension is supported
        if ext in SUPPORTED_EXTENSIONS:
            return True
        
        # Skip unwanted extensions
        if ext in SKIP_EXTENSIONS:
            return False
        
        # For files without extension, check if they contain text
        return ext == ""

    def _respect_depth_limit(self, file_path: str) -> bool:
        """
        Checks if a file respects the depth limit.
        
        Args:
            file_path: File path
            
        Returns:
            True if file respects the limit, False otherwise
        """
        if self.max_depth is None:
            return True
        
        # Count directory levels
        path_parts = file_path.strip("/").split("/")
        depth = len(path_parts) - 1  # -1 because file itself doesn't count
        
        return depth <= self.max_depth

    def _get_repository_tree(self) -> list[GitHubPagesFileInfo]:
        """
        Retrieves the repository file tree recursively.
        
        Returns:
            List of file information
        """
        # Initialize client if not already done (for public repos)
        if not self.github_client:
            self.github_client = Github()
        
        try:
            repo = self.github_client.get_repo(f"{self.repo_owner}/{self.repo_name}")
            
            # Get file tree recursively
            tree = repo.get_git_tree(self.branch, recursive=True)
            
            files_info = []
            processed_count = 0
            
            for item in tree.tree:
                # Ignore directories
                if item.type != "blob":
                    continue
                
                file_path = item.path
                
                # Filter by root directory if specified
                if self.root_directory:
                    if not file_path.startswith(self.root_directory + "/"):
                        continue
                    # Adjust relative path
                    file_path = file_path[len(self.root_directory) + 1:]
                
                # Check depth limits
                if not self._respect_depth_limit(file_path):
                    continue
                
                # Check if file should be processed
                if not self._should_process_file(file_path):
                    continue
                
                # Check file size
                if item.size and item.size > MAX_FILE_SIZE_BYTES:
                    logger.warning(f"File too large, skipping: {file_path} ({item.size} bytes)")
                    continue
                
                # Build download URL - use original item.path for raw GitHub URL
                download_url = f"https://raw.githubusercontent.com/{self.repo_owner}/{self.repo_name}/{self.branch}/{item.path}"
                
                files_info.append(GitHubPagesFileInfo(
                    path=file_path,  # Use adjusted path for processing
                    sha=item.sha,
                    size=item.size or 0,
                    url=item.url,
                    download_url=download_url
                ))
                
                processed_count += 1
                if processed_count >= self.max_files:
                    logger.info(f"File limit reached: {self.max_files}")
                    break
            
            logger.info(f"Found {len(files_info)} files to process")
            return files_info
            
        except GithubException as e:
            if e.status == 401:
                raise CredentialExpiredError("Invalid or expired GitHub token")
            elif e.status == 403:
                raise InsufficientPermissionsError(
                    "Insufficient permissions to access repository"
                )
            elif e.status == 404:
                raise ConnectorValidationError(
                    f"Repository or branch not found: {self.repo_owner}/{self.repo_name}:{self.branch}"
                )
            else:
                raise ConnectorValidationError(f"GitHub API error: {e}")
        
        except RateLimitExceededException:
            logger.warning("GitHub rate limit reached, waiting...")
            sleep_after_rate_limit_exception(self.github_client)
            # Retry after waiting
            return self._get_repository_tree()

    def _download_file_content(self, file_info: GitHubPagesFileInfo) -> str:
        """
        Downloads and processes file content.
        
        Args:
            file_info: File information
            
        Returns:
            Text content of the file
        """
        try:
            response = requests.get(file_info.download_url, timeout=30)
            response.raise_for_status()
            
            # Detect encoding
            content = response.content
            
            # Try different encodings
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    text_content = content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                logger.warning(f"Unable to decode file: {file_info.path}")
                return ""
            
            # Process according to file type
            return self._process_file_content(text_content, file_info.path)
            
        except requests.RequestException as e:
            logger.warning(f"Error downloading {file_info.path}: {e}")
            return ""

    def _process_file_content(self, content: str, file_path: str) -> str:
        """
        Processes file content according to its type.
        
        Args:
            content: Raw file content
            file_path: File path
            
        Returns:
            Processed text content
        """
        _, ext = file_path.lower().rsplit(".", 1) if "." in file_path else ("", "")
        ext = f".{ext}" if ext else ""
        
        if ext in [".html", ".htm"]:
            # HTML processing with BeautifulSoup
            try:
                soup = BeautifulSoup(content, "html.parser")
                parsed_html = web_html_cleanup(soup)
                return parsed_html.cleaned_text
            except Exception as e:
                logger.warning(f"Error parsing HTML from {file_path}: {e}")
                return content
        
        elif ext in [".md", ".markdown"]:
            # Convert Markdown to HTML then extract text
            try:
                html_content = markdown(content)
                soup = BeautifulSoup(html_content, "html.parser")
                return soup.get_text(strip=True)
            except Exception as e:
                logger.warning(f"Error parsing Markdown from {file_path}: {e}")
                return content
        
        elif ext in [".rst"]:
            # Return raw content for reStructuredText files
            return content
        
        else:
            # Return raw content for other file types
            return content

    def _build_page_url(self, file_path: str) -> str:
        """
        Builds the GitHub Pages URL for a file.
        
        Args:
            file_path: File path
            
        Returns:
            GitHub Pages URL
        """
        # Special handling for index.html
        if file_path.endswith("index.html"):
            dir_path = file_path[:-10]  # Remove "index.html"
            if not dir_path:
                return self.pages_base_url.rstrip("/")
            return urljoin(self.pages_base_url, dir_path)
        
        # For Markdown files, change extension to .html
        if file_path.endswith((".md", ".markdown")):
            file_path = file_path.rsplit(".", 1)[0] + ".html"
        
        return urljoin(self.pages_base_url, file_path)

    def _get_file_last_modified(self, file_info: GitHubPagesFileInfo) -> datetime | None:
        """
        Gets the last modification date of a file via GitHub API.
        
        Note: This makes an API call per file which could impact rate limits.
        Consider caching or batching for large repositories.
        
        Args:
            file_info: File information
            
        Returns:
            Last modification date or None
        """
        if not self.github_client:
            return None
        
        try:
            repo = self.github_client.get_repo(f"{self.repo_owner}/{self.repo_name}")
            
            # Get the commits that modified this file
            # Note: This is expensive for polling - consider optimizing for production
            # Extract original path from download_url for API call
            original_path = file_info.download_url.split(f"/{self.branch}/", 1)[1]
            commits = repo.get_commits(path=original_path, sha=self.branch)
            
            # Take the most recent commit
            if commits.totalCount > 0:
                latest_commit = commits[0]
                return latest_commit.commit.committer.date.replace(tzinfo=timezone.utc)
            
        except Exception as e:
            logger.debug(f"Couldn't get modification date for {file_info.path}: {e}")
        
        return None

    def _create_document(self, file_info: GitHubPagesFileInfo, content: str) -> Document:
        """
        Creates an Onyx document from a GitHub Pages file.
        
        Args:
            file_info: File information
            content: Text content of the file
            
        Returns:
            Onyx document
        """
        page_url = self._build_page_url(file_info.path)
        
        # Get last modification date
        last_modified = self._get_file_last_modified(file_info)
        
        # Create semantic title from path
        title = file_info.path.replace("/", " > ")
        if title.endswith(".html") or title.endswith(".htm"):
            title = title.rsplit(".", 1)[0]
        elif title.endswith((".md", ".markdown")):
            title = title.rsplit(".", 1)[0]
        
        return Document(
            id=page_url,
            sections=[TextSection(link=page_url, text=content)],
            source=DocumentSource.WEB,  # Use WEB source for web content
            semantic_identifier=title,
            doc_updated_at=last_modified,
            metadata={
                "repo_owner": self.repo_owner,
                "repo_name": self.repo_name,
                "branch": self.branch,
                "file_path": file_info.path,
                "file_sha": file_info.sha,
                "file_size": str(file_info.size),
                "pages_url": page_url,
                "source_type": "github_pages",
            }
        )

    def _load_documents(
        self, 
        start_time: datetime | None = None, 
        end_time: datetime | None = None
    ) -> GenerateDocumentsOutput:
        """
        Load documents from GitHub Pages.
        
        Args:
            start_time: Filter files modified after this date
            end_time: Filter files modified before this date
            
        Yields:
            Document batches
        """
        logger.info(f"Starting GitHub Pages indexing: {self.repo_owner}/{self.repo_name}:{self.branch}")
        
        # Get the file list
        files_info = self._get_repository_tree()
        
        if not files_info:
            logger.warning("No files found to index")
            return
        
        documents_batch = []
        processed_count = 0
        
        for file_info in files_info:
            try:
                # Download and process content
                content = self._download_file_content(file_info)
                
                if not content.strip():
                    logger.debug(f"Empty content for {file_info.path}, skipping")
                    continue
                
                # Create document
                document = self._create_document(file_info, content)
                
                # Filter by date if necessary
                if start_time and document.doc_updated_at and document.doc_updated_at < start_time:
                    continue
                if end_time and document.doc_updated_at and document.doc_updated_at > end_time:
                    continue
                
                documents_batch.append(document)
                processed_count += 1
                
                # Send batch if full
                if len(documents_batch) >= self.batch_size:
                    logger.info(f"Sending batch of {len(documents_batch)} documents")
                    yield documents_batch
                    documents_batch = []
                
            except Exception as e:
                logger.error(f"Error processing {file_info.path}: {e}")
                continue
        
        # Send final batch if not empty
        if documents_batch:
            logger.info(f"Sending final batch of {len(documents_batch)} documents")
            yield documents_batch
        
        logger.info(f"Indexing completed: {processed_count} documents processed")

    @override
    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load all documents from GitHub Pages"""
        yield from self._load_documents()

    @override
    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """
        Incremental polling based on modification dates.
        
        Args:
            start: Start timestamp
            end: End timestamp
            
        Yields:
            Documents modified in the period
        """
        start_time = datetime.fromtimestamp(start, tz=timezone.utc)
        end_time = datetime.fromtimestamp(end, tz=timezone.utc)
        
        logger.info(f"Polling GitHub Pages from {start_time} to {end_time}")
        
        yield from self._load_documents(start_time, end_time)

    def validate_connector_settings(self) -> None:
        """Validates connector configuration"""
        if not self.repo_owner or not self.repo_name:
            raise ConnectorValidationError(
                "Repository owner and name must be specified"
            )
        
        # Initialize client without token for public repositories if needed
        if not self.github_client:
            self.github_client = Github()
        
        try:
            # Check repository access
            repo = self.github_client.get_repo(f"{self.repo_owner}/{self.repo_name}")
            
            # Check branch existence
            try:
                repo.get_branch(self.branch)
            except Exception:
                raise ConnectorValidationError(
                    f"Branch '{self.branch}' not found in repository"
                )
            
            logger.info(f"Repository {self.repo_owner}/{self.repo_name} validated successfully")
            
        except Exception as e:
            if "Not Found" in str(e):
                raise ConnectorValidationError(
                    f"Repository {self.repo_owner}/{self.repo_name} not found or not accessible"
                )
            elif "rate limit" in str(e).lower():
                raise ConnectorValidationError(
                    "GitHub rate limit exceeded. Please provide an access token."
                )
            else:
                raise ConnectorValidationError(f"Repository validation failed: {e}")


if __name__ == "__main__":
    import os
    
    # Test connector
    connector = GitHubPagesConnector(
        repo_owner=os.environ["GITHUB_REPO_OWNER"],
        repo_name=os.environ["GITHUB_REPO_NAME"],
        branch=os.environ.get("GITHUB_BRANCH", "gh-pages"),
    )
    
    connector.load_credentials({
        "github_access_token": os.environ["GITHUB_ACCESS_TOKEN"]
    })
    
    # Test validation
    connector.validate_connector_settings()
    
    # Test loading
    document_batches = connector.load_from_state()
    for batch in document_batches:
        print(f"Batch of {len(batch)} documents:")
        for doc in batch[:2]:  # Show only first 2
            print(f"  - {doc.semantic_identifier} ({doc.id})")