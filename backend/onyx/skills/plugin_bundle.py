import json
import zipfile
from collections.abc import Mapping
from typing import Final

from pydantic import JsonValue

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import BUILT_IN_SKILLS
from onyx.skills.bundle import (
    PLUGIN_BUNDLE_LAYOUT,
    PLUGIN_MANIFEST_PATHS,
    SKILL_MD_NAME,
    check_skill_md_size,
    normalize_custom_bundle,
    open_bundle_zip,
)
from onyx.skills.metadata import frontmatter_for_jsonb, parse_skill_document
from onyx.skills.models import (
    MCP_URL_TRANSPORTS,
    SKILL_NAME_MAX_LENGTH,
    SKILL_NAME_PATTERN,
    PluginAuthor,
    PluginBundle,
    PluginBundleSkill,
    PluginManifest,
    PluginNeed,
    PluginSkillContent,
    PluginUnusedPart,
)
from onyx.utils.url import normalize_mcp_server_url

SKILLS_DIR: Final = "skills"
MCP_JSON_PATH: Final = ".mcp.json"
_JSON_MAX_BYTES: Final = 1024 * 1024

_UNUSED_PART_PATHS: Final[Mapping[PluginUnusedPart, tuple[str, ...]]] = {
    PluginUnusedPart.COMMANDS: ("commands/",),
    PluginUnusedPart.AGENTS: ("agents/",),
    PluginUnusedPart.HOOKS: ("hooks/",),
    PluginUnusedPart.LSP_SERVERS: (".lsp.json",),
    PluginUnusedPart.OUTPUT_STYLES: ("output-styles/",),
    PluginUnusedPart.BIN: ("bin/",),
    PluginUnusedPart.THEMES: ("themes/",),
    PluginUnusedPart.MONITORS: ("monitors/",),
}
_UNUSED_PART_KEYS: Final[Mapping[PluginUnusedPart, str]] = {
    PluginUnusedPart.COMMANDS: "commands",
    PluginUnusedPart.AGENTS: "agents",
    PluginUnusedPart.HOOKS: "hooks",
    PluginUnusedPart.LSP_SERVERS: "lspServers",
    PluginUnusedPart.OUTPUT_STYLES: "outputStyles",
    PluginUnusedPart.THEMES: "themes",
    PluginUnusedPart.MONITORS: "monitors",
}


def _invalid(detail: str) -> OnyxError:
    return OnyxError(OnyxErrorCode.INVALID_INPUT, detail)


def _read_json(bundle_zip: zipfile.ZipFile, path: str) -> JsonValue:
    info = bundle_zip.getinfo(path)
    if info.file_size > _JSON_MAX_BYTES:
        raise _invalid(f"{path} is larger than 1 MiB.")
    try:
        return json.loads(bundle_zip.read(info))
    except (ValueError, UnicodeDecodeError) as exc:
        raise _invalid(f"{path} is not valid JSON: {exc}") from exc


def _optional_string(manifest: Mapping[str, JsonValue], key: str) -> str | None:
    value = manifest.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        url = value.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
    return None


def _author(value: JsonValue) -> PluginAuthor | None:
    if isinstance(value, str) and value.strip():
        return PluginAuthor(name=value.strip())
    if isinstance(value, dict):
        author = PluginAuthor(
            **{
                key: item.strip()
                for key in ("name", "email", "url")
                if isinstance(item := value.get(key), str) and item.strip()
            }
        )
        if author != PluginAuthor():
            return author
    return None


def _manifest(
    raw: Mapping[str, JsonValue], file_paths: list[str], manifest_path: str
) -> PluginManifest:
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise _invalid(f"{manifest_path} needs a 'name'.")
    if len(name) > SKILL_NAME_MAX_LENGTH or not SKILL_NAME_PATTERN.fullmatch(name):
        raise _invalid(
            f"The plugin name '{name}' in {manifest_path} must use only lowercase "
            f"letters, numbers and single hyphens, and at most "
            f"{SKILL_NAME_MAX_LENGTH} characters."
        )
    keywords = raw.get("keywords")
    unused = [
        part
        for part, prefixes in _UNUSED_PART_PATHS.items()
        if any(path.startswith(prefixes) for path in file_paths)
        or _UNUSED_PART_KEYS.get(part) in raw
    ]
    return PluginManifest(
        name=name,
        version=_optional_string(raw, "version"),
        description=_optional_string(raw, "description"),
        author=_author(raw.get("author")),
        homepage=_optional_string(raw, "homepage"),
        repository=_optional_string(raw, "repository"),
        license=_optional_string(raw, "license"),
        keywords=(
            [item for item in keywords if isinstance(item, str)]
            if isinstance(keywords, list)
            else []
        ),
        unused_parts=unused,
    )


