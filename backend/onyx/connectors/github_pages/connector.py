import os
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import List
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from github import Github
from github import RateLimitExceededException
from github.GithubException import GithubException
from markdown import markdown  # type: ignore
from pydantic import BaseModel

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
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_BRANCH = "gh-pages"
MAX_FILES_PER_SCAN = 1000
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_TIMEOUT = 30

SUPPORTED_EXTENSIONS = {
    ".html",
    ".htm",
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".asciidoc",
    ".adoc",
}
SKIP_EXTENSIONS = {
    ".css",
    ".js",
    ".json",
    ".xml",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
}


class GitHubPagesFileInfo(BaseModel):
    path: str
    original_path: str
    sha: str
    size: int
    url: str
    download_url: str
    last_modified: Optional[datetime] = None


class GitHubPagesConnector(LoadConnector, PollConnector):
    """
    Connector for indexing GitHub Pages sites via the GitHub API.

    Features:
    - Indexes HTML, Markdown, and text files from GitHub Pages repositories
    - Supports filtering by directory depth and file types
    - Handles rate limiting and authentication
    - Provides incremental polling based on file modification dates
    """

    def __init__(
        self,
        repo_owner: str,
        repo_name: str,
        branch: str = DEFAULT_BRANCH,
        root_directory: str = "",
        max_files: int = MAX_FILES_PER_SCAN,
        max_depth: Optional[int] = None,
        batch_size: int = INDEX_BATCH_SIZE,
        github_token: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """
        Initialize the GitHub Pages connector.

        Args:
            repo_owner: GitHub repository owner (username or organization)
            repo_name: GitHub repository name
            branch: Branch to scan (default: gh-pages)
            root_directory: Root directory to scan (default: entire repository)
            max_files: Maximum number of files to index
            max_depth: Maximum scan depth (None = unlimited)
            batch_size: Size of document batches
            github_token: GitHub access token for authentication
            timeout: Request timeout in seconds
        """
        self.repo_owner = repo_owner.strip()
        self.repo_name = repo_name.strip()
        self.branch = branch.strip()
        self.root_directory = root_directory.strip("/")
        self.max_files = max_files
        self.max_depth = max_depth
        self.batch_size = batch_size
        self.timeout = timeout

        # Initialize GitHub client
        self.github_client = Github(github_token) if github_token else Github()

        # Initialize HTTP session for better performance
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Onyx-GitHubPages-Connector/1.0"})

        # Build GitHub Pages base URL
        self.pages_base_url = f"https://{self.repo_owner}.github.io/{self.repo_name}/"

        logger.info(
            f"Initialized GitHub Pages connector for {self.repo_owner}/{self.repo_name}"
        )

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        """Load GitHub credentials from the provided dictionary."""
        github_token = credentials.get("github_access_token")
        if github_token:
            self.github_client = Github(github_token)
            logger.info("GitHub credentials loaded successfully")
        else:
            self.github_client = Github()
            logger.info("Using public GitHub access (no token provided)")

    def _should_process_file(self, file_path: str) -> bool:
        """Determine if a file should be processed based on its extension."""
        _, ext = os.path.splitext(file_path.lower())

        # Check if extension is supported
        if ext in SUPPORTED_EXTENSIONS:
            return True

        # Skip unwanted extensions
        if ext in SKIP_EXTENSIONS:
            return False

        # For files without extension, check if they might contain text
        return ext == ""

    def _respect_depth_limit(self, file_path: str) -> bool:
        """Check if a file respects the depth limit."""
        if self.max_depth is None:
            return True

        # Count directory levels (excluding the file itself)
        path_parts = file_path.strip("/").split("/")
        depth = len(path_parts) - 1

        return depth <= self.max_depth

    def _get_repository_tree(self) -> List[GitHubPagesFileInfo]:
        """Retrieve the repository file tree recursively."""
        try:
            logger.info(
                f"Fetching repository tree for {self.repo_owner}/{self.repo_name}:{self.branch}"
            )

            repo = self.github_client.get_repo(f"{self.repo_owner}/{self.repo_name}")
            tree = repo.get_git_tree(self.branch, recursive=True)

            files_info = []
            processed_count = 0
            skipped_count = 0

            for item in tree.tree:
                # Skip directories
                if item.type != "blob":
                    continue

                file_path = item.path

                # Filter by root directory if specified
                if self.root_directory:
                    if not file_path.startswith(self.root_directory + "/"):
                        continue
                    # Adjust relative path for processing
                    file_path = file_path[len(self.root_directory) + 1 :]

                # Check depth limits
                if not self._respect_depth_limit(file_path):
                    skipped_count += 1
                    continue

                # Check if file should be processed
                if not self._should_process_file(file_path):
                    skipped_count += 1
                    continue

                # Check file size
                if item.size and item.size > MAX_FILE_SIZE_BYTES:
                    logger.warning(
                        f"File too large, skipping: {file_path} ({item.size} bytes)"
                    )
                    skipped_count += 1
                    continue

                # Build download URL
                download_url = f"https://raw.githubusercontent.com/{self.repo_owner}/{self.repo_name}/{self.branch}/{item.path}"

                files_info.append(
                    GitHubPagesFileInfo(
                        path=file_path,
                        original_path=item.path,
                        sha=item.sha,
                        size=item.size or 0,
                        url=item.url,
                        download_url=download_url,
                    )
                )

                processed_count += 1
                if processed_count >= self.max_files:
                    logger.info(f"File limit reached: {self.max_files}")
                    break

            logger.info(
                f"Found {len(files_info)} files to process (skipped {skipped_count} files)"
            )
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
        """Download and decode file content."""
        try:
            response = self._session.get(file_info.download_url, timeout=self.timeout)
            response.raise_for_status()

            content = response.content

            # Try different encodings
            for encoding in ["utf-8", "latin-1", "cp1252"]:
                try:
                    text_content = content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                logger.warning(f"Unable to decode file: {file_info.path}")
                return ""

            return self._process_file_content(text_content, file_info.path)

        except requests.RequestException as e:
            logger.warning(f"Error downloading {file_info.path}: {e}")
            return ""

    def _process_file_content(self, content: str, file_path: str) -> str:
        """Process file content according to its type."""
        _, ext = os.path.splitext(file_path.lower())

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
        """Build the GitHub Pages URL for a file."""
        # Special handling for index.html
        if file_path.endswith("index.html"):
            dir_path = file_path[:-10]  # Remove "index.html"
            if not dir_path:
                return self.pages_base_url.rstrip("/")
            return urljoin(self.pages_base_url, dir_path)

        # For Markdown files, change extension to .html
        if file_path.endswith((".md", ".markdown")):
            file_path = os.path.splitext(file_path)[0] + ".html"

        return urljoin(self.pages_base_url, file_path)

    def _get_file_last_modified(
        self, file_info: GitHubPagesFileInfo
    ) -> Optional[datetime]:
        """Get the last modification date of a file via GitHub API."""
        try:
            repo = self.github_client.get_repo(f"{self.repo_owner}/{self.repo_name}")

            # Get the commits that modified this file
            commits = repo.get_commits(path=file_info.original_path, sha=self.branch)

            # Take the most recent commit
            if commits.totalCount > 0:
                latest_commit = commits[0]
                return latest_commit.commit.committer.date.replace(tzinfo=timezone.utc)

        except Exception as e:
            logger.debug(f"Couldn't get modification date for {file_info.path}: {e}")

        return None

    def _create_document(
        self, file_info: GitHubPagesFileInfo, content: str
    ) -> Document:
        """Create an Onyx document from a GitHub Pages file."""
        page_url = self._build_page_url(file_info.path)
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
            source=DocumentSource.WEB,
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
                "connector_version": "2.0",
            },
        )

    def _load_documents(
        self, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None
    ) -> GenerateDocumentsOutput:
        """Load documents from GitHub Pages with optional time filtering."""
        logger.info(
            f"Starting GitHub Pages indexing: {self.repo_owner}/{self.repo_name}:{self.branch}"
        )

        # Get the file list
        files_info = self._get_repository_tree()

        if not files_info:
            logger.warning("No files found to index")
            return

        documents_batch = []
        processed_count = 0
        skipped_count = 0

        for file_info in files_info:
            try:
                # Download and process content
                content = self._download_file_content(file_info)

                if not content.strip():
                    logger.debug(f"Empty content for {file_info.path}, skipping")
                    skipped_count += 1
                    continue

                # Create document
                document = self._create_document(file_info, content)

                # Filter by date if necessary
                if (
                    start_time
                    and document.doc_updated_at
                    and document.doc_updated_at < start_time
                ):
                    continue
                if (
                    end_time
                    and document.doc_updated_at
                    and document.doc_updated_at > end_time
                ):
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
                skipped_count += 1
                continue

        # Send final batch if not empty
        if documents_batch:
            logger.info(f"Sending final batch of {len(documents_batch)} documents")
            yield documents_batch

        logger.info(
            f"Indexing completed: {processed_count} documents processed, {skipped_count} skipped"
        )

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Load all documents from GitHub Pages."""
        yield from self._load_documents()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Incremental polling based on modification dates."""
        start_time = datetime.fromtimestamp(start, tz=timezone.utc)
        end_time = datetime.fromtimestamp(end, tz=timezone.utc)

        logger.info(f"Polling GitHub Pages from {start_time} to {end_time}")

        yield from self._load_documents(start_time, end_time)

    def validate_connector_settings(self) -> None:
        """Validate connector configuration."""
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
            except GithubException:
                raise ConnectorValidationError(
                    f"Branch '{self.branch}' not found in repository"
                )

            logger.info(
                f"Repository {self.repo_owner}/{self.repo_name} validated successfully"
            )

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

    def __del__(self) -> None:
        """Clean up session resources."""
        if hasattr(self, "_session"):
            self._session.close()


if __name__ == "__main__":
    # Minimal working example
    import os

    # Test connector
    connector = GitHubPagesConnector(
        repo_owner=os.environ.get("GITHUB_REPO_OWNER", "onyx-ai"),
        repo_name=os.environ.get("GITHUB_REPO_NAME", "onyx"),
        branch=os.environ.get("GITHUB_BRANCH", "gh-pages"),
        github_token=os.environ.get("GITHUB_ACCESS_TOKEN"),
        max_files=10,
    )

    # Test validation
    connector.validate_connector_settings()

    # Test loading
    document_batches = connector.load_from_state()
    for batch in document_batches:
        print(f"Batch of {len(batch)} documents:")
        for doc in batch[:2]:  # Show only first 2
            print(f"  - {doc.semantic_identifier} ({doc.id})")
