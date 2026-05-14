"""Common types and the ``SkillsBackend`` protocol.

A skills backend is the bridge between *where api_server writes* and
*what the sandbox reads*. Today only the S3 Files backend is implemented
(Kubernetes-only deployments); the protocol lives in its own module so
adding Docker-volume or local-symlink backends later doesn't churn
imports.

The protocol is intentionally minimal: writes are idempotent (re-writing
the same bytes is a no-op semantically), and reads are not modeled — the
sandbox-side read path is the filesystem the deployment mode exposes at
``/skills/`` (e.g. CSI mount), so the read path lives in the materializer,
not here.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from pydantic import BaseModel


class SkillFile(BaseModel):
    """A single file in a skill tree.

    ``relative_path`` is forward-slash-separated, relative to the skill
    root (e.g. ``"SKILL.md"`` or ``"scripts/render.py"``). Symlinks,
    dotted traversal, and absolute paths are rejected by
    ``validate_skill_files`` so a buggy caller can't escape the skill
    root via a backend write.
    """

    relative_path: str
    content: bytes


class SkillsManifestEntry(BaseModel):
    """One row in the per-tenant ``_manifest.json``.

    Built-ins are not listed in the per-tenant manifest (they're
    discovered by ls on ``_builtins/``); customs are.
    """

    slug: str
    name: str
    description: str
    bundle_sha256: str


def _validate_relative_path(relative_path: str) -> None:
    if not relative_path:
        raise ValueError("skill file relative_path is empty")
    if relative_path.startswith("/") or "\\" in relative_path:
        raise ValueError(f"skill file relative_path is not relative: {relative_path!r}")
    if any(part in ("", ".", "..") for part in relative_path.split("/")):
        raise ValueError(f"skill file relative_path is traversal: {relative_path!r}")


def validate_skill_files(files: Iterable[SkillFile]) -> list[SkillFile]:
    """Materialize the iterable once and validate every path. Returns a
    fresh list so callers can iterate twice (size check + write)."""
    materialized = list(files)
    for f in materialized:
        _validate_relative_path(f.relative_path)
    return materialized


class SkillsBackend(Protocol):
    """How api_server delivers skill files to sandboxes.

    All write methods are idempotent: calling them twice with the same
    inputs is a no-op (or a content-equivalent overwrite). Implementations
    are responsible for atomicity within a single skill — partially-written
    skill trees must never be visible to readers.
    """

    def write_builtin(self, slug: str, files: Iterable[SkillFile]) -> None:
        """Write a built-in skill tree under ``_builtins/<slug>/``."""
        ...

    def write_custom(
        self, tenant_id: str, slug: str, files: Iterable[SkillFile]
    ) -> None:
        """Write a custom skill tree under ``tenants/<tenant_id>/_custom/<slug>/``."""
        ...

    def delete_custom(self, tenant_id: str, slug: str) -> None:
        """Remove a custom skill tree. No-op if missing."""
        ...

    def write_manifest(
        self,
        tenant_id: str,
        builtin: Iterable[SkillsManifestEntry],
        custom: Iterable[SkillsManifestEntry],
    ) -> None:
        """Replace the per-tenant manifest atomically."""
        ...
