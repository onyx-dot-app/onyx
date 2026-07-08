"""Skills marketplace: fetch and unpack skill bundles from git hosting providers."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlparse

import requests
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from onyx.configs.app_configs import SKILL_MARKETPLACE_ARCHIVE_MAX_BYTES
from onyx.configs.app_configs import SKILL_MARKETPLACE_FETCH_TIMEOUT_SECONDS
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import SLUG_REGEX
from onyx.skills.bundle import DEFAULT_PER_FILE_MAX_BYTES
from onyx.skills.bundle import DEFAULT_TOTAL_MAX_BYTES
from onyx.skills.bundle import parse_skill_md_text
from onyx.skills.bundle import SKILL_MD_NAME
from onyx.skills.bundle import TEMPLATE_SUFFIX
from onyx.utils.url import ssrf_safe_get
from onyx.utils.url import SSRFException

_SUPPORTED_HOSTS = ("github.com", "gitlab.com")
# Maximum number of tar members to extract (zip-bomb / runaway archive guard).
_TAR_MAX_MEMBERS = 10_000


class ParsedSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: str
    owner: str
    repo: str
    ref: str | None
    subpath: str | None
    skill_filters: list[str] = Field(default_factory=list)


class DiscoveredSkill(BaseModel):
    model_config = ConfigDict(frozen=True)

    slug: str
    name: str
    description: str
    rel_path: str
    abs_dir: Path


def _strip_skills_command(raw: str) -> tuple[str, list[str]]:
    """Strip leading npx/skills/add tokens; collect --skill/-s values.

    Returns (source_token, skill_filters).
    """
    tokens = raw.split()
    # Drop npx variants and the skills binary name
    while tokens and tokens[0] in ("npx", "-y", "npx-y"):
        tokens.pop(0)
    # Drop package name variants: skills, skills@latest, skills@X.Y.Z
    if tokens and (tokens[0] == "skills" or tokens[0].startswith("skills@")):
        tokens.pop(0)
    if tokens and tokens[0] == "add":
        tokens.pop(0)

    # Flags that consume a following value (besides --skill/-s which we collect).
    _VALUE_FLAGS = {"--agent", "-a"}
    # Boolean flags to skip (no following value).
    _BOOL_FLAGS = {"--global", "-g", "--yes", "-y", "--copy", "--all", "--list", "-l"}

    skill_filters: list[str] = []
    source: str | None = None
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("--skill", "-s"):
            i += 1
            if i < len(tokens):
                skill_filters.append(tokens[i])
        elif tok in _VALUE_FLAGS:
            i += 1  # skip value
        elif tok in _BOOL_FLAGS:
            pass
        elif tok.startswith("-"):
            # Unknown flag; if it contains '=' it's self-contained, else skip next.
            if "=" not in tok:
                i += 1
        else:
            if source is None:
                source = tok
        i += 1

    return source or "", skill_filters


def parse_skill_source(raw: str) -> ParsedSource:
    """Parse a skills.sh command, bare owner/repo, or full URL into ParsedSource."""
    stripped = raw.strip()

    # Detect skills.sh command by presence of 'add' keyword before non-flag token,
    # or by leading npx/skills prefix.
    looks_like_command = (
        any(stripped.startswith(prefix) for prefix in ("npx ", "skills ", "skills@"))
        or " add " in stripped
    )

    if looks_like_command:
        source_token, skill_filters = _strip_skills_command(stripped)
    else:
        source_token = stripped
        skill_filters = []

    if not source_token:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "no source found in input")

    if source_token.startswith("https://") or source_token.startswith("http://"):
        return _parse_url_source(source_token, skill_filters)

    # Bare owner/repo (may contain a host prefix like github.com/owner/repo)
    if "/" in source_token:
        parts = source_token.split("/")
        if "." in parts[0]:
            host = parts[0].lower()
            if host not in _SUPPORTED_HOSTS:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"unsupported host '{host}'; supported: {', '.join(_SUPPORTED_HOSTS)}",
                )
            if len(parts) < 3:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"cannot extract owner and repo from '{source_token}'",
                )
            owner = parts[1]
            repo = parts[2].removesuffix(".git")
            return ParsedSource(
                host=host,
                owner=owner,
                repo=repo,
                ref=None,
                subpath=None,
                skill_filters=skill_filters,
            )
        if len(parts) < 2:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"cannot extract owner and repo from '{source_token}'",
            )
        owner = parts[0]
        repo = parts[1].removesuffix(".git")
        return ParsedSource(
            host="github.com",
            owner=owner,
            repo=repo,
            ref=None,
            subpath=None,
            skill_filters=skill_filters,
        )

    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        f"cannot extract owner and repo from '{source_token}'",
    )


def _parse_url_source(url: str, skill_filters: list[str]) -> ParsedSource:
    """Parse a full https:// URL into ParsedSource."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in _SUPPORTED_HOSTS:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"unsupported host '{host}'; supported: {', '.join(_SUPPORTED_HOSTS)}",
        )

    # path looks like /owner/repo[.git][/tree/<ref>[/subpath...]]
    path_parts = [p for p in parsed.path.split("/") if p]
    if len(path_parts) < 2:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"cannot extract owner and repo from URL '{url}'",
        )

    ref: str | None = None
    subpath: str | None = None

    # GitLab inserts a "-" separator between the project path and tree/blob/...
    # The project path may be nested through subgroups
    # (group/subgroup/.../repo), so everything before "-" is the project path:
    # all but the last segment is the owner namespace, the last is the repo.
    if host == "gitlab.com" and "-" in path_parts:
        sep = path_parts.index("-")
        project_parts = path_parts[:sep]
        if len(project_parts) < 2:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"cannot extract owner and repo from URL '{url}'",
            )
        owner = "/".join(project_parts[:-1])
        repo = project_parts[-1].removesuffix(".git")
        rest = path_parts[sep + 1 :]
    else:
        owner = path_parts[0]
        repo = path_parts[1].removesuffix(".git")
        rest = path_parts[2:]

    # Tree/ref form: /tree/<ref>[/<subpath>...] (after the host-specific prefix
    # handling above). A slash-containing ref is not disambiguated from the
    # subpath — the first segment after tree is taken as the ref.
    if rest and rest[0] == "tree":
        if len(rest) < 2:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"malformed tree URL '{url}': missing ref after /tree/",
            )
        ref = rest[1]
        if len(rest) > 2:
            subpath = "/".join(rest[2:])

    return ParsedSource(
        host=host,
        owner=owner,
        repo=repo,
        ref=ref,
        subpath=subpath,
        skill_filters=skill_filters,
    )


