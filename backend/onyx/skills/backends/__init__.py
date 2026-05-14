"""Skills delivery backends.

Today only the S3 Files backend is wired up — local/dev and
docker-compose deployments keep using ``SKILLS_TEMPLATE_PATH`` for the
host-symlink path that upstream's materializer already targets. Adding
a FilesystemSkillsBackend later for those modes is a clean addition
because the protocol is independent of the backing store.

Public API:
    SkillsBackend, SkillFile, SkillsManifestEntry — types
    S3FilesSkillsBackend                          — the K8s backend
    get_skills_backend                            — singleton (or None)
    bootstrap_builtins_to_backend                 — startup hook
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from onyx.server.features.build.configs import SKILLS_S3_BUCKET
from onyx.server.features.build.configs import SKILLS_S3_FILES_FILE_SYSTEM_ID
from onyx.server.features.build.configs import SKILLS_S3_PREFIX
from onyx.skills.backends.base import SkillFile
from onyx.skills.backends.base import SkillsBackend
from onyx.skills.backends.base import SkillsManifestEntry
from onyx.skills.backends.s3_files import S3FilesSkillsBackend
from onyx.skills.registry import BuiltinSkill
from onyx.skills.registry import BuiltinSkillRegistry
from onyx.utils.logger import setup_logger

__all__ = [
    "SkillFile",
    "SkillsBackend",
    "SkillsManifestEntry",
    "S3FilesSkillsBackend",
    "get_skills_backend",
    "reset_skills_backend",
    "bootstrap_builtins_to_backend",
    "read_skill_tree_from_disk",
]

logger = setup_logger()

_backend: SkillsBackend | None = None
_backend_resolved: bool = False
_backend_lock = Lock()


def get_skills_backend() -> SkillsBackend | None:
    """Return the active backend, or ``None`` when not configured.

    Local/dev and docker-compose deployments leave ``SKILLS_S3_BUCKET``
    empty and get ``None`` here. Callers (api_server startup, K8s pod
    create) treat ``None`` as "no backend to bootstrap / no CSI mount to
    inject" and silently fall back to upstream's host-symlink path.
    """
    global _backend, _backend_resolved
    if not _backend_resolved:
        with _backend_lock:
            if not _backend_resolved:
                _backend = _build_backend()
                _backend_resolved = True
    return _backend


def reset_skills_backend() -> None:
    """For tests."""
    global _backend, _backend_resolved
    with _backend_lock:
        _backend = None
        _backend_resolved = False


def _build_backend() -> SkillsBackend | None:
    if not SKILLS_S3_BUCKET:
        return None
    return S3FilesSkillsBackend(
        bucket=SKILLS_S3_BUCKET,
        key_prefix=SKILLS_S3_PREFIX,
        file_system_id=SKILLS_S3_FILES_FILE_SYSTEM_ID or None,
    )


def read_skill_tree_from_disk(source_dir: Path) -> list[SkillFile]:
    """Walk a source skill dir and return all files as ``SkillFile`` entries.

    Used by ``bootstrap_builtins_to_backend`` to upload built-ins from
    the codebase to the backend. Skips dotfiles and ``__pycache__``
    anywhere in the tree but keeps everything else byte-for-byte.
    """
    out: list[SkillFile] = []
    for child in sorted(source_dir.rglob("*")):
        if not child.is_file():
            continue
        rel = child.relative_to(source_dir)
        if any(part.startswith(".") or part == "__pycache__" for part in rel.parts):
            continue
        out.append(SkillFile(relative_path=rel.as_posix(), content=child.read_bytes()))
    return out


def bootstrap_builtins_to_backend(
    registry: BuiltinSkillRegistry,
    backend: SkillsBackend | None,
) -> None:
    """Write every registered built-in to the active backend.

    No-op when ``backend`` is ``None`` (no S3 configured) — local/dev
    deployments don't need this because the materializer there reads
    from the host filesystem directly.

    Idempotent: ``write_builtin`` re-PUTs the same bytes on every restart,
    which is a no-op semantically. We deliberately don't filter on
    ``is_available(db)`` here — admins need to *see* an image-generation
    skill exists even on tenants without a provider configured;
    availability filtering happens at materialization time.
    """
    if backend is None:
        return

    builtins: list[BuiltinSkill] = registry.list_all()
    for skill in builtins:
        try:
            files = read_skill_tree_from_disk(skill.source_dir)
            if not files:
                logger.warning(
                    "Built-in skill %s has no files on disk at %s — skipping",
                    skill.slug,
                    skill.source_dir,
                )
                continue
            backend.write_builtin(skill.slug, files)
            logger.info(
                "Mirrored built-in skill %s (%d files) to skills backend",
                skill.slug,
                len(files),
            )
        except Exception:
            logger.exception(
                "Failed to mirror built-in skill %s to skills backend", skill.slug
            )
            raise
