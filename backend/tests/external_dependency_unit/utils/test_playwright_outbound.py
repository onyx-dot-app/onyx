import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest

from onyx.connectors.web.connector import ScrapeSessionContext, WebConnector
from onyx.server.security.models import SSRFProtectionLevel
from onyx.utils import playwright_fetch
from onyx.utils.playwright_fetch import fetch_rendered_html
from onyx.utils.url import validate_outbound_http_url


@pytest.mark.parametrize(
    "attack",
    [
        "redirect",
        "javascript",
        "image",
        "iframe",
        "popup",
        "worker",
        "dedicated",
        "shared",
        "csp",
        "oversized",
        "dom",
        "dom_utf8",
        "web_dom",
    ],
)
def test_browser_blocks_private_followup_requests(attack: str) -> None:
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            target = f"http://localhost:{server.server_port}/blocked"
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/middle")
                self.end_headers()
                return
            if self.path == "/middle":
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "application/javascript" if self.path == "/sw.js" else "text/html",
            )
            if self.path == "/csp":
                self.send_header("Content-Security-Policy", "img-src 'none'")
                self.send_header("Content-Encoding", "gzip")
                self.send_header(
                    "Content-Length",
                    str(len(gzip.compress(b'<p>test content</p><img src="/blocked">'))),
                )
            self.end_headers()
            bodies = {
                "/javascript": f'<script>location.href="{target}"</script>',
                "/image": f'<img src="{target}">',
                "/iframe": f'<iframe src="{target}"></iframe>',
                "/popup": f'<script>window.open("{target}")</script>',
                "/worker": '<script>navigator.serviceWorker.register("/sw.js").then(()=>navigator.serviceWorker.ready).then(r=>r.active.postMessage("fetch"))</script>',
                "/csp": '<img src="/blocked">',
                "/dom": '<script>document.body.append("x".repeat(2048))</script>',
                "/dom_utf8": "<script>document.body.append(String.fromCharCode(233).repeat(600))</script>",
                "/web_dom": '<script>document.body.append("x".repeat(2048))</script>',
                "/dedicated": f'<script>const worker=new Worker(URL.createObjectURL(new Blob([`postMessage("started");fetch("{target}")`], {{type:"application/javascript"}})));worker.onmessage=()=>document.documentElement.dataset.workerStarted="yes"</script>',
                "/shared": f'<script>new SharedWorker(URL.createObjectURL(new Blob([`fetch("{target}")`], {{type:"application/javascript"}})))</script>',
                "/sw.js": f'self.addEventListener("install", e=>self.skipWaiting()); self.addEventListener("activate",e=>e.waitUntil(clients.claim())); self.addEventListener("message",e=>fetch("{target}"));',
            }
            content = (
                "<p>test content</p>" + bodies.get(self.path, "<p>content</p>")
            ).encode()
            if self.path == "/oversized":
                content += b"x" * 2048
            self.wfile.write(gzip.compress(content) if self.path == "/csp" else content)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = f"http://127.0.0.1:{server.server_port}"

    def validate_target(url: str, **kwargs: bool) -> str:
        if urlsplit(url).netloc == urlsplit(source).netloc:
            return url
        return validate_outbound_http_url(url, **kwargs)

    try:
        with (
            patch(
                "onyx.utils.playwright_fetch.validate_outbound_http_url",
                side_effect=validate_target,
            ),
            patch.object(
                playwright_fetch, "MAX_RENDERED_DOCUMENT_BYTES", 1024, create=True
            ),
        ):
            if attack == "web_dom":
                session = ScrapeSessionContext(source, [f"{source}/web_dom"])
                with (
                    patch(
                        "onyx.connectors.web.connector.get_connector_oauth_header",
                        return_value=None,
                    ),
                    patch(
                        "onyx.connectors.web.connector.get_security_settings"
                    ) as settings,
                    patch("onyx.connectors.web.connector.ssrf_safe_get") as preflight,
                ):
                    settings.return_value.ssrf_protection_level = (
                        SSRFProtectionLevel.VALIDATE_ALL
                    )
                    preflight.return_value.__enter__.return_value.headers = {
                        "content-type": "text/html"
                    }
                    session.initialize()
                    try:
                        with pytest.raises(
                            ValueError, match="Rendered document exceeds"
                        ):
                            WebConnector(source)._do_scrape(
                                0, f"{source}/web_dom", session, slim=True
                            )
                    finally:
                        session.stop()
                assert "/web_dom" in requests
                return
            result = fetch_rendered_html(
                f"{source}/{attack}",
                navigation_timeout_ms=2000,
                bot_challenge_grace_ms=1000,
            )
        if attack in ("oversized", "dom", "dom_utf8"):
            assert result is None
        if attack not in ("redirect", "javascript", "oversized", "dom", "dom_utf8"):
            assert result is not None
            assert "test content" in result.html
        if attack == "dedicated":
            assert result is not None
            assert "data-worker-started" not in result.html
        assert f"/{attack}" in requests
        assert "/blocked" not in requests
        if attack == "worker":
            assert "/sw.js" not in requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("redirect", [False, True])
