import io
import ipaddress
import random
import socket
import time
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


class ScrapeSessionContext:
    """Session level context for scraping"""

    def __init__(self, base_url: str, to_visit: list[str]):
        self.base_url = base_url
        self.to_visit = to_visit
        self.visited_links: set[str] = set()
        self.content_hashes: set[int] = set()

        self.doc_batch: list[Document] = []

        self.at_least_one_doc: bool = False
        self.last_error: str | None = None
        self.needs_retry: bool = False

        self.playwright: Playwright | None = None
        self.playwright_context: BrowserContext | None = None

    def initialize(self) -> None:
        self.stop()
        self.playwright, self.playwright_context = start_playwright()

    def stop(self) -> None:
        if self.playwright_context:
            self.playwright_context.close()
            self.playwright_context = None

        if self.playwright:
            self.playwright.stop()
            self.playwright = None


class ScrapeResult:
    doc: Document | None = None
    retry: bool = False


WEB_CONNECTOR_MAX_SCROLL_ATTEMPTS = 20
# Threshold for determining when to replace vs append iframe content
IFRAME_TEXT_LENGTH_THRESHOLD = 700
# Message indicating JavaScript is disabled, which often appears when scraping fails
JAVASCRIPT_DISABLED_MESSAGE = "You have JavaScript disabled in your browser"

# Define common headers that mimic a real browser
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

# Common PDF MIME types
PDF_MIME_TYPES = [
    "application/pdf",
    "application/x-pdf",
    "application/acrobat",
    "application/vnd.pdf",
    "text/pdf",
    "text/x-pdf",
]


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
        # Use a more realistic browser-like request
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)

        response = session.get(url, timeout=5, allow_redirects=True)

        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # Extract status code from the response, defaulting to -1 if response is None
        status_code = e.response.status_code if e.response is not None else -1

        # For 403 errors, we do have internet connection, but the request is blocked by the server
        # this is usually due to bot detection. Future calls (via Playwright) will usually get
        # around this.
        if status_code == 403:
            logger.warning(
                f"Received 403 Forbidden for {url}, will retry with browser automation"
            )
            return

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


def _same_site(base_url: str, candidate_url: str) -> bool:
    base, candidate = urlparse(base_url), urlparse(candidate_url)
    base_netloc = base.netloc.lower().removeprefix("www.")
    candidate_netloc = candidate.netloc.lower().removeprefix("www.")
    if base_netloc != candidate_netloc:
        return False

    base_path = (base.path or "/").rstrip("/")
    if base_path in ("", "/"):
        return True

    candidate_path = candidate.path or "/"
    if candidate_path == base_path:
        return True

    boundary = f"{base_path}/"
    return candidate_path.startswith(boundary)


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

        if _same_site(base_url, href):
            internal_links.add(href)
    return internal_links


def is_pdf_content(response: requests.Response) -> bool:
    """Check if the response contains PDF content based on content-type header"""
    content_type = response.headers.get("content-type", "").lower()
    return any(pdf_type in content_type for pdf_type in PDF_MIME_TYPES)


