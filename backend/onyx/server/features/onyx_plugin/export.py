"""Builds the Onyx plugin zip with the deployment's address in the files, for a host
that takes no install options, such as claude.ai chat."""

import io
import shlex
import zipfile
from pathlib import Path

from onyx.oauth_provider.models import OAuthProviderSettings
from onyx.server.features.onyx_plugin.models import (
    HooksFile,
    Marketplace,
    McpConfig,
    PluginManifest,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Read for the plugin version only: a marketplace file has no use in an upload.
MARKETPLACE_PATH = ".claude-plugin/marketplace.json"
MANIFEST_PATH = ".claude-plugin/plugin.json"
MCP_CONFIG_PATH = ".mcp.json"
HOOKS_PATH = "hooks/hooks.json"
TEST_SUFFIX = ".test.ts"
MCP_SERVER_NAME = "onyx"
URL_OPTION = "onyx_url"
TOKEN_OPTION = "onyx_api_token"
TOKEN_NOTE = "Only needed for prefetch."


def _load_plugin_dir() -> Path | None:
    """The plugin folder, or None in an image built without the `agent-plugin`
    build context. The image keeps the folder at its repo path, with / as the repo root."""
    plugin_dir = Path(__file__).resolve().parents[5] / "extensions" / "agent-plugin"
    if (plugin_dir / MANIFEST_PATH).is_file():
        return plugin_dir
    logger.warning("Onyx plugin export is off: no plugin files at %s", plugin_dir)
    return None


PLUGIN_DIR = _load_plugin_dir()


def _stamped_manifest(plugin_dir: Path) -> str:
    manifest = PluginManifest.model_validate_json(
        (plugin_dir / MANIFEST_PATH).read_text()
    )
    marketplace = Marketplace.model_validate_json(
        (plugin_dir / MARKETPLACE_PATH).read_text()
    )
    versions = {entry.name: entry.version for entry in marketplace.plugins}
    manifest.version = versions[manifest.name]
    del manifest.user_config[URL_OPTION]
    # The MCP server signs in through OAuth, so only the prefetch needs the token.
    token = manifest.user_config[TOKEN_OPTION]
    token.required = None
    token.description = f"{TOKEN_NOTE} {token.description}"
    return manifest.dump()


def _stamped_mcp_config(plugin_dir: Path, mcp_resource_url: str) -> str:
    config = McpConfig.model_validate_json((plugin_dir / MCP_CONFIG_PATH).read_text())
    server = config.mcp_servers[MCP_SERVER_NAME]
    server.url = mcp_resource_url
    server.headers = None
    return config.dump()


def _stamped_hooks(plugin_dir: Path, web_url: str) -> str:
    hooks = HooksFile.model_validate_json((plugin_dir / HOOKS_PATH).read_text())
    # The hook reads the bare ONYX_URL when the plugin has no URL option.
    prefix = f"ONYX_URL={shlex.quote(web_url)} "
    for groups in hooks.hooks.values():
        for group in groups:
            for hook in group.hooks:
                hook.command = prefix + hook.command
    return hooks.dump()


def build_plugin_bundle(plugin_dir: Path, settings: OAuthProviderSettings) -> bytes:
    stamped: dict[str, str] = {
        MANIFEST_PATH: _stamped_manifest(plugin_dir),
        MCP_CONFIG_PATH: _stamped_mcp_config(plugin_dir, settings.mcp_resource_url),
        HOOKS_PATH: _stamped_hooks(plugin_dir, settings.web_url),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for path in sorted(plugin_dir.rglob("*")):
            name = path.relative_to(plugin_dir).as_posix()
            if not path.is_file() or name == MARKETPLACE_PATH:
                continue
            if name.endswith(TEST_SUFFIX):
                continue
            # from_file keeps the launcher's executable bit.
            info = zipfile.ZipInfo.from_file(path, name)
            bundle.writestr(
                info,
                stamped[name] if name in stamped else path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
            )
    return buffer.getvalue()
