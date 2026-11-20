import io
import json
import zipfile
from collections.abc import Mapping
from typing import Final
from urllib.parse import urlparse

from pydantic import JsonValue

from onyx.error_handling.exceptions import OnyxError
from onyx.skills.bundle import (
    PLUGIN_MANIFEST_PATHS,
    SKILL_MD_NAME,
    TEMPLATE_SUFFIX,
    compute_bundle_manifest,
)
from onyx.skills.marketplace.models import (
    BlockedPlugin,
    CompleteMarketplace,
    FailedMarketplace,
    GitHubRepoSource,
    MarketplaceEntry,
    ReadyPlugin,
    RemotePlugin,
    UnsupportedPlugin,
)
from onyx.skills.models import (
    GITHUB_SKILL_MAX_COUNT,
    SKILL_NAME_MAX_LENGTH,
    SKILL_NAME_PATTERN,
)
from onyx.skills.plugin_bundle import MCP_JSON_PATH, SKILLS_DIR, read_plugin_bundle
from onyx.utils.github import GITHUB_REPOSITORY_COMPONENT_PATTERN

MARKETPLACE_MANIFEST_PATHS: Final = (
    ".claude-plugin/marketplace.json",
    ".agents/plugins/marketplace.json",
)
PLUGIN_ENTRY_MAX_COUNT: Final = 500
_MANIFEST_MAX_BYTES: Final = 1024 * 1024
_BUNDLES_MAX_BYTES: Final = 256 * 1024 * 1024
# A fixed time makes the same files give the same zip.
_ZIP_DATE_TIME: Final = (1980, 1, 1, 0, 0, 0)
_ENTRY_FIELDS: Final = (
    "name",
    "description",
    "version",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "mcpServers",
)
_BUILT_PLUGIN_JSON: Final = ".claude-plugin/plugin.json"
NOT_SUPPORTED_REASON: Final = "Not supported in Onyx."


class BundleBudget:
    """The limits on all ready plugins of one marketplace, local and remote."""

    def __init__(self) -> None:
        self.skill_count = 0
        self.bundle_bytes = 0

    def add(self, plugin: ReadyPlugin) -> None:
        self.skill_count += len(plugin.bundle.skills)
        self.bundle_bytes += len(plugin.bundle.content)
        if self.skill_count > GITHUB_SKILL_MAX_COUNT:
            raise ValueError(
                f"The marketplace has more than {GITHUB_SKILL_MAX_COUNT} skills."
            )
        if self.bundle_bytes > _BUNDLES_MAX_BYTES:
            raise ValueError(
                "The marketplace plugins are larger than "
                f"{_BUNDLES_MAX_BYTES // (1024 * 1024)} MiB together."
            )


def _join(*parts: str) -> str:
    return "/".join(part for part in parts if part)


def _relative_path(value: str) -> str:
    parts = [part for part in value.strip().split("/") if part not in {"", "."}]
    if value.startswith("/") or "\\" in value or ".." in parts:
        raise ValueError(f"The path '{value}' must stay in the repository.")
    return "/".join(parts)


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"The field '{key}' is defined twice.")
        result[key] = value
    return result


def _json_object(data: bytes, path: str) -> dict[str, JsonValue]:
    if len(data) > _MANIFEST_MAX_BYTES:
        raise ValueError(f"{path} is larger than 1 MiB.")
    try:
        value = json.loads(data, object_pairs_hook=_unique_object)
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path} is not UTF-8 text.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be a JSON object.")
    return value


def _folder_files(files: Mapping[str, bytes], root: str) -> dict[str, bytes]:
    prefix = f"{root}/" if root else ""
    return {
        path.removeprefix(prefix): content
        for path, content in files.items()
        if path.startswith(prefix)
        and not path.endswith(TEMPLATE_SUFFIX)
        and "__pycache__" not in path.split("/")
    }


def _declared_skill_folders(
    folder_files: Mapping[str, bytes], declared: JsonValue
) -> list[str]:
    paths = [declared] if isinstance(declared, str) else declared
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise ValueError("The entry field 'skills' must be a list of folders.")
    folders: list[str] = []
    for path in paths:
        if not isinstance(path, str):
            raise ValueError("The entry field 'skills' must be a list of folders.")
        folder = _relative_path(path)
        if _join(folder, SKILL_MD_NAME) in folder_files:
            folders.append(folder)
            continue
        prefix = f"{folder}/" if folder else ""
        children = sorted(
            {
                path.removeprefix(prefix).split("/", 1)[0]
                for path in folder_files
                if path.startswith(prefix)
                and path.removeprefix(prefix).count("/") == 1
                and path.endswith(f"/{SKILL_MD_NAME}")
            }
        )
        if not children:
            raise ValueError(f"The skill folder '{path}' has no {SKILL_MD_NAME}.")
        folders.extend(_join(folder, child) for child in children)
    return folders


