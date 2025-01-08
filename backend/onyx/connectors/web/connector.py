import io
from datetime import datetime
from datetime import timezone
from enum import Enum
from typing import Any
from typing import cast
from typing import Tuple
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from oauthlib.oauth2 import BackendApplicationClient
from playwright.sync_api import BrowserContext
from playwright.sync_api import Playwright
from playwright.sync_api import sync_playwright
from requests_oauthlib import OAuth2Session  # type:ignore
from urllib3.exceptions import MaxRetryError

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import WEB_CONNECTOR_OAUTH_CLIENT_ID
from onyx.configs.app_configs import WEB_CONNECTOR_OAUTH_CLIENT_SECRET
from onyx.configs.app_configs import WEB_CONNECTOR_OAUTH_TOKEN_URL
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnector
from onyx.connectors.models import Document
from onyx.connectors.models import Section
from onyx.connectors.models import SlimDocument
from onyx.db.document import get_document_ids_for_connector_credential_pair
from onyx.db.engine import get_session_with_tenant
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.utils.logger import setup_logger
from onyx.utils.sitemap import list_pages_for_site
from onyx.utils.url_frontier import URLFrontier
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

logger = setup_logger()

_SLIM_BATCH_SIZE = 1000


class WEB_CONNECTOR_VALID_SETTINGS(str, Enum):
    # Given a base site, index everything under that path
    RECURSIVE = "recursive"
    # Given a URL, index only the given page
    SINGLE = "single"
    # Given a sitemap.xml URL, parse all the pages in it
    SITEMAP = "sitemap"
    # Given a file upload where every line is a URL, parse all the URLs provided
    UPLOAD = "upload"


def check_internet_connection(url: str, frontier: URLFrontier) -> None:
    try:
        response = requests.get(url, timeout=3)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # Extract status code from the response, defaulting to -1 if response is None
        status_code = e.response.status_code if e.response is not None else -1
        if status_code == 429:
            retry_after = e.response.headers.get("Retry-After", 5)
            frontier.handle_ratelimit(url, retry_after)
            raise Exception(
                f"Rate limited for {url}. Retry after {retry_after} seconds"
            )
        error_msg = {
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            500: "Internal Server Error",
            502: "Bad Gateway",
            503: "Service Unavailable",
            504: "Gateway Timeout",
        }.get(status_code, "HTTP Error")
        raise Exception(f"{error_msg} ({status_code}) for {url} - {e}")
    except requests.exceptions.SSLError as e:
        cause = (
            e.args[0].reason
            if isinstance(e.args, tuple) and isinstance(e.args[0], MaxRetryError)
            else e.args
        )
        raise Exception(f"SSL error {str(cause)}")
    except (requests.RequestException, ValueError) as e:
        raise Exception(f"Unable to reach {url} - check your internet connection: {e}")


def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


def get_internal_links(
    base_url: str, url: str, soup: BeautifulSoup, should_ignore_pound: bool = True
) -> set[str]:
    internal_links = set()
    for link in cast(list[dict[str, Any]], soup.find_all("a")):
        href = cast(str | None, link.get("href"))
        if not href:
            continue

        # Account for malformed backslashes in URLs
        href = href.replace("\\", "/")

        if should_ignore_pound and "#" in href:
            href = href.split("#")[0]

        if not is_valid_url(href):
            # Relative path handling
            href = urljoin(url, href)

        if urlparse(href).netloc == urlparse(url).netloc and base_url in href:
            internal_links.add(href)
    return internal_links


def start_playwright() -> Tuple[Playwright, BrowserContext]:
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=True)

    context = browser.new_context()

    if (
        WEB_CONNECTOR_OAUTH_CLIENT_ID
        and WEB_CONNECTOR_OAUTH_CLIENT_SECRET
        and WEB_CONNECTOR_OAUTH_TOKEN_URL
    ):
        client = BackendApplicationClient(client_id=WEB_CONNECTOR_OAUTH_CLIENT_ID)
        oauth = OAuth2Session(client=client)
        token = oauth.fetch_token(
            token_url=WEB_CONNECTOR_OAUTH_TOKEN_URL,
            client_id=WEB_CONNECTOR_OAUTH_CLIENT_ID,
            client_secret=WEB_CONNECTOR_OAUTH_CLIENT_SECRET,
        )
        context.set_extra_http_headers(
            {"Authorization": "Bearer {}".format(token["access_token"])}
        )

    return playwright, context


