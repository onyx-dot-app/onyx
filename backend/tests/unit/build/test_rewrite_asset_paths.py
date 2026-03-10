"""Unit tests for _rewrite_asset_paths in the webapp proxy."""

from onyx.server.features.build.api.api import _rewrite_asset_paths

SESSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
BASE = f"/api/build/sessions/{SESSION_ID}/webapp"


def rewrite(html: str) -> str:
    return _rewrite_asset_paths(html.encode(), SESSION_ID).decode()


class TestNextjsPathRewriting:
    def test_rewrites_bare_next_script_src(self):
        html = '<script src="/_next/static/chunks/main.js">'
        result = rewrite(html)
        assert f'src="{BASE}/_next/static/chunks/main.js"' in result
        assert '"/_next/' not in result

    def test_rewrites_bare_next_in_single_quotes(self):
        html = "<link href='/_next/static/css/app.css'>"
        result = rewrite(html)
        assert f"'{BASE}/_next/static/css/app.css'" in result

    def test_rewrites_bare_next_in_url_parens(self):
        html = "background: url(/_next/static/media/font.woff2)"
        result = rewrite(html)
        assert f"url({BASE}/_next/static/media/font.woff2)" in result

    def test_no_double_prefix_when_already_proxied(self):
        """assetPrefix makes Next.js emit already-prefixed URLs — must not double-rewrite."""
        already_prefixed = f'<script src="{BASE}/_next/static/chunks/main.js">'
        result = rewrite(already_prefixed)
        # Should be unchanged
        assert result == already_prefixed
        # Specifically, no double path
        assert f"{BASE}/{BASE}" not in result

    def test_rewrites_favicon(self):
        html = '<link rel="icon" href="/favicon.ico">'
        result = rewrite(html)
        assert f'"{BASE}/favicon.ico"' in result

    def test_rewrites_json_data_path_double_quoted(self):
        html = 'fetch("/data/tickets.json")'
        result = rewrite(html)
        assert f'"{BASE}/data/tickets.json"' in result

    def test_rewrites_json_data_path_single_quoted(self):
        html = "fetch('/data/items.json')"
        result = rewrite(html)
        assert f"'{BASE}/data/items.json'" in result