def _skill(bundle_zip: zipfile.ZipFile, folder: str, path: str) -> PluginBundleSkill:
    raw = bundle_zip.read(f"{path}/{SKILL_MD_NAME}")
    try:
        check_skill_md_size(raw)
        document = parse_skill_document(raw)
    except OnyxError as exc:
        raise OnyxError(
            exc.error_code, f"{path}/{SKILL_MD_NAME}: {exc.detail}", extra=exc.extra
        ) from exc
    name = document.metadata.name
    if name in BUILT_IN_SKILLS:
        raise _invalid(f"{path}/{SKILL_MD_NAME}: skill name '{name}' is reserved.")
    warnings = (
        [f"The folder {path} holds the skill '{name}'. Onyx uses the name '{name}'."]
        if name != folder
        else []
    )
    return PluginBundleSkill(
        content=PluginSkillContent(
            path=path,
            skill_md=raw.decode("utf-8"),
            frontmatter=frontmatter_for_jsonb(document),
        ),
        warnings=warnings,
    )


def mcp_need(name: str, entry: JsonValue) -> PluginNeed:
    if not isinstance(entry, dict):
        return PluginNeed(name=name, url=None, transport=None, supported=False)
    transport = entry.get("type")
    raw_url = entry.get("url")
    if not isinstance(transport, str):
        transport = "stdio" if "command" in entry else None
    url = normalize_mcp_server_url(raw_url) if isinstance(raw_url, str) else None
    return PluginNeed(
        name=name,
        url=url,
        transport=transport,
        supported=url is not None and transport in MCP_URL_TRANSPORTS,
    )


def _servers(
    value: JsonValue,
    source: str,
    bundle_zip: zipfile.ZipFile,
    paths: set[str],
    *,
    from_manifest: bool,
) -> dict[str, JsonValue]:
    if isinstance(value, str) and from_manifest:
        path = value.removeprefix("./")
        if path not in paths:
            raise _invalid(f"{source} names the MCP file {value}, which is missing.")
        return _servers(
            _read_json(bundle_zip, path), path, bundle_zip, paths, from_manifest=False
        )
    if not isinstance(value, dict):
        raise _invalid(f"The MCP servers in {source} must be a JSON object.")
    nested = value.get("mcpServers")
    if isinstance(nested, dict):
        return dict(nested)
    return dict(value)


def read_plugin_bundle(zip_bytes: bytes) -> PluginBundle:
    normalized = normalize_custom_bundle(zip_bytes, layout=PLUGIN_BUNDLE_LAYOUT)
    warnings: list[str] = []
    with open_bundle_zip(normalized.content) as bundle_zip:
        file_paths = sorted(
            info.filename for info in bundle_zip.infolist() if not info.is_dir()
        )
        paths = set(file_paths)
        manifest_paths = [path for path in PLUGIN_MANIFEST_PATHS if path in paths]
        manifest_path = manifest_paths[0]
        if len(manifest_paths) > 1:
            warnings.append(
                f"The plugin has more than one plugin.json. Onyx reads {manifest_path}."
            )
        raw_manifest = _read_json(bundle_zip, manifest_path)
        if not isinstance(raw_manifest, dict):
            raise _invalid(f"{manifest_path} must be a JSON object.")
        manifest = _manifest(raw_manifest, file_paths, manifest_path)
        if "skills" in raw_manifest:
            warnings.append(
                f"{manifest_path} names skill folders. Onyx reads only "
                f"{SKILLS_DIR}/<name>/{SKILL_MD_NAME}."
            )

        skills: list[PluginBundleSkill] = []
        for path in file_paths:
            parts = path.split("/")
            if parts[-1] != SKILL_MD_NAME:
                continue
            if len(parts) == 3 and parts[0] == SKILLS_DIR:
                skills.append(_skill(bundle_zip, parts[1], f"{SKILLS_DIR}/{parts[1]}"))
            else:
                warnings.append(
                    f"Onyx skips {path}. A skill must be in "
                    f"{SKILLS_DIR}/<name>/{SKILL_MD_NAME}."
                )
        names: dict[str, str] = {}
        for skill in skills:
            other = names.setdefault(skill.content.name, skill.content.path)
            if other != skill.content.path:
                raise _invalid(
                    f"{other} and {skill.content.path} both hold the skill "
                    f"'{skill.content.name}'."
                )

        servers: dict[str, JsonValue] = {}
        sources: list[tuple[JsonValue, str, bool]] = []
        if "mcpServers" in raw_manifest:
            sources.append((raw_manifest["mcpServers"], manifest_path, True))
        if MCP_JSON_PATH in paths and raw_manifest.get("mcpServers") not in (
            MCP_JSON_PATH,
            f"./{MCP_JSON_PATH}",
        ):
            sources.append(
                (_read_json(bundle_zip, MCP_JSON_PATH), MCP_JSON_PATH, False)
            )
        for value, source, from_manifest in sources:
            for name, entry in _servers(
                value, source, bundle_zip, paths, from_manifest=from_manifest
            ).items():
                if name in servers:
                    warnings.append(
                        f"The MCP server '{name}' is defined twice. Onyx uses the "
                        f"first one."
                    )
                    continue
                servers[name] = entry

    if not skills and not servers:
        raise _invalid(
            "This plugin has no skill and no MCP server. Onyx uses only skills "
            f"in {SKILLS_DIR}/<name>/{SKILL_MD_NAME} and MCP servers in "
            f"{MCP_JSON_PATH} or plugin.json."
        )
    return PluginBundle(
        content=normalized.content,
        manifest=manifest,
        skills=skills,
        needs=[mcp_need(name, servers[name]) for name in sorted(servers)],
        warnings=warnings,
    )
