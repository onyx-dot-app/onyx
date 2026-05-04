"""Shared Playwright-based fetching helpers.

Centralizes the browser-launch tuning and bot-detection-aware navigation
logic that was originally embedded in `onyx.connectors.web.connector`.

Two consumers:
- `WebConnector` (long-lived `BrowserContext` reused across many pages
  in a single crawl) uses `start_playwright()` directly.
- `OnyxWebCrawler` (lazy fallback when its `requests`-based fetch hits
  a Cloudflare/bot challenge) uses `fetch_rendered_html()` to do a
  one-shot navigation per URL.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import BrowserContext
from playwright.sync_api import Playwright
from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel

from onyx.configs.app_configs import WEB_CONNECTOR_OAUTH_CLIENT_ID
from onyx.configs.app_configs import WEB_CONNECTOR_OAUTH_CLIENT_SECRET
from onyx.configs.app_configs import WEB_CONNECTOR_OAUTH_TOKEN_URL
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException
from onyx.utils.url import validate_outbound_http_url

logger = setup_logger()


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    # Brotli decoding has been flaky in brotlicffi/httpx for certain chunked responses;
    # stick to gzip/deflate to keep connectivity checks stable.
    "Accept-Encoding": "gzip, deflate",
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

# Grace period after page navigation to allow bot-detection challenges
# (Cloudflare / Imperva / etc.) and SPA content rendering to complete.
DEFAULT_BOT_CHALLENGE_GRACE_MS = 5000

# Total per-navigation budget for Playwright `goto` / wait_for_load_state.
# Generous because we *want* to absorb a Cloudflare interstitial.
DEFAULT_NAVIGATION_TIMEOUT_MS = 30000


class RenderedPage(BaseModel):
    """Result of a successful Playwright navigation."""

    html: str
    final_url: str
    last_modified: str | None = None
    status: int | None = None


def start_playwright() -> tuple[Playwright, BrowserContext]:
    """Launch a Playwright Chromium context tuned to look like a real browser.

    Used by both the long-lived web-connector crawl and the one-shot
    OnyxWebCrawler fallback. Caller owns lifecycle and must call
    `context.close()` + `playwright.stop()` when done.
    """
    playwright = sync_playwright().start()

    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-site-isolation-trials",
        ],
    )

    context = browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        viewport={"width": 1440, "height": 900},
        device_scale_factor=2.0,
        locale="en-US",
        timezone_id="America/Los_Angeles",
        has_touch=False,
        java_script_enabled=True,
        color_scheme="light",
        bypass_csp=True,
        ignore_https_errors=True,
    )

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

    # Hide common automation tells used by bot-detection scripts.
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
    """)

    if (
        WEB_CONNECTOR_OAUTH_CLIENT_ID
        and WEB_CONNECTOR_OAUTH_CLIENT_SECRET
        and WEB_CONNECTOR_OAUTH_TOKEN_URL
    ):
        # Imported lazily so the OAuth deps don't get pulled in unless configured.
        from oauthlib.oauth2 import BackendApplicationClient
        from requests_oauthlib import OAuth2Session

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


@contextmanager
def playwright_session() -> Iterator[BrowserContext]:
    """Context-manager wrapper around `start_playwright()` for one-shot use.

    Yields a `BrowserContext` and guarantees both the context and the
    underlying `Playwright` instance are torn down when the `with` block
    exits, including when setup itself raises (e.g. missing Chromium binary).
    Use this for short-lived fetches that own their Playwright lifecycle
    end-to-end. Long-lived crawls that need to detach setup from teardown
    across method boundaries (see `WebConnector`) should keep using
    `start_playwright()` directly.
    """
    playwright: Playwright | None = None
    context: BrowserContext | None = None
    try:
        playwright, context = start_playwright()
        yield context
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                logger.debug("Failed to close Playwright context", exc_info=True)
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                logger.debug("Failed to stop Playwright", exc_info=True)


def _looks_like_bot_challenge(status: int, cf_ray_header: str | None) -> bool:
    """Heuristic: did this response look like a Cloudflare/Imperva challenge?

    We trigger the post-navigation grace period when *either* signal is
    present so JS challenges have time to resolve before we read the DOM.
    """
    return cf_ray_header is not None or status == 403


