"""Unit tests for webapp proxy path rewriting/injection."""

from collections.abc import AsyncGenerator
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from fastapi import Request
from starlette.responses import StreamingResponse

from onyx.db.enums import SharingScope
from onyx.server.features.build.api import api
from onyx.server.features.build.api.api import _inject_hmr_fixer
from onyx.server.features.build.api.api import _rewrite_asset_paths
from onyx.server.features.build.api.api import _rewrite_proxy_response_headers

SESSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
BASE = f"/api/build/sessions/{SESSION_ID}/webapp"


def rewrite(html: str) -> str:
    return _rewrite_asset_paths(html.encode(), SESSION_ID).decode()


def inject(html: str) -> str:
    return _inject_hmr_fixer(html.encode(), SESSION_ID).decode()


class TestNextjsPathRewriting:
    def test_rewrites_bare_next_script_src(self) -> None:
        html = '<script src="/_next/static/chunks/main.js">'
        result = rewrite(html)
        assert f'src="{BASE}/_next/static/chunks/main.js"' in result
        assert '"/_next/' not in result

    def test_rewrites_bare_next_in_single_quotes(self) -> None:
        html = "<link href='/_next/static/css/app.css'>"
        result = rewrite(html)
        assert f"'{BASE}/_next/static/css/app.css'" in result

    def test_rewrites_bare_next_in_url_parens(self) -> None:
        html = "background: url(/_next/static/media/font.woff2)"
        result = rewrite(html)
        assert f"url({BASE}/_next/static/media/font.woff2)" in result

    def test_no_double_prefix_when_already_proxied(self) -> None:
        """assetPrefix makes Next.js emit already-prefixed URLs — must not double-rewrite."""
        already_prefixed = f'<script src="{BASE}/_next/static/chunks/main.js">'
        result = rewrite(already_prefixed)
        # Should be unchanged
        assert result == already_prefixed
        # Specifically, no double path
        assert f"{BASE}/{BASE}" not in result

    def test_rewrites_favicon(self) -> None:
        html = '<link rel="icon" href="/favicon.ico">'
        result = rewrite(html)
        assert f'"{BASE}/favicon.ico"' in result

    def test_rewrites_json_data_path_double_quoted(self) -> None:
        html = 'fetch("/data/tickets.json")'
        result = rewrite(html)
        assert f'"{BASE}/data/tickets.json"' in result

    def test_rewrites_json_data_path_single_quoted(self) -> None:
        html = "fetch('/data/items.json')"
        result = rewrite(html)
        assert f"'{BASE}/data/items.json'" in result

    def test_rewrites_escaped_next_font_path_in_json_script(self) -> None:
        """Next dev can embed font asset paths in JSON-escaped script payloads."""
        html = r'{"src":"\/_next\/static\/media\/font.woff2"}'
        result = rewrite(html)
        assert (
            r'{"src":"\/api\/build\/sessions\/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\/webapp\/_next\/static\/media\/font.woff2"}'
            in result
        )

    def test_rewrites_escaped_next_font_path_in_style_payload(self) -> None:
        """Keep dynamically generated next/font URLs inside the session proxy."""
        html = r'{"css":"@font-face{src:url(\"\/_next\/static\/media\/font.woff2\")"}'
        result = rewrite(html)
        assert (
            r"\/api\/build\/sessions\/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\/webapp\/_next\/static\/media\/font.woff2"
            in result
        )

    def test_rewrites_absolute_next_font_url(self) -> None:
        html = '<link rel="preload" as="font" href="https://craft-dev.onyx.app/_next/static/media/font.woff2">'
        result = rewrite(html)
        assert f'"{BASE}/_next/static/media/font.woff2"' in result

    def test_rewrites_root_hmr_path(self) -> None:
        html = 'new WebSocket("wss://craft-dev.onyx.app/_next/webpack-hmr?id=abc")'
        result = rewrite(html)
        assert '"wss://craft-dev.onyx.app/_next/webpack-hmr?id=abc"' not in result
        assert '"/_next/webpack-hmr?id=abc"' in result

    def test_rewrites_escaped_absolute_next_font_url(self) -> None:
        html = (
            r'{"href":"https:\/\/craft-dev.onyx.app\/_next\/static\/media\/font.woff2"}'
        )
        result = rewrite(html)
        assert (
            r'{"href":"\/api\/build\/sessions\/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\/webapp\/_next\/static\/media\/font.woff2"}'
            in result
        )


