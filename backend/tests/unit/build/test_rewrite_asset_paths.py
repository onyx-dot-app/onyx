"""Unit tests for the Craft webapp proxy."""

import re
from collections.abc import AsyncGenerator
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from fastapi import Request
from starlette.responses import StreamingResponse

from onyx.db.enums import SharingScope
from onyx.server.features.build import webapp_proxy as api

SESSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
BASE = f"/api/build/sessions/{SESSION_ID}/webapp"
NEXT_TEMPLATE_CONFIG = (
    Path(api.__file__).resolve().parents[0]
    / "sandbox/image/templates/outputs/web/next.config.ts"
)
DOCKER_SANDBOX_MANAGER = (
    Path(api.__file__).resolve().parents[0] / "sandbox/docker/docker_sandbox_manager.py"
)
KUBERNETES_SANDBOX_MANAGER = (
    Path(api.__file__).resolve().parents[0]
    / "sandbox/kubernetes/kubernetes_sandbox_manager.py"
)
WEB_NEXT_CONFIG = Path(__file__).resolve().parents[4] / "web/next.config.js"


class TestNextjsProxyMountContract:
    def test_webapp_prefix_is_used_as_next_base_path(self) -> None:
        """A proxied App Router app needs basePath, not just assetPrefix.

        Rewriting /_next/static URLs makes chunks load, but it does not update
        Next's client-side mount/base-path contract. Without basePath, Craft
        previews can SSR successfully through /api/build/.../webapp while the
        client runtime never hydrates.
        """
        config_source = NEXT_TEMPLATE_CONFIG.read_text()

        assert "ONYX_WEBAPP_BASE_PATH" in config_source
        assert "assetPrefix" in config_source
        assert re.search(r"\bbasePath\s*[:=]", config_source)

    def test_sandbox_start_scripts_export_next_base_path(self) -> None:
        for manager_source in (DOCKER_SANDBOX_MANAGER, KUBERNETES_SANDBOX_MANAGER):
            source = manager_source.read_text()

            assert (
                'export ONYX_WEBAPP_BASE_PATH="/api/build/sessions/$(basename '
                '{session_path})/webapp"'
            ) in source
            assert "export WEBAPP_ASSET_PREFIX" not in source
            assert 'grep -q "WEBAPP_ASSET_PREFIX" next.config.ts' in source
            assert (
                "? {{ basePath: webappBasePath, assetPrefix: webappBasePath }}"
                in source
            )

    def test_web_dev_rewrites_hmr_websocket_to_backend(self) -> None:
        """Local Next dev cannot proxy websocket upgrades via /api/[...path]."""
        source = WEB_NEXT_CONFIG.read_text()

        assert "/api/build/sessions/:sessionId/webapp/_next/webpack-hmr" in source
        assert "/build/sessions/:sessionId/webapp/_next/webpack-hmr" in source


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
        self.last_url: str | None = None

    def build_request(
        self, method: str, url: str, headers: dict[str, str]
    ) -> SimpleNamespace:
        self.last_url = url
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
    async def test_proxy_request_targets_native_nextjs_base_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream = _FakeUpstream(200, {"content-type": "text/html"}, b"ok")
        fake_client = _FakeAsyncClient(upstream)
        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(api, "_get_proxy_client", lambda: fake_client)

        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        await api._proxy_request("", request, UUID(SESSION_ID))

        assert fake_client.last_url == f"http://sandbox/{BASE.lstrip('/')}"

    @pytest.mark.asyncio
    async def test_proxy_request_preserves_link_header_on_html_response(
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
            '</_next/static/media/font.woff2>; rel=preload; as="font"'
        )

    @pytest.mark.asyncio
    async def test_proxy_request_streams_html_without_injecting_hmr_script(
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
        assert isinstance(response, StreamingResponse)
        chunks = [chunk async for chunk in response.body_iterator]
        body = b"".join(cast(list[bytes], chunks)).decode("utf-8")

        assert body == "<html><head><title>x</title></head><body></body></html>"
        assert "window.WebSocket = function (url, protocols)" not in body

    def test_hmr_websocket_url_targets_native_nextjs_base_path(self) -> None:
        target = api._webapp_hmr_websocket_url(
            UUID(SESSION_ID), "http://sandbox:3014", "id=req-1"
        )

        assert target == (
            f"ws://sandbox:3014/{BASE.lstrip('/')}/_next/webpack-hmr?id=req-1"
        )

    def test_hmr_websocket_url_strips_non_hmr_query_params(self) -> None:
        target = api._webapp_hmr_websocket_url(
            UUID(SESSION_ID),
            "http://sandbox:3014",
            "id=req-1&token=secret&authorization=bearer",
        )

        assert target == (
            f"ws://sandbox:3014/{BASE.lstrip('/')}/_next/webpack-hmr?id=req-1"
        )

    @pytest.mark.asyncio
    async def test_hmr_websocket_proxy_does_not_forward_viewer_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        class FakeWebSocket:
            url = SimpleNamespace(query="id=req-1&token=secret")
            accepted = False

            async def accept(self) -> None:
                self.accepted = True

        class FakeConnect:
            def __init__(self, uri: str, **kwargs: object) -> None:
                captured["uri"] = uri
                captured["kwargs"] = kwargs

            async def __aenter__(self) -> object:
                return object()

            async def __aexit__(self, *_args: object) -> bool:
                return False

        async def noop_pump(*_args: object) -> None:
            return None

        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(api, "websocket_connect", FakeConnect)
        monkeypatch.setattr(api, "_pump_webapp_to_upstream", noop_pump)
        monkeypatch.setattr(api, "_pump_upstream_to_webapp", noop_pump)

        websocket = FakeWebSocket()
        await api._proxy_webapp_hmr_websocket(
            UUID(SESSION_ID), cast(api.WebSocket, websocket)
        )

        assert websocket.accepted
        assert captured["uri"] == (
            f"ws://sandbox/{BASE.lstrip('/')}/_next/webpack-hmr?id=req-1"
        )
        assert captured["kwargs"] == {
            "additional_headers": None,
            "compression": None,
            "extensions": None,
            "origin": None,
            "proxy": None,
            "subprotocols": None,
            "user_agent_header": None,
        }

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
    async def test_proxy_streams_js_asset_paths_without_rewriting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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

        assert isinstance(response, StreamingResponse)
        chunks = [chunk async for chunk in response.body_iterator]
        assert b"".join(cast(list[bytes], chunks)) == js

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
    async def test_text_response_closes_upstream_after_stream_drain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream = _FakeUpstream(
            200, {"content-type": "text/html"}, b"<html><head></head></html>"
        )
        monkeypatch.setattr(api, "_get_sandbox_url", _fake_sandbox_url)
        monkeypatch.setattr(
            api, "_get_proxy_client", lambda: _FakeAsyncClient(upstream)
        )
        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        response = await api._proxy_request("", request, UUID(SESSION_ID))
        assert isinstance(response, StreamingResponse)
        chunks = [chunk async for chunk in response.body_iterator]

        assert b"".join(cast(list[bytes], chunks)) == b"<html><head></head></html>"
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
