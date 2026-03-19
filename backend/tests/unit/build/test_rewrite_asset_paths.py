"""Unit tests for webapp proxy path rewriting/injection."""

from types import SimpleNamespace
from typing import cast
from typing import Literal
from uuid import UUID

import httpx
import pytest
from fastapi import Request
from sqlalchemy.orm import Session

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


class TestProxyRequestWiring:
    def test_proxy_request_rewrites_link_header_on_html_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        html = b"<html><head></head><body>ok</body></html>"
        upstream = httpx.Response(
            200,
            headers={
                "content-type": "text/html; charset=utf-8",
                "link": '</_next/static/media/font.woff2>; rel=preload; as="font"',
            },
            content=html,
        )

        monkeypatch.setattr(api, "_get_sandbox_url", lambda *_args: "http://sandbox")

        class FakeClient:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def __enter__(self) -> "FakeClient":
                return self

            def __exit__(self, *_args: object) -> Literal[False]:
                return False

            def get(self, _url: str, headers: dict[str, str]) -> httpx.Response:
                assert "host" not in {key.lower() for key in headers}
                return upstream

        monkeypatch.setattr(api.httpx, "Client", FakeClient)

        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        response = api._proxy_request(
            "", request, UUID(SESSION_ID), cast(Session, SimpleNamespace())
        )

        assert response.headers["link"] == (
            f'<{BASE}/_next/static/media/font.woff2>; rel=preload; as="font"'
        )

    def test_proxy_request_injects_hmr_fixer_for_html_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        upstream = httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><head><title>x</title></head><body></body></html>",
        )

        monkeypatch.setattr(api, "_get_sandbox_url", lambda *_args: "http://sandbox")

        class FakeClient:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                pass

            def __enter__(self) -> "FakeClient":
                return self

            def __exit__(self, *_args: object) -> Literal[False]:
                return False

            def get(self, _url: str, headers: dict[str, str]) -> httpx.Response:
                assert "host" not in {key.lower() for key in headers}
                return upstream

        monkeypatch.setattr(api.httpx, "Client", FakeClient)

        request = cast(Request, SimpleNamespace(headers={}, query_params=""))

        response = api._proxy_request(
            "", request, UUID(SESSION_ID), cast(Session, SimpleNamespace())
        )
        body = cast(bytes, response.body).decode("utf-8")

        assert "window.WebSocket = function (url, protocols)" in body
        assert body.index("window.WebSocket = function (url, protocols)") < body.index(
            "<title>x</title>"
        )

    def test_rewrites_absolute_link_header_font_preload_paths(self) -> None:
        headers = {
            "link": (
                '<https://craft-dev.onyx.app/_next/static/media/font.woff2>; rel=preload; as="font"; crossorigin'
            )
        }

        result = _rewrite_proxy_response_headers(headers, SESSION_ID)

        assert f"<{BASE}/_next/static/media/font.woff2>" in result["link"]
