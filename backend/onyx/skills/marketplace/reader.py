"""Read declared marketplaces without provider, database, or network access."""

import io
import json
import re
import tarfile
import zipfile
import zlib

from pydantic import JsonValue

from onyx.error_handling.exceptions import OnyxError
from onyx.skills.bundle import SKILL_MD_NAME, build_custom_bundle
from onyx.skills.marketplace.archive import (
    MANIFEST_MAX_BYTES,
    ArchiveFiles,
    ArchiveLimitError,
    archive_files,
    archive_path,
    require_regular_path,
)
from onyx.skills.marketplace.read_models import (
    BlockedSkill,
    CompleteMarketplace,
    FailedMarketplace,
    ReadySkill,
    UnsupportedPlugin,
)
from onyx.skills.metadata import parse_skill_document
from onyx.skills.models import GITHUB_SKILL_MAX_COUNT
from onyx.utils.bundle import compute_bundle_metadata

BUNDLE_CACHE_MAX_BYTES = 256 * 1024 * 1024
_MANIFESTS = (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json")
_PLUGIN_MANIFESTS = (
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    "plugin.json",
)
_COMPONENTS = (
    "mcpServers",
    "hooks",
    "apps",
    "lspServers",
    "outputStyles",
    "themes",
    "monitors",
    "workflows",
    "settings",
)
_COMPONENT_PATHS = (
    ".mcp.json",
    "mcp.json",
    ".app.json",
    ".lsp.json",
    "hooks",
    "hooks.json",
    "apps",
    "output-styles",
    "themes",
    "workflows",
    "monitors/monitors.json",
    "bin",
    "settings.json",
)


def _join(base: str, path: str) -> str:
    return "/".join(part for part in (base, archive_path(path)) if part)


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate manifest field: {key}")
        result[key] = value
    return result


def _json(files: ArchiveFiles, path: str) -> dict[str, JsonValue]:
    require_regular_path(files, path)
    opener = files[path]
    if opener is None:
        raise ValueError(f"Unreadable manifest: {path}")
    with opener() as source:
        data = source.read(MANIFEST_MAX_BYTES + 1)
    if len(data) > MANIFEST_MAX_BYTES:
        raise ValueError(f"Manifest exceeds {MANIFEST_MAX_BYTES} bytes: {path}")
    value: JsonValue = json.loads(data, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError(f"Manifest must be an object: {path}")
    return value


def _skill(files: ArchiveFiles, path: str, key: str) -> ReadySkill | BlockedSkill:
    prefix = path + "/"
    try:
        require_regular_path(files, path)
        for member in files:
            if member.startswith(prefix):
                require_regular_path(files, member)
        if f"{prefix}{SKILL_MD_NAME}" not in files:
            raise ValueError("Missing SKILL.md")
        bundle = build_custom_bundle(
            {
                p.removeprefix(prefix): f
                for p, f in files.items()
                if p.startswith(prefix) and f is not None
            }
        )
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            parse_skill_document(
                archive.read(SKILL_MD_NAME), directory_name=path.rsplit("/", 1)[-1]
            )
        return ReadySkill(
            entry_key=key,
            path=path,
            bundle_bytes=bundle,
            content_digest=compute_bundle_metadata(bundle).content_digest,
        )
    except ArchiveLimitError:
        raise
    except (OnyxError, ValueError) as exc:
        return BlockedSkill(
            entry_key=key,
            path=path,
            reason=exc.detail if isinstance(exc, OnyxError) else str(exc),
        )


def _children(files: ArchiveFiles, root: str) -> list[str]:
    prefix = root + "/" if root else ""
    return sorted(
        {
            prefix + p.removeprefix(prefix).split("/", 1)[0]
            for p, opener in files.items()
            if p.startswith(prefix)
            and ("/" in p.removeprefix(prefix) or opener is None)
        }
    )


def _has_components(
    files: ArchiveFiles,
    root: str,
    relative: set[str],
    manifests: list[dict[str, JsonValue]],
) -> bool:
    for component_path in _COMPONENT_PATHS:
        require_regular_path(files, _join(root, component_path))
    mixed = any(m.get(c) for m in manifests for c in _COMPONENTS)
    for manifest in manifests:
        experimental = manifest.get("experimental")
        if isinstance(experimental, dict):
            mixed |= any(bool(experimental.get(c)) for c in ("monitors", "themes"))
        for component in ("agents", "commands"):
            declared = manifest.get(component, "./" + component)
            paths = [declared] if isinstance(declared, str) else declared
            if isinstance(paths, list):
                for path in paths:
                    if not isinstance(path, str):
                        raise ValueError(f"Invalid {component} path: {root}")
                    target = archive_path(path)
                    require_regular_path(files, _join(root, target))
                    mixed |= any(
                        p.endswith(".md")
                        and (p == target or p.startswith(target + "/"))
                        for p in relative
                    )
            elif declared:
                mixed = True
    mixed |= any(
        p == c or p.startswith(c + "/") for p in relative for c in _COMPONENT_PATHS
    )
    return mixed


def _plugin_skills(
    files: ArchiveFiles,
    folder: str,
    name: str,
    plugin: dict[str, JsonValue],
    plugin_root: str,
) -> list[str] | UnsupportedPlugin:
    source = plugin.get("source")
    if isinstance(source, dict):
        kind = source.get("source")
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"Invalid plugin source: {name}")
        if kind != "local":
            return UnsupportedPlugin(
                entry_key=name, reason=f"Unsupported source: {kind}"
            )
        source = source.get("path")
    elif (
        isinstance(source, str) and "/" not in source and source not in ("", ".", "..")
    ):
        source = _join(plugin_root, source)
    if not isinstance(source, str) or not source:
        raise ValueError(f"Invalid local plugin source: {name}")
    root = _join(folder, source)
    require_regular_path(files, root)
    prefix = root + "/" if root else ""
    relative = {p.removeprefix(prefix) for p in files if p.startswith(prefix)}
    if not relative:
        raise ValueError(f"Plugin folder is missing: {root}")
    manifests = [plugin]
    for path in _PLUGIN_MANIFESTS:
        require_regular_path(files, prefix + path)
        if path in relative:
            manifests.append(_json(files, prefix + path))
    if "plugin.json" in relative:
        return UnsupportedPlugin(
            entry_key=name, reason="Root plugin.json format is not supported"
        )
    mixed = _has_components(files, root, relative, manifests)
    if mixed:
        return UnsupportedPlugin(
            entry_key=name, reason="Plugin contains components other than skills"
        )
    declared = plugin.get("skills")
    if "skills" in plugin:
        paths = [declared] if isinstance(declared, str) else declared
        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
            raise ValueError(f"Invalid skills list: {name}")
        skill_paths: list[str] = []
        for path in paths:
            if not isinstance(path, str):
                continue
            target = _join(root, path)
            if _join(target, SKILL_MD_NAME) in files or target in files:
                skill_paths.append(target)
            else:
                require_regular_path(files, target)
                skill_paths.extend(_children(files, target) or [target])
        return skill_paths
    target = _join(root, "skills")
    require_regular_path(files, target)
    return _children(files, target)


def read_marketplace_archive(
    data: bytes, folder: str | None = None
) -> CompleteMarketplace | FailedMarketplace:
    """Read a root archive or one repository wrapper; paths are repository-relative.

    An incomplete manifest/archive fails the entire read. Blocked skill keys remain
    present, so reconciliation must not retire them. Never infer absence on failure.
    """
    try:
        folder = archive_path(folder or "")
        with archive_files(data) as files:
            # Providers may wrap a repository in one commit-named directory.
            if not any(_join(folder, p) in files for p in _MANIFESTS):
                roots = {p.split("/", 1)[0] for p in files}
                if len(roots) == 1 and all("/" in p for p in files):
                    files = {p.split("/", 1)[1]: f for p, f in files.items()}
            for candidate in _MANIFESTS:
                require_regular_path(files, _join(folder, candidate))
            manifest_path = next(
                (_join(folder, p) for p in _MANIFESTS if _join(folder, p) in files),
                None,
            )
            if manifest_path is None:
                raise ValueError("Marketplace manifest is missing")
            manifest = _json(files, manifest_path)
            metadata = manifest.get("metadata")
            plugin_root = (
                metadata.get("pluginRoot", "") if isinstance(metadata, dict) else ""
            )
            if not isinstance(plugin_root, str):
                raise ValueError("Invalid metadata.pluginRoot")
            plugin_root = archive_path(plugin_root)
            if not isinstance(manifest.get("name"), str) or not manifest["name"]:
                raise ValueError("Marketplace name is missing")
            plugins = manifest.get("plugins")
            if not isinstance(plugins, list):
                raise ValueError("Marketplace plugins must be an array")
            entries: list[ReadySkill | BlockedSkill | UnsupportedPlugin] = []
            plugin_names: set[str] = set()
            skill_keys: set[str] = set()
            cache: dict[str, ReadySkill | BlockedSkill] = {}
            bundle_bytes = 0
            for plugin in plugins:
                if not isinstance(plugin, dict):
                    raise ValueError("Plugin entry must be an object")
                name = plugin.get("name")
                if not isinstance(name, str) or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._-]*", name
                ):
                    raise ValueError("Invalid plugin name")
                if name in plugin_names:
                    raise ValueError(f"Duplicate plugin identity: {name}")
                plugin_names.add(name)
                skill_paths = _plugin_skills(files, folder, name, plugin, plugin_root)
                if isinstance(skill_paths, UnsupportedPlugin):
                    entries.append(skill_paths)
                    continue
                for path in skill_paths:
                    key = f"{name}/{path.rsplit('/', 1)[-1]}"
                    if not path or key in skill_keys:
                        raise ValueError(f"Duplicate or empty skill identity: {key}")
                    skill_keys.add(key)
                    if len(skill_keys) > GITHUB_SKILL_MAX_COUNT:
                        raise ValueError(
                            f"Marketplace exceeds {GITHUB_SKILL_MAX_COUNT} skills"
                        )
                    if path not in cache:
                        cached = _skill(files, path, key)
                        if isinstance(cached, ReadySkill):
                            bundle_bytes += len(cached.bundle_bytes)
                            if bundle_bytes > BUNDLE_CACHE_MAX_BYTES:
                                raise ArchiveLimitError(
                                    f"Generated bundles exceed {BUNDLE_CACHE_MAX_BYTES} bytes"
                                )
                        cache[path] = cached
                    entries.append(cache[path].model_copy(update={"entry_key": key}))
            return CompleteMarketplace(entries=entries)
    except (
        ValueError,
        KeyError,
        OSError,
        EOFError,
        tarfile.TarError,
        zipfile.BadZipFile,
        zlib.error,
        RuntimeError,
        NotImplementedError,
        RecursionError,
    ) as exc:
        return FailedMarketplace(reason=f"Cannot read marketplace: {exc}")