# Strings that appear in Cloudflare challenge HTML bodies (Managed Challenge,
# Turnstile interstitial, "I'm Under Attack" mode, etc.). If a rendered page
# still contains any of these after our grace period, the JS challenge did
# not resolve (or we were actively rejected) and the body is the challenge
# page itself rather than the real content.
#
# Why these specifically:
# - `challenges.cloudflare.com` — script src on every CF challenge page
# - `/cdn-cgi/challenge-platform/` — CF's challenge JS path
# - `cf-chl-bypass` — class on CF challenge container divs
# - `cf-mitigated` — appears in some challenge bodies as well as headers
# - `Just a moment...` — title on the legacy IUAM challenge page
# - `Verifying you are human` — Managed Challenge / Turnstile UI string
_CLOUDFLARE_CHALLENGE_BODY_MARKERS = (
    "challenges.cloudflare.com",
    "/cdn-cgi/challenge-platform/",
    "cf-chl-bypass",
    "cf-mitigated",
    "Just a moment...",
    "Verifying you are human",
)


def looks_like_cloudflare_challenge(html: str) -> bool:
    """Did this rendered HTML come back as a Cloudflare challenge page?

    Used by callers (e.g. `OnyxWebCrawler`) to distinguish "we got real
    content" from "Chromium rendered the challenge interstitial itself
    because CF didn't let us through". The latter must NOT be returned
    to the LLM as if it were the page.
    """
    return bool(html) and any(
        marker in html for marker in _CLOUDFLARE_CHALLENGE_BODY_MARKERS
    )


def fetch_rendered_html(
    url: str,
    *,
    navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
    bot_challenge_grace_ms: int = DEFAULT_BOT_CHALLENGE_GRACE_MS,
) -> RenderedPage | None:
    """Render a single URL via headless Chromium and return the final HTML.

    Owns its own short-lived Playwright lifecycle (one context per call),
    so it's safe to invoke from arbitrary worker threads. Suitable for
    one-shot fetches where bot-detection mitigation is needed; not the
    right tool for high-volume crawling (use a long-lived `BrowserContext`
    via `start_playwright()` instead).

    Returns:
        RenderedPage on success, or None if navigation failed entirely
        (including SSRF rejection of the URL). A non-None return with a
        4xx/5xx `status` is still possible — the caller can decide whether
        to use the rendered HTML (challenge pages often render real content
        after JS executes despite the original 4xx status code).
    """
    # Playwright bypasses our `requests`-level SSRF protection, so revalidate
    # the URL here before letting Chromium navigate to it. Note: there is a
    # small TOCTOU window between validation and the actual navigation, the
    # same window that ssrf_safe_get accepts for HTTPS URLs.
    try:
        validate_outbound_http_url(url)
    except (SSRFException, ValueError) as exc:
        logger.warning(
            "Refusing Playwright fallback for %s (%s)", url, exc.__class__.__name__
        )
        return None

    try:
        with playwright_session() as context:
            page = context.new_page()
            try:
                # Use "commit" instead of "domcontentloaded" to avoid hanging
                # on bot-detection pages that may never fire domcontentloaded.
                response = page.goto(
                    url,
                    timeout=navigation_timeout_ms,
                    wait_until="commit",
                )

                cf_ray = response.header_value("cf-ray") if response else None
                status = response.status if response else None

                if status is not None and _looks_like_bot_challenge(status, cf_ray):
                    page.wait_for_timeout(bot_challenge_grace_ms)

                # Best-effort wait for network to settle (SPA / CF challenge JS).
                try:
                    page.wait_for_load_state(
                        "networkidle", timeout=bot_challenge_grace_ms
                    )
                except PlaywrightTimeoutError:
                    pass

                html = page.content()
                final_url = page.url
                last_modified = (
                    response.header_value("Last-Modified") if response else None
                )
                return RenderedPage(
                    html=html,
                    final_url=final_url,
                    last_modified=last_modified,
                    status=status,
                )
            finally:
                page.close()
    except Exception as exc:
        msg = str(exc)
        if "Executable doesn't exist" in msg:
            # Friendlier message for the common "venv has Playwright but
            # Chromium binary not installed" footgun. Production Docker
            # images install it during build (see backend/Dockerfile),
            # but local dev `pip install`s won't.
            logger.warning(
                "Playwright fallback unavailable for %s: Chromium binary not "
                "installed. Run `playwright install chromium` in your venv.",
                url,
            )
        else:
            logger.warning(
                "Playwright fallback failed to render %s (%s: %s)",
                url,
                exc.__class__.__name__,
                msg.splitlines()[0] if msg else "",
            )
        return None
