import json
import subprocess
from pathlib import Path

import pytest

CONFIG: Path = Path(__file__).resolve().parents[2] / "web/next.config.js"
SCRIPT: str = """
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const sandbox = {
  module: {exports: {}},
  process: {env: JSON.parse(process.argv[3])},
  __dirname: path.dirname(process.argv[1]),
  require(name) {
    if (name === '@sentry/nextjs') return {withSentryConfig: config => config};
    if (name === 'next/constants') return {PHASE_DEVELOPMENT_SERVER: 'phase-development-server'};
    if (name === 'next-intl/plugin') return () => config => config;
    throw new Error(`Unexpected config dependency: ${name}`);
  }
};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), sandbox);
const config = sandbox.module.exports(process.argv[2]);
config.rewrites().then(routes => process.stdout.write(JSON.stringify(routes)));
"""


@pytest.mark.parametrize(
    "phase",
    ["phase-development-server", "phase-production-build", "phase-production-server"],
)
@pytest.mark.parametrize("override_upstreams", [False, True])
def test_oauth_discovery_rewrites_exist_only_in_next_dev(
    phase: str, override_upstreams: bool
) -> None:
    environment: dict[str, str] = (
        {
            "INTERNAL_URL": "http://api.internal:8080",
            "MCP_INTERNAL_URL": "http://mcp.internal:8090",
        }
        if override_upstreams
        else {}
    )
    routes: list[dict[str, str]] = json.loads(
        subprocess.check_output(
            ["node", "-e", SCRIPT, str(CONFIG), phase, json.dumps(environment)],
            text=True,
            timeout=15,
        )
    )
    discovery: dict[str, str] = {
        route["source"]: route["destination"]
        for route in routes
        if route["source"].startswith("/.well-known/")
    }
    assert any(route["source"] == "/api/docs" for route in routes)
    if phase == "phase-development-server":
        assert discovery == {
            "/.well-known/oauth-authorization-server/:path*": (
                environment.get("INTERNAL_URL", "http://localhost:8080")
                + "/oauth-provider/metadata"
            ),
            "/.well-known/oauth-protected-resource/:path*": (
                environment.get("MCP_INTERNAL_URL", "http://127.0.0.1:8090")
                + "/.well-known/oauth-protected-resource/:path*"
            ),
        }
    else:
        assert discovery == {}