def test_web_connector_limits_bearer_to_crawl_origin(redirect: bool) -> None:
    received: list[tuple[str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

        def do_GET(self) -> None:
            received.append((self.path, self.headers.get("Authorization")))
            cross_origin = f"http://127.0.0.1:{cross_server.server_port}/cross"
            if redirect and self.path == "/root":
                self.send_response(302)
                self.send_header("Location", cross_origin)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            body = (
                f'<img src="/same"><img src="{cross_origin}"><img src="/private">'
                if self.path == "/root"
                else "<p>content</p>"
            )
            self.wfile.write(body.encode())

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    cross_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    cross_thread = Thread(target=cross_server.serve_forever, daemon=True)
    cross_thread.start()
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = f"http://127.0.0.1:{server.server_port}"
    session = ScrapeSessionContext(source, [f"{source}/root"])

    def validate_target(url: str, **kwargs: bool) -> str:
        if urlsplit(url).path != "/private":
            return url
        return validate_outbound_http_url(url, **kwargs)

    try:
        with (
            patch.object(
                playwright_fetch, "WEB_CONNECTOR_OAUTH_CLIENT_ID", "test-client"
            ),
            patch.object(
                playwright_fetch, "WEB_CONNECTOR_OAUTH_CLIENT_SECRET", "test-secret"
            ),
            patch.object(
                playwright_fetch,
                "WEB_CONNECTOR_OAUTH_TOKEN_URL",
                "https://auth.example/token",
            ),
            patch(
                "requests_oauthlib.OAuth2Session.fetch_token",
                return_value={"access_token": "test-token"},
            ),
            patch.object(
                playwright_fetch,
                "validate_outbound_http_url",
                side_effect=validate_target,
            ),
            patch("onyx.connectors.web.connector.get_security_settings") as settings,
            patch("onyx.connectors.web.connector.protected_url_check"),
            patch("onyx.connectors.web.connector.ssrf_safe_get") as preflight,
        ):
            settings.return_value.ssrf_protection_level = (
                SSRFProtectionLevel.VALIDATE_ALL
            )
            preflight.return_value.__enter__.return_value.headers = {
                "content-type": "text/html"
            }
            session.initialize()
            assert session.playwright_context is not None
            session.playwright_context.grant_permissions(
                ["local-network-access"], origin=source
            )
            connector = WebConnector(source)
            connector._do_scrape(0, f"{source}/root", session, slim=True)
        assert ("/root", "Bearer test-token") in received
        assert ("/cross", None) in received
        assert ("/cross", "Bearer test-token") not in received
        assert all(path != "/private" for path, _ in received)
        if not redirect:
            assert ("/same", "Bearer test-token") in received
    finally:
        session.stop()
        cross_server.shutdown()
        cross_server.server_close()
        cross_thread.join()
        server.shutdown()
        server.server_close()
        thread.join()