def _deterministic_zip(bundle_files: Mapping[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_:
        for path in sorted(bundle_files):
            info = zipfile.ZipInfo(path, date_time=_ZIP_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zip_.writestr(info, bundle_files[path])
    return output.getvalue()


def _plugin_files(
    folder_files: Mapping[str, bytes], entry: Mapping[str, JsonValue]
) -> dict[str, bytes]:
    manifest_path = next(
        (path for path in PLUGIN_MANIFEST_PATHS if path in folder_files), None
    )
    folder_manifest = (
        _json_object(folder_files[manifest_path], manifest_path)
        if manifest_path is not None
        else {}
    )
    manifest = {
        field: entry[field] for field in _ENTRY_FIELDS if field in entry
    } | folder_manifest
    declared = entry.get("skills")
    if declared is None:
        bundle_files = {
            path: content
            for path, content in folder_files.items()
            if path not in PLUGIN_MANIFEST_PATHS
        }
    else:
        manifest.pop("skills", None)
        bundle_files = {}
        names: dict[str, str] = {}
        for folder in _declared_skill_folders(folder_files, declared):
            name = folder.rsplit("/", 1)[-1]
            other = names.setdefault(name, folder)
            if other != folder:
                raise ValueError(
                    f"The skill folders {other} and {folder} share a name."
                )
            prefix = f"{folder}/"
            for path, content in folder_files.items():
                if path.startswith(prefix):
                    relative = path.removeprefix(prefix)
                    bundle_files[f"{SKILLS_DIR}/{name}/{relative}"] = content
        declared_servers = manifest.get("mcpServers")
        server_files = (
            declared_servers
            if isinstance(declared_servers, list)
            else [declared_servers]
        )
        for server_file in [MCP_JSON_PATH, *server_files]:
            if not isinstance(server_file, str):
                continue
            path = server_file.removeprefix("./")
            if path in folder_files:
                bundle_files[path] = folder_files[path]
    bundle_files[_BUILT_PLUGIN_JSON] = json.dumps(
        manifest, indent=2, sort_keys=True
    ).encode()
    return bundle_files


def build_entry_bundle(
    files: Mapping[str, bytes],
    root: str,
    entry: Mapping[str, JsonValue],
    entry_key: str,
) -> ReadyPlugin | BlockedPlugin:
    if len(entry_key) > SKILL_NAME_MAX_LENGTH or not SKILL_NAME_PATTERN.fullmatch(
        entry_key
    ):
        return BlockedPlugin(
            entry_key=entry_key,
            path=root,
            reason=f"The entry name '{entry_key}' must use only lowercase letters, "
            f"numbers and single hyphens, and at most {SKILL_NAME_MAX_LENGTH} "
            "characters.",
        )
    folder_files = _folder_files(files, root)
    if not folder_files:
        return BlockedPlugin(
            entry_key=entry_key,
            path=root,
            reason=f"The plugin folder '{root or '.'}' is missing.",
        )
    try:
        bundle = read_plugin_bundle(
            _deterministic_zip(_plugin_files(folder_files, entry))
        )
    except OnyxError as exc:
        return BlockedPlugin(entry_key=entry_key, path=root, reason=exc.detail)
    except ValueError as exc:
        return BlockedPlugin(entry_key=entry_key, path=root, reason=str(exc))
    return ReadyPlugin(
        entry_key=entry_key,
        path=root,
        bundle=bundle,
        file_manifest=compute_bundle_manifest(bundle.content),
    )


def _github_repository(value: JsonValue) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    text = value.strip().removesuffix("/").removesuffix(".git")
    if "://" in text:
        parsed = urlparse(text)
        if parsed.scheme != "https" or parsed.hostname not in {
            "github.com",
            "www.github.com",
        }:
            return None
        text = parsed.path.strip("/")
    parts = text.split("/")
    if len(parts) != 2 or not all(
        part not in {".", ".."} and GITHUB_REPOSITORY_COMPONENT_PATTERN.fullmatch(part)
        for part in parts
    ):
        return None
    return parts[0], parts[1]


def _optional_text(source: Mapping[str, JsonValue], key: str) -> str | None:
    value = source.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _remote_source(source: Mapping[str, JsonValue]) -> GitHubRepoSource | None:
    kind = source.get("source")
    if kind == "github":
        repository = _github_repository(source.get("repo"))
        path = None
    elif kind == "git-subdir":
        repository = _github_repository(source.get("url"))
        raw_path = source.get("path")
        path = _relative_path(raw_path) if isinstance(raw_path, str) else None
    else:
        return None
    if repository is None:
        return None
    return GitHubRepoSource(
        owner=repository[0],
        repo=repository[1],
        ref=_optional_text(source, "ref"),
        sha=_optional_text(source, "sha"),
        path=path or None,
    )


def _read_entry(
    files: Mapping[str, bytes],
    base: str,
    plugin_root: str,
    entry_key: str,
    entry: dict[str, JsonValue],
) -> MarketplaceEntry:
    source = entry.get("source")
    if isinstance(source, dict):
        try:
            remote = _remote_source(source)
        except ValueError as exc:
            return BlockedPlugin(entry_key=entry_key, path=None, reason=str(exc))
        if remote is None:
            return UnsupportedPlugin(entry_key=entry_key, reason=NOT_SUPPORTED_REASON)
        return RemotePlugin(entry_key=entry_key, source=remote, entry=entry)
    if not isinstance(source, str):
        return BlockedPlugin(
            entry_key=entry_key,
            path=None,
            reason="The entry needs a 'source' folder or repository.",
        )
    try:
        relative = _relative_path(source)
    except ValueError as exc:
        return BlockedPlugin(entry_key=entry_key, path=None, reason=str(exc))
    # metadata.pluginRoot applies to a bare folder name.
    if source.strip() not in {"", ".", "./"} and "/" not in source:
        relative = _join(plugin_root, relative)
    root = _join(base, relative)
    return build_entry_bundle(files, root, entry, entry_key)


def _plugin_entries(manifest: Mapping[str, JsonValue]) -> list[dict[str, JsonValue]]:
    plugins = manifest.get("plugins")
    if not isinstance(plugins, list):
        raise ValueError("The marketplace 'plugins' must be a list.")
    if len(plugins) > PLUGIN_ENTRY_MAX_COUNT:
        raise ValueError(
            f"The marketplace has more than {PLUGIN_ENTRY_MAX_COUNT} plugins."
        )
    names: set[str] = set()
    entries: list[dict[str, JsonValue]] = []
    for plugin in plugins:
        if not isinstance(plugin, dict):
            raise ValueError("Each marketplace plugin must be an object.")
        name = plugin.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each marketplace plugin needs a 'name'.")
        if name in names:
            raise ValueError(f"Two marketplace plugins are named '{name}'.")
        names.add(name)
        entries.append(plugin)
    return entries


def read_marketplace(
    files: Mapping[str, bytes],
    folder: str | None,
) -> CompleteMarketplace | FailedMarketplace:
    base = folder or ""
    manifest_path = next(
        (
            _join(base, path)
            for path in MARKETPLACE_MANIFEST_PATHS
            if _join(base, path) in files
        ),
        None,
    )
    if manifest_path is None:
        return FailedMarketplace(
            reason=f"No {MARKETPLACE_MANIFEST_PATHS[0]} in "
            f"{f'the folder {base}' if base else 'the repository root'}."
        )
    try:
        manifest = _json_object(files[manifest_path], manifest_path)
        name = manifest.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("The marketplace needs a 'name'.")
        metadata = manifest.get("metadata", {})
        plugin_root = (
            metadata.get("pluginRoot", "") if isinstance(metadata, dict) else ""
        )
        if not isinstance(plugin_root, str):
            raise ValueError("The marketplace metadata.pluginRoot must be text.")
        plugin_root = _relative_path(plugin_root)
        entries: list[MarketplaceEntry] = []
        budget = BundleBudget()
        for entry in _plugin_entries(manifest):
            key = str(entry["name"])
            result = _read_entry(files, base, plugin_root, key, entry)
            if isinstance(result, ReadyPlugin):
                budget.add(result)
            entries.append(result)
    except ValueError as exc:
        return FailedMarketplace(reason=str(exc))
    return CompleteMarketplace(name=name.strip(), entries=tuple(entries))