class TestRuntimeFixerInjection:
    def test_injects_websocket_rewrite_shim(self) -> None:
        html = "<html><head></head><body></body></html>"
        result = inject(html)
        assert "window.WebSocket = function (url, protocols)" in result
        assert f'var WEBAPP_BASE = "{BASE}"' in result

    def test_injects_hmr_websocket_stub(self) -> None:
        html = "<html><head></head><body></body></html>"
        result = inject(html)
        assert "function MockHmrWebSocket(url)" in result
        assert "return new MockHmrWebSocket(rewriteNextAssetUrl(url));" in result

    def test_injects_before_head_contents(self) -> None:
        html = "<html><head><title>x</title></head><body></body></html>"
        result = inject(html)
        assert result.index(
            "window.WebSocket = function (url, protocols)"
        ) < result.index("<title>x</title>")

    def test_rewritten_hmr_url_still_matches_shim_intercept_logic(self) -> None:
        html = '<html><head></head><body>new WebSocket("wss://craft-dev.onyx.app/_next/webpack-hmr?id=abc")</body></html>'

        rewritten = rewrite(html)
        assert '"wss://craft-dev.onyx.app/_next/webpack-hmr?id=abc"' not in rewritten
        assert 'new WebSocket("/_next/webpack-hmr?id=abc")' in rewritten

        injected = inject(rewritten)

        assert 'new WebSocket("/_next/webpack-hmr?id=abc")' in injected
        assert 'parsedUrl.pathname.indexOf("/_next/webpack-hmr") === 0' in injected


class TestProxyHeaderRewriting:
    def test_rewrites_link_header_font_preload_paths(self) -> None:
        headers = {
            "link": (
                '</_next/static/media/font.woff2>; rel=preload; as="font"; crossorigin, '
                '</_next/static/media/font2.woff2>; rel=preload; as="font"; crossorigin'
            )
        }

        result = _rewrite_proxy_response_headers(headers, SESSION_ID)

        assert f"<{BASE}/_next/static/media/font.woff2>" in result["link"]


class _FakeUpstream:
    """Stand-in for httpx's streaming response in the async proxy path."""

    def __init__(
        self, status_code: int, headers: dict[str, str], content: bytes
    ) -> None:
        self.status_code = status_code
        self.headers = httpx.Headers(headers)
        self._content = content
        self.close_count = 0

    async def aread(self) -> bytes:
        return self._content

    async def aclose(self) -> None:
        self.close_count += 1

    async def aiter_bytes(self, **_kwargs: object) -> AsyncIterator[bytes]:
        for i in range(0, len(self._content), 4):
            yield self._content[i : i + 4]


class _FakeAsyncClient:
    """Captures the forwarded request headers and returns a canned upstream."""

    def __init__(
        self, upstream: _FakeUpstream, captured: dict[str, str] | None = None
    ) -> None:
        self._upstream = upstream
        self._captured = captured

    def build_request(
        self, method: str, url: str, headers: dict[str, str]
    ) -> SimpleNamespace:
        if self._captured is not None:
            self._captured.update(headers)
        return SimpleNamespace(method=method, url=url, headers=headers)

    async def send(self, _request: object, **_kwargs: object) -> _FakeUpstream:
        return self._upstream


async def _fake_sandbox_url(_session_id: UUID) -> str:
    return "http://sandbox"