def extract_urls_from_sitemap(sitemap_url: str) -> list[str]:
    response = requests.get(sitemap_url)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, "html.parser")
    urls = [
        _ensure_absolute_url(sitemap_url, loc_tag.text)
        for loc_tag in soup.find_all("loc")
    ]

    if len(urls) == 0 and len(soup.find_all("urlset")) == 0:
        # the given url doesn't look like a sitemap, let's try to find one
        urls = list_pages_for_site(sitemap_url)

    if len(urls) == 0:
        raise ValueError(
            f"No URLs found in sitemap {sitemap_url}. Try using the 'single' or 'recursive' scraping options instead."
        )

    return urls


def _ensure_absolute_url(source_url: str, maybe_relative_url: str) -> str:
    if not urlparse(maybe_relative_url).netloc:
        return urljoin(source_url, maybe_relative_url)
    return maybe_relative_url


def _ensure_valid_url(url: str) -> str:
    if "://" not in url:
        return "https://" + url
    return url


def _read_urls_file(location: str) -> list[str]:
    with open(location, "r") as f:
        urls = [_ensure_valid_url(line.strip()) for line in f if line.strip()]
    return urls


def _get_datetime_from_last_modified_header(last_modified: str) -> datetime | None:
    try:
        return datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        return None


class WebConnector(LoadConnector, SlimConnector):
    def __init__(
        self,
        base_url: str,  # Can't change this without disrupting existing users
        web_connector_type: str = WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value,
        mintlify_cleanup: bool = True,  # Mostly ok to apply to other websites as well
        batch_size: int = INDEX_BATCH_SIZE,
        tenant_id: str = POSTGRES_DEFAULT_SCHEMA,
        connector_id: int | None = None,
        credential_id: int | None = None,
    ) -> None:
        self.mintlify_cleanup = mintlify_cleanup
        self.batch_size = batch_size
        self.recursive = False
        self.tenant_id = tenant_id
        self.connector_id = connector_id
        self.credential_id = credential_id

        if web_connector_type == WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value:
            self.recursive = True
            self.to_visit_list = [_ensure_valid_url(base_url)]
            return

        elif web_connector_type == WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value:
            self.to_visit_list = [_ensure_valid_url(base_url)]

        elif web_connector_type == WEB_CONNECTOR_VALID_SETTINGS.SITEMAP:
            self.to_visit_list = extract_urls_from_sitemap(_ensure_valid_url(base_url))

        elif web_connector_type == WEB_CONNECTOR_VALID_SETTINGS.UPLOAD:
            logger.warning(
                "This is not a UI supported Web Connector flow, "
                "are you sure you want to do this?"
            )
            self.to_visit_list = _read_urls_file(base_url)

        else:
            raise ValueError(
                "Invalid Web Connector Config, must choose a valid type between: " ""
            )

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        if credentials:
            logger.warning("Unexpected credentials provided for Web Connector")
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Traverses through all pages found on the website
        and converts them into documents"""
        if not self.to_visit_list:
            raise ValueError("No URLs to visit")

        frontier = URLFrontier()
        for url in self.to_visit_list:
            frontier.add_url(url)

        base_url = self.to_visit_list[0]  # For the recursive case
        doc_batch: list[Document] = []

        # Needed to report error
        at_least_one_doc = False
        last_error = None

        playwright, context = start_playwright()
        restart_playwright = False
        while frontier.has_next_url():
            current_url = frontier.get_next_url()

            if not current_url:
                continue

            logger.info(f"Visiting {current_url}")

            try:
                check_internet_connection(current_url, frontier)
                if restart_playwright:
                    playwright, context = start_playwright()
                    restart_playwright = False

                if current_url.split(".")[-1] == "pdf":
                    # PDF files are not checked for links
                    response = requests.get(current_url)
                    if response.status_code == 429:
                        frontier.handle_ratelimit(
                            current_url, int(response.headers.get("Retry-After", 5))
                        )
                        continue
                    if response.status_code != 200:
                        last_error = (
                            f"Failed to fetch '{current_url}': {response.status_code}"
                        )
                        logger.error(last_error)
                        continue

                    page_text, metadata = read_pdf_file(
                        file=io.BytesIO(response.content)
                    )
                    last_modified = response.headers.get("Last-Modified")

                    doc_batch.append(
                        Document(
                            id=current_url,
                            sections=[Section(link=current_url, text=page_text)],
                            source=DocumentSource.WEB,
                            semantic_identifier=current_url.split("/")[-1],
                            metadata=metadata,
                            doc_updated_at=_get_datetime_from_last_modified_header(
                                last_modified
                            )
                            if last_modified
                            else None,
                        )
                    )
                    continue

                page = context.new_page()
                page_response = page.goto(current_url)
                if not page_response:
                    last_error = f"Failed to fetch '{current_url}'"
                    logger.error(last_error)
                    continue

                retry_after = page_response.header_value("Retry-After")
                last_modified = (
                    page_response.header_value("Last-Modified")
                    if page_response
                    else None
                )
                final_page = page.url
                if final_page != current_url:
                    logger.info(f"Redirected to {final_page}")
                    frontier.add_url(final_page)
                    continue

                content = page.content()
                soup = BeautifulSoup(content, "html.parser")

                if self.recursive:
                    internal_links = get_internal_links(base_url, current_url, soup)
                    for link in internal_links:
                        frontier.add_url(link)

                if page_response and str(page_response.status)[0] in ("4", "5"):
                    last_error = f"Skipped indexing {current_url} due to HTTP {page_response.status} response"
                    logger.info(last_error)
                    if page_response.status == 429:
                        frontier.handle_ratelimit(
                            current_url, int(retry_after) if retry_after else 5
                        )
                    continue

                parsed_html = web_html_cleanup(soup, self.mintlify_cleanup)

                doc_batch.append(
                    Document(
                        id=current_url,
                        sections=[
                            Section(link=current_url, text=parsed_html.cleaned_text)
                        ],
                        source=DocumentSource.WEB,
                        semantic_identifier=parsed_html.title or current_url,
                        metadata={},
                        doc_updated_at=_get_datetime_from_last_modified_header(
                            last_modified
                        )
                        if last_modified
                        else None,
                    )
                )

                page.close()
            except Exception as e:
                last_error = f"Failed to fetch '{current_url}': {e}"
                logger.exception(last_error)
                playwright.stop()
                restart_playwright = True
                continue

            if len(doc_batch) >= self.batch_size:
                playwright.stop()
                restart_playwright = True
                at_least_one_doc = True
                yield doc_batch
                doc_batch = []

        if doc_batch:
            playwright.stop()
            at_least_one_doc = True
            yield doc_batch

        if not at_least_one_doc:
            if last_error:
                raise RuntimeError(last_error)
            raise RuntimeError("No valid pages found.")

    def retrieve_all_slim_documents(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> GenerateSlimDocumentOutput:
        frontier = URLFrontier()
        slim_doc_batch: list[SlimDocument] = []

        if self.connector_id is None or self.credential_id is None:
            raise ValueError(
                "Connector and Credential IDs are required for slim documents"
            )

        with get_session_with_tenant(self.tenant_id) as db_session:
            for doc_id in get_document_ids_for_connector_credential_pair(
                db_session, self.connector_id, self.credential_id
            ):
                frontier.add_url(doc_id)

        while frontier.has_next_url():
            current_url = frontier.get_next_url()
            if current_url is None:
                continue
            try:
                check_internet_connection(current_url, frontier=frontier)
            except Exception as e:
                logger.exception(f"Failed to fetch '{current_url}': {e}")
                continue
            slim_doc_batch.append(SlimDocument(id=current_url))
            if len(slim_doc_batch) >= _SLIM_BATCH_SIZE:
                yield slim_doc_batch
                slim_doc_batch = []

        if slim_doc_batch:
            yield slim_doc_batch


if __name__ == "__main__":
    connector = WebConnector("https://docs.onyx.app/")
    document_batches = connector.load_from_state()
    cnt = 0
    for batch in document_batches:
        for doc in batch:
            cnt += 1
            print(doc.id)
    print(f"Total documents: {cnt}")