def fetch_repo_archive(source: ParsedSource) -> bytes:
    """Download the repository tar.gz archive for the given ParsedSource."""
    ref = source.ref or "HEAD"

    # owner/repo/ref come from URL path segments that urlparse already decoded,
    # so re-encode before interpolating — an unescaped '#'/'?' would otherwise
    # truncate the path as a fragment/query and fetch a different resource.
    # safe="/" keeps subgroup and slashed-ref separators intact.
    owner = quote(source.owner, safe="/")
    repo = quote(source.repo, safe="")
    ref_enc = quote(ref, safe="/")

    if source.host == "github.com":
        url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref_enc}"
    else:
        # gitlab.com
        url = (
            f"https://gitlab.com/{owner}/{repo}"
            f"/-/archive/{ref_enc}/{repo}-{ref_enc}.tar.gz"
        )

    try:
        response = ssrf_safe_get(
            url,
            timeout=SKILL_MARKETPLACE_FETCH_TIMEOUT_SECONDS,
            stream=True,
        )
    except SSRFException as exc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"SSRF check failed for '{url}': {exc}",
        ) from exc
    except requests.RequestException as exc:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"failed to reach '{url}': {exc}",
        ) from exc

    # Context-manage the streamed response so the connection is released on
    # every exit path (status raises, size-cap, stream error, or success)
    # rather than leaking until GC.
    with response:
        if response.status_code == 404:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND,
                f"Repository or ref not found: {source.owner}/{source.repo}@{ref}",
            )
        if response.status_code != 200:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                f"unexpected status {response.status_code} fetching '{url}'",
            )

        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > SKILL_MARKETPLACE_ARCHIVE_MAX_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"archive exceeds {SKILL_MARKETPLACE_ARCHIVE_MAX_BYTES // (1024 * 1024)} MiB",
                    )
                chunks.append(chunk)
        except requests.RequestException as exc:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                f"error streaming archive from '{url}': {exc}",
            ) from exc

        return b"".join(chunks)


