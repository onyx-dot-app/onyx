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

import base64
from collections.abc import Iterator
from contextlib import contextmanager
from typing import NotRequired, TypedDict, cast
from urllib.parse import urlsplit

from playwright.sync_api import (
    BrowserContext,
    CDPSession,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel

from onyx.configs.app_configs import (
    WEB_CONNECTOR_OAUTH_CLIENT_ID,
    WEB_CONNECTOR_OAUTH_CLIENT_SECRET,
    WEB_CONNECTOR_OAUTH_TOKEN_URL,
)
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException, validate_outbound_http_url

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
MAX_RENDERED_DOCUMENT_BYTES = 20 * 1024 * 1024


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
            "--block-new-web-contents",
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
        ignore_https_errors=True,
        service_workers="block",
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

    return playwright, context


def get_connector_oauth_header() -> str | None:
    if not (
        WEB_CONNECTOR_OAUTH_CLIENT_ID
        and WEB_CONNECTOR_OAUTH_CLIENT_SECRET
        and WEB_CONNECTOR_OAUTH_TOKEN_URL
    ):
        return None

    from oauthlib.oauth2 import BackendApplicationClient
    from requests_oauthlib import OAuth2Session

    client = BackendApplicationClient(client_id=WEB_CONNECTOR_OAUTH_CLIENT_ID)
    oauth = OAuth2Session(client=client)
    token = oauth.fetch_token(
        token_url=WEB_CONNECTOR_OAUTH_TOKEN_URL,
        client_id=WEB_CONNECTOR_OAUTH_CLIENT_ID,
        client_secret=WEB_CONNECTOR_OAUTH_CLIENT_SECRET,
    )
    return f"Bearer {token['access_token']}"


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


def _ssrf_allows(
    url: str, *, allow_private_network: bool, allow_loopback: bool = False
) -> bool:
    """Does `url` pass the outbound destination policy for a rendered fetch?"""
    try:
        validate_outbound_http_url(
            url,
            allow_private_network=allow_private_network,
            block_loopback_and_link_local=not allow_loopback,
            block_link_local_only=True,
        )
        return True
    except (SSRFException, ValueError):
        return False


class _ResponseStream(TypedDict):
    stream: str


class _StreamChunk(TypedDict):
    data: str
    eof: bool
    base64Encoded: NotRequired[bool]


def _read_document_body(session: CDPSession, request_id: str) -> str | None:
    stream = cast(
        _ResponseStream,
        session.send("Fetch.takeResponseBodyAsStream", {"requestId": request_id}),
    )["stream"]
    body = bytearray()
    try:
        while True:
            chunk = cast(
                _StreamChunk,
                session.send("IO.read", {"handle": stream, "size": 64 * 1024}),
            )
            data = (
                base64.b64decode(chunk["data"])
                if chunk.get("base64Encoded")
                else chunk["data"].encode()
            )
            if len(body) + len(data) > MAX_RENDERED_DOCUMENT_BYTES:
                return None
            body.extend(data)
            if chunk["eof"]:
                return base64.b64encode(body).decode()
    finally:
        session.send("IO.close", {"handle": stream})


class _Header(TypedDict):
    name: str
    value: str


class _InterceptedRequest(TypedDict):
    url: str
    headers: dict[str, str]


class _PausedRequest(TypedDict):
    requestId: str
    request: _InterceptedRequest
    responseStatusCode: NotRequired[int]
    responseHeaders: NotRequired[list[_Header]]


def _url_origin(url: str) -> tuple[str, str | None, int | None]:
    parsed = urlsplit(url)
    port = parsed.port
    return (
        parsed.scheme,
        parsed.hostname,
        port if port is not None else {"https": 443, "http": 80}.get(parsed.scheme),
    )


def install_ssrf_guard(
    page: Page,
    *,
    allow_private_network: bool,
    allow_loopback: bool = False,
    authorization_header: str | None = None,
    authorization_url: str | None = None,
) -> None:
    if allow_private_network:
        page.context.grant_permissions(["local-network-access"])
    session = page.context.new_cdp_session(page)
    session.send("Network.setCacheDisabled", {"cacheDisabled": True})

    def guard_request(event: _PausedRequest) -> None:
        if "responseStatusCode" in event:
            headers = event.get("responseHeaders", []) + [
                _Header(name="Content-Security-Policy", value="worker-src 'none'")
            ]
            if 300 <= event["responseStatusCode"] < 400 or event[
                "responseStatusCode"
            ] in (204, 205):
                session.send(
                    "Fetch.continueResponse", {"requestId": event["requestId"]}
                )
                return
            # Shared workers use browser-side CSP, which header-only overrides do not update.
            body = _read_document_body(session, event["requestId"])
            if body is None:
                session.send(
                    "Fetch.failRequest",
                    {"requestId": event["requestId"], "errorReason": "BlockedByClient"},
                )
                return
            session.send(
                "Fetch.fulfillRequest",
                {
                    "requestId": event["requestId"],
                    "responseCode": event["responseStatusCode"],
                    "responseHeaders": headers,
                    "body": body,
                },
            )
            return

        url = event["request"]["url"]
        if not _ssrf_allows(
            url,
            allow_private_network=allow_private_network,
            allow_loopback=allow_loopback,
        ):
            session.send(
                "Fetch.failRequest",
                {"requestId": event["requestId"], "errorReason": "BlockedByClient"},
            )
            return

        if authorization_header is not None:
            headers = [
                _Header(name=name, value=value)
                for name, value in event["request"]["headers"].items()
                if not (
                    name.lower() == "authorization" and value == authorization_header
                )
            ]
            if authorization_url is not None and _url_origin(url) == _url_origin(
                authorization_url
            ):
                headers = [
                    header
                    for header in headers
                    if header["name"].lower() != "authorization"
                ]
                headers.append(
                    _Header(name="Authorization", value=authorization_header)
                )
            session.send(
                "Fetch.continueRequest",
                {"requestId": event["requestId"], "headers": headers},
            )
        else:
            session.send("Fetch.continueRequest", {"requestId": event["requestId"]})

    # Playwright route handlers do not run for subsequent HTTP redirect hops.
    session.on("Fetch.requestPaused", guard_request)
    session.send(
        "Fetch.enable",
        {
            "patterns": [
                {"urlPattern": "*", "requestStage": "Request"},
                {
                    "urlPattern": "*",
                    "resourceType": "Document",
                    "requestStage": "Response",
                },
            ]
        },
    )


def read_bounded_page_html(page: Page) -> str | None:
    html = cast(
        str | None,
        page.evaluate(
            """(limit) => {
                const html = (document.doctype ? new XMLSerializer().serializeToString(document.doctype) : "")
                    + (document.documentElement ? document.documentElement.outerHTML : "");
                return html.length > limit ? null : html;
            }""",
            MAX_RENDERED_DOCUMENT_BYTES,
        ),
    )
    if html is None or len(html.encode("utf-8")) > MAX_RENDERED_DOCUMENT_BYTES:
        return None
    return html


def fetch_rendered_html(
    url: str,
    *,
    navigation_timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
    bot_challenge_grace_ms: int = DEFAULT_BOT_CHALLENGE_GRACE_MS,
    allow_private_network: bool = False,
) -> RenderedPage | None:
    """Render a single URL via headless Chromium and return the final HTML.

    Owns its own short-lived Playwright lifecycle (one context per call),
    so it's safe to invoke from arbitrary worker threads. Suitable for
    one-shot fetches where bot-detection mitigation is needed; not the
    right tool for high-volume crawling (use a long-lived `BrowserContext`
    via `start_playwright()` instead).

    When ``allow_private_network`` is True, the private-IP guard is skipped
    so operators on trusted networks can render URLs that resolve to RFC1918
    addresses. Scheme/credential/blocked-hostname checks still apply.

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
    if not _ssrf_allows(url, allow_private_network=allow_private_network):
        logger.warning("Refusing Playwright fallback for %s", url)
        return None

    try:
        with playwright_session() as context:
            page = context.new_page()
            install_ssrf_guard(page, allow_private_network=allow_private_network)
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

                final_url = page.url
                if not _ssrf_allows(
                    final_url, allow_private_network=allow_private_network
                ):
                    logger.warning(
                        "Playwright fallback ended on a disallowed destination"
                    )
                    return None

                html = read_bounded_page_html(page)
                if html is None:
                    return None
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
