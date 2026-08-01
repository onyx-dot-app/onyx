"""Next.js dev server start script and readiness probe behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

from onyx.server.features.build.sandbox import nextjs_dev
from onyx.server.features.build.sandbox.nextjs_dev import build_nextjs_start_script
from onyx.server.features.build.session.manager import SessionManager

_SESSION_PATH = "/workspace/sessions/0d9ed7f2-8757-4d09-9812-bd7e4a45e232"

_TEMPLATE_NEXT_CONFIG = (
    Path(nextjs_dev.__file__).parent
    / "image"
    / "templates"
    / "outputs"
    / "web"
    / "next.config.ts"
)


def test_start_script_exports_allowed_dev_origins() -> None:
    with patch.object(nextjs_dev, "WEB_DOMAIN", "https://cloud.onyx.app"):
        script = build_nextjs_start_script(_SESSION_PATH, 3010)

    assert 'export ONYX_WEBAPP_ALLOWED_DEV_ORIGINS="cloud.onyx.app"' in script
    assert (
        'export ONYX_WEBAPP_BASE_PATH="/api/build/sessions/'
        f'$(basename {_SESSION_PATH})/webapp"' in script
    )
    assert "-p 3010" in script


def test_start_script_allowed_dev_origins_is_hostname_only() -> None:
    # Next 16 allowedDevOrigins entries are hostnames — no scheme, no port.
    with patch.object(nextjs_dev, "WEB_DOMAIN", "http://localhost:3000"):
        script = build_nextjs_start_script(_SESSION_PATH, 3010)

    assert 'export ONYX_WEBAPP_ALLOWED_DEV_ORIGINS="localhost"' in script


def test_start_script_config_rewrite_matches_scaffold_template() -> None:
    """The legacy next.config.ts rewrite must produce the current template."""
    script = build_nextjs_start_script(_SESSION_PATH, 3010)
    assert _TEMPLATE_NEXT_CONFIG.read_text().strip() in script


def test_nextjs_ready_probe_targets_base_path_dev_asset() -> None:
    """Probing bare "/" renders a spurious 404 page per poll, and probing the
    app page reports not-ready when generated app code 500s — the probe must
    hit a basePath-scoped /_next/static path and accept any response."""
    session_id = UUID("0d9ed7f2-8757-4d09-9812-bd7e4a45e232")
    sandbox_id = UUID("11111111-2222-3333-4444-555555555555")

    sandbox_manager = MagicMock()
    sandbox_manager.get_webapp_url.return_value = "http://sandbox-x:3010"

    response = MagicMock()
    response.status_code = 500
    http_client = MagicMock()
    http_client.__enter__.return_value = http_client
    http_client.get.return_value = response

    with (
        patch(
            "onyx.server.features.build.session.manager.get_sandbox_manager",
            return_value=sandbox_manager,
        ),
        patch(
            "onyx.server.features.build.session.manager.httpx.Client",
            return_value=http_client,
        ),
    ):
        manager = SessionManager(MagicMock())
        ready = manager._check_nextjs_ready(sandbox_id, session_id, 3010)

    assert ready is True
    http_client.get.assert_called_once_with(
        f"http://sandbox-x:3010/api/build/sessions/{session_id}/webapp"
        "/_next/static/onyx-ready-probe.js"
    )
