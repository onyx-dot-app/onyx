import re
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _ensure_valid_url(url: str) -> str:
    """Ensure URL is valid and has a scheme."""
    if not urlparse(url).scheme:
        url = "https://" + url
    return url


def _get_datetime_from_last_modified_header(last_modified: str | None) -> datetime | None:
    """Convert Last-Modified header to datetime."""
    if not last_modified:
        return None
    try:
        return datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def get_internal_links(base_url: str, current_url: str, soup: BeautifulSoup) -> list[str]:
    """Extract internal links from the page that match the base URL pattern."""
    internal_links = []
    base_url_parsed = urlparse(base_url)
    base_url_pattern = re.compile(base_url)

    for link in soup.find_all("a", href=True):
        href = link["href"]
        # Handle both absolute and relative paths starting with '/'
        absolute_url = urljoin(current_url, href)
        
        # Only include links that match the base URL pattern
        if base_url_pattern.match(absolute_url):
            internal_links.append(absolute_url)

    return internal_links


class RegulationConnector(LoadConnector):
    def __init__(
        self,
        base_url: str,
        batch_size: int = 100,
        **kwargs: Any,
    ) -> None:
        self.base_url = _ensure_valid_url(base_url)
        self.batch_size = batch_size
        self.to_visit_list = [self.base_url]

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        if credentials:
            logger.warning("Unexpected credentials provided for Regulation Connector")
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Traverses through all pages found on the e-regulation website
        and converts them into documents"""
        visited_links: set[str] = set()
        to_visit: list[str] = self.to_visit_list
        content_hashes = set()

        if not to_visit:
            raise ValueError("No URLs to visit")

        doc_batch: list[Document] = []

        # Needed to report error
        at_least_one_doc = False
        last_error = None

        while to_visit:
            current_url = to_visit.pop()
            current_url_no_fragment = current_url.split('#')[0]
            if current_url_no_fragment in visited_links:
                continue
            visited_links.add(current_url)

            try:
                index = len(visited_links)
                logger.info(f"{index}: Visiting {current_url}")

                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml"
                }
            
                response = requests.get(current_url, timeout=5, headers=headers)
                response.raise_for_status()

                last_modified = response.headers.get("Last-Modified")
                content = response.text
                soup = BeautifulSoup(content, "html.parser")

                # Extract internal links for recursive crawling
                internal_links = get_internal_links(self.base_url, current_url, soup)
                for link in internal_links:
                    if link not in visited_links:
                        to_visit.append(link)

                # Parse and clean the HTML content
                parsed_html = web_html_cleanup(content)

                # Create document from the cleaned content
                doc_batch.append(
                    Document(
                        id=current_url,
                        sections=[TextSection(link=current_url, text=parsed_html.cleaned_text)],
                        source=DocumentSource.REGULATION,
                        semantic_identifier=parsed_html.title or current_url,
                        metadata={
                            "base_regulation_url": self.base_url
                        },
                        doc_updated_at=_get_datetime_from_last_modified_header(last_modified)
                        if last_modified
                        else None,
                    )
                )

            except Exception as e:
                last_error = f"Failed to fetch '{current_url}': {e}"
                logger.exception(last_error)
                continue

            if len(doc_batch) >= self.batch_size:
                at_least_one_doc = True
                yield doc_batch
                doc_batch = []

        if doc_batch:
            at_least_one_doc = True
            yield doc_batch

        if not at_least_one_doc:
            if last_error:
                raise RuntimeError(last_error)
            raise RuntimeError("No valid pages found.")

    def validate_connector_settings(self) -> None:
        # Make sure we have at least one valid URL to check
        if not self.to_visit_list:
            raise ConnectorValidationError(
                "No URL configured. Please provide at least one valid URL."
            )

        # Test the base URL for connectivity and correctness
        test_url = self.to_visit_list[0]

        # Make a quick request to see if we get a valid response
        try:
            response = requests.get(test_url, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            err_str = str(e)
            if "401" in err_str:
                raise ConnectorValidationError(f"Unauthorized access to '{test_url}': {e}")
            elif "403" in err_str:
                raise ConnectorValidationError(f"Forbidden access to '{test_url}': {e}")
            elif "404" in err_str:
                raise ConnectorValidationError(f"Page not found for '{test_url}': {e}")
            else:
                raise ConnectorValidationError(f"Unexpected error validating '{test_url}': {e}") 