def _safe_extract_tar(
    archive_bytes: bytes,
    dest: Path,
) -> None:
    """Extract a tar.gz archive into dest with path-traversal and size guards."""
    buf = io.BytesIO(archive_bytes)
    try:
        tf = tarfile.open(fileobj=buf, mode="r:gz")
    except tarfile.TarError as exc:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"archive is not a valid tar.gz: {exc}",
        ) from exc

    dest_resolved = dest.resolve()
    member_count = 0
    total_bytes = 0

    with tf:
        for member in tf:
            member_count += 1
            if member_count > _TAR_MAX_MEMBERS:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"archive exceeds {_TAR_MAX_MEMBERS} members",
                )

            # Reject symlinks, hardlinks, and device files — only regular files and dirs.
            if member.issym() or member.islnk():
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"archive contains a symlink/hardlink: '{member.name}'",
                )
            if not (member.isreg() or member.isdir()):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"archive contains unsupported entry type: '{member.name}'",
                )

            # Resolve target and check it stays inside dest.
            target = (dest / member.name).resolve()
            try:
                target.relative_to(dest_resolved)
            except ValueError:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"archive entry escapes root: '{member.name}'",
                )

            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            if member.size > DEFAULT_PER_FILE_MAX_BYTES:
                raise OnyxError(
                    OnyxErrorCode.PAYLOAD_TOO_LARGE,
                    f"file '{member.name}' exceeds "
                    f"{DEFAULT_PER_FILE_MAX_BYTES // (1024 * 1024)} MiB",
                )
            total_bytes += member.size
            if total_bytes > DEFAULT_TOTAL_MAX_BYTES:
                raise OnyxError(
                    OnyxErrorCode.PAYLOAD_TOO_LARGE,
                    f"archive exceeds {DEFAULT_TOTAL_MAX_BYTES // (1024 * 1024)} MiB uncompressed",
                )

            target.parent.mkdir(parents=True, exist_ok=True)
            fobj = tf.extractfile(member)
            if fobj is None:
                continue
            with fobj, open(target, "wb") as out:
                written = 0
                while True:
                    chunk = fobj.read(64 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > DEFAULT_PER_FILE_MAX_BYTES:
                        raise OnyxError(
                            OnyxErrorCode.PAYLOAD_TOO_LARGE,
                            f"file '{member.name}' exceeds "
                            f"{DEFAULT_PER_FILE_MAX_BYTES // (1024 * 1024)} MiB",
                        )
                    out.write(chunk)


def _strip_top_level_dir(root: Path) -> Path:
    """If root contains exactly one child directory, return it (GitHub/GitLab wrap)."""
    children = list(root.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return root


def _parse_manifest_skill_dirs(search_root: Path) -> list[Path]:
    """Read .claude-plugin/marketplace.json or plugin.json for declared skill dirs.

    Manifest content is untrusted (it ships inside the fetched archive), so every
    declared path is confined to ``search_root`` — absolute paths, ``..`` escapes,
    and anything resolving outside the repo root are skipped.
    """
    root_resolved = search_root.resolve()

    def _confined(base: Path, rel: str) -> Path | None:
        if rel.startswith("/") or ".." in Path(rel).parts:
            return None
        candidate = (base / rel).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            return None
        return candidate if candidate.is_dir() else None

    dirs: list[Path] = []
    for name in ("marketplace.json", "plugin.json"):
        manifest_path = search_root / ".claude-plugin" / name
        if not manifest_path.is_file():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        # Format 1: top-level "skills" array of relative paths
        skills_list = data.get("skills")
        if isinstance(skills_list, list):
            for entry in skills_list:
                if not isinstance(entry, str):
                    continue
                confined = _confined(search_root, entry)
                if confined is not None:
                    dirs.append(confined)

        # Format 2: "plugins" list with metadata.pluginRoot and skills
        plugins = data.get("plugins")
        if isinstance(plugins, list):
            for plugin in plugins:
                if not isinstance(plugin, dict):
                    continue
                meta = plugin.get("metadata", {})
                plugin_root_rel = (
                    meta.get("pluginRoot", "") if isinstance(meta, dict) else ""
                )
                plugin_root = search_root
                if plugin_root_rel:
                    confined_root = _confined(search_root, plugin_root_rel)
                    if confined_root is None:
                        continue
                    plugin_root = confined_root
                skill_entries = plugin.get("skills", [])
                if isinstance(skill_entries, list):
                    for entry in skill_entries:
                        if not isinstance(entry, str):
                            continue
                        confined = _confined(plugin_root, entry)
                        if confined is not None:
                            dirs.append(confined)
    return dirs


def _discover_skills_in_dir(
    archive_bytes: bytes,
    tmp: Path,
    subpath: str | None = None,
) -> list[DiscoveredSkill]:
    """Core discovery logic operating on an already-created tmp directory."""
    _safe_extract_tar(archive_bytes, tmp)
    repo_root = _strip_top_level_dir(tmp)

    # Determine search root, guarding against traversal.
    if subpath:
        search_root = (repo_root / subpath).resolve()
        try:
            search_root.relative_to(repo_root.resolve())
        except ValueError:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"subpath '{subpath}' escapes repository root",
            )
        if not search_root.is_dir():
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND,
                f"subpath '{subpath}' not found in archive",
            )
    else:
        search_root = repo_root

    seen: set[Path] = set()
    skill_dirs: list[Path] = []

    def _add(d: Path) -> None:
        resolved = d.resolve()
        if (
            resolved not in seen
            and resolved.is_dir()
            and (resolved / SKILL_MD_NAME).is_file()
        ):
            seen.add(resolved)
            skill_dirs.append(d)

    # Root-level SKILL.md
    _add(search_root)

    # Flat: skills/*/SKILL.md
    skills_base = search_root / "skills"
    if skills_base.is_dir():
        skills_children = sorted(skills_base.iterdir())
        for d in skills_children:
            if d.is_dir() and not d.name.startswith("."):
                _add(d)
        # Catalog: skills/*/*/SKILL.md
        for d in skills_children:
            if d.is_dir() and not d.name.startswith("."):
                for sub in sorted(d.iterdir()):
                    if sub.is_dir():
                        _add(sub)
        # Hidden curated containers
        for hidden in (".curated", ".experimental"):
            container = skills_base / hidden
            if container.is_dir():
                for d in sorted(container.iterdir()):
                    if d.is_dir():
                        _add(d)

    # .claude/skills/*/SKILL.md
    claude_skills = search_root / ".claude" / "skills"
    if claude_skills.is_dir():
        for d in sorted(claude_skills.iterdir()):
            if d.is_dir():
                _add(d)

    # .agents/skills/*/SKILL.md
    agents_skills = search_root / ".agents" / "skills"
    if agents_skills.is_dir():
        for d in sorted(agents_skills.iterdir()):
            if d.is_dir():
                _add(d)

    # Manifest-declared dirs
    for d in _parse_manifest_skill_dirs(search_root):
        _add(d)

    results: list[DiscoveredSkill] = []
    repo_root_resolved = repo_root.resolve()
    for skill_dir in skill_dirs:
        try:
            skill_md_text = (skill_dir / SKILL_MD_NAME).read_text(encoding="utf-8")
            name, description = parse_skill_md_text(skill_md_text)
        except OnyxError:
            continue
        except Exception:
            continue

        # slug: dir basename. Only a true repo-root SKILL.md (no subpath) falls
        # back to the repo wrapper dir name; a subpath leaf (e.g. a tree URL
        # pointing at skills/docx) keeps its own dir name.
        if skill_dir.resolve() == repo_root_resolved:
            slug_candidate = repo_root.name.lower()
            # Strip common suffixes like -main, -master
            for suffix in ("-main", "-master"):
                if slug_candidate.endswith(suffix):
                    slug_candidate = slug_candidate[: -len(suffix)]
                    break
        else:
            slug_candidate = skill_dir.name.lower()

        # Slugify: replace non-alnum with '-', strip leading/trailing '-'
        slug = re.sub(r"[^a-z0-9]+", "-", slug_candidate).strip("-")
        if not SLUG_REGEX.match(slug):
            continue

        try:
            rel_path = str(skill_dir.resolve().relative_to(repo_root_resolved))
        except ValueError:
            rel_path = skill_dir.name

        results.append(
            DiscoveredSkill(
                slug=slug,
                name=name,
                description=description,
                rel_path=rel_path,
                abs_dir=skill_dir.resolve(),
            )
        )

    return sorted(results, key=lambda s: s.slug)


