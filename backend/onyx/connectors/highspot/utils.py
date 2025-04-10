from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from onyx.file_processing.html_utils import web_html_cleanup
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Constants
WEB_CONNECTOR_MAX_SCROLL_ATTEMPTS = 20
JAVASCRIPT_DISABLED_MESSAGE = "You have JavaScript disabled in your browser"
DEFAULT_TIMEOUT = 60000  # 60 seconds


def scrape_url_content(
    url: str, scroll_before_scraping: bool = False, timeout_ms: int = DEFAULT_TIMEOUT
) -> Optional[str]:
    """
    Scrapes content from a given URL and returns the cleaned text.

    Args:
        url: The URL to scrape
        scroll_before_scraping: Whether to scroll through the page to load lazy content
        timeout_ms: Timeout in milliseconds for page navigation and loading

    Returns:
        The cleaned text content of the page or None if scraping fails
    """
    playwright = None
    browser = None
    try:
        validate_url(url)
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        logger.info(f"Navigating to URL: {url}")
        try:
            page.goto(url, timeout=timeout_ms)
        except Exception as e:
            logger.error(f"Failed to navigate to {url}: {str(e)}")
            return None

        if scroll_before_scraping:
            logger.debug("Scrolling page to load lazy content")
            scroll_attempts = 0
            previous_height = page.evaluate("document.body.scrollHeight")
            while scroll_attempts < WEB_CONNECTOR_MAX_SCROLL_ATTEMPTS:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception as e:
                    logger.warning(f"Network idle wait timed out: {str(e)}")
                    break

                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == previous_height:
                    break
                previous_height = new_height
                scroll_attempts += 1

        content = page.content()
        soup = BeautifulSoup(content, "html.parser")

        parsed_html = web_html_cleanup(soup)

        if JAVASCRIPT_DISABLED_MESSAGE in parsed_html.cleaned_text:
            logger.debug("JavaScript disabled message detected, checking iframes")
            try:
                iframe_count = page.frame_locator("iframe").locator("html").count()
                if iframe_count > 0:
                    iframe_texts = (
                        page.frame_locator("iframe").locator("html").all_inner_texts()
                    )
                    iframe_content = "\n".join(iframe_texts)

                    if len(parsed_html.cleaned_text) < 700:
                        parsed_html.cleaned_text = iframe_content
                    else:
                        parsed_html.cleaned_text += "\n" + iframe_content
            except Exception as e:
                logger.warning(f"Error processing iframes: {str(e)}")

        return parsed_html.cleaned_text

    except Exception as e:
        logger.error(f"Error scraping URL {url}: {str(e)}")
        return None

    finally:
        if browser:
            try:
                browser.close()
            except Exception as e:
                logger.debug(f"Error closing browser: {str(e)}")
        if playwright:
            try:
                playwright.stop()
            except Exception as e:
                logger.debug(f"Error stopping playwright: {str(e)}")


def validate_url(url: str) -> None:
    """
    Validates that a URL is properly formatted.

    Args:
        url: The URL to validate

    Raises:
        ValueError: If URL is not valid
    """
    parse = urlparse(url)
    if parse.scheme != "http" and parse.scheme != "https":
        raise ValueError("URL must be of scheme https?://")

    if not parse.hostname:
        raise ValueError("URL must include a hostname")
