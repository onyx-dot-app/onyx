import os
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
from typing import Any, List, Optional
from requests.auth import HTTPBasicAuth
from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.constants import DocumentSource
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.utils.logger import setup_logger

logger = setup_logger()

_TIMEOUT = 60
_MAX_DEPTH = 5  

class GithubPagesConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        base_url: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.base_url = base_url
        self.batch_size = batch_size
        self.visited_urls = set()  
        self.auth: Optional[HTTPBasicAuth] = None

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        github_username = credentials.get("github_username")
        github_token = credentials.get("github_personal_access_token")
        if not github_username or not github_token:
            logger.warning("GitHub credentials are missing. Requests may fail for private pages.")
        self.auth = HTTPBasicAuth(github_username, github_token) if github_username and github_token else None

    def load_from_state(self, state: dict) -> None:
        """Restores the state of the connector from a given state dictionary."""
        self.visited_urls = set(state.get("visited_urls", []))

    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        return urlunparse(parsed._replace(fragment='', query=''))  

    def _fetch_with_retry(self, url: str, retries: int = 3, delay: int = 2) -> Optional[str]:
        for attempt in range(retries):
            try:
                response = requests.get(url, timeout=_TIMEOUT, auth=self.auth)
                response.raise_for_status()
                return response.text
            except requests.exceptions.RequestException as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                time.sleep(delay)
        logger.error(f"All attempts failed for {url}")
        return None

    def _crawl_github_pages(self, url: str, batch_size: int, depth: int = 0) -> List[str]:
        if depth > _MAX_DEPTH:
            return []

        to_visit = [url]
        crawled_urls = []

        while to_visit and len(crawled_urls) < batch_size:
            current_url = to_visit.pop()
            if current_url not in self.visited_urls:
                content = self._fetch_with_retry(current_url)
                if content:
                    soup = BeautifulSoup(content, 'html.parser')
                    self.visited_urls.add(current_url)
                    crawled_urls.append(current_url)

                    for link in soup.find_all('a'):
                        href = link.get('href')
                        if href:
                            full_url = self._normalize_url(urljoin(self.base_url, href))
                            if full_url.startswith(self.base_url) and full_url not in self.visited_urls:
                                to_visit.append(full_url)

        return crawled_urls

    def _index_pages(self, urls: List[str]) -> List[Document]:
        documents = []
        for url in urls:
            content = self._fetch_with_retry(url)
            if content:
                soup = BeautifulSoup(content, 'html.parser')
                text_content = soup.get_text()
                metadata = {
                    "url": url,
                    "crawl_time": time.time(),
                    "content_length": len(text_content),
                }

                documents.append(
                    Document(
                        id=url,
                        sections=[Section(link=url, text=text_content)],
                        source=DocumentSource.GITHUB_PAGES,
                        semantic_identifier=url,
                        metadata=metadata,
                    )
                )
        return documents

    def _get_all_crawled_urls(self) -> List[str]:
        all_crawled_urls = []
        while True:
            crawled_urls = self._crawl_github_pages(self.base_url, self.batch_size)
            if not crawled_urls:
                break
            all_crawled_urls.extend(crawled_urls)
        return all_crawled_urls

    def _pull_all_pages(self) -> GenerateDocumentsOutput:
        for crawled_urls in self._get_all_crawled_urls():
            yield self._index_pages(crawled_urls)

    def poll_source(self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch) -> GenerateDocumentsOutput:
        yield from self._pull_all_pages()


if __name__ == "__main__":
    connector = GithubPagesConnector(
        base_url=os.environ["GITHUB_PAGES_BASE_URL"]
    )

    credentials = {
        "github_username": os.getenv("GITHUB_USERNAME", ""),
        "github_personal_access_token": os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", ""),
    }

    connector.load_credentials(credentials)

    document_batches = connector.poll_source(0, 0)
    print(next(document_batches))