def start_playwright() -> Tuple[Playwright, BrowserContext]:
    playwright = sync_playwright().start()

    # Launch browser with more realistic settings
    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-site-isolation-trials",
        ],
    )

    # Create a context with realistic browser properties
    context = browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        viewport={"width": 1440, "height": 900},
        device_scale_factor=2.0,
        locale="en-US",
        timezone_id="America/Los_Angeles",
        has_touch=False,
        java_script_enabled=True,
        color_scheme="light",
        # Add more realistic browser properties
        bypass_csp=True,
        ignore_https_errors=True,
    )

    # Set additional headers to mimic a real browser
    context.set_extra_http_headers(
        {
            "Accept": DEFAULT_HEADERS["Accept"],
            "Accept-Language": DEFAULT_HEADERS["Accept-Language"],
            "Sec-Fetch-Dest": DEFAULT_HEADERS["Sec-Fetch-Dest"],
            "Sec-Fetch-Mode": DEFAULT_HEADERS["Sec-Fetch-Mode"],
            "Sec-Fetch-Site": DEFAULT_HEADERS["Sec-Fetch-Site"],
            "Sec-Fetch-User": DEFAULT_HEADERS["Sec-Fetch-User"],
            "Sec-CH-UA": DEFAULT_HEADERS["Sec-CH-UA"],
            "Sec-CH-UA-Mobile": DEFAULT_HEADERS["Sec-CH-UA-Mobile"],
            "Sec-CH-UA-Platform": DEFAULT_HEADERS["Sec-CH-UA-Platform"],
            "Cache-Control": "max-age=0",
            "DNT": "1",
        }
    )

    # Add a script to modify navigator properties to avoid detection
    context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
    """
    )

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
        response = requests.get(sitemap_url, headers=DEFAULT_HEADERS)
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


def _handle_cookies(context: BrowserContext, url: str) -> None:
    """Handle cookies for the given URL to help with bot detection"""
    try:
        # Parse the URL to get the domain
        parsed_url = urlparse(url)
        domain = parsed_url.netloc

        # Add some common cookies that might help with bot detection
        cookies: list[dict[str, str]] = [
            {
                "name": "cookieconsent",
                "value": "accepted",
                "domain": domain,
                "path": "/",
            },
            {
                "name": "consent",
                "value": "true",
                "domain": domain,
                "path": "/",
            },
            {
                "name": "session",
                "value": "random_session_id",
                "domain": domain,
                "path": "/",
            },
        ]

        # Add cookies to the context
        for cookie in cookies:
            try:
                context.add_cookies([cookie])  # type: ignore
            except Exception as e:
                logger.debug(f"Failed to add cookie {cookie['name']} for {domain}: {e}")
    except Exception:
        logger.exception(
            f"Unexpected error while handling cookies for Web Connector with URL {url}"
        )


class WebConnector(LoadConnector):
    MAX_RETRIES = 3

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

    def _do_scrape(
        self,
        index: int,
        initial_url: str,
        session_ctx: ScrapeSessionContext,
    ) -> ScrapeResult:
        """Returns a ScrapeResult object with a doc and retry flag."""

        if session_ctx.playwright is None:
            raise RuntimeError("scrape_context.playwright is None")

        if session_ctx.playwright_context is None:
            raise RuntimeError("scrape_context.playwright_context is None")

        result = ScrapeResult()

        # Handle cookies for the URL
        _handle_cookies(session_ctx.playwright_context, initial_url)

        # First do a HEAD request to check content type without downloading the entire content
        head_response = requests.head(
            initial_url, headers=DEFAULT_HEADERS, allow_redirects=True
        )
        is_pdf = is_pdf_content(head_response)

        if is_pdf or initial_url.lower().endswith(".pdf"):
            # PDF files are not checked for links
            response = requests.get(initial_url, headers=DEFAULT_HEADERS)
            page_text, metadata, images = read_pdf_file(
                file=io.BytesIO(response.content)
            )
            last_modified = response.headers.get("Last-Modified")

            result.doc = Document(
                id=initial_url,
                sections=[TextSection(link=initial_url, text=page_text)],
                source=DocumentSource.WEB,
                semantic_identifier=initial_url.split("/")[-1],
                metadata=metadata,
                doc_updated_at=(
                    _get_datetime_from_last_modified_header(last_modified)
                    if last_modified
                    else None
                ),
            )

            return result

        page = session_ctx.playwright_context.new_page()
        try:
            # Can't use wait_until="networkidle" because it interferes with the scrolling behavior
            page_response = page.goto(
                initial_url,
                timeout=30000,  # 30 seconds
                wait_until="domcontentloaded",  # Wait for DOM to be ready
            )

            last_modified = (
                page_response.header_value("Last-Modified") if page_response else None
            )
            final_url = page.url
            if final_url != initial_url:
                protected_url_check(final_url)
                initial_url = final_url
                if initial_url in session_ctx.visited_links:
                    logger.info(
                        f"{index}: {initial_url} redirected to {final_url} - already indexed"
                    )
                    page.close()
                    return result

                logger.info(f"{index}: {initial_url} redirected to {final_url}")
                session_ctx.visited_links.add(initial_url)

            # If we got here, the request was successful
            if self.scroll_before_scraping:
                scroll_attempts = 0
                previous_height = page.evaluate("document.body.scrollHeight")
                while scroll_attempts < WEB_CONNECTOR_MAX_SCROLL_ATTEMPTS:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    # wait for the content to load if we scrolled
                    page.wait_for_load_state("networkidle", timeout=30000)
                    time.sleep(0.5)  # let javascript run

                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == previous_height:
                        break  # Stop scrolling when no more content is loaded
                    previous_height = new_height
                    scroll_attempts += 1

            content = page.content()
            soup = BeautifulSoup(content, "html.parser")

            if self.recursive:
                internal_links = get_internal_links(
                    session_ctx.base_url, initial_url, soup
                )
                for link in internal_links:
                    if link not in session_ctx.visited_links:
                        session_ctx.to_visit.append(link)

            if page_response and str(page_response.status)[0] in ("4", "5"):
                session_ctx.last_error = f"Skipped indexing {initial_url} due to HTTP {page_response.status} response"
                logger.info(session_ctx.last_error)
                result.retry = True
                return result

            # after this point, we don't need the caller to retry
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
                        page.frame_locator("iframe").locator("html").all_inner_texts()
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
            if hashed_text in session_ctx.content_hashes:
                logger.info(
                    f"{index}: Skipping duplicate title + content for {initial_url}"
                )
                return result

            session_ctx.content_hashes.add(hashed_text)

            result.doc = Document(
                id=initial_url,
                sections=[TextSection(link=initial_url, text=parsed_html.cleaned_text)],
                source=DocumentSource.WEB,
                semantic_identifier=parsed_html.title or initial_url,
                metadata={},
                doc_updated_at=(
                    _get_datetime_from_last_modified_header(last_modified)
                    if last_modified
                    else None
                ),
            )
        finally:
            page.close()

        return result

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Traverses through all pages found on the website
        and converts them into documents"""

        if not self.to_visit_list:
            raise ValueError("No URLs to visit")

        base_url = self.to_visit_list[0]  # For the recursive case
        check_internet_connection(base_url)  # make sure we can connect to the base url

        session_ctx = ScrapeSessionContext(base_url, self.to_visit_list)
        session_ctx.initialize()

        while session_ctx.to_visit:
            initial_url = session_ctx.to_visit.pop()
            if initial_url in session_ctx.visited_links:
                continue
            session_ctx.visited_links.add(initial_url)

            try:
                protected_url_check(initial_url)
            except Exception as e:
                session_ctx.last_error = f"Invalid URL {initial_url} due to {e}"
                logger.warning(session_ctx.last_error)
                continue

            index = len(session_ctx.visited_links)
            logger.info(f"{index}: Visiting {initial_url}")

            # Add retry mechanism with exponential backoff
            retry_count = 0

            while retry_count < self.MAX_RETRIES:
                if retry_count > 0:
                    # Add a random delay between retries (exponential backoff)
                    delay = min(2**retry_count + random.uniform(0, 1), 10)
                    logger.info(
                        f"Retry {retry_count}/{self.MAX_RETRIES} for {initial_url} after {delay:.2f}s delay"
                    )
                    time.sleep(delay)

                try:
                    result = self._do_scrape(index, initial_url, session_ctx)
                    if result.retry:
                        continue

                    if result.doc:
                        session_ctx.doc_batch.append(result.doc)
                except Exception as e:
                    session_ctx.last_error = f"Failed to fetch '{initial_url}': {e}"
                    logger.exception(session_ctx.last_error)
                    session_ctx.initialize()
                    continue
                finally:
                    retry_count += 1

                break  # success / don't retry

            if len(session_ctx.doc_batch) >= self.batch_size:
                session_ctx.initialize()
                session_ctx.at_least_one_doc = True
                yield session_ctx.doc_batch
                session_ctx.doc_batch = []

        if session_ctx.doc_batch:
            session_ctx.stop()
            session_ctx.at_least_one_doc = True
            yield session_ctx.doc_batch

        if not session_ctx.at_least_one_doc:
            if session_ctx.last_error:
                raise RuntimeError(session_ctx.last_error)
            raise RuntimeError("No valid pages found.")

        session_ctx.stop()

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
