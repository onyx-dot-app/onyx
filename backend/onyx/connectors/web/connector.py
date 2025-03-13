import io
import ipaddress
import socket
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
from onyx.configs.app_configs import WEB_CONNECTOR_VALIDATE_URLS
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import read_pdf_file
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.utils.logger import setup_logger
from onyx.utils.sitemap import list_pages_for_site
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

WEB_CONNECTOR_MAX_SCROLL_ATTEMPTS = 20
# Threshold for determining when to replace vs append iframe content
IFRAME_TEXT_LENGTH_THRESHOLD = 700
# Message indicating JavaScript is disabled, which often appears when scraping fails
JAVASCRIPT_DISABLED_MESSAGE = "You have JavaScript disabled in your browser"


class WEB_CONNECTOR_VALID_SETTINGS(str, Enum):
    # Given a base site, index everything under that path
    RECURSIVE = "recursive"
    # Given a URL, index only the given page
    SINGLE = "single"
    # Given a sitemap.xml URL, parse all the pages in it
    SITEMAP = "sitemap"
    # Given a file upload where every line is a URL, parse all the URLs provided
    UPLOAD = "upload"


def protected_url_check(url: str) -> None:
    """Couple considerations:
    - DNS mapping changes over time so we don't want to cache the results
    - Fetching this is assumed to be relatively fast compared to other bottlenecks like reading
      the page or embedding the contents
    - To be extra safe, all IPs associated with the URL must be global
    - This is to prevent misuse and not explicit attacks
    """
    if not WEB_CONNECTOR_VALIDATE_URLS:
        return

    parse = urlparse(url)
    if parse.scheme != "http" and parse.scheme != "https":
        raise ValueError("URL must be of scheme https?://")

    if not parse.hostname:
        raise ValueError("URL must include a hostname")

    try:
        # This may give a large list of IP addresses for domains with extensive DNS configurations
        # such as large distributed systems of CDNs
        info = socket.getaddrinfo(parse.hostname, None)
    except socket.gaierror as e:
        raise ConnectionError(f"DNS resolution failed for {parse.hostname}: {e}")

    for address in info:
        ip = address[4][0]
        if not ipaddress.ip_address(ip).is_global:
            raise ValueError(
                f"Non-global IP address detected: {ip}, skipping page {url}. "
                f"The Web Connector is not allowed to read loopback, link-local, or private ranges"
            )


def check_internet_connection(url: str) -> None:
    try:
        response = requests.get(url, timeout=3)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # Extract status code from the response, defaulting to -1 if response is None
        status_code = e.response.status_code if e.response is not None else -1
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

        # "#!" indicates the page is using a hashbang URL, which is a client-side routing technique
        if should_ignore_pound and "#" in href and "#!" not in href:
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
    try:
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
    except requests.RequestException as e:
        raise RuntimeError(f"Failed to fetch sitemap from {sitemap_url}: {e}")
    except ValueError as e:
        raise RuntimeError(f"Error processing sitemap {sitemap_url}: {e}")
    except Exception as e:
        raise RuntimeError(
            f"Unexpected error while processing sitemap {sitemap_url}: {e}"
        )


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


