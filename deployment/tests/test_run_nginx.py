import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
RUN_NGINX_SCRIPT: Path = REPO_ROOT / "deployment/data/nginx/run-nginx.sh"


@pytest.fixture
def mock_nginx_env(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mock_nginx = bin_dir / "nginx"
    mock_nginx.write_text(
        "#!/bin/sh\n"
        'if [ "$1" != "-g" ] || [ "$2" != "daemon off;" ]; then\n'
        '    echo "Invalid nginx arguments: $*" >&2\n'
        "    exit 1\n"
        "fi\n"
        'if grep -q "\\${CONF_DIR}" "$CONF_DIR/app.conf"; then\n'
        '    echo "ERROR: unexpanded \\${CONF_DIR} found in app.conf" >&2\n'
        "    exit 1\n"
        "fi\n"
        'echo "nginx validated configuration and started successfully"\n'
        "exit 0\n"
    )
    mock_nginx.chmod(0o755)

    conf_dir = tmp_path / "conf.d"
    conf_dir.mkdir()

    app_template = conf_dir / "app.conf.template"
    app_template.write_text(
        "upstream api { server ${ONYX_BACKEND_API_HOST}:8080; }\n"
        'include "${CONF_DIR}/mcp_upstream.conf.inc";\n'
        "server {\n"
        "    listen 80;\n"
        "    server_name ${DOMAIN};\n"
        '    include "${CONF_DIR}/mcp.conf.inc";\n'
        '    include "${CONF_DIR}/webhook.conf.inc";\n'
        "}\n"
    )

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "CONF_DIR": str(conf_dir),
        "DOMAIN": "localhost",
        "RUN_NGINX_DAEMON": "false",
    }
    return conf_dir, env


def test_run_nginx_mcp_enabled_with_templates(
    mock_nginx_env: tuple[Path, dict[str, str]],
) -> None:
    conf_dir, env = mock_nginx_env
    env["MCP_SERVER_ENABLED"] = "true"
    env["ONYX_MCP_SERVER_HOST"] = "custom_mcp_server"

    mcp_upstream = conf_dir / "mcp_upstream.conf.inc.template"
    mcp_upstream.write_text(
        "upstream mcp_server { server ${ONYX_MCP_SERVER_HOST}:8090; }\n"
    )

    mcp_conf = conf_dir / "mcp.conf.inc.template"
    mcp_conf.write_text(
        "location /mcp/ { proxy_pass http://${ONYX_MCP_SERVER_HOST}:8090; }\n"
    )

    webhook_conf = conf_dir / "webhook.conf.inc"
    webhook_conf.write_text(
        "location /webhook { proxy_pass http://webhook_server:8080; }\n"
    )

    result = subprocess.run(
        ["/bin/sh", str(RUN_NGINX_SCRIPT), "app.conf.template"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        timeout=10,
    )

    assert "MCP server is enabled, creating MCP configuration..." in result.stdout
    assert "nginx validated configuration and started successfully" in result.stdout
    assert (conf_dir / "mcp_upstream.conf.inc").is_file()
    assert (conf_dir / "mcp.conf.inc").is_file()
    assert (conf_dir / "webhook.conf.inc").is_file()

    app_content = (conf_dir / "app.conf").read_text()
    assert f'include "{conf_dir}/mcp_upstream.conf.inc";' in app_content
    assert "${CONF_DIR}" not in app_content

    upstream_content = (conf_dir / "mcp_upstream.conf.inc").read_text()
    assert "server custom_mcp_server:8090;" in upstream_content

    mcp_content = (conf_dir / "mcp.conf.inc").read_text()
    assert "proxy_pass http://custom_mcp_server:8090;" in mcp_content


def test_run_nginx_mcp_enabled_fallback_when_templates_missing(
    mock_nginx_env: tuple[Path, dict[str, str]],
) -> None:
    conf_dir, env = mock_nginx_env
    env["MCP_SERVER_ENABLED"] = "true"

    # Issue #17008: templates are missing in conf.d
    result = subprocess.run(
        ["/bin/sh", str(RUN_NGINX_SCRIPT), "app.conf.template"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        timeout=10,
    )

    assert "MCP configuration templates are missing" in result.stdout
    assert "nginx validated configuration and started successfully" in result.stdout
    assert (conf_dir / "mcp_upstream.conf.inc").is_file()
    assert (conf_dir / "mcp.conf.inc").is_file()
    assert (conf_dir / "webhook.conf.inc").is_file()

    upstream_content = (conf_dir / "mcp_upstream.conf.inc").read_text()
    assert "Empty file - MCP server templates not found" in upstream_content

    mcp_content = (conf_dir / "mcp.conf.inc").read_text()
    assert "Empty file - MCP server templates not found" in mcp_content

    webhook_content = (conf_dir / "webhook.conf.inc").read_text()
    assert "Empty file - webhook configuration not found" in webhook_content


def test_run_nginx_mcp_disabled(mock_nginx_env: tuple[Path, dict[str, str]]) -> None:
    conf_dir, env = mock_nginx_env
    env["MCP_SERVER_ENABLED"] = "false"

    result = subprocess.run(
        ["/bin/sh", str(RUN_NGINX_SCRIPT), "app.conf.template"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        timeout=10,
    )

    assert "MCP server is disabled, removing MCP configuration..." in result.stdout
    assert "nginx validated configuration and started successfully" in result.stdout
    assert (conf_dir / "mcp_upstream.conf.inc").is_file()
    assert (conf_dir / "mcp.conf.inc").is_file()

    upstream_content = (conf_dir / "mcp_upstream.conf.inc").read_text()
    assert "Empty file - MCP server is disabled" in upstream_content

    mcp_content = (conf_dir / "mcp.conf.inc").read_text()
    assert "Empty file - MCP server is disabled" in mcp_content
