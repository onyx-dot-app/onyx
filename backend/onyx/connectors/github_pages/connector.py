from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from io import StringIO
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from github import Github
from github import RateLimitExceededException
from github.GithubException import GithubException
from typing_extensions import override

from onyx.configs.app_configs import GITHUB_CONNECTOR_BASE_URL
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.github.rate_limit_utils import sleep_after_rate_limit_exception
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.connectors.web.connector import _get_datetime_from_last_modified_header
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.html_utils import parse_html_page_basic
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.utils.logger import setup_logger

logger = setup_logger()

_MAX_NUM_RATE_LIMIT_RETRIES = 5
ITEMS_PER_PAGE = 100

# Enhanced headers from web connector for better bot detection avoidance
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
        "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-CH-UA": '"Google Chrome";v="123", "Not:A-Brand";v="8"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"macOS"',
}


class GithubPagesCheckpoint(ConnectorCheckpoint):
    """Checkpoint for GitHub Pages connector"""

    repo_owner: str
    repo_name: str
    pages_processed: list[str] = []  # List of page URLs already processed
    current_sha: str | None = None  # Current commit SHA for change detection
    has_more: bool = True


class GithubPagesConnector(LoadConnector, CheckpointedConnector[GithubPagesCheckpoint]):
    """
    Connector for GitHub Pages sites that uses the GitHub API to discover
    and index all pages in a GitHub Pages repository.
    """

    def __init__(
        self,
        repo_owner: str,
        repo_name: str,
        include_readme: bool = True,
        **kwargs: Any,
    ) -> None:
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.include_readme = include_readme
        self.github_client: Github | None = None

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load GitHub credentials"""
        self.github_client = (
            Github(
                credentials["github_access_token"],
                base_url=GITHUB_CONNECTOR_BASE_URL,
                per_page=ITEMS_PER_PAGE,
            )
            if GITHUB_CONNECTOR_BASE_URL
            else Github(credentials["github_access_token"], per_page=ITEMS_PER_PAGE)
        )
        return None

    def _get_github_repo(self, attempt_num: int = 0) -> Any:
        """Get the GitHub repository with rate limiting"""
        if self.github_client is None:
            raise ConnectorMissingCredentialError("GitHub")

        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError("Too many rate limit retries")

        try:
            return self.github_client.get_repo(f"{self.repo_owner}/{self.repo_name}")
        except RateLimitExceededException:
            sleep_after_rate_limit_exception(self.github_client)
            return self._get_github_repo(attempt_num + 1)

    def _check_github_pages_enabled(self, repo: Any) -> str | None:
        """Check if GitHub Pages is enabled for the repository and return the base URL"""
        try:
            # Try to get pages information using the REST API approach
            # Note: get_pages() may not be available in all versions of PyGithub
            if hasattr(repo, "get_pages"):
                pages = repo.get_pages()
                if pages and hasattr(pages, "html_url") and pages.html_url:
                    return pages.html_url.rstrip("/")
        except GithubException as e:
            # Check if it's a 404 - means Pages is not enabled
            if e.status == 404:
                logger.info(f"GitHub Pages is not enabled for {repo.full_name}")
            else:
                logger.warning(
                    f"Could not access GitHub Pages for {repo.full_name}: {e}"
                )
        except Exception as e:
            logger.warning(
                f"Error checking GitHub Pages status for {repo.full_name}: {e}"
            )

        return None

    def _get_pages_urls(self, repo: Any, base_url: str) -> list[str]:
        """
        Discover all page URLs by examining the repository contents.
        This looks for HTML files, markdown files, and other web assets.
        """
        urls = []

        try:
            # Get the default branch contents
            contents = repo.get_contents("")

            # If there's a gh-pages branch, use that instead
            try:
                repo.get_branch("gh-pages")
                contents = repo.get_contents("", ref="gh-pages")
                logger.info(f"Using gh-pages branch for {repo.full_name}")
            except GithubException:
                # No gh-pages branch, use default branch
                pass

            urls.extend(self._process_contents(contents, base_url, repo))

        except GithubException as e:
            logger.error(f"Error getting repository contents: {e}")

        logger.info(f"Discovered {len(urls)} URLs from repository content")
        return urls

    def _process_contents(
        self, contents: Any, base_url: str, repo: Any, path_prefix: str = ""
    ) -> list[str]:
        """Recursively process repository contents to find web pages"""
        urls = []

        for content in contents:
            if content.type == "dir":
                # Recursively process subdirectories
                try:
                    subcontents = repo.get_contents(content.path)
                    sub_urls = self._process_contents(
                        subcontents, base_url, repo, content.path + "/"
                    )
                    urls.extend(sub_urls)
                except GithubException:
                    continue
            elif content.type == "file":
                # Check if this is a web page file
                logger.debug(f"Checking file: {content.name} (path: {content.path})")
                if self._is_web_page_file(content.name):
                    # Convert GitHub file path to web URL
                    web_path = self._convert_to_web_path(content.path)
                    if web_path:
                        full_url = urljoin(base_url + "/", web_path)
                        urls.append(full_url)
                        logger.debug(
                            f"Added page URL: {full_url} (from file: {content.path})"
                        )
                    else:
                        logger.debug(
                            f"Could not convert path to web URL: {content.path}"
                        )
                else:
                    logger.debug(f"Skipping non-web file: {content.name}")

        return urls

    def _get_source_files_from_repo(self, repo: Any) -> list[dict]:
        """
        Get source files directly from the GitHub repository that would be part of GitHub Pages.
        This works with private repos and doesn't require the site to be published.
        """
        files = []

        try:
            # First, try to find files in gh-pages branch if it exists
            branch_ref = None
            try:
                repo.get_branch("gh-pages")
                branch_ref = "gh-pages"
                logger.info(f"Using gh-pages branch for {repo.full_name}")
            except GithubException:
                # No gh-pages branch, check if Pages is configured for another branch
                try:
                    pages = repo.get_pages()
                    if hasattr(pages, "source") and hasattr(pages.source, "branch"):
                        branch_ref = pages.source.branch
                        logger.info(
                            f"Using Pages source branch '{branch_ref}' for {repo.full_name}"
                        )
                except Exception:
                    # Use default branch
                    branch_ref = repo.default_branch
                    logger.info(
                        f"Using default branch '{branch_ref}' for {repo.full_name}"
                    )

            # Get files from the determined branch
            if branch_ref:
                files.extend(self._get_files_from_branch(repo, branch_ref))

        except GithubException as e:
            logger.error(f"Error getting repository files: {e}")

        logger.info(f"Found {len(files)} potential GitHub Pages source files")
        return files

    def _get_files_from_branch(
        self, repo: Any, branch_ref: str, path: str = ""
    ) -> list[dict]:
        """Recursively get all web content files from a branch"""
        files = []

        try:
            contents = repo.get_contents(path, ref=branch_ref)

            for content in contents:
                if content.type == "dir":
                    # Skip certain directories
                    if content.name.startswith(".") or content.name in [
                        "node_modules",
                        "_site",
                        "vendor",
                    ]:
                        continue
                    # Recursively process subdirectories
                    try:
                        sub_files = self._get_files_from_branch(
                            repo, branch_ref, content.path
                        )
                        files.extend(sub_files)
                    except GithubException:
                        continue
                elif content.type == "file":
                    # Check if this is a web content file
                    if self._is_web_content_file(content.name):
                        files.append(
                            {
                                "path": content.path,
                                "name": content.name,
                                "sha": content.sha,
                                "size": content.size,
                                "content_obj": content,
                            }
                        )

        except GithubException as e:
            logger.error(f"Error getting files from path '{path}': {e}")

        return files

    def _is_web_content_file(self, filename: str) -> bool:
        """Check if a file contains web content that should be indexed"""
        filename_lower = filename.lower()

        # HTML files
        if filename_lower.endswith((".html", ".htm")):
            return True

        # Markdown files
        if filename_lower.endswith((".md", ".markdown")):
            return True

        # Text files that might contain content
        if filename_lower.endswith((".txt", ".rst")):
            return True

        # Jekyll/GitHub Pages specific files
        if filename_lower in ["_config.yml", "_config.yaml"]:
            return False  # Config files don't contain content to index

        return False

    def _create_document_from_github_file(
        self, repo: Any, file_info: dict, base_url: str
    ) -> Document | None:
        """Create a document from a GitHub file's content using existing file processing utilities"""
        try:
            content_obj = file_info["content_obj"]

            # Get the file content
            if content_obj.size > 1000000:  # Skip files larger than 1MB
                logger.warning(
                    f"Skipping large file {file_info['path']} ({content_obj.size} bytes)"
                )
                return None

            file_content = content_obj.decoded_content.decode("utf-8")

            # Process the content using existing Onyx file processing utilities
            try:
                file_io = StringIO(file_content)
                processed_text = extract_file_text(
                    file_io, file_info["name"], break_on_unprocessable=False
                )

                # If extract_file_text couldn't process it, try basic approaches
                if not processed_text.strip():
                    if file_info["name"].lower().endswith((".html", ".htm")):
                        # Use existing HTML processing
                        processed_text = parse_html_page_basic(file_content)
                    else:
                        # For other files, use content as-is (with basic cleanup)
                        processed_text = file_content

            except Exception as e:
                logger.warning(
                    f"File processing failed for {file_info['path']}: {e}, using raw content"
                )
                processed_text = file_content

            # Extract title using existing utilities or fallback methods
            title = self._extract_title_from_content(file_content, file_info["name"])

            if not processed_text.strip():
                logger.warning(f"No content found in {file_info['path']}")
                return None

            # Create the document URL (where it would be published)
            doc_url = self._convert_file_path_to_url(file_info["path"], base_url)

            return Document(
                id=f"github_pages_{repo.full_name}_{file_info['path']}",
                sections=[TextSection(text=processed_text, link=doc_url)],
                source=DocumentSource.GITHUB_PAGES,
                semantic_identifier=f"{repo.full_name}: {title}",
                doc_updated_at=datetime.now(
                    timezone.utc
                ),  # Could get from Git commit if needed
                metadata={
                    "repo_owner": self.repo_owner,
                    "repo_name": self.repo_name,
                    "file_path": file_info["path"],
                    "file_name": file_info["name"],
                    "sha": file_info["sha"],
                    "url": doc_url,
                    "title": title,
                    "content_length": str(len(processed_text)),
                    "repository_url": repo.html_url,
                },
            )

        except Exception as e:
            logger.error(f"Error processing file {file_info['path']}: {e}")
            return None

    def _extract_title_from_content(self, content: str, filename: str) -> str:
        """Extract title from file content using simple heuristics"""
        lines = content.split("\n")

        # For markdown files, check for YAML front matter title
        if filename.lower().endswith((".md", ".markdown")):
            if lines and lines[0].strip() == "---":
                for i, line in enumerate(lines[1:], 1):
                    if line.strip() == "---":
                        break
                    if line.strip().startswith("title:"):
                        title = line.split("title:", 1)[1].strip().strip("\"'")
                        if title:
                            return title

            # Check for first heading
            for line in lines:
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
                elif line.startswith("## "):
                    return line[3:].strip()

        # For HTML files, try to extract title
        elif filename.lower().endswith((".html", ".htm")):
            try:
                soup = BeautifulSoup(content, "html.parser")
                title_tag = soup.find("title")
                if title_tag and title_tag.text:
                    return title_tag.text.strip()
                # Try h1 tag as fallback
                h1_tag = soup.find("h1")
                if h1_tag and h1_tag.text:
                    return h1_tag.text.strip()
            except Exception:
                pass

        # Fallback to filename
        return filename

    def _convert_file_path_to_url(self, file_path: str, base_url: str) -> str:
        """Convert a repository file path to the corresponding GitHub Pages URL"""
        # Handle index files
        if file_path.lower() in ["index.html", "index.md", "readme.md"]:
            return base_url + "/"

        # Remove file extensions for certain files
        if file_path.lower().endswith(".md") or file_path.lower().endswith(".markdown"):
            # Markdown files are usually served without extension
            url_path = file_path.rsplit(".", 1)[0]
        elif file_path.lower().endswith(".html"):
            # HTML files might be served with or without extension
            url_path = file_path
        else:
            url_path = file_path

        return f"{base_url.rstrip('/')}/{url_path}"

    def _is_web_page_file(self, filename: str) -> bool:
        """Check if a file is likely to be a web page"""
        filename_lower = filename.lower()

        # HTML files
        if filename_lower.endswith((".html", ".htm")):
            return True

        # Markdown files that might be rendered as pages
        if filename_lower.endswith((".md", ".markdown")):
            # Include README files if configured
            if self.include_readme and filename_lower.startswith("readme"):
                return True
            # Include index markdown files
            if filename_lower.startswith("index"):
                return True
            # Include other markdown files (GitHub Pages often renders these)
            return True

        return False

    def _convert_to_web_path(self, file_path: str) -> str | None:
        """Convert a GitHub file path to a web URL path"""
        # Remove file extensions for certain files
        if file_path.lower().endswith(".md") or file_path.lower().endswith(".markdown"):
            # Markdown files are usually served without extension
            base_path = file_path.rsplit(".", 1)[0]
            if base_path.lower().endswith("readme"):
                # README.md becomes just the directory
                return base_path[:-6].rstrip("/") or "."
            elif base_path.lower().endswith("index"):
                # index.md becomes just the directory
                return base_path[:-5].rstrip("/") or "."
            else:
                return base_path
        elif file_path.lower().endswith((".html", ".htm")):
            # HTML files might be served with or without extension
            if file_path.lower().endswith("index.html"):
                # index.html becomes just the directory
                return file_path[:-10].rstrip("/") or "."
            else:
                return file_path

        return file_path

    def _fetch_page_content(self, url: str) -> Document | None:
        """Fetch and process a single page from the published GitHub Pages site"""
        try:
            # Use session-based approach for better connection handling
            session = requests.Session()
            session.headers.update(DEFAULT_HEADERS)

            response = session.get(url, timeout=30, allow_redirects=True)
            response.raise_for_status()

            # Parse HTML content
            soup = BeautifulSoup(response.content, "html.parser")
            parsed_html = web_html_cleanup(soup, mintlify_cleanup_enabled=True)

            if not parsed_html.cleaned_text.strip():
                logger.warning(f"No content found for {url}")
                return None

            # Create document
            title = parsed_html.title or f"Page from {self.repo_owner}/{self.repo_name}"

            # Get last modified time from response headers if available using web connector utility
            last_modified_str = response.headers.get("Last-Modified")
            doc_updated_at = (
                _get_datetime_from_last_modified_header(last_modified_str)
                if last_modified_str
                else datetime.now(timezone.utc)
            )

            return Document(
                id=url,
                sections=[TextSection(text=parsed_html.cleaned_text, link=url)],
                source=DocumentSource.GITHUB_PAGES,
                semantic_identifier=title,
                doc_updated_at=doc_updated_at,
                metadata={
                    "repo_owner": self.repo_owner,
                    "repo_name": self.repo_name,
                    "url": url,
                    "title": title,
                    "content_length": str(len(parsed_html.cleaned_text)),
                    "last_modified": last_modified_str or "",
                },
            )

        except requests.exceptions.HTTPError as e:
            # Handle HTTP errors
            status_code = e.response.status_code if e.response is not None else -1
            if status_code == 403:
                logger.warning(
                    f"Received 403 Forbidden for {url}, might be blocked by bot detection"
                )
            elif status_code == 404:
                logger.warning(f"Page not found: {url}")
            else:
                logger.error(f"HTTP error {status_code} for {url}: {e}")
            return None
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL error fetching {url}: {e}")
            return None
        except (requests.RequestException, ValueError) as e:
            logger.error(f"Network error fetching {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error processing {url}: {e}")
            return None

    @override
    def load_from_state(self) -> Generator[list[Document], None, None]:
        """Load all documents from the GitHub Pages site"""
        documents = list(self._fetch_from_github_pages())
        if documents:
            yield documents

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GithubPagesCheckpoint,
    ) -> CheckpointOutput[GithubPagesCheckpoint]:
        """Load documents from checkpoint - for GitHub Pages we just load all since pages don't change frequently"""
        return self._fetch_from_github_pages_with_checkpoint(checkpoint)

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> CheckpointOutput[GithubPagesCheckpoint]:
        """Poll for new documents - for GitHub Pages we just reload all"""
        checkpoint = GithubPagesCheckpoint(
            repo_owner=self.repo_owner,
            repo_name=self.repo_name,
            pages_processed=[],
            current_sha=None,
            has_more=True,
        )
        return self._fetch_from_github_pages_with_checkpoint(checkpoint)

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> GithubPagesCheckpoint:
        """Validate and parse checkpoint JSON"""
        return GithubPagesCheckpoint.model_validate_json(checkpoint_json)

    @override
    def build_dummy_checkpoint(self) -> GithubPagesCheckpoint:
        """Build a dummy checkpoint to start indexing"""
        return GithubPagesCheckpoint(
            repo_owner=self.repo_owner,
            repo_name=self.repo_name,
            pages_processed=[],
            current_sha=None,
            has_more=True,
        )

    def _check_connectivity(self, base_url: str) -> None:
        """Check connectivity to the GitHub Pages site"""
        try:
            session = requests.Session()
            session.headers.update(DEFAULT_HEADERS)

            response = session.get(base_url, timeout=10, allow_redirects=True)
            response.raise_for_status()
            logger.info(f"Successfully connected to GitHub Pages at {base_url}")
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else -1
            if status_code == 403:
                logger.warning(
                    f"Received 403 Forbidden for {base_url}, might be blocked by bot detection but will continue"
                )
                return  # Continue despite 403, as pages might still be accessible
            elif status_code == 404:
                raise ConnectorValidationError(
                    f"GitHub Pages site not found at {base_url}. Make sure GitHub Pages is enabled for this repository."
                )
            else:
                error_msg = f"HTTP error {status_code} connecting to {base_url}: {e}"
                raise ConnectorValidationError(error_msg)
        except requests.exceptions.SSLError as e:
            raise ConnectorValidationError(f"SSL error connecting to {base_url}: {e}")
        except (requests.RequestException, ValueError) as e:
            raise ConnectorValidationError(
                f"Unable to reach {base_url} - check your internet connection: {e}"
            )

    def _fetch_from_github_pages_with_checkpoint(
        self, checkpoint: GithubPagesCheckpoint
    ) -> Generator[Document, None, GithubPagesCheckpoint]:
        """Main method to fetch documents from GitHub Pages with checkpoint support"""
        if self.github_client is None:
            raise ConnectorMissingCredentialError("GitHub")

        try:
            # Get repository
            repo = self._get_github_repo()

            # Determine the GitHub Pages base URL (for metadata and URL generation)
            base_url = self._check_github_pages_enabled(repo)
            if not base_url:
                # Try common GitHub Pages URL patterns
                possible_urls = [
                    f"https://{self.repo_owner}.github.io/{self.repo_name}",
                    f"https://{self.repo_owner}.github.io/{self.repo_name.lower()}",
                    f"https://{self.repo_owner.lower()}.github.io/{self.repo_name}",
                    f"https://{self.repo_owner.lower()}.github.io/{self.repo_name.lower()}",
                ]
                base_url = possible_urls[0]  # Default fallback for metadata
                logger.info(f"Using default GitHub Pages URL for metadata: {base_url}")

            # Get source files directly from GitHub repository (not the published site)
            source_files = self._get_source_files_from_repo(repo)
            logger.info(
                f"Found {len(source_files)} source files in repository {repo.full_name}"
            )

            if not source_files:
                logger.warning(
                    f"No web content files found in repository {repo.full_name}."
                )
                checkpoint.has_more = False
                return checkpoint

            # Process each source file and create documents from GitHub content
            processed_files = []
            for i, file_info in enumerate(source_files):
                logger.info(
                    f"Processing file {i+1}/{len(source_files)}: {file_info['path']}"
                )
                doc = self._create_document_from_github_file(repo, file_info, base_url)
                if doc:
                    logger.info(
                        f"Successfully created document for {file_info['path']}"
                    )
                    yield doc
                    processed_files.append(file_info["path"])
                else:
                    logger.warning(f"Failed to create document for {file_info['path']}")

            # Mark as complete
            checkpoint.has_more = False
            checkpoint.pages_processed = processed_files
            return checkpoint

        except GithubException as e:
            if e.status == 401:
                error_msg = (
                    f"GitHub credential appears to be invalid or expired (HTTP 401) "
                    f"for {self.repo_owner}/{self.repo_name}"
                )
            elif e.status == 403:
                error_msg = f"Insufficient permissions to access repository {self.repo_owner}/{self.repo_name} (HTTP 403)"
            elif e.status == 404:
                error_msg = f"Repository {self.repo_owner}/{self.repo_name} not found (HTTP 404)"
            else:
                error_msg = f"GitHub API error ({e.status}): {e}"

            logger.error(error_msg)
            raise ConnectorValidationError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error processing GitHub Pages for {self.repo_owner}/{self.repo_name}: {e}"
            logger.error(error_msg)
            raise e

    def _fetch_from_github_pages(self) -> Generator[Document, None, None]:
        """Main method to fetch documents from GitHub Pages"""
        if self.github_client is None:
            raise ConnectorMissingCredentialError("GitHub")

        try:
            # Get repository
            repo = self._get_github_repo()

            # Determine the GitHub Pages base URL (for metadata and URL generation)
            base_url = self._check_github_pages_enabled(repo)
            if not base_url:
                # Try common GitHub Pages URL patterns
                possible_urls = [
                    f"https://{self.repo_owner}.github.io/{self.repo_name}",
                    f"https://{self.repo_owner}.github.io/{self.repo_name.lower()}",
                    f"https://{self.repo_owner.lower()}.github.io/{self.repo_name}",
                    f"https://{self.repo_owner.lower()}.github.io/{self.repo_name.lower()}",
                ]
                base_url = possible_urls[0]  # Default fallback for metadata
                logger.info(f"Using default GitHub Pages URL for metadata: {base_url}")

            # Get source files directly from GitHub repository (not the published site)
            source_files = self._get_source_files_from_repo(repo)
            logger.info(
                f"Found {len(source_files)} source files in repository {repo.full_name}"
            )

            if not source_files:
                logger.warning(
                    f"No web content files found in repository {repo.full_name}."
                )
                return

            # Process each source file and create documents from GitHub content
            for i, file_info in enumerate(source_files):
                logger.info(
                    f"Processing file {i+1}/{len(source_files)}: {file_info['path']}"
                )
                doc = self._create_document_from_github_file(repo, file_info, base_url)
                if doc:
                    logger.info(
                        f"Successfully created document for {file_info['path']}"
                    )
                    yield doc
                else:
                    logger.warning(f"Failed to create document for {file_info['path']}")

        except GithubException as e:
            if e.status == 401:
                error_msg = (
                    f"GitHub credential appears to be invalid or expired (HTTP 401) "
                    f"for {self.repo_owner}/{self.repo_name}"
                )
            elif e.status == 403:
                error_msg = f"Insufficient permissions to access repository {self.repo_owner}/{self.repo_name} (HTTP 403)"
            elif e.status == 404:
                error_msg = f"Repository {self.repo_owner}/{self.repo_name} not found (HTTP 404)"
            else:
                error_msg = f"GitHub API error (status={e.status}) for {self.repo_owner}/{self.repo_name}: {e.data}"

            logger.error(error_msg)
            raise ConnectorValidationError(error_msg)
        except Exception as e:
            error_msg = f"Unexpected error processing GitHub Pages for {self.repo_owner}/{self.repo_name}: {e}"
            logger.error(error_msg)
            raise e

    def validate_connector_settings(self) -> None:
        """Validate the connector configuration"""
        if self.github_client is None:
            raise ConnectorMissingCredentialError("GitHub credentials not loaded.")

        if not self.repo_owner:
            raise ConnectorValidationError("Repository owner must be provided.")

        if not self.repo_name:
            raise ConnectorValidationError("Repository name must be provided.")

        try:
            repo = self._get_github_repo()
            # Try to access the repository to validate credentials and permissions
            repo.get_commits().totalCount  # This will trigger an API call
            logger.info(
                f"Successfully validated access to repository: {self.repo_owner}/{self.repo_name}"
            )
        except GithubException as e:
            if e.status == 401:
                raise CredentialExpiredError(
                    "GitHub credential appears to be invalid or expired (HTTP 401)."
                )
            elif e.status == 403:
                raise InsufficientPermissionsError(
                    f"Your GitHub token does not have sufficient permissions for repository "
                    f"{self.repo_owner}/{self.repo_name} (HTTP 403)."
                )
            elif e.status == 404:
                raise ConnectorValidationError(
                    f"GitHub repository not found: {self.repo_owner}/{self.repo_name} (HTTP 404)"
                )
            else:
                raise ConnectorValidationError(
                    f"Unexpected GitHub error (status={e.status}): {e.data}"
                )
        except Exception as exc:
            raise ConnectorValidationError(
                f"Unexpected error during GitHub Pages settings validation: {exc}"
            )


if __name__ == "__main__":
    import os

    # Test the connector
    connector = GithubPagesConnector(
        repo_owner=os.environ.get("REPO_OWNER", "octocat"),
        repo_name=os.environ.get("REPO_NAME", "Hello-World"),
    )

    connector.load_credentials(
        {"github_access_token": os.environ["GITHUB_ACCESS_TOKEN"]}
    )

    # Test loading documents
    for doc_batch in connector.load_from_state():
        for doc in doc_batch:
            print(f"Document: {doc.semantic_identifier}")
            print(f"URL: {doc.metadata.get('url')}")
            print(f"Content length: {len(doc.sections[0].text or '')}")
            print("---")
