"""The exported plugin zip carries the deployment's address and needs no install options."""

import io
import json
import stat
import zipfile
from pathlib import Path

from onyx.oauth_provider.models import OAuthProviderSettings
from onyx.server.features.onyx_plugin.export import (
    HOOKS_PATH,
    MANIFEST_PATH,
    MARKETPLACE_PATH,
    MCP_CONFIG_PATH,
    PLUGIN_DIR,
    TEST_SUFFIX,
    build_plugin_bundle,
)

assert PLUGIN_DIR is not None, "extensions/agent-plugin is missing from the checkout"
SOURCE_DIR: Path = PLUGIN_DIR

WEB_URL = "https://onyx.example.com"
SETTINGS = OAuthProviderSettings(
    issuer_url=f"{WEB_URL}/api/oauth-provider",
    mcp_resource_url=f"{WEB_URL}/mcp/",
    web_url=WEB_URL,
    web_origin=WEB_URL,
)


def _bundle() -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(build_plugin_bundle(SOURCE_DIR, SETTINGS)))


def test_bundle_holds_every_plugin_file_but_the_marketplace_and_tests() -> None:
    source = {
        path.relative_to(SOURCE_DIR).as_posix()
        for path in SOURCE_DIR.rglob("*")
        if path.is_file()
    }
    tests = {name for name in source if name.endswith(TEST_SUFFIX)}
    assert tests
    assert set(_bundle().namelist()) == source - {MARKETPLACE_PATH} - tests


def test_mcp_server_points_at_the_deployment_and_sends_no_token() -> None:
    server = json.loads(_bundle().read(MCP_CONFIG_PATH))["mcpServers"]["onyx"]
    source = json.loads((SOURCE_DIR / MCP_CONFIG_PATH).read_text())["mcpServers"][
        "onyx"
    ]
    assert "headers" in source
    del source["headers"]
    assert server == {**source, "url": f"{WEB_URL}/mcp/"}


def test_manifest_takes_the_marketplace_version_and_asks_for_no_address() -> None:
    manifest = json.loads(_bundle().read(MANIFEST_PATH))
    source = json.loads((SOURCE_DIR / MANIFEST_PATH).read_text())
    marketplace = json.loads((SOURCE_DIR / MARKETPLACE_PATH).read_text())

    assert manifest["version"] == marketplace["plugins"][0]["version"]
    assert manifest["name"] == source["name"]
    options = manifest["userConfig"]
    assert "onyx_url" not in options
    assert "required" not in options["onyx_api_token"]
    assert options["onyx_api_token"]["sensitive"] is True
    assert options["onyx_prefetch"] == source["userConfig"]["onyx_prefetch"]
    assert not any(option.get("required") for option in options.values())


def test_every_hook_gets_the_deployment_address() -> None:
    hooks = json.loads(_bundle().read(HOOKS_PATH))
    source = json.loads((SOURCE_DIR / HOOKS_PATH).read_text())
    assert hooks["hooks"].keys() == source["hooks"].keys()
    for event, groups in hooks["hooks"].items():
        for group, source_group in zip(groups, source["hooks"][event], strict=True):
            assert group.get("matcher") == source_group.get("matcher")
            for hook, source_hook in zip(
                group["hooks"], source_group["hooks"], strict=True
            ):
                assert hook["command"] == f"ONYX_URL={WEB_URL} {source_hook['command']}"
                assert hook["timeout"] == source_hook["timeout"]


def test_launcher_stays_executable_and_unchanged() -> None:
    bundle = _bundle()
    launcher = "scripts/onyx-hook"
    assert bundle.getinfo(launcher).external_attr >> 16 & stat.S_IXUSR
    assert bundle.read(launcher) == (SOURCE_DIR / launcher).read_bytes()
