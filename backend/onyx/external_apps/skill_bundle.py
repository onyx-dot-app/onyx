"""Skill bundles for built-in external apps.

A built-in external app ships a skill bundle — SKILL.md plus a runnable
helper (and optionally a CLI) — that teaches the Craft agent how to call
that app's API. The bundle is delivered into the user's sandbox through
the same mechanism as skills, but is never a `Skill` row, so it never
appears in the skills tab.

The bundle is conceptually a single zip per app. *Where that zip lives is
not yet decided* (object storage / FileStore vs. shipped in the Onyx
image). `_load_builtin_bundle_zip` is the one seam that owns that
decision: today it zips the on-disk source directory in this package; a
future change swaps only that function to fetch from S3/FileStore.
Everything downstream consumes an already-unzipped `FileSet`.
"""

import io
import zipfile
from pathlib import Path

from onyx.db.enums import ExternalAppType
from onyx.server.features.build.sandbox.models import FileSet
from onyx.utils.logger import setup_logger

logger = setup_logger()

_BUNDLE_ROOT = Path(__file__).parent / "skill_bundles"

_EXCLUDED_PARTS: frozenset[str] = frozenset({"__pycache__"})


def _bundle_dir(app_type: ExternalAppType) -> Path:
    # ExternalAppType values are upper-snake (e.g. GOOGLE_CALENDAR); the
    # on-disk bundle directories are lower-snake (google_calendar).
    return _BUNDLE_ROOT / app_type.value.lower()


def _is_excluded(rel: Path) -> bool:
    return any(part in _EXCLUDED_PARTS or part.startswith(".") for part in rel.parts)


def _load_builtin_bundle_zip(app_type: ExternalAppType) -> bytes | None:
    """Return the app's skill bundle as zip bytes, or None if it has no
    bundle.

    SEAM: this is the only place that knows where bundles live. It
    currently zips the in-package source directory. To move bundles to
    object storage / FileStore, replace this body with a fetch — the
    return contract (zip bytes or None) stays the same.
    """
    src = _bundle_dir(app_type)
    if not src.is_dir():
        return None

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(src)
            if _is_excluded(rel):
                continue
            zf.writestr(rel.as_posix(), path.read_bytes())
    return buf.getvalue()


def get_builtin_external_app_bundle(
    app_type: ExternalAppType,
) -> FileSet | None:
    """Unzipped `{relpath: bytes}` for a built-in app's skill bundle.

    Returns None when the app type has no bundle (e.g. CUSTOM, or a
    provider that hasn't shipped one yet).
    """
    zip_bytes = _load_builtin_bundle_zip(app_type)
    if zip_bytes is None:
        return None

    files: FileSet = {}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                files[info.filename] = zf.read(info)
    except zipfile.BadZipFile:
        logger.warning(
            "Built-in external app bundle for %s is not a valid zip; skipping",
            app_type,
        )
        return None

    return files or None
