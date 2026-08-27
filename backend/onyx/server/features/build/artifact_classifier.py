"""Classifies a session's outputs listing into artifacts.

Pure functions: each visible top-level entry is one artifact, files typed by
extension with a generic fallback, directories aggregated over their visible
descendants, and the scaffolded webapp directory recognized. Hidden names (the
shared workspace visibility rule) never influence the result, so churn in
node_modules or .next cannot dirty an artifact. Callers adapt the sandbox
daemon's outputs manifest into ``OutputEntry`` values, and the listing must be
complete: a truncated manifest reduces to hashes that flap, so skip
reconciliation instead of reducing one.
"""

import mimetypes
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath

from onyx.db.enums import ArtifactType
from onyx.server.features.build.configs import is_hidden_workspace_name
from onyx.server.features.build.sandbox.nextjs_dev import (
    WEBAPP_OUTPUTS_RELATIVE_PACKAGE_JSON,
    WEBAPP_ROOT_NAME,
)

# Formats a product surface handles (preview, export). .doc and .xls have no
# such surface and stay generic.
_EXTENSION_TYPES = {
    ".pptx": ArtifactType.PPTX,
    ".ppt": ArtifactType.PPTX,
    ".docx": ArtifactType.DOCX,
    ".xlsx": ArtifactType.EXCEL,
    ".xlsm": ArtifactType.EXCEL,
    ".pdf": ArtifactType.PDF,
    ".csv": ArtifactType.CSV,
    ".md": ArtifactType.MARKDOWN,
    ".markdown": ArtifactType.MARKDOWN,
}

_ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar"}

# Checked before the mimetypes families: .ts is registered as video/mp2t.
_CODE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".html",
    ".css",
    ".scss",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sql",
    ".sh",
    ".ipynb",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".rb",
    ".php",
}

_MEDIA_FAMILY_TYPES = {
    "image": ArtifactType.IMAGE,
    "audio": ArtifactType.AUDIO,
    "video": ArtifactType.VIDEO,
}


@dataclass(frozen=True)
class OutputEntry:
    """One entry of an outputs listing, path outputs-relative with ``/``
    separators. ``sha256`` is None for directories and unhashed files."""

    path: str
    is_directory: bool
    size: int | None = None
    mtime_ns: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class DerivedArtifact:
    """One artifact a reconciler should upsert, keyed by ``path``."""

    path: str
    name: str
    type: ArtifactType
    size_bytes: int | None
    content_hash: str | None


def classify_file(filename: str) -> ArtifactType:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in _EXTENSION_TYPES:
        return _EXTENSION_TYPES[suffix]
    if suffix in _ARCHIVE_SUFFIXES:
        return ArtifactType.ARCHIVE
    if suffix in _CODE_SUFFIXES:
        return ArtifactType.CODE
    mime, _ = mimetypes.guess_type(filename)
    if mime is not None:
        family = mime.split("/", 1)[0]
        if family in _MEDIA_FAMILY_TYPES:
            return _MEDIA_FAMILY_TYPES[family]
    return ArtifactType.FILE


def _is_visible(path: str) -> bool:
    return not any(is_hidden_workspace_name(part) for part in path.split("/"))


def _file_signal(entry: OutputEntry) -> str | None:
    """Change signal for a file: its hash, or a size-and-mtime surrogate for
    files past the hash ceiling, shaped so it can never read as a real sha.
    The manifest carries fstat size and mtime for every file it lists. An
    adapter omitting one degrades detection to the other field alone, which
    still beats no signal, so partial metadata is accepted."""
    if entry.sha256 is not None:
        return entry.sha256
    if entry.size is None and entry.mtime_ns is None:
        return None
    size = "" if entry.size is None else entry.size
    mtime = "" if entry.mtime_ns is None else entry.mtime_ns
    return f"meta:{size}:{mtime}"


def _directory_hash(root: str, contents: list[OutputEntry]) -> str:
    """Deterministic hash of a directory's visible content, over paths
    relative to the directory, so identical trees hash identically. A child
    rename, addition, removal, or change signal all move it."""
    prefix = len(root) + 1
    digest = sha256()
    for entry in sorted(contents, key=lambda e: e.path):
        relative = entry.path[prefix:]
        if entry.is_directory:
            digest.update(f"{relative}\x00dir\n".encode())
        else:
            digest.update(f"{relative}\x00{_file_signal(entry) or ''}\n".encode())
    return digest.hexdigest()


def derive_artifacts(entries: list[OutputEntry]) -> list[DerivedArtifact]:
    """Reduce a complete outputs listing to its artifacts, sorted by path.

    Each visible top-level entry is one artifact, nested files belong to
    their top-level directory and never surface on their own.
    """
    top_level: list[OutputEntry] = []
    children: dict[str, list[OutputEntry]] = defaultdict(list)
    for entry in entries:
        if not _is_visible(entry.path):
            continue
        root, _, nested = entry.path.partition("/")
        if nested:
            children[root].append(entry)
        else:
            top_level.append(entry)

    artifacts: list[DerivedArtifact] = []
    for entry in top_level:
        name = PurePosixPath(entry.path).name
        if not entry.is_directory:
            artifacts.append(
                DerivedArtifact(
                    path=entry.path,
                    name=name,
                    type=classify_file(entry.path),
                    size_bytes=entry.size,
                    content_hash=_file_signal(entry),
                )
            )
            continue
        contents = children[entry.path]
        is_webapp = entry.path == WEBAPP_ROOT_NAME and any(
            c.path == WEBAPP_OUTPUTS_RELATIVE_PACKAGE_JSON and not c.is_directory
            for c in contents
        )
        artifacts.append(
            DerivedArtifact(
                path=entry.path,
                name=name,
                type=ArtifactType.WEB_APP if is_webapp else ArtifactType.DIRECTORY,
                size_bytes=sum(c.size or 0 for c in contents if not c.is_directory),
                content_hash=_directory_hash(entry.path, contents),
            )
        )
    return sorted(artifacts, key=lambda a: a.path)