class WebConnector(LoadConnector):
    def __init__(
        self,
        base_url: str,  # Can't change this without disrupting existing users
        web_connector_type: str = WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value,
        mintlify_cleanup: bool = True,  # Mostly ok to apply to other websites as well
        batch_size: int = INDEX_BATCH_SIZE,
        scroll_before_scraping: bool = False,
        **kwargs: Any,
    ) -> None:
        self.mintlify_cleanup = mintlify_cleanup
        self.batch_size = batch_size
        self.recursive = False
        self.scroll_before_scraping = scroll_before_scraping
        self.web_connector_type = web_connector_type

        if web_connector_type == WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value:
            self.recursive = True
            self.to_visit_list = [_ensure_valid_url(base_url)]
            return

        elif web_connector_type == WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value:
            self.to_visit_list = [_ensure_valid_url(base_url)]

        elif web_connector_type == WEB_CONNECTOR_VALID_SETTINGS.SITEMAP:
            self.to_visit_list = extract_urls_from_sitemap(_ensure_valid_url(base_url))

        elif web_connector_type == WEB_CONNECTOR_VALID_SETTINGS.UPLOAD:
            # Explicitly check if running in multi-tenant mode to prevent potential security risks
            if MULTI_TENANT:
                raise ValueError(
                    "Upload input for web connector is not supported in cloud environments"
                )

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
        visited_links: set[str] = set()
        to_visit: list[str] = self.to_visit_list
        content_hashes = set()

        if not to_visit:
            raise ValueError("No URLs to visit")

        base_url = to_visit[0]  # For the recursive case
        doc_batch: list[Document] = []

        # Needed to report error
        at_least_one_doc = False
        last_error = None

        playwright, context = start_playwright()
        restart_playwright = False
        while to_visit:
            initial_url = to_visit.pop()
            if initial_url in visited_links:
                continue
            visited_links.add(initial_url)

            try:
                protected_url_check(initial_url)
            except Exception as e:
                last_error = f"Invalid URL {initial_url} due to {e}"
                logger.warning(last_error)
                continue

            index = len(visited_links)
            logger.info(f"{index}: Visiting {initial_url}")

            try:
                check_internet_connection(initial_url)
                if restart_playwright:
                    playwright, context = start_playwright()
                    restart_playwright = False

                if initial_url.split(".")[-1] == "pdf":
                    # PDF files are not checked for links
                    response = requests.get(initial_url)
                    page_text, metadata, images = read_pdf_file(
                        file=io.BytesIO(response.content)
                    )
                    last_modified = response.headers.get("Last-Modified")

                    doc_batch.append(
                        Document(
                            id=initial_url,
                            sections=[TextSection(link=initial_url, text=page_text)],
                            source=DocumentSource.WEB,
                            semantic_identifier=initial_url.split("/")[-1],
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

                # Can't use wait_until="networkidle" because it interferes with the scrolling behavior
                page_response = page.goto(
                    initial_url,
                    timeout=30000,  # 30 seconds
                )

                last_modified = (
                    page_response.header_value("Last-Modified")
                    if page_response
                    else None
                )
                final_url = page.url
                if final_url != initial_url:
                    protected_url_check(final_url)
                    initial_url = final_url
                    if initial_url in visited_links:
                        logger.info(
                            f"{index}: {initial_url} redirected to {final_url} - already indexed"
                        )
                        continue
                    logger.info(f"{index}: {initial_url} redirected to {final_url}")
                    visited_links.add(initial_url)

                if self.scroll_before_scraping:
                    scroll_attempts = 0
                    previous_height = page.evaluate("document.body.scrollHeight")
                    while scroll_attempts < WEB_CONNECTOR_MAX_SCROLL_ATTEMPTS:
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_load_state("networkidle", timeout=30000)
                        new_height = page.evaluate("document.body.scrollHeight")
                        if new_height == previous_height:
                            break  # Stop scrolling when no more content is loaded
                        previous_height = new_height
                        scroll_attempts += 1

                content = page.content()
                soup = BeautifulSoup(content, "html.parser")

                if self.recursive:
                    internal_links = get_internal_links(base_url, initial_url, soup)
                    for link in internal_links:
                        if link not in visited_links:
                            to_visit.append(link)

                if page_response and str(page_response.status)[0] in ("4", "5"):
                    last_error = f"Skipped indexing {initial_url} due to HTTP {page_response.status} response"
                    logger.info(last_error)
                    continue

                parsed_html = web_html_cleanup(soup, self.mintlify_cleanup)

                """For websites containing iframes that need to be scraped,
                the code below can extract text from within these iframes.
                """
                logger.debug(
                    f"{index}: Length of cleaned text {len(parsed_html.cleaned_text)}"
                )
                if JAVASCRIPT_DISABLED_MESSAGE in parsed_html.cleaned_text:
                    iframe_count = page.frame_locator("iframe").locator("html").count()
                    if iframe_count > 0:
                        iframe_texts = (
                            page.frame_locator("iframe")
                            .locator("html")
                            .all_inner_texts()
                        )
                        document_text = "\n".join(iframe_texts)
                        """ 700 is the threshold value for the length of the text extracted
                        from the iframe based on the issue faced """
                        if len(parsed_html.cleaned_text) < IFRAME_TEXT_LENGTH_THRESHOLD:
                            parsed_html.cleaned_text = document_text
                        else:
                            parsed_html.cleaned_text += "\n" + document_text

                # Sometimes pages with #! will serve duplicate content
                # There are also just other ways this can happen
                hashed_text = hash((parsed_html.title, parsed_html.cleaned_text))
                if hashed_text in content_hashes:
                    logger.info(
                        f"{index}: Skipping duplicate title + content for {initial_url}"
                    )
                    continue
                content_hashes.add(hashed_text)

                doc_batch.append(
                    Document(
                        id=initial_url,
                        sections=[
                            TextSection(link=initial_url, text=parsed_html.cleaned_text)
                        ],
                        source=DocumentSource.WEB,
                        semantic_identifier=parsed_html.title or initial_url,
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
                last_error = f"Failed to fetch '{initial_url}': {e}"
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

    def validate_connector_settings(self) -> None:
        # Make sure we have at least one valid URL to check
        if not self.to_visit_list:
            raise ConnectorValidationError(
                "No URL configured. Please provide at least one valid URL."
            )

        if (
            self.web_connector_type == WEB_CONNECTOR_VALID_SETTINGS.SITEMAP.value
            or self.web_connector_type == WEB_CONNECTOR_VALID_SETTINGS.RECURSIVE.value
        ):
            return None

        # We'll just test the first URL for connectivity and correctness
        test_url = self.to_visit_list[0]

        # Check that the URL is allowed and well-formed
        try:
            protected_url_check(test_url)
        except ValueError as e:
            raise ConnectorValidationError(
                f"Protected URL check failed for '{test_url}': {e}"
            )
        except ConnectionError as e:
            # Typically DNS or other network issues
            raise ConnectorValidationError(str(e))

        # Make a quick request to see if we get a valid response
        try:
            check_internet_connection(test_url)
        except Exception as e:
            err_str = str(e)
            if "401" in err_str:
                raise CredentialExpiredError(
                    f"Unauthorized access to '{test_url}': {e}"
                )
            elif "403" in err_str:
                raise InsufficientPermissionsError(
                    f"Forbidden access to '{test_url}': {e}"
                )
            elif "404" in err_str:
                raise ConnectorValidationError(f"Page not found for '{test_url}': {e}")
            elif "Max retries exceeded" in err_str and "NameResolutionError" in err_str:
                raise ConnectorValidationError(
                    f"Unable to resolve hostname for '{test_url}'. Please check the URL and your internet connection."
                )
            else:
                # Could be a 5xx or another error, treat as unexpected
                raise UnexpectedValidationError(
                    f"Unexpected error validating '{test_url}': {e}"
                )


if __name__ == "__main__":
    connector = WebConnector("https://docs.onyx.app/")
    document_batches = connector.load_from_state()
    print(next(document_batches))
