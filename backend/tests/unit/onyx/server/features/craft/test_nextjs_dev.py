"""Next.js dev server start script and readiness probe behavior."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

from onyx.server.features.build.sandbox import nextjs_dev
from onyx.server.features.build.sandbox.nextjs_dev import (
    WEBAPP_ABSENT_SENTINEL,
    WEBAPP_AUTOSTART_SENTINEL,
    build_nextjs_start_script,
    build_webapp_bootstrap_script,
    build_webapp_restore_script,
    build_webapp_script_write_snippet,
)
from onyx.server.features.build.sandbox.session_workspace import (
    build_session_workspace_setup_script,
)
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
_TEMPLATE_PACKAGE_JSON = (
    Path(nextjs_dev.__file__).parent
    / "image"
    / "templates"
    / "outputs"
    / "web"
    / "package.json"
)
_TEMPLATE_AGENTS_MD = _TEMPLATE_PACKAGE_JSON.parent / "AGENTS.md"


def test_start_script_exports_allowed_dev_origins() -> None:
    with patch.object(nextjs_dev, "WEB_DOMAIN", "https://cloud.onyx.app"):
        script = build_nextjs_start_script(_SESSION_PATH, 3010)

    assert 'export ONYX_WEBAPP_ALLOWED_DEV_ORIGINS="cloud.onyx.app"' in script
    assert (
        'export ONYX_WEBAPP_BASE_PATH="/api/build/sessions/'
        f'$(basename {_SESSION_PATH})/webapp"' in script
    )


def test_start_script_port_is_env_driven_not_a_dup_flag() -> None:
    """A `-p` flag would collide with the template `dev` script's own `-p`;
    the port must flow via ONYX_WEBAPP_PORT."""
    script = build_nextjs_start_script(_SESSION_PATH, 3010)

    assert "export ONYX_WEBAPP_PORT=3010" in script
    assert "bun run dev -- -H 0.0.0.0 $PORT_FLAG >" in script


def test_start_script_writes_naive_path_port_file() -> None:
    """A hand-started `bun run dev` reads this file, so the preview proxy still
    finds the server on the port it routes to."""
    script = build_nextjs_start_script(_SESSION_PATH, 3010)

    assert f"echo 3010 > {_SESSION_PATH}/.nextjs-port" in script


def test_template_dev_script_wires_port_to_managed_env_and_port_file() -> None:
    """The template `dev` script is the port contract's consumer side: the
    managed launch flows the port via ONYX_WEBAPP_PORT, and a hand-started
    `bun run dev` falls back to the `.nextjs-port` file the start script writes
    (`../../` from the web dir is the session root)."""
    dev_script = json.loads(_TEMPLATE_PACKAGE_JSON.read_text())["scripts"]["dev"]

    assert dev_script.startswith("next dev -p ")
    assert (
        "${ONYX_WEBAPP_PORT:-$(cat ../../.nextjs-port 2>/dev/null || echo 3000)}"
        in dev_script
    )

    web_dir = Path(_SESSION_PATH) / "outputs" / "web"
    assert (web_dir / "../../.nextjs-port").resolve() == Path(
        _SESSION_PATH
    ) / ".nextjs-port"


def test_template_agents_md_documents_only_real_scripts() -> None:
    """The template AGENTS.md and package.json are the two halves of the
    sandbox tool contract. A documented `bun run <script>` that doesn't exist
    sends agents into guess-and-fail loops (the doc once said "Run ESLint"
    while the template shipped oxlint and no typecheck script)."""
    scripts = set(json.loads(_TEMPLATE_PACKAGE_JSON.read_text())["scripts"])
    documented = set(
        re.findall(r"bun run ([A-Za-z0-9:_-]+)", _TEMPLATE_AGENTS_MD.read_text())
    )

    assert documented <= scripts
    # The verify workflow's commands must stay documented, not just valid.
    assert {"dev", "lint", "typecheck"} <= documented


def test_start_script_passes_port_flag_when_dev_script_ignores_env() -> None:
    """A `dev` script without the ONYX_WEBAPP_PORT marker (legacy scaffold, or
    rewritten by the agent) ignores the env var and would bind 3000; the
    managed launch must pass -p explicitly for those."""
    script = build_nextjs_start_script(_SESSION_PATH, 3010)

    assert 'if ! grep -q "ONYX_WEBAPP_PORT" package.json 2>/dev/null; then' in script
    assert 'PORT_FLAG="-p 3010"' in script


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


def _assert_valid_bash(script: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sh") as f:
        f.write(script)
        f.flush()
        result = subprocess.run(["bash", "-n", f.name], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_bootstrap_script_is_valid_bash() -> None:
    script = build_webapp_bootstrap_script(_SESSION_PATH, 3010)
    _assert_valid_bash(script)


def test_bootstrap_script_embeds_port_write_and_env_exports() -> None:
    script = build_webapp_bootstrap_script(_SESSION_PATH, 3010)

    assert f"echo 3010 > {_SESSION_PATH}/.nextjs-port" in script
    assert "export ONYX_WEBAPP_PORT=3010" in script
    assert (
        'export ONYX_WEBAPP_BASE_PATH="/api/build/sessions/'
        f'$(basename {_SESSION_PATH})/webapp"' in script
    )


def test_bootstrap_script_reuses_live_server_via_embedded_guard() -> None:
    script = build_webapp_bootstrap_script(_SESSION_PATH, 3010)

    assert 'kill -0 "$NEXTJS_PID" 2>/dev/null' in script
    assert (
        f'[ "$(readlink /proc/$NEXTJS_PID/cwd 2>/dev/null)" '
        f'= "{_SESSION_PATH}/outputs/web" ]' in script
    )
    assert "already running" in script
    # Exactly one liveness guard: the embedded start script's.
    assert script.count("kill -0") == 1


def test_setup_script_writes_start_webapp_script_and_chmod_444() -> None:
    script = build_session_workspace_setup_script(
        session_path=_SESSION_PATH,
        agents_md="# Agent",
        session_opencode_config_json='{"model": "x"}',
        nextjs_port=3010,
    )

    assert f"> {_SESSION_PATH}/start-webapp.sh" in script
    assert f"chmod 444 {_SESSION_PATH}/start-webapp.sh" in script
    # No eager scaffold/install at setup time: the old eager invocations (bare
    # session path, unquoted) are gone. What's left mentioning bun/outputs is
    # inert text inside the printf'd start-webapp.sh payload, which addresses
    # the session dir via the $SESSION_PATH shell variable instead.
    assert f"cd {_SESSION_PATH}/outputs/web &&" not in script
    assert (
        f"cp -r /workspace/templates/outputs/* {_SESSION_PATH}/outputs/" not in script
    )


def test_setup_script_headless_writes_no_start_webapp_script() -> None:
    script = build_session_workspace_setup_script(
        session_path=_SESSION_PATH,
        agents_md="# Agent",
        session_opencode_config_json='{"model": "x"}',
        nextjs_port=None,
    )

    assert "start-webapp.sh" not in script
    assert "chmod 444" not in script


def test_setup_script_is_valid_bash() -> None:
    script = build_session_workspace_setup_script(
        session_path=_SESSION_PATH,
        agents_md="# Agent",
        session_opencode_config_json='{"model": "x"}',
        nextjs_port=3010,
    )
    _assert_valid_bash(script)


def test_webapp_script_write_snippet_removes_before_writing() -> None:
    snippet = build_webapp_script_write_snippet(_SESSION_PATH, 3010)

    assert f"rm -f {_SESSION_PATH}/start-webapp.sh" in snippet
    assert f"chmod 444 {_SESSION_PATH}/start-webapp.sh" in snippet
    remove_index = snippet.index("rm -f")
    write_index = snippet.index("printf")
    assert remove_index < write_index


def test_restore_script_rewrites_scripts_before_gated_autostart() -> None:
    script = build_webapp_restore_script(_SESSION_PATH, 3010)

    # Script rewrite (with the new port) must come before the auto-start gate.
    assert build_webapp_script_write_snippet(_SESSION_PATH, 3010) in script
    gate = f"[ -f {_SESSION_PATH}/outputs/web/package.json ]"
    assert gate in script
    assert script.index("printf") < script.index(gate)

    # The auto-start must exec the tamper-hardened canonical copy, gated on
    # the webapp actually existing in the restored snapshot, and backgrounded.
    autostart = f"nohup bash {_SESSION_PATH}/start-webapp.sh"
    assert autostart in script
    assert script.index(gate) < script.index(autostart)
    assert f"> {_SESSION_PATH}/webapp-bootstrap.log 2>&1 &" in script

    # Exactly one sentinel per branch; k8s restore relies on them for success.
    assert WEBAPP_AUTOSTART_SENTINEL in script
    assert WEBAPP_ABSENT_SENTINEL in script


def test_restore_script_is_valid_bash() -> None:
    _assert_valid_bash(build_webapp_restore_script(_SESSION_PATH, 3010))