class _FakeACM:
    """No-op async context manager standing in for an async DB session."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> bool:
        return False


class TestProxyRequestWiring:
    @pytest.mark.asyncio
    async def test_proxy_request_rewrites_link_header_on_html_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream = _FakeUpstream(
            200,
            {
                "content-type": "text/html; charset=utf-8",
                "link": '</_next/static/media/font.woff2>; rel=preload; as="font"',
            },
            b"<html><head></head><body>ok</body></html>",
        )
        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(
            api, "_get_proxy_client", lambda: _FakeAsyncClient(upstream)
        )

        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        response = await api._proxy_request("", request, UUID(SESSION_ID))

        assert response.headers["link"] == (
            f'<{BASE}/_next/static/media/font.woff2>; rel=preload; as="font"'
        )

    @pytest.mark.asyncio
    async def test_proxy_request_injects_hmr_fixer_for_html_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream = _FakeUpstream(
            200,
            {"content-type": "text/html; charset=utf-8"},
            b"<html><head><title>x</title></head><body></body></html>",
        )
        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(
            api, "_get_proxy_client", lambda: _FakeAsyncClient(upstream)
        )

        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        response = await api._proxy_request("", request, UUID(SESSION_ID))
        body = cast(bytes, response.body).decode("utf-8")

        assert "window.WebSocket = function (url, protocols)" in body
        assert body.index("window.WebSocket = function (url, protocols)") < body.index(
            "<title>x</title>"
        )

    @pytest.mark.asyncio
    async def test_proxy_request_strips_sensitive_viewer_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Credential, CSRF, and forwarded-identity headers must not reach the sandbox."""
        upstream = _FakeUpstream(200, {"content-type": "text/plain"}, b"ok")
        forwarded_headers: dict[str, str] = {}

        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(
            api,
            "_get_proxy_client",
            lambda: _FakeAsyncClient(upstream, forwarded_headers),
        )

        # Security spec: every header here must never reach the sandbox,
        # regardless of how EXCLUDED_REQUEST_HEADERS evolves. Removing a key
        # from the deny-list while leaving it here surfaces as a leak below.
        # Mixed-case keys exercise the case-insensitive comparator.
        sensitive_headers = {
            "host": "app.onyx.local",
            "content-length": "7",
            "Connection": "keep-alive",
            "Keep-Alive": "timeout=5",
            "Proxy-Authenticate": "Basic",
            "Proxy-Authorization": "Basic victim-proxy-token",
            "TE": "trailers",
            "Trailer": "Expires",
            "Transfer-Encoding": "chunked",
            "Upgrade": "websocket",
            "Cookie": "fastapiusersauth=victim-session",
            "Authorization": "Bearer victim-token",
            "X-Api-Key": "victim-api-key",
            "X-Auth-Token": "victim-auth-token",
            "X-CSRF-Token": "csrf-token",
            "X-XSRF-Token": "xsrf-token",
            "Forwarded": "for=203.0.113.10;proto=https",
            "X-Forwarded-For": "203.0.113.10",
            "X-Forwarded-Host": "evil.example.com",
            "X-Forwarded-Port": "443",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Server": "evil.example.com",
            "X-Real-IP": "203.0.113.10",
            "X-Client-IP": "203.0.113.10",
            "CF-Connecting-IP": "203.0.113.10",
            "True-Client-IP": "203.0.113.10",
            "X-Forwarded-User": "victim@example.com",
            "X-Forwarded-Email": "victim@example.com",
            "X-Forwarded-Preferred-Username": "victim",
            # x-onyx-* prefix matcher (not literal deny-list entries).
            "X-Onyx-Authorization": "Bearer alt-victim-token",
            "X-Onyx-Tenant-ID": "victim-tenant",
            "X-Onyx-Request-ID": "abc-123",
            "X-Onyx-Future-Header": "should-be-stripped-by-prefix",
        }

        # Completeness check: every literal deny-list entry is covered above.
        # If a new entry is added to EXCLUDED_REQUEST_HEADERS without also
        # being added here, this assertion fails and forces the test to grow.
        covered = {key.lower() for key in sensitive_headers}
        assert api.EXCLUDED_REQUEST_HEADERS <= covered, (
            f"Deny-list entries missing from test input: "
            f"{api.EXCLUDED_REQUEST_HEADERS - covered}"
        )

        benign_headers = {"accept": "text/plain", "user-agent": "pytest"}
        request = cast(
            Request,
            SimpleNamespace(
                headers={**sensitive_headers, **benign_headers},
                query_params="",
            ),
        )

        await api._proxy_request("", request, UUID(SESSION_ID))

        lower = {key.lower(): value for key, value in forwarded_headers.items()}
        # Exact match: no sensitive header survives, no extra header leaks
        # through. If a new sensitive header is added to the request without a
        # corresponding deny-list entry, this assertion will catch it.
        assert lower == benign_headers

    def test_rewrites_absolute_link_header_font_preload_paths(self) -> None:
        headers = {
            "link": (
                '<https://craft-dev.onyx.app/_next/static/media/font.woff2>; rel=preload; as="font"; crossorigin'
            )
        }

        result = _rewrite_proxy_response_headers(headers, SESSION_ID)

        assert f"<{BASE}/_next/static/media/font.woff2>" in result["link"]

    @pytest.mark.asyncio
    async def test_proxy_sets_immutable_cache_control_on_next_static_media(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Content-hashed /_next/static/media/* assets (fonts, images) get a long
        immutable cache, overriding the dev server's no-store so the browser skips
        re-proxying on reload."""
        upstream = _FakeUpstream(
            200,
            {
                "content-type": "font/woff2",
                "cache-control": "no-store, must-revalidate",
                "pragma": "no-cache",
            },
            b"\x00\x01font",
        )
        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(
            api, "_get_proxy_client", lambda: _FakeAsyncClient(upstream)
        )
        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        response = await api._proxy_request(
            "_next/static/media/font.woff2", request, UUID(SESSION_ID)
        )

        assert (
            response.headers["cache-control"] == "public, max-age=31536000, immutable"
        )
        assert "pragma" not in response.headers

    @pytest.mark.asyncio
    async def test_proxy_preserves_no_cache_on_next_static_chunks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dev chunk/CSS URLs are path-stable but content-volatile, so the dev server
        marks them no-cache. The proxy must NOT override that to immutable — doing so
        serves stale code after an edit + full reload (Turbopack dev does not
        content-hash chunk filenames)."""
        upstream = _FakeUpstream(
            200,
            {
                "content-type": "application/javascript",
                "cache-control": "no-cache, must-revalidate",
            },
            b"console.log(1)",
        )
        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(
            api, "_get_proxy_client", lambda: _FakeAsyncClient(upstream)
        )
        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        response = await api._proxy_request(
            "_next/static/chunks/main.js", request, UUID(SESSION_ID)
        )

        assert response.headers["cache-control"] == "no-cache, must-revalidate"
        assert "immutable" not in response.headers["cache-control"]

    @pytest.mark.asyncio
    async def test_proxy_rewrites_js_asset_paths(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JS bundles are rewritten; idempotent for new sandboxes (assetPrefix),
        and corrects bare /_next/ refs for sandboxes started before this deploy."""
        js = b'import x from "/_next/static/chunks/dep.js"'
        upstream = _FakeUpstream(200, {"content-type": "application/javascript"}, js)
        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(
            api, "_get_proxy_client", lambda: _FakeAsyncClient(upstream)
        )
        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        response = await api._proxy_request(
            "_next/static/chunks/x.js", request, UUID(SESSION_ID)
        )

        body = cast(bytes, response.body).decode()
        assert f'"/{BASE.lstrip("/")}/_next/static/chunks/dep.js"' in body

    @pytest.mark.asyncio
    async def test_proxy_streams_binary_assets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-rewritable assets stream straight through, byte-for-byte."""
        body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        upstream = _FakeUpstream(200, {"content-type": "image/png"}, body)
        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(
            api, "_get_proxy_client", lambda: _FakeAsyncClient(upstream)
        )
        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        response = await api._proxy_request("logo.png", request, UUID(SESSION_ID))

        assert isinstance(response, StreamingResponse)
        chunks = [chunk async for chunk in response.body_iterator]
        assert b"".join(cast(list[bytes], chunks)) == body
        assert upstream.close_count == 1  # released after full drain

    @pytest.mark.asyncio
    async def test_streaming_closes_upstream_on_early_disconnect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the client disconnects mid-stream, the pooled connection is still
        released (the generator's finally runs on GeneratorExit)."""
        upstream = _FakeUpstream(200, {"content-type": "image/png"}, b"abcdefghijkl")
        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(
            api, "_get_proxy_client", lambda: _FakeAsyncClient(upstream)
        )
        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        response = await api._proxy_request("logo.png", request, UUID(SESSION_ID))
        assert isinstance(response, StreamingResponse)

        body_iter = cast(AsyncGenerator[bytes, None], response.body_iterator)
        first = await body_iter.__anext__()
        assert first == b"abcd"
        await body_iter.aclose()

        assert upstream.close_count >= 1

    @pytest.mark.asyncio
    async def test_buffered_response_closes_upstream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The buffer-and-rewrite branch releases the upstream after reading."""
        upstream = _FakeUpstream(
            200, {"content-type": "text/html"}, b"<html><head></head></html>"
        )
        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(
            api, "_get_proxy_client", lambda: _FakeAsyncClient(upstream)
        )
        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        await api._proxy_request("", request, UUID(SESSION_ID))

        assert upstream.close_count == 1


class _FakeCacheBackend:
    """In-memory stand-in for the Redis-backed CacheBackend (get/set/delete)."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    def set(self, key: str, value: str | bytes, **_kwargs: object) -> None:
        self._store[key] = value.encode() if isinstance(value, str) else value

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


class TestWebappAccessCache:
    @pytest.mark.asyncio
    async def test_grant_is_cached_skipping_db_on_repeat(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A granted (session, viewer) pair skips the DB on subsequent assets."""
        viewer = SimpleNamespace(id=UUID("11111111-1111-1111-1111-111111111111"))
        calls = {"n": 0}

        async def fake_access(
            _db: object, _sid: UUID
        ) -> tuple[SharingScope, UUID] | None:
            calls["n"] += 1
            # Owner == viewer, so a PRIVATE session is granted.
            return (SharingScope.PRIVATE, viewer.id)

        monkeypatch.setattr(api, "get_webapp_access_async", fake_access)
        monkeypatch.setattr(
            api, "get_async_session_context_manager", lambda: _FakeACM()
        )

        # Shared backend across both calls so the grant persists like Redis would.
        shared = _FakeCacheBackend()
        monkeypatch.setattr(api, "get_cache_backend", lambda: shared)

        await api._check_webapp_access(UUID(SESSION_ID), cast(api.User, viewer))
        await api._check_webapp_access(UUID(SESSION_ID), cast(api.User, viewer))

        assert calls["n"] == 1  # second call served from cache

    @pytest.mark.asyncio
    async def test_private_session_denies_non_owner_and_is_not_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-owner gets 404 on a private session, and the denial is re-queried
        (denials are never cached, so re-sharing takes effect immediately)."""
        shared = _FakeCacheBackend()
        monkeypatch.setattr(api, "get_cache_backend", lambda: shared)
        owner_id = UUID("22222222-2222-2222-2222-222222222222")
        viewer = SimpleNamespace(id=UUID("33333333-3333-3333-3333-333333333333"))
        calls = {"n": 0}

        async def fake_access(
            _db: object, _sid: UUID
        ) -> tuple[SharingScope, UUID] | None:
            calls["n"] += 1
            return (SharingScope.PRIVATE, owner_id)

        monkeypatch.setattr(api, "get_webapp_access_async", fake_access)
        monkeypatch.setattr(
            api, "get_async_session_context_manager", lambda: _FakeACM()
        )

        for _ in range(2):
            with pytest.raises(HTTPException) as exc:
                await api._check_webapp_access(UUID(SESSION_ID), cast(api.User, viewer))
            assert exc.value.status_code == 404

        assert calls["n"] == 2  # denial hit the DB both times