def build_bundle_for_skill(skill: DiscoveredSkill) -> bytes:
    """Produce an in-memory zip of a discovered skill's contents.

    The zip root contains the skill dir's contents (SKILL.md at root, all
    sibling files/subdirs). Excludes symlinks, .template files, and __pycache__.
    """
    buf = io.BytesIO()
    total = 0

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        skill_root = skill.abs_dir
        for dirpath, dirnames, filenames in os.walk(skill_root):
            # Prune __pycache__ in-place so os.walk skips them.
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]

            dir_path = Path(dirpath)
            for filename in filenames:
                file_path = dir_path / filename

                # Skip symlinks and .template files.
                if file_path.is_symlink():
                    continue
                if filename.endswith(TEMPLATE_SUFFIX):
                    continue

                rel = file_path.relative_to(skill_root)
                arc_name = str(rel)

                file_size = file_path.stat().st_size
                if file_size > DEFAULT_PER_FILE_MAX_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"file '{arc_name}' exceeds "
                        f"{DEFAULT_PER_FILE_MAX_BYTES // (1024 * 1024)} MiB",
                    )
                total += file_size
                if total > DEFAULT_TOTAL_MAX_BYTES:
                    raise OnyxError(
                        OnyxErrorCode.PAYLOAD_TOO_LARGE,
                        f"skill bundle exceeds "
                        f"{DEFAULT_TOTAL_MAX_BYTES // (1024 * 1024)} MiB uncompressed",
                    )

                zf.write(file_path, arcname=arc_name)

    return buf.getvalue()


@contextmanager
def extracted_skills(
    archive_bytes: bytes,
    subpath: str | None = None,
) -> Iterator[list[DiscoveredSkill]]:
    """Context manager: extract archive, yield discovered skills, then clean up.

    abs_dir on each DiscoveredSkill is only valid inside this with-block.
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        skills = _discover_skills_in_dir(archive_bytes, tmp, subpath)
        yield skills
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